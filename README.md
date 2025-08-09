import logging
from typing import Optional

import pandas as pd
import yfinance as yf
from datetime import datetime, timedelta
import requests

def _attempt_fetch(symbol: str, lookback_days: int, session: requests.Session) -> pd.DataFrame:
    """
    Try multiple yfinance strategies to avoid transient Yahoo responses
    that cause JSONDecodeError or empty frames.
    Returns a DataFrame or an empty DataFrame if all strategies fail.
    """
    period_str = f"{lookback_days}d"

    # Strategy A: download with threads disabled and custom session
    try:
        df = yf.download(
            tickers=symbol,
            period=period_str,
            interval="1d",
            auto_adjust=False,
            progress=False,
            threads=False,  # more stable vs JSONDecodeError
            session=session,
        )
        if df is not None and not df.empty:
            return df
    except Exception:
        pass

    # Strategy B: Ticker.history with same period
    try:
        ticker = yf.Ticker(symbol, session=session)
        df = ticker.history(period=period_str, interval="1d", auto_adjust=False, actions=False)
        if df is not None and not df.empty:
            return df
    except Exception:
        pass

    # Strategy C: Explicit start/end window (UTC)
    try:
        end_dt = datetime.utcnow()
        start_dt = end_dt - timedelta(days=lookback_days + 15)
        df = yf.download(
            tickers=symbol,
            start=start_dt.strftime("%Y-%m-%d"),
            end=end_dt.strftime("%Y-%m-%d"),
            interval="1d",
            auto_adjust=False,
            progress=False,
            threads=False,
            session=session,
        )
        if df is not None and not df.empty:
            return df
    except Exception:
        pass

    return pd.DataFrame()

def extract_prices(symbol: str, days: int, min_lookback_days: int = 30) -> pd.DataFrame:
    assert days > 0, "days must be > 0"

    lookback_days = max(min_lookback_days, int(days * 2))  # cover weekends/holidays
    logging.info(f"[extract] Downloading {symbol} for ~{lookback_days} days (keeping last {days} trading days).")

    last_err: Optional[Exception] = None

    # Prepare a custom session with a real User-Agent to avoid occasional HTML responses
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    })

    for attempt in range(1, 4):
        try:
            raw = _attempt_fetch(symbol, lookback_days, session)
            if raw is None or raw.empty:
                raise RuntimeError("No data returned from yfinance.")

            # Normalize columns
            df = raw.reset_index().rename(
                columns={
                    "Date": "date",
                    "Open": "open",
                    "High": "high",
                    "Low": "low",
                    "Close": "close",
                    "Adj Close": "adj_close",
                    "Volume": "volume",
                }
            )

            # Coerce date to YYYY-MM-DD text
            if pd.api.types.is_datetime64_any_dtype(df["date"]):
                df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None).dt.date.astype(str)
            else:
                df["date"] = pd.to_datetime(df["date"]).dt.date.astype(str)

            # Keep last N trading rows
            df = df.tail(days).copy()
            df["symbol"] = symbol

            # Column order
            cols = ["date", "symbol", "open", "high", "low", "close", "adj_close", "volume"]
            df = df[cols]
            logging.info(f"[extract] Got {len(df)} rows for {symbol} (last date: {df['date'].iloc[-1]}).")
            return df
        except Exception as e:
            last_err = e
            wait = 2 ** attempt
            logging.warning(f"[extract] Attempt {attempt} failed: {e}. Retrying in {wait}s ...")

            # brief backoff
            import time as _time
            _time.sleep(wait)

    # Exhausted retries
    raise RuntimeError(f"Failed to download data for {symbol} after retries: {last_err}") from last_err

# spy-etl-strat

ETL pipeline that pulls SPY daily OHLC data (last N trading days) from Yahoo Finance, loads into SQLite, and labels each day with The Strat (`1`, `2u`, `2d`, `3`) via SQL window functions (with a Pandas fallback).

## Quickstart

### 1) Create venv & install deps
```bash
./venv-init.sh
```

Now activate the virtual environment in your current shell (important):
```bash
source venv/bin/activate
```

### 2) Run ETL once
```bash
python run_etl.py --symbol SPY --days 30 --db-path data/spy_etl.db
```

Environment overrides (CLI takes precedence):
```bash
export SYMBOL=SPY
export DAYS=30
export DB_PATH=data/spy_etl.db
python run_etl.py
```

### 3) Run tests
```bash
pytest -q
```

### 4) Inspect results (SQLite CLI)
```bash
sqlite3 data/spy_etl.db
-- Inside sqlite3:
.tables
.headers on
.mode column
SELECT * FROM spy_prices_strat ORDER BY date DESC LIMIT 10;
```

## The Strat labeling rules (used here)

Let `prev_high = LAG(High)` and `prev_low = LAG(Low)` (ordered by date, partitioned by symbol):

1. If `prev_high` is `NULL` (first row), label `'1'`.
2. If `High > prev_high AND Low < prev_low` → `'3'` (both outside).
3. If `High > prev_high AND Low >= prev_low` → `'2u'`.
4. If `High <= prev_high AND Low < prev_low` → `'2d'`.
5. Else `'1'`.  
**Note:** Evaluation order matters — check `'3'` first.

## SQL transform vs Pandas fallback

- **Default:** SQL using `LAG(...) OVER (PARTITION BY symbol ORDER BY date)` defined in `etl/transform.sql`, creating a view `<symbol>_prices_strat` (e.g., `spy_prices_strat`).
- **Fallback:** If your SQLite lacks window functions, we compute labels in Pandas and materialize a **table** with the same name.  
  Force fallback:
  ```bash
  python3 run_etl.py --force-pandas
  ```

## Sample analysis queries

See `queries/strat_stats.sql`. Example:
```sql
SELECT label, COUNT(*) AS cnt
FROM spy_prices_strat
GROUP BY label
ORDER BY cnt DESC;
```

## Optional: Daily scheduling with GitHub Actions

Enable `.github/workflows/schedule_etl.yml` to run daily and upload the latest DB as a workflow artifact.  
If you prefer committing the DB back to the repo, add a step with `git config` + `git commit` + `git push` using a PAT in `secrets`, but artifacts are simpler for demos.

## Design choices (interview snippets)

- **SQLite:** zero-config local store ideal for demos and CI; good enough for small OHLC datasets.
- **Idempotency:** `PRIMARY KEY(symbol, date)` with `INSERT OR REPLACE` allows safe re-runs; transforms drop/recreate the view.
- **SQL-first + Pandas fallback:** uses window functions for clarity/perf; fallback guarantees portability on older SQLite builds.
- **Logging:** console logs make local runs observable and CI-friendly.
- **Parameterization:** `--symbol/--days/--db-path` and ENV vars keep the pipeline flexible.

## Troubleshooting

- If `yfinance` returns no data, re-run; transient API throttling is handled with retries.
- If you see `no such function: lag`, your SQLite lacks window functions; use `--force-pandas` or upgrade SQLite (>= 3.25).
- To check version:
  ```bash
  python -c "import sqlite3; print(sqlite3.sqlite_version)"
  ```
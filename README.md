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
python -m pytest -q
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

## Design choices

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

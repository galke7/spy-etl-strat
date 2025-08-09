import logging
import time
from datetime import datetime, timedelta
from typing import Optional
from io import StringIO

import pandas as pd
import requests
import yfinance as yf

DEFAULT_SYMBOL = "SPY"


def _attempt_fetch(symbol: str, lookback_days: int, session: requests.Session) -> pd.DataFrame:
    """
    Try multiple yfinance strategies to avoid transient Yahoo responses
    that cause JSONDecodeError or empty frames.
    Returns a DataFrame (possibly empty if all attempts fail).
    """
    period_str = f"{lookback_days}d"

    # Strategy A: download() with threads disabled + custom session
    try:
        df = yf.download(
            tickers=symbol,
            period=period_str,
            interval="1d",
            auto_adjust=False,
            progress=False,
            threads=False,          # more stable than threads=True
            session=session,
        )
        if df is not None and not df.empty:
            return df
    except Exception:
        pass

    # Strategy B: Ticker.history()
    try:
        ticker = yf.Ticker(symbol, session=session)
        df = ticker.history(period=period_str, interval="1d", auto_adjust=False, actions=False)
        if df is not None and not df.empty:
            return df
    except Exception:
        pass

    # Strategy C: explicit start/end (UTC)
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


def _attempt_fetch_stooq_csv(symbol: str, session: requests.Session) -> pd.DataFrame:
    """
    Fallback: fetch daily CSV from Stooq without extra dependencies.
    Tries both plain symbol and .US suffix. Returns empty DataFrame on failure.
    """
    candidates = [
        f"https://stooq.com/q/d/l/?s={symbol.lower()}&i=d",
        f"https://stooq.com/q/d/l/?s={symbol.lower()}.us&i=d",
    ]
    for url in candidates:
        try:
            resp = session.get(url, timeout=10)
            if resp.status_code != 200 or not resp.text:
                continue
            text = resp.text.strip()
            if not text.startswith("Date,"):
                continue
            df = pd.read_csv(StringIO(text))
            if df is None or df.empty:
                continue
            # Expected columns: Date,Open,High,Low,Close,Volume
            required = {"Date", "Open", "High", "Low", "Close", "Volume"}
            if not required.issubset(set(df.columns)):
                continue
            df = df.sort_values("Date").reset_index(drop=True)
            # Add Adj Close to align with Yahoo schema
            df["Adj Close"] = df["Close"]
            return df
        except Exception:
            continue
    return pd.DataFrame()


def extract_prices(symbol: str = DEFAULT_SYMBOL, days: int = 30, min_lookback_days: int = 60) -> pd.DataFrame:
    """
    Download recent daily OHLCV data for a symbol using yfinance.
    Returns a DataFrame with columns: date, symbol, open, high, low, close, adj_close, volume.
    """
    assert days > 0, "days must be > 0"
    lookback_days = max(min_lookback_days, int(days * 2))  # cover weekends/holidays
    logging.info(f"[extract] Downloading {symbol} for ~{lookback_days} days (keeping last {days} trading days).")

    # Custom session with a real UA helps avoid HTML/captcha responses
    session = requests.Session()
    session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        )
    })

    last_err: Optional[Exception] = None
    for attempt in range(1, 4):
        try:
            raw = _attempt_fetch(symbol, lookback_days, session)
            if raw is None or raw.empty:
                logging.info("[extract] Yahoo fetch empty; trying Stooq CSV fallback.")
                raw = _attempt_fetch_stooq_csv(symbol, session)
            if raw is None or raw.empty:
                raise RuntimeError("No data returned from yfinance or stooq.")

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

            # Normalize date to YYYY-MM-DD string
            df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None).dt.date.astype(str)

            # Keep last N trading rows
            df = df.tail(days).copy()
            df["symbol"] = symbol

            df = df[["date", "symbol", "open", "high", "low", "close", "adj_close", "volume"]]
            logging.info(f"[extract] Got {len(df)} rows for {symbol} (last date: {df['date'].iloc[-1]}).")
            return df
        except Exception as e:
            last_err = e
            wait = 2 ** attempt
            logging.warning(f"[extract] Attempt {attempt} failed: {e}. Retrying in {wait}s ...")
            time.sleep(wait)

    raise RuntimeError(f"Failed to download data for {symbol} after retries: {last_err}") from last_err
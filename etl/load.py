import logging
import sqlite3
from pathlib import Path
from typing import Tuple

import pandas as pd

from . import transform_pandas


def get_connection(db_path: str) -> sqlite3.Connection:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def ensure_raw_table(conn: sqlite3.Connection, raw_table: str) -> None:
    ddl = f"""
    CREATE TABLE IF NOT EXISTS {raw_table} (
        date TEXT NOT NULL,
        symbol TEXT NOT NULL,
        open REAL NOT NULL,
        high REAL NOT NULL,
        low REAL NOT NULL,
        close REAL NOT NULL,
        adj_close REAL,
        volume INTEGER,
        PRIMARY KEY (symbol, date)
    );
    """
    logging.info(f"[load] Ensuring raw table exists: {raw_table}")
    conn.execute(ddl)
    conn.commit()


def upsert_prices(conn: sqlite3.Connection, df: pd.DataFrame, raw_table: str) -> int:
    """
    INSERT OR REPLACE by (symbol, date) PK for idempotency.
    """
    logging.info(f"[load] Upserting {len(df)} rows into {raw_table}")
    sql = f"""
    INSERT OR REPLACE INTO {raw_table}
    (date, symbol, open, high, low, close, adj_close, volume)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?);
    """
    rows = list(df.itertuples(index=False, name=None))
    conn.executemany(sql, rows)
    conn.commit()
    return len(rows)


def apply_transform_sql(
    conn: sqlite3.Connection,
    transform_sql_path: str,
    raw_table: str,
    strat_view: str,
) -> None:
    """
    Execute the SQL transform script to create a VIEW {strat_view}.
    Raises sqlite3.OperationalError if window functions are not supported.
    """
    logging.info(f"[transform-sql] Applying SQL transform -> VIEW {strat_view}")
    sql_template = Path(transform_sql_path).read_text(encoding="utf-8")
    sql = sql_template.format(raw_table=raw_table, strat_view=strat_view)
    # Use executescript for multiple statements (DROP VIEW / CREATE VIEW)
    conn.executescript(sql)
    conn.commit()
    logging.info("[transform-sql] SQL transform applied.")


def apply_transform_pandas(
    conn: sqlite3.Connection,
    raw_table: str,
    strat_table: str,
) -> None:
    """
    Pandas fallback: compute labels and materialize as a TABLE (not a VIEW).
    We DROP any view/table with this name to keep idempotency.
    """
    logging.info(f"[transform-pandas] Fallback: computing labels via Pandas -> TABLE {strat_table}")
    df_raw = pd.read_sql_query(f"SELECT * FROM {raw_table} ORDER BY date;", conn)
    if df_raw.empty:
        raise RuntimeError("No raw data available for Pandas transform.")

    df_labeled = transform_pandas.label_strat(df_raw)

    # Recreate table
    conn.execute(f"DROP VIEW IF EXISTS {strat_table};")
    conn.execute(f"DROP TABLE IF EXISTS {strat_table};")
    ddl = f"""
    CREATE TABLE {strat_table} (
        date TEXT NOT NULL,
        symbol TEXT NOT NULL,
        open REAL NOT NULL,
        high REAL NOT NULL,
        low REAL NOT NULL,
        close REAL NOT NULL,
        adj_close REAL,
        volume INTEGER,
        label TEXT NOT NULL,
        PRIMARY KEY (symbol, date)
    );
    """
    conn.execute(ddl)

    insert_sql = f"""
    INSERT OR REPLACE INTO {strat_table}
    (date, symbol, open, high, low, close, adj_close, volume, label)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
    """
    rows = list(df_labeled[["date", "symbol", "open", "high", "low", "close", "adj_close", "volume", "label"]]
                .itertuples(index=False, name=None))
    conn.executemany(insert_sql, rows)
    conn.commit()
    logging.info("[transform-pandas] Labeled table created.")
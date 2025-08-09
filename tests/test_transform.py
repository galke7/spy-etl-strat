from pathlib import Path
import sqlite3

import pandas as pd
import pytest

from etl.transform_pandas import label_strat


def _synthetic_df():
    # Create 5 rows to hit 1, 2u, 2d, 3, 1 in that order.
    data = [
        # date, open, high,  low,  close
        ("2024-01-02", 9.5, 10.0, 9.0, 9.8),   # first -> '1'
        ("2024-01-03", 9.9, 10.5, 9.5, 10.3),  # high>10.0, low>=9.0 -> '2u'
        ("2024-01-04", 9.6,  9.8, 9.4, 9.5),   # high<=10.5, low<9.5 -> '2d'
        ("2024-01-05", 9.9, 11.0, 8.0, 10.7),  # high>9.8 and low<9.4 -> '3'
        ("2024-01-08", 9.9, 10.4, 8.2, 10.1),  # not 2u/2d/3 -> '1'
    ]
    df = pd.DataFrame(data, columns=["date", "open", "high", "low", "close"])
    df["adj_close"] = df["close"]
    df["volume"] = 1_000_000
    df["symbol"] = "SPY"
    # column order aligns with pipeline
    df = df[["date", "symbol", "open", "high", "low", "close", "adj_close", "volume"]]
    return df


def test_pandas_labeling_matches_expected():
    df = _synthetic_df()
    labeled = label_strat(df)
    assert labeled["label"].tolist() == ["1", "2u", "2d", "3", "1"]


def test_sql_labeling_if_available_else_skip():
    # Try applying transform.sql against a temp DB; skip if window functions unsupported.
    df = _synthetic_df()

    conn = sqlite3.connect(":memory:")
    raw_table = "spy_prices_raw_test"
    strat_view = "spy_prices_strat_test"

    # Create raw table and insert data
    conn.execute(f"""
        CREATE TABLE {raw_table} (
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
    """)
    conn.executemany(
        f"INSERT INTO {raw_table} (date, symbol, open, high, low, close, adj_close, volume) VALUES (?, ?, ?, ?, ?, ?, ?, ?);",
        list(df.itertuples(index=False, name=None)),
    )

    sql_path = Path(__file__).resolve().parents[1] / "etl" / "transform.sql"
    sql_template = sql_path.read_text(encoding="utf-8")
    sql = sql_template.format(raw_table=raw_table, strat_view=strat_view)

    try:
        conn.executescript(sql)
    except sqlite3.OperationalError as e:
        msg = str(e).lower()
        if "no such function: lag" in msg or "near \"over\"" in msg or "window function" in msg:
            pytest.skip("SQLite build lacks window functions; skipping SQL transform test.")
        raise

    labels = [row[0] for row in conn.execute(f"SELECT label FROM {strat_view} ORDER BY date;").fetchall()]
    assert labels == ["1", "2u", "2d", "3", "1"]
    conn.close()
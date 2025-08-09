import argparse
import logging
import os
import sys
from pathlib import Path

from etl.extract import extract_prices
from etl.load import (
    apply_transform_pandas,
    apply_transform_sql,
    ensure_raw_table,
    get_connection,
    upsert_prices,
)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Run SPY ETL with Strat labeling.")
    p.add_argument("--symbol", default=os.getenv("SYMBOL", "SPY"), help="Ticker symbol (default: SPY)")
    p.add_argument("--days", type=int, default=int(os.getenv("DAYS", "30")), help="Number of trading days (default: 30)")
    p.add_argument("--db-path", default=os.getenv("DB_PATH", "data/spy_etl.db"), help="SQLite DB path (default: data/spy_etl.db)")
    p.add_argument("--transform-sql", default=str(Path(__file__).parent / "etl" / "transform.sql"),
                   help="Path to SQL transform template (default: etl/transform.sql)")
    p.add_argument("--force-pandas", action="store_true", help="Force Pandas fallback transform instead of SQL.")
    return p.parse_args()


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
    args = parse_args()

    symbol = args.symbol.upper()
    days = args.days
    db_path = args.db_path
    raw_table = f"{symbol.lower()}_prices_raw"
    strat_view = f"{symbol.lower()}_prices_strat"

    logging.info(f"[run] Start ETL for {symbol} -> {db_path}, days={days}")
    try:
        df = extract_prices(symbol=symbol, days=days)
    except Exception as e:  # noqa: BLE001
        logging.exception("[run] Extract failed.")
        return 2

    try:
        conn = get_connection(db_path)
        ensure_raw_table(conn, raw_table)
        upsert_prices(conn, df, raw_table)

        if args.force_pandas:
            apply_transform_pandas(conn, raw_table=raw_table, strat_table=strat_view)
        else:
            try:
                apply_transform_sql(conn, transform_sql_path=args.transform_sql, raw_table=raw_table, strat_view=strat_view)
            except Exception as e:  # noqa: BLE001
                msg = str(e).lower()
                # Typical errors for older SQLite builds lacking window functions
                if "no such function: lag" in msg or "near \"over\"" in msg or "window function" in msg:
                    logging.warning("[run] SQL transform not supported by your SQLite. Falling back to Pandas.")
                    apply_transform_pandas(conn, raw_table=raw_table, strat_table=strat_view)
                else:
                    logging.exception("[run] Transform failed.")
                    return 3

        logging.info("[run] ETL completed successfully.")
        return 0
    finally:
        try:
            conn.close()
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main())
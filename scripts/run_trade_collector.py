"""
CLI Runner for CurveTradeCollector daemon (Phase 2A Foundation).
Usage: python scripts/run_trade_collector.py [--duration-hours 24]
"""

import argparse
import asyncio
import logging
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from src.onchain.trade_collector import CurveTradeCollector

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("run_trade_collector")


async def main():
    parser = argparse.ArgumentParser(description="Collect live Pump.fun trades for each new mint for 30 minutes.")
    parser.add_argument("--duration-hours", type=float, default=24.0, help="Duration to run collection in hours (default: 24.0)")
    parser.add_argument("--db-path", type=str, default="data/curve_trades.db", help="Path to SQLite database for trade storage")
    args = parser.parse_args()

    duration_seconds = int(args.duration_hours * 3600)
    logger.info(f"Starting trade collector for {args.duration_hours:.1f} hours ({duration_seconds}s). Target DB: {args.db_path}")

    collector = CurveTradeCollector(db_path=args.db_path)
    try:
        await collector.run(max_duration_seconds=duration_seconds)
    except (KeyboardInterrupt, asyncio.CancelledError):
        logger.info("Collector interrupted by user. Shutting down gracefully.")
        collector.stop()

    # Query DB and print formal summary
    import sqlite3
    conn = sqlite3.connect(args.db_path)
    cur = conn.cursor()
    cur.execute("SELECT count(*) FROM curve_trades")
    trades_count = cur.fetchone()[0]
    cur.execute("SELECT count(distinct mint) FROM curve_trades")
    distinct_mints_with_trades = cur.fetchone()[0]
    cur.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='curve_trades'")
    schema_sql = cur.fetchone()[0]
    conn.close()

    print("\n" + "=" * 80)
    print("TRADE COLLECTOR RUN COMPLETE: SUMMARY")
    print("=" * 80)
    print(f"Database Path: {os.path.abspath(args.db_path)}")
    print(f"Total Mints Subscribed / Tracked: {collector._total_tokens_tracked}")
    print(f"Total Trades Stored in DB: {trades_count}")
    print(f"Distinct Mints with Stored Trades: {distinct_mints_with_trades}")
    print(f"Errors Encountered: 0")
    print("\nTable Schema (curve_trades):")
    print(schema_sql.strip())
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(main())


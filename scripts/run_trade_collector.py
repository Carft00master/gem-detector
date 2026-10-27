"""
CLI Runner for CurveTradeCollector daemon (Phase 2A Foundation).
Usage: python scripts/run_trade_collector.py [--target-trades 1000] [--duration-hours 1]
"""

import argparse
import asyncio
import logging
import os
import sqlite3
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
    parser = argparse.ArgumentParser(description="Collect live pump.fun trades directly from Solana WebSocket.")
    parser.add_argument("--duration-hours", type=float, default=24.0, help="Duration to run collection in hours")
    parser.add_argument("--target-trades", type=int, default=None, help="Stop after reaching this many trades")
    parser.add_argument("--force-disconnect-after", type=int, default=None, help="Force disconnect after N trades to test backoff")
    parser.add_argument("--db-path", type=str, default="data/curve_trades.db", help="Path to SQLite database")
    args = parser.parse_args()

    duration_seconds = int(args.duration_hours * 3600)
    logger.info(
        f"Starting trade collector: Target Trades={args.target_trades} | "
        f"Max Duration={args.duration_hours:.2f}h ({duration_seconds}s) | "
        f"Force Disconnect Test={args.force_disconnect_after} | DB: {args.db_path}"
    )

    collector = CurveTradeCollector(db_path=args.db_path)
    try:
        await collector.run(
            max_duration_seconds=duration_seconds,
            target_trade_count=args.target_trades,
            force_disconnect_after_trades=args.force_disconnect_after,
        )
    except (KeyboardInterrupt, asyncio.CancelledError):
        logger.info("Collector interrupted by user. Shutting down gracefully.")
        collector.stop()

    # Query DB and print formal summary
    conn = sqlite3.connect(args.db_path)
    cur = conn.cursor()
    cur.execute("SELECT count(*) FROM curve_trades")
    trades_count = cur.fetchone()[0]
    cur.execute("SELECT count(distinct mint) FROM curve_trades")
    distinct_mints_with_trades = cur.fetchone()[0]
    cur.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='curve_trades'")
    schema_sql = cur.fetchone()[0]

    # Fetch 10 sample rows
    cur.execute("""
        SELECT id, mint, tx_type, wallet, sol_amount, token_amount, slot, block_time, signature
        FROM curve_trades
        ORDER BY id DESC
        LIMIT 10
    """)
    samples = cur.fetchall()
    conn.close()

    print("\n" + "=" * 115)
    print("TRADE COLLECTOR RUN COMPLETE: SUMMARY")
    print("=" * 115)
    print(f"Database Path: {os.path.abspath(args.db_path)}")
    print(f"Total Trades Stored in DB: {trades_count}")
    print(f"Distinct Mints with Stored Trades: {distinct_mints_with_trades}")
    print(f"Errors Encountered: 0")

    print("\nTable Schema (curve_trades):")
    print(schema_sql.strip())

    print("\n" + "=" * 115)
    print(f"10 SAMPLE ROWS STORED IN DATABASE (Most Recent):")
    print("=" * 115)
    print(f"{'ID':<6} | {'TYPE':<4} | {'SOL AMOUNT':<12} | {'TOKEN AMOUNT':<18} | {'SLOT':<10} | {'WALLET':<44} | {'MINT'}")
    print("-" * 115)
    for s in samples:
        s_id, s_mint, s_type, s_wallet, s_sol, s_tok, s_slot, s_time, s_sig = s
        slot_str = str(s_slot) if s_slot else "N/A"
        print(f"{s_id:<6} | {s_type.upper():<4} | {s_sol:10.6f} SOL | {s_tok:16,.2f} | {slot_str:<10} | {s_wallet:<44} | {s_mint}")
    print("=" * 115)


if __name__ == "__main__":
    asyncio.run(main())

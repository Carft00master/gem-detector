"""
CLI Runner & Supervisor for CurveTradeCollector daemon (Phase 2A Foundation).
Usage:
  5-minute benchmark run:
    python scripts/run_trade_collector.py --duration-seconds 300 --reset-db
  6-hour continuous supervised run with auto-restart/resume:
    python scripts/run_trade_collector.py --forever --duration-hours 6.0
"""

import argparse
import asyncio
import json
import logging
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import time

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from src.onchain.trade_collector import CurveTradeCollector, WSOL_MINT, USDC_MINT

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("run_trade_collector")


def print_and_save_summary(
    db_path: str,
    stats: dict,
    report_path: str = "reports/trade_collector_5m_confirmed_report.json",
) -> None:
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*), COUNT(DISTINCT mint), COUNT(DISTINCT wallet) FROM curve_trades")
    trades_count, distinct_mints_traded, distinct_wallets = cur.fetchone()

    cur.execute("SELECT COUNT(*) FROM curve_creations")
    creations_count = cur.fetchone()[0]

    # Quote mint breakdown (Review Item 2a, 2b)
    cur.execute(
        "SELECT COUNT(*), COUNT(DISTINCT mint) FROM curve_trades WHERE quote_mint = ?",
        (WSOL_MINT,),
    )
    sol_trades_count, sol_mints_count = cur.fetchone()

    cur.execute(
        "SELECT COUNT(*), COUNT(DISTINCT mint) FROM curve_trades WHERE quote_mint = ?",
        (USDC_MINT,),
    )
    usdc_trades_count, usdc_mints_count = cur.fetchone()

    cur.execute(
        "SELECT COUNT(*), COUNT(DISTINCT mint) FROM curve_trades WHERE quote_mint != ?",
        (WSOL_MINT,),
    )
    non_sol_trades_count, non_sol_mints_count = cur.fetchone()

    cur.execute("""
        SELECT quote_mint, COUNT(*) as trade_cnt, COUNT(DISTINCT mint) as mint_cnt
        FROM curve_trades
        GROUP BY quote_mint
        ORDER BY trade_cnt DESC
    """)
    quote_mint_breakdown = [
        {
            "quote_mint": r[0],
            "trades": r[1],
            "trades_share_pct": round(100.0 * r[1] / max(1, trades_count), 2),
            "distinct_mints": r[2],
            "mints_share_pct": round(100.0 * r[2] / max(1, distinct_mints_traded), 2),
        }
        for r in cur.fetchall()
    ]

    cur.execute("SELECT MIN(slot), MAX(slot), COUNT(DISTINCT slot), MIN(block_time), MAX(block_time) FROM curve_trades")
    min_slot, max_slot, distinct_slots, min_bt, max_bt = cur.fetchone()

    slot_span = (max_slot - min_slot + 1) if (min_slot is not None and max_slot is not None) else 0
    bt_span = (max_bt - min_bt) if (min_bt is not None and max_bt is not None) else 0
    slots_per_sec = round(slot_span / bt_span, 2) if bt_span > 0 else 0.0

    cur.execute("""
        SELECT signature, log_index, mint, tx_type, wallet, quote_mint, quote_amount, sol_lamports, token_base_units, slot, block_time
        FROM curve_trades
        ORDER BY id ASC
        LIMIT 10
    """)
    sample_rows = cur.fetchall()

    cur.execute("""
        SELECT signature, log_index, mint, tx_type, wallet, quote_mint, quote_amount, sol_lamports, token_base_units, slot, block_time
        FROM curve_trades
        WHERE quote_mint != ?
        ORDER BY id ASC
        LIMIT 5
    """, (WSOL_MINT,))
    non_sol_sample_rows = cur.fetchall()
    conn.close()

    # Measure actual SQLite file size on disk (including WAL if present)
    total_db_bytes = 0
    for suffix in ["", "-wal", "-shm"]:
        p = Path(f"{db_path}{suffix}")
        if p.exists():
            total_db_bytes += p.stat().st_size

    elapsed = max(1.0, stats.get("elapsed_seconds", 1.0))
    trades_per_sec = round(trades_count / elapsed, 2)
    creations_per_sec = round(creations_count / elapsed, 2)
    ws_bps = stats.get("bytes_per_second", 0.0)
    bytes_per_stored_row = round(total_db_bytes / max(1, trades_count + creations_count), 1)

    summary_payload = {
        "stats": stats,
        "db_metrics": {
            "db_path": db_path,
            "total_db_bytes_on_disk": total_db_bytes,
            "creations_in_db": creations_count,
            "trades_in_db": trades_count,
            "distinct_mints_with_trades": distinct_mints_traded,
            "distinct_wallets": distinct_wallets,
            "sol_quoted_trades": sol_trades_count,
            "sol_quoted_trades_pct": round(100.0 * sol_trades_count / max(1, trades_count), 2),
            "sol_quoted_mints": sol_mints_count,
            "sol_quoted_mints_pct": round(100.0 * sol_mints_count / max(1, distinct_mints_traded), 2),
            "usdc_quoted_trades": usdc_trades_count,
            "usdc_quoted_trades_pct": round(100.0 * usdc_trades_count / max(1, trades_count), 2),
            "usdc_quoted_mints": usdc_mints_count,
            "usdc_quoted_mints_pct": round(100.0 * usdc_mints_count / max(1, distinct_mints_traded), 2),
            "non_sol_quoted_trades": non_sol_trades_count,
            "non_sol_quoted_trades_pct": round(100.0 * non_sol_trades_count / max(1, trades_count), 2),
            "non_sol_quoted_mints": non_sol_mints_count,
            "non_sol_quoted_mints_pct": round(100.0 * non_sol_mints_count / max(1, distinct_mints_traded), 2),
            "quote_mint_breakdown": quote_mint_breakdown,
            "min_slot": min_slot,
            "max_slot": max_slot,
            "slot_span": slot_span,
            "distinct_slots": distinct_slots,
            "min_block_time": min_bt,
            "max_block_time": max_bt,
            "block_time_span_seconds": bt_span,
            "observed_slots_per_second": slots_per_sec,
            "measured_trades_per_sec": trades_per_sec,
            "measured_creations_per_sec": creations_per_sec,
            "bytes_per_stored_record": bytes_per_stored_row,
        },
        "sample_rows": [
            {
                "signature": r[0],
                "log_index": r[1],
                "mint": r[2],
                "tx_type": r[3],
                "wallet": r[4],
                "quote_mint": r[5],
                "quote_amount": r[6],
                "sol_lamports": r[7],
                "token_base_units": r[8],
                "slot": r[9],
                "block_time": r[10],
            }
            for r in sample_rows
        ],
        "non_sol_sample_rows": [
            {
                "signature": r[0],
                "log_index": r[1],
                "mint": r[2],
                "tx_type": r[3],
                "wallet": r[4],
                "quote_mint": r[5],
                "quote_amount": r[6],
                "sol_lamports": r[7],
                "token_base_units": r[8],
                "slot": r[9],
                "block_time": r[10],
            }
            for r in non_sol_sample_rows
        ],
    }

    Path(report_path).parent.mkdir(parents=True, exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(summary_payload, f, indent=2)

    if os.path.exists("data/raw_trade_samples.json"):
        shutil.copyfile("data/raw_trade_samples.json", "reports/trade_collector_1000_sample.json")

    print("\n" + "=" * 125)
    print("CURVE TRADE COLLECTOR RUN SUMMARY (Review Item 2)")
    print("=" * 125)
    print(f"WebSocket Provider (name only)    : {stats['provider_name']} (mode={stats.get('subscription_mode', 'full')})")
    print(f"Commitment Level                  : {stats['commitment']}")
    print(f"Elapsed Duration                  : {stats['elapsed_seconds']:.2f} s")
    print(f"Total WS Bytes Received           : {stats['total_ws_bytes_received']:,} bytes")
    print(f"Measured WS Throughput            : {ws_bps:,.2f} bytes/s ({ws_bps / 1024:.2f} KB/s | {ws_bps * 86400 / (1024**2):.2f} MB/day)")
    print(f"Total WS Notifications Received   : {stats['total_ws_messages_received']:,} ({stats['messages_per_second']:.2f} msgs/s)")
    print(f"Skipped (value.err != null)       : {stats['skipped_err_count']:,} ({stats.get('failed_notification_pct', 0.0):.2f}%)")
    print(f"CreateEvent Mints Recorded        : {creations_count:,} ({creations_per_sec:.2f} creations/s)")
    print(f"Trades Stored (new & <30m old)    : {trades_count:,} across {distinct_mints_traded:,} mints ({trades_per_sec:.2f} trades/s)")
    print(f"  |-- SOL-quoted                  : {sol_trades_count:,} trades ({100.0*sol_trades_count/max(1,trades_count):.2f}%) | {sol_mints_count:,} mints ({100.0*sol_mints_count/max(1,distinct_mints_traded):.2f}%)")
    print(f"  |-- USDC-quoted                 : {usdc_trades_count:,} trades ({100.0*usdc_trades_count/max(1,trades_count):.2f}%) | {usdc_mints_count:,} mints ({100.0*usdc_mints_count/max(1,distinct_mints_traded):.2f}%)")
    print(f"  |-- All Non-SOL-quoted          : {non_sol_trades_count:,} trades ({100.0*non_sol_trades_count/max(1,trades_count):.2f}%) | {non_sol_mints_count:,} mints ({100.0*non_sol_mints_count/max(1,distinct_mints_traded):.2f}%)")
    print(f"Trades Dropped Total              : {stats['dropped_trades_total']:,}")
    print(f"  |-- Dropped (pre-existing mint) : {stats['dropped_untracked_mint_count']:,}")
    print(f"  |-- Dropped (mint age > 30m)    : {stats['dropped_expired_mint_count']:,}")
    print(f"Duplicate (sig, log_idx) Ignored  : {stats['duplicate_trades_ignored']:,}")
    print("-" * 125)
    print(f"Slot Range (from context.slot)    : {min_slot} .. {max_slot} (Span: {slot_span} slots, {distinct_slots} distinct slots)")
    print(f"Block Time Range                  : {min_bt} .. {max_bt} (Span: {bt_span} s | {slots_per_sec:.2f} slots/s)")
    print(f"SQLite Disk Footprint             : {total_db_bytes:,} bytes ({bytes_per_stored_row:.1f} bytes/record)")
    print("=" * 125)
    print("QUOTE MINT BREAKDOWN IN DB:")
    for qm in quote_mint_breakdown:
        print(f"  quote_mint={qm['quote_mint']} | trades={qm['trades']:5d} ({qm['trades_share_pct']:6.2f}%) | mints={qm['distinct_mints']:3d} ({qm['mints_share_pct']:6.2f}%)")
    print("=" * 125)
    print("10 SAMPLE ROWS (sig, log_idx, mint, tx_type, wallet, quote_mint, quote_amount, sol_lamports, token_base_units, slot, block_time):")
    print("-" * 125)
    for idx, r in enumerate(sample_rows, 1):
        sol_str = f"{r[7]:12d}" if r[7] is not None else "        NULL"
        print(
            f"{idx:2d} | sig={r[0]} | idx={r[1]:2d} | mint={r[2]} | {r[3].upper():<4} | "
            f"wallet={r[4]} | q_mint={r[5]} | q_amt={r[6]:12d} | sol_lamports={sol_str} | tok_units={r[8]:16d} | slot={r[9]} | ts={r[10]}"
        )
    print("=" * 125)


async def run_worker(args: argparse.Namespace) -> None:
    duration_seconds = int(args.duration_seconds) if args.duration_seconds is not None else int(args.duration_hours * 3600)
    collector = CurveTradeCollector(
        db_path=args.db_path,
        reset_db=args.reset_db,
        subscription_mode=args.subscription_mode,
    )
    if args.pid_file:
        Path(args.pid_file).write_text(str(os.getpid()), encoding="utf-8")

    try:
        stats = await collector.run(
            max_duration_seconds=duration_seconds if duration_seconds > 0 else None,
            target_trade_count=args.target_trades,
            force_disconnect_after_trades=args.force_disconnect_after,
        )
    except (KeyboardInterrupt, asyncio.CancelledError):
        logger.info("Collector interrupted. Shutting down gracefully.")
        stats = {
            "provider_name": "QuickNode",
            "subscription_mode": args.subscription_mode,
            "commitment": "confirmed",
            "elapsed_seconds": 1.0,
            "total_ws_bytes_received": collector.total_ws_bytes_received,
            "bytes_per_second": 0.0,
            "total_ws_messages_received": collector.total_ws_messages_received,
            "messages_per_second": 0.0,
            "skipped_err_count": collector.skipped_err_count,
            "failed_notification_pct": 0.0,
            "creations_recorded": collector.creations_recorded,
            "trades_stored": collector.total_trades_collected,
            "dropped_untracked_mint_count": collector.dropped_untracked_mint_count,
            "dropped_expired_mint_count": collector.dropped_expired_mint_count,
            "dropped_trades_total": collector.dropped_untracked_mint_count + collector.dropped_expired_mint_count,
            "duplicate_trades_ignored": collector.duplicate_trades_ignored,
        }
    finally:
        collector.close()

    print_and_save_summary(args.db_path, stats)


def run_supervisor(args: argparse.Namespace) -> None:
    """
    Supervisor mode (--forever):
    Spawns the collector worker subprocess, monitors it, and automatically restarts/resumes
    if the worker crashes or is forcibly terminated (e.g., kill -9 / TerminateProcess),
    until the total target duration (or infinite if not set) expires.
    """
    total_duration = int(args.duration_seconds) if args.duration_seconds is not None else int(args.duration_hours * 3600)
    sup_start = time.time()
    restart_count = 0

    logger.info(
        f"Supervisor (--forever) started (PID={os.getpid()}). "
        f"Target total duration={total_duration}s | Max restarts={args.max_restarts}"
    )

    first_run = True
    while True:
        elapsed = time.time() - sup_start
        if total_duration > 0 and elapsed >= total_duration:
            logger.info("Supervisor total duration reached. Exiting cleanly.")
            break

        rem_sec = max(1, int(total_duration - elapsed)) if total_duration > 0 else 0
        cmd = [
            sys.executable,
            os.path.abspath(__file__),
            "--worker",
            "--db-path", args.db_path,
            "--duration-seconds", str(rem_sec),
            "--subscription-mode", args.subscription_mode,
        ]
        if first_run and args.reset_db:
            cmd.append("--reset-db")
        if args.pid_file:
            cmd.extend(["--pid-file", args.pid_file])
        first_run = False

        logger.info(f"Supervisor spawning worker (restart #{restart_count}): {' '.join(cmd)}")
        proc = subprocess.Popen(cmd)
        try:
            rc = proc.wait()
        except KeyboardInterrupt:
            logger.info("Supervisor received KeyboardInterrupt; terminating worker...")
            proc.terminate()
            proc.wait(timeout=10)
            break

        elapsed = time.time() - sup_start
        if rc == 0 and (total_duration > 0 and elapsed >= total_duration - 1):
            logger.info("Worker completed scheduled duration (exit code 0).")
            break

        restart_count += 1
        logger.warning(
            f"Worker exited unexpectedly with code {rc} (forced kill / crash). "
            f"Restart #{restart_count} in 2.0s (resuming state from {args.db_path})..."
        )
        if args.max_restarts is not None and restart_count > args.max_restarts:
            logger.info(f"Reached max_restarts ({args.max_restarts}). Supervisor stopping.")
            break
        time.sleep(2.0)


def main():
    parser = argparse.ArgumentParser(description="Collect live pump.fun creations and trades from Solana WebSocket.")
    parser.add_argument("--duration-hours", type=float, default=6.0, help="Duration to run collection in hours")
    parser.add_argument("--duration-seconds", type=int, default=None, help="Override duration in seconds")
    parser.add_argument("--target-trades", type=int, default=None, help="Stop after reaching this many trades")
    parser.add_argument("--force-disconnect-after", type=int, default=None, help="Force WS disconnect after N trades")
    parser.add_argument("--db-path", type=str, default="data/curve_trades.db", help="Path to SQLite database")
    parser.add_argument("--reset-db", action="store_true", help="Drop and recreate tables before starting")
    parser.add_argument("--subscription-mode", type=str, choices=["full", "smaller"], default="full", help="Subscription mode: full (program) or smaller (MintAuthority + active curves)")
    parser.add_argument("--forever", action="store_true", help="Run supervisor loop that auto-restarts on crash/kill")
    parser.add_argument("--worker", action="store_true", help="Internal flag for supervised worker process")
    parser.add_argument("--pid-file", type=str, default=None, help="Write worker PID to file for kill -9 testing")
    parser.add_argument("--max-restarts", type=int, default=None, help="Optional cap on supervisor restarts for testing")
    args = parser.parse_args()

    if args.forever and not args.worker:
        run_supervisor(args)
    else:
        asyncio.run(run_worker(args))


if __name__ == "__main__":
    main()

"""
Coverage Audit for 6-Hour CurveTradeCollector Dataset (Review Item 2):
1. Sample A: 40 random mints from the 5,250 created mints with 0 stored trades.
   - Call SolanaProvider.execute_rpc("getSignaturesForAddress", [bonding_curve, ...])
   - Report how many had trades in their first 30 minutes (1800s).
   - For any non-creation signatures in the first 30m, fetch getTransaction to verify whether
     they emitted TradeEvent or were non-trade instructions / occurred during a WS gap.
2. Sample B: 40 random mints from the 6,530 created mints with >0 stored trades.
   - Call SolanaProvider.execute_rpc("getSignaturesForAddress", [bonding_curve, ...])
   - Compare stored trade count (and stored distinct trade signatures) with on-chain successful
     trade count in the same 30-minute window [created_block_time, created_block_time + 1800].
   - For any difference between on-chain signatures and stored signatures, inspect the missing
     signatures (gap slot check + getTransaction log inspection) to identify any systematic miss.
"""

import base64
import json
import os
import random
import sqlite3
import sys
from typing import Any, Dict, List, Set, Tuple

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from src.onchain.provider import SolanaProvider
from src.onchain.trade_collector import (
    CREATE_EVENT_DISCRIMINATOR,
    TRADE_EVENT_DISCRIMINATOR,
    COMPLETE_EVENT_DISCRIMINATOR,
    COMPLETE_MIGRATION_DISCRIMINATOR,
)


def fetch_all_sigs_in_30m(
    provider: SolanaProvider,
    bonding_curve: str,
    created_bt: int,
    created_slot: int,
) -> List[Dict[str, Any]]:
    """Fetch all getSignaturesForAddress entries on bonding_curve within [created_bt, created_bt + 1800]."""
    all_sigs: List[Dict[str, Any]] = []
    before_sig = None
    while True:
        opts: Dict[str, Any] = {"limit": 1000}
        if before_sig:
            opts["before"] = before_sig
        res = provider.execute_rpc("getSignaturesForAddress", [bonding_curve, opts])
        batch = res.get("result") or []
        if not batch:
            break
        all_sigs.extend(batch)
        oldest_bt = batch[-1].get("blockTime")
        oldest_slot = batch[-1].get("slot", 0)
        if len(batch) < 1000:
            break
        if oldest_bt is not None and oldest_bt < created_bt:
            break
        if oldest_slot and oldest_slot < created_slot:
            break
        before_sig = batch[-1].get("signature")
    return all_sigs


def inspect_tx_events(provider: SolanaProvider, sig: str) -> Dict[str, Any]:
    """Fetch transaction and count TradeEvents, CreateEvents, CompleteEvents, and Instruction logs."""
    res = provider.execute_rpc(
        "getTransaction",
        [sig, {"encoding": "json", "commitment": "confirmed", "maxSupportedTransactionVersion": 0}],
    )
    tx = res.get("result")
    if not tx:
        res = provider.execute_rpc(
            "getTransaction",
            [sig, {"encoding": "json", "commitment": "confirmed", "maxSupportedTransactionVersion": 1}],
        )
        tx = res.get("result")
    if not tx:
        return {"found": False, "trade_events": 0, "instructions": []}

    meta = tx.get("meta") or {}
    logs = meta.get("logMessages") or []
    trade_events = 0
    create_events = 0
    complete_events = 0
    instructions: List[str] = []
    for l in logs:
        if "Program log: Instruction: " in l:
            instructions.append(l.split("Program log: Instruction: ", 1)[1].strip())
        elif "Program data: " in l:
            b64_str = l.split("Program data: ", 1)[1].strip()
            try:
                raw = base64.b64decode(b64_str)
                disc = raw[:8]
                if disc == TRADE_EVENT_DISCRIMINATOR:
                    trade_events += 1
                elif disc == CREATE_EVENT_DISCRIMINATOR:
                    create_events += 1
                elif disc in (COMPLETE_EVENT_DISCRIMINATOR, COMPLETE_MIGRATION_DISCRIMINATOR):
                    complete_events += 1
            except Exception:
                pass
    return {
        "found": True,
        "slot": tx.get("slot"),
        "blockTime": tx.get("blockTime"),
        "err": meta.get("err"),
        "trade_events": trade_events,
        "create_events": create_events,
        "complete_events": complete_events,
        "instructions": instructions,
    }


def main():
    provider = SolanaProvider()
    conn = sqlite3.connect("data/curve_trades.db")
    cur = conn.cursor()

    # Load collector gaps
    cur.execute("SELECT gap_id, start_slot, end_slot, duration_seconds FROM collector_gaps ORDER BY gap_id ASC")
    gaps = cur.fetchall()

    def is_slot_in_gap(slot: int) -> Optional[int]:
        for gid, s_start, s_end, _ in gaps:
            if s_start < slot < s_end:
                return gid
        return None

    # collector end block_time (after which collector stopped listening)
    cur.execute("SELECT MAX(block_time), MAX(slot) FROM curve_trades")
    max_collector_bt, max_collector_slot = cur.fetchone()

    # 1. Identify all 5,250 created mints with 0 stored trades and 6,530 created mints with >0 stored trades
    cur.execute("""
        SELECT c.mint, c.bonding_curve, c.signature, c.slot, c.created_block_time, c.name, c.symbol, c.excluded_gap
        FROM curve_creations c
        LEFT JOIN (SELECT DISTINCT mint FROM curve_trades) t ON c.mint = t.mint
        WHERE t.mint IS NULL
        ORDER BY c.slot ASC, c.mint ASC
    """)
    zero_trade_mints = cur.fetchall()

    cur.execute("""
        SELECT c.mint, c.bonding_curve, c.signature, c.slot, c.created_block_time, c.name, c.symbol, c.excluded_gap
        FROM curve_creations c
        INNER JOIN (SELECT DISTINCT mint FROM curve_trades) t ON c.mint = t.mint
        ORDER BY c.slot ASC, c.mint ASC
    """)
    traded_mints = cur.fetchall()

    print(f"Total created mints: {len(zero_trade_mints) + len(traded_mints)}")
    print(f"Created mints with 0 stored trades: {len(zero_trade_mints)}")
    print(f"Created mints with >0 stored trades: {len(traded_mints)}")

    rng_a = random.Random(42)
    sample_a = rng_a.sample(zero_trade_mints, 40)

    rng_b = random.Random(42)
    sample_b = rng_b.sample(traded_mints, 40)

    # --- SAMPLE A: 40 Random Mints with 0 Stored Trades ---
    print("\n" + "=" * 140)
    print("SAMPLE A: 40 RANDOM CREATED MINTS WITH 0 STORED TRADES")
    print("=" * 140)
    print(
        f"{'#':<3} | {'MINT':<44} | {'BONDING CURVE':<44} | {'CREATED SLOT':<12} | "
        f"{'OK SIGS (30m)':<13} | {'ONCHAIN TRADES (30m)':<20} | {'NOTES'}"
    )
    print("-" * 140)

    sample_a_results = []
    sample_a_with_trades = 0
    sample_a_with_trades_in_active_window = 0

    for idx, (mint, b_curve, create_sig, create_slot, create_bt, name, symbol, excl_gap) in enumerate(sample_a, 1):
        sigs = fetch_all_sigs_in_30m(provider, b_curve, create_bt, create_slot)
        # Filter to successful sigs within first 30 minutes [create_bt, create_bt + 1800]
        ok_30m = [
            s for s in sigs
            if s.get("err") is None
            and s.get("blockTime") is not None
            and create_bt <= int(s["blockTime"]) <= create_bt + 1800
        ]
        non_create_sigs = [s for s in ok_30m if s.get("signature") != create_sig]

        onchain_trades_30m = 0
        onchain_trades_before_collector_stop = 0
        onchain_trades_in_gap = 0
        notes = []

        # Also verify the creation tx on the first 3 mints (or any mint with non_create_sigs)
        if idx <= 3:
            c_info = inspect_tx_events(provider, create_sig)
            onchain_trades_30m += c_info["trade_events"]

        for s in non_create_sigs:
            sig_str = s["signature"]
            s_slot = int(s.get("slot") or 0)
            info = inspect_tx_events(provider, sig_str)
            t_cnt = info["trade_events"]
            onchain_trades_30m += t_cnt
            if t_cnt > 0:
                gid = is_slot_in_gap(s_slot)
                if s_slot > max_collector_slot:
                    notes.append(f"post_run_stop(slot={s_slot})")
                elif gid is not None:
                    onchain_trades_in_gap += t_cnt
                    notes.append(f"in_gap_{gid}(slot={s_slot},trades={t_cnt})")
                else:
                    onchain_trades_before_collector_stop += t_cnt
                    notes.append(f"missed(slot={s_slot},trades={t_cnt},ix={info['instructions']})")
            else:
                notes.append(f"non_trade_tx(ix={info['instructions']})")

        if not non_create_sigs:
            notes.append(f"Create-only ({name[:22]!r})")

        if onchain_trades_30m > 0:
            sample_a_with_trades += 1
        if onchain_trades_before_collector_stop > 0:
            sample_a_with_trades_in_active_window += 1

        note_str = "; ".join(notes)
        print(
            f"{idx:<3d} | {mint:<44} | {b_curve:<44} | {create_slot:<12d} | "
            f"{len(ok_30m):<13d} | {onchain_trades_30m:<20d} | {note_str}"
        )
        sample_a_results.append({
            "index": idx,
            "mint": mint,
            "bonding_curve": b_curve,
            "creation_signature": create_sig,
            "created_slot": create_slot,
            "created_block_time": create_bt,
            "name": name,
            "symbol": symbol,
            "ok_signatures_in_30m": len(ok_30m),
            "non_creation_signatures_in_30m": len(non_create_sigs),
            "onchain_trades_in_30m": onchain_trades_30m,
            "onchain_trades_in_gap": onchain_trades_in_gap,
            "onchain_trades_missed_while_connected": onchain_trades_before_collector_stop,
            "notes": note_str,
        })

    print("-" * 140)
    print(
        f"SAMPLE A SUMMARY: {sample_a_with_trades}/40 ({100.0*sample_a_with_trades/40:.1f}%) had any trade in first 30m | "
        f"{40 - sample_a_with_trades}/40 ({100.0*(40 - sample_a_with_trades)/40:.1f}%) were strictly Create-only (0 trades on-chain) | "
        f"Missed while connected (outside WS gaps / post-stop): {sample_a_with_trades_in_active_window}/40"
    )

    # --- SAMPLE B: 40 Random Mints with >0 Stored Trades ---
    print("\n" + "=" * 150)
    print("SAMPLE B: 40 RANDOM CREATED MINTS WITH >0 STORED TRADES (30-MINUTE WINDOW COMPARISON)")
    print("=" * 150)
    print(
        f"{'#':<3} | {'MINT':<44} | {'STORED TRADES':<13} | {'STORED SIGS':<11} | "
        f"{'ONCHAIN TRADE SIGS':<18} | {'ONCHAIN TRADE EVENTS':<20} | {'GAP/POST-STOP':<13} | {'COVERAGE %':<10} | {'NOTES'}"
    )
    print("-" * 150)

    sample_b_results = []
    total_stored_events_b = 0
    total_onchain_events_b = 0
    total_onchain_connected_events_b = 0

    for idx, (mint, b_curve, create_sig, create_slot, create_bt, name, symbol, excl_gap) in enumerate(sample_b, 1):
        cur.execute(
            "SELECT signature, log_index, slot, block_time FROM curve_trades WHERE mint = ? ORDER BY slot ASC, log_index ASC",
            (mint,),
        )
        db_rows = cur.fetchall()
        stored_event_count = len(db_rows)
        stored_sigs: Set[str] = {r[0] for r in db_rows}
        events_per_stored_sig: Dict[str, int] = {}
        for r in db_rows:
            events_per_stored_sig[r[0]] = events_per_stored_sig.get(r[0], 0) + 1

        sigs = fetch_all_sigs_in_30m(provider, b_curve, create_bt, create_slot)
        ok_30m = [
            s for s in sigs
            if s.get("err") is None
            and s.get("blockTime") is not None
            and create_bt <= int(s["blockTime"]) <= create_bt + 1800
        ]

        # Determine which on-chain signatures in [create_bt, create_bt + 1800] had TradeEvents:
        # 1. Any signature already in stored_sigs definitely had events_per_stored_sig[sig] TradeEvents
        #    (since _parse_and_store_notification processes ALL logs in a received transaction notification).
        # 2. For any signature in ok_30m NOT in stored_sigs:
        #    - If sig == create_sig and create_sig not in stored_sigs: creation tx had 0 TradeEvents (since CreateEvent was parsed from that exact tx!).
        #    - Otherwise, inspect via getTransaction to count exact TradeEvents and see why it wasn't in stored_sigs!
        onchain_trade_sigs = 0
        onchain_trade_events = 0
        gap_or_post_stop_events = 0
        connected_missed_events = 0
        notes = []

        for s in ok_30m:
            sig_str = s["signature"]
            s_slot = int(s.get("slot") or 0)
            if sig_str in stored_sigs:
                onchain_trade_sigs += 1
                onchain_trade_events += events_per_stored_sig[sig_str]
            elif sig_str == create_sig:
                # Creation tx was received and parsed (that's how mint is in curve_creations);
                # if create_sig is not in stored_sigs, it had 0 TradeEvents.
                continue
            else:
                gid = is_slot_in_gap(s_slot)
                if s_slot > max_collector_slot:
                    onchain_trade_sigs += 1
                    onchain_trade_events += 1
                    gap_or_post_stop_events += 1
                    notes.append(f"post_stop(slot={s_slot})")
                elif gid is not None:
                    onchain_trade_sigs += 1
                    onchain_trade_events += 1
                    gap_or_post_stop_events += 1
                    notes.append(f"in_gap_{gid}(slot={s_slot})")
                else:
                    info = inspect_tx_events(provider, sig_str)
                    t_cnt = info["trade_events"]
                    if t_cnt > 0:
                        onchain_trade_sigs += 1
                        onchain_trade_events += t_cnt
                        connected_missed_events += t_cnt
                        notes.append(f"missed_connected(slot={s_slot},ev={t_cnt},ix={info['instructions']})")
                    else:
                        notes.append(f"non_trade_tx(ix={info['instructions'][:2]})")

        cov_raw_pct = 100.0 * stored_event_count / max(1, onchain_trade_events)
        onchain_connected_events = max(stored_event_count, onchain_trade_events - gap_or_post_stop_events)
        cov_connected_pct = 100.0 * stored_event_count / max(1, onchain_connected_events)

        total_stored_events_b += stored_event_count
        total_onchain_events_b += onchain_trade_events
        total_onchain_connected_events_b += onchain_connected_events

        if not notes:
            notes.append("100% match")
        note_str = "; ".join(notes[:4])

        print(
            f"{idx:<3d} | {mint:<44} | {stored_event_count:<13d} | {len(stored_sigs):<11d} | "
            f"{onchain_trade_sigs:<18d} | {onchain_trade_events:<20d} | {gap_or_post_stop_events:<13d} | "
            f"{cov_raw_pct:<9.2f}% | {note_str}"
        )
        sample_b_results.append({
            "index": idx,
            "mint": mint,
            "bonding_curve": b_curve,
            "created_slot": create_slot,
            "created_block_time": create_bt,
            "excluded_gap": excl_gap,
            "stored_trade_events": stored_event_count,
            "stored_distinct_trade_sigs": len(stored_sigs),
            "onchain_trade_sigs_in_30m": onchain_trade_sigs,
            "onchain_trade_events_in_30m": onchain_trade_events,
            "gap_or_post_stop_trade_events": gap_or_post_stop_events,
            "connected_missed_trade_events": connected_missed_events,
            "raw_coverage_pct": round(cov_raw_pct, 2),
            "connected_coverage_pct": round(cov_connected_pct, 2),
            "notes": note_str,
        })

    agg_raw_cov = 100.0 * total_stored_events_b / max(1, total_onchain_events_b)
    agg_conn_cov = 100.0 * total_stored_events_b / max(1, total_onchain_connected_events_b)
    perfect_raw_cnt = sum(1 for r in sample_b_results if r["stored_trade_events"] == r["onchain_trade_events_in_30m"])
    perfect_conn_cnt = sum(1 for r in sample_b_results if r["connected_missed_trade_events"] == 0)

    print("-" * 150)
    print(
        f"SAMPLE B SUMMARY: Stored={total_stored_events_b} events across 40 mints | "
        f"On-chain 30m total={total_onchain_events_b} events (Raw coverage={agg_raw_cov:.2f}%, {perfect_raw_cnt}/40 mints 100%) | "
        f"On-chain while connected={total_onchain_connected_events_b} events (Connected coverage={agg_conn_cov:.2f}%, {perfect_conn_cnt}/40 mints 100%)"
    )
    print("=" * 150)

    report = {
        "total_created_mints": len(zero_trade_mints) + len(traded_mints),
        "zero_trade_mints_count": len(zero_trade_mints),
        "zero_trade_mints_pct": round(100.0 * len(zero_trade_mints) / (len(zero_trade_mints) + len(traded_mints)), 2),
        "traded_mints_count": len(traded_mints),
        "sample_a_zero_stored_trades": {
            "sample_size": 40,
            "random_seed": 42,
            "mints_with_any_onchain_trade_in_30m": sample_a_with_trades,
            "mints_strictly_create_only_0_trades_onchain": 40 - sample_a_with_trades,
            "mints_with_missed_trade_while_connected": sample_a_with_trades_in_active_window,
            "rows": sample_a_results,
        },
        "sample_b_positive_stored_trades": {
            "sample_size": 40,
            "random_seed": 42,
            "total_stored_trade_events": total_stored_events_b,
            "total_onchain_trade_events_in_30m": total_onchain_events_b,
            "total_onchain_connected_trade_events_in_30m": total_onchain_connected_events_b,
            "aggregate_raw_coverage_pct": round(agg_raw_cov, 2),
            "aggregate_connected_coverage_pct": round(agg_conn_cov, 2),
            "mints_with_100pct_raw_coverage": perfect_raw_cnt,
            "mints_with_100pct_connected_coverage": perfect_conn_cnt,
            "rows": sample_b_results,
        },
    }
    with open("reports/coverage_audit_6h.json", "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    print("Saved coverage audit report to reports/coverage_audit_6h.json.")
    conn.close()


if __name__ == "__main__":
    main()

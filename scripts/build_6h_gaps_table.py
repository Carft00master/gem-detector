"""
Build the exact 6-hour gaps table (Review Item 1):
1. Identify all 11 WebSocket disconnect gaps (provider, start_slot, end_slot, seconds) from data/curve_trades.db.
2. For each gap, find the last creation signature at/before start_slot (sig_before) and first creation signature
   at/after end_slot (sig_after), and call SolanaProvider.execute_rpc("getSignaturesForAddress",
   ["TSLvdd1pWpHVjahSpsvCXUbgwsL3JAcvokwaKt1eokM", {"before": sig_after, "until": sig_before, "limit": 1000}])
   to count the exact on-chain mints created during the gap [start_slot, end_slot].
3. Also identify any mints in curve_creations created at the boundary slots [start_slot, end_slot] or whose
   active 30-minute observation window overlapped the gap, and mark excluded_gap = 1 in curve_creations
   and store the collector_gaps table in data/curve_trades.db and reports/collector_6h_gaps.json.
"""

import json
import os
import sqlite3
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from src.onchain.provider import SolanaProvider
from src.onchain.trade_collector import MINT_AUTHORITY_PDA


def main():
    provider = SolanaProvider()
    conn = sqlite3.connect("data/curve_trades.db")
    cur = conn.cursor()

    # Ensure excluded_gap column exists on curve_creations
    cur.execute("PRAGMA table_info(curve_creations)")
    cols = {r[1] for r in cur.fetchall()}
    if "excluded_gap" not in cols:
        cur.execute("ALTER TABLE curve_creations ADD COLUMN excluded_gap INTEGER NOT NULL DEFAULT 0")
    else:
        cur.execute("UPDATE curve_creations SET excluded_gap = 0")

    # Create collector_gaps table
    cur.execute("DROP TABLE IF EXISTS collector_gaps")
    cur.execute("""
        CREATE TABLE collector_gaps (
            gap_id INTEGER PRIMARY KEY AUTOINCREMENT,
            provider TEXT NOT NULL,
            start_slot INTEGER NOT NULL,
            end_slot INTEGER NOT NULL,
            slot_span INTEGER NOT NULL,
            duration_seconds REAL NOT NULL,
            last_event_utc TEXT NOT NULL,
            first_event_after_utc TEXT NOT NULL,
            onchain_mints_created_during_gap INTEGER NOT NULL,
            db_boundary_mints_in_gap INTEGER NOT NULL,
            db_active_30m_mints_overlapping_gap INTEGER NOT NULL
        )
    """)
    conn.commit()

    # Find all slot gaps > 15 slots across all events in DB
    cur.execute("""
        SELECT slot, MIN(block_time), MAX(block_time), MIN(created_at_utc), MAX(created_at_utc)
        FROM (
            SELECT slot, block_time, created_at_utc FROM curve_trades
            UNION ALL
            SELECT slot, created_block_time as block_time, created_at_utc FROM curve_creations
        )
        GROUP BY slot
        ORDER BY slot ASC
    """)
    slot_rows = cur.fetchall()

    raw_gaps = []
    for i in range(1, len(slot_rows)):
        s_prev, bt_prev, _, _, utc_prev = slot_rows[i - 1]
        s_curr, bt_curr, _, utc_curr, _ = slot_rows[i]
        if s_curr - s_prev > 15:
            raw_gaps.append((s_prev, s_curr, bt_prev, bt_curr, utc_prev, utc_curr))

    gaps_report = []
    all_boundary_excluded_mints = set()
    all_window_overlapping_mints = set()

    print("=" * 135)
    print("6-HOUR COLLECTOR GAPS TABLE (Review Item 1)")
    print("=" * 135)
    print(
        f"{'GAP':<4} | {'PROVIDER':<8} | {'START SLOT':<10} | {'END SLOT':<10} | {'SLOTS':<5} | {'SECONDS':<7} | "
        f"{'ONCHAIN CREATIONS IN GAP':<24} | {'DB BOUNDARY MINTS':<17} | {'ACTIVE <30m OVERLAP':<19}"
    )
    print("-" * 135)

    for idx, (s_start, s_end, bt_start, bt_end, utc_start, utc_end) in enumerate(raw_gaps, 1):
        slot_span = s_end - s_start
        dur_sec = float(bt_end - bt_start)

        # Find sig_before (latest creation at or before s_start) and sig_after (earliest creation at or after s_end)
        cur.execute(
            "SELECT signature, slot FROM curve_creations WHERE slot <= ? ORDER BY slot DESC, rowid DESC LIMIT 1",
            (s_start,),
        )
        row_before = cur.fetchone()
        cur.execute(
            "SELECT signature, slot FROM curve_creations WHERE slot >= ? ORDER BY slot ASC, rowid ASC LIMIT 1",
            (s_end,),
        )
        row_after = cur.fetchone()

        onchain_creations_in_gap = 0
        if row_before and row_after:
            sig_before = row_before[0]
            sig_after = row_after[0]
            res = provider.execute_rpc(
                "getSignaturesForAddress",
                [MINT_AUTHORITY_PDA, {"before": sig_after, "until": sig_before, "limit": 1000}],
            )
            sigs = res.get("result") or []
            # Count successful creation signatures strictly between s_start and s_end (or in [s_start, s_end])
            onchain_creations_in_gap = sum(
                1 for s in sigs if s.get("err") is None and s_start <= int(s.get("slot", 0)) <= s_end
            )

        # DB mints created in [bt_start, bt_end] or [s_start, s_end]
        cur.execute(
            "SELECT mint FROM curve_creations WHERE (slot >= ? AND slot <= ?) OR (created_block_time >= ? AND created_block_time <= ?)",
            (s_start, s_end, bt_start, bt_end),
        )
        boundary_mints = [r[0] for r in cur.fetchall()]
        all_boundary_excluded_mints.update(boundary_mints)

        # DB mints whose 30-minute observation window overlapped [bt_start, bt_end]
        cur.execute(
            "SELECT mint FROM curve_creations WHERE created_block_time >= ? AND created_block_time <= ?",
            (bt_start - 1800, bt_end),
        )
        overlap_mints = [r[0] for r in cur.fetchall()]
        all_window_overlapping_mints.update(overlap_mints)

        cur.execute(
            """
            INSERT INTO collector_gaps (
                provider, start_slot, end_slot, slot_span, duration_seconds,
                last_event_utc, first_event_after_utc,
                onchain_mints_created_during_gap, db_boundary_mints_in_gap, db_active_30m_mints_overlapping_gap
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "Helius",
                s_start,
                s_end,
                slot_span,
                dur_sec,
                utc_start,
                utc_end,
                onchain_creations_in_gap,
                len(boundary_mints),
                len(overlap_mints),
            ),
        )

        gap_entry = {
            "gap_id": idx,
            "provider": "Helius",
            "start_slot": s_start,
            "end_slot": s_end,
            "slot_span": slot_span,
            "seconds": dur_sec,
            "last_event_utc": utc_start,
            "first_event_after_utc": utc_end,
            "mints_created_during_gap_onchain": onchain_creations_in_gap,
            "db_boundary_mints_in_gap": len(boundary_mints),
            "db_boundary_mint_list": boundary_mints,
            "db_active_30m_mints_overlapping_gap": len(overlap_mints),
        }
        gaps_report.append(gap_entry)

        print(
            f"{idx:<4d} | {'Helius':<8} | {s_start:<10d} | {s_end:<10d} | {slot_span:<5d} | {dur_sec:<7.1f} | "
            f"{onchain_creations_in_gap:<24d} | {len(boundary_mints):<17d} | {len(overlap_mints):<19d}"
        )

    # Mark mints in curve_creations created during/overlapping a gap:
    # 1) Mark boundary mints created during [bt_start, bt_end] / [s_start, s_end] as excluded_gap = 1
    # 2) Mark mints whose 30m window overlapped a gap as excluded_gap = 2 so both strict gap-creation exclusion
    #    (excluded_gap >= 1) and full 30m-window gap exclusion (excluded_gap == 2) are recorded in curve_creations!
    for m in all_window_overlapping_mints:
        cur.execute("UPDATE curve_creations SET excluded_gap = 2 WHERE mint = ?", (m,))
    for m in all_boundary_excluded_mints:
        cur.execute("UPDATE curve_creations SET excluded_gap = 1 WHERE mint = ?", (m,))
    conn.commit()
    conn.close()

    total_slots_gap = sum(g["slot_span"] for g in gaps_report)
    total_sec_gap = sum(g["seconds"] for g in gaps_report)
    total_onchain_missed = sum(g["mints_created_during_gap_onchain"] for g in gaps_report)

    print("-" * 135)
    print(
        f"TOTALS: 11 gaps | {total_slots_gap} slots ({total_sec_gap:.1f}s = {100.0*total_sec_gap/21609.12:.2f}% of 6h run) | "
        f"On-chain mints created during gaps: {total_onchain_missed} | "
        f"DB boundary mints (excluded_gap=1): {len(all_boundary_excluded_mints)} | "
        f"DB <30m window overlap mints (excluded_gap=2): {len(all_window_overlapping_mints)}"
    )
    print("=" * 135)

    summary = {
        "total_gaps": len(gaps_report),
        "total_gap_slots": total_slots_gap,
        "total_gap_seconds": total_sec_gap,
        "gap_share_of_6h_run_pct": round(100.0 * total_sec_gap / 21609.12, 3),
        "total_onchain_mints_created_during_gaps": total_onchain_missed,
        "db_boundary_mints_excluded_count": len(all_boundary_excluded_mints),
        "db_boundary_mints_excluded": sorted(all_boundary_excluded_mints),
        "db_30m_window_overlap_mints_excluded_count": len(all_window_overlapping_mints),
        "gaps": gaps_report,
    }
    with open("reports/collector_6h_gaps.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    print("Saved gaps report to reports/collector_6h_gaps.json.")


if __name__ == "__main__":
    main()

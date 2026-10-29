"""
Route A Descriptives on 6-Hour SOL-Quoted Cohort (Review Item 4):
Computes and outputs reports/route_a_descriptives.json and verbatim console tables:
1. Cohort separation: SOL-quoted vs non-SOL-quoted, gap-excluded mints.
2. Graduation rate within 30 minutes (overall, organic >2 slots / >25 slots vs bundled 0-2 slots).
3. Distinct buyers (excluding high-frequency bot wallets active in >=50 mints and wallets that
   round-trip buy+sell the same mint within 60s) at +1m, +2m, +5m, +10m.
4. Market-cap paths (SOL and USD at $150/SOL) at +1m, +2m, +5m, +10m, +30m.
5. Creator and top-10 holder shares of 1B total supply computed from cumulative curve trade balances.
6. Wash/bump & high-frequency bot wallet trade and SOL volume shares.
7. Hourly variation across Hours 1..6.
"""

from collections import defaultdict
import json
import math
import os
import sqlite3
import sys
from typing import Any, Dict, List, Set, Tuple

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from src.onchain.trade_collector import WSOL_MINT

TOTAL_SUPPLY_BASE_UNITS = 1_000_000_000_000_000  # 1B tokens * 10^6 decimals
INITIAL_V_SOL = 30_000_000_000                   # 30 SOL
INITIAL_V_TOK = 1_073_000_000_000_000            # 1.073B tokens
INITIAL_R_TOK = 793_100_000_000_000              # 793.1M tradable tokens
SOL_PRICE_USD = 150.0


def percentile(sorted_vals: List[float], p: float) -> float:
    if not sorted_vals:
        return 0.0
    if len(sorted_vals) == 1:
        return float(sorted_vals[0])
    idx = (len(sorted_vals) - 1) * (p / 100.0)
    lo = int(math.floor(idx))
    hi = int(math.ceil(idx))
    if lo == hi:
        return float(sorted_vals[lo])
    return float(sorted_vals[lo] * (hi - idx) + sorted_vals[hi] * (idx - lo))


def summarize_dist(vals: List[float], decimals: int = 2) -> Dict[str, Any]:
    if not vals:
        return {"count": 0, "min": 0.0, "p10": 0.0, "p25": 0.0, "median": 0.0, "mean": 0.0, "p75": 0.0, "p90": 0.0, "p95": 0.0, "max": 0.0}
    s = sorted(vals)
    return {
        "count": len(s),
        "min": round(s[0], decimals),
        "p10": round(percentile(s, 10), decimals),
        "p25": round(percentile(s, 25), decimals),
        "median": round(percentile(s, 50), decimals),
        "mean": round(sum(s) / len(s), decimals),
        "p75": round(percentile(s, 75), decimals),
        "p90": round(percentile(s, 90), decimals),
        "p95": round(percentile(s, 95), decimals),
        "max": round(s[-1], decimals),
    }


def main():
    conn = sqlite3.connect("data/curve_trades.db")
    cur = conn.cursor()

    # 1. Load creations
    cur.execute("""
        SELECT mint, creator, slot, created_block_time, excluded_gap
        FROM curve_creations
        ORDER BY created_block_time ASC, slot ASC
    """)
    creations = cur.fetchall()
    mint_info: Dict[str, Dict[str, Any]] = {}
    min_bt = creations[0][3]
    max_bt = creations[-1][3]
    for m, creator, slot, c_bt, excl_gap in creations:
        mint_info[m] = {
            "mint": m,
            "creator": creator,
            "created_slot": int(slot),
            "created_bt": int(c_bt),
            "excluded_gap": int(excl_gap),
        }

    # Load completions
    cur.execute("SELECT mint, slot, block_time, event_type FROM curve_completions")
    completions_map: Dict[str, Dict[str, Any]] = {}
    for m, s, bt, ev_type in cur.fetchall():
        completions_map[m] = {"slot": int(s), "block_time": int(bt), "event_type": ev_type}

    # Check quote separation
    cur.execute("""
        SELECT quote_mint, COUNT(*), COUNT(DISTINCT mint)
        FROM curve_trades
        GROUP BY quote_mint
        ORDER BY COUNT(*) DESC
    """)
    quote_rows = cur.fetchall()
    total_all_trades = sum(r[1] for r in quote_rows)
    sol_trade_count = sum(r[1] for r in quote_rows if r[0] == WSOL_MINT)
    nonsol_trade_count = total_all_trades - sol_trade_count

    # Load all SOL-quoted trades ordered by mint, slot, log_index
    cur.execute("""
        SELECT
            mint, tx_type, wallet, sol_lamports, token_base_units,
            virtual_sol_reserves, virtual_token_reserves,
            real_sol_reserves, real_token_reserves,
            slot, block_time
        FROM curve_trades
        WHERE quote_mint = ?
        ORDER BY mint ASC, slot ASC, log_index ASC, id ASC
    """, (WSOL_MINT,))
    sol_trades_raw = cur.fetchall()

    # Group SOL trades by mint & identify wallet activity across mints
    trades_by_mint: Dict[str, List[Tuple]] = defaultdict(list)
    wallet_mints: Dict[str, Set[str]] = defaultdict(set)
    for row in sol_trades_raw:
        m = row[0]
        w = row[2]
        trades_by_mint[m].append(row)
        wallet_mints[w].add(m)

    # Identify wallets active in >= 50 distinct mints
    high_freq_bot_wallets: Set[str] = {w for w, ms in wallet_mints.items() if len(ms) >= 50}

    # Identify round-trip wallets per mint (wallets that both buy and sell the same mint within <= 60s)
    # Also compute causal round-trip up to horizon H so both causal and full-window are available
    roundtrip_60s_by_mint: Dict[str, Set[str]] = defaultdict(set)
    all_roundtrip_wallets: Set[str] = set()

    for m, t_list in trades_by_mint.items():
        buy_times_by_wallet: Dict[str, List[int]] = defaultdict(list)
        sell_times_by_wallet: Dict[str, List[int]] = defaultdict(list)
        for r in t_list:
            tx_type = r[1]
            w = r[2]
            bt = int(r[10])
            if tx_type == "buy":
                buy_times_by_wallet[w].append(bt)
            else:
                sell_times_by_wallet[w].append(bt)
        for w, b_ts_list in buy_times_by_wallet.items():
            s_ts_list = sell_times_by_wallet.get(w)
            if not s_ts_list:
                continue
            # Check if any buy and sell by w on mint m are within 60 seconds
            is_rt = False
            i_b, i_s = 0, 0
            b_sorted = sorted(b_ts_list)
            s_sorted = sorted(s_ts_list)
            while i_b < len(b_sorted) and i_s < len(s_sorted):
                if abs(s_sorted[i_s] - b_sorted[i_b]) <= 60:
                    is_rt = True
                    break
                if b_sorted[i_b] < s_sorted[i_s]:
                    i_b += 1
                else:
                    i_s += 1
            if is_rt:
                roundtrip_60s_by_mint[m].add(w)
                all_roundtrip_wallets.add(w)

    # Filter SOL-quoted traded mints excluding gap boundary creations (excluded_gap == 1)
    all_sol_mints = sorted(trades_by_mint.keys())
    sol_mints_no_gap_create = [m for m in all_sol_mints if mint_info.get(m, {}).get("excluded_gap", 0) != 1]
    sol_mints_strict_no_gap_overlap = [m for m in all_sol_mints if mint_info.get(m, {}).get("excluded_gap", 0) == 0]

    # Wash / bump / bot volume and trade count shares across SOL-quoted trades (excluding gap-created mints)
    total_sol_trades_clean = 0
    total_sol_vol_lamports = 0
    hf_bot_trades = 0
    hf_bot_vol_lamports = 0
    rt60_trades = 0
    rt60_vol_lamports = 0
    union_bot_wash_trades = 0
    union_bot_wash_vol_lamports = 0

    for m in sol_mints_no_gap_create:
        rt_set = roundtrip_60s_by_mint[m]
        for r in trades_by_mint[m]:
            w = r[2]
            lamp = int(r[3] or 0)
            total_sol_trades_clean += 1
            total_sol_vol_lamports += lamp
            in_hf = w in high_freq_bot_wallets
            in_rt = w in rt_set
            if in_hf:
                hf_bot_trades += 1
                hf_bot_vol_lamports += lamp
            if in_rt:
                rt60_trades += 1
                rt60_vol_lamports += lamp
            if in_hf or in_rt:
                union_bot_wash_trades += 1
                union_bot_wash_vol_lamports += lamp

    # Graduation rate within 30 minutes
    graduated_mints_30m = []
    graduated_instant_0_2_slots = []
    graduated_organic_gt_2_slots = []
    graduated_organic_gt_25_slots = []

    for m in sol_mints_no_gap_create:
        c_info = mint_info[m]
        c_bt = c_info["created_bt"]
        c_slot = c_info["created_slot"]
        comp = completions_map.get(m)
        # Also check if any trade hit real_token_reserves == 0 within 1800s
        comp_slot = None
        comp_bt = None
        if comp and (comp["block_time"] - c_bt <= 1800):
            comp_slot = comp["slot"]
            comp_bt = comp["block_time"]
        else:
            for r in trades_by_mint[m]:
                if r[8] is not None and int(r[8]) == 0 and (int(r[10]) - c_bt <= 1800):
                    comp_slot = int(r[9])
                    comp_bt = int(r[10])
                    break
        if comp_slot is not None:
            slot_delay = max(0, comp_slot - c_slot)
            graduated_mints_30m.append((m, slot_delay, max(0, comp_bt - c_bt)))
            if slot_delay <= 2:
                graduated_instant_0_2_slots.append(m)
            else:
                graduated_organic_gt_2_slots.append(m)
            if slot_delay > 25:
                graduated_organic_gt_25_slots.append(m)

    # Horizons: +1m (60s), +2m (120s), +5m (300s), +10m (600s), +30m (1800s)
    horizons_buyers = [60, 120, 300, 600]
    horizons_mc = [60, 120, 300, 600, 1800]

    distinct_clean_buyers_by_h: Dict[int, List[int]] = {h: [] for h in horizons_buyers}
    distinct_all_buyers_by_h: Dict[int, List[int]] = {h: [] for h in horizons_buyers}
    mc_sol_by_h: Dict[int, List[float]] = {h: [] for h in horizons_mc}
    mc_usd_by_h: Dict[int, List[float]] = {h: [] for h in horizons_mc}
    creator_share_by_h: Dict[int, List[float]] = {h: [] for h in horizons_mc}
    top10_share_by_h: Dict[int, List[float]] = {h: [] for h in horizons_mc}
    gates_pass_by_h: Dict[int, Dict[str, int]] = {
        h: {"creator_le_3pct": 0, "top10_le_18pct": 0, "mc_le_16k": 0, "all_three_gates": 0}
        for h in horizons_mc
    }

    for m in sol_mints_no_gap_create:
        c_info = mint_info[m]
        c_bt = c_info["created_bt"]
        creator_wallet = c_info["creator"]
        t_list = trades_by_mint[m]
        rt_set = roundtrip_60s_by_mint[m]

        # Single pass across sorted trades for this mint across horizons
        t_idx = 0
        n_trades = len(t_list)
        all_buyers_seen: Set[str] = set()
        clean_buyers_seen: Set[str] = set()
        wallet_balances: Dict[str, int] = defaultdict(int)
        curr_v_sol = INITIAL_V_SOL
        curr_v_tok = INITIAL_V_TOK

        for h in horizons_mc:
            target_bt = c_bt + h
            while t_idx < n_trades and int(t_list[t_idx][10]) <= target_bt:
                row = t_list[t_idx]
                tx_type = row[1]
                w = row[2]
                tok_u = int(row[4] or 0)
                v_sol_r = row[5]
                v_tok_r = row[6]
                if v_sol_r is not None and v_tok_r is not None and int(v_tok_r) > 0:
                    curr_v_sol = int(v_sol_r)
                    curr_v_tok = int(v_tok_r)
                if tx_type == "buy":
                    all_buyers_seen.add(w)
                    if w not in high_freq_bot_wallets and w not in rt_set:
                        clean_buyers_seen.add(w)
                    wallet_balances[w] += tok_u
                else:
                    wallet_balances[w] = max(0, wallet_balances[w] - tok_u)
                t_idx += 1

            if h in distinct_clean_buyers_by_h:
                distinct_clean_buyers_by_h[h].append(len(clean_buyers_seen))
                distinct_all_buyers_by_h[h].append(len(all_buyers_seen))

            # Market cap at horizon h
            mc_sol = (curr_v_sol / 1e9) * (TOTAL_SUPPLY_BASE_UNITS / max(1, curr_v_tok))
            mc_usd = mc_sol * SOL_PRICE_USD
            mc_sol_by_h[h].append(mc_sol)
            mc_usd_by_h[h].append(mc_usd)

            # Creator share & Top-10 holder share (% of 1B total supply)
            c_bal = max(0, wallet_balances.get(creator_wallet, 0))
            c_pct = 100.0 * c_bal / TOTAL_SUPPLY_BASE_UNITS
            pos_bals = sorted((b for b in wallet_balances.values() if b > 0), reverse=True)
            top10_bal = sum(pos_bals[:10])
            top10_pct = 100.0 * top10_bal / TOTAL_SUPPLY_BASE_UNITS

            creator_share_by_h[h].append(c_pct)
            top10_share_by_h[h].append(top10_pct)

            if c_pct <= 3.0:
                gates_pass_by_h[h]["creator_le_3pct"] += 1
            if top10_pct <= 18.0:
                gates_pass_by_h[h]["top10_le_18pct"] += 1
            if mc_usd <= 16000.0:
                gates_pass_by_h[h]["mc_le_16k"] += 1
            if c_pct <= 3.0 and top10_pct <= 18.0 and mc_usd <= 16000.0:
                gates_pass_by_h[h]["all_three_gates"] += 1

    # Hourly variation (6 one-hour buckets from min_bt)
    hourly_rows = []
    grad_set_30m = {g[0] for g in graduated_mints_30m}
    for hr in range(6):
        h_start = min_bt + hr * 3600
        h_end = min_bt + (hr + 1) * 3600 if hr < 5 else max_bt + 1
        h_creations = [
            m for m, info in mint_info.items()
            if h_start <= info["created_bt"] < h_end and info["excluded_gap"] != 1
        ]
        h_sol_mints = [m for m in h_creations if m in trades_by_mint]
        h_grads = [m for m in h_sol_mints if m in grad_set_30m]
        h_trades = 0
        h_vol_sol = 0.0
        h_bot_wash_trades = 0
        h_clean_buyers_5m = []

        for m in h_sol_mints:
            c_bt = mint_info[m]["created_bt"]
            rt_set = roundtrip_60s_by_mint[m]
            cb_5m: Set[str] = set()
            for r in trades_by_mint[m]:
                h_trades += 1
                h_vol_sol += int(r[3] or 0) / 1e9
                w = r[2]
                if w in high_freq_bot_wallets or w in rt_set:
                    h_bot_wash_trades += 1
                elif r[1] == "buy" and int(r[10]) <= c_bt + 300:
                    cb_5m.add(w)
            h_clean_buyers_5m.append(len(cb_5m))

        hourly_rows.append({
            "hour_index": hr + 1,
            "start_block_time": h_start,
            "end_block_time": h_end,
            "creations_non_gap": len(h_creations),
            "sol_traded_mints": len(h_sol_mints),
            "zero_or_nonsol_mints": len(h_creations) - len(h_sol_mints),
            "sol_trades": h_trades,
            "sol_volume": round(h_vol_sol, 2),
            "graduations_within_30m": len(h_grads),
            "graduation_rate_of_sol_mints_pct": round(100.0 * len(h_grads) / max(1, len(h_sol_mints)), 2),
            "graduation_rate_of_all_creations_pct": round(100.0 * len(h_grads) / max(1, len(h_creations)), 2),
            "bot_or_wash_trade_share_pct": round(100.0 * h_bot_wash_trades / max(1, h_trades), 2),
            "median_clean_buyers_at_5m": round(percentile(sorted(h_clean_buyers_5m), 50), 1),
            "mean_clean_buyers_at_5m": round(sum(h_clean_buyers_5m) / max(1, len(h_clean_buyers_5m)), 2),
        })

    n_sol_cohort = len(sol_mints_no_gap_create)
    n_all_creations_clean = sum(1 for info in mint_info.values() if info["excluded_gap"] != 1)

    report = {
        "cohort_summary": {
            "total_creations_6h": len(mint_info),
            "gap_boundary_excluded_creations": sum(1 for info in mint_info.values() if info["excluded_gap"] == 1),
            "gap_30m_window_overlap_creations": sum(1 for info in mint_info.values() if info["excluded_gap"] == 2),
            "clean_non_gap_boundary_creations": n_all_creations_clean,
            "total_trades_all_quotes": total_all_trades,
            "sol_quoted_trades": sol_trade_count,
            "sol_quoted_trades_share_pct": round(100.0 * sol_trade_count / total_all_trades, 2),
            "non_sol_quoted_trades": nonsol_trade_count,
            "non_sol_quoted_trades_share_pct": round(100.0 * nonsol_trade_count / total_all_trades, 2),
            "distinct_quote_assets": len(quote_rows),
            "sol_quoted_mints_total": len(all_sol_mints),
            "sol_quoted_mints_excluding_gap_creations": n_sol_cohort,
            "sol_quoted_mints_strict_no_gap_overlap": len(sol_mints_strict_no_gap_overlap),
        },
        "graduation_30m": {
            "total_graduated_within_30m": len(graduated_mints_30m),
            "graduation_rate_of_sol_traded_mints_pct": round(100.0 * len(graduated_mints_30m) / n_sol_cohort, 3),
            "graduation_rate_of_all_creations_pct": round(100.0 * len(graduated_mints_30m) / n_all_creations_clean, 3),
            "instant_bundled_0_to_2_slots_count": len(graduated_instant_0_2_slots),
            "organic_gt_2_slots_count": len(graduated_organic_gt_2_slots),
            "organic_gt_25_slots_count": len(graduated_organic_gt_25_slots),
            "graduated_mints_detail": [
                {"mint": m, "slots_to_grad": sl, "seconds_to_grad": sec}
                for m, sl, sec in graduated_mints_30m
            ],
        },
        "wash_and_bot_wallets": {
            "total_distinct_sol_wallets": len(wallet_mints),
            "high_freq_bot_wallets_ge_50_mints_count": len(high_freq_bot_wallets),
            "roundtrip_60s_wallets_count": len(all_roundtrip_wallets),
            "total_sol_trades_analyzed": total_sol_trades_clean,
            "total_sol_volume": round(total_sol_vol_lamports / 1e9, 2),
            "high_freq_bot_trade_share_pct": round(100.0 * hf_bot_trades / total_sol_trades_clean, 2),
            "high_freq_bot_volume_share_pct": round(100.0 * hf_bot_vol_lamports / total_sol_vol_lamports, 2),
            "roundtrip_60s_trade_share_pct": round(100.0 * rt60_trades / total_sol_trades_clean, 2),
            "roundtrip_60s_volume_share_pct": round(100.0 * rt60_vol_lamports / total_sol_vol_lamports, 2),
            "combined_bot_or_wash_trade_share_pct": round(100.0 * union_bot_wash_trades / total_sol_trades_clean, 2),
            "combined_bot_or_wash_volume_share_pct": round(100.0 * union_bot_wash_vol_lamports / total_sol_vol_lamports, 2),
        },
        "distinct_buyers_by_horizon": {
            f"+{h//60}m": {
                "clean_non_bot_buyers": summarize_dist([float(x) for x in distinct_clean_buyers_by_h[h]], 2),
                "all_buyers_unfiltered": summarize_dist([float(x) for x in distinct_all_buyers_by_h[h]], 2),
                "mints_with_clean_buyers_ge_5": sum(1 for x in distinct_clean_buyers_by_h[h] if x >= 5),
                "mints_with_clean_buyers_ge_8": sum(1 for x in distinct_clean_buyers_by_h[h] if x >= 8),
                "mints_with_clean_buyers_ge_10": sum(1 for x in distinct_clean_buyers_by_h[h] if x >= 10),
                "mints_with_clean_buyers_ge_15": sum(1 for x in distinct_clean_buyers_by_h[h] if x >= 15),
                "mints_with_clean_buyers_ge_20": sum(1 for x in distinct_clean_buyers_by_h[h] if x >= 20),
                "mints_with_clean_buyers_ge_30": sum(1 for x in distinct_clean_buyers_by_h[h] if x >= 30),
            }
            for h in horizons_buyers
        },
        "market_cap_paths": {
            f"+{h//60}m": {
                "mc_sol": summarize_dist(mc_sol_by_h[h], 2),
                "mc_usd_at_150_sol": summarize_dist(mc_usd_by_h[h], 2),
            }
            for h in horizons_mc
        },
        "holder_concentration_from_trade_balances": {
            f"+{h//60}m": {
                "creator_share_pct_of_1b": summarize_dist(creator_share_by_h[h], 3),
                "top10_holder_share_pct_of_1b": summarize_dist(top10_share_by_h[h], 3),
                "mints_passing_creator_le_3pct": gates_pass_by_h[h]["creator_le_3pct"],
                "mints_passing_top10_le_18pct": gates_pass_by_h[h]["top10_le_18pct"],
                "mints_passing_mc_le_16k": gates_pass_by_h[h]["mc_le_16k"],
                "mints_passing_all_three_gates": gates_pass_by_h[h]["all_three_gates"],
            }
            for h in horizons_mc
        },
        "hourly_variation": hourly_rows,
    }

    with open("reports/route_a_descriptives.json", "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    # Print verbatim summary tables
    print("=" * 135)
    print("ROUTE A DESCRIPTIVES — 6-HOUR SOL-QUOTED COHORT (Review Item 4)")
    print("=" * 135)
    cs = report["cohort_summary"]
    gr = report["graduation_30m"]
    wb = report["wash_and_bot_wallets"]
    print(
        f"Cohort: {cs['total_creations_6h']} creations ({cs['gap_boundary_excluded_creations']} gap-boundary excluded) | "
        f"SOL-quoted: {cs['sol_quoted_trades']} trades ({cs['sol_quoted_trades_share_pct']}%) across {cs['sol_quoted_mints_excluding_gap_creations']} mints | "
        f"Non-SOL: {cs['non_sol_quoted_trades']} trades ({cs['non_sol_quoted_trades_share_pct']}%) across {cs['distinct_quote_assets'] - 1} non-SOL quote assets"
    )
    print(
        f"Graduation (<=30m): {gr['total_graduated_within_30m']} graduated ({gr['graduation_rate_of_sol_traded_mints_pct']}% of SOL-traded mints, "
        f"{gr['graduation_rate_of_all_creations_pct']}% of all creations) | "
        f"Instant bundled (0-2 slots): {gr['instant_bundled_0_to_2_slots_count']} | "
        f"Organic (>2 slots): {gr['organic_gt_2_slots_count']} (>25 slots: {gr['organic_gt_25_slots_count']})"
    )
    print(
        f"Wash & Bot Shares: Total SOL wallets={wb['total_distinct_sol_wallets']} | "
        f">=50-mint bots={wb['high_freq_bot_wallets_ge_50_mints_count']} wallets ({wb['high_freq_bot_trade_share_pct']}% trades, {wb['high_freq_bot_volume_share_pct']}% SOL vol) | "
        f"<=60s round-trip={wb['roundtrip_60s_wallets_count']} wallets ({wb['roundtrip_60s_trade_share_pct']}% trades, {wb['roundtrip_60s_volume_share_pct']}% SOL vol) | "
        f"Combined bot/wash union={wb['combined_bot_or_wash_trade_share_pct']}% trades, {wb['combined_bot_or_wash_volume_share_pct']}% SOL vol"
    )

    print("\n1. DISTINCT NON-BOT BUYERS (EXCLUDING >=50-MINT BOTS & <=60s ROUND-TRIP WALLETS)")
    print("-" * 135)
    print(f"{'HORIZON':<8} | {'MEDIAN':<7} | {'MEAN':<7} | {'P75':<7} | {'P90':<7} | {'P95':<7} | {'MAX':<7} | {'>=5':<6} | {'>=8':<6} | {'>=10':<6} | {'>=15':<6} | {'>=20':<6} | {'>=30':<6}")
    print("-" * 135)
    for h in horizons_buyers:
        hk = f"+{h//60}m"
        d = report["distinct_buyers_by_horizon"][hk]
        cb = d["clean_non_bot_buyers"]
        print(
            f"{hk:<8} | {cb['median']:<7.1f} | {cb['mean']:<7.2f} | {cb['p75']:<7.1f} | {cb['p90']:<7.1f} | {cb['p95']:<7.1f} | {cb['max']:<7.0f} | "
            f"{d['mints_with_clean_buyers_ge_5']:<6d} | {d['mints_with_clean_buyers_ge_8']:<6d} | {d['mints_with_clean_buyers_ge_10']:<6d} | "
            f"{d['mints_with_clean_buyers_ge_15']:<6d} | {d['mints_with_clean_buyers_ge_20']:<6d} | {d['mints_with_clean_buyers_ge_30']:<6d}"
        )

    print("\n2. MARKET-CAP PATHS (USD AT $150/SOL) & HOLDER CONCENTRATION (% OF 1B TOTAL SUPPLY)")
    print("-" * 135)
    print(
        f"{'HORIZON':<8} | {'MC P25 ($)':<11} | {'MC MED ($)':<11} | {'MC MEAN ($)':<11} | {'MC P90 ($)':<11} | "
        f"{'CREATOR MED%':<12} | {'CREATOR MEAN%':<13} | {'TOP10 MED%':<10} | {'TOP10 MEAN%':<11} | {'PASS ALL 3 GATES'}"
    )
    print("-" * 135)
    for h in horizons_mc:
        hk = f"+{h//60}m"
        mc = report["market_cap_paths"][hk]["mc_usd_at_150_sol"]
        hc = report["holder_concentration_from_trade_balances"][hk]
        cr = hc["creator_share_pct_of_1b"]
        t10 = hc["top10_holder_share_pct_of_1b"]
        print(
            f"{hk:<8} | {mc['p25']:<11.2f} | {mc['median']:<11.2f} | {mc['mean']:<11.2f} | {mc['p90']:<11.2f} | "
            f"{cr['median']:<12.3f} | {cr['mean']:<13.3f} | {t10['median']:<10.3f} | {t10['mean']:<11.3f} | "
            f"{hc['mints_passing_all_three_gates']}/{n_sol_cohort}"
        )

    print("\n3. HOURLY VARIATION ACROSS HOURS 1..6")
    print("-" * 135)
    print(
        f"{'HOUR':<6} | {'CREATIONS':<10} | {'SOL MINTS':<10} | {'SOL TRADES':<11} | {'SOL VOL':<11} | "
        f"{'GRADS (30m)':<12} | {'GRAD % (SOL)':<13} | {'BOT/WASH %':<11} | {'BUYERS@5m (MED/MEAN)'}"
    )
    print("-" * 135)
    for hr in hourly_rows:
        print(
            f"Hour {hr['hour_index']:<1d} | {hr['creations_non_gap']:<10d} | {hr['sol_traded_mints']:<10d} | "
            f"{hr['sol_trades']:<11d} | {hr['sol_volume']:<11.2f} | {hr['graduations_within_30m']:<12d} | "
            f"{hr['graduation_rate_of_sol_mints_pct']:<12.2f}% | {hr['bot_or_wash_trade_share_pct']:<10.2f}% | "
            f"{hr['median_clean_buyers_at_5m']:.1f} / {hr['mean_clean_buyers_at_5m']:.2f}"
        )
    print("=" * 135)
    print("Saved descriptives report to reports/route_a_descriptives.json.")
    conn.close()


if __name__ == "__main__":
    main()

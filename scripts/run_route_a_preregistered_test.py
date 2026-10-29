"""
Evaluate the Pre-Registered Route A Strategy Specification (Review Item 5):
Reads reports/route_a_preregistered_spec_2026_10_28.json (committed BEFORE outcome evaluation):
- SOL-quoted mints only, excluding gap-boundary creations (excluded_gap != 1).
- Train split: First 4 hours of the 6-hour dataset.
- Test split: Last 2 hours of the 6-hour dataset (restricted to mints with full 30m maturity window).
- Evaluates the 5 pre-listed variants on the Train split, selects the single best variant on Train
  according to the pre-registered criterion, and evaluates that chosen variant ONCE on the Test split
  (plus reports full transparency table across horizons 1m, 2m, 5m, 10m, 30m with and without -30% stop-loss,
  at 2-slot and 3-slot latency, and failed-landing rate from S+0 data).
- Reports median, mean, mean excluding top trade, share below -50%, 95% bootstrap CI (10,000 resamples),
  and number of variants tried (5).
"""

from collections import defaultdict
import json
import math
import os
import random
import sqlite3
import sys
from typing import Any, Dict, List, Optional, Set, Tuple

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from src.onchain.trade_collector import WSOL_MINT

TOTAL_SUPPLY_BASE_UNITS = 1_000_000_000_000_000  # 1B tokens * 10^6
INITIAL_V_SOL = 30_000_000_000                   # 30 SOL in lamports
INITIAL_V_TOK = 1_073_000_000_000_000            # 1.073B tokens
GRAD_V_SOL = 115_005_359_056                     # ~115.005 SOL at graduation
GRAD_V_TOK = 279_900_000_000_000                 # 279.9M virtual tokens at graduation
SOL_PRICE_USD = 150.0

FEE_RATE = 0.0125                                # 1.25% each way (100 bps protocol + 25 bps creator)
POSITION_SOL_LAMPORTS = 500_000_000              # 0.50 SOL ($75 at $150/SOL)
TX_FEE_LAMPORTS = 5_000                          # 0.000005 SOL network fee per tx

# Empirical S+0 failure rate (45 / 76 = 59.2105%) and window failure rate (227 / 849 = 26.7373%)
P_FAIL_S0 = 45.0 / 76.0
P_LAND_S0 = 1.0 - P_FAIL_S0
P_FAIL_WINDOW = 227.0 / 849.0
P_LAND_WINDOW = 1.0 - P_FAIL_WINDOW


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


def bootstrap_ci(vals: List[float], n_boot: int = 10000, seed: int = 42) -> Dict[str, Tuple[float, float]]:
    if not vals:
        return {"mean_ci95": (0.0, 0.0), "median_ci95": (0.0, 0.0)}
    if len(vals) == 1:
        v = round(vals[0], 2)
        return {"mean_ci95": (v, v), "median_ci95": (v, v)}
    rng = random.Random(seed)
    n = len(vals)
    boot_means = []
    boot_medians = []
    for _ in range(n_boot):
        sample = [vals[rng.randrange(n)] for _ in range(n)]
        boot_means.append(sum(sample) / n)
        sample.sort()
        boot_medians.append(percentile(sample, 50))
    boot_means.sort()
    boot_medians.sort()
    return {
        "mean_ci95": (round(percentile(boot_means, 2.5), 2), round(percentile(boot_means, 97.5), 2)),
        "median_ci95": (round(percentile(boot_medians, 2.5), 2), round(percentile(boot_medians, 97.5), 2)),
    }


def summarize_returns(rets: List[float], compute_boot: bool = True) -> Dict[str, Any]:
    if not rets:
        return {
            "n_trades": 0,
            "median_pct": 0.0,
            "mean_pct": 0.0,
            "mean_ex_top_pct": 0.0,
            "share_below_minus_50pct": 0.0,
            "win_rate_pct": 0.0,
            "min_pct": 0.0,
            "max_pct": 0.0,
            "mean_ci95": [0.0, 0.0],
            "median_ci95": [0.0, 0.0],
            "s0_landing_adjusted_expected_mean_pct": 0.0,
        }
    s = sorted(rets)
    n = len(s)
    med = percentile(s, 50)
    mean_all = sum(s) / n
    mean_ex_top = (sum(s[:-1]) / (n - 1)) if n > 1 else mean_all
    below_m50 = 100.0 * sum(1 for x in s if x < -50.0) / n
    win_rate = 100.0 * sum(1 for x in s if x > 0.0) / n
    ci = bootstrap_ci(rets, n_boot=10000, seed=42) if compute_boot else {"mean_ci95": (0.0, 0.0), "median_ci95": (0.0, 0.0)}
    failed_attempt_ret_pct = -100.0 * TX_FEE_LAMPORTS / (POSITION_SOL_LAMPORTS + TX_FEE_LAMPORTS)
    exp_s0_mean = P_LAND_S0 * mean_all + P_FAIL_S0 * failed_attempt_ret_pct

    return {
        "n_trades": n,
        "median_pct": round(med, 2),
        "mean_pct": round(mean_all, 2),
        "mean_ex_top_pct": round(mean_ex_top, 2),
        "share_below_minus_50pct": round(below_m50, 2),
        "win_rate_pct": round(win_rate, 2),
        "min_pct": round(s[0], 2),
        "max_pct": round(s[-1], 2),
        "mean_ci95": list(ci["mean_ci95"]),
        "median_ci95": list(ci["median_ci95"]),
        "s0_landing_adjusted_expected_mean_pct": round(exp_s0_mean, 2),
    }


def compute_exit_return_pct(
    tokens_bought: int,
    eff_sol_in: float,
    v_sol_state: int,
    v_tok_state: int,
) -> float:
    """
    Compute net return (%) when selling tokens_bought into the bonding curve at reserve state (v_sol_state, v_tok_state),
    accounting for our own position's presence on the curve and the 1.25% exit fee + network tx fee.
    """
    v_sol_with_pos = min(GRAD_V_SOL, int(v_sol_state + eff_sol_in))
    v_tok_with_pos = max(GRAD_V_TOK, int(v_tok_state - tokens_bought))
    gross_sol_out = (v_sol_with_pos * tokens_bought) / (v_tok_with_pos + tokens_bought)
    net_sol_out = gross_sol_out * (1.0 - FEE_RATE) - TX_FEE_LAMPORTS
    total_cost = POSITION_SOL_LAMPORTS + TX_FEE_LAMPORTS
    return 100.0 * (net_sol_out - total_cost) / total_cost


def simulate_single_mint_trade(
    t_list: List[Tuple],
    created_bt: int,
    creator_wallet: str,
    high_freq_bots: Set[str],
    eval_time_sec: int,
    min_clean_buyers_N: int,
    creator_max_pct: float,
    top10_max_pct: float,
    mc_max_usd: float,
    latency_slots: int,
    horizons_sec: List[int],
    stop_loss_pct: float = -30.0,
) -> Optional[Dict[str, Any]]:
    """
    Check if a mint passes all 4 entry gates at created_bt + eval_time_sec.
    If it passes, simulate entry at trigger_slot + latency_slots and compute returns across all horizons
    (both pure fixed-horizon and with -30% stop-loss).
    """
    eval_bt = created_bt + eval_time_sec
    n_trades = len(t_list)

    # Identify causal round-trip wallets up to eval_bt (buy and sell within 60s up to eval_bt)
    buy_times: Dict[str, List[int]] = defaultdict(list)
    sell_times: Dict[str, List[int]] = defaultdict(list)
    wallet_bals: Dict[str, int] = defaultdict(int)
    curr_v_sol = INITIAL_V_SOL
    curr_v_tok = INITIAL_V_TOK
    curr_r_tok = 793_100_000_000_000
    last_eval_idx = -1

    for idx, row in enumerate(t_list):
        bt = int(row[10])
        if bt > eval_bt:
            break
        last_eval_idx = idx
        tx_type = row[1]
        w = row[2]
        tok_u = int(row[4] or 0)
        if row[5] is not None and row[6] is not None and int(row[6]) > 0:
            curr_v_sol = int(row[5])
            curr_v_tok = int(row[6])
            curr_r_tok = int(row[8] if row[8] is not None else curr_r_tok)
        if tx_type == "buy":
            buy_times[w].append(bt)
            wallet_bals[w] += tok_u
        else:
            sell_times[w].append(bt)
            wallet_bals[w] = max(0, wallet_bals[w] - tok_u)

    if last_eval_idx < 0:
        return None

    # Causal round-trip check up to eval_bt
    rt_wallets_at_eval: Set[str] = set()
    for w, b_list in buy_times.items():
        s_list = sell_times.get(w)
        if not s_list:
            continue
        for b_t in b_list:
            if any(abs(s_t - b_t) <= 60 for s_t in s_list):
                rt_wallets_at_eval.add(w)
                break

    clean_buyers = {
        w for w in buy_times.keys()
        if w not in high_freq_bots and w not in rt_wallets_at_eval
    }
    if len(clean_buyers) < min_clean_buyers_N:
        return None

    # Gate 2: Creator share <= 3.0%
    creator_bal = max(0, wallet_bals.get(creator_wallet, 0))
    creator_pct = 100.0 * creator_bal / TOTAL_SUPPLY_BASE_UNITS
    if creator_pct > creator_max_pct:
        return None

    # Gate 3: Top-10 holder share <= 18.0%
    pos_bals = sorted((b for b in wallet_bals.values() if b > 0), reverse=True)
    top10_pct = 100.0 * sum(pos_bals[:10]) / TOTAL_SUPPLY_BASE_UNITS
    if top10_pct > top10_max_pct:
        return None

    # Gate 4: Market cap <= $16,000
    mc_sol = (curr_v_sol / 1e9) * (TOTAL_SUPPLY_BASE_UNITS / max(1, curr_v_tok))
    mc_usd = mc_sol * SOL_PRICE_USD
    if mc_usd > mc_max_usd:
        return None

    # Triggered! Find entry state at trigger_slot + latency_slots
    trigger_slot = int(t_list[last_eval_idx][9])
    entry_target_slot = trigger_slot + latency_slots

    entry_idx = last_eval_idx
    while entry_idx + 1 < n_trades and int(t_list[entry_idx + 1][9]) <= entry_target_slot:
        entry_idx += 1

    entry_row = t_list[entry_idx]
    v_sol_entry = int(entry_row[5] or INITIAL_V_SOL)
    v_tok_entry = int(entry_row[6] or INITIAL_V_TOK)
    r_tok_entry = int(entry_row[8]) if entry_row[8] is not None else 793_100_000_000_000
    entry_bt = max(eval_bt, int(entry_row[10]))

    # If bonding curve already graduated at or before entry_target_slot, cannot enter on curve
    if r_tok_entry <= 0:
        return None

    eff_sol_in = POSITION_SOL_LAMPORTS * (1.0 - FEE_RATE)
    tokens_bought = int((v_tok_entry * eff_sol_in) / (v_sol_entry + eff_sol_in))
    if tokens_bought <= 0:
        return None

    # Evaluate exits across all horizons [60, 120, 300, 600, 1800]
    fixed_returns: Dict[str, float] = {}
    sl_returns: Dict[str, float] = {}

    for h_sec in horizons_sec:
        h_label = f"{h_sec // 60}m"
        exit_target_bt = entry_bt + h_sec

        # Walk forward from entry_idx + 1 up to exit_target_bt
        curr_idx = entry_idx
        sl_triggered_ret: Optional[float] = None

        for j in range(entry_idx + 1, n_trades):
            r_j = t_list[j]
            bt_j = int(r_j[10])
            if bt_j > exit_target_bt:
                break
            curr_idx = j
            if sl_triggered_ret is None:
                v_s_j = int(r_j[5] or v_sol_entry)
                v_t_j = int(r_j[6] or v_tok_entry)
                mtm_ret = compute_exit_return_pct(tokens_bought, eff_sol_in, v_s_j, v_t_j)
                if mtm_ret <= stop_loss_pct:
                    # Stop-loss triggered at slot of r_j; execute exit at stop_slot + latency_slots
                    stop_slot = int(r_j[9]) + latency_slots
                    sl_idx = j
                    while sl_idx + 1 < n_trades and int(t_list[sl_idx + 1][9]) <= stop_slot:
                        sl_idx += 1
                    r_sl = t_list[sl_idx]
                    sl_triggered_ret = compute_exit_return_pct(
                        tokens_bought,
                        eff_sol_in,
                        int(r_sl[5] or v_s_j),
                        int(r_sl[6] or v_t_j),
                    )

        r_exit = t_list[curr_idx]
        fixed_ret = compute_exit_return_pct(
            tokens_bought,
            eff_sol_in,
            int(r_exit[5] or v_sol_entry),
            int(r_exit[6] or v_tok_entry),
        )
        fixed_returns[h_label] = fixed_ret
        sl_returns[h_label] = sl_triggered_ret if sl_triggered_ret is not None else fixed_ret

    return {
        "trigger_slot": trigger_slot,
        "entry_slot": entry_target_slot,
        "entry_bt": entry_bt,
        "clean_buyers_at_eval": len(clean_buyers),
        "creator_pct_at_eval": round(creator_pct, 3),
        "top10_pct_at_eval": round(top10_pct, 3),
        "mc_usd_at_eval": round(mc_usd, 2),
        "fixed_returns": fixed_returns,
        "stop_loss_returns": sl_returns,
    }


def main():
    with open("reports/route_a_preregistered_spec_2026_10_28.json", "r", encoding="utf-8") as f:
        spec = json.load(f)

    conn = sqlite3.connect("data/curve_trades.db")
    cur = conn.cursor()

    cur.execute("""
        SELECT mint, creator, slot, created_block_time, excluded_gap
        FROM curve_creations
        ORDER BY created_block_time ASC, slot ASC
    """)
    creations = cur.fetchall()
    min_bt = int(creations[0][3])
    max_bt = int(creations[-1][3])
    split_4h_bt = min_bt + 14400
    max_mature_test_bt = max_bt - 1800

    mint_info = {
        m: {
            "mint": m,
            "creator": creator,
            "created_slot": int(slot),
            "created_bt": int(c_bt),
            "excluded_gap": int(excl_gap),
        }
        for m, creator, slot, c_bt, excl_gap in creations
    }

    # Load all SOL-quoted trades
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
    sol_trades = cur.fetchall()

    trades_by_mint: Dict[str, List[Tuple]] = defaultdict(list)
    wallet_mints_train: Dict[str, Set[str]] = defaultdict(set)
    wallet_mints_all: Dict[str, Set[str]] = defaultdict(set)

    for row in sol_trades:
        m = row[0]
        w = row[2]
        bt = int(row[10])
        trades_by_mint[m].append(row)
        wallet_mints_all[w].add(m)
        if bt < split_4h_bt:
            wallet_mints_train[w].add(m)

    high_freq_bots_all = {w for w, ms in wallet_mints_all.items() if len(ms) >= 50}

    # Partition SOL-quoted mints (excluding gap boundary creations excluded_gap == 1) into Train (first 4h) and Test (last 2h mature)
    train_mints = [
        m for m in sorted(trades_by_mint.keys())
        if mint_info[m]["excluded_gap"] != 1 and min_bt <= mint_info[m]["created_bt"] < split_4h_bt
    ]
    test_mints = [
        m for m in sorted(trades_by_mint.keys())
        if mint_info[m]["excluded_gap"] != 1 and split_4h_bt <= mint_info[m]["created_bt"] <= max_mature_test_bt
    ]

    horizons_sec = spec["exit_rules"]["fixed_horizons_seconds"]
    variants = spec["pre_listed_variants_max_5"]

    print("=" * 155)
    print("PRE-REGISTERED ROUTE A STRATEGY EVALUATION (Review Item 5)")
    print("=" * 155)
    print(
        f"Dataset Split: Train (Hours 1-4) = {len(train_mints)} SOL-quoted mints | "
        f"Out-of-Sample Test (Hours 5-6 mature) = {len(test_mints)} SOL-quoted mints | "
        f"Variants Tried = {len(variants)} (max allowed = 5)"
    )

    def evaluate_variant_on_split(v: Dict[str, Any], mint_list: List[str], latency_slots: int) -> Dict[str, Any]:
        trades_sim = []
        for m in mint_list:
            info = mint_info[m]
            sim = simulate_single_mint_trade(
                t_list=trades_by_mint[m],
                created_bt=info["created_bt"],
                creator_wallet=info["creator"],
                high_freq_bots=high_freq_bots_all,
                eval_time_sec=v["eval_time_sec"],
                min_clean_buyers_N=v["min_clean_buyers_N"],
                creator_max_pct=v["creator_max_pct"],
                top10_max_pct=v["top10_max_pct"],
                mc_max_usd=v["mc_max_usd"],
                latency_slots=latency_slots,
                horizons_sec=horizons_sec,
                stop_loss_pct=-30.0,
            )
            if sim is not None:
                sim["mint"] = m
                trades_sim.append(sim)

        by_horizon_fixed = {}
        by_horizon_sl = {}
        for h_sec in horizons_sec:
            hl = f"{h_sec // 60}m"
            f_rets = [t["fixed_returns"][hl] for t in trades_sim]
            s_rets = [t["stop_loss_returns"][hl] for t in trades_sim]
            by_horizon_fixed[hl] = summarize_returns(f_rets, compute_boot=True)
            by_horizon_sl[hl] = summarize_returns(s_rets, compute_boot=True)

        return {
            "variant_id": v["variant_id"],
            "latency_slots": latency_slots,
            "n_trades": len(trades_sim),
            "fixed_horizons": by_horizon_fixed,
            "with_minus_30pct_stop_loss": by_horizon_sl,
            "sample_trades": trades_sim[:10],
        }

    # 1. Evaluate all 5 pre-listed variants on the 4-Hour Train Split (2-slot latency)
    print("\n1. TRAIN SPLIT (FIRST 4 HOURS) — ALL 5 PRE-LISTED VARIANTS (2-SLOT LATENCY, 5m EXIT WITH -30% STOP-LOSS)")
    print("-" * 155)
    print(
        f"{'VARIANT':<15} | {'RULE':<22} | {'N_TRADES':<8} | {'MEDIAN %':<9} | {'MEAN %':<8} | "
        f"{'MEAN EX-TOP %':<13} | {'<-50% SHARE':<11} | {'95% BOOT CI (MEAN)':<22} | {'95% BOOT CI (MEDIAN)':<22} | {'S+0 LAND ADJ %'}"
    )
    print("-" * 155)

    train_results_2slot = {}
    for v in variants:
        res = evaluate_variant_on_split(v, train_mints, latency_slots=2)
        train_results_2slot[v["variant_id"]] = res
        m5 = res["with_minus_30pct_stop_loss"]["5m"]
        rule_str = f"t={v['eval_time_sec']}s, N>={v['min_clean_buyers_N']}"
        print(
            f"{v['variant_id']:<15} | {rule_str:<22} | {m5['n_trades']:<8d} | {m5['median_pct']:<+9.2f} | "
            f"{m5['mean_pct']:<+8.2f} | {m5['mean_ex_top_pct']:<+13.2f} | {m5['share_below_minus_50pct']:<10.2f}% | "
            f"[{m5['mean_ci95'][0]:+6.2f}%, {m5['mean_ci95'][1]:+6.2f}%]   | "
            f"[{m5['median_ci95'][0]:+6.2f}%, {m5['median_ci95'][1]:+6.2f}%]   | {m5['s0_landing_adjusted_expected_mean_pct']:+6.2f}%"
        )

    # Select best variant on Train according to pre-registered criterion:
    # Highest mean_ex_top_pct at 5m with -30% stop-loss among variants with >= 10 train trades (or highest sample size if <10)
    eligible_variants = [v for v in variants if train_results_2slot[v["variant_id"]]["n_trades"] >= 10]
    if eligible_variants:
        chosen_variant = max(
            eligible_variants,
            key=lambda v: train_results_2slot[v["variant_id"]]["with_minus_30pct_stop_loss"]["5m"]["mean_ex_top_pct"],
        )
    else:
        chosen_variant = max(variants, key=lambda v: train_results_2slot[v["variant_id"]]["n_trades"])

    chosen_id = chosen_variant["variant_id"]
    print("-" * 155)
    print(f"SELECTED VARIANT FROM 4-HOUR TRAIN SPLIT: {chosen_id} ({chosen_variant['description']})")

    # 2. Evaluate the chosen variant ONCE on the Out-of-Sample Test Split (Last 2 Hours) at 2-slot and 3-slot latency
    test_res_2slot = evaluate_variant_on_split(chosen_variant, test_mints, latency_slots=2)
    test_res_3slot = evaluate_variant_on_split(chosen_variant, test_mints, latency_slots=3)
    train_res_3slot = evaluate_variant_on_split(chosen_variant, train_mints, latency_slots=3)

    print(f"\n2. OUT-OF-SAMPLE TEST SPLIT (LAST 2 HOURS) — SELECTED VARIANT {chosen_id} ACROSS ALL HORIZONS (2-SLOT & 3-SLOT LATENCY)")
    print("-" * 155)
    print(
        f"{'EXIT MODE':<22} | {'HORIZON':<7} | {'LATENCY':<7} | {'N':<4} | {'MEDIAN %':<9} | {'MEAN %':<8} | "
        f"{'MEAN EX-TOP %':<13} | {'<-50% SHARE':<11} | {'95% BOOT CI (MEAN)':<22} | {'95% BOOT CI (MEDIAN)':<22} | {'S+0 EXP %'}"
    )
    print("-" * 155)

    for lat_label, t_res in [("2 slots", test_res_2slot), ("3 slots", test_res_3slot)]:
        for mode_label, mode_key in [("Fixed + StopLoss(-30%)", "with_minus_30pct_stop_loss"), ("Pure Fixed Horizon", "fixed_horizons")]:
            for h_sec in horizons_sec:
                hl = f"{h_sec // 60}m"
                m_stat = t_res[mode_key][hl]
                print(
                    f"{mode_label:<22} | {hl:<7} | {lat_label:<7} | {m_stat['n_trades']:<4d} | {m_stat['median_pct']:<+9.2f} | "
                    f"{m_stat['mean_pct']:<+8.2f} | {m_stat['mean_ex_top_pct']:<+13.2f} | {m_stat['share_below_minus_50pct']:<10.2f}% | "
                    f"[{m_stat['mean_ci95'][0]:+6.2f}%, {m_stat['mean_ci95'][1]:+6.2f}%]   | "
                    f"[{m_stat['median_ci95'][0]:+6.2f}%, {m_stat['median_ci95'][1]:+6.2f}%]   | {m_stat['s0_landing_adjusted_expected_mean_pct']:+6.2f}%"
                )
        print("-" * 155)

    output = {
        "spec_id": spec["spec_id"],
        "preregistered_git_commit": "111b2ee",
        "variants_tried_count": len(variants),
        "max_variants_allowed": 5,
        "dataset_splits": {
            "min_block_time": min_bt,
            "split_4h_block_time": split_4h_bt,
            "max_mature_test_block_time": max_mature_test_bt,
            "max_block_time": max_bt,
            "train_sol_mints_count": len(train_mints),
            "test_sol_mints_count": len(test_mints),
        },
        "failed_landing_rates_applied": {
            "s0_failure_rate": round(P_FAIL_S0, 4),
            "s0_landing_rate": round(P_LAND_S0, 4),
            "window_failure_rate": round(P_FAIL_WINDOW, 4),
            "window_landing_rate": round(P_LAND_WINDOW, 4),
        },
        "train_split_all_5_variants_2slot": train_results_2slot,
        "selected_variant_id": chosen_id,
        "selected_variant_spec": chosen_variant,
        "selected_variant_train_3slot": train_res_3slot,
        "out_of_sample_test_2slot": test_res_2slot,
        "out_of_sample_test_3slot": test_res_3slot,
    }
    with open("reports/route_a_preregistered_results.json", "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2)
    print("Saved pre-registered evaluation results to reports/route_a_preregistered_results.json.")
    conn.close()


if __name__ == "__main__":
    main()

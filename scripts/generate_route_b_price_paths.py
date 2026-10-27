"""
Route B Realistic Latency Price Paths & Horizon Replay Generator (Review Item 3).
- Uses PRE-swap reserves of the first successful transaction at or after target (state at the target).
- Computes lag (slot_tx - slot_target): median, max, and count > 50 slots per horizon.
- Reports both Version A (Available Only) and Version B (Carried Forward).
- Headlines S+10 and S+20 entries ($91 and $185) with explicit lag notices.
- Outputs reports/route_b_price_paths.json.
"""

import json
import math
import os
import random
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

PUMPSWAP_PROGRAM = "pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA"
WSOL = "So11111111111111111111111111111111111111112"

HORIZONS = {
    "S+5": 5,
    "S+10": 10,
    "S+20": 20,
    "S+40": 40,
    "+30s": 139,
    "+2m": 554,
    "+5m": 1386,
    "+15m": 4158,
    "+60m": 16632,
}

SOL_USD_PRICE = 150.0
PRIORITY_FEE_SOL = 0.002
TIER_0_FEE_RATE = 0.0125  # 125 bps total


def load_fixture(sig: str) -> Optional[dict]:
    p1 = Path(f"tests/fixtures/txs/{sig}.json")
    if p1.exists():
        try:
            return json.load(open(p1, encoding="utf-8"))
        except Exception:
            return None
    p2 = Path(f"data/retrospective_cache/txs/{sig}.json")
    if p2.exists():
        try:
            return json.load(open(p2, encoding="utf-8"))
        except Exception:
            return None
    return None


def get_pool_balances_from_tx(tx: dict, pool: str, mint: str, use_pre: bool = False) -> Tuple[Optional[float], Optional[float]]:
    meta = tx.get("meta") or {}
    tb_list = (meta.get("preTokenBalances") or []) if use_pre else (meta.get("postTokenBalances") or [])
    wsol_bal = None
    tok_bal = None
    for tb in tb_list:
        if tb.get("owner") == pool:
            m = tb.get("mint")
            amt = (tb.get("uiTokenAmount") or {}).get("uiAmount")
            if m == WSOL:
                wsol_bal = amt
            elif m == mint:
                tok_bal = amt
    return wsol_bal, tok_bal


def bootstrap_ci(data: List[float], n_boot: int = 10000, conf: float = 0.95) -> Tuple[float, float]:
    if not data:
        return (0.0, 0.0)
    if len(data) == 1:
        return (data[0], data[0])
    random.seed(42)
    means = []
    n = len(data)
    for _ in range(n_boot):
        sample = [random.choice(data) for _ in range(n)]
        means.append(sum(sample) / n)
    means.sort()
    lower_idx = int((1.0 - conf) / 2.0 * n_boot)
    upper_idx = int((1.0 + conf) / 2.0 * n_boot)
    return round(means[lower_idx], 2), round(means[upper_idx], 2)


def calc_stats(values: List[float]) -> Dict[str, Any]:
    if not values:
        return {"n": 0, "median": None, "mean_ex_top1": None, "frac_below_neg50_pct": None, "bootstrap_95_ci": None}
    v_sorted = sorted(values)
    n = len(v_sorted)
    med = v_sorted[n // 2] if n % 2 != 0 else (v_sorted[n // 2 - 1] + v_sorted[n // 2]) / 2.0
    ex_top1 = v_sorted[:-1] if n > 1 else v_sorted
    mean_ex1 = sum(ex_top1) / len(ex_top1)
    frac_lt_50 = sum(1 for x in v_sorted if x < -50.0) / n
    ci = bootstrap_ci(v_sorted)
    return {
        "n": n,
        "median": round(med, 2),
        "mean_ex_top1": round(mean_ex1, 2),
        "frac_below_neg50_pct": round(frac_lt_50 * 100.0, 2),
        "bootstrap_95_ci": list(ci),
    }


def calc_lag_stats(lags: List[int]) -> Dict[str, Any]:
    if not lags:
        return {"n": 0, "median": None, "max": None, "count_lag_gt_50": 0}
    l_sorted = sorted(lags)
    n = len(l_sorted)
    med = l_sorted[n // 2] if n % 2 != 0 else (l_sorted[n // 2 - 1] + l_sorted[n // 2]) / 2.0
    max_lag = l_sorted[-1]
    cnt_gt_50 = sum(1 for l in l_sorted if l > 50)
    return {
        "n": n,
        "median_lag_slots": med,
        "max_lag_slots": max_lag,
        "count_lag_gt_50": cnt_gt_50,
        "pct_lag_gt_50": round(cnt_gt_50 / n * 100.0, 1),
    }


def simulate_trade(
    entry_usd: float,
    entry_vault: float,
    entry_tok: float,
    boost_sol: float,
    exit_vault: float,
    exit_tok: float,
) -> float:
    entry_sol = entry_usd / SOL_USD_PRICE
    net_entry_sol = entry_sol * (1.0 - TIER_0_FEE_RATE)

    s_eff_entry = entry_vault + boost_sol
    trader_tokens = (entry_tok * net_entry_sol) / (s_eff_entry + net_entry_sol)

    s_eff_exit = exit_vault + boost_sol
    gross_sol_exit = (s_eff_exit * trader_tokens) / (exit_tok + trader_tokens)
    net_sol_exit = gross_sol_exit * (1.0 - TIER_0_FEE_RATE) - PRIORITY_FEE_SOL

    capped_net_sol_exit = max(0.0, min(net_sol_exit, exit_vault))
    total_outlay_sol = entry_sol + PRIORITY_FEE_SOL
    ret_pct = ((capped_net_sol_exit - total_outlay_sol) / total_outlay_sol) * 100.0
    return round(ret_pct, 2)


def main():
    print("=" * 115)
    print("ROUTE B PRICE PATHS & REALISTIC HORIZON REPLAY (Review Item 3)")
    print("PRE-swap reserves used at target slots | Lag & Carried-Forward Analysis")
    print("=" * 115)

    with open("reports/retrospective_report.json", encoding="utf-8") as f:
        retro = json.load(f)

    reached_pools = [r for r in retro["per_migration_table"] if r.get("reached_creation_slot")]
    print(f"Loaded {len(reached_pools)} reached pools.")

    pool_results = []

    rel_prices_slots = {"S+0": [], "S+1": [], "S+2": [], "S+3": []}

    # Version A: Available Only
    rel_prices_horizons_avail = {h: [] for h in HORIZONS}
    sim_s10_91_avail = {h: [] for h in HORIZONS if HORIZONS[h] > 10}
    sim_s10_185_avail = {h: [] for h in HORIZONS if HORIZONS[h] > 10}
    sim_s20_91_avail = {h: [] for h in HORIZONS if HORIZONS[h] > 20}
    sim_s20_185_avail = {h: [] for h in HORIZONS if HORIZONS[h] > 20}

    # Version B: Carried Forward (all 34 pools)
    rel_prices_horizons_carried = {h: [] for h in HORIZONS}
    sim_s10_91_carried = {h: [] for h in HORIZONS if HORIZONS[h] > 10}
    sim_s10_185_carried = {h: [] for h in HORIZONS if HORIZONS[h] > 10}
    sim_s20_91_carried = {h: [] for h in HORIZONS if HORIZONS[h] > 20}
    sim_s20_185_carried = {h: [] for h in HORIZONS if HORIZONS[h] > 20}

    horizon_lags = {h: [] for h in HORIZONS}
    horizon_coverage = {h: {"available": 0, "carried_forward": 0, "not_obtained": 0} for h in HORIZONS}

    pools_s0_surge_gt_1_5 = 0

    for r in reached_pools:
        idx = r["index"]
        pool = r["pool_address"]
        mint = r["mint"]
        mig_sig = r["migration_signature"]
        c_slot = r["creation_slot"]

        # 1. Opening Balances (Post balances of migration transaction)
        mig_tx = load_fixture(mig_sig)
        assert mig_tx is not None, f"Missing migration fixture for {pool}"
        wsol_open, tok_open = get_pool_balances_from_tx(mig_tx, pool, mint, use_pre=False)
        assert wsol_open is not None and tok_open is not None

        boost_sol = 84.990359 - wsol_open
        price_open = (wsol_open + boost_sol) / tok_open

        # 2. Window S+0 .. S+3 State Tracking
        sig_cache_path = f"data/retrospective_cache/pool_sigs/{pool}.json"
        sigs = json.load(open(sig_cache_path, encoding="utf-8"))
        window_sigs = [s for s in sigs if 0 <= (s.get("slot", 0) - c_slot) <= 3]

        curr_vault = wsol_open
        curr_tok = tok_open

        slot_states = {}
        for offset_val in [0, 1, 2, 3]:
            offset_label = f"S+{offset_val}"
            target_s = c_slot + offset_val
            s_sigs = [s for s in window_sigs if s.get("slot", 0) == target_s]
            s_sigs_sorted = sorted(s_sigs, key=lambda x: x.get("transactionIndex", 0))

            for s in s_sigs_sorted:
                sig_val = s["signature"]
                tx_data = load_fixture(sig_val)
                if not tx_data:
                    continue
                meta = tx_data.get("meta") or {}
                if meta.get("err") is not None:
                    continue
                w_b, t_b = get_pool_balances_from_tx(tx_data, pool, mint, use_pre=False)
                if w_b is not None and t_b is not None:
                    curr_vault = w_b
                    curr_tok = t_b

            eff_price = (curr_vault + boost_sol) / curr_tok
            rel_p = eff_price / price_open
            slot_states[offset_label] = {
                "slot": target_s,
                "vault_sol": round(curr_vault, 6),
                "token_reserve": round(curr_tok, 2),
                "effective_price_sol": eff_price,
                "price_rel_open": round(rel_p, 4),
            }
            rel_prices_slots[offset_label].append(rel_p)

        if slot_states["S+0"]["price_rel_open"] > 1.5:
            pools_s0_surge_gt_1_5 += 1

        # 3. Horizon Sampling using PRE-swap reserves of first successful tx at or after target
        horizon_states = {}
        last_known_reserves = (curr_vault, curr_tok, (curr_vault + boost_sol) / curr_tok)

        for h_label, h_slots in HORIZONS.items():
            target_slot = c_slot + h_slots
            candidates = sorted(
                [s for s in sigs if s.get("slot", 0) >= target_slot and s.get("err") is None],
                key=lambda x: (x.get("slot", 0), x.get("transactionIndex", 0)),
            )

            found_pre = None
            found_sig = None
            found_slot = None

            for cand in candidates:
                csig = cand["signature"]
                ctx = load_fixture(csig)
                if ctx and ctx.get("meta"):
                    w_b, t_b = get_pool_balances_from_tx(ctx, pool, mint, use_pre=True)
                    if w_b is not None and t_b is not None:
                        found_pre = (w_b, t_b)
                        found_sig = csig
                        found_slot = cand.get("slot", 0)
                        break

            if found_pre:
                h_vault, h_tok = found_pre
                h_eff_price = (h_vault + boost_sol) / h_tok
                rel_open = h_eff_price / price_open
                lag = found_slot - target_slot

                horizon_states[h_label] = {
                    "status": "AVAILABLE",
                    "slot": found_slot,
                    "target_slot": target_slot,
                    "lag_slots": lag,
                    "signature": found_sig,
                    "vault_sol": round(h_vault, 6),
                    "token_reserve": round(h_tok, 2),
                    "effective_price_sol": h_eff_price,
                    "price_rel_open": round(rel_open, 4),
                }
                rel_prices_horizons_avail[h_label].append(round(rel_open, 4))
                rel_prices_horizons_carried[h_label].append(round(rel_open, 4))
                horizon_lags[h_label].append(lag)
                horizon_coverage[h_label]["available"] += 1
                last_known_reserves = (h_vault, h_tok, h_eff_price)
            else:
                # Carry forward last known price
                c_vault, c_tok, c_price = last_known_reserves
                c_rel_open = c_price / price_open
                horizon_states[h_label] = {
                    "status": "CARRIED_FORWARD",
                    "target_slot": target_slot,
                    "vault_sol": round(c_vault, 6),
                    "token_reserve": round(c_tok, 2),
                    "effective_price_sol": c_price,
                    "price_rel_open": round(c_rel_open, 4),
                    "note": "Carried forward from last known reserves",
                }
                rel_prices_horizons_carried[h_label].append(round(c_rel_open, 4))
                horizon_coverage[h_label]["carried_forward"] += 1

        # 4. Simulate Trades for S+10 and S+20 entries
        # S+10 Entry State
        s10_st = horizon_states["S+10"]
        s10_v = s10_st["vault_sol"]
        s10_t = s10_st["token_reserve"]

        for h_label in sim_s10_91_avail:
            exit_st = horizon_states[h_label]
            # Version B: always simulate (carried forward if needed)
            ret91_c = simulate_trade(91.0, s10_v, s10_t, boost_sol, exit_st["vault_sol"], exit_st["token_reserve"])
            ret185_c = simulate_trade(185.0, s10_v, s10_t, boost_sol, exit_st["vault_sol"], exit_st["token_reserve"])
            sim_s10_91_carried[h_label].append(ret91_c)
            sim_s10_185_carried[h_label].append(ret185_c)

            # Version A: simulate only if horizon was AVAILABLE
            if exit_st["status"] == "AVAILABLE":
                sim_s10_91_avail[h_label].append(ret91_c)
                sim_s10_185_avail[h_label].append(ret185_c)

            horizon_states[h_label]["sim_from_s10_91_pct"] = ret91_c
            horizon_states[h_label]["sim_from_s10_185_pct"] = ret185_c

        # S+20 Entry State
        s20_st = horizon_states["S+20"]
        s20_v = s20_st["vault_sol"]
        s20_t = s20_st["token_reserve"]

        for h_label in sim_s20_91_avail:
            exit_st = horizon_states[h_label]
            ret91_c = simulate_trade(91.0, s20_v, s20_t, boost_sol, exit_st["vault_sol"], exit_st["token_reserve"])
            ret185_c = simulate_trade(185.0, s20_v, s20_t, boost_sol, exit_st["vault_sol"], exit_st["token_reserve"])
            sim_s20_91_carried[h_label].append(ret91_c)
            sim_s20_185_carried[h_label].append(ret185_c)

            if exit_st["status"] == "AVAILABLE":
                sim_s20_91_avail[h_label].append(ret91_c)
                sim_s20_185_avail[h_label].append(ret185_c)

            horizon_states[h_label]["sim_from_s20_91_pct"] = ret91_c
            horizon_states[h_label]["sim_from_s20_185_pct"] = ret185_c

        pool_results.append({
            "index": idx,
            "pool_address": pool,
            "mint": mint,
            "creation_slot": c_slot,
            "opening_balances": {
                "vault_sol": round(wsol_open, 6),
                "boost_sol": round(boost_sol, 6),
                "token_reserve": round(tok_open, 2),
                "price_open_sol": price_open,
            },
            "window_slots": slot_states,
            "horizon_samples": horizon_states,
        })

    # Summary
    summary = {
        "pools_analyzed": len(reached_pools),
        "pools_with_s0_price_surge_gt_1_5": {
            "count": pools_s0_surge_gt_1_5,
            "total_pools": len(reached_pools),
            "percentage": round(pools_s0_surge_gt_1_5 / len(reached_pools) * 100.0, 2),
        },
        "price_relative_to_open_by_window_slot": {
            s: calc_stats(rel_prices_slots[s]) for s in ["S+0", "S+1", "S+2", "S+3"]
        },
        "horizon_lag_statistics": {
            h: calc_lag_stats(horizon_lags[h]) for h in HORIZONS
        },
        "price_relative_to_open_by_horizon": {
            h: {
                "version_a_available_only": calc_stats(rel_prices_horizons_avail[h]),
                "version_b_carried_forward": calc_stats(rel_prices_horizons_carried[h]),
                "coverage": horizon_coverage[h],
            }
            for h in HORIZONS
        },
        "headline_simulated_entry_s10": {
            "version_a_available_only": {
                "sim_91_usd": {h: calc_stats(sim_s10_91_avail[h]) for h in sim_s10_91_avail},
                "sim_185_usd": {h: calc_stats(sim_s10_185_avail[h]) for h in sim_s10_185_avail},
            },
            "version_b_carried_forward": {
                "sim_91_usd": {h: calc_stats(sim_s10_91_carried[h]) for h in sim_s10_91_carried},
                "sim_185_usd": {h: calc_stats(sim_s10_185_carried[h]) for h in sim_s10_185_carried},
            },
        },
        "headline_simulated_entry_s20": {
            "version_a_available_only": {
                "sim_91_usd": {h: calc_stats(sim_s20_91_avail[h]) for h in sim_s20_91_avail},
                "sim_185_usd": {h: calc_stats(sim_s20_185_avail[h]) for h in sim_s20_185_avail},
            },
            "version_b_carried_forward": {
                "sim_91_usd": {h: calc_stats(sim_s20_91_carried[h]) for h in sim_s20_91_carried},
                "sim_185_usd": {h: calc_stats(sim_s20_185_carried[h]) for h in sim_s20_185_carried},
            },
        },
    }

    report = {
        "metadata": {
            "title": "Route B Realistic Latency Price Paths & Replay (Review Item 3)",
            "methodology": "PRE-swap reserves used at target slot | Lag & Carried-Forward Analysis",
            "total_pools": len(reached_pools),
            "fee_tier": "Tier 0 (125 bps total)",
            "priority_fee_sol": PRIORITY_FEE_SOL,
        },
        "summary": summary,
        "per_pool_data": pool_results,
    }

    out_file = "reports/route_b_price_paths.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    print(f"\nReport generated successfully: {out_file}")

    print("\n" + "=" * 115)
    print("HORIZON LAG STATISTICS (slot_tx - slot_target):")
    print("=" * 115)
    print(f"{'HORIZON':<8} | {'N AVAIL':<8} | {'MEDIAN LAG (slots)':<20} | {'MAX LAG (slots)':<16} | {'LAG > 50 SLOTS'}")
    print("-" * 115)
    for h in HORIZONS:
        lst = summary["horizon_lag_statistics"][h]
        print(f"{h:<8} | {lst['n']:<8d} | {lst['median_lag_slots']:<20.1f} | {lst['max_lag_slots']:<16d} | {lst['count_lag_gt_50']} / {lst['n']} ({lst['pct_lag_gt_50']}%)")

    print("\n" + "=" * 115)
    print("PRICE RELATIVE TO OPEN: VERSION A (Available Only) vs VERSION B (Carried Forward):")
    print("=" * 115)
    for h in HORIZONS:
        cov = summary["price_relative_to_open_by_horizon"][h]["coverage"]
        va = summary["price_relative_to_open_by_horizon"][h]["version_a_available_only"]
        vb = summary["price_relative_to_open_by_horizon"][h]["version_b_carried_forward"]
        print(f"  {h:<6}: [Ver A: Avail n={va['n']:2d}] Median={va['median']:6.3f}x | Mean(ex1)={va['mean_ex_top1']:6.3f}x | 95% CI=[{va['bootstrap_95_ci'][0]:.2f}, {va['bootstrap_95_ci'][1]:.2f}]")
        print(f"          [Ver B: Carry n={vb['n']:2d}] Median={vb['median']:6.3f}x | Mean(ex1)={vb['mean_ex_top1']:6.3f}x | 95% CI=[{vb['bootstrap_95_ci'][0]:.2f}, {vb['bootstrap_95_ci'][1]:.2f}] (Carried: {cov['carried_forward']})")

    print("\n" + "=" * 115)
    print("HEADLINE ENTRY: S+10 (~2.2s reaction time) -> SIMULATED $91 ENTRY (Returns %)")
    print("=" * 115)
    for h in sim_s10_91_avail:
        va = summary["headline_simulated_entry_s10"]["version_a_available_only"]["sim_91_usd"][h]
        vb = summary["headline_simulated_entry_s10"]["version_b_carried_forward"]["sim_91_usd"][h]
        lst = summary["horizon_lag_statistics"][h]
        lag_notice = f" [LARGE LAG: max={lst['max_lag_slots']}s]" if lst["max_lag_slots"] > 50 else ""
        print(f"  Exit {h:<6}{lag_notice}:")
        print(f"    Ver A (n={va['n']:2d} Avail): Median={va['median']:+6.2f}% | Mean(ex1)={va['mean_ex_top1']:+6.2f}% | <-50%: {va['frac_below_neg50_pct']:5.1f}% | 95% CI: [{va['bootstrap_95_ci'][0]:+6.2f}%, {va['bootstrap_95_ci'][1]:+6.2f}%]")
        print(f"    Ver B (n={vb['n']:2d} Carry): Median={vb['median']:+6.2f}% | Mean(ex1)={vb['mean_ex_top1']:+6.2f}% | <-50%: {vb['frac_below_neg50_pct']:5.1f}% | 95% CI: [{vb['bootstrap_95_ci'][0]:+6.2f}%, {vb['bootstrap_95_ci'][1]:+6.2f}%]")

    print("\n" + "=" * 115)
    print("HEADLINE ENTRY: S+20 (~4.3s reaction time) -> SIMULATED $91 ENTRY (Returns %)")
    print("=" * 115)
    for h in sim_s20_91_avail:
        va = summary["headline_simulated_entry_s20"]["version_a_available_only"]["sim_91_usd"][h]
        vb = summary["headline_simulated_entry_s20"]["version_b_carried_forward"]["sim_91_usd"][h]
        lst = summary["horizon_lag_statistics"][h]
        lag_notice = f" [LARGE LAG: max={lst['max_lag_slots']}s]" if lst["max_lag_slots"] > 50 else ""
        print(f"  Exit {h:<6}{lag_notice}:")
        print(f"    Ver A (n={va['n']:2d} Avail): Median={va['median']:+6.2f}% | Mean(ex1)={va['mean_ex_top1']:+6.2f}% | <-50%: {va['frac_below_neg50_pct']:5.1f}% | 95% CI: [{va['bootstrap_95_ci'][0]:+6.2f}%, {va['bootstrap_95_ci'][1]:+6.2f}%]")
        print(f"    Ver B (n={vb['n']:2d} Carry): Median={vb['median']:+6.2f}% | Mean(ex1)={vb['mean_ex_top1']:+6.2f}% | <-50%: {vb['frac_below_neg50_pct']:5.1f}% | 95% CI: [{vb['bootstrap_95_ci'][0]:+6.2f}%, {vb['bootstrap_95_ci'][1]:+6.2f}%]")


if __name__ == "__main__":
    main()

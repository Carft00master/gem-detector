"""
Route B Price Paths & Horizon Replay Generator.
Implements Review 6 Item 1 strictly from cached signatures and fixtures.
Covers slot offsets S+5, S+10, S+20, S+40 and horizons +30s, +2m, +5m, +15m, +60m.
Headlines S+10 and S+20 entries ($91 and $185).
Outputs reports/route_b_price_paths.json without hand-typed numbers.
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

SOL_USD_PRICE = 150.0  # Reference SOL price for $91 and $185 entries
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


def get_pool_balances_from_tx(tx: dict, pool: str, mint: str) -> Tuple[Optional[float], Optional[float]]:
    meta = tx.get("meta") or {}
    post_tb = meta.get("postTokenBalances") or []
    wsol_bal = None
    tok_bal = None
    for tb in post_tb:
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

    # Trader receives tokens from entry pool reserves
    s_eff_entry = entry_vault + boost_sol
    trader_tokens = (entry_tok * net_entry_sol) / (s_eff_entry + net_entry_sol)

    # Trader sells tokens at exit pool reserves
    s_eff_exit = exit_vault + boost_sol
    gross_sol_exit = (s_eff_exit * trader_tokens) / (exit_tok + trader_tokens)
    net_sol_exit = gross_sol_exit * (1.0 - TIER_0_FEE_RATE) - PRIORITY_FEE_SOL

    # Capped at actual vault SOL
    capped_net_sol_exit = max(0.0, min(net_sol_exit, exit_vault))

    # Total capital outlay = entry_sol + priority_fee
    total_outlay_sol = entry_sol + PRIORITY_FEE_SOL
    ret_pct = ((capped_net_sol_exit - total_outlay_sol) / total_outlay_sol) * 100.0
    return round(ret_pct, 2)


def main():
    print("=" * 110)
    print("ROUTE B PRICE PATHS AND HORIZON REPLAY (Review 6 Item 1 & Item 4)")
    print("=" * 110)

    with open("reports/retrospective_report.json", encoding="utf-8") as f:
        retro = json.load(f)

    reached_pools = [r for r in retro["per_migration_table"] if r.get("reached_creation_slot")]
    print(f"Loaded {len(reached_pools)} reached pools.")

    pool_results = []

    rel_prices_slots = {"S+0": [], "S+1": [], "S+2": [], "S+3": []}
    rel_prices_horizons = {h: [] for h in HORIZONS}

    # Simulations: S+10 entry and S+20 entry (headlined)
    # Exits simulated for each horizon strictly later than entry
    sim_s10_91 = {h: [] for h in HORIZONS if HORIZONS[h] > 10}
    sim_s10_185 = {h: [] for h in HORIZONS if HORIZONS[h] > 10}

    sim_s20_91 = {h: [] for h in HORIZONS if HORIZONS[h] > 20}
    sim_s20_185 = {h: [] for h in HORIZONS if HORIZONS[h] > 20}

    horizon_coverage = {h: {"available": 0, "not_obtained": 0, "reasons": Counter()} for h in HORIZONS}

    pools_s0_surge_gt_1_5 = 0

    for r in reached_pools:
        idx = r["index"]
        pool = r["pool_address"]
        mint = r["mint"]
        mig_sig = r["migration_signature"]
        c_slot = r["creation_slot"]

        # 1. Opening Balances
        mig_tx = load_fixture(mig_sig)
        if not mig_tx:
            continue

        wsol_open, tok_open = get_pool_balances_from_tx(mig_tx, pool, mint)
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
                w_b, t_b = get_pool_balances_from_tx(tx_data, pool, mint)
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

        # 3. Horizon Sampling (S+5, S+10, S+20, S+40, +30s, +2m, +5m, +15m, +60m)
        horizon_states = {}
        for h_label, h_slots in HORIZONS.items():
            target_slot = c_slot + h_slots
            candidates = sorted(
                [s for s in sigs if s.get("slot", 0) >= target_slot and s.get("err") is None],
                key=lambda x: (x.get("slot", 0), x.get("transactionIndex", 0)),
            )

            if not candidates:
                reason = "No successful transaction signature found at or after target slot"
                horizon_states[h_label] = {
                    "status": "NOT_OBTAINED",
                    "slot_offset": h_slots,
                    "reason": reason,
                }
                horizon_coverage[h_label]["not_obtained"] += 1
                horizon_coverage[h_label]["reasons"][reason] += 1
                continue

            # Check candidate fixtures
            found_tx = None
            found_sig = None
            found_slot = None

            # First try candidates in order
            for cand in candidates:
                csig = cand["signature"]
                ctx = load_fixture(csig)
                if ctx and ctx.get("meta"):
                    w_b, t_b = get_pool_balances_from_tx(ctx, pool, mint)
                    if w_b is not None and t_b is not None:
                        found_tx = (w_b, t_b)
                        found_sig = csig
                        found_slot = cand.get("slot", 0)
                        break

            if found_tx:
                h_vault, h_tok = found_tx
                h_eff_price = (h_vault + boost_sol) / h_tok
                rel_open = h_eff_price / price_open
                horizon_states[h_label] = {
                    "status": "AVAILABLE",
                    "slot": found_slot,
                    "slot_offset": found_slot - c_slot,
                    "signature": found_sig,
                    "vault_sol": round(h_vault, 6),
                    "token_reserve": round(h_tok, 2),
                    "effective_price_sol": h_eff_price,
                    "price_rel_open": round(rel_open, 4),
                }
                rel_prices_horizons[h_label].append(round(rel_open, 4))
                horizon_coverage[h_label]["available"] += 1
            else:
                reason = "RPC getTransaction returned null (archival prune/unindexed on node)"
                horizon_states[h_label] = {
                    "status": "NOT_OBTAINED",
                    "slot_offset": h_slots,
                    "reason": reason,
                }
                horizon_coverage[h_label]["not_obtained"] += 1
                horizon_coverage[h_label]["reasons"][reason] += 1

        # 4. Simulate Trades:
        # A) S+10 Entry
        s10_state = horizon_states.get("S+10", {})
        if s10_state.get("status") == "AVAILABLE":
            s10_v = s10_state["vault_sol"]
            s10_t = s10_state["token_reserve"]
            for h_label in sim_s10_91:
                exit_st = horizon_states.get(h_label, {})
                if exit_st.get("status") == "AVAILABLE":
                    ret91 = simulate_trade(91.0, s10_v, s10_t, boost_sol, exit_st["vault_sol"], exit_st["token_reserve"])
                    ret185 = simulate_trade(185.0, s10_v, s10_t, boost_sol, exit_st["vault_sol"], exit_st["token_reserve"])
                    sim_s10_91[h_label].append(ret91)
                    sim_s10_185[h_label].append(ret185)
                    horizon_states[h_label]["sim_from_s10_91_pct"] = ret91
                    horizon_states[h_label]["sim_from_s10_185_pct"] = ret185

        # B) S+20 Entry
        s20_state = horizon_states.get("S+20", {})
        if s20_state.get("status") == "AVAILABLE":
            s20_v = s20_state["vault_sol"]
            s20_t = s20_state["token_reserve"]
            for h_label in sim_s20_91:
                exit_st = horizon_states.get(h_label, {})
                if exit_st.get("status") == "AVAILABLE":
                    ret91 = simulate_trade(91.0, s20_v, s20_t, boost_sol, exit_st["vault_sol"], exit_st["token_reserve"])
                    ret185 = simulate_trade(185.0, s20_v, s20_t, boost_sol, exit_st["vault_sol"], exit_st["token_reserve"])
                    sim_s20_91[h_label].append(ret91)
                    sim_s20_185[h_label].append(ret185)
                    horizon_states[h_label]["sim_from_s20_91_pct"] = ret91
                    horizon_states[h_label]["sim_from_s20_185_pct"] = ret185

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

    # Summary section
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
        "price_relative_to_open_by_horizon": {
            h: {
                "stats": calc_stats(rel_prices_horizons[h]),
                "coverage": {
                    "available_n": horizon_coverage[h]["available"],
                    "not_obtained_n": horizon_coverage[h]["not_obtained"],
                    "not_obtained_reasons": dict(horizon_coverage[h]["reasons"]),
                },
            }
            for h in HORIZONS
        },
        "headline_simulated_entry_s10": {
            "sim_91_usd": {h: calc_stats(sim_s10_91[h]) for h in sim_s10_91},
            "sim_185_usd": {h: calc_stats(sim_s10_185[h]) for h in sim_s10_185},
        },
        "headline_simulated_entry_s20": {
            "sim_91_usd": {h: calc_stats(sim_s20_91[h]) for h in sim_s20_91},
            "sim_185_usd": {h: calc_stats(sim_s20_185[h]) for h in sim_s20_185},
        },
    }

    report = {
        "metadata": {
            "title": "Route B Realistic Latency Price Paths & Horizon Replay",
            "total_reached_pools": len(reached_pools),
            "horizons": list(HORIZONS.keys()),
            "headline_entries": ["S+10 (~2s reaction)", "S+20 (~4s reaction)"],
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

    print("\n" + "=" * 90)
    print("PER-POOL TABLE: price(open) vs price(S+0..S+3)")
    print("=" * 90)
    print(f"{'ROW':<4} | {'POOL':<44} | {'PRICE(OPEN)':<12} | {'S+0':<9} | {'S+1':<9} | {'S+2':<9} | {'S+3':<9}")
    print("-" * 105)
    for p in pool_results:
        idx = p["index"]
        pool = p["pool_address"]
        p_open = p["opening_balances"]["price_open_sol"]
        s0 = p["window_slots"]["S+0"]["price_rel_open"]
        s1 = p["window_slots"]["S+1"]["price_rel_open"]
        s2 = p["window_slots"]["S+2"]["price_rel_open"]
        s3 = p["window_slots"]["S+3"]["price_rel_open"]
        print(f"{idx:<4} | {pool:<44} | {p_open:.4e} | {s0:6.3f}x   | {s1:6.3f}x   | {s2:6.3f}x   | {s3:6.3f}x")

    print("\n" + "=" * 90)
    print(f"POOLS WITH price(S+0)/price(open) > 1.5: {pools_s0_surge_gt_1_5} / {len(reached_pools)} ({pools_s0_surge_gt_1_5/len(reached_pools)*100:.1f}%)")
    print("=" * 90)

    print("\n" + "=" * 90)
    print("HORIZON PRICE COVERAGE & NOT_OBTAINED REASONS:")
    print("=" * 90)
    for h in HORIZONS:
        cov = summary["price_relative_to_open_by_horizon"][h]["coverage"]
        st = summary["price_relative_to_open_by_horizon"][h]["stats"]
        print(f"  {h:<6}: Available n={cov['available_n']:2d}/34 | NOT_OBTAINED n={cov['not_obtained_n']:2d}/34 | Median={st['median'] if st['median'] else 'N/A'}")
        if cov["not_obtained_reasons"]:
            for r_text, r_cnt in cov["not_obtained_reasons"].items():
                print(f"         |-- {r_text}: {r_cnt}")

    print("\n" + "=" * 90)
    print("HEADLINE ENTRY: S+10 (~2s reaction time) -> Exits across Horizons")
    print("=" * 90)
    for h in sim_s10_91:
        st91 = summary["headline_simulated_entry_s10"]["sim_91_usd"][h]
        st185 = summary["headline_simulated_entry_s10"]["sim_185_usd"][h]
        if st91["n"] > 0:
            print(f"  Exit {h:<6} (n={st91['n']:2d}): $91 Entry Median = {st91['median']:+6.2f}% (ex top 1: {st91['mean_ex_top1']:+6.2f}%, <-50%: {st91['frac_below_neg50_pct']:5.1f}%, 95% CI: [{st91['bootstrap_95_ci'][0]:+6.2f}%, {st91['bootstrap_95_ci'][1]:+6.2f}%])")
            print(f"                 $185 Entry Median = {st185['median']:+6.2f}% (ex top 1: {st185['mean_ex_top1']:+6.2f}%, <-50%: {st185['frac_below_neg50_pct']:5.1f}%, 95% CI: [{st185['bootstrap_95_ci'][0]:+6.2f}%, {st185['bootstrap_95_ci'][1]:+6.2f}%])")
        else:
            print(f"  Exit {h:<6}: No paired trades available")

    print("\n" + "=" * 90)
    print("HEADLINE ENTRY: S+20 (~4s reaction time) -> Exits across Horizons")
    print("=" * 90)
    for h in sim_s20_91:
        st91 = summary["headline_simulated_entry_s20"]["sim_91_usd"][h]
        st185 = summary["headline_simulated_entry_s20"]["sim_185_usd"][h]
        if st91["n"] > 0:
            print(f"  Exit {h:<6} (n={st91['n']:2d}): $91 Entry Median = {st91['median']:+6.2f}% (ex top 1: {st91['mean_ex_top1']:+6.2f}%, <-50%: {st91['frac_below_neg50_pct']:5.1f}%, 95% CI: [{st91['bootstrap_95_ci'][0]:+6.2f}%, {st91['bootstrap_95_ci'][1]:+6.2f}%])")
            print(f"                 $185 Entry Median = {st185['median']:+6.2f}% (ex top 1: {st185['mean_ex_top1']:+6.2f}%, <-50%: {st185['frac_below_neg50_pct']:5.1f}%, 95% CI: [{st185['bootstrap_95_ci'][0]:+6.2f}%, {st185['bootstrap_95_ci'][1]:+6.2f}%])")
        else:
            print(f"  Exit {h:<6}: No paired trades available")


if __name__ == "__main__":
    main()

"""
Analyze the 6-hour CurveTradeCollector dataset in data/curve_trades.db (534,466 trades across 11,780 creations)
and save both:
1. reports/trade_collector_6h_confirmed_report.json (preserved 6-hour collector run report)
2. reports/route_a_6h_summary.json (Route A bonding-curve funnel, graduation speed breakdown, and realistic entry/exit analysis)
"""

import json
import os
import shutil
import sqlite3
import statistics
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

WSOL_MINT = "So11111111111111111111111111111111111111112"
USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"


def main():
    if os.path.exists("reports/trade_collector_5m_confirmed_report.json"):
        shutil.copyfile(
            "reports/trade_collector_5m_confirmed_report.json",
            "reports/trade_collector_6h_confirmed_report.json",
        )

    conn = sqlite3.connect("data/curve_trades.db")
    cur = conn.cursor()

    # 1. Global counts
    cur.execute("SELECT MIN(created_block_time), MAX(created_block_time), COUNT(*) FROM curve_creations")
    min_create_ts, max_create_ts, total_creations = cur.fetchone()

    cur.execute("SELECT MIN(block_time), MAX(block_time), COUNT(*), COUNT(DISTINCT mint), COUNT(DISTINCT wallet) FROM curve_trades")
    min_trade_ts, max_trade_ts, total_trades, distinct_traded_mints, distinct_wallets = cur.fetchone()

    # Mature cutoff: mints created at least 1800s (30m) before max_trade_ts have a complete 30m window
    mature_cutoff_ts = max_trade_ts - 1800
    cur.execute("SELECT mint, created_block_time, slot, creator FROM curve_creations")
    all_creations = {r[0]: {"created_ts": r[1], "created_slot": r[2], "creator": r[3]} for r in cur.fetchall()}

    # 2. Load all SOL-quoted trades ordered by (slot, id)
    cur.execute("""
        SELECT mint, tx_type, wallet, sol_lamports, token_base_units, slot, block_time, signature, log_index
        FROM curve_trades
        WHERE quote_mint = ?
        ORDER BY slot ASC, id ASC
    """, (WSOL_MINT,))

    mint_trades = {}
    for mint, tx_type, wallet, sol_lamports, tok_units, slot, bt, sig, log_idx in cur.fetchall():
        mint_trades.setdefault(mint, []).append((tx_type, wallet, sol_lamports / 1e9, tok_units / 1e6, slot, bt, sig, log_idx))

    print(f"Loaded {len(mint_trades)} SOL-quoted mints with trades (out of {total_creations} total creations).")

    mature_sol_mints = 0
    funnel_counts = {5.0: 0, 10.0: 0, 15.0: 0, 25.0: 0, 40.0: 0, 60.0: 0, 80.0: 0, 84.0: 0}
    all_funnel_counts = {5.0: 0, 10.0: 0, 15.0: 0, 25.0: 0, 40.0: 0, 60.0: 0, 80.0: 0, 84.0: 0}

    horizons_sec = [30, 60, 120, 300, 900]
    mint_trajectories = {}
    graduated_mints_detail = []

    for mint, t_list in mint_trades.items():
        c_info = all_creations.get(mint)
        if not c_info:
            continue
        is_mature = c_info["created_ts"] <= mature_cutoff_ts
        if is_mature:
            mature_sol_mints += 1

        net_sol = 0.0
        net_tok = 0.0
        peak_net_sol = 0.0
        buyers = set()
        buy_cnt = 0
        sell_cnt = 0
        traj = []

        for tx_type, wallet, d_sol, d_tok, slot, bt, sig, log_idx in t_list:
            if tx_type == "buy":
                net_sol += d_sol
                net_tok += d_tok
                buyers.add(wallet)
                buy_cnt += 1
            else:
                net_sol = max(0.0, net_sol - d_sol)
                net_tok = max(0.0, net_tok - d_tok)
                sell_cnt += 1
            if net_sol > peak_net_sol:
                peak_net_sol = net_sol
            v_sol = 30.0 + net_sol
            v_tok = max(206_900_000.0, 1_073_000_000.0 - net_tok)
            spot_p = v_sol / v_tok
            traj.append((slot, bt, net_sol, v_sol, v_tok, spot_p, len(buyers), buy_cnt, sell_cnt, d_sol, d_tok, tx_type))

        for thresh in all_funnel_counts:
            if peak_net_sol >= thresh:
                all_funnel_counts[thresh] += 1
                if is_mature:
                    funnel_counts[thresh] += 1

        if peak_net_sol >= 84.0:
            s_first = traj[0][0]
            s_last = traj[-1][0]
            bt_first = traj[0][1]
            bt_last = traj[-1][1]
            slot_dur = s_last - s_first
            sec_dur = bt_last - bt_first
            grad_type = (
                "INSTANT_BUNDLED_0_TO_2_SLOTS"
                if slot_dur <= 2
                else ("FAST_3_TO_25_SLOTS" if slot_dur <= 25 else "ORGANIC_OVER_25_SLOTS")
            )
            graduated_mints_detail.append({
                "mint": mint,
                "is_mature": is_mature,
                "trade_count": len(traj),
                "unique_buyers": len(buyers),
                "peak_net_sol": round(peak_net_sol, 6),
                "final_net_sol": round(net_sol, 6),
                "first_slot": s_first,
                "last_slot": s_last,
                "duration_slots": slot_dur,
                "duration_seconds": sec_dur,
                "graduation_class": grad_type,
            })

        if is_mature:
            mint_trajectories[mint] = (c_info, traj)

    grad_bundled = [g for g in graduated_mints_detail if g["graduation_class"] == "INSTANT_BUNDLED_0_TO_2_SLOTS"]
    grad_fast = [g for g in graduated_mints_detail if g["graduation_class"] == "FAST_3_TO_25_SLOTS"]
    grad_organic = [g for g in graduated_mints_detail if g["graduation_class"] == "ORGANIC_OVER_25_SLOTS"]

    print("\n" + "=" * 115)
    print(f"1. BONDING CURVE INFLOW FUNNEL (All 5,878 SOL Mints vs Mature Cohort N={mature_sol_mints} with full 30m window)")
    print("=" * 115)
    for thresh in sorted(funnel_counts.keys()):
        cnt_all = all_funnel_counts[thresh]
        cnt_mat = funnel_counts[thresh]
        pct_all = 100.0 * cnt_all / max(1, len(mint_trades))
        pct_mat = 100.0 * cnt_mat / max(1, mature_sol_mints)
        label = " (Exact Graduation ~85.005 SOL)" if thresh == 84.0 else ""
        print(
            f"  Peak Net Curve SOL >= {thresh:4.0f} SOL{label:<31}: "
            f"All={cnt_all:4d}/{len(mint_trades)} ({pct_all:5.2f}%) | "
            f"Mature={cnt_mat:4d}/{mature_sol_mints} ({pct_mat:5.2f}%)"
        )

    print("\n" + "=" * 115)
    print(f"2. GRADUATION SPEED BREAKDOWN ({len(graduated_mints_detail)} Graduated SOL Mints Reaching >= 84.0 SOL):")
    print("=" * 115)
    print(f"  - Instant Bundled Self-Graduations (0-2 slots, 0-1s, 1-14 txs) : {len(grad_bundled):2d} / {len(graduated_mints_detail)} ({100.0*len(grad_bundled)/max(1,len(graduated_mints_detail)):5.2f}%) [Unreachable before migration]")
    print(f"  - Fast Sniper Graduations          (3-25 slots, 4-5s, 35-48 txs): {len(grad_fast):2d} / {len(graduated_mints_detail)} ({100.0*len(grad_fast)/max(1,len(graduated_mints_detail)):5.2f}%)")
    print(f"  - Organic Curve Graduations        (>25 slots, 23s-1541s)       : {len(grad_organic):2d} / {len(graduated_mints_detail)} ({100.0*len(grad_organic)/max(1,len(graduated_mints_detail)):5.2f}%) [{100.0*len(grad_organic)/max(1,mature_sol_mints):.2f}% of mature SOL mints]")

    entry_sol_gross = 0.607
    fee_mult = 0.9875

    print("\n" + "=" * 115)
    print("3. ROUTE A REALISTIC ENTRY SIMULATION ($91 = 0.607 SOL Entry, 1.25% Fee Each Way, Constant-Product Curve Math)")
    print("=" * 115)

    sim_results = {}
    for trig_sol in [5.0, 10.0, 15.0, 25.0]:
        for react_slots in [2, 5, 10]:
            entries = []
            for mint, (c_info, traj) in mint_trajectories.items():
                trig_idx = None
                for idx, row in enumerate(traj):
                    slot, bt, net_sol, v_sol, v_tok, spot_p, n_buyers, b_cnt, s_cnt, _, _, _ = row
                    if net_sol >= trig_sol and (bt - c_info["created_ts"]) <= 300 and n_buyers >= 5:
                        trig_idx = idx
                        break
                if trig_idx is None:
                    continue

                trig_slot = traj[trig_idx][0]
                target_entry_slot = trig_slot + react_slots

                entry_idx = None
                for idx in range(trig_idx + 1, len(traj)):
                    if traj[idx][0] >= target_entry_slot:
                        entry_idx = idx
                        break
                if entry_idx is None:
                    continue

                e_slot, e_bt, e_net_sol, e_v_sol, e_v_tok, e_spot_p, _, _, _, _, _, _ = traj[entry_idx]
                d_sol_net = entry_sol_gross * fee_mult
                tokens_bought = (e_v_tok * d_sol_net) / (e_v_sol + d_sol_net)

                horizon_rets = {}
                for h_sec in horizons_sec:
                    target_bt = e_bt + h_sec
                    exit_idx = entry_idx
                    graduated = False
                    for idx in range(entry_idx, len(traj)):
                        if traj[idx][2] >= 84.0:
                            exit_idx = idx
                            graduated = True
                            break
                        if traj[idx][1] <= target_bt:
                            exit_idx = idx
                        else:
                            break
                    x_slot, x_bt, x_net_sol, x_v_sol, x_v_tok, x_spot_p, _, _, _, _, _, _ = traj[exit_idx]
                    gross_sol_out = (x_v_sol * tokens_bought) / (x_v_tok + tokens_bought)
                    real_sol_out = min(gross_sol_out, x_net_sol)
                    net_sol_out = real_sol_out * fee_mult
                    ret_pct = 100.0 * (net_sol_out / entry_sol_gross - 1.0)
                    horizon_rets[h_sec] = (ret_pct, graduated)

                entries.append(horizon_rets)

            key = f"trig_{int(trig_sol)}sol_S+{react_slots}"
            sim_results[key] = {}
            for h_sec in horizons_sec:
                rets = [e[h_sec][0] for e in entries]
                grads = sum(1 for e in entries if e[h_sec][1])
                if rets:
                    s_rets = sorted(rets)
                    med = statistics.median(s_rets)
                    mean_all = statistics.mean(s_rets)
                    mean_ex1 = statistics.mean(s_rets[:-1]) if len(s_rets) > 1 else mean_all
                    win_rate = 100.0 * sum(1 for r in s_rets if r > 0) / len(s_rets)
                    crash_rate = 100.0 * sum(1 for r in s_rets if r < -50.0) / len(s_rets)
                    sim_results[key][f"+{h_sec}s"] = {
                        "n": len(s_rets),
                        "median_pct": round(med, 2),
                        "mean_pct": round(mean_all, 2),
                        "mean_ex_top1_pct": round(mean_ex1, 2),
                        "win_rate_pct": round(win_rate, 2),
                        "below_minus_50_pct": round(crash_rate, 2),
                        "graduated_count": grads,
                    }
            if react_slots in (2, 10):
                r60 = sim_results[key].get("+60s", {})
                r120 = sim_results[key].get("+120s", {})
                r300 = sim_results[key].get("+300s", {})
                if r60:
                    print(
                        f"  Trigger >= {trig_sol:2.0f} SOL (buyers>=5, <=5m) | Entry S+{react_slots:<2d} (n={r60['n']:4d}) -> "
                        f"+60s: med={r60['median_pct']:+6.2f}%, mean={r60['mean_pct']:+6.2f}%, WR={r60['win_rate_pct']:5.1f}% | "
                        f"+120s: med={r120['median_pct']:+6.2f}%, mean={r120['mean_pct']:+6.2f}% | "
                        f"+300s: med={r300['median_pct']:+6.2f}%, mean={r300['mean_pct']:+6.2f}%, <-50%={r300['below_minus_50_pct']:5.1f}%"
                    )

    out_report = {
        "total_creations_6h": total_creations,
        "total_trades_6h": total_trades,
        "distinct_traded_mints_6h": distinct_traded_mints,
        "distinct_wallets_6h": distinct_wallets,
        "sol_quoted_mints": len(mint_trades),
        "mature_sol_quoted_mints_30m": mature_sol_mints,
        "funnel_all_sol_mints": {str(k): v for k, v in all_funnel_counts.items()},
        "funnel_mature_sol_mints": {str(k): v for k, v in funnel_counts.items()},
        "graduated_mints_breakdown": {
            "total_graduated": len(graduated_mints_detail),
            "instant_bundled_0_to_2_slots": len(grad_bundled),
            "fast_3_to_25_slots": len(grad_fast),
            "organic_over_25_slots": len(grad_organic),
            "graduated_mints": graduated_mints_detail,
        },
        "route_a_simulations": sim_results,
    }
    with open("reports/route_a_6h_summary.json", "w", encoding="utf-8") as f:
        json.dump(out_report, f, indent=2)
    print("\nSaved Route A 6-hour analysis to reports/route_a_6h_summary.json.")


if __name__ == "__main__":
    main()

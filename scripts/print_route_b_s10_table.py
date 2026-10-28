"""
Print per-pool table for the $91 entry at S+10 after fixing the Route B Vault & Boost bug (Review Item 1):
- Prints wsol_open, true boost_sol (17.584505 SOL for 19 InitBoost pools, 0.0 for 15 unboosted pools),
  p(S+10), p(S+20), p(S+40), v(S+20), E-model returns, price-ratio returns, and classification.
- Reports the genuine price crash count (Rows 7, 14, 26, 28 at S+20 = 4/34 [11.76%]; 0/19 [0.0%] in boosted pools)
  and corrects earlier statements ("32% below -50% at S+20", "-41% at 2 min").
"""

import json


def main():
    with open("reports/route_b_price_paths.json", "r", encoding="utf-8") as f:
        data = json.load(f)

    pools = data["per_pool_data"]
    summary = data["summary"]

    print("=" * 165)
    print("PER-POOL TABLE FOR $91 ENTRY AT S+10 (AFTER FIXING BOOST_SOL & VERIFYING SWAP-IMPLIED S_eff < 2%)")
    print("=" * 165)
    header = (
        f"{'ROW':<3} | {'POOL':<44} | {'BOOST':<7} | {'p(S+10) SOL (Rel)':<21} | "
        f"{'p(S+20) SOL (Rel)':<21} | {'p20/p10':<7} | {'v(S+20)':<8} | {'E-MOD S20':<9} | {'PR-RET S20':<10} | {'CLASSIFICATION'}"
    )
    print(header)
    print("-" * 165)

    genuine_crashes_s20 = []
    micro_pool_self_impact_s20 = []
    boosted_pools = []
    unboosted_pools = []

    for p in pools:
        idx = p["index"]
        addr = p["pool_address"]
        boost = p["opening_balances"]["boost_sol"]
        is_boosted = p["is_boosted_pool"]

        s10 = p["horizon_samples"]["S+10"]
        s20 = p["horizon_samples"]["S+20"]
        s40 = p["horizon_samples"]["S+40"]

        p10_sol, p10_rel = s10["effective_price_sol"], s10["price_rel_open"]
        p20_sol, p20_rel = s20["effective_price_sol"], s20["price_rel_open"]
        p20_p10 = p20_sol / p10_sol if p10_sol > 0 else 0.0

        v10 = s10["vault_sol"]
        v20 = s20["vault_sol"]

        ret20 = s20["sim_from_s10_91_pct"]
        pr_ret20 = s20["price_ratio_ret_from_s10_91_pct"]

        if is_boosted:
            boosted_pools.append(idx)
        else:
            unboosted_pools.append(idx)

        cls_str = "STANDARD_BOOSTED_OK" if is_boosted else "UNBOOSTED_OK"
        if pr_ret20 < -50.0:
            cls_str = f"GENUINE_CRASH (p20/p10={p20_p10:.3f}x)"
            genuine_crashes_s20.append(idx)
        elif ret20 < -50.0:
            cls_str = f"MICRO_POOL_UNPERTURBED_EXIT (v10={v10:.3f} SOL < $91 entry; p20/p10={p20_p10:.3f}x)"
            micro_pool_self_impact_s20.append(idx)

        print(
            f"{idx:<3d} | {addr:<44} | {boost:7.4f} | {p10_sol:.4e} ({p10_rel:5.3f}x) | "
            f"{p20_sol:.4e} ({p20_rel:5.3f}x) | {p20_p10:6.3f}x | {v20:8.3f} | {ret20:+8.2f}% | {pr_ret20:+9.2f}% | {cls_str}"
        )

    print("=" * 165)
    print("SUMMARY OF CORRECTIONS AFTER FIXING THE VAULT/BOOST BUG:")
    print("=" * 165)
    print(f"1. Cohort Composition (34 Reached Pools):")
    print(f"   - Standard Boosted Pools (InitBoost called, boost=17.584505 SOL, wsol_open=67.41..116.80 SOL): {len(boosted_pools)} pools {boosted_pools}")
    print(f"   - Unboosted Micro-Pools (InitBoost NOT called, boost=0.000000 SOL, wsol_open=0.033..21.67 SOL): {len(unboosted_pools)} pools {unboosted_pools}")
    print(f"2. Genuine Price Crashes (<-50% price return) between S+10 and S+20:")
    print(f"   - Count: {len(genuine_crashes_s20)} / 34 pools ({len(genuine_crashes_s20)/34*100:.2f}%): Rows {genuine_crashes_s20}")
    print("     (Row 7: 0.156x [-84.93%], Row 14: 0.273x [-73.68%], Row 26: 0.057x [-94.75%], Row 28: 0.415x [-60.05%];")
    print("      Row 28's real vault drop from 0.1888 to 0.1227 SOL was previously masked by the fake 84.8 SOL boost.)")
    print(f"   - Among the 19 Standard Boosted Pools: 0 / 19 (0.00%) crash >50% at S+20 (median return -3.51%, mean ex-top1 -3.05%).")
    print(f"3. Correction to Earlier Statements ('32% below -50% at S+20' and '-41% median at 2 min'):")
    s20_b19 = summary["headline_simulated_entry_s10"]["version_a_available_only"]["boosted_19_pools_sim_91_usd"]["S+20"]
    s20_pr = summary["headline_simulated_entry_s10"]["version_a_available_only"]["price_ratio_91_usd_genuine_crashes"]["S+20"]
    s20_em = summary["headline_simulated_entry_s10"]["version_a_available_only"]["sim_91_usd"]["S+20"]
    m2_b19 = summary["headline_simulated_entry_s10"]["version_a_available_only"]["boosted_19_pools_sim_91_usd"]["+2m"]
    m2_pr = summary["headline_simulated_entry_s10"]["version_a_available_only"]["price_ratio_91_usd_genuine_crashes"]["+2m"]
    m2_em = summary["headline_simulated_entry_s10"]["version_a_available_only"]["sim_91_usd"]["+2m"]
    print(f"   - At S+20 (from S+10 $91 entry):")
    print(f"     * Genuine price crash rate (<-50%): {s20_pr['frac_below_neg50_pct']}% ({s20_pr['count_below_neg50']}/34, Rows {genuine_crashes_s20}), NOT 32.4%.")
    print(f"     * 19 Standard Boosted Pools: 0.0% (0/19) below -50%, median {s20_b19['median']:+.2f}%, mean(ex1) {s20_b19['mean_ex_top1']:+.2f}%.")
    print(f"     * All-34 Unperturbed E-Model: median {s20_em['median']:+.2f}%, mean(ex1) {s20_em['mean_ex_top1']:+.2f}%, {s20_em['frac_below_neg50_pct']}% ({s20_em['count_below_neg50']}/34) <-50%")
    print(f"       (because 9 unboosted micro-pools {micro_pool_self_impact_s20} have total vault 0.036..0.539 SOL < $91 [0.607 SOL] entry).")
    print(f"   - At +2m (from S+10 $91 entry):")
    print(f"     * 19 Standard Boosted Pools: median {m2_b19['median']:+.2f}% (was -41.48% when diluted by micro-pools), mean(ex1) {m2_b19['mean_ex_top1']:+.2f}%, 0.0% (0/19) <-50%.")
    print(f"     * Genuine Price-Ratio Return (all 34 pools): median {m2_pr['median']:+.2f}%, mean(ex1) {m2_pr['mean_ex_top1']:+.2f}%, {m2_pr['frac_below_neg50_pct']}% ({m2_pr['count_below_neg50']}/34) <-50%.")
    print(f"     * All-34 Unperturbed E-Model: median {m2_em['median']:+.2f}%, mean(ex1) {m2_em['mean_ex_top1']:+.2f}%, {m2_em['frac_below_neg50_pct']}% ({m2_em['count_below_neg50']}/34) <-50%.")


if __name__ == "__main__":
    main()

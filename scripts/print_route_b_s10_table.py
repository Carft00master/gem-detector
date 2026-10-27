"""
Print per-pool table for the $91 entry at S+10 (Review Item 3):
- p(S+10), p(S+20), p(S+40) (both effective SOL price and ratio to open)
- Simulated $91 entry return at S+20 and S+40
- Mathematical reconciliation of "32.4% (11/34) below -50% at S+20" with the
  nearly flat cross-sectional mean ratio (3.95x at S+10, 3.92x at S+20).
"""

import json

SOL_USD_PRICE = 150.0
PRIORITY_FEE_SOL = 0.002
TIER_0_FEE_RATE = 0.0125


def simulate_uncapped(entry_usd, entry_vault, entry_tok, boost_sol, exit_vault, exit_tok):
    entry_sol = entry_usd / SOL_USD_PRICE
    net_entry_sol = entry_sol * (1.0 - TIER_0_FEE_RATE)
    s_eff_entry = entry_vault + boost_sol
    trader_tokens = (entry_tok * net_entry_sol) / (s_eff_entry + net_entry_sol)

    s_eff_exit = exit_vault + boost_sol
    gross_sol_exit = (s_eff_exit * trader_tokens) / (exit_tok + trader_tokens)
    net_sol_exit = gross_sol_exit * (1.0 - TIER_0_FEE_RATE) - PRIORITY_FEE_SOL
    total_outlay_sol = entry_sol + PRIORITY_FEE_SOL
    return round(((net_sol_exit - total_outlay_sol) / total_outlay_sol) * 100.0, 2)


def main():
    with open("reports/route_b_price_paths.json", "r", encoding="utf-8") as f:
        data = json.load(f)

    pools = data["per_pool_data"]
    print("=" * 145)
    print("PER-POOL TABLE FOR $91 ENTRY AT S+10: p(S+10), p(S+20), p(S+40) AND RETURNS (Review Item 3)")
    print("=" * 145)
    header = (
        f"{'ROW':<3} | {'POOL':<44} | {'p(S+10) SOL (Rel)':<21} | {'p(S+20) SOL (Rel)':<21} | "
        f"{'p(S+40) SOL (Rel)':<21} | {'v(S+20)':<8} | {'RET S+20':<9} | {'RET S+40':<9} | {'CAUSE IF <-50%'}"
    )
    print(header)
    print("-" * 145)

    vault_capped_lt50 = []
    price_crash_lt50 = []
    pumped_cluster = []
    normal_cluster = []

    for p in pools:
        idx = p["index"]
        addr = p["pool_address"]
        boost = p["opening_balances"]["boost_sol"]

        s10 = p["horizon_samples"]["S+10"]
        s20 = p["horizon_samples"]["S+20"]
        s40 = p["horizon_samples"]["S+40"]

        p10_sol, p10_rel = s10["effective_price_sol"], s10["price_rel_open"]
        p20_sol, p20_rel = s20["effective_price_sol"], s20["price_rel_open"]
        p40_sol, p40_rel = s40["effective_price_sol"], s40["price_rel_open"]

        v10, t10 = s10["vault_sol"], s10["token_reserve"]
        v20, t20 = s20["vault_sol"], s20["token_reserve"]

        ret20 = s20["sim_from_s10_91_pct"]
        ret40 = s40["sim_from_s10_91_pct"]

        uncapped20 = simulate_uncapped(91.0, v10, t10, boost, v20, t20)

        cause = ""
        if ret20 < -50.0:
            if uncapped20 >= -50.0:
                cause = f"VAULT_CAP (v20={v20:.3f} SOL < 0.304 SOL; uncapped={uncapped20:+.2f}%)"
                vault_capped_lt50.append(idx)
            else:
                cause = f"PRICE_CRASH (p20/p10={p20_rel/p10_rel:.2f}x; uncapped={uncapped20:+.2f}%)"
                price_crash_lt50.append(idx)

        if p10_rel > 1.5 and v10 > 100.0:
            pumped_cluster.append((idx, p10_rel, p20_rel, ret20))
        else:
            normal_cluster.append((idx, p10_rel, p20_rel, ret20))

        print(
            f"{idx:<3d} | {addr:<44} | {p10_sol:.4e} ({p10_rel:5.3f}x) | "
            f"{p20_sol:.4e} ({p20_rel:5.3f}x) | {p40_sol:.4e} ({p40_rel:5.3f}x) | "
            f"{v20:8.3f} | {ret20:+8.2f}% | {ret40:+8.2f}% | {cause}"
        )

    print("=" * 145)
    print("RECONCILIATION: 32.35% (11/34) BELOW -50% AT S+20 vs FLAT MEAN RATIO (3.95x -> 3.92x)")
    print("=" * 145)
    print(f"1. Total pools with S+10 -> S+20 return < -50%: {len(vault_capped_lt50) + len(price_crash_lt50)} / 34 ({(len(vault_capped_lt50) + len(price_crash_lt50))/34*100:.2f}%)")
    print(f"   - Mechanism A (Vault Cap on Low-Real-SOL Boosted Pools): {len(vault_capped_lt50)} pools (Rows {vault_capped_lt50})")
    print("     A $91 entry costs 0.6067 SOL + 0.002 SOL priority = 0.6087 SOL total outlay.")
    print("     To avoid a -50% loss, exit payout must be >= 0.3043 SOL. However, these 8 boosted pools have")
    print("     historical real WSOL vault balances of only 0.041 to 0.159 SOL at S+20 (while boost_sol is ~84.8 SOL).")
    print("     Because simulate_trade caps exit proceeds at historical exit_vault (min(net_sol_exit, exit_vault)),")
    print("     the payout is capped at 0.041..0.159 SOL (-73.94% to -93.26% return) even when price p(S+20) >= p(S+10).")
    print(f"   - Mechanism B (Genuine Price Dump > 50% between S+10 and S+20): {len(price_crash_lt50)} pools (Rows {price_crash_lt50})")
    print("     Row 7 (0.879x -> 0.342x, -62.86%), Row 14 (0.996x -> 0.517x, -50.38%), Row 26 (0.480x -> 0.099x, -80.57%).")
    print("2. Why the cross-sectional mean ratio (ex-top1) stays nearly flat (3.95x at S+10 vs 3.92x at S+20):")
    print(f"   - The 34-pool distribution is strongly bimodal: {len(pumped_cluster)} S+0 bot-pumped pools sit at 7.55x..9.00x open")
    print("     with ~216-237 SOL in the vault and remain virtually stationary between S+10 and S+20 (returns -3.02% to -3.63%,")
    print("     reflecting the 2x 125 bps swap fee + priority fees). Their sum of ratios is 119.38 at S+10 and 119.65 at S+20.")
    print(f"   - Across the 33 ex-top1 pools, the 13 ex-top1 bot-pumped pools alone contribute 110.44 / 33 = 3.35x to the mean")
    print("     at S+10 and 110.66 / 33 = 3.35x at S+20. The 20 non-pumped pools have small ratios (~0.10x..1.85x), so")
    print("     a -50% crash in a ~0.9x pool reduces the cross-sectional mean ratio by only ~0.015x while adding to the <-50% count.")


if __name__ == "__main__":
    main()

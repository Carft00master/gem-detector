"""
Reconstruct NODF calibration case from real on-chain pool reserves.
This script derives all golden values INDEPENDENTLY without importing the fill simulator.
Calculates exact dollar components (spot move, entry/exit impact, entry/exit DEX fees, entry/exit priority fees)
and proves they sum exactly to net P&L.
"""

def derive_calibration_breakdown(position_size_usd: float, sol_usd: float = 107.34):
    # Real on-chain pool reserves from cached transactions on BNchF8GC...
    # Entry: Slot 456718972 (2026-10-14 05:16:35 UTC, right at logged 05:16:37 entry)
    x_entry = 1041.062831401  # SOL
    y_entry = 16641000.860614  # Tokens
    p_spot_entry = x_entry / y_entry
    p_spot_entry_usd = p_spot_entry * sol_usd
    mc_sol_entry = p_spot_entry * 1_000_000_000.0
    mc_usd_entry = mc_sol_entry * sol_usd

    # Exit: Slot 456719083 (2026-10-14 05:17:00 UTC, right at logged 05:17:01 exit)
    x_exit = 1042.080754334   # SOL
    y_exit = 16625028.626444   # Tokens
    p_spot_exit = x_exit / y_exit
    p_spot_exit_usd = p_spot_exit * sol_usd

    # Fee tier at ~62,560 SOL market cap: Tier 16 (Seasoned)
    # Tier 16 schedule: 20 bps LP, 5 bps protocol, 25 bps creator = 50 bps total
    fee_bps = 50.0
    fee_rate = fee_bps / 10000.0
    prio_fee_sol = 0.005
    prio_fee_usd = prio_fee_sol * sol_usd

    # 1. ENTRY SWAP
    # sol_to_swap is the position size in SOL
    sol_to_swap = position_size_usd / sol_usd
    # E-based model: gross swap amount = E * (1 + fee_rate) -> E = gross / (1 + fee_rate)
    eff_swap_sol_in = sol_to_swap / (1.0 + fee_rate)
    entry_dex_fee_sol = sol_to_swap - eff_swap_sol_in
    entry_dex_fee_usd = entry_dex_fee_sol * sol_usd

    # Tokens received via constant product: delta_y = y * E / (x + E)
    tokens_out = (y_entry * eff_swap_sol_in) / (x_entry + eff_swap_sol_in)
    
    # Pure AMM price impact on entry:
    # Execution price without fees: P_swap = E / delta_y = (x + E) / y
    # Initial spot price: P_spot = x / y
    # Impact rate = (P_swap - P_spot) / P_spot = E / x
    entry_price_impact_rate = eff_swap_sol_in / x_entry
    entry_price_impact_pct = entry_price_impact_rate * 100.0

    # 2. EXIT SWAP
    # Selling tokens_out back into pool at exit
    # Constant product: gross SOL out E_out = x_exit * tokens_out / (y_exit + tokens_out)
    gross_sol_out = (x_exit * tokens_out) / (y_exit + tokens_out)
    
    # Pure AMM price impact on exit:
    # Spot price: P_spot_exit = x_exit / y_exit
    # Execution price without fees: P_swap_exit = E_out / tokens_out = x_exit / (y_exit + tokens_out)
    # Impact rate = (P_spot_exit - P_swap_exit) / P_spot_exit = E_out / x_exit
    exit_price_impact_rate = gross_sol_out / x_exit
    exit_price_impact_pct = exit_price_impact_rate * 100.0

    # DEX fee on exit: fee_rate * E_out
    exit_dex_fee_sol = gross_sol_out * fee_rate
    exit_dex_fee_usd = exit_dex_fee_sol * sol_usd

    # Net proceeds to seller
    net_sol_out = gross_sol_out - exit_dex_fee_sol - prio_fee_sol
    net_usd_out = net_sol_out * sol_usd

    # Total cash invested: position size + entry priority fee
    total_capital_invested_usd = position_size_usd + prio_fee_usd
    net_pnl_usd = net_usd_out - total_capital_invested_usd
    net_return_pct = (net_pnl_usd / total_capital_invested_usd) * 100.0

    # Spot price movement on the effective swapped capital:
    # Pure AMM constant-product return before fees:
    # E_out / E_in = (x_exit / x_entry) * (y_entry / (y_exit + tokens_out)) * ...
    # Decomposition:
    # E_out = E_in * (P_spot_exit / P_spot_entry) * (1 - entry_impact) * (1 - exit_impact)
    # where entry_impact_loss = E_in * (1 - 1 / (1 + entry_impact_rate)) = E_in * entry_impact_rate / (1 + entry_price_impact_rate)
    # Exact linear decomposition of delta SOL:
    spot_move_rate = (p_spot_exit - p_spot_entry) / p_spot_entry
    ideal_proceeds_sol = eff_swap_sol_in * (p_spot_exit / p_spot_entry)
    spot_gain_sol = ideal_proceeds_sol - eff_swap_sol_in
    spot_gain_usd = spot_gain_sol * sol_usd

    entry_impact_loss_sol = ideal_proceeds_sol - (tokens_out * p_spot_exit)
    entry_impact_loss_usd = entry_impact_loss_sol * sol_usd

    exit_impact_loss_sol = (tokens_out * p_spot_exit) - gross_sol_out
    exit_impact_loss_usd = exit_impact_loss_sol * sol_usd

    # Exact dollar sum:
    # net_pnl_usd = spot_gain_usd - entry_impact_loss_usd - exit_impact_loss_usd 
    #               - entry_dex_fee_usd - exit_dex_fee_usd - 2 * prio_fee_usd
    sum_components = (
        spot_gain_usd
        - entry_impact_loss_usd
        - exit_impact_loss_usd
        - entry_dex_fee_usd
        - exit_dex_fee_usd
        - 2 * prio_fee_usd
    )

    return {
        "position_size_usd": position_size_usd,
        "sol_usd": sol_usd,
        "entry_reserves": (x_entry, y_entry),
        "exit_reserves": (x_exit, y_exit),
        "spot_price_entry_usd": p_spot_entry_usd,
        "spot_price_exit_usd": p_spot_exit_usd,
        "spot_move_pct": spot_move_rate * 100.0,
        "spot_move_usd": spot_gain_usd,
        "entry_price_impact_pct": entry_price_impact_pct,
        "entry_price_impact_usd": entry_impact_loss_usd,
        "entry_dex_fee_usd": entry_dex_fee_usd,
        "entry_prio_fee_usd": prio_fee_usd,
        "exit_price_impact_pct": exit_price_impact_pct,
        "exit_price_impact_usd": exit_impact_loss_usd,
        "exit_dex_fee_usd": exit_dex_fee_usd,
        "exit_prio_fee_usd": prio_fee_usd,
        "total_fees_usd": entry_dex_fee_usd + exit_dex_fee_usd + 2 * prio_fee_usd,
        "net_proceeds_usd": net_usd_out,
        "net_pnl_usd": net_pnl_usd,
        "net_return_pct": net_return_pct,
        "sum_components_usd": sum_components,
        "reconciliation_diff_usd": abs(net_pnl_usd - sum_components),
    }

if __name__ == "__main__":
    for size in [91.19, 184.89]:
        res = derive_calibration_breakdown(size)
        print(f"\n=======================================================")
        print(f"POSITION SIZE: ${size:.2f} (SOL/USD: ${res['sol_usd']:.2f})")
        print(f"=======================================================")
        print(f"Entry Reserves: {res['entry_reserves'][0]:.4f} SOL | {res['entry_reserves'][1]:.2f} Tokens")
        print(f"Exit Reserves:  {res['exit_reserves'][0]:.4f} SOL | {res['exit_reserves'][1]:.2f} Tokens")
        print(f"Spot Price Move: {res['spot_move_pct']:+.4f}% (${res['spot_move_usd']:+.4f})")
        print(f"Entry Price Impact: {res['entry_price_impact_pct']:.4f}% (-${res['entry_price_impact_usd']:.4f})")
        print(f"Entry DEX Fee (50 bps): -${res['entry_dex_fee_usd']:.4f}")
        print(f"Entry Priority Fee (0.005 SOL): -${res['entry_prio_fee_usd']:.4f}")
        print(f"Exit Price Impact: {res['exit_price_impact_pct']:.4f}% (-${res['exit_price_impact_usd']:.4f})")
        print(f"Exit DEX Fee (50 bps): -${res['exit_dex_fee_usd']:.4f}")
        print(f"Exit Priority Fee (0.005 SOL): -${res['exit_prio_fee_usd']:.4f}")
        print(f"-------------------------------------------------------")
        print(f"Sum of Components:     ${res['sum_components_usd']:+.4f}")
        print(f"Net Realized PnL:      ${res['net_pnl_usd']:+.4f}")
        print(f"Net Realized Return:   {res['net_return_pct']:+.4f}%")
        print(f"Reconciliation Diff:   ${res['reconciliation_diff_usd']:.6f}")

"""
Unit tests for Venue-Aware AMM Execution Scaling across $25 to $1,000 Position Sizes
Guarantees strictly decreasing executable multiples and strictly increasing price impact as size scales.
"""

import pytest
from src.research.execution import AMMExecutionSimulator


def test_strictly_decreasing_executable_multiple_with_size():
    """
    CRITICAL REGRESSION TEST:
    Verify that for finite pool liquidity, position sizes ($25, $50, $100, $250, $500, $1,000)
    produce strictly decreasing executable multiples (Executable MFE) due to price impact.
    """
    sim = AMMExecutionSimulator()
    entry_mc = 15000.0
    exit_mc = 3000000.0 # 200x theoretical runner
    entry_liq = 4000.0
    exit_liq = 250000.0

    sizes = [25.0, 50.0, 100.0, 250.0, 500.0, 1000.0]
    results = sim.evaluate_multi_tier_sizes(
        entry_mc=entry_mc,
        exit_mc=exit_mc,
        entry_liquidity=entry_liq,
        exit_liquidity=exit_liq,
        chain="solana",
        venue="raydium",
        position_sizes=tuple(sizes),
    )

    prev_multiple = float("inf")
    prev_entry_impact = -1.0
    prev_exit_impact = -1.0

    for sz in sizes:
        res = results[sz]
        assert res.is_executable is True

        # 1. Entry price impact must strictly increase with size
        assert res.entry_price_impact_pct > prev_entry_impact
        prev_entry_impact = res.entry_price_impact_pct

        # 2. Exit price impact must strictly increase with size
        assert res.exit_price_impact_pct > prev_exit_impact
        prev_exit_impact = res.exit_price_impact_pct

        # 3. Executable multiple must strictly decrease with size
        assert res.executable_mfe_ratio < prev_multiple
        prev_multiple = res.executable_mfe_ratio

        # 4. Executable multiple must be strictly less than theoretical 200x
        assert res.executable_mfe_ratio < 200.0

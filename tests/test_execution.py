"""
Unit tests for AMM Constant-Product Slippage, Price Impact, and Execution Engine
"""

import pytest
from src.research.execution import AMMExecutionSimulator


def test_amm_constant_product_slippage():
    """Verify price impact increases proportionally with position size."""
    sim = AMMExecutionSimulator(dex_fee_pct=0.30)

    # $100 position into $5,000 liquidity (2% impact)
    res_100 = sim.simulate_trade(
        position_size_usd=100.0,
        entry_mc=15000.0,
        exit_mc=1500000.0,
        entry_liquidity=5000.0,
        exit_liquidity=300000.0,
    )

    # $1,000 position into $5,000 liquidity (16.67% impact)
    res_1000 = sim.simulate_trade(
        position_size_usd=1000.0,
        entry_mc=15000.0,
        exit_mc=1500000.0,
        entry_liquidity=5000.0,
        exit_liquidity=300000.0,
    )

    assert res_100.is_executable is True
    assert res_100.entry_price_impact_pct == pytest.approx(3.85, 0.1)
    assert res_1000.entry_price_impact_pct == pytest.approx(28.57, 0.1)

    # Executable multiple should be strictly less than theoretical 100x multiple
    assert res_100.theoretical_mfe_ratio == 100.0
    assert res_100.executable_mfe_ratio < 100.0
    assert res_100.executable_mfe_ratio > 80.0
    assert res_1000.executable_mfe_ratio < res_100.executable_mfe_ratio


def test_insufficient_liquidity_rejection():
    """Verify trades into micro-liquidity pools (< $1,500) are rejected."""
    sim = AMMExecutionSimulator(min_pool_liquidity_usd=1500.0)

    res = sim.simulate_trade(
        position_size_usd=250.0,
        entry_mc=10000.0,
        exit_mc=100000.0,
        entry_liquidity=800.0,   # Below $1500 minimum
        exit_liquidity=20000.0,
    )

    assert res.is_executable is False
    assert res.execution_rejection_reason == "INSUFFICIENT_LIQUIDITY_DEPTH"


def test_graduation_price_anchoring_prevents_phantom_pnl():
    """
    Verify that post-graduation FDV jumps (e.g. $68k bonding curve MC -> $24M DEX FDV)
    are anchored strictly to actual fill/exit price rather than MC ratio,
    preventing multi-thousand dollar phantom profits.
    """
    sim = AMMExecutionSimulator()

    # Case: Token graduates from PumpFun bonding curve to Raydium
    # Recorded entry MC: $68,643 (bonding curve metric)
    # Recorded exit MC: $24,707,276 (DEX FDV, ~360x jump in reported MC)
    # Actual entry price: $0.02288
    # Actual exit price: $0.02470 (actual price gain: +7.95%)
    res = sim.simulate_trade(
        position_size_usd=100.0,
        entry_mc=68643.0,
        exit_mc=24707276.0,
        entry_liquidity=25000.0,
        exit_liquidity=500000.0,
        venue="raydium",
        entry_price=0.02288,
        exit_price=0.02470,
    )

    assert res.is_executable is True
    # Return should be ~+7.9% minus fees/impact, NOT +36,000%!
    assert res.net_realized_return_pct < 15.0
    assert res.net_realized_return_pct > 0.0
    assert res.net_realized_pnl_usd < 15.0 # ~$5-$8 profit, not $23,000+!


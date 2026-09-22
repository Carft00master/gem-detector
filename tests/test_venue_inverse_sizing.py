"""
Unit tests for Venue-Specific Analytical Inverse Trade Sizing
"""

import pytest
from src.research.execution import AMMExecutionSimulator


def test_venue_specific_inverse_trade_sizing():
    sim = AMMExecutionSimulator()

    # 1. Pump.fun virtual offset (eff_x = 2000 + 4500 = 6500)
    # S = (0.01 * 6500) / 0.99 = 65.66
    p_limits = sim.calculate_max_position_limits(liquidity_usd=4000.0, venue="pumpfun")
    assert p_limits.max_position_1pct_usd == pytest.approx(65.66, 0.05)
    assert p_limits.max_position_5pct_usd == pytest.approx((0.05 * 6500.0) / 0.95, 0.05)

    # 2. Raydium standard AMM (quote_x = 2000)
    # S = (0.01 * 2000) / 0.99 = 20.20
    r_limits = sim.calculate_max_position_limits(liquidity_usd=4000.0, venue="raydium")
    assert r_limits.max_position_1pct_usd == pytest.approx(20.20, 0.05)

    # 3. Aerodrome concentrated tick depth (eff_x = 4000)
    # S = (0.01 * 4000) / 0.99 = 40.40
    a_limits = sim.calculate_max_position_limits(liquidity_usd=4000.0, venue="aerodrome")
    assert a_limits.max_position_1pct_usd == pytest.approx(40.40, 0.05)

    # 4. Unsupported venue
    u_limits = sim.calculate_max_position_limits(liquidity_usd=4000.0, venue="unsupported_custom")
    assert u_limits.max_position_1pct_usd == 0.0

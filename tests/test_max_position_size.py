"""
Unit tests for Per-Token Maximum Executable Position Size Limits
"""

import pytest
from src.research.execution import AMMExecutionSimulator


def test_max_position_size_limit_calculations():
    sim = AMMExecutionSimulator()

    # Pool with $10,000 liquidity
    limits = sim.calculate_max_position_limits(liquidity_usd=10000.0, venue="raydium")

    # Formula: max_pos = (impact * quote_reserve) / (1 - impact)
    assert limits.max_position_1pct_usd == pytest.approx(50.51, 0.05)
    assert limits.max_position_2pct_usd == pytest.approx(102.04, 0.05)
    assert limits.max_position_5pct_usd == pytest.approx(263.16, 0.05)
    assert limits.max_position_10pct_usd == pytest.approx(555.56, 0.05)

    assert limits.max_position_1pct_usd < limits.max_position_2pct_usd < limits.max_position_5pct_usd < limits.max_position_10pct_usd

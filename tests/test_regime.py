"""
Unit tests for Macro Market Regime Engine and Segmentation
"""

import pytest
from src.engine.market_regime import MarketRegimeEngine


def test_market_regime_classification():
    # Hot Bull Regime
    hot = MarketRegimeEngine.evaluate_regime(sol_return_24h_pct=6.5, sol_return_1h_pct=1.2, token_launches_per_hour=180)
    assert hot.regime == "HOT"
    assert hot.regime_multiplier >= 1.2

    # Panic Selloff Regime
    panic = MarketRegimeEngine.evaluate_regime(sol_return_24h_pct=-14.0, sol_return_1h_pct=-6.0)
    assert panic.regime == "PANIC"
    assert panic.regime_multiplier <= 0.60
    assert "MACRO_PANIC_SELLOFF" in panic.signals

    # Cold Low Liquidity Regime
    cold = MarketRegimeEngine.evaluate_regime(sol_return_24h_pct=-5.0, token_launches_per_hour=25)
    assert cold.regime == "COLD"
    assert cold.regime_multiplier < 1.0

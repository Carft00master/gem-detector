"""
Tests for Regime-Adjusted Learning Gain and Improvement Validation.
"""

import pytest
from src.paper.performance_analytics import PerformanceAnalyticsEngine


def test_regime_adjusted_learning_gain_calculation():
    """Verify raw vs regime-adjusted win rate and PnL delta calculation."""
    # 40 early trades (mixed regimes, 30% win rate)
    early = [
        {"status": "CLOSED", "regime": "HOT" if (i % 2 == 0) else "COLD", "net_realized_pnl_usd": 50.0 if (i % 3 == 0) else -30.0}
        for i in range(40)
    ]
    # 40 recent trades (mixed regimes, 60% win rate)
    recent = [
        {"status": "CLOSED", "regime": "HOT" if (i % 2 == 0) else "COLD", "net_realized_pnl_usd": 120.0 if (i % 3 != 0) else -40.0}
        for i in range(40)
    ]

    all_trades = early + recent
    gain = PerformanceAnalyticsEngine.calculate_regime_adjusted_learning_gain(all_trades, cohort_n=40)

    assert gain.early_sample_size == 40
    assert gain.recent_sample_size == 40
    assert gain.raw_win_rate_delta_pct > 20.0
    assert gain.regime_adjusted_win_rate_delta_pct > 15.0
    assert gain.is_statistically_significant is True
    assert "GENUINE_LEARNING_GAIN" in gain.verdict

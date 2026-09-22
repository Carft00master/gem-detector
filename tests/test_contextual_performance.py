"""
Tests for 5-Dimensional Contextual Smart Wallet Performance Engine.
"""

import pytest
from src.learning.smart_money.contextual_performance import WalletContextualPerformanceEngine


def test_contextual_performance_slicing():
    """Verify performance metrics partitioning across Regime, MC, Age, Curve, and Density."""
    interactions = [
        # HOT regime, 5-10K MC, 1-5m age, 20-40% curve, 75-100th density (Winners)
        {
            "market_regime": "HOT",
            "entry_market_cap_usd": 7500.0,
            "token_age_minutes": 3.0,
            "curve_progress_pct": 30.0,
            "activity_density_percentile": 85.0,
            "realized_pnl_usd": 250.0,
            "realized_return_pct": 125.0,
            "target_100k": 1,
            "target_3m": 1,
            "mfe_ratio": 3.5,
            "mae_ratio": 0.85,
        },
        # COLD regime, 25-50K MC, 30-60m age, 60-80% curve, 0-25th density (Losers)
        {
            "market_regime": "COLD",
            "entry_market_cap_usd": 35000.0,
            "token_age_minutes": 45.0,
            "curve_progress_pct": 70.0,
            "activity_density_percentile": 20.0,
            "realized_pnl_usd": -50.0,
            "realized_return_pct": -25.0,
            "target_100k": 0,
            "target_3m": 0,
            "mfe_ratio": 1.1,
            "mae_ratio": 0.60,
        },
    ]

    report = WalletContextualPerformanceEngine.evaluate_wallet_context("TestWallet123", interactions)

    assert report.total_trades_evaluated == 2
    assert "HOT" in report.by_regime
    assert "COLD" in report.by_regime
    assert report.by_regime["HOT"].win_rate_pct == 100.0
    assert report.by_regime["COLD"].win_rate_pct == 0.0

    assert "5–10K" in report.by_market_cap
    assert "25–50K" in report.by_market_cap
    assert report.by_market_cap["5–10K"].sample_size == 1
    assert report.best_regime == "HOT"
    assert report.best_mc_range == "5–10K"

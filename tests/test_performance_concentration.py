"""
Tests for P&L Concentration Analytics and Generation x Regime Matrix.
"""

import pytest
from src.paper.performance_analytics import PerformanceAnalyticsEngine


def test_pnl_concentration_and_outlier_removal():
    """Verify top 1/5/10 trade P&L share and outlier removal metrics."""
    # 20 trades where 1 trade is a huge +$2,000 winner and others are +$50 / -$30
    trades = [
        {"status": "CLOSED", "net_realized_pnl_usd": 2000.0, "net_realized_return_pct": 800.0},
    ]
    for i in range(19):
        pnl = 50.0 if (i % 2 == 0) else -30.0
        trades.append({"status": "CLOSED", "net_realized_pnl_usd": pnl, "net_realized_return_pct": 20.0 if pnl > 0 else -12.0})

    conc = PerformanceAnalyticsEngine.calculate_pnl_concentration(trades)

    assert conc.total_closed_trades == 20
    assert conc.total_realized_pnl_usd > 2000.0
    assert conc.top_1_trade_pnl_usd == 2000.0
    assert conc.top_1_trade_pnl_share_pct > 80.0
    assert conc.is_heavily_concentrated is True
    assert conc.pnl_without_top_1_usd < 250.0


def test_generation_regime_matrix_computation():
    """Verify TRADE_GENERATION x MARKET_REGIME matrix calculation."""
    trades = []
    regimes = ["HOT", "NORMAL", "COLD"]
    for i in range(60):
        r = regimes[i % 3]
        trades.append({
            "status": "CLOSED",
            "regime": r,
            "net_realized_pnl_usd": 100.0 if r == "HOT" else (20.0 if r == "NORMAL" else -40.0),
            "net_realized_return_pct": 40.0 if r == "HOT" else (10.0 if r == "NORMAL" else -15.0),
            "mfe_ratio": 1.8 if r == "HOT" else 1.2,
            "mae_ratio": 0.9 if r == "HOT" else 0.7,
        })

    matrix = PerformanceAnalyticsEngine.calculate_generation_regime_matrix(trades, cohort_size=50)
    assert len(matrix) > 0
    # Confirm HOT regime has high win rate / PnL in matrix
    hot_cells = [c for c in matrix if c.regime == "HOT"]
    assert len(hot_cells) > 0
    assert hot_cells[0].win_rate_pct == 100.0

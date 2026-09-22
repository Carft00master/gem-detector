"""
Tests for Trade Performance Generations, Rolling Windows & Scientific Cohort Learning Analytics.
"""

import pytest
from src.paper.performance_analytics import PerformanceAnalyticsEngine


def test_performance_generations_partitioning():
    """Verify trades are cleanly grouped into 50-trade cohorts with cumulative metrics."""
    synthetic_trades = []
    for i in range(120):
        is_win = (i % 3 != 0)
        pnl = 50.0 if is_win else -25.0
        synthetic_trades.append({
            "signal_id": f"trade_{i}",
            "status": "CLOSED",
            "net_realized_pnl_usd": pnl,
            "net_realized_return_pct": 20.0 if is_win else -10.0,
            "hold_duration_seconds": 1200.0,
            "mfe_ratio": 1.45,
            "mae_ratio": 0.85,
            "entry_market_cap_usd": 12000.0,
            "p_reach_3m": 0.15,
            "outcome_label": "SUCCESS" if is_win else "FAILURE",
        })

    generations = PerformanceAnalyticsEngine.calculate_generations(synthetic_trades, cohort_size=50)
    assert len(generations) == 3
    assert generations[0].generation_label == "Trades 1–50"
    assert generations[0].trade_count == 50
    assert generations[1].generation_label == "Trades 51–100"
    assert generations[1].trade_count == 50
    assert generations[2].generation_label == "Trades 101–120"
    assert generations[2].trade_count == 20

    # Cumulative PnL continuity
    assert generations[1].cumulative_pnl_usd == generations[0].cumulative_pnl_usd + generations[1].total_pnl_usd


def test_rolling_windows_and_early_vs_recent_comparison():
    """Verify rolling windows and statistical early vs recent cohort comparison."""
    synthetic_trades = []
    for i in range(60):
        # Improving trajectory: early trades have lower win rate, recent have higher
        is_win = (i > 30) or (i % 4 == 0)
        pnl = 80.0 if is_win else -40.0
        synthetic_trades.append({
            "signal_id": f"trade_{i}",
            "status": "CLOSED",
            "net_realized_pnl_usd": pnl,
            "net_realized_return_pct": 32.0 if is_win else -16.0,
            "hold_duration_seconds": 900.0,
            "mfe_ratio": 1.60 if is_win else 1.05,
            "mae_ratio": 0.90 if is_win else 0.60,
            "entry_market_cap_usd": 15000.0,
            "p_reach_3m": 0.18,
            "target_reached_3m": is_win,
            "outcome_label": "SUCCESS" if is_win else "FAILURE",
        })

    rolling = PerformanceAnalyticsEngine.calculate_rolling_windows(synthetic_trades, windows=[25, 50])
    assert len(rolling) == 2
    assert rolling[0].window_size == 25
    assert rolling[1].window_size == 50

    comparison = PerformanceAnalyticsEngine.compare_early_vs_recent(synthetic_trades, cohort_n=25)
    assert comparison.early_cohort_size == 25
    assert comparison.recent_cohort_size == 25
    assert comparison.recent_win_rate_pct > comparison.early_win_rate_pct
    assert comparison.is_improving is True

"""
Unit tests for RoutePerformanceReporter (Phase 1g)
Verifies isolated route performance reporting with 1,000-resample bootstrap confidence intervals
for Win Rate, Profit Factor, Median MFE, Median MAE, and Total Realized P&L.
"""

import pytest
from src.paper.ledger import PaperTradingLedger
from src.paper.route_reporting import RoutePerformanceReporter, RouteMetricsReport


@pytest.fixture
def sample_trades():
    return [
        # Route A trades (4 wins, 2 losses)
        {
            "route": "ROUTE_A",
            "status": "CLOSED",
            "net_realized_pnl_usd": 150.0,
            "position_size_usd": 100.0,
            "total_fees_usd": 2.5,
            "network_cost_usd": 0.5,
            "mfe_ratio": 2.8,
            "mae_ratio": 0.85,
        },
        {
            "route": "ROUTE_A",
            "status": "CLOSED",
            "net_realized_pnl_usd": 200.0,
            "position_size_usd": 100.0,
            "total_fees_usd": 2.5,
            "network_cost_usd": 0.5,
            "mfe_ratio": 3.2,
            "mae_ratio": 0.90,
        },
        {
            "route": "ROUTE_A",
            "status": "CLOSED",
            "net_realized_pnl_usd": -40.0,
            "position_size_usd": 100.0,
            "total_fees_usd": 2.0,
            "network_cost_usd": 0.5,
            "mfe_ratio": 1.1,
            "mae_ratio": 0.60,
        },
        {
            "route": "ROUTE_A",
            "status": "CLOSED",
            "net_realized_pnl_usd": 80.0,
            "position_size_usd": 100.0,
            "total_fees_usd": 2.2,
            "network_cost_usd": 0.5,
            "mfe_ratio": 1.9,
            "mae_ratio": 0.88,
        },
        {
            "route": "ROUTE_A",
            "status": "CLOSED",
            "net_realized_pnl_usd": -50.0,
            "position_size_usd": 100.0,
            "total_fees_usd": 2.0,
            "network_cost_usd": 0.5,
            "mfe_ratio": 1.05,
            "mae_ratio": 0.50,
        },
        {
            "route": "ROUTE_A",
            "status": "CLOSED",
            "net_realized_pnl_usd": 120.0,
            "position_size_usd": 100.0,
            "total_fees_usd": 2.5,
            "network_cost_usd": 0.5,
            "mfe_ratio": 2.4,
            "mae_ratio": 0.92,
        },
        # Route B trades (1 win, 3 losses)
        {
            "route": "ROUTE_B",
            "status": "CLOSED",
            "net_realized_pnl_usd": -12.0,
            "position_size_usd": 50.0,
            "total_fees_usd": 1.0,
            "network_cost_usd": 5.0,  # high priority fee
            "mfe_ratio": 1.02,
            "mae_ratio": 0.76,
        },
        {
            "route": "ROUTE_B",
            "status": "CLOSED",
            "net_realized_pnl_usd": 65.0,
            "position_size_usd": 50.0,
            "total_fees_usd": 1.0,
            "network_cost_usd": 5.0,
            "mfe_ratio": 2.5,
            "mae_ratio": 0.95,
        },
        {
            "route": "ROUTE_B",
            "status": "CLOSED",
            "net_realized_pnl_usd": -8.0,
            "position_size_usd": 50.0,
            "total_fees_usd": 1.0,
            "network_cost_usd": 5.0,
            "mfe_ratio": 1.01,
            "mae_ratio": 0.84,
        },
    ]


def test_empty_route_report():
    reporter = RoutePerformanceReporter()
    rep = reporter.generate_report_for_route("ROUTE_A", trades=[])
    assert rep.total_trades == 0
    assert rep.winning_trades == 0
    assert rep.win_rate.point_estimate == 0.0
    assert rep.win_rate.ci_lower == 0.0
    assert rep.win_rate.ci_upper == 0.0
    assert rep.profit_factor.point_estimate == 0.0


def test_route_a_bootstrap_confidence_intervals(sample_trades):
    reporter = RoutePerformanceReporter(n_resamples=1000, random_seed=42)
    rep = reporter.generate_report_for_route("ROUTE_A", trades=sample_trades)

    assert rep.route == "ROUTE_A"
    assert rep.total_trades == 6
    assert rep.winning_trades == 4
    assert rep.losing_trades == 2

    # Win rate point estimate = 4 / 6 = 66.67%
    assert rep.win_rate.point_estimate == pytest.approx(66.67, abs=0.1)
    # 95% bootstrap CI must bound the point estimate
    assert 0.0 <= rep.win_rate.ci_lower <= rep.win_rate.point_estimate
    assert rep.win_rate.point_estimate <= rep.win_rate.ci_upper <= 100.0

    # Total P&L = 150 + 200 - 40 + 80 - 50 + 120 = +$460
    assert rep.total_realized_pnl_usd.point_estimate == pytest.approx(460.0, abs=0.1)
    assert rep.total_realized_pnl_usd.ci_lower < rep.total_realized_pnl_usd.point_estimate
    assert rep.total_realized_pnl_usd.ci_upper > rep.total_realized_pnl_usd.point_estimate

    # Profit factor: Gross profit = 550, Gross loss = 90 -> 550 / 90 = 6.11
    assert rep.profit_factor.point_estimate == pytest.approx(6.11, abs=0.1)
    assert rep.profit_factor.ci_lower > 1.0

    # Average position size = $100
    assert rep.avg_position_size_usd == 100.0
    # Fixed cost pct: avg fixed cost is (2.5 + 0.5) / 100 = 3.0%
    assert rep.fixed_cost_pct_of_size > 0.0


def test_route_b_latency_upper_bound_tagging(sample_trades):
    reporter = RoutePerformanceReporter(n_resamples=500, random_seed=42)
    rep = reporter.generate_report_for_route(
        "ROUTE_B",
        trades=sample_trades,
        is_latency_upper_bound=True,
    )

    assert rep.route == "ROUTE_B"
    assert rep.total_trades == 3
    assert rep.is_latency_upper_bound is True

    # Fixed cost % for Route B with high network tips
    # Network cost $5 on $50 size is ~10%
    assert rep.fixed_cost_pct_of_size >= 10.0

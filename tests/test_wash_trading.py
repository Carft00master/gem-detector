"""
Unit tests for Wash-Trading and Artificial Volume Detection
"""

from datetime import datetime, timezone
import pytest
from src.engine.wash_trading import TradeEvent, WashTradingDetector


def test_organic_volume_low_turnover():
    """Test realistic volume with healthy capital turnover (< 3x)."""
    now = datetime.now(timezone.utc)
    trades = [
        TradeEvent("W1", "buy", 300.0, now),
        TradeEvent("W2", "buy", 450.0, now),
        TradeEvent("W3", "buy", 200.0, now),
        TradeEvent("W4", "buy", 600.0, now),
    ]

    res = WashTradingDetector.analyze_trades(
        trades=trades,
        total_volume_usd=1550.0,
        unique_buyers_count=4,
        market_cap_usd=20000.0,
    )

    assert res.capital_turnover_ratio == 1.0
    assert res.wash_trade_risk == 0.0
    assert res.volume_quality_score == 1.0


def test_circular_wash_trading_high_turnover():
    """
    Test rapid buy-then-sell loops recycled by the same wallet inflating volume.
    $500 unique capital generating $10,000 in volume (20x turnover).
    """
    now = datetime.now(timezone.utc)
    trades = []
    for _ in range(5):
        trades.append(TradeEvent("WashBot1", "buy", 500.0, now))
        trades.append(TradeEvent("WashBot1", "sell", 490.0, now))

    res = WashTradingDetector.analyze_trades(
        trades=trades,
        total_volume_usd=10000.0,
        unique_buyers_count=1,
        market_cap_usd=15000.0,
    )

    assert res.capital_turnover_ratio >= 15.0
    assert res.wash_trade_risk >= 0.70
    assert res.volume_quality_score <= 0.30
    assert "EXTREME_CAPITAL_TURNOVER_WASH" in res.signals


def test_aggregate_metrics_organic():
    """Verify organic volume with healthy trade sizes ($50+) and low turnover passes cleanly."""
    res = WashTradingDetector.analyze_aggregate_metrics(
        volume_5m_usd=5000.0,
        txns_5m_buys=50,
        txns_5m_sells=30,
        liquidity_usd=15000.0,
        unique_buyers_count=35,
        market_cap_usd=40000.0,
    )
    assert res.avg_trade_size_usd == 62.5
    assert res.capital_turnover_ratio == 0.33
    assert res.wash_trade_risk == 0.0
    assert res.volume_quality_score == 1.0
    assert len(res.signals) == 0


def test_aggregate_metrics_bump_bot_detected():
    """Verify bump bot micro-churn ($1.50 across 60 txns) is flagged with high wash risk."""
    res = WashTradingDetector.analyze_aggregate_metrics(
        volume_5m_usd=90.0,
        txns_5m_buys=45,
        txns_5m_sells=15,
        liquidity_usd=10000.0,
        unique_buyers_count=8,
        market_cap_usd=25000.0,
    )
    assert res.avg_trade_size_usd == 1.50
    assert res.wash_trade_risk >= 0.60
    assert "BUMP_BOT_MICRO_CHURN" in res.signals


def test_aggregate_metrics_hyper_turnover_detected():
    """Verify hyper-turnover circular volume (4.5x pool liquidity) is flagged with high wash risk."""
    res = WashTradingDetector.analyze_aggregate_metrics(
        volume_5m_usd=45000.0,
        txns_5m_buys=80,
        txns_5m_sells=80,
        liquidity_usd=10000.0,
        unique_buyers_count=25,
        market_cap_usd=30000.0,
    )
    assert res.turnover_5m_ratio == 4.5
    assert res.wash_trade_risk >= 0.50
    assert "HYPER_TURNOVER_WASH_VOLUME" in res.signals


def test_aggregate_metrics_nascent_pool_exempt():
    """
    Verify brand-new pools with low initial trades (e.g. 6 txns totaling $3.50)
    are exempt from bump-bot micro-churn rejection.
    """
    res = WashTradingDetector.analyze_aggregate_metrics(
        volume_5m_usd=3.50,
        txns_5m_buys=5,
        txns_5m_sells=1,
        liquidity_usd=8000.0,
        unique_buyers_count=4,
        market_cap_usd=12000.0,
    )
    assert res.avg_trade_size_usd == 0.58
    assert "BUMP_BOT_MICRO_CHURN" not in res.signals
    assert res.wash_trade_risk == 0.0

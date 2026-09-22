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

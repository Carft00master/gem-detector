"""
Unit tests for Order-Flow Quality and Trade-Size Shannon Entropy
"""

import pytest
from src.engine.order_flow import OrderFlowEngine


def test_organic_retail_order_flow():
    # Diverse trade sizes spanning multiple log tiers
    trade_sizes = [15.0, 45.0, 75.0, 150.0, 300.0, 800.0, 1200.0, 35.0, 90.0, 250.0]
    of = OrderFlowEngine.evaluate(
        txns_buys=60,
        txns_sells=20,
        volume_usd=5000.0,
        unique_buyers=50,
        unique_sellers=15,
        liquidity_usd=4000.0,
        token_age_minutes=25.0,
        raw_trade_sizes=trade_sizes,
    )

    assert of.volume_weighted_buy_ratio == 0.75
    assert of.buyer_seller_wallet_ratio > 3.0
    assert of.trade_size_entropy > 1.0  # Diverse entropy
    assert of.order_flow_quality_score >= 0.70
    assert "ORGANIC_TRADE_ENTROPY" in of.signals


def test_uniform_bot_low_entropy_penalized():
    # Exactly identical trade sizes (bot wash-trading signature)
    trade_sizes = [50.0, 50.0, 50.0, 50.0, 50.0, 50.0, 50.0, 50.0]
    of = OrderFlowEngine.evaluate(
        txns_buys=50,
        txns_sells=10,
        volume_usd=3000.0,
        unique_buyers=5,
        unique_sellers=2,
        liquidity_usd=2000.0,
        token_age_minutes=15.0,
        raw_trade_sizes=trade_sizes,
    )

    assert of.trade_size_entropy == 0.0  # Pure 0 entropy
    assert "LOW_ENTROPY_BOT_PATTERN" in of.signals
    assert of.order_flow_quality_score < 0.50

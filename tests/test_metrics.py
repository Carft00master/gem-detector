"""
Unit tests for MetricsEngine
"""

import pytest
from src.engine.metrics import MetricsEngine


def test_evaluate_vol_mc_ratio():
    # Optimal velocity (0.8x to 3.5x)
    score, sig = MetricsEngine.evaluate_vol_mc_ratio(1.5)
    assert score == 1.0
    assert sig == "OPTIMAL_VELOCITY"

    # Moderate velocity
    score, sig = MetricsEngine.evaluate_vol_mc_ratio(0.6)
    assert score == 0.75
    assert sig == "MODERATE_VOLUME"

    # High volume
    score, sig = MetricsEngine.evaluate_vol_mc_ratio(4.5)
    assert score == 0.70
    assert sig == "HIGH_VOLUME"

    # Wash trading risk
    score, sig = MetricsEngine.evaluate_vol_mc_ratio(8.5)
    assert score == 0.25
    assert sig == "WASH_TRADING_RISK"

    # No volume
    score, sig = MetricsEngine.evaluate_vol_mc_ratio(0.0)
    assert score == 0.0
    assert sig == "NO_VOLUME"


def test_evaluate_order_flow():
    # Bullish heavy order flow
    score, sigs = MetricsEngine.evaluate_order_flow(
        buy_sell_ratio=2.2,
        buyer_seller_ratio=1.9,
        unique_buyers=65,
    )
    assert score == 1.0
    assert "HEAVY_BUY_PRESSURE" in sigs
    assert "ORGANIC_WALLET_INFLOW" in sigs
    assert "STRONG_HOLDER_BASE" in sigs

    # Weak order flow
    score, sigs = MetricsEngine.evaluate_order_flow(
        buy_sell_ratio=0.7,
        buyer_seller_ratio=0.8,
        unique_buyers=10,
    )
    assert score < 0.2
    assert "NET_SELLING_PRESSURE" in sigs
    assert "SELLER_DOMINANCE" in sigs
    assert "THIN_BUYER_BASE" in sigs


def test_evaluate_liquidity():
    # Healthy locked LP
    score, sigs = MetricsEngine.evaluate_liquidity(
        liquidity_usd=8000.0,
        liquidity_mc_ratio=0.25,
        lp_burned_pct=100.0,
    )
    assert score == 1.0
    assert "DEEP_LIQUIDITY_BACKING" in sigs
    assert "LP_100_LOCKED_BURNED" in sigs

    # Unlocked LP / Thin
    score, sigs = MetricsEngine.evaluate_liquidity(
        liquidity_usd=500.0,
        liquidity_mc_ratio=0.05,
        lp_burned_pct=0.0,
    )
    assert score <= 0.1
    assert "THIN_LIQUIDITY_HIGH_SLIPPAGE" in sigs
    assert "LP_UNLOCKED_RUG_RISK" in sigs


def test_evaluate_holder_decentralization():
    # Clean decentralized token with dev exit
    score, sigs = MetricsEngine.evaluate_holder_decentralization(
        top10_pct=14.0,
        dev_holding_pct=0.0,
        dev_sold_all=True,
    )
    assert score == 1.0
    assert "EXCELLENT_DISTRIBUTION" in sigs
    assert "DEV_CLEAN_EXIT" in sigs

    # Heavily concentrated token
    score, sigs = MetricsEngine.evaluate_holder_decentralization(
        top10_pct=45.0,
        dev_holding_pct=12.0,
        dev_sold_all=False,
    )
    assert score == 0.0
    assert "HIGH_TOP10_CONCENTRATION" in sigs
    assert "DEV_HOLDS_LARGE_SUPPLY" in sigs

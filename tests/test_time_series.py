"""
Unit tests for Time-Series & Derivative Feature Extraction
"""

import pytest
from src.engine.features import FeatureExtractor
from src.feeds.base_feed import TokenCandidate


def test_time_series_feature_extraction():
    cand = TokenCandidate(
        address="SoTestToken",
        pair_address="PairTest",
        symbol="TEST",
        name="Test Token",
        chain="solana",
        dex_id="pumpfun",
        market_cap_usd=20000.0,
        price_usd=0.0002,
        liquidity_usd=5000.0,
        volume_5m_usd=2400.0,
        volume_1h_usd=12000.0,
        txns_5m_buys=30,
        txns_5m_sells=10,
        unique_buyers_1h=45,
        unique_sellers_1h=15,
        age_minutes=20.0,
    )
    cand.calculate_ratios()

    price_history = [
        {"price_usd": 0.00010, "elapsed_minutes": 0.0},
        {"price_usd": 0.00012, "elapsed_minutes": 5.0},
        {"price_usd": 0.00011, "elapsed_minutes": 10.0},
        {"price_usd": 0.00016, "elapsed_minutes": 15.0},
        {"price_usd": 0.00020, "elapsed_minutes": 20.0},
    ]

    feats = FeatureExtractor.extract_from_candidate(cand, price_history)

    assert feats.volume_mc_ratio_5m == pytest.approx(0.12, 0.01)
    assert feats.volume_persistence_ratio >= 1.5  # 2400 / (12000/12 = 1000) = 2.4
    assert feats.return_5m > 0.0
    assert feats.higher_highs_count >= 2
    assert feats.new_holders_per_min > 1.5
    assert "return_5m" in feats.to_dict()

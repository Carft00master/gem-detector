"""
Unit tests for Data Confidence and Telemetry Scorer
"""

import pytest
from src.engine.data_confidence import DataConfidenceEngine
from src.feeds.base_feed import TokenCandidate


def test_data_confidence_scoring():
    # Fresh candidate with deep history
    fresh_cand = TokenCandidate(
        address="FreshMint",
        pair_address="Pair",
        symbol="FRESH",
        name="Fresh",
        chain="solana",
        dex_id="raydium",
        market_cap_usd=25000.0,
        price_usd=0.00025,
        liquidity_usd=8000.0,
        volume_5m_usd=3000.0,
        txns_5m_buys=25,
        txns_5m_sells=5,
        age_minutes=15.0,
    )

    conf_fresh = DataConfidenceEngine.evaluate(fresh_cand, rpc_latency_ms=80.0, data_age_seconds=3.0)
    assert conf_fresh.data_confidence_score >= 0.85
    assert conf_fresh.sample_size_score == 1.0

    # Stale candidate with missing volume and high RPC latency
    stale_cand = TokenCandidate(
        address="StaleMint",
        pair_address="Pair",
        symbol="STALE",
        name="Stale",
        chain="solana",
        dex_id="unknown",
        market_cap_usd=5000.0,
        price_usd=0.00005,
        liquidity_usd=300.0,
        volume_5m_usd=0.0,
        volume_1h_usd=0.0,
        txns_5m_buys=0,
        txns_5m_sells=0,
        age_minutes=0.5,
    )

    conf_stale = DataConfidenceEngine.evaluate(stale_cand, rpc_latency_ms=3000.0, data_age_seconds=400.0)
    assert conf_stale.data_confidence_score < 0.50
    assert "HIGHLY_STALE_DATA_DEGRADED" in conf_stale.signals
    assert "HIGH_RPC_LATENCY_LAG" in conf_stale.signals

"""
Unit tests for Wallet Graph, Funder Clustering, and Effective Top-10 Concentration
"""

from datetime import datetime, timezone
import pytest
from src.engine.wallet_graph import WalletGraphEngine, WalletNode


def test_independent_retail_wallets():
    """Test organic decentralized token with distinct funders and random buy timings."""
    wallets = [
        WalletNode("W1", 3.0, funding_source="FunderA", first_buy_timestamp=datetime(2026, 8, 24, 10, 0, 0)),
        WalletNode("W2", 2.5, funding_source="FunderB", first_buy_timestamp=datetime(2026, 8, 24, 10, 1, 30)),
        WalletNode("W3", 2.0, funding_source="FunderC", first_buy_timestamp=datetime(2026, 8, 24, 10, 3, 45)),
        WalletNode("W4", 1.8, funding_source="FunderD", first_buy_timestamp=datetime(2026, 8, 24, 10, 6, 12)),
        WalletNode("W5", 1.5, funding_source="FunderE", first_buy_timestamp=datetime(2026, 8, 24, 10, 9, 20)),
    ]

    res = WalletGraphEngine.analyze_wallets(wallets)

    assert res.raw_top10_pct == 10.8
    assert res.effective_top10_pct == 10.8  # No clustering
    assert res.wallet_independence_score >= 0.90
    assert res.cabal_risk_score <= 0.10


def test_cabal_common_funder_sybil_bundling():
    """
    Test cabal splitting 30% of supply across 10 wallets (3% each) funded by the exact same funder wallet.
    Raw top 10 would look like only 30%, but effective concentration detects the 30% single-cluster monopoly.
    """
    wallets = []
    for i in range(10):
        wallets.append(
            WalletNode(
                address=f"Sybil_{i}",
                holding_pct=3.0,
                funding_source="CabalMasterWallet",
                first_buy_timestamp=datetime(2026, 8, 24, 10, 0, i % 2), # Synchronized buy
            )
        )

    res = WalletGraphEngine.analyze_wallets(wallets)

    assert res.raw_top10_pct == 30.0
    assert res.largest_cluster_pct == 30.0  # Combined into 1 single 30% economic cluster
    assert res.cabal_risk_score >= 0.60
    assert res.wallet_independence_score <= 0.40
    assert "COMMON_FUNDER_CABAL_RISK" in res.signals

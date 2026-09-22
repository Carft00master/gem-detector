"""
Unit tests for Funding Entity Classification and False Cabal Avoidance
"""

from datetime import datetime, timezone
import pytest
from src.engine.wallet_graph import FundingEntityType, WalletGraphEngine, WalletNode


def test_exchange_funded_wallets_do_not_form_cabal():
    """
    Verify that multiple organic retail buyers who funded from Binance or Coinbase
    are NOT falsely clustered as a coordinated cabal.
    """
    wallets = [
        WalletNode("W1", 3.0, funding_source="Binance_Hot_Wallet_1", first_buy_timestamp=datetime(2026, 8, 24, 10, 0, 0)),
        WalletNode("W2", 2.8, funding_source="Binance_Hot_Wallet_1", first_buy_timestamp=datetime(2026, 8, 24, 10, 2, 0)),
        WalletNode("W3", 2.5, funding_source="Coinbase_Hot_Wallet_2", first_buy_timestamp=datetime(2026, 8, 24, 10, 5, 0)),
        WalletNode("W4", 2.0, funding_source="OKX_Hot_Wallet", first_buy_timestamp=datetime(2026, 8, 24, 10, 8, 0)),
    ]

    res = WalletGraphEngine.analyze_wallets(wallets)

    assert res.exchange_funded_wallets_count == 4
    # Zero coordinator wallets identified (Binance is recognized as public exchange)
    assert len(res.coordinator_wallets) == 0
    # Wallets remain independent (largest cluster is single wallet 3.0%)
    assert res.largest_cluster_pct == 3.0
    assert res.cabal_risk_score <= 0.15
    assert "ORGANIC_EXCHANGE_FUNDED_WALLETS" in res.signals


def test_private_coordinator_cabal_detected():
    """
    Verify that multiple wallets funded by the same UNKNOWN private address
    ARE properly clustered and flagged as a coordinator cabal.
    """
    wallets = [
        WalletNode("W1", 4.0, funding_source="0xPrivateSniperCoordinator999", first_buy_timestamp=datetime(2026, 8, 24, 10, 0, 0)),
        WalletNode("W2", 4.0, funding_source="0xPrivateSniperCoordinator999", first_buy_timestamp=datetime(2026, 8, 24, 10, 0, 1)),
        WalletNode("W3", 4.0, funding_source="0xPrivateSniperCoordinator999", first_buy_timestamp=datetime(2026, 8, 24, 10, 0, 2)),
    ]

    res = WalletGraphEngine.analyze_wallets(wallets)

    assert len(res.coordinator_wallets) == 1
    assert res.largest_cluster_pct == 12.0  # 4.0 + 4.0 + 4.0 merged
    assert res.cabal_risk_score >= 0.35
    assert "PRIVATE_COORDINATOR_CABAL_RISK" in res.signals

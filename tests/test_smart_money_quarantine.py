"""
Tests for Smart Money Temporal Quarantine, Tri-Split Datasets & Zero-Leakage Invariants.
"""

import pytest
from src.learning.smart_money.quarantine import SmartMoneyQuarantineManager, TriSplitSmartMoneyDatasets


def test_tri_split_dataset_zero_overlap():
    """Verify tri-split datasets (discovery, validation, evaluation) have zero token overlap."""
    synthetic_tokens = [
        {"token_address": f"Tok_{i:03d}", "discovery_timestamp": f"2026-08-{i%28+1:02d}T10:00:00Z"}
        for i in range(100)
    ]

    splits = SmartMoneyQuarantineManager.create_tri_split_datasets(
        tokens=synthetic_tokens,
        discovery_ratio=0.40,
        validation_ratio=0.30,
    )

    assert splits.is_leakage_free is True
    assert len(splits.discovery_dataset) == 40
    assert len(splits.validation_dataset) == 30
    assert len(splits.evaluation_dataset) == 30

    # Assert mutual exclusivity of token sets
    assert len(splits.discovery_token_addresses & splits.validation_token_addresses) == 0
    assert len(splits.discovery_token_addresses & splits.evaluation_token_addresses) == 0
    assert len(splits.validation_token_addresses & splits.evaluation_token_addresses) == 0


def test_wallet_discovery_quarantine_blocks_discovery_token():
    """Verify that a wallet discovered on Token A is strictly blocked from scoring Token A."""
    mgr = SmartMoneyQuarantineManager()
    wallet = "WalletQuarantineAlpha"
    token_a = "TokenDiscovery_A"
    token_b = "TokenForward_B"

    # Register discovery of wallet on Token A at timestamp T0
    mgr.register_discovery_quarantine(
        wallet_address=wallet,
        token_address=token_a,
        token_timestamp="2026-08-01T12:00:00Z",
    )

    # 1. Scoring on discovery token A must be strictly BLOCKED
    is_elig_a, reason_a = mgr.is_wallet_eligible_for_token(
        wallet_address=wallet,
        token_address=token_a,
        evaluation_timestamp="2026-08-05T12:00:00Z",
    )
    assert is_elig_a is False
    assert "DISCOVERY_TOKEN_QUARANTINE" in reason_a

    # 2. Scoring on a prior or concurrent timestamp must be BLOCKED
    is_elig_early, reason_early = mgr.is_wallet_eligible_for_token(
        wallet_address=wallet,
        token_address=token_b,
        evaluation_timestamp="2026-08-01T10:00:00Z",  # Before discovery
    )
    assert is_elig_early is False
    assert "BLOCKED_PRIOR_TO_ELIGIBILITY_TIMESTAMP" in reason_early

    # 3. Scoring on a subsequent token B after discovery timestamp must be ALLOWED
    is_elig_b, reason_b = mgr.is_wallet_eligible_for_token(
        wallet_address=wallet,
        token_address=token_b,
        evaluation_timestamp="2026-08-05T12:00:00Z",  # After discovery
    )
    assert is_elig_b is True
    assert reason_b == "ELIGIBLE_FORWARD_SIGNAL"


def test_token_quarantine_flag():
    """Verify that tokens used for wallet discovery are flagged as quarantined."""
    mgr = SmartMoneyQuarantineManager()
    mgr.register_discovery_quarantine("WalletX", "TokQuarantine1", "2026-08-01T10:00:00Z")

    assert mgr.is_token_quarantined("TokQuarantine1") is True
    assert mgr.is_token_quarantined("TokUnrelated2") is False

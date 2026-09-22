"""
Unit tests for Tier 2 Live On-Chain Fill Validation
"""

import pytest
from src.research.execution import AMMExecutionSimulator
from src.research.onchain_fill_validation import LiveOnChainFillValidator


def test_onchain_fill_validator_live_accuracy():
    sim = AMMExecutionSimulator()
    validator = LiveOnChainFillValidator(sim)

    report = validator.audit_live_fills()

    assert report.total_live_txs_audited > 0
    # Median fill error must be within 0.50%
    assert report.median_fill_error_pct <= 0.50
    # P95 fill error must be within 1.50%
    assert report.p95_fill_error_pct <= 1.50
    assert report.is_live_fill_accuracy_validated is True

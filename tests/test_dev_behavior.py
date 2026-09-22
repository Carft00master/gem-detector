"""
Unit tests for Developer & Deployer Behavior Engine
"""

import pytest
from src.engine.dev_behavior import DevBehaviorEngine


def test_clean_dev_exit_strong_classification():
    rep = DevBehaviorEngine.evaluate_dev(
        initial_allocation_pct=3.0,
        current_holding_pct=0.0,
        number_of_sells=3,
        transferred_to_subwallets=False,
    )
    assert rep.classification == "STRONG"
    assert rep.dev_risk_score <= 0.15
    assert rep.pct_supply_sold == 100.0
    assert "DEV_COMPLETELY_EXITED_CLEAN" in rep.signals


def test_dev_dump_critical_classification():
    rep = DevBehaviorEngine.evaluate_dev(
        initial_allocation_pct=20.0,
        current_holding_pct=12.0,
        number_of_sells=1,
        transferred_to_subwallets=True,
    )
    assert rep.classification == "CRITICAL"
    assert rep.dev_risk_score >= 0.70
    assert "DEV_HOLDS_CRITICAL_SUPPLY" in rep.signals
    assert "DEV_SUBWALLET_TRANSFER_STEALTH_RISK" in rep.signals

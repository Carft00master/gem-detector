"""
Unit tests for CreditBudgetTracker:
- Daily call logging
- 70% budget warning
- 95% hard stop
- Persistent state reload
"""

import pytest
from src.onchain.credit_budget import CreditBudgetTracker, CreditBudgetExceededError


def test_credit_budget_tracker_basic_flow(tmp_path):
    budget_file = tmp_path / "test_budget.json"
    tracker = CreditBudgetTracker(
        storage_path=budget_file,
        monthly_budget_per_endpoint=1000,
        warn_threshold_pct=0.70,
        hard_stop_threshold_pct=0.95,
    )

    eid = "rpc_0"
    alias = "Endpoint 0 [REDACTED]"
    assert tracker.can_call(eid, alias) is True

    # Record 500 calls (50%) -> no warning, can call
    tracker.record_call(eid, credits=500, masked_alias=alias)
    usage = tracker.get_endpoint_usage(eid)
    assert usage["monthly_calls"] == 500
    assert usage["pct_used"] == 50.0
    assert usage["is_warned_70"] is False
    assert usage["is_stopped_95"] is False
    assert tracker.can_call(eid) is True

    # Record 200 more (700 total = 70%) -> warning flag set
    tracker.record_call(eid, credits=200, masked_alias=alias)
    usage = tracker.get_endpoint_usage(eid)
    assert usage["monthly_calls"] == 700
    assert usage["pct_used"] == 70.0
    assert usage["is_warned_70"] is True
    assert usage["is_stopped_95"] is False
    assert tracker.can_call(eid) is True

    # Record 250 more (950 total = 95%) -> hard stop
    tracker.record_call(eid, credits=250, masked_alias=alias)
    usage = tracker.get_endpoint_usage(eid)
    assert usage["monthly_calls"] == 950
    assert usage["pct_used"] == 95.0
    assert usage["is_stopped_95"] is True
    assert tracker.can_call(eid) is False

    # Calling record_call again should raise CreditBudgetExceededError
    with pytest.raises(CreditBudgetExceededError):
        tracker.record_call(eid, credits=1, masked_alias=alias)


def test_credit_budget_persistence(tmp_path):
    budget_file = tmp_path / "test_budget.json"
    tracker1 = CreditBudgetTracker(storage_path=budget_file, monthly_budget_per_endpoint=1000)
    tracker1.record_call("endpoint_alpha", credits=350, masked_alias="Alpha [REDACTED]")

    # Instantiate new tracker pointing to same file
    tracker2 = CreditBudgetTracker(storage_path=budget_file, monthly_budget_per_endpoint=1000)
    usage = tracker2.get_endpoint_usage("endpoint_alpha")
    assert usage["monthly_calls"] == 350
    assert usage["alias"] == "Alpha [REDACTED]"

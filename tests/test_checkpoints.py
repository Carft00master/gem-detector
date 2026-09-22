"""
Unit tests for Automated Live Milestone Checkpoints
"""

import pytest
from src.research.checkpoints import LiveMilestoneTracker


def test_milestone_checkpoints_trigger(tmp_path):
    tracker = LiveMilestoneTracker(checkpoints_dir=tmp_path)

    # 1. Below milestone (N=15) -> None
    recs_15 = [{"token_address": f"tok_{i}", "market_cap_usd": 15000.0} for i in range(15)]
    res1 = tracker.evaluate_checkpoints(recs_15)
    assert res1 is None

    # 2. At milestone N=25 -> Triggers CheckpointReport
    recs_25 = [{"token_address": f"tok_{i}", "market_cap_usd": 15000.0, "target_3m": int(i < 2)} for i in range(25)]
    res2 = tracker.evaluate_checkpoints(recs_25)
    assert res2 is not None
    assert res2.milestone_n == 25
    assert res2.sample_size == 25
    assert res2.guardrail_status == "PRELIMINARY / INSUFFICIENT LIVE SAMPLE (N < 100)"

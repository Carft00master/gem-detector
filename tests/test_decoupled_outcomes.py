"""
Unit tests for Decoupled Target Milestones vs Independent Risk Events
"""

import pytest
from src.research.outcomes import TargetOutcomes, TrajectoryEvaluator


def test_target_reached_with_subsequent_dev_dump():
    """
    Verify that a token reaching $3M and sustaining it before an eventual dev dump
    correctly records both TARGET_SURVIVABLE_3M = True and DEV_DUMP_EVENT = True.
    """
    # 15 observations: Discovery at $15K -> Runner to $3.5M -> Dev dumps at minute 180
    obs = [
        {"market_cap_usd": 15000.0, "liquidity_usd": 4000.0, "elapsed_minutes": 0.0, "timestamp": "2026-08-24T12:00:00Z"},
        {"market_cap_usd": 80000.0, "liquidity_usd": 15000.0, "elapsed_minutes": 15.0, "timestamp": "2026-08-24T12:15:00Z"},
        {"market_cap_usd": 450000.0, "liquidity_usd": 60000.0, "elapsed_minutes": 45.0, "timestamp": "2026-08-24T12:45:00Z"},
        {"market_cap_usd": 1200000.0, "liquidity_usd": 150000.0, "elapsed_minutes": 75.0, "timestamp": "2026-08-24T13:15:00Z"},
        {"market_cap_usd": 3200000.0, "liquidity_usd": 300000.0, "elapsed_minutes": 110.0, "timestamp": "2026-08-24T13:50:00Z"},
        {"market_cap_usd": 3500000.0, "liquidity_usd": 320000.0, "elapsed_minutes": 120.0, "timestamp": "2026-08-24T14:00:00Z"}, # Sustained 10 mins
        {"market_cap_usd": 200000.0, "liquidity_usd": 2000.0, "elapsed_minutes": 180.0, "timestamp": "2026-08-24T15:00:00Z", "is_dev_dump": True, "dev_dump_pct": 12.0},
    ]

    outcomes = TrajectoryEvaluator.evaluate(obs, initial_market_cap=15000.0, min_persistence_minutes=5.0)

    # 1. Target milestones must be achieved
    assert outcomes.target_touch_3m is True
    assert outcomes.target_persistent_3m is True
    assert outcomes.target_survivable_3m is True
    assert outcomes.target_3m is True
    assert outcomes.time_to_3m_min == 110.0

    # 2. Risk event must be independently logged
    assert outcomes.dev_dump_event is True
    assert outcomes.drawdown_75pct_event is True

    # 3. Horizon-specific flags
    assert outcomes.target_3m_15m is False # Reached at 110m, not 15m
    assert outcomes.target_3m_1h is False
    assert outcomes.target_3m_6h is True   # 110m <= 360m
    assert outcomes.target_3m_24h is True

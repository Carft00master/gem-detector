"""
Unit tests for Target Outcomes, Trajectory Evaluation, Persistence, and Drawdowns
"""

import pytest
from src.research.outcomes import TargetOutcomes, TrajectoryEvaluator


def test_target_3m_runner_with_persistence():
    """Test a true 300x breakout reaching $3M and persisting without catastrophic pre-target dump."""
    observations = [
        {"elapsed_minutes": 0.0, "market_cap_usd": 10000.0, "liquidity_usd": 2500.0},
        {"elapsed_minutes": 15.0, "market_cap_usd": 55000.0, "liquidity_usd": 12000.0},
        {"elapsed_minutes": 30.0, "market_cap_usd": 120000.0, "liquidity_usd": 28000.0},
        {"elapsed_minutes": 60.0, "market_cap_usd": 550000.0, "liquidity_usd": 95000.0},
        {"elapsed_minutes": 90.0, "market_cap_usd": 1200000.0, "liquidity_usd": 220000.0},
        {"elapsed_minutes": 120.0, "market_cap_usd": 3200000.0, "liquidity_usd": 550000.0},
        {"elapsed_minutes": 135.0, "market_cap_usd": 3400000.0, "liquidity_usd": 580000.0},
        {"elapsed_minutes": 150.0, "market_cap_usd": 3100000.0, "liquidity_usd": 530000.0},
    ]

    outcomes = TrajectoryEvaluator.evaluate(observations, initial_market_cap=10000.0)

    assert outcomes.target_50k is True
    assert outcomes.target_100k is True
    assert outcomes.target_500k is True
    assert outcomes.target_1m is True
    assert outcomes.target_3m is True
    assert outcomes.is_valid_3m_runner is True
    assert outcomes.time_to_3m_min == 120.0
    assert outcomes.mfe_ratio == 340.0
    assert outcomes.persistence_3m_minutes >= 15.0
    assert outcomes.had_catastrophic_pre_target_drawdown is False


def test_wick_above_3m_rejected():
    """Test that a momentary 1-second wick that instantly crashes is rejected by persistence filter."""
    observations = [
        {"elapsed_minutes": 0.0, "market_cap_usd": 10000.0, "liquidity_usd": 2500.0},
        {"elapsed_minutes": 10.0, "market_cap_usd": 3100000.0, "liquidity_usd": 5000.0},
        {"elapsed_minutes": 11.0, "market_cap_usd": 20000.0, "liquidity_usd": 1000.0},  # Instant dump
    ]

    outcomes = TrajectoryEvaluator.evaluate(observations, initial_market_cap=10000.0, min_persistence_minutes=5.0)

    assert outcomes.target_3m is True
    # Should NOT be classified as valid runner due to lack of persistence (< 5 min)
    assert outcomes.is_valid_3m_runner is False


def test_pre_target_catastrophic_drawdown_penalty():
    """Test that a token dumping > 80% before eventually pumping is flagged."""
    observations = [
        {"elapsed_minutes": 0.0, "market_cap_usd": 50000.0, "liquidity_usd": 10000.0},
        {"elapsed_minutes": 20.0, "market_cap_usd": 5000.0, "liquidity_usd": 800.0},   # 90% dump
        {"elapsed_minutes": 120.0, "market_cap_usd": 3500000.0, "liquidity_usd": 400000.0},
    ]

    outcomes = TrajectoryEvaluator.evaluate(observations, initial_market_cap=50000.0, catastrophic_drawdown_limit_pct=75.0)

    assert outcomes.target_3m is True
    assert outcomes.had_catastrophic_pre_target_drawdown is True
    assert outcomes.is_valid_3m_runner is False

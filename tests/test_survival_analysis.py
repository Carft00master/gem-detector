"""
Unit tests for Survival Analysis, Time-to-Event Modeling, TokenLifecycleState, and Eventual Horizon Integrity
"""

import pytest
from src.research.outcome_maturity import CanonicalOutcomeMaturityEngine, TokenLifecycleState
from src.research.survival_analysis import SurvivalAnalysisEngine


def test_active_token_cannot_become_eventual_failure():
    # Active token with liquidity and normal trading, discovered 45 minutes ago
    rec = {
        "token_address": "tok_active_live",
        "elapsed_minutes": 45.0,
        "market_cap_usd": 25000.0,
        "liquidity_usd": 4000.0,
        "volume_1h_usd": 12000.0,
        "p_rug": 0.05,
    }
    state = CanonicalOutcomeMaturityEngine.evaluate_token_maturity(rec, target_name="TARGET_3M", horizon_name="eventual")
    assert state.lifecycle_state == TokenLifecycleState.ACTIVE.value
    assert state.is_mature is False
    assert state.outcome_status == "PENDING"  # NEVER failure!


def test_unbounded_event_remains_pending_when_token_is_active():
    rec = {
        "token_address": "tok_active_24h",
        "elapsed_minutes": 1440.0,  # 24h elapsed
        "market_cap_usd": 35000.0,
        "liquidity_usd": 6000.0,
        "volume_1h_usd": 2500.0,
        "p_rug": 0.08,
    }
    # 24h fixed horizon is FAILURE (mature)
    s24h = CanonicalOutcomeMaturityEngine.evaluate_token_maturity(rec, target_name="TARGET_3M", horizon_name="24h")
    assert s24h.is_mature is True
    assert s24h.outcome_status == "FAILURE"

    # Eventual unbounded horizon is PENDING because token is still ACTIVE!
    s_eventual = CanonicalOutcomeMaturityEngine.evaluate_token_maturity(rec, target_name="TARGET_3M", horizon_name="eventual")
    assert s_eventual.is_mature is False
    assert s_eventual.outcome_status == "PENDING"


def test_terminal_token_produces_eventual_failure():
    # LP pulled / rugged token
    rec = {
        "token_address": "tok_rugged",
        "elapsed_minutes": 30.0,
        "market_cap_usd": 1000.0,
        "liquidity_usd": 10.0,  # LP drained
        "p_rug": 0.99,
    }
    state = CanonicalOutcomeMaturityEngine.evaluate_token_maturity(rec, target_name="TARGET_3M", horizon_name="eventual")
    assert state.lifecycle_state == TokenLifecycleState.LIQUIDITY_DRAINED.value
    assert state.is_mature is True
    assert state.outcome_status == "FAILURE"


def test_fixed_horizon_failure_works_correctly():
    rec = {
        "token_address": "tok_fixed",
        "elapsed_minutes": 60.0,
        "market_cap_usd": 20000.0,
    }
    s15m = CanonicalOutcomeMaturityEngine.evaluate_token_maturity(rec, target_name="TARGET_3M", horizon_name="15m")
    assert s15m.is_mature is True
    assert s15m.outcome_status == "FAILURE"


def test_right_censoring_works_correctly():
    rec = {
        "token_address": "tok_stream_lost",
        "elapsed_minutes": 10.0,
        "outcome_status": "RIGHT_CENSORED",
    }
    state = CanonicalOutcomeMaturityEngine.evaluate_token_maturity(rec, target_name="TARGET_3M", horizon_name="1h")
    assert state.is_mature is False
    assert state.outcome_status == "RIGHT_CENSORED"


def test_survival_output_excludes_pending_as_failures():
    # 20 tokens: 2 winners at 10m, 18 in-flight active tokens at 15m
    records = []
    for i in range(20):
        is_win = (i < 2)
        records.append({
            "token_address": f"tok_{i}",
            "elapsed_minutes": 15.0,
            "market_cap_usd": 3000000.0 if is_win else 20000.0,
            "liquidity_usd": 5000.0,
            "time_to_3m_min": 10.0 if is_win else None,
            "target_3m": int(is_win),
        })

    rep = SurvivalAnalysisEngine.analyze_survival(records, target_name="TARGET_3M")
    assert rep.total_cohort_n == 20
    assert rep.total_target_events == 2
    assert rep.total_censored_in_flight == 18

    # 15m cumulative target probability: 2 / 20 = 10.0%
    inv_15m = next(inv for inv in rep.intervals if inv.interval_label == "15m")
    assert inv_15m.cumulative_event_prob_pct == 10.00
    assert inv_15m.kaplan_meier_survival == 0.90


def test_survival_estimates_handle_censored_data():
    records = [
        {"token_address": "tok_1", "elapsed_minutes": 5.0, "time_to_3m_min": 4.0, "target_3m": 1},
        {"token_address": "tok_2", "elapsed_minutes": 8.0, "outcome_status": "RIGHT_CENSORED"},
        {"token_address": "tok_3", "elapsed_minutes": 120.0, "liquidity_usd": 0.0, "p_rug": 0.99},  # Rug
        {"token_address": "tok_4", "elapsed_minutes": 25.0, "liquidity_usd": 5000.0},  # Active
    ]
    rep = SurvivalAnalysisEngine.analyze_survival(records, target_name="TARGET_3M")
    assert rep.total_target_events == 1
    assert rep.total_competing_risk_events == 1
    assert rep.total_censored_in_flight == 2


def test_zero_event_state_reported_correctly():
    # 25 active tokens, 0 winners
    records = [{"token_address": f"tok_{i}", "elapsed_minutes": 20.0, "liquidity_usd": 4000.0} for i in range(25)]
    rep = SurvivalAnalysisEngine.analyze_survival(records, target_name="TARGET_3M")

    assert rep.total_target_events == 0
    assert "NO TARGET EVENTS OBSERVED YET" in rep.status_label
    assert rep.intervals[0].formatted_event_prob == "0.00% (No Events)"


def test_target_touch_time_used_for_time_to_event():
    records = [
        {"token_address": "tok_fast", "elapsed_minutes": 60.0, "time_to_3m_min": 7.5, "target_3m": 1},
        {"token_address": "tok_slow", "elapsed_minutes": 120.0, "time_to_3m_min": 45.0, "target_3m": 1},
    ]
    rep = SurvivalAnalysisEngine.analyze_survival(records, target_name="TARGET_3M")
    assert rep.median_time_to_event_min == 26.25  # median of 7.5 and 45.0


def test_terminal_risk_event_is_separate_from_target_event():
    records = [
        {"token_address": "tok_winner", "elapsed_minutes": 10.0, "time_to_3m_min": 6.0, "target_3m": 1},
        {"token_address": "tok_rugged", "elapsed_minutes": 15.0, "liquidity_usd": 10.0, "p_rug": 0.99},
    ]
    rep = SurvivalAnalysisEngine.analyze_survival(records, target_name="TARGET_3M")
    assert rep.total_target_events == 1
    assert rep.total_competing_risk_events == 1
    assert rep.total_censored_in_flight == 0

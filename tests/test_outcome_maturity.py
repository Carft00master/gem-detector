"""
Unit tests for Canonical Outcome Maturity, Pending States, Multi-Horizon Independence, and Evidence Statuses
"""

import pytest
from src.research.discovery_audit import DiscoveryCaptureAuditor
from src.research.outcome_maturity import CanonicalOutcomeMaturityEngine, TokenHorizonMaturityState
from src.research.ranking_power import RankingPowerAuditor


def test_pending_horizon_never_classified_as_failure():
    # Token discovered 20 minutes ago, target 3M not touched
    rec = {
        "token_address": "tok_pending",
        "elapsed_minutes": 20.0,
        "market_cap_usd": 18000.0,
        "peak_market_cap_usd": 25000.0,
    }
    # 15m should be FAILURE (mature)
    s15m = CanonicalOutcomeMaturityEngine.evaluate_token_maturity(rec, target_name="TARGET_3M", horizon_name="15m")
    assert s15m.is_mature is True
    assert s15m.outcome_status == "FAILURE"

    # 1h should be PENDING (not failure!)
    s1h = CanonicalOutcomeMaturityEngine.evaluate_token_maturity(rec, target_name="TARGET_3M", horizon_name="1h")
    assert s1h.is_mature is False
    assert s1h.outcome_status == "PENDING"

    # 24h should be PENDING (not failure!)
    s24h = CanonicalOutcomeMaturityEngine.evaluate_token_maturity(rec, target_name="TARGET_3M", horizon_name="24h")
    assert s24h.is_mature is False
    assert s24h.outcome_status == "PENDING"


def test_successful_target_before_horizon():
    # Reached 3M in 8 minutes
    rec = {
        "token_address": "tok_winner",
        "elapsed_minutes": 45.0,
        "peak_market_cap_usd": 3500000.0,
        "time_to_3m_min": 8.0,
        "target_3m": 1,
    }
    # 15m -> SUCCESS
    s15m = CanonicalOutcomeMaturityEngine.evaluate_token_maturity(rec, target_name="TARGET_3M", horizon_name="15m")
    assert s15m.is_mature is True
    assert s15m.outcome_status == "SUCCESS"

    # 24h -> SUCCESS
    s24h = CanonicalOutcomeMaturityEngine.evaluate_token_maturity(rec, target_name="TARGET_3M", horizon_name="24h")
    assert s24h.is_mature is True
    assert s24h.outcome_status == "SUCCESS"


def test_failed_target_after_horizon_expiry():
    # Reached 3M only after 30 minutes (missed 15m horizon)
    rec = {
        "token_address": "tok_late_runner",
        "elapsed_minutes": 60.0,
        "peak_market_cap_usd": 3200000.0,
        "time_to_3m_min": 30.0,
        "target_3m": 1,
    }
    # 15m -> FAILURE (expired before target)
    s15m = CanonicalOutcomeMaturityEngine.evaluate_token_maturity(rec, target_name="TARGET_3M", horizon_name="15m")
    assert s15m.is_mature is True
    assert s15m.outcome_status == "FAILURE"

    # 1h -> SUCCESS (within 60m horizon)
    s1h = CanonicalOutcomeMaturityEngine.evaluate_token_maturity(rec, target_name="TARGET_3M", horizon_name="1h")
    assert s1h.is_mature is True
    assert s1h.outcome_status == "SUCCESS"


def test_right_censoring_before_horizon():
    # Stream disconnected at 10 minutes before reaching 1h horizon
    rec = {
        "token_address": "tok_censored",
        "elapsed_minutes": 10.0,
        "outcome_status": "RIGHT_CENSORED",
    }
    s1h = CanonicalOutcomeMaturityEngine.evaluate_token_maturity(rec, target_name="TARGET_3M", horizon_name="1h")
    assert s1h.is_mature is False
    assert s1h.outcome_status == "RIGHT_CENSORED"


def test_mature_sample_evidence_statuses():
    assert "INSUFFICIENT" in CanonicalOutcomeMaturityEngine.get_evidence_status(10)
    assert "VERY_EARLY" in CanonicalOutcomeMaturityEngine.get_evidence_status(35)
    assert "PRELIMINARY" in CanonicalOutcomeMaturityEngine.get_evidence_status(75)
    assert "EMERGING_EVIDENCE" in CanonicalOutcomeMaturityEngine.get_evidence_status(150)
    assert "MODERATE_EVIDENCE" in CanonicalOutcomeMaturityEngine.get_evidence_status(350)
    assert "STRONGER_EVIDENCE" in CanonicalOutcomeMaturityEngine.get_evidence_status(600)


def test_ranking_power_filters_pending_and_reports_evidence_level():
    # 20 pending tokens, 0 mature
    records = [{"token_address": f"tok_{i}", "elapsed_minutes": 10.0, "p_reach_3m": 0.05} for i in range(20)]
    report = RankingPowerAuditor.audit_ranking_power(records, scope="FULL_UNIVERSE")

    assert report.total_population_n == 20
    assert report.n_mature == 0
    assert report.n_pending == 20
    assert "NO_POSITIVES_YET" in report.sample_guardrail_status
    assert "INSUFFICIENT" in report.evidence_level


def test_telemetry_quality_vs_discovery_capture_quality_independence():
    # Fast telemetry (high TQS) but transient/short time in window (low DCQ)
    tqs = DiscoveryCaptureAuditor.calculate_telemetry_quality_score(
        rpc_latency_ms=50.0,
        websocket_latency_ms=30.0,
        has_complete_features=True,
    )
    dcq = DiscoveryCaptureAuditor.calculate_discovery_capture_quality(
        time_in_range_sec=5.0,
        observation_count=1,
        delay_from_true_entry_sec=25.0,
    )
    assert tqs >= 90.0
    assert dcq <= 25.0

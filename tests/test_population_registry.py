"""
Unit tests for Canonical Population Registry, Invariant Validation, and Zero-Positive Safety
"""

import pytest
from src.research.evaluation import ModelPerformanceReport, ResearchEvaluator
from src.research.onchain_fill_validation import LiveOnChainFillValidator, RawErrorDistribution
from src.research.opportunity_funnel import OpportunityFunnelAuditor
from src.research.population_registry import (
    CanonicalPopulationRegistry,
    PopulationCounts,
    PopulationIntegrityError,
)
from src.research.ranking_power import RankingPowerAuditor


def test_population_invariants_valid():
    # 53 = 24 + 8 + 21
    counts = PopulationCounts(
        full_universe=53,
        capture_confirmed=24,
        discovery_missed=8,
        discovery_uncertain=21,
        model_eligible=22,
        first_alert_opportunities=21,
        alerted=13,
        tradeable=13,
        target_touch=0,
        target_persistent=0,
        target_survivable=0,
    )
    # Should validate without exception
    CanonicalPopulationRegistry.validate_invariants(counts)


def test_population_invariants_partition_violation_raises():
    # 53 != 20 + 8 + 21 (Sum = 49)
    counts = PopulationCounts(
        full_universe=53,
        capture_confirmed=20,
        discovery_missed=8,
        discovery_uncertain=21,
        model_eligible=15,
        first_alert_opportunities=15,
        alerted=10,
        tradeable=10,
    )
    with pytest.raises(PopulationIntegrityError):
        CanonicalPopulationRegistry.validate_invariants(counts)


def test_population_invariants_containment_violation_raises():
    # Model Eligible (25) > Captured (24) -> Must Raise
    counts = PopulationCounts(
        full_universe=53,
        capture_confirmed=24,
        discovery_missed=8,
        discovery_uncertain=21,
        model_eligible=25,
        first_alert_opportunities=21,
        alerted=13,
        tradeable=13,
    )
    with pytest.raises(PopulationIntegrityError):
        CanonicalPopulationRegistry.validate_invariants(counts)


def test_zero_positive_metrics_are_none_and_formatted_na():
    y_true = [0, 0, 0, 0, 0, 0, 0, 0, 0, 0]
    y_prob = [0.1, 0.2, 0.05, 0.15, 0.3, 0.08, 0.12, 0.25, 0.04, 0.18]

    report = ResearchEvaluator.evaluate_model(y_true, y_prob, model_name="ZeroPosTest")

    assert report.total_positives == 0
    assert report.recall is None
    assert report.pr_auc is None
    assert report.roc_auc is None
    assert report.base_rate_lift_3m is None

    assert report.formatted_pr_auc == "N/A (No Positives)"
    assert report.formatted_roc_auc == "N/A (Single Class)"
    assert report.formatted_recall == "N/A (0/0)"
    assert report.formatted_lift == "[N/A / NO POSITIVES]"
    assert "INSUFFICIENT POSITIVE EVENTS" in report.status_label


def test_zero_positive_winner_recall_in_opportunity_funnel():
    records = [{"token_address": f"tok_{i}", "market_cap_usd": 15000.0, "target_3m": 0} for i in range(20)]
    funnel = OpportunityFunnelAuditor.audit_funnel(records)

    rec = funnel.recall
    assert rec.total_ground_truth_winners == 0
    assert rec.discovery_recall_pct is None
    assert rec.model_recall_pct is None
    assert rec.alert_recall_pct is None
    assert rec.end_to_end_recall_pct is None

    assert rec.formatted_discovery_recall == "N/A (0/0)"
    assert rec.formatted_end_to_end_recall == "N/A (0/0)"


def test_raw_execution_error_unrounded_quantiles():
    raw_errors = [0.1001, 0.2003, 0.1504, 0.0502, 0.3005]
    dist = LiveOnChainFillValidator.compute_raw_error_distribution(raw_errors)

    assert dist.min_error == 0.0502
    assert dist.max_error == 0.3005
    assert 0.15 <= dist.median_error <= 0.16

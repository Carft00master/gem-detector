"""
Unit tests for Corrected Brier Skill Score, Prevalence Baseline, and Calibration Slopes
"""

import pytest
from src.research.evaluation import ResearchEvaluator


def test_brier_prevalence_baseline_and_skill_score():
    """
    Verify Brier score baseline:
    - Prevalence baseline: p*(1-p)
    - 50% constant predictor baseline: 0.25
    - Brier skill score: 1 - ML / Prevalence
    """
    # Population with 4% positive rate (1 positive out of 25)
    y_true = [1] + [0] * 24
    # Well-calibrated model output
    y_prob = [0.25] + [0.03] * 24

    report = ResearchEvaluator.evaluate_model(
        y_true=y_true,
        y_prob=y_prob,
        model_name="TestCalibratedModel",
    )

    base_p = 1 / 25 # 0.04
    expected_prev_brier = base_p * (1.0 - base_p) # 0.0384

    assert report.brier_prevalence_baseline == pytest.approx(expected_prev_brier, 0.001)
    assert report.brier_50pct_baseline == 0.25
    assert report.brier_score_ml < expected_prev_brier
    assert report.brier_skill_score_pct > 0.0 # Positive skill over uninformed prevalence
    assert report.expected_calibration_error <= 0.15


def test_sample_size_with_every_metric():
    """Verify that report includes sample size N, unique tokens, and base rate."""
    y_true = [1, 0, 0, 0, 0, 0, 0, 0, 0, 0]
    y_prob = [0.9, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1]
    token_ids = [f"Token_{i}" for i in range(10)]

    report = ResearchEvaluator.evaluate_model(
        y_true=y_true,
        y_prob=y_prob,
        token_ids=token_ids,
        model_name="TestReportN",
    )

    assert report.sample_size == 10
    assert report.unique_token_count == 10
    assert report.total_positives == 1
    assert report.population_base_rate == 0.10
    assert report.primary_first_alert_precision_at_10 == 0.10

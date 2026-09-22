"""
Unit tests for Discovery Age Cohort Stratification
"""

import pytest
from src.research.age_cohorts import AgeCohortAnalyzer


def test_age_cohort_performance_stratification():
    records = []
    # 30 tokens across different ages
    for i in range(30):
        age = float(i * 3.0) # 0 to 90 min
        is_win = (i % 5 == 0)
        records.append({
            "token_address": f"Token_{i}",
            "token_age_minutes": age,
            "target_3m": int(is_win),
            "is_valid_3m_runner": int(is_win),
            "p_reach_3m": 0.20 if is_win else 0.05,
        })

    cohorts = AgeCohortAnalyzer.analyze_cohorts(records)

    assert len(cohorts) == 6
    cohort_labels = [c.cohort_label for c in cohorts]
    assert "0 - 1 min" in cohort_labels
    assert "1 - 5 min" in cohort_labels
    assert "5 - 15 min" in cohort_labels
    assert "15 - 30 min" in cohort_labels
    assert "30 - 60 min" in cohort_labels
    assert "60+ min" in cohort_labels

    total_tokens_sum = sum(c.total_tokens for c in cohorts)
    assert total_tokens_sum == 30

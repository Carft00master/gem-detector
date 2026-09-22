"""
Unit tests for Opportunity-Window Speed Classification
"""

import pytest
from src.research.opportunity_window import OpportunityWindowAnalyzer


def test_opportunity_window_classification():
    assert OpportunityWindowAnalyzer.classify_window(10.0) == "FAST_WIN"
    assert OpportunityWindowAnalyzer.classify_window(45.0) == "EARLY_WIN"
    assert OpportunityWindowAnalyzer.classify_window(180.0) == "SLOW_WIN"
    assert OpportunityWindowAnalyzer.classify_window(720.0) == "LATE_WIN"
    assert OpportunityWindowAnalyzer.classify_window(2000.0) == "EVENTUAL_WIN"
    assert OpportunityWindowAnalyzer.classify_window(None) == "NO_TARGET_REACHED"


def test_opportunity_window_analyzer_aggregation():
    sample_records = [
        {"token_address": "tok1", "time_to_3m_min": 12.0},
        {"token_address": "tok2", "time_to_3m_min": 35.0},
        {"token_address": "tok3", "time_to_3m_min": 240.0},
        {"token_address": "tok4", "time_to_3m_min": None},
    ]

    rep = OpportunityWindowAnalyzer.analyze_opportunities(sample_records)

    assert rep.total_opportunities == 4
    assert rep.total_3m_winners == 3
    assert rep.fast_win_count == 1
    assert rep.early_win_count == 1
    assert rep.slow_win_count == 1
    assert rep.late_win_count == 0
    assert rep.eventual_win_count == 0
    assert rep.median_time_to_target_min == 35.0

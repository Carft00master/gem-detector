import sys
from pathlib import Path
import pytest

from app.services.research_service import ResearchService
from src.learning.error_learning import ErrorAnalyzer


def test_research_service_learning_status_tp():
    svc = ResearchService()
    status = svc.get_learning_status()
    assert status is not None
    error_classification = status.get("error_classification", [])
    assert len(error_classification) == 4

    t3m_row = next(r for r in error_classification if r["target"] == "TARGET_3M")
    # Verified: 58 trades have hit 3M+ in the live dataset
    assert t3m_row["tp"] >= 50, f"Expected at least 50 True Positives for TARGET_3M, got {t3m_row['tp']}"
    assert t3m_row["recall"] > 0.0, f"Expected Recall > 0%, got {t3m_row['recall']}"
    assert t3m_row["precision"] > 0.0, f"Expected Precision > 0%, got {t3m_row['precision']}"


def test_error_analyzer_recognizes_target_reached_3m():
    analyzer = ErrorAnalyzer()
    token = {
        "token_address": "TestToken123",
        "symbol": "TEST",
        "market_cap_usd": 25000.0,
        "entry_market_cap_usd": 25000.0,
        "exit_market_cap_usd": 4500000.0,
        "mfe_ratio": 180.0,
        "target_reached_3m": True,
        "scanner_selected": True,
        "p_reach_3m": 0.15,
        "is_mature": True,
    }
    outcome = analyzer._extract_actual_outcome(token, "TARGET_3M")
    assert outcome == 1

    report = analyzer.build_error_report([token], target="TARGET_3M", threshold=0.08)
    assert report.true_positives == 1
    assert report.false_negatives == 0

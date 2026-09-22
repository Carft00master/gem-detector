"""
Unit tests for Execution Quote Accuracy Benchmarking
"""

import pytest
from src.research.execution import AMMExecutionSimulator
from src.research.execution_validation import ExecutionQuoteValidator


def test_execution_quote_validator_accuracy():
    sim = AMMExecutionSimulator()
    validator = ExecutionQuoteValidator(sim)

    report = validator.validate_quotes()

    assert report.total_swaps_evaluated > 0
    # Median quote error must be within 0.50%
    assert report.median_quote_error_pct <= 0.50
    # P95 quote error must be within 1.00%
    assert report.p95_quote_error_pct <= 1.00
    assert report.is_execution_model_validated is True

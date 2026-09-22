"""
Unit tests for Wilson Score and Clopper-Pearson Exact Binomial Confidence Intervals
"""

import pytest
from src.research.evaluation import ResearchEvaluator


def test_wilson_and_exact_confidence_intervals_n10():
    """
    Verify Wilson and Clopper-Pearson Exact 95% Confidence Intervals for N=10, k=5.
    Expected:
    - Wilson 95% CI: [0.2366, 0.7634]
    - Clopper-Pearson Exact 95% CI: [0.1871, 0.8129]
    """
    wilson_lower, wilson_upper = ResearchEvaluator.compute_wilson_ci(k=5, n=10, confidence=0.95)
    exact_lower, exact_upper = ResearchEvaluator.compute_clopper_pearson_exact_ci(k=5, n=10, confidence=0.95)

    assert wilson_lower == pytest.approx(0.2366, abs=0.005)
    assert wilson_upper == pytest.approx(0.7634, abs=0.005)

    assert exact_lower == pytest.approx(0.1871, abs=0.005)
    assert exact_upper == pytest.approx(0.8129, abs=0.005)

    # Exact interval should be wider than Wilson interval for small samples
    assert (exact_upper - exact_lower) > (wilson_upper - wilson_lower)


def test_boundary_exact_intervals():
    """Test boundary conditions for k=0 and k=n."""
    w_0, w_0_u = ResearchEvaluator.compute_wilson_ci(k=0, n=10)
    e_0, e_0_u = ResearchEvaluator.compute_clopper_pearson_exact_ci(k=0, n=10)
    assert e_0 == 0.0
    assert e_0_u > 0.0

    w_n_l, w_n = ResearchEvaluator.compute_wilson_ci(k=10, n=10)
    e_n_l, e_n = ResearchEvaluator.compute_clopper_pearson_exact_ci(k=10, n=10)
    assert e_n == 1.0
    assert e_n_l < 1.0

"""
Unit tests for ErrorAnalyzer and missed winner profiling in error_learning.py
"""

import unittest
from typing import Any, Dict, List

from src.learning.error_learning import (
    ErrorAnalysisReport,
    ErrorAnalyzer,
    ErrorClassification,
    MissedWinnerProfile,
    _safe_median,
)


class TestErrorLearning(unittest.TestCase):
    def setUp(self) -> None:
        self.analyzer = ErrorAnalyzer()

    def test_safe_median(self) -> None:
        """Test safe median computation with empty, single, even, odd, and NaN/None elements."""
        self.assertEqual(_safe_median([]), 0.0)
        self.assertEqual(_safe_median([None]), 0.0)
        self.assertEqual(_safe_median([float("nan"), float("inf")]), 0.0)
        self.assertEqual(_safe_median([5.0]), 5.0)
        self.assertEqual(_safe_median([1.0, 3.0, 2.0]), 2.0)
        self.assertEqual(_safe_median([1.0, 2.0, 3.0, 4.0]), 2.5)

    def test_classify_observations_contingency(self) -> None:
        """Test classification into TP, TN, FP, FN and skipping of censored tokens."""
        tokens: List[Dict[str, Any]] = [
            # True Positive: prob >= threshold (0.15 >= 0.08) and hit target_3m
            {
                "token_address": "addr_tp",
                "symbol": "TOKEN_TP",
                "p_reach_3m": 0.15,
                "scanner_selected": True,
                "target_3m": True,
                "market_cap_usd": 15000.0,
                "liquidity_usd": 8000.0,
                "token_age_minutes": 5.0,
                "market_regime": "HOT",
                "venue": "pump_fun",
            },
            # False Positive: prob >= threshold (0.10 >= 0.08) but failed target_3m
            {
                "token_address": "addr_fp",
                "symbol": "TOKEN_FP",
                "p_reach_3m": 0.10,
                "scanner_selected": False,
                "target_3m": False,
                "peak_market_cap_usd": 30000.0,
                "market_cap_usd": 12000.0,
                "liquidity_usd": 6000.0,
                "token_age_minutes": 10.0,
                "market_regime": "NORMAL",
                "venue": "pump_fun",
            },
            # False Negative: prob < threshold (0.04 < 0.08), not selected, but hit target_3m
            {
                "token_address": "addr_fn",
                "symbol": "TOKEN_FN",
                "p_reach_3m": 0.04,
                "scanner_selected": False,
                "target_3m": True,
                "market_cap_usd": 20000.0,
                "liquidity_usd": 12000.0,
                "token_age_minutes": 18.0,
                "market_regime": "HOT",
                "venue": "raydium",
            },
            # True Negative: prob < threshold (0.02 < 0.08), not selected, failed target_3m
            {
                "token_address": "addr_tn",
                "symbol": "TOKEN_TN",
                "p_reach_3m": 0.02,
                "scanner_selected": False,
                "target_3m": False,
                "peak_market_cap_usd": 15000.0,
                "market_cap_usd": 8000.0,
                "liquidity_usd": 3000.0,
                "token_age_minutes": 2.0,
                "market_regime": "COLD",
                "venue": "pump_fun",
            },
            # Pending / Censored token: must be skipped
            {
                "token_address": "addr_pending",
                "symbol": "TOKEN_PENDING",
                "p_reach_3m": 0.20,
                "outcome_status": "PENDING",
            },
            # Right Censored token: must be skipped
            {
                "token_address": "addr_censored",
                "symbol": "TOKEN_CENSORED",
                "p_reach_3m": 0.01,
                "outcome_status": "RIGHT_CENSORED",
            },
        ]

        classifications = self.analyzer.classify_observations(tokens, target="TARGET_3M", threshold=0.08)
        self.assertEqual(len(classifications), 4)

        cls_by_addr = {c.token_address: c for c in classifications}
        self.assertEqual(cls_by_addr["addr_tp"].classification, "TRUE_POSITIVE")
        self.assertEqual(cls_by_addr["addr_fp"].classification, "FALSE_POSITIVE")
        self.assertEqual(cls_by_addr["addr_fn"].classification, "FALSE_NEGATIVE")
        self.assertEqual(cls_by_addr["addr_tn"].classification, "TRUE_NEGATIVE")

    def test_build_error_report_metrics(self) -> None:
        """Test calculation of Precision, Recall, and F1 in build_error_report."""
        tokens = [
            {"token_address": "t1", "symbol": "T1", "p_reach_3m": 0.10, "target_3m": True},    # TP
            {"token_address": "t2", "symbol": "T2", "p_reach_3m": 0.12, "target_3m": False},   # FP
            {"token_address": "t3", "symbol": "T3", "p_reach_3m": 0.01, "target_3m": True},    # FN
            {"token_address": "t4", "symbol": "T4", "p_reach_3m": 0.02, "target_3m": False},   # TN
        ]

        report = self.analyzer.build_error_report(tokens, target="TARGET_3M", threshold=0.08)
        self.assertEqual(report.total_observations, 4)
        self.assertEqual(report.total_mature, 4)
        self.assertEqual(report.true_positives, 1)
        self.assertEqual(report.false_positives, 1)
        self.assertEqual(report.false_negatives, 1)
        self.assertEqual(report.true_negatives, 1)
        self.assertAlmostEqual(report.precision, 0.5)
        self.assertAlmostEqual(report.recall, 0.5)
        self.assertAlmostEqual(report.f1, 0.5)

    def test_missed_winner_profiling(self) -> None:
        """Test build_missed_winner_profile medians, distributions, and feature ranking."""
        tokens = [
            {
                "token_address": "fn1",
                "symbol": "FN1",
                "p_reach_3m": 0.03,
                "target_3m": True,
                "market_cap_usd": 16000.0,
                "liquidity_usd": 9000.0,
                "token_age_minutes": 10.0,
                "market_regime": "HOT",
                "venue": "pump_fun",
                "activity_density_score": 88.0,
                "trader_density_score": 75.0,
                "curve_progress": 0.70,
                "wallet_quality_score": 80.0,
            },
            {
                "token_address": "fn2",
                "symbol": "FN2",
                "p_reach_3m": 0.05,
                "target_3m": True,
                "market_cap_usd": 24000.0,
                "liquidity_usd": 11000.0,
                "token_age_minutes": 20.0,
                "market_regime": "NORMAL",
                "venue": "raydium",
                "activity_density_score": 92.0,
                "trader_density_score": 85.0,
                "curve_progress": 0.90,
                "wallet_quality_score": 84.0,
            },
            {
                "token_address": "tp1",
                "symbol": "TP1",
                "p_reach_3m": 0.20,
                "target_3m": True,
                "market_cap_usd": 12000.0,
                "liquidity_usd": 7000.0,
                "token_age_minutes": 4.0,
                "market_regime": "HOT",
                "venue": "pump_fun",
                "activity_density_score": 95.0,
                "trader_density_score": 90.0,
                "curve_progress": 0.60,
                "wallet_quality_score": 85.0,
            },
        ]

        report = self.analyzer.build_error_report(tokens, target="TARGET_3M", threshold=0.08)
        profile = report.missed_winner_profile
        self.assertIsNotNone(profile)
        self.assertEqual(profile.total_missed, 2)
        self.assertEqual(profile.median_entry_mc, 20000.0)
        self.assertEqual(profile.median_entry_age_minutes, 15.0)
        self.assertEqual(profile.median_activity_density, 90.0)
        self.assertEqual(profile.median_trader_density, 80.0)
        self.assertEqual(profile.median_curve_progress, 0.80)
        self.assertEqual(profile.median_wallet_quality, 82.0)
        self.assertEqual(profile.median_liquidity, 10000.0)

        # Check distribution counts
        self.assertEqual(profile.regime_distribution["HOT"], 1)
        self.assertEqual(profile.regime_distribution["NORMAL"], 1)
        self.assertEqual(profile.venue_distribution["pump_fun"], 1)
        self.assertEqual(profile.venue_distribution["raydium"], 1)

        # Check distinguishing features
        self.assertTrue(len(profile.top_distinguishing_features) > 0)
        self.assertTrue(len(profile.comparison_vs_true_positives) > 0)

    def test_weekly_report_generation(self) -> None:
        """Test generating weekly markdown summary report."""
        tokens = [
            {
                "token_address": "winner_001",
                "symbol": "GEM1",
                "p_reach_3m": 0.15,
                "target_3m": True,
                "market_cap_usd": 15000.0,
                "liquidity_usd": 8000.0,
                "token_age_minutes": 5.0,
                "market_regime": "HOT",
                "venue": "pump_fun",
            },
            {
                "token_address": "missed_001",
                "symbol": "MISSEDGEM",
                "p_reach_3m": 0.02,
                "target_3m": True,
                "market_cap_usd": 18000.0,
                "liquidity_usd": 9500.0,
                "token_age_minutes": 12.0,
                "market_regime": "NORMAL",
                "venue": "pump_fun",
            },
        ]
        markdown = self.analyzer.generate_weekly_report(tokens)
        self.assertIn("# Weekly Missed Winner Analysis & Error Audit Report", markdown)
        self.assertIn("MISSEDGEM", markdown)
        self.assertIn("Precision", markdown)
        self.assertIn("Recall (Capture Rate)", markdown)


if __name__ == "__main__":
    unittest.main()

"""
Unit tests for EntryPolicyOptimizer in src/learning/entry_optimizer.py
"""

import unittest
from typing import Any, Dict, List

from src.learning.entry_optimizer import (
    ALL_AGE_BUCKETS,
    ALL_ENTRY_POLICIES,
    ALL_LIQUIDITY_BUCKETS,
    ALL_MARKET_REGIMES,
    ContextualEntryResult,
    EntryOptimizationReport,
    EntryPolicyEvaluation,
    EntryPolicyOptimizer,
    POLICY_CONFIRMATION,
    POLICY_FIRST_PULLBACK,
    POLICY_HIGHER_LOW_CONFIRMATION,
    POLICY_IMMEDIATE,
    POLICY_LIQUIDITY_EXPANSION,
    POLICY_MOMENTUM_REENTRY,
    QUALITY_EARLY_ENTRY,
    QUALITY_FALSE_BREAKOUT_ENTRY,
    QUALITY_GOOD_ENTRY,
    QUALITY_HIGH_SLIPPAGE_ENTRY,
    QUALITY_LATE_ENTRY,
    QUALITY_MODERATE_ENTRY,
)


class TestEntryPolicyOptimizer(unittest.TestCase):
    def setUp(self) -> None:
        self.optimizer = EntryPolicyOptimizer()

    def test_six_policies_evaluated(self) -> None:
        """Verify that evaluate_entry_policies returns exactly 6 policies in expected order."""
        evals = self.optimizer.evaluate_entry_policies(
            alert_price=1.0,
            peak_price=2.5,
            trough_price=0.8,
            final_price=2.0,
            liquidity_usd=5000.0,
            token_age_minutes=10.0,
            position_size_usd=250.0,
        )
        self.assertEqual(len(evals), 6)
        policies = [e.policy for e in evals]
        expected_policies = [
            POLICY_IMMEDIATE,
            POLICY_CONFIRMATION,
            POLICY_FIRST_PULLBACK,
            POLICY_HIGHER_LOW_CONFIRMATION,
            POLICY_LIQUIDITY_EXPANSION,
            POLICY_MOMENTUM_REENTRY,
        ]
        self.assertEqual(policies, expected_policies)

    def test_policy_multipliers_and_entry_prices(self) -> None:
        """Verify policy entry prices match specified multiplier rules."""
        alert_price = 10.0
        evals = self.optimizer.evaluate_entry_policies(
            alert_price=alert_price,
            peak_price=20.0,
            trough_price=8.0,
            final_price=15.0,
            liquidity_usd=10000.0,
            token_age_minutes=12.0,
        )
        eval_dict = {e.policy: e for e in evals}

        # 1. IMMEDIATE: 1.00x
        self.assertAlmostEqual(eval_dict[POLICY_IMMEDIATE].entry_price_usd, 10.0, places=4)
        self.assertAlmostEqual(eval_dict[POLICY_IMMEDIATE].entry_delay_minutes, 0.0, places=2)

        # 2. CONFIRMATION: 1.05x
        self.assertAlmostEqual(eval_dict[POLICY_CONFIRMATION].entry_price_usd, 10.5, places=4)
        self.assertAlmostEqual(eval_dict[POLICY_CONFIRMATION].entry_delay_minutes, 2.0, places=2)

        # 3. FIRST_PULLBACK: 0.90x
        self.assertAlmostEqual(eval_dict[POLICY_FIRST_PULLBACK].entry_price_usd, 9.0, places=4)
        self.assertAlmostEqual(eval_dict[POLICY_FIRST_PULLBACK].entry_delay_minutes, 5.0, places=2)

        # 4. HIGHER_LOW_CONFIRMATION: 0.95x
        self.assertAlmostEqual(eval_dict[POLICY_HIGHER_LOW_CONFIRMATION].entry_price_usd, 9.5, places=4)
        self.assertAlmostEqual(eval_dict[POLICY_HIGHER_LOW_CONFIRMATION].entry_delay_minutes, 8.0, places=2)

        # 5. LIQUIDITY_EXPANSION: 1.02x
        self.assertAlmostEqual(eval_dict[POLICY_LIQUIDITY_EXPANSION].entry_price_usd, 10.2, places=4)
        self.assertAlmostEqual(eval_dict[POLICY_LIQUIDITY_EXPANSION].entry_delay_minutes, 10.0, places=2)

        # 6. MOMENTUM_REENTRY: 1.08x
        self.assertAlmostEqual(eval_dict[POLICY_MOMENTUM_REENTRY].entry_price_usd, 10.8, places=4)
        self.assertAlmostEqual(eval_dict[POLICY_MOMENTUM_REENTRY].entry_delay_minutes, 15.0, places=2)

    def test_safe_defaults_mfe_mae(self) -> None:
        """Verify safe defaults: if peak <= entry, mfe = 0. If trough >= entry, mae = 0."""
        # Case 1: Peak is below entry and trough is above entry (flat/loss scenario)
        evals = self.optimizer.evaluate_entry_policies(
            alert_price=1.0,
            peak_price=0.85,  # peak < entry (even for pullback 0.90)
            trough_price=1.10, # trough > entry
            final_price=0.80,
            liquidity_usd=5000.0,
            token_age_minutes=10.0,
        )
        for e in evals:
            self.assertEqual(e.mfe_pct, 0.0)
            self.assertEqual(e.mae_pct, 0.0)
            self.assertEqual(e.max_drawdown_pct, 0.0)

    def test_classification_logic(self) -> None:
        """Verify non-anticipative entry quality classification labels."""
        # 1. HIGH_SLIPPAGE_ENTRY: slippage > 5
        label = self.optimizer.classify_entry_quality(mfe_pct=60.0, mae_pct=-10.0, slippage_pct=5.5)
        self.assertEqual(label, QUALITY_HIGH_SLIPPAGE_ENTRY)

        # 2. FALSE_BREAKOUT_ENTRY: mae < -40 AND mfe < 15
        label = self.optimizer.classify_entry_quality(mfe_pct=10.0, mae_pct=-45.0, slippage_pct=1.0)
        self.assertEqual(label, QUALITY_FALSE_BREAKOUT_ENTRY)

        # 3. GOOD_ENTRY: mfe > 50 AND mae > -20 AND slippage < 3
        label = self.optimizer.classify_entry_quality(mfe_pct=80.0, mae_pct=-15.0, slippage_pct=1.5)
        self.assertEqual(label, QUALITY_GOOD_ENTRY)

        # 4. EARLY_ENTRY: mae < -30 but mfe > 30
        label = self.optimizer.classify_entry_quality(mfe_pct=50.0, mae_pct=-35.0, slippage_pct=1.0)
        self.assertEqual(label, QUALITY_EARLY_ENTRY)

        # 5. LATE_ENTRY: mfe < 20
        label = self.optimizer.classify_entry_quality(mfe_pct=15.0, mae_pct=-10.0, slippage_pct=1.0)
        self.assertEqual(label, QUALITY_LATE_ENTRY)

        # 6. MODERATE_ENTRY: fallback
        label = self.optimizer.classify_entry_quality(mfe_pct=35.0, mae_pct=-15.0, slippage_pct=1.0)
        self.assertEqual(label, QUALITY_MODERATE_ENTRY)

    def test_cohort_bucketing(self) -> None:
        """Verify age and liquidity cohort bucketing logic."""
        # Age buckets: '<5m', '5-15m', '15-30m', '30-60m', '60m+'
        self.assertEqual(self.optimizer.get_age_bucket(2.5), "<5m")
        self.assertEqual(self.optimizer.get_age_bucket(5.0), "5-15m")
        self.assertEqual(self.optimizer.get_age_bucket(14.9), "5-15m")
        self.assertEqual(self.optimizer.get_age_bucket(20.0), "15-30m")
        self.assertEqual(self.optimizer.get_age_bucket(45.0), "30-60m")
        self.assertEqual(self.optimizer.get_age_bucket(90.0), "60m+")

        # Liquidity buckets: '<2K', '2K-5K', '5K-15K', '15K+'
        self.assertEqual(self.optimizer.get_liquidity_bucket(1500.0), "<2K")
        self.assertEqual(self.optimizer.get_liquidity_bucket(2500.0), "2K-5K")
        self.assertEqual(self.optimizer.get_liquidity_bucket(8000.0), "5K-15K")
        self.assertEqual(self.optimizer.get_liquidity_bucket(25000.0), "15K+")

        # Regimes: NORMAL, HOT, COLD, PANIC
        self.assertEqual(self.optimizer.normalize_regime("HOT"), "HOT")
        self.assertEqual(self.optimizer.normalize_regime("BULL_BREAKOUT"), "HOT")
        self.assertEqual(self.optimizer.normalize_regime("CAPITULATION"), "PANIC")
        self.assertEqual(self.optimizer.normalize_regime("DISTRIBUTION"), "COLD")
        self.assertEqual(self.optimizer.normalize_regime(None), "NORMAL")

    def test_contextual_performance_and_report_generation(self) -> None:
        """Verify contextual grouping and report generation across multiple tokens."""
        tokens: List[Dict[str, Any]] = [
            {
                "token_address": "addr_1",
                "alert_price": 0.001,
                "peak_price": 0.005,
                "trough_price": 0.0008,
                "final_price": 0.004,
                "liquidity_usd": 6000.0,
                "token_age_minutes": 8.0,
                "market_regime": "HOT",
            },
            {
                "token_address": "addr_2",
                "alert_price": 0.01,
                "peak_price": 0.012,
                "trough_price": 0.004,
                "final_price": 0.005,
                "liquidity_usd": 1500.0,
                "token_age_minutes": 2.0,
                "market_regime": "PANIC",
            },
            {
                "token_address": "addr_3",
                "alert_price": 0.05,
                "peak_price": 0.15,
                "trough_price": 0.045,
                "final_price": 0.12,
                "liquidity_usd": 20000.0,
                "token_age_minutes": 45.0,
                "market_regime": "NORMAL",
            },
        ]

        # Contextual Performance
        ctx_results = self.optimizer.evaluate_contextual_performance(tokens)
        self.assertTrue(len(ctx_results) > 0)
        for res in ctx_results:
            self.assertIn(res.best_policy, ALL_ENTRY_POLICIES)
            self.assertGreater(res.sample_size, 0)
            self.assertEqual(len(res.policy_performance), 6)

        # Full Optimization Report
        report = self.optimizer.generate_entry_optimization_report(tokens)
        self.assertEqual(report.total_tokens_evaluated, 3)
        self.assertEqual(report.token_address, "AGGREGATE")
        self.assertIn(report.best_policy_overall, ALL_ENTRY_POLICIES)
        self.assertEqual(len(report.evaluations), 18)  # 3 tokens * 6 policies
        self.assertIn("overall", report.conditional_policy_rankings)
        self.assertIn("HOT", report.best_policy_by_regime)

        # Test dictionary serialization
        rep_dict = report.to_dict()
        self.assertEqual(rep_dict["total_tokens_evaluated"], 3)
        self.assertIn("best_policy_overall", rep_dict)

    def test_empty_tokens_edge_case(self) -> None:
        """Verify behavior on empty tokens list."""
        ctx_results = self.optimizer.evaluate_contextual_performance([])
        self.assertEqual(ctx_results, [])

        report = self.optimizer.generate_entry_optimization_report([])
        self.assertEqual(report.total_tokens_evaluated, 0)
        self.assertEqual(report.best_policy_overall, POLICY_IMMEDIATE)
        self.assertEqual(report.evaluations, [])


if __name__ == "__main__":
    unittest.main()

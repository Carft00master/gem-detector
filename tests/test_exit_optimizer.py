"""
Unit tests for ExitPolicyOptimizer in src/learning/exit_optimizer.py
"""

import unittest
from typing import Any, Dict, List

from src.learning.exit_optimizer import (
    EXIT_POLICIES,
    LABEL_CORRECT_EXIT,
    LABEL_EXIT_TOO_EARLY,
    LABEL_EXIT_TOO_LATE,
    LABEL_MISSED_EXTENSION,
    LABEL_RUG_PROTECTED,
    LABEL_UNKNOWN,
    POLICY_FIXED_TARGETS,
    POLICY_RISK_INVALIDATION,
    POLICY_STAGED_EXITS,
    POLICY_TIME_BASED,
    POLICY_TRAILING_STOP,
    ExitOptimizationReport,
    ExitPolicyEvaluation,
    ExitPolicyOptimizer,
)


class TestExitPolicyOptimizer(unittest.TestCase):
    def setUp(self) -> None:
        self.optimizer = ExitPolicyOptimizer()

    def test_five_policies_defined(self) -> None:
        """Verify that all 5 expected exit policies are present."""
        expected = [
            "TRAILING_STOP",
            "RISK_INVALIDATION",
            "TIME_BASED",
            "FIXED_TARGETS",
            "STAGED_EXITS",
        ]
        self.assertEqual(self.optimizer.EXIT_POLICIES, expected)
        self.assertEqual(len(self.optimizer.EXIT_POLICIES), 5)

    def test_label_exit_mistake_rules(self) -> None:
        """Verify the 5 exit quality labeling criteria."""
        # 1. MISSED_EXTENSION: MFE > 500% and realized < 100%
        self.assertEqual(
            self.optimizer.label_exit_mistake(
                realized_pct=80.0,
                mfe_pct=600.0,
                mae_pct=-10.0,
                additional_upside=0.0,
                drawdown_avoided=0.0,
            ),
            LABEL_MISSED_EXTENSION,
        )

        # 2. EXIT_TOO_LATE: realized < 0 and MFE > 50%
        self.assertEqual(
            self.optimizer.label_exit_mistake(
                realized_pct=-15.0,
                mfe_pct=80.0,
                mae_pct=-25.0,
                additional_upside=0.0,
                drawdown_avoided=0.0,
            ),
            LABEL_EXIT_TOO_LATE,
        )

        # 3. EXIT_TOO_EARLY: realized < 0.50 * MFE and MFE > 100%
        self.assertEqual(
            self.optimizer.label_exit_mistake(
                realized_pct=40.0,
                mfe_pct=200.0,
                mae_pct=-5.0,
                additional_upside=0.0,
                drawdown_avoided=0.0,
            ),
            LABEL_EXIT_TOO_EARLY,
        )

        # 4. CORRECT_EXIT: realized >= 0.70 * MFE
        self.assertEqual(
            self.optimizer.label_exit_mistake(
                realized_pct=75.0,
                mfe_pct=100.0,
                mae_pct=-5.0,
                additional_upside=0.0,
                drawdown_avoided=0.0,
            ),
            LABEL_CORRECT_EXIT,
        )

        # 5. RUG_PROTECTED: drawdown_avoided > 60%
        self.assertEqual(
            self.optimizer.label_exit_mistake(
                realized_pct=-10.0,
                mfe_pct=20.0,
                mae_pct=-80.0,
                additional_upside=0.0,
                drawdown_avoided=75.0,
            ),
            LABEL_RUG_PROTECTED,
        )

    def test_evaluate_exit_policy(self) -> None:
        """Verify mathematical calculations in evaluate_exit_policy."""
        eval_res = self.optimizer.evaluate_exit_policy(
            policy=POLICY_TRAILING_STOP,
            entry_price=10.0,
            exit_price=18.0,
            peak_price=20.0,
            trough_price=9.0,
            post_exit_peak_price=22.0,
            post_exit_trough_price=12.0,
            time_in_trade=45.0,
            regime="HOT",
            token_address="token123",
            symbol="RUNNER",
        )

        # realized_return = (18 - 10) / 10 * 100 = 80.0%
        self.assertAlmostEqual(eval_res.realized_return_pct, 80.0, places=2)
        # mfe = (20 - 10) / 10 * 100 = 100.0%
        self.assertAlmostEqual(eval_res.mfe_pct, 100.0, places=2)
        # mae = (9 - 10) / 10 * 100 = -10.0%
        self.assertAlmostEqual(eval_res.mae_pct, -10.0, places=2)
        # max_drawdown = min(mae, 0) = -10.0%
        self.assertAlmostEqual(eval_res.max_drawdown_pct, -10.0, places=2)
        # additional_upside = (22 - 18) / 18 * 100 = 22.2222%
        self.assertAlmostEqual(eval_res.additional_upside_after_exit_pct, 22.2222, places=2)
        # drawdown_avoided = abs((12 - 18) / 18 * 100) = 33.3333%
        self.assertAlmostEqual(eval_res.drawdown_avoided_pct, 33.3333, places=2)
        # Realized 80% on 100% MFE -> 80% >= 70% -> CORRECT_EXIT
        self.assertEqual(eval_res.exit_quality_label, LABEL_CORRECT_EXIT)
        self.assertEqual(eval_res.regime, "HOT")

    def test_evaluate_all_policies(self) -> None:
        """Verify evaluating all policies simultaneously."""
        exit_prices = {
            POLICY_TRAILING_STOP: 1.7,
            POLICY_RISK_INVALIDATION: 0.9,
            POLICY_TIME_BASED: 1.2,
            POLICY_FIXED_TARGETS: 3.0,
            POLICY_STAGED_EXITS: 2.2,
        }
        evals = self.optimizer.evaluate_all_policies(
            entry_price=1.0,
            exit_prices=exit_prices,
            peak_price=3.5,
            trough_price=0.8,
            post_exit_peak={"default": 3.8},
            post_exit_trough={"default": 0.5},
            times={"default": 60.0},
            regime="NORMAL",
        )
        self.assertEqual(len(evals), 5)
        eval_dict = {e.policy: e for e in evals}
        self.assertAlmostEqual(eval_dict[POLICY_FIXED_TARGETS].realized_return_pct, 200.0, places=2)
        self.assertAlmostEqual(eval_dict[POLICY_RISK_INVALIDATION].realized_return_pct, -10.0, places=2)

    def test_build_exit_report(self) -> None:
        """Verify aggregated report creation and ranking."""
        evals = [
            self.optimizer.evaluate_exit_policy(POLICY_TRAILING_STOP, 1.0, 1.8, 2.0, 0.9, 2.1, 0.8, 30.0, "HOT"),
            self.optimizer.evaluate_exit_policy(POLICY_TRAILING_STOP, 1.0, 1.5, 1.8, 0.95, 1.6, 0.5, 40.0, "NORMAL"),
            self.optimizer.evaluate_exit_policy(POLICY_FIXED_TARGETS, 1.0, 3.0, 3.2, 0.9, 3.5, 0.4, 60.0, "HOT"),
            self.optimizer.evaluate_exit_policy(POLICY_FIXED_TARGETS, 1.0, 0.5, 1.2, 0.4, 0.6, 0.2, 20.0, "NORMAL"),
            self.optimizer.evaluate_exit_policy(POLICY_TIME_BASED, 1.0, 1.1, 1.3, 0.9, 1.2, 0.6, 240.0, "NORMAL"),
        ]

        report = self.optimizer.build_exit_report(evals)
        self.assertEqual(report.total_trades_evaluated, 5)
        self.assertIn(report.best_policy_overall, [POLICY_TRAILING_STOP, POLICY_FIXED_TARGETS, POLICY_TIME_BASED])
        self.assertIn(POLICY_TRAILING_STOP, report.policy_summary)
        self.assertIn(POLICY_FIXED_TARGETS, report.policy_summary)
        self.assertIn("HOT", report.contextual_performance)
        self.assertIn("NORMAL", report.contextual_performance)

        # Serialization test
        rep_dict = report.to_dict()
        self.assertEqual(rep_dict["total_trades_evaluated"], 5)
        self.assertIn("policy_summary", rep_dict)

    def test_empty_evaluations_edge_case(self) -> None:
        """Verify behavior on empty evaluation list."""
        report = self.optimizer.build_exit_report([])
        self.assertEqual(report.total_trades_evaluated, 0)
        self.assertEqual(report.best_policy_overall, POLICY_TRAILING_STOP)
        self.assertEqual(report.evaluations, [])

    def test_simulate_policy_on_path_scenarios(self) -> None:
        """Verify path simulations for all 5 exit policies."""
        # 1. RISK_INVALIDATION (dev dump)
        traj_dump = [{"price_usd": 1.0, "elapsed_minutes": 5.0, "is_dev_dump": True}]
        res = self.optimizer.simulate_policy_on_path(POLICY_RISK_INVALIDATION, 1.0, traj_dump)
        self.assertEqual(res[6], "RISK_INVALIDATION")

        # 2. RISK_INVALIDATION (liquidity drain)
        traj_drain = [{"price_usd": 1.0, "elapsed_minutes": 5.0, "is_liquidity_drained": True}]
        res = self.optimizer.simulate_policy_on_path(POLICY_RISK_INVALIDATION, 1.0, traj_drain)
        self.assertEqual(res[6], "RISK_INVALIDATION")

        # 3. FIXED_TARGETS (10x profit)
        traj_10x = [{"price_usd": 10.5, "elapsed_minutes": 15.0}]
        res = self.optimizer.simulate_policy_on_path(POLICY_FIXED_TARGETS, 1.0, traj_10x)
        self.assertEqual(res[6], "FIXED_TARGET")

        # 4. FIXED_TARGETS (3x after 60 min)
        traj_3x = [{"price_usd": 3.2, "elapsed_minutes": 65.0}]
        res = self.optimizer.simulate_policy_on_path(POLICY_FIXED_TARGETS, 1.0, traj_3x)
        self.assertEqual(res[6], "FIXED_TARGET")

        # 5. FIXED_TARGETS (stop loss -50%)
        traj_stop = [{"price_usd": 0.48, "elapsed_minutes": 10.0}]
        res = self.optimizer.simulate_policy_on_path(POLICY_FIXED_TARGETS, 1.0, traj_stop)
        self.assertEqual(res[6], "STOP_LOSS")

        # 6. TIME_BASED (after 240m)
        traj_time = [{"price_usd": 1.1, "elapsed_minutes": 245.0}]
        res = self.optimizer.simulate_policy_on_path(POLICY_TIME_BASED, 1.0, traj_time)
        self.assertEqual(res[6], "TIME_BASED_EXPIRY")

        # 7. TRAILING_STOP (25% drawdown from peak after +25% profit)
        traj_trail = [
            {"price_usd": 1.4, "elapsed_minutes": 10.0},
            {"price_usd": 2.0, "elapsed_minutes": 20.0},
            {"price_usd": 1.45, "elapsed_minutes": 30.0},  # (2.0 - 1.45)/2.0 = 27.5% drop >= 25%
        ]
        res = self.optimizer.simulate_policy_on_path(POLICY_TRAILING_STOP, 1.0, traj_trail)
        self.assertEqual(res[6], "TRAILING_STOP")

        # 8. STAGED_EXITS ($3M MC target)
        traj_staged = [{"price_usd": 5.0, "market_cap_usd": 3_200_000.0, "elapsed_minutes": 20.0}]
        res = self.optimizer.simulate_policy_on_path(POLICY_STAGED_EXITS, 1.0, traj_staged)
        self.assertEqual(res[6], "STAGED_FINAL_TARGET")


if __name__ == "__main__":
    unittest.main()

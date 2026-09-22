"""
Unit tests for ChampionChallengerEngine and Comparison Scorecard
"""

import unittest

from src.learning.champion_challenger import (
    ChampionChallengerEngine,
    ComparisonScorecard,
    ScorecardMetric,
    ShadowPredictionRecord,
)


class TestChampionChallenger(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = ChampionChallengerEngine(champion_id="v1.0.0", min_sample_size=30)

    def test_dataclass_serialization(self) -> None:
        """Verify serialization and deserialization of dataclasses."""
        metric = ScorecardMetric(
            metric_name="PR-AUC",
            champion_value=0.80,
            challenger_value=0.88,
            improvement_pct=10.0,
            meets_threshold=True,
            threshold=5.0,
            direction="higher_is_better",
        )
        metric_dict = metric.to_dict()
        reconstructed_metric = ScorecardMetric.from_dict(metric_dict)
        self.assertEqual(reconstructed_metric.metric_name, "PR-AUC")
        self.assertEqual(reconstructed_metric.improvement_pct, 10.0)

        scorecard = ComparisonScorecard(
            champion_id="v1.0.0",
            challenger_id="v1.1.0-cand",
            model_type="SELECTION",
            evaluation_period="2025-Q1",
            sample_size=100,
            metrics=[metric],
            all_thresholds_met=True,
            promotion_recommendation="PROMOTE",
            regime_specific_results={"BULL": {"champion_brier": 0.10, "challenger_brier": 0.08}},
            venue_specific_results={"RAYDIUM": {"champion_brier": 0.12, "challenger_brier": 0.09}},
            notes=["Test note"],
        )
        sc_dict = scorecard.to_dict()
        reconstructed_sc = ComparisonScorecard.from_dict(sc_dict)
        self.assertEqual(reconstructed_sc.champion_id, "v1.0.0")
        self.assertEqual(len(reconstructed_sc.metrics), 1)
        self.assertEqual(reconstructed_sc.metrics[0].metric_name, "PR-AUC")
        self.assertEqual(reconstructed_sc.promotion_recommendation, "PROMOTE")

        shadow = ShadowPredictionRecord(
            token_address="Mint123",
            timestamp="2025-01-01T00:00:00Z",
            champion_prediction=0.65,
            challenger_prediction=0.82,
            actual_outcome=1,
            model_type="SELECTION",
        )
        sh_dict = shadow.to_dict()
        reconstructed_sh = ShadowPredictionRecord.from_dict(sh_dict)
        self.assertEqual(reconstructed_sh.token_address, "Mint123")
        self.assertEqual(reconstructed_sh.actual_outcome, 1)

    def test_record_shadow_prediction(self) -> None:
        """Verify recording shadow prediction records."""
        rec = self.engine.record_shadow_prediction(
            token_address="TokenA",
            champion_pred=0.45,
            challenger_pred=0.75,
            model_type="SELECTION",
            actual_outcome=1,
        )
        self.assertEqual(len(self.engine.shadow_predictions), 1)
        self.assertEqual(rec.token_address, "TokenA")
        self.assertEqual(rec.champion_prediction, 0.45)
        self.assertEqual(rec.challenger_prediction, 0.75)
        self.assertEqual(rec.actual_outcome, 1)
        self.assertEqual(rec.model_type, "SELECTION")

    def test_helper_metrics(self) -> None:
        """Verify exact calculations of helper metrics."""
        # Brier score
        preds = [0.9, 0.1]
        labels = [1, 0]
        # (0.9-1)^2 + (0.1-0)^2 = 0.01 + 0.01 = 0.02 / 2 = 0.01
        self.assertAlmostEqual(self.engine._compute_brier(preds, labels), 0.01, places=4)

        # Precision@10
        preds_p = [0.9, 0.8, 0.7, 0.6, 0.5, 0.4, 0.3, 0.2, 0.1, 0.05]
        labels_p = [1, 1, 1, 1, 1, 0, 0, 0, 0, 0]
        self.assertAlmostEqual(self.engine._compute_precision_at_k(preds_p, labels_p, k=5), 1.0, places=4)
        self.assertAlmostEqual(self.engine._compute_precision_at_k(preds_p, labels_p, k=10), 0.5, places=4)

        # PR-AUC
        # Perfect classifier: top 2 are positive out of 4
        preds_auc = [0.9, 0.8, 0.2, 0.1]
        labels_auc = [1, 1, 0, 0]
        self.assertAlmostEqual(self.engine._compute_pr_auc(preds_auc, labels_auc), 1.0, places=4)

        # ECE
        # Perfectly calibrated
        preds_ece = [0.1, 0.1, 0.9, 0.9]
        labels_ece = [0, 0, 1, 1]
        self.assertAlmostEqual(self.engine._compute_ece(preds_ece, labels_ece), 0.1, places=2)

        # Rug rate
        rug_flags = [1, 0, 1, 0]
        self.assertAlmostEqual(self.engine._compute_rug_rate(rug_flags), 0.5, places=4)
        self.assertEqual(self.engine._compute_rug_rate(None), 0.0)

    def test_compare_predictions_promote(self) -> None:
        """Verify scorecard and PROMOTE recommendation when challenger clearly wins."""
        n = 50
        labels = [1 if i < 15 else 0 for i in range(n)]

        # Champion predictions: moderate/noisy ranking
        champ_preds = [0.6 if (i < 8 or (15 <= i < 20)) else 0.4 for i in range(n)]

        # Challenger predictions: near perfect ranking
        chall_preds = [0.95 if i < 15 else 0.05 for i in range(n)]

        scorecard = self.engine.compare_predictions(
            champion_preds=champ_preds,
            challenger_preds=chall_preds,
            labels=labels,
            champion_id="v1.0.0",
            challenger_id="v1.1.0_challenger",
            model_type="SELECTION",
            evaluation_period="2025-H1",
        )

        self.assertEqual(scorecard.sample_size, 50)
        self.assertTrue(scorecard.all_thresholds_met)
        self.assertEqual(scorecard.promotion_recommendation, "PROMOTE")
        self.assertEqual(len(scorecard.metrics), 6)

        # PR-AUC metric check
        pr_metric = next(m for m in scorecard.metrics if m.metric_name == "PR-AUC")
        self.assertTrue(pr_metric.meets_threshold)
        self.assertGreater(pr_metric.improvement_pct, 5.0)

    def test_compare_predictions_not_ready(self) -> None:
        """Verify NOT_READY when performance is slightly better but below required gates."""
        n = 50
        labels = [1 if i < 15 else 0 for i in range(n)]

        # Champion and challenger have nearly identical ranking
        champ_preds = [0.55 if i < 15 else 0.45 for i in range(n)]
        chall_preds = [0.56 if i < 15 else 0.44 for i in range(n)]

        scorecard = self.engine.compare_predictions(
            champion_preds=champ_preds,
            challenger_preds=chall_preds,
            labels=labels,
            champion_id="v1.0.0",
            challenger_id="v1.0.1_small_delta",
            model_type="SELECTION",
        )

        self.assertFalse(scorecard.all_thresholds_met)
        self.assertEqual(scorecard.promotion_recommendation, "NOT_READY")

    def test_compare_predictions_regressed(self) -> None:
        """Verify scorecard and REGRESSED recommendation when challenger is degraded."""
        n = 50
        labels = [1 if i < 15 else 0 for i in range(n)]

        # Champion predictions: good accuracy
        champ_preds = [0.90 if i < 15 else 0.10 for i in range(n)]

        # Challenger predictions: inverted / poor accuracy
        chall_preds = [0.10 if i < 15 else 0.90 for i in range(n)]

        scorecard = self.engine.compare_predictions(
            champion_preds=champ_preds,
            challenger_preds=chall_preds,
            labels=labels,
            champion_id="v1.0.0",
            challenger_id="v1.1.0_bad",
            model_type="SELECTION",
        )

        self.assertFalse(scorecard.all_thresholds_met)
        self.assertEqual(scorecard.promotion_recommendation, "REGRESSED")

    def test_compare_predictions_insufficient_data(self) -> None:
        """Verify INSUFFICIENT_DATA when sample size is below min_sample_size or 0 positives."""
        champ_preds = [0.8, 0.7, 0.2]
        chall_preds = [0.9, 0.85, 0.1]
        labels = [1, 1, 0]

        scorecard = self.engine.compare_predictions(
            champion_preds=champ_preds,
            challenger_preds=chall_preds,
            labels=labels,
            champion_id="v1.0.0",
            challenger_id="challenger_small",
        )
        self.assertEqual(scorecard.promotion_recommendation, "INSUFFICIENT_DATA")

        # Zero positives
        labels_zero = [0] * 40
        c_preds = [0.2] * 40
        ch_preds = [0.1] * 40
        scorecard_zero = self.engine.compare_predictions(
            champion_preds=c_preds,
            challenger_preds=ch_preds,
            labels=labels_zero,
        )
        self.assertEqual(scorecard_zero.promotion_recommendation, "INSUFFICIENT_DATA")

    def test_compare_by_regime_and_venue(self) -> None:
        """Verify subgroup segmentation by regime and venue."""
        n = 40
        champ_preds = [0.6 if i % 2 == 0 else 0.4 for i in range(n)]
        chall_preds = [0.8 if i % 2 == 0 else 0.2 for i in range(n)]
        labels = [1 if i % 2 == 0 else 0 for i in range(n)]

        regimes = ["HIGH_VOL" if i < 20 else "LOW_VOL" for i in range(n)]
        venues = ["RAYDIUM" if i % 2 == 0 else "METEORA" for i in range(n)]

        regime_results = self.engine.compare_by_regime(champ_preds, chall_preds, labels, regimes)
        self.assertIn("HIGH_VOL", regime_results)
        self.assertIn("LOW_VOL", regime_results)
        self.assertIn("champion_brier", regime_results["HIGH_VOL"])
        self.assertIn("challenger_brier", regime_results["HIGH_VOL"])

        venue_results = self.engine.compare_by_venue(champ_preds, chall_preds, labels, venues)
        self.assertIn("RAYDIUM", venue_results)
        self.assertIn("METEORA", venue_results)

        scorecard = self.engine.compare_predictions(
            champion_preds=champ_preds,
            challenger_preds=chall_preds,
            labels=labels,
            regimes=regimes,
            venues=venues,
        )
        self.assertEqual(len(scorecard.regime_specific_results), 2)
        self.assertEqual(len(scorecard.venue_specific_results), 2)


if __name__ == "__main__":
    unittest.main()

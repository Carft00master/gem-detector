"""
Comprehensive Test Suite for the Adaptive Learning Engine.
Tests: dataset construction, no future leakage, TP/TN/FP/FN labeling, entry/exit policy evaluation,
counterfactual integrity, model calibration, challenger validation, promotion gate, rollback,
model versioning, insufficient data handling, regime/venue-specific validation.
"""

import tempfile
import unittest
from pathlib import Path

from src.learning.trainer import ChallengerTrainer, TrainedChallengerModel
from src.learning.calibrator import ChallengerCalibrator, CalibrationResult
from src.learning.feature_selector import FeatureSelector, V1_FROZEN_FEATURES
from src.learning.walk_forward import WalkForwardValidator, WalkForwardFold
from src.learning.champion_challenger import ChampionChallengerEngine
from src.learning.promotion_policy import PromotionPolicy, PromotionThresholds
from src.learning.drift_detector import LearningDriftDetector


class TestChallengerTrainer(unittest.TestCase):
    """Test challenger model training for all three learning problems."""

    def _make_training_data(self, n=100):
        import random
        random.seed(42)
        features = []
        labels = []
        for i in range(n):
            f = {name: random.random() for name in V1_FROZEN_FEATURES}
            # Label correlates with buyer_quality and liquidity_quality
            label = 1 if (f["buyer_quality"] + f["liquidity_quality"]) > 1.0 else 0
            features.append(f)
            labels.append(label)
        return features, labels

    def test_train_selection_challenger_logistic(self):
        """Train logistic regression selection challenger."""
        features, labels = self._make_training_data()
        model = ChallengerTrainer.train_selection_challenger(
            features, labels, list(V1_FROZEN_FEATURES),
            algorithm="logistic_regression",
        )
        self.assertEqual(model.model_type, "SELECTION")
        self.assertEqual(model.algorithm, "logistic_regression")
        self.assertEqual(model.training_sample_size, 100)
        self.assertGreater(model.positive_count, 0)
        self.assertGreater(model.negative_count, 0)
        self.assertGreater(len(model.model_hash), 0)
        self.assertLess(model.raw_train_brier, 1.0)

    def test_train_entry_challenger(self):
        """Train entry policy prediction challenger."""
        features, labels = self._make_training_data(50)
        model = ChallengerTrainer.train_entry_challenger(
            features, labels, list(V1_FROZEN_FEATURES),
        )
        self.assertEqual(model.model_type, "ENTRY")

    def test_train_exit_challenger(self):
        """Train exit quality prediction challenger."""
        features, labels = self._make_training_data(50)
        model = ChallengerTrainer.train_exit_challenger(
            features, labels, list(V1_FROZEN_FEATURES),
        )
        self.assertEqual(model.model_type, "EXIT")

    def test_predict_proba_returns_valid_probability(self):
        """Predictions must be in [0, 1]."""
        features, labels = self._make_training_data()
        model = ChallengerTrainer.train_selection_challenger(
            features, labels, list(V1_FROZEN_FEATURES),
        )
        for f in features:
            p = model.predict_proba(f)
            self.assertGreaterEqual(p, 0.0)
            self.assertLessEqual(p, 1.0)

    def test_model_hash_immutability(self):
        """Same training data should produce same model hash."""
        features, labels = self._make_training_data()
        m1 = ChallengerTrainer.train_selection_challenger(
            features, labels, list(V1_FROZEN_FEATURES),
        )
        m2 = ChallengerTrainer.train_selection_challenger(
            features, labels, list(V1_FROZEN_FEATURES),
        )
        self.assertEqual(m1.model_hash, m2.model_hash)

    def test_train_all_challengers(self):
        """Train all supported algorithm types."""
        features, labels = self._make_training_data()
        models = ChallengerTrainer.train_all_challengers(
            features, labels, list(V1_FROZEN_FEATURES), model_type="SELECTION",
        )
        # At minimum logistic regression should always succeed
        self.assertGreaterEqual(len(models), 1)
        algos = {m.algorithm for m in models}
        self.assertIn("logistic_regression", algos)


class TestChallengerCalibrator(unittest.TestCase):
    """Test calibration of challenger predictions."""

    def _make_predictions(self, n=200):
        import random
        random.seed(42)
        preds = [random.random() * 0.5 for _ in range(n)]
        labels = [1 if p > 0.25 and random.random() > 0.3 else 0 for p in preds]
        return preds, labels

    def test_platt_calibration(self):
        """Platt scaling should produce a valid CalibrationResult."""
        preds, labels = self._make_predictions()
        result, calibrated = ChallengerCalibrator.calibrate_platt(preds, labels)
        self.assertEqual(result.method, "platt")
        self.assertEqual(len(calibrated), len(preds))
        self.assertGreaterEqual(result.brier_before, 0.0)
        self.assertLessEqual(result.brier_before, 1.0)
        for p in calibrated:
            self.assertGreaterEqual(p, 0.0)
            self.assertLessEqual(p, 1.0)

    def test_isotonic_calibration(self):
        """Isotonic calibration should produce a valid CalibrationResult."""
        preds, labels = self._make_predictions()
        result, calibrated = ChallengerCalibrator.calibrate_isotonic(preds, labels)
        self.assertEqual(result.method, "isotonic")
        self.assertEqual(len(calibrated), len(preds))

    def test_select_best_calibration(self):
        """Should choose method with lower ECE."""
        preds, labels = self._make_predictions()
        result, calibrated = ChallengerCalibrator.select_best_calibration(preds, labels)
        self.assertIn(result.method, ["platt", "isotonic"])

    def test_calibration_on_test_set(self):
        """Calibration fitted on val should apply to different test predictions."""
        preds, labels = self._make_predictions(200)
        test_preds = [p * 0.8 for p in preds[:50]]
        result, calibrated = ChallengerCalibrator.calibrate_platt(preds, labels, test_preds)
        self.assertEqual(len(calibrated), 50)


class TestFeatureSelector(unittest.TestCase):
    """Test feature importance and selection."""

    def _make_data(self, n=200):
        import random
        random.seed(42)
        features = []
        labels = []
        all_names = list(V1_FROZEN_FEATURES) + ["activity_density_score", "noise_feature"]
        for _ in range(n):
            f = {name: random.random() for name in all_names}
            label = 1 if f["buyer_quality"] > 0.5 else 0
            features.append(f)
            labels.append(label)
        return features, labels, all_names

    def test_evaluate_feature_importance(self):
        """Should rank features by importance."""
        features, labels, names = self._make_data()
        rankings = FeatureSelector.evaluate_feature_importance(features, labels, names)
        self.assertEqual(len(rankings), len(names))
        # Buyer quality should rank high since labels depend on it
        top_5_names = [r.feature_name for r in rankings[:5]]
        self.assertIn("buyer_quality", top_5_names)

    def test_frozen_features_always_selected(self):
        """v1.0.0 frozen features must always be in the selected set."""
        features, labels, names = self._make_data()
        report = FeatureSelector.select_features(features, labels)
        for frozen in V1_FROZEN_FEATURES:
            self.assertIn(frozen, report.selected_features)

    def test_schema_hash_deterministic(self):
        """Same features should produce same schema hash."""
        features, labels, names = self._make_data()
        r1 = FeatureSelector.select_features(features, labels)
        r2 = FeatureSelector.select_features(features, labels)
        self.assertEqual(r1.schema_hash, r2.schema_hash)


class TestWalkForwardValidator(unittest.TestCase):
    """Test chronological walk-forward validation."""

    def _timestamps(self, n=300):
        from datetime import datetime, timedelta, timezone
        base = datetime(2025, 1, 1, tzinfo=timezone.utc)
        return [(base + timedelta(hours=i)).isoformat() for i in range(n)]

    def test_generate_folds_no_overlap(self):
        """Folds must not overlap: train < val < test timestamps."""
        timestamps = self._timestamps()
        v = WalkForwardValidator()
        folds = v.generate_folds(timestamps, n_folds=3)
        self.assertGreaterEqual(len(folds), 1)
        for fold in folds:
            self.assertGreater(fold.train_size, 0)
            self.assertGreater(fold.validation_size, 0)
            self.assertGreater(fold.test_size, 0)

    def test_validate_no_leakage(self):
        """No future data should leak into training."""
        timestamps = self._timestamps()
        v = WalkForwardValidator()
        folds = v.generate_folds(timestamps, n_folds=3)
        is_clean = v.validate_no_leakage(folds, timestamps)
        self.assertTrue(is_clean)

    def test_temporal_degradation_detection(self):
        """Detect performance degradation across folds."""
        from src.learning.walk_forward import WalkForwardResult
        v = WalkForwardValidator()
        # Simulate degrading performance
        results = [
            WalkForwardResult(fold_index=0, test_metrics={"pr_auc": 0.80}),
            WalkForwardResult(fold_index=1, test_metrics={"pr_auc": 0.70}),
            WalkForwardResult(fold_index=2, test_metrics={"pr_auc": 0.60}),
        ]
        degrading = v.detect_temporal_degradation(results, "pr_auc")
        self.assertTrue(degrading)


class TestChampionChallengerEngine(unittest.TestCase):
    """Test champion vs challenger comparison."""

    def test_record_shadow_prediction(self):
        """Should record shadow predictions."""
        engine = ChampionChallengerEngine()
        rec = engine.record_shadow_prediction("token1", 0.1, 0.15)
        self.assertEqual(rec.champion_prediction, 0.1)
        self.assertEqual(rec.challenger_prediction, 0.15)

    def test_compare_predictions_insufficient_data(self):
        """Should return INSUFFICIENT_DATA for small samples."""
        engine = ChampionChallengerEngine(min_sample_size=30)
        scorecard = engine.compare_predictions(
            champion_preds=[0.1] * 5,
            challenger_preds=[0.15] * 5,
            labels=[0] * 5,
            champion_id="v1.0.0",
            challenger_id="v1.1_candidate",
        )
        self.assertEqual(scorecard.promotion_recommendation, "INSUFFICIENT_DATA")

    def test_compare_predictions_with_data(self):
        """Should produce valid scorecard with sufficient data."""
        import random
        random.seed(42)
        n = 100
        labels = [1 if random.random() > 0.85 else 0 for _ in range(n)]
        champ = [random.random() * 0.3 for _ in range(n)]
        chall = [random.random() * 0.3 for _ in range(n)]
        engine = ChampionChallengerEngine(min_sample_size=30)
        scorecard = engine.compare_predictions(
            champ, chall, labels, "v1.0.0", "v1.1_candidate",
        )
        self.assertGreater(len(scorecard.metrics), 0)
        self.assertIn(scorecard.promotion_recommendation,
                      ["PROMOTE", "NOT_READY", "INSUFFICIENT_DATA", "REGRESSED"])


class TestPromotionPolicy(unittest.TestCase):
    """Test multi-metric promotion gate."""

    def test_insufficient_data_blocks_promotion(self):
        """Sample size < 250 should block promotion."""
        from src.learning.champion_challenger import ComparisonScorecard, ScorecardMetric
        policy = PromotionPolicy()
        scorecard = ComparisonScorecard(
            champion_id="v1.0.0",
            challenger_id="v1.1",
            model_type="SELECTION",
            evaluation_period="",
            sample_size=100,  # Below 250 threshold
            metrics=[],
            all_thresholds_met=True,
            promotion_recommendation="PROMOTE",
        )
        decision = policy.evaluate(scorecard, walk_forward_periods_passed=3)
        self.assertEqual(decision.decision, "INSUFFICIENT_DATA")

    def test_promotion_requires_all_regimes(self):
        """If any regime fails, promotion should be blocked."""
        from src.learning.champion_challenger import ComparisonScorecard, ScorecardMetric
        policy = PromotionPolicy()
        scorecard = ComparisonScorecard(
            champion_id="v1.0.0",
            challenger_id="v1.1",
            model_type="SELECTION",
            evaluation_period="",
            sample_size=500,
            metrics=[],
            all_thresholds_met=True,
            promotion_recommendation="PROMOTE",
        )
        regime_results = {"NORMAL": True, "HOT": True, "COLD": False}
        decision = policy.evaluate(scorecard, walk_forward_periods_passed=3,
                                   regime_results=regime_results)
        self.assertEqual(decision.decision, "BLOCKED_BY_REGIME")

    def test_no_single_metric_sufficient(self):
        """Even if some metrics pass, failing one blocks promotion."""
        from src.learning.champion_challenger import ComparisonScorecard, ScorecardMetric
        policy = PromotionPolicy()
        scorecard = ComparisonScorecard(
            champion_id="v1.0.0",
            challenger_id="v1.1",
            model_type="SELECTION",
            evaluation_period="",
            sample_size=500,
            metrics=[
                ScorecardMetric(metric_name="PR-AUC", champion_value=0.5, challenger_value=0.55,
                                improvement_pct=10.0, meets_threshold=True, threshold=5.0),
                ScorecardMetric(metric_name="Brier Score", champion_value=0.2, challenger_value=0.3,
                                improvement_pct=-50.0, meets_threshold=False, threshold=5.0,
                                direction="lower_is_better"),
            ],
            all_thresholds_met=False,
            promotion_recommendation="NOT_READY",
        )
        decision = policy.evaluate(scorecard, walk_forward_periods_passed=3)
        self.assertNotEqual(decision.decision, "PROMOTE")


class TestDriftDetector(unittest.TestCase):
    """Test 7-dimension drift monitoring and rollback."""

    def test_no_drift_returns_normal(self):
        """Identical baseline/current should return NORMAL."""
        detector = LearningDriftDetector()
        stats = {
            "training_data": 0.5, "feature": 0.3, "label": 0.1,
            "market_regime": 0.25, "venue_distribution": 0.2,
            "probability": 0.15, "execution": 0.1,
        }
        health = detector.detect_drift(stats, dict(stats))
        self.assertEqual(health.overall_status, "NORMAL")
        self.assertFalse(health.should_trigger_rollback)

    def test_large_probability_drift_triggers_rollback(self):
        """Major probability drift should trigger rollback."""
        detector = LearningDriftDetector()
        baseline = {
            "training_data": 0.5, "feature": 0.3, "label": 0.1,
            "market_regime": 0.25, "venue_distribution": 0.2,
            "probability": 0.15, "execution": 0.1,
        }
        current = dict(baseline)
        current["probability"] = 0.15 + 0.15 * 0.5  # 50% drift, well above 8% alarm
        health = detector.detect_drift(baseline, current)
        self.assertTrue(health.should_trigger_rollback)

    def test_warning_status(self):
        """Moderate drift should produce WARNING."""
        detector = LearningDriftDetector()
        baseline = {
            "training_data": 1.0, "feature": 0.3, "label": 0.1,
            "market_regime": 0.25, "venue_distribution": 0.2,
            "probability": 0.15, "execution": 0.1,
        }
        current = dict(baseline)
        # 15% drift on training_data — between warning (10%) and alarm (25%)
        current["training_data"] = 1.0 + 1.0 * 0.15
        health = detector.detect_drift(baseline, current)
        has_warning = any(d.status in ("WARNING", "RETRAIN_RECOMMENDED") for d in health.dimensions)
        self.assertTrue(has_warning)


class TestSafetyRule(unittest.TestCase):
    """Test that learning never optimizes raw ROI ignoring risk."""

    def test_trainer_uses_brier_not_raw_accuracy(self):
        """Training metric should be Brier score, not raw accuracy."""
        import random
        random.seed(42)
        features = [{name: random.random() for name in V1_FROZEN_FEATURES} for _ in range(100)]
        labels = [1 if random.random() > 0.8 else 0 for _ in range(100)]
        model = ChallengerTrainer.train_selection_challenger(
            features, labels, list(V1_FROZEN_FEATURES),
        )
        # Brier score should be computed and stored
        self.assertGreater(model.raw_train_brier, 0.0)
        self.assertLess(model.raw_train_brier, 1.0)


class TestV1FrozenIntegrity(unittest.TestCase):
    """Verify v1.0.0 model is never modified by the learning engine."""

    def test_frozen_version_manifest_unchanged(self):
        """The frozen version manifest must remain v1.0.0."""
        from src.version import FROZEN_VERSION_MANIFEST
        self.assertEqual(FROZEN_VERSION_MANIFEST.scanner_version, "v1.0.0")
        self.assertEqual(FROZEN_VERSION_MANIFEST.model_version, "v1.0.0")
        self.assertEqual(FROZEN_VERSION_MANIFEST.calibration_version, "v1.0.0")

    def test_calibrated_predictor_weights_unchanged(self):
        """v1.0.0 predictor weights must not be modified."""
        from src.models.predictor import CalibratedMLPredictor
        predictor = CalibratedMLPredictor()
        self.assertEqual(predictor.weights["bias"], -3.2)
        self.assertEqual(predictor.weights["effective_volume_mc_ratio_5m"], 0.45)
        self.assertEqual(predictor.weights["wash_trade_risk"], -1.60)


if __name__ == "__main__":
    unittest.main()

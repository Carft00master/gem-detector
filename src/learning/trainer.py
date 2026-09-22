"""
Challenger Model Trainer (Adaptive Learning Engine)
Trains multiple challenger model types for each of the three learning problems:
- Model A — Selection: P(100K), P(500K), P(1M), P(3M)
- Model B — Entry: Expected MFE, MAE, optimal entry condition
- Model C — Exit: Expected return, drawdown, optimal exit action
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import logging
import math
from typing import Any, Dict, List, Optional, Tuple
import uuid

logger = logging.getLogger(__name__)


@dataclass
class TrainedChallengerModel:
    model_id: str
    model_type: str           # 'SELECTION' | 'ENTRY' | 'EXIT'
    algorithm: str            # 'logistic_regression' | 'gradient_boosting' | 'hist_gradient_boosting'
    feature_names: List[str]
    weights: Dict[str, float]  # For logistic regression; tree models store parameters differently
    intercept: float = 0.0
    calibration_method: str = "none"

    # Training Metadata
    training_sample_size: int = 0
    positive_count: int = 0
    negative_count: int = 0
    training_period: str = ""
    model_hash: str = ""

    # Raw Validation Metrics (before calibration)
    raw_train_brier: float = 1.0
    raw_val_brier: float = 1.0
    raw_val_pr_auc: Optional[float] = None
    raw_val_precision_at_10: float = 0.0

    def predict_proba(self, features: Dict[str, float]) -> float:
        """Produce uncalibrated probability from logistic regression weights."""
        logit = self.intercept
        for fname, weight in self.weights.items():
            logit += weight * features.get(fname, 0.0)
        logit = max(-15.0, min(15.0, logit))
        return 1.0 / (1.0 + math.exp(-logit))

    def compute_hash(self) -> str:
        """SHA-256 hash of model weights for immutable versioning."""
        payload = json.dumps({
            "algorithm": self.algorithm,
            "intercept": self.intercept,
            "weights": dict(sorted(self.weights.items())),
            "feature_names": sorted(self.feature_names),
        }, sort_keys=True)
        return hashlib.sha256(payload.encode()).hexdigest()[:16]


class ChallengerTrainer:
    """
    Trains challenger models using logistic regression, gradient boosting,
    and histogram gradient boosting for each learning problem.
    """

    SUPPORTED_ALGORITHMS = [
        "logistic_regression",
        "gradient_boosting",
        "hist_gradient_boosting",
    ]

    @classmethod
    def train_selection_challenger(
        cls,
        features: List[Dict[str, float]],
        labels: List[int],
        feature_names: List[str],
        algorithm: str = "logistic_regression",
        target_name: str = "TARGET_3M",
        training_period: str = "",
    ) -> TrainedChallengerModel:
        """Train a selection challenger model predicting target achievement probability."""
        return cls._train_binary_classifier(
            features=features,
            labels=labels,
            feature_names=feature_names,
            algorithm=algorithm,
            model_type="SELECTION",
            training_period=training_period,
        )

    @classmethod
    def train_entry_challenger(
        cls,
        features: List[Dict[str, float]],
        labels: List[int],
        feature_names: List[str],
        algorithm: str = "logistic_regression",
        training_period: str = "",
    ) -> TrainedChallengerModel:
        """Train an entry quality prediction model."""
        return cls._train_binary_classifier(
            features=features,
            labels=labels,
            feature_names=feature_names,
            algorithm=algorithm,
            model_type="ENTRY",
            training_period=training_period,
        )

    @classmethod
    def train_exit_challenger(
        cls,
        features: List[Dict[str, float]],
        labels: List[int],
        feature_names: List[str],
        algorithm: str = "logistic_regression",
        training_period: str = "",
    ) -> TrainedChallengerModel:
        """Train an exit quality prediction model."""
        return cls._train_binary_classifier(
            features=features,
            labels=labels,
            feature_names=feature_names,
            algorithm=algorithm,
            model_type="EXIT",
            training_period=training_period,
        )

    @classmethod
    def _train_binary_classifier(
        cls,
        features: List[Dict[str, float]],
        labels: List[int],
        feature_names: List[str],
        algorithm: str,
        model_type: str,
        training_period: str,
    ) -> TrainedChallengerModel:
        """
        Core training function. Uses sklearn if available, falls back to manual
        logistic regression via iterative gradient descent.
        """
        n = len(features)
        n_pos = sum(labels)
        n_neg = n - n_pos

        if algorithm == "logistic_regression":
            weights, intercept = cls._fit_logistic_regression(features, labels, feature_names)
        elif algorithm in ("gradient_boosting", "hist_gradient_boosting"):
            # Try sklearn; fall back to logistic regression if not available
            try:
                weights, intercept = cls._fit_sklearn_gbm(features, labels, feature_names, algorithm)
            except ImportError:
                logger.warning(f"sklearn not available for {algorithm}, falling back to logistic regression")
                weights, intercept = cls._fit_logistic_regression(features, labels, feature_names)
                algorithm = "logistic_regression"
        else:
            weights, intercept = cls._fit_logistic_regression(features, labels, feature_names)

        model = TrainedChallengerModel(
            model_id=str(uuid.uuid4())[:12],
            model_type=model_type,
            algorithm=algorithm,
            feature_names=feature_names,
            weights=weights,
            intercept=intercept,
            training_sample_size=n,
            positive_count=n_pos,
            negative_count=n_neg,
            training_period=training_period,
        )
        model.model_hash = model.compute_hash()

        # Compute training metrics
        train_preds = [model.predict_proba(f) for f in features]
        model.raw_train_brier = cls._compute_brier(train_preds, labels)

        return model

    @classmethod
    def _fit_logistic_regression(
        cls,
        features: List[Dict[str, float]],
        labels: List[int],
        feature_names: List[str],
        learning_rate: float = 0.01,
        max_iterations: int = 500,
        l2_lambda: float = 0.1,
    ) -> Tuple[Dict[str, float], float]:
        """
        Manual L2-regularized logistic regression via mini-batch gradient descent.
        """
        n = len(features)
        weights = {f: 0.0 for f in feature_names}
        intercept = 0.0

        for iteration in range(max_iterations):
            grad_w = {f: 0.0 for f in feature_names}
            grad_b = 0.0

            for i in range(n):
                logit = intercept + sum(weights[f] * features[i].get(f, 0.0) for f in feature_names)
                logit = max(-15.0, min(15.0, logit))
                p = 1.0 / (1.0 + math.exp(-logit))
                error = p - labels[i]

                for f in feature_names:
                    grad_w[f] += error * features[i].get(f, 0.0) / n
                grad_b += error / n

            # Update with L2 regularization
            for f in feature_names:
                weights[f] -= learning_rate * (grad_w[f] + l2_lambda * weights[f] / n)
            intercept -= learning_rate * grad_b

        return weights, intercept

    @classmethod
    def _fit_sklearn_gbm(
        cls,
        features: List[Dict[str, float]],
        labels: List[int],
        feature_names: List[str],
        algorithm: str,
    ) -> Tuple[Dict[str, float], float]:
        """
        Fit using sklearn gradient boosting, extract feature importances as pseudo-weights.
        """
        from sklearn.ensemble import GradientBoostingClassifier, HistGradientBoostingClassifier
        import numpy as np

        X = np.array([[f.get(fname, 0.0) for fname in feature_names] for f in features])
        y = np.array(labels)

        if algorithm == "hist_gradient_boosting":
            clf = HistGradientBoostingClassifier(
                max_iter=100, max_depth=4, learning_rate=0.1, min_samples_leaf=20, random_state=42
            )
        else:
            clf = GradientBoostingClassifier(
                n_estimators=100, max_depth=4, learning_rate=0.1, min_samples_leaf=20, random_state=42
            )

        clf.fit(X, y)

        # Extract feature importances as pseudo-weights
        importances = clf.feature_importances_
        weights = {fname: float(imp) for fname, imp in zip(feature_names, importances)}

        return weights, 0.0

    @staticmethod
    def _compute_brier(predictions: List[float], labels: List[int]) -> float:
        n = len(predictions)
        if n == 0:
            return 1.0
        return sum((p - y) ** 2 for p, y in zip(predictions, labels)) / n

    @classmethod
    def train_all_challengers(
        cls,
        features: List[Dict[str, float]],
        labels: List[int],
        feature_names: List[str],
        model_type: str = "SELECTION",
        training_period: str = "",
    ) -> List[TrainedChallengerModel]:
        """Train challengers using all supported algorithms and return the list."""
        challengers = []
        for algo in cls.SUPPORTED_ALGORITHMS:
            try:
                model = cls._train_binary_classifier(
                    features=features,
                    labels=labels,
                    feature_names=feature_names,
                    algorithm=algo,
                    model_type=model_type,
                    training_period=training_period,
                )
                challengers.append(model)
                logger.info(f"Trained {algo} challenger for {model_type}: brier={model.raw_train_brier:.4f}")
            except Exception as e:
                logger.warning(f"Failed to train {algo} for {model_type}: {e}")
        return challengers

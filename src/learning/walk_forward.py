"""
Chronological Walk-Forward Validation Engine
Provides strictly chronological rolling-window and expanding-window validation partitions,
leakage verification, cross-fold stability scoring, and temporal degradation detection.
"""

from dataclasses import dataclass, field
from datetime import datetime
import logging
import math
import statistics
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


def _parse_iso_timestamp(ts_str: str) -> datetime:
    """Safely parse an ISO 8601 timestamp string into a timezone-aware or naive datetime."""
    try:
        clean_ts = ts_str.replace("Z", "+00:00")
        return datetime.fromisoformat(clean_ts)
    except Exception:
        try:
            return datetime.fromisoformat(ts_str)
        except Exception:
            return datetime.min


@dataclass
class WalkForwardFold:
    """
    Represents a single chronological train/validation/test fold.
    
    Guarantees strict chronological ordering with non-overlapping indices:
    Train [T0 -> T1] < Validation [T1 -> T2] < Test [T2 -> T3].
    """
    fold_index: int
    train_start: str
    train_end: str
    validation_start: str
    validation_end: str
    test_start: str
    test_end: str
    train_size: int
    validation_size: int
    test_size: int
    train_indices: List[int] = field(default_factory=list)
    validation_indices: List[int] = field(default_factory=list)
    test_indices: List[int] = field(default_factory=list)


@dataclass
class WalkForwardResult:
    """
    Performance metrics and diagnostics for a single walk-forward fold evaluation.
    """
    fold_index: int
    train_metrics: Dict[str, float] = field(default_factory=dict)
    validation_metrics: Dict[str, float] = field(default_factory=dict)
    test_metrics: Dict[str, float] = field(default_factory=dict)
    is_overfitting: bool = False  # True if validation/train performance >> test performance
    stability_score: float = 0.0  # Cross-fold metric stability


@dataclass
class WalkForwardReport:
    """
    Synthesized validation report aggregating performance and diagnostics across all folds.
    """
    total_folds: int
    total_observations: int
    fold_results: List[WalkForwardResult] = field(default_factory=list)
    mean_test_pr_auc: float = 0.0
    std_test_pr_auc: float = 0.0
    mean_test_brier: float = 0.0
    mean_test_precision_at_10: float = 0.0
    cross_fold_stability_score: float = 0.0  # 1.0 = perfectly stable
    has_temporal_degradation: bool = False
    summary: str = ""


class WalkForwardValidator:
    """
    Chronological Walk-Forward Cross-Validation Engine.
    
    Implements expanding/rolling window validation to ensure no future lookahead
    bias, verifies zero leakage between partitions, computes metric stability,
    and detects performance degradation over time.
    """
    DEFAULT_TRAIN_RATIO: float = 0.60
    DEFAULT_VALIDATION_RATIO: float = 0.20
    DEFAULT_TEST_RATIO: float = 0.20
    MIN_FOLD_SIZE: int = 50

    def generate_folds(
        self,
        timestamps: List[str],
        n_folds: int = 3,
        train_ratio: float = 0.60,
        val_ratio: float = 0.20,
        test_ratio: float = 0.20,
    ) -> List[WalkForwardFold]:
        """
        Generate strictly chronological expanding-window walk-forward folds.
        
        Timestamps are sorted chronologically without random shuffling.
        Each fold uses strictly earlier data for training, followed by validation and test sets.
        
        Expanding Window Schedule (default 3 folds):
        - Fold 1: First 60% train, next 20% val, next 20% test
        - Fold 2: First 70% train, next 15% val, next 15% test
        - Fold 3: First 80% train, next 10% val, last 10% test
        
        Args:
            timestamps: List of ISO 8601 timestamp strings corresponding to observations.
            n_folds: Number of walk-forward folds to create (default: 3).
            train_ratio: Initial training split ratio for the first fold (default: 0.60).
            val_ratio: Initial validation split ratio for the first fold (default: 0.20).
            test_ratio: Initial test split ratio for the first fold (default: 0.20).
            
        Returns:
            List of WalkForwardFold instances with chronological slices and index mappings.
        """
        if not timestamps:
            logger.warning("Empty timestamp list provided to generate_folds.")
            return []

        n_obs = len(timestamps)
        if n_obs < self.MIN_FOLD_SIZE:
            logger.warning(
                f"Dataset size ({n_obs}) is below recommended MIN_FOLD_SIZE ({self.MIN_FOLD_SIZE})."
            )

        if n_folds < 1:
            raise ValueError(f"n_folds must be >= 1, got {n_folds}")

        # Ensure minimum observations to create 3 non-empty splits
        if n_obs < 3:
            logger.error(f"Cannot generate folds: need at least 3 observations, got {n_obs}.")
            return []

        # Chronologically sort indices according to timestamp
        sorted_indices = sorted(
            range(n_obs),
            key=lambda idx: (_parse_iso_timestamp(timestamps[idx]), timestamps[idx], idx),
        )

        folds: List[WalkForwardFold] = []

        for fold_idx in range(n_folds):
            if n_folds == 1:
                cur_train_prop = train_ratio
                cur_val_prop = val_ratio
            else:
                # Expanding window progression:
                # Train ratio increases linearly from train_ratio up to 0.80 (or max possible).
                max_train = max(train_ratio, 0.80)
                cur_train_prop = train_ratio + fold_idx * ((max_train - train_ratio) / (n_folds - 1))
                remaining_prop = max(0.0, 1.0 - cur_train_prop)
                cur_val_prop = remaining_prop / 2.0

            # Calculate index boundaries
            train_end_idx = int(round(n_obs * cur_train_prop))
            val_end_idx = int(round(n_obs * (cur_train_prop + cur_val_prop)))

            # Clamp boundaries to guarantee non-empty slices and chronological progression
            train_end_idx = max(1, min(train_end_idx, n_obs - 2))
            val_end_idx = max(train_end_idx + 1, min(val_end_idx, n_obs - 1))
            test_end_idx = n_obs

            train_idxs = sorted_indices[0:train_end_idx]
            val_idxs = sorted_indices[train_end_idx:val_end_idx]
            test_idxs = sorted_indices[val_end_idx:test_end_idx]

            fold = WalkForwardFold(
                fold_index=fold_idx,
                train_start=timestamps[train_idxs[0]],
                train_end=timestamps[train_idxs[-1]],
                validation_start=timestamps[val_idxs[0]],
                validation_end=timestamps[val_idxs[-1]],
                test_start=timestamps[test_idxs[0]],
                test_end=timestamps[test_idxs[-1]],
                train_size=len(train_idxs),
                validation_size=len(val_idxs),
                test_size=len(test_idxs),
                train_indices=train_idxs,
                validation_indices=val_idxs,
                test_indices=test_idxs,
            )
            folds.append(fold)

        return folds

    def validate_no_leakage(
        self,
        folds: List[WalkForwardFold],
        timestamps: List[str],
    ) -> bool:
        """
        Verify that for every fold:
        max(train_timestamps) <= min(validation_timestamps) <= max(val_timestamps) <= min(test_timestamps)
        and that index sets are strictly disjoint.
        
        Args:
            folds: List of WalkForwardFold instances.
            timestamps: List of ISO 8601 timestamp strings corresponding to indices.
            
        Returns:
            True if all folds strictly adhere to chronological non-leakage, False otherwise.
        """
        if not folds or not timestamps:
            logger.warning("Empty folds or timestamps provided to validate_no_leakage.")
            return False

        n_obs = len(timestamps)

        for fold in folds:
            if not fold.train_indices or not fold.validation_indices or not fold.test_indices:
                logger.error(f"Fold {fold.fold_index} contains empty partition indices.")
                return False

            # Check index bounds
            all_indices = fold.train_indices + fold.validation_indices + fold.test_indices
            if any(i < 0 or i >= n_obs for i in all_indices):
                logger.error(f"Fold {fold.fold_index} contains out-of-bounds indices.")
                return False

            # Check disjoint index sets (zero sample overlap)
            train_set = set(fold.train_indices)
            val_set = set(fold.validation_indices)
            test_set = set(fold.test_indices)

            if train_set.intersection(val_set) or train_set.intersection(test_set) or val_set.intersection(test_set):
                logger.error(f"Fold {fold.fold_index} has overlapping sample indices between splits.")
                return False

            # Convert to datetimes for strict temporal comparison
            train_dts = [_parse_iso_timestamp(timestamps[i]) for i in fold.train_indices]
            val_dts = [_parse_iso_timestamp(timestamps[i]) for i in fold.validation_indices]
            test_dts = [_parse_iso_timestamp(timestamps[i]) for i in fold.test_indices]

            max_train_dt = max(train_dts)
            min_val_dt = min(val_dts)
            max_val_dt = max(val_dts)
            min_test_dt = min(test_dts)

            if max_train_dt > min_val_dt:
                logger.error(
                    f"Fold {fold.fold_index} train->val leakage: "
                    f"max(train)={max_train_dt.isoformat()} > min(val)={min_val_dt.isoformat()}"
                )
                return False

            if max_val_dt > min_test_dt:
                logger.error(
                    f"Fold {fold.fold_index} val->test leakage: "
                    f"max(val)={max_val_dt.isoformat()} > min(test)={min_test_dt.isoformat()}"
                )
                return False

        return True

    def compute_stability_score(
        self,
        fold_results: List[WalkForwardResult],
        metric_key: str = "brier_score",
    ) -> float:
        """
        Calculate the cross-fold stability score for a given metric using Coefficient of Variation.
        
        Score = 1.0 - min(1.0, CV), where CV = standard_deviation / mean.
        A score of 1.0 indicates perfect cross-fold consistency; 0.0 indicates extreme variance.
        
        Args:
            fold_results: List of WalkForwardResult instances.
            metric_key: Metric key to evaluate (e.g., 'brier_score', 'pr_auc', 'precision_at_10').
            
        Returns:
            Stability score float in range [0.0, 1.0].
        """
        if not fold_results:
            return 0.0

        values: List[float] = []
        for res in fold_results:
            val = res.test_metrics.get(metric_key)
            if val is None:
                val = res.validation_metrics.get(metric_key)
            if val is None:
                val = res.train_metrics.get(metric_key)
            if val is not None:
                values.append(float(val))

        if not values:
            return 0.0

        if len(values) == 1:
            return 1.0

        mean_val = statistics.mean(values)
        stdev_val = statistics.stdev(values)

        if abs(mean_val) < 1e-9:
            # If mean is 0 and stdev is 0, metric is perfectly stable at 0
            return 1.0 if stdev_val < 1e-9 else 0.0

        cv = abs(stdev_val / mean_val)
        stability = max(0.0, 1.0 - min(1.0, cv))
        return float(stability)

    def detect_temporal_degradation(
        self,
        fold_results: List[WalkForwardResult],
        metric_key: str = "pr_auc",
    ) -> bool:
        """
        Determine whether later folds show consistent performance degradation over time.
        
        For higher-is-better metrics (PR-AUC, Precision, Recall, ROC-AUC, F1):
        Degradation is detected when performance decreases chronologically.
        
        For lower-is-better metrics (Brier score, Loss, MSE, RMSE, FPR):
        Degradation is detected when error increases chronologically.
        
        Args:
            fold_results: List of WalkForwardResult instances.
            metric_key: Key of the metric to analyze (default: 'pr_auc').
            
        Returns:
            True if consistent temporal degradation is detected, False otherwise.
        """
        if not fold_results or len(fold_results) < 2:
            return False

        # Ensure chronological order by fold_index
        sorted_results = sorted(fold_results, key=lambda r: r.fold_index)

        values: List[float] = []
        for res in sorted_results:
            val = res.test_metrics.get(metric_key)
            if val is None:
                val = res.validation_metrics.get(metric_key)
            if val is not None:
                values.append(float(val))

        if len(values) < 2:
            return False

        lower_is_better_keys = {
            "brier",
            "brier_score",
            "loss",
            "log_loss",
            "mse",
            "rmse",
            "mae",
            "ece",
            "fpr",
            "false_positive_rate",
        }
        lower_is_better = any(k in metric_key.lower() for k in lower_is_better_keys)

        n = len(values)
        x_mean = (n - 1) / 2.0
        y_mean = statistics.mean(values)
        cov_xy = sum((i - x_mean) * (values[i] - y_mean) for i in range(n))
        var_x = sum((i - x_mean) ** 2 for i in range(n))
        slope = (cov_xy / var_x) if var_x > 0 else 0.0

        if lower_is_better:
            # Positive slope or monotonically increasing error means degradation
            monotonic_decline = all(values[i] <= values[i + 1] for i in range(n - 1)) and values[-1] > values[0]
            trend_decline = slope > 0.0 and values[-1] > values[0]
            return monotonic_decline or trend_decline
        else:
            # Negative slope or monotonically decreasing performance means degradation
            monotonic_decline = all(values[i] >= values[i + 1] for i in range(n - 1)) and values[-1] < values[0]
            trend_decline = slope < 0.0 and values[-1] < values[0]
            return monotonic_decline or trend_decline

    def check_overfitting(
        self,
        result: WalkForwardResult,
        metric_key: str = "pr_auc",
        threshold: float = 0.15,
    ) -> bool:
        """
        Check if validation or training performance substantially exceeds test performance.
        
        Args:
            result: WalkForwardResult instance for a fold.
            metric_key: Primary metric key to compare (default: 'pr_auc').
            threshold: Divergence gap indicating overfitting (default: 0.15).
            
        Returns:
            True if overfitting is detected, False otherwise.
        """
        train_val = result.train_metrics.get(metric_key)
        val_val = result.validation_metrics.get(metric_key)
        test_val = result.test_metrics.get(metric_key)

        if test_val is None:
            return False

        lower_is_better_keys = {
            "brier",
            "brier_score",
            "loss",
            "log_loss",
            "mse",
            "rmse",
            "mae",
            "ece",
            "fpr",
            "false_positive_rate",
        }
        lower_is_better = any(k in metric_key.lower() for k in lower_is_better_keys)

        if lower_is_better:
            # Overfitting if test error >> val error or test error >> train error
            if val_val is not None and (test_val - val_val) > threshold:
                return True
            if train_val is not None and (test_val - train_val) > threshold:
                return True
        else:
            # Overfitting if val/train performance >> test performance
            if val_val is not None and (val_val - test_val) > threshold:
                return True
            if train_val is not None and (train_val - test_val) > threshold:
                return True

        return False

    def build_report(
        self,
        fold_results: List[WalkForwardResult],
        total_observations: int,
    ) -> WalkForwardReport:
        """
        Synthesize fold-level evaluation results into an aggregate WalkForwardReport.
        
        Args:
            fold_results: List of WalkForwardResult instances across all folds.
            total_observations: Total number of observations in the dataset.
            
        Returns:
            WalkForwardReport containing summary statistics, stability scores, and degradation status.
        """
        if not fold_results:
            return WalkForwardReport(
                total_folds=0,
                total_observations=total_observations,
                fold_results=[],
                summary="No fold results available.",
            )

        pr_aucs: List[float] = []
        brier_scores: List[float] = []
        p_at_10s: List[float] = []

        for res in fold_results:
            # Check for PR-AUC in test metrics
            for k in ["pr_auc", "pr-auc", "auc_pr", "test_pr_auc"]:
                if k in res.test_metrics:
                    pr_aucs.append(float(res.test_metrics[k]))
                    break

            # Check for Brier Score in test metrics
            for k in ["brier_score", "brier", "test_brier", "test_brier_score"]:
                if k in res.test_metrics:
                    brier_scores.append(float(res.test_metrics[k]))
                    break

            # Check for Precision@10 in test metrics
            for k in [
                "precision_at_10",
                "p@10",
                "primary_first_alert_precision_at_10",
                "test_precision_at_10",
            ]:
                if k in res.test_metrics:
                    p_at_10s.append(float(res.test_metrics[k]))
                    break

        mean_pr_auc = float(statistics.mean(pr_aucs)) if pr_aucs else 0.0
        std_pr_auc = float(statistics.stdev(pr_aucs)) if len(pr_aucs) > 1 else 0.0
        mean_brier = float(statistics.mean(brier_scores)) if brier_scores else 0.0
        mean_p10 = float(statistics.mean(p_at_10s)) if p_at_10s else 0.0

        # Choose primary stability metric (brier_score preferred, then pr_auc)
        stability_metric = "brier_score" if brier_scores else "pr_auc"
        stability = self.compute_stability_score(fold_results, metric_key=stability_metric)

        # Detect temporal degradation
        degradation_metric = "pr_auc" if pr_aucs else "brier_score"
        has_degradation = self.detect_temporal_degradation(fold_results, metric_key=degradation_metric)

        overfitting_count = sum(1 for r in fold_results if r.is_overfitting)

        summary_lines = [
            "=== Walk-Forward Validation Report ===",
            f"Total Observations: {total_observations:,}",
            f"Total Folds: {len(fold_results)}",
            f"Mean Test PR-AUC: {mean_pr_auc:.4f} (+/- {std_pr_auc:.4f})",
            f"Mean Test Brier Score: {mean_brier:.4f}",
            f"Mean Test Precision@10: {mean_p10:.4f}",
            f"Cross-Fold Stability Score: {stability:.4f} (1.0 = perfect)",
            f"Temporal Degradation Detected: {'YES' if has_degradation else 'NO'}",
            f"Overfitting Folds: {overfitting_count} / {len(fold_results)}",
        ]

        return WalkForwardReport(
            total_folds=len(fold_results),
            total_observations=total_observations,
            fold_results=fold_results,
            mean_test_pr_auc=mean_pr_auc,
            std_test_pr_auc=std_pr_auc,
            mean_test_brier=mean_brier,
            mean_test_precision_at_10=mean_p10,
            cross_fold_stability_score=stability,
            has_temporal_degradation=has_degradation,
            summary="\n".join(summary_lines),
        )

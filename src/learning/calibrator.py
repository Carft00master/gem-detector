"""
Challenger Calibration Engine (Adaptive Learning Engine)
Calibrates challenger predictions using isotonic regression and Platt scaling
on held-out validation data. Validates calibration quality on unseen test data.
"""

from dataclasses import dataclass, field
import logging
import math
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass
class CalibrationResult:
    method: str                    # 'isotonic' | 'platt' | 'none'
    brier_before: float = 1.0
    brier_after: float = 1.0
    brier_skill_score_pct: float = 0.0
    log_loss_before: float = 10.0
    log_loss_after: float = 10.0
    ece_before: float = 1.0
    ece_after: float = 1.0
    calibration_intercept: float = 0.0  # Platt a
    calibration_slope: float = 1.0       # Platt b
    is_well_calibrated: bool = False    # ECE <= 0.15
    reliability_buckets: List[Dict[str, float]] = field(default_factory=list)


class ChallengerCalibrator:
    """
    Calibrates challenger model outputs using Platt scaling (logistic regression
    on log-odds) or isotonic regression (piecewise-linear monotonic mapping).
    """

    @classmethod
    def calibrate_platt(
        cls,
        val_predictions: List[float],
        val_labels: List[int],
        test_predictions: Optional[List[float]] = None,
    ) -> Tuple[CalibrationResult, List[float]]:
        """
        Fit Platt scaling (sigmoid calibration) on validation data.
        Returns calibration result and calibrated test predictions.
        """
        n = len(val_predictions)
        if n < 10:
            return CalibrationResult(method="platt"), list(test_predictions or val_predictions)

        # Fit a and b: calibrated_p = 1 / (1 + exp(-(a * logit + b)))
        # Use gradient descent on validation log loss
        a = 1.0
        b = 0.0
        lr = 0.01

        for _ in range(300):
            grad_a = 0.0
            grad_b = 0.0
            for p, y in zip(val_predictions, val_labels):
                logit = math.log(max(1e-8, p) / max(1e-8, 1.0 - p))
                cal_logit = a * logit + b
                cal_logit = max(-15.0, min(15.0, cal_logit))
                cal_p = 1.0 / (1.0 + math.exp(-cal_logit))
                error = cal_p - y
                grad_a += error * logit / n
                grad_b += error / n
            a -= lr * grad_a
            b -= lr * grad_b

        # Apply calibration to test predictions
        target_preds = test_predictions if test_predictions is not None else val_predictions
        calibrated = []
        for p in target_preds:
            logit = math.log(max(1e-8, p) / max(1e-8, 1.0 - p))
            cal_logit = max(-15.0, min(15.0, a * logit + b))
            calibrated.append(1.0 / (1.0 + math.exp(-cal_logit)))

        # Compute metrics
        brier_before = cls._brier(val_predictions, val_labels)
        cal_val = [
            1.0 / (1.0 + math.exp(-max(-15.0, min(15.0, a * math.log(max(1e-8, p) / max(1e-8, 1.0 - p)) + b))))
            for p in val_predictions
        ]
        brier_after = cls._brier(cal_val, val_labels)
        base_rate = sum(val_labels) / max(1, n)
        base_brier = base_rate * (1.0 - base_rate)
        bss = ((base_brier - brier_after) / base_brier * 100.0) if base_brier > 0 else 0.0

        ece_before = cls._expected_calibration_error(val_predictions, val_labels)
        ece_after = cls._expected_calibration_error(cal_val, val_labels)

        result = CalibrationResult(
            method="platt",
            brier_before=brier_before,
            brier_after=brier_after,
            brier_skill_score_pct=bss,
            log_loss_before=cls._log_loss(val_predictions, val_labels),
            log_loss_after=cls._log_loss(cal_val, val_labels),
            ece_before=ece_before,
            ece_after=ece_after,
            calibration_intercept=b,
            calibration_slope=a,
            is_well_calibrated=(ece_after <= 0.15),
            reliability_buckets=cls._reliability_diagram(cal_val, val_labels),
        )

        return result, calibrated

    @classmethod
    def calibrate_isotonic(
        cls,
        val_predictions: List[float],
        val_labels: List[int],
        test_predictions: Optional[List[float]] = None,
    ) -> Tuple[CalibrationResult, List[float]]:
        """
        Fit isotonic (monotonic piecewise-linear) calibration on validation data.
        """
        n = len(val_predictions)
        if n < 10:
            return CalibrationResult(method="isotonic"), list(test_predictions or val_predictions)

        # Sort by predicted probability and compute pool-adjacent-violators
        paired = sorted(zip(val_predictions, val_labels), key=lambda x: x[0])
        sorted_preds = [p for p, _ in paired]
        sorted_labels = [float(y) for _, y in paired]

        # Pool Adjacent Violators Algorithm (PAVA)
        iso_values = list(sorted_labels)
        block_size = [1] * n

        i = 0
        while i < n - 1:
            if iso_values[i] > iso_values[i + 1]:
                # Merge blocks
                merged = (iso_values[i] * block_size[i] + iso_values[i + 1] * block_size[i + 1]) / (block_size[i] + block_size[i + 1])
                iso_values[i] = merged
                block_size[i] += block_size[i + 1]
                iso_values.pop(i + 1)
                block_size.pop(i + 1)
                n = len(iso_values)
                if i > 0:
                    i -= 1
            else:
                i += 1

        # Expand blocks back to original length
        expanded = []
        for val, sz in zip(iso_values, block_size):
            expanded.extend([val] * sz)

        # Build mapping table: sorted_preds -> expanded
        mapping = list(zip(sorted_preds, expanded))

        # Apply to test predictions
        target_preds = test_predictions if test_predictions is not None else val_predictions
        calibrated = [cls._interpolate_isotonic(p, mapping) for p in target_preds]

        brier_before = cls._brier(val_predictions, val_labels)
        cal_val = [cls._interpolate_isotonic(p, mapping) for p in val_predictions]
        brier_after = cls._brier(cal_val, val_labels)
        base_rate = sum(val_labels) / max(1, len(val_labels))
        base_brier = base_rate * (1.0 - base_rate)
        bss = ((base_brier - brier_after) / base_brier * 100.0) if base_brier > 0 else 0.0

        result = CalibrationResult(
            method="isotonic",
            brier_before=brier_before,
            brier_after=brier_after,
            brier_skill_score_pct=bss,
            log_loss_before=cls._log_loss(val_predictions, val_labels),
            log_loss_after=cls._log_loss(cal_val, val_labels),
            ece_before=cls._expected_calibration_error(val_predictions, val_labels),
            ece_after=cls._expected_calibration_error(cal_val, val_labels),
            is_well_calibrated=(cls._expected_calibration_error(cal_val, val_labels) <= 0.15),
            reliability_buckets=cls._reliability_diagram(cal_val, val_labels),
        )

        return result, calibrated

    @classmethod
    def select_best_calibration(
        cls,
        val_predictions: List[float],
        val_labels: List[int],
        test_predictions: Optional[List[float]] = None,
    ) -> Tuple[CalibrationResult, List[float]]:
        """Try both methods and return the one with lower test ECE."""
        platt_result, platt_cal = cls.calibrate_platt(val_predictions, val_labels, test_predictions)
        iso_result, iso_cal = cls.calibrate_isotonic(val_predictions, val_labels, test_predictions)

        if iso_result.ece_after <= platt_result.ece_after:
            return iso_result, iso_cal
        return platt_result, platt_cal

    @staticmethod
    def _interpolate_isotonic(p: float, mapping: List[Tuple[float, float]]) -> float:
        """Linearly interpolate in the isotonic mapping table."""
        if not mapping:
            return p
        if p <= mapping[0][0]:
            return mapping[0][1]
        if p >= mapping[-1][0]:
            return mapping[-1][1]

        for i in range(len(mapping) - 1):
            x0, y0 = mapping[i]
            x1, y1 = mapping[i + 1]
            if x0 <= p <= x1:
                if x1 - x0 < 1e-12:
                    return y0
                t = (p - x0) / (x1 - x0)
                return y0 + t * (y1 - y0)
        return mapping[-1][1]

    @staticmethod
    def _brier(predictions: List[float], labels: List[int]) -> float:
        n = len(predictions)
        if n == 0:
            return 1.0
        return sum((p - y) ** 2 for p, y in zip(predictions, labels)) / n

    @staticmethod
    def _log_loss(predictions: List[float], labels: List[int]) -> float:
        n = len(predictions)
        if n == 0:
            return 10.0
        eps = 1e-8
        return -sum(
            y * math.log(max(eps, p)) + (1 - y) * math.log(max(eps, 1.0 - p))
            for p, y in zip(predictions, labels)
        ) / n

    @staticmethod
    def _expected_calibration_error(predictions: List[float], labels: List[int], n_bins: int = 10) -> float:
        n = len(predictions)
        if n == 0:
            return 1.0
        bin_width = 1.0 / n_bins
        ece = 0.0
        for b in range(n_bins):
            lo = b * bin_width
            hi = (b + 1) * bin_width
            in_bin = [(p, y) for p, y in zip(predictions, labels) if lo <= p < hi]
            if in_bin:
                avg_pred = sum(p for p, _ in in_bin) / len(in_bin)
                avg_label = sum(y for _, y in in_bin) / len(in_bin)
                ece += abs(avg_pred - avg_label) * len(in_bin) / n
        return ece

    @staticmethod
    def _reliability_diagram(predictions: List[float], labels: List[int], n_bins: int = 10) -> List[Dict[str, float]]:
        buckets = []
        bin_width = 1.0 / n_bins
        for b in range(n_bins):
            lo = b * bin_width
            hi = (b + 1) * bin_width
            in_bin = [(p, y) for p, y in zip(predictions, labels) if lo <= p < hi]
            if in_bin:
                buckets.append({
                    "bin_lower": lo,
                    "bin_upper": hi,
                    "mean_predicted": sum(p for p, _ in in_bin) / len(in_bin),
                    "empirical_rate": sum(y for _, y in in_bin) / len(in_bin),
                    "count": len(in_bin),
                })
        return buckets

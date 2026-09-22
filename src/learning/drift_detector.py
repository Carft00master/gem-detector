"""
Learning Drift Detector and Operational Health Engine
Monitors 7 operational and statistical drift dimensions (training data, features,
labels, market regimes, venue distribution, predicted probabilities, execution slippage)
and triggers automated model rollbacks or retraining workflows when thresholds are breached.
"""

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
import logging
import math
from typing import Any, Dict, List, Optional, Tuple, Union
import uuid

from src.learning.model_registry import ModelRollbackEvent

logger = logging.getLogger(__name__)

# Valid dimension string enumerations
VALID_DIMENSIONS = [
    "training_data",
    "feature",
    "label",
    "market_regime",
    "venue_distribution",
    "probability",
    "execution",
]

# Valid status string enumerations
VALID_STATUSES = [
    "NORMAL",
    "WARNING",
    "RETRAIN_RECOMMENDED",
    "MODEL_REVIEW_REQUIRED",
]

STATUS_SEVERITY_ORDER = {
    "NORMAL": 0,
    "WARNING": 1,
    "RETRAIN_RECOMMENDED": 2,
    "MODEL_REVIEW_REQUIRED": 3,
}


@dataclass
class DriftDimension:
    """
    Status and magnitude assessment for an individual monitored drift dimension.
    
    Attributes:
        dimension: Name of the drift dimension ('training_data' | 'feature' | 'label' |
                   'market_regime' | 'venue_distribution' | 'probability' | 'execution').
        status: Current health status ('NORMAL' | 'WARNING' | 'RETRAIN_RECOMMENDED' | 'MODEL_REVIEW_REQUIRED').
        current_value: Observed metric value in current evaluation window.
        baseline_value: Reference metric value from baseline champion training/validation period.
        drift_magnitude: Normalized relative or absolute drift magnitude.
        threshold: The active threshold level applied (warning or alarm).
        is_alarming: Whether the drift magnitude breached the critical alarm threshold.
    """
    dimension: str
    status: str
    current_value: float
    baseline_value: float
    drift_magnitude: float
    threshold: float
    is_alarming: bool = False

    def __post_init__(self) -> None:
        """Validate and normalize status and dimension."""
        if self.dimension not in VALID_DIMENSIONS:
            logger.debug("Drift dimension '%s' is not in standard dimensions list.", self.dimension)
        if self.status:
            self.status = self.status.upper()
            if self.status not in VALID_STATUSES:
                logger.warning("Unrecognized drift status '%s'. Normalizing to 'NORMAL'.", self.status)
                self.status = "NORMAL"

    def to_dict(self) -> Dict[str, Any]:
        """Convert dimension to dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DriftDimension":
        """Reconstruct DriftDimension from dictionary."""
        d = dict(data)
        d["current_value"] = float(d.get("current_value", 0.0))
        d["baseline_value"] = float(d.get("baseline_value", 0.0))
        d["drift_magnitude"] = float(d.get("drift_magnitude", 0.0))
        d["threshold"] = float(d.get("threshold", 0.0))
        d["is_alarming"] = bool(d.get("is_alarming", False))
        return cls(**d)


@dataclass
class LearningHealthReport:
    """
    Holistic operational health report aggregating all 7 monitored drift dimensions.
    
    Attributes:
        overall_status: Worst status across all 7 monitored dimensions.
        dimensions: List of individual DriftDimension evaluations.
        should_trigger_rollback: True if safety/execution dimensions require immediate model rollback.
        rollback_reason: Detailed failure reason if rollback is triggered.
        timestamp: ISO 8601 UTC timestamp of report generation.
        recommendations: Actionable remediation steps based on observed drift patterns.
    """
    overall_status: str  # 'NORMAL' | 'WARNING' | 'RETRAIN_RECOMMENDED' | 'MODEL_REVIEW_REQUIRED'
    dimensions: List[DriftDimension]
    should_trigger_rollback: bool = False
    rollback_reason: Optional[str] = None
    timestamp: str = ""
    recommendations: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        """Validate and ensure timestamp and normalized status."""
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()
        if self.overall_status:
            self.overall_status = self.overall_status.upper()
            if self.overall_status not in VALID_STATUSES:
                self.overall_status = "NORMAL"

    def get_dimension(self, dimension_name: str) -> Optional[DriftDimension]:
        """Retrieve a specific dimension evaluation by name."""
        for dim in self.dimensions:
            if dim.dimension == dimension_name:
                return dim
        return None

    def to_dict(self) -> Dict[str, Any]:
        """Convert health report to a JSON-serializable dictionary."""
        return {
            "overall_status": self.overall_status,
            "dimensions": [d.to_dict() for d in self.dimensions],
            "should_trigger_rollback": self.should_trigger_rollback,
            "rollback_reason": self.rollback_reason,
            "timestamp": self.timestamp,
            "recommendations": list(self.recommendations),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "LearningHealthReport":
        """Reconstruct LearningHealthReport from dictionary."""
        d = dict(data)
        dims_data = d.get("dimensions") or []
        parsed_dims: List[DriftDimension] = []
        for dim_item in dims_data:
            if isinstance(dim_item, dict):
                parsed_dims.append(DriftDimension.from_dict(dim_item))
            elif isinstance(dim_item, DriftDimension):
                parsed_dims.append(dim_item)
        d["dimensions"] = parsed_dims
        recs = d.get("recommendations") or []
        if isinstance(recs, str):
            try:
                recs = json.loads(recs)
            except Exception:
                recs = [recs]
        d["recommendations"] = list(recs)
        return cls(**d)


class LearningDriftDetector:
    """
    Monitors seven operational and statistical drift dimensions:
    1. training_data: Fraction of input features exhibiting significant distribution drift.
    2. feature: Normalized aggregate feature value shifts across input features.
    3. label: Shift in base positive winner / rug rate outcomes.
    4. market_regime: Divergence in active market regime distributions.
    5. venue_distribution: Shift in DEX execution volume shares (Raydium, Meteora, Orca, Pump.fun).
    6. probability: Predicted probability distribution and mean shift.
    7. execution: Degradation in execution slippage and realized fill pricing.
    """

    # Default warning and alarm levels per dimension
    DRIFT_THRESHOLDS: Dict[str, Dict[str, float]] = {
        "training_data": {"warning": 0.10, "alarm": 0.25},
        "feature": {"warning": 0.15, "alarm": 0.30},
        "label": {"warning": 0.05, "alarm": 0.15},
        "market_regime": {"warning": 0.20, "alarm": 0.40},
        "venue_distribution": {"warning": 0.15, "alarm": 0.30},
        "probability": {"warning": 0.03, "alarm": 0.08},
        "execution": {"warning": 0.10, "alarm": 0.25},
    }

    # Dimension aliases for flexible statistics dictionary key lookups
    DIMENSION_ALIASES: Dict[str, List[str]] = {
        "training_data": [
            "training_data",
            "training_data_drift",
            "training_drift",
            "features_drifted_fraction",
            "feature_drift_ratio",
        ],
        "feature": [
            "feature",
            "feature_drift",
            "feature_drift_magnitude",
            "mean_feature_drift",
            "features",
        ],
        "label": [
            "label",
            "label_drift",
            "label_base_rate",
            "base_rate_shift",
            "target_rate",
            "winner_rate",
        ],
        "market_regime": [
            "market_regime",
            "regime_drift",
            "market_regime_shift",
            "regime_jsd",
            "regime_distribution",
        ],
        "venue_distribution": [
            "venue_distribution",
            "venue_drift",
            "venue_distribution_shift",
            "venue_jsd",
            "venues",
        ],
        "probability": [
            "probability",
            "probability_drift",
            "prediction_drift",
            "mean_prediction_shift",
            "pred_mean",
            "mean_probability",
        ],
        "execution": [
            "execution",
            "execution_drift",
            "slippage_increase",
            "slippage_bps",
            "execution_slippage",
            "slippage",
        ],
    }

    def __init__(self, thresholds: Optional[Dict[str, Dict[str, float]]] = None) -> None:
        """
        Initialize the drift detector with custom or default thresholds.

        Args:
            thresholds: Optional custom dictionary mapping dimensions to {"warning": float, "alarm": float}.
        """
        self.thresholds: Dict[str, Dict[str, float]] = {}
        for dim, default_vals in self.DRIFT_THRESHOLDS.items():
            self.thresholds[dim] = {
                "warning": default_vals["warning"],
                "alarm": default_vals["alarm"],
            }

        if thresholds is not None:
            for dim, vals in thresholds.items():
                if dim in self.thresholds:
                    if "warning" in vals:
                        self.thresholds[dim]["warning"] = float(vals["warning"])
                    if "alarm" in vals:
                        self.thresholds[dim]["alarm"] = float(vals["alarm"])

        logger.info("LearningDriftDetector initialized across 7 drift dimensions.")

    def _extract_stat_value(
        self,
        stats: Dict[str, float],
        dim_name: str,
        default: float = 0.0,
    ) -> float:
        """
        Extract float value from stats dictionary using canonical name or aliases.

        Args:
            stats: Dictionary of observed statistics.
            dim_name: Canonical dimension identifier.
            default: Default value if not found.

        Returns:
            Extracted float value.
        """
        if not isinstance(stats, dict):
            return default

        # Direct canonical check
        if dim_name in stats and stats[dim_name] is not None:
            try:
                return float(stats[dim_name])
            except (ValueError, TypeError):
                pass

        # Check aliases
        aliases = self.DIMENSION_ALIASES.get(dim_name, [])
        for alias in aliases:
            if alias in stats and stats[alias] is not None:
                try:
                    return float(stats[alias])
                except (ValueError, TypeError):
                    pass

        return default

    def calculate_drift_magnitude(self, current: float, baseline: float) -> float:
        """
        Calculate normalized relative drift magnitude: abs(current - baseline) / max(abs(baseline), 1e-6).
        If baseline is zero, returns absolute current value to prevent division by zero.

        Args:
            current: Current observed metric value.
            baseline: Baseline reference metric value.

        Returns:
            Computed drift magnitude.
        """
        if abs(baseline) < 1e-6:
            return abs(current)
        return abs(current - baseline) / max(abs(baseline), 1e-6)

    def detect_drift(
        self,
        baseline_stats: Dict[str, float],
        current_stats: Dict[str, float],
    ) -> LearningHealthReport:
        """
        Compare baseline stats against current stats across all 7 monitored drift dimensions.

        Classification Rules:
        - drift_magnitude = abs(current - baseline) / max(abs(baseline), 1e-6)
        - If magnitude > alarm: status = 'MODEL_REVIEW_REQUIRED', is_alarming = True.
        - If magnitude > warning: status = 'RETRAIN_RECOMMENDED' for data/regime dimensions,
          or 'WARNING' for operational dimensions.
        - Otherwise status = 'NORMAL'.
        - If probability or execution is MODEL_REVIEW_REQUIRED: should_trigger_rollback = True.
        - overall_status = worst status across all evaluated dimensions.

        Args:
            baseline_stats: Reference statistics dictionary from training or validation period.
            current_stats: Live production statistics dictionary from recent sliding window.

        Returns:
            LearningHealthReport detailing health, alarms, rollback triggers, and recommendations.
        """
        dimensions: List[DriftDimension] = []
        recommendations: List[str] = []
        rollback_triggers: List[DriftDimension] = []

        for dim_name in VALID_DIMENSIONS:
            baseline_val = self._extract_stat_value(baseline_stats, dim_name, default=0.0)
            current_val = self._extract_stat_value(current_stats, dim_name, default=0.0)

            # If current_stats passes a pre-computed drift magnitude directly and baseline is 0
            drift_mag = self.calculate_drift_magnitude(current_val, baseline_val)

            warning_thresh = self.thresholds[dim_name]["warning"]
            alarm_thresh = self.thresholds[dim_name]["alarm"]

            if drift_mag > alarm_thresh:
                status = "MODEL_REVIEW_REQUIRED"
                is_alarming = True
                applied_threshold = alarm_thresh
            elif drift_mag > warning_thresh:
                if dim_name in ("training_data", "feature", "label", "market_regime", "venue_distribution"):
                    status = "RETRAIN_RECOMMENDED"
                else:
                    status = "WARNING"
                is_alarming = False
                applied_threshold = warning_thresh
            else:
                status = "NORMAL"
                is_alarming = False
                applied_threshold = warning_thresh

            dim_obj = DriftDimension(
                dimension=dim_name,
                status=status,
                current_value=current_val,
                baseline_value=baseline_val,
                drift_magnitude=drift_mag,
                threshold=applied_threshold,
                is_alarming=is_alarming,
            )
            dimensions.append(dim_obj)

            # Check rollback requirement for safety-critical dimensions
            if status == "MODEL_REVIEW_REQUIRED" and dim_name in ("probability", "execution"):
                rollback_triggers.append(dim_obj)

            # Generate dimension-specific recommendations
            if status in ("WARNING", "RETRAIN_RECOMMENDED", "MODEL_REVIEW_REQUIRED"):
                rec = self._generate_recommendation(dim_obj)
                if rec:
                    recommendations.append(rec)

        # Rollback evaluation
        should_trigger_rollback = len(rollback_triggers) > 0
        rollback_reason: Optional[str] = None
        if should_trigger_rollback:
            reasons = [
                f"{d.dimension} drift magnitude ({d.drift_magnitude:.4f}) breached alarm threshold ({d.threshold:.4f})"
                for d in rollback_triggers
            ]
            rollback_reason = f"Safety-critical model rollback triggered: {'; '.join(reasons)}."
            recommendations.insert(
                0,
                f"CRITICAL: Immediate champion model rollback required. {rollback_reason}",
            )
            logger.warning("Automated rollback condition met: %s", rollback_reason)

        # Determine overall status (worst status across all dimensions)
        worst_severity = max(STATUS_SEVERITY_ORDER.get(d.status, 0) for d in dimensions)
        severity_to_status = {v: k for k, v in STATUS_SEVERITY_ORDER.items()}
        overall_status = severity_to_status.get(worst_severity, "NORMAL")

        logger.info(
            "LearningDriftDetector evaluated 7 dimensions: overall_status=%s, rollback_needed=%s",
            overall_status,
            should_trigger_rollback,
        )

        return LearningHealthReport(
            overall_status=overall_status,
            dimensions=dimensions,
            should_trigger_rollback=should_trigger_rollback,
            rollback_reason=rollback_reason,
            timestamp=datetime.now(timezone.utc).isoformat(),
            recommendations=recommendations,
        )

    def _generate_recommendation(self, dim: DriftDimension) -> str:
        """Generate targeted remediation recommendation for a drifted dimension."""
        dim_name = dim.dimension
        status = dim.status
        mag_pct = dim.drift_magnitude * 100.0

        if dim_name == "training_data":
            return (
                f"Training Data [{status}]: {mag_pct:.1f}% feature drift detected. "
                "Verify upstream ingestion pipelines and update data cleaning filters."
            )
        elif dim_name == "feature":
            return (
                f"Feature Distribution [{status}]: {mag_pct:.1f}% aggregate feature shift. "
                "Recalibrate feature normalization scalers and inspect raw token telemetry."
            )
        elif dim_name == "label":
            return (
                f"Label Base Rate [{status}]: {mag_pct:.1f}% shift in base winner/rug rate. "
                "Adjust class reweighting factors and verify multi-horizon outcome definitions."
            )
        elif dim_name == "market_regime":
            return (
                f"Market Regime [{status}]: {mag_pct:.1f}% shift in regime frequency. "
                "Update regime classification transition matrix and retrain regime-conditioned submodels."
            )
        elif dim_name == "venue_distribution":
            return (
                f"Venue Distribution [{status}]: {mag_pct:.1f}% shift in DEX volume distribution. "
                "Rebalance venue-specific training weights across Raydium, Meteora, and Pump.fun."
            )
        elif dim_name == "probability":
            return (
                f"Prediction Probability [{status}]: {mag_pct:.1f}% mean prediction shift. "
                "Execute Platt scaling / Isotonic probability recalibration on recent sliding window."
            )
        elif dim_name == "execution":
            return (
                f"Execution Slippage [{status}]: {mag_pct:.1f}% slippage degradation. "
                "Review dynamic priority fee multipliers and route optimization parameters."
            )
        return f"Dimension {dim_name} exhibited {status} with magnitude {mag_pct:.1f}%."

    def check_rollback_needed(self, health: LearningHealthReport) -> bool:
        """
        Check if a health report necessitates initiating an automated model rollback.

        Args:
            health: The evaluated LearningHealthReport.

        Returns:
            True if automated rollback is required, False otherwise.
        """
        return bool(health.should_trigger_rollback)

    def generate_rollback_event(
        self,
        health: LearningHealthReport,
        failed_model_id: str,
        champion_id: str,
    ) -> ModelRollbackEvent:
        """
        Generate an auditable ModelRollbackEvent populated with failure context and metric snapshots.

        Args:
            health: The LearningHealthReport triggering the rollback.
            failed_model_id: Identifier of the failing active model.
            champion_id: Identifier of the fallback verified champion.

        Returns:
            ModelRollbackEvent ready for model registry persistence.
        """
        metrics_at_failure: Dict[str, float] = {}
        for dim in health.dimensions:
            metrics_at_failure[f"{dim.dimension}_current"] = dim.current_value
            metrics_at_failure[f"{dim.dimension}_baseline"] = dim.baseline_value
            metrics_at_failure[f"{dim.dimension}_drift_magnitude"] = dim.drift_magnitude

        reason = (
            health.rollback_reason
            if health.rollback_reason
            else "Automated rollback triggered by LearningDriftDetector."
        )

        event = ModelRollbackEvent(
            event_id=str(uuid.uuid4()),
            old_champion_id=champion_id,
            failed_model_id=failed_model_id,
            rollback_reason=reason,
            metrics_at_failure=metrics_at_failure,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

        logger.warning(
            "Created ModelRollbackEvent %s for failed model %s -> fallback champion %s",
            event.event_id,
            failed_model_id,
            champion_id,
        )

        return event

    def format_report_summary(self, health: LearningHealthReport) -> str:
        """
        Format the LearningHealthReport as a clean text summary.

        Args:
            health: Evaluated LearningHealthReport.

        Returns:
            Human-readable formatted string.
        """
        lines = [
            f"=== Learning Health Report [{health.timestamp}] ===",
            f"Overall Status: {health.overall_status}",
            f"Rollback Triggered: {health.should_trigger_rollback}",
        ]
        if health.rollback_reason:
            lines.append(f"Rollback Reason: {health.rollback_reason}")

        lines.append("\n--- Drift Dimensions ---")
        for d in health.dimensions:
            alarm_flag = " [ALARM]" if d.is_alarming else ""
            lines.append(
                f"  {d.dimension:20s}: {d.status:22s} | Curr: {d.current_value:.4f} | Base: {d.baseline_value:.4f} | "
                f"Drift: {d.drift_magnitude * 100.0:6.2f}% (Thresh: {d.threshold * 100.0:5.2f}%){alarm_flag}"
            )

        if health.recommendations:
            lines.append("\n--- Recommendations ---")
            for rec in health.recommendations:
                lines.append(f"  * {rec}")

        return "\n".join(lines)

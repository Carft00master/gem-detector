"""
Promotion Policy and Automated Deployment Gate
Evaluates challenger models against active champions using configurable minimum improvement
margins, chronological walk-forward validation folds, and regime/venue consistency checks.
"""

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
import logging
import math
from typing import Any, Dict, List, Optional, Tuple, Union
import uuid

logger = logging.getLogger(__name__)

# Attempt to import ComparisonScorecard from champion_challenger module, with robust fallback
try:
    from src.learning.champion_challenger import ComparisonScorecard
except ImportError:
    @dataclass
    class ComparisonScorecard:
        """
        Scorecard comparing challenger model performance against active champion.
        Serves as data container when standalone or before champion_challenger module is loaded.
        """
        challenger_id: str = ""
        champion_id: str = ""
        sample_size: int = 0
        challenger_pr_auc: float = 0.0
        champion_pr_auc: float = 0.0
        pr_auc_improvement_pct: float = 0.0
        challenger_precision_at_10: float = 0.0
        champion_precision_at_10: float = 0.0
        precision_at_10_improvement_pct: float = 0.0
        challenger_brier_score: float = 0.0
        champion_brier_score: float = 0.0
        brier_degradation_pct: float = 0.0
        challenger_rug_rate: float = 0.0
        champion_rug_rate: float = 0.0
        rug_rate_increase_abs: float = 0.0
        challenger_execution_return: float = 0.0
        champion_execution_return: float = 0.0
        execution_return_degradation_pct: float = 0.0
        metric_diffs: Dict[str, float] = field(default_factory=dict)
        is_statistically_significant: bool = False
        recommendation: str = ""
        created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

        def to_dict(self) -> Dict[str, Any]:
            """Convert scorecard to dictionary."""
            return asdict(self)


# Valid decision string enumerations
VALID_DECISIONS = {
    "PROMOTE",
    "NOT_READY",
    "INSUFFICIENT_DATA",
    "BLOCKED_BY_REGIME",
    "BLOCKED_BY_METRIC",
}


@dataclass
class PromotionThresholds:
    """
    Configurable minimum improvement margins and safety constraints required for model promotion.
    
    Attributes:
        min_pr_auc_improvement_pct: Minimum required PR-AUC improvement over champion (%).
        min_precision_at_10_improvement_pct: Minimum required Precision@10 improvement over champion (%).
        max_brier_degradation_pct: Maximum acceptable Brier score degradation over champion (%).
        max_rug_rate_increase_abs: Maximum acceptable rug rate increase in absolute percentage points.
        max_execution_return_degradation_pct: Maximum acceptable execution return degradation (%).
        min_walk_forward_periods_passed: Minimum number of walk-forward validation folds passed.
        require_all_regimes_improved: If True, candidate must not degrade in any market regime.
        require_all_venues_improved: If True, candidate must not degrade across any trading venue.
        min_sample_size: Minimum test sample count required to validate promotion.
    """
    min_pr_auc_improvement_pct: float = 5.0
    min_precision_at_10_improvement_pct: float = 10.0
    max_brier_degradation_pct: float = 5.0
    max_rug_rate_increase_abs: float = 2.0
    max_execution_return_degradation_pct: float = 5.0
    min_walk_forward_periods_passed: int = 2
    require_all_regimes_improved: bool = True
    require_all_venues_improved: bool = True
    min_sample_size: int = 250

    def to_dict(self) -> Dict[str, Any]:
        """Convert thresholds configuration to dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PromotionThresholds":
        """Reconstruct PromotionThresholds from dictionary."""
        valid_keys = {
            "min_pr_auc_improvement_pct",
            "min_precision_at_10_improvement_pct",
            "max_brier_degradation_pct",
            "max_rug_rate_increase_abs",
            "max_execution_return_degradation_pct",
            "min_walk_forward_periods_passed",
            "require_all_regimes_improved",
            "require_all_venues_improved",
            "min_sample_size",
        }
        filtered = {k: v for k, v in data.items() if k in valid_keys}
        return cls(**filtered)


@dataclass
class PromotionDecision:
    """
    Structured promotion evaluation decision with comprehensive metric breakdown.
    
    Attributes:
        decision: Final promotion verdict ('PROMOTE' | 'NOT_READY' | 'INSUFFICIENT_DATA' | 'BLOCKED_BY_REGIME' | 'BLOCKED_BY_METRIC').
        challenger_id: Unique identifier of the candidate model evaluated.
        champion_id: Unique identifier of the baseline champion model.
        passing_metrics: List of metrics that satisfied the promotion threshold conditions.
        failing_metrics: List of metrics that violated the promotion threshold conditions.
        walk_forward_periods_passed: Number of chronological walk-forward periods passed.
        regime_results: Dictionary mapping market regimes to pass/fail boolean status.
        venue_results: Dictionary mapping execution venues to pass/fail boolean status.
        requires_operator_approval: Whether operator manual approval is required before promotion.
        decision_reason: Human-readable narrative detailing the decision rationale.
        timestamp: ISO 8601 UTC timestamp of the evaluation.
    """
    decision: str  # 'PROMOTE' | 'NOT_READY' | 'INSUFFICIENT_DATA' | 'BLOCKED_BY_REGIME' | 'BLOCKED_BY_METRIC'
    challenger_id: str = ""
    champion_id: str = ""
    passing_metrics: List[str] = field(default_factory=list)
    failing_metrics: List[str] = field(default_factory=list)
    walk_forward_periods_passed: int = 0
    regime_results: Dict[str, bool] = field(default_factory=dict)
    venue_results: Dict[str, bool] = field(default_factory=dict)
    requires_operator_approval: bool = True
    decision_reason: str = ""
    timestamp: str = ""

    def __post_init__(self) -> None:
        """Validate and normalize decision fields."""
        if self.decision:
            self.decision = self.decision.upper()
            if self.decision not in VALID_DECISIONS:
                logger.warning(
                    "Unrecognized promotion decision '%s'. Normalizing to 'NOT_READY'.",
                    self.decision,
                )
                self.decision = "NOT_READY"
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()

    @property
    def is_promoted(self) -> bool:
        """Return True if the challenger model is approved for promotion."""
        return self.decision == "PROMOTE"

    @property
    def is_blocked(self) -> bool:
        """Return True if promotion was explicitly blocked by safety or metric gates."""
        return self.decision in ("BLOCKED_BY_REGIME", "BLOCKED_BY_METRIC", "INSUFFICIENT_DATA")

    def to_dict(self) -> Dict[str, Any]:
        """Convert decision to a JSON-serializable dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PromotionDecision":
        """Reconstruct PromotionDecision from dictionary."""
        d = dict(data)
        for key in ("passing_metrics", "failing_metrics"):
            val = d.get(key)
            if isinstance(val, str):
                try:
                    d[key] = json.loads(val)
                except Exception:
                    d[key] = []
            elif val is None:
                d[key] = []

        for key in ("regime_results", "venue_results"):
            val = d.get(key)
            if isinstance(val, str):
                try:
                    d[key] = json.loads(val)
                except Exception:
                    d[key] = {}
            elif val is None:
                d[key] = {}

        return cls(**d)


class PromotionPolicy:
    """
    Evaluation engine that enforces statistical, safety, and operational gates
    before promoting a candidate challenger model to active production champion.
    """

    def __init__(self, thresholds: Optional[PromotionThresholds] = None) -> None:
        """
        Initialize the PromotionPolicy with configurable thresholds.

        Args:
            thresholds: Optional custom PromotionThresholds. If None, defaults are used.
        """
        self.thresholds = thresholds if thresholds is not None else PromotionThresholds()
        logger.info(
            "PromotionPolicy initialized with min_pr_auc_imp=%.2f%%, min_p10_imp=%.2f%%, min_wf_periods=%d",
            self.thresholds.min_pr_auc_improvement_pct,
            self.thresholds.min_precision_at_10_improvement_pct,
            self.thresholds.min_walk_forward_periods_passed,
        )

    def _find_metric_in_scorecard_list(self, scorecard: Any, metric_names: List[str]) -> Optional[Any]:
        """Look for a metric object in scorecard.metrics list by matching metric names."""
        metrics_list = None
        if isinstance(scorecard, dict):
            metrics_list = scorecard.get("metrics")
        elif hasattr(scorecard, "metrics"):
            metrics_list = getattr(scorecard, "metrics")

        if isinstance(metrics_list, list):
            for item in metrics_list:
                name = ""
                if isinstance(item, dict):
                    name = str(item.get("metric_name", ""))
                elif hasattr(item, "metric_name"):
                    name = str(getattr(item, "metric_name", ""))
                
                clean_name = name.lower().replace("-", "_").replace("@", "_").replace(" ", "_")
                for target in metric_names:
                    clean_target = target.lower().replace("-", "_").replace("@", "_").replace(" ", "_")
                    if clean_name == clean_target or clean_target in clean_name:
                        return item
        return None

    def _extract_metric_value(
        self,
        scorecard: Any,
        attr_names: List[str],
        default: float = 0.0,
    ) -> float:
        """
        Safely extract a float metric value from a scorecard object or dictionary.

        Args:
            scorecard: ComparisonScorecard instance or dict.
            attr_names: Candidate attribute or key names to probe.
            default: Default value if not found.

        Returns:
            Extracted float value.
        """
        if isinstance(scorecard, dict):
            for name in attr_names:
                if name in scorecard and scorecard[name] is not None:
                    try:
                        return float(scorecard[name])
                    except (ValueError, TypeError):
                        pass
                # Check nested metric_diffs or metrics dict
                for subkey in ("metric_diffs", "metrics"):
                    subdict = scorecard.get(subkey)
                    if isinstance(subdict, dict) and name in subdict and subdict[name] is not None:
                        try:
                            return float(subdict[name])
                        except (ValueError, TypeError):
                            pass
        else:
            for name in attr_names:
                if hasattr(scorecard, name):
                    val = getattr(scorecard, name)
                    if val is not None:
                        try:
                            return float(val)
                        except (ValueError, TypeError):
                            pass
                # Check nested metric_diffs on object
                for subkey in ("metric_diffs", "metrics"):
                    if hasattr(scorecard, subkey):
                        subdict = getattr(scorecard, subkey)
                        if isinstance(subdict, dict) and name in subdict and subdict[name] is not None:
                            try:
                                return float(subdict[name])
                            except (ValueError, TypeError):
                                pass
        return default

    def _extract_string_value(
        self,
        scorecard: Any,
        attr_names: List[str],
        default: str = "",
    ) -> str:
        """Safely extract a string field from scorecard object or dict."""
        if isinstance(scorecard, dict):
            for name in attr_names:
                if name in scorecard and scorecard[name] is not None:
                    return str(scorecard[name])
        else:
            for name in attr_names:
                if hasattr(scorecard, name):
                    val = getattr(scorecard, name)
                    if val is not None:
                        return str(val)
        return default

    def _compute_pr_auc_improvement(self, scorecard: Any) -> float:
        """Compute or extract PR-AUC percentage improvement."""
        # 1. Probe scorecard.metrics list
        metric_item = self._find_metric_in_scorecard_list(scorecard, ["pr_auc", "pr_auc_score", "prauc"])
        if metric_item is not None:
            if isinstance(metric_item, dict) and "improvement_pct" in metric_item:
                return float(metric_item["improvement_pct"])
            elif hasattr(metric_item, "improvement_pct"):
                return float(getattr(metric_item, "improvement_pct"))

        # 2. Probe direct improvement fields
        direct = self._extract_metric_value(
            scorecard,
            ["pr_auc_improvement_pct", "pr_auc_diff_pct", "pr_auc_improvement"],
            default=float("nan"),
        )
        if not math.isnan(direct):
            return direct

        # 3. Calculate from challenger and champion absolute scores
        challenger_val = self._extract_metric_value(scorecard, ["challenger_pr_auc", "challenger_pr_auc_score"])
        champion_val = self._extract_metric_value(scorecard, ["champion_pr_auc", "champion_pr_auc_score"])

        if champion_val > 1e-6:
            return ((challenger_val - champion_val) / champion_val) * 100.0
        elif challenger_val > 1e-6:
            return 100.0
        return 0.0

    def _compute_precision_at_10_improvement(self, scorecard: Any) -> float:
        """Compute or extract Precision@10 percentage improvement."""
        # 1. Probe scorecard.metrics list
        metric_item = self._find_metric_in_scorecard_list(scorecard, ["precision_at_10", "p10", "precision_10"])
        if metric_item is not None:
            if isinstance(metric_item, dict) and "improvement_pct" in metric_item:
                return float(metric_item["improvement_pct"])
            elif hasattr(metric_item, "improvement_pct"):
                return float(getattr(metric_item, "improvement_pct"))

        # 2. Probe direct improvement fields
        direct = self._extract_metric_value(
            scorecard,
            ["precision_at_10_improvement_pct", "precision_at_10_diff_pct", "precision_at_10_improvement"],
            default=float("nan"),
        )
        if not math.isnan(direct):
            return direct

        # 3. Calculate from challenger and champion absolute scores
        challenger_val = self._extract_metric_value(scorecard, ["challenger_precision_at_10", "challenger_p10"])
        champion_val = self._extract_metric_value(scorecard, ["champion_precision_at_10", "champion_p10"])

        if champion_val > 1e-6:
            return ((challenger_val - champion_val) / champion_val) * 100.0
        elif challenger_val > 1e-6:
            return 100.0
        return 0.0

    def _compute_brier_degradation(self, scorecard: Any) -> float:
        """Compute or extract Brier score degradation percentage (lower Brier is better)."""
        # 1. Probe scorecard.metrics list
        metric_item = self._find_metric_in_scorecard_list(scorecard, ["brier_score", "brier"])
        if metric_item is not None:
            champ_val = float(getattr(metric_item, "champion_value", metric_item.get("champion_value", 0.0) if isinstance(metric_item, dict) else 0.0))
            chall_val = float(getattr(metric_item, "challenger_value", metric_item.get("challenger_value", 0.0) if isinstance(metric_item, dict) else 0.0))
            if champ_val > 1e-6:
                return ((chall_val - champ_val) / champ_val) * 100.0

        # 2. Probe direct degradation fields
        direct = self._extract_metric_value(
            scorecard,
            ["brier_degradation_pct", "brier_score_degradation_pct", "brier_diff_pct"],
            default=float("nan"),
        )
        if not math.isnan(direct):
            return direct

        # 3. Calculate from challenger and champion absolute scores
        challenger_val = self._extract_metric_value(scorecard, ["challenger_brier_score", "challenger_brier"])
        champion_val = self._extract_metric_value(scorecard, ["champion_brier_score", "champion_brier"])

        if champion_val > 1e-6:
            return ((challenger_val - champion_val) / champion_val) * 100.0
        elif challenger_val > 1e-6:
            return 100.0
        return 0.0

    def _compute_rug_rate_increase_abs(self, scorecard: Any) -> float:
        """Compute or extract absolute rug rate increase in percentage points."""
        # 1. Probe scorecard.metrics list
        metric_item = self._find_metric_in_scorecard_list(scorecard, ["rug_rate", "rugs"])
        if metric_item is not None:
            champ_val = float(getattr(metric_item, "champion_value", metric_item.get("champion_value", 0.0) if isinstance(metric_item, dict) else 0.0))
            chall_val = float(getattr(metric_item, "challenger_value", metric_item.get("challenger_value", 0.0) if isinstance(metric_item, dict) else 0.0))
            if abs(chall_val) <= 1.0 and abs(champ_val) <= 1.0 and (chall_val > 0 or champ_val > 0):
                return (chall_val - champ_val) * 100.0
            return chall_val - champ_val

        # 2. Probe direct increase fields
        direct = self._extract_metric_value(
            scorecard,
            ["rug_rate_increase_abs", "rug_rate_diff_abs", "rug_rate_diff"],
            default=float("nan"),
        )
        if not math.isnan(direct):
            return direct

        # 3. Calculate from challenger and champion absolute scores
        challenger_val = self._extract_metric_value(scorecard, ["challenger_rug_rate", "challenger_rugs"])
        champion_val = self._extract_metric_value(scorecard, ["champion_rug_rate", "champion_rugs"])

        if abs(challenger_val) <= 1.0 and abs(champion_val) <= 1.0 and (challenger_val > 0 or champion_val > 0):
            return (challenger_val - champion_val) * 100.0
        return challenger_val - champion_val

    def _compute_execution_return_degradation(self, scorecard: Any) -> float:
        """Compute or extract execution return degradation percentage (higher return is better)."""
        # 1. Probe scorecard.metrics list
        metric_item = self._find_metric_in_scorecard_list(scorecard, ["execution_return", "execution", "return"])
        if metric_item is not None:
            champ_val = float(getattr(metric_item, "champion_value", metric_item.get("champion_value", 0.0) if isinstance(metric_item, dict) else 0.0))
            chall_val = float(getattr(metric_item, "challenger_value", metric_item.get("challenger_value", 0.0) if isinstance(metric_item, dict) else 0.0))
            if abs(champ_val) > 1e-6:
                return ((champ_val - chall_val) / abs(champ_val)) * 100.0
            elif chall_val < champ_val:
                return 100.0
            return 0.0

        # 2. Probe direct degradation fields
        direct = self._extract_metric_value(
            scorecard,
            ["execution_return_degradation_pct", "execution_return_diff_pct"],
            default=float("nan"),
        )
        if not math.isnan(direct):
            return direct

        # 3. Calculate from challenger and champion absolute scores
        challenger_val = self._extract_metric_value(scorecard, ["challenger_execution_return", "challenger_return"])
        champion_val = self._extract_metric_value(scorecard, ["champion_execution_return", "champion_return"])

        if abs(champion_val) > 1e-6:
            return ((champion_val - challenger_val) / abs(champion_val)) * 100.0
        elif challenger_val < champion_val:
            return 100.0
        return 0.0

    def evaluate(
        self,
        scorecard: Union[ComparisonScorecard, Dict[str, Any]],
        walk_forward_periods_passed: int = 0,
        regime_results: Optional[Dict[str, bool]] = None,
        venue_results: Optional[Dict[str, bool]] = None,
    ) -> PromotionDecision:
        """
        Evaluate candidate model scorecard against policy thresholds.

        Evaluation Rules:
        1. Return INSUFFICIENT_DATA if sample_size < min_sample_size (default 250).
        2. Return BLOCKED_BY_REGIME if any market regime or venue failed and consistency is required.
        3. Return BLOCKED_BY_METRIC if any statistical/operational metric threshold failed.
        4. Return PROMOTE only if ALL conditions pass.
        5. Otherwise return NOT_READY.

        Args:
            scorecard: ComparisonScorecard or dictionary containing side-by-side performance.
            walk_forward_periods_passed: Count of chronological folds where challenger beat champion.
            regime_results: Optional mapping of regime name to pass/fail boolean.
            venue_results: Optional mapping of venue name to pass/fail boolean.

        Returns:
            PromotionDecision containing verdict, passing/failing metric breakdown, and narrative rationale.
        """
        regime_map = dict(regime_results) if regime_results is not None else {}
        venue_map = dict(venue_results) if venue_results is not None else {}

        challenger_id = self._extract_string_value(
            scorecard, ["challenger_id", "candidate_id", "model_id"], default="unknown_challenger"
        )
        champion_id = self._extract_string_value(
            scorecard, ["champion_id", "baseline_id", "old_champion_id"], default="unknown_champion"
        )

        sample_size = int(
            self._extract_metric_value(
                scorecard,
                ["sample_size", "test_sample_size", "n_samples", "validation_sample_size"],
                default=0.0,
            )
        )

        passing_metrics: List[str] = []
        failing_metrics: List[str] = []

        # 1. PR-AUC Improvement Check
        pr_auc_imp = self._compute_pr_auc_improvement(scorecard)
        if pr_auc_imp >= self.thresholds.min_pr_auc_improvement_pct:
            passing_metrics.append(
                f"PR-AUC improvement: {pr_auc_imp:+.2f}% >= {self.thresholds.min_pr_auc_improvement_pct:.2f}%"
            )
        else:
            failing_metrics.append(
                f"PR-AUC improvement: {pr_auc_imp:+.2f}% < {self.thresholds.min_pr_auc_improvement_pct:.2f}%"
            )

        # 2. Precision@10 Improvement Check
        p10_imp = self._compute_precision_at_10_improvement(scorecard)
        if p10_imp >= self.thresholds.min_precision_at_10_improvement_pct:
            passing_metrics.append(
                f"Precision@10 improvement: {p10_imp:+.2f}% >= {self.thresholds.min_precision_at_10_improvement_pct:.2f}%"
            )
        else:
            failing_metrics.append(
                f"Precision@10 improvement: {p10_imp:+.2f}% < {self.thresholds.min_precision_at_10_improvement_pct:.2f}%"
            )

        # 3. Brier Score Degradation Check (lower is better, max degradation threshold)
        brier_deg = self._compute_brier_degradation(scorecard)
        if brier_deg <= self.thresholds.max_brier_degradation_pct:
            passing_metrics.append(
                f"Brier degradation: {brier_deg:+.2f}% <= {self.thresholds.max_brier_degradation_pct:.2f}%"
            )
        else:
            failing_metrics.append(
                f"Brier degradation: {brier_deg:+.2f}% > {self.thresholds.max_brier_degradation_pct:.2f}%"
            )

        # 4. Rug Rate Increase Check (absolute percentage points)
        rug_rate_inc = self._compute_rug_rate_increase_abs(scorecard)
        if rug_rate_inc <= self.thresholds.max_rug_rate_increase_abs:
            passing_metrics.append(
                f"Rug rate increase: {rug_rate_inc:+.2f}pp <= {self.thresholds.max_rug_rate_increase_abs:.2f}pp"
            )
        else:
            failing_metrics.append(
                f"Rug rate increase: {rug_rate_inc:+.2f}pp > {self.thresholds.max_rug_rate_increase_abs:.2f}pp"
            )

        # 5. Execution Return Degradation Check
        exec_deg = self._compute_execution_return_degradation(scorecard)
        if exec_deg <= self.thresholds.max_execution_return_degradation_pct:
            passing_metrics.append(
                f"Execution return degradation: {exec_deg:+.2f}% <= {self.thresholds.max_execution_return_degradation_pct:.2f}%"
            )
        else:
            failing_metrics.append(
                f"Execution return degradation: {exec_deg:+.2f}% > {self.thresholds.max_execution_return_degradation_pct:.2f}%"
            )

        # 6. Walk-Forward Validation Gate
        if walk_forward_periods_passed >= self.thresholds.min_walk_forward_periods_passed:
            passing_metrics.append(
                f"Walk-forward periods passed: {walk_forward_periods_passed} >= {self.thresholds.min_walk_forward_periods_passed}"
            )
        else:
            failing_metrics.append(
                f"Walk-forward periods passed: {walk_forward_periods_passed} < {self.thresholds.min_walk_forward_periods_passed}"
            )

        # 7. Regime Consistency Check
        regime_failed = False
        failed_regimes: List[str] = []
        if self.thresholds.require_all_regimes_improved and regime_map:
            for regime, passed in regime_map.items():
                if not passed:
                    regime_failed = True
                    failed_regimes.append(regime)

        # 8. Venue Consistency Check
        venue_failed = False
        failed_venues: List[str] = []
        if self.thresholds.require_all_venues_improved and venue_map:
            for venue, passed in venue_map.items():
                if not passed:
                    venue_failed = True
                    failed_venues.append(venue)

        # Evaluate Gating Priority
        if sample_size < self.thresholds.min_sample_size:
            decision = "INSUFFICIENT_DATA"
            reason = (
                f"Evaluation sample size ({sample_size}) is below the required minimum of "
                f"{self.thresholds.min_sample_size} samples. Model cannot be promoted safely."
            )
            logger.info("Promotion check for challenger %s: INSUFFICIENT_DATA (samples=%d)", challenger_id, sample_size)

        elif regime_failed or venue_failed:
            decision = "BLOCKED_BY_REGIME"
            reasons = []
            if failed_regimes:
                reasons.append(f"Regimes failed: [{', '.join(failed_regimes)}]")
            if failed_venues:
                reasons.append(f"Venues failed: [{', '.join(failed_venues)}]")
            reason = f"Challenger failed regime/venue consistency invariant: {'; '.join(reasons)}."
            logger.info("Promotion check for challenger %s: BLOCKED_BY_REGIME (%s)", challenger_id, reason)

        elif len(failing_metrics) > 0:
            decision = "BLOCKED_BY_METRIC"
            reason = f"Challenger failed metric thresholds: {'; '.join(failing_metrics)}."
            logger.info("Promotion check for challenger %s: BLOCKED_BY_METRIC (%d metrics failed)", challenger_id, len(failing_metrics))

        elif len(failing_metrics) == 0 and not regime_failed and not venue_failed and sample_size >= self.thresholds.min_sample_size:
            decision = "PROMOTE"
            reason = (
                f"All promotion criteria met: {len(passing_metrics)} metrics passed, "
                f"walk-forward validation verified ({walk_forward_periods_passed} folds), "
                f"and regime consistency confirmed over {sample_size} test samples."
            )
            logger.info("Promotion check for challenger %s: PROMOTE", challenger_id)

        else:
            decision = "NOT_READY"
            reason = "Model evaluation incomplete or failed to fulfill promotion prerequisites."
            logger.info("Promotion check for challenger %s: NOT_READY", challenger_id)

        return PromotionDecision(
            decision=decision,
            challenger_id=challenger_id,
            champion_id=champion_id,
            passing_metrics=passing_metrics,
            failing_metrics=failing_metrics,
            walk_forward_periods_passed=walk_forward_periods_passed,
            regime_results=regime_map,
            venue_results=venue_map,
            requires_operator_approval=True,
            decision_reason=reason,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

    def validate_deployment_readiness(
        self,
        decision: PromotionDecision,
        operator_approved: bool = False,
    ) -> Tuple[bool, str]:
        """
        Validate whether a promotion decision is ready for automated or operator deployment.

        Args:
            decision: Evaluated PromotionDecision instance.
            operator_approved: Whether the operator has provided signed approval.

        Returns:
            Tuple of (is_deployable, reason_string).
        """
        if decision.decision != "PROMOTE":
            return False, f"Model is not approved for promotion (current status: {decision.decision}): {decision.decision_reason}"

        if decision.requires_operator_approval and not operator_approved:
            return False, "Model passed all automated promotion thresholds but requires explicit operator sign-off."

        return True, f"Model {decision.challenger_id} is fully verified and authorized for production promotion."

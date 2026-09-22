"""
Champion-Challenger Evaluation & Promotion Engine
Manages rigorous shadow comparison and gate-level validation between production
champion (v1.0.0) and candidate challenger models across discrimination (PR-AUC,
Precision@10), calibration (Brier Score, ECE), safety (Rug Rate), and execution returns.
"""

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import logging
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass
class ScorecardMetric:
    """
    Individual evaluation metric comparison between champion and challenger.

    Attributes:
        metric_name: Name of the metric (e.g., 'PR-AUC', 'Brier Score').
        champion_value: Benchmark metric score of the active production champion.
        challenger_value: Metric score achieved by candidate challenger.
        improvement_pct: Percentage improvement (positive = challenger is superior).
        meets_threshold: Boolean indicating if required delta threshold is satisfied.
        threshold: Required delta threshold percentage.
        direction: Optimization direction ('higher_is_better' | 'lower_is_better').
    """
    metric_name: str
    champion_value: float
    challenger_value: float
    improvement_pct: float
    meets_threshold: bool
    threshold: float
    direction: str = "higher_is_better"

    def to_dict(self) -> Dict[str, Any]:
        """Convert metric to a dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ScorecardMetric":
        """Reconstruct ScorecardMetric from dictionary."""
        return cls(**data)


@dataclass
class ComparisonScorecard:
    """
    Comprehensive multi-gate scorecard summarizing champion vs challenger evaluation.

    Attributes:
        champion_id: Unique identifier / version of champion baseline (default 'v1.0.0').
        challenger_id: Unique identifier / candidate model ID being evaluated.
        model_type: Problem category ('SELECTION' | 'ENTRY' | 'EXIT').
        evaluation_period: ISO date/time range or description of validation partition.
        sample_size: Number of evaluated token observations.
        metrics: List of individual ScorecardMetric records.
        all_thresholds_met: True if and only if all evaluated metric gates pass.
        promotion_recommendation: Actionable status ('PROMOTE' | 'NOT_READY' | 'INSUFFICIENT_DATA' | 'REGRESSED').
        regime_specific_results: Metric breakdown segmented by market regime.
        venue_specific_results: Metric breakdown segmented by DEX / venue.
        notes: Audit observations, caveats, and data availability notes.
    """
    champion_id: str
    challenger_id: str
    model_type: str
    evaluation_period: str
    sample_size: int
    metrics: List[ScorecardMetric]
    all_thresholds_met: bool
    promotion_recommendation: str
    regime_specific_results: Dict[str, Dict[str, float]] = field(default_factory=dict)
    venue_specific_results: Dict[str, Dict[str, float]] = field(default_factory=dict)
    notes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Convert scorecard to a dictionary representation."""
        return {
            "champion_id": self.champion_id,
            "challenger_id": self.challenger_id,
            "model_type": self.model_type,
            "evaluation_period": self.evaluation_period,
            "sample_size": self.sample_size,
            "metrics": [m.to_dict() for m in self.metrics],
            "all_thresholds_met": self.all_thresholds_met,
            "promotion_recommendation": self.promotion_recommendation,
            "regime_specific_results": self.regime_specific_results,
            "venue_specific_results": self.venue_specific_results,
            "notes": list(self.notes),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ComparisonScorecard":
        """Reconstruct ComparisonScorecard from dictionary."""
        d = dict(data)
        metrics_raw = d.get("metrics") or []
        parsed_metrics = []
        for item in metrics_raw:
            if isinstance(item, ScorecardMetric):
                parsed_metrics.append(item)
            elif isinstance(item, dict):
                parsed_metrics.append(ScorecardMetric.from_dict(item))
        d["metrics"] = parsed_metrics
        return cls(**d)


@dataclass
class ShadowPredictionRecord:
    """
    Side-by-side inference prediction recorded during live shadow evaluation.

    Attributes:
        token_address: Mint address of the evaluated token.
        timestamp: ISO 8601 UTC timestamp of inference.
        champion_prediction: Probability score output by active champion.
        challenger_prediction: Probability score output by candidate shadow model.
        actual_outcome: Realized binary outcome label (1/0) if mature, else None.
        model_type: Problem category ('SELECTION' | 'ENTRY' | 'EXIT').
    """
    token_address: str
    timestamp: str
    champion_prediction: float
    challenger_prediction: float
    actual_outcome: Optional[int] = None
    model_type: str = "SELECTION"

    def to_dict(self) -> Dict[str, Any]:
        """Convert shadow record to dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ShadowPredictionRecord":
        """Reconstruct ShadowPredictionRecord from dictionary."""
        return cls(**data)


class ChampionChallengerEngine:
    """
    Production Champion-Challenger Evaluation Engine.

    Conducts comparative performance evaluation between current champion models
    and challenger candidates across discrimination, calibration, safety, and regime robustness.
    """
    DEFAULT_CHAMPION_ID: str = "v1.0.0"
    MIN_SAMPLE_SIZE: int = 30

    def __init__(
        self,
        champion_id: str = "v1.0.0",
        min_sample_size: int = 30,
    ) -> None:
        """
        Initialize the ChampionChallengerEngine.

        Args:
            champion_id: Default champion identifier (default: 'v1.0.0').
            min_sample_size: Minimum sample size required for promotion recommendation.
        """
        self.champion_id: str = champion_id or self.DEFAULT_CHAMPION_ID
        self.min_sample_size: int = max(1, min_sample_size)
        self.shadow_predictions: List[ShadowPredictionRecord] = []

    def record_shadow_prediction(
        self,
        token_address: str,
        champion_pred: float,
        challenger_pred: float,
        model_type: str = "SELECTION",
        timestamp: Optional[str] = None,
        actual_outcome: Optional[int] = None,
    ) -> ShadowPredictionRecord:
        """
        Record simultaneous champion and challenger inference predictions.

        Args:
            token_address: Token contract/mint address.
            champion_pred: Prediction probability from current champion.
            challenger_pred: Prediction probability from candidate challenger.
            model_type: Problem domain ('SELECTION' | 'ENTRY' | 'EXIT').
            timestamp: Optional ISO 8601 timestamp string (default: current UTC time).
            actual_outcome: Optional realized binary label if available.

        Returns:
            The created ShadowPredictionRecord.
        """
        ts = timestamp or datetime.now(timezone.utc).isoformat()
        record = ShadowPredictionRecord(
            token_address=token_address,
            timestamp=ts,
            champion_prediction=float(champion_pred),
            challenger_prediction=float(challenger_pred),
            actual_outcome=int(actual_outcome) if actual_outcome is not None else None,
            model_type=model_type.upper(),
        )
        self.shadow_predictions.append(record)
        return record

    def compare_predictions(
        self,
        champion_preds: List[float],
        challenger_preds: List[float],
        labels: List[int],
        champion_id: str = "v1.0.0",
        challenger_id: str = "challenger",
        model_type: str = "SELECTION",
        evaluation_period: str = "",
        regimes: Optional[List[str]] = None,
        venues: Optional[List[str]] = None,
        rug_flags: Optional[List[int]] = None,
        champion_returns: Optional[List[float]] = None,
        challenger_returns: Optional[List[float]] = None,
    ) -> ComparisonScorecard:
        """
        Compute full comparative promotion scorecard across all six core gates.

        Gates evaluated:
        1. PR-AUC (higher_is_better, threshold = 5% improvement)
        2. Precision@10 (higher_is_better, threshold = 10% improvement)
        3. Brier Score (lower_is_better, threshold = not worse by 5%, i.e. >= -5.0% improvement)
        4. ECE (lower_is_better, threshold = not worse by 5%, i.e. >= -5.0% improvement)
        5. Rug Rate (lower_is_better, threshold = not worse by 2%, i.e. >= -2.0% improvement)
        6. Execution Return (higher_is_better, threshold = 0% improvement, i.e. >= 0.0% improvement)

        Args:
            champion_preds: Probability outputs from champion model.
            challenger_preds: Probability outputs from challenger model.
            labels: Ground truth binary target outcomes (1/0).
            champion_id: Champion model identifier.
            challenger_id: Challenger model identifier.
            model_type: Model domain ('SELECTION' | 'ENTRY' | 'EXIT').
            evaluation_period: Description or date range of test partition.
            regimes: Optional list of market regimes per observation.
            venues: Optional list of venues / DEXs per observation.
            rug_flags: Optional binary indicators (1 = rugged, 0 = safe).
            champion_returns: Optional realized percentage returns for champion picks.
            challenger_returns: Optional realized percentage returns for challenger picks.

        Returns:
            ComparisonScorecard with complete metric breakdown and promotion recommendation.
        """
        # Align lengths
        n = min(len(champion_preds), len(challenger_preds), len(labels))
        c_preds = [float(p) for p in champion_preds[:n]]
        ch_preds = [float(p) for p in challenger_preds[:n]]
        y_true = [int(y) for y in labels[:n]]

        notes: List[str] = []
        champ_id = champion_id or self.champion_id
        m_type = model_type.upper() if model_type else "SELECTION"

        if n == 0:
            notes.append("Empty dataset provided; cannot compute metrics.")
            return ComparisonScorecard(
                champion_id=champ_id,
                challenger_id=challenger_id,
                model_type=m_type,
                evaluation_period=evaluation_period,
                sample_size=0,
                metrics=[],
                all_thresholds_met=False,
                promotion_recommendation="INSUFFICIENT_DATA",
                regime_specific_results={},
                venue_specific_results={},
                notes=notes,
            )

        # 1. PR-AUC (higher_is_better, threshold = 5% improvement)
        champ_pr_auc = self._compute_pr_auc(c_preds, y_true)
        chall_pr_auc = self._compute_pr_auc(ch_preds, y_true)
        pr_auc_imp = self._calculate_improvement(champ_pr_auc, chall_pr_auc, "higher_is_better")
        pr_auc_threshold = 5.0
        pr_auc_meets = (pr_auc_imp >= pr_auc_threshold)
        pr_auc_metric = ScorecardMetric(
            metric_name="PR-AUC",
            champion_value=champ_pr_auc,
            challenger_value=chall_pr_auc,
            improvement_pct=round(pr_auc_imp, 2),
            meets_threshold=pr_auc_meets,
            threshold=pr_auc_threshold,
            direction="higher_is_better",
        )

        # 2. Precision@10 (higher_is_better, threshold = 10% improvement)
        champ_p10 = self._compute_precision_at_k(c_preds, y_true, k=10)
        chall_p10 = self._compute_precision_at_k(ch_preds, y_true, k=10)
        p10_imp = self._calculate_improvement(champ_p10, chall_p10, "higher_is_better")
        p10_threshold = 10.0
        p10_meets = (p10_imp >= p10_threshold)
        p10_metric = ScorecardMetric(
            metric_name="Precision@10",
            champion_value=champ_p10,
            challenger_value=chall_p10,
            improvement_pct=round(p10_imp, 2),
            meets_threshold=p10_meets,
            threshold=p10_threshold,
            direction="higher_is_better",
        )

        # 3. Brier Score (lower_is_better, threshold = not worse by 5%)
        champ_brier = self._compute_brier(c_preds, y_true)
        chall_brier = self._compute_brier(ch_preds, y_true)
        brier_imp = self._calculate_improvement(champ_brier, chall_brier, "lower_is_better")
        brier_threshold = -5.0
        brier_meets = (brier_imp >= brier_threshold)
        brier_metric = ScorecardMetric(
            metric_name="Brier Score",
            champion_value=champ_brier,
            challenger_value=chall_brier,
            improvement_pct=round(brier_imp, 2),
            meets_threshold=brier_meets,
            threshold=brier_threshold,
            direction="lower_is_better",
        )

        # 4. ECE (lower_is_better, threshold = not worse by 5%)
        champ_ece = self._compute_ece(c_preds, y_true)
        chall_ece = self._compute_ece(ch_preds, y_true)
        ece_imp = self._calculate_improvement(champ_ece, chall_ece, "lower_is_better")
        ece_threshold = -5.0
        ece_meets = (ece_imp >= ece_threshold)
        ece_metric = ScorecardMetric(
            metric_name="ECE",
            champion_value=champ_ece,
            challenger_value=chall_ece,
            improvement_pct=round(ece_imp, 2),
            meets_threshold=ece_meets,
            threshold=ece_threshold,
            direction="lower_is_better",
        )

        # 5. Rug Rate (lower_is_better, threshold = not worse by 2%)
        has_rug_flags = rug_flags is not None and len(rug_flags) > 0
        if has_rug_flags:
            aligned_rug = [int(r) for r in rug_flags[:n]]
            champ_rug = self._compute_rug_rate(aligned_rug, y_true)
            chall_rug = self._compute_rug_rate(aligned_rug, y_true)
            rug_imp = self._calculate_improvement(champ_rug, chall_rug, "lower_is_better")
            rug_meets = (rug_imp >= -2.0)
        else:
            champ_rug = 0.0
            chall_rug = 0.0
            rug_imp = 0.0
            rug_meets = True
            notes.append("Rug rate data not available; defaulted to 0.0.")

        rug_threshold = -2.0
        rug_metric = ScorecardMetric(
            metric_name="Rug Rate",
            champion_value=champ_rug,
            challenger_value=chall_rug,
            improvement_pct=round(rug_imp, 2),
            meets_threshold=rug_meets,
            threshold=rug_threshold,
            direction="lower_is_better",
        )

        # 6. Execution Return (higher_is_better, threshold = 0% improvement)
        champ_ret = self._compute_execution_return(c_preds, y_true, champion_returns)
        chall_ret = self._compute_execution_return(ch_preds, y_true, challenger_returns)
        ret_imp = self._calculate_improvement(champ_ret, chall_ret, "higher_is_better")
        ret_threshold = 0.0
        ret_meets = (ret_imp >= ret_threshold)
        ret_metric = ScorecardMetric(
            metric_name="Execution Return",
            champion_value=champ_ret,
            challenger_value=chall_ret,
            improvement_pct=round(ret_imp, 2),
            meets_threshold=ret_meets,
            threshold=ret_threshold,
            direction="higher_is_better",
        )

        metrics = [
            pr_auc_metric,
            p10_metric,
            brier_metric,
            ece_metric,
            rug_metric,
            ret_metric,
        ]

        all_thresholds_met = all(m.meets_threshold for m in metrics)

        # Determine promotion recommendation
        positives = sum(y_true)
        if n < self.min_sample_size:
            promotion_recommendation = "INSUFFICIENT_DATA"
            notes.append(f"Sample size (N={n}) is below minimum required ({self.min_sample_size}).")
        elif positives == 0:
            promotion_recommendation = "INSUFFICIENT_DATA"
            notes.append("No positive label events found in validation partition.")
        elif (
            pr_auc_imp < 0.0
            or p10_imp < 0.0
            or brier_imp < -10.0
            or ece_imp < -10.0
            or ret_imp < -5.0
        ):
            promotion_recommendation = "REGRESSED"
            notes.append("Challenger exhibits substantial regression against champion on primary metrics.")
        elif all_thresholds_met:
            promotion_recommendation = "PROMOTE"
            notes.append("All gates satisfied: challenger qualifies for champion promotion.")
        else:
            promotion_recommendation = "NOT_READY"
            notes.append("Challenger performance is stable but did not meet all required improvement thresholds.")

        # Subgroup evaluations
        regime_results = self.compare_by_regime(c_preds, ch_preds, y_true, regimes) if regimes else {}
        venue_results = self.compare_by_venue(c_preds, ch_preds, y_true, venues) if venues else {}

        return ComparisonScorecard(
            champion_id=champ_id,
            challenger_id=challenger_id,
            model_type=m_type,
            evaluation_period=evaluation_period,
            sample_size=n,
            metrics=metrics,
            all_thresholds_met=all_thresholds_met,
            promotion_recommendation=promotion_recommendation,
            regime_specific_results=regime_results,
            venue_specific_results=venue_results,
            notes=notes,
        )

    def compare_by_regime(
        self,
        preds_champion: List[float],
        preds_challenger: List[float],
        labels: List[int],
        regimes: List[str],
    ) -> Dict[str, Dict[str, float]]:
        """
        Group observations by market regime and compute Brier score comparisons.

        Args:
            preds_champion: Champion probability predictions.
            preds_challenger: Challenger probability predictions.
            labels: Ground truth binary labels.
            regimes: Regime identifier strings per observation.

        Returns:
            Dictionary mapping each regime name to champion and challenger Brier scores.
        """
        return self._group_and_compare_brier(preds_champion, preds_challenger, labels, regimes)

    def compare_by_venue(
        self,
        preds_champion: List[float],
        preds_challenger: List[float],
        labels: List[int],
        venues: List[str],
    ) -> Dict[str, Dict[str, float]]:
        """
        Group observations by DEX/venue and compute Brier score comparisons.

        Args:
            preds_champion: Champion probability predictions.
            preds_challenger: Challenger probability predictions.
            labels: Ground truth binary labels.
            venues: Venue identifier strings per observation.

        Returns:
            Dictionary mapping each venue name to champion and challenger Brier scores.
        """
        return self._group_and_compare_brier(preds_champion, preds_challenger, labels, venues)

    def _group_and_compare_brier(
        self,
        preds_champ: List[float],
        preds_chall: List[float],
        labels: List[int],
        groups: Optional[List[str]],
    ) -> Dict[str, Dict[str, float]]:
        """
        Internal helper to partition data by grouping categories and compute Brier scores.
        """
        if not groups:
            return {}

        n = min(len(preds_champ), len(preds_chall), len(labels), len(groups))
        if n == 0:
            return {}

        grouped_indices: Dict[str, List[int]] = {}
        for i in range(n):
            grp = str(groups[i])
            if grp not in grouped_indices:
                grouped_indices[grp] = []
            grouped_indices[grp].append(i)

        results: Dict[str, Dict[str, float]] = {}
        for grp, idxs in grouped_indices.items():
            g_champ = [preds_champ[i] for i in idxs]
            g_chall = [preds_chall[i] for i in idxs]
            g_labels = [labels[i] for i in idxs]

            champ_brier = self._compute_brier(g_champ, g_labels)
            chall_brier = self._compute_brier(g_chall, g_labels)
            imp_pct = self._calculate_improvement(champ_brier, chall_brier, "lower_is_better")

            results[grp] = {
                "champion_brier": round(champ_brier, 4),
                "challenger_brier": round(chall_brier, 4),
                "champion": round(champ_brier, 4),
                "challenger": round(chall_brier, 4),
                "improvement_pct": round(imp_pct, 2),
                "sample_size": float(len(idxs)),
            }

        return results

    # ==================== Helper Metrics ====================

    @staticmethod
    def _compute_brier(preds: List[float], labels: List[int]) -> float:
        """
        Compute Mean Squared Error (Brier Score) between probabilities and binary labels.

        Brier = (1/N) * sum((p_i - y_i)^2). Lower is better.
        """
        n = min(len(preds), len(labels))
        if n == 0:
            return 1.0
        total_sq_err = sum((preds[i] - labels[i]) ** 2 for i in range(n))
        return round(total_sq_err / n, 4)

    @staticmethod
    def _compute_precision_at_k(preds: List[float], labels: List[int], k: int = 10) -> float:
        """
        Compute Precision@K by ranking predictions in descending order and
        calculating the proportion of positive outcomes in the top K instances.
        """
        n = min(len(preds), len(labels))
        if n == 0 or k <= 0:
            return 0.0
        pairs = sorted(zip(preds[:n], labels[:n]), key=lambda x: x[0], reverse=True)
        top_k = pairs[:k]
        if not top_k:
            return 0.0
        true_positives = sum(1 for _, y in top_k if y == 1)
        return round(true_positives / len(top_k), 4)

    @staticmethod
    def _compute_pr_auc(preds: List[float], labels: List[int]) -> float:
        """
        Compute Area Under Precision-Recall Curve (PR-AUC) using trapezoidal integration.

        Sorts predictions descending, computes cumulative precision and recall,
        and applies trapezoidal integration over positive recall increments.
        """
        n = min(len(preds), len(labels))
        if n == 0:
            return 0.0
        total_positives = sum(1 for y in labels[:n] if y == 1)
        if total_positives == 0:
            return 0.0

        pairs = sorted(zip(preds[:n], labels[:n]), key=lambda x: x[0], reverse=True)
        precisions = [1.0]
        recalls = [0.0]
        tp = 0

        for i, (_, y) in enumerate(pairs, 1):
            if y == 1:
                tp += 1
            precisions.append(tp / i)
            recalls.append(tp / total_positives)

        pr_auc = 0.0
        for i in range(1, len(recalls)):
            dx = recalls[i] - recalls[i - 1]
            if dx > 0:
                pr_auc += dx * (precisions[i] + precisions[i - 1]) / 2.0

        return round(min(1.0, max(0.0, pr_auc)), 4)

    @staticmethod
    def _compute_ece(preds: List[float], labels: List[int], n_bins: int = 10) -> float:
        """
        Compute Expected Calibration Error (ECE) across equal-width probability bins.
        """
        n = min(len(preds), len(labels))
        if n == 0:
            return 0.0
        bin_width = 1.0 / max(1, n_bins)
        ece = 0.0

        for b in range(n_bins):
            lo = b * bin_width
            hi = (b + 1) * bin_width
            in_bin = [
                (preds[i], labels[i])
                for i in range(n)
                if (lo <= preds[i] < hi) or (b == n_bins - 1 and preds[i] == 1.0)
            ]
            if in_bin:
                avg_pred = sum(p for p, _ in in_bin) / len(in_bin)
                avg_label = sum(y for _, y in in_bin) / len(in_bin)
                ece += abs(avg_pred - avg_label) * (len(in_bin) / n)

        return round(ece, 4)

    @staticmethod
    def _compute_rug_rate(rug_flags: Optional[List[int]], labels: Optional[List[int]] = None) -> float:
        """
        Compute empirical rug rate from binary flags.

        Args:
            rug_flags: Binary list where 1 = rug pull event, 0 = safe.
            labels: Optional labels list (unused, for API consistency).

        Returns:
            Proportion of tokens identified as rugs.
        """
        if not rug_flags:
            return 0.0
        n = len(rug_flags)
        if n == 0:
            return 0.0
        return round(sum(1 for r in rug_flags if r == 1) / n, 4)

    @classmethod
    def _compute_execution_return(
        cls,
        preds: List[float],
        labels: List[int],
        explicit_returns: Optional[List[float]] = None,
        top_k: int = 10,
    ) -> float:
        """
        Compute expected / realized execution return.

        If explicit returns are supplied, returns their mean.
        Otherwise, estimates return over top-K ranked candidates with a payout proxy.
        """
        if explicit_returns and len(explicit_returns) > 0:
            return round(sum(explicit_returns) / len(explicit_returns), 4)

        n = min(len(preds), len(labels))
        if n == 0:
            return 0.0

        pairs = sorted(zip(preds[:n], labels[:n]), key=lambda x: x[0], reverse=True)
        selected = pairs[:top_k]
        if not selected:
            return 0.0

        # Proxy payoff: 1.0 on positive label (100% win), -0.5 on negative label (50% loss)
        simulated_returns = [1.0 if y == 1 else -0.5 for _, y in selected]
        return round(sum(simulated_returns) / len(simulated_returns), 4)

    @staticmethod
    def _calculate_improvement(champion_val: float, challenger_val: float, direction: str) -> float:
        """
        Calculate relative percentage improvement for higher_is_better and lower_is_better metrics.

        Positive percentage always signifies challenger superiority.
        """
        if abs(champion_val) < 1e-9:
            if abs(challenger_val) < 1e-9:
                return 0.0
            if direction == "higher_is_better":
                return 100.0 if challenger_val > champion_val else -100.0
            else:  # lower_is_better
                return 100.0 if challenger_val < champion_val else -100.0

        if direction == "higher_is_better":
            return ((challenger_val - champion_val) / abs(champion_val)) * 100.0
        else:
            return ((champion_val - challenger_val) / abs(champion_val)) * 100.0

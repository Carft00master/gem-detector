"""
Feature Importance & Selection Engine (Adaptive Learning Engine)
Evaluates feature importance, mutual information, and forward selection across
the 12 frozen v1.0.0 features + 6 trader behavior features.
Never removes features from v1.0.0 control model; only evaluates additions for challengers.
"""

from dataclasses import dataclass, field
import logging
import math
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass
class FeatureImportanceRecord:
    feature_name: str
    importance_score: float = 0.0
    mutual_information: float = 0.0
    correlation_with_target: float = 0.0
    is_v1_frozen_feature: bool = True
    is_candidate_addition: bool = False
    redundancy_warning: Optional[str] = None


@dataclass
class FeatureSelectionReport:
    total_features_evaluated: int
    v1_frozen_features: int
    candidate_additions: int
    selected_features: List[str]
    rejected_features: List[str]
    feature_rankings: List[FeatureImportanceRecord]
    recommended_schema: Dict[str, str]
    schema_hash: str = ""


# The 12 frozen v1.0.0 features
V1_FROZEN_FEATURES = [
    "effective_vol_mc_ratio",
    "effective_buy_pressure",
    "buyer_quality",
    "liquidity_quality",
    "holder_quality",
    "breakout_quality",
    "wallet_independence",
    "wash_trade_risk",
    "cabal_risk_score",
    "dev_risk_score",
    "contract_risk",
    "liquidity_risk",
]

# Candidate additions from Trader Behavior Engine
CANDIDATE_BEHAVIOR_FEATURES = [
    "activity_density_score",
    "participation_breadth_score",
    "two_sided_market_quality",
    "curve_traction_score",
    "early_traction_score",
    "trader_style_match_score",
]

# Contextual features that may improve conditional performance
CANDIDATE_CONTEXT_FEATURES = [
    "token_age_minutes",
    "market_cap_usd",
    "liquidity_usd",
    "volume_5m_usd",
    "volume_1h_usd",
    "unique_buyers",
    "unique_sellers",
]


class FeatureSelector:
    """
    Evaluates feature importance and recommends feature schemas for challenger models.
    """

    @classmethod
    def evaluate_feature_importance(
        cls,
        features: List[Dict[str, float]],
        labels: List[int],
        feature_names: List[str],
    ) -> List[FeatureImportanceRecord]:
        """
        Compute importance scores for all features using correlation-based ranking
        and mutual information estimation.
        """
        if not features or not labels or len(features) != len(labels):
            return []

        n = len(labels)
        records = []

        for fname in feature_names:
            values = [f.get(fname, 0.0) for f in features]

            # Pearson correlation with target
            corr = cls._pearson_correlation(values, [float(y) for y in labels])

            # Mutual information estimate (discretized)
            mi = cls._estimate_mutual_information(values, labels)

            # Combined importance score
            importance = abs(corr) * 0.6 + mi * 0.4

            is_frozen = fname in V1_FROZEN_FEATURES
            is_candidate = fname in CANDIDATE_BEHAVIOR_FEATURES or fname in CANDIDATE_CONTEXT_FEATURES

            # Redundancy check
            redundancy = None
            if is_candidate and abs(corr) < 0.05 and mi < 0.01:
                redundancy = f"LOW_SIGNAL: |corr|={abs(corr):.3f}, MI={mi:.3f}"

            records.append(FeatureImportanceRecord(
                feature_name=fname,
                importance_score=importance,
                mutual_information=mi,
                correlation_with_target=corr,
                is_v1_frozen_feature=is_frozen,
                is_candidate_addition=is_candidate,
                redundancy_warning=redundancy,
            ))

        # Sort by importance descending
        records.sort(key=lambda r: r.importance_score, reverse=True)
        return records

    @classmethod
    def select_features(
        cls,
        features: List[Dict[str, float]],
        labels: List[int],
        min_importance: float = 0.02,
    ) -> FeatureSelectionReport:
        """
        Perform forward feature selection: always include v1.0.0 frozen features,
        then add candidate features that meet minimum importance threshold.
        """
        all_feature_names = list(V1_FROZEN_FEATURES) + list(CANDIDATE_BEHAVIOR_FEATURES) + list(CANDIDATE_CONTEXT_FEATURES)
        rankings = cls.evaluate_feature_importance(features, labels, all_feature_names)

        selected = list(V1_FROZEN_FEATURES)  # Always include frozen features
        rejected = []

        for rec in rankings:
            if rec.is_v1_frozen_feature:
                continue
            if rec.importance_score >= min_importance and rec.redundancy_warning is None:
                selected.append(rec.feature_name)
            else:
                rejected.append(rec.feature_name)

        schema = {f: "float64" for f in selected}
        schema_str = "|".join(sorted(selected))
        schema_hash = str(hash(schema_str))

        return FeatureSelectionReport(
            total_features_evaluated=len(all_feature_names),
            v1_frozen_features=len(V1_FROZEN_FEATURES),
            candidate_additions=len(selected) - len(V1_FROZEN_FEATURES),
            selected_features=selected,
            rejected_features=rejected,
            feature_rankings=rankings,
            recommended_schema=schema,
            schema_hash=schema_hash,
        )

    @staticmethod
    def _pearson_correlation(x: List[float], y: List[float]) -> float:
        """Compute Pearson correlation coefficient between two lists."""
        n = len(x)
        if n < 3:
            return 0.0

        mean_x = sum(x) / n
        mean_y = sum(y) / n

        cov = sum((xi - mean_x) * (yi - mean_y) for xi, yi in zip(x, y)) / n
        std_x = math.sqrt(sum((xi - mean_x) ** 2 for xi in x) / n)
        std_y = math.sqrt(sum((yi - mean_y) ** 2 for yi in y) / n)

        if std_x < 1e-12 or std_y < 1e-12:
            return 0.0

        return max(-1.0, min(1.0, cov / (std_x * std_y)))

    @staticmethod
    def _estimate_mutual_information(values: List[float], labels: List[int], n_bins: int = 10) -> float:
        """
        Estimate mutual information between a continuous feature and binary labels
        using histogram discretization.
        """
        n = len(values)
        if n < 10:
            return 0.0

        # Discretize continuous feature into bins
        min_v = min(values)
        max_v = max(values)
        if max_v - min_v < 1e-12:
            return 0.0

        bin_width = (max_v - min_v) / n_bins
        bins = [min(n_bins - 1, int((v - min_v) / bin_width)) for v in values]

        # Joint and marginal counts
        joint = {}  # (bin, label) -> count
        margin_x = {}  # bin -> count
        margin_y = {}  # label -> count

        for b, y in zip(bins, labels):
            joint[(b, y)] = joint.get((b, y), 0) + 1
            margin_x[b] = margin_x.get(b, 0) + 1
            margin_y[y] = margin_y.get(y, 0) + 1

        mi = 0.0
        for (b, y), count in joint.items():
            p_xy = count / n
            p_x = margin_x[b] / n
            p_y = margin_y[y] / n
            if p_xy > 0 and p_x > 0 and p_y > 0:
                mi += p_xy * math.log(p_xy / (p_x * p_y))

        return max(0.0, mi)

"""
Error Analysis & Missed Winner Profiling Engine (Adaptive Learning Engine)
Classifies observations into TP / TN / FP / FN, audits classifier performance (Precision, Recall, F1),
profiles missed winners (False Negatives) against captured winners (True Positives),
and generates weekly diagnostic reports for continuous model adaptation.
"""

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import logging
import math
import statistics
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


def _safe_median(values: List[float]) -> float:
    """
    Compute the median of a list of floats safely.
    Handles empty lists, None items, and NaN/Inf by filtering and returning 0.0.
    Uses statistics.median where possible, falling back to manual sorted median.
    """
    if not values:
        return 0.0
    valid: List[float] = []
    for v in values:
        if v is None:
            continue
        try:
            fv = float(v)
            if not (math.isnan(fv) or math.isinf(fv)):
                valid.append(fv)
        except (ValueError, TypeError):
            continue

    if not valid:
        return 0.0

    try:
        return float(statistics.median(valid))
    except Exception:
        sorted_vals = sorted(valid)
        n = len(sorted_vals)
        mid = n // 2
        if n % 2 == 1:
            return float(sorted_vals[mid])
        else:
            return float((sorted_vals[mid - 1] + sorted_vals[mid]) / 2.0)


@dataclass
class ErrorClassification:
    """
    Point-in-time classification record for an individual token observation.
    Classifies token into TRUE_POSITIVE, TRUE_NEGATIVE, FALSE_POSITIVE, or FALSE_NEGATIVE.
    """
    token_address: str
    symbol: str
    target: str                           # 'TARGET_100K' | 'TARGET_500K' | 'TARGET_1M' | 'TARGET_3M'
    horizon: str                          # e.g. '15m', '1h', '6h', '24h', 'eventual'
    classification: str                   # 'TRUE_POSITIVE' | 'TRUE_NEGATIVE' | 'FALSE_POSITIVE' | 'FALSE_NEGATIVE'
    predicted_probability: float
    actual_outcome: int                   # 0 or 1
    scanner_selected: bool
    market_cap_usd: float
    liquidity_usd: float
    token_age_minutes: float
    market_regime: str
    venue: str

    def to_dict(self) -> Dict[str, Any]:
        """Convert classification record to a dictionary."""
        return asdict(self)


@dataclass
class MissedWinnerProfile:
    """
    Comprehensive quantitative profile of missed breakout opportunities (False Negatives).
    Compares missed winner distributions and feature medians against captured winners (True Positives).
    """
    total_missed: int
    median_entry_mc: float
    median_entry_age_minutes: float
    median_activity_density: float
    median_trader_density: float
    median_curve_progress: float
    median_wallet_quality: float
    median_liquidity: float
    regime_distribution: Dict[str, int]
    venue_distribution: Dict[str, int]
    age_bucket_distribution: Dict[str, int]
    mc_bucket_distribution: Dict[str, int]
    top_distinguishing_features: List[Tuple[str, float]]
    comparison_vs_true_positives: Dict[str, Dict[str, float]]

    def to_dict(self) -> Dict[str, Any]:
        """Convert missed winner profile to dictionary."""
        return asdict(self)


@dataclass
class ErrorAnalysisReport:
    """
    Full error analysis report across all mature observations for a specified target milestone.
    """
    target: str
    total_observations: int
    total_mature: int
    true_positives: int
    true_negatives: int
    false_positives: int
    false_negatives: int
    precision: float
    recall: float
    f1: float
    missed_winner_profile: Optional[MissedWinnerProfile]
    classifications: List[ErrorClassification]
    report_timestamp: str

    def to_dict(self) -> Dict[str, Any]:
        """Convert error report to dictionary."""
        return {
            "target": self.target,
            "total_observations": self.total_observations,
            "total_mature": self.total_mature,
            "true_positives": self.true_positives,
            "true_negatives": self.true_negatives,
            "false_positives": self.false_positives,
            "false_negatives": self.false_negatives,
            "precision": self.precision,
            "recall": self.recall,
            "f1": self.f1,
            "missed_winner_profile": self.missed_winner_profile.to_dict() if self.missed_winner_profile else None,
            "classifications": [c.to_dict() for c in self.classifications],
            "report_timestamp": self.report_timestamp,
        }


class ErrorAnalyzer:
    """
    Classifies mature token outcomes against model predictions / scanner selections,
    evaluates classification metrics, analyzes missed winners (False Negatives),
    and generates detailed error diagnostic reports.
    """

    TARGET_MC_THRESHOLDS: Dict[str, float] = {
        "TARGET_100K": 100_000.0,
        "TARGET_500K": 500_000.0,
        "TARGET_1M": 1_000_000.0,
        "TARGET_3M": 3_000_000.0,
    }

    TARGET_OUTCOME_KEYS: Dict[str, List[str]] = {
        "TARGET_100K": ["target_100k", "target_reached_100k", "target_100k_reached", "reached_100k", "hit_100k", "target_100k_within_24h", "target_100k_within_1h"],
        "TARGET_500K": ["target_500k", "target_reached_500k", "target_500k_reached", "reached_500k", "hit_500k", "target_500k_within_24h", "target_500k_within_1h"],
        "TARGET_1M": ["target_1m", "target_reached_1m", "target_1m_reached", "reached_1m", "hit_1m", "target_1m_within_24h", "target_1m_within_1h"],
        "TARGET_3M": [
            "target_3m",
            "target_reached_3m",
            "target_3m_reached",
            "target_touch_3m",
            "target_survivable_3m",
            "target_persistent_3m",
            "reached_3m",
            "hit_3m",
            "target_3m_24h",
            "target_3m_eventual",
        ],
    }

    PROB_FIELD_KEYS: Dict[str, List[str]] = {
        "TARGET_100K": ["p_reach_100k", "p_100k", "prob_100k"],
        "TARGET_500K": ["p_reach_500k", "p_500k", "prob_500k"],
        "TARGET_1M": ["p_reach_1m", "p_1m", "prob_1m"],
        "TARGET_3M": ["p_reach_3m", "p_3m", "prob_3m", "p_reach_survivable_3m"],
    }

    STANDARD_AGE_BUCKETS: List[Tuple[str, float, float]] = [
        ("<1m", 0.0, 1.0),
        ("1-5m", 1.0, 5.0),
        ("5-15m", 5.0, 15.0),
        ("15-30m", 15.0, 30.0),
        ("30-60m", 30.0, 60.0),
        ("60m+", 60.0, float("inf")),
    ]

    STANDARD_MC_BUCKETS: List[Tuple[str, float, float]] = [
        ("<5K", 0.0, 5000.0),
        ("5K-10K", 5000.0, 10000.0),
        ("10K-25K", 10000.0, 25000.0),
        ("25K-50K", 25000.0, 50000.0),
        ("50K-100K", 50000.0, 100000.0),
        ("100K+", 100000.0, float("inf")),
    ]

    STANDARD_REGIMES: List[str] = ["NORMAL", "HOT", "COLD", "PANIC"]
    STANDARD_VENUES: List[str] = ["pump_fun", "raydium", "meteora", "moonshot"]

    def __init__(self) -> None:
        """Initialize the ErrorAnalyzer."""
        pass

    @staticmethod
    def _safe_median(values: List[float]) -> float:
        """Safe median helper exposed on class."""
        return _safe_median(values)

    @staticmethod
    def _extract_float(data: Dict[str, Any], keys: List[str], default: float = 0.0) -> float:
        """Safely extract a float value from multiple candidate keys in dictionary or nested features."""
        for k in keys:
            if k in data and data[k] is not None:
                try:
                    val = float(data[k])
                    if not (math.isnan(val) or math.isinf(val)):
                        return val
                except (ValueError, TypeError):
                    continue

        # Check in nested 'features' dict if present
        features = data.get("features")
        if isinstance(features, dict):
            for k in keys:
                if k in features and features[k] is not None:
                    try:
                        val = float(features[k])
                        if not (math.isnan(val) or math.isinf(val)):
                            return val
                    except (ValueError, TypeError):
                        continue

        # Check in nested 'trader_behavior' or 'raw_data' dict if present
        for sub_key in ("trader_behavior", "raw_data", "metrics"):
            sub_dict = data.get(sub_key)
            if isinstance(sub_dict, dict):
                for k in keys:
                    if k in sub_dict and sub_dict[k] is not None:
                        try:
                            val = float(sub_dict[k])
                            if not (math.isnan(val) or math.isinf(val)):
                                return val
                        except (ValueError, TypeError):
                            continue

        return default

    @staticmethod
    def _extract_bool(data: Dict[str, Any], keys: List[str], default: bool = False) -> bool:
        """Safely extract a boolean value from multiple candidate keys."""
        for k in keys:
            if k in data and data[k] is not None:
                v = data[k]
                if isinstance(v, bool):
                    return v
                if isinstance(v, (int, float)):
                    return bool(v)
                if isinstance(v, str):
                    lower_v = v.strip().lower()
                    if lower_v in ("true", "1", "yes", "t"):
                        return True
                    if lower_v in ("false", "0", "no", "f"):
                        return False
        return default

    @staticmethod
    def _extract_str(data: Dict[str, Any], keys: List[str], default: str = "") -> str:
        """Safely extract a string value from multiple candidate keys."""
        for k in keys:
            if k in data and data[k] is not None:
                s = str(data[k]).strip()
                if s:
                    return s
        return default

    def _is_token_mature(self, token: Dict[str, Any], target: str) -> bool:
        """
        Determine if token has reached maturity and can be evaluated.
        Skips tokens with outcome_status == 'PENDING', 'RIGHT_CENSORED', 'CENSORED', or 'UNCERTAIN'.
        """
        # Check explicit maturity flag
        if "is_mature" in token and token["is_mature"] is False:
            return False

        if token.get("is_censored") is True or token.get("is_right_censored") is True:
            return False

        # Check status fields
        status_keys = [
            "outcome_status",
            "status",
            "censoring_status",
            "status_3m_24h",
            "status_3m_eventual",
            "status_3m_1h",
            "status_3m_6h",
            "status_3m_15m",
            "maturity_status",
        ]
        censored_statuses = {"PENDING", "RIGHT_CENSORED", "CENSORED", "UNCERTAIN", "IN_PROGRESS"}

        for k in status_keys:
            if k in token and token[k] is not None:
                val = str(token[k]).strip().upper()
                if val in censored_statuses:
                    return False

        # Also check outcomes sub-dict if present
        outcomes = token.get("outcomes")
        if isinstance(outcomes, dict):
            for k in status_keys:
                if k in outcomes and outcomes[k] is not None:
                    val = str(outcomes[k]).strip().upper()
                    if val in censored_statuses:
                        return False

        return True

    def _extract_predicted_probability(self, token: Dict[str, Any], target: str) -> float:
        """Extract predicted probability for the specified target."""
        target_keys = self.PROB_FIELD_KEYS.get(target, [])
        prob = self._extract_float(token, target_keys, default=-1.0)
        if prob >= 0.0:
            return prob

        # Fallback to general probability keys
        general_prob_keys = [
            "predicted_probability",
            "predicted_prob",
            "prob",
            "probability",
            "p_reach_target",
            "p_reach_3m",
            "model_probability",
            "p_pred",
        ]
        prob = self._extract_float(token, general_prob_keys, default=-1.0)
        if prob >= 0.0:
            return prob

        # Check score (0-100) normalized to 0.0-1.0
        score_val = self._extract_float(token, ["score", "breakout_score", "probability_score"], default=-1.0)
        if score_val >= 0.0:
            if score_val > 1.0:
                return min(1.0, score_val / 100.0)
            return score_val

        return 0.0

    def _extract_actual_outcome(self, token: Dict[str, Any], target: str) -> int:
        """
        Determine if the actual outcome reached the target milestone (SUCCESS = 1, FAILURE = 0).
        """
        # 1. Direct actual_outcome field
        if "actual_outcome" in token and token["actual_outcome"] is not None:
            try:
                return 1 if int(token["actual_outcome"]) == 1 or bool(token["actual_outcome"]) else 0
            except (ValueError, TypeError):
                pass

        # 2. Check direct boolean outcome keys
        target_outcome_keys = self.TARGET_OUTCOME_KEYS.get(target, self.TARGET_OUTCOME_KEYS["TARGET_3M"])
        for k in target_outcome_keys:
            if k in token and token[k] is not None:
                v = token[k]
                if isinstance(v, bool):
                    if v:
                        return 1
                elif isinstance(v, (int, float)):
                    if v == 1:
                        return 1
                elif isinstance(v, str):
                    if v.strip().upper() in ("1", "TRUE", "SUCCESS", "HIT", "REACHED"):
                        return 1

        # 3. Check outcomes sub-dict
        outcomes = token.get("outcomes")
        if isinstance(outcomes, dict):
            for k in target_outcome_keys:
                if k in outcomes and outcomes[k] is not None:
                    v = outcomes[k]
                    if isinstance(v, bool) and v:
                        return 1
                    if isinstance(v, (int, float)) and v == 1:
                        return 1
                    if isinstance(v, str) and v.strip().upper() in ("1", "TRUE", "SUCCESS", "HIT", "REACHED"):
                        return 1

        # 4. Check outcome status strings (e.g. 'SUCCESS')
        outcome_status = self._extract_str(token, ["outcome_status", "status", "target_status"]).upper()
        if outcome_status == "SUCCESS":
            return 1

        # 5. Check if peak market cap reached the target threshold
        target_threshold_mc = self.TARGET_MC_THRESHOLDS.get(target, 3_000_000.0)
        peak_mc = self._extract_float(
            token,
            [
                "peak_market_cap_usd",
                "highest_observed_mc_usd",
                "max_market_cap",
                "max_mc_usd",
                "max_mc",
                "highest_mc",
                "peak_mc",
                "exit_market_cap_usd",
            ],
            default=0.0,
        )

        # Infer peak from entry market cap and Maximum Favorable Excursion (MFE)
        entry_mc = self._extract_float(token, ["entry_market_cap_usd", "entry_mc_usd", "market_cap_usd"], default=0.0)
        mfe = self._extract_float(token, ["mfe_ratio", "mfe"], default=1.0)
        if entry_mc > 0 and mfe > 1.0:
            implied_peak = entry_mc * mfe
            if implied_peak > peak_mc:
                peak_mc = implied_peak

        # If 3M target was explicitly reached, lower milestone thresholds are also satisfied
        if bool(token.get("target_reached_3m", False)):
            peak_mc = max(peak_mc, 3_000_000.0)

        if peak_mc >= target_threshold_mc:
            return 1

        return 0

    @classmethod
    def get_age_bucket(cls, age_minutes: float) -> str:
        """Map token age in minutes into standard age buckets."""
        for label, low, high in cls.STANDARD_AGE_BUCKETS:
            if low <= age_minutes < high:
                return label
        return "60m+"

    @classmethod
    def get_mc_bucket(cls, mc_usd: float) -> str:
        """Map token market cap USD into standard market cap buckets."""
        for label, low, high in cls.STANDARD_MC_BUCKETS:
            if low <= mc_usd < high:
                return label
        return "100K+"

    def classify_observations(
        self,
        tokens: List[Dict[str, Any]],
        target: str = "TARGET_3M",
        threshold: float = 0.08,
    ) -> List[ErrorClassification]:
        """
        For each mature token observation:
        - predicted_positive = (p_reach_target >= threshold) OR scanner_selected
        - actual_positive = target outcome is SUCCESS (e.g. target_3m == 1 or reached target MC)
        - Classify as TRUE_POSITIVE, TRUE_NEGATIVE, FALSE_POSITIVE, or FALSE_NEGATIVE.
        Skips tokens with outcome_status == 'PENDING' or 'RIGHT_CENSORED'.

        Args:
            tokens: List of token observation dictionaries.
            target: Target milestone ('TARGET_100K', 'TARGET_500K', 'TARGET_1M', 'TARGET_3M').
            threshold: Probability decision threshold.

        Returns:
            List of ErrorClassification records for all mature tokens.
        """
        classifications: List[ErrorClassification] = []

        for token in tokens:
            if not isinstance(token, dict):
                continue

            # Skip immature / censored tokens
            if not self._is_token_mature(token, target):
                continue

            token_addr = self._extract_str(token, ["token_address", "address", "token", "mint"], default="unknown")
            symbol = self._extract_str(token, ["symbol", "ticker", "name"], default="UNKNOWN")
            horizon = self._extract_str(token, ["horizon", "horizon_label", "timeframe"], default="24h")
            market_regime = self._extract_str(token, ["market_regime", "regime", "macro_regime"], default="NORMAL").upper()
            venue = self._extract_str(token, ["venue", "dex_id", "dex", "chain_venue"], default="pump_fun").lower()

            mc_usd = self._extract_float(
                token,
                ["market_cap_usd", "entry_market_cap_usd", "initial_mc", "mc_usd", "first_observed_mc_usd", "mc"],
                default=0.0,
            )
            liq_usd = self._extract_float(
                token,
                ["liquidity_usd", "entry_liquidity_usd", "initial_liq", "liq_usd", "liquidity"],
                default=0.0,
            )
            age_min = self._extract_float(
                token,
                ["token_age_minutes", "entry_token_age_minutes", "age_minutes", "token_age_min", "elapsed_minutes", "age"],
                default=0.0,
            )

            scanner_selected = self._extract_bool(
                token,
                ["scanner_selected", "is_selected", "alerted", "is_alerted", "passed_filters", "selected"],
                default=False,
            )

            pred_prob = self._extract_predicted_probability(token, target)
            actual_outcome = self._extract_actual_outcome(token, target)

            predicted_positive = (pred_prob >= threshold) or scanner_selected
            actual_positive = (actual_outcome == 1)

            if predicted_positive and actual_positive:
                cls_type = "TRUE_POSITIVE"
            elif not predicted_positive and not actual_positive:
                cls_type = "TRUE_NEGATIVE"
            elif predicted_positive and not actual_positive:
                cls_type = "FALSE_POSITIVE"
            else:
                cls_type = "FALSE_NEGATIVE"

            record = ErrorClassification(
                token_address=token_addr,
                symbol=symbol,
                target=target,
                horizon=horizon,
                classification=cls_type,
                predicted_probability=round(pred_prob, 6),
                actual_outcome=actual_outcome,
                scanner_selected=scanner_selected,
                market_cap_usd=round(mc_usd, 2),
                liquidity_usd=round(liq_usd, 2),
                token_age_minutes=round(age_min, 2),
                market_regime=market_regime,
                venue=venue,
            )
            classifications.append(record)

        return classifications

    def build_missed_winner_profile(
        self,
        false_negatives: List[ErrorClassification],
        true_positives: List[ErrorClassification],
        all_tokens: List[Dict[str, Any]],
    ) -> MissedWinnerProfile:
        """
        Compute quantitative metrics for the False Negative (missed winners) cohort:
        - Median entry MC, age, activity density, trader density, curve progress, wallet quality, liquidity.
        - Compare vs True Positive (captured winners) group medians.
        - Compute regime, venue, age bucket, and market cap bucket distributions.
        - Rank features by absolute gap between FN and TP medians.

        Args:
            false_negatives: List of False Negative classifications.
            true_positives: List of True Positive classifications.
            all_tokens: Full list of raw token observation dictionaries.

        Returns:
            MissedWinnerProfile instance.
        """
        total_missed = len(false_negatives)

        # Index tokens by address for feature lookup
        token_map: Dict[str, Dict[str, Any]] = {}
        for t in all_tokens:
            if isinstance(t, dict):
                addr = self._extract_str(t, ["token_address", "address", "token", "mint"])
                if addr:
                    token_map[addr] = t

        # Helper to extract a feature vector across a classification list
        def get_feature_values(
            cls_list: List[ErrorClassification],
            feature_name: str,
            candidate_keys: List[str],
            fallback_fn=None,
        ) -> List[float]:
            vals: List[float] = []
            for c in cls_list:
                td = token_map.get(c.token_address, {})
                v = self._extract_float(td, candidate_keys, default=-999999.0)
                if v != -999999.0:
                    vals.append(v)
                elif fallback_fn is not None:
                    vals.append(fallback_fn(c))
                else:
                    vals.append(0.0)
            return vals

        # 1. Standard 7 Key Profile Features for FN
        fn_mcs = [c.market_cap_usd for c in false_negatives]
        fn_ages = [c.token_age_minutes for c in false_negatives]
        fn_liqs = [c.liquidity_usd for c in false_negatives]

        fn_act_densities = get_feature_values(
            false_negatives,
            "activity_density",
            ["activity_density_score", "activity_density", "entry_activity_density_score", "activity_score", "txns_5m_buys"],
        )
        fn_trader_densities = get_feature_values(
            false_negatives,
            "trader_density",
            [
                "trader_density",
                "trader_density_score",
                "participation_breadth_score",
                "unique_buyers",
                "unique_traders",
                "unique_buyers_1h",
            ],
        )
        fn_curve_progresses = get_feature_values(
            false_negatives,
            "curve_progress",
            ["curve_progress", "entry_curve_progress", "curve_progress_pct", "bonding_curve_pct", "curve_traction_score"],
        )
        fn_wallet_qualities = get_feature_values(
            false_negatives,
            "wallet_quality",
            [
                "wallet_quality",
                "wallet_quality_score",
                "smart_wallet_score",
                "wallet_edge_score",
                "buyer_quality",
                "wallet_independence",
            ],
        )

        med_mc = _safe_median(fn_mcs)
        med_age = _safe_median(fn_ages)
        med_act_density = _safe_median(fn_act_densities)
        med_trader_density = _safe_median(fn_trader_densities)
        med_curve = _safe_median(fn_curve_progresses)
        med_wallet = _safe_median(fn_wallet_qualities)
        med_liq = _safe_median(fn_liqs)

        # 2. Distributions for FN
        regime_dist: Dict[str, int] = {r: 0 for r in self.STANDARD_REGIMES}
        venue_dist: Dict[str, int] = {v: 0 for v in self.STANDARD_VENUES}
        age_bucket_dist: Dict[str, int] = {label: 0 for label, _, _ in self.STANDARD_AGE_BUCKETS}
        mc_bucket_dist: Dict[str, int] = {label: 0 for label, _, _ in self.STANDARD_MC_BUCKETS}

        for fn in false_negatives:
            reg = fn.market_regime if fn.market_regime in regime_dist else fn.market_regime or "UNKNOWN"
            regime_dist[reg] = regime_dist.get(reg, 0) + 1

            ven = fn.venue if fn.venue in venue_dist else fn.venue or "unknown"
            venue_dist[ven] = venue_dist.get(ven, 0) + 1

            age_b = self.get_age_bucket(fn.token_age_minutes)
            age_bucket_dist[age_b] = age_bucket_dist.get(age_b, 0) + 1

            mc_b = self.get_mc_bucket(fn.market_cap_usd)
            mc_bucket_dist[mc_b] = mc_bucket_dist.get(mc_b, 0) + 1

        # 3. Comprehensive Feature Comparison vs True Positives
        features_to_compare: Dict[str, Tuple[List[str], Any]] = {
            "entry_market_cap_usd": (
                ["market_cap_usd", "entry_market_cap_usd", "initial_mc", "mc_usd"],
                lambda c: c.market_cap_usd,
            ),
            "entry_token_age_minutes": (
                ["token_age_minutes", "entry_token_age_minutes", "age_minutes"],
                lambda c: c.token_age_minutes,
            ),
            "liquidity_usd": (
                ["liquidity_usd", "entry_liquidity_usd", "initial_liq"],
                lambda c: c.liquidity_usd,
            ),
            "predicted_probability": (
                ["predicted_probability", "predicted_prob", "p_reach_3m"],
                lambda c: c.predicted_probability,
            ),
            "activity_density_score": (
                ["activity_density_score", "activity_density", "entry_activity_density_score"],
                None,
            ),
            "trader_density_score": (
                ["trader_density", "trader_density_score", "participation_breadth_score", "unique_buyers"],
                None,
            ),
            "curve_progress": (
                ["curve_progress", "entry_curve_progress", "bonding_curve_pct", "curve_traction_score"],
                None,
            ),
            "wallet_quality_score": (
                ["wallet_quality", "wallet_quality_score", "smart_wallet_score", "buyer_quality"],
                None,
            ),
            "volume_5m_usd": (
                ["volume_5m_usd", "volume_5m"],
                None,
            ),
            "volume_1h_usd": (
                ["volume_1h_usd", "volume_1h"],
                None,
            ),
            "buy_pressure": (
                ["buy_pressure", "buy_sell_ratio_5m", "effective_buy_pressure"],
                None,
            ),
            "two_sided_market_quality": (
                ["two_sided_market_quality", "two_sided_score"],
                None,
            ),
            "curve_traction_score": (
                ["curve_traction_score", "curve_traction"],
                None,
            ),
            "early_traction_score": (
                ["early_traction_score", "early_traction"],
                None,
            ),
            "wash_trade_risk": (
                ["wash_trade_risk", "wash_risk_score"],
                None,
            ),
            "dev_risk_score": (
                ["dev_risk_score", "dev_holding_pct"],
                None,
            ),
        }

        comparison_vs_true_positives: Dict[str, Dict[str, float]] = {}

        for feat_name, (keys, fallback) in features_to_compare.items():
            fn_vals = get_feature_values(false_negatives, feat_name, keys, fallback)
            tp_vals = get_feature_values(true_positives, feat_name, keys, fallback)

            fn_med = _safe_median(fn_vals)
            tp_med = _safe_median(tp_vals)
            gap = fn_med - tp_med

            comparison_vs_true_positives[feat_name] = {
                "missed_median": round(fn_med, 4),
                "captured_median": round(tp_med, 4),
                "gap": round(gap, 4),
            }

        # Rank features by absolute gap between FN and TP medians
        top_distinguishing_features: List[Tuple[str, float]] = sorted(
            [(feat, round(abs(comp["gap"]), 4)) for feat, comp in comparison_vs_true_positives.items()],
            key=lambda x: x[1],
            reverse=True,
        )

        return MissedWinnerProfile(
            total_missed=total_missed,
            median_entry_mc=round(med_mc, 2),
            median_entry_age_minutes=round(med_age, 2),
            median_activity_density=round(med_act_density, 2),
            median_trader_density=round(med_trader_density, 2),
            median_curve_progress=round(med_curve, 4),
            median_wallet_quality=round(med_wallet, 2),
            median_liquidity=round(med_liq, 2),
            regime_distribution=regime_dist,
            venue_distribution=venue_dist,
            age_bucket_distribution=age_bucket_dist,
            mc_bucket_distribution=mc_bucket_dist,
            top_distinguishing_features=top_distinguishing_features,
            comparison_vs_true_positives=comparison_vs_true_positives,
        )

    def build_error_report(
        self,
        tokens: List[Dict[str, Any]],
        target: str = "TARGET_3M",
        threshold: float = 0.08,
    ) -> ErrorAnalysisReport:
        """
        Classify all observations, count contingency matrix outcomes,
        compute Precision / Recall / F1, and profile missed winners.

        Args:
            tokens: List of token observation dictionaries.
            target: Target breakout milestone ('TARGET_100K', 'TARGET_500K', 'TARGET_1M', 'TARGET_3M').
            threshold: Probability decision threshold.

        Returns:
            ErrorAnalysisReport instance.
        """
        classifications = self.classify_observations(tokens, target=target, threshold=threshold)

        total_obs = len(tokens)
        total_mature = len(classifications)

        tp_list = [c for c in classifications if c.classification == "TRUE_POSITIVE"]
        tn_list = [c for c in classifications if c.classification == "TRUE_NEGATIVE"]
        fp_list = [c for c in classifications if c.classification == "FALSE_POSITIVE"]
        fn_list = [c for c in classifications if c.classification == "FALSE_NEGATIVE"]

        tp = len(tp_list)
        tn = len(tn_list)
        fp = len(fp_list)
        fn = len(fn_list)

        # Metrics with safe zero division handling
        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = (2.0 * precision * recall) / (precision + recall) if (precision + recall) > 0.0 else 0.0

        # Build missed winner profile if any mature tokens exist
        missed_profile: Optional[MissedWinnerProfile] = None
        if total_mature > 0:
            missed_profile = self.build_missed_winner_profile(fn_list, tp_list, tokens)

        now_iso = datetime.now(timezone.utc).isoformat()

        logger.info(
            f"Error report generated for {target}: Total={total_obs}, Mature={total_mature}, "
            f"TP={tp}, TN={tn}, FP={fp}, FN={fn}, Prec={precision:.3f}, Rec={recall:.3f}, F1={f1:.3f}"
        )

        return ErrorAnalysisReport(
            target=target,
            total_observations=total_obs,
            total_mature=total_mature,
            true_positives=tp,
            true_negatives=tn,
            false_positives=fp,
            false_negatives=fn,
            precision=round(precision, 4),
            recall=round(recall, 4),
            f1=round(f1, 4),
            missed_winner_profile=missed_profile,
            classifications=classifications,
            report_timestamp=now_iso,
        )

    def generate_weekly_report(self, tokens: List[Dict[str, Any]]) -> str:
        """
        Generate a comprehensive, markdown-formatted weekly missed winner analysis report.
        Includes: contingency metrics, missed winner counts, distinguishing feature gaps,
        regime and venue breakdowns, and actionable parameter recommendations.

        Args:
            tokens: List of token observation dictionaries across the evaluation window.

        Returns:
            Markdown-formatted report string.
        """
        report = self.build_error_report(tokens, target="TARGET_3M", threshold=0.08)
        profile = report.missed_winner_profile

        lines: List[str] = []
        lines.append("# Weekly Missed Winner Analysis & Error Audit Report")
        lines.append("")
        lines.append(f"**Target Milestone**: `{report.target}`  ")
        lines.append(f"**Report Generated**: `{report.report_timestamp}`  ")
        lines.append(f"**Total Population Ingested**: `{report.total_observations:,}` observations  ")
        lines.append(f"**Total Mature Cohort**: `{report.total_mature:,}` tokens  ")
        lines.append("")

        # 1. Executive Summary & Contingency Table
        lines.append("## 1. Classification & Model Diagnostic Summary")
        lines.append("")
        lines.append("| Metric | Count / Value | Description |")
        lines.append("| :--- | :--- | :--- |")
        lines.append(f"| **True Positives (TP)** | `{report.true_positives:,}` | Breakouts captured by model / scanner |")
        lines.append(f"| **True Negatives (TN)** | `{report.true_negatives:,}` | Non-breakouts correctly rejected |")
        lines.append(f"| **False Positives (FP)** | `{report.false_positives:,}` | Scanner alerted tokens that failed breakout |")
        lines.append(f"| **False Negatives (FN)** | `{report.false_negatives:,}` | **Missed Winners** that reached target uncaught |")
        lines.append(f"| **Precision** | `{report.precision:.2%}` | Ratio of successful alerts to total alerts |")
        lines.append(f"| **Recall (Capture Rate)** | `{report.recall:.2%}` | Ratio of captured winners to total winners |")
        lines.append(f"| **F1 Score** | `{report.f1:.4f}` | Harmonic mean of Precision and Recall |")
        lines.append("")

        if not profile or report.total_mature == 0:
            lines.append("> [!NOTE]")
            lines.append("> Insufficient mature token observations available to profile missed winners.")
            return "\n".join(lines)

        # 2. Missed Winner Feature Profile
        lines.append("## 2. Missed Winner (False Negative) Baseline Profile")
        lines.append("")
        lines.append(f"A total of **{profile.total_missed}** winning tokens reached target valuation without being captured.")
        lines.append("")
        lines.append("| Core Dimension | Missed Winner Median | Unit / Scale |")
        lines.append("| :--- | :--- | :--- |")
        lines.append(f"| **Entry Market Cap** | `${profile.median_entry_mc:,.2f}` | USD |")
        lines.append(f"| **Entry Token Age** | `{profile.median_entry_age_minutes:.1f}` min | Minutes from discovery |")
        lines.append(f"| **Liquidity Depth** | `${profile.median_liquidity:,.2f}` | USD |")
        lines.append(f"| **Activity Density Score** | `{profile.median_activity_density:.1f}` / 100 | Normalized transaction velocity |")
        lines.append(f"| **Trader Density Score** | `{profile.median_trader_density:.1f}` / 100 | Unique buyer breadth |")
        lines.append(f"| **Bonding Curve Progress** | `{profile.median_curve_progress:.1%}` | Curve completion ratio |")
        lines.append(f"| **Smart-Wallet Quality** | `{profile.median_wallet_quality:.1f}` / 100 | Smart-money wallet tier |")
        lines.append("")

        # 3. Distinguishing Features: Missed vs Captured Winners
        lines.append("## 3. Feature Comparison: Missed Winners (FN) vs Captured Winners (TP)")
        lines.append("")
        lines.append("Quantifies the behavioral and microstructure gaps between missed and captured breakout tokens.")
        lines.append("")
        lines.append("| Feature Name | Missed (FN) Median | Captured (TP) Median | Gap (FN - TP) | Distinguishing Rank |")
        lines.append("| :--- | :--- | :--- | :--- | :--- |")

        for rank, (feat_name, imp_score) in enumerate(profile.top_distinguishing_features, start=1):
            comp = profile.comparison_vs_true_positives.get(feat_name, {})
            fn_med = comp.get("missed_median", 0.0)
            tp_med = comp.get("captured_median", 0.0)
            gap = comp.get("gap", 0.0)
            sign = "+" if gap > 0 else ""
            lines.append(f"| `{feat_name}` | `{fn_med:,.2f}` | `{tp_med:,.2f}` | `{sign}{gap:,.2f}` | #{rank} (Impact: {imp_score:.2f}) |")

        lines.append("")

        # 4. Environmental & Market Distributions
        lines.append("## 4. Missed Winner Distribution Breakdowns")
        lines.append("")
        lines.append("### 4.1 Market Regime Breakdown")
        lines.append("")
        lines.append("| Macro Regime | Missed Count | Share of Total Missed |")
        lines.append("| :--- | :--- | :--- |")
        for reg, count in profile.regime_distribution.items():
            share = (count / profile.total_missed) if profile.total_missed > 0 else 0.0
            lines.append(f"| `{reg}` | `{count}` | `{share:.1%}` |")
        lines.append("")

        lines.append("### 4.2 DEX / Venue Breakdown")
        lines.append("")
        lines.append("| Venue / Pool | Missed Count | Share of Total Missed |")
        lines.append("| :--- | :--- | :--- |")
        for ven, count in profile.venue_distribution.items():
            share = (count / profile.total_missed) if profile.total_missed > 0 else 0.0
            lines.append(f"| `{ven}` | `{count}` | `{share:.1%}` |")
        lines.append("")

        lines.append("### 4.3 Age Bucket Breakdown at Observation")
        lines.append("")
        lines.append("| Age Range | Missed Count | Share of Total Missed |")
        lines.append("| :--- | :--- | :--- |")
        for age_b, count in profile.age_bucket_distribution.items():
            share = (count / profile.total_missed) if profile.total_missed > 0 else 0.0
            lines.append(f"| `{age_b}` | `{count}` | `{share:.1%}` |")
        lines.append("")

        lines.append("### 4.4 Market Cap Range at Observation")
        lines.append("")
        lines.append("| MC Range | Missed Count | Share of Total Missed |")
        lines.append("| :--- | :--- | :--- |")
        for mc_b, count in profile.mc_bucket_distribution.items():
            share = (count / profile.total_missed) if profile.total_missed > 0 else 0.0
            lines.append(f"| `{mc_b}` | `{count}` | `{share:.1%}` |")
        lines.append("")

        # 5. Top Missed Tokens Sample
        fn_classifications = [c for c in report.classifications if c.classification == "FALSE_NEGATIVE"]
        if fn_classifications:
            lines.append("## 5. Sample Missed Winners Cohort")
            lines.append("")
            lines.append("| Symbol | Address | Market Cap | Age | Pred Prob | Regime | Venue |")
            lines.append("| :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
            sample_fn = fn_classifications[:10]
            for c in sample_fn:
                short_addr = f"{c.token_address[:6]}...{c.token_address[-4:]}" if len(c.token_address) > 12 else c.token_address
                lines.append(
                    f"| **{c.symbol}** | `{short_addr}` | `${c.market_cap_usd:,.0f}` | "
                    f"`{c.token_age_minutes:.1f}m` | `{c.predicted_probability:.3f}` | `{c.market_regime}` | `{c.venue}` |"
                )
            lines.append("")

        # 6. Actionable Takeaways & Next Steps
        lines.append("## 6. Actionable Challenger Model Recommendations")
        lines.append("")
        if profile.total_missed > 0:
            lines.append("Based on the quantitative error profile, the following adaptations are indicated:")
            lines.append("")
            if profile.top_distinguishing_features:
                top_feature, top_gap = profile.top_distinguishing_features[0]
                lines.append(f"1. **Primary Feature Divergence**: `{top_feature}` exhibited the highest distinction (gap: {top_gap:.2f}). Evaluate weighting adjustment in challenger feature schema.")
            if profile.median_entry_mc > 35000.0:
                lines.append(f"2. **Discovery Ceiling**: Missed winners show median entry MC of ${profile.median_entry_mc:,.0f}, suggesting early-stage discovery latency or tight MC filter ceilings.")
            if profile.median_activity_density > 60.0:
                lines.append("3. **Traction Sensitivity**: High activity density in missed tokens indicates organic microcap velocity was present but underweighted relative to static safety filters.")
            lines.append("4. **Threshold Tuning**: Evaluate challenger threshold candidates to improve recall without sacrificing target precision.")
        else:
            lines.append("Zero false negatives observed in current mature window. Current model achieved 100% recall.")

        lines.append("")
        return "\n".join(lines)

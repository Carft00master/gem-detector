"""
Research Evaluation, Exact Binomial Statistics & Probabilistic Calibration Engine
Computes Precision@K, PR-AUC, ROC-AUC, Prevalence Brier Baseline, Brier Skill Score (BSS),
Wilson 95% Confidence Intervals, Clopper-Pearson Exact Binomial 95% Confidence Intervals,
Calibration Intercept/Slope, and Reliability Diagrams.
"""

from dataclasses import dataclass, field
import math
import random
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class CalibrationBucket:
    bucket_label: str
    bin_lower: float
    bin_upper: float
    predicted_mean_prob: float = 0.0
    empirical_event_rate: float = 0.0
    sample_count: int = 0
    positive_count: int = 0


@dataclass
class BaseRateReport:
    total_tokens: int = 0
    tokens_reached_50k: int = 0
    base_rate_50k: float = 0.0
    tokens_reached_100k: int = 0
    base_rate_100k: float = 0.0
    tokens_reached_500k: int = 0
    base_rate_500k: float = 0.0
    tokens_reached_1m: int = 0
    base_rate_1m: float = 0.0
    tokens_reached_3m: int = 0
    base_rate_3m: float = 0.0
    tokens_rugged: int = 0
    rug_rate: float = 0.0
    manipulated_count: int = 0
    manipulation_rate: float = 0.0


@dataclass
class LeadTimeReport:
    avg_lead_time_50k_min: float = 0.0
    median_lead_time_50k_min: float = 0.0
    avg_lead_time_100k_min: float = 0.0
    median_lead_time_100k_min: float = 0.0
    avg_lead_time_500k_min: float = 0.0
    median_lead_time_500k_min: float = 0.0
    avg_lead_time_1m_min: float = 0.0
    median_lead_time_1m_min: float = 0.0
    avg_lead_time_3m_min: float = 0.0
    median_lead_time_3m_min: float = 0.0


@dataclass
class ModelPerformanceReport:
    model_name: str
    sample_size: int
    unique_token_count: int = 0
    total_positives: int = 0
    total_negatives: int = 0
    total_censored: int = 0
    population_base_rate: float = 0.0

    # Primary Benchmark Metric (One Token = One Opportunity)
    # FIRST-ALERT TOKEN-LEVEL PRECISION@10 FOR TARGET $3M
    primary_first_alert_precision_at_10: float = 0.0
    primary_precision_wilson_ci_95: Tuple[float, float] = (0.0, 0.0)
    primary_precision_exact_ci_95: Tuple[float, float] = (0.0, 0.0)

    # Contingency Counts
    selected_candidates: int = 0
    true_positives: int = 0
    false_positives: int = 0
    true_negatives: int = 0
    false_negatives: int = 0

    # Discrimination & Precision Metrics
    precision: float = 0.0
    recall: Optional[float] = None
    f1_score: Optional[float] = None
    pr_auc: Optional[float] = None
    roc_auc: Optional[float] = None
    precision_at_10: float = 0.0
    precision_at_25: float = 0.0
    precision_at_50: float = 0.0
    precision_at_100: float = 0.0
    precision_at_1_pct: float = 0.0
    precision_at_5_pct: float = 0.0
    precision_at_10_pct: float = 0.0

    false_positive_rate: float = 0.0
    false_negative_rate: Optional[float] = None
    base_rate_lift_3m: Optional[float] = None
    status_label: str = "EVALUATED"

    @property
    def formatted_pr_auc(self) -> str:
        return f"{self.pr_auc:.4f}" if self.pr_auc is not None else "N/A (No Positives)"

    @property
    def formatted_roc_auc(self) -> str:
        return f"{self.roc_auc:.4f}" if self.roc_auc is not None else "N/A (Single Class)"

    @property
    def formatted_recall(self) -> str:
        return f"{self.recall:.2%}" if self.recall is not None else "N/A (0/0)"

    @property
    def formatted_lift(self) -> str:
        return f"{self.base_rate_lift_3m:.2f}x" if self.base_rate_lift_3m is not None else "[N/A / NO POSITIVES]"

    # Probabilistic Brier Baseline & Skill Score Reporting
    brier_score_ml: float = 0.0
    brier_prevalence_baseline: float = 0.0   # p * (1 - p)
    brier_50pct_baseline: float = 0.25       # Constant 50% predictor
    brier_absolute_improvement: float = 0.0  # Prevalence - ML
    brier_skill_score_pct: float = 0.0       # (1 - ML / Prevalence) * 100%

    # Calibration Curve Intercept & Slope
    calibration_intercept: float = 0.0       # alpha in logit(y) = alpha + beta * logit(p)
    calibration_slope: float = 1.0           # beta in logit(y) = alpha + beta * logit(p)

    log_loss: float = 0.0
    expected_calibration_error: float = 0.0  # ECE
    is_empirically_calibrated: bool = False
    reliability_diagram: List[CalibrationBucket] = field(default_factory=list)

    # 95% Token-Clustered Bootstrap Confidence Intervals: metric_name -> (lower, upper)
    confidence_intervals_95: Dict[str, Tuple[float, float]] = field(default_factory=dict)

    lead_times: LeadTimeReport = field(default_factory=LeadTimeReport)
    base_rates: BaseRateReport = field(default_factory=BaseRateReport)


class ResearchEvaluator:
    @staticmethod
    def compute_wilson_ci(k: int, n: int, confidence: float = 0.95) -> Tuple[float, float]:
        """
        Compute Wilson Score 95% confidence interval for a binomial proportion.
        Appropriate for small sample sizes (e.g. N=10).
        """
        if n <= 0:
            return (0.0, 0.0)
        z = 1.959963984540054  # 95% normal quantile
        p_hat = k / n
        denominator = 1.0 + (z ** 2) / n
        center = (p_hat + (z ** 2) / (2.0 * n)) / denominator
        margin = (z / denominator) * math.sqrt((p_hat * (1.0 - p_hat) / n) + ((z ** 2) / (4.0 * (n ** 2))))
        lower = max(0.0, center - margin)
        upper = min(1.0, center + margin)
        return (round(lower, 4), round(upper, 4))

    @staticmethod
    def compute_clopper_pearson_exact_ci(k: int, n: int, confidence: float = 0.95) -> Tuple[float, float]:
        """
        Compute Clopper-Pearson Exact 95% binomial confidence interval via bisection search.
        Guarantees exact conservative coverage for small samples (N=10).
        """
        if n <= 0:
            return (0.0, 0.0)
        alpha = 1.0 - confidence
        alpha2 = alpha / 2.0

        def binom_cdf(x: float, total_n: int, successes: int) -> float:
            # P(X <= successes | p = x)
            cdf = 0.0
            for i in range(successes + 1):
                comb = math.comb(total_n, i)
                cdf += comb * (x ** i) * ((1.0 - x) ** (total_n - i))
            return cdf

        # Lower bound: P(X >= k | p = L) = alpha / 2  <=> 1 - P(X <= k-1 | p = L) = alpha / 2
        if k == 0:
            lower = 0.0
        else:
            low, high = 0.0, 1.0
            for _ in range(60):
                mid = (low + high) / 2.0
                tail = 1.0 - binom_cdf(mid, n, k - 1)
                if tail < alpha2:
                    low = mid
                else:
                    high = mid
            lower = (low + high) / 2.0

        # Upper bound: P(X <= k | p = U) = alpha / 2
        if k == n:
            upper = 1.0
        else:
            low, high = 0.0, 1.0
            for _ in range(60):
                mid = (low + high) / 2.0
                cdf_val = binom_cdf(mid, n, k)
                if cdf_val < alpha2:
                    high = mid
                else:
                    low = mid
            upper = (low + high) / 2.0

        return (round(lower, 4), round(upper, 4))

    @staticmethod
    def compute_base_rate(records: List[Dict[str, Any]]) -> BaseRateReport:
        n = len(records)
        report = BaseRateReport(total_tokens=n)
        if n == 0:
            return report

        c_50k = sum(1 for r in records if r.get("target_50k"))
        c_100k = sum(1 for r in records if r.get("target_100k"))
        c_500k = sum(1 for r in records if r.get("target_500k"))
        c_1m = sum(1 for r in records if r.get("target_1m"))
        c_3m = sum(1 for r in records if r.get("target_3m") or r.get("is_valid_3m_runner"))
        c_rug = sum(1 for r in records if r.get("is_rug_event"))
        c_manip = sum(1 for r in records if r.get("wash_trade_risk", 0) > 0.6 or r.get("cabal_risk_score", 0) > 0.6)

        report.tokens_reached_50k = c_50k
        report.base_rate_50k = c_50k / n
        report.tokens_reached_100k = c_100k
        report.base_rate_100k = c_100k / n
        report.tokens_reached_500k = c_500k
        report.base_rate_500k = c_500k / n
        report.tokens_reached_1m = c_1m
        report.base_rate_1m = c_1m / n
        report.tokens_reached_3m = c_3m
        report.base_rate_3m = c_3m / n
        report.tokens_rugged = c_rug
        report.rug_rate = c_rug / n
        report.manipulated_count = c_manip
        report.manipulation_rate = c_manip / n

        return report

    @staticmethod
    def compute_precision_at_k(ranked_predictions: List[Tuple[float, int]], k: int) -> float:
        if not ranked_predictions:
            return 0.0
        top_k = ranked_predictions[:k]
        if not top_k:
            return 0.0
        true_positives = sum(1 for _, y_true in top_k if y_true == 1)
        return true_positives / len(top_k)

    @staticmethod
    def compute_pr_auc(ranked_predictions: List[Tuple[float, int]]) -> Optional[float]:
        """Compute Area Under Precision-Recall Curve (PR-AUC) using trapezoidal integration."""
        total_positives = sum(1 for _, y in ranked_predictions if y == 1)
        if total_positives == 0 or not ranked_predictions:
            return None

        precisions = []
        recalls = []
        tp = 0
        for i, (_, y) in enumerate(ranked_predictions, 1):
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

    @classmethod
    def compute_calibration_diagram(
        cls,
        y_true: List[int],
        y_prob: List[float],
        num_bins: int = 10,
    ) -> Tuple[List[CalibrationBucket], float]:
        """
        Compute 10-bin reliability diagram and Expected Calibration Error (ECE).
        """
        buckets = []
        n = len(y_true)
        if n == 0:
            return buckets, 0.0

        bin_step = 1.0 / num_bins
        total_ece = 0.0

        for b in range(num_bins):
            b_lower = round(b * bin_step, 2)
            b_upper = round((b + 1) * bin_step, 2)
            label = f"{b_lower:.1f} - {b_upper:.1f}"

            bin_y = [y for p, y in zip(y_prob, y_true) if (b_lower <= p < b_upper) or (b == num_bins - 1 and p == 1.0)]
            bin_p = [p for p in y_prob if (b_lower <= p < b_upper) or (b == num_bins - 1 and p == 1.0)]

            count = len(bin_y)
            pos = sum(bin_y)
            mean_p = sum(bin_p) / count if count > 0 else (b_lower + b_upper) / 2.0
            emp_rate = pos / count if count > 0 else 0.0

            if count > 0:
                total_ece += (count / n) * abs(mean_p - emp_rate)

            buckets.append(CalibrationBucket(
                bucket_label=label,
                bin_lower=b_lower,
                bin_upper=b_upper,
                predicted_mean_prob=round(mean_p, 4),
                empirical_event_rate=round(emp_rate, 4),
                sample_count=count,
                positive_count=pos,
            ))

        return buckets, round(total_ece, 4)

    @classmethod
    def compute_calibration_slope_and_intercept(
        cls,
        y_true: List[int],
        y_prob: List[float],
    ) -> Tuple[float, float]:
        """
        Compute calibration intercept (alpha) and slope (beta) on log-odds scale:
        logit(p_empirical) = alpha + beta * logit(p_pred)
        """
        n = len(y_true)
        if n < 5 or sum(y_true) == 0 or sum(y_true) == n:
            return 0.0, 1.0

        eps = 1e-6
        x_logits = [math.log(max(eps, min(1.0 - eps, p)) / (1.0 - max(eps, min(1.0 - eps, p)))) for p in y_prob]
        pairs = sorted(zip(x_logits, y_true), key=lambda x: x[0])
        x_sorted = [p[0] for p in pairs]
        y_sorted = [p[1] for p in pairs]

        x_mean = sum(x_sorted) / n
        y_mean = sum(y_sorted) / n
        var_x = sum((x - x_mean) ** 2 for x in x_sorted)
        cov_xy = sum((x - x_mean) * (y - y_mean) for x, y in zip(x_sorted, y_sorted))

        if var_x > 0:
            beta = cov_xy / var_x
            alpha = y_mean - beta * x_mean
            return round(alpha, 4), round(beta, 4)
        return 0.0, 1.0

    @classmethod
    def token_clustered_bootstrap_ci(
        cls,
        y_true: List[int],
        y_prob: List[float],
        token_ids: Optional[List[str]] = None,
        num_resamples: int = 400,
        threshold: float = 0.5,
    ) -> Dict[str, Tuple[float, float]]:
        """Compute 95% bootstrap confidence intervals clustered by unique tokens."""
        n = len(y_true)
        if n < 10:
            return {}

        tokens = token_ids or [f"Tok_{i}" for i in range(n)]
        unique_tokens = list(set(tokens))
        num_clusters = len(unique_tokens)

        token_to_indices: Dict[str, List[int]] = {}
        for idx, t_id in enumerate(tokens):
            token_to_indices.setdefault(t_id, []).append(idx)

        boot_roc = []
        boot_prec = []
        boot_brier = []

        rng = random.Random(42)

        for _ in range(num_resamples):
            resampled_tokens = [rng.choice(unique_tokens) for _ in range(num_clusters)]
            sampled_indices = []
            for t_id in resampled_tokens:
                sampled_indices.extend(token_to_indices[t_id])

            if not sampled_indices:
                continue

            res_true = [y_true[i] for i in sampled_indices]
            res_prob = [y_prob[i] for i in sampled_indices]
            res_n = len(res_true)

            brier = sum((p - y) ** 2 for p, y in zip(res_prob, res_true)) / res_n
            boot_brier.append(brier)

            tp = sum(1 for p, y in zip(res_prob, res_true) if p >= threshold and y == 1)
            fp = sum(1 for p, y in zip(res_prob, res_true) if p >= threshold and y == 0)
            boot_prec.append(tp / (tp + fp) if (tp + fp) > 0 else 0.0)

            pos = [p for p, y in zip(res_prob, res_true) if y == 1]
            neg = [p for p, y in zip(res_prob, res_true) if y == 0]
            if pos and neg:
                ranks = sum(1.0 if ps > ns else (0.5 if ps == ns else 0.0) for ps in pos for ns in neg)
                boot_roc.append(ranks / (len(pos) * len(neg)))

        def get_ci(arr: List[float]) -> Tuple[float, float]:
            if not arr:
                return (0.0, 0.0)
            arr.sort()
            return (round(arr[int(0.025 * len(arr))], 4), round(arr[int(0.975 * len(arr))], 4))

        return {
            "roc_auc": get_ci(boot_roc),
            "precision": get_ci(boot_prec),
            "brier_score": get_ci(boot_brier),
        }

    @classmethod
    def evaluate_model(
        cls,
        y_true: List[int],
        y_prob: List[float],
        token_ids: Optional[List[str]] = None,
        censored_flags: Optional[List[bool]] = None,
        lead_time_data: Optional[List[Dict[str, Any]]] = None,
        model_name: str = "CalibratedPredictor",
        threshold: float = 0.5,
    ) -> ModelPerformanceReport:
        n = len(y_true)
        report = ModelPerformanceReport(model_name=model_name, sample_size=n)
        if n == 0:
            return report

        report.unique_token_count = len(set(token_ids)) if token_ids else n
        report.total_positives = sum(y_true)
        report.total_negatives = n - report.total_positives
        report.total_censored = sum(1 for c in censored_flags if c) if censored_flags else 0

        base_rate = report.total_positives / n if n > 0 else 0.0
        report.population_base_rate = round(base_rate, 4)

        pairs = sorted(zip(y_prob, y_true), key=lambda x: x[0], reverse=True)

        # Precision@K
        report.precision_at_10 = cls.compute_precision_at_k(pairs, 10)
        report.precision_at_25 = cls.compute_precision_at_k(pairs, 25)
        report.precision_at_50 = cls.compute_precision_at_k(pairs, 50)
        report.precision_at_100 = cls.compute_precision_at_k(pairs, 100)

        # Primary Benchmark: Token-Level First Alert Precision@10 with Exact CIs
        top_10 = pairs[:10]
        k_10 = sum(1 for _, y in top_10 if y == 1)
        n_10 = len(top_10)
        report.primary_first_alert_precision_at_10 = report.precision_at_10
        report.primary_precision_wilson_ci_95 = cls.compute_wilson_ci(k_10, n_10, 0.95)
        report.primary_precision_exact_ci_95 = cls.compute_clopper_pearson_exact_ci(k_10, n_10, 0.95)

        # PR-AUC
        report.pr_auc = cls.compute_pr_auc(pairs)

        # Contingency Matrix
        tp = sum(1 for p, y in zip(y_prob, y_true) if p >= threshold and y == 1)
        fp = sum(1 for p, y in zip(y_prob, y_true) if p >= threshold and y == 0)
        fn = sum(1 for p, y in zip(y_prob, y_true) if p < threshold and y == 1)
        tn = sum(1 for p, y in zip(y_prob, y_true) if p < threshold and y == 0)

        report.selected_candidates = tp + fp
        report.true_positives = tp
        report.false_positives = fp
        report.true_negatives = tn
        report.false_negatives = fn
        report.precision = round(tp / (tp + fp) if (tp + fp) > 0 else 0.0, 4)

        if report.total_positives == 0:
            report.recall = None
            report.f1_score = None
            report.false_negative_rate = None
            report.base_rate_lift_3m = None
            report.pr_auc = None
            report.roc_auc = None
            report.status_label = "STATUS: INSUFFICIENT POSITIVE EVENTS (N_pos=0) - Continue observation"
        else:
            report.recall = round(tp / (tp + fn) if (tp + fn) > 0 else 0.0, 4)
            if report.recall is not None and (report.precision + report.recall) > 0:
                report.f1_score = round(2 * (report.precision * report.recall) / (report.precision + report.recall), 4)
            report.false_negative_rate = round(fn / (fn + tp) if (fn + tp) > 0 else 0.0, 4)
            report.base_rate_lift_3m = round((report.precision / base_rate) if base_rate > 0 else 1.0, 2)
            report.status_label = "EVALUATED"

        report.false_positive_rate = round(fp / (fp + tn) if (fp + tn) > 0 else 0.0, 4)

        # Corrected Brier Baselines
        brier_ml = sum((p - y) ** 2 for p, y in zip(y_prob, y_true)) / n
        report.brier_score_ml = round(brier_ml, 5)
        brier_prev = base_rate * (1.0 - base_rate)
        report.brier_prevalence_baseline = round(brier_prev, 5)
        report.brier_50pct_baseline = 0.25000
        report.brier_absolute_improvement = round(brier_prev - brier_ml, 5)

        if brier_prev > 0:
            report.brier_skill_score_pct = round((1.0 - (brier_ml / brier_prev)) * 100.0, 2)
        else:
            report.brier_skill_score_pct = 0.0

        # Log Loss
        eps = 1e-12
        logloss = -sum(y * math.log(max(eps, p)) + (1 - y) * math.log(max(eps, 1 - p)) for p, y in zip(y_prob, y_true)) / n
        report.log_loss = round(logloss, 4)

        # Reliability Diagram & ECE
        diagram, ece = cls.compute_calibration_diagram(y_true, y_prob)
        report.reliability_diagram = diagram
        report.expected_calibration_error = ece
        report.is_empirically_calibrated = (ece <= 0.15)

        # Calibration Slope & Intercept
        alpha, beta = cls.compute_calibration_slope_and_intercept(y_true, y_prob)
        report.calibration_intercept = alpha
        report.calibration_slope = beta

        # ROC-AUC
        pos_scores = [p for p, y in zip(y_prob, y_true) if y == 1]
        neg_scores = [p for p, y in zip(y_prob, y_true) if y == 0]
        if pos_scores and neg_scores:
            ranks = sum(1.0 if ps > ns else (0.5 if ps == ns else 0.0) for ps in pos_scores for ns in neg_scores)
            report.roc_auc = round(ranks / (len(pos_scores) * len(neg_scores)), 4)
        else:
            report.roc_auc = None

        # Clustered Bootstrap CIs
        report.confidence_intervals_95 = cls.token_clustered_bootstrap_ci(
            y_true, y_prob, token_ids=token_ids, threshold=threshold
        )

        # Lead Times
        if lead_time_data:
            lead_times_3m = [d.get("time_to_3m_min") for d in lead_time_data if d.get("time_to_3m_min") is not None]
            lead_times_1m = [d.get("time_to_1m_min") for d in lead_time_data if d.get("time_to_1m_min") is not None]
            lead_times_100k = [d.get("time_to_100k_min") for d in lead_time_data if d.get("time_to_100k_min") is not None]

            if lead_times_3m:
                report.lead_times.avg_lead_time_3m_min = round(sum(lead_times_3m) / len(lead_times_3m), 1)
                sorted_3m = sorted(lead_times_3m)
                report.lead_times.median_lead_time_3m_min = round(sorted_3m[len(sorted_3m) // 2], 1)

            if lead_times_1m:
                report.lead_times.avg_lead_time_1m_min = round(sum(lead_times_1m) / len(lead_times_1m), 1)
                sorted_1m = sorted(lead_times_1m)
                report.lead_times.median_lead_time_1m_min = round(sorted_1m[len(sorted_1m) // 2], 1)

            if lead_times_100k:
                report.lead_times.avg_lead_time_100k_min = round(sum(lead_times_100k) / len(lead_times_100k), 1)
                sorted_100k = sorted(lead_times_100k)
                report.lead_times.median_lead_time_100k_min = round(sorted_100k[len(sorted_100k) // 2], 1)

        return report

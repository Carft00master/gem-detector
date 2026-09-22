"""
Discovery Age Cohort Stratification Engine (v1.0.0 Frozen)
Evaluates breakout scanner predictive performance stratified across 6 discovery age cohorts:
1. 0 - 1 minute
2. 1 - 5 minutes
3. 5 - 15 minutes
4. 15 - 30 minutes
5. 30 - 60 minutes
6. 60+ minutes

Ensures explicit "N=0 / NO DATA" formatting across empty cohorts to avoid misleading blank cells.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
import numpy as np

from src.research.evaluation import ResearchEvaluator


@dataclass
class AgeCohortPerformance:
    cohort_label: str
    min_age_minutes: float
    max_age_minutes: float
    total_tokens: int = 0
    positive_tokens_3m: int = 0
    empirical_base_rate: float = 0.0
    precision_at_10: float = 0.0
    pr_auc: float = 0.0
    brier_score: float = 0.0
    median_lead_time_min: float = 0.0
    median_return_pct: float = 0.0
    rug_rate: float = 0.0

    @property
    def display_sample_size(self) -> str:
        return str(self.total_tokens) if self.total_tokens > 0 else "N=0 / NO DATA"

    @property
    def display_base_rate(self) -> str:
        return f"{self.empirical_base_rate:.2%}" if self.total_tokens > 0 else "N=0 / NO DATA"

    @property
    def display_precision_10(self) -> str:
        if self.total_tokens == 0:
            return "N=0 / NO DATA"
        return f"{self.precision_at_10:.2%}"

    @property
    def display_pr_auc(self) -> str:
        if self.total_tokens == 0:
            return "N=0 / NO DATA"
        return f"{self.pr_auc:.4f}"

    @property
    def display_rug_rate(self) -> str:
        if self.total_tokens == 0:
            return "N=0 / NO DATA"
        return f"{self.rug_rate:.1%}"


class AgeCohortAnalyzer:
    AGE_COHORTS = [
        ("0 - 1 min", 0.0, 1.0),
        ("1 - 5 min", 1.0, 5.0),
        ("5 - 15 min", 5.0, 15.0),
        ("15 - 30 min", 15.0, 30.0),
        ("30 - 60 min", 30.0, 60.0),
        ("60+ min", 60.0, 1000000.0),
    ]

    @classmethod
    def analyze_cohorts(
        cls,
        records: List[Dict[str, Any]],
        ml_probs: Optional[List[float]] = None,
    ) -> List[AgeCohortPerformance]:
        """
        Segment tokens by discovery age and compute predictive metrics.
        """
        results: List[AgeCohortPerformance] = []
        n = len(records)
        probs = ml_probs or [float(r.get("p_reach_3m", 0.05)) for r in records]

        for label, min_a, max_a in cls.AGE_COHORTS:
            cohort_records = []
            cohort_probs = []
            for r, p in zip(records, probs):
                age = float(r.get("token_age_minutes", r.get("elapsed_minutes", 10.0)))
                if (min_a <= age < max_a) or (max_a > 100000.0 and age >= min_a):
                    cohort_records.append(r)
                    cohort_probs.append(p)

            c_n = len(cohort_records)
            perf = AgeCohortPerformance(
                cohort_label=label,
                min_age_minutes=min_a,
                max_age_minutes=max_a,
                total_tokens=c_n,
            )

            if c_n > 0:
                y_true = [1 if (r.get("target_3m") or r.get("is_valid_3m_runner") or r.get("target_survivable_3m")) else 0 for r in cohort_records]
                c_pos = sum(y_true)
                c_rug = sum(1 for r in cohort_records if r.get("is_rug_event") or r.get("rug_event"))
                lead_times = [float(r.get("time_to_3m_min", 0.0)) for r in cohort_records if r.get("time_to_3m_min")]

                perf.positive_tokens_3m = c_pos
                perf.empirical_base_rate = round(c_pos / c_n, 4)
                perf.rug_rate = round(c_rug / c_n, 4)

                eval_rep = ResearchEvaluator.evaluate_model(
                    y_true=y_true,
                    y_prob=cohort_probs,
                    model_name=f"Cohort_{label}",
                )
                perf.precision_at_10 = eval_rep.precision_at_10
                perf.pr_auc = eval_rep.pr_auc
                perf.brier_score = eval_rep.brier_score_ml
                perf.median_lead_time_min = round(float(np.median(lead_times)), 1) if lead_times else 0.0

            results.append(perf)

        return results

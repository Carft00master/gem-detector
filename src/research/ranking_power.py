"""
Live Ranking Power & Canonical Multi-Population Percentile Lift Auditor (v1.0.0 Frozen)
Evaluates empirical ranking power and selection lift across authoritative population scopes:
1. FULL_UNIVERSE              (End-to-End Scanner Performance across all discovered candidates)
2. CAPTURE_CONFIRMED          (Performance across tokens verified inside $8K-$35K)
3. MODEL_ELIGIBLE             (Conditional Model Performance across tokens with complete feature vectors)
4. FIRST_ALERT_OPPORTUNITIES  (Deduplicated holdout test first alert opportunities)

Zero-Positive Metric Protection:
When positive target events == 0, PR-AUC, ROC-AUC, and Lift are formatted as "N/A (No Positives)".
"""

from dataclasses import dataclass, field
import math
from typing import Any, Dict, List, Optional, Tuple
import numpy as np

from src.research.evaluation import ResearchEvaluator
from src.research.population_registry import CanonicalPopulationRegistry, PopulationCounts, PopulationRegistrySummary


@dataclass
class PercentileRankTier:
    tier_label: str
    percentile_cutoff: float          # e.g. 0.01 for Top 1%
    total_candidates: int = 0
    selected_count: int = 0
    hit_count_3m: int = 0
    empirical_hit_rate: float = 0.0
    base_rate: float = 0.0
    lift_over_base_rate: Optional[float] = None
    wilson_ci_95: Tuple[float, float] = (0.0, 0.0)

    @property
    def formatted_lift(self) -> str:
        return f"{self.lift_over_base_rate:.2f}x" if self.lift_over_base_rate is not None else "[N/A / NO POSITIVES]"


@dataclass
class RankingPowerReport:
    population_scope: str = "FULL_UNIVERSE"  # "FULL_UNIVERSE" | "CAPTURE_CONFIRMED" | "MODEL_ELIGIBLE" | "FIRST_ALERT_OPPORTUNITIES"
    scope_description: str = "End-to-End Scanner Performance (All Ingested Candidates)"
    total_population_n: int = 0
    n_mature: int = 0
    n_pending: int = 0
    n_censored: int = 0
    unique_tokens_count: int = 0
    total_positives_3m: int = 0
    total_negatives_3m: int = 0
    population_base_rate: float = 0.0
    pr_auc: Optional[float] = None
    roc_auc: Optional[float] = None
    sample_guardrail_status: str = "STATUS: INSUFFICIENT POSITIVE EVENTS"
    evidence_level: str = "INSUFFICIENT (N < 25)"
    is_statistically_conclusive: bool = False
    tiers: List[PercentileRankTier] = field(default_factory=list)

    @property
    def formatted_pr_auc(self) -> str:
        return f"{self.pr_auc:.4f}" if self.pr_auc is not None else "N/A (No Positives)"

    @property
    def formatted_roc_auc(self) -> str:
        return f"{self.roc_auc:.4f}" if self.roc_auc is not None else "N/A (Single Class)"


@dataclass
class MultiPopulationRankingReport:
    full_universe_report: RankingPowerReport = field(default_factory=RankingPowerReport)
    capture_confirmed_report: RankingPowerReport = field(default_factory=RankingPowerReport)
    model_eligible_report: RankingPowerReport = field(default_factory=RankingPowerReport)
    first_alert_report: RankingPowerReport = field(default_factory=RankingPowerReport)
    registry_summary: Optional[PopulationRegistrySummary] = None


class RankingPowerAuditor:
    PERCENTILE_TIERS = [
        ("Top 1%", 0.01),
        ("Top 5%", 0.05),
        ("Top 10%", 0.10),
        ("Top 20%", 0.20),
        ("Top 50%", 0.50),
        ("All Candidates (100%)", 1.00),
    ]

    @classmethod
    def audit_ranking_power(
        cls,
        records: List[Dict[str, Any]],
        ml_probs: Optional[List[float]] = None,
        scope: str = "FULL_UNIVERSE",
    ) -> RankingPowerReport:
        """
        Evaluate empirical selection lift across percentile subsets for an explicit population scope.
        """
        n = len(records)
        scope_desc = {
            "FULL_UNIVERSE": "End-to-End Scanner Performance (All Ingested Candidates)",
            "CAPTURE_CONFIRMED": "Capture-Confirmed Population (Prompt Ingestion in $8K-$35K)",
            "MODEL_ELIGIBLE": "Conditional Model Performance (Complete Feature Vectors)",
            "FIRST_ALERT_OPPORTUNITIES": "Deduplicated First-Alert Opportunities (Locked Holdout)",
        }.get(scope, "Custom Population Scope")

        report = RankingPowerReport(
            population_scope=scope,
            scope_description=scope_desc,
            total_population_n=n,
        )
        if n == 0:
            return report

        tokens = [r.get("token_address", f"tok_{i}") for i, r in enumerate(records)]
        report.unique_tokens_count = len(set(tokens))
        probs = ml_probs or [float(r.get("p_reach_3m", 0.05)) for r in records]

        from src.research.outcome_maturity import CanonicalOutcomeMaturityEngine
        maturity_states = [CanonicalOutcomeMaturityEngine.evaluate_token_maturity(r, target_name="TARGET_3M", horizon_name="24h") for r in records]

        n_mat = sum(1 for s in maturity_states if s.is_mature)
        n_pnd = sum(1 for s in maturity_states if s.outcome_status == "PENDING")
        n_cns = sum(1 for s in maturity_states if s.outcome_status == "RIGHT_CENSORED")
        total_pos = sum(1 for s in maturity_states if s.outcome_status == "SUCCESS")
        total_neg = sum(1 for s in maturity_states if s.outcome_status == "FAILURE")

        report.n_mature = n_mat
        report.n_pending = n_pnd
        report.n_censored = n_cns
        report.total_positives_3m = total_pos
        report.total_negatives_3m = total_neg
        report.evidence_level = CanonicalOutcomeMaturityEngine.get_evidence_status(n_mat)

        base_rate = total_pos / n_mat if n_mat > 0 else 0.0
        report.population_base_rate = round(base_rate, 4)

        if total_pos == 0:
            if n_mat < 25:
                report.sample_guardrail_status = f"NO_POSITIVES_YET / INSUFFICIENT EVIDENCE (N_mature={n_mat}, N_pending={n_pnd})"
            else:
                report.sample_guardrail_status = f"NO_POSITIVES_AFTER_MATURE_SAMPLE (N_mature={n_mat})"
            report.is_statistically_conclusive = False
            report.pr_auc = None
            report.roc_auc = None
        elif n_mat < 100:
            report.sample_guardrail_status = f"PRELIMINARY / INSUFFICIENT LIVE SAMPLE (N_mature={n_mat} < 100)"
            report.is_statistically_conclusive = False
            eval_rep = ResearchEvaluator.evaluate_model(y_true=[1 if s.outcome_status == "SUCCESS" else 0 for s in maturity_states if s.is_mature], y_prob=[p for p, s in zip(probs, maturity_states) if s.is_mature], model_name=f"Shadow_{scope}")
            report.pr_auc = eval_rep.pr_auc
            report.roc_auc = eval_rep.roc_auc
        else:
            report.sample_guardrail_status = f"STATISTICALLY_EVALUATED (N_mature={n_mat} >= 100)"
            report.is_statistically_conclusive = True
            eval_rep = ResearchEvaluator.evaluate_model(y_true=[1 if s.outcome_status == "SUCCESS" else 0 for s in maturity_states if s.is_mature], y_prob=[p for p, s in zip(probs, maturity_states) if s.is_mature], model_name=f"Shadow_{scope}")
            report.pr_auc = eval_rep.pr_auc
            report.roc_auc = eval_rep.roc_auc

        # Rank mature candidates by predicted probability descending
        mature_pairs = [(p, 1 if s.outcome_status == "SUCCESS" else 0) for p, s in zip(probs, maturity_states) if s.is_mature]
        pairs = sorted(mature_pairs, key=lambda x: x[0], reverse=True)
        eval_n = len(pairs)

        for label, pct in cls.PERCENTILE_TIERS:
            k = max(1, int(math.ceil(eval_n * pct))) if eval_n > 0 else 0
            top_subset = pairs[:k]
            k_hits = sum(1 for _, y in top_subset if y == 1)
            emp_rate = k_hits / k if k > 0 else 0.0
            lift = (emp_rate / base_rate) if base_rate > 0 else None
            ci = ResearchEvaluator.compute_wilson_ci(k_hits, k, 0.95) if k > 0 else (0.0, 0.0)

            report.tiers.append(PercentileRankTier(
                tier_label=label,
                percentile_cutoff=pct,
                total_candidates=eval_n,
                selected_count=k,
                hit_count_3m=k_hits,
                empirical_hit_rate=round(emp_rate, 4),
                base_rate=round(base_rate, 4),
                lift_over_base_rate=round(lift, 2) if lift is not None else None,
                wilson_ci_95=ci,
            ))

        return report

    @classmethod
    def audit_multi_populations(
        cls,
        shadow_records: List[Dict[str, Any]],
        ml_probs: Optional[List[float]] = None,
    ) -> MultiPopulationRankingReport:
        """
        Produce ranking reports for Full Universe, Capture Confirmed, Model Eligible, and First Alert populations.
        """
        if ml_probs is not None and len(ml_probs) == len(shadow_records):
            probs = ml_probs
        else:
            probs = [float(r.get("p_reach_3m", 0.05)) for r in shadow_records]
        
        # 1. Full Universe (N=53)
        full_rep = cls.audit_ranking_power(shadow_records, ml_probs=probs, scope="FULL_UNIVERSE")

        # Classify each token authoritatively using CanonicalPopulationRegistry
        seen_first_alerts = set()
        token_states = [CanonicalPopulationRegistry.classify_token_state(r, seen_first_alerts) for r in shadow_records]

        # 2. Capture Confirmed
        captured_pairs = [(r, p) for r, p, st in zip(shadow_records, probs, token_states) if st.discovery_status == "CAPTURE_CONFIRMED"]
        c_recs = [cp[0] for cp in captured_pairs]
        c_probs = [cp[1] for cp in captured_pairs]
        captured_rep = cls.audit_ranking_power(c_recs, ml_probs=c_probs, scope="CAPTURE_CONFIRMED")

        # 3. Model Eligible
        eligible_pairs = [(r, p) for r, p, st in zip(shadow_records, probs, token_states) if st.model_status == "MODEL_ELIGIBLE"]
        e_recs = [ep[0] for ep in eligible_pairs]
        e_probs = [ep[1] for ep in eligible_pairs]
        eligible_rep = cls.audit_ranking_power(e_recs, ml_probs=e_probs, scope="MODEL_ELIGIBLE")

        # 4. First Alert Opportunities
        fa_pairs = [(r, p) for r, p, st in zip(shadow_records, probs, token_states) if st.first_alert_status == "FIRST_ALERT"]
        fa_recs = [f[0] for f in fa_pairs]
        fa_probs = [f[1] for f in fa_pairs]
        fa_rep = cls.audit_ranking_power(fa_recs, ml_probs=fa_probs, scope="FIRST_ALERT_OPPORTUNITIES")

        return MultiPopulationRankingReport(
            full_universe_report=full_rep,
            capture_confirmed_report=captured_rep,
            model_eligible_report=eligible_rep,
            first_alert_report=fa_rep,
        )

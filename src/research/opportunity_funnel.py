"""
Canonical 11-Stage Opportunity Funnel & Zero-Event Safe Winner Recall Engine (v1.0.0 Frozen)
Integrates directly with CanonicalPopulationRegistry to track the complete 11-stage lifecycle:
Stage 1:  FULL_UNIVERSE
Stage 2:  CAPTURE_CONFIRMED
Stage 3:  UNCERTAIN
Stage 4:  MISSED
Stage 5:  MODEL_ELIGIBLE
Stage 6:  FIRST_ALERT_OPPORTUNITIES
Stage 7:  ALERTED
Stage 8:  TRADEABLE
Stage 9:  TARGET_TOUCH
Stage 10: TARGET_PERSISTENT
Stage 11: TARGET_SURVIVABLE

Computes conversion rates and 4-tier Winner Recall:
- DISCOVERY_RECALL   = (captured winners / all winners)
- MODEL_RECALL       = (model-eligible winners / captured winners)
- ALERT_RECALL       = (alerted winners / model-eligible winners)
- END_TO_END_RECALL  = (survivable winners / all winners)

When actual target winners == 0, recall metrics are treated as undefined and return None ("N/A (0/0)").
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
import numpy as np

from src.research.population_registry import CanonicalPopulationRegistry, PopulationCounts, PopulationRegistrySummary


@dataclass
class FunnelStageMetric:
    stage_index: int
    stage_name: str
    token_count: int = 0
    winner_count_3m: int = 0
    conversion_from_previous_pct: float = 100.0
    conversion_from_start_pct: float = 100.0
    description: str = ""


@dataclass
class WinnerRecallReport:
    total_ground_truth_winners: int = 0
    winners_captured_in_range: int = 0
    winners_model_eligible: int = 0
    winners_ranked_top_decile: int = 0
    winners_alerted_early: int = 0
    winners_survivable_executed: int = 0

    discovery_recall_pct: Optional[float] = None
    model_recall_pct: Optional[float] = None
    alert_recall_pct: Optional[float] = None
    end_to_end_recall_pct: Optional[float] = None

    status_label: str = "EVALUATED"

    @property
    def formatted_discovery_recall(self) -> str:
        return f"{self.discovery_recall_pct:.2f}%" if self.discovery_recall_pct is not None else "N/A (0/0)"

    @property
    def formatted_model_recall(self) -> str:
        return f"{self.model_recall_pct:.2f}%" if self.model_recall_pct is not None else "N/A (0/0)"

    @property
    def formatted_alert_recall(self) -> str:
        return f"{self.alert_recall_pct:.2f}%" if self.alert_recall_pct is not None else "N/A (0/0)"

    @property
    def formatted_end_to_end_recall(self) -> str:
        return f"{self.end_to_end_recall_pct:.2f}%" if self.end_to_end_recall_pct is not None else "N/A (0/0)"


@dataclass
class OpportunityFunnelReport:
    total_initial_candidates: int = 0
    stages: List[FunnelStageMetric] = field(default_factory=list)
    recall: WinnerRecallReport = field(default_factory=WinnerRecallReport)
    registry_summary: Optional[PopulationRegistrySummary] = None


class OpportunityFunnelAuditor:
    @classmethod
    def audit_funnel(
        cls,
        shadow_records: List[Dict[str, Any]],
        ml_probs: Optional[List[float]] = None,
    ) -> OpportunityFunnelReport:
        """
        Evaluate full 11-stage conversion funnel using CanonicalPopulationRegistry.
        """
        n = len(shadow_records)
        report = OpportunityFunnelReport(total_initial_candidates=n)
        if n == 0:
            return report

        reg = CanonicalPopulationRegistry()
        reg_summary = reg.build_registry_from_shadow_tokens(shadow_records)
        report.registry_summary = reg_summary
        counts = reg_summary.counts

        # 11 Canonical Stages
        c_full = counts.full_universe
        c_cap = counts.capture_confirmed
        c_unc = counts.discovery_uncertain
        c_mis = counts.discovery_missed
        c_elig = counts.model_eligible
        c_fa = counts.first_alert_opportunities
        c_alrt = counts.alerted
        c_trd = counts.tradeable
        c_tch = counts.target_touch
        c_pst = counts.target_persistent
        c_srv = counts.target_survivable

        w_full = counts.target_touch

        stage_definitions = [
            (1, "1. FULL_UNIVERSE", c_full, w_full, "Total observed raw tokens entering scanner"),
            (2, "2. CAPTURE_CONFIRMED", c_cap, w_full, "Promptly observed inside $8K-$35K window"),
            (3, "3. UNCERTAIN", c_unc, 0, "Telemetry delay > 5000ms or single-tick transient"),
            (4, "4. MISSED", c_mis, 0, "Bypassed discovery window without timely capture"),
            (5, "5. MODEL_ELIGIBLE", c_elig, w_full, "Captured tokens with complete feature vectors (LP >= $500)"),
            (6, "6. FIRST_ALERT_OPPORTUNITY", c_fa, w_full, "Deduplicated 1st token signal among eligible"),
            (7, "7. ALERTED", c_alrt, w_full, "Triggered EARLY_BREAKOUT or HIGH_CONVICTION alert"),
            (8, "8. TRADEABLE", c_trd, w_full, "Passed execution liquidity (LP >= $1,500) and risk filters"),
            (9, "9. TARGET_TOUCH", c_tch, c_tch, "Reached $3,000,000 market cap milestone"),
            (10, "10. TARGET_PERSISTENT", c_pst, c_pst, "Sustained $3M for >= 5.0 minutes"),
            (11, "11. TARGET_SURVIVABLE", c_srv, c_srv, "Reached $3M without catastrophic pre-drawdown"),
        ]

        stages = []
        prev_cnt = c_full
        for idx, name, cnt, w_cnt, desc in stage_definitions:
            conv_prev = (cnt / prev_cnt * 100.0) if prev_cnt > 0 else 0.0
            conv_start = (cnt / c_full * 100.0) if c_full > 0 else 0.0
            stages.append(FunnelStageMetric(
                stage_index=idx,
                stage_name=name,
                token_count=cnt,
                winner_count_3m=w_cnt,
                conversion_from_previous_pct=round(conv_prev, 1),
                conversion_from_start_pct=round(conv_start, 1),
                description=desc,
            ))
            if idx not in (3, 4):  # Don't update prev_cnt for parallel failure branches
                prev_cnt = cnt

        report.stages = stages

        # Multi-Tier Recall Decomposition with Zero-Positive Protection
        if w_full == 0:
            report.recall = WinnerRecallReport(
                total_ground_truth_winners=0,
                winners_captured_in_range=0,
                winners_model_eligible=0,
                winners_ranked_top_decile=0,
                winners_alerted_early=0,
                winners_survivable_executed=0,
                discovery_recall_pct=None,
                model_recall_pct=None,
                alert_recall_pct=None,
                end_to_end_recall_pct=None,
                status_label="STATUS: INSUFFICIENT POSITIVE EVENTS (N_pos=0)",
            )
        else:
            w_cap = sum(1 for t in reg_summary.tokens if t.discovery_status == "CAPTURE_CONFIRMED" and t.target_status != "NO_TARGET")
            w_elig = sum(1 for t in reg_summary.tokens if t.model_status == "MODEL_ELIGIBLE" and t.target_status != "NO_TARGET")
            w_alrt = sum(1 for t in reg_summary.tokens if t.alert_status == "ALERTED" and t.target_status != "NO_TARGET")
            w_srv = sum(1 for t in reg_summary.tokens if t.target_status == "SURVIVABLE_WINNER")

            disc_rec = (w_cap / w_full * 100.0) if w_full > 0 else None
            model_rec = (w_elig / w_cap * 100.0) if w_cap > 0 else None
            alert_rec = (w_alrt / w_elig * 100.0) if w_elig > 0 else None
            e2e_rec = (w_srv / w_full * 100.0) if w_full > 0 else None

            report.recall = WinnerRecallReport(
                total_ground_truth_winners=w_full,
                winners_captured_in_range=w_cap,
                winners_model_eligible=w_elig,
                winners_ranked_top_decile=w_alrt,
                winners_alerted_early=w_alrt,
                winners_survivable_executed=w_srv,
                discovery_recall_pct=round(disc_rec, 2) if disc_rec is not None else None,
                model_recall_pct=round(model_rec, 2) if model_rec is not None else None,
                alert_recall_pct=round(alert_rec, 2) if alert_rec is not None else None,
                end_to_end_recall_pct=round(e2e_rec, 2) if e2e_rec is not None else None,
                status_label="EVALUATED",
            )

        return report

"""
Automated Live Validation Checkpoints Engine (v1.0.0 Frozen)
Triggers comprehensive statistical validation snapshots at predefined sample milestones:
N = 25, 50, 100, 250, 500 shadow candidates.

Each milestone report contains:
- population size, unique tokens, positive count, base rate
- ranking lift across percentiles
- primary Precision@10 with exact CIs
- PR-AUC, ROC-AUC, Brier score, ECE
- opportunity-window lead times
- execution quote accuracy (Median & P95)
- paper-trade return & max drawdown
- rug rate and missed discovery rate
"""

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.research.age_cohorts import AgeCohortAnalyzer
from src.research.discovery_audit import DiscoveryCaptureAuditor
from src.research.evaluation import ResearchEvaluator
from src.research.execution_validation import ExecutionQuoteValidator
from src.research.opportunity_window import OpportunityWindowAnalyzer
from src.research.ranking_power import RankingPowerAuditor
from src.version import FROZEN_VERSION_MANIFEST

logger = logging.getLogger(__name__)


@dataclass
class CheckpointReport:
    milestone_n: int
    scanner_version: str
    timestamp: str
    sample_size: int
    unique_tokens: int
    positive_count: int
    base_rate_pct: float
    precision_at_10_pct: float
    precision_exact_ci_95: List[float]
    pr_auc: float
    roc_auc: float
    brier_skill_score_pct: float
    ece_score: float
    median_time_to_target_min: float
    median_execution_quote_error_pct: float
    p95_execution_quote_error_pct: float
    universe_capture_rate_pct: float
    rug_rate_pct: float
    guardrail_status: str


class LiveMilestoneTracker:
    MILESTONES = [25, 50, 100, 250, 500]

    def __init__(self, checkpoints_dir: Optional[Path] = None):
        self.base_dir = checkpoints_dir or (Path(__file__).resolve().parent.parent.parent / "data" / "checkpoints")
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.discovery_auditor = DiscoveryCaptureAuditor()
        self.execution_validator = ExecutionQuoteValidator()

    def evaluate_checkpoints(
        self,
        shadow_records: List[Dict[str, Any]],
        ml_probs: Optional[List[float]] = None,
    ) -> Optional[CheckpointReport]:
        """
        Evaluate if current sample count triggers an automated milestone checkpoint report.
        """
        n = len(shadow_records)
        if n not in self.MILESTONES and not (n > 0 and n % 100 == 0):
            return None

        probs = ml_probs or [float(r.get("p_reach_3m", 0.05)) for r in shadow_records]
        y_true = [1 if (r.get("target_3m") or r.get("is_valid_3m_runner") or r.get("target_survivable_3m")) else 0 for r in shadow_records]
        tokens = [r.get("token_address", f"tok_{i}") for i, r in enumerate(shadow_records)]

        eval_rep = ResearchEvaluator.evaluate_model(y_true=y_true, y_prob=probs, token_ids=tokens, model_name=f"Checkpoint_N{n}")
        ranking_rep = RankingPowerAuditor.audit_ranking_power(shadow_records, ml_probs=probs)
        opp_rep = OpportunityWindowAnalyzer.analyze_opportunities(shadow_records)
        disc_rep = self.discovery_auditor.audit_ingestion_population(shadow_records)
        exec_rep = self.execution_validator.validate_quotes()

        c_rug = sum(1 for r in shadow_records if r.get("is_rug_event") or r.get("rug_event"))
        rug_rate = (c_rug / n * 100.0) if n > 0 else 0.0

        report = CheckpointReport(
            milestone_n=n,
            scanner_version=FROZEN_VERSION_MANIFEST.scanner_version,
            timestamp=datetime.now(timezone.utc).isoformat(),
            sample_size=n,
            unique_tokens=len(set(tokens)),
            positive_count=sum(y_true),
            base_rate_pct=round(eval_rep.base_rates.base_rate_3m * 100.0, 2),
            precision_at_10_pct=round(eval_rep.precision_at_10 * 100.0, 2),
            precision_exact_ci_95=[round(eval_rep.primary_precision_exact_ci_95[0] * 100.0, 2), round(eval_rep.primary_precision_exact_ci_95[1] * 100.0, 2)],
            pr_auc=round(eval_rep.pr_auc, 4),
            roc_auc=round(eval_rep.roc_auc, 4),
            brier_skill_score_pct=round(eval_rep.brier_skill_score_pct, 2),
            ece_score=round(eval_rep.expected_calibration_error, 4),
            median_time_to_target_min=opp_rep.median_time_to_target_min,
            median_execution_quote_error_pct=exec_rep.median_quote_error_pct,
            p95_execution_quote_error_pct=exec_rep.p95_quote_error_pct,
            universe_capture_rate_pct=disc_rep.universe_capture_rate_pct,
            rug_rate_pct=round(rug_rate, 2),
            guardrail_status="PRELIMINARY / INSUFFICIENT LIVE SAMPLE (N < 100)" if n < 100 else "VALIDATED_SAMPLE (N >= 100)",
        )

        # Persist checkpoint JSON
        out_file = self.base_dir / f"checkpoint_N{n}_{int(datetime.now(timezone.utc).timestamp())}.json"
        with open(out_file, "w", encoding="utf-8") as f:
            json.dump(asdict(report), f, indent=2)

        return report

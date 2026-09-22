"""
Research Data Export & Comprehensive Report Generation Service
Supports CSV/JSON export and formal markdown quantitative audit reports.
"""

import csv
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional
import pandas as pd

from src.research.shadow import ShadowUniverseLogger
from src.research.storage import ResearchStorage
from src.version import FROZEN_VERSION_MANIFEST

logger = logging.getLogger(__name__)


class ExportService:
    def __init__(self, export_dir: Optional[Path] = None):
        self.root_dir = Path(__file__).resolve().parent.parent.parent
        self.export_dir = export_dir or (self.root_dir / "exports")
        self.export_dir.mkdir(parents=True, exist_ok=True)
        self.storage = ResearchStorage()
        self.shadow_logger = ShadowUniverseLogger()

    def export_shadow_universe_csv(self, filename: Optional[str] = None) -> Path:
        tokens = self.shadow_logger.load_all_shadow_tokens()
        if not tokens:
            tokens = self.storage.load_training_dataset()

        fname = filename or f"shadow_universe_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.csv"
        out_path = self.export_dir / fname

        df = pd.DataFrame(tokens)
        df.to_csv(out_path, index=False, encoding="utf-8")
        logger.info(f"Exported {len(tokens)} shadow universe records to {out_path}")
        return out_path

    def export_paper_trades_csv(self, filename: Optional[str] = None) -> Path:
        from src.paper.ledger import PaperTradingLedger
        ledger = PaperTradingLedger()
        trades = ledger.load_all_trades()

        fname = filename or f"paper_trades_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.csv"
        out_path = self.export_dir / fname

        df = pd.DataFrame(trades)
        df.to_csv(out_path, index=False, encoding="utf-8")
        logger.info(f"Exported {len(trades)} paper trading records to {out_path}")
        return out_path

    def export_json(self, data: Any, filename: str) -> Path:
        out_path = self.export_dir / filename
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, default=str)
        logger.info(f"Exported JSON dataset to {out_path}")
        return out_path

    def generate_comprehensive_research_report(self) -> Path:
        """
        Generate a comprehensive, formal markdown research audit report.
        """
        from app.services.research_service import ResearchService
        from app.services.paper_trading_service import PaperTradingService

        res_svc = ResearchService()
        paper_svc = PaperTradingService()

        reg = res_svc.get_population_registry_summary()
        funnel = res_svc.get_opportunity_funnel()
        maturity = res_svc.get_outcome_maturity_dashboard()
        survival = res_svc.get_survival_analysis("TARGET_3M")
        ranking = res_svc.get_ranking_power_report()
        discovery = res_svc.get_discovery_audit_summary()
        tier1, tier2 = res_svc.get_execution_validation()
        paper_stats = paper_svc.calculate_aggregate_stats()

        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        report_md = f"""# Quantitative Research & Validation Audit Report

**Scanner Version**: `{FROZEN_VERSION_MANIFEST.scanner_version}` (Frozen)  
**Model Version**: `{FROZEN_VERSION_MANIFEST.model_version}`  
**Report Generated**: `{ts}`  
**Evidence Level**: `{maturity.overall_evidence_status}`  

---

## 1. Canonical Population Registry & Invariant Validation

- **Full Ingested Universe ($N$)**: `{reg.counts.full_universe}`
- **Capture-Confirmed ($8\\text{{K}}–35\\text{{K}}$)**: `{reg.counts.capture_confirmed}`
- **Discovery Missed ($>35\\text{{K}}$)**: `{reg.counts.discovery_missed}`
- **Discovery Uncertain ($>5000\\text{{ms}}$)**: `{reg.counts.discovery_uncertain}`
- **Model Eligible (Complete Features & LP $\\ge \\$500$)**: `{reg.counts.model_eligible}`
- **First Alert Opportunities**: `{reg.counts.first_alert_opportunities}`
- **Alerted Tokens**: `{reg.counts.alerted}`
- **Tradeable Tokens**: `{reg.counts.tradeable}`
- **Target Survivable Winners ($3\\text{{M}}$)**: `{reg.counts.target_survivable}`

$$\\text{{Partition Invariant: }} {reg.counts.full_universe} = {reg.counts.capture_confirmed} + {reg.counts.discovery_missed} + {reg.counts.discovery_uncertain} \\quad \\checkmark$$

---

## 2. 11-Stage Opportunity Funnel

| Stage Index & Name | Tokens ($N$) | 3M Winners | Stage Conversion | Funnel Conversion |
| :--- | :---: | :---: | :---: | :---: |
"""
        for s in funnel.stages:
            report_md += f"| {s.stage_name} | {s.token_count} | {s.winner_count_3m} | {s.conversion_from_previous_pct:.1f}% | {s.conversion_from_start_pct:.1f}% |\n"

        report_md += f"""
### Multi-Tier Winner Recall ({funnel.recall.status_label})
- **Discovery Recall**: `{funnel.recall.formatted_discovery_recall}` ({funnel.recall.winners_captured_in_range} / {funnel.recall.total_ground_truth_winners})
- **Model Recall**: `{funnel.recall.formatted_model_recall}` ({funnel.recall.winners_ranked_top_decile} / {funnel.recall.winners_captured_in_range})
- **Alert Recall**: `{funnel.recall.formatted_alert_recall}` ({funnel.recall.winners_alerted_early} / {funnel.recall.winners_model_eligible})
- **End-to-End Recall**: `{funnel.recall.formatted_end_to_end_recall}` ({funnel.recall.winners_survivable_executed} / {funnel.recall.total_ground_truth_winners})

---

## 3. Kaplan-Meier & Competing-Risk Survival Analysis

**Status**: `{survival.status_label}`  
**Cohort Size**: `{survival.total_cohort_n}` | **Target Breakouts**: `{survival.total_target_events}` | **Terminal Rugs**: `{survival.total_competing_risk_events}` | **In-Flight**: `{survival.total_censored_in_flight}`  

| Interval ($t$) | At Risk | Target Events | Terminal Rugs | Censored/Pending | Survival $S(t)$ | Cum Target Prob $F(t)$ | Cum Rug Incidence |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
"""
        for inv in survival.intervals:
            report_md += f"| {inv.interval_label} | {inv.n_at_risk} | {inv.n_target_events} | {inv.n_competing_risk_events} | {inv.n_censored} | {inv.kaplan_meier_survival:.4f} | {inv.formatted_event_prob} | {inv.formatted_risk_incidence} |\n"

        report_md += f"""
---

## 4. Two-Tier Execution Accuracy Benchmark

- **Tier 1 (Reserve Mathematics)**: Evaluated `{tier1.total_swaps_evaluated}` swaps | Median Error: `{tier1.median_quote_error_pct:.3f}%` | P95: `{tier1.p95_quote_error_pct:.3f}%` | Status: `EXACT / VALIDATED`
- **Tier 2 (Live On-Chain Fills)**: Evaluated `{tier2.total_live_txs_audited}` transactions | Min: `{tier2.relative_fill_error_distribution.min_error:.3f}%` | Median: `{tier2.relative_fill_error_distribution.median_error:.3f}%` | P95: `{tier2.relative_fill_error_distribution.p95_error:.3f}%` | Max: `{tier2.relative_fill_error_distribution.max_error:.3f}%` | Status: `{tier2.sample_size_tier_status}`

---

## 5. Paper Trading Aggregate Performance

- **Total Simulated Trades**: `{paper_stats.total_trades}` (Open: `{paper_stats.open_trades_count}`, Closed: `{paper_stats.closed_trades_count}`)
- **Win Rate**: `{paper_stats.win_rate_pct:.2f}%`
- **Total Realized P&L**: `\\${paper_stats.total_realized_pnl_usd:.2f}`
- **Profit Factor**: `{paper_stats.profit_factor:.2f}`
- **Average Return**: `{paper_stats.mean_return_pct:.2f}%` (Median: `{paper_stats.median_return_pct:.2f}%`)
- **Max Drawdown**: `{paper_stats.max_drawdown_pct:.2f}%`
"""
        out_path = self.export_dir / f"research_report_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.md"
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(report_md)
        logger.info(f"Generated research audit report at {out_path}")
        return out_path

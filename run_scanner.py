"""
Gem Detector - Research-Grade CLI Entry Point
Usage:
    python run_scanner.py
    python run_scanner.py --preset high_conviction
    python run_scanner.py --once
    python run_scanner.py --train-model
    python run_scanner.py --backtest
"""

import argparse
import asyncio
import logging
from pathlib import Path
import sys
from typing import Any, Dict

# Ensure project root is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent))

# Ensure Windows stdout/stderr supports UTF-8 Unicode emojis
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from src.config import load_config
from src.main import GemDetectorEngine
from src.models.train import TemporalWalkForwardTrainer


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="💎 Research-Grade Sub-$10K to $3M+ Breakout Scanner & Predictive Radar",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument(
        "--preset",
        type=str,
        default=None,
        help="Strategy preset: 'microcap_sniper', 'momentum_breakout', 'high_conviction', 'bnb_breakout'",
    )
    parser.add_argument(
        "--chain",
        type=str,
        nargs="+",
        default=None,
        help="Chains to scan: e.g. solana bsc",
    )
    parser.add_argument(
        "--min-mc",
        type=float,
        default=None,
        help="Minimum market cap in USD (default 8000)",
    )
    parser.add_argument(
        "--max-mc",
        type=float,
        default=None,
        help="Maximum market cap in USD (default 50000)",
    )
    parser.add_argument(
        "--min-score",
        type=float,
        default=None,
        help="Minimum model score threshold for alerts (default 75)",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=None,
        help="Scan poll interval in seconds (default 10)",
    )
    parser.add_argument(
        "--once",
        "--snapshot",
        action="store_true",
        help="Run a single scan cycle, output quantitative radar to console, and exit",
    )
    parser.add_argument(
        "--model-mode",
        type=str,
        choices=["calibrated", "baseline"],
        default="calibrated",
        help="Model predictor mode: 'calibrated' (ML probabilities) or 'baseline' (Rule score)",
    )
    parser.add_argument(
        "--train-model",
        action="store_true",
        help="Execute temporal walk-forward model training and output performance report",
    )
    parser.add_argument(
        "--backtest",
        action="store_true",
        help="Execute historical point-in-time backtest and output validation metrics",
    )
    parser.add_argument(
        "--tournament",
        action="store_true",
        help="Execute 7-model baseline tournament and output leaderboard",
    )
    parser.add_argument(
        "--lineage-audit",
        action="store_true",
        help="Execute data lineage and timestamp audit on stored dataset",
    )
    parser.add_argument(
        "--paper-ledger",
        action="store_true",
        help="View persistent paper-trading execution ledger from SQLite",
    )
    parser.add_argument(
        "--drift-check",
        action="store_true",
        help="Audit calibration drift and reliability on latest closed paper trades",
    )
    parser.add_argument(
        "--position-size",
        type=float,
        default=250.0,
        help="Position size in USD for AMM slippage simulation (default $250)",
    )
    parser.add_argument(
        "--telegram-token",
        type=str,
        default=None,
        help="Telegram bot token for instant breakout alerts",
    )
    parser.add_argument(
        "--shadow-universe",
        action="store_true",
        help="Inspect recorded shadow universe population denominator",
    )
    parser.add_argument(
        "--ranking-lift",
        action="store_true",
        help="Audit ranking power and selection lift over base rate across percentiles",
    )
    parser.add_argument(
        "--opportunity-funnel",
        action="store_true",
        help="Audit 8-stage opportunity funnel and winner recall metrics",
    )
    parser.add_argument(
        "--onchain-fills",
        action="store_true",
        help="Audit Tier 2 live on-chain fill execution accuracy",
    )
    parser.add_argument(
        "--discovery-causes",
        action="store_true",
        help="Audit 11 discovery failure cause breakdown for MISSED/UNCERTAIN tokens",
    )
    parser.add_argument(
        "--age-cohorts",
        action="store_true",
        help="Evaluate performance stratified across discovery age cohorts",
    )
    parser.add_argument(
        "--outcome-maturity",
        action="store_true",
        help="Audit canonical outcome maturity across evaluation horizons (15m, 1h, 6h, 24h, 7d, eventual)",
    )
    parser.add_argument(
        "--target-matrix",
        action="store_true",
        help="Audit 4x7 multi-target x multi-horizon empirical success rate matrix",
    )
    parser.add_argument(
        "--survival-analysis",
        action="store_true",
        help="Execute Kaplan-Meier and Competing Risks Survival Analysis for breakout targets",
    )
    parser.add_argument(
        "--discovery-audit",
        action="store_true",
        help="Audit discovery-capture and ingestion telemetry latency inside $8K-$35K",
    )
    parser.add_argument(
        "--execution-audit",
        action="store_true",
        help="Audit execution quote errors (Median & P95) against on-chain swap math",
    )
    parser.add_argument(
        "--opportunity-windows",
        action="store_true",
        help="Analyze speed of breakout (FAST_WIN to EVENTUAL_WIN)",
    )
    parser.add_argument(
        "--checkpoints",
        action="store_true",
        help="Evaluate automated validation milestone checkpoints (N=25, 50, 100, 250, 500)",
    )
    parser.add_argument(
        "--telegram-chat",
        type=str,
        default=None,
        help="Telegram chat ID for instant breakout alerts",
    )
    parser.add_argument(
        "--discord-webhook",
        type=str,
        default=None,
        help="Discord webhook URL for instant breakout alerts",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable detailed debug logging",
    )
    return parser.parse_args()


async def main_async() -> None:
    args = parse_args()

    # Logging setup
    log_level = logging.DEBUG if args.debug else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    if args.shadow_universe:
        from src.research.shadow import ShadowUniverseLogger
        logger_shadow = ShadowUniverseLogger()
        tokens = logger_shadow.load_all_shadow_tokens()
        print(f"\n[+] TRUE SHADOW UNIVERSE ({len(tokens)} tokens recorded in denominator)")
        for t in tokens[-15:]:
            print(f" - {t.get('symbol')} ({t.get('chain')}/{t.get('venue')}) @ ${t.get('market_cap_usd'):,.0f} MC | Age: {t.get('token_age_minutes', 0):.1f}m | State: {t.get('signal_state')} | P(3M): {t.get('p_reach_3m'):.1%}")
        return

    if args.discovery_audit:
        from src.research.discovery_audit import DiscoveryCaptureAuditor
        from src.research.shadow import ShadowUniverseLogger
        logger_shadow = ShadowUniverseLogger()
        tokens = logger_shadow.load_all_shadow_tokens()
        auditor = DiscoveryCaptureAuditor()
        summary = auditor.audit_ingestion_population(tokens)
        print(f"\n[+] DISCOVERY-CAPTURE & INGESTION LATENCY AUDIT")
        print(f"Total Evaluated Tokens: {summary.total_tokens_evaluated}")
        print(f"Universe Capture Rate: {summary.universe_capture_rate_pct:.2f}%")
        print(f"Captured: {summary.discovery_captured_count} | Late: {summary.discovery_late_count} | Missed: {summary.discovery_missed_count} | Uncertain: {summary.discovery_uncertain_count}")
        print(f"Median Time In Window: {summary.median_time_in_range_sec:.1f}s | Median RPC Latency: {summary.median_rpc_latency_ms:.1f}ms | Median WS Latency: {summary.median_websocket_latency_ms:.1f}ms")
        return

    if args.execution_audit:
        from src.research.execution_validation import ExecutionQuoteValidator
        validator = ExecutionQuoteValidator()
        report = validator.validate_quotes()
        print(f"\n[+] EXECUTION QUOTE ACCURACY BENCHMARK")
        print(f"Swaps Evaluated: {report.total_swaps_evaluated}")
        print(f"Median Quote Error: {report.median_quote_error_pct:.3f}%")
        print(f"P95 Quote Error: {report.p95_quote_error_pct:.3f}%")
        print(f"Max Quote Error: {report.max_quote_error_pct:.3f}%")
        print(f"Median Price Impact Error: {report.median_impact_error_pct:.3f}%")
        print(f"Execution Model Validated: {report.is_execution_model_validated}")
        return

    if args.opportunity_windows:
        from src.research.opportunity_window import OpportunityWindowAnalyzer
        from src.research.shadow import ShadowUniverseLogger
        logger_shadow = ShadowUniverseLogger()
        tokens = logger_shadow.load_all_shadow_tokens()
        opp_rep = OpportunityWindowAnalyzer.analyze_opportunities(tokens)
        print(f"\n[+] OPPORTUNITY WINDOW SPEED ANALYSIS (Total 3M Winners: {opp_rep.total_3m_winners})")
        print(f"FAST_WIN (<15m): {opp_rep.fast_win_count}")
        print(f"EARLY_WIN (15m-1h): {opp_rep.early_win_count}")
        print(f"SLOW_WIN (1h-6h): {opp_rep.slow_win_count}")
        print(f"LATE_WIN (6h-24h): {opp_rep.late_win_count}")
        print(f"EVENTUAL_WIN (>24h): {opp_rep.eventual_win_count}")
        print(f"Median Time to Target: {opp_rep.median_time_to_target_min:.1f} min")
        return

    if args.checkpoints:
        from src.research.checkpoints import LiveMilestoneTracker
        from src.research.shadow import ShadowUniverseLogger
        logger_shadow = ShadowUniverseLogger()
        tokens = logger_shadow.load_all_shadow_tokens()
        tracker = LiveMilestoneTracker()
        cp = tracker.evaluate_checkpoints(tokens)
        print(f"\n[+] VALIDATION MILESTONES CHECK")
        print(f"Current Shadow Tokens: {len(tokens)}")
        if cp:
            print(f"Milestone N={cp.milestone_n} Triggered! Precision@10: {cp.precision_at_10_pct:.2f}% | Capture Rate: {cp.universe_capture_rate_pct:.1f}%")
        else:
            print(f"Next Milestones: {LiveMilestoneTracker.MILESTONES}")
        return

    if args.opportunity_funnel:
        from src.research.opportunity_funnel import OpportunityFunnelAuditor
        from src.research.shadow import ShadowUniverseLogger
        logger_shadow = ShadowUniverseLogger()
        tokens = logger_shadow.load_all_shadow_tokens()
        funnel_rep = OpportunityFunnelAuditor.audit_funnel(tokens)
        print(f"\n[+] CANONICAL 11-STAGE OPPORTUNITY FUNNEL (Total Discovered: {funnel_rep.total_initial_candidates})")
        for stg in funnel_rep.stages:
            print(f" {stg.stage_name:26s} | Tokens: {stg.token_count:3d} | 3M Winners: {stg.winner_count_3m:2d} | Conversion: {stg.conversion_from_previous_pct:5.1f}% (Funnel: {stg.conversion_from_start_pct:5.1f}%)")
        rec = funnel_rep.recall
        print(f"\n[+] WINNER RECALL DECOMPOSITION ({rec.status_label})")
        print(f" Discovery Recall:  {rec.formatted_discovery_recall} ({rec.winners_captured_in_range} / {rec.total_ground_truth_winners})")
        print(f" Model Recall:      {rec.formatted_model_recall} ({rec.winners_ranked_top_decile} / {rec.winners_captured_in_range})")
        print(f" Alert Recall:      {rec.formatted_alert_recall} ({rec.winners_alerted_early} / {rec.winners_model_eligible})")
        print(f" End-to-End Recall: {rec.formatted_end_to_end_recall} ({rec.winners_survivable_executed} / {rec.total_ground_truth_winners})")
        return

    if args.onchain_fills:
        from src.research.onchain_fill_validation import LiveOnChainFillValidator
        validator = LiveOnChainFillValidator()
        report = validator.audit_live_fills()
        print(f"\n[+] TIER 2: LIVE ON-CHAIN FILL VALIDATION BENCHMARK")
        print(f"Txs Audited: {report.total_live_txs_audited}")
        print(f"Median Fill Error: {report.median_fill_error_pct:.3f}%")
        print(f"P95 Fill Error: {report.p95_fill_error_pct:.3f}%")
        print(f"Max Fill Error: {report.max_fill_error_pct:.3f}%")
        print(f"Median Price Impact Error: {report.median_price_impact_error_pct:.3f}%")
        print(f"Fill Accuracy Validated: {report.is_live_fill_accuracy_validated}")
        return

    if args.discovery_causes:
        from src.research.discovery_audit import DiscoveryCaptureAuditor
        from src.research.shadow import ShadowUniverseLogger
        logger_shadow = ShadowUniverseLogger()
        tokens = logger_shadow.load_all_shadow_tokens()
        auditor = DiscoveryCaptureAuditor()
        summary = auditor.audit_ingestion_population(tokens)
        print(f"\n[+] DISCOVERY FAILURE CAUSE BREAKDOWN ({summary.discovery_late_count + summary.discovery_missed_count + summary.discovery_uncertain_count} total failures)")
        for fc in summary.failure_causes:
            print(f" - {fc.cause_code:28s} | Affected: {fc.count:2d} ({fc.percentage:4.1f}%) | Latency: {fc.median_latency_ms:5.1f}ms | Time Lost: {fc.median_time_lost_sec:4.1f}s")
        return

    if args.outcome_maturity:
        from src.research.outcome_maturity import CanonicalOutcomeMaturityEngine
        from src.research.shadow import ShadowUniverseLogger
        logger_shadow = ShadowUniverseLogger()
        tokens = logger_shadow.load_all_shadow_tokens()
        dash = CanonicalOutcomeMaturityEngine.build_dashboard_and_matrix(tokens)
        print(f"\n[+] TARGET 3M OUTCOME MATURITY DASHBOARD ({dash.overall_evidence_status})")
        print(f"Total Evaluated: {dash.total_tokens_evaluated}")
        for r in dash.horizon_summary_rows:
            print(f" - {r.horizon_name:8s} | Mature: {r.n_mature:2d} | Pending: {r.n_pending:2d} | Censored: {r.n_censored:2d} | Success: {r.n_success:2d} | Failure: {r.n_failure:2d} | Rate: {r.formatted_success_rate}")
        return

    if args.target_matrix:
        from src.research.outcome_maturity import CanonicalOutcomeMaturityEngine
        from src.research.shadow import ShadowUniverseLogger
        logger_shadow = ShadowUniverseLogger()
        tokens = logger_shadow.load_all_shadow_tokens()
        dash = CanonicalOutcomeMaturityEngine.build_dashboard_and_matrix(tokens)
        print(f"\n[+] 4x6 MULTI-TARGET x MULTI-HORIZON EMPIRICAL MATRIX")
        for r in dash.matrix_rows:
            print(f" - {r.target_name:12s} ({r.horizon_name:8s}) | Mature: {r.n_mature:2d} | Pending: {r.n_pending:2d} | Success: {r.n_success:2d} | Failure: {r.n_failure:2d} | Rate: {r.formatted_success_rate}")
        return

    if args.survival_analysis:
        from src.research.shadow import ShadowUniverseLogger
        from src.research.survival_analysis import SurvivalAnalysisEngine
        logger_shadow = ShadowUniverseLogger()
        tokens = logger_shadow.load_all_shadow_tokens()
        rep = SurvivalAnalysisEngine.analyze_survival(tokens, target_name="TARGET_3M")
        print(f"\n[+] KAPLAN-MEIER & COMPETING RISKS SURVIVAL ANALYSIS ({rep.status_label})")
        print(f"Cohort Size: {rep.total_cohort_n} | Target Events: {rep.total_target_events} | Terminal Rugs: {rep.total_competing_risk_events} | Censored/In-Flight: {rep.total_censored_in_flight}")
        for inv in rep.intervals:
            print(f" - {inv.interval_label:6s} | At Risk: {inv.n_at_risk:2d} | Target Events: {inv.n_target_events:2d} | Rug Events: {inv.n_competing_risk_events:2d} | Censored: {inv.n_censored:2d} | Survival S(t): {inv.kaplan_meier_survival:.4f} | Cum Prob: {inv.formatted_event_prob} | Rug Inc: {inv.formatted_risk_incidence}")
        return

    if args.ranking_lift or args.age_cohorts:
        from backtest_scanner import ComprehensiveBacktester
        backtester = ComprehensiveBacktester(use_ml=(args.model_mode == "calibrated"))
        report, exec_res, tournament, lineage, drift, policies, multi_ranking, cohorts, discovery, exec_val, onchain_fills, opp_win, opp_funnel, maturity_dash, survival_rep = backtester.run_backtest(position_size=args.position_size)
        backtester.print_comprehensive_report(report, exec_res, tournament, lineage, drift, policies, multi_ranking, cohorts, discovery, exec_val, onchain_fills, opp_win, opp_funnel, maturity_dash, survival_rep, position_size=args.position_size)
        return

    if args.paper_ledger:
        from src.paper.ledger import PaperTradingLedger
        ledger = PaperTradingLedger()
        trades = ledger.load_all_trades()
        print(f"\n[+] LIVE PAPER-TRADING LEDGER ({len(trades)} trades recorded)")
        for t in trades[-15:]:
            status = t.get("status", "OPEN")
            pnl = t.get("net_realized_pnl_usd", 0.0) or 0.0
            pnl_str = f"+${pnl:.2f}" if pnl >= 0 else f"-${abs(pnl):.2f}"
            print(f" - [{status}] {t.get('symbol')} ({t.get('venue')}) @ ${t.get('market_cap_usd'):,.0f} MC | Fill: ${t.get('simulated_fill_price_usd'):.6f} | P(3M): {t.get('p_reach_3m'):.1%} | Exit: {t.get('exit_reason')} | PnL: {pnl_str} ({t.get('outcome_label')})")
        return

    if args.drift_check:
        from src.paper.drift_monitor import CalibrationDriftMonitor
        monitor = CalibrationDriftMonitor()
        report = monitor.audit_drift(batch_size=100)
        print(f"\n[+] CALIBRATION DRIFT AUDIT REPORT")
        print(f"Sample Size: {report.sample_size} trades ({report.unique_tokens} unique tokens)")
        print(f"Guardrail Status: {report.sample_guardrail_status}")
        print(f"Empirical Breakout Rate: {report.empirical_success_rate:.2%}")
        print(f"Mean Predicted Probability: {report.mean_predicted_prob:.2%}")
        print(f"Probability Bias: {report.probability_bias:+.2%}")
        print(f"Expected Calibration Error (ECE): {report.expected_calibration_error:.4f}")
        print(f"Status: {report.drift_status}")
        for alert in report.alerts:
            print(f" ⚠️  {alert}")
        return

    if args.lineage_audit:
        from src.research.lineage import DataLineageAuditor
        from src.research.storage import ResearchStorage
        storage = ResearchStorage()
        records = storage.load_training_dataset()
        report = DataLineageAuditor.audit_dataset(records, is_synthetic=len(records) < 10)
        print(f"\n[+] DATA LINEAGE AUDIT REPORT")
        print(f"Dataset Provenance: {report.dataset_type}")
        print(f"Total Unique Tokens: {report.total_tokens}")
        print(f"Total Snapshots: {report.total_snapshots}")
        print(f"Population Base Rate: {report.base_rate_3m:.2%}")
        print(f"Zero Timestamp Leakage: {report.is_valid_leakage_free}")
        for note in report.audit_notes:
            print(f" - {note}")
        return

    if args.tournament:
        from backtest_scanner import ComprehensiveBacktester
        backtester = ComprehensiveBacktester(use_ml=(args.model_mode == "calibrated"))
        report, exec_res, tournament, lineage, drift, policies, multi_ranking, cohorts, discovery, exec_val, onchain_fills, opp_win, opp_funnel = backtester.run_backtest(position_size=args.position_size)
        backtester.print_comprehensive_report(report, exec_res, tournament, lineage, drift, policies, multi_ranking, cohorts, discovery, exec_val, onchain_fills, opp_win, opp_funnel, position_size=args.position_size)
        return

    if args.train_model:
        print("\n[+] Running Temporal Walk-Forward Model Training & Calibration Pipeline...")
        trainer = TemporalWalkForwardTrainer()
        report = trainer.train_and_evaluate()
        print(f"\nModel: {report.model_name}")
        print(f"Sample Size: N={report.sample_size} (Unique Tokens: {report.unique_token_count})")
        print(f"Primary Precision@10: {report.precision_at_10:.2%}")
        print(f"Wilson 95% CI: [{report.primary_precision_wilson_ci_95[0]:.2%}, {report.primary_precision_wilson_ci_95[1]:.2%}]")
        print(f"Exact 95% CI: [{report.primary_precision_exact_ci_95[0]:.2%}, {report.primary_precision_exact_ci_95[1]:.2%}]")
        print(f"PR-AUC: {report.pr_auc:.4f} | ROC-AUC: {report.roc_auc:.4f}")
        print(f"ML Brier Score: {report.brier_score_ml:.5f} (Prevalence Baseline: {report.brier_prevalence_baseline:.5f})")
        print(f"Brier Skill Score: {report.brier_skill_score_pct:+.2f}%")
        print(f"Expected Calibration Error (ECE): {report.expected_calibration_error:.4f}")
        print(f"Base Rate Lift ($3M Target): {report.base_rate_lift_3m:.2f}x")
        return

    if args.backtest:
        from backtest_scanner import ComprehensiveBacktester
        backtester = ComprehensiveBacktester(use_ml=(args.model_mode == "calibrated"))
        report, exec_res, tournament, lineage, drift, policies, multi_ranking, cohorts, discovery, exec_val, onchain_fills, opp_win, opp_funnel = backtester.run_backtest(position_size=args.position_size)
        backtester.print_comprehensive_report(report, exec_res, tournament, lineage, drift, policies, multi_ranking, cohorts, discovery, exec_val, onchain_fills, opp_win, opp_funnel, position_size=args.position_size)
        return

    # Build overrides dictionary
    overrides: Dict[str, Any] = {}
    if args.chain:
        overrides.setdefault("scanner", {})["active_chains"] = [c.lower() for c in args.chain]
    if args.interval:
        overrides.setdefault("scanner", {})["poll_interval_sec"] = args.interval
    if args.min_mc is not None:
        overrides.setdefault("filters", {})["min_market_cap_usd"] = args.min_mc
    if args.max_mc is not None:
        overrides.setdefault("filters", {})["max_market_cap_usd"] = args.max_mc
    if args.min_score is not None:
        overrides.setdefault("scoring", {})["alert_score_threshold"] = args.min_score

    if args.telegram_token and args.telegram_chat:
        overrides.setdefault("alerts", {}).setdefault("telegram", {})["enabled"] = True
        overrides["alerts"]["telegram"]["bot_token"] = args.telegram_token
        overrides["alerts"]["telegram"]["chat_id"] = args.telegram_chat

    if args.discord_webhook:
        overrides.setdefault("alerts", {}).setdefault("discord", {})["enabled"] = True
        overrides["alerts"]["discord"]["webhook_url"] = args.discord_webhook

    # Load configuration
    config = load_config(
        settings_path="config/settings.yaml",
        presets_path="config/presets.yaml",
        preset=args.preset,
        overrides=overrides if overrides else None,
    )

    engine = GemDetectorEngine(config, use_calibrated_ml=(args.model_mode == "calibrated"))
    try:
        await engine.run(single_shot=args.once)
    except (KeyboardInterrupt, asyncio.CancelledError):
        print("\n[!] Scanner stopped by user.")


def main() -> None:
    try:
        asyncio.run(main_async())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()

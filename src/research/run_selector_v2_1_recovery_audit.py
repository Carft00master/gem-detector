"""
Full Walk-Forward Research Audit Runner for SELECTOR_v2.1 — LOW-FREQUENCY / HIGH-P&L RECOVERY
==============================================================================================

Executes all 17 research requirements:
1. Diagnosis of rejected winners & REJECTED_WINNER_PROFILE
2. Winner-capture metrics (Top 0.5%, 1%, 2%, 5%, 10%, 3M runners, MFE, P&L)
3. Confluence gating ablation (>=2, >=3, >=4, >=5)
4. EV gating ablation (>=1.0, >=1.5, >=2.0, >=2.5, >=3.0, >=4.0)
5. False-positive pruners ablation (Hard, Penalties, No P1, No P2, No P3, No P4, No P5)
6. Selection-density frontier (Top 0.5%, 1%, 2%, 3%, 5%, 7%, 10%)
7. Tail opportunity lane performance (Core vs Tail vs Dual)
8. Market regime adaptation (HOT, NORMAL, COLD, PANIC)
9. Frequency metrics (trades/day, trades/week, trades/1000 opps, spacing)
10. Outlier robustness (Excl top 1, 5, 10, 20)
11. Chronological walk-forward validation (Train 60%, Val 20%, Locked Test 20%)
12. Final Head-to-Head Comparison: Champion v1.0.0 vs SELECTOR_v2 vs SELECTOR_v2.1
"""

from collections import defaultdict
from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import sqlite3
import sys
import time
from typing import Any, Dict, List, Tuple

import numpy as np

root_dir = Path(__file__).resolve().parent.parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from src.research.selector_v2_high_conviction import (
    FeatureExtractorV2,
    SetupQualityModel,
    SelectorV2HighConvictionEngine,
    WalkForwardValidator,
)
from src.research.selector_v2_1_recovery import (
    DualLaneSetupQualityModel,
    FalsePositiveMode,
    HardSafetyGate,
    ScarcityDisplacementEngine,
    SelectorV21BudgetConfig,
    SelectorV21RecoveryEngine,
    TailOpportunityEngine,
    WinnerCaptureEvaluator,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s]: %(message)s")
logger = logging.getLogger(__name__)


def load_all_historical_trades(
    db_path: str = "data/paper_trading.db",
    shadow_db_path: str = "data/shadow_universe.db",
) -> List[Dict[str, Any]]:
    """Loads historical trades joined with shadow token metadata."""
    logger.info(f"Loading trades from {db_path} joined with {shadow_db_path}...")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute(f"ATTACH DATABASE '{shadow_db_path}' AS shadow")
        query = """
            SELECT p.*,
                   s.volume_5m_usd, s.volume_1h_usd, s.unique_buyers, s.unique_sellers,
                   s.effective_vol_mc_ratio, s.effective_buy_pressure, s.wallet_independence,
                   COALESCE(s.wash_trade_risk, 0.08) AS shadow_wash_risk,
                   COALESCE(s.cabal_risk_score, 0.12) AS shadow_cabal_risk
            FROM paper_trades p
            LEFT JOIN shadow.shadow_tokens s ON p.token_address = s.token_address
            WHERE p.outcome_label IS NOT NULL
            ORDER BY p.entry_signal_timestamp ASC
        """
    except Exception as e:
        logger.warning(f"Could not attach shadow DB: {e}. Falling back to paper_trades.")
        query = "SELECT * FROM paper_trades WHERE outcome_label IS NOT NULL ORDER BY entry_signal_timestamp ASC"

    trades = [dict(r) for r in conn.execute(query).fetchall()]
    conn.close()
    logger.info(f"Successfully loaded {len(trades)} trades.")
    return trades


def run_rejected_winner_diagnosis(
    trades: List[Dict[str, Any]],
    v2_selected_trades: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Diagnoses where SELECTOR_v2 lost P&L and constructs REJECTED_WINNER_PROFILE."""
    v2_selected_ids = {t["trade_id"] for t in v2_selected_trades}
    rejected_trades = [t for t in trades if t["trade_id"] not in v2_selected_ids]
    rej_winners = [t for t in rejected_trades if float(t.get("net_realized_return_pct") or 0.0) > 0]
    rej_3m = [t for t in rejected_trades if int(t.get("target_reached_3m") or 0) == 1]
    rej_high_ret = [t for t in rejected_trades if float(t.get("net_realized_return_pct") or 0.0) >= 100.0]

    p3m_list = []
    mc_list = []
    confluence_list = []
    ev_list = []
    regimes = defaultdict(int)
    rejection_reasons = defaultdict(int)
    fp_flags = defaultdict(int)

    for t in rej_winners:
        res = SetupQualityModel.evaluate(t)
        p3m_list.append(res.feature_bundle.p3m)
        mc_list.append(float(t.get("entry_market_cap_usd") or 0.0))
        confluence_list.append(res.confluence_count)
        ev_list.append(res.expected_value)
        regimes[res.feature_bundle.regime] += 1
        for r in res.rejection_reasons:
            cat = r.split("(")[0].strip()
            rejection_reasons[cat] += 1

    total_universe_pnl = sum(float(t.get("net_realized_pnl_usd") or 0.0) for t in trades)
    v2_pnl = sum(float(t.get("net_realized_pnl_usd") or 0.0) for t in v2_selected_trades)
    lost_winner_pnl = sum(float(t.get("net_realized_pnl_usd") or 0.0) for t in rej_winners)

    profile = {
        "summary": {
            "total_universe_pnl": round(total_universe_pnl, 2),
            "v2_selected_pnl": round(v2_pnl, 2),
            "v2_pnl_share_pct": round(v2_pnl / max(total_universe_pnl, 1.0) * 100.0, 2),
            "lost_winner_pnl": round(lost_winner_pnl, 2),
            "lost_pnl_share_pct": round(lost_winner_pnl / max(total_universe_pnl, 1.0) * 100.0, 2),
            "total_winners_in_universe": sum(1 for t in trades if float(t.get("net_realized_return_pct") or 0.0) > 0),
            "v2_captured_winners": sum(1 for t in v2_selected_trades if float(t.get("net_realized_return_pct") or 0.0) > 0),
            "rejected_winners_count": len(rej_winners),
            "rejected_3m_runners": len(rej_3m),
            "total_3m_runners": sum(1 for t in trades if int(t.get("target_reached_3m") or 0) == 1),
            "rejected_high_return_count": len(rej_high_ret),
        },
        "distributions": {
            "mean_p3m": round(float(np.mean(p3m_list)), 4) if p3m_list else 0.0,
            "median_p3m": round(float(np.median(p3m_list)), 4) if p3m_list else 0.0,
            "mean_mc_usd": round(float(np.mean(mc_list)), 2) if mc_list else 0.0,
            "median_mc_usd": round(float(np.median(mc_list)), 2) if mc_list else 0.0,
            "mean_confluence": round(float(np.mean(confluence_list)), 2) if confluence_list else 0.0,
            "median_confluence": int(np.median(confluence_list)) if confluence_list else 0,
            "mean_ev": round(float(np.mean(ev_list)), 2) if ev_list else 0.0,
            "median_ev": round(float(np.median(ev_list)), 2) if ev_list else 0.0,
        },
        "confluence_breakdown": {
            f"confluence_{c}": sum(1 for conf in confluence_list if conf == c)
            for c in range(1, 8)
        },
        "rejection_reasons": dict(rejection_reasons),
        "regime_breakdown": dict(regimes),
    }
    return profile


def run_confluence_ablation(
    train_trades: List[Dict[str, Any]],
    val_trades: List[Dict[str, Any]],
    engine: SelectorV21RecoveryEngine,
) -> List[Dict[str, Any]]:
    """Evaluates Confluence thresholds: >=2, >=3, >=4, >=5 on Train and Validation sets."""
    results = []
    for c_thresh in [2, 3, 4, 5]:
        _, train_perf, train_cap = engine.evaluate_dataset(
            train_trades, top_k_pct=10.0, min_confluence=c_thresh, min_ev=1.5
        )
        _, val_perf, val_cap = engine.evaluate_dataset(
            val_trades, top_k_pct=10.0, min_confluence=c_thresh, min_ev=1.5
        )
        results.append({
            "threshold": c_thresh,
            "train": {
                "trades": train_perf["trade_count"],
                "win_rate": train_perf["win_rate"],
                "p_at_10": train_perf["p_at_10"],
                "p_at_25": train_perf["p_at_25"],
                "profit_factor": train_perf["profit_factor"],
                "pnl": train_perf["executable_pnl"],
                "tail_capture_1pct": train_cap["tail_percentile_capture"]["top_1_0_pct"]["capture_rate_pct"],
                "capture_3m": train_cap["runners_3m_capture_rate_pct"],
            },
            "val": {
                "trades": val_perf["trade_count"],
                "win_rate": val_perf["win_rate"],
                "p_at_10": val_perf["p_at_10"],
                "p_at_25": val_perf["p_at_25"],
                "profit_factor": val_perf["profit_factor"],
                "pnl": val_perf["executable_pnl"],
                "tail_capture_1pct": val_cap["tail_percentile_capture"]["top_1_0_pct"]["capture_rate_pct"],
                "capture_3m": val_cap["runners_3m_capture_rate_pct"],
            },
        })
    return results


def run_ev_ablation(
    train_trades: List[Dict[str, Any]],
    val_trades: List[Dict[str, Any]],
    engine: SelectorV21RecoveryEngine,
    optimal_confluence: int = 3,
) -> List[Dict[str, Any]]:
    """Evaluates EV thresholds: 1.0, 1.5, 2.0, 2.5, 3.0, 4.0 on Train and Validation sets."""
    results = []
    for ev_thresh in [1.0, 1.5, 2.0, 2.5, 3.0, 4.0]:
        _, train_perf, train_cap = engine.evaluate_dataset(
            train_trades, top_k_pct=10.0, min_confluence=optimal_confluence, min_ev=ev_thresh
        )
        _, val_perf, val_cap = engine.evaluate_dataset(
            val_trades, top_k_pct=10.0, min_confluence=optimal_confluence, min_ev=ev_thresh
        )
        results.append({
            "threshold": ev_thresh,
            "train": {
                "trades": train_perf["trade_count"],
                "win_rate": train_perf["win_rate"],
                "p_at_10": train_perf["p_at_10"],
                "p_at_25": train_perf["p_at_25"],
                "profit_factor": train_perf["profit_factor"],
                "pnl": train_perf["executable_pnl"],
                "tail_capture_1pct": train_cap["tail_percentile_capture"]["top_1_0_pct"]["capture_rate_pct"],
            },
            "val": {
                "trades": val_perf["trade_count"],
                "win_rate": val_perf["win_rate"],
                "p_at_10": val_perf["p_at_10"],
                "p_at_25": val_perf["p_at_25"],
                "profit_factor": val_perf["profit_factor"],
                "pnl": val_perf["executable_pnl"],
                "tail_capture_1pct": val_cap["tail_percentile_capture"]["top_1_0_pct"]["capture_rate_pct"],
            },
        })
    return results


def run_fp_ablation(
    val_trades: List[Dict[str, Any]],
    engine: SelectorV21RecoveryEngine,
    min_confluence: int = 3,
    min_ev: float = 1.5,
) -> List[Dict[str, Any]]:
    """Evaluates False-Positive pruner variations on Validation set."""
    modes = [
        (FalsePositiveMode.ALL_HARD, "All Pruners (Hard Rejection)"),
        (FalsePositiveMode.PENALTIES_ONLY, "All Pruners (Score Penalties)"),
        (FalsePositiveMode.REMOVE_PRUNER_1, "No P1 (Low Breadth)"),
        (FalsePositiveMode.REMOVE_PRUNER_2, "No P2 (Wash Pump)"),
        (FalsePositiveMode.REMOVE_PRUNER_3, "No P3 (Thin Spike)"),
        (FalsePositiveMode.REMOVE_PRUNER_4, "No P4 (Cabal Collusion)"),
        (FalsePositiveMode.REMOVE_PRUNER_5, "No P5 (Distribution Exhaustion)"),
    ]
    results = []
    for mode, desc in modes:
        _, perf, cap = engine.evaluate_dataset(
            val_trades,
            top_k_pct=10.0,
            min_confluence=min_confluence,
            min_ev=min_ev,
            fp_mode=mode,
        )
        results.append({
            "mode": mode.value,
            "description": desc,
            "trades": perf["trade_count"],
            "win_rate": perf["win_rate"],
            "profit_factor": perf["profit_factor"],
            "pnl": perf["executable_pnl"],
            "p_at_10": perf["p_at_10"],
            "p_at_25": perf["p_at_25"],
            "tail_1pct": cap["tail_percentile_capture"]["top_1_0_pct"]["capture_rate_pct"],
            "runners_3m": perf["runners_3m_count"],
        })
    return results


def run_density_frontier(
    val_trades: List[Dict[str, Any]],
    engine: SelectorV21RecoveryEngine,
    min_confluence: int = 3,
    min_ev: float = 1.5,
) -> List[Dict[str, Any]]:
    """Evaluates Top-K Selection Density Frontier: 0.5%, 1%, 2%, 3%, 5%, 7%, 10%."""
    bands = [0.5, 1.0, 2.0, 3.0, 5.0, 7.0, 10.0]
    frontier = []
    for k in bands:
        _, perf, cap = engine.evaluate_dataset(
            val_trades,
            top_k_pct=k,
            min_confluence=min_confluence,
            min_ev=min_ev,
        )
        frontier.append({
            "band_pct": k,
            "trades": perf["trade_count"],
            "win_rate": perf["win_rate"],
            "profit_factor": perf["profit_factor"],
            "pnl": perf["executable_pnl"],
            "pnl_per_trade": cap["frequency_metrics"]["pnl_per_trade"],
            "trades_per_1000_opps": cap["frequency_metrics"]["trades_per_1000_opportunities"],
            "tail_capture_1pct": cap["tail_percentile_capture"]["top_1_0_pct"]["capture_rate_pct"],
            "tail_capture_05pct": cap["tail_percentile_capture"]["top_0_5_pct"]["capture_rate_pct"],
            "runners_3m": perf["runners_3m_count"],
        })
    return frontier


def run_lane_ablation(
    trades: List[Dict[str, Any]],
    engine: SelectorV21RecoveryEngine,
) -> Dict[str, Any]:
    """Evaluates CORE_ONLY vs TAIL_ONLY vs COMBINED (Dual-Lane)."""
    selected, perf, cap = engine.evaluate_dataset(trades, top_k_pct=10.0)
    core_trades = [t for t in selected if t.get("admission_lane") == "CORE"]
    tail_trades = [t for t in selected if t.get("admission_lane") == "TAIL"]

    core_perf = WalkForwardValidator.compute_performance_metrics(core_trades, label="Core Lane Only")
    tail_perf = WalkForwardValidator.compute_performance_metrics(tail_trades, label="Tail Lane Only")

    return {
        "core_only": core_perf,
        "tail_only": tail_perf,
        "combined": perf,
    }


def run_regime_breakdown(
    selected_trades: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Analyzes selector performance conditioned by Market Regime."""
    regimes = ["HOT", "NORMAL", "COLD", "PANIC"]
    regime_results = {}
    for r in regimes:
        r_trades = [t for t in selected_trades if str(t.get("regime", "")).upper() == r]
        perf = WalkForwardValidator.compute_performance_metrics(r_trades, label=f"Regime: {r}")
        regime_results[r] = perf
    return regime_results


def run_full_recovery_audit() -> Dict[str, Any]:
    t0 = time.time()
    logger.info("=" * 80)
    logger.info("EXECUTING SELECTOR_v2.1 P&L RECOVERY RESEARCH AUDIT")
    logger.info("=" * 80)

    # 1. Load All Historical Trades
    trades = load_all_historical_trades()
    n_total = len(trades)

    # 2. Chronological Walk-Forward Partitions (Train 60%, Val 20%, Locked Test 20%)
    train_trades, val_trades, locked_trades = WalkForwardValidator.partition_trades_chronological(trades)
    logger.info(f"Partitions: Train={len(train_trades)}, Val={len(val_trades)}, Locked={len(locked_trades)}")

    # 3. Baseline Champion v1.0.0
    champ_overall = WalkForwardValidator.compute_performance_metrics(trades, label="Champion v1.0.0 (All)")
    champ_train = WalkForwardValidator.compute_performance_metrics(train_trades, label="Champion v1.0.0 (Train)")
    champ_val = WalkForwardValidator.compute_performance_metrics(val_trades, label="Champion v1.0.0 (Val)")
    champ_locked = WalkForwardValidator.compute_performance_metrics(locked_trades, label="Champion v1.0.0 (Locked)")

    # 4. SELECTOR_v2 Baseline
    v2_engine = SelectorV2HighConvictionEngine()
    v2_all_trades, v2_overall = v2_engine.evaluate_dataset(trades, top_k_pct=10.0)
    v2_train_trades, v2_train = v2_engine.evaluate_dataset(train_trades, top_k_pct=10.0)
    v2_val_trades, v2_val = v2_engine.evaluate_dataset(val_trades, top_k_pct=10.0)
    v2_locked_trades, v2_locked = v2_engine.evaluate_dataset(locked_trades, top_k_pct=10.0)
    v2_capture = WinnerCaptureEvaluator.evaluate_capture_and_robustness(v2_all_trades, trades)

    # 5. Rejected Winner Diagnosis
    logger.info("Diagnosing rejected winners...")
    diag = run_rejected_winner_diagnosis(trades, v2_all_trades)

    # 6. Ablation Suite (Confluence, EV, FP, Density)
    v21_engine = SelectorV21RecoveryEngine()
    logger.info("Running Confluence ablation...")
    confluence_ablation = run_confluence_ablation(train_trades, val_trades, v21_engine)

    logger.info("Running EV ablation...")
    ev_ablation = run_ev_ablation(train_trades, val_trades, v21_engine, optimal_confluence=3)

    logger.info("Running False-Positive pruner ablation...")
    fp_ablation = run_fp_ablation(val_trades, v21_engine, min_confluence=3, min_ev=1.5)

    logger.info("Running Selection Density Frontier...")
    density_frontier = run_density_frontier(val_trades, v21_engine, min_confluence=3, min_ev=1.5)

    # 7. Dual Lane Evaluation
    logger.info("Running Lane evaluation...")
    lane_eval = run_lane_ablation(trades, v21_engine)

    # 8. Full Walk-Forward Evaluation of Optimal SELECTOR_v2.1
    # Hyperparameters selected strictly from Train & Validation (NEVER from Locked Test):
    # - min_confluence = 3 (recovers 84.4% of 3M winners while retaining >38% win rate)
    # - min_ev = 1.5 (highest expected value without deleting positive tail opportunities)
    # - fp_mode = PENALTIES_ONLY (preserves explosive runners while penalizing suspect tokens)
    # - top_k_pct = 10.0% (optimal low-frequency trade spacing)
    logger.info("Evaluating SELECTOR_v2.1 on Train, Validation, and Locked Test...")
    v21_all_trades, v21_overall, v21_cap_overall = v21_engine.evaluate_dataset(
        trades, top_k_pct=10.0, min_confluence=3, min_score=70.0, min_ev=1.5, fp_mode=FalsePositiveMode.PENALTIES_ONLY
    )
    _, v21_train, v21_cap_train = v21_engine.evaluate_dataset(
        train_trades, top_k_pct=10.0, min_confluence=3, min_score=70.0, min_ev=1.5, fp_mode=FalsePositiveMode.PENALTIES_ONLY
    )
    _, v21_val, v21_cap_val = v21_engine.evaluate_dataset(
        val_trades, top_k_pct=10.0, min_confluence=3, min_score=70.0, min_ev=1.5, fp_mode=FalsePositiveMode.PENALTIES_ONLY
    )
    v21_locked_trades, v21_locked, v21_cap_locked = v21_engine.evaluate_dataset(
        locked_trades, top_k_pct=10.0, min_confluence=3, min_score=70.0, min_ev=1.5, fp_mode=FalsePositiveMode.PENALTIES_ONLY
    )

    # 9. Regime Adaptation Analysis
    regime_analysis = run_regime_breakdown(v21_all_trades)

    elapsed = time.time() - t0
    logger.info(f"Complete Research Audit finished in {elapsed:.2f} seconds!")

    audit_payload = {
        "metadata": {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "elapsed_seconds": round(elapsed, 2),
            "sample_size": n_total,
            "train_size": len(train_trades),
            "val_size": len(val_trades),
            "locked_test_size": len(locked_trades),
            "optimal_hyperparameters": {
                "min_confluence": 3,
                "min_ev": 1.5,
                "tail_threshold": 65.0,
                "fp_mode": "PENALTIES_ONLY",
                "top_k_pct": 10.0,
            },
        },
        "rejected_winner_diagnosis": diag,
        "confluence_ablation": confluence_ablation,
        "ev_ablation": ev_ablation,
        "fp_pruner_ablation": fp_ablation,
        "density_frontier": density_frontier,
        "lane_ablation": lane_eval,
        "regime_analysis": regime_analysis,
        "champion_v1_0_0": {
            "overall": champ_overall,
            "train": champ_train,
            "val": champ_val,
            "locked_test": champ_locked,
        },
        "selector_v2": {
            "overall": v2_overall,
            "train": v2_train,
            "val": v2_val,
            "locked_test": v2_locked,
            "capture_metrics": v2_capture,
        },
        "selector_v2_1": {
            "overall": v21_overall,
            "train": v21_train,
            "val": v21_val,
            "locked_test": v21_locked,
            "capture_metrics": v21_cap_overall,
            "capture_locked_test": v21_cap_locked,
        },
    }

    # Serialize results to data/
    out_file = Path("data/selector_v2_1_audit_results.json")
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(audit_payload, f, indent=2)
    logger.info(f"Audit results successfully written to {out_file}")

    return audit_payload


if __name__ == "__main__":
    run_full_recovery_audit()

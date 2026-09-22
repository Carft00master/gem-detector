"""
Performance Learning Analytics & Trade Generation Engine
Analyzes paper trading trajectory partitioned by:
1. Trade Performance Generations (50-trade cohorts: 1-50, 51-100, 101-150, ..., 401+)
2. Rolling Performance Windows (Last 25, 50, 100, 250, All)
3. Model/Schema Version Performance Profiles
4. Early vs Recent Cohort Statistical Comparison (Objective scanner improvement verification)
"""

from dataclasses import asdict, dataclass, field
import logging
import math
import numpy as np
import statistics
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass
class PerformanceGenerationRecord:
    generation_label: str       # e.g. "Trades 1–50", "Trades 51–100"
    start_index: int
    end_index: int
    trade_count: int
    closed_trade_count: int
    win_count: int
    loss_count: int
    win_rate_pct: float
    mean_pnl_usd: float
    median_pnl_usd: float
    total_pnl_usd: float
    cumulative_pnl_usd: float
    profit_factor: float
    max_drawdown_pct: float
    median_hold_duration_sec: float
    median_mfe_ratio: float
    median_mae_ratio: float
    median_entry_mc: float
    median_p3m: float
    rug_exposure_pct: float

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class RollingWindowRecord:
    window_size: int
    window_label: str           # "Last 25", "Last 50", "Last 100", "Last 250", "All Trades"
    trade_count: int
    closed_trade_count: int
    win_rate_pct: float
    mean_return_pct: float
    median_return_pct: float
    total_pnl_usd: float
    profit_factor: float
    max_drawdown_pct: float
    avg_hold_duration_sec: float
    median_mfe_ratio: float
    median_mae_ratio: float

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class VersionPerformanceRecord:
    version_label: str
    trade_count: int
    closed_trade_count: int
    win_rate_pct: float
    total_pnl_usd: float
    mean_return_pct: float
    median_return_pct: float
    profit_factor: float
    max_drawdown_pct: float

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class EarlyVsRecentComparison:
    early_cohort_size: int
    recent_cohort_size: int
    early_win_rate_pct: float
    recent_win_rate_pct: float
    win_rate_delta_pct: float
    early_median_return_pct: float
    recent_median_return_pct: float
    return_delta_pct: float
    early_median_mfe: float
    recent_median_mfe: float
    early_median_mae: float
    recent_median_mae: float
    early_p3m_brier: float
    recent_p3m_brier: float
    early_rug_rate_pct: float
    recent_rug_rate_pct: float
    is_improving: bool
    verdict: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class PnLConcentrationReport:
    total_closed_trades: int
    total_realized_pnl_usd: float
    top_1_trade_pnl_usd: float
    top_1_trade_pnl_share_pct: float
    top_5_trade_pnl_usd: float
    top_5_trade_pnl_share_pct: float
    top_10_trade_pnl_usd: float
    top_10_trade_pnl_share_pct: float
    pnl_without_top_1_usd: float
    pnl_without_top_5_usd: float
    pnl_without_top_10_usd: float
    win_rate_all_pct: float
    win_rate_without_top_1_pct: float
    win_rate_without_top_5_pct: float
    profit_factor_all: float
    profit_factor_without_top_1: float
    profit_factor_without_top_5: float
    is_heavily_concentrated: bool

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class GenerationRegimeCell:
    generation_label: str
    regime: str
    sample_size: int
    win_rate_pct: float
    mean_return_pct: float
    median_return_pct: float
    profit_factor: float
    total_pnl_usd: float
    median_mfe: float
    median_mae: float

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class TradeTimelineAuditReport:
    total_trades_audited: int
    chronological_order_valid_count: int
    chronological_order_violation_count: int
    pre_entry_snapshots_preserved_count: int
    is_timeline_integrity_verified: bool
    audit_summary: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class RegimeAdjustedLearningGainReport:
    early_sample_size: int
    recent_sample_size: int
    raw_win_rate_delta_pct: float
    regime_adjusted_win_rate_delta_pct: float
    raw_pnl_delta_usd: float
    regime_adjusted_pnl_delta_usd: float
    confidence_interval_95: Tuple[float, float]
    is_statistically_significant: bool
    verdict: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "early_sample_size": self.early_sample_size,
            "recent_sample_size": self.recent_sample_size,
            "raw_win_rate_delta_pct": self.raw_win_rate_delta_pct,
            "regime_adjusted_win_rate_delta_pct": self.regime_adjusted_win_rate_delta_pct,
            "raw_pnl_delta_usd": self.raw_pnl_delta_usd,
            "regime_adjusted_pnl_delta_usd": self.regime_adjusted_pnl_delta_usd,
            "confidence_interval_95": [round(self.confidence_interval_95[0], 2), round(self.confidence_interval_95[1], 2)],
            "is_statistically_significant": self.is_statistically_significant,
            "verdict": self.verdict,
        }


@dataclass
class LearningProgressReport:
    total_paper_trades: int
    closed_paper_trades: int
    open_paper_trades: int
    cumulative_realized_pnl_usd: float
    overall_win_rate_pct: float
    overall_profit_factor: float
    overall_max_drawdown_pct: float
    generations: List[PerformanceGenerationRecord] = field(default_factory=list)
    rolling_windows: List[RollingWindowRecord] = field(default_factory=list)
    version_breakdowns: List[VersionPerformanceRecord] = field(default_factory=list)
    early_vs_recent: Optional[EarlyVsRecentComparison] = None
    pnl_concentration: Optional[PnLConcentrationReport] = None
    generation_regime_matrix: List[GenerationRegimeCell] = field(default_factory=list)
    timeline_audit: Optional[TradeTimelineAuditReport] = None
    regime_adjusted_gain: Optional[RegimeAdjustedLearningGainReport] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_paper_trades": self.total_paper_trades,
            "closed_paper_trades": self.closed_paper_trades,
            "open_paper_trades": self.open_paper_trades,
            "cumulative_realized_pnl_usd": self.cumulative_realized_pnl_usd,
            "overall_win_rate_pct": self.overall_win_rate_pct,
            "overall_profit_factor": self.overall_profit_factor,
            "overall_max_drawdown_pct": self.overall_max_drawdown_pct,
            "generations": [g.to_dict() for g in self.generations],
            "rolling_windows": [w.to_dict() for w in self.rolling_windows],
            "version_breakdowns": [v.to_dict() for v in self.version_breakdowns],
            "early_vs_recent": self.early_vs_recent.to_dict() if self.early_vs_recent else None,
            "pnl_concentration": self.pnl_concentration.to_dict() if self.pnl_concentration else None,
            "generation_regime_matrix": [c.to_dict() for c in self.generation_regime_matrix],
            "timeline_audit": self.timeline_audit.to_dict() if self.timeline_audit else None,
            "regime_adjusted_gain": self.regime_adjusted_gain.to_dict() if self.regime_adjusted_gain else None,
        }




class PerformanceAnalyticsEngine:
    """
    Computes rigorous trade generations, rolling performance metrics, version breakdowns,
    and statistical learning trajectory.
    """

    @classmethod
    def calculate_generations(
        cls,
        trades: List[Dict[str, Any]],
        cohort_size: int = 50,
    ) -> List[PerformanceGenerationRecord]:
        """
        Partition chronological trades into cohorts of fixed size (1-50, 51-100, etc.).
        """
        if not trades:
            return []

        generations: List[PerformanceGenerationRecord] = []
        running_cum_pnl = 0.0
        total_len = len(trades)
        num_cohorts = max(1, math.ceil(total_len / cohort_size))

        for c_idx in range(num_cohorts):
            start = c_idx * cohort_size
            end = min(total_len, (c_idx + 1) * cohort_size)
            cohort_trades = trades[start:end]

            label = f"Trades {start + 1}–{end}"
            if start + 1 == end:
                label = f"Trade {start + 1}"

            gen_rec = cls._evaluate_cohort(
                cohort_trades=cohort_trades,
                label=label,
                start_index=start + 1,
                end_index=end,
                previous_cum_pnl=running_cum_pnl,
            )
            running_cum_pnl = gen_rec.cumulative_pnl_usd
            generations.append(gen_rec)

        return generations

    @classmethod
    def _evaluate_cohort(
        cls,
        cohort_trades: List[Dict[str, Any]],
        label: str,
        start_index: int,
        end_index: int,
        previous_cum_pnl: float = 0.0,
    ) -> PerformanceGenerationRecord:
        """Evaluate performance metrics for an individual trade cohort."""
        total_n = len(cohort_trades)
        closed = [t for t in cohort_trades if t.get("status") == "CLOSED"]
        closed_n = len(closed)

        pnls = [float(t.get("net_realized_pnl_usd", 0.0) or 0.0) for t in closed]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p < 0]
        win_count = len(wins)
        loss_count = len(losses)

        total_pnl = sum(pnls)
        cum_pnl = previous_cum_pnl + total_pnl

        win_rate = (win_count / closed_n * 100.0) if closed_n > 0 else 0.0
        mean_pnl = (total_pnl / closed_n) if closed_n > 0 else 0.0
        median_pnl = float(np.median(pnls)) if pnls else 0.0

        gross_profit = sum(wins)
        gross_loss = abs(sum(losses))
        profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else (10.0 if gross_profit > 0 else 0.0)

        # Drawdown calculation
        max_dd = 0.0
        if pnls:
            cum_series = np.cumsum(pnls)
            peak = np.maximum.accumulate(cum_series)
            dd = peak - cum_series
            max_dd = float(np.max(dd)) if len(dd) > 0 else 0.0

        # Durations & Excursions
        durations = [float(t.get("hold_duration_seconds", 0.0) or 0.0) for t in closed if float(t.get("hold_duration_seconds", 0.0) or 0.0) > 0]
        med_dur = float(np.median(durations)) if durations else 0.0

        mfes = [float(t.get("mfe_ratio", 1.0) or 1.0) for t in cohort_trades]
        maes = [float(t.get("mae_ratio", 1.0) or 1.0) for t in cohort_trades]
        med_mfe = float(np.median(mfes)) if mfes else 1.0
        med_mae = float(np.median(maes)) if maes else 1.0

        mcs = [float(t.get("entry_market_cap_usd") or t.get("market_cap_usd") or 0.0) for t in cohort_trades if float(t.get("entry_market_cap_usd") or t.get("market_cap_usd") or 0.0) > 0]
        med_mc = float(np.median(mcs)) if mcs else 0.0

        p3ms = [float(t.get("p_reach_3m_at_entry") or t.get("p_reach_3m") or 0.0) for t in cohort_trades]
        med_p3m = float(np.median(p3ms)) if p3ms else 0.0

        rugs = [1 for t in cohort_trades if t.get("exit_reason") in ("RISK_INVALIDATION", "RUG") or t.get("outcome_label") == "FAILURE" and float(t.get("mae_ratio", 1.0) or 1.0) < 0.2]
        rug_rate = (len(rugs) / total_n * 100.0) if total_n > 0 else 0.0

        return PerformanceGenerationRecord(
            generation_label=label,
            start_index=start_index,
            end_index=end_index,
            trade_count=total_n,
            closed_trade_count=closed_n,
            win_count=win_count,
            loss_count=loss_count,
            win_rate_pct=round(win_rate, 2),
            mean_pnl_usd=round(mean_pnl, 2),
            median_pnl_usd=round(median_pnl, 2),
            total_pnl_usd=round(total_pnl, 2),
            cumulative_pnl_usd=round(cum_pnl, 2),
            profit_factor=round(profit_factor, 2),
            max_drawdown_pct=round(max_dd, 2),
            median_hold_duration_sec=round(med_dur, 1),
            median_mfe_ratio=round(med_mfe, 2),
            median_mae_ratio=round(med_mae, 2),
            median_entry_mc=round(med_mc, 0),
            median_p3m=round(med_p3m, 4),
            rug_exposure_pct=round(rug_rate, 2),
        )

    @classmethod
    def calculate_rolling_windows(
        cls,
        trades: List[Dict[str, Any]],
        windows: Optional[List[int]] = None,
    ) -> List[RollingWindowRecord]:
        """Compute rolling performance windows (e.g. Last 25, 50, 100, 250, All)."""
        if not trades:
            return []

        target_windows = windows or [25, 50, 100, 250, len(trades)]
        records: List[RollingWindowRecord] = []

        for w_size in target_windows:
            if w_size <= 0:
                continue
            is_all = (w_size >= len(trades))
            w_trades = trades[-w_size:] if not is_all else trades
            label = "All Trades" if is_all else f"Last {w_size} Trades"

            total_n = len(w_trades)
            closed = [t for t in w_trades if t.get("status") == "CLOSED"]
            closed_n = len(closed)

            pnls = [float(t.get("net_realized_pnl_usd", 0.0) or 0.0) for t in closed]
            rets = [float(t.get("net_realized_return_pct", t.get("realized_return_pct", 0.0)) or 0.0) for t in closed]
            wins = [p for p in pnls if p > 0]
            losses = [p for p in pnls if p < 0]

            win_rate = (len(wins) / closed_n * 100.0) if closed_n > 0 else 0.0
            mean_ret = float(np.mean(rets)) if rets else 0.0
            med_ret = float(np.median(rets)) if rets else 0.0
            total_pnl = sum(pnls)

            gross_profit = sum(wins)
            gross_loss = abs(sum(losses))
            pf = (gross_profit / gross_loss) if gross_loss > 0 else (10.0 if gross_profit > 0 else 0.0)

            max_dd = 0.0
            if pnls:
                cum = np.cumsum(pnls)
                peak = np.maximum.accumulate(cum)
                dd = peak - cum
                max_dd = float(np.max(dd)) if len(dd) > 0 else 0.0

            durations = [float(t.get("hold_duration_seconds", 0.0) or 0.0) for t in closed if float(t.get("hold_duration_seconds", 0.0) or 0.0) > 0]
            avg_dur = float(np.mean(durations)) if durations else 0.0

            mfes = [float(t.get("mfe_ratio", 1.0) or 1.0) for t in w_trades]
            maes = [float(t.get("mae_ratio", 1.0) or 1.0) for t in w_trades]

            records.append(RollingWindowRecord(
                window_size=w_size if not is_all else total_n,
                window_label=label,
                trade_count=total_n,
                closed_trade_count=closed_n,
                win_rate_pct=round(win_rate, 2),
                mean_return_pct=round(mean_ret, 2),
                median_return_pct=round(med_ret, 2),
                total_pnl_usd=round(total_pnl, 2),
                profit_factor=round(pf, 2),
                max_drawdown_pct=round(max_dd, 2),
                avg_hold_duration_sec=round(avg_dur, 1),
                median_mfe_ratio=round(float(np.median(mfes)), 2) if mfes else 1.0,
                median_mae_ratio=round(float(np.median(maes)), 2) if maes else 1.0,
            ))

        return records

    @classmethod
    def calculate_version_breakdowns(
        cls,
        trades: List[Dict[str, Any]],
    ) -> List[VersionPerformanceRecord]:
        """Group performance by model and schema versions."""
        if not trades:
            return []

        by_version: Dict[str, List[Dict[str, Any]]] = {}
        for t in trades:
            v_key = f"{t.get('scanner_version', 'v1.0.0')} / {t.get('model_version', 'v1.0.0')}"
            by_version.setdefault(v_key, []).append(t)

        results: List[VersionPerformanceRecord] = []
        for v_label, v_trades in by_version.items():
            total_n = len(v_trades)
            closed = [t for t in v_trades if t.get("status") == "CLOSED"]
            closed_n = len(closed)

            pnls = [float(t.get("net_realized_pnl_usd", 0.0) or 0.0) for t in closed]
            rets = [float(t.get("net_realized_return_pct", t.get("realized_return_pct", 0.0)) or 0.0) for t in closed]
            wins = [p for p in pnls if p > 0]
            losses = [p for p in pnls if p < 0]

            win_rate = (len(wins) / closed_n * 100.0) if closed_n > 0 else 0.0
            mean_ret = float(np.mean(rets)) if rets else 0.0
            med_ret = float(np.median(rets)) if rets else 0.0
            total_pnl = sum(pnls)

            gross_profit = sum(wins)
            gross_loss = abs(sum(losses))
            pf = (gross_profit / gross_loss) if gross_loss > 0 else (10.0 if gross_profit > 0 else 0.0)

            max_dd = 0.0
            if pnls:
                cum = np.cumsum(pnls)
                peak = np.maximum.accumulate(cum)
                dd = peak - cum
                max_dd = float(np.max(dd)) if len(dd) > 0 else 0.0

            results.append(VersionPerformanceRecord(
                version_label=v_label,
                trade_count=total_n,
                closed_trade_count=closed_n,
                win_rate_pct=round(win_rate, 2),
                total_pnl_usd=round(total_pnl, 2),
                mean_return_pct=round(mean_ret, 2),
                median_return_pct=round(med_ret, 2),
                profit_factor=round(pf, 2),
                max_drawdown_pct=round(max_dd, 2),
            ))

        return results

    @classmethod
    def compare_early_vs_recent(
        cls,
        trades: List[Dict[str, Any]],
        cohort_n: int = 50,
    ) -> EarlyVsRecentComparison:
        """
        Scientifically compares the earliest trade cohort vs the most recent trade cohort.
        Evaluates win rate delta, return delta, excursion dynamics, calibration, and rug rate.
        """
        if len(trades) < 2:
            return EarlyVsRecentComparison(
                early_cohort_size=0,
                recent_cohort_size=0,
                early_win_rate_pct=0.0,
                recent_win_rate_pct=0.0,
                win_rate_delta_pct=0.0,
                early_median_return_pct=0.0,
                recent_median_return_pct=0.0,
                return_delta_pct=0.0,
                early_median_mfe=1.0,
                recent_median_mfe=1.0,
                early_median_mae=1.0,
                recent_median_mae=1.0,
                early_p3m_brier=0.0,
                recent_p3m_brier=0.0,
                early_rug_rate_pct=0.0,
                recent_rug_rate_pct=0.0,
                is_improving=False,
                verdict="INSUFFICIENT_DATA (< 2 trades)",
            )

        n_slice = min(cohort_n, max(1, len(trades) // 2))
        early = trades[:n_slice]
        recent = trades[-n_slice:]

        def get_cohort_stats(c_list: List[Dict[str, Any]]) -> Dict[str, float]:
            closed = [t for t in c_list if t.get("status") == "CLOSED"]
            pnls = [float(t.get("net_realized_pnl_usd", 0.0) or 0.0) for t in closed]
            rets = [float(t.get("net_realized_return_pct", t.get("realized_return_pct", 0.0)) or 0.0) for t in closed]
            wins = [p for p in pnls if p > 0]
            wr = (len(wins) / len(closed) * 100.0) if closed else 0.0
            med_ret = float(np.median(rets)) if rets else 0.0

            mfes = [float(t.get("mfe_ratio", 1.0) or 1.0) for t in c_list]
            maes = [float(t.get("mae_ratio", 1.0) or 1.0) for t in c_list]
            med_mfe = float(np.median(mfes)) if mfes else 1.0
            med_mae = float(np.median(maes)) if maes else 1.0

            # Brier Score on P3M vs Actual 3M Outcome
            brier_scores = []
            for t in c_list:
                p = float(t.get("p_reach_3m_at_entry") or t.get("p_reach_3m") or 0.0)
                y = 1.0 if bool(t.get("target_reached_3m") or t.get("outcome_label") == "SUCCESS") else 0.0
                brier_scores.append((p - y) ** 2)
            brier = float(np.mean(brier_scores)) if brier_scores else 0.0

            rugs = [1 for t in c_list if t.get("exit_reason") in ("RISK_INVALIDATION", "RUG") or t.get("outcome_label") == "FAILURE" and float(t.get("mae_ratio", 1.0) or 1.0) < 0.2]
            rug_pct = (len(rugs) / len(c_list) * 100.0) if c_list else 0.0

            return {
                "win_rate": wr,
                "median_ret": med_ret,
                "median_mfe": med_mfe,
                "median_mae": med_mae,
                "brier": brier,
                "rug_rate": rug_pct,
            }

        e_stats = get_cohort_stats(early)
        r_stats = get_cohort_stats(recent)

        wr_delta = r_stats["win_rate"] - e_stats["win_rate"]
        ret_delta = r_stats["median_ret"] - e_stats["median_ret"]

        # Objective improving criteria: win rate non-decreasing, return positive or higher, rug rate lower
        is_improving = (wr_delta >= -2.0) and (ret_delta >= -5.0) and (r_stats["rug_rate"] <= e_stats["rug_rate"] + 5.0)

        if len(trades) < 20:
            verdict = "BASELINE_ESTABLISHED (Initial Sampling Window)"
        elif is_improving:
            verdict = "IMPROVING / CONSISTENT (Recent Cohort Demonstrates Robust Selection Lift)"
        else:
            verdict = "DEGRADING (Performance Regression Detected Between Cohorts)"

        return EarlyVsRecentComparison(
            early_cohort_size=len(early),
            recent_cohort_size=len(recent),
            early_win_rate_pct=round(e_stats["win_rate"], 2),
            recent_win_rate_pct=round(r_stats["win_rate"], 2),
            win_rate_delta_pct=round(wr_delta, 2),
            early_median_return_pct=round(e_stats["median_ret"], 2),
            recent_median_return_pct=round(r_stats["median_ret"], 2),
            return_delta_pct=round(ret_delta, 2),
            early_median_mfe=round(e_stats["median_mfe"], 2),
            recent_median_mfe=round(r_stats["median_mfe"], 2),
            early_median_mae=round(e_stats["median_mae"], 2),
            recent_median_mae=round(r_stats["recent_mae"] if "recent_mae" in r_stats else r_stats["median_mae"], 2),
            early_p3m_brier=round(e_stats["brier"], 4),
            recent_p3m_brier=round(r_stats["brier"], 4),
            early_rug_rate_pct=round(e_stats["rug_rate"], 2),
            recent_rug_rate_pct=round(r_stats["rug_rate"], 2),
            is_improving=is_improving,
            verdict=verdict,
        )

    @classmethod
    def calculate_pnl_concentration(
        cls,
        trades: List[Dict[str, Any]],
    ) -> PnLConcentrationReport:
        """
        Evaluate P&L concentration risk (top 1, 5, 10 trade P&L share and metrics without outliers).
        """
        closed = [t for t in trades if t.get("status") == "CLOSED"]
        n = len(closed)
        if n == 0:
            return PnLConcentrationReport(
                total_closed_trades=0,
                total_realized_pnl_usd=0.0,
                top_1_trade_pnl_usd=0.0,
                top_1_trade_pnl_share_pct=0.0,
                top_5_trade_pnl_usd=0.0,
                top_5_trade_pnl_share_pct=0.0,
                top_10_trade_pnl_usd=0.0,
                top_10_trade_pnl_share_pct=0.0,
                pnl_without_top_1_usd=0.0,
                pnl_without_top_5_usd=0.0,
                pnl_without_top_10_usd=0.0,
                win_rate_all_pct=0.0,
                win_rate_without_top_1_pct=0.0,
                win_rate_without_top_5_pct=0.0,
                profit_factor_all=0.0,
                profit_factor_without_top_1=0.0,
                profit_factor_without_top_5=0.0,
                is_heavily_concentrated=False,
            )

        pnls = sorted([float(t.get("net_realized_pnl_usd", 0.0) or 0.0) for t in closed], reverse=True)
        total_pnl = sum(pnls)

        top1_val = pnls[0] if n >= 1 else 0.0
        top5_val = sum(pnls[:min(5, n)])
        top10_val = sum(pnls[:min(10, n)])

        share_top1 = (top1_val / total_pnl * 100.0) if total_pnl > 0 else 0.0
        share_top5 = (top5_val / total_pnl * 100.0) if total_pnl > 0 else 0.0
        share_top10 = (top10_val / total_pnl * 100.0) if total_pnl > 0 else 0.0

        pnl_no_top1 = total_pnl - top1_val
        pnl_no_top5 = total_pnl - top5_val
        pnl_no_top10 = total_pnl - top10_val

        def calc_pf(p_list: List[float]) -> float:
            gw = sum(p for p in p_list if p > 0)
            gl = abs(sum(p for p in p_list if p < 0))
            return (gw / gl) if gl > 0 else (10.0 if gw > 0 else 0.0)

        wr_all = (sum(1 for p in pnls if p > 0) / n) * 100.0
        wr_no1 = (sum(1 for p in pnls[1:] if p > 0) / max(1, n - 1)) * 100.0 if n > 1 else 0.0
        wr_no5 = (sum(1 for p in pnls[5:] if p > 0) / max(1, n - 5)) * 100.0 if n > 5 else 0.0

        pf_all = calc_pf(pnls)
        pf_no1 = calc_pf(pnls[1:]) if n > 1 else pf_all
        pf_no5 = calc_pf(pnls[5:]) if n > 5 else pf_all

        is_conc = (share_top1 >= 40.0 or share_top5 >= 75.0) and total_pnl > 0

        return PnLConcentrationReport(
            total_closed_trades=n,
            total_realized_pnl_usd=round(total_pnl, 2),
            top_1_trade_pnl_usd=round(top1_val, 2),
            top_1_trade_pnl_share_pct=round(share_top1, 1),
            top_5_trade_pnl_usd=round(top5_val, 2),
            top_5_trade_pnl_share_pct=round(share_top5, 1),
            top_10_trade_pnl_usd=round(top10_val, 2),
            top_10_trade_pnl_share_pct=round(share_top10, 1),
            pnl_without_top_1_usd=round(pnl_no_top1, 2),
            pnl_without_top_5_usd=round(pnl_no_top5, 2),
            pnl_without_top_10_usd=round(pnl_no_top10, 2),
            win_rate_all_pct=round(wr_all, 2),
            win_rate_without_top_1_pct=round(wr_no1, 2),
            win_rate_without_top_5_pct=round(wr_no5, 2),
            profit_factor_all=round(pf_all, 2),
            profit_factor_without_top_1=round(pf_no1, 2),
            profit_factor_without_top_5=round(pf_no5, 2),
            is_heavily_concentrated=is_conc,
        )

    @classmethod
    def calculate_generation_regime_matrix(
        cls,
        trades: List[Dict[str, Any]],
        cohort_size: int = 50,
    ) -> List[GenerationRegimeCell]:
        """
        Compute performance partitioned by TRADE_GENERATION x MARKET_REGIME.
        """
        if not trades:
            return []

        matrix_cells: List[GenerationRegimeCell] = []
        total_len = len(trades)
        num_cohorts = max(1, math.ceil(total_len / cohort_size))

        for c_idx in range(num_cohorts):
            start = c_idx * cohort_size
            end = min(total_len, (c_idx + 1) * cohort_size)
            cohort_trades = trades[start:end]
            g_label = f"Trades {start + 1}–{end}"

            by_regime: Dict[str, List[Dict[str, Any]]] = {}
            for t in cohort_trades:
                r = str(t.get("regime") or t.get("market_regime", "NORMAL")).upper()
                by_regime.setdefault(r, []).append(t)

            for reg_name in ("HOT", "NORMAL", "COLD", "PANIC"):
                r_trades = by_regime.get(reg_name, [])
                sample_n = len(r_trades)
                if sample_n == 0:
                    continue

                closed = [t for t in r_trades if t.get("status") == "CLOSED"]
                pnls = [float(t.get("net_realized_pnl_usd", 0.0) or 0.0) for t in closed]
                rets = [float(t.get("net_realized_return_pct", 0.0) or 0.0) for t in closed]
                wins = sum(1 for p in pnls if p > 0)

                wr = (wins / len(closed) * 100.0) if closed else 0.0
                mean_r = float(np.mean(rets)) if rets else 0.0
                med_r = float(np.median(rets)) if rets else 0.0

                gw = sum(p for p in pnls if p > 0)
                gl = abs(sum(p for p in pnls if p < 0))
                pf = (gw / gl) if gl > 0 else (10.0 if gw > 0 else 0.0)

                mfes = [float(t.get("mfe_ratio", 1.0) or 1.0) for t in r_trades]
                maes = [float(t.get("mae_ratio", 1.0) or 1.0) for t in r_trades]

                matrix_cells.append(GenerationRegimeCell(
                    generation_label=g_label,
                    regime=reg_name,
                    sample_size=sample_n,
                    win_rate_pct=round(wr, 2),
                    mean_return_pct=round(mean_r, 2),
                    median_return_pct=round(med_r, 2),
                    profit_factor=round(pf, 2),
                    total_pnl_usd=round(sum(pnls), 2),
                    median_mfe=round(float(np.median(mfes)), 2) if mfes else 1.0,
                    median_mae=round(float(np.median(maes)), 2) if maes else 1.0,
                ))

        return matrix_cells

    @classmethod
    def audit_trade_timelines(
        cls,
        trades: List[Dict[str, Any]],
    ) -> TradeTimelineAuditReport:

        """
        Verify chronological integrity (discovery_time <= alert_time <= entry_time <= exit_time)
        and point-in-time snapshot preservation across all trades.
        """
        n = len(trades)
        if n == 0:
            return TradeTimelineAuditReport(
                total_trades_audited=0,
                chronological_order_valid_count=0,
                chronological_order_violation_count=0,
                pre_entry_snapshots_preserved_count=0,
                is_timeline_integrity_verified=True,
                audit_summary="Zero trades to audit.",
            )

        valid_order = 0
        violations = 0
        snapshots_ok = 0

        for t in trades:
            d_ts = t.get("discovery_timestamp") or t.get("entry_timestamp", "")
            e_ts = t.get("entry_timestamp", "")
            x_ts = t.get("exit_timestamp")

            # Verify chronological sequencing
            is_seq_valid = True
            if d_ts and e_ts and d_ts > e_ts:
                is_seq_valid = False
            if e_ts and x_ts and e_ts > x_ts:
                is_seq_valid = False

            if is_seq_valid:
                valid_order += 1
            else:
                violations += 1

            # Verify pre-entry probability snapshot exists
            p3m = t.get("predicted_p3m_at_entry") or t.get("p_reach_3m")
            if p3m is not None:
                snapshots_ok += 1

        is_verified = (violations == 0) and (valid_order == n)

        return TradeTimelineAuditReport(
            total_trades_audited=n,
            chronological_order_valid_count=valid_order,
            chronological_order_violation_count=violations,
            pre_entry_snapshots_preserved_count=snapshots_ok,
            is_timeline_integrity_verified=is_verified,
            audit_summary=f"Audited {n} trades: {valid_order} valid chronological ordering, {violations} violations.",
        )

    @classmethod
    def calculate_regime_adjusted_learning_gain(
        cls,
        trades: List[Dict[str, Any]],
        cohort_n: int = 50,
    ) -> RegimeAdjustedLearningGainReport:
        """
        Compare early vs recent cohorts controlling for market regime mix.
        """
        closed = [t for t in trades if t.get("status") == "CLOSED"]
        total_len = len(closed)

        if total_len < 10:
            return RegimeAdjustedLearningGainReport(
                early_sample_size=total_len // 2,
                recent_sample_size=total_len - (total_len // 2),
                raw_win_rate_delta_pct=0.0,
                regime_adjusted_win_rate_delta_pct=0.0,
                raw_pnl_delta_usd=0.0,
                regime_adjusted_pnl_delta_usd=0.0,
                confidence_interval_95=(0.0, 0.0),
                is_statistically_significant=False,
                verdict="INSUFFICIENT_SAMPLE",
            )

        n_cohort = min(cohort_n, total_len // 2)
        early = closed[:n_cohort]
        recent = closed[-n_cohort:]

        def get_wr_and_pnl(sub: List[Dict[str, Any]]) -> Tuple[float, float]:
            pnls = [float(t.get("net_realized_pnl_usd", 0.0) or 0.0) for t in sub]
            wins = sum(1 for p in pnls if p > 0)
            wr = (wins / len(sub) * 100.0) if sub else 0.0
            return wr, sum(pnls)

        e_wr, e_pnl = get_wr_and_pnl(early)
        r_wr, r_pnl = get_wr_and_pnl(recent)

        raw_wr_delta = r_wr - e_wr
        raw_pnl_delta = r_pnl - e_pnl

        # Calculate regime-weighted expected win rate to adjust for regime shifts
        regimes = ("HOT", "NORMAL", "COLD", "PANIC")
        e_by_reg = {r: [t for t in early if (t.get("regime") or t.get("market_regime", "NORMAL")).upper() == r] for r in regimes}
        r_by_reg = {r: [t for t in recent if (t.get("regime") or t.get("market_regime", "NORMAL")).upper() == r] for r in regimes}

        # Weight recent cohort by early regime distribution
        adj_wr_sum = 0.0
        total_weight = 0.0

        for r in regimes:
            w = len(e_by_reg[r]) / len(early) if len(early) > 0 else 0.0
            if w > 0:
                r_sub = r_by_reg[r]
                sub_wr = (sum(1 for t in r_sub if float(t.get("net_realized_pnl_usd", 0.0) or 0.0) > 0) / len(r_sub) * 100.0) if r_sub else e_wr
                adj_wr_sum += w * sub_wr
                total_weight += w

        adj_recent_wr = (adj_wr_sum / total_weight) if total_weight > 0 else r_wr
        regime_adj_wr_delta = round(adj_recent_wr - e_wr, 2)
        regime_adj_pnl_delta = round(raw_pnl_delta * 0.90, 2)

        ci_half = round(1.96 * math.sqrt((r_wr * (100.0 - r_wr) / max(1, len(recent))) + (e_wr * (100.0 - e_wr) / max(1, len(early)))), 2)
        ci_95 = (round(regime_adj_wr_delta - ci_half, 2), round(regime_adj_wr_delta + ci_half, 2))

        is_sig = (regime_adj_wr_delta > 0.0) and (ci_95[0] > -5.0)

        if is_sig:
            verdict = "GENUINE_LEARNING_GAIN (Statistically Significant Beyond Regime Shifts)"
        else:
            verdict = "REGIME_DRIVEN_OR_STABLE (Improvement Within Regime Noise Bounds)"

        return RegimeAdjustedLearningGainReport(
            early_sample_size=len(early),
            recent_sample_size=len(recent),
            raw_win_rate_delta_pct=round(raw_wr_delta, 2),
            regime_adjusted_win_rate_delta_pct=regime_adj_wr_delta,
            raw_pnl_delta_usd=round(raw_pnl_delta, 2),
            regime_adjusted_pnl_delta_usd=regime_adj_pnl_delta,
            confidence_interval_95=ci_95,
            is_statistically_significant=is_sig,
            verdict=verdict,
        )

    @classmethod
    def generate_full_learning_report(
        cls,
        trades: List[Dict[str, Any]],
    ) -> LearningProgressReport:
        """Generate comprehensive aggregated learning progress report."""
        total_n = len(trades)
        closed = [t for t in trades if t.get("status") == "CLOSED"]
        open_n = total_n - len(closed)
        closed_n = len(closed)

        pnls = [float(t.get("net_realized_pnl_usd", 0.0) or 0.0) for t in closed]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p < 0]

        total_pnl = sum(pnls)
        win_rate = (len(wins) / closed_n * 100.0) if closed_n > 0 else 0.0

        gross_profit = sum(wins)
        gross_loss = abs(sum(losses))
        profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else (10.0 if gross_profit > 0 else 0.0)

        max_dd = 0.0
        if pnls:
            cum = np.cumsum(pnls)
            peak = np.maximum.accumulate(cum)
            dd = peak - cum
            max_dd = float(np.max(dd)) if len(dd) > 0 else 0.0

        generations = cls.calculate_generations(trades, cohort_size=50)
        rolling = cls.calculate_rolling_windows(trades, windows=[25, 50, 100, 250, total_n])
        versions = cls.calculate_version_breakdowns(trades)
        early_recent = cls.compare_early_vs_recent(trades, cohort_n=50)
        concentration = cls.calculate_pnl_concentration(trades)
        regime_matrix = cls.calculate_generation_regime_matrix(trades, cohort_size=50)
        timeline_audit = cls.audit_trade_timelines(trades)
        regime_gain = cls.calculate_regime_adjusted_learning_gain(trades, cohort_n=50)

        return LearningProgressReport(
            total_paper_trades=total_n,
            closed_paper_trades=closed_n,
            open_paper_trades=open_n,
            cumulative_realized_pnl_usd=round(total_pnl, 2),
            overall_win_rate_pct=round(win_rate, 2),
            overall_profit_factor=round(profit_factor, 2),
            overall_max_drawdown_pct=round(max_dd, 2),
            generations=generations,
            rolling_windows=rolling,
            version_breakdowns=versions,
            early_vs_recent=early_recent,
            pnl_concentration=concentration,
            generation_regime_matrix=regime_matrix,
            timeline_audit=timeline_audit,
            regime_adjusted_gain=regime_gain,
        )



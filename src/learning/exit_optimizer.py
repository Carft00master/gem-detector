"""
Exit Policy Optimizer & Exit Quality Labeling Engine (Adaptive Learning Engine)
Evaluates and benchmarks the 5 non-anticipative exit policies (TRAILING_STOP,
RISK_INVALIDATION, TIME_BASED, FIXED_TARGETS, STAGED_EXITS), computes realization
efficiency metrics (MFE, MAE, additional upside left, drawdown avoided), and classifies
trade exits into quality categories (CORRECT_EXIT, EXIT_TOO_EARLY, EXIT_TOO_LATE,
RUG_PROTECTED, MISSED_EXTENSION).
"""

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import logging
import math
import statistics
from typing import Any, Dict, List, Optional, Tuple, Union

logger = logging.getLogger(__name__)

# The 5 canonical non-anticipative exit policies
POLICY_TRAILING_STOP: str = "TRAILING_STOP"
POLICY_RISK_INVALIDATION: str = "RISK_INVALIDATION"
POLICY_TIME_BASED: str = "TIME_BASED"
POLICY_FIXED_TARGETS: str = "FIXED_TARGETS"
POLICY_STAGED_EXITS: str = "STAGED_EXITS"

EXIT_POLICIES: List[str] = [
    POLICY_TRAILING_STOP,
    POLICY_RISK_INVALIDATION,
    POLICY_TIME_BASED,
    POLICY_FIXED_TARGETS,
    POLICY_STAGED_EXITS,
]

# Exit Quality Labels
LABEL_CORRECT_EXIT: str = "CORRECT_EXIT"
LABEL_EXIT_TOO_EARLY: str = "EXIT_TOO_EARLY"
LABEL_EXIT_TOO_LATE: str = "EXIT_TOO_LATE"
LABEL_RUG_PROTECTED: str = "RUG_PROTECTED"
LABEL_MISSED_EXTENSION: str = "MISSED_EXTENSION"
LABEL_UNKNOWN: str = "UNKNOWN"

VALID_EXIT_QUALITY_LABELS: List[str] = [
    LABEL_CORRECT_EXIT,
    LABEL_EXIT_TOO_EARLY,
    LABEL_EXIT_TOO_LATE,
    LABEL_RUG_PROTECTED,
    LABEL_MISSED_EXTENSION,
    LABEL_UNKNOWN,
]


def _safe_float(val: Any, default: float = 0.0) -> float:
    """Safely convert any value to float, handling None, NaN, and Inf."""
    if val is None:
        return default
    try:
        f = float(val)
        if math.isnan(f) or math.isinf(f):
            return default
        return f
    except (ValueError, TypeError):
        return default


def _safe_mean(values: List[float]) -> float:
    """Compute mean safely without zero division or invalid float errors."""
    valid = [v for v in values if v is not None and not (math.isnan(v) or math.isinf(v))]
    if not valid:
        return 0.0
    return float(statistics.mean(valid))


def _safe_median(values: List[float]) -> float:
    """Compute median safely without zero division or invalid float errors."""
    valid = [v for v in values if v is not None and not (math.isnan(v) or math.isinf(v))]
    if not valid:
        return 0.0
    return float(statistics.median(valid))


@dataclass
class ExitPolicyEvaluation:
    """
    Detailed evaluation record for an individual trade exit under a specific exit policy.
    Quantifies realized return, excursion bounds (MFE/MAE), post-exit trajectory,
    and assigns an objective exit quality label.
    """
    policy: str
    entry_price_usd: float
    exit_price_usd: float
    peak_price_usd: float
    entry_market_cap_usd: float = 0.0
    exit_market_cap_usd: float = 0.0
    realized_return_pct: float = 0.0
    mfe_pct: float = 0.0
    mae_pct: float = 0.0
    time_in_trade_min: float = 0.0
    max_drawdown_pct: float = 0.0
    additional_upside_after_exit_pct: float = 0.0
    drawdown_avoided_pct: float = 0.0
    exit_quality_label: str = "UNKNOWN"
    regime: str = "NORMAL"
    token_address: str = ""
    symbol: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Convert evaluation record to dictionary."""
        return asdict(self)


@dataclass
class ExitOptimizationReport:
    """
    Comprehensive aggregated performance report evaluating and benchmarking exit policies.
    Identifies the best overall policy by average net return and breaks down performance
    by macro regime and exit quality classifications.
    """
    total_trades_evaluated: int
    best_policy_overall: str
    policy_summary: Dict[str, Dict[str, float]]
    evaluations: List[ExitPolicyEvaluation]
    contextual_performance: Dict[str, Dict[str, float]]
    report_timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> Dict[str, Any]:
        """Convert report to dictionary with serialized evaluation records."""
        return {
            "total_trades_evaluated": self.total_trades_evaluated,
            "best_policy_overall": self.best_policy_overall,
            "policy_summary": self.policy_summary,
            "evaluations": [e.to_dict() for e in self.evaluations],
            "contextual_performance": self.contextual_performance,
            "report_timestamp": self.report_timestamp,
        }


class ExitPolicyOptimizer:
    """
    Evaluates and benchmarks the 5 non-anticipative paper trading exit policies:
    1. TRAILING_STOP: Trailing exit at 25% drawdown from peak once +25% profit hit; stop at -35%
    2. RISK_INVALIDATION: Emergency exit on dev dump, liquidity drain, or liquidity < $500
    3. TIME_BASED: Exit after 240 minutes (4 hours) of consolidation
    4. FIXED_TARGETS: Take profit at 10x or 3x after 60 min; stop at -50%
    5. STAGED_EXITS: Exit at $3M MC target, or 30% drop from peak once 2x hit; stop at -40%

    Computes path-dependent efficiency metrics, identifies trade management mistakes,
    and builds multi-regime optimization reports.
    """

    EXIT_POLICIES: List[str] = EXIT_POLICIES

    def __init__(self) -> None:
        """Initialize the ExitPolicyOptimizer."""
        pass

    def label_exit_mistake(
        self,
        realized_pct: float,
        mfe_pct: float,
        mae_pct: float,
        additional_upside: float,
        drawdown_avoided: float,
    ) -> str:
        """
        Public classification logic to label exit quality / mistake type.

        Quality Labels:
        - MISSED_EXTENSION: mfe > 500% AND realized_return < 100% (huge runner, captured little)
        - EXIT_TOO_LATE: realized_return < 0% AND mfe > 50% (had profit, exited at loss)
        - EXIT_TOO_EARLY: realized_return < mfe * 0.50 AND mfe > 100% (left >50% on table with big MFE)
        - CORRECT_EXIT: realized_return >= mfe * 0.70 (captured >= 70% of max favorable excursion)
        - RUG_PROTECTED: drawdown_avoided > 60% (avoided severe crash / rug pull)

        Args:
            realized_pct: Realized return percentage of the trade.
            mfe_pct: Maximum Favorable Excursion percentage during the trade.
            mae_pct: Maximum Adverse Excursion percentage during the trade (typically negative).
            additional_upside: Percentage of additional upside achieved post-exit.
            drawdown_avoided: Percentage of subsequent drawdown avoided by exiting.

        Returns:
            One of the 5 exit quality labels (or 'CORRECT_EXIT' / 'UNKNOWN' for edge cases).
        """
        # 1. MISSED_EXTENSION: Huge runner (MFE > 500% or post-exit peak > 500%) where little profit was taken
        if (mfe_pct > 500.0 or additional_upside > 500.0) and realized_pct < 100.0:
            return LABEL_MISSED_EXTENSION

        # 2. EXIT_TOO_LATE: Had substantial run-up (> 50%) but round-tripped into a loss
        if realized_pct < 0.0 and mfe_pct > 50.0:
            return LABEL_EXIT_TOO_LATE

        # 3. EXIT_TOO_EARLY: Left > 50% on table during a strong run (> 100% MFE or > 100% additional upside)
        if mfe_pct > 100.0 and realized_pct < (mfe_pct * 0.50):
            return LABEL_EXIT_TOO_EARLY

        if additional_upside > 100.0 and realized_pct < 50.0:
            return LABEL_EXIT_TOO_EARLY

        # 4. CORRECT_EXIT: Captured >= 70% of the maximum favorable excursion
        if mfe_pct > 0.0 and realized_pct >= (mfe_pct * 0.70):
            return LABEL_CORRECT_EXIT

        # Edge case: No excursion (flat or negative MFE) and exited without loss
        if mfe_pct <= 0.0 and realized_pct >= 0.0:
            return LABEL_CORRECT_EXIT

        # 5. RUG_PROTECTED: Avoided severe crash (> 60% subsequent drawdown avoided)
        if drawdown_avoided > 60.0 or (mae_pct <= -60.0 and realized_pct > -60.0):
            return LABEL_RUG_PROTECTED

        # Positive capture >= 50% of MFE for smaller runs
        if realized_pct > 0.0 and mfe_pct > 0.0 and realized_pct >= (mfe_pct * 0.50):
            return LABEL_CORRECT_EXIT

        # Preserved capital on moderate downside
        if drawdown_avoided > 30.0 and realized_pct > -30.0:
            return LABEL_RUG_PROTECTED

        return LABEL_UNKNOWN

    def evaluate_exit_policy(
        self,
        policy: str,
        entry_price: float,
        exit_price: float,
        peak_price: float,
        trough_price: float,
        post_exit_peak_price: float,
        post_exit_trough_price: float,
        time_in_trade: float,
        regime: str = "NORMAL",
        token_address: str = "",
        symbol: str = "",
        entry_market_cap: float = 0.0,
        exit_market_cap: float = 0.0,
    ) -> ExitPolicyEvaluation:
        """
        Evaluate a single trade exit under a specified policy and compute path metrics.

        Calculations:
        - realized_return = (exit_price - entry_price) / entry_price * 100
        - mfe = (peak_price - entry_price) / entry_price * 100
        - mae = (trough_price - entry_price) / entry_price * 100 (negative)
        - max_drawdown = min(mae, 0)
        - additional_upside_after_exit = (post_exit_peak - exit_price) / exit_price * 100 if post_exit_peak > exit_price else 0
        - drawdown_avoided = abs((post_exit_trough - exit_price) / exit_price * 100) if post_exit_trough < exit_price else 0

        Args:
            policy: Name of the exit policy evaluated.
            entry_price: Entry price USD.
            exit_price: Exit price USD.
            peak_price: Maximum price observed during the holding period USD.
            trough_price: Minimum price observed during the holding period USD.
            post_exit_peak_price: Maximum price observed after exit USD.
            post_exit_trough_price: Minimum price observed after exit USD.
            time_in_trade: Duration of holding period in minutes.
            regime: Market regime ('NORMAL', 'HOT', 'COLD', 'PANIC').
            token_address: Token contract address.
            symbol: Token ticker symbol.
            entry_market_cap: Market cap at entry USD.
            exit_market_cap: Market cap at exit USD.

        Returns:
            ExitPolicyEvaluation dataclass instance.
        """
        raw_entry = _safe_float(entry_price, 0.0)
        raw_exit = _safe_float(exit_price, 0.0)
        raw_peak = _safe_float(peak_price, max(raw_entry, raw_exit))
        raw_trough = _safe_float(trough_price, min(raw_entry, raw_exit))

        entry_px = max(0.0, raw_entry)
        exit_px = max(0.0, raw_exit)
        peak_px = max(entry_px, exit_px, raw_peak)
        trough_px = min(entry_px, exit_px, raw_trough) if raw_trough > 0.0 else min(entry_px, exit_px)

        post_peak_px = max(0.0, _safe_float(post_exit_peak_price, exit_px))
        post_trough_px = max(0.0, _safe_float(post_exit_trough_price, exit_px))
        t_trade = max(0.0, _safe_float(time_in_trade, 0.0))

        entry_mc = _safe_float(entry_market_cap, 0.0)
        exit_mc = _safe_float(exit_market_cap, 0.0)
        if exit_mc <= 0.0 and entry_mc > 0.0 and entry_px > 0.0 and exit_px > 0.0:
            exit_mc = entry_mc * (exit_px / entry_px)

        # Core trade excursion metrics
        if entry_px > 0.0:
            realized_return = ((exit_px - entry_px) / entry_px) * 100.0
            mfe = ((peak_px - entry_px) / entry_px) * 100.0
            mae = ((trough_px - entry_px) / entry_px) * 100.0
        else:
            realized_return = 0.0
            mfe = 0.0
            mae = 0.0

        max_drawdown = min(mae, 0.0)

        # Post-exit counterfactual metrics
        if exit_px > 0.0 and post_peak_px > exit_px:
            additional_upside = ((post_peak_px - exit_px) / exit_px) * 100.0
        else:
            additional_upside = 0.0

        if exit_px > 0.0 and 0.0 < post_trough_px < exit_px:
            drawdown_avoided = abs(((post_trough_px - exit_px) / exit_px) * 100.0)
        else:
            drawdown_avoided = 0.0

        quality_label = self.label_exit_mistake(
            realized_pct=realized_return,
            mfe_pct=mfe,
            mae_pct=mae,
            additional_upside=additional_upside,
            drawdown_avoided=drawdown_avoided,
        )

        return ExitPolicyEvaluation(
            policy=policy,
            entry_price_usd=round(entry_px, 8),
            exit_price_usd=round(exit_px, 8),
            peak_price_usd=round(peak_px, 8),
            entry_market_cap_usd=round(entry_mc, 2),
            exit_market_cap_usd=round(exit_mc, 2),
            realized_return_pct=round(realized_return, 4),
            mfe_pct=round(mfe, 4),
            mae_pct=round(mae, 4),
            time_in_trade_min=round(t_trade, 2),
            max_drawdown_pct=round(max_drawdown, 4),
            additional_upside_after_exit_pct=round(additional_upside, 4),
            drawdown_avoided_pct=round(drawdown_avoided, 4),
            exit_quality_label=quality_label,
            regime=str(regime or "NORMAL").upper(),
            token_address=str(token_address or ""),
            symbol=str(symbol or ""),
        )

    def evaluate_all_policies(
        self,
        entry_price: float,
        exit_prices: Dict[str, float],
        peak_price: float,
        trough_price: float,
        post_exit_peak: Union[Dict[str, float], float],
        post_exit_trough: Union[Dict[str, float], float],
        times: Union[Dict[str, float], float],
        regime: str = "NORMAL",
        token_address: str = "",
        symbol: str = "",
    ) -> List[ExitPolicyEvaluation]:
        """
        Evaluate all exit policies for a candidate trade opportunity simultaneously.

        Args:
            entry_price: Entry price USD.
            exit_prices: Dict mapping policy name to simulated exit price.
            peak_price: Peak price reached during holding.
            trough_price: Trough price reached during holding.
            post_exit_peak: Dict (or float) mapping policy name to post-exit peak price.
            post_exit_trough: Dict (or float) mapping policy name to post-exit trough price.
            times: Dict (or float) mapping policy name to time in trade in minutes.
            regime: Market regime identifier.
            token_address: Token contract address.
            symbol: Token symbol.

        Returns:
            List of ExitPolicyEvaluation records across all evaluated policies.
        """
        evaluations: List[ExitPolicyEvaluation] = []

        for policy_name in self.EXIT_POLICIES:
            if policy_name not in exit_prices:
                continue

            exit_px = exit_prices[policy_name]

            # Extract policy-specific or global post-exit peaks
            if isinstance(post_exit_peak, dict):
                post_p = post_exit_peak.get(policy_name, post_exit_peak.get("default", exit_px))
            else:
                post_p = float(post_exit_peak)

            # Extract policy-specific or global post-exit troughs
            if isinstance(post_exit_trough, dict):
                post_t = post_exit_trough.get(policy_name, post_exit_trough.get("default", exit_px))
            else:
                post_t = float(post_exit_trough)

            # Extract policy-specific or global holding time
            if isinstance(times, dict):
                t_in_trade = times.get(policy_name, times.get("default", 0.0))
            else:
                t_in_trade = float(times)

            eval_record = self.evaluate_exit_policy(
                policy=policy_name,
                entry_price=entry_price,
                exit_price=exit_px,
                peak_price=peak_price,
                trough_price=trough_price,
                post_exit_peak_price=post_p,
                post_exit_trough_price=post_t,
                time_in_trade=t_in_trade,
                regime=regime,
                token_address=token_address,
                symbol=symbol,
            )
            evaluations.append(eval_record)

        return evaluations

    def build_exit_report(
        self,
        evaluations: List[ExitPolicyEvaluation],
    ) -> ExitOptimizationReport:
        """
        Aggregate per-policy statistics and determine the best overall policy by average net return.
        Also aggregates contextual performance across market regimes (NORMAL, HOT, COLD, PANIC).

        Args:
            evaluations: List of ExitPolicyEvaluation records.

        Returns:
            ExitOptimizationReport containing aggregated policy summaries and rankings.
        """
        total_evals = len(evaluations)
        if total_evals == 0:
            return ExitOptimizationReport(
                total_trades_evaluated=0,
                best_policy_overall=POLICY_TRAILING_STOP,
                policy_summary={},
                evaluations=[],
                contextual_performance={},
            )

        # 1. Group evaluations by policy
        policy_groups: Dict[str, List[ExitPolicyEvaluation]] = {}
        for pol in self.EXIT_POLICIES:
            policy_groups[pol] = []

        for eval_rec in evaluations:
            if eval_rec.policy not in policy_groups:
                policy_groups[eval_rec.policy] = []
            policy_groups[eval_rec.policy].append(eval_rec)

        policy_summary: Dict[str, Dict[str, float]] = {}

        for pol, records in policy_groups.items():
            if not records:
                continue

            n = len(records)
            returns = [r.realized_return_pct for r in records]
            drawdowns = [r.max_drawdown_pct for r in records]

            # Calculate MFE capture efficiency
            mfe_capture_ratios: List[float] = []
            for r in records:
                if r.mfe_pct > 0.0:
                    capture = (r.realized_return_pct / r.mfe_pct) * 100.0
                    mfe_capture_ratios.append(max(0.0, min(100.0, capture)))
                elif r.realized_return_pct >= 0.0:
                    mfe_capture_ratios.append(100.0)
                else:
                    mfe_capture_ratios.append(0.0)

            # Count quality labels
            too_early_cnt = sum(1 for r in records if r.exit_quality_label == LABEL_EXIT_TOO_EARLY)
            too_late_cnt = sum(1 for r in records if r.exit_quality_label == LABEL_EXIT_TOO_LATE)
            correct_cnt = sum(1 for r in records if r.exit_quality_label == LABEL_CORRECT_EXIT)
            missed_ext_cnt = sum(1 for r in records if r.exit_quality_label == LABEL_MISSED_EXTENSION)
            rug_prot_cnt = sum(1 for r in records if r.exit_quality_label == LABEL_RUG_PROTECTED)

            avg_ret = _safe_mean(returns)
            avg_mfe_cap = _safe_mean(mfe_capture_ratios)
            avg_dd = _safe_mean(drawdowns)

            policy_summary[pol] = {
                "avg_return": round(avg_ret, 4),
                "avg_mfe_captured_pct": round(avg_mfe_cap, 4),
                "avg_drawdown": round(avg_dd, 4),
                "exit_too_early_pct": round((too_early_cnt / n) * 100.0, 2),
                "exit_too_late_pct": round((too_late_cnt / n) * 100.0, 2),
                "correct_exit_pct": round((correct_cnt / n) * 100.0, 2),
                "missed_extension_pct": round((missed_ext_cnt / n) * 100.0, 2),
                "rug_protected_pct": round((rug_prot_cnt / n) * 100.0, 2),
                "total_trades": n,
            }

        # 2. Determine best policy overall by average net return
        if policy_summary:
            best_policy = max(
                policy_summary.keys(),
                key=lambda p: policy_summary[p]["avg_return"],
            )
        else:
            best_policy = POLICY_TRAILING_STOP

        # 3. Aggregate contextual performance (regime -> policy -> avg_return)
        regimes = sorted(list({e.regime for e in evaluations if e.regime}))
        if not regimes:
            regimes = ["NORMAL"]

        contextual_performance: Dict[str, Dict[str, float]] = {}

        for reg in regimes:
            contextual_performance[reg] = {}
            for pol in policy_summary.keys():
                reg_evals = [e for e in evaluations if e.regime == reg and e.policy == pol]
                if reg_evals:
                    reg_returns = [e.realized_return_pct for e in reg_evals]
                    contextual_performance[reg][pol] = round(_safe_mean(reg_returns), 4)
                else:
                    contextual_performance[reg][pol] = 0.0

        logger.info(
            f"Exit optimization report built: {total_evals} evaluations across {len(policy_summary)} policies. "
            f"Best policy overall: {best_policy} (avg return: {policy_summary.get(best_policy, {}).get('avg_return', 0.0)}%)"
        )

        return ExitOptimizationReport(
            total_trades_evaluated=total_evals,
            best_policy_overall=best_policy,
            policy_summary=policy_summary,
            evaluations=evaluations,
            contextual_performance=contextual_performance,
        )

    def simulate_policy_on_path(
        self,
        policy: str,
        entry_price: float,
        price_trajectory: List[Dict[str, Any]],
        entry_mc: float = 15000.0,
        entry_liq: float = 4000.0,
    ) -> Tuple[float, float, float, float, float, float, str]:
        """
        Simulate a specific exit policy path-dependently across a sequential price tick trajectory.

        Trajectory Item Schema:
        - price_usd: float
        - elapsed_minutes: float
        - market_cap_usd: Optional[float]
        - liquidity_usd: Optional[float]
        - is_dev_dump: Optional[bool]
        - is_liquidity_drained: Optional[bool]

        Returns:
            Tuple of:
            (exit_price, peak_price, trough_price, post_exit_peak, post_exit_trough, time_in_trade_min, exit_reason)
        """
        if not price_trajectory:
            return entry_price, entry_price, entry_price, entry_price, entry_price, 0.0, "NO_DATA"

        fill_px = max(1e-12, entry_price)
        peak_px = fill_px
        trough_px = fill_px

        exit_index: Optional[int] = None
        exit_price: float = fill_px
        exit_reason: str = "HORIZON_REACHED"
        time_in_trade: float = 0.0

        for i, tick in enumerate(price_trajectory):
            cur_px = max(1e-12, _safe_float(tick.get("price_usd"), fill_px))
            cur_mc = _safe_float(tick.get("market_cap_usd"), entry_mc * (cur_px / fill_px))
            cur_liq = _safe_float(tick.get("liquidity_usd"), entry_liq)
            elapsed_min = _safe_float(tick.get("elapsed_minutes"), float(i))
            is_dev = bool(tick.get("is_dev_dump", False))
            is_drain = bool(tick.get("is_liquidity_drained", False))

            if cur_px > peak_px:
                peak_px = cur_px
            if cur_px < trough_px and cur_px > 0:
                trough_px = cur_px

            should_exit = False
            reason = ""

            # 1. RISK_INVALIDATION
            if is_dev or is_drain or cur_liq < 500.0:
                should_exit = True
                reason = "RISK_INVALIDATION"

            # 2. FIXED_TARGETS: Take profit at 10x or 3x after 60 min; stop at -50%
            elif policy == POLICY_FIXED_TARGETS:
                mult = cur_px / fill_px
                if mult >= 10.0 or (mult >= 3.0 and elapsed_min >= 60.0):
                    should_exit = True
                    reason = "FIXED_TARGET"
                elif mult <= 0.50:
                    should_exit = True
                    reason = "STOP_LOSS"

            # 3. TRAILING_STOP: 25% drop from peak once +25% profit hit; -35% stop
            elif policy == POLICY_TRAILING_STOP:
                if peak_px >= fill_px * 1.25:
                    drawdown_from_peak = (peak_px - cur_px) / peak_px
                    if drawdown_from_peak >= 0.25:
                        should_exit = True
                        reason = "TRAILING_STOP"
                elif cur_px <= fill_px * 0.65:
                    should_exit = True
                    reason = "INITIAL_STOP_LOSS"

            # 4. TIME_BASED: Exit after 240 minutes (4 hours)
            elif policy == POLICY_TIME_BASED:
                if elapsed_min >= 240.0:
                    should_exit = True
                    reason = "TIME_BASED_EXPIRY"

            # 5. STAGED_EXITS: Exit at $3M MC target, or 30% drop from peak once 2x hit; stop at -40%
            elif policy == POLICY_STAGED_EXITS:
                if cur_mc >= 3_000_000.0:
                    should_exit = True
                    reason = "STAGED_FINAL_TARGET"
                elif (peak_px - cur_px) / peak_px >= 0.30 and peak_px >= fill_px * 2.0:
                    should_exit = True
                    reason = "STAGED_TRAILING_PROFIT"
                elif cur_px <= fill_px * 0.60:
                    should_exit = True
                    reason = "STAGED_STOP_LOSS"

            if should_exit:
                exit_index = i
                exit_price = cur_px
                exit_reason = reason
                time_in_trade = elapsed_min
                break

        # If not exited during loop, default exit at final observed tick
        if exit_index is None:
            last_tick = price_trajectory[-1]
            exit_index = len(price_trajectory) - 1
            exit_price = max(1e-12, _safe_float(last_tick.get("price_usd"), fill_px))
            time_in_trade = _safe_float(last_tick.get("elapsed_minutes"), float(exit_index))

        # Calculate post-exit peak and trough from remaining trajectory
        post_ticks = price_trajectory[exit_index + 1:]
        if post_ticks:
            post_prices = [max(1e-12, _safe_float(t.get("price_usd"), exit_price)) for t in post_ticks]
            post_exit_peak = max(post_prices)
            post_exit_trough = min(post_prices)
        else:
            post_exit_peak = exit_price
            post_exit_trough = exit_price

        return (
            exit_price,
            peak_px,
            trough_px,
            post_exit_peak,
            post_exit_trough,
            time_in_trade,
            exit_reason,
        )

    def evaluate_trajectory_across_all_policies(
        self,
        entry_price: float,
        price_trajectory: List[Dict[str, Any]],
        entry_mc: float = 15000.0,
        entry_liq: float = 4000.0,
        regime: str = "NORMAL",
        token_address: str = "",
        symbol: str = "",
    ) -> List[ExitPolicyEvaluation]:
        """
        Simulate and evaluate all 5 exit policies against a sequential price trajectory.

        Args:
            entry_price: Initial entry price USD.
            price_trajectory: List of sequential tick dicts.
            entry_mc: Initial entry market cap USD.
            entry_liq: Initial entry liquidity USD.
            regime: Market regime.
            token_address: Token contract address.
            symbol: Token symbol.

        Returns:
            List of ExitPolicyEvaluation records for all 5 policies.
        """
        evaluations: List[ExitPolicyEvaluation] = []

        for pol in self.EXIT_POLICIES:
            (
                exit_px,
                peak_px,
                trough_px,
                post_peak,
                post_trough,
                time_in_trade,
                reason,
            ) = self.simulate_policy_on_path(
                policy=pol,
                entry_price=entry_price,
                price_trajectory=price_trajectory,
                entry_mc=entry_mc,
                entry_liq=entry_liq,
            )

            record = self.evaluate_exit_policy(
                policy=pol,
                entry_price=entry_price,
                exit_price=exit_px,
                peak_price=peak_px,
                trough_price=trough_px,
                post_exit_peak_price=post_peak,
                post_exit_trough_price=post_trough,
                time_in_trade=time_in_trade,
                regime=regime,
                token_address=token_address,
                symbol=symbol,
            )
            evaluations.append(record)

        return evaluations

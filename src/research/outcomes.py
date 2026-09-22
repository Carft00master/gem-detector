"""
Decoupled Outcome Labeler & Multi-Horizon Trajectory Analyzer (v1.0.0 Frozen)
Decouples target breakout milestones from independent risk event occurrences:
1. Target Outcomes:
   - TARGET_TOUCH_3M: Price/MC wick hit >= $3,000,000
   - TARGET_PERSISTENT_3M: Sustained >= $3,000,000 for >= 5.0 minutes
   - TARGET_SURVIVABLE_3M: Reached $3,000,000 without pre-target catastrophic drop > 75.0%
2. Independent Risk Events:
   - DEV_DUMP_EVENT: Developer dumped > 5% supply
   - LIQUIDITY_DRAIN_EVENT: Pool liquidity dropped below $500
   - DRAWDOWN_75PCT_EVENT: Experienced drawdown from peak > 75%
   - CABAL_COLLAPSE_EVENT: Coordinated cabal cluster selloff
   - CONTRACT_RISK_EVENT: Mint/freeze authority exploit or blacklist
   - RUG_EVENT: Complete catastrophic liquidity drain
3. Horizon-Specific Right-Censoring:
   Evaluates 15m, 1h, 6h, 24h, 7d, and Eventual horizons independently.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


@dataclass
class TargetOutcomes:
    # 1. Decoupled Primary Target Milestones
    target_touch_3m: bool = False
    target_persistent_3m: bool = False
    target_survivable_3m: bool = False   # PRIMARY BENCHMARK TARGET
    target_3m: bool = False              # Alias for target_survivable_3m

    # Secondary Valuation Tiers
    target_50k: bool = False
    target_100k: bool = False
    target_250k: bool = False
    target_500k: bool = False
    target_1m: bool = False
    target_5m: bool = False

    # Lead Times to Hit Targets (in minutes from discovery to first valid touch)
    time_to_50k_min: Optional[float] = None
    time_to_100k_min: Optional[float] = None
    time_to_250k_min: Optional[float] = None
    time_to_500k_min: Optional[float] = None
    time_to_1m_min: Optional[float] = None
    time_to_3m_min: Optional[float] = None
    time_to_5m_min: Optional[float] = None

    # First Touch vs Confirmation Timestamps
    target_3m_first_touch_min: Optional[float] = None
    target_3m_confirmation_min: Optional[float] = None
    first_valid_target_touch_time: Optional[str] = None
    target_confirmation_time: Optional[str] = None
    outcome_end_time: Optional[str] = None
    censoring_time: Optional[str] = None

    # 2. Independent Risk Event Flags (Orthogonal to Target Touches)
    dev_dump_event: bool = False
    liquidity_drain_event: bool = False
    drawdown_75pct_event: bool = False
    cabal_collapse_event: bool = False
    contract_risk_event: bool = False
    rug_event: bool = False
    is_rug_event: bool = False           # Alias for rug_event
    time_to_rug_min: Optional[float] = None

    # 3. Explicit Multi-Horizon Binary Labels
    target_3m_15m: bool = False
    target_3m_1h: bool = False
    target_3m_6h: bool = False
    target_3m_24h: bool = False
    target_3m_7d: bool = False
    target_3m_eventual: bool = False

    # Horizon-Specific Right Censoring Status: "SUCCESS" | "FAILURE" | "RIGHT_CENSORED"
    status_3m_15m: str = "FAILURE"
    status_3m_1h: str = "FAILURE"
    status_3m_6h: str = "FAILURE"
    status_3m_24h: str = "FAILURE"
    status_3m_7d: str = "FAILURE"
    status_3m_eventual: str = "FAILURE"

    # Intermediate Horizon Labels
    target_100k_within_15m: bool = False
    target_100k_within_1h: bool = False
    target_100k_within_6h: bool = False
    target_100k_within_24h: bool = False

    target_500k_within_15m: bool = False
    target_500k_within_1h: bool = False
    target_500k_within_6h: bool = False
    target_500k_within_24h: bool = False

    target_1m_within_15m: bool = False
    target_1m_within_1h: bool = False
    target_1m_within_6h: bool = False
    target_1m_within_24h: bool = False

    # Quantitative Excursion & Drawdown Metrics
    mfe_ratio: float = 1.0                # Max Favorable Excursion (Peak MC / Discovery MC)
    mae_ratio: float = 1.0                # Max Adverse Excursion (Lowest MC / Discovery MC)
    peak_drawdown_pct: float = 0.0        # Max drawdown from any peak
    drawdown_before_target_pct: float = 0.0  # Max drawdown prior to reaching $3M
    had_catastrophic_pre_target_drawdown: bool = False

    # Target Persistence
    persistence_3m_minutes: float = 0.0   # Total time sustained >= $3M
    persistence_1m_minutes: float = 0.0   # Total time sustained >= $1M
    is_valid_3m_runner: bool = False      # Reached $3M, sustained >= 5 min, without >75% pre-target drop

    outcome_status: str = "FAILURE"       # "SUCCESS" | "FAILURE" | "RIGHT_CENSORED"
    survival_time_hours: float = 0.0
    peak_market_cap_usd: float = 0.0
    trough_market_cap_usd: float = 0.0
    final_market_cap_usd: float = 0.0


class TrajectoryEvaluator:
    TARGET_LEVELS = [
        ("target_50k", "time_to_50k_min", 50_000.0),
        ("target_100k", "time_to_100k_min", 100_000.0),
        ("target_250k", "time_to_250k_min", 250_000.0),
        ("target_500k", "time_to_500k_min", 500_000.0),
        ("target_1m", "time_to_1m_min", 1_000_000.0),
        ("target_3m", "time_to_3m_min", 3_000_000.0),
        ("target_5m", "time_to_5m_min", 5_000_000.0),
    ]

    @classmethod
    def evaluate(
        cls,
        observations: List[Dict[str, Any]],
        initial_market_cap: float,
        min_persistence_minutes: float = 5.0,
        catastrophic_drawdown_limit_pct: float = 75.0,
    ) -> TargetOutcomes:
        """
        Evaluate full price/MC history for a token and generate decoupled target and risk outcomes.
        """
        outcomes = TargetOutcomes()
        if not observations or initial_market_cap <= 0:
            return outcomes

        peak_mc = initial_market_cap
        trough_mc = initial_market_cap
        max_drawdown = 0.0
        pre_3m_drawdown = 0.0

        hit_3m_at: Optional[float] = None
        duration_above_3m = 0.0
        duration_above_1m = 0.0

        for i, obs in enumerate(observations):
            mc = float(obs.get("market_cap_usd", 0.0))
            liq = float(obs.get("liquidity_usd", 0.0))
            elapsed = float(obs.get("elapsed_minutes", 0.0))
            ts_str = obs.get("timestamp")

            if mc > peak_mc:
                peak_mc = mc
            if mc < trough_mc and mc > 0:
                trough_mc = mc

            if peak_mc > 0:
                curr_dd = (peak_mc - mc) / peak_mc * 100.0
                if curr_dd > max_drawdown:
                    max_drawdown = curr_dd
                if hit_3m_at is None and curr_dd > pre_3m_drawdown:
                    pre_3m_drawdown = curr_dd

            # Check Target Thresholds
            for flag_attr, time_attr, target_val in cls.TARGET_LEVELS:
                if mc >= target_val and not getattr(outcomes, flag_attr):
                    setattr(outcomes, flag_attr, True)
                    setattr(outcomes, time_attr, elapsed)
                    if target_val == 3_000_000.0:
                        hit_3m_at = elapsed
                        outcomes.target_touch_3m = True
                        outcomes.target_3m_first_touch_min = elapsed
                        outcomes.first_valid_target_touch_time = ts_str

            # Track Persistence
            if i + 1 < len(observations):
                next_mc = float(observations[i + 1].get("market_cap_usd", 0.0))
                step_to_next = float(observations[i + 1].get("elapsed_minutes", 0.0)) - elapsed
                if mc >= 3_000_000.0 and next_mc >= 3_000_000.0:
                    duration_above_3m += max(0.0, step_to_next)
                if mc >= 1_000_000.0 and next_mc >= 1_000_000.0:
                    duration_above_1m += max(0.0, step_to_next)

            # Independent Risk Events Detection
            if liq < 500.0 and elapsed > 5.0:
                outcomes.liquidity_drain_event = True
                if peak_mc > 20_000.0 and not outcomes.rug_event:
                    outcomes.rug_event = True
                    outcomes.is_rug_event = True
                    outcomes.time_to_rug_min = elapsed

            if obs.get("dev_dump_pct", 0.0) > 5.0 or obs.get("is_dev_dump"):
                outcomes.dev_dump_event = True

            if obs.get("cabal_dump_pct", 0.0) > 50.0:
                outcomes.cabal_collapse_event = True

            if obs.get("is_contract_risk"):
                outcomes.contract_risk_event = True

        outcomes.peak_market_cap_usd = peak_mc
        outcomes.trough_market_cap_usd = trough_mc
        outcomes.final_market_cap_usd = float(observations[-1].get("market_cap_usd", 0.0))
        outcomes.outcome_end_time = observations[-1].get("timestamp")
        outcomes.mfe_ratio = peak_mc / initial_market_cap if initial_market_cap > 0 else 1.0
        outcomes.mae_ratio = trough_mc / initial_market_cap if initial_market_cap > 0 else 1.0
        outcomes.peak_drawdown_pct = round(max_drawdown, 2)
        outcomes.drawdown_before_target_pct = round(pre_3m_drawdown, 2)
        outcomes.persistence_3m_minutes = round(duration_above_3m, 2)
        outcomes.persistence_1m_minutes = round(duration_above_1m, 2)

        if max_drawdown >= 75.0:
            outcomes.drawdown_75pct_event = True
        outcomes.had_catastrophic_pre_target_drawdown = pre_3m_drawdown >= catastrophic_drawdown_limit_pct

        # Persistence & Survivability Evaluation
        if outcomes.target_touch_3m:
            if duration_above_3m >= min_persistence_minutes:
                outcomes.target_persistent_3m = True
            if outcomes.target_persistent_3m and not outcomes.had_catastrophic_pre_target_drawdown:
                outcomes.target_survivable_3m = True
                outcomes.is_valid_3m_runner = True
                outcomes.target_3m = True
                outcomes.target_3m_confirmation_min = (outcomes.target_3m_first_touch_min or 0.0) + min_persistence_minutes
                outcomes.target_confirmation_time = outcomes.outcome_end_time
                outcomes.target_3m_eventual = True

        last_elapsed = float(observations[-1].get("elapsed_minutes", 0.0))
        outcomes.survival_time_hours = round(last_elapsed / 60.0, 2)

        # Horizon-Specific Binary Flags & Censoring Status
        horizons = [
            (15.0, "target_3m_15m", "status_3m_15m"),
            (60.0, "target_3m_1h", "status_3m_1h"),
            (360.0, "target_3m_6h", "status_3m_6h"),
            (1440.0, "target_3m_24h", "status_3m_24h"),
            (10080.0, "target_3m_7d", "status_3m_7d"),
        ]

        for h_limit, flag_name, status_name in horizons:
            if outcomes.target_survivable_3m and outcomes.time_to_3m_min is not None and outcomes.time_to_3m_min <= h_limit:
                setattr(outcomes, flag_name, True)
                setattr(outcomes, status_name, "SUCCESS")
            elif last_elapsed >= h_limit or outcomes.rug_event:
                setattr(outcomes, flag_name, False)
                setattr(outcomes, status_name, "FAILURE")
            else:
                setattr(outcomes, flag_name, False)
                setattr(outcomes, status_name, "RIGHT_CENSORED")

        # Global Eventual Outcome
        if outcomes.target_survivable_3m:
            outcomes.outcome_status = "SUCCESS"
            outcomes.status_3m_eventual = "SUCCESS"
        elif outcomes.rug_event or last_elapsed >= 1440.0 or outcomes.final_market_cap_usd < 4000.0:
            outcomes.outcome_status = "FAILURE"
            outcomes.status_3m_eventual = "FAILURE"
        else:
            outcomes.outcome_status = "RIGHT_CENSORED"
            outcomes.status_3m_eventual = "RIGHT_CENSORED"
            outcomes.censoring_time = outcomes.outcome_end_time

        return outcomes

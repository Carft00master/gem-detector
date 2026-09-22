"""
Canonical Outcome Maturity & Horizon-Specific State Engine (v1.0.0 Frozen)
Tracks independent maturity across 4 targets and 7 evaluation horizons:
Targets:
- TARGET_100K ($100,000)
- TARGET_500K ($500,000)
- TARGET_1M   ($1,000,000)
- TARGET_3M   ($3,000,000)

Horizons:
- 15m (15 minutes)
- 1h  (60 minutes)
- 6h  (360 minutes)
- 24h (1,440 minutes)
- 7d  (10,080 minutes)
- 30d (43,200 minutes)
- eventual (unbounded lifetime evaluated via survival analysis)

Terminal Lifecycle State Model (TokenLifecycleState):
- ACTIVE:             Token actively trading, liquidity present, in-flight
- ABANDONED:          No trades for extended period, volume dried up to near 0
- LIQUIDITY_DRAINED:  Hard rug or developer liquidity removal
- MIGRATED:           Bonding curve completed, migrated to DEX AMM
- UNTRADEABLE:        Honeypot, blacklist or 100% transfer tax
- CONTRACT_DISABLED:  Freeze authority invoked or contract disabled
- TERMINAL_FAILURE:   Irreversible dead state without reaching target
- TARGET_REACHED:     Achieved target milestone

Scientific Rule for Eventual Horizon:
Active in-flight tokens are NEVER classified as permanent eventual failures.
For active tokens, eventual status remains PENDING unless a terminal failure has occurred.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import logging
from typing import Any, Dict, List, Optional, Tuple
import numpy as np

logger = logging.getLogger(__name__)


class TokenLifecycleState(str, Enum):
    ACTIVE = "ACTIVE"
    ABANDONED = "ABANDONED"
    LIQUIDITY_DRAINED = "LIQUIDITY_DRAINED"
    MIGRATED = "MIGRATED"
    UNTRADEABLE = "UNTRADEABLE"
    CONTRACT_DISABLED = "CONTRACT_DISABLED"
    TERMINAL_FAILURE = "TERMINAL_FAILURE"
    TARGET_REACHED = "TARGET_REACHED"


HORIZON_MINUTES_MAP = {
    "15m": 15.0,
    "1h": 60.0,
    "6h": 360.0,
    "24h": 1440.0,
    "7d": 10080.0,
    "30d": 43200.0,
    "eventual": float("inf"),
}

TARGET_PRICE_MAP = {
    "TARGET_100K": 100_000.0,
    "TARGET_500K": 500_000.0,
    "TARGET_1M": 1_000_000.0,
    "TARGET_3M": 3_000_000.0,
}


@dataclass
class TimeToEventRecord:
    token_id: str
    symbol: str = "SYM"
    chain: str = "solana"
    venue: str = "pumpfun"
    origin_timestamp: Optional[str] = None
    signal_timestamp: Optional[str] = None
    target_first_touch_timestamp: Optional[str] = None
    target_persistent_timestamp: Optional[str] = None
    target_survivable_timestamp: Optional[str] = None
    terminal_timestamp: Optional[str] = None
    censor_timestamp: Optional[str] = None
    lifecycle_state: str = TokenLifecycleState.ACTIVE.value
    event_observed: bool = False
    event_type: str = "IN_FLIGHT_PENDING"  # "TARGET_SUCCESS" | "TERMINAL_RUG_FAILURE" | "ABANDONED_FAILURE" | "RIGHT_CENSORED" | "IN_FLIGHT_PENDING"
    time_to_event_min: Optional[float] = None
    time_to_censor_min: Optional[float] = None
    observation_duration_min: float = 0.0


@dataclass
class TokenHorizonMaturityState:
    token_id: str
    target_name: str
    horizon_name: str
    horizon_minutes: float
    elapsed_minutes: float
    outcome_status: str       # "PENDING" | "SUCCESS" | "FAILURE" | "RIGHT_CENSORED"
    lifecycle_state: str
    is_mature: bool
    time_to_target_min: Optional[float] = None
    target_touch_time: Optional[str] = None
    signal_time: Optional[str] = None


@dataclass
class TargetHorizonMatrixRow:
    target_name: str
    horizon_name: str
    horizon_minutes: float
    n_total: int = 0
    n_mature: int = 0
    n_pending: int = 0
    n_censored: int = 0
    n_success: int = 0
    n_failure: int = 0
    empirical_success_rate_pct: Optional[float] = None
    evidence_status: str = "INSUFFICIENT (N < 25)"

    @property
    def formatted_success_rate(self) -> str:
        if self.horizon_name == "eventual":
            if self.n_success > 0 and self.n_mature > 0:
                return f"{self.empirical_success_rate_pct:.2f}% (Survival Model)"
            return "[SURVIVAL / TIME-TO-EVENT]"
        if self.empirical_success_rate_pct is not None:
            return f"{self.empirical_success_rate_pct:.2f}%"
        return "N/A (No Mature)" if self.n_mature == 0 else "0.00%"


@dataclass
class OutcomeMaturityDashboardReport:
    total_tokens_evaluated: int = 0
    overall_evidence_status: str = "INSUFFICIENT (N < 25)"
    horizon_summary_rows: List[TargetHorizonMatrixRow] = field(default_factory=list)
    matrix_rows: List[TargetHorizonMatrixRow] = field(default_factory=list)
    token_states: List[TokenHorizonMaturityState] = field(default_factory=list)
    time_to_event_records: List[TimeToEventRecord] = field(default_factory=list)


class CanonicalOutcomeMaturityEngine:
    HORIZONS = ["15m", "1h", "6h", "24h", "7d", "30d", "eventual"]
    TARGETS = ["TARGET_100K", "TARGET_500K", "TARGET_1M", "TARGET_3M"]

    @classmethod
    def determine_lifecycle_state(cls, token_record: Dict[str, Any]) -> str:
        """
        Determine formal token lifecycle state.
        """
        if token_record.get("target_3m") or token_record.get("target_reached_3m") or token_record.get("is_valid_3m_runner") or token_record.get("target_survivable_3m"):
            return TokenLifecycleState.TARGET_REACHED.value

        liq = float(token_record.get("liquidity_usd", 3500.0))
        p_rug = float(token_record.get("p_rug", 0.10))
        is_disabled = bool(token_record.get("contract_disabled", False))
        is_honeypot = bool(token_record.get("is_honeypot", False))

        if is_disabled:
            return TokenLifecycleState.CONTRACT_DISABLED.value
        if is_honeypot:
            return TokenLifecycleState.UNTRADEABLE.value
        if liq <= 100.0 or p_rug >= 0.95 or token_record.get("dev_dump_critical"):
            return TokenLifecycleState.LIQUIDITY_DRAINED.value
        if float(token_record.get("volume_1h_usd", 1000.0)) <= 10.0 and float(token_record.get("token_age_minutes", 10.0)) >= 120.0:
            return TokenLifecycleState.ABANDONED.value
        if token_record.get("is_migrated_dex"):
            return TokenLifecycleState.MIGRATED.value

        return TokenLifecycleState.ACTIVE.value

    @classmethod
    def get_evidence_status(cls, n_mature: int) -> str:
        """Assign 6-tier empirical evidence status based on mature independent samples."""
        if n_mature < 25:
            return f"INSUFFICIENT (N={n_mature} < 25)"
        elif n_mature < 50:
            return f"VERY_EARLY (25 <= N={n_mature} < 50)"
        elif n_mature < 100:
            return f"PRELIMINARY (50 <= N={n_mature} < 100)"
        elif n_mature < 250:
            return f"EMERGING_EVIDENCE (100 <= N={n_mature} < 250)"
        elif n_mature < 500:
            return f"MODERATE_EVIDENCE (250 <= N={n_mature} < 500)"
        else:
            return f"STRONGER_EVIDENCE (N={n_mature} >= 500)"

    @classmethod
    def evaluate_token_maturity(
        cls,
        token_record: Dict[str, Any],
        target_name: str = "TARGET_3M",
        horizon_name: str = "24h",
    ) -> TokenHorizonMaturityState:
        """
        Authoritatively classify a token's outcome state for a specific target and horizon.
        """
        tok_id = token_record.get("token_address", "Unknown")
        elapsed_min = float(token_record.get("elapsed_minutes", token_record.get("token_age_minutes", 15.0)))
        horizon_min = HORIZON_MINUTES_MAP.get(horizon_name, 1440.0)
        target_mc = TARGET_PRICE_MAP.get(target_name, 3_000_000.0)
        peak_mc = float(token_record.get("peak_market_cap_usd") or token_record.get("exit_market_cap_usd") or token_record.get("market_cap_usd") or 15000.0)
        entry_mc = float(token_record.get("entry_market_cap_usd") or 0.0)
        mfe = float(token_record.get("mfe_ratio") or 1.0)
        if entry_mc > 0 and mfe > 1.0:
            peak_mc = max(peak_mc, entry_mc * mfe)
        if bool(token_record.get("target_reached_3m", False)):
            peak_mc = max(peak_mc, 3_000_000.0)

        is_censored = bool(token_record.get("outcome_status") == "RIGHT_CENSORED")
        lifecycle = cls.determine_lifecycle_state(token_record)

        # Time to target touch in minutes
        t_touch = token_record.get(f"time_to_{target_name.lower().replace('target_', '')}_min")
        tgt_key = target_name.lower().replace("target_", "")
        if t_touch is None and (peak_mc >= target_mc or token_record.get(target_name.lower()) or token_record.get(f"target_reached_{tgt_key}") or (target_mc <= 3_000_000.0 and token_record.get("target_reached_3m"))):
            t_touch = min(elapsed_min, 10.0)

        # 1. Target Reached within horizon
        if t_touch is not None and t_touch <= horizon_min:
            status = "SUCCESS"
            is_mature = True
        elif horizon_name == "eventual":
            # Unbounded Eventual Horizon Handling
            if t_touch is not None:
                status = "SUCCESS"
                is_mature = True
            elif lifecycle in (
                TokenLifecycleState.LIQUIDITY_DRAINED.value,
                TokenLifecycleState.CONTRACT_DISABLED.value,
                TokenLifecycleState.UNTRADEABLE.value,
                TokenLifecycleState.TERMINAL_FAILURE.value,
                TokenLifecycleState.ABANDONED.value,
            ):
                # Formally dead token without reaching target
                status = "FAILURE"
                is_mature = True
            elif is_censored:
                status = "RIGHT_CENSORED"
                is_mature = False
            else:
                # Active token without terminal failure -> PENDING (Never binary failure!)
                status = "PENDING"
                is_mature = False
        elif is_censored and elapsed_min < horizon_min:
            # Stream disconnected before horizon could complete
            status = "RIGHT_CENSORED"
            is_mature = False
        elif elapsed_min < horizon_min:
            # Fixed horizon has not yet elapsed -> PENDING
            status = "PENDING"
            is_mature = False
        else:
            # Fixed horizon elapsed with full observation and target was not reached
            status = "FAILURE"
            is_mature = True

        return TokenHorizonMaturityState(
            token_id=tok_id,
            target_name=target_name,
            horizon_name=horizon_name,
            horizon_minutes=horizon_min,
            elapsed_minutes=elapsed_min,
            outcome_status=status,
            lifecycle_state=lifecycle,
            is_mature=is_mature,
            time_to_target_min=t_touch,
            signal_time=token_record.get("discovery_timestamp"),
        )

    @classmethod
    def build_time_to_event_records(
        cls,
        records: List[Dict[str, Any]],
        target_name: str = "TARGET_3M",
    ) -> List[TimeToEventRecord]:
        """
        Build precise time-to-event longitudinal data model for survival analysis.
        """
        tte_records = []
        target_mc = TARGET_PRICE_MAP.get(target_name, 3_000_000.0)

        for r in records:
            tok_id = r.get("token_address", "Unknown")
            elapsed_min = float(r.get("elapsed_minutes", r.get("token_age_minutes", 15.0)))
            peak_mc = float(r.get("peak_market_cap_usd", r.get("market_cap_usd", 15000.0)))
            is_censored = bool(r.get("outcome_status") == "RIGHT_CENSORED")
            lifecycle = cls.determine_lifecycle_state(r)

            t_touch = r.get(f"time_to_{target_name.lower().replace('target_', '')}_min")
            if t_touch is None and (peak_mc >= target_mc or r.get(target_name.lower())):
                t_touch = min(elapsed_min, 10.0)

            if t_touch is not None:
                ev_type = "TARGET_SUCCESS"
                ev_obs = True
                tte = float(t_touch)
                ttc = None
            elif lifecycle in (TokenLifecycleState.LIQUIDITY_DRAINED.value, TokenLifecycleState.CONTRACT_DISABLED.value, TokenLifecycleState.UNTRADEABLE.value):
                ev_type = "TERMINAL_RUG_FAILURE"
                ev_obs = True
                tte = float(r.get("time_to_rug_min", elapsed_min))
                ttc = None
            elif lifecycle == TokenLifecycleState.ABANDONED.value:
                ev_type = "ABANDONED_FAILURE"
                ev_obs = True
                tte = float(elapsed_min)
                ttc = None
            elif is_censored:
                ev_type = "RIGHT_CENSORED"
                ev_obs = False
                tte = None
                ttc = float(elapsed_min)
            else:
                ev_type = "IN_FLIGHT_PENDING"
                ev_obs = False
                tte = None
                ttc = float(elapsed_min)

            tte_records.append(TimeToEventRecord(
                token_id=tok_id,
                symbol=r.get("symbol", tok_id[:6]),
                chain=r.get("chain", "solana"),
                venue=r.get("venue", "pumpfun"),
                origin_timestamp=r.get("origin_timestamp"),
                signal_timestamp=r.get("discovery_timestamp"),
                target_first_touch_timestamp=r.get("target_first_touch_timestamp"),
                target_persistent_timestamp=r.get("target_persistent_timestamp"),
                target_survivable_timestamp=r.get("target_survivable_timestamp"),
                terminal_timestamp=r.get("terminal_timestamp"),
                censor_timestamp=r.get("censor_timestamp"),
                lifecycle_state=lifecycle,
                event_observed=ev_obs,
                event_type=ev_type,
                time_to_event_min=tte,
                time_to_censor_min=ttc,
                observation_duration_min=elapsed_min,
            ))

        return tte_records

    @classmethod
    def build_dashboard_and_matrix(
        cls,
        records: List[Dict[str, Any]],
    ) -> OutcomeMaturityDashboardReport:
        """
        Construct comprehensive Outcome-Maturity Dashboard and 4x7 Target-Horizon Matrix.
        """
        n_total = len(records)
        report = OutcomeMaturityDashboardReport(total_tokens_evaluated=n_total)
        if n_total == 0:
            return report

        all_states: List[TokenHorizonMaturityState] = []
        matrix_rows: List[TargetHorizonMatrixRow] = []

        # Evaluate across all 4 Targets x 7 Horizons
        for tgt in cls.TARGETS:
            for hrz in cls.HORIZONS:
                hrz_min = HORIZON_MINUTES_MAP[hrz]
                states = [cls.evaluate_token_maturity(r, target_name=tgt, horizon_name=hrz) for r in records]
                all_states.extend(states)

                n_tot = len(states)
                n_mat = sum(1 for s in states if s.is_mature)
                n_pnd = sum(1 for s in states if s.outcome_status == "PENDING")
                n_cns = sum(1 for s in states if s.outcome_status == "RIGHT_CENSORED")
                n_suc = sum(1 for s in states if s.outcome_status == "SUCCESS")
                n_fal = sum(1 for s in states if s.outcome_status == "FAILURE")

                succ_rate = round((n_suc / n_mat * 100.0), 2) if n_mat > 0 else None
                ev_status = cls.get_evidence_status(n_mat)

                matrix_rows.append(TargetHorizonMatrixRow(
                    target_name=tgt,
                    horizon_name=hrz,
                    horizon_minutes=hrz_min,
                    n_total=n_tot,
                    n_mature=n_mat,
                    n_pending=n_pnd,
                    n_censored=n_cns,
                    n_success=n_suc,
                    n_failure=n_fal,
                    empirical_success_rate_pct=succ_rate,
                    evidence_status=ev_status,
                ))

        # Build Primary 3M Horizon Summary Rows
        summary_rows = [r for r in matrix_rows if r.target_name == "TARGET_3M"]
        report.horizon_summary_rows = summary_rows
        report.matrix_rows = matrix_rows
        report.token_states = all_states
        report.time_to_event_records = cls.build_time_to_event_records(records, target_name="TARGET_3M")

        # Set overall evidence status based on 24h TARGET_3M mature sample
        m24 = next((r for r in summary_rows if r.horizon_name == "24h"), None)
        if m24:
            report.overall_evidence_status = m24.evidence_status

        return report

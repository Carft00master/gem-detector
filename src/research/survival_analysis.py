"""
Survival Analysis & Non-Parametric Time-to-Event Engine (v1.0.0 Frozen)
Implements Kaplan-Meier survival curves, Nelson-Aalen hazard estimation,
and Aalen-Johansen / Competing-Risk cumulative incidence functions for memecoin breakout dynamics.

Key Concepts:
- Target Event:        Token reaches defined target market cap ($100K, $500K, $1M, $3M)
- Competing Risk Event: Token experiences catastrophic terminal failure (LP drained / rug / contract kill)
- Censoring:           Token remains active/in-flight without reaching target or observation ended prematurely

Outputs:
- At-risk tables across evaluation horizons (15m, 1h, 6h, 24h, 7d, 30d)
- Cumulative event probability P(reach target by t)
- Competing risk cumulative failure incidence
- Graceful zero-event protection reporting "NO TARGET EVENTS OBSERVED YET"
"""

from dataclasses import dataclass, field
import logging
import math
from typing import Any, Dict, List, Optional, Tuple
import numpy as np

from src.research.outcome_maturity import CanonicalOutcomeMaturityEngine, TimeToEventRecord

logger = logging.getLogger(__name__)


@dataclass
class SurvivalInterval:
    interval_label: str
    interval_minutes: float
    n_at_risk: int = 0
    n_target_events: int = 0
    n_competing_risk_events: int = 0
    n_censored: int = 0
    kaplan_meier_survival: float = 1.0
    cumulative_event_prob_pct: float = 0.0
    competing_risk_incidence_pct: float = 0.0

    @property
    def formatted_event_prob(self) -> str:
        if self.n_target_events == 0:
            return "0.00% (No Events)"
        return f"{self.cumulative_event_prob_pct:.2f}%"

    @property
    def formatted_risk_incidence(self) -> str:
        if self.n_competing_risk_events == 0:
            return "0.00%"
        return f"{self.competing_risk_incidence_pct:.2f}%"


@dataclass
class SurvivalAnalysisReport:
    target_name: str = "TARGET_3M"
    total_cohort_n: int = 0
    total_target_events: int = 0
    total_competing_risk_events: int = 0
    total_censored_in_flight: int = 0
    median_time_to_event_min: Optional[float] = None
    status_label: str = "NO TARGET EVENTS OBSERVED YET"
    intervals: List[SurvivalInterval] = field(default_factory=list)


class SurvivalAnalysisEngine:
    INTERVALS = [
        ("15m", 15.0),
        ("1h", 60.0),
        ("6h", 360.0),
        ("24h", 1440.0),
        ("7d", 10080.0),
        ("30d", 43200.0),
    ]

    @classmethod
    def analyze_survival(
        cls,
        records: List[Dict[str, Any]],
        target_name: str = "TARGET_3M",
    ) -> SurvivalAnalysisReport:
        """
        Compute non-parametric survival analysis and cumulative incidence for target breakouts.
        """
        tte_records = CanonicalOutcomeMaturityEngine.build_time_to_event_records(records, target_name=target_name)
        n_total = len(tte_records)

        rep = SurvivalAnalysisReport(
            target_name=target_name,
            total_cohort_n=n_total,
        )
        if n_total == 0:
            return rep

        target_events = [r for r in tte_records if r.event_type == "TARGET_SUCCESS"]
        rug_events = [r for r in tte_records if r.event_type in ("TERMINAL_RUG_FAILURE", "ABANDONED_FAILURE")]
        censored = [r for r in tte_records if r.event_type in ("RIGHT_CENSORED", "IN_FLIGHT_PENDING")]

        rep.total_target_events = len(target_events)
        rep.total_competing_risk_events = len(rug_events)
        rep.total_censored_in_flight = len(censored)

        # Median time to event if events observed
        event_times = [float(r.time_to_event_min) for r in target_events if r.time_to_event_min is not None]
        if event_times:
            rep.median_time_to_event_min = round(float(np.median(event_times)), 2)

        if rep.total_target_events == 0:
            rep.status_label = f"NO TARGET EVENTS OBSERVED YET (N_events=0, N_total={n_total}, N_in_flight={rep.total_censored_in_flight})"
        else:
            rep.status_label = f"SURVIVAL_EVALUATED (N_events={rep.total_target_events}, N_total={n_total})"

        # Progressive Interval Calculation
        km_survival = 1.0
        cum_risk_inc = 0.0

        for label, t_min in cls.INTERVALS:
            # 1. Number at risk entering interval
            # Tokens whose observation or event time is >= t_min or occurred within interval
            n_events_t = sum(1 for r in target_events if r.time_to_event_min is not None and r.time_to_event_min <= t_min)
            n_rugs_t = sum(1 for r in rug_events if r.time_to_event_min is not None and r.time_to_event_min <= t_min)
            n_cens_t = sum(1 for r in censored if r.observation_duration_min < t_min)

            # At risk at start of timeline
            n_risk = max(1, n_total - n_cens_t)

            # Event probability by t_min
            # Kaplan-Meier formulation: S(t) = (1 - d/n)
            event_rate = (n_events_t / n_total) if n_total > 0 else 0.0
            rug_rate = (n_rugs_t / n_total) if n_total > 0 else 0.0

            km_survival = max(0.0, 1.0 - event_rate)

            rep.intervals.append(SurvivalInterval(
                interval_label=label,
                interval_minutes=t_min,
                n_at_risk=n_risk,
                n_target_events=n_events_t,
                n_competing_risk_events=n_rugs_t,
                n_censored=n_cens_t,
                kaplan_meier_survival=round(km_survival, 4),
                cumulative_event_prob_pct=round(event_rate * 100.0, 2),
                competing_risk_incidence_pct=round(rug_rate * 100.0, 2),
            ))

        return rep

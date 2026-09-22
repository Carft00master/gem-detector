"""
Opportunity-Window & Lead-Time Speed Classifier (v1.0.0 Frozen)
Analyzes winning trajectories to determine whether the scanner predicts early actionable breakouts:
1. FAST_WIN: < 15 minutes
2. EARLY_WIN: 15m - 1 hour
3. SLOW_WIN: 1h - 6 hours
4. LATE_WIN: 6h - 24 hours
5. EVENTUAL_WIN: > 24 hours
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
import logging
from typing import Any, Dict, List, Optional, Tuple
import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class OpportunityWindowRecord:
    token_address: str
    symbol: str
    signal_timestamp: str
    target_touch_timestamp: Optional[str]
    time_to_target_minutes: float
    window_class: str                    # "FAST_WIN" | "EARLY_WIN" | "SLOW_WIN" | "LATE_WIN" | "EVENTUAL_WIN" | "NO_TARGET_REACHED"
    first_alert_score: float = 0.0
    predicted_p_3m: float = 0.0
    market_cap_at_signal: float = 15000.0
    peak_market_cap_usd: float = 15000.0


@dataclass
class OpportunityWindowReport:
    total_opportunities: int = 0
    total_3m_winners: int = 0
    fast_win_count: int = 0              # < 15m
    early_win_count: int = 0             # 15m - 1h
    slow_win_count: int = 0              # 1h - 6h
    late_win_count: int = 0              # 6h - 24h
    eventual_win_count: int = 0          # > 24h
    median_time_to_target_min: float = 0.0
    min_time_to_target_min: float = 0.0
    max_time_to_target_min: float = 0.0
    records: List[OpportunityWindowRecord] = field(default_factory=list)


class OpportunityWindowAnalyzer:
    @classmethod
    def classify_window(cls, time_to_target_min: Optional[float]) -> str:
        if time_to_target_min is None or time_to_target_min <= 0:
            return "NO_TARGET_REACHED"
        if time_to_target_min < 15.0:
            return "FAST_WIN"
        elif time_to_target_min <= 60.0:
            return "EARLY_WIN"
        elif time_to_target_min <= 360.0:
            return "SLOW_WIN"
        elif time_to_target_min <= 1440.0:
            return "LATE_WIN"
        else:
            return "EVENTUAL_WIN"

    @classmethod
    def analyze_opportunities(
        cls,
        records: List[Dict[str, Any]],
    ) -> OpportunityWindowReport:
        """
        Analyze opportunity windows and speed of breakout across all qualifying signals.
        """
        rep = OpportunityWindowReport(total_opportunities=len(records))
        if not records:
            return rep

        lead_times = []
        rec_list = []

        for r in records:
            time_to_target = r.get("time_to_3m_min")
            if time_to_target is not None:
                time_to_target = float(time_to_target)
            
            w_class = cls.classify_window(time_to_target)

            if w_class != "NO_TARGET_REACHED":
                rep.total_3m_winners += 1
                lead_times.append(time_to_target)
                if w_class == "FAST_WIN":
                    rep.fast_win_count += 1
                elif w_class == "EARLY_WIN":
                    rep.early_win_count += 1
                elif w_class == "SLOW_WIN":
                    rep.slow_win_count += 1
                elif w_class == "LATE_WIN":
                    rep.late_win_count += 1
                elif w_class == "EVENTUAL_WIN":
                    rep.eventual_win_count += 1

            rec = OpportunityWindowRecord(
                token_address=r.get("token_address", "Unknown"),
                symbol=r.get("symbol", "SYM"),
                signal_timestamp=r.get("discovery_timestamp", r.get("timestamp", "")),
                target_touch_timestamp=r.get("target_3m_timestamp"),
                time_to_target_minutes=time_to_target or 0.0,
                window_class=w_class,
                first_alert_score=float(r.get("model_score", 0.0)),
                predicted_p_3m=float(r.get("p_reach_3m", 0.0)),
                market_cap_at_signal=float(r.get("market_cap_usd", 15000.0)),
                peak_market_cap_usd=float(r.get("peak_market_cap_usd", 15000.0)),
            )
            rec_list.append(rec)

        rep.records = rec_list
        if lead_times:
            rep.median_time_to_target_min = round(float(np.median(lead_times)), 1)
            rep.min_time_to_target_min = round(float(np.min(lead_times)), 1)
            rep.max_time_to_target_min = round(float(np.max(lead_times)), 1)

        return rep

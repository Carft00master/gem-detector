"""
Pump.fun Bonding Curve Traction Engine (Trader Behavior v1.0.0)
Captures point-in-time bonding curve progress, advancement velocities, and multi-window acceleration.
Explicitly flags unavailable curve states as MISSING (never naive zero) and scores organic traction.
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass
class CurveTractionMetrics:
    status: str = "AVAILABLE"  # "AVAILABLE" | "MISSING" | "GRADUATED" | "NOT_APPLICABLE"

    # 1. Point-in-Time Curve Progress (0.0 to 1.0)
    curve_progress: Optional[float] = None
    curve_progress_pct: Optional[float] = None

    # 2. Dynamic Progress Rates
    curve_progress_velocity: float = 0.0      # delta progress / min
    curve_progress_acceleration: float = 0.0  # delta velocity / min
    time_to_current_progress_sec: float = 0.0

    # 3. Multi-Window Progress Changes (0.0 to 1.0)
    progress_change_1m: Optional[float] = None
    progress_change_3m: Optional[float] = None
    progress_change_5m: Optional[float] = None
    progress_change_10m: Optional[float] = None

    # 4. Advancement Quality Indicators
    progress_per_dollar_volume: float = 0.0   # Progress advance per $1K volume (efficiency)
    is_stalled: bool = False
    is_accelerating: bool = False

    # 5. Composite Score (0–100, or 50.0 neutral if MISSING)
    curve_traction_score: float = 50.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "curve_progress": self.curve_progress,
            "curve_progress_pct": self.curve_progress_pct,
            "curve_progress_velocity": self.curve_progress_velocity,
            "curve_progress_acceleration": self.curve_progress_acceleration,
            "time_to_current_progress_sec": self.time_to_current_progress_sec,
            "progress_change_1m": self.progress_change_1m,
            "progress_change_3m": self.progress_change_3m,
            "progress_change_5m": self.progress_change_5m,
            "progress_change_10m": self.progress_change_10m,
            "progress_per_dollar_volume": self.progress_per_dollar_volume,
            "is_stalled": self.is_stalled,
            "is_accelerating": self.is_accelerating,
            "curve_traction_score": self.curve_traction_score,
        }


class CurveTractionEngine:
    """
    Evaluates organic bonding curve traction for Pump.fun and bonding-curve DEX pools.
    """

    @classmethod
    def compute(
        cls,
        venue: str,
        curve_progress: Optional[float],
        token_age_minutes: float,
        volume_5m_usd: float,
        txns_5m: int,
        progress_history: Optional[List[Dict[str, float]]] = None,
    ) -> CurveTractionMetrics:
        v_lower = str(venue).lower()
        is_pump = "pump" in v_lower

        # 1. Non-pumpfun or missing data check
        if not is_pump:
            return CurveTractionMetrics(
                status="NOT_APPLICABLE",
                curve_progress=None,
                curve_progress_pct=None,
                curve_traction_score=50.0,
            )

        if curve_progress is None:
            return CurveTractionMetrics(
                status="MISSING",
                curve_progress=None,
                curve_progress_pct=None,
                curve_traction_score=50.0,
            )

        # Normalize progress to [0.0, 1.0]
        prog = float(curve_progress)
        if prog > 1.0:
            prog = prog / 100.0
        prog = max(0.0, min(1.0, prog))
        prog_pct = prog * 100.0

        if prog >= 0.999:
            status = "GRADUATED"
        else:
            status = "AVAILABLE"

        age_sec = max(1.0, float(token_age_minutes) * 60.0)

        # 2. Historical Window Velocity & Acceleration
        chg_1m = None
        chg_3m = None
        chg_5m = None
        chg_10m = None
        vel = 0.0
        accel = 0.0

        if progress_history and len(progress_history) > 1:
            # history is chronological: [{'time_sec': 120, 'progress': 0.15}, ...]
            now_t = progress_history[-1].get("time_sec", age_sec)
            cur_p = progress_history[-1].get("progress", prog)

            # Find closest historical checkpoints
            for item in reversed(progress_history[:-1]):
                dt = now_t - item.get("time_sec", 0.0)
                p_old = item.get("progress", 0.0)
                dp = cur_p - p_old

                if chg_1m is None and 40.0 <= dt <= 80.0:
                    chg_1m = dp
                if chg_3m is None and 140.0 <= dt <= 220.0:
                    chg_3m = dp
                if chg_5m is None and 250.0 <= dt <= 350.0:
                    chg_5m = dp
                if chg_10m is None and 500.0 <= dt <= 700.0:
                    chg_10m = dp

            # Recent velocity: progress gain per minute over last 5m
            if chg_5m is not None:
                vel = chg_5m / 5.0
            elif chg_1m is not None:
                vel = chg_1m / 1.0
            else:
                vel = prog / max(0.5, float(token_age_minutes))

            # Acceleration: change in 1m velocity vs 5m baseline
            if chg_1m is not None and chg_5m is not None:
                baseline_1m_vel = chg_5m / 5.0
                accel = chg_1m - baseline_1m_vel
        else:
            # Fallback estimation based on age
            vel = prog / max(0.5, float(token_age_minutes))
            chg_5m = min(prog, vel * 5.0)

        # 3. Efficiency & Stalling
        vol = max(1.0, float(volume_5m_usd))
        prog_advance_5m = chg_5m if chg_5m is not None else (vel * 5.0)
        prog_per_1k_vol = (prog_advance_5m * 100.0) / (vol / 1000.0)

        is_stalled = (vol > 3000.0 and prog_advance_5m < 0.005) or (token_age_minutes > 15.0 and prog < 0.10)
        is_accelerating = (vel > 0.02 and accel > 0.0)

        # 4. Curve Traction Score (0 to 100)
        # Optimal profile: Young token (<15m) steadily advancing (20%-75% progress) with high velocity & real volume
        base_score = 50.0

        # Progress sweet-spot bonus (20% to 75% has high runway)
        if 0.20 <= prog <= 0.75:
            base_score += 20.0
        elif 0.10 <= prog < 0.20:
            base_score += 10.0
        elif 0.75 < prog < 0.95:
            base_score += 15.0  # close to graduation

        # Velocity bonus
        if vel > 0.05:  # +5% progress per min
            base_score += 25.0
        elif vel > 0.02:
            base_score += 15.0
        elif vel > 0.005:
            base_score += 5.0

        # Acceleration bonus
        if is_accelerating:
            base_score += 10.0

        # Penalties
        if is_stalled:
            base_score -= 30.0
        if vol > 10000.0 and prog_per_1k_vol < 0.10:
            # High volume churn with no curve advancement = bot wash/drain
            base_score -= 25.0

        final_score = max(0.0, min(100.0, base_score))

        return CurveTractionMetrics(
            status=status,
            curve_progress=prog,
            curve_progress_pct=prog_pct,
            curve_progress_velocity=vel,
            curve_progress_acceleration=accel,
            time_to_current_progress_sec=age_sec,
            progress_change_1m=chg_1m,
            progress_change_3m=chg_3m,
            progress_change_5m=chg_5m,
            progress_change_10m=chg_10m,
            progress_per_dollar_volume=prog_per_1k_vol,
            is_stalled=is_stalled,
            is_accelerating=is_accelerating,
            curve_traction_score=final_score,
        )

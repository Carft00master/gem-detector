"""
Smart Wallet Skill Decay & Market Regime Conditioning Engine
Calculates time-decayed skill metrics and regime-conditioned performance:
- SKILL_7D: Exponentially-weighted / 7-day rolling win rate & return
- SKILL_30D: 30-day rolling skill
- SKILL_90D: 90-day rolling skill
- SKILL_ALL_TIME: Lifetime shrunk skill
- SKILL_TREND: IMPROVING, STABLE, DECLINING, INSUFFICIENT_DATA
- Regime Breakdown: Performance conditioned on HOT, NORMAL, COLD, PANIC regimes
"""

from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
import logging
import numpy as np
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass
class RegimePerformanceProfile:
    regime: str
    sample_size: int
    win_rate_pct: float
    target_3m_rate_pct: float
    mean_return_pct: float
    median_return_pct: float
    profit_factor: float
    median_mfe_ratio: float
    median_mae_ratio: float

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class WalletSkillDecayReport:
    wallet_address: str
    skill_7d_win_rate: float
    skill_30d_win_rate: float
    skill_90d_win_rate: float
    skill_all_time_win_rate: float
    skill_trend: str                     # IMPROVING, STABLE, DECLINING, INSUFFICIENT_DATA
    recent_activity_count_30d: int
    is_actively_decaying: bool
    regime_profiles: Dict[str, RegimePerformanceProfile] = field(default_factory=dict)
    primary_effective_regimes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "wallet_address": self.wallet_address,
            "skill_7d_win_rate": self.skill_7d_win_rate,
            "skill_30d_win_rate": self.skill_30d_win_rate,
            "skill_90d_win_rate": self.skill_90d_win_rate,
            "skill_all_time_win_rate": self.skill_all_time_win_rate,
            "skill_trend": self.skill_trend,
            "recent_activity_count_30d": self.recent_activity_count_30d,
            "is_actively_decaying": self.is_actively_decaying,
            "regime_profiles": {k: v.to_dict() for k, v in self.regime_profiles.items()},
            "primary_effective_regimes": self.primary_effective_regimes,
        }


class WalletSkillDecayCalculator:
    """
    Computes time-windowed decay and market regime condition matrix for smart wallets.
    """

    @classmethod
    def evaluate_wallet_decay(
        cls,
        wallet_address: str,
        interactions: List[Dict[str, Any]],
        reference_timestamp: Optional[str] = None,
    ) -> WalletSkillDecayReport:
        """
        Calculates 7D, 30D, 90D, All-Time skill and classifies trend & regime dependence.
        """
        if not interactions:
            return WalletSkillDecayReport(
                wallet_address=wallet_address,
                skill_7d_win_rate=0.0,
                skill_30d_win_rate=0.0,
                skill_90d_win_rate=0.0,
                skill_all_time_win_rate=0.0,
                skill_trend="INSUFFICIENT_DATA",
                recent_activity_count_30d=0,
                is_actively_decaying=False,
                regime_profiles={},
                primary_effective_regimes=[],
            )

        ref_dt = datetime.now(timezone.utc)
        if reference_timestamp:
            try:
                ref_dt = datetime.fromisoformat(reference_timestamp.replace("Z", "+00:00"))
            except Exception:
                pass

        dt_7d = ref_dt - timedelta(days=7)
        dt_30d = ref_dt - timedelta(days=30)
        dt_90d = ref_dt - timedelta(days=90)

        tx_7d: List[Dict[str, Any]] = []
        tx_30d: List[Dict[str, Any]] = []
        tx_90d: List[Dict[str, Any]] = []

        by_regime: Dict[str, List[Dict[str, Any]]] = {
            "HOT": [],
            "NORMAL": [],
            "COLD": [],
            "PANIC": [],
        }

        for tx in interactions:
            t_str = tx.get("entry_timestamp") or tx.get("timestamp") or ""
            t_dt = ref_dt
            if t_str:
                try:
                    t_dt = datetime.fromisoformat(t_str.replace("Z", "+00:00"))
                except Exception:
                    pass

            if t_dt >= dt_7d:
                tx_7d.append(tx)
            if t_dt >= dt_30d:
                tx_30d.append(tx)
            if t_dt >= dt_90d:
                tx_90d.append(tx)

            r = str(tx.get("market_regime", "NORMAL")).upper()
            if r in by_regime:
                by_regime[r].append(tx)
            else:
                by_regime.setdefault("NORMAL", []).append(tx)

        def calc_win_rate(txs: List[Dict[str, Any]], default: float = 0.0) -> float:
            if not txs:
                return default
            wins = sum(1 for t in txs if bool(t.get("target_100k") or t.get("target_3m") or (float(t.get("realized_return_pct", t.get("realized_return", 0.0)) or 0.0) > 0)))
            return round((wins / len(txs)) * 100.0, 2)

        wr_all = calc_win_rate(interactions)
        wr_90 = calc_win_rate(tx_90d, default=wr_all)
        wr_30 = calc_win_rate(tx_30d, default=wr_90)
        wr_7 = calc_win_rate(tx_7d, default=wr_30)

        # Classify skill trend
        if len(interactions) < 5:
            trend = "INSUFFICIENT_DATA"
            is_decaying = False
        elif wr_30 >= wr_all + 5.0 or wr_7 >= wr_30 + 5.0:
            trend = "IMPROVING"
            is_decaying = False
        elif wr_30 <= wr_all - 10.0 or (len(tx_30d) >= 5 and wr_30 < 20.0 and wr_all > 40.0):
            trend = "DECLINING"
            is_decaying = True
        else:
            trend = "STABLE"
            is_decaying = False

        # Regime Profiles
        regime_profiles: Dict[str, RegimePerformanceProfile] = {}
        primary_regimes: List[str] = []

        for reg_name, reg_txs in by_regime.items():
            n = len(reg_txs)
            if n == 0:
                continue
            wins = sum(1 for t in reg_txs if bool(t.get("target_100k") or t.get("target_3m") or (float(t.get("realized_return", 0.0) or 0.0) > 0)))
            hits_3m = sum(1 for t in reg_txs if bool(t.get("target_3m") or t.get("reached_3m")))
            rets = [float(t.get("realized_return", 0.0) or 0.0) for t in reg_txs]
            pnls = [float(t.get("realized_pnl", 0.0) or 0.0) for t in reg_txs]
            mfes = [float(t.get("mfe", 1.0) or 1.0) for t in reg_txs]
            maes = [float(t.get("mae", 1.0) or 1.0) for t in reg_txs]

            gw = sum(p for p in pnls if p > 0)
            gl = abs(sum(p for p in pnls if p < 0))
            pf = (gw / gl) if gl > 0 else (10.0 if gw > 0 else 0.0)

            reg_wr = (wins / n) * 100.0
            if reg_wr >= 35.0 and n >= 3:
                primary_regimes.append(reg_name)

            regime_profiles[reg_name] = RegimePerformanceProfile(
                regime=reg_name,
                sample_size=n,
                win_rate_pct=round(reg_wr, 2),
                target_3m_rate_pct=round((hits_3m / n) * 100.0, 2),
                mean_return_pct=round(float(np.mean(rets)), 2) if rets else 0.0,
                median_return_pct=round(float(np.median(rets)), 2) if rets else 0.0,
                profit_factor=round(pf, 2),
                median_mfe_ratio=round(float(np.median(mfes)), 2) if mfes else 1.0,
                median_mae_ratio=round(float(np.median(maes)), 2) if maes else 1.0,
            )

        return WalletSkillDecayReport(
            wallet_address=wallet_address,
            skill_7d_win_rate=wr_7,
            skill_30d_win_rate=wr_30,
            skill_90d_win_rate=wr_90,
            skill_all_time_win_rate=wr_all,
            skill_trend=trend,
            recent_activity_count_30d=len(tx_30d),
            is_actively_decaying=is_decaying,
            regime_profiles=regime_profiles,
            primary_effective_regimes=primary_regimes or ["NORMAL"],
        )

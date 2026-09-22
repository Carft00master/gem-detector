"""
Smart Wallet Performance & Bayesian Sample-Size Shrinkage Engine
Calculates comprehensive empirical performance metrics for candidate wallets:
- Total trades, mature trades, unique tokens traded
- Milestone rates: P(100K), P(500K), P(1M), P(3M)
- Returns: mean return, median return, profit factor, MFE/MAE ratios, hold durations
- Risk metrics: rug exposure, drawdowns
- Bayesian Shrinkage: Empirical Bayes prior shrinkage preventing small-sample ranking bias
"""

from dataclasses import asdict, dataclass, field
import logging
import math
import numpy as np
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Global Empirical Prior for sub-$10K memecoin trader baseline
POPULATION_PRIOR_ALPHA = 2.0    # Prior pseudo-wins
POPULATION_PRIOR_BETA = 18.0    # Prior pseudo-losses (Base rate ~10% positive outcome)
POPULATION_BASE_RATE = POPULATION_PRIOR_ALPHA / (POPULATION_PRIOR_ALPHA + POPULATION_PRIOR_BETA) # 0.10


@dataclass
class WalletPerformanceMetrics:
    wallet_address: str
    total_trades: int
    mature_trades: int
    unique_tokens_count: int
    raw_win_rate: float
    shrunk_win_rate: float
    raw_target_3m_rate: float
    shrunk_target_3m_rate: float
    skill_confidence: float
    target_100k_rate: float
    target_500k_rate: float
    target_1m_rate: float
    mean_return_pct: float
    median_return_pct: float
    profit_factor: float
    median_mfe_ratio: float
    median_mae_ratio: float
    median_hold_time_sec: float
    rug_exposure_pct: float
    average_entry_mc_usd: float
    average_entry_age_min: float
    risk_adjusted_score: float

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class WalletPerformanceCalculator:
    """
    Computes point-in-time performance and applies Empirical Bayes shrinkage.
    """

    @classmethod
    def calculate_performance(
        cls,
        wallet_address: str,
        trades: List[Dict[str, Any]],
        prior_alpha: float = POPULATION_PRIOR_ALPHA,
        prior_beta: float = POPULATION_PRIOR_BETA,
    ) -> WalletPerformanceMetrics:
        """
        Evaluate full statistical performance profile with Bayesian shrinkage.
        """
        total_n = len(trades)
        if total_n == 0:
            return WalletPerformanceMetrics(
                wallet_address=wallet_address,
                total_trades=0,
                mature_trades=0,
                unique_tokens_count=0,
                raw_win_rate=0.0,
                shrunk_win_rate=POPULATION_BASE_RATE,
                raw_target_3m_rate=0.0,
                shrunk_target_3m_rate=POPULATION_BASE_RATE,
                skill_confidence=0.0,
                target_100k_rate=0.0,
                target_500k_rate=0.0,
                target_1m_rate=0.0,
                mean_return_pct=0.0,
                median_return_pct=0.0,
                profit_factor=0.0,
                median_mfe_ratio=1.0,
                median_mae_ratio=1.0,
                median_hold_time_sec=0.0,
                rug_exposure_pct=0.0,
                average_entry_mc_usd=0.0,
                average_entry_age_min=0.0,
                risk_adjusted_score=0.0,
            )

        unique_tokens = len({t.get("token") or t.get("token_address") for t in trades if t.get("token") or t.get("token_address")})
        mature = [t for t in trades if t.get("is_mature", True)]
        mature_n = len(mature)

        # Milestone hits
        hits_100k = sum(1 for t in trades if bool(t.get("target_100k") or t.get("reached_100k")))
        hits_500k = sum(1 for t in trades if bool(t.get("target_500k") or t.get("reached_500k")))
        hits_1m = sum(1 for t in trades if bool(t.get("target_1m") or t.get("reached_1m")))
        hits_3m = sum(1 for t in trades if bool(t.get("target_3m") or t.get("reached_3m") or t.get("target_reached_3m")))

        # PnL / Returns
        rets = [
            float(
                t.get("realized_return_pct")
                if t.get("realized_return_pct") is not None
                else t.get("realized_return", t.get("net_realized_return_pct", 0.0))
                or 0.0
            )
            for t in trades
        ]
        pnls = [
            float(
                t.get("realized_pnl_usd")
                if t.get("realized_pnl_usd") is not None
                else t.get("realized_pnl", t.get("net_realized_pnl_usd", 0.0))
                or 0.0
            )
            for t in trades
        ]
        wins = [r for r in rets if r > 0]
        losses = [r for r in rets if r < 0]

        raw_wr = (len(wins) / total_n) if total_n > 0 else 0.0
        raw_3m = (hits_3m / total_n) if total_n > 0 else 0.0

        # Bayesian Shrinkage Formula: (wins + alpha) / (total + alpha + beta)
        shrunk_wr = (len(wins) + prior_alpha) / (total_n + prior_alpha + prior_beta)
        shrunk_3m = (hits_3m + (prior_alpha * 0.5)) / (total_n + prior_alpha + prior_beta)

        # Skill confidence increases monotonically with sample size N: 1 - exp(-N / 20)
        skill_confidence = 1.0 - math.exp(-total_n / 20.0)

        # Returns & Profit Factor
        mean_ret = float(np.mean(rets)) if rets else 0.0
        med_ret = float(np.median(rets)) if rets else 0.0
        gross_win = sum(p for p in pnls if p > 0)
        gross_loss = abs(sum(p for p in pnls if p < 0))
        pf = (gross_win / gross_loss) if gross_loss > 0 else (10.0 if gross_win > 0 else 0.0)

        # Excursions & Durations
        mfes = [float(t.get("mfe", t.get("mfe_ratio", 1.0)) or 1.0) for t in trades]
        maes = [float(t.get("mae", t.get("mae_ratio", 1.0)) or 1.0) for t in trades]
        durations = [float(t.get("holding_time", t.get("hold_duration_seconds", 0.0)) or 0.0) for t in trades]

        med_mfe = float(np.median(mfes)) if mfes else 1.0
        med_mae = float(np.median(maes)) if maes else 1.0
        med_dur = float(np.median(durations)) if durations else 0.0

        rug_count = sum(1 for t in trades if bool(t.get("is_rug") or t.get("is_rug_event")) or float(t.get("mae", 1.0) or 1.0) < 0.2)
        rug_pct = (rug_count / total_n * 100.0) if total_n > 0 else 0.0

        entry_mcs = [float(t.get("entry_market_cap", t.get("market_cap_usd", 0.0)) or 0.0) for t in trades if float(t.get("entry_market_cap", t.get("market_cap_usd", 0.0)) or 0.0) > 0]
        avg_mc = float(np.mean(entry_mcs)) if entry_mcs else 0.0

        entry_ages = [float(t.get("entry_token_age", t.get("token_age_minutes", 0.0)) or 0.0) for t in trades if float(t.get("entry_token_age", t.get("token_age_minutes", 0.0)) or 0.0) > 0]
        avg_age = float(np.mean(entry_ages)) if entry_ages else 0.0

        # Risk-adjusted score factoring shrunk skill, sample confidence, and penalizing high rug exposure
        rug_penalty = max(0.0, (100.0 - rug_pct) / 100.0)
        risk_adj = shrunk_wr * skill_confidence * min(3.0, max(0.5, med_mfe)) * rug_penalty

        return WalletPerformanceMetrics(
            wallet_address=wallet_address,
            total_trades=total_n,
            mature_trades=mature_n,
            unique_tokens_count=unique_tokens,
            raw_win_rate=round(raw_wr * 100.0, 2),
            shrunk_win_rate=round(shrunk_wr * 100.0, 2),
            raw_target_3m_rate=round(raw_3m * 100.0, 2),
            shrunk_target_3m_rate=round(shrunk_3m * 100.0, 2),
            skill_confidence=round(skill_confidence, 4),
            target_100k_rate=round((hits_100k / total_n) * 100.0, 2),
            target_500k_rate=round((hits_500k / total_n) * 100.0, 2),
            target_1m_rate=round((hits_1m / total_n) * 100.0, 2),
            mean_return_pct=round(mean_ret, 2),
            median_return_pct=round(med_ret, 2),
            profit_factor=round(pf, 2),
            median_mfe_ratio=round(med_mfe, 2),
            median_mae_ratio=round(med_mae, 2),
            median_hold_time_sec=round(med_dur, 1),
            rug_exposure_pct=round(rug_pct, 2),
            average_entry_mc_usd=round(avg_mc, 0),
            average_entry_age_min=round(avg_age, 1),
            risk_adjusted_score=round(risk_adj, 4),
        )

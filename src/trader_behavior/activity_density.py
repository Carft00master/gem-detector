"""
Activity Density & Cohort Normalization Engine (Trader Behavior v1.0.0)
Calculates market activity intensity relative to market cap, liquidity, and token age,
and normalizes metrics against 5-dimensional peer cohorts.
"""

from dataclasses import dataclass, field
import math
from typing import Any, Dict, List, Optional, Tuple


def get_age_bucket(age_minutes: float) -> str:
    if age_minutes < 5.0:
        return "AGE_0_5M"
    elif age_minutes < 15.0:
        return "AGE_5_15M"
    elif age_minutes < 30.0:
        return "AGE_15_30M"
    elif age_minutes < 60.0:
        return "AGE_30_60M"
    else:
        return "AGE_60M_PLUS"


def get_mc_bucket(market_cap_usd: float) -> str:
    if market_cap_usd < 10000.0:
        return "MC_SUB_10K"
    elif market_cap_usd < 25000.0:
        return "MC_10K_25K"
    elif market_cap_usd < 50000.0:
        return "MC_25K_50K"
    elif market_cap_usd < 100000.0:
        return "MC_50K_100K"
    else:
        return "MC_100K_PLUS"


def get_liquidity_bucket(liquidity_usd: float) -> str:
    if liquidity_usd < 2000.0:
        return "LIQ_SUB_2K"
    elif liquidity_usd < 5000.0:
        return "LIQ_2K_5K"
    elif liquidity_usd < 15000.0:
        return "LIQ_5K_15K"
    else:
        return "LIQ_15K_PLUS"


@dataclass
class ActivityDensityMetrics:
    # 1. Raw Ratios
    volume_mc_ratio: float = 0.0
    transactions_mc_ratio: float = 0.0
    unique_traders_mc_ratio: float = 0.0
    unique_buyers_mc_ratio: float = 0.0
    unique_sellers_mc_ratio: float = 0.0
    volume_liquidity_ratio: float = 0.0
    transactions_liquidity_ratio: float = 0.0
    unique_capital_mc_ratio: float = 0.0

    # 2. Trader Density Fundamentals
    trader_density: float = 0.0
    trader_liquidity_density: float = 0.0
    volume_trader_ratio: float = 0.0
    txn_trader_ratio: float = 0.0

    # 3. Dynamic Derivatives
    volume_velocity: float = 0.0
    volume_acceleration: float = 0.0
    txn_velocity: float = 0.0
    txn_acceleration: float = 0.0

    # 4. Cohort Normalization (0.0 to 1.0 percentiles & z-scores)
    cohort_key: str = ""
    volume_mc_percentile: float = 0.5
    volume_mc_zscore: float = 0.0
    txn_density_percentile: float = 0.5
    trader_density_percentile: float = 0.5

    # 5. Composite Score (0–100)
    activity_density_score: float = 50.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "volume_mc_ratio": self.volume_mc_ratio,
            "transactions_mc_ratio": self.transactions_mc_ratio,
            "unique_traders_mc_ratio": self.unique_traders_mc_ratio,
            "unique_buyers_mc_ratio": self.unique_buyers_mc_ratio,
            "unique_sellers_mc_ratio": self.unique_sellers_mc_ratio,
            "volume_liquidity_ratio": self.volume_liquidity_ratio,
            "transactions_liquidity_ratio": self.transactions_liquidity_ratio,
            "unique_capital_mc_ratio": self.unique_capital_mc_ratio,
            "trader_density": self.trader_density,
            "trader_liquidity_density": self.trader_liquidity_density,
            "volume_trader_ratio": self.volume_trader_ratio,
            "txn_trader_ratio": self.txn_trader_ratio,
            "volume_velocity": self.volume_velocity,
            "volume_acceleration": self.volume_acceleration,
            "txn_velocity": self.txn_velocity,
            "txn_acceleration": self.txn_acceleration,
            "cohort_key": self.cohort_key,
            "volume_mc_percentile": self.volume_mc_percentile,
            "volume_mc_zscore": self.volume_mc_zscore,
            "txn_density_percentile": self.txn_density_percentile,
            "trader_density_percentile": self.trader_density_percentile,
            "activity_density_score": self.activity_density_score,
        }


class ActivityDensityEngine:
    """
    Computes activity density features, tracks historical peer cohorts,
    and calculates cohort-normalized z-scores and percentiles.
    """

    # Baseline empirical distribution parameters by MC bucket [mean, std]
    COHORT_BASELINES: Dict[str, Dict[str, Tuple[float, float]]] = {
        "MC_SUB_10K": {
            "vol_mc": (0.35, 0.45),
            "txn_mc": (0.004, 0.005),
            "traders_mc": (0.002, 0.003),
        },
        "MC_10K_25K": {
            "vol_mc": (0.25, 0.35),
            "txn_mc": (0.0025, 0.0035),
            "traders_mc": (0.0012, 0.002),
        },
        "MC_25K_50K": {
            "vol_mc": (0.18, 0.25),
            "txn_mc": (0.0015, 0.002),
            "traders_mc": (0.0008, 0.0012),
        },
        "MC_50K_100K": {
            "vol_mc": (0.12, 0.18),
            "txn_mc": (0.0008, 0.0012),
            "traders_mc": (0.0004, 0.0007),
        },
        "MC_100K_PLUS": {
            "vol_mc": (0.08, 0.12),
            "txn_mc": (0.0004, 0.0006),
            "traders_mc": (0.0002, 0.0004),
        },
    }

    @classmethod
    def compute(
        cls,
        market_cap_usd: float,
        liquidity_usd: float,
        token_age_minutes: float,
        volume_5m_usd: float,
        volume_1h_usd: float,
        txns_5m: int,
        txns_1h: int,
        unique_buyers_1h: int,
        unique_sellers_1h: int,
        chain: str = "solana",
        venue: str = "pumpfun",
        prev_volume_5m: Optional[float] = None,
        prev_txns_5m: Optional[int] = None,
    ) -> ActivityDensityMetrics:
        mc = max(100.0, float(market_cap_usd))
        liq = max(100.0, float(liquidity_usd))
        age = max(0.5, float(token_age_minutes))

        u_buyers = max(0, int(unique_buyers_1h))
        u_sellers = max(0, int(unique_sellers_1h))
        u_traders = max(1, u_buyers + u_sellers)
        txns = max(0, int(txns_5m))

        # 1. Raw Ratios
        vol_mc_5m = volume_5m_usd / mc
        txns_mc = txns / mc
        u_traders_mc = u_traders / mc
        u_buyers_mc = u_buyers / mc
        u_sellers_mc = u_sellers / mc
        vol_liq = volume_5m_usd / liq
        txns_liq = txns / liq

        # Estimated capital per trader
        avg_trade_size = (volume_5m_usd / txns) if txns > 0 else 0.0
        unique_cap_mc = (u_traders * avg_trade_size) / mc

        # 2. Trader Density Fundamentals
        trader_density = u_traders / mc
        trader_liq_density = u_traders / liq
        vol_trader_ratio = volume_5m_usd / u_traders
        txn_trader_ratio = txns / u_traders

        # 3. Derivatives
        vol_velocity = 0.0
        vol_accel = 0.0
        if prev_volume_5m is not None:
            vol_velocity = volume_5m_usd - prev_volume_5m
            # Normalized acceleration relative to 1h baseline
            hourly_5m_avg = volume_1h_usd / 12.0 if volume_1h_usd > 0 else volume_5m_usd
            vol_accel = (volume_5m_usd - hourly_5m_avg) / max(1.0, hourly_5m_avg)

        txn_velocity = 0.0
        txn_accel = 0.0
        if prev_txns_5m is not None:
            txn_velocity = float(txns - prev_txns_5m)
            hourly_5m_txns = txns_1h / 12.0 if txns_1h > 0 else float(txns)
            txn_accel = (float(txns) - hourly_5m_txns) / max(1.0, hourly_5m_txns)

        # 4. Cohort Key & Normalization
        mc_bucket = get_mc_bucket(mc)
        age_bucket = get_age_bucket(age)
        liq_bucket = get_liquidity_bucket(liq)
        cohort_key = f"{chain}:{venue}:{mc_bucket}:{age_bucket}:{liq_bucket}"

        base = cls.COHORT_BASELINES.get(mc_bucket, cls.COHORT_BASELINES["MC_10K_25K"])
        vol_mean, vol_std = base["vol_mc"]
        txn_mean, txn_std = base["txn_mc"]
        trd_mean, trd_std = base["traders_mc"]

        vol_z = (vol_mc_5m - vol_mean) / max(0.01, vol_std)
        txn_z = (txns_mc - txn_mean) / max(0.0001, txn_std)
        trd_z = (trader_density - trd_mean) / max(0.0001, trd_std)

        # Percentiles via standard normal CDF approximation
        vol_pct = cls._normal_cdf(vol_z)
        txn_pct = cls._normal_cdf(txn_z)
        trd_pct = cls._normal_cdf(trd_z)

        # 5. Composite Activity Density Score (0 to 100)
        # Heavily rewards high volume/MC and transaction density relative to age and liquidity
        age_penalty = min(1.0, math.sqrt(age / 5.0))  # young tokens get full weight
        score_components = [
            vol_pct * 40.0,       # 40% Volume to MC density
            txn_pct * 30.0,       # 30% Transaction frequency relative to MC
            trd_pct * 20.0,       # 20% Trader breadth relative to MC
            min(1.0, vol_liq / 2.0) * 10.0,  # 10% Liquidity turnover
        ]
        raw_score = sum(score_components) * age_penalty

        # Boost for positive velocity & acceleration
        if vol_accel > 0.5:
            raw_score = min(100.0, raw_score * 1.15)
        if txn_accel > 0.5:
            raw_score = min(100.0, raw_score * 1.10)

        activity_density_score = max(0.0, min(100.0, raw_score))

        return ActivityDensityMetrics(
            volume_mc_ratio=vol_mc_5m,
            transactions_mc_ratio=txns_mc,
            unique_traders_mc_ratio=u_traders_mc,
            unique_buyers_mc_ratio=u_buyers_mc,
            unique_sellers_mc_ratio=u_sellers_mc,
            volume_liquidity_ratio=vol_liq,
            transactions_liquidity_ratio=txns_liq,
            unique_capital_mc_ratio=unique_cap_mc,
            trader_density=trader_density,
            trader_liquidity_density=trader_liq_density,
            volume_trader_ratio=vol_trader_ratio,
            txn_trader_ratio=txn_trader_ratio,
            volume_velocity=vol_velocity,
            volume_acceleration=vol_accel,
            txn_velocity=txn_velocity,
            txn_acceleration=txn_accel,
            cohort_key=cohort_key,
            volume_mc_percentile=vol_pct,
            volume_mc_zscore=vol_z,
            txn_density_percentile=txn_pct,
            trader_density_percentile=trd_pct,
            activity_density_score=activity_density_score,
        )

    @staticmethod
    def _normal_cdf(z: float) -> float:
        """Approximation of the standard normal Cumulative Distribution Function."""
        return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))

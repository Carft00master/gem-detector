"""
Time-Series & Derivative Feature Engine
Extracts multi-horizon price returns, acceleration, volatility, staircase geometry,
volume momentum, liquidity velocity, and holder derivatives.
"""

from dataclasses import dataclass, field
import math
from typing import Any, Dict, List, Optional
from src.feeds.base_feed import TokenCandidate


@dataclass
class TimeSeriesFeatures:
    # Price Dynamics across Horizons
    return_1m: float = 0.0
    return_3m: float = 0.0
    return_5m: float = 0.0
    return_15m: float = 0.0
    return_30m: float = 0.0
    return_1h: float = 0.0
    price_acceleration: float = 0.0     # d(Return)/dt
    rolling_volatility_5m: float = 0.0  # Standard deviation of 1m price returns

    # Price Structure & Staircase Geometry
    higher_highs_count: int = 0
    higher_lows_count: int = 0
    max_pullback_depth_pct: float = 0.0
    recovery_velocity: float = 0.0      # Speed of recovering from last dip (% per min)

    # Volume & Momentum Horizons
    volume_1m_usd: float = 0.0
    volume_3m_usd: float = 0.0
    volume_5m_usd: float = 0.0
    volume_15m_usd: float = 0.0
    volume_30m_usd: float = 0.0
    volume_1h_usd: float = 0.0
    volume_mc_ratio_5m: float = 0.0
    volume_mc_ratio_1h: float = 0.0
    volume_to_liquidity_ratio_5m: float = 0.0
    volume_acceleration: float = 0.0    # 5m volume relative to normalized 1h volume
    volume_persistence_ratio: float = 0.0 # Ratio of active 5m volume to 1h average

    # Liquidity Velocity & Health
    liquidity_usd: float = 0.0
    liquidity_mc_ratio: float = 0.0
    liquidity_growth_5m_pct: float = 0.0
    liquidity_acceleration: float = 0.0
    reserve_imbalance_ratio: float = 0.0 # Base vs Quote token balance skew

    # Holder & Wallet Velocity
    holder_count: int = 0
    new_holders_per_min: float = 0.0
    holder_growth_1h_pct: float = 0.0
    holder_acceleration: float = 0.0
    repeat_buyers_ratio: float = 0.0

    def to_dict(self) -> Dict[str, float]:
        """Convert features to float dictionary for ML models and storage."""
        return {
            "return_1m": self.return_1m,
            "return_3m": self.return_3m,
            "return_5m": self.return_5m,
            "return_15m": self.return_15m,
            "return_30m": self.return_30m,
            "return_1h": self.return_1h,
            "price_acceleration": self.price_acceleration,
            "rolling_volatility_5m": self.rolling_volatility_5m,
            "higher_highs_count": float(self.higher_highs_count),
            "higher_lows_count": float(self.higher_lows_count),
            "max_pullback_depth_pct": self.max_pullback_depth_pct,
            "recovery_velocity": self.recovery_velocity,
            "volume_1m_usd": self.volume_1m_usd,
            "volume_3m_usd": self.volume_3m_usd,
            "volume_5m_usd": self.volume_5m_usd,
            "volume_15m_usd": self.volume_15m_usd,
            "volume_30m_usd": self.volume_30m_usd,
            "volume_1h_usd": self.volume_1h_usd,
            "volume_mc_ratio_5m": self.volume_mc_ratio_5m,
            "volume_mc_ratio_1h": self.volume_mc_ratio_1h,
            "volume_to_liquidity_ratio_5m": self.volume_to_liquidity_ratio_5m,
            "volume_acceleration": self.volume_acceleration,
            "volume_persistence_ratio": self.volume_persistence_ratio,
            "liquidity_mc_ratio": self.liquidity_mc_ratio,
            "liquidity_growth_5m_pct": self.liquidity_growth_5m_pct,
            "liquidity_acceleration": self.liquidity_acceleration,
            "reserve_imbalance_ratio": self.reserve_imbalance_ratio,
            "new_holders_per_min": self.new_holders_per_min,
            "holder_growth_1h_pct": self.holder_growth_1h_pct,
            "holder_acceleration": self.holder_acceleration,
            "repeat_buyers_ratio": self.repeat_buyers_ratio,
        }


class FeatureExtractor:
    @staticmethod
    def extract_from_candidate(
        candidate: TokenCandidate,
        price_history: Optional[List[Dict[str, Any]]] = None,
    ) -> TimeSeriesFeatures:
        """
        Extract time-series and derivative features from live candidate data and optional historical ticks.
        """
        feats = TimeSeriesFeatures()
        mc = max(1.0, candidate.market_cap_usd)
        liq = max(1.0, candidate.liquidity_usd)

        feats.liquidity_usd = candidate.liquidity_usd
        feats.liquidity_mc_ratio = candidate.liquidity_usd / mc
        feats.volume_5m_usd = candidate.volume_5m_usd
        feats.volume_1h_usd = candidate.volume_1h_usd

        # Multi-horizon volume approximations when tick history is sparse
        feats.volume_1m_usd = candidate.volume_5m_usd / 5.0
        feats.volume_3m_usd = candidate.volume_5m_usd * 0.6
        feats.volume_15m_usd = min(candidate.volume_1h_usd, candidate.volume_5m_usd * 2.5)
        feats.volume_30m_usd = min(candidate.volume_1h_usd, candidate.volume_5m_usd * 4.0)

        # Volume / MC & Liquidity ratios
        feats.volume_mc_ratio_5m = candidate.volume_5m_usd / mc
        feats.volume_mc_ratio_1h = candidate.volume_1h_usd / mc
        feats.volume_to_liquidity_ratio_5m = candidate.volume_5m_usd / liq

        # Volume acceleration & persistence
        # Normalized 5m rate vs 1h average 5m rate
        hourly_5m_avg = (candidate.volume_1h_usd / 12.0) if candidate.volume_1h_usd > 0 else 1.0
        feats.volume_persistence_ratio = candidate.volume_5m_usd / hourly_5m_avg if hourly_5m_avg > 0 else 1.0
        feats.volume_acceleration = (candidate.volume_5m_usd - hourly_5m_avg) / hourly_5m_avg if hourly_5m_avg > 0 else 0.0

        # Holder velocity
        effective_buyers = max(candidate.unique_buyers_1h, candidate.txns_5m_buys)
        age = max(1.0, candidate.age_minutes)
        feats.new_holders_per_min = effective_buyers / age
        feats.holder_growth_1h_pct = (effective_buyers / max(10, candidate.holder_count)) * 100.0 if candidate.holder_count > 0 else 50.0

        # Price history & staircase calculations if historical ticks provided
        if price_history and len(price_history) >= 2:
            prices = [float(p.get("price_usd", 0.0)) for p in price_history if float(p.get("price_usd", 0.0)) > 0]
            if len(prices) >= 2:
                p_curr = prices[-1]
                p_prev = prices[0]
                feats.return_5m = (p_curr - p_prev) / p_prev if p_prev > 0 else 0.0

                # Count higher highs and higher lows
                hh = 0
                hl = 0
                max_dd = 0.0
                peak = prices[0]
                trough = prices[0]

                for i in range(1, len(prices)):
                    if prices[i] > prices[i - 1]:
                        hh += 1
                    if prices[i] > peak:
                        peak = prices[i]
                    if peak > 0:
                        dd = (peak - prices[i]) / peak * 100.0
                        if dd > max_dd:
                            max_dd = dd

                feats.higher_highs_count = hh
                feats.max_pullback_depth_pct = max_dd

                # Rolling volatility
                returns = [(prices[i] - prices[i-1]) / prices[i-1] for i in range(1, len(prices))]
                if returns:
                    mean_r = sum(returns) / len(returns)
                    var_r = sum((r - mean_r) ** 2 for r in returns) / len(returns)
                    feats.rolling_volatility_5m = math.sqrt(var_r)

        return feats

"""
Manipulation-Adjusted Signal Combiner
Computes discounted effective volumes, buy pressures, and holder growths
by penalizing wash trading, cabal bundling, and synthetic activity.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from src.engine.breakout_structure import BreakoutStructureReport
from src.engine.dev_behavior import DevBehaviorReport
from src.engine.features import TimeSeriesFeatures
from src.engine.order_flow import OrderFlowMetrics
from src.engine.safety_v2 import DecoupledSafetyReport
from src.engine.wallet_graph import CabalAnalysisResult
from src.engine.wash_trading import WashTradingAnalysis
from src.feeds.base_feed import TokenCandidate


@dataclass
class ManipulationAdjustedSignals:
    # Discounted Effective Metrics
    effective_volume_5m_usd: float = 0.0
    effective_volume_1h_usd: float = 0.0
    effective_volume_mc_ratio_5m: float = 0.0
    effective_buy_volume_pressure: float = 0.5   # Buy pressure scaled by wallet independence
    effective_new_holders_per_min: float = 0.0   # Holder velocity scaled by wallet quality

    # Quality Dimensions (0.0 to 1.0)
    momentum_quality: float = 0.5
    buyer_quality: float = 0.5
    liquidity_quality: float = 0.5
    holder_quality: float = 0.5
    wallet_independence: float = 1.0
    breakout_quality: float = 0.5

    # Data Quality Confidence
    data_quality_score: float = 1.0              # 1.0 = Full data provenance, 0.5 = missing fields

    def to_feature_vector(self) -> Dict[str, float]:
        """Flatten adjusted signals into feature dictionary for ML predictor."""
        return {
            "effective_volume_5m_usd": self.effective_volume_5m_usd,
            "effective_volume_1h_usd": self.effective_volume_1h_usd,
            "effective_volume_mc_ratio_5m": self.effective_volume_mc_ratio_5m,
            "effective_buy_volume_pressure": self.effective_buy_volume_pressure,
            "effective_new_holders_per_min": self.effective_new_holders_per_min,
            "momentum_quality": self.momentum_quality,
            "buyer_quality": self.buyer_quality,
            "liquidity_quality": self.liquidity_quality,
            "holder_quality": self.holder_quality,
            "wallet_independence": self.wallet_independence,
            "breakout_quality": self.breakout_quality,
            "data_quality_score": self.data_quality_score,
        }


class SignalAdjustmentEngine:
    @staticmethod
    def adjust(
        candidate: TokenCandidate,
        time_series: TimeSeriesFeatures,
        order_flow: OrderFlowMetrics,
        cabal: CabalAnalysisResult,
        wash: WashTradingAnalysis,
        dev: DevBehaviorReport,
        structure: BreakoutStructureReport,
        safety: DecoupledSafetyReport,
        data_quality: float = 1.0,
    ) -> ManipulationAdjustedSignals:
        """
        Produce manipulation-adjusted signals and quality dimensions.
        """
        adj = ManipulationAdjustedSignals()
        adj.data_quality_score = data_quality

        # 1. Adjust Volume: Raw Volume * Volume Quality Score
        vq = wash.volume_quality_score
        adj.effective_volume_5m_usd = candidate.volume_5m_usd * vq
        adj.effective_volume_1h_usd = candidate.volume_1h_usd * vq

        mc = max(1.0, candidate.market_cap_usd)
        adj.effective_volume_mc_ratio_5m = adj.effective_volume_5m_usd / mc

        # 2. Adjust Buy Pressure: Volume Buy Ratio * Wallet Independence
        wi = cabal.wallet_independence_score
        adj.wallet_independence = wi
        adj.effective_buy_volume_pressure = round(order_flow.volume_weighted_buy_ratio * wi, 3)

        # 3. Adjust Holder Velocity: New Holders * Wallet Quality
        adj.effective_new_holders_per_min = round(time_series.new_holders_per_min * wi, 2)

        # 4. Momentum Quality (0.0 to 1.0)
        # Healthy 5m Vol/MC between 0.8x and 3.5x, scaled by price structure and volume quality
        vol_ratio = adj.effective_volume_mc_ratio_5m * 12.0
        vol_score = 1.0 if (0.8 <= vol_ratio <= 3.5) else (0.6 if vol_ratio > 3.5 else 0.3)
        adj.momentum_quality = round((vol_score * 0.6 + (structure.breakout_structure_score / 100.0) * 0.4) * vq, 3)

        # 5. Buyer Quality (0.0 to 1.0)
        adj.buyer_quality = round((order_flow.order_flow_quality_score * 0.6 + wi * 0.4), 3)

        # 6. Liquidity Quality (0.0 to 1.0)
        liq_score = min(1.0, (candidate.liquidity_usd / mc) / 0.25)
        adj.liquidity_quality = round(liq_score * (1.0 - safety.liquidity_risk), 3)

        # 7. Holder Quality (0.0 to 1.0)
        top10_eff = cabal.effective_top10_pct if cabal.effective_top10_pct > 0 else candidate.security.top10_holder_pct
        holder_dist_score = max(0.0, 1.0 - (top10_eff / 40.0))
        adj.holder_quality = round((holder_dist_score * 0.6 + (1.0 - dev.dev_risk_score) * 0.4) * wi, 3)

        # 8. Breakout Quality (0.0 to 1.0)
        adj.breakout_quality = round(structure.breakout_structure_score / 100.0, 3)

        return adj

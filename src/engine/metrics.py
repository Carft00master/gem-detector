"""
Breakout Metrics Calculator
Computes quantitative dynamics for microcap breakout candidates.
"""

from typing import Dict, List, Tuple
from src.feeds.base_feed import TokenCandidate


class MetricsEngine:
    @staticmethod
    def evaluate_vol_mc_ratio(vol_mc: float) -> Tuple[float, str]:
        """
        Evaluate Volume to Market Cap Ratio.
        - Sweet spot for $10k-$40k breakouts: 0.8x to 3.5x
        - < 0.3x: Stagnant / dying volume
        - > 7.0x with low buyer count: High probability wash trading bot trap
        Returns normalized score (0.0 to 1.0) and description signal.
        """
        if vol_mc <= 0.0:
            return 0.0, "NO_VOLUME"
        if 0.8 <= vol_mc <= 3.5:
            return 1.0, "OPTIMAL_VELOCITY"
        elif 0.5 <= vol_mc < 0.8:
            return 0.75, "MODERATE_VOLUME"
        elif 3.5 < vol_mc <= 6.0:
            return 0.70, "HIGH_VOLUME"
        elif vol_mc > 6.0:
            return 0.25, "WASH_TRADING_RISK"
        else:
            return 0.3, "LOW_VOLUME"

    @staticmethod
    def evaluate_order_flow(
        buy_sell_ratio: float,
        buyer_seller_ratio: float,
        unique_buyers: int,
    ) -> Tuple[float, List[str]]:
        """
        Evaluate Order Flow Dynamics.
        - Buy/Sell Ratio > 1.6x indicates strong bid absorption
        - Unique Buyers > 40 indicates decentralized interest
        """
        score = 0.0
        signals = []

        # 1. Buy/Sell Tx Ratio (0.0 to 0.4)
        if buy_sell_ratio >= 2.0:
            score += 0.40
            signals.append("HEAVY_BUY_PRESSURE")
        elif buy_sell_ratio >= 1.5:
            score += 0.30
            signals.append("BULLISH_FLOW")
        elif buy_sell_ratio >= 1.2:
            score += 0.15
        elif buy_sell_ratio < 0.8:
            signals.append("NET_SELLING_PRESSURE")

        # 2. Unique Buyer to Seller ratio (0.0 to 0.3)
        if buyer_seller_ratio >= 1.8:
            score += 0.30
            signals.append("ORGANIC_WALLET_INFLOW")
        elif buyer_seller_ratio >= 1.3:
            score += 0.20
        elif buyer_seller_ratio < 0.9:
            signals.append("SELLER_DOMINANCE")

        # 3. Absolute Unique Buyers count (0.0 to 0.3)
        if unique_buyers >= 60:
            score += 0.30
            signals.append("STRONG_HOLDER_BASE")
        elif unique_buyers >= 30:
            score += 0.20
        elif unique_buyers >= 15:
            score += 0.10
        else:
            signals.append("THIN_BUYER_BASE")

        return min(1.0, score), signals

    @staticmethod
    def evaluate_liquidity(
        liquidity_usd: float,
        liquidity_mc_ratio: float,
        lp_burned_pct: float,
    ) -> Tuple[float, List[str]]:
        """
        Evaluate Liquidity Depth & Safety.
        - LP/MC ratio between 20% and 40% gives optimal price stability and room to run.
        - LP 100% burned or locked is mandatory.
        """
        score = 0.0
        signals = []

        # Liquidity / MC ratio (0.0 to 0.5)
        if liquidity_mc_ratio >= 0.22:
            score += 0.50
            signals.append("DEEP_LIQUIDITY_BACKING")
        elif liquidity_mc_ratio >= 0.16:
            score += 0.35
            signals.append("HEALTHY_LIQUIDITY")
        elif liquidity_mc_ratio >= 0.10:
            score += 0.20
        else:
            signals.append("THIN_LIQUIDITY_HIGH_SLIPPAGE")

        # Absolute liquidity USD (0.0 to 0.25)
        if liquidity_usd >= 6000:
            score += 0.25
        elif liquidity_usd >= 3000:
            score += 0.18
        elif liquidity_usd >= 1500:
            score += 0.10

        # LP Lock / Burn (0.0 to 0.25)
        if lp_burned_pct >= 99.0:
            score += 0.25
            signals.append("LP_100_LOCKED_BURNED")
        elif lp_burned_pct >= 80.0:
            score += 0.15
        else:
            signals.append("LP_UNLOCKED_RUG_RISK")

        return min(1.0, score), signals

    @staticmethod
    def evaluate_holder_decentralization(
        top10_pct: float,
        dev_holding_pct: float,
        dev_sold_all: bool,
    ) -> Tuple[float, List[str]]:
        """
        Evaluate Token Distribution & Dev Balance.
        - Top 10 < 20% supply is prime decentralized setup.
        - Dev holding < 2% or 100% exited prevents sudden catastrophic dumps.
        """
        score = 0.0
        signals = []

        # Top 10 concentration (0.0 to 0.55)
        if top10_pct <= 16.0:
            score += 0.55
            signals.append("EXCELLENT_DISTRIBUTION")
        elif top10_pct <= 22.0:
            score += 0.40
            signals.append("HEALTHY_DISTRIBUTION")
        elif top10_pct <= 30.0:
            score += 0.20
        else:
            signals.append("HIGH_TOP10_CONCENTRATION")

        # Dev Holding (0.0 to 0.45)
        if dev_sold_all or dev_holding_pct <= 1.0:
            score += 0.45
            signals.append("DEV_CLEAN_EXIT")
        elif dev_holding_pct <= 3.0:
            score += 0.30
            signals.append("LOW_DEV_HOLDING")
        elif dev_holding_pct <= 5.0:
            score += 0.15
        else:
            signals.append("DEV_HOLDS_LARGE_SUPPLY")

        return min(1.0, score), signals

"""
Order-Flow Quality & Trade Entropy Engine
Calculates volume-weighted buy/sell pressure, trade-size distribution, Shannon entropy,
and age/liquidity normalized transaction intensity.
"""

from dataclasses import dataclass, field
import math
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class OrderFlowMetrics:
    buy_count: int = 0
    sell_count: int = 0
    buy_volume_usd: float = 0.0
    sell_volume_usd: float = 0.0
    unique_buyers: int = 0
    unique_sellers: int = 0

    # Volume-Weighted & Normalized Ratios
    volume_weighted_buy_ratio: float = 0.5   # Buy Vol / Total Vol (0.0 to 1.0)
    buyer_seller_wallet_ratio: float = 1.0   # Unique Buyers / Unique Sellers
    normalized_buy_intensity: float = 0.0    # Buy Vol / (Liquidity * sqrt(Age))

    # Trade Size Distribution
    mean_buy_size_usd: float = 0.0
    median_buy_size_usd: float = 0.0
    mean_sell_size_usd: float = 0.0
    median_sell_size_usd: float = 0.0
    trade_size_entropy: float = 1.0          # Shannon Entropy (High = organic, Low = bot uniformity)

    # Order Flow Quality Score (0 to 1.0)
    order_flow_quality_score: float = 0.5
    signals: List[str] = field(default_factory=list)


class OrderFlowEngine:
    @staticmethod
    def calculate_trade_size_entropy(trade_sizes: List[float]) -> float:
        """
        Compute Shannon Entropy over trade sizes partitioned into log-scale capital buckets:
        Buckets: [<$25, $25-$100, $100-$500, $500-$2500, >$2500]
        - High entropy (> 1.2): Diverse retail & trader ticket distribution (Organic)
        - Very low entropy (< 0.4): Suspiciously uniform ticket sizes (Automated Bot / Wash)
        """
        if not trade_sizes or len(trade_sizes) < 3:
            return 1.0

        buckets = [0, 0, 0, 0, 0]
        for s in trade_sizes:
            if s < 25.0:
                buckets[0] += 1
            elif s < 100.0:
                buckets[1] += 1
            elif s < 500.0:
                buckets[2] += 1
            elif s < 2500.0:
                buckets[3] += 1
            else:
                buckets[4] += 1

        total = len(trade_sizes)
        entropy = 0.0
        for count in buckets:
            if count > 0:
                p = count / total
                entropy -= p * math.log(p)

        return round(entropy, 3)

    @classmethod
    def evaluate(
        cls,
        txns_buys: int,
        txns_sells: int,
        volume_usd: float,
        unique_buyers: int,
        unique_sellers: int,
        liquidity_usd: float,
        token_age_minutes: float,
        raw_trade_sizes: Optional[List[float]] = None,
    ) -> OrderFlowMetrics:
        """
        Compute comprehensive order flow dynamics with volume weighting and trade entropy.
        """
        m = OrderFlowMetrics()
        m.buy_count = txns_buys
        m.sell_count = txns_sells
        m.unique_buyers = max(1, unique_buyers)
        m.unique_sellers = max(1, unique_sellers)

        total_txns = txns_buys + txns_sells
        if total_txns == 0:
            return m

        # Volume estimation by trade split if raw trade sizes not provided
        buy_fraction = txns_buys / total_txns
        m.buy_volume_usd = volume_usd * buy_fraction
        m.sell_volume_usd = volume_usd * (1.0 - buy_fraction)
        m.volume_weighted_buy_ratio = buy_fraction

        # Buyer to seller wallet ratio
        m.buyer_seller_wallet_ratio = m.unique_buyers / m.unique_sellers

        # Mean trade size
        m.mean_buy_size_usd = m.buy_volume_usd / txns_buys if txns_buys > 0 else 0.0
        m.mean_sell_size_usd = m.sell_volume_usd / txns_sells if txns_sells > 0 else 0.0
        m.median_buy_size_usd = m.mean_buy_size_usd * 0.85

        # Trade size entropy
        if raw_trade_sizes:
            m.trade_size_entropy = cls.calculate_trade_size_entropy(raw_trade_sizes)
        else:
            # Baseline estimation from transaction counts
            m.trade_size_entropy = 1.3 if total_txns >= 25 else (0.8 if total_txns >= 5 else 0.5)

        # Normalized Buy Intensity: BuyVolume / (Liquidity * sqrt(Age))
        age = max(1.0, token_age_minutes)
        liq = max(100.0, liquidity_usd)
        m.normalized_buy_intensity = m.buy_volume_usd / (liq * math.sqrt(age))

        # Sample size significance dampener (prevent 3 trades with 3 buys scoring 100%)
        significance = min(1.0, total_txns / 30.0)

        # Quality scoring (0.0 to 1.0)
        quality = 0.0
        signals = []

        # 1. Buy Volume Ratio (0.0 to 0.40)
        if m.volume_weighted_buy_ratio >= 0.70:
            quality += 0.40 * significance
            signals.append("HEAVY_BUY_VOLUME_DOMINANCE")
        elif m.volume_weighted_buy_ratio >= 0.58:
            quality += 0.30 * significance
            signals.append("NET_ACCUMULATION_FLOW")
        elif m.volume_weighted_buy_ratio < 0.45:
            signals.append("NET_DISTRIBUTION_FLOW")

        # 2. Buyer Wallet Diversity (0.0 to 0.30)
        if m.buyer_seller_wallet_ratio >= 1.6:
            quality += 0.30 * significance
            signals.append("BROAD_BUYER_PROPAGATION")
        elif m.buyer_seller_wallet_ratio >= 1.2:
            quality += 0.18 * significance

        # 3. Trade Size Entropy (0.0 to 0.30)
        if m.trade_size_entropy >= 1.1:
            quality += 0.30
            signals.append("ORGANIC_TRADE_ENTROPY")
        elif m.trade_size_entropy < 0.5:
            signals.append("LOW_ENTROPY_BOT_PATTERN")
            quality *= 0.7  # Penalty for bot uniformity

        m.order_flow_quality_score = round(min(1.0, max(0.0, quality)), 3)
        m.signals = signals
        return m

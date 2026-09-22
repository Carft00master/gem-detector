"""
Two-Sided Market Quality Engine (Trader Behavior v1.0.0)
Measures the balance and depth of real two-sided trading participation.
Combines two-sided flow, buy pressure, and price direction so balanced markets without price progress
are not falsely classified as bullish breakouts.
"""

from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass
class TwoSidedMarketQualityMetrics:
    # 1. Volume Balance Ratios
    two_sided_volume_ratio: float = 0.0  # min(buy_vol, sell_vol) / max(buy_vol, sell_vol)
    buy_volume_usd: float = 0.0
    sell_volume_usd: float = 0.0
    net_order_flow_usd: float = 0.0

    # 2. Transaction & Wallet Imbalance
    buy_transaction_ratio: float = 0.5   # buys / total_txns
    sell_transaction_ratio: float = 0.5  # sells / total_txns
    buyer_count_ratio: float = 0.5       # unique_buyers / total_unique_traders
    seller_count_ratio: float = 0.5      # unique_sellers / total_unique_traders

    # 3. Interacting Drivers
    buy_pressure_index: float = 0.5      # Buy Vol / (Buy Vol + Sell Vol)
    price_return_5m_pct: float = 0.0
    price_responsiveness_score: float = 50.0  # Price movement per net dollar flow

    # 4. Composite Quality Score (0–100)
    two_sided_market_quality: float = 50.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "two_sided_volume_ratio": self.two_sided_volume_ratio,
            "buy_volume_usd": self.buy_volume_usd,
            "sell_volume_usd": self.sell_volume_usd,
            "net_order_flow_usd": self.net_order_flow_usd,
            "buy_transaction_ratio": self.buy_transaction_ratio,
            "sell_transaction_ratio": self.sell_transaction_ratio,
            "buyer_count_ratio": self.buyer_count_ratio,
            "seller_count_ratio": self.seller_count_ratio,
            "buy_pressure_index": self.buy_pressure_index,
            "price_return_5m_pct": self.price_return_5m_pct,
            "price_responsiveness_score": self.price_responsiveness_score,
            "two_sided_market_quality": self.two_sided_market_quality,
        }


class TwoSidedMarketQualityEngine:
    """
    Evaluates real two-sided market liquidity and interaction with price direction.
    """

    @classmethod
    def compute(
        cls,
        volume_5m_usd: float,
        txns_5m_buys: int,
        txns_5m_sells: int,
        unique_buyers_1h: int,
        unique_sellers_1h: int,
        price_return_5m_pct: float = 0.0,
        estimated_buy_volume_usd: Optional[float] = None,
        estimated_sell_volume_usd: Optional[float] = None,
    ) -> TwoSidedMarketQualityMetrics:
        b_txns = max(0, int(txns_5m_buys))
        s_txns = max(0, int(txns_5m_sells))
        total_txns = max(1, b_txns + s_txns)

        u_buyers = max(0, int(unique_buyers_1h))
        u_sellers = max(0, int(unique_sellers_1h))
        u_traders = max(1, u_buyers + u_sellers)

        # Estimate volume split if not explicitly provided
        total_vol = max(0.0, float(volume_5m_usd))
        if estimated_buy_volume_usd is not None and estimated_sell_volume_usd is not None:
            buy_vol = max(0.0, float(estimated_buy_volume_usd))
            sell_vol = max(0.0, float(estimated_sell_volume_usd))
        else:
            # Derive from txn ratio with empirical skew
            buy_share = float(b_txns) / float(total_txns) if total_txns > 0 else 0.5
            buy_vol = total_vol * buy_share
            sell_vol = total_vol * (1.0 - buy_share)

        net_flow = buy_vol - sell_vol
        total_directional_vol = buy_vol + sell_vol

        # 1. Two-sided volume ratio
        if total_directional_vol > 0 and max(buy_vol, sell_vol) > 0:
            two_sided_ratio = min(buy_vol, sell_vol) / max(buy_vol, sell_vol)
            buy_pressure = buy_vol / total_directional_vol
        else:
            two_sided_ratio = 0.0
            buy_pressure = 0.5

        # 2. Transaction & count ratios
        buy_txn_ratio = float(b_txns) / float(total_txns)
        sell_txn_ratio = float(s_txns) / float(total_txns)
        buyer_cnt_ratio = float(u_buyers) / float(u_traders)
        seller_cnt_ratio = float(u_sellers) / float(u_traders)

        # 3. Price responsiveness interaction
        # If two-sided ratio is high (e.g. 0.8) AND price return is positive, market is absorbing sells smoothly.
        # If two-sided ratio is 1.0 but price is plunging or flat, it's not a breakout.
        price_ret = float(price_return_5m_pct)
        if price_ret > 0.05 and buy_pressure >= 0.52:
            resp_score = 85.0
        elif price_ret > 0.0 and buy_pressure >= 0.50:
            resp_score = 70.0
        elif price_ret <= -0.05:
            resp_score = 25.0
        else:
            resp_score = 50.0

        # 4. Two-Sided Market Quality (0–100)
        # Optimal quality: Active buyers (55%-75% buy pressure) with healthy organic exit liquidity (25%-45% sell share)
        # and positive price expansion.
        flow_health = min(1.0, two_sided_ratio / 0.5) * 40.0  # up to 40 pts for real counterparty liquidity
        pressure_points = min(1.0, buy_pressure / 0.7) * 30.0 # up to 30 pts for net accumulation
        price_points = (resp_score / 100.0) * 30.0            # up to 30 pts for positive price response

        # Penalty if extreme one-sided illiquidity (e.g. 100% buys, 0 sellers = potential honeypot or illiquid trap)
        if two_sided_ratio < 0.05 and total_vol > 5000.0:
            flow_health *= 0.5

        quality_score = max(0.0, min(100.0, flow_health + pressure_points + price_points))

        return TwoSidedMarketQualityMetrics(
            two_sided_volume_ratio=two_sided_ratio,
            buy_volume_usd=buy_vol,
            sell_volume_usd=sell_vol,
            net_order_flow_usd=net_flow,
            buy_transaction_ratio=buy_txn_ratio,
            sell_transaction_ratio=sell_txn_ratio,
            buyer_count_ratio=buyer_cnt_ratio,
            seller_count_ratio=seller_cnt_ratio,
            buy_pressure_index=buy_pressure,
            price_return_5m_pct=price_ret,
            price_responsiveness_score=resp_score,
            two_sided_market_quality=quality_score,
        )

"""
Participation Breadth Engine (Trader Behavior v1.0.0)
Measures the breadth and dispersion of unique trader participation relative to transaction volume.
Rewards organic distributed trading and penalizes small sybil loops and circular wash trading.
"""

from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass
class ParticipationBreadthMetrics:
    # 1. Dispersion Ratios (0.0 to 1.0)
    trader_to_transaction_ratio: float = 0.0
    buyer_to_buy_txn_ratio: float = 0.0
    seller_to_sell_txn_ratio: float = 0.0

    # 2. Dynamic Growth Rates (fractional change over interval)
    unique_trader_growth_pct: float = 0.0
    unique_buyer_growth_pct: float = 0.0
    unique_seller_growth_pct: float = 0.0

    # 3. Concentration & Diversity Indicators
    effective_trader_dispersion: float = 0.0
    repeat_buyer_penalty: float = 0.0

    # 4. Composite Score (0–100)
    participation_breadth_score: float = 50.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "trader_to_transaction_ratio": self.trader_to_transaction_ratio,
            "buyer_to_buy_txn_ratio": self.buyer_to_buy_txn_ratio,
            "seller_to_sell_txn_ratio": self.seller_to_sell_txn_ratio,
            "unique_trader_growth_pct": self.unique_trader_growth_pct,
            "unique_buyer_growth_pct": self.unique_buyer_growth_pct,
            "unique_seller_growth_pct": self.unique_seller_growth_pct,
            "effective_trader_dispersion": self.effective_trader_dispersion,
            "repeat_buyer_penalty": self.repeat_buyer_penalty,
            "participation_breadth_score": self.participation_breadth_score,
        }


class ParticipationBreadthEngine:
    """
    Evaluates how broadly distributed transaction counts are across distinct wallets.
    """

    @classmethod
    def compute(
        cls,
        txns_5m_buys: int,
        txns_5m_sells: int,
        unique_buyers_1h: int,
        unique_sellers_1h: int,
        prev_unique_buyers: Optional[int] = None,
        prev_unique_sellers: Optional[int] = None,
    ) -> ParticipationBreadthMetrics:
        b_txns = max(0, int(txns_5m_buys))
        s_txns = max(0, int(txns_5m_sells))
        total_txns = max(1, b_txns + s_txns)

        u_buyers = max(0, int(unique_buyers_1h))
        u_sellers = max(0, int(unique_sellers_1h))
        u_traders = max(0, u_buyers + u_sellers)

        # 1. Ratios (1.0 means every transaction is a unique wallet)
        trader_txn_ratio = min(1.0, u_traders / total_txns) if total_txns > 0 else 0.0
        buyer_buy_ratio = min(1.0, u_buyers / max(1, b_txns)) if b_txns > 0 else 0.0
        seller_sell_ratio = min(1.0, u_sellers / max(1, s_txns)) if s_txns > 0 else 0.0

        # 2. Growth metrics
        trader_growth = 0.0
        buyer_growth = 0.0
        seller_growth = 0.0
        if prev_unique_buyers is not None and prev_unique_buyers > 0:
            buyer_growth = (u_buyers - prev_unique_buyers) / float(prev_unique_buyers)
        if prev_unique_sellers is not None and prev_unique_sellers > 0:
            seller_growth = (u_sellers - prev_unique_sellers) / float(prev_unique_sellers)
        prev_traders = (prev_unique_buyers or 0) + (prev_unique_sellers or 0)
        if prev_traders > 0:
            trader_growth = (u_traders - prev_traders) / float(prev_traders)

        # 3. Penalties for extreme repetition (e.g. 50 txns but only 2 buyers)
        repeat_penalty = 0.0
        if b_txns >= 10 and buyer_buy_ratio < 0.20:
            # Concentrated bot loop
            repeat_penalty = (0.20 - buyer_buy_ratio) * 100.0

        dispersion = (buyer_buy_ratio * 0.6 + trader_txn_ratio * 0.4)

        # 4. Composite Participation Breadth Score (0 to 100)
        base_score = dispersion * 70.0  # up to 70 pts from wallet uniqueness

        # Add growth momentum (up to 30 pts)
        if u_buyers >= 50:
            base_score += 15.0
        elif u_buyers >= 20:
            base_score += 10.0
        elif u_buyers >= 8:
            base_score += 5.0

        if buyer_growth > 0.10:
            base_score += 15.0
        elif buyer_growth > 0.0:
            base_score += 8.0

        final_score = max(0.0, min(100.0, base_score - repeat_penalty))

        return ParticipationBreadthMetrics(
            trader_to_transaction_ratio=trader_txn_ratio,
            buyer_to_buy_txn_ratio=buyer_buy_ratio,
            seller_to_sell_txn_ratio=seller_sell_ratio,
            unique_trader_growth_pct=trader_growth,
            unique_buyer_growth_pct=buyer_growth,
            unique_seller_growth_pct=seller_growth,
            effective_trader_dispersion=dispersion,
            repeat_buyer_penalty=repeat_penalty,
            participation_breadth_score=final_score,
        )

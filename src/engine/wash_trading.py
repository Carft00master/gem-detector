"""
Multi-Window Wash-Trading & Artificial-Volume Detection Engine
Analyzes capital turnover across 1m, 5m, 15m windows at wallet, cluster, and token levels,
detects circular counterparties, trade-size repetition, and computes VOLUME_QUALITY_SCORE.
"""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class TradeEvent:
    wallet_address: str
    tx_type: str        # 'buy' or 'sell'
    amount_usd: float
    timestamp: datetime
    cluster_id: Optional[str] = None


@dataclass
class WashTradingAnalysis:
    wash_trade_risk: float = 0.0          # 0.0 to 1.0
    artificial_volume_risk: float = 0.0   # 0.0 to 1.0
    volume_quality_score: float = 1.0     # 1.0 = 100% Organic, 0.0 = Pure Wash

    # Multi-Window Capital Turnover Ratios
    turnover_1m_ratio: float = 1.0
    turnover_5m_ratio: float = 1.0
    turnover_15m_ratio: float = 1.0
    capital_turnover_ratio: float = 1.0   # 5m reference turnover

    # Cluster & Repetition Diagnostics
    cluster_turnover_ratio: float = 1.0
    circular_loops_detected: int = 0
    rapid_roundtrips_count: int = 0
    trade_size_repetition_count: int = 0  # Identical dollar amount trades
    avg_roundtrip_duration_sec: float = 0.0
    circular_volume_usd: float = 0.0
    signals: List[str] = field(default_factory=list)


class WashTradingDetector:
    @classmethod
    def analyze_trades(
        cls,
        trades: List[TradeEvent],
        total_volume_usd: float,
        unique_buyers_count: int,
        market_cap_usd: float,
        roundtrip_windows_sec: Tuple[float, float, float] = (60.0, 300.0, 900.0),
    ) -> WashTradingAnalysis:
        """
        Detect wash-trading across multi-timeframe windows and cluster layers.
        """
        res = WashTradingAnalysis()
        if not trades or total_volume_usd <= 0:
            return res

        now = datetime.now(timezone.utc)
        wallet_max_capital: Dict[str, float] = defaultdict(float)
        cluster_max_capital: Dict[str, float] = defaultdict(float)
        wallet_last_buy_time: Dict[str, datetime] = {}
        wallet_last_buy_amount: Dict[str, float] = {}

        # Trade size repetition tracking
        size_counts: Dict[float, int] = defaultdict(int)

        rapid_roundtrips = 0
        circular_loops = 0
        circular_vol = 0.0
        roundtrip_durations = []

        # Multi-window volume buckets
        vol_1m = 0.0
        vol_5m = 0.0
        vol_15m = 0.0

        for tr in trades:
            w = tr.wallet_address
            c_id = tr.cluster_id or w
            delta_now = abs((now - tr.timestamp.replace(tzinfo=timezone.utc) if tr.timestamp.tzinfo is None else (now - tr.timestamp)).total_seconds())

            if delta_now <= 60.0:
                vol_1m += tr.amount_usd
            if delta_now <= 300.0:
                vol_5m += tr.amount_usd
            if delta_now <= 900.0:
                vol_15m += tr.amount_usd

            size_key = round(tr.amount_usd, 1)
            size_counts[size_key] += 1

            if tr.tx_type == "buy":
                wallet_max_capital[w] = max(wallet_max_capital[w], tr.amount_usd)
                cluster_max_capital[c_id] = max(cluster_max_capital[c_id], tr.amount_usd)
                wallet_last_buy_time[w] = tr.timestamp
                wallet_last_buy_amount[w] = tr.amount_usd
            elif tr.tx_type == "sell":
                if w in wallet_last_buy_time:
                    delta = (tr.timestamp - wallet_last_buy_time[w]).total_seconds()
                    if 0 <= delta <= 300.0:
                        rapid_roundtrips += 1
                        roundtrip_durations.append(delta)
                        last_buy = wallet_last_buy_amount.get(w, 0.0)
                        if last_buy > 0 and tr.amount_usd >= 0.8 * last_buy:
                            circular_loops += 1
                            circular_vol += tr.amount_usd

        # Compute Unique Capital
        total_wallet_capital = max(1.0, sum(wallet_max_capital.values()))
        total_cluster_capital = max(1.0, sum(cluster_max_capital.values()))

        res.capital_turnover_ratio = round(total_volume_usd / total_wallet_capital, 2)
        res.cluster_turnover_ratio = round(total_volume_usd / total_cluster_capital, 2)
        res.turnover_1m_ratio = round(vol_1m / total_wallet_capital, 2) if vol_1m > 0 else 1.0
        res.turnover_5m_ratio = res.capital_turnover_ratio
        res.turnover_15m_ratio = round(vol_15m / total_wallet_capital, 2) if vol_15m > 0 else res.capital_turnover_ratio

        res.rapid_roundtrips_count = rapid_roundtrips
        res.circular_loops_detected = circular_loops
        res.circular_volume_usd = round(circular_vol, 2)

        if roundtrip_durations:
            res.avg_roundtrip_duration_sec = round(sum(roundtrip_durations) / len(roundtrip_durations), 1)

        # Identical Trade-Size Repetition
        repeat_sizes = sum(c for sz, c in size_counts.items() if c >= 3 and sz >= 20.0)
        res.trade_size_repetition_count = repeat_sizes

        # Risk Scoring
        wash_risk = 0.0
        signals = []

        if res.capital_turnover_ratio >= 15.0:
            wash_risk += 0.45
            signals.append("EXTREME_CAPITAL_TURNOVER_WASH")
        elif res.capital_turnover_ratio >= 8.0:
            wash_risk += 0.25
            signals.append("ELEVATED_CAPITAL_TURNOVER")

        if circular_loops >= 5:
            wash_risk += 0.40
            signals.append("MULTIPLE_CIRCULAR_LOOPS")
        elif circular_loops >= 2:
            wash_risk += 0.20
            signals.append("REPEATED_BUY_SELL_ROUNDTRIPS")

        if repeat_sizes >= 6:
            wash_risk += 0.25
            signals.append("HIGH_TRADE_SIZE_REPETITION_BOTS")

        vol_per_buyer = total_volume_usd / max(1, unique_buyers_count)
        if vol_per_buyer > 2500.0 and unique_buyers_count < 15:
            wash_risk += 0.30
            signals.append("CONCENTRATED_VOLUME_FEW_WALLETS")

        res.wash_trade_risk = round(min(1.0, max(0.0, wash_risk)), 3)
        res.artificial_volume_risk = round(min(1.0, wash_risk * 1.1), 3)
        res.volume_quality_score = round(max(0.05, 1.0 - res.wash_trade_risk), 3)
        res.signals = signals

        return res

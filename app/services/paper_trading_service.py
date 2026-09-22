"""
Paper Trading Application Service
Interfaces with persistent SQLite Paper Trading Ledger and 5-Policy Simulation Engine.
"""

from dataclasses import dataclass, field
import logging
from typing import Any, Dict, List, Optional
import numpy as np

from src.paper.engine import PaperTradingEngine, PolicyBacktestResult
from src.paper.ledger import PaperTradingLedger, PaperTradeRecord
from src.research.storage import ResearchStorage

logger = logging.getLogger(__name__)


@dataclass
class PaperTradingAggregateStats:
    total_trades: int = 0
    open_trades_count: int = 0
    closed_trades_count: int = 0
    winning_trades_count: int = 0
    losing_trades_count: int = 0
    win_rate_pct: float = 0.0
    total_realized_pnl_usd: float = 0.0
    mean_return_pct: float = 0.0
    median_return_pct: float = 0.0
    profit_factor: float = 0.0
    max_drawdown_pct: float = 0.0
    avg_winner_usd: float = 0.0
    avg_loser_usd: float = 0.0
    avg_mfe_pct: float = 0.0
    avg_mae_pct: float = 0.0
    status_label: str = "PAPER / SIMULATION"


class PaperTradingService:
    def __init__(self, ledger: Optional[PaperTradingLedger] = None):
        self.ledger = ledger or PaperTradingLedger()
        self.storage = ResearchStorage()
        self._trades_cache: Optional[List[Dict[str, Any]]] = None
        self._trades_cache_time: float = 0.0
        self._stats_cache: Optional[PaperTradingAggregateStats] = None
        self._stats_cache_time: float = 0.0

    def invalidate_cache(self) -> None:
        """Clear cached trade records and aggregate statistics."""
        self._trades_cache = None
        self._trades_cache_time = 0.0
        self._stats_cache = None
        self._stats_cache_time = 0.0

    def get_all_trades(self, force_refresh: bool = False) -> List[Dict[str, Any]]:
        import time
        now = time.time()
        if not force_refresh and self._trades_cache is not None and (now - self._trades_cache_time) < 15.0:
            return self._trades_cache

        trades = self.ledger.load_all_trades()
        self._trades_cache = trades
        self._trades_cache_time = now
        return trades

    def get_open_trades(self) -> List[Dict[str, Any]]:
        all_trades = self.get_all_trades()
        return [t for t in all_trades if t.get("status") == "OPEN"]

    def get_closed_trades(self) -> List[Dict[str, Any]]:
        all_trades = self.get_all_trades()
        return [t for t in all_trades if t.get("status") == "CLOSED"]

    def calculate_aggregate_stats(self, trades: Optional[List[Dict[str, Any]]] = None) -> PaperTradingAggregateStats:
        import time
        now = time.time()
        if trades is None:
            if self._stats_cache is not None and (now - self._stats_cache_time) < 15.0:
                return self._stats_cache
            trades = self.get_all_trades()

        total = len(trades)
        closed = [t for t in trades if t.get("status") == "CLOSED"]
        open_count = total - len(closed)

        if not closed:
            return PaperTradingAggregateStats(
                total_trades=total,
                open_trades_count=open_count,
                closed_trades_count=0,
            )

        def _val(t, *keys, default=0.0):
            for k in keys:
                v = t.get(k)
                if v is not None:
                    try:
                        return float(v)
                    except (ValueError, TypeError):
                        pass
            return default

        pnls = [_val(t, "net_realized_pnl_usd", "pnl") for t in closed]
        rets = [_val(t, "net_realized_return_pct", "realized_return_pct", "return_pct") for t in closed]
        mfes = [_val(t, "mfe_ratio", "max_favorable_excursion_pct") for t in closed]
        maes = [_val(t, "mae_ratio", "max_adverse_excursion_pct") for t in closed]

        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p < 0]
        win_count = len(wins)
        loss_count = len(losses)

        total_pnl = sum(pnls)
        gross_profit = sum(wins)
        gross_loss = abs(sum(losses))
        profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else (10.0 if gross_profit > 0 else 0.0)

        # Max Drawdown calculation from cumulative PnL series
        cum_pnl = np.cumsum(pnls)
        running_max = np.maximum.accumulate(cum_pnl)
        drawdowns = (running_max - cum_pnl)
        max_dd = float(np.max(drawdowns)) if len(drawdowns) > 0 else 0.0

        res = PaperTradingAggregateStats(
            total_trades=total,
            open_trades_count=open_count,
            closed_trades_count=len(closed),
            winning_trades_count=win_count,
            losing_trades_count=loss_count,
            win_rate_pct=round((win_count / len(closed)) * 100.0, 2),
            total_realized_pnl_usd=round(total_pnl, 2),
            mean_return_pct=round(float(np.mean(rets)), 2) if rets else 0.0,
            median_return_pct=round(float(np.median(rets)), 2) if rets else 0.0,
            profit_factor=round(profit_factor, 2),
            max_drawdown_pct=round(max_dd, 2),
            avg_winner_usd=round(float(np.mean(wins)), 2) if wins else 0.0,
            avg_loser_usd=round(float(np.mean(losses)), 2) if losses else 0.0,
            avg_mfe_pct=round(float(np.mean(mfes)), 2) if mfes else 0.0,
            avg_mae_pct=round(float(np.mean(maes)), 2) if maes else 0.0,
        )
        self._stats_cache = res
        self._stats_cache_time = now
        return res

    def run_five_policy_comparison(self, position_size_usd: float = 250.0) -> Dict[str, PolicyBacktestResult]:
        records = self.storage.load_training_dataset(limit=500)
        if not records:
            from src.research.shadow import ShadowUniverseLogger
            records = ShadowUniverseLogger().load_recent_shadow_tokens(limit=500)
        return PaperTradingEngine.backtest_all_five_policies(records, position_size_usd=position_size_usd)

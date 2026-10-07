"""
Virtual Wallet Application Service.
Provides high-level APIs for UI views, analytics calculation, session switching,
and event bus synchronization.
"""

import logging
from typing import Optional, List, Dict, Any

from app.application.events import event_bus
from src.wallet.store import WalletStore
from src.wallet.engine import VirtualWalletEngine
from src.wallet.stats import WalletStatsCalculator, WalletSummaryStats, DailyWalletStats, WeeklyWalletStats
from src.wallet.models import WalletSessionRecord, WalletPositionRecord

logger = logging.getLogger(__name__)


class WalletService:
    def __init__(
        self,
        engine: Optional[VirtualWalletEngine] = None,
        tz_offset_hours: int = 1,
    ):
        self.store = WalletStore()
        self.engine = engine or VirtualWalletEngine(store=self.store)
        self.stats_calculator = WalletStatsCalculator(store=self.store, tz_offset_hours=tz_offset_hours)
        
        # Wire event bus connections so wallet automatically tracks paper trades in real-time
        event_bus.paper_trade_opened.connect(self._handle_paper_trade_opened)
        event_bus.paper_trade_closed.connect(self._handle_paper_trade_closed)

    def _handle_paper_trade_opened(self, trade_dict: Dict[str, Any]):
        try:
            # Wrap in stub object
            stub = type("TradeStub", (), trade_dict)()
            pos = self.engine.on_paper_trade_opened(stub)
            if pos:
                if hasattr(event_bus, "wallet_updated"):
                    event_bus.wallet_updated.emit()
        except Exception as e:
            logger.warning(f"WalletService error handling paper_trade_opened: {e}")

    def _handle_paper_trade_closed(self, trade_dict: Dict[str, Any]):
        try:
            stub = type("TradeStub", (), trade_dict)()
            pos = self.engine.on_paper_trade_closed(stub)
            if pos:
                if hasattr(event_bus, "wallet_updated"):
                    event_bus.wallet_updated.emit()
        except Exception as e:
            logger.warning(f"WalletService error handling paper_trade_closed: {e}")

    # --- Query Methods ---

    def get_active_session(self) -> WalletSessionRecord:
        return self.engine.session

    def list_sessions(self) -> List[WalletSessionRecord]:
        return self.store.list_sessions()

    def get_summary_stats(self) -> WalletSummaryStats:
        return self.stats_calculator.compute_summary_stats(self.engine.session)

    def get_daily_breakdown(self) -> List[DailyWalletStats]:
        return self.stats_calculator.compute_daily_breakdown(self.engine.session.session_id)

    def get_weekly_breakdown(self) -> List[WeeklyWalletStats]:
        return self.stats_calculator.compute_weekly_breakdown(self.engine.session.session_id)

    def get_open_positions(self) -> List[Dict[str, Any]]:
        positions = self.store.get_open_positions(self.engine.session.session_id)
        return [self._pos_to_dict(p) for p in positions]

    def get_all_positions(self, limit: int = 500) -> List[Dict[str, Any]]:
        positions = self.store.get_all_positions(self.engine.session.session_id, limit=limit)
        return [self._pos_to_dict(p) for p in positions]

    def get_equity_curve(self, limit: int = 1000) -> List[Dict[str, Any]]:
        snapshots = self.store.get_snapshots(self.engine.session.session_id, limit=limit)
        return [
            {
                "timestamp": s.timestamp,
                "cash": s.cash_balance_usd,
                "deployed": s.deployed_capital_usd,
                "equity": s.total_equity_usd,
                "open_count": s.open_positions_count,
            }
            for s in snapshots
        ]

    def create_new_session(
        self,
        name: str,
        starting_capital: float = 1000.0,
        risk_pct: float = 0.05,
        sizing_mode: str = "COMPOUNDING"
    ) -> WalletSessionRecord:
        sess = self.engine.create_new_session(
            name=name,
            starting_capital=starting_capital,
            risk_pct=risk_pct,
            sizing_mode=sizing_mode,
        )
        if hasattr(event_bus, "wallet_updated"):
            event_bus.wallet_updated.emit()
        return sess

    def switch_session(self, session_id: str) -> bool:
        ok = self.engine.set_active_session(session_id)
        if ok and hasattr(event_bus, "wallet_updated"):
            event_bus.wallet_updated.emit()
        return ok

    def reconcile(self) -> int:
        count = self.engine.reconcile_with_paper_trades()
        if count > 0 and hasattr(event_bus, "wallet_updated"):
            event_bus.wallet_updated.emit()
        return count

    def _pos_to_dict(self, pos: WalletPositionRecord) -> Dict[str, Any]:
        return {
            "position_id": pos.position_id,
            "paper_trade_id": pos.paper_trade_id,
            "token_address": pos.token_address,
            "symbol": pos.symbol,
            "chain": pos.chain,
            "venue": pos.venue,
            "position_size_usd": pos.position_size_usd,
            "entry_price_usd": pos.entry_price_usd,
            "simulated_fill_price_usd": pos.simulated_fill_price_usd,
            "entry_market_cap_usd": pos.entry_market_cap_usd,
            "entry_liquidity_usd": pos.entry_liquidity_usd,
            "entry_timestamp": pos.entry_timestamp,
            "entry_price_impact_pct": pos.entry_price_impact_pct,
            "entry_fees_usd": pos.entry_fees_usd,
            "status": pos.status,
            "skip_reason": pos.skip_reason,
            "exit_price_usd": pos.exit_price_usd,
            "exit_market_cap_usd": pos.exit_market_cap_usd,
            "exit_liquidity_usd": pos.exit_liquidity_usd,
            "exit_timestamp": pos.exit_timestamp,
            "exit_reason": pos.exit_reason,
            "exit_price_impact_pct": pos.exit_price_impact_pct,
            "exit_fees_usd": pos.exit_fees_usd,
            "gross_exit_proceeds_usd": pos.gross_exit_proceeds_usd,
            "net_realized_pnl_usd": pos.net_realized_pnl_usd,
            "net_realized_return_pct": pos.net_realized_return_pct,
            "hold_duration_seconds": pos.hold_duration_seconds,
            "equity_before_usd": pos.equity_before_usd,
            "equity_after_usd": pos.equity_after_usd,
        }

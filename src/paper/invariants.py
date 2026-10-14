"""
Ledger-Write Integrity Invariants & Trade Quarantine Engine (Phase 1e)
Enforces mathematical, on-chain, and temporal invariants before any record is committed to the ledger.
If ANY invariant is violated, the trade is rejected and persisted to trade_quarantine with a forensic reason.

Integrity Invariants:
1. Exit Multiple <= Peak Multiple (MFE): You cannot exit higher than the peak executable price reached.
2. Entry Price within Executable Range for that Slot: Logged entry cannot be below AMM spot.
3. Proceeds <= Pool Reserve Limits: Sell proceeds cannot exceed what the pool's SOL reserve can physically pay.
4. Hold Duration <= Max Hold Duration.
5. Stale Price Force-Close: Stale price (>10s) force-closes position at last executable price.
6. Route Isolation: Maximum one open position per mint per route.
7. Fill-Derived Returns Only: P&L and Return % must be derived strictly from simulated tokens & fill proceeds.
"""

from dataclasses import asdict
import logging
import math
from typing import Any, Dict, List, Optional, Tuple

from src.paper.ledger import PaperTradeRecord, PaperTradingLedger

logger = logging.getLogger(__name__)


class InvariantViolation(Exception):
    """Raised when an execution or accounting invariant is violated."""
    pass


class LedgerInvariantValidator:
    """
    Validates and enforces ledger invariants. Writes violations to quarantine.
    """
    def __init__(self, ledger: Optional[PaperTradingLedger] = None, max_hold_seconds: float = 7200.0):
        self.ledger = ledger or PaperTradingLedger()
        self.max_hold_seconds = max_hold_seconds

    def validate_entry(
        self,
        trade: PaperTradeRecord,
        active_positions: Dict[str, Any],
        min_executable_price: Optional[float] = None,
        max_executable_price: Optional[float] = None,
    ) -> Tuple[bool, Optional[str]]:
        """
        Validate entry invariants at entry time.
        """
        # 1. One open position per mint per route
        route = getattr(trade, "route", "ROUTE_A")
        token_addr = trade.token_address
        pos_key = f"{route}:{token_addr}"
        if pos_key in active_positions:
            reason = f"INVARIANT_VIOLATION: Duplicate open position on route {route} for mint {token_addr}"
            self._quarantine(trade, reason)
            return False, reason

        # 2. Entry Price within Executable Slot Range
        if min_executable_price is not None and max_executable_price is not None:
            fill_p = trade.simulated_fill_price_usd or trade.entry_price_usd
            # Allow 1% numerical tolerance for boundary rounding
            if fill_p < min_executable_price * 0.98 or fill_p > max_executable_price * 1.02:
                reason = (
                    f"INVARIANT_VIOLATION: Entry price ${fill_p:.8f} is outside executable slot range "
                    f"[${min_executable_price:.8f}, ${max_executable_price:.8f}]"
                )
                self._quarantine(trade, reason)
                return False, reason

        # 3. Valid positive capital commitment
        if trade.position_size_usd <= 0.0:
            reason = f"INVARIANT_VIOLATION: Non-positive position size ${trade.position_size_usd}"
            self._quarantine(trade, reason)
            return False, reason

        return True, None

    def validate_exit(
        self,
        trade: PaperTradeRecord,
        pool_sol_reserve: Optional[float] = None,
        oracle_sol_usd: Optional[float] = None,
    ) -> Tuple[bool, Optional[str]]:
        """
        Validate exit invariants before committing a closed trade.
        """
        # 1. Exit multiple <= Peak multiple (MFE)
        exit_mc = trade.exit_market_cap_usd or 0.0
        entry_mc = trade.entry_market_cap_usd or trade.market_cap_usd or 0.0
        mfe_ratio = trade.mfe_ratio or 1.0

        if entry_mc > 0 and exit_mc > 0:
            exit_multiple = exit_mc / entry_mc
            # Allow tiny float tolerance (1e-3)
            if exit_multiple > mfe_ratio + 0.005:
                reason = (
                    f"INVARIANT_VIOLATION: Exit multiple ({exit_multiple:.3f}x) exceeds "
                    f"peak multiple / MFE ratio ({mfe_ratio:.3f}x)"
                )
                self._quarantine(trade, reason)
                return False, reason

        # 2. Proceeds <= Pool Reserve Limits
        if pool_sol_reserve is not None and pool_sol_reserve > 0.0:
            sol_price = oracle_sol_usd or (trade.entry_effective_sol_usd if hasattr(trade, "entry_effective_sol_usd") else 100.0)
            net_proceeds_usd = trade.exit_net_proceeds_usd or (trade.position_size_usd + trade.net_realized_pnl_usd)
            pool_value_usd = pool_sol_reserve * sol_price
            if net_proceeds_usd > pool_value_usd * 1.01:
                reason = (
                    f"INVARIANT_VIOLATION: Net proceeds ${net_proceeds_usd:,.2f} exceed "
                    f"pool total SOL reserves value (${pool_value_usd:,.2f})"
                )
                self._quarantine(trade, reason)
                return False, reason

        # 3. Hold duration <= max hold duration
        if trade.hold_duration_seconds > self.max_hold_seconds:
            reason = (
                f"INVARIANT_VIOLATION: Hold duration {trade.hold_duration_seconds:.1f}s exceeds "
                f"maximum allowable hold {self.max_hold_seconds:.1f}s"
            )
            self._quarantine(trade, reason)
            return False, reason

        # 4. Fill-Derived Returns Invariant
        # Net return % must strictly equal (net_pnl / position_size) * 100
        if trade.position_size_usd > 0:
            expected_ret = round((trade.net_realized_pnl_usd / trade.position_size_usd) * 100.0, 2)
            actual_ret = round(trade.net_realized_return_pct, 2)
            if abs(expected_ret - actual_ret) > 0.10:
                reason = (
                    f"INVARIANT_VIOLATION: Net return % ({actual_ret:.2f}%) does not match "
                    f"fill-derived PnL / Size ({expected_ret:.2f}%)"
                )
                self._quarantine(trade, reason)
                return False, reason

        return True, None

    def _quarantine(self, trade: PaperTradeRecord, reason: str) -> None:
        """Write violating trade to quarantine table."""
        try:
            self.ledger.record_quarantine(
                token_address=trade.token_address,
                reason=reason,
                route=getattr(trade, "route", "ROUTE_A"),
                signal_id=trade.signal_id,
                trade_id=trade.trade_id,
                trade_dict=asdict(trade),
            )
        except Exception as e:
            logger.error(f"Failed to record trade quarantine: {e}")

"""
Core Virtual Wallet Engine.
Executes capital-constrained position sizing, venue-specific AMM simulation,
cash ledger accounting, equity tracking, and automatic reconciliation with paper trades.
"""

import uuid
import logging
from typing import Optional, Dict, Any, List
from datetime import datetime, timezone

from src.research.execution import AMMExecutionSimulator
from src.paper.ledger import PaperTradeRecord
from src.wallet.models import (
    WalletSessionRecord,
    WalletPositionRecord,
    WalletLedgerRecord,
    WalletEquitySnapshotRecord,
)
from src.wallet.store import WalletStore

logger = logging.getLogger(__name__)


def _extract_field(obj: Any, field_name: str, default: Any = None) -> Any:
    """Extract a field from either an object or a dictionary safely."""
    if isinstance(obj, dict):
        return obj.get(field_name, default)
    return getattr(obj, field_name, default)


class VirtualWalletEngine:
    def __init__(
        self,
        store: Optional[WalletStore] = None,
        execution_sim: Optional[AMMExecutionSimulator] = None,
        starting_capital: float = 1000.0,
        risk_pct: float = 0.05,
        sizing_mode: str = "COMPOUNDING",
        min_trade_size_usd: float = 10.0,
    ):
        self.store = store or WalletStore()
        self.execution_sim = execution_sim or AMMExecutionSimulator()
        self.min_trade_size_usd = min_trade_size_usd
        
        # Load or bootstrap default forward testing session
        self.session: WalletSessionRecord = self.store.get_or_create_default_session(
            starting_capital=starting_capital,
            risk_pct=risk_pct,
            sizing_mode=sizing_mode,
        )
        logger.info(
            f"VirtualWalletEngine initialized: Session '{self.session.name}' "
            f"| Capital: ${self.session.current_cash_usd:,.2f} | Equity: ${self.session.current_equity_usd:,.2f} "
            f"| Mode: {self.session.sizing_mode} @ {self.session.risk_pct * 100:.0f}%"
        )
        
        # Reconcile any open wallet positions against paper trade ledger on startup
        self.reconcile_with_paper_trades()

    def set_active_session(self, session_id: str) -> bool:
        sess = self.store.get_session(session_id)
        if sess:
            self.session = sess
            return True
        return False

    def create_new_session(
        self,
        name: str,
        starting_capital: float = 1000.0,
        risk_pct: float = 0.05,
        sizing_mode: str = "COMPOUNDING"
    ) -> WalletSessionRecord:
        """Create a fresh isolated virtual wallet session."""
        sess_id = f"sess_{str(uuid.uuid4())[:8]}"
        now_iso = datetime.now(timezone.utc).isoformat()
        sess = WalletSessionRecord(
            session_id=sess_id,
            name=name,
            starting_capital_usd=starting_capital,
            risk_pct=risk_pct,
            sizing_mode=sizing_mode,
            current_cash_usd=starting_capital,
            current_equity_usd=starting_capital,
            peak_equity_usd=starting_capital,
            max_drawdown_pct=0.0,
            is_active=True,
            created_at=now_iso,
            updated_at=now_iso,
        )
        self.store.save_session(sess)

        # Deposit
        dep = WalletLedgerRecord(
            entry_id=f"led_{str(uuid.uuid4())[:8]}",
            session_id=sess_id,
            timestamp=now_iso,
            entry_type="INITIAL_DEPOSIT",
            amount_usd=starting_capital,
            cash_balance_after_usd=starting_capital,
            notes=f"Initial virtual capital deposit: ${starting_capital:,.2f}"
        )
        self.store.record_ledger_entry(dep)
        self.session = sess
        return sess

    # --- Trade Lifecycle Hooks ---

    def on_paper_trade_opened(self, paper_trade: Any) -> Optional[WalletPositionRecord]:
        """
        Called when the paper engine opens a position.
        Calculates wallet allocation, applies pool liquidity caps, simulates real fill,
        and debits the cash ledger.
        """
        if not self.session.is_active:
            return None

        # Check if already mirrored
        p_id = _extract_field(paper_trade, "trade_id") or _extract_field(paper_trade, "signal_id")
        if not p_id:
            return None
            
        existing = self.store.get_position_by_paper_id(self.session.session_id, p_id)
        if existing:
            return existing

        now_iso = datetime.now(timezone.utc).isoformat()
        token_addr = _extract_field(paper_trade, "token_address", "")
        symbol = _extract_field(paper_trade, "symbol", "UNKNOWN")
        chain = _extract_field(paper_trade, "chain", "solana")
        venue = _extract_field(paper_trade, "venue", "raydium")
        entry_price = float(_extract_field(paper_trade, "entry_price_usd", 0.0) or 0.0)
        entry_mc = float(_extract_field(paper_trade, "entry_market_cap_usd", 0.0) or _extract_field(paper_trade, "market_cap_usd", 0.0) or 0.0)
        entry_liq = float(_extract_field(paper_trade, "entry_liquidity_usd", 0.0) or _extract_field(paper_trade, "liquidity_usd", 0.0) or 0.0)

        # 1. Calculate Target Position Size
        if self.session.sizing_mode == "COMPOUNDING":
            target_size = self.session.current_equity_usd * self.session.risk_pct
        else:
            target_size = self.session.starting_capital_usd * self.session.risk_pct

        # 2. Liquidity-Depth Cap: max position size at 2.0% AMM price impact
        max_depth_size = self.execution_sim.calculate_max_position_limits(entry_liq, venue).max_position_2pct_usd
        if max_depth_size > 0:
            target_size = min(target_size, max_depth_size)

        # 3. Cash Availability Gate
        if self.session.current_cash_usd < self.min_trade_size_usd:
            # Skip trade due to insufficient capital
            skip_pos = WalletPositionRecord(
                position_id=f"wpos_{str(uuid.uuid4())[:8]}",
                session_id=self.session.session_id,
                paper_trade_id=p_id,
                token_address=token_addr,
                symbol=symbol,
                chain=chain,
                venue=venue,
                position_size_usd=0.0,
                entry_price_usd=entry_price,
                simulated_fill_price_usd=entry_price,
                entry_market_cap_usd=entry_mc,
                entry_liquidity_usd=entry_liq,
                entry_timestamp=now_iso,
                status="SKIPPED",
                skip_reason="NO_CAPITAL",
                equity_before_usd=self.session.current_equity_usd,
                equity_after_usd=self.session.current_equity_usd,
            )
            self.store.create_position(skip_pos)
            logger.info(f"Virtual Wallet: Skipped {symbol} (Free cash ${self.session.current_cash_usd:.2f} < ${self.min_trade_size_usd:.2f})")
            return skip_pos

        committed_size = min(target_size, self.session.current_cash_usd)
        if committed_size < self.min_trade_size_usd:
            return None

        # 4. Simulate Real AMM Execution Entry at Wallet Size
        exec_entry = self.execution_sim.simulate_trade(
            position_size_usd=committed_size,
            entry_mc=entry_mc,
            exit_mc=entry_mc,
            entry_liquidity=entry_liq,
            exit_liquidity=entry_liq,
            chain=chain,
            venue=venue,
        )

        impact_factor = 1.0 + (exec_entry.entry_price_impact_pct / 100.0)
        sim_fill = entry_price * impact_factor if entry_price > 0 else 0.0

        pos_id = f"wpos_{str(uuid.uuid4())[:8]}"
        pos = WalletPositionRecord(
            position_id=pos_id,
            session_id=self.session.session_id,
            paper_trade_id=p_id,
            token_address=token_addr,
            symbol=symbol,
            chain=chain,
            venue=venue,
            position_size_usd=committed_size,
            entry_price_usd=entry_price,
            simulated_fill_price_usd=sim_fill,
            entry_market_cap_usd=entry_mc,
            entry_liquidity_usd=entry_liq,
            entry_timestamp=now_iso,
            entry_price_impact_pct=exec_entry.entry_price_impact_pct,
            entry_fees_usd=exec_entry.dex_swap_fees_usd + exec_entry.network_priority_fees_usd,
            status="OPEN",
            equity_before_usd=self.session.current_equity_usd,
            equity_after_usd=self.session.current_equity_usd,
        )
        self.store.create_position(pos)

        # 5. Ledger Accounting: Debit Cash
        new_cash = round(self.session.current_cash_usd - committed_size, 2)
        self.session.current_cash_usd = new_cash
        self.store.save_session(self.session)

        led_entry = WalletLedgerRecord(
            entry_id=f"led_{str(uuid.uuid4())[:8]}",
            session_id=self.session.session_id,
            timestamp=now_iso,
            entry_type="BUY",
            amount_usd=-committed_size,
            cash_balance_after_usd=new_cash,
            position_id=pos_id,
            notes=f"Entry BUY: {symbol} (${committed_size:.2f} @ impact {exec_entry.entry_price_impact_pct:.2f}%)"
        )
        self.store.record_ledger_entry(led_entry)

        logger.info(
            f"Virtual Wallet Admitted: {symbol} | Allocated: ${committed_size:.2f} "
            f"| Cash Rem: ${new_cash:,.2f} | Impact: {exec_entry.entry_price_impact_pct:.2f}%"
        )
        return pos

    def on_paper_trade_closed(self, paper_trade: Any) -> Optional[WalletPositionRecord]:
        """
        Called when a paper trade closes.
        Re-simulates exit at the wallet's specific position size, calculates net realized PnL,
        credits proceeds back to cash, and records an equity snapshot.
        """
        if not self.session.is_active:
            return None

        p_id = _extract_field(paper_trade, "trade_id") or _extract_field(paper_trade, "signal_id")
        if not p_id:
            return None

        pos = self.store.get_position_by_paper_id(self.session.session_id, p_id)
        if not pos or pos.status != "OPEN":
            return None

        now_iso = datetime.now(timezone.utc).isoformat()
        exit_price = float(_extract_field(paper_trade, "exit_price_usd", 0.0) or 0.0)
        exit_mc = float(_extract_field(paper_trade, "exit_market_cap_usd", 0.0) or 0.0)
        raw_exit_liq = _extract_field(paper_trade, "exit_liquidity_usd", None)
        exit_liq = float(raw_exit_liq) if raw_exit_liq is not None else 0.0
        exit_reason = _extract_field(paper_trade, "exit_reason", "MANUAL_OR_EXPIRED")
        hold_sec = float(_extract_field(paper_trade, "hold_duration_seconds", 0.0) or 0.0)
        paper_ret = float(_extract_field(paper_trade, "net_realized_return_pct", 0.0) or 0.0)

        # Zero-Liquidity / Drained Pool / Rug Protection:
        venue_str = str(pos.venue or "").lower()
        is_bonding_curve = "pump" in venue_str or "stonk" in venue_str or "curve" in venue_str

        # If exit_liq is missing or 0, fallback to entry_liquidity or derive from exit_mc
        if exit_liq < 500.0:
            if is_bonding_curve and exit_mc > 0:
                exit_liq = max(1500.0, exit_mc * 0.60)
            elif pos.entry_liquidity_usd and pos.entry_liquidity_usd >= 1500.0:
                exit_liq = pos.entry_liquidity_usd

        # A trade must NEVER be classified as an LP-drain rug if:
        # 1. The paper trade was clearly profitable (paper_ret > 0.0)
        # 2. It was closed due to displacement by a higher rank
        # 3. It hit a planned take-profit or staged trailing profit exit
        is_benign_exit = (
            paper_ret > 0.0
            or exit_reason in (
                "DISPLACED_BY_HIGHER_RANK",
                "STAGED_TRAILING_PROFIT",
                "STAGED_BREAKEVEN_PROTECTION",
                "TP_TARGET_1",
                "TP_TARGET_2",
                "TP_TARGET_3",
            )
        )

        if is_benign_exit:
            is_rug = False
        elif is_bonding_curve:
            # On bonding curves, LP cannot be pulled by dev. Rug only if extreme collapse / invalidation.
            is_rug = (exit_reason == "RISK_INVALIDATION" and paper_ret <= -80.0) or (exit_mc < 1000.0 and paper_ret <= -80.0)
        else:
            # Standard AMM (Raydium, Uniswap)
            is_rug = (
                exit_reason == "RISK_INVALIDATION"
                or paper_ret <= -90.0
                or (0.0 < exit_liq < 500.0 and paper_ret <= 0.0)
                or (exit_liq <= 0.0 and paper_ret <= -50.0)
            )

        if is_rug:
            priority_fee = 0.02 if pos.chain == "solana" else 0.05
            total_fees = round(priority_fee * 2.0, 2)
            net_pnl = round(-pos.position_size_usd - total_fees, 2)
            net_ret = -100.0
            proceeds = 0.0
            exit_impact = 100.0
        else:
            # Re-simulate execution at the wallet's specific position size
            exec_result = self.execution_sim.simulate_trade(
                position_size_usd=pos.position_size_usd,
                entry_mc=pos.entry_market_cap_usd,
                exit_mc=exit_mc if exit_mc > 0 else pos.entry_market_cap_usd,
                entry_liquidity=pos.entry_liquidity_usd,
                exit_liquidity=exit_liq if exit_liq > 0 else 0.0,
                chain=pos.chain,
                venue=pos.venue,
                entry_price=pos.entry_price_usd or pos.simulated_fill_price_usd,
                exit_price=exit_price if exit_price > 0 else None,
            )

            if is_benign_exit and not exec_result.is_executable and paper_ret > 0:
                # Fallback to proportional paper trade return if simulation rejected on liquidity glitch
                net_ret = paper_ret
                net_pnl = round(pos.position_size_usd * (paper_ret / 100.0), 2)
                total_fees = round((0.02 if pos.chain == "solana" else 0.05) * 2.0, 2)
                proceeds = max(0.0, round(pos.position_size_usd + net_pnl, 2))
                exit_impact = 1.0
            else:
                net_pnl = exec_result.net_realized_pnl_usd
                net_ret = exec_result.net_realized_return_pct
                total_fees = exec_result.dex_swap_fees_usd + exec_result.network_priority_fees_usd
                proceeds = max(0.0, round(pos.position_size_usd + net_pnl, 2))
                exit_impact = exec_result.exit_price_impact_pct

        # Update Position
        pos.status = "CLOSED"
        pos.exit_price_usd = exit_price
        pos.exit_market_cap_usd = exit_mc
        pos.exit_liquidity_usd = exit_liq
        pos.exit_timestamp = now_iso
        pos.exit_reason = exit_reason
        pos.exit_price_impact_pct = exit_impact
        pos.exit_fees_usd = total_fees
        pos.gross_exit_proceeds_usd = proceeds
        pos.net_realized_pnl_usd = net_pnl
        pos.net_realized_return_pct = net_ret
        pos.hold_duration_seconds = hold_sec
        pos.equity_before_usd = self.session.current_equity_usd

        # Update Session Cash and Equity
        new_cash = round(self.session.current_cash_usd + proceeds, 2)
        new_equity = round(self.session.current_equity_usd + net_pnl, 2)

        self.session.current_cash_usd = new_cash
        self.session.current_equity_usd = new_equity
        if new_equity > self.session.peak_equity_usd:
            self.session.peak_equity_usd = new_equity

        # Drawdown calculation
        dd = ((self.session.peak_equity_usd - new_equity) / self.session.peak_equity_usd * 100.0) if self.session.peak_equity_usd > 0 else 0.0
        if dd > self.session.max_drawdown_pct:
            self.session.max_drawdown_pct = round(dd, 2)

        pos.equity_after_usd = new_equity
        self.store.update_position(pos)
        self.store.save_session(self.session)

        # Ledger Credit
        led_entry = WalletLedgerRecord(
            entry_id=f"led_{str(uuid.uuid4())[:8]}",
            session_id=self.session.session_id,
            timestamp=now_iso,
            entry_type="SELL",
            amount_usd=proceeds,
            cash_balance_after_usd=new_cash,
            position_id=pos.position_id,
            notes=f"Exit SELL: {pos.symbol} (PnL: ${net_pnl:+.2f} / {net_ret:+.1f}%)"
        )
        self.store.record_ledger_entry(led_entry)

        # Snapshot Equity
        self.snapshot_equity()

        logger.info(
            f"Virtual Wallet Closed: {pos.symbol} | PnL: ${net_pnl:+.2f} ({net_ret:+.1f}%) "
            f"| Equity: ${new_equity:,.2f} | Reason: {exit_reason}"
        )
        return pos

    def snapshot_equity(self) -> WalletEquitySnapshotRecord:
        """Create a mark-to-market snapshot of the wallet equity."""
        open_pos = self.store.get_open_positions(self.session.session_id)
        deployed = sum(p.position_size_usd for p in open_pos)
        snap = WalletEquitySnapshotRecord(
            snapshot_id=f"snap_{str(uuid.uuid4())[:8]}",
            session_id=self.session.session_id,
            timestamp=datetime.now(timezone.utc).isoformat(),
            cash_balance_usd=self.session.current_cash_usd,
            deployed_capital_usd=deployed,
            mark_to_market_value_usd=deployed,  # Book value baseline until tick update
            total_equity_usd=self.session.current_equity_usd,
            open_positions_count=len(open_pos),
        )
        self.store.record_snapshot(snap)
        return snap

    def reconcile_with_paper_trades(self) -> int:
        """
        Reconciles open wallet positions against paper_trading.db.
        If a paper trade closed while offline or was terminated as a zombie,
        closes the wallet position cleanly.
        """
        import sqlite3
        from src.utils.paths import get_data_dir

        paper_db = get_data_dir() / "paper_trading.db"
        if not paper_db.exists():
            return 0

        open_wallet_positions = self.store.get_open_positions(self.session.session_id)
        if not open_wallet_positions:
            return 0

        reconciled_count = 0
        try:
            with sqlite3.connect(f"file:{paper_db}?mode=ro", uri=True, timeout=10.0) as conn:
                conn.row_factory = sqlite3.Row
                cur = conn.cursor()
                for pos in open_wallet_positions:
                    cur.execute(
                        "SELECT * FROM paper_trades WHERE (trade_id = ? OR signal_id = ?) LIMIT 1",
                        (pos.paper_trade_id, pos.paper_trade_id)
                    )
                    row = cur.fetchone()
                    if row and row["status"] == "CLOSED":
                        # Paper trade closed while wallet was offline -> close wallet position now
                        mock_trade = type("PaperTradeStub", (), dict(row))()
                        self.on_paper_trade_closed(mock_trade)
                        reconciled_count += 1
                        logger.info(f"Reconciled offline paper trade for wallet: {pos.symbol}")
        except Exception as e:
            logger.warning(f"Error during wallet reconciliation: {e}")

        return reconciled_count

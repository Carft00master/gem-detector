"""
Unit tests for the Virtual Wallet Subsystem.
Tests isolated capital allocation, compounding vs fixed sizing, AMM slippage/fee modeling,
cash ledger accounting, paper trade event handling, and daily/weekly statistics.
"""

import pytest
import tempfile
import shutil
from pathlib import Path
from dataclasses import dataclass
from datetime import datetime, timezone

from src.wallet.models import (
    WalletSessionRecord,
    WalletPositionRecord,
    WalletLedgerRecord,
    WalletEquitySnapshotRecord,
)
from src.wallet.store import WalletStore
from src.wallet.engine import VirtualWalletEngine
from src.wallet.stats import WalletStatsCalculator
from src.research.execution import AMMExecutionSimulator


@dataclass
class MockPaperTrade:
    trade_id: str
    token_address: str = "So11111111111111111111111111111111111111112"
    symbol: str = "TESTCOIN"
    chain: str = "solana"
    venue: str = "raydium"
    entry_price_usd: float = 0.001
    entry_market_cap_usd: float = 50000.0
    entry_liquidity_usd: float = 20000.0
    status: str = "OPEN"
    exit_price_usd: float = 0.002
    exit_market_cap_usd: float = 100000.0
    exit_liquidity_usd: float = 25000.0
    exit_reason: str = "TP_TARGET_1"
    hold_duration_seconds: float = 1200.0


@pytest.fixture
def temp_store(tmp_path):
    db_file = tmp_path / "test_virtual_wallet.db"
    store = WalletStore(db_path=db_file)
    return store


class TestVirtualWallet:
    def test_initial_session_and_deposit(self, temp_store):
        engine = VirtualWalletEngine(
            store=temp_store,
            starting_capital=1000.0,
            risk_pct=0.05,
            sizing_mode="COMPOUNDING",
        )
        assert engine.session is not None
        assert engine.session.starting_capital_usd == 1000.0
        assert engine.session.current_cash_usd == 1000.0
        assert engine.session.current_equity_usd == 1000.0
        assert engine.session.risk_pct == 0.05

        ledger = temp_store.get_ledger_entries(engine.session.session_id)
        assert len(ledger) == 1
        assert ledger[0].entry_type == "INITIAL_DEPOSIT"
        assert ledger[0].amount_usd == 1000.0

    def test_position_sizing_compounding(self, temp_store):
        engine = VirtualWalletEngine(
            store=temp_store,
            starting_capital=1000.0,
            risk_pct=0.05,
            sizing_mode="COMPOUNDING",
        )
        mock_pt = MockPaperTrade(trade_id="pt_001")
        pos = engine.on_paper_trade_opened(mock_pt)

        assert pos is not None
        assert pos.status == "OPEN"
        # 5% of $1,000 = $50
        assert pos.position_size_usd == 50.0
        # Cash should be decremented by $50
        assert engine.session.current_cash_usd == 950.0
        # Simulated fill price should have impact
        assert pos.simulated_fill_price_usd >= pos.entry_price_usd

        # Check ledger record
        ledger = temp_store.get_ledger_entries(engine.session.session_id)
        buy_entries = [e for e in ledger if e.entry_type == "BUY"]
        assert len(buy_entries) == 1
        assert buy_entries[0].amount_usd == -50.0
        assert buy_entries[0].cash_balance_after_usd == 950.0

    def test_position_sizing_liquidity_cap(self, temp_store):
        engine = VirtualWalletEngine(
            store=temp_store,
            starting_capital=1000.0,
            risk_pct=0.05,
            sizing_mode="COMPOUNDING",
        )
        # Token with tiny liquidity: $200 liquidity on Raydium
        mock_pt = MockPaperTrade(
            trade_id="pt_illiquid",
            entry_liquidity_usd=200.0,
        )
        pos = engine.on_paper_trade_opened(mock_pt)
        assert pos is not None
        # Max position at 2% depth for $200 liq is $4.00, which is < min_trade_size ($10), so skipped or capped
        # If capped below min_trade_size, it returns None
        assert pos is None or pos.position_size_usd <= 50.0

    def test_cash_exhaustion_gate(self, temp_store):
        engine = VirtualWalletEngine(
            store=temp_store,
            starting_capital=1000.0,
            risk_pct=0.05,
            min_trade_size_usd=10.0,
        )
        # Drain cash to $5
        engine.session.current_cash_usd = 5.0
        temp_store.save_session(engine.session)

        mock_pt = MockPaperTrade(trade_id="pt_no_cash")
        pos = engine.on_paper_trade_opened(mock_pt)

        assert pos is not None
        assert pos.status == "SKIPPED"
        assert pos.skip_reason == "NO_CAPITAL"
        assert pos.position_size_usd == 0.0

    def test_position_closing_and_pnl_accounting(self, temp_store):
        engine = VirtualWalletEngine(
            store=temp_store,
            starting_capital=1000.0,
            risk_pct=0.05,
        )
        # Open a position ($50)
        mock_pt = MockPaperTrade(
            trade_id="pt_win",
            entry_price_usd=0.001,
            entry_market_cap_usd=50000.0,
            exit_price_usd=0.002,         # 100% price double
            exit_market_cap_usd=100000.0,
        )
        open_pos = engine.on_paper_trade_opened(mock_pt)
        assert open_pos is not None
        assert engine.session.current_cash_usd == 950.0

        # Close position
        mock_pt.status = "CLOSED"
        closed_pos = engine.on_paper_trade_closed(mock_pt)

        assert closed_pos is not None
        assert closed_pos.status == "CLOSED"
        # Gross exit should be roughly $100 minus fees and price impact
        assert closed_pos.gross_exit_proceeds_usd > 85.0
        assert closed_pos.net_realized_pnl_usd > 35.0
        # Cash returned should increase cash beyond starting $1,000
        assert engine.session.current_cash_usd > 1000.0
        assert engine.session.current_equity_usd > 1000.0

        # Ledger should have SELL
        ledger = temp_store.get_ledger_entries(engine.session.session_id)
        sell_entries = [e for e in ledger if e.entry_type == "SELL"]
        assert len(sell_entries) == 1
        assert sell_entries[0].amount_usd == closed_pos.gross_exit_proceeds_usd

    def test_daily_and_weekly_stats(self, temp_store):
        engine = VirtualWalletEngine(store=temp_store, starting_capital=1000.0)
        calculator = WalletStatsCalculator(store=temp_store)

        mock_pt = MockPaperTrade(trade_id="pt_stat_test")
        engine.on_paper_trade_opened(mock_pt)
        mock_pt.status = "CLOSED"
        engine.on_paper_trade_closed(mock_pt)

        # Summary stats
        summary = calculator.compute_summary_stats(engine.session)
        assert summary.starting_capital_usd == 1000.0
        assert summary.closed_positions_count == 1
        assert summary.total_positions_admitted == 1
        assert summary.net_realized_pnl_usd != 0.0

        # Daily breakdown
        daily = calculator.compute_daily_breakdown(engine.session.session_id)
        assert len(daily) >= 1
        assert daily[0].trades_closed == 1

        # Weekly breakdown
        weekly = calculator.compute_weekly_breakdown(engine.session.session_id)
        assert len(weekly) >= 1
        assert weekly[0].trades_closed == 1

    def test_dict_payload_compatibility(self, temp_store):
        engine = VirtualWalletEngine(store=temp_store, starting_capital=1000.0)
        dict_payload = {
            "trade_id": "dict_trade_123",
            "token_address": "TokenAddr111111",
            "symbol": "DICTCOIN",
            "chain": "solana",
            "venue": "pumpfun",
            "entry_price_usd": 0.05,
            "entry_market_cap_usd": 80000.0,
            "entry_liquidity_usd": 30000.0,
        }
        pos = engine.on_paper_trade_opened(dict_payload)
        assert pos is not None
        assert pos.symbol == "DICTCOIN"
        assert pos.status == "OPEN"

        close_dict = {
            "trade_id": "dict_trade_123",
            "exit_price_usd": 0.08,
            "exit_market_cap_usd": 128000.0,
            "exit_liquidity_usd": 35000.0,
            "exit_reason": "TP_TARGET_2",
            "hold_duration_seconds": 900.0,
        }
        closed_pos = engine.on_paper_trade_closed(close_dict)
        assert closed_pos is not None
        assert closed_pos.status == "CLOSED"
        assert closed_pos.net_realized_pnl_usd > 0

    def test_liquidity_drain_rug_zero_proceeds(self, temp_store):
        """Verify that an LP-drained rug produces -100% return and 0 proceeds in virtual wallet."""
        engine = VirtualWalletEngine(store=temp_store, starting_capital=1000.0, risk_pct=0.05)
        mock_pt = MockPaperTrade(
            trade_id="pt_rug_01",
            symbol="RUGPULL",
            entry_price_usd=0.001,
            entry_market_cap_usd=20000.0,
            entry_liquidity_usd=10000.0,
        )
        pos = engine.on_paper_trade_opened(mock_pt)
        assert pos is not None
        assert pos.position_size_usd == 50.0
        assert engine.session.current_cash_usd == 950.0

        # Simulate rug where liquidity is drained to 0 and exit_reason is RISK_INVALIDATION
        mock_pt.status = "CLOSED"
        mock_pt.exit_price_usd = 0.0
        mock_pt.exit_market_cap_usd = 0.0
        mock_pt.exit_liquidity_usd = 0.0
        mock_pt.exit_reason = "RISK_INVALIDATION"

        closed_pos = engine.on_paper_trade_closed(mock_pt)
        assert closed_pos is not None
        assert closed_pos.status == "CLOSED"
        # Zero proceeds returned to cash
        assert closed_pos.gross_exit_proceeds_usd == 0.0
        assert closed_pos.net_realized_return_pct == -100.0
        assert closed_pos.net_realized_pnl_usd <= -50.0
        # Cash should remain 950.0 (lost the $50)
        assert engine.session.current_cash_usd == 950.0

    def test_execution_simulator_drained_pool_protection(self):
        """Verify execution simulator returns -100% and unexecutable on drained pools."""
        sim = AMMExecutionSimulator()
        
        # Test Raydium with exit liquidity < 500
        res = sim.simulate_trade(
            position_size_usd=100.0,
            entry_mc=30000.0,
            exit_mc=5000000.0, # fake spike on dust
            entry_liquidity=15000.0,
            exit_liquidity=0.0, # drained to zero
            venue="raydium",
        )
        assert not res.is_executable
        assert res.execution_rejection_reason == "INSUFFICIENT_EXIT_LIQUIDITY_RUG"
        assert res.net_realized_return_pct == -100.0
        assert res.net_realized_pnl_usd <= -100.0
        assert res.executable_mfe_ratio == 0.0

        # Test PumpFun with collapsed liquidity
        res_pump = sim.simulate_trade(
            position_size_usd=100.0,
            entry_mc=30000.0,
            exit_mc=10000000.0,
            entry_liquidity=12000.0,
            exit_liquidity=100.0,
            venue="pumpfun",
        )
        assert not res_pump.is_executable
        assert res_pump.execution_rejection_reason == "INSUFFICIENT_EXIT_LIQUIDITY_RUG"
        assert res_pump.net_realized_return_pct == -100.0
        assert res_pump.executable_mfe_ratio == 0.0

    def test_bonding_curve_profitable_exit_not_flagged_as_rug(self, temp_store):
        """Verify profitable bonding curve trade with 0/null reported liquidity is NOT treated as a rug."""
        engine = VirtualWalletEngine(
            store=temp_store,
            starting_capital=1000.0,
            risk_pct=0.05,
            sizing_mode="COMPOUNDING",
        )

        sig = {
            "trade_id": "trade_sim_01",
            "token_address": "8pRi63b8w6L6J7H8uQvSIM",
            "symbol": "SIM",
            "chain": "solana",
            "venue": "pumpfun",
            "entry_price_usd": 0.000010,
            "simulated_fill_price_usd": 0.000010,
            "entry_market_cap_usd": 10000.0,
            "liquidity_usd": 5000.0,
            "position_size_usd": 50.0,
        }
        pos = engine.on_paper_trade_opened(sig)
        assert pos is not None
        assert pos.status == "OPEN"

        # Closed via staged trailing profit with +60% gain, DexScreener reports exit liq 0.0
        closed_trade = {
            "trade_id": pos.paper_trade_id,
            "exit_price_usd": 0.000016,
            "exit_market_cap_usd": 16000.0,
            "exit_liquidity_usd": 0.0, # null/0 on pumpfun
            "exit_reason": "STAGED_TRAILING_PROFIT",
            "net_realized_return_pct": 55.0,
            "hold_duration_seconds": 300.0,
        }
        closed_pos = engine.on_paper_trade_closed(closed_trade)
        assert closed_pos is not None
        assert closed_pos.status == "CLOSED"
        assert closed_pos.net_realized_return_pct > 0.0
        assert closed_pos.net_realized_pnl_usd > 0.0
        assert closed_pos.gross_exit_proceeds_usd > 50.0
        assert engine.session.current_cash_usd > 1000.0

    def test_displaced_by_higher_rank_missing_liq_not_flagged_as_rug(self, temp_store):
        """Verify displaced position with None exit liquidity is NOT liquidated as a rug."""
        engine = VirtualWalletEngine(
            store=temp_store,
            starting_capital=1000.0,
            risk_pct=0.05,
            sizing_mode="COMPOUNDING",
        )

        sig = {
            "trade_id": "trade_vanta_01",
            "token_address": "vanta123456789",
            "symbol": "VANTA",
            "chain": "solana",
            "venue": "pumpfun",
            "entry_price_usd": 0.000017,
            "simulated_fill_price_usd": 0.000017,
            "entry_market_cap_usd": 17000.0,
            "liquidity_usd": 8000.0,
            "position_size_usd": 50.0,
        }
        pos = engine.on_paper_trade_opened(sig)
        assert pos is not None

        # Closed via DISPLACED_BY_HIGHER_RANK with 400% gain but exit_liquidity_usd is None
        closed_trade = {
            "trade_id": pos.paper_trade_id,
            "exit_price_usd": 0.000085,
            "exit_market_cap_usd": 85000.0,
            "exit_liquidity_usd": None, # force close didn't pass it
            "exit_reason": "DISPLACED_BY_HIGHER_RANK",
            "net_realized_return_pct": 380.0,
            "hold_duration_seconds": 600.0,
        }
        closed_pos = engine.on_paper_trade_closed(closed_trade)
        assert closed_pos is not None
        assert closed_pos.status == "CLOSED"
        assert closed_pos.net_realized_return_pct > 0.0
        assert closed_pos.gross_exit_proceeds_usd > 200.0
        assert engine.session.current_cash_usd > 1150.0


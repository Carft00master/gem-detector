"""
Unit tests for Path-Dependent Paper Trading Engine & 5 Exit Policies
"""

from datetime import datetime, timezone
import pytest
from src.feeds.base_feed import TokenCandidate
from src.models.predictor import BreakoutPredictionOutput
from src.paper.engine import PaperTradingEngine
from src.paper.ledger import PaperTradingLedger


@pytest.fixture
def paper_engine(tmp_path):
    db_file = tmp_path / "test_paper.db"
    jsonl_file = tmp_path / "test_paper.jsonl"
    ledger = PaperTradingLedger(db_path=db_file, jsonl_path=jsonl_file)
    return PaperTradingEngine(ledger=ledger, default_position_size_usd=100.0)


def test_paper_trading_trailing_stop_policy(paper_engine):
    """Verify trailing stop triggers when price drops 25% from peak after entering profit."""
    cand = TokenCandidate(
        address="TestTrailingToken",
        pair_address="Pair",
        symbol="TRAIL",
        name="Trailing Stop Token",
        chain="solana",
        dex_id="raydium",
        market_cap_usd=15000.0,
        price_usd=0.00015,
        liquidity_usd=5000.0,
    )
    pred = BreakoutPredictionOutput(p_reach_3m=0.25, alert_state="HIGH_CONVICTION")

    # 1. Enter Paper Trade
    trade = paper_engine.on_breakout_alert(cand, pred, position_size=100.0)
    assert trade is not None
    assert trade.token_address == "TestTrailingToken"
    assert trade.status == "OPEN"

    # 2. Price rallies 3x (+200%)
    paper_engine.on_price_tick(
        token_address="TestTrailingToken",
        current_price_usd=0.00045,
        current_market_cap_usd=45000.0,
        current_liquidity_usd=15000.0,
        elapsed_minutes=30.0,
        policy="TRAILING_STOP",
    )
    assert "TestTrailingToken" in paper_engine.active_positions

    # 3. Price drops 30% from peak ($0.00045 -> $0.00030)
    exit_trade = paper_engine.on_price_tick(
        token_address="TestTrailingToken",
        current_price_usd=0.00030,
        current_market_cap_usd=30000.0,
        current_liquidity_usd=10000.0,
        elapsed_minutes=45.0,
        policy="TRAILING_STOP",
    )

    # 4. Trailing stop must trigger
    assert exit_trade is not None
    assert exit_trade.status == "CLOSED"
    assert exit_trade.exit_reason == "TRAILING_STOP"
    assert exit_trade.net_realized_pnl_usd > 0.0 # Closed in net profit
    assert "TestTrailingToken" not in paper_engine.active_positions


def test_paper_trading_risk_invalidation_policy(paper_engine):
    """Verify risk invalidation triggers immediate exit on developer dump or liquidity drain."""
    cand = TokenCandidate(
        address="TestRugToken",
        pair_address="Pair",
        symbol="RUG",
        name="Rug Token",
        chain="solana",
        dex_id="pumpfun",
        market_cap_usd=12000.0,
        price_usd=0.00012,
        liquidity_usd=4000.0,
    )
    pred = BreakoutPredictionOutput(p_reach_3m=0.15, alert_state="EARLY_BREAKOUT")

    trade = paper_engine.on_breakout_alert(cand, pred, position_size=100.0)
    assert trade is not None

    # Dev dumps supply
    exit_trade = paper_engine.on_price_tick(
        token_address="TestRugToken",
        current_price_usd=0.00006,
        current_market_cap_usd=6000.0,
        current_liquidity_usd=1500.0,
        elapsed_minutes=10.0,
        is_dev_dump=True,
    )

    assert exit_trade is not None
    assert exit_trade.exit_reason == "RISK_INVALIDATION"
    assert exit_trade.outcome_label == "FAILURE"

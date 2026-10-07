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
        liquidity_usd=14000.0,
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
        current_liquidity_usd=40000.0,
        elapsed_minutes=30.0,
        policy="TRAILING_STOP",
    )
    assert "TestTrailingToken" in paper_engine.active_positions

    # 3. Price drops 30% from peak ($0.00045 -> $0.00030)
    exit_trade = paper_engine.on_price_tick(
        token_address="TestTrailingToken",
        current_price_usd=0.00030,
        current_market_cap_usd=30000.0,
        current_liquidity_usd=25000.0,
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
        liquidity_usd=11000.0,
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


def test_paper_trading_liquidity_drain_exit_and_serial_rug_protection(paper_engine):
    """Verify that drained pool causes -100% failure and blocks serial relaunch of same symbol."""
    cand = TokenCandidate(
        address="TestDrainedToken1",
        pair_address="Pair1",
        symbol="SCAMCOIN",
        name="Scam Coin",
        chain="solana",
        dex_id="raydium",
        market_cap_usd=20000.0,
        price_usd=0.0002,
        liquidity_usd=16000.0,
    )
    pred = BreakoutPredictionOutput(p_reach_3m=0.20, alert_state="EARLY_BREAKOUT")

    trade = paper_engine.on_breakout_alert(cand, pred, position_size=100.0)
    assert trade is not None

    # Simulate 100% LP drain with DexScreener division-by-zero price spike
    exit_trade = paper_engine.on_price_tick(
        token_address="TestDrainedToken1",
        current_price_usd=10.0, # astronomical dust spike
        current_market_cap_usd=5000000.0, # fake $5M MC
        current_liquidity_usd=0.0, # 100% liquidity pulled!
        elapsed_minutes=15.0,
        is_liquidity_drained=True,
    )

    assert exit_trade is not None
    assert exit_trade.exit_reason == "RISK_INVALIDATION"
    assert exit_trade.outcome_label == "FAILURE"
    assert exit_trade.net_realized_return_pct == -100.0
    assert exit_trade.net_realized_pnl_usd <= -100.0
    assert not exit_trade.target_reached_3m

    # Symbol SCAMCOIN should now be in rugged_symbols
    assert "SCAMCOIN" in paper_engine.rugged_symbols

    # Try to relaunch SCAMCOIN under a new contract address
    cand_relaunch = TokenCandidate(
        address="TestDrainedToken2_NewAddr",
        pair_address="Pair2",
        symbol="SCAMCOIN",
        name="Scam Coin Relaunch",
        chain="solana",
        dex_id="raydium",
        market_cap_usd=25000.0,
        price_usd=0.00025,
        liquidity_usd=20000.0,
    )
    relaunch_trade = paper_engine.on_breakout_alert(cand_relaunch, pred, position_size=100.0)
    # Must be blocked by serial rug protection!
    assert relaunch_trade is None


def test_paper_trading_liquidity_mc_ratio_gate(paper_engine):
    """Verify that paper trading rejects creator-seeded LP traps (ratio > 1.35) and paper-thin pools (< 0.20)."""
    pred = BreakoutPredictionOutput(p_reach_3m=0.20, alert_state="EARLY_BREAKOUT")

    # 1. Creator seeded LP trap: $10k MC, $20k LP (ratio 2.0 > 1.35)
    cand_trap = TokenCandidate(
        address="LpTrapToken",
        pair_address="Pair",
        symbol="LPTRAP",
        name="LP Trap Token",
        chain="solana",
        dex_id="raydium",
        market_cap_usd=10000.0,
        price_usd=0.0001,
        liquidity_usd=20000.0,
    )
    assert paper_engine.on_breakout_alert(cand_trap, pred, position_size=100.0) is None

    # 2. Paper-thin pool: $100k MC, $10k LP (ratio 0.10 < 0.20)
    cand_thin = TokenCandidate(
        address="ThinPoolToken",
        pair_address="Pair",
        symbol="THIN",
        name="Thin Pool Token",
        chain="solana",
        dex_id="raydium",
        market_cap_usd=100000.0,
        price_usd=0.001,
        liquidity_usd=10000.0,
    )
    assert paper_engine.on_breakout_alert(cand_thin, pred, position_size=100.0) is None


def test_graduation_fdv_jump_does_not_trigger_false_staged_exit(paper_engine):
    """
    Verify that in STAGED_EXITS, a post-graduation FDV jump to $1M+ without real price
    appreciation (price multiple < 1.5x) does NOT trigger a premature false target exit.
    """
    cand = TokenCandidate(
        address="GraduatingToken",
        pair_address="Pair",
        symbol="GRAD",
        name="Graduating Token",
        chain="solana",
        dex_id="pumpfun",
        market_cap_usd=30000.0,
        price_usd=0.00030,
        liquidity_usd=25000.0,
    )
    pred = BreakoutPredictionOutput(p_reach_3m=0.20, p_reach_500k=0.45, alert_state="EARLY_BREAKOUT")
    trade = paper_engine.on_breakout_alert(cand, pred, position_size=100.0)
    assert trade is not None
    trade.exit_policy = "STAGED_EXITS"

    # Token graduates: DexScreener immediately calculates FDV as $1,200,000,
    # but the price is still $0.000315 (only 1.05x price multiple, no real breakout yet)
    exit_trade = paper_engine.on_price_tick(
        token_address="GraduatingToken",
        current_price_usd=0.000315,
        current_market_cap_usd=1200000.0, # post-graduation FDV jump
        current_liquidity_usd=50000.0,
        elapsed_minutes=5.0,
        policy="STAGED_EXITS",
    )

    # Position must stay OPEN — not falsely trigger STAGED_FINAL_TARGET on feed unit mismatch
    assert exit_trade is None
    assert "GraduatingToken" in paper_engine.active_positions


def test_bonding_curve_immune_to_dexscreener_null_liquidity(paper_engine):
    """Verify that Pump.fun bonding curves are not falsely liquidated when DexScreener reports null/zero liquidity."""
    cand = TokenCandidate(
        address="RealPumpToken111111111111111111111111111pump",
        pair_address="PairPump1",
        symbol="PUMPTOKEN",
        name="Pump Token",
        chain="solana",
        dex_id="pump-fun",
        market_cap_usd=30000.0,
        price_usd=0.00003,
        liquidity_usd=18000.0,
    )
    pred = BreakoutPredictionOutput(p_reach_3m=0.25, alert_state="EARLY_BREAKOUT")
    trade = paper_engine.on_breakout_alert(cand, pred, position_size=100.0)
    assert trade is not None
    assert "RealPumpToken111111111111111111111111111pump" in paper_engine.active_positions

    # DexScreener polls tick with liquidity=0.0 (null liquidity API response) but token is healthy
    exit_trade = paper_engine.on_price_tick(
        token_address="RealPumpToken111111111111111111111111111pump",
        current_price_usd=0.000035,
        current_market_cap_usd=35000.0,
        current_liquidity_usd=0.0,
        elapsed_minutes=0.5,
        is_liquidity_drained=False,
    )
    # Position must NOT be liquidated!
    assert exit_trade is None
    assert "RealPumpToken111111111111111111111111111pump" in paper_engine.active_positions
    assert "PUMPTOKEN" not in paper_engine.rugged_symbols


def test_pumpswap_drained_pool_dust_spike_invalidation(paper_engine):
    """
    Verify that Pumpswap/AMM pools with drained liquidity and division-by-zero price spikes
    are recognized as RISK_INVALIDATION (-100% loss) and never recorded as fake wins.
    """
    cand = TokenCandidate(
        address="CS9h1jrajbHeK5SjrKhki8mxPQGt5nRrD48S4PVR6AXg",
        pair_address="5bXumLkh9XuNRoEMQLvvoeUNzuSxUpPEikpQZRt2wvxW",
        symbol="APP",
        name="Sent from my Pumpfun App",
        chain="solana",
        dex_id="pumpswap",
        market_cap_usd=10761.80,
        price_usd=0.00001076,
        liquidity_usd=10483.43,
    )
    pred = BreakoutPredictionOutput(p_reach_3m=0.08, alert_state="EARLY_BREAKOUT")
    trade = paper_engine.on_breakout_alert(cand, pred, position_size=100.0)
    assert trade is not None
    assert trade.venue == "pumpswap"

    # Liquidity is drained to $0.01 and price spikes 20,000x to $0.2373 ($237M FDV)
    exit_trade = paper_engine.on_price_tick(
        token_address="CS9h1jrajbHeK5SjrKhki8mxPQGt5nRrD48S4PVR6AXg",
        current_price_usd=0.2373,
        current_market_cap_usd=237330183.0,
        current_liquidity_usd=0.01,
        elapsed_minutes=0.2,
        is_liquidity_drained=True,
    )

    assert exit_trade is not None
    assert exit_trade.exit_reason == "RISK_INVALIDATION"
    assert exit_trade.outcome_label == "FAILURE"
    assert exit_trade.net_realized_return_pct == -100.0
    assert exit_trade.net_realized_pnl_usd <= -100.0
    assert not exit_trade.target_reached_3m
    assert "APP" in paper_engine.rugged_symbols


def test_staged_exits_early_breakeven_lock(paper_engine):
    """Verify that in STAGED_EXITS, reaching +25% locks the position at breakeven +3%."""
    cand = TokenCandidate(
        address="TestBreakoutToken25",
        pair_address="Pair25",
        symbol="BE25",
        name="Breakeven 25 Token",
        chain="solana",
        dex_id="pumpswap",
        market_cap_usd=20000.0,
        price_usd=0.00010,
        liquidity_usd=12000.0,
    )
    pred = BreakoutPredictionOutput(p_reach_3m=0.20, alert_state="EARLY_BREAKOUT")
    trade = paper_engine.on_breakout_alert(cand, pred, position_size=100.0)
    assert trade is not None
    trade.exit_policy = "STAGED_EXITS"

    # Price rallies to +30% ($0.000130, multiple = 1.30x)
    paper_engine.on_price_tick(
        token_address="TestBreakoutToken25",
        current_price_usd=0.000130,
        current_market_cap_usd=26000.0,
        current_liquidity_usd=15000.0,
        elapsed_minutes=5.0,
        policy="STAGED_EXITS",
    )
    assert "TestBreakoutToken25" in paper_engine.active_positions

    # Price dumps back to $0.000104 (below 1.05x breakeven threshold)
    exit_trade = paper_engine.on_price_tick(
        token_address="TestBreakoutToken25",
        current_price_usd=0.000104,
        current_market_cap_usd=20800.0,
        current_liquidity_usd=12000.0,
        elapsed_minutes=10.0,
        policy="STAGED_EXITS",
    )
    assert exit_trade is not None
    assert exit_trade.exit_reason == "STAGED_BREAKEVEN_PROTECTION"
    assert exit_trade.net_realized_pnl_usd >= -5.0  # Protected from dump loss (-48%)


def test_staged_exits_momentum_trailing_profit(paper_engine):
    """Verify that in STAGED_EXITS, reaching +50% triggers trailing profit on a 25% drop from peak."""
    cand = TokenCandidate(
        address="TestTrailToken50",
        pair_address="Pair50",
        symbol="TRAIL50",
        name="Trailing 50 Token",
        chain="solana",
        dex_id="pumpswap",
        market_cap_usd=20000.0,
        price_usd=0.00010,
        liquidity_usd=12000.0,
    )
    pred = BreakoutPredictionOutput(p_reach_3m=0.20, alert_state="EARLY_BREAKOUT")
    trade = paper_engine.on_breakout_alert(cand, pred, position_size=100.0)
    assert trade is not None
    trade.exit_policy = "STAGED_EXITS"

    # Price rallies to +50% ($0.000150, multiple = 1.50x)
    paper_engine.on_price_tick(
        token_address="TestTrailToken50",
        current_price_usd=0.000150,
        current_market_cap_usd=30000.0,
        current_liquidity_usd=18000.0,
        elapsed_minutes=8.0,
        policy="STAGED_EXITS",
    )
    assert "TestTrailToken50" in paper_engine.active_positions

    # Price drops 27% from peak to $0.000110
    exit_trade = paper_engine.on_price_tick(
        token_address="TestTrailToken50",
        current_price_usd=0.000110,
        current_market_cap_usd=22000.0,
        current_liquidity_usd=13000.0,
        elapsed_minutes=15.0,
        policy="STAGED_EXITS",
    )
    assert exit_trade is not None
    assert exit_trade.exit_reason == "STAGED_TRAILING_PROFIT"
    assert exit_trade.net_realized_pnl_usd > 0.0  # Closed in profit


def test_stonkfun_toxic_pool_rejection(paper_engine):
    """Verify that tokens from stonkfun are rejected by toxic pool defense."""
    cand = TokenCandidate(
        address="StonkFunTokenAddr",
        pair_address="PairSF",
        symbol="STONK",
        name="Stonk Token",
        chain="solana",
        dex_id="stonkfun",
        market_cap_usd=15000.0,
        price_usd=0.00015,
        liquidity_usd=10000.0,
    )
    pred = BreakoutPredictionOutput(p_reach_3m=0.20, alert_state="EARLY_BREAKOUT")
    trade = paper_engine.on_breakout_alert(cand, pred, position_size=100.0)
    assert trade is None


def test_sub_6000_liquidity_rejected(paper_engine):
    """Verify that tokens below $6,000 liquidity floor are rejected."""
    cand = TokenCandidate(
        address="Sub6kLiqTokenAddr",
        pair_address="PairSub6k",
        symbol="THIN6K",
        name="Thin 6K Token",
        chain="solana",
        dex_id="pumpswap",
        market_cap_usd=15000.0,
        price_usd=0.00015,
        liquidity_usd=4500.0,  # Below $6,000
    )
    pred = BreakoutPredictionOutput(p_reach_3m=0.20, alert_state="EARLY_BREAKOUT")
    trade = paper_engine.on_breakout_alert(cand, pred, position_size=100.0)
    assert trade is None


def test_bump_bot_micro_churn_rejected(paper_engine):
    """Verify that bump bot micro-churn ($1.71 across 70 txns) is rejected."""
    cand = TokenCandidate(
        address="BumpBotTokenAddr",
        pair_address="PairBump",
        symbol="BUMPBOT",
        name="Bump Bot Churn Token",
        chain="solana",
        dex_id="pumpswap",
        market_cap_usd=15000.0,
        price_usd=0.00015,
        liquidity_usd=10000.0,
        volume_5m_usd=120.0,
        txns_5m_buys=50,
        txns_5m_sells=20,
    )
    pred = BreakoutPredictionOutput(p_reach_3m=0.20, alert_state="EARLY_BREAKOUT")
    trade = paper_engine.on_breakout_alert(cand, pred, position_size=100.0)
    assert trade is None


def test_hyper_turnover_wash_volume_rejected(paper_engine):
    """Verify that hyper-turnover circular volume (4.375x pool liquidity) is rejected."""
    cand = TokenCandidate(
        address="HyperTurnoverTokenAddr",
        pair_address="PairHyper",
        symbol="TURNOVER",
        name="Hyper Turnover Token",
        chain="solana",
        dex_id="pumpswap",
        market_cap_usd=20000.0,
        price_usd=0.00020,
        liquidity_usd=8000.0,
        volume_5m_usd=35000.0,
        txns_5m_buys=25,
        txns_5m_sells=25,
    )
    pred = BreakoutPredictionOutput(p_reach_3m=0.20, alert_state="EARLY_BREAKOUT")
    trade = paper_engine.on_breakout_alert(cand, pred, position_size=100.0)
    assert trade is None


def test_nascent_token_few_txns_accepted(paper_engine):
    """Verify that nascent tokens with few transactions (< 40 txns) pass cleanly without false positive."""
    cand = TokenCandidate(
        address="NascentGemTokenAddr",
        pair_address="PairNascent",
        symbol="NASCENT",
        name="Nascent Gem Token",
        chain="solana",
        dex_id="pumpswap",
        market_cap_usd=12000.0,
        price_usd=0.00012,
        liquidity_usd=8000.0,
        volume_5m_usd=5.0,
        txns_5m_buys=6,
        txns_5m_sells=2,
    )
    pred = BreakoutPredictionOutput(p_reach_3m=0.20, alert_state="EARLY_BREAKOUT")
    trade = paper_engine.on_breakout_alert(cand, pred, position_size=100.0)
    assert trade is not None
    assert trade.token_address == "NascentGemTokenAddr"

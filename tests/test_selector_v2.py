"""
Unit and Integration Tests for SELECTOR_v2_HIGH_CONVICTION
Verifies:
1. Token Setup State Machine (First-Alert Unit & Repeated Setup Suppression)
2. 8 High-Conviction Feature Groups
3. Confluence Requirement (>= 4 Axes)
4. False-Positive Elimination (5 Loss Archetypes)
5. Setup Quality Model & Tier Classification (A+, A, B, C, REJECT)
6. Expected-Value Formulation
7. Opportunity Displacement & Trade Budget Caps
8. Chronological Entity-Disjoint Walk-Forward Partitioning
"""

import pytest
from src.research.selector_v2_high_conviction import (
    TokenSetupState,
    TokenSetupStateMachine,
    FeatureExtractorV2,
    ConfluenceEngine,
    FalsePositivePruner,
    ExpectedValueEngine,
    SetupQualityModel,
    SetupTier,
    TradeBudgetConfig,
    OpportunityDisplacementEngine,
    WalkForwardValidator,
    SelectorV2HighConvictionEngine,
)


# ------------------------------------------------------------------------------
# 1. TOKEN SETUP STATE MACHINE TESTS
# ------------------------------------------------------------------------------

def test_token_state_machine_first_alert_primary_unit():
    sm = TokenSetupStateMachine(cooldown_minutes=60.0, re_entry_consolidation_pct=20.0)
    addr = "Token_Test_001"
    sym = "TEST1"

    # Step 1: Initial state below $8k is WATCHING
    state, can_trade, reason = sm.evaluate_transition(
        token_address=addr,
        symbol=sym,
        timestamp="2026-09-01T10:00:00Z",
        current_mc=6500.0,
        is_qualifying_setup=True,
        setup_score=75.0,
    )
    assert state == TokenSetupState.WATCHING
    assert not can_trade
    assert "MC_BELOW_DISCOVERY_FLOOR" in reason

    # Step 2: Rises to $12k with qualifying setup -> FIRST_ALERT_QUALIFIED
    state, can_trade, reason = sm.evaluate_transition(
        token_address=addr,
        symbol=sym,
        timestamp="2026-09-01T10:05:00Z",
        current_mc=12000.0,
        is_qualifying_setup=True,
        setup_score=82.0,
    )
    assert state == TokenSetupState.QUALIFIED
    assert can_trade
    assert "FIRST_ALERT_QUALIFIED" in reason

    # Step 3: Executed into trade
    sm.mark_traded(addr, "2026-09-01T10:05:30Z")
    rec = sm.tokens[addr]
    assert rec.state == TokenSetupState.TRADED
    assert rec.trade_count == 1

    # Step 4: Repeated ticks at same price or minor variation -> REPEATED_SETUP_SUPPRESSED
    state, can_trade, reason = sm.evaluate_transition(
        token_address=addr,
        symbol=sym,
        timestamp="2026-09-01T10:15:00Z",
        current_mc=12500.0,
        is_qualifying_setup=True,
        setup_score=85.0,
    )
    assert not can_trade
    assert reason == "REPEATED_SETUP_SUPPRESSED"

    # Step 5: After cooldown AND >= 20% consolidation, new breakout wave allowed
    # Drop to $9,000 (28% consolidation from $12,500 peak)
    sm.evaluate_transition(addr, sym, "2026-09-01T11:00:00Z", 9000.0, False, 40.0)

    # Post-cooldown fresh setup at 11:30:00
    state, can_trade, reason = sm.evaluate_transition(
        token_address=addr,
        symbol=sym,
        timestamp="2026-09-01T11:30:00Z",
        current_mc=11000.0,
        is_qualifying_setup=True,
        setup_score=78.0,
    )
    assert state == TokenSetupState.QUALIFIED
    assert can_trade
    assert "MATERIAL_NEW_SETUP" in reason


def test_token_fatal_invalidation():
    sm = TokenSetupStateMachine()
    addr = "Token_Rug_001"
    sym = "RUG"

    state, can_trade, reason = sm.evaluate_transition(
        token_address=addr,
        symbol=sym,
        timestamp="2026-09-01T12:00:00Z",
        current_mc=15000.0,
        is_qualifying_setup=True,
        setup_score=80.0,
        has_fatal_red_flag=True,
    )
    assert state == TokenSetupState.INVALIDATED
    assert not can_trade
    assert reason == "INVALIDATED_FATAL_RED_FLAG"


# ------------------------------------------------------------------------------
# 2. FEATURE GROUPS & CONFLUENCE TESTS
# ------------------------------------------------------------------------------

def test_feature_extraction_and_confluence():
    token = {
        "token_address": "Token_Confluence_001",
        "symbol": "CONF",
        "entry_market_cap_usd": 18000.0,
        "entry_liquidity_usd": 14000.0,
        "p_reach_3m_at_entry": 0.165,
        "p_reach_100k_at_entry": 0.45,
        "p_reach_500k_at_entry": 0.32,
        "p_reach_1m_at_entry": 0.22,
        "volume_5m_usd": 15000.0,
        "volume_1h_usd": 40000.0,
        "unique_buyers": 55,
        "unique_sellers": 20,
        "txns_5m_buys": 60,
        "txns_5m_sells": 25,
        "validated_wallet_count": 2,
        "independent_wallet_count": 2,
        "wash_trade_risk": 0.05,
        "cabal_risk_at_entry": 0.08,
        "regime": "HOT",
        "entry_slippage_pct": 1.2,
        "entry_price_impact_pct": 1.1,
    }

    fb = FeatureExtractorV2.extract(token)
    assert fb.p3m == 0.165
    assert fb.liquidity_usd == 14000.0
    assert fb.unique_buyers_to_tx_ratio >= 0.8
    assert fb.regime == "HOT"

    cr = ConfluenceEngine.evaluate(fb)
    assert cr.confluence_count >= 5
    assert cr.is_confluent
    assert "PROBABILITY" in cr.confirmed_axes
    assert "MOMENTUM" in cr.confirmed_axes
    assert "PARTICIPATION" in cr.confirmed_axes
    assert "MARKET_QUALITY" in cr.confirmed_axes


# ------------------------------------------------------------------------------
# 3. FALSE-POSITIVE PRUNER TESTS
# ------------------------------------------------------------------------------

def test_false_positive_low_breadth():
    # High P3M but only 12 unique buyers
    token = {
        "p_reach_3m_at_entry": 0.18,
        "unique_buyers": 12,
        "entry_market_cap_usd": 20000.0,
        "entry_liquidity_usd": 12000.0,
    }
    fb = FeatureExtractorV2.extract(token)
    fp = FalsePositivePruner.evaluate(fb, token)
    assert fp.is_false_positive
    assert "FP_HIGH_P3M_LOW_BREADTH" in fp.triggered_filters


def test_false_positive_wash_pump():
    # Volume/Liquidity massive + cabal concentration high
    token = {
        "entry_market_cap_usd": 10000.0,
        "entry_liquidity_usd": 10000.0,
        "volume_5m_usd": 65000.0,
        "cabal_risk_at_entry": 0.55,
        "wash_trade_risk": 0.45,
    }
    fb = FeatureExtractorV2.extract(token)
    fp = FalsePositivePruner.evaluate(fb, token)
    assert fp.is_false_positive
    assert "FP_WASH_PUMP_LOW_INDEPENDENCE" in fp.triggered_filters


def test_false_positive_thin_spike():
    # Price velocity high but pool liquidity is sub-$6k
    token = {
        "entry_market_cap_usd": 35000.0,
        "entry_liquidity_usd": 5000.0,
        "volume_5m_usd": 40000.0,
        "price_velocity": 85.0,
    }
    fb = FeatureExtractorV2.extract(token)
    fp = FalsePositivePruner.evaluate(fb, token)
    assert fp.is_false_positive
    assert "FP_HIGH_MOMENTUM_THIN_LIQUIDITY" in fp.triggered_filters


# ------------------------------------------------------------------------------
# 4. SETUP QUALITY MODEL & TIERS
# ------------------------------------------------------------------------------

def test_setup_quality_tiers():
    strong_token = {
        "token_address": "Token_Strong",
        "symbol": "STRG",
        "entry_market_cap_usd": 16000.0,
        "entry_liquidity_usd": 18000.0,
        "p_reach_3m_at_entry": 0.185,
        "p_reach_100k_at_entry": 0.50,
        "p_reach_500k_at_entry": 0.38,
        "p_reach_1m_at_entry": 0.28,
        "volume_5m_usd": 25000.0,
        "volume_1h_usd": 60000.0,
        "unique_buyers": 75,
        "unique_sellers": 22,
        "txns_5m_buys": 80,
        "txns_5m_sells": 25,
        "validated_wallet_count": 3,
        "independent_wallet_count": 3,
        "wash_trade_risk": 0.03,
        "cabal_risk_at_entry": 0.05,
        "regime": "HOT",
        "entry_slippage_pct": 0.8,
        "entry_price_impact_pct": 0.8,
        "data_confidence_at_entry": 0.95,
    }

    res = SetupQualityModel.evaluate(strong_token)
    assert res.is_eligible
    assert res.tier in (SetupTier.A_PLUS, SetupTier.A)
    assert res.setup_quality_score >= 70.0
    assert res.confluence_count >= 5
    assert res.expected_value > 0.0


# ------------------------------------------------------------------------------
# 5. OPPORTUNITY DISPLACEMENT & TRADE BUDGET TESTS
# ------------------------------------------------------------------------------

def test_opportunity_displacement_and_budget():
    budget = TradeBudgetConfig(
        max_new_trades_per_hour=2,
        max_simultaneous_positions=4,
    )
    engine = OpportunityDisplacementEngine(budget)

    # 4 simultaneous qualifying candidates in the same hour
    c1 = {
        "token_address": "T1", "symbol": "CAND1", "timestamp": "2026-09-01T14:00:00Z",
        "entry_market_cap_usd": 15000.0, "entry_liquidity_usd": 15000.0, "p_reach_3m_at_entry": 0.20,
        "p_reach_100k_at_entry": 0.55, "p_reach_500k_at_entry": 0.40, "p_reach_1m_at_entry": 0.30,
        "volume_5m_usd": 20000.0, "volume_1h_usd": 50000.0,
        "unique_buyers": 60, "txns_5m_buys": 65, "validated_wallet_count": 2, "cabal_risk_at_entry": 0.05,
        "wash_trade_risk": 0.04,
    }
    c2 = {
        "token_address": "T2", "symbol": "CAND2", "timestamp": "2026-09-01T14:00:00Z",
        "entry_market_cap_usd": 12000.0, "entry_liquidity_usd": 14000.0, "p_reach_3m_at_entry": 0.18,
        "p_reach_100k_at_entry": 0.50, "p_reach_500k_at_entry": 0.35, "p_reach_1m_at_entry": 0.25,
        "volume_5m_usd": 16000.0, "volume_1h_usd": 40000.0,
        "unique_buyers": 50, "txns_5m_buys": 55, "validated_wallet_count": 2, "cabal_risk_at_entry": 0.06,
        "wash_trade_risk": 0.04,
    }
    c3 = {
        "token_address": "T3", "symbol": "CAND3", "timestamp": "2026-09-01T14:00:00Z",
        "entry_market_cap_usd": 10000.0, "entry_liquidity_usd": 11000.0, "p_reach_3m_at_entry": 0.17,
        "p_reach_100k_at_entry": 0.48, "p_reach_500k_at_entry": 0.32, "p_reach_1m_at_entry": 0.22,
        "volume_5m_usd": 12000.0, "volume_1h_usd": 30000.0,
        "unique_buyers": 45, "txns_5m_buys": 50, "validated_wallet_count": 1, "cabal_risk_at_entry": 0.08,
        "wash_trade_risk": 0.05,
    }
    c4 = {
        "token_address": "T4", "symbol": "CAND4", "timestamp": "2026-09-01T14:00:00Z",
        "entry_market_cap_usd": 9500.0, "entry_liquidity_usd": 10500.0, "p_reach_3m_at_entry": 0.165,
        "p_reach_100k_at_entry": 0.45, "p_reach_500k_at_entry": 0.30, "p_reach_1m_at_entry": 0.20,
        "volume_5m_usd": 10000.0, "volume_1h_usd": 25000.0,
        "unique_buyers": 40, "txns_5m_buys": 45, "validated_wallet_count": 1, "cabal_risk_at_entry": 0.09,
        "wash_trade_risk": 0.05,
    }

    selected = engine.process_candidates_window([c1, c2, c3, c4], "2026-09-01T14", top_k_pct=100.0)

    # Budget cap is 2 per hour: only T1 and T2 admitted, T3 and T4 displaced!
    assert len(selected) == 2
    selected_symbols = [s["symbol"] for s in selected]
    assert "CAND1" in selected_symbols
    assert "CAND2" in selected_symbols
    assert "CAND3" not in selected_symbols
    assert "CAND4" not in selected_symbols


# ------------------------------------------------------------------------------
# 6. WALK-FORWARD CHRONOLOGICAL ENTITY-DISJOINT PARTITIONING
# ------------------------------------------------------------------------------

def test_chronological_entity_disjoint_split():
    mock_trades = []
    for i in range(100):
        mock_trades.append({
            "token_address": f"Token_{i:03d}",
            "symbol": f"SYM_{i:03d}",
            "entry_signal_timestamp": f"2026-08-{1 + (i // 4):02d}T12:00:00Z",
            "net_realized_return_pct": 5.0 if i % 3 == 0 else -6.0,
            "net_realized_pnl_usd": 5.0 if i % 3 == 0 else -6.0,
            "target_reached_3m": 1 if i % 25 == 0 else 0,
        })

    train, val, locked = WalkForwardValidator.partition_trades_chronological(mock_trades)
    train_tokens = set(t["token_address"] for t in train)
    val_tokens = set(t["token_address"] for t in val)
    locked_tokens = set(t["token_address"] for t in locked)

    # Entity-disjoint validation: zero token overlap
    assert len(train_tokens.intersection(val_tokens)) == 0
    assert len(train_tokens.intersection(locked_tokens)) == 0
    assert len(val_tokens.intersection(locked_tokens)) == 0

    # Chronological ordering check
    assert max(t["entry_signal_timestamp"] for t in train) <= min(t["entry_signal_timestamp"] for t in val)
    assert max(t["entry_signal_timestamp"] for t in val) <= min(t["entry_signal_timestamp"] for t in locked)


# ------------------------------------------------------------------------------
# 7. ANTI-FAKE-VOLUME HARD SAFETY GATE V2.2 TESTS
# ------------------------------------------------------------------------------

def test_hard_safety_gate_v22_bump_bot_micro_churn_rejected():
    from src.research.selector_v2_2_recovery import HardSafetyGateV22
    token = {
        "token_address": "BumpToken",
        "symbol": "BUMP",
        "market_cap_usd": 25000.0,
        "liquidity_usd": 12000.0,
        "volume_5m_usd": 150.0,
        "txns_5m_buys": 50,
        "txns_5m_sells": 25,
        "unique_buyers": 15,
    }
    fb = FeatureExtractorV2.extract(token)
    is_safe, rejections = HardSafetyGateV22.evaluate(token, fb)
    assert not is_safe
    assert any("BUMP_BOT_MICRO_CHURN" in r for r in rejections)


def test_hard_safety_gate_v22_hyper_turnover_wash_volume_rejected():
    from src.research.selector_v2_2_recovery import HardSafetyGateV22
    token = {
        "token_address": "HyperTurnoverToken",
        "symbol": "HYPER",
        "market_cap_usd": 25000.0,
        "liquidity_usd": 8000.0,
        "volume_5m_usd": 32000.0,  # 4.0x pool liquidity
        "txns_5m_buys": 30,
        "txns_5m_sells": 30,
        "unique_buyers": 20,
    }
    fb = FeatureExtractorV2.extract(token)
    is_safe, rejections = HardSafetyGateV22.evaluate(token, fb)
    assert not is_safe
    assert any("HYPER_TURNOVER_WASH_VOLUME" in r for r in rejections)


def test_hard_safety_gate_v22_nascent_token_accepted():
    from src.research.selector_v2_2_recovery import HardSafetyGateV22
    token = {
        "token_address": "NascentWinner",
        "symbol": "WINNER",
        "market_cap_usd": 15000.0,
        "liquidity_usd": 9000.0,
        "volume_5m_usd": 6.0,   # Micro volume in first seconds
        "txns_5m_buys": 6,
        "txns_5m_sells": 2,     # 8 txns total (< 40 threshold)
        "unique_buyers": 5,
    }
    fb = FeatureExtractorV2.extract(token)
    is_safe, rejections = HardSafetyGateV22.evaluate(token, fb)
    assert is_safe
    assert len(rejections) == 0

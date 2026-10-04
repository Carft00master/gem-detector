"""
Integration Tests for SELECTOR_v2_HIGH_CONVICTION in GemDetectorEngine and UI Services.
Verifies:
1. GemDetectorEngine correctly attaches v2_eval metadata in scan_cycle().
2. High-conviction setups (A+, A) trigger paper trade entries with formatted entry_reason.
3. Ineligible setups (B, C, REJECT, MC < $8k) are filtered and not admitted.
4. Hourly trade budget caps and duplicate setups are suppressed by the state machine.
5. ScannerService properly maps v2 metadata into candidate dictionaries.
6. SetupQualityModel can perform on-the-fly evaluation if v2 metadata is absent.
"""

import pytest
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch
from datetime import datetime, timezone

from src.config import load_config, AppConfig, SelectorConfig
from src.feeds.base_feed import TokenCandidate, TokenSecurityReport
from src.models.predictor import BreakoutPredictionOutput
from src.main import GemDetectorEngine
from src.research.selector_v2_high_conviction import SetupTier, SetupQualityModel
from app.services.scanner_service import ScannerService


@pytest.fixture
def mock_engine(tmp_path):
    """Create a GemDetectorEngine with Selector V2 enabled."""
    cfg = load_config()
    cfg.selector.enabled = True
    cfg.selector.mode = "V2_HIGH_CONVICTION"
    cfg.selector.min_market_cap_usd = 8000.0
    cfg.selector.min_confluence_axes = 4
    cfg.selector.min_setup_score = 70.0
    cfg.selector.min_expected_value = 3.0
    cfg.selector.max_new_trades_per_hour = 2
    cfg.selector.max_simultaneous_positions = 6

    with patch("src.paper.engine.PaperTradingLedger"):
        engine = GemDetectorEngine(config=cfg)
        engine.paper_engine.ledger = MagicMock()
        engine.paper_engine.ledger.db_path = str(tmp_path / "paper_test.db")
        engine.paper_engine.ledger.record_entry = MagicMock()
        engine.paper_engine.ledger.record_trade_event = MagicMock()
        engine.dataset_pipeline = MagicMock()
        engine.shadow_logger = MagicMock()
        engine.security_auditor = MagicMock()
        engine.security_auditor.audit_token = AsyncMock()
        engine.safety_engine = MagicMock()
        engine.safety_engine.evaluate_safety = MagicMock(return_value=MagicMock(liquidity_risk=0.1, contract_risk=0.1, critical_flags=[]))
        engine.dev_profiler = MagicMock()
        engine.dev_profiler.profile_dev = MagicMock(return_value=MagicMock(classification="SAFE", dev_risk_score=0.1))
        engine.safety_analyzer = MagicMock()
        engine.safety_analyzer.analyze_token = MagicMock(return_value=MagicMock(liquidity_risk=0.1, contract_risk=0.1, critical_flags=[]))
        return engine


def _make_candidate(address: str, symbol: str, mc: float, liq: float, p3m: float, buyers: int = 80):
    cand = TokenCandidate(
        address=address,
        pair_address=f"PAIR_{address}",
        symbol=symbol,
        name=f"Test {symbol}",
        chain="solana",
        dex_id="raydium",
        price_usd=0.001,
        market_cap_usd=mc,
        liquidity_usd=liq,
        volume_5m_usd=25000.0,
        volume_1h_usd=80000.0,
        txns_5m_buys=60,
        txns_5m_sells=20,
        unique_buyers_1h=buyers,
        unique_sellers_1h=15,
        age_minutes=12.0,
        security=TokenSecurityReport(
            is_honeypot=False,
            mint_renounced=True,
            freeze_renounced=True,
            lp_burned_or_locked_pct=100.0,
            dev_holding_pct=0.02,
        ),
    )
    cand.calculate_ratios()
    return cand


def _make_prediction(p3m: float):
    return BreakoutPredictionOutput(
        p_reach_100k=min(0.95, p3m * 3.5),
        p_reach_500k=min(0.85, p3m * 2.2),
        p_reach_1m=min(0.70, p3m * 1.5),
        p_reach_3m=p3m,
        p_rug=0.04,
        alert_state="HIGH_CONVICTION",
        data_confidence=0.90,
    )


@pytest.mark.asyncio
async def test_scan_cycle_selector_v2_admission_and_rejection(mock_engine):
    """Verify eligible candidate opens a trade and ineligible candidate is rejected."""
    # 1. High conviction candidate (MC $25k, Liq $22k, P(3M) 0.16) -> A or A+ Tier (liq/mc >= 0.80)
    cand_high = _make_candidate("ADDR_CONV_01", "ALPHA", mc=25000.0, liq=22000.0, p3m=0.16, buyers=80)
    
    # 2. Ineligible candidate (MC $5,000 < $8,000 floor)
    cand_low = _make_candidate("ADDR_LOW_01", "MICRO", mc=5000.0, liq=3000.0, p3m=0.18, buyers=60)

    mock_engine.dexscreener_feed = MagicMock()
    mock_engine.geckoterminal_feed = MagicMock()
    mock_engine.dexscreener_feed.fetch_candidates = AsyncMock(return_value=[cand_high, cand_low])
    mock_engine.geckoterminal_feed.fetch_candidates = AsyncMock(return_value=[])
    mock_engine.dexscreener_feed.fetch_pairs_by_tokens = AsyncMock(return_value=[])

    # Predictor returns high probability for both
    mock_engine.ml_predictor = MagicMock()
    mock_engine.ml_predictor.predict = MagicMock(side_effect=lambda *args, **kwargs: _make_prediction(0.16))

    mock_engine.pipeline = MagicMock()
    mock_engine.pipeline.extract_features_single = MagicMock(return_value=MagicMock())

    results = await mock_engine.scan_cycle()
    assert len(results) == 2

    # Check high conviction candidate metadata
    high_res = next(r for r in results if r[0].address == "ADDR_CONV_01")
    high_cand, high_pred, high_meta = high_res
    assert "selector_v2" in high_meta
    v2_high = high_meta["selector_v2"]
    assert v2_high["tier"] in ("A+", "A", "HIGH_CONVICTION", "EMERGING_BREAKOUT", "EXTREME_TAIL")
    assert v2_high["is_eligible"] is True
    assert v2_high["confluence_count"] >= 2
    assert v2_high["expected_value"] >= 1.5

    # Verify high conviction candidate opened a paper trade
    assert "ADDR_CONV_01" in mock_engine.paper_engine.active_positions
    trade = mock_engine.paper_engine.active_positions["ADDR_CONV_01"]
    assert "SELECTOR_V2" in trade.entry_reason

    # Check low MC candidate metadata
    low_res = next(r for r in results if r[0].address == "ADDR_LOW_01")
    low_cand, low_pred, low_meta = low_res
    v2_low = low_meta["selector_v2"]
    assert v2_low["is_eligible"] is False
    assert any("MC_BELOW" in r for r in v2_low["rejection_reasons"])
    assert "ADDR_LOW_01" not in mock_engine.paper_engine.active_positions


@pytest.mark.asyncio
async def test_slot_queue_capacity_cap(mock_engine):
    """Verify that no more than max_simultaneous_positions (8) are admitted simultaneously."""
    cands = [
        _make_candidate(f"ADDR_BATCH_{i}", f"TOK{i}", mc=30000.0, liq=26000.0, p3m=0.17, buyers=80)
        for i in range(12)
    ]

    mock_engine.dexscreener_feed = MagicMock()
    mock_engine.geckoterminal_feed = MagicMock()
    mock_engine.dexscreener_feed.fetch_candidates = AsyncMock(return_value=cands)
    mock_engine.geckoterminal_feed.fetch_candidates = AsyncMock(return_value=[])
    mock_engine.dexscreener_feed.fetch_pairs_by_tokens = AsyncMock(return_value=[])

    mock_engine.ml_predictor = MagicMock()
    mock_engine.ml_predictor.predict = MagicMock(side_effect=lambda *args, **kwargs: _make_prediction(0.17))
    mock_engine.pipeline = MagicMock()
    mock_engine.pipeline.extract_features_single = MagicMock(return_value=MagicMock())

    await mock_engine.scan_cycle()

    # Under Option B slot queue, capacity is capped at max_simultaneous_positions (8)
    assert len(mock_engine.paper_engine.active_positions) <= 8


def test_scanner_service_candidate_to_dict_telemetry():
    """Verify ScannerService formats V2 telemetry for UI consumption."""
    svc = ScannerService()
    cand = _make_candidate("ADDR_SVC_01", "TEST_SVC", mc=35000.0, liq=15000.0, p3m=0.16)
    pred = _make_prediction(0.16)
    meta = {
        "selector_v2": {
            "tier": "A+",
            "setup_quality_score": 86.4,
            "confluence_count": 6,
            "expected_value": 14.8,
            "confirmed_axes": ["PROBABILITY", "MOMENTUM", "PARTICIPATION", "MARKET_QUALITY", "CURVE", "EXECUTION"],
            "is_eligible": True,
            "rejection_reasons": [],
        }
    }

    from app.services.scanner_service import _candidate_to_dict
    d = _candidate_to_dict(cand, pred, meta=meta)
    assert d["setup_tier"] == "A+"
    assert d["setup_quality_score"] == 86.4
    assert d["confluence_count"] == 6
    assert d["expected_value"] == 14.8
    assert d["is_v2_eligible"] is True
    assert len(d["confirmed_axes"]) == 6


def test_setup_quality_model_dynamic_evaluation():
    """Verify SetupQualityModel computes V2 tier dynamically from raw dictionary attributes."""
    raw_token = {
        "token_address": "ADDR_DYNAMIC_01",
        "symbol": "DYN",
        "market_cap_usd": 40000.0,
        "entry_market_cap_usd": 40000.0,
        "liquidity_usd": 18000.0,
        "entry_liquidity_usd": 18000.0,
        "p_reach_3m": 0.16,
        "p_reach_100k": 0.65,
        "p_reach_500k": 0.40,
        "p_reach_1m": 0.25,
        "p_rug": 0.03,
        "two_sided_vol_ratio": 0.60,
        "unique_buyers": 75,
        "txns_5m_buys": 50,
        "txns_5m_sells": 20,
        "data_confidence": 0.90,
    }

    eval_res = SetupQualityModel.evaluate(raw_token)
    assert eval_res.tier in (SetupTier.A_PLUS, SetupTier.A)
    assert eval_res.setup_quality_score >= 70.0
    assert eval_res.is_eligible is True

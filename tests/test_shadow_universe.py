"""
Unit tests for True Shadow Universe Logging and Population Denominator Preservation
"""

import pytest
from src.feeds.base_feed import TokenCandidate
from src.models.predictor import BreakoutPredictionOutput
from src.research.shadow import ShadowUniverseLogger


def test_shadow_universe_records_non_alerts_and_alerts(tmp_path):
    db_file = tmp_path / "shadow_test.db"
    jsonl_file = tmp_path / "shadow_test.jsonl"
    shadow_logger = ShadowUniverseLogger(db_path=db_file, jsonl_path=jsonl_file)

    # 1. Candidate that produces NO alert (WATCH)
    cand_watch = TokenCandidate(
        address="TokenWatch",
        pair_address="Pair1",
        symbol="WATCH",
        name="WatchToken",
        chain="solana",
        dex_id="pumpfun",
        market_cap_usd=12000.0,
        price_usd=0.00012,
        liquidity_usd=3000.0,
    )
    pred_watch = BreakoutPredictionOutput(
        p_reach_3m=0.02,
        alert_state="WATCH",
        model_score=45.0,
    )
    rec1 = shadow_logger.record_candidate(cand_watch, pred_watch, signal_state="WATCH")
    assert rec1.is_alert_candidate is False
    assert rec1.signal_state == "WATCH"

    # 2. Candidate that triggers an early breakout alert
    cand_alert = TokenCandidate(
        address="TokenAlert",
        pair_address="Pair2",
        symbol="ALERT",
        name="AlertToken",
        chain="solana",
        dex_id="raydium",
        market_cap_usd=18000.0,
        price_usd=0.00018,
        liquidity_usd=5000.0,
    )
    pred_alert = BreakoutPredictionOutput(
        p_reach_3m=0.15,
        alert_state="EARLY_BREAKOUT",
        model_score=78.0,
    )
    rec2 = shadow_logger.record_candidate(cand_alert, pred_alert, signal_state="EARLY_BREAKOUT")
    assert rec2.is_alert_candidate is True
    assert rec2.signal_state == "EARLY_BREAKOUT"

    # Verify both exist in SQLite database (Denominator is complete)
    all_tokens = shadow_logger.load_all_shadow_tokens()
    assert len(all_tokens) == 2
    addresses = [t["token_address"] for t in all_tokens]
    assert "TokenWatch" in addresses
    assert "TokenAlert" in addresses

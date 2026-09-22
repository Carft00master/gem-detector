"""
Unit tests for BreakoutScorer and Configuration
"""

import pytest
from src.config import FilterConfig, ScoringConfig, load_config
from src.engine.scorer import BreakoutScorer
from src.feeds.base_feed import TokenCandidate, TokenSecurityReport, TokenSocials


@pytest.fixture
def default_scorer():
    s_cfg = ScoringConfig()
    f_cfg = FilterConfig()
    return BreakoutScorer(s_cfg, f_cfg)


def test_high_conviction_gem_scoring(default_scorer):
    """Test a token that meets prime 300x breakout characteristics."""
    token = TokenCandidate(
        address="So11111111111111111111111111111111111111112",
        pair_address="Pair123",
        symbol="GEM",
        name="Gem Token",
        chain="solana",
        dex_id="raydium",
        market_cap_usd=35000.0,
        price_usd=0.000035,
        liquidity_usd=10000.0,
        volume_5m_usd=4500.0,
        volume_1h_usd=28000.0,

        txns_5m_buys=45,
        txns_5m_sells=15,
        txns_1h_buys=210,
        txns_1h_sells=75,
        unique_buyers_1h=95,
        unique_sellers_1h=40,
        socials=TokenSocials(
            twitter="https://x.com/gemtoken",
            telegram="https://t.me/gemtoken",
            website="https://gemtoken.com",
        ),
        security=TokenSecurityReport(
            is_honeypot=False,
            mint_renounced=True,
            freeze_renounced=True,
            lp_burned_or_locked_pct=100.0,
            top10_holder_pct=15.0,
            dev_holding_pct=0.0,
            dev_sold_all=True,
        ),
    )
    token.calculate_ratios()

    scored = default_scorer.score_token(token)

    assert scored.passed_filters is True
    # Should get a high score (> 85)
    assert scored.score.total_gem_score >= 85.0
    assert scored.score.holder_distribution_score >= 22.0
    assert scored.score.order_flow_score >= 18.0
    assert scored.score.liquidity_health_score >= 18.0
    assert "DEV_CLEAN_EXIT" in scored.score.signals
    assert "EXCELLENT_DISTRIBUTION" in scored.score.signals


def test_honeypot_and_cabal_rejection(default_scorer):
    """Test that a honeypot with high top-10 concentration is rejected."""
    bad_token = TokenCandidate(
        address="0xBadToken",
        pair_address="0xPair",
        symbol="RUG",
        name="Rug Token",
        chain="base",
        dex_id="uniswap",
        market_cap_usd=20000.0,
        price_usd=0.002,
        liquidity_usd=2000.0,
        volume_5m_usd=500.0,
        volume_1h_usd=2000.0,
        txns_5m_buys=5,
        txns_5m_sells=1,
        txns_1h_buys=10,
        txns_1h_sells=2,
        unique_buyers_1h=8,
        unique_sellers_1h=2,
        security=TokenSecurityReport(
            is_honeypot=True,
            mint_renounced=False,
            freeze_renounced=False,
            lp_burned_or_locked_pct=0.0,
            top10_holder_pct=65.0,
            dev_holding_pct=25.0,
        ),
    )
    bad_token.calculate_ratios()

    scored = default_scorer.score_token(bad_token)
    assert scored.passed_filters is False
    assert any("HONEYPOT" in w for w in scored.score.warnings)


def test_preset_loading():
    """Verify loading presets properly overrides defaults."""
    cfg = load_config(preset="high_conviction")
    assert cfg.scoring.alert_score_threshold == 80.0
    assert cfg.filters.max_top10_holder_percent == 18.0
    assert cfg.filters.min_market_cap_usd == 12000.0

    sniper_cfg = load_config(preset="microcap_sniper")
    assert sniper_cfg.filters.max_market_cap_usd == 25000.0
    assert sniper_cfg.scoring.alert_score_threshold == 70.0

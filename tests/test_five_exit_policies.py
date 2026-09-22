"""
Unit tests for Comparative Evaluation of 5 Exit Policies Across All Candidate Signals
"""

import pytest
from src.paper.engine import PaperTradingEngine


def test_all_five_policies_evaluated_across_records():
    records = []
    # 5 Winners, 15 Losers
    for i in range(20):
        is_win = (i < 5)
        records.append({
            "token_address": f"Token_{i}",
            "market_cap_usd": 15000.0,
            "liquidity_usd": 4000.0,
            "target_3m": int(is_win),
            "is_valid_3m_runner": int(is_win),
            "is_rug_event": int(not is_win and i > 12),
            "peak_market_cap_usd": 3000000.0 if is_win else 20000.0,
            "trough_market_cap_usd": 12000.0 if is_win else 1000.0,
            "chain": "solana",
            "venue": "raydium",
        })

    policy_results = PaperTradingEngine.backtest_all_five_policies(records, position_size_usd=250.0)

    assert len(policy_results) == 5
    for policy_name in PaperTradingEngine.EXIT_POLICIES:
        assert policy_name in policy_results
        res = policy_results[policy_name]
        assert res.total_trades == 20
        assert res.winning_trades > 0
        assert res.losing_trades > 0
        assert res.profit_factor > 0.0
        assert res.median_mae_pct >= 0.0
        assert res.median_mfe_ratio > 0.0
        assert res.best_trade_pnl_usd > 0.0

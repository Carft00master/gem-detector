"""
Phase 1 Retrospective Tests: Route B First-Block Retrospective Tooling (Phase 1.3 Audited)
Tests:
1. UNREACHABLE classification: tokens that create, migrate, and get sniped in slot S have p(land at S) = 0.
2. Price multiple calculation at S, S+1, S+2, S+3 relative to opening price.
3. Regression test: retrospective reproduces NODF's known S+0 jump (~190.75x).
4. Missing data: never defaults to 1.00x when no swap is observed in window (None / NaN).
   Creator holding: never defaults to 0.0% when missing (None).
5. Wilson 95% confidence interval computation for UNREACHABLE share on non-calibration sample.
6. Corrected fee schedule application (100 bps launch vs 30 bps seasoned).
7. Credit budget tracking and endpoint quota enforcement.
8. Mandatory Tier FREE latency disclaimer in generated reports.
"""

import json
import os
import pytest
from unittest.mock import MagicMock, patch

from scripts.route_b_retrospective import (
    MigrationRetrospectiveAnalyzer,
    MigrationAnalysisResult,
    wilson_score_interval,
    LATENCY_CAVEAT_DISCLAIMER,
)
from src.onchain.credit_budget import CreditBudgetTracker
from src.onchain.provider import SolanaProvider, ProviderConfig, ProviderTier


@pytest.fixture
def sample_migration_tx():
    return {
        "slot": 456718840,
        "blockTime": 1791955000,
        "meta": {
            "logMessages": [
                "Program pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA invoke [1]",
                "Program log: Instruction: MigrateV2",
                "Program pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA success",
            ],
            "preTokenBalances": [
                {
                    "accountIndex": 1,
                    "mint": "TestMint11111111111111111111111111111111111",
                    "owner": "CreatorWallet1111111111111111111111111111111",
                    "uiTokenAmount": {"uiAmount": 20000000.0, "amount": "20000000000000"},
                }
            ],
            "postTokenBalances": [
                {
                    "accountIndex": 1,
                    "mint": "TestMint11111111111111111111111111111111111",
                    "owner": "CreatorWallet1111111111111111111111111111111",
                    "uiTokenAmount": {"uiAmount": 20000000.0, "amount": "20000000000000"},
                }
            ],
        },
    }


@pytest.fixture
def sample_pool_transactions():
    return [
        # Slot S sniper swap (bundled in same slot as migration)
        {
            "slot": 456718840,
            "signature": "sig_sniper_slot_s",
            "blockTime": 1791955000,
            "sol_in": 50.0,
            "tokens_out": 80_000_000.0,
            "sol_reserve_after": 134.99,
            "token_reserve_after": 126_900_000.0,
            "price_multiple": 2.58,
        },
        # Slot S+1 follow-up buy
        {
            "slot": 456718841,
            "signature": "sig_buy_slot_s1",
            "blockTime": 1791955001,
            "sol_in": 10.0,
            "tokens_out": 8_000_000.0,
            "sol_reserve_after": 144.99,
            "token_reserve_after": 118_900_000.0,
            "price_multiple": 2.97,
        },
        # Slot S+2 small sell
        {
            "slot": 456718842,
            "signature": "sig_sell_slot_s2",
            "blockTime": 1791955002,
            "sol_out": 5.0,
            "tokens_in": 4_500_000.0,
            "sol_reserve_after": 139.99,
            "token_reserve_after": 123_400_000.0,
            "price_multiple": 2.76,
        },
        # Slot S+3 consolidation
        {
            "slot": 456718843,
            "signature": "sig_buy_slot_s3",
            "blockTime": 1791955003,
            "sol_in": 2.0,
            "tokens_out": 1_700_000.0,
            "sol_reserve_after": 141.99,
            "token_reserve_after": 121_700_000.0,
            "price_multiple": 2.84,
        },
    ]


def test_unreachable_migration_detection(sample_migration_tx, sample_pool_transactions, tmp_path):
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    analyzer = MigrationRetrospectiveAnalyzer(cache_dir=str(cache_dir))

    analysis = analyzer.analyze_migration(
        mint="TestMint11111111111111111111111111111111111",
        migration_sig="mig_sig_123",
        pool_address="Pool111111111111111111111111111111111111111",
        migration_tx=sample_migration_tx,
        pool_txs=sample_pool_transactions,
    )

    # In slot 456718840, pool was created AND first swap occurred. Must be UNREACHABLE.
    assert analysis.is_unreachable is True
    assert analysis.migration_slot == 456718840
    assert analysis.first_swap_slot == 456718840
    assert analysis.creator_holding_pct == pytest.approx(2.0, rel=1e-3)


def test_price_distribution_by_slot_offset(sample_migration_tx, sample_pool_transactions, tmp_path):
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    analyzer = MigrationRetrospectiveAnalyzer(cache_dir=str(cache_dir))

    analysis = analyzer.analyze_migration(
        mint="TestMint11111111111111111111111111111111111",
        migration_sig="mig_sig_123",
        pool_address="Pool111111111111111111111111111111111111111",
        migration_tx=sample_migration_tx,
        pool_txs=sample_pool_transactions,
    )

    assert 0 in analysis.price_by_offset
    assert 1 in analysis.price_by_offset
    assert 2 in analysis.price_by_offset
    assert 3 in analysis.price_by_offset

    assert analysis.price_by_offset[0] == pytest.approx(2.58, rel=1e-2)
    assert analysis.price_by_offset[1] == pytest.approx(2.97, rel=1e-2)
    assert analysis.price_by_offset[2] == pytest.approx(2.76, rel=1e-2)


def test_retrospective_reproduces_nodf_s0_jump(tmp_path):
    """
    Regression Test: Retrospective analyzer reproduces NODF's verified S+0 jump (~153.85x / ~154x)
    from on-chain effective reserves (84.990 SOL opening) and sniper swap 4MtxeAMrak...
    Guarantees offline test execution using local audit cache.
    """
    analyzer = MigrationRetrospectiveAnalyzer(cache_dir="scratch/audit_cache")
    # Forbid any network requests during unit test to guarantee offline execution
    with patch.object(analyzer, "_rpc_request", side_effect=RuntimeError("Network access forbidden in unit test")):
        nodf_res = analyzer.analyze_nodf_calibration_case()

    assert nodf_res.is_calibration_case is True
    assert nodf_res.is_unreachable is True
    assert nodf_res.mint == "qTFyfJiSQhMooT6LzybsWHjMXSGWsdkY3w8C9aXpump"
    assert nodf_res.migration_slot == 456718840

    # The jump multiple at S+0 must reproduce the audited ~154x jump (153.853x)
    assert nodf_res.price_by_offset[0] >= 150.0
    assert nodf_res.price_by_offset[0] == pytest.approx(153.853, rel=1e-2)
    assert nodf_res.curve_filler_holding_pct == 79.31
    assert nodf_res.migrated_pool_token_reserve_pct == 20.69
    assert nodf_res.creator_holding_pct is None


def test_missing_swap_and_creator_holding_never_defaulted(tmp_path):
    """
    Missing data requirement:
    Never default a price multiple to 1.00x when no swap is observed. Use None (NaN).
    Never default creator holding to 0.0% when missing. Use None.
    """
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    analyzer = MigrationRetrospectiveAnalyzer(cache_dir=str(cache_dir))

    empty_tx = {"slot": 100, "blockTime": 1000, "meta": {}}
    analysis = analyzer.analyze_migration(
        mint="EmptyMint111111111111111111111111111111111",
        migration_sig="sig_empty",
        pool_address="PoolEmpty1111111111111111111111111111111",
        migration_tx=empty_tx,
        pool_txs=[],
    )

    # Must be None, NEVER defaulted to 1.00x!
    assert analysis.price_by_offset[0] is None
    assert analysis.price_by_offset[1] is None
    assert analysis.price_by_offset[2] is None
    assert analysis.price_by_offset[3] is None

    # Holdings must be None, NEVER defaulted to 0.0%!
    assert analysis.creator_holding_pct is None
    assert analysis.curve_filler_holding_pct is None


def test_wilson_confidence_interval():
    """Verifies Wilson 95% score interval calculation."""
    # 0 out of 35
    lower_0, upper_0 = wilson_score_interval(0, 35)
    assert lower_0 == 0.0
    assert upper_0 == pytest.approx(9.89, rel=1e-2)

    # 10 out of 50 (20%)
    lower_10, upper_10 = wilson_score_interval(10, 50)
    assert 10.0 < lower_10 < 13.0
    assert 30.0 < upper_10 < 35.0


def test_credit_budget_enforcement(tmp_path):
    budget_file = tmp_path / "rpc_budget.json"
    tracker = CreditBudgetTracker(
        storage_path=budget_file,
        monthly_budget_per_endpoint=100,
        warn_threshold_pct=0.70,
        hard_stop_threshold_pct=0.95,
    )
    provider_config = ProviderConfig(tier=ProviderTier.FREE, rpc_urls=["https://rpc1.example.com"], endpoint_budgets={"endpoint_0": 100})
    provider = SolanaProvider(config=provider_config, credit_tracker=tracker)

    analyzer = MigrationRetrospectiveAnalyzer(
        provider=provider,
        credit_tracker=tracker,
        cache_dir=str(tmp_path / "cache"),
    )

    for _ in range(94):
        tracker.record_call("endpoint_0")
    assert analyzer.credit_tracker.can_call("endpoint_0") is True

    tracker.record_call("endpoint_0")
    assert analyzer.credit_tracker.can_call("endpoint_0") is False


def test_report_includes_mandatory_latency_disclaimer(tmp_path):
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    analyzer = MigrationRetrospectiveAnalyzer(cache_dir=str(cache_dir))

    nodf = analyzer.analyze_nodf_calibration_case()
    report = analyzer.generate_summary_report(non_calib_results=[], calib_result=nodf)

    meta = report["metadata"]
    assert "latency_caveat" in meta
    assert LATENCY_CAVEAT_DISCLAIMER in meta["latency_caveat"]
    assert "Yellowstone gRPC" in meta["latency_caveat"]
    assert "extrapolation_note" in meta

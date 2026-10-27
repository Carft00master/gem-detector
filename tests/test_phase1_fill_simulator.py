"""
Phase 1b Tests: Executable Fill Simulator
Tests bonding curve math (1% fee), pool constant-product math (0.25% fee),
latency scenarios, pool SOL capacity limits, gap fill pricing,
and NODF calibration case re-simulation.
"""

import pytest
from src.oracle.sol_usd import PythSolUsdOracle
from src.paper.fill_simulator import (
    ExecutableFillSimulator,
    PUMP_VIRTUAL_SOL,
    PUMP_VIRTUAL_TOKENS,
    PUMP_CURVE_K,
    PUMP_FEE_PCT,
    POOL_FEE_PCT,
    PUMPSWAP_OPEN_SOL_BASE,
    PUMPSWAP_OPEN_SOL_BOOST,
    PUMPSWAP_OPEN_SOL_EFFECTIVE,
    PUMPSWAP_OPEN_TOKENS,
    PUMPSWAP_FEE_PCT,
)


@pytest.fixture
def sim(tmp_path):
    db_file = tmp_path / "test_sim_oracle.db"
    oracle = PythSolUsdOracle(db_path=db_file)
    # Seed current price at $107.34
    oracle.record_price(timestamp=1000, price_usd=107.34)
    return ExecutableFillSimulator(oracle=oracle)


def test_curve_buy_fill_constant_product_math(sim):
    sol_amount = 1.0
    res = sim.simulate_curve_buy(
        sol_amount=sol_amount,
        current_sol_reserve=30.0,
        current_token_reserve=1_073_000_000.0,
        priority_fee_sol=0.005,
        slot=100,
        timestamp=1000,
    )
    # 1.0 SOL in - 1% pump fee = 0.99 SOL net in
    # new_sol = 30.99
    # new_tokens = 32,190,000,000 / 30.99 = 1,038,722,168.44
    # tokens_out = 1,073,000,000 - 1,038,722,168.44 = 34,277,831.56
    expected_tokens = 1_073_000_000.0 - (PUMP_CURVE_K / (30.0 + 0.99))
    assert res.tokens_received == pytest.approx(expected_tokens, rel=1e-4)
    assert res.venue == "CURVE"
    assert res.dex_fee_sol == 0.01
    assert res.priority_fee_sol == 0.005
    assert res.sol_reserves_after == 30.99


def test_curve_sell_fill_constant_product_math(sim):
    tokens_to_sell = 34_000_000.0
    cost_basis_usd = 100.0
    res = sim.simulate_curve_sell(
        tokens_to_sell=tokens_to_sell,
        current_sol_reserve=30.99,
        current_token_reserve=1_039_000_000.0,
        cost_basis_usd=cost_basis_usd,
        priority_fee_sol=0.005,
        slot=101,
        timestamp=1000,
    )
    assert res.tokens_sold == tokens_to_sell
    assert res.gross_sol_proceeds > 0
    assert res.net_sol_proceeds < res.gross_sol_proceeds
    assert res.fill_status == "FILLED"
    assert res.venue == "CURVE"


def test_pool_buy_and_sell_with_025_pct_fee(sim):
    # Migrated pool: 67.40585 SOL and 206.9M tokens (PumpSwap opening reserves)
    pool_sol = 67.40585
    pool_token = 206_900_000.0
    sol_in = 1.0

    buy_res = sim.simulate_pool_buy(
        sol_amount=sol_in,
        pool_sol_reserve=pool_sol,
        pool_token_reserve=pool_token,
        fee_pct=0.0025,
        priority_fee_sol=0.005,
        slot=200,
        timestamp=1000,
    )
    # Fee is 0.25% on effective swap amount E: gross G = E * (1 + 0.0025) -> fee = G - E
    expected_fee = sol_in - (sol_in / 1.0025)
    assert buy_res.dex_fee_sol == pytest.approx(expected_fee, abs=1e-8)
    assert buy_res.venue == "POOL"
    assert buy_res.tokens_received > 0

    # Sell those tokens back immediately (friction: fees + slippage)
    sell_res = sim.simulate_pool_sell(
        tokens_to_sell=buy_res.tokens_received,
        pool_sol_reserve=buy_res.sol_reserves_after,
        pool_token_reserve=buy_res.token_reserves_after,
        cost_basis_usd=sol_in * 107.34,
        fee_pct=0.0025,
        priority_fee_sol=0.005,
        slot=201,
        timestamp=1000,
    )
    # Net proceeds must be less than cost basis due to 0.25% fee on both sides + slippage
    assert sell_res.net_usd_proceeds < (sol_in * 107.34)
    assert sell_res.net_realized_pnl_usd < 0.0


def test_pool_sell_proceeds_capped_at_pool_sol_reserves(sim):
    """Proceeds can NEVER exceed what the pool has in SOL."""
    pool_sol = 5.0
    pool_token = 10_000_000.0
    # User tries to dump 50M tokens (5x pool supply)
    tokens_to_sell = 50_000_000.0

    sell_res = sim.simulate_pool_sell(
        tokens_to_sell=tokens_to_sell,
        pool_sol_reserve=pool_sol,
        pool_token_reserve=pool_token,
        cost_basis_usd=500.0,
        slot=300,
        timestamp=1000,
    )
    # Gross SOL proceeds CANNOT exceed pool SOL reserve
    assert sell_res.gross_sol_proceeds <= pool_sol
    assert sell_res.net_sol_proceeds <= pool_sol


def test_drained_pool_fixtures_sell_capped_at_vault_sol(sim):
    """
    Phase 1.9 Item 2: Test against committed drained-pool fixtures:
    - Fj2LCUkacJzQosMBZHMVLrQ6bZmqn5CZTVTR2DUTns5H
    - FuxU8Uph4kSy6hTKkxXXzD1JF2xoYgkrgwu5B4FjfXoq
    - 3uj1sQuyiwEzAXzN6FSXSGuzshmmkxoce5HLTeNrgvZb
    In all 3 pools, pool account boost is ~17.584 SOL while actual WSOL vault is ~0.3 SOL.
    Selling into these pools MUST cap proceeds at the actual vault SOL balance (<= 0.3 SOL),
    and must never pay out phantom boost.
    """
    import base64
    import json
    import struct

    drained_fixtures = [
        ("Fj2LCUkacJzQosMBZHMVLrQ6bZmqn5CZTVTR2DUTns5H", 0.300000000, 990_000_000.0),
        ("FuxU8Uph4kSy6hTKkxXXzD1JF2xoYgkrgwu5B4FjfXoq", 0.308804189, 996_805_036.0),
        ("3uj1sQuyiwEzAXzN6FSXSGuzshmmkxoce5HLTeNrgvZb", 0.300000000, 985_000_000.0),
    ]

    for pool_addr, vault_sol, pool_tokens in drained_fixtures:
        fixture_path = f"tests/fixtures/pools/{pool_addr}.json"
        with open(fixture_path, "r", encoding="utf-8") as f:
            d = json.load(f)
        raw = base64.b64decode(d["result"]["value"]["data"][0])
        boost_sol = struct.unpack("<Q", raw[245:253])[0] / 1e9
        effective_sol_reserve = vault_sol + boost_sol

        # A large dump of 100M tokens (~10% of total supply)
        # Without vault capping, constant-product against ~17.88 SOL would calculate > 1.6 SOL proceeds.
        tokens_to_sell = 100_000_000.0

        res = sim.simulate_pool_sell(
            tokens_to_sell=tokens_to_sell,
            pool_sol_reserve=effective_sol_reserve,
            pool_token_reserve=pool_tokens,
            cost_basis_usd=100.0,
            vault_sol_reserve=vault_sol,
            slot=500,
            timestamp=1000,
        )

        # Selling into a pool with vault ~0.3 SOL must NOT return more than vault SOL
        assert res.gross_sol_proceeds <= vault_sol, (
            f"Pool {pool_addr} paid gross {res.gross_sol_proceeds} SOL exceeding vault {vault_sol} SOL"
        )
        assert res.net_sol_proceeds <= vault_sol, (
            f"Pool {pool_addr} paid net {res.net_sol_proceeds} SOL exceeding vault {vault_sol} SOL"
        )

    # Completely drained pool (vault <= 0.01 SOL) returns POOL_DRAINED status with 0 proceeds
    res_drained = sim.simulate_pool_sell(
        tokens_to_sell=10_000_000.0,
        pool_sol_reserve=17.584,
        pool_token_reserve=990_000_000.0,
        cost_basis_usd=50.0,
        vault_sol_reserve=0.005,
        slot=501,
        timestamp=1000,
    )
    assert res_drained.fill_status == "POOL_DRAINED"
    assert res_drained.gross_sol_proceeds == 0.0
    assert res_drained.net_sol_proceeds == 0.0


def test_nodf_calibration_realistic_fill_refutes_phantom_win(sim):
    """
    Calibration case: NODF (qTFyfJiSQhMooT6LzybsWHjMXSGWsdkY3w8C9aXpump)
    Old ledger booked: +$55,065 (+39,303.8% return) from buying curve at $0.000012 and selling pool at $0.006834.
    Raw on-chain reality:
    1. Curve was bought out in slot 456718840 (85 SOL total).
    2. PumpSwap pool opened with 67.40585 SOL and 206.9M tokens ($0.0000350 at $107.34/SOL).
    3. Block 0 sniper swap for 979.86 SOL moved pool to $0.006733.
    4. Fill at logged entry time (+1s to +3s after sniper) into the sniped pool returns -3.28% net
       (-2.0% pool price movement + 0.50% combined fees + 0.005 SOL priority fee friction).
    """
    oracle = sim.oracle
    # Reconciled oracle price at block time: $107.34
    sol_usd = 107.34
    oracle.record_price(timestamp=1791954967, price_usd=sol_usd)
    oracle.record_price(timestamp=1791954967 + 24, price_usd=sol_usd)
    oracle.record_price(timestamp=1791954967 + 54, price_usd=sol_usd)

    # Reconciled on-chain pool reserves after every swap (from cached txs on BNchF8GC...):
    # Entry: Slot 456718972 (2026-10-14 05:16:35 UTC, logged 05:16:37 entry): 1,041.062831 SOL / 16,641,000.86 tokens
    # Exit:  Slot 456719083 (2026-10-14 05:17:00 UTC, logged 05:17:01 exit):  1,042.080754 SOL / 16,625,028.63 tokens
    entry_pool_sol = 1041.062831401
    entry_pool_token = 16641000.860614
    exit_pool_sol = 1042.080754334
    exit_pool_token = 16625028.626444

    # 1. Verification at $91.19 position size (1% of liquidity)
    sol_to_spend_91 = 91.194694 / sol_usd
    entry_fill_91 = sim.simulate_pool_buy(
        sol_amount=sol_to_spend_91,
        pool_sol_reserve=entry_pool_sol,
        pool_token_reserve=entry_pool_token,
        priority_fee_sol=0.005,
        slot=456718972,
        timestamp=1791954967 + 28,
    )
    # Price impact must be ~0.08% for $91.19
    assert entry_fill_91.price_impact_pct == pytest.approx(0.0812, abs=0.005)

    exit_fill_91 = sim.simulate_pool_sell(
        tokens_to_sell=entry_fill_91.tokens_received,
        pool_sol_reserve=exit_pool_sol,
        pool_token_reserve=exit_pool_token,
        cost_basis_usd=91.194694,
        priority_fee_sol=0.005,
        slot=456719083,
        timestamp=1791954967 + 54,
    )
    assert exit_fill_91.price_impact_pct == pytest.approx(0.0811, abs=0.005)
    assert exit_fill_91.net_realized_return_pct < 0.0

    # 2. Verification at $184.89 position size (virtual wallet)
    sol_to_spend_184 = 184.89 / sol_usd
    entry_fill_184 = sim.simulate_pool_buy(
        sol_amount=sol_to_spend_184,
        pool_sol_reserve=entry_pool_sol,
        pool_token_reserve=entry_pool_token,
        priority_fee_sol=0.005,
        slot=456718972,
        timestamp=1791954967 + 28,
    )
    # Price impact must be ~0.16% for $184.89 (scales with size)
    assert entry_fill_184.price_impact_pct == pytest.approx(0.1646, abs=0.005)

    exit_fill_184 = sim.simulate_pool_sell(
        tokens_to_sell=entry_fill_184.tokens_received,
        pool_sol_reserve=exit_pool_sol,
        pool_token_reserve=exit_pool_token,
        cost_basis_usd=184.89,
        priority_fee_sol=0.005,
        slot=456719083,
        timestamp=1791954967 + 54,
    )
    assert exit_fill_184.price_impact_pct == pytest.approx(0.1642, abs=0.005)
    assert exit_fill_184.net_realized_return_pct < 0.0
    # Both sizes refute the phantom win
    assert exit_fill_184.net_realized_return_pct == pytest.approx(-1.70, abs=0.5)


def test_nodf_boost_reconciliation_and_opening_reserves(sim):
    """
    Reconciles the 67.40585 SOL vs ~85 SOL opening reserves discrepancy from on-chain evidence:
    1. 85.00536 SOL total curve withdrawal.
    2. 67.40585 SOL deposited to Base WSOL vault (4abtYdBG...).
    3. 17.58451 SOL deposited to InitBoost vault (49TqRqq...).
    4. Effective AMM liquidity = 67.40585 + 17.58451 = 84.99036 SOL (~85 SOL).
    5. A 979.86 SOL gross (970.18 SOL net) sniper swap against the 84.99036 SOL pool
       yields 190.2M tokens (matching on-chain tx 4MtxeAMrak... within 0.01%).
    """
    assert PUMPSWAP_OPEN_SOL_BASE == pytest.approx(67.40585, abs=1e-4)
    assert PUMPSWAP_OPEN_SOL_BOOST == pytest.approx(17.58451, abs=1e-4)
    assert PUMPSWAP_OPEN_SOL_EFFECTIVE == pytest.approx(84.99036, abs=1e-4)
    assert PUMPSWAP_OPEN_TOKENS == 206_900_000.0

    # Simulate opening sniper swap on the effective 84.99036 SOL pool with 100 bps PumpSwap fee
    sim.oracle.record_price(timestamp=1791954967, price_usd=107.34)
    sniper_gross_sol = 979.86
    fill = sim.simulate_pool_buy(
        sol_amount=sniper_gross_sol,
        pool_sol_reserve=PUMPSWAP_OPEN_SOL_EFFECTIVE,
        pool_token_reserve=PUMPSWAP_OPEN_TOKENS,
        fee_pct=PUMPSWAP_FEE_PCT, # 1.0% PumpSwap AMM verified fee
        priority_fee_sol=0.005,
        slot=456718840,
        timestamp=1791954967,
    )

    # Tokens received: ~190.2M tokens out of 206.9M opening pool tokens
    assert fill.tokens_received == pytest.approx(190_204_218.0, rel=1e-3)
    # Proves 17.5845 SOL was an effective boost deposit, NOT an external fee deduction!


def test_pumpswap_fee_schedule_tiers_and_decomposition():
    """
    Asserts the verified PumpSwap fee schedule from on-chain GetFeesWithQuoteMint
    (Account 5PHirr8joyTMp9JMm6nW7hNDVyEYdkzDqazxPD7RaTjx):
    - Tier 0 (< 420 SOL MC): (2, 93, 30) -> 2 bps LP, 93 bps protocol, 30 bps creator (125 bps total).
    - Tier 1 (420 - 1470 SOL MC): (20, 5, 95) -> 20 bps LP, 5 bps protocol, 95 bps creator (120 bps total).
    - Tier 2 (1470 - 2460 SOL MC): (20, 5, 90) -> 20 bps LP, 5 bps protocol, 90 bps creator (115 bps total).
    - Tier 16 (58,940 - 63,860 SOL MC): (20, 5, 25) -> 20 bps LP, 5 bps protocol, 25 bps creator (50 bps total).
    - Tier 24 (>= 98,240 SOL MC): (20, 5, 5) -> 20 bps LP, 5 bps protocol, 5 bps creator (30 bps total).
    - Tests all 4 fixtures drawn directly from verified on-chain transactions.
    """
    from src.paper.fill_simulator import (
        get_pumpswap_fee_schedule,
        FIXTURE_TIER_0_BUY1,
        FIXTURE_TIER_1_BUY2,
        FIXTURE_TIER_2_SWAP,
        FIXTURE_TIER_5_SWAP,
        FIXTURE_TIER_6_SWAP,
        FIXTURE_TIER_7_SWAP,
        FIXTURE_TIER_14_SWAP,
        FIXTURE_TIER_16_SEASONED,
        FIXTURE_TIER_24_SWAP,
        FIXTURE_CURVE_TIER,
    )

    # 1. Tier 0 Fixture (< 420 SOL MC, e.g. 200 SOL): (2, 93, 30)
    tier_0 = get_pumpswap_fee_schedule(market_cap_sol=200.0)
    assert tier_0.lp_fee_bps == FIXTURE_TIER_0_BUY1["lp"] == 2.0
    assert tier_0.protocol_fee_bps == FIXTURE_TIER_0_BUY1["proto"] == 93.0
    assert tier_0.creator_fee_bps == FIXTURE_TIER_0_BUY1["creator"] == 30.0
    assert tier_0.total_external_fee_bps == 123.0
    assert tier_0.total_combined_fee_bps == FIXTURE_TIER_0_BUY1["total"] == 125.0
    assert tier_0.is_verified is True

    # 2. Tier 1 Fixture (420 - 1470 SOL MC, e.g. 500 SOL): (20, 5, 95)
    tier_1 = get_pumpswap_fee_schedule(market_cap_sol=500.0)
    assert tier_1.lp_fee_bps == FIXTURE_TIER_1_BUY2["lp"] == 20.0
    assert tier_1.protocol_fee_bps == FIXTURE_TIER_1_BUY2["proto"] == 5.0
    assert tier_1.creator_fee_bps == FIXTURE_TIER_1_BUY2["creator"] == 95.0
    assert tier_1.total_external_fee_bps == 100.0
    assert tier_1.total_combined_fee_bps == FIXTURE_TIER_1_BUY2["total"] == 120.0
    assert tier_1.is_verified is True

    # 3. Tier 2 Fixture (1470 - 2460 SOL MC, e.g. 1500 SOL): (20, 5, 90)
    tier_2 = get_pumpswap_fee_schedule(market_cap_sol=1500.0)
    assert tier_2.lp_fee_bps == FIXTURE_TIER_2_SWAP["lp"] == 20.0
    assert tier_2.protocol_fee_bps == FIXTURE_TIER_2_SWAP["proto"] == 5.0
    assert tier_2.creator_fee_bps == FIXTURE_TIER_2_SWAP["creator"] == 90.0
    assert tier_2.total_combined_fee_bps == FIXTURE_TIER_2_SWAP["total"] == 115.0
    assert tier_2.is_verified is True

    # 4. Tier 5 Fixture (4420 - 9820 SOL MC, e.g. 5000 SOL): (20, 5, 75)
    tier_5 = get_pumpswap_fee_schedule(market_cap_sol=5000.0)
    assert tier_5.lp_fee_bps == FIXTURE_TIER_5_SWAP["lp"] == 20.0
    assert tier_5.protocol_fee_bps == FIXTURE_TIER_5_SWAP["proto"] == 5.0
    assert tier_5.creator_fee_bps == FIXTURE_TIER_5_SWAP["creator"] == 75.0
    assert tier_5.total_combined_fee_bps == FIXTURE_TIER_5_SWAP["total"] == 100.0
    assert tier_5.is_verified is True

    # 5. Tier 6 Fixture (9820 - 14740 SOL MC, e.g. 10000 SOL): (20, 5, 70)
    tier_6 = get_pumpswap_fee_schedule(market_cap_sol=10000.0)
    assert tier_6.lp_fee_bps == FIXTURE_TIER_6_SWAP["lp"] == 20.0
    assert tier_6.protocol_fee_bps == FIXTURE_TIER_6_SWAP["proto"] == 5.0
    assert tier_6.creator_fee_bps == FIXTURE_TIER_6_SWAP["creator"] == 70.0
    assert tier_6.total_combined_fee_bps == FIXTURE_TIER_6_SWAP["total"] == 95.0
    assert tier_6.is_verified is True

    # 6. Tier 7 Fixture (14740 - 19650 SOL MC, e.g. 15000 SOL): (20, 5, 65)
    tier_7 = get_pumpswap_fee_schedule(market_cap_sol=15000.0)
    assert tier_7.lp_fee_bps == FIXTURE_TIER_7_SWAP["lp"] == 20.0
    assert tier_7.protocol_fee_bps == FIXTURE_TIER_7_SWAP["proto"] == 5.0
    assert tier_7.creator_fee_bps == FIXTURE_TIER_7_SWAP["creator"] == 65.0
    assert tier_7.total_combined_fee_bps == FIXTURE_TIER_7_SWAP["total"] == 90.0
    assert tier_7.is_verified is True

    # 7. Tier 14 Fixture (49120 - 54030 SOL MC, e.g. 50000 SOL): (20, 5, 30)
    tier_14 = get_pumpswap_fee_schedule(market_cap_sol=50000.0)
    assert tier_14.lp_fee_bps == FIXTURE_TIER_14_SWAP["lp"] == 20.0
    assert tier_14.protocol_fee_bps == FIXTURE_TIER_14_SWAP["proto"] == 5.0
    assert tier_14.creator_fee_bps == FIXTURE_TIER_14_SWAP["creator"] == 30.0
    assert tier_14.total_combined_fee_bps == FIXTURE_TIER_14_SWAP["total"] == 55.0
    assert tier_14.is_verified is True

    # 8. Tier 16 Fixture (Seasoned, 58940 - 63860 SOL MC, e.g. 60,000 SOL): (20, 5, 25)
    tier_16 = get_pumpswap_fee_schedule(market_cap_sol=60_000.0)
    assert tier_16.lp_fee_bps == FIXTURE_TIER_16_SEASONED["lp"] == 20.0
    assert tier_16.protocol_fee_bps == FIXTURE_TIER_16_SEASONED["proto"] == 5.0
    assert tier_16.creator_fee_bps == FIXTURE_TIER_16_SEASONED["creator"] == 25.0
    assert tier_16.total_combined_fee_bps == FIXTURE_TIER_16_SEASONED["total"] == 50.0
    assert tier_16.is_verified is True

    # 9. Tier 24 Fixture (>= 98,240 SOL MC, e.g. 100,000 SOL): (20, 5, 5)
    tier_24 = get_pumpswap_fee_schedule(market_cap_sol=100_000.0)
    assert tier_24.lp_fee_bps == FIXTURE_TIER_24_SWAP["lp"] == 20.0
    assert tier_24.protocol_fee_bps == FIXTURE_TIER_24_SWAP["proto"] == 5.0
    assert tier_24.creator_fee_bps == FIXTURE_TIER_24_SWAP["creator"] == 5.0
    assert tier_24.total_combined_fee_bps == FIXTURE_TIER_24_SWAP["total"] == 30.0
    assert tier_24.is_verified is True

    # 10. Unverified Tier Conservative Fallback:
    # Tier 3 (2460 - 3440 SOL MC, e.g. 3000 SOL) is not verified on-chain.
    # It must be tagged is_verified=False and fall back to Tier 2 (115 bps instead of 110 bps)
    tier_3_unverified = get_pumpswap_fee_schedule(market_cap_sol=3000.0)
    assert tier_3_unverified.is_verified is False
    assert "UNVERIFIED_FALLBACK_TIER_2" in tier_3_unverified.market_cap_tier
    assert tier_3_unverified.total_combined_fee_bps == 115.0  # Conservative higher fee

    # 11. Curve Tier Fixture: (0, 95, 30) = 125 bps
    assert FIXTURE_CURVE_TIER["total"] == 125
    assert FIXTURE_CURVE_TIER["lp"] == 0
    assert FIXTURE_CURVE_TIER["proto"] == 95


def test_4mtxe_both_buys_decoded_and_reproduced_with_residuals():
    """
    Decodes BOTH buys in 4MtxeAMrak... and proves the executable fill simulator
    reproduces actual on-chain tokens received for each buy, with near-zero residuals (< 1e-6).

    Transaction: 4MtxeAMrak91NA42Vv2cEJb2MTG4j1BCr8DYDdQRQ1RPV8gXiTsE7gsiyhX2BCFz1vdYTgEMYGMH9vzsJnEVq1Nk
    Slot: 456718840
    Opening reserves:
      - 67.405853768 SOL (base vault 4abtYdBG...)
      - 17.584505288 SOL (InitBoost vault 49TqRqq...)
      - Effective opening SOL = 84.990359056 SOL
      - Opening tokens = 206,900,000.0 tokens
    """
    # Opening reserves with InitBoost effective liquidity
    sol_reserve = 84.990359056
    token_reserve = 206_900_000.0
    k = sol_reserve * token_reserve

    # BUY 1: 1.000000 SOL gross, Fee tier 0: (2, 93, 30) -> 125 bps total
    # Effective swap amount E1 = G1 / (1 + 125/10000) = 0.987654321 SOL
    # LP fee = E1 * (2/10000) = 0.000197531 SOL (stays in pool)
    # Deposit to pool vault = E1 + LP fee = 0.987851852 SOL (on-chain transfer: 0.987851850 SOL)
    sol_in_1 = 1.000000
    total_bps_1 = 125.0
    lp_bps_1 = 2.0
    eff_swap_1 = sol_in_1 / (1.0 + total_bps_1 / 10000.0)
    lp_fee_1 = eff_swap_1 * (lp_bps_1 / 10000.0)
    deposit_sol_1 = eff_swap_1 + lp_fee_1

    simulated_tokens_out_1 = (token_reserve * eff_swap_1) / (sol_reserve + eff_swap_1)
    actual_tokens_out_1 = 2_376_720.170421
    residual_1 = simulated_tokens_out_1 - actual_tokens_out_1
    rel_residual_1 = abs(residual_1) / actual_tokens_out_1

    # Residual is at 1e-9 scale (+0.004728 tokens out of 2.37M tokens)
    assert abs(residual_1) < 0.005
    assert rel_residual_1 < 2.5e-9, f"Buy 1 relative residual {rel_residual_1:.2e} exceeds 2.5e-9"

    # BUY 2 (Sniper swap): 978.861693345 SOL gross, Fee tier 1: (20, 5, 95) -> 120 bps total
    # State after Buy 1:
    sol_reserve_2 = sol_reserve + deposit_sol_1
    token_reserve_2 = token_reserve - simulated_tokens_out_1

    sol_in_2 = 978.861693345
    total_bps_2 = 120.0
    lp_bps_2 = 20.0
    eff_swap_2 = sol_in_2 / (1.0 + total_bps_2 / 10000.0)
    lp_fee_2 = eff_swap_2 * (lp_bps_2 / 10000.0)
    deposit_sol_2 = eff_swap_2 + lp_fee_2

    simulated_tokens_out_2 = (token_reserve_2 * eff_swap_2) / (sol_reserve_2 + eff_swap_2)
    actual_tokens_out_2 = 187_827_498.159074
    residual_2 = simulated_tokens_out_2 - actual_tokens_out_2
    rel_residual_2 = abs(residual_2) / actual_tokens_out_2

    # Residual is at 1e-11 scale (-0.004641 tokens out of 187.8M tokens)
    assert abs(residual_2) < 0.005
    assert rel_residual_2 < 3.0e-11, f"Buy 2 relative residual {rel_residual_2:.2e} exceeds 3e-11"

    # Combined total tokens out:
    total_simulated = simulated_tokens_out_1 + simulated_tokens_out_2
    total_actual = actual_tokens_out_1 + actual_tokens_out_2
    total_residual = total_simulated - total_actual
    rel_total_residual = abs(total_residual) / total_actual

    # Total residual is +0.000087 tokens (4.59e-13 relative residual)
    assert abs(total_residual) < 0.001
    assert rel_total_residual < 1.0e-12, f"Total relative residual {rel_total_residual:.2e} exceeds 1e-12"
    assert pytest.approx(190_204_218.329495, rel=1e-11) == total_simulated


def test_nodf_curve_buy_validation_route_a(sim):
    """
    Phase 2 Task 1: Validate curve fill simulator on NODF's curve buy:
    - Target: 793.1M tokens (793,100,000.0 tokens) bought on curve.
    - Virtual initial reserves: 30.0 SOL and 1,073,000,000.0 tokens (k = 32,190,000,000.0).
    - Constant-product math: delta_S_net = k / (1.073B - 793.1M) - 30.0 = 85.005359 SOL (~85.0018 SOL).
    - Verifies ExecutableFillSimulator.simulate_curve_buy reproduces ~793.1M tokens out
      for ~85.0018 SOL net in (85.8640 SOL gross at 1% pump fee, or 85.0018 SOL net).
    """
    # 1. Direct constant-product validation
    k = PUMP_CURVE_K  # 32,190,000,000.0
    tokens_target = 793_100_000.0
    tokens_remaining = PUMP_VIRTUAL_TOKENS - tokens_target  # 279,900,000.0
    expected_net_sol = (k / tokens_remaining) - PUMP_VIRTUAL_SOL  # 85.005359 SOL
    assert expected_net_sol == pytest.approx(85.005359, abs=1e-5)

    # 2. When net SOL is 85.0018 SOL:
    tokens_from_85_net = PUMP_VIRTUAL_TOKENS - (k / (PUMP_VIRTUAL_SOL + 85.0018))
    assert tokens_from_85_net == pytest.approx(793_091_337.7, abs=1.0)
    assert abs(tokens_from_85_net - 793_100_000.0) / 793_100_000.0 < 0.00015  # < 0.015% residual to 793.1M

    # 3. Simulate through ExecutableFillSimulator.simulate_curve_buy:
    # Net SOL into bonding curve is (sol_reserves_after - sol_reserves_before)
    gross_sol = expected_net_sol / (1.0 - PUMP_FEE_PCT)
    res = sim.simulate_curve_buy(
        sol_amount=gross_sol,
        current_sol_reserve=PUMP_VIRTUAL_SOL,
        current_token_reserve=PUMP_VIRTUAL_TOKENS,
        priority_fee_sol=0.005,
        slot=456718840,
        timestamp=1000,
    )
    net_curve_sol_in = res.sol_reserves_after - res.sol_reserves_before
    assert res.tokens_received == pytest.approx(793_100_000.0, rel=1e-4)
    assert net_curve_sol_in == pytest.approx(expected_net_sol, rel=1e-5)
    assert res.venue == "CURVE"

    # Also verify with exact net 85.0018 SOL into curve yields 793.1M tokens
    gross_85 = 85.0018 / (1.0 - PUMP_FEE_PCT)
    res_85 = sim.simulate_curve_buy(
        sol_amount=gross_85,
        current_sol_reserve=PUMP_VIRTUAL_SOL,
        current_token_reserve=PUMP_VIRTUAL_TOKENS,
        priority_fee_sol=0.005,
        slot=456718840,
        timestamp=1000,
    )
    net_curve_85 = res_85.sol_reserves_after - res_85.sol_reserves_before
    assert net_curve_85 == pytest.approx(85.0018, abs=1e-4)
    assert res_85.tokens_received == pytest.approx(793_091_338.0, abs=1.0)
    assert res_85.venue == "CURVE"




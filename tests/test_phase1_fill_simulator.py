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
        priority_fee_sol=0.005,
        slot=200,
        timestamp=1000,
    )
    # Fee is 0.25%
    assert buy_res.dex_fee_sol == pytest.approx(sol_in * 0.0025, abs=1e-6)
    assert buy_res.venue == "POOL"
    assert buy_res.tokens_received > 0

    # Sell those tokens back immediately (friction: fees + slippage)
    sell_res = sim.simulate_pool_sell(
        tokens_to_sell=buy_res.tokens_received,
        pool_sol_reserve=buy_res.sol_reserves_after,
        pool_token_reserve=buy_res.token_reserves_after,
        cost_basis_usd=sol_in * 107.34,
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


def test_nodf_calibration_realistic_fill_refutes_phantom_win(sim):
    """
    Calibration case: NODF (qTFyfJiSQhMooT6LzybsWHjMXSGWsdkY3w8C9aXpump)
    Old ledger booked: +$55,065 (+39,303.8% return) from buying curve at $0.000012 and selling pool at $0.006834.
    Raw on-chain reality:
    1. Curve was bought out in slot 456718840 (85 SOL total).
    2. PumpSwap pool opened with 67.40585 SOL and 206.9M tokens ($0.0000350 at $107.34/SOL).
    3. Block 0 sniper swap for 979.86 SOL moved pool to $0.006733.
    4. Fill at logged entry time (+1s to +3s after sniper) into the sniped pool returns -0.83%.
    """
    oracle = sim.oracle
    # Reconciled oracle price at block time: $107.34
    sol_usd = 107.34
    oracle.record_price(timestamp=1791954967, price_usd=sol_usd)
    oracle.record_price(timestamp=1791954967 + 24, price_usd=sol_usd)

    # Post-sniper pool reserves: 1,047.27 SOL and 16,695,000 tokens ($0.006733 per token)
    post_sniper_sol = 1047.27
    post_sniper_token = 16_695_000.0
    position_size_usd = 184.89
    sol_to_spend = position_size_usd / sol_usd

    # Realistic entry into post-sniper pool
    entry_fill = sim.simulate_pool_buy(
        sol_amount=sol_to_spend,
        pool_sol_reserve=post_sniper_sol,
        pool_token_reserve=post_sniper_token,
        priority_fee_sol=0.005,
        slot=456718841,
        timestamp=1791954967,
    )
    assert entry_fill.effective_fill_price_usd > 0.0060

    # Sell at logged exit time (pool had 1,038.5 SOL and 16,840,000 tokens)
    exit_fill = sim.simulate_pool_sell(
        tokens_to_sell=entry_fill.tokens_received,
        pool_sol_reserve=1038.5,
        pool_token_reserve=16_840_000.0,
        cost_basis_usd=position_size_usd,
        priority_fee_sol=0.005,
        slot=456718870,
        timestamp=1791954967 + 24, # 0.4 min = 24s
    )
    # The return is near -0.8%, completely refuting the +39,303.8% phantom win!
    assert exit_fill.net_realized_return_pct < 5.0
    assert exit_fill.net_realized_return_pct == pytest.approx(-0.83, abs=2.0)
    assert exit_fill.net_realized_pnl_usd < 5.0


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

    # Effective pool SOL after sniper: ~1055 SOL (DexScreener pooled 1,058.89 SOL after ~6.8 SOL of sells)
    assert fill.sol_reserves_after == pytest.approx(1055.05, abs=0.5)
    # Tokens received: ~190.2M tokens out of 206.9M opening pool tokens
    assert fill.tokens_received == pytest.approx(190_204_218.0, rel=1e-3)
    # Proves 17.5845 SOL was an effective boost deposit, NOT an external fee deduction!


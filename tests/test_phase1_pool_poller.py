"""
Unit tests for PoolReservePoller:
- Filters active targets to open positions + watchlist only
- Batched parsing of WSOL and token vault reserves
- Credit budget deduction on successful calls
- 429 rate limit backoff
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from src.onchain.provider import SolanaProvider, ProviderConfig, ProviderTier
from src.onchain.credit_budget import CreditBudgetTracker
from src.onchain.pool_poller import PoolReservePoller, PoolReserveSnapshot


@pytest.mark.asyncio
async def test_pool_poller_filters_to_open_and_watchlist_only(tmp_path):
    tracker = CreditBudgetTracker(storage_path=tmp_path / "budget.json", monthly_budget_per_endpoint=1000)
    provider = SolanaProvider(config=ProviderConfig(tier=ProviderTier.FREE), credit_tracker=tracker)
    poller = PoolReservePoller(provider=provider)

    # Register 3 pools
    poller.register_pool("pool_1", "wsol_1", "tok_1", "mint_1", is_open_position=False, is_watchlist=False)
    poller.register_pool("pool_2", "wsol_2", "tok_2", "mint_2", is_open_position=False, is_watchlist=False)
    poller.register_pool("pool_3", "wsol_3", "tok_3", "mint_3", is_open_position=False, is_watchlist=False)

    # No targets should be active yet
    assert len(poller.get_active_targets()) == 0

    # Mark mint_1 as open position and mint_3 as watchlist
    poller.set_open_positions({"mint_1"})
    poller.set_watchlist({"mint_3"})

    active = poller.get_active_targets()
    assert len(active) == 2
    active_mints = {p.token_address for p in active}
    assert active_mints == {"mint_1", "mint_3"}
    assert "mint_2" not in active_mints


@pytest.mark.asyncio
async def test_pool_poller_parses_reserves_and_deducts_credit(tmp_path):
    tracker = CreditBudgetTracker(storage_path=tmp_path / "budget.json", monthly_budget_per_endpoint=1000)
    cfg = ProviderConfig(tier=ProviderTier.FREE, rpc_urls=["https://mock-rpc.solana.com?api-key=test"])
    provider = SolanaProvider(config=cfg, credit_tracker=tracker)
    poller = PoolReservePoller(provider=provider)

    poller.register_pool("pool_A", "wsol_vault_A", "tok_vault_A", "mint_A", is_open_position=True)

    # Mock response for getMultipleAccounts
    mock_val = [
        {
            "data": {
                "parsed": {
                    "info": {
                        "tokenAmount": {"uiAmount": 85.5}
                    }
                }
            }
        },
        {
            "data": {
                "parsed": {
                    "info": {
                        "tokenAmount": {"uiAmount": 200_000_000.0}
                    }
                }
            }
        }
    ]

    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.json = AsyncMock(return_value={"result": {"context": {"slot": 456718900}, "value": mock_val}})
    mock_post = MagicMock()
    mock_post.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_post.__aexit__ = AsyncMock(return_value=None)

    with patch("aiohttp.ClientSession.post", return_value=mock_post):
        snaps = await poller.poll_reserves_once()
        assert len(snaps) == 1
        snap = snaps[0]
        assert snap.pool_address == "pool_A"
        assert snap.vault_sol_reserve == 85.5
        assert snap.boost_sol == pytest.approx(17.584505288)
        assert snap.sol_reserve == pytest.approx(85.5 + 17.584505288)
        assert snap.token_reserve == 200_000_000.0
        assert snap.spot_price_sol == pytest.approx((85.5 + 17.584505288) / 200_000_000.0)
        assert snap.slot == 456718900

        # Verify credit tracker deducted 1 credit
        usage = tracker.get_endpoint_usage("endpoint_0")
        assert usage["monthly_calls"] == 1


@pytest.mark.asyncio
async def test_pool_poller_nodf_committed_fixture_boost_and_effective_reserves(tmp_path):
    """Verify that PoolReservePoller decodes boost from committed NODF fixture and calculates effective reserves."""
    import base64
    import json
    from src.onchain.pool_poller import extract_boost_from_account_data

    # 1. Load committed NODF pool account fixture
    fixture_path = "tests/fixtures/pools/BNchF8GCxGKxsWbpkUE5D8RhGfB31QGT7DbAvMPY7RiV.json"
    with open(fixture_path, "r", encoding="utf-8") as f:
        pool_fixture = json.load(f)

    raw_bytes = base64.b64decode(pool_fixture["result"]["value"]["data"][0])
    decoded_boost = extract_boost_from_account_data(raw_bytes)
    assert decoded_boost == pytest.approx(17.584010360, abs=1e-8)

    # 2. Register NODF pool with the decoded boost
    tracker = CreditBudgetTracker(storage_path=tmp_path / "budget.json", monthly_budget_per_endpoint=1000)
    provider = SolanaProvider(config=ProviderConfig(tier=ProviderTier.FREE), credit_tracker=tracker)
    poller = PoolReservePoller(provider=provider)

    nodf_pool = "BNchF8GCxGKxsWbpkUE5D8RhGfB31QGT7DbAvMPY7RiV"
    nodf_mint = "qTFyfJiSQhMooT6LzybsWHjMXSGWsdkY3w8C9aXpump"
    poller.register_pool(
        pool_address=nodf_pool,
        wsol_vault="wsol_vault_nodf",
        token_vault="token_vault_nodf",
        token_address=nodf_mint,
        is_open_position=True,
        boost_sol=decoded_boost,
    )

    # 3. Mock real post-snipe vault balances (1,037.582853 SOL vault, 16,695,781.67 tokens)
    mock_val = [
        {"data": {"parsed": {"info": {"tokenAmount": {"uiAmount": 1037.582853}}}}},
        {"data": {"parsed": {"info": {"tokenAmount": {"uiAmount": 16695781.67}}}}},
    ]
    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.json = AsyncMock(return_value={"result": {"context": {"slot": 456718840}, "value": mock_val}})
    mock_post = MagicMock()
    mock_post.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_post.__aexit__ = AsyncMock(return_value=None)

    with patch("aiohttp.ClientSession.post", return_value=mock_post):
        snaps = await poller.poll_reserves_once()
        assert len(snaps) == 1
        snap = snaps[0]
        assert snap.pool_address == nodf_pool
        assert snap.vault_sol_reserve == 1037.582853
        assert snap.boost_sol == pytest.approx(17.584010360)
        # Effective SOL reserve = vault (1037.582853) + boost (17.584010) = 1055.166863
        assert snap.sol_reserve == pytest.approx(1055.16686336, abs=1e-4)
        assert snap.token_reserve == 16695781.67
        # Effective spot price = 1055.16686336 / 16695781.67 = 6.319961e-5 SOL/token
        assert snap.spot_price_sol == pytest.approx(6.319961e-5, abs=1e-8)



@pytest.mark.asyncio
async def test_adaptive_polling_intervals_and_stability_backoff(tmp_path):
    tracker = CreditBudgetTracker(storage_path=tmp_path / "budget.json", monthly_budget_per_endpoint=1000)
    provider = SolanaProvider(config=ProviderConfig(tier=ProviderTier.FREE), credit_tracker=tracker)
    poller = PoolReservePoller(
        provider=provider,
        fast_interval_sec=2.5,
        stable_interval_sec=7.5,
        idle_interval_sec=10.0,
        price_change_threshold=0.005,
    )

    # 1. No active targets -> Idle interval (10.0s)
    assert poller.compute_adaptive_interval() == 10.0

    # 2. Add an active target
    poller.register_pool("pool_X", "wsol_X", "tok_X", "mint_X", is_open_position=True)
    # First snapshot with open position -> fast poll (2.5s)
    poller.latest_reserves["pool_X"] = PoolReserveSnapshot(
        pool_address="pool_X", token_address="mint_X", sol_reserve=100.0,
        token_reserve=1_000_000.0, spot_price_sol=0.0001, slot=100, timestamp=1.0, endpoint_alias="alias"
    )
    assert poller.compute_adaptive_interval() == 2.5

    # 3. Simulate stable price (change < 0.5%): 0.0001001 vs 0.0001000 (+0.1%)
    poller._previous_prices["pool_X"] = 0.0001000
    poller.latest_reserves["pool_X"].spot_price_sol = 0.0001001
    assert poller.compute_adaptive_interval() == 7.5  # Backs off to stable (5-10s)

    # 4. Simulate volatile price move (change >= 0.5%): 0.0001020 vs 0.0001000 (+2.0%)
    poller.latest_reserves["pool_X"].spot_price_sol = 0.0001020
    assert poller.compute_adaptive_interval() == 2.5  # Speeds up to fast (2.5s)


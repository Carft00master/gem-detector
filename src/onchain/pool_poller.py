"""
Post-Migration Pool Reserve Poller (Phase 1 Tier FREE)
Performs batched getMultipleAccounts polling on vault accounts for open positions
and watchlist tokens only.
Enforces 2-5s intervals, exponential backoff with jitter on HTTP 429, round-robin
failover across SOLANA_RPC_URLS, and strict credit budget tracking.
Never prints or logs RPC credentials.
"""

import asyncio
from dataclasses import dataclass, field
import logging
import random
import time
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from src.onchain.provider import SolanaProvider, AllEndpointsExhaustedError, redact_secrets

logger = logging.getLogger(__name__)


import struct
import base64

PUMPSWAP_STANDARD_BOOST_SOL = 17.584505288
PUMPSWAP_BOOST_OFFSET = 245


def extract_boost_from_account_data(raw_data: bytes) -> float:
    """Extract little-endian u64 boost at offset 245 from 301-byte PumpSwap pool account."""
    if len(raw_data) < PUMPSWAP_BOOST_OFFSET + 8:
        return 0.0
    lamports = struct.unpack("<Q", raw_data[PUMPSWAP_BOOST_OFFSET:PUMPSWAP_BOOST_OFFSET + 8])[0]
    return lamports / 1e9


@dataclass
class PoolVaultPair:
    pool_address: str
    wsol_vault: str
    token_vault: str
    token_address: str
    symbol: str = ""
    is_open_position: bool = False
    is_watchlist: bool = False
    boost_sol: float = PUMPSWAP_STANDARD_BOOST_SOL


@dataclass
class PoolReserveSnapshot:
    pool_address: str
    token_address: str
    sol_reserve: float  # Effective SOL reserve (vault + boost)
    token_reserve: float
    spot_price_sol: float  # Effective spot price
    slot: int
    timestamp: float
    endpoint_alias: str
    vault_sol_reserve: float = 0.0  # Raw vault balance
    boost_sol: float = 0.0  # Boost amount added



class PoolReservePoller:
    """
    Batched RPC poller for migrated AMM pool reserves.
    Restricted to open positions + watchlist tokens to minimize RPC credit consumption.
    """
    def __init__(
        self,
        provider: Optional[SolanaProvider] = None,
        poll_interval_sec: float = 3.0,
        fast_interval_sec: float = 2.5,
        stable_interval_sec: float = 7.5,
        idle_interval_sec: float = 10.0,
        price_change_threshold: float = 0.005,
        max_batch_size: int = 100,
        on_reserves_updated: Optional[Callable[[PoolReserveSnapshot], Any]] = None,
    ):
        self.provider = provider or SolanaProvider()
        self.poll_interval = max(2.0, min(5.0, poll_interval_sec))
        self.fast_interval = max(2.0, min(5.0, fast_interval_sec))
        self.stable_interval = max(5.0, min(10.0, stable_interval_sec))
        self.idle_interval = max(5.0, min(30.0, idle_interval_sec))
        self.price_change_threshold = price_change_threshold
        self.current_interval = self.stable_interval
        self.max_batch_size = max_batch_size
        self.on_reserves_updated = on_reserves_updated

        self.tracked_pools: Dict[str, PoolVaultPair] = {}
        self.latest_reserves: Dict[str, PoolReserveSnapshot] = {}
        self._previous_prices: Dict[str, float] = {}

        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._session: Any = None
        self._consecutive_429s = 0

    def register_pool(
        self,
        pool_address: str,
        wsol_vault: str,
        token_vault: str,
        token_address: str,
        symbol: str = "",
        is_open_position: bool = False,
        is_watchlist: bool = False,
        boost_sol: float = PUMPSWAP_STANDARD_BOOST_SOL,
    ) -> None:
        """Register or update a pool to be actively polled."""
        self.tracked_pools[pool_address] = PoolVaultPair(
            pool_address=pool_address,
            wsol_vault=wsol_vault,
            token_vault=token_vault,
            token_address=token_address,
            symbol=symbol,
            is_open_position=is_open_position,
            is_watchlist=is_watchlist,
            boost_sol=boost_sol,
        )

    def unregister_pool(self, pool_address: str) -> None:
        """Remove a pool from active polling when closed and removed from watchlist."""
        self.tracked_pools.pop(pool_address, None)
        self.latest_reserves.pop(pool_address, None)

    def set_open_positions(self, open_mints: Set[str]) -> None:
        """Update open position status for all tracked pools."""
        for p in self.tracked_pools.values():
            p.is_open_position = p.token_address in open_mints

    def set_watchlist(self, watchlist_mints: Set[str]) -> None:
        """Update watchlist status for all tracked pools."""
        for p in self.tracked_pools.values():
            p.is_watchlist = p.token_address in watchlist_mints

    def get_active_targets(self) -> List[PoolVaultPair]:
        """Return only pools that are open positions or on the active watchlist."""
        return [
            p for p in self.tracked_pools.values()
            if p.is_open_position or p.is_watchlist
        ]

    async def _get_http_session(self) -> Any:
        if self._session is None or self._session.closed:
            self._session = self.provider.create_async_session(timeout=8.0)
        return self._session

    async def poll_reserves_once(self) -> List[PoolReserveSnapshot]:
        """
        Execute a single batched getMultipleAccounts call across all active vaults.
        Handles round-robin RPC selection, 429 exponential backoff, and credit tracking.
        """
        targets = self.get_active_targets()
        if not targets:
            return []

        # Build list of pubkeys (wsol_vault + token_vault for each active pool)
        vault_to_pool: Dict[str, Tuple[str, str]] = {}  # vault -> (pool_address, "wsol" | "token")
        pubkeys_to_fetch: List[str] = []

        for t in targets:
            vault_to_pool[t.wsol_vault] = (t.pool_address, "wsol")
            vault_to_pool[t.token_vault] = (t.pool_address, "token")
            pubkeys_to_fetch.extend([t.wsol_vault, t.token_vault])

        # Chunk into batches of up to max_batch_size (Solana limit is 100)
        chunks = [
            pubkeys_to_fetch[i:i + self.max_batch_size]
            for i in range(0, len(pubkeys_to_fetch), self.max_batch_size)
        ]

        session = await self._get_http_session()
        snapshots: List[PoolReserveSnapshot] = []
        now_ts = time.time()

        for chunk in chunks:
            # Select next RPC endpoint from round-robin pool with credit check
            try:
                endpoint_id, masked_alias, rpc_url = self.provider.get_next_rpc_endpoint()
            except AllEndpointsExhaustedError as e:
                logger.critical(f"PoolReservePoller: {e}")
                return snapshots

            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getMultipleAccounts",
                "params": [
                    chunk,
                    {"encoding": "jsonParsed", "commitment": "processed"}
                ]
            }

            try:
                result_json = await self.provider.execute_rpc_async(
                    session=session,
                    method="getMultipleAccounts",
                    params=[chunk, {"encoding": "jsonParsed", "commitment": "processed"}],
                    timeout=8.0,
                )
                self._consecutive_429s = 0
                val = result_json.get("result", {}).get("value", [])
                slot = result_json.get("result", {}).get("context", {}).get("slot", 0)

                # Accumulate parsed balances per pool
                pool_balances: Dict[str, Dict[str, float]] = {}

                for pubkey, account_info in zip(chunk, val):
                    if not account_info or pubkey not in vault_to_pool:
                        continue
                    pool_addr, vault_type = vault_to_pool[pubkey]
                    amt = 0.0
                    try:
                        token_amt = account_info.get("data", {}).get("parsed", {}).get("info", {}).get("tokenAmount", {})
                        amt = float(token_amt.get("uiAmount", 0.0) or 0.0)
                    except Exception:
                        amt = 0.0

                    pool_entry = pool_balances.setdefault(pool_addr, {})
                    pool_entry[vault_type] = amt

                # Create snapshots for pools where both balances were parsed
                for pool_addr, balances in pool_balances.items():
                    target_info = self.tracked_pools.get(pool_addr)
                    if not target_info:
                        continue
                    wsol = balances.get("wsol", 0.0)
                    tok = balances.get("token", 0.0)
                    boost = target_info.boost_sol
                    effective_sol = wsol + boost
                    spot = (effective_sol / tok) if tok > 0 else 0.0

                    snap = PoolReserveSnapshot(
                        pool_address=pool_addr,
                        token_address=target_info.token_address,
                        sol_reserve=effective_sol,
                        token_reserve=tok,
                        spot_price_sol=spot,
                        slot=slot,
                        timestamp=now_ts,
                        endpoint_alias=masked_alias,
                        vault_sol_reserve=wsol,
                        boost_sol=boost,
                    )
                    prev_price = self.latest_reserves[pool_addr].spot_price_sol if pool_addr in self.latest_reserves else None
                    if prev_price is not None:
                        self._previous_prices[pool_addr] = prev_price
                    self.latest_reserves[pool_addr] = snap
                    snapshots.append(snap)

                    if self.on_reserves_updated:
                        try:
                            if asyncio.iscoroutinefunction(self.on_reserves_updated):
                                await self.on_reserves_updated(snap)
                            else:
                                self.on_reserves_updated(snap)
                        except Exception as cb_err:
                            logger.error(f"Error in on_reserves_updated callback: {cb_err}")

            except asyncio.TimeoutError:
                logger.warning(f"Timeout querying RPC on {masked_alias}")
            except Exception as e:
                sanitized_err = redact_secrets(str(e))
                logger.warning(f"Error querying {masked_alias}: {sanitized_err}")

        return snapshots

    async def start(self) -> None:
        """Start background polling loop."""
        self._running = True
        self._task = asyncio.create_task(self._poll_loop())
        logger.info(f"PoolReservePoller started with {self.poll_interval}s interval (open positions + watchlist only).")

    async def stop(self) -> None:
        """Stop background polling loop."""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        if self._session and not self._session.closed:
            await self._session.close()
        logger.info("PoolReservePoller stopped.")

    def compute_adaptive_interval(self) -> float:
        """
        Calculates adaptive polling interval based on active targets and price volatility:
        - If no open positions and no active watchlist tokens: idle interval (10.0s) with 0 RPC calls.
        - If active targets exist and price moved >= threshold (default 0.5%): fast interval (2.0 - 5.0s, default 2.5s).
        - If active targets exist and price is stable (< 0.5%): backs off to stable interval (5.0 - 10.0s, default 7.5s).
        """
        targets = self.get_active_targets()
        if not targets:
            self.current_interval = self.idle_interval
            return self.current_interval

        has_volatile_target = False
        for t in targets:
            p_addr = t.pool_address
            latest = self.latest_reserves.get(p_addr)
            prev = self._previous_prices.get(p_addr)
            if latest and prev and prev > 0:
                pct_change = abs(latest.spot_price_sol - prev) / prev
                if pct_change >= self.price_change_threshold:
                    has_volatile_target = True
                    break
            elif latest and prev is None and t.is_open_position:
                has_volatile_target = True
                break

        if has_volatile_target:
            self.current_interval = self.fast_interval
        else:
            self.current_interval = self.stable_interval

        return self.current_interval

    async def _poll_loop(self) -> None:
        while self._running:
            try:
                targets = self.get_active_targets()
                if targets:
                    await self.poll_reserves_once()
                interval = self.compute_adaptive_interval()
            except Exception as e:
                logger.error(f"Unexpected error in pool poller loop: {e}")
                interval = self.poll_interval
            await asyncio.sleep(interval)

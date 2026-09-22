"""
GeckoTerminal Live Feed
Fetches newly created and trending microcap pools across Solana and Base.
"""

import asyncio
from datetime import datetime, timezone
import logging
from typing import Any, Dict, List, Optional
import aiohttp

from src.feeds.base_feed import BaseFeed, TokenCandidate, TokenSocials, TokenSecurityReport

logger = logging.getLogger(__name__)

CHAIN_MAP = {
    "solana": "solana",
    "bsc": "bsc",
    "bnb": "bsc",
    "robinhood": "robinhood",
    "base": "base",
    "ethereum": "eth",
    "eth": "eth",
}


class GeckoTerminalFeed(BaseFeed):
    BASE_URL = "https://api.geckoterminal.com/api/v2"

    def __init__(self, session: Optional[aiohttp.ClientSession] = None):
        self._session = session
        self._owns_session = session is None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=6)
            connector = aiohttp.TCPConnector(ssl=False)
            self._session = aiohttp.ClientSession(
                timeout=timeout,
                connector=connector,
                headers={
                    "Accept": "application/json;version=20230302",
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko)",
                },
            )
        return self._session

    async def fetch_new_pools(self, network: str, page: int = 1) -> List[Dict[str, Any]]:
        """Fetch newly created pools for a specific network."""
        gt_network = CHAIN_MAP.get(network.lower(), network.lower())
        session = await self._get_session()
        try:
            url = f"{self.BASE_URL}/networks/{gt_network}/new_pools?page={page}"
            async with session.get(url) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get("data", []) or []
                logger.debug(f"GeckoTerminal new_pools status: {resp.status}")
        except Exception as e:
            logger.debug(f"GeckoTerminal new_pools error: {e}")
        return []

    async def fetch_trending_pools(self, network: str) -> List[Dict[str, Any]]:
        """Fetch trending pools for a specific network."""
        gt_network = CHAIN_MAP.get(network.lower(), network.lower())
        session = await self._get_session()
        try:
            url = f"{self.BASE_URL}/networks/{gt_network}/trending_pools"
            async with session.get(url) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get("data", []) or []
        except Exception as e:
            logger.debug(f"GeckoTerminal trending_pools error: {e}")
        return []

    def _parse_pool(self, pool_data: Dict[str, Any], network: str) -> Optional[TokenCandidate]:
        try:
            attributes = pool_data.get("attributes", {})
            name = attributes.get("name", "Unknown")
            pool_address = attributes.get("address", "")
            base_token_price_usd = float(attributes.get("base_token_price_usd") or 0.0)
            fdv_usd = float(attributes.get("fdv_usd") or attributes.get("market_cap_usd") or 0.0)
            reserve_usd = float(attributes.get("reserve_in_usd") or 0.0)

            # Volume
            vol_dict = attributes.get("volume_usd", {})
            vol_5m = float(vol_dict.get("m5") or 0.0)
            vol_1h = float(vol_dict.get("h1") or 0.0)
            vol_24h = float(vol_dict.get("h24") or 0.0)

            # Transactions
            tx_dict = attributes.get("transactions", {})
            m5_tx = tx_dict.get("m5", {})
            h1_tx = tx_dict.get("h1", {})

            buys_5m = int(m5_tx.get("buys") or 0)
            sells_5m = int(m5_tx.get("sells") or 0)
            buys_1h = int(h1_tx.get("buys") or 0)
            sells_1h = int(h1_tx.get("sells") or 0)

            buyers_1h = int(h1_tx.get("buyers") or max(int(buys_1h * 0.8), buys_5m))
            sellers_1h = int(h1_tx.get("sellers") or max(int(sells_1h * 0.75), sells_5m))

            # Pool creation timestamp
            pool_created_at_str = attributes.get("pool_created_at")
            created_at = None
            age_minutes = 0.0
            if pool_created_at_str:
                try:
                    created_at = datetime.fromisoformat(pool_created_at_str.replace("Z", "+00:00"))
                    now_utc = datetime.now(timezone.utc)
                    age_minutes = max(0.0, (now_utc - created_at).total_seconds() / 60.0)
                except Exception:
                    pass

            # Extract base token address from relationships
            relationships = pool_data.get("relationships", {})
            base_token_data = relationships.get("base_token", {}).get("data", {})
            base_token_id = base_token_data.get("id", "")
            # ID format: "network_address"
            token_address = base_token_id.split("_")[-1] if "_" in base_token_id else pool_address

            # Symbol extraction
            symbol = name.split("/")[0].strip() if "/" in name else name

            candidate = TokenCandidate(
                address=token_address,
                pair_address=pool_address,
                symbol=symbol,
                name=name,
                chain=network.lower(),
                dex_id=relationships.get("dex", {}).get("data", {}).get("id", "dex"),
                market_cap_usd=fdv_usd,
                price_usd=base_token_price_usd,
                liquidity_usd=reserve_usd,
                volume_5m_usd=vol_5m,
                volume_1h_usd=vol_1h,
                volume_24h_usd=vol_24h,
                txns_5m_buys=buys_5m,
                txns_5m_sells=sells_5m,
                txns_1h_buys=buys_1h,
                txns_1h_sells=sells_1h,
                unique_buyers_1h=buyers_1h,
                unique_sellers_1h=sellers_1h,
                created_at=created_at,
                age_minutes=age_minutes,
                socials=TokenSocials(),
                security=TokenSecurityReport(),
                raw_data=pool_data,
            )
            candidate.calculate_ratios()
            return candidate
        except Exception as e:
            logger.debug(f"Error parsing GeckoTerminal pool: {e}")
            return None

    async def fetch_candidates(self, chain: str) -> List[TokenCandidate]:
        """Fetch candidates from new and trending pools."""
        candidates: Dict[str, TokenCandidate] = {}

        new_pools_task = self.fetch_new_pools(chain)
        trending_pools_task = self.fetch_trending_pools(chain)

        new_pools, trending_pools = await asyncio.gather(
            new_pools_task, trending_pools_task, return_exceptions=True
        )

        if isinstance(new_pools, list):
            for p in new_pools:
                cand = self._parse_pool(p, chain)
                if cand and cand.address:
                    candidates[cand.address] = cand

        if isinstance(trending_pools, list):
            for p in trending_pools:
                cand = self._parse_pool(p, chain)
                if cand and cand.address and cand.address not in candidates:
                    candidates[cand.address] = cand

        return list(candidates.values())

    async def close(self) -> None:
        if self._owns_session and self._session and not self._session.closed:
            await self._session.close()

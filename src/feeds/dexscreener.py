"""
DexScreener Live Feed
Fetches latest token profiles, boosted tokens, and live pair metrics across Solana, Base, and EVM chains.
"""

import asyncio
from datetime import datetime, timezone
import logging
from typing import Any, Dict, List, Optional
import aiohttp

from src.feeds.base_feed import BaseFeed, TokenCandidate, TokenSocials, TokenSecurityReport

logger = logging.getLogger(__name__)


class DexScreenerFeed(BaseFeed):
    BASE_URL = "https://api.dexscreener.com"

    def __init__(self, session: Optional[aiohttp.ClientSession] = None):
        self._session = session
        self._owns_session = session is None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=4)
            connector = aiohttp.TCPConnector(ssl=False)
            self._session = aiohttp.ClientSession(
                timeout=timeout,
                connector=connector,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko)"},
            )
        return self._session

    async def fetch_token_profiles(self) -> List[Dict[str, Any]]:
        """Fetch latest active token profiles from DexScreener."""
        session = await self._get_session()
        try:
            url = f"{self.BASE_URL}/token-profiles/latest/v1"
            async with session.get(url) as resp:
                if resp.status == 200:
                    return await resp.json()
                logger.warning(f"DexScreener profiles returned status {resp.status}")
        except Exception as e:
            logger.debug(f"Error fetching DexScreener token profiles: {e}")
        return []

    async def fetch_token_boosts(self) -> List[Dict[str, Any]]:
        """Fetch latest boosted tokens on DexScreener."""
        session = await self._get_session()
        try:
            url = f"{self.BASE_URL}/token-boosts/latest/v1"
            async with session.get(url) as resp:
                if resp.status == 200:
                    return await resp.json()
        except Exception as e:
            logger.debug(f"Error fetching DexScreener token boosts: {e}")
        return []

    async def fetch_pairs_by_tokens(self, chain: str, token_addresses: List[str]) -> List[Dict[str, Any]]:
        """Fetch pair data for up to 30 tokens in batch."""
        if not token_addresses:
            return []
        session = await self._get_session()
        # DexScreener tokens endpoint accepts comma-separated addresses
        addresses_str = ",".join(token_addresses[:30])
        try:
            url = f"{self.BASE_URL}/tokens/v1/{chain}/{addresses_str}"
            async with session.get(url) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if isinstance(data, list):
                        return data
                    elif isinstance(data, dict) and "pairs" in data:
                        return data["pairs"] or []
        except Exception as e:
            # Fallback to general tokens endpoint
            try:
                fallback_url = f"{self.BASE_URL}/latest/dex/tokens/{addresses_str}"
                async with session.get(fallback_url) as resp2:
                    if resp2.status == 200:
                        data2 = await resp2.json()
                        return data2.get("pairs", []) or []
            except Exception as e2:
                logger.debug(f"Error fetching token batch data: {e2}")
        return []

    async def fetch_search_pairs(self, query: str) -> List[Dict[str, Any]]:
        """Search pairs by symbol or term."""
        session = await self._get_session()
        try:
            url = f"{self.BASE_URL}/latest/dex/search?q={query}"
            async with session.get(url) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get("pairs", []) or []
        except Exception as e:
            logger.debug(f"Error searching pairs for query {query}: {e}")
        return []

    def _parse_pair(self, pair: Dict[str, Any]) -> Optional[TokenCandidate]:
        """Convert a raw DexScreener pair dict into a normalized TokenCandidate."""
        try:
            base_token = pair.get("baseToken", {})
            token_address = base_token.get("address", "")
            if not token_address:
                return None

            symbol = base_token.get("symbol", "UNKNOWN")
            name = base_token.get("name", "Unknown")
            chain_id = pair.get("chainId", "").lower()
            dex_id = pair.get("dexId", "").lower()
            pair_address = pair.get("pairAddress", "")

            # Market Cap & Pricing
            market_cap = float(pair.get("marketCap") or pair.get("fdv") or 0.0)
            price_usd = float(pair.get("priceUsd") or 0.0)

            # Liquidity
            liq_data = pair.get("liquidity", {})
            liquidity_usd = float(liq_data.get("usd") or 0.0)

            # Volume
            vol_data = pair.get("volume", {})
            vol_5m = float(vol_data.get("m5") or 0.0)
            vol_1h = float(vol_data.get("h1") or 0.0)
            vol_24h = float(vol_data.get("h24") or 0.0)

            # Transactions
            tx_data = pair.get("txns", {})
            tx_5m = tx_data.get("m5", {})
            tx_1h = tx_data.get("h1", {})

            buys_5m = int(tx_5m.get("buys") or 0)
            sells_5m = int(tx_5m.get("sells") or 0)
            buys_1h = int(tx_1h.get("buys") or 0)
            sells_1h = int(tx_1h.get("sells") or 0)

            # Approximating unique buyers from txns (or from info if available)
            # In microcaps, unique buyers is roughly 70-90% of total buys in first hour
            unique_buyers_est = max(int(buys_1h * 0.8), buys_5m)
            unique_sellers_est = max(int(sells_1h * 0.75), sells_5m)

            # Age
            pair_created_at_ms = pair.get("pairCreatedAt")
            created_at = None
            age_minutes = 0.0
            if pair_created_at_ms:
                created_at = datetime.fromtimestamp(pair_created_at_ms / 1000.0, tz=timezone.utc)
                now_utc = datetime.now(timezone.utc)
                age_minutes = max(0.0, (now_utc - created_at).total_seconds() / 60.0)

            # Socials
            info = pair.get("info", {})
            social_links = info.get("socials", []) or []
            websites = info.get("websites", []) or []

            socials = TokenSocials()
            for s in social_links:
                stype = s.get("type", "").lower()
                surl = s.get("url", "")
                if "twitter" in stype or "x.com" in surl or "twitter.com" in surl:
                    socials.twitter = surl
                elif "telegram" in stype or "t.me" in surl:
                    socials.telegram = surl
                elif "discord" in stype:
                    socials.discord = surl

            if websites:
                socials.website = websites[0].get("url")

            # Security baseline
            security = TokenSecurityReport(
                lp_burned_or_locked_pct=100.0 if "burn" in dex_id or "pump" in dex_id else 95.0,
                mint_renounced=True,
                freeze_renounced=True,
            )

            candidate = TokenCandidate(
                address=token_address,
                pair_address=pair_address,
                symbol=symbol,
                name=name,
                chain=chain_id,
                dex_id=dex_id,
                market_cap_usd=market_cap,
                price_usd=price_usd,
                liquidity_usd=liquidity_usd,
                volume_5m_usd=vol_5m,
                volume_1h_usd=vol_1h,
                volume_24h_usd=vol_24h,
                txns_5m_buys=buys_5m,
                txns_5m_sells=sells_5m,
                txns_1h_buys=buys_1h,
                txns_1h_sells=sells_1h,
                unique_buyers_1h=unique_buyers_est,
                unique_sellers_1h=unique_sellers_est,
                created_at=created_at,
                age_minutes=age_minutes,
                socials=socials,
                security=security,
                raw_data=pair,
            )
            candidate.calculate_ratios()
            return candidate
        except Exception as e:
            logger.debug(f"Error parsing pair: {e}")
            return None

    async def fetch_candidates(self, chain: str) -> List[TokenCandidate]:
        """Fetch active candidates for a given chain via token profiles."""
        candidates: Dict[str, TokenCandidate] = {}

        # 1. Fetch token profiles
        try:
            profiles = await asyncio.wait_for(self.fetch_token_profiles(), timeout=2.5)
        except Exception:
            profiles = []

        target_addresses: set[str] = set()
        if isinstance(profiles, list):
            for p in profiles:
                p_chain = p.get("chainId", "").lower()
                if not chain or p_chain == chain.lower():
                    token_addr = p.get("tokenAddress")
                    if token_addr:
                        target_addresses.add(token_addr)

        # 2. Batch fetch pair data concurrently (chunks of 30)
        address_list = list(target_addresses)[:60]
        chunks = [address_list[i : i + 30] for i in range(0, len(address_list), 30)]
        chunk_tasks = [self.fetch_pairs_by_tokens(chain, ch) for ch in chunks]
        
        if chunk_tasks:
            try:
                results = await asyncio.wait_for(asyncio.gather(*chunk_tasks, return_exceptions=True), timeout=3.5)
                for res in results:
                    if isinstance(res, list):
                        for pair in res:
                            candidate = self._parse_pair(pair)
                            if candidate:
                                candidates[candidate.address] = candidate
            except Exception as e:
                logger.debug(f"Error fetching pair batches: {e}")

        return list(candidates.values())

    async def close(self) -> None:
        if self._owns_session and self._session and not self._session.closed:
            await self._session.close()

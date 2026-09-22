"""
Discord Webhook Alert Dispatcher
Sends rich embed cards for high-conviction breakout tokens.
"""

import logging
from typing import Optional
import aiohttp

from src.config import DiscordAlertConfig
from src.feeds.base_feed import ScoredToken

logger = logging.getLogger(__name__)


class DiscordNotifier:
    def __init__(self, config: DiscordAlertConfig, session: Optional[aiohttp.ClientSession] = None):
        self.config = config
        self._session = session
        self._owns_session = session is None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def send_alert(self, scored_token: ScoredToken) -> bool:
        if not self.config.enabled or not self.config.webhook_url:
            return False

        if scored_token.score.total_gem_score < self.config.min_score_for_alert:
            return False

        t = scored_token.token
        s = scored_token.score

        dex_link = f"https://dexscreener.com/{t.chain}/{t.pair_address or t.address}"
        rug_link = f"https://rugcheck.xyz/tokens/{t.address}" if t.chain == "solana" else ""

        # Color: Green if score >= 80, Gold if >= 70
        color = 0x00FF88 if s.total_gem_score >= 80 else 0xF1C40F

        embed = {
            "title": f"🚀 Potential Breakout: ${t.symbol} ({t.name})",
            "description": f"**Gem Score:** `{s.total_gem_score}/100` | **Chain:** `{t.chain.upper()}` | **DEX:** `{t.dex_id.upper()}`",
            "url": dex_link,
            "color": color,
            "fields": [
                {
                    "name": "💰 Market Cap",
                    "value": f"${t.market_cap_usd:,.0f}",
                    "inline": True,
                },
                {
                    "name": "💧 Liquidity",
                    "value": f"${t.liquidity_usd:,.0f} ({t.liquidity_mc_ratio:.1%})",
                    "inline": True,
                },
                {
                    "name": "📊 5m / 1h Vol",
                    "value": f"${t.volume_5m_usd:,.0f} / ${t.volume_1h_usd:,.0f}",
                    "inline": True,
                },
                {
                    "name": "🔥 Buy/Sell Ratio",
                    "value": f"{max(t.buy_sell_ratio_5m, t.buy_sell_ratio_1h):.2f}x",
                    "inline": True,
                },
                {
                    "name": "👥 Unique Buyers",
                    "value": f"{t.unique_buyers_1h}",
                    "inline": True,
                },
                {
                    "name": "🛡️ Top 10 Supply",
                    "value": f"{t.security.top10_holder_pct:.1f}%",
                    "inline": True,
                },
                {
                    "name": "🎯 Key Signals",
                    "value": ", ".join(s.signals[:5]) if s.signals else "Standard",
                    "inline": False,
                },
            ],
            "footer": {"text": "Sub-$10k to $3M Breakout Scanner"},
        }

        if rug_link:
            embed["fields"].append({
                "name": "🔗 Links",
                "value": f"[DexScreener]({dex_link}) • [RugCheck]({rug_link})",
                "inline": False,
            })

        payload = {"embeds": [embed]}
        session = await self._get_session()

        try:
            async with session.post(self.config.webhook_url, json=payload) as resp:
                if resp.status in (200, 204):
                    logger.info(f"Discord alert sent for ${t.symbol}")
                    return True
                else:
                    err_txt = await resp.text()
                    logger.error(f"Discord alert error: {err_txt}")
        except Exception as e:
            logger.error(f"Failed to dispatch Discord alert: {e}")
        return False

    async def close(self) -> None:
        if self._owns_session and self._session and not self._session.closed:
            await self._session.close()

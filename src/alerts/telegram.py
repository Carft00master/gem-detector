"""
Telegram Alert Dispatcher
Sends formatted alert messages for high-conviction breakout tokens.
"""

import logging
from typing import Optional
import aiohttp

from src.config import TelegramAlertConfig
from src.feeds.base_feed import ScoredToken

logger = logging.getLogger(__name__)


class TelegramNotifier:
    def __init__(self, config: TelegramAlertConfig, session: Optional[aiohttp.ClientSession] = None):
        self.config = config
        self._session = session
        self._owns_session = session is None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def send_alert(self, scored_token: ScoredToken) -> bool:
        if not self.config.enabled or not self.config.bot_token or not self.config.chat_id:
            return False

        if scored_token.score.total_gem_score < self.config.min_score_for_alert:
            return False

        t = scored_token.token
        s = scored_token.score

        dex_link = f"https://dexscreener.com/{t.chain}/{t.pair_address or t.address}"
        rug_link = f"https://rugcheck.xyz/tokens/{t.address}" if t.chain == "solana" else ""

        signals_str = ", ".join(s.signals[:4]) if s.signals else "Standard"

        msg = (
            f"🚀 <b>POTENTIAL 300x BREAKOUT DETECTED</b>\n"
            f"<b>Token:</b> ${t.symbol} ({t.name})\n"
            f"<b>Chain:</b> {t.chain.upper()} | <b>DEX:</b> {t.dex_id.upper()}\n"
            f"<b>Gem Score:</b> 🟢 <b>{s.total_gem_score}/100</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"💰 <b>Market Cap:</b> ${t.market_cap_usd:,.0f}\n"
            f"💧 <b>Liquidity:</b> ${t.liquidity_usd:,.0f} ({t.liquidity_mc_ratio:.1%} of MC)\n"
            f"📊 <b>5m / 1h Vol:</b> ${t.volume_5m_usd:,.0f} / ${t.volume_1h_usd:,.0f}\n"
            f"🔥 <b>Buy/Sell Ratio:</b> {max(t.buy_sell_ratio_5m, t.buy_sell_ratio_1h):.2f}x\n"
            f"👥 <b>Unique Buyers:</b> {t.unique_buyers_1h}\n"
            f"🛡️ <b>Top 10 Supply:</b> {t.security.top10_holder_pct:.1f}%\n"
            f"🎯 <b>Signals:</b> <i>{signals_str}</i>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🔗 <a href='{dex_link}'>DexScreener Chart</a>"
        )
        if rug_link:
            msg += f" | <a href='{rug_link}'>RugCheck</a>"

        session = await self._get_session()
        url = f"https://api.telegram.org/bot{self.config.bot_token}/sendMessage"
        payload = {
            "chat_id": self.config.chat_id,
            "text": msg,
            "parse_mode": "HTML",
            "disable_web_page_preview": False,
        }

        try:
            async with session.post(url, json=payload) as resp:
                if resp.status == 200:
                    logger.info(f"Telegram alert sent for ${t.symbol}")
                    return True
                else:
                    err_txt = await resp.text()
                    logger.error(f"Telegram alert error: {err_txt}")
        except Exception as e:
            logger.error(f"Failed to dispatch Telegram alert: {e}")
        return False

    async def close(self) -> None:
        if self._owns_session and self._session and not self._session.closed:
            await self._session.close()

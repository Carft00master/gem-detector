"""
Multi-State Alert Dispatcher
Dispatches 6 distinct alert states across Telegram and Discord:
WATCH | EARLY_BREAKOUT | HIGH_CONVICTION | MANIPULATION_WARNING | RUG_WARNING | EXIT_INVALIDATION
"""

import logging
from typing import Any, Dict, Optional
import aiohttp

from src.config import AlertConfig
from src.feeds.base_feed import TokenCandidate
from src.models.predictor import BreakoutPredictionOutput

logger = logging.getLogger(__name__)

STATE_COLORS = {
    "HIGH_CONVICTION": 0x00FF88,     # Vibrant Neon Green
    "EARLY_BREAKOUT": 0x2ECC71,      # Green
    "WATCH": 0x3498DB,               # Blue
    "MANIPULATION_WARNING": 0xE67E22,# Orange
    "RUG_WARNING": 0xE74C3C,         # Red
    "EXIT_INVALIDATION": 0x95A5A6,   # Gray
}

STATE_EMOJIS = {
    "HIGH_CONVICTION": "🚀 ★ [HIGH CONVICTION BREAKOUT]",
    "EARLY_BREAKOUT": "🟢 [EARLY BREAKOUT MOMENTUM]",
    "WATCH": "👀 [WATCHLIST SETUP]",
    "MANIPULATION_WARNING": "⚠️ [MANIPULATION / WASH WARNING]",
    "RUG_WARNING": "🚨 [CRITICAL RUG / SAFETY RISK]",
    "EXIT_INVALIDATION": "❌ [SIGNAL INVALIDATION / EXIT]",
}


class MultiStateAlertDispatcher:
    def __init__(self, config: AlertConfig, session: Optional[aiohttp.ClientSession] = None):
        self.config = config
        self._session = session
        self._owns_session = session is None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            connector = aiohttp.TCPConnector(ssl=False)
            self._session = aiohttp.ClientSession(connector=connector)
        return self._session

    async def dispatch_alert(
        self,
        token: TokenCandidate,
        prediction: BreakoutPredictionOutput,
    ) -> None:
        """Dispatch multi-state alerts to Telegram and Discord."""
        state = prediction.alert_state
        if state == "WATCH" and not self.config.telegram.enabled and not self.config.discord.enabled:
            return

        await self._send_telegram(token, prediction)
        await self._send_discord(token, prediction)

    async def _send_telegram(self, t: TokenCandidate, p: BreakoutPredictionOutput) -> None:
        cfg = self.config.telegram
        if not cfg.enabled or not cfg.bot_token or not cfg.chat_id:
            return

        header = STATE_EMOJIS.get(p.alert_state, f"[{p.alert_state}]")
        dex_link = f"https://dexscreener.com/{t.chain}/{t.pair_address or t.address}"
        rug_link = f"https://rugcheck.xyz/tokens/{t.address}" if t.chain == "solana" else ""

        signals_str = ", ".join(p.signals[:3]) if p.signals else "Standard"
        warnings_str = ", ".join(p.risk_warnings[:2]) if p.risk_warnings else "None"

        msg = (
            f"<b>{header}</b>\n"
            f"<b>Token:</b> ${t.symbol} ({t.name})\n"
            f"<b>Chain / DEX:</b> {t.chain.upper()} | {t.dex_id.upper()}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🎯 <b>P(Target $3M):</b> <code>{p.p_reach_3m:.2%}</code> | <b>Score:</b> <code>{p.model_score:.1f}/100</code>\n"
            f"📊 <b>P($100K):</b> <code>{p.p_reach_100k:.1%}</code> | <b>P($1M):</b> <code>{p.p_reach_1m:.1%}</code>\n"
            f"💰 <b>Market Cap:</b> ${t.market_cap_usd:,.0f} | <b>Liquidity:</b> ${t.liquidity_usd:,.0f} ({t.liquidity_mc_ratio:.1%})\n"
            f"🛡️ <b>Rug Risk:</b> <code>{p.p_rug:.1%}</code> | <b>Cabal Risk:</b> <code>{p.p_cabal:.1%}</code>\n"
            f"🧼 <b>Wash Risk:</b> <code>{p.p_manipulation:.1%}</code> | <b>Wallet Indep:</b> <code>{p.wallet_independence:.2f}</code>\n"
            f"👥 <b>Buyers / Sellers:</b> {t.unique_buyers_1h} / {t.unique_sellers_1h}\n"
            f"⚡ <b>Signals:</b> <i>{signals_str}</i>\n"
        )
        if p.risk_warnings:
            msg += f"⚠️ <b>Risks:</b> <i>{warnings_str}</i>\n"

        msg += f"━━━━━━━━━━━━━━━━━━━━\n🔗 <a href='{dex_link}'>DexScreener</a>"
        if rug_link:
            msg += f" | <a href='{rug_link}'>RugCheck</a>"

        session = await self._get_session()
        url = f"https://api.telegram.org/bot{cfg.bot_token}/sendMessage"
        payload = {"chat_id": cfg.chat_id, "text": msg, "parse_mode": "HTML", "disable_web_page_preview": False}

        try:
            async with session.post(url, json=payload) as resp:
                if resp.status == 200:
                    logger.info(f"Telegram {p.alert_state} alert sent for ${t.symbol}")
        except Exception as e:
            logger.debug(f"Telegram dispatch error: {e}")

    async def _send_discord(self, t: TokenCandidate, p: BreakoutPredictionOutput) -> None:
        cfg = self.config.discord
        if not cfg.enabled or not cfg.webhook_url:
            return

        header = STATE_EMOJIS.get(p.alert_state, f"[{p.alert_state}]")
        dex_link = f"https://dexscreener.com/{t.chain}/{t.pair_address or t.address}"
        color = STATE_COLORS.get(p.alert_state, 0x3498DB)

        embed = {
            "title": f"{header}: ${t.symbol} ({t.name})",
            "description": f"**P($3M Target):** `{p.p_reach_3m:.2%}` | **Model Score:** `{p.model_score:.1f}/100` | **Chain:** `{t.chain.upper()}`",
            "url": dex_link,
            "color": color,
            "fields": [
                {"name": "💰 Market Cap", "value": f"${t.market_cap_usd:,.0f}", "inline": True},
                {"name": "💧 Liquidity", "value": f"${t.liquidity_usd:,.0f} ({t.liquidity_mc_ratio:.1%})", "inline": True},
                {"name": "🎯 P($100K) / P($1M)", "value": f"`{p.p_reach_100k:.1%}` / `{p.p_reach_1m:.1%}`", "inline": True},
                {"name": "🛡️ Rug Risk", "value": f"`{p.p_rug:.1%}`", "inline": True},
                {"name": "⚠️ Cabal Risk", "value": f"`{p.p_cabal:.1%}`", "inline": True},
                {"name": "🧼 Wash Risk", "value": f"`{p.p_manipulation:.1%}`", "inline": True},
                {"name": "👥 Unique Buyers", "value": f"{t.unique_buyers_1h}", "inline": True},
                {"name": "⚡ Signals", "value": ", ".join(p.signals[:4]) if p.signals else "Normal", "inline": False},
            ],
            "footer": {"text": "Research-Grade Sub-$10K Breakout Radar"},
        }
        if p.risk_warnings:
            embed["fields"].append({"name": "🚨 Warnings", "value": ", ".join(p.risk_warnings), "inline": False})

        payload = {"embeds": [embed]}
        session = await self._get_session()
        try:
            async with session.post(cfg.webhook_url, json=payload) as resp:
                if resp.status in (200, 204):
                    logger.info(f"Discord {p.alert_state} alert sent for ${t.symbol}")
        except Exception as e:
            logger.debug(f"Discord dispatch error: {e}")

    async def close(self) -> None:
        if self._owns_session and self._session and not self._session.closed:
            await self._session.close()

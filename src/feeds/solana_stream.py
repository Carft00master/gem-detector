"""
Solana & PumpPortal Live WebSocket Stream
Provides instant real-time detection of new token launches and trade flow on Solana.
"""

import asyncio
import json
import logging
from typing import Any, Callable, Dict, Optional
import websockets

logger = logging.getLogger(__name__)


class SolanaPumpStream:
    PUMP_PORTAL_WS = "wss://pumpportal.fun/api/data"

    def __init__(self, on_new_token: Optional[Callable[[Dict[str, Any]], Any]] = None,
                 on_trade: Optional[Callable[[Dict[str, Any]], Any]] = None):
        self.on_new_token = on_new_token
        self.on_trade = on_trade
        self._running = False
        self._ws_task: Optional[asyncio.Task] = None

    async def start(self) -> None:
        """Start background websocket listener."""
        self._running = True
        self._ws_task = asyncio.create_task(self._listen_loop())

    async def stop(self) -> None:
        """Stop websocket listener."""
        self._running = False
        if self._ws_task and not self._ws_task.done():
            self._ws_task.cancel()
            try:
                await self._ws_task
            except asyncio.CancelledError:
                pass

    async def _listen_loop(self) -> None:
        while self._running:
            try:
                async with websockets.connect(
                    self.PUMP_PORTAL_WS,
                    ping_interval=20,
                    ping_timeout=20,
                    close_timeout=10,
                ) as ws:
                    logger.info("Connected to Solana / PumpPortal stream")

                    # Subscribe to new token creations
                    await ws.send(json.dumps({"method": "subscribeNewToken"}))

                    while self._running:
                        msg = await ws.recv()
                        try:
                            data = json.loads(msg)
                            tx_type = data.get("txType")
                            if tx_type == "create" or "mint" in data:
                                if self.on_new_token:
                                    if asyncio.iscoroutinefunction(self.on_new_token):
                                        await self.on_new_token(data)
                                    else:
                                        self.on_new_token(data)
                            elif tx_type in ("buy", "sell"):
                                if self.on_trade:
                                    if asyncio.iscoroutinefunction(self.on_trade):
                                        await self.on_trade(data)
                                    else:
                                        self.on_trade(data)
                        except json.JSONDecodeError:
                            continue
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.debug(f"Solana stream reconnecting after error: {e}")
                if self._running:
                    await asyncio.sleep(5)

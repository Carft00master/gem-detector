"""
On-Chain Curve Trade Collector (Phase 2A Foundation).
Subscribes to live token creations and subsequent trading flow on pump.fun bonding curves
for their first 30 minutes.

Stores distinct buy/sell events into data/curve_trades.db without modifying
existing databases (all existing DBs remain strictly read-only).
"""

import asyncio
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import sqlite3
import time
from typing import Any, Dict, Optional, Set

import websockets

from src.utils.ssl_context import get_verified_ssl_context

logger = logging.getLogger("trade_collector")


class CurveTradeCollector:
    PUMPPORTAL_WS_URL = "wss://pumpportal.fun/api/data"
    TRACKING_WINDOW_SECONDS = 1800  # 30 minutes

    def __init__(self, db_path: str = "data/curve_trades.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

        self._running = False
        self._ws: Optional[websockets.WebSocketClientProtocol] = None
        self._tracked_mints: Dict[str, float] = {}  # mint -> expiry_timestamp
        self._total_trades_collected = 0
        self._total_tokens_tracked = 0

    def _init_db(self) -> None:
        """Create trades database schema if not present."""
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS curve_trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                mint TEXT NOT NULL,
                tx_type TEXT NOT NULL,
                wallet TEXT NOT NULL,
                sol_amount REAL NOT NULL,
                token_amount REAL NOT NULL,
                slot INTEGER,
                block_time INTEGER,
                signature TEXT,
                created_at_utc TEXT NOT NULL
            )
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_curve_trades_mint ON curve_trades(mint)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_curve_trades_time ON curve_trades(block_time)")
        conn.commit()
        conn.close()

    def record_trade(
        self,
        mint: str,
        tx_type: str,
        wallet: str,
        sol_amount: float,
        token_amount: float,
        slot: Optional[int],
        block_time: Optional[int],
        signature: Optional[str],
    ) -> None:
        """Insert trade event into isolated curve_trades.db."""
        now_utc = datetime.now(timezone.utc).isoformat()
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO curve_trades (mint, tx_type, wallet, sol_amount, token_amount, slot, block_time, signature, created_at_utc)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (mint, tx_type.lower(), wallet, sol_amount, token_amount, slot, block_time, signature, now_utc))
        conn.commit()
        conn.close()
        self._total_trades_collected += 1

    async def _handle_message(self, raw_msg: str) -> None:
        """Parse incoming websocket stream message."""
        try:
            data = json.loads(raw_msg)
        except Exception:
            return

        # Case 1: New token creation event
        if "signature" in data and "mint" in data and data.get("txType") == "create":
            mint = data["mint"]
            expiry = time.time() + self.TRACKING_WINDOW_SECONDS
            self._tracked_mints[mint] = expiry
            self._total_tokens_tracked += 1
            logger.info(f"New mint detected: {mint}. Subscribing to trades for 30m.")
            
            # Subscribe to token's trades on PumpPortal
            if self._ws:
                sub_payload = {"method": "subscribeTokenTrade", "keys": [mint]}
                await self._ws.send(json.dumps(sub_payload))

        # Case 2: Trade execution event on tracked token
        tx_type = data.get("txType")
        if tx_type in ("buy", "sell"):
            mint = data.get("mint")
            if mint and mint in self._tracked_mints:
                wallet = data.get("traderPublicKey") or data.get("user") or "UNKNOWN"
                sol_amt = float(data.get("solAmount") or data.get("vSolInBondingCurve") or 0.0)
                tok_amt = float(data.get("tokenAmount") or data.get("vTokensInBondingCurve") or 0.0)
                slot = data.get("slot")
                b_time = data.get("blockTime") or int(time.time())
                sig = data.get("signature")

                self.record_trade(
                    mint=mint,
                    tx_type=tx_type,
                    wallet=wallet,
                    sol_amount=sol_amt,
                    token_amount=tok_amt,
                    slot=slot,
                    block_time=b_time,
                    signature=sig,
                )

    async def _prune_expired_mints(self) -> None:
        """Unsubscribe and prune mints that have exceeded the 30-minute window."""
        while self._running:
            await asyncio.sleep(60)
            now = time.time()
            expired = [m for m, exp in self._tracked_mints.items() if now >= exp]
            if expired:
                for m in expired:
                    del self._tracked_mints[m]
                if self._ws:
                    try:
                        unsub_payload = {"method": "unsubscribeTokenTrade", "keys": expired}
                        await self._ws.send(json.dumps(unsub_payload))
                    except Exception as e:
                        logger.warning(f"Error unsubscribing expired mints: {e}")
                logger.info(f"Pruned {len(expired)} expired tokens. Active tracking: {len(self._tracked_mints)} tokens.")

    async def run(self, max_duration_seconds: Optional[int] = None) -> None:
        """Run trade collection loop."""
        self._running = True
        ssl_ctx = get_verified_ssl_context()
        start_time = time.time()

        asyncio.create_task(self._prune_expired_mints())

        logger.info(f"CurveTradeCollector starting. DB: {self.db_path}")
        while self._running:
            if max_duration_seconds and (time.time() - start_time) >= max_duration_seconds:
                logger.info(f"Target duration of {max_duration_seconds}s reached. Stopping collector.")
                break

            try:
                logger.info("Connecting to PumpPortal stream...")
                async with websockets.connect(
                    self.PUMPPORTAL_WS_URL,
                    ssl=ssl_ctx,
                    open_timeout=15,
                    ping_interval=20,
                    ping_timeout=20,
                ) as ws:
                    self._ws = ws
                    logger.info("Connected. Subscribing to new token creations...")
                    await ws.send(json.dumps({"method": "subscribeNewToken"}))

                    # Re-subscribe to any active tokens
                    if self._tracked_mints:
                        active_keys = list(self._tracked_mints.keys())
                        await ws.send(json.dumps({"method": "subscribeTokenTrade", "keys": active_keys}))

                    while self._running:
                        if max_duration_seconds and (time.time() - start_time) >= max_duration_seconds:
                            break
                        msg = await ws.recv()
                        await self._handle_message(msg)

            except Exception as e:
                logger.warning(f"WebSocket connection error: {e}. Reconnecting in 5s...")
                await asyncio.sleep(5.0)

    def stop(self) -> None:
        self._running = False

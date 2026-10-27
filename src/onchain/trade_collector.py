"""
On-Chain Curve Trade Collector (Phase 2A Foundation).
Connects to Solana WebSocket log stream for pump.fun bonding curve program (6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P),
decoding native Anchor TradeEvent records into data/curve_trades.db.

Features:
- Decodes TradeEvent binary logs (mint, user wallet, sol_amount, token_amount, is_buy, timestamp, slot, signature)
- Exponential backoff with jitter on disconnect
- Saves first 50 raw trade messages to data/raw_trade_samples.json for inspection
- Strictly keeps existing databases read-only
"""

import asyncio
import base64
from datetime import datetime, timezone
import hashlib
import json
import logging
import os
from pathlib import Path
import random
import sqlite3
import struct
import time
from typing import Any, Dict, List, Optional, Set

import websockets

from src.utils.ssl_context import get_verified_ssl_context
from src.utils.env_loader import load_env_file

load_env_file()
logger = logging.getLogger("trade_collector")

PUMP_FUN_PROGRAM = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"
TRADE_EVENT_DISCRIMINATOR = hashlib.sha256(b"event:TradeEvent").digest()[:8]  # bddb7fd34ee661ee

B58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def b58encode(b: bytes) -> str:
    n = int.from_bytes(b, "big")
    res = []
    while n > 0:
        n, r = divmod(n, 58)
        res.append(B58_ALPHABET[r])
    pad = 0
    for byte in b:
        if byte == 0:
            pad += 1
        else:
            break
    return "1" * pad + "".join(reversed(res))


class CurveTradeCollector:
    def __init__(
        self,
        db_path: str = "data/curve_trades.db",
        raw_samples_path: str = "data/raw_trade_samples.json",
        max_samples: int = 50,
        initial_backoff: float = 1.0,
        max_backoff: float = 30.0,
        backoff_multiplier: float = 2.0,
    ):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.raw_samples_path = Path(raw_samples_path)
        self.max_samples = max_samples
        self.raw_samples: List[Dict[str, Any]] = []

        self.initial_backoff = initial_backoff
        self.max_backoff = max_backoff
        self.backoff_multiplier = backoff_multiplier

        self._init_db()

        self._running = False
        self._ws: Optional[Any] = None
        self._total_trades_collected = 0
        self._tracked_mints: Set[str] = set()
        self._reconnect_attempts = 0
        self._force_disconnect_requested = False

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
        self._tracked_mints.add(mint)

    def _parse_and_store_trade(self, raw_msg: Dict[str, Any]) -> bool:
        """Parse Anchor TradeEvent from log message."""
        val = raw_msg.get("params", {}).get("result", {}).get("value", {})
        logs = val.get("logs") or []
        sig = val.get("signature")
        slot = raw_msg.get("params", {}).get("result", {}).get("context", {}).get("slot")

        stored_any = False
        for l in logs:
            if "Program data: " in l:
                b64_str = l.split("Program data: ")[1].strip()
                try:
                    raw = base64.b64decode(b64_str)
                    if len(raw) >= 97 and raw[:8] == TRADE_EVENT_DISCRIMINATOR:
                        mint = b58encode(raw[8:40])
                        sol_amt = struct.unpack("<Q", raw[40:48])[0] / 1e9
                        tok_amt = struct.unpack("<Q", raw[48:56])[0] / 1e6
                        is_buy = raw[56] == 1
                        user = b58encode(raw[57:89])
                        ts = struct.unpack("<q", raw[89:97])[0]

                        tx_type = "buy" if is_buy else "sell"

                        self.record_trade(
                            mint=mint,
                            tx_type=tx_type,
                            wallet=user,
                            sol_amount=sol_amt,
                            token_amount=tok_amt,
                            slot=slot,
                            block_time=ts,
                            signature=sig,
                        )
                        stored_any = True

                        if len(self.raw_samples) < self.max_samples:
                            sample = {
                                "signature": sig,
                                "slot": slot,
                                "timestamp": ts,
                                "mint": mint,
                                "wallet": user,
                                "tx_type": tx_type,
                                "sol_amount": sol_amt,
                                "token_amount": tok_amt,
                                "raw_log": l,
                            }
                            self.raw_samples.append(sample)
                            if len(self.raw_samples) == self.max_samples:
                                self._save_raw_samples()
                except Exception as e:
                    logger.debug(f"Failed decoding log chunk: {e}")

        return stored_any

    def _save_raw_samples(self) -> None:
        try:
            self.raw_samples_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.raw_samples_path, "w", encoding="utf-8") as f:
                json.dump(self.raw_samples, f, indent=2)
            logger.info(f"Saved {len(self.raw_samples)} raw trade samples to {self.raw_samples_path}")
        except Exception as e:
            logger.error(f"Error saving raw trade samples: {e}")

    def request_forced_disconnect(self) -> None:
        """Trigger an intentional socket closure for testing reconnection and backoff."""
        self._force_disconnect_requested = True
        if self._ws:
            asyncio.create_task(self._ws.close(code=1000, reason="Forced test disconnect"))

    async def run(
        self,
        max_duration_seconds: Optional[int] = None,
        target_trade_count: Optional[int] = None,
        force_disconnect_after_trades: Optional[int] = None,
    ) -> None:
        """Main trade collection loop with real exponential backoff with jitter."""
        self._running = True
        ssl_ctx = get_verified_ssl_context()
        start_time = time.time()

        ws_url = os.environ.get("SOLANA_WS_URL") or os.environ.get("SOLANA_RPC_URL", "").replace("https://", "wss://")
        if not ws_url:
            raise ValueError("No SOLANA_WS_URL configured in environment.")

        logger.info(f"CurveTradeCollector starting on {ws_url.split('/')[2]}. DB: {self.db_path}")

        while self._running:
            if max_duration_seconds and (time.time() - start_time) >= max_duration_seconds:
                logger.info("Target duration reached. Stopping collector.")
                break

            if target_trade_count and self._total_trades_collected >= target_trade_count:
                logger.info(f"Target trade count ({target_trade_count}) reached. Stopping collector.")
                break

            try:
                logger.info(f"Connecting to Solana WebSocket log stream...")
                async with websockets.connect(
                    ws_url,
                    ssl=ssl_ctx,
                    open_timeout=15,
                    ping_interval=20,
                    ping_timeout=20,
                ) as ws:
                    self._ws = ws
                    self._reconnect_attempts = 0  # Reset backoff on successful connection
                    logger.info("Connected. Subscribing to pump.fun contract logs...")

                    sub_payload = {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "logsSubscribe",
                        "params": [
                            {"mentions": [PUMP_FUN_PROGRAM]},
                            {"commitment": "processed"}
                        ]
                    }
                    await ws.send(json.dumps(sub_payload))
                    resp = await ws.recv()
                    logger.info(f"Subscription confirmed: {resp}")

                    while self._running:
                        if max_duration_seconds and (time.time() - start_time) >= max_duration_seconds:
                            break
                        if target_trade_count and self._total_trades_collected >= target_trade_count:
                            break

                        if force_disconnect_after_trades and self._total_trades_collected >= force_disconnect_after_trades:
                            logger.info("Triggering test forced disconnect...")
                            force_disconnect_after_trades = None  # trigger only once
                            await ws.close(code=1000, reason="Test forced disconnect")
                            break

                        msg = await ws.recv()
                        try:
                            data = json.loads(msg)
                            self._parse_and_store_trade(data)
                        except Exception:
                            pass

            except Exception as e:
                self._reconnect_attempts += 1
                # Exponential backoff with jitter
                delay = min(self.max_backoff, self.initial_backoff * (self.backoff_multiplier ** (self._reconnect_attempts - 1)))
                jitter = random.uniform(0, 0.5 * delay)
                sleep_time = delay + jitter
                logger.warning(
                    f"WebSocket disconnected ({e}). Reconnecting in {sleep_time:.2f}s "
                    f"(attempt {self._reconnect_attempts}, base={delay:.2f}s, jitter={jitter:.2f}s)..."
                )
                await asyncio.sleep(sleep_time)

        self._save_raw_samples()

    def stop(self) -> None:
        self._running = False

"""
On-Chain Curve Trade Collector (Phase 2A Foundation).
Connects to Solana WebSocket log stream for pump.fun bonding curve program (6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P),
decoding native Anchor CreateEvent and TradeEvent (V1 & V2 BuyV2/SellV2) records into data/curve_trades.db.

Features:
- Uses "confirmed" commitment level
- Skips notifications where value.err is not null (tracks skipped_err_count with fast pre-JSON check)
- Takes slot strictly from notification context.slot
- Decodes CreateEvent (1b72a94ddeeb6376) to record mint creation time
- Keeps only trades for mints created since collector start and younger than 30 minutes (1800s)
- Full V1 + V2 (BuyV2/SellV2) TradeEvent decode:
  - Stores quote_mint (Pubkey) and quote_amount (raw integer base units) for all trades
  - Populates sol_lamports and sol_amount ONLY for SOL-quoted trades (NULL for USDC/SPL-quoted V2 trades)
  - Stores token_base_units (raw integer) and UNIQUE(signature, log_index)
- Supports both full-program subscription and smaller subscription (MintAuthority PDA + active <30m bonding curves)
- Tracks WebSocket ingress bytes and messages per second and identifies provider name (without exposing keys)
- Uses SQLite WAL mode and persists state across forced kills/restarts
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
from typing import Any, Dict, List, Optional, Set, Tuple

import websockets

from src.utils.ssl_context import get_verified_ssl_context
from src.utils.env_loader import load_env_file

load_env_file()
logger = logging.getLogger("trade_collector")

PUMP_FUN_PROGRAM = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"
MINT_AUTHORITY_PDA = "TSLvdd1pWpHVjahSpsvCXUbgwsL3JAcvokwaKt1eokM"
WSOL_MINT = "So11111111111111111111111111111111111111112"
USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"

CREATE_EVENT_DISCRIMINATOR = hashlib.sha256(b"event:CreateEvent").digest()[:8]  # 1b72a94ddeeb6376
TRADE_EVENT_DISCRIMINATOR = hashlib.sha256(b"event:TradeEvent").digest()[:8]    # bddb7fd34ee661ee

MAX_MINT_AGE_SECONDS = 1800  # 30 minutes

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


def identify_ws_provider_name(ws_url: str) -> str:
    """Return human-readable provider name from URL without exposing any API key or path token."""
    if not ws_url:
        return "UNKNOWN"
    try:
        host = ws_url.split("/")[2].split("?")[0].lower()
    except IndexError:
        return "UNKNOWN"
    if "helius" in host:
        return "Helius"
    if "quiknode" in host or "quicknode" in host:
        return "QuickNode"
    if "alchemy" in host:
        return "Alchemy"
    if "solana.com" in host:
        return "SolanaPublic"
    return host


class CurveTradeCollector:
    def __init__(
        self,
        db_path: str = "data/curve_trades.db",
        raw_samples_path: str = "data/raw_trade_samples.json",
        max_samples: int = 50,
        max_mint_age_seconds: int = MAX_MINT_AGE_SECONDS,
        initial_backoff: float = 1.0,
        max_backoff: float = 30.0,
        backoff_multiplier: float = 2.0,
        reset_db: bool = False,
        subscription_mode: str = "full",
    ):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.raw_samples_path = Path(raw_samples_path)
        self.max_samples = max_samples
        self.max_mint_age_seconds = max_mint_age_seconds
        self.raw_samples: List[Dict[str, Any]] = []
        self.subscription_mode = subscription_mode

        self.initial_backoff = initial_backoff
        self.max_backoff = max_backoff
        self.backoff_multiplier = backoff_multiplier

        # Runtime counters
        self.skipped_err_count = 0
        self.creations_recorded = 0
        self.total_trades_collected = 0
        self.dropped_untracked_mint_count = 0
        self.dropped_expired_mint_count = 0
        self.duplicate_trades_ignored = 0
        self.total_ws_bytes_received = 0
        self.total_ws_messages_received = 0

        # Active cohort: mint -> creation block_time (unix seconds) and mint -> bonding_curve
        self._mint_creation_times: Dict[str, int] = {}
        self._mint_bonding_curves: Dict[str, str] = {}
        self._subscribed_curves: Set[str] = set()
        self._next_rpc_id = 10

        self._conn: Optional[sqlite3.Connection] = None
        self._init_db(reset_db=reset_db)

        self._running = False
        self._ws: Optional[Any] = None
        self._reconnect_attempts = 0
        self._force_disconnect_requested = False

    def _init_db(self, reset_db: bool = False) -> None:
        """Create WAL-mode SQLite schema and recover active <30m mints if resuming."""
        self._conn = sqlite3.connect(self.db_path, timeout=30.0)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        cur = self._conn.cursor()

        # Check if old schema lacks quote_mint / quote_amount / sol_lamports / log_index
        cur.execute("PRAGMA table_info(curve_trades)")
        cols_info = cur.fetchall()
        cols = {row[1] for row in cols_info}
        sol_lamports_notnull = any(row[1] == "sol_lamports" and row[3] == 1 for row in cols_info)
        if reset_db or (
            cols
            and (
                "quote_mint" not in cols
                or "quote_amount" not in cols
                or "sol_lamports" not in cols
                or "log_index" not in cols
                or sol_lamports_notnull
            )
        ):
            cur.execute("DROP TABLE IF EXISTS curve_trades")
            cur.execute("DROP TABLE IF EXISTS curve_creations")
            cur.execute("DROP TABLE IF EXISTS collector_state")

        cur.execute("""
            CREATE TABLE IF NOT EXISTS curve_creations (
                mint TEXT PRIMARY KEY,
                signature TEXT NOT NULL,
                log_index INTEGER NOT NULL,
                bonding_curve TEXT NOT NULL,
                creator TEXT NOT NULL,
                slot INTEGER NOT NULL,
                created_block_time INTEGER NOT NULL,
                name TEXT,
                symbol TEXT,
                created_at_utc TEXT NOT NULL
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS curve_trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                signature TEXT NOT NULL,
                log_index INTEGER NOT NULL,
                mint TEXT NOT NULL,
                tx_type TEXT NOT NULL,
                wallet TEXT NOT NULL,
                quote_mint TEXT NOT NULL,
                quote_amount INTEGER NOT NULL,
                sol_lamports INTEGER,
                token_base_units INTEGER NOT NULL,
                sol_amount REAL,
                token_amount REAL NOT NULL,
                slot INTEGER NOT NULL,
                block_time INTEGER NOT NULL,
                created_at_utc TEXT NOT NULL,
                UNIQUE(signature, log_index)
            )
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_curve_trades_mint ON curve_trades(mint)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_curve_trades_quote_mint ON curve_trades(quote_mint)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_curve_trades_slot ON curve_trades(slot)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_curve_trades_time ON curve_trades(block_time)")

        cur.execute("""
            CREATE TABLE IF NOT EXISTS collector_state (
                key TEXT PRIMARY KEY,
                value INTEGER NOT NULL
            )
        """)
        self._conn.commit()

        # Recover mints created within the last 30 minutes on restart/resume
        cutoff_ts = int(time.time()) - self.max_mint_age_seconds
        cur.execute(
            "SELECT mint, bonding_curve, created_block_time FROM curve_creations WHERE created_block_time >= ?",
            (cutoff_ts,),
        )
        recovered = cur.fetchall()
        for m_addr, b_curve, c_ts in recovered:
            self._mint_creation_times[m_addr] = int(c_ts)
            self._mint_bonding_curves[m_addr] = b_curve

        cur.execute("SELECT COUNT(*) FROM curve_trades")
        existing_trades = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM curve_creations")
        existing_creations = cur.fetchone()[0]

        if recovered or existing_trades > 0:
            logger.info(
                f"Resumed DB state from {self.db_path}: {existing_trades} existing trades, "
                f"{existing_creations} total creations, {len(recovered)} active mints (<30m old) restored."
            )

    def record_creation(
        self,
        mint: str,
        signature: str,
        log_index: int,
        bonding_curve: str,
        creator: str,
        slot: int,
        created_block_time: int,
        name: str = "",
        symbol: str = "",
    ) -> None:
        """Persist CreateEvent into curve_creations and register active mint."""
        now_utc = datetime.now(timezone.utc).isoformat()
        cur = self._conn.cursor()
        cur.execute("""
            INSERT OR IGNORE INTO curve_creations (
                mint, signature, log_index, bonding_curve, creator,
                slot, created_block_time, name, symbol, created_at_utc
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            mint, signature, log_index, bonding_curve, creator,
            slot, created_block_time, name, symbol, now_utc
        ))
        if cur.rowcount > 0:
            self.creations_recorded += 1
        self._conn.commit()
        self._mint_creation_times[mint] = created_block_time
        self._mint_bonding_curves[mint] = bonding_curve

    def record_trade(
        self,
        signature: str,
        log_index: int,
        mint: str,
        tx_type: str,
        wallet: str,
        quote_mint: str,
        quote_amount: int,
        sol_lamports: Optional[int],
        token_base_units: int,
        slot: int,
        block_time: int,
    ) -> bool:
        """
        Insert trade event into curve_trades.db with UNIQUE(signature, log_index).
        sol_lamports and sol_amount are populated ONLY for SOL-quoted trades (NULL otherwise).
        """
        now_utc = datetime.now(timezone.utc).isoformat()
        sol_amount = (sol_lamports / 1e9) if sol_lamports is not None else None
        token_amount = token_base_units / 1e6
        cur = self._conn.cursor()
        cur.execute("""
            INSERT OR IGNORE INTO curve_trades (
                signature, log_index, mint, tx_type, wallet,
                quote_mint, quote_amount, sol_lamports, token_base_units,
                sol_amount, token_amount, slot, block_time, created_at_utc
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            signature, log_index, mint, tx_type.lower(), wallet,
            quote_mint, quote_amount, sol_lamports, token_base_units,
            sol_amount, token_amount, slot, block_time, now_utc
        ))
        inserted = cur.rowcount > 0
        self._conn.commit()
        if inserted:
            self.total_trades_collected += 1
        else:
            self.duplicate_trades_ignored += 1
        return inserted

    @staticmethod
    def _decode_create_event(raw: bytes) -> Optional[Dict[str, Any]]:
        """Decode Anchor CreateEvent binary payload."""
        if len(raw) < 116 or raw[:8] != CREATE_EVENT_DISCRIMINATOR:
            return None
        try:
            off = 8
            strings = []
            for _ in range(3):  # name, symbol, uri
                if off + 4 > len(raw):
                    return None
                slen = struct.unpack("<I", raw[off:off + 4])[0]
                off += 4
                if slen > 1024 or off + slen > len(raw):
                    return None
                sval = raw[off:off + slen].decode("utf-8", errors="replace")
                strings.append(sval)
                off += slen

            if off + 96 > len(raw):
                return None
            mint = b58encode(raw[off:off + 32])
            bonding_curve = b58encode(raw[off + 32:off + 64])
            user = b58encode(raw[off + 64:off + 96])
            creator = user
            ts = int(time.time())
            if off + 136 <= len(raw):
                creator = b58encode(raw[off + 96:off + 128])
                parsed_ts = struct.unpack("<q", raw[off + 128:off + 136])[0]
                if 1_600_000_000 <= parsed_ts <= 2_500_000_000:
                    ts = parsed_ts

            return {
                "name": strings[0],
                "symbol": strings[1],
                "uri": strings[2],
                "mint": mint,
                "bonding_curve": bonding_curve,
                "user": user,
                "creator": creator,
                "timestamp": ts,
            }
        except Exception:
            return None

    @staticmethod
    def _decode_trade_event(raw: bytes) -> Optional[Dict[str, Any]]:
        """
        Decode Anchor TradeEvent binary payload (V1 and V2 BuyV2/SellV2).
        Layout:
          [0..8]     discriminator (bddb7fd34ee661ee)
          [8..40]    mint (Pubkey)
          [40..48]   sol_amount (u64, 0 for non-SOL V2 curves)
          [48..56]   token_amount (u64, base units)
          [56]       is_buy (bool, u8)
          [57..89]   user (Pubkey)
          [89..97]   timestamp (i64)
          ...
          For V2 events (len(raw) >= 350, last 88 bytes raw[-88:]):
          [-88..-56] quote_mint (Pubkey, 32B)
          [-56..-48] quote_amount (u64, raw base units of quote_mint)
          [-48..-40] virtual_quote_reserves (u64)
          [-40..-32] real_quote_reserves (u64)
          [-32..-24] quote_fee_basis_points (u64)
          [-24..-16] quote_fee (u64)
          [-16..-8]  quote_creator_fee (u64)
          [-8..0]    quote_extra (u64)
        """
        if len(raw) < 97 or raw[:8] != TRADE_EVENT_DISCRIMINATOR:
            return None
        try:
            mint = b58encode(raw[8:40])
            raw_sol_amount = struct.unpack("<Q", raw[40:48])[0]
            token_base_units = struct.unpack("<Q", raw[48:56])[0]
            is_buy = raw[56] == 1
            user = b58encode(raw[57:89])
            ts = struct.unpack("<q", raw[89:97])[0]

            if raw_sol_amount > 0:
                quote_mint = WSOL_MINT
                quote_amount = raw_sol_amount
                sol_lamports: Optional[int] = raw_sol_amount
            elif len(raw) >= 350:
                v2_quote_mint = b58encode(raw[-88:-56])
                v2_quote_amount = struct.unpack("<Q", raw[-56:-48])[0]
                if v2_quote_mint and v2_quote_mint != "11111111111111111111111111111111":
                    quote_mint = v2_quote_mint
                    quote_amount = v2_quote_amount
                else:
                    quote_mint = WSOL_MINT
                    quote_amount = 0
                sol_lamports = quote_amount if quote_mint == WSOL_MINT else None
            else:
                quote_mint = WSOL_MINT
                quote_amount = 0
                sol_lamports = 0

            return {
                "mint": mint,
                "quote_mint": quote_mint,
                "quote_amount": quote_amount,
                "sol_lamports": sol_lamports,
                "token_base_units": token_base_units,
                "is_buy": is_buy,
                "wallet": user,
                "timestamp": ts,
            }
        except Exception:
            return None

    def _parse_and_store_notification(self, raw_msg: Dict[str, Any]) -> Tuple[bool, List[str]]:
        """
        Process a logsNotification message:
        1. Skip if value.err is not None (increment skipped_err_count).
        2. Read slot strictly from context.slot.
        3. Decode CreateEvent and TradeEvent logs with their log_index.
        4. Keep only TradeEvents for mints created since start and younger than 30 minutes.
        Returns (stored_any_trade, newly_created_bonding_curves).
        """
        result_obj = raw_msg.get("params", {}).get("result", {})
        if not result_obj:
            return False, []

        val = result_obj.get("value", {})
        if val.get("err") is not None:
            self.skipped_err_count += 1
            return False, []

        context = result_obj.get("context", {})
        slot = context.get("slot")
        if slot is None:
            return False, []
        slot = int(slot)

        sig = val.get("signature")
        if not sig:
            return False, []

        logs = val.get("logs") or []
        stored_any = False
        new_curves: List[str] = []

        for log_idx, l in enumerate(logs):
            if "Program data: " not in l:
                continue
            b64_str = l.split("Program data: ", 1)[1].strip()
            try:
                raw = base64.b64decode(b64_str)
            except Exception:
                continue

            if len(raw) < 8:
                continue

            disc = raw[:8]
            if disc == CREATE_EVENT_DISCRIMINATOR:
                cev = self._decode_create_event(raw)
                if cev:
                    self.record_creation(
                        mint=cev["mint"],
                        signature=sig,
                        log_index=log_idx,
                        bonding_curve=cev["bonding_curve"],
                        creator=cev["creator"],
                        slot=slot,
                        created_block_time=cev["timestamp"],
                        name=cev["name"],
                        symbol=cev["symbol"],
                    )
                    new_curves.append(cev["bonding_curve"])
            elif disc == TRADE_EVENT_DISCRIMINATOR:
                tev = self._decode_trade_event(raw)
                if not tev:
                    continue

                mint = tev["mint"]
                trade_ts = tev["timestamp"]

                # Check if mint was created since collector start
                created_ts = self._mint_creation_times.get(mint)
                if created_ts is None:
                    self.dropped_untracked_mint_count += 1
                    continue

                # Check if mint is younger than 30 minutes (1800s)
                age_sec = trade_ts - created_ts
                if age_sec > self.max_mint_age_seconds:
                    self.dropped_expired_mint_count += 1
                    continue

                tx_type = "buy" if tev["is_buy"] else "sell"
                sol_lamports = tev["sol_lamports"]
                inserted = self.record_trade(
                    signature=sig,
                    log_index=log_idx,
                    mint=mint,
                    tx_type=tx_type,
                    wallet=tev["wallet"],
                    quote_mint=tev["quote_mint"],
                    quote_amount=tev["quote_amount"],
                    sol_lamports=sol_lamports,
                    token_base_units=tev["token_base_units"],
                    slot=slot,
                    block_time=trade_ts,
                )
                if inserted:
                    stored_any = True
                    if len(self.raw_samples) < self.max_samples:
                        self.raw_samples.append({
                            "signature": sig,
                            "log_index": log_idx,
                            "slot": slot,
                            "timestamp": trade_ts,
                            "mint": mint,
                            "wallet": tev["wallet"],
                            "tx_type": tx_type,
                            "quote_mint": tev["quote_mint"],
                            "quote_amount": tev["quote_amount"],
                            "sol_lamports": sol_lamports,
                            "token_base_units": tev["token_base_units"],
                            "sol_amount": (sol_lamports / 1e9) if sol_lamports is not None else None,
                            "token_amount": tev["token_base_units"] / 1e6,
                            "mint_age_seconds": age_sec,
                            "raw_log": l,
                        })
                        if len(self.raw_samples) == self.max_samples:
                            self._save_raw_samples()

        return stored_any, new_curves

    def _save_raw_samples(self) -> None:
        if not self.raw_samples:
            return
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

    async def _subscribe_bonding_curve(self, ws: Any, bonding_curve: str) -> None:
        if bonding_curve in self._subscribed_curves:
            return
        self._subscribed_curves.add(bonding_curve)
        self._next_rpc_id += 1
        sub_payload = {
            "jsonrpc": "2.0",
            "id": self._next_rpc_id,
            "method": "logsSubscribe",
            "params": [
                {"mentions": [bonding_curve]},
                {"commitment": "confirmed"},
            ],
        }
        await ws.send(json.dumps(sub_payload))

    async def run(
        self,
        max_duration_seconds: Optional[int] = None,
        target_trade_count: Optional[int] = None,
        force_disconnect_after_trades: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Main trade collection loop with confirmed commitment and exponential backoff."""
        self._running = True
        ssl_ctx = get_verified_ssl_context()
        start_time = time.time()

        ws_url = os.environ.get("SOLANA_WS_URL") or os.environ.get("SOLANA_RPC_URL", "").replace("https://", "wss://")
        if not ws_url:
            raise ValueError("No SOLANA_WS_URL configured in environment.")

        provider_name = identify_ws_provider_name(ws_url)
        logger.info(
            f"CurveTradeCollector starting | Provider: {provider_name} | Mode: {self.subscription_mode} | "
            f"Commitment: confirmed | DB: {self.db_path}"
        )

        while self._running:
            if max_duration_seconds and (time.time() - start_time) >= max_duration_seconds:
                logger.info("Target duration reached. Stopping collector.")
                break

            if target_trade_count and self.total_trades_collected >= target_trade_count:
                logger.info(f"Target trade count ({target_trade_count}) reached. Stopping collector.")
                break

            try:
                logger.info(f"Connecting to {provider_name} WebSocket log stream (confirmed, mode={self.subscription_mode})...")
                async with websockets.connect(
                    ws_url,
                    ssl=ssl_ctx,
                    open_timeout=15,
                    ping_interval=20,
                    ping_timeout=20,
                    max_size=4 * 1024 * 1024,
                ) as ws:
                    self._ws = ws
                    self._subscribed_curves.clear()
                    target_pubkey = MINT_AUTHORITY_PDA if self.subscription_mode == "smaller" else PUMP_FUN_PROGRAM
                    sub_payload = {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "logsSubscribe",
                        "params": [
                            {"mentions": [target_pubkey]},
                            {"commitment": "confirmed"},
                        ],
                    }
                    await ws.send(json.dumps(sub_payload))
                    resp = await ws.recv()
                    if isinstance(resp, str):
                        self.total_ws_bytes_received += len(resp.encode("utf-8"))
                    else:
                        self.total_ws_bytes_received += len(resp)
                    self.total_ws_messages_received += 1
                    resp_data = json.loads(resp)
                    if "error" in resp_data:
                        raise RuntimeError(f"logsSubscribe error: {resp_data['error']}")
                    self._reconnect_attempts = 0
                    logger.info(f"Subscription confirmed on {provider_name}: {resp}")

                    # If in smaller subscription mode, subscribe to any recovered active <30m bonding curves
                    if self.subscription_mode == "smaller":
                        now_ts = int(time.time())
                        for m_addr, c_ts in list(self._mint_creation_times.items()):
                            if now_ts - c_ts <= self.max_mint_age_seconds:
                                bc = self._mint_bonding_curves.get(m_addr)
                                if bc:
                                    await self._subscribe_bonding_curve(ws, bc)

                    while self._running:
                        elapsed = time.time() - start_time
                        if max_duration_seconds and elapsed >= max_duration_seconds:
                            break
                        if target_trade_count and self.total_trades_collected >= target_trade_count:
                            break

                        if force_disconnect_after_trades and self.total_trades_collected >= force_disconnect_after_trades:
                            logger.info("Triggering test forced disconnect...")
                            force_disconnect_after_trades = None
                            await ws.close(code=1000, reason="Test forced disconnect")
                            break

                        remaining = (max_duration_seconds - elapsed) if max_duration_seconds else 15.0
                        wait_timeout = max(0.5, min(15.0, remaining))
                        try:
                            msg = await asyncio.wait_for(ws.recv(), timeout=wait_timeout)
                        except asyncio.TimeoutError:
                            continue

                        if isinstance(msg, str):
                            self.total_ws_bytes_received += len(msg.encode("utf-8"))
                        else:
                            self.total_ws_bytes_received += len(msg)
                        self.total_ws_messages_received += 1

                        # Fast pre-JSON check for failed transaction notifications
                        if isinstance(msg, str) and '"logsNotification"' in msg and '"err":null' not in msg:
                            self.skipped_err_count += 1
                            continue

                        try:
                            data = json.loads(msg)
                            _, new_curves = self._parse_and_store_notification(data)
                            if self.subscription_mode == "smaller" and new_curves:
                                for bc in new_curves:
                                    await self._subscribe_bonding_curve(ws, bc)
                        except Exception:
                            pass

            except Exception as e:
                if max_duration_seconds and (time.time() - start_time) >= max_duration_seconds:
                    break
                self._reconnect_attempts += 1
                delay = min(
                    self.max_backoff,
                    self.initial_backoff * (self.backoff_multiplier ** (self._reconnect_attempts - 1)),
                )
                jitter = random.uniform(0, 0.5 * delay)
                sleep_time = delay + jitter
                logger.warning(
                    f"WebSocket disconnected ({type(e).__name__}). Reconnecting in {sleep_time:.2f}s "
                    f"(attempt {self._reconnect_attempts}, base={delay:.2f}s, jitter={jitter:.2f}s)..."
                )
                await asyncio.sleep(sleep_time)

        elapsed_total = max(0.001, time.time() - start_time)
        self._save_raw_samples()
        if self._conn:
            self._conn.commit()

        return {
            "provider_name": provider_name,
            "subscription_mode": self.subscription_mode,
            "commitment": "confirmed",
            "elapsed_seconds": round(elapsed_total, 2),
            "total_ws_bytes_received": self.total_ws_bytes_received,
            "bytes_per_second": round(self.total_ws_bytes_received / elapsed_total, 2),
            "total_ws_messages_received": self.total_ws_messages_received,
            "messages_per_second": round(self.total_ws_messages_received / elapsed_total, 2),
            "skipped_err_count": self.skipped_err_count,
            "failed_notification_pct": round(
                100.0 * self.skipped_err_count / max(1, self.total_ws_messages_received - 1), 2
            ),
            "creations_recorded": self.creations_recorded,
            "trades_stored": self.total_trades_collected,
            "dropped_untracked_mint_count": self.dropped_untracked_mint_count,
            "dropped_expired_mint_count": self.dropped_expired_mint_count,
            "dropped_trades_total": self.dropped_untracked_mint_count + self.dropped_expired_mint_count,
            "duplicate_trades_ignored": self.duplicate_trades_ignored,
        }

    def close(self) -> None:
        self._running = False
        if self._conn:
            try:
                self._conn.commit()
                self._conn.close()
            except Exception:
                pass
            self._conn = None

    def stop(self) -> None:
        self._running = False

"""
Compare side-by-side over 30 seconds (Review Item 2d):
Stream 1 (Full Program):
  logsSubscribe({"mentions": ["6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"]}, {"commitment": "confirmed"})
Stream 2 (Smaller Subscription — MintAuthority + Active Bonding Curves):
  1. Subscribe to MintAuthority PDA ("TSLvdd1pWpHVjahSpsvCXUbgwsL3JAcvokwaKt1eokM") to receive ONLY Create/CreateV2 transactions.
  2. For each newly created mint, dynamically send logsSubscribe({"mentions": [bonding_curve]}, {"commitment": "confirmed"})
     on the same WebSocket connection (and logsUnsubscribe after 30 minutes).
Measure exact notifications, failed notifications, bytes/s, creations captured, and trades captured for new (<30m) mints!
"""

import asyncio
import base64
import json
import os
import sys
import time
import websockets

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from src.utils.env_loader import load_env_file
from src.utils.ssl_context import get_verified_ssl_context
from src.onchain.trade_collector import (
    PUMP_FUN_PROGRAM,
    CREATE_EVENT_DISCRIMINATOR,
    TRADE_EVENT_DISCRIMINATOR,
    CurveTradeCollector,
)

load_env_file()
MINT_AUTHORITY_PDA = "TSLvdd1pWpHVjahSpsvCXUbgwsL3JAcvokwaKt1eokM"


async def run_full_program_stream(ws_url: str, duration: float = 30.0) -> dict:
    ssl_ctx = get_verified_ssl_context()
    msgs_rx = 0
    bytes_rx = 0
    failed_msgs = 0
    creations = set()
    trades_new_mints = set()
    trades_old_mints = 0
    t0 = time.time()

    async with websockets.connect(ws_url, ssl=ssl_ctx, open_timeout=10, max_size=4 * 1024 * 1024) as ws:
        await ws.send(json.dumps({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "logsSubscribe",
            "params": [{"mentions": [PUMP_FUN_PROGRAM]}, {"commitment": "confirmed"}],
        }))
        await ws.recv()
        while time.time() - t0 < duration:
            rem = duration - (time.time() - t0)
            if rem <= 0:
                break
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=min(2.0, rem))
            except asyncio.TimeoutError:
                continue
            b_len = len(msg.encode("utf-8")) if isinstance(msg, str) else len(msg)
            bytes_rx += b_len
            msgs_rx += 1
            data = json.loads(msg)
            val = (data.get("params") or {}).get("result", {}).get("value", {})
            if val.get("err") is not None:
                failed_msgs += 1
                continue
            sig = val.get("signature", "")
            for idx, l in enumerate(val.get("logs") or []):
                if "Program data: " not in l:
                    continue
                try:
                    raw = base64.b64decode(l.split("Program data: ", 1)[1].strip())
                except Exception:
                    continue
                if raw[:8] == CREATE_EVENT_DISCRIMINATOR:
                    cev = CurveTradeCollector._decode_create_event(raw)
                    if cev:
                        creations.add(cev["mint"])
                elif raw[:8] == TRADE_EVENT_DISCRIMINATOR:
                    tev = CurveTradeCollector._decode_trade_event(raw)
                    if tev:
                        if tev["mint"] in creations:
                            trades_new_mints.add((sig, idx))
                        else:
                            trades_old_mints += 1

    elapsed = max(0.001, time.time() - t0)
    return {
        "mode": "full_program_logsSubscribe (6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P)",
        "elapsed_sec": round(elapsed, 2),
        "msgs_rx": msgs_rx,
        "msgs_per_sec": round(msgs_rx / elapsed, 2),
        "bytes_rx": bytes_rx,
        "bytes_per_sec": round(bytes_rx / elapsed, 2),
        "failed_msgs": failed_msgs,
        "failed_pct": round(100.0 * failed_msgs / max(1, msgs_rx), 2),
        "creations_captured": len(creations),
        "new_mint_trades_captured": len(trades_new_mints),
        "old_mint_trades_discarded": trades_old_mints,
        "created_mints": sorted(creations),
    }


async def run_smaller_subscription_stream(ws_url: str, duration: float = 30.0) -> dict:
    ssl_ctx = get_verified_ssl_context()
    msgs_rx = 0
    bytes_rx = 0
    failed_msgs = 0
    creations = set()
    subscribed_curves = set()
    trades_new_mints = set()
    sub_errors = 0
    req_id = 1
    t0 = time.time()

    async with websockets.connect(ws_url, ssl=ssl_ctx, open_timeout=10, max_size=4 * 1024 * 1024) as ws:
        await ws.send(json.dumps({
            "jsonrpc": "2.0",
            "id": req_id,
            "method": "logsSubscribe",
            "params": [{"mentions": [MINT_AUTHORITY_PDA]}, {"commitment": "confirmed"}],
        }))
        await ws.recv()
        while time.time() - t0 < duration:
            rem = duration - (time.time() - t0)
            if rem <= 0:
                break
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=min(2.0, rem))
            except asyncio.TimeoutError:
                continue
            b_len = len(msg.encode("utf-8")) if isinstance(msg, str) else len(msg)
            bytes_rx += b_len
            msgs_rx += 1
            data = json.loads(msg)
            if "error" in data:
                sub_errors += 1
                continue
            if "params" not in data:
                continue
            val = (data.get("params") or {}).get("result", {}).get("value", {})
            if val.get("err") is not None:
                failed_msgs += 1
                continue
            sig = val.get("signature", "")
            for idx, l in enumerate(val.get("logs") or []):
                if "Program data: " not in l:
                    continue
                try:
                    raw = base64.b64decode(l.split("Program data: ", 1)[1].strip())
                except Exception:
                    continue
                if raw[:8] == CREATE_EVENT_DISCRIMINATOR:
                    cev = CurveTradeCollector._decode_create_event(raw)
                    if cev:
                        m = cev["mint"]
                        bc = cev["bonding_curve"]
                        creations.add(m)
                        if bc not in subscribed_curves:
                            subscribed_curves.add(bc)
                            req_id += 1
                            await ws.send(json.dumps({
                                "jsonrpc": "2.0",
                                "id": req_id,
                                "method": "logsSubscribe",
                                "params": [{"mentions": [bc]}, {"commitment": "confirmed"}],
                            }))
                elif raw[:8] == TRADE_EVENT_DISCRIMINATOR:
                    tev = CurveTradeCollector._decode_trade_event(raw)
                    if tev and tev["mint"] in creations:
                        trades_new_mints.add((sig, idx))

    elapsed = max(0.001, time.time() - t0)
    return {
        "mode": "smaller_subscription (MintAuthority TSLvdd1pWpHVjahSpsvCXUbgwsL3JAcvokwaKt1eokM + active bonding_curve logsSubscribe)",
        "elapsed_sec": round(elapsed, 2),
        "msgs_rx": msgs_rx,
        "msgs_per_sec": round(msgs_rx / elapsed, 2),
        "bytes_rx": bytes_rx,
        "bytes_per_sec": round(bytes_rx / elapsed, 2),
        "failed_msgs": failed_msgs,
        "failed_pct": round(100.0 * failed_msgs / max(1, msgs_rx), 2),
        "creations_captured": len(creations),
        "new_mint_trades_captured": len(trades_new_mints),
        "sub_errors": sub_errors,
        "created_mints": sorted(creations),
    }


async def main():
    ws_url = os.environ.get("SOLANA_WS_URL")
    print("Running 30s side-by-side comparison: Full Program vs Smaller Subscription (MintAuthority + Active Curves)...")
    full_res, small_res = await asyncio.gather(
        run_full_program_stream(ws_url, 30.0),
        run_smaller_subscription_stream(ws_url, 30.0),
    )
    bandwidth_reduction_pct = round(100.0 * (1.0 - small_res["bytes_rx"] / max(1, full_res["bytes_rx"])), 2)
    msg_reduction_pct = round(100.0 * (1.0 - small_res["msgs_rx"] / max(1, full_res["msgs_rx"])), 2)
    comparison = {
        "full_program_stream": full_res,
        "smaller_subscription_stream": small_res,
        "bandwidth_reduction_pct": bandwidth_reduction_pct,
        "message_reduction_pct": msg_reduction_pct,
        "creations_match_exact": full_res["created_mints"] == small_res["created_mints"],
    }
    with open("reports/bandwidth_comparison_report.json", "w", encoding="utf-8") as f:
        json.dump(comparison, f, indent=2)
    print(json.dumps(comparison, indent=2))


if __name__ == "__main__":
    asyncio.run(main())

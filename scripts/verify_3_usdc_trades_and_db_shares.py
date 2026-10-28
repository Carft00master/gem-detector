"""
Verify TradeEvent V2 decode (quote_mint, quote_amount) against on-chain token balance changes
for all zero-SOL trades in data/curve_trades.db (including 3 USDC trades) and write
reports/zero_sol_buy_investigation.json directly from the script (Review Item 2a, 2b, 2c & Item 3).
"""

import base64
import json
import os
from pathlib import Path
import sqlite3
import struct
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from src.onchain.provider import SolanaProvider
from src.onchain.trade_collector import TRADE_EVENT_DISCRIMINATOR, b58encode
from scripts.decode_full_trade_event_layout import parse_complete_trade_event
from scripts.generate_route_b_price_paths import get_account_keys, load_fixture

WSOL_MINT = "So11111111111111111111111111111111111111112"
USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"


def fetch_or_load_tx(provider: SolanaProvider, sig: str) -> dict:
    cached = load_fixture(sig)
    if cached and cached.get("meta"):
        return cached
    res = provider.execute_rpc(
        "getTransaction",
        [sig, {"encoding": "json", "commitment": "confirmed", "maxSupportedTransactionVersion": 1}],
    )
    tx = res.get("result")
    if tx:
        out_path = Path(f"data/retrospective_cache/txs/{sig}.json")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(tx, f)
    return tx


def main():
    conn = sqlite3.connect("data/curve_trades.db")
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*), COUNT(DISTINCT mint) FROM curve_trades")
    total_trades, total_mints = cur.fetchone()

    cur.execute("SELECT signature, log_index, mint, tx_type, wallet, sol_lamports, token_base_units, slot, block_time FROM curve_trades WHERE sol_lamports = 0 ORDER BY id ASC")
    zero_rows = cur.fetchall()
    conn.close()

    print(f"Total trades in DB: {total_trades} across {total_mints} mints.")
    print(f"Trades with sol_lamports == 0: {len(zero_rows)}")

    provider = SolanaProvider()

    # Ensure we also include the original 5p58kQ1Q... fixture
    extra_sig = "5p58kQ1QXCgbpQSmjiDH8SKu3Vcwfrahu8Zi9WuDECsqHQSUWcM2UjXGRAaG3S1Vt1iuMvx3V9a92Pe5r7VscXSE"
    all_sigs_to_check = [extra_sig] + [r[0] for r in zero_rows if r[0] != extra_sig]
    # Deduplicate preserving order
    seen = set()
    unique_sigs = []
    for s in all_sigs_to_check:
        if s not in seen:
            seen.add(s)
            unique_sigs.append(s)

    decoded_records = []
    usdc_trades_verified = []

    for sig in unique_sigs:
        tx = fetch_or_load_tx(provider, sig)
        if not tx:
            continue
        meta = tx.get("meta") or {}
        logs = meta.get("logMessages") or []

        # Map token balance deltas by (mint, owner) and by mint
        pre_tb = {(tb.get("accountIndex"), tb.get("mint")): tb for tb in (meta.get("preTokenBalances") or [])}
        post_tb = {(tb.get("accountIndex"), tb.get("mint")): tb for tb in (meta.get("postTokenBalances") or [])}
        all_keys = sorted(set(pre_tb.keys()) | set(post_tb.keys()))

        deltas_by_mint = {}
        for acc_idx, m in all_keys:
            t_pre = pre_tb.get((acc_idx, m), {})
            t_post = post_tb.get((acc_idx, m), {})
            owner = t_post.get("owner") or t_pre.get("owner") or "?"
            raw_pre = int((t_pre.get("uiTokenAmount") or {}).get("amount") or 0)
            raw_post = int((t_post.get("uiTokenAmount") or {}).get("amount") or 0)
            dec_places = (t_post.get("uiTokenAmount") or t_pre.get("uiTokenAmount") or {}).get("decimals", 6)
            d_raw = raw_post - raw_pre
            if d_raw != 0:
                deltas_by_mint.setdefault(m, []).append({
                    "accountIndex": acc_idx,
                    "owner": owner,
                    "pre_raw": raw_pre,
                    "post_raw": raw_post,
                    "delta_raw": d_raw,
                    "decimals": dec_places,
                    "delta_ui": round(d_raw / (10 ** dec_places), 6),
                })

        for l_idx, line in enumerate(logs):
            if "Program data:" in line:
                try:
                    raw = base64.b64decode(line.split("Program data:")[-1].strip())
                except Exception:
                    continue
                if raw[:8] == TRADE_EVENT_DISCRIMINATOR and len(raw) >= 350:
                    dec = parse_complete_trade_event(raw)
                    if dec["sol_amount"] == 0:
                        qm = dec["quote_mint"]
                        qa = dec["quote_amount"]
                        qf = dec["quote_fee"]
                        qcf = dec["quote_creator_fee"]
                        tm = dec["mint"]
                        ta = dec["token_amount"]

                        q_deltas = deltas_by_mint.get(qm, [])
                        t_deltas = deltas_by_mint.get(tm, [])

                        rec = {
                            "signature": sig,
                            "slot": tx.get("slot"),
                            "err": meta.get("err"),
                            "log_index": l_idx,
                            "decoded_trade_event": dec,
                            "quote_mint_balance_deltas": q_deltas,
                            "base_mint_balance_deltas": t_deltas,
                        }
                        decoded_records.append(rec)
                        if qm == USDC_MINT:
                            usdc_trades_verified.append(rec)

    print("\n" + "=" * 135)
    print(f"DECODED ZERO-SOL TRADEEVENTS ACROSS {len(unique_sigs)} TRANSACTIONS ({len(decoded_records)} events total, {len(usdc_trades_verified)} USDC-quoted):")
    print("=" * 135)
    for i, r in enumerate(decoded_records, 1):
        d = r["decoded_trade_event"]
        qm = d["quote_mint"]
        qm_label = "USDC" if qm == USDC_MINT else f"TOKEN({qm[:8]}..)"
        q_deltas = r["quote_mint_balance_deltas"]
        t_deltas = r["base_mint_balance_deltas"]
        print(
            f"{i:2d} | sig={r['signature'][:24]}.. | slot={r['slot']} | {'BUY' if d['is_buy'] else 'SELL':<4} | "
            f"mint={d['mint']} | tok_raw={d['token_amount']:16d} | quote={qm_label:<16} | "
            f"quote_amt_raw={d['quote_amount']:14d} | quote_fee={d['quote_fee']:10d} | v_quote={d['virtual_quote_reserves']:15d}"
        )
        for qd in q_deltas:
            print(f"     [Quote Balance Delta] owner={qd['owner']:<44} | pre={qd['pre_raw']:15d} | post={qd['post_raw']:15d} | delta={qd['delta_raw']:+16d} ({qd['delta_ui']:+14.6f})")
        for td in t_deltas:
            print(f"     [Token Balance Delta] owner={td['owner']:<44} | pre={td['pre_raw']:15d} | post={td['post_raw']:15d} | delta={td['delta_raw']:+16d} ({td['delta_ui']:+14.6f})")

    out_report = {
        "total_trades_in_db": total_trades,
        "total_mints_in_db": total_mints,
        "zero_sol_trades_in_db": len(zero_rows),
        "decoded_zero_sol_events": decoded_records,
        "usdc_trades_verified": usdc_trades_verified,
    }
    with open("reports/zero_sol_buy_investigation.json", "w", encoding="utf-8") as f:
        json.dump(out_report, f, indent=2)
    print("\nSaved reports/zero_sol_buy_investigation.json directly from script.")


if __name__ == "__main__":
    main()

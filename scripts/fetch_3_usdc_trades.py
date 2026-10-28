"""
Fetch 2 additional USDC-quoted transactions on bonding curve CYUvJgUZxnHJiPXHH8Gm9RkrHf58uMDz98EbUaJwdDTo
(mint 3XLdvSS6iEXm7eZqMauQim9uBdsPnPSEuc7Pguojpump) via SolanaProvider.execute_rpc so we have
3 distinct USDC-quoted (EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v) TradeEvents verified against
on-chain token balance changes (Review Item 2c), plus 3 SPL-token-quoted TradeEvents from data/curve_trades.db!
"""

import base64
import json
import os
from pathlib import Path
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from src.onchain.provider import SolanaProvider
from src.onchain.trade_collector import TRADE_EVENT_DISCRIMINATOR
from scripts.decode_full_trade_event_layout import parse_complete_trade_event
from scripts.verify_3_usdc_trades_and_db_shares import USDC_MINT, fetch_or_load_tx


def main():
    provider = SolanaProvider()
    curve_addr = "CYUvJgUZxnHJiPXHH8Gm9RkrHf58uMDz98EbUaJwdDTo"
    res = provider.execute_rpc("getSignaturesForAddress", [curve_addr, {"limit": 15}])
    sigs_info = res.get("result") or []
    print(f"Found {len(sigs_info)} signatures on USDC bonding curve {curve_addr}.")

    usdc_verified = []
    for s_obj in sigs_info:
        if s_obj.get("err") is not None:
            continue
        sig = s_obj["signature"]
        tx = fetch_or_load_tx(provider, sig)
        if not tx:
            continue
        meta = tx.get("meta") or {}
        logs = meta.get("logMessages") or []

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
                    if dec["quote_mint"] == USDC_MINT:
                        usdc_verified.append({
                            "signature": sig,
                            "slot": tx.get("slot"),
                            "log_index": l_idx,
                            "decoded_trade_event": dec,
                            "quote_mint_balance_deltas": deltas_by_mint.get(USDC_MINT, []),
                            "base_mint_balance_deltas": deltas_by_mint.get(dec["mint"], []),
                        })
        if len(usdc_verified) >= 4:
            break

    print("=" * 130)
    print(f"VERIFIED {len(usdc_verified)} DISTINCT USDC-QUOTED (EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v) TRADES:")
    print("=" * 130)
    for i, u in enumerate(usdc_verified, 1):
        d = u["decoded_trade_event"]
        print(f"\nUSDC Trade #{i}: sig={u['signature']} | slot={u['slot']} | side={'BUY' if d['is_buy'] else 'SELL'}")
        print(f"  user={d['user']} | mint={d['mint']}")
        print(f"  Decoded TradeEvent: token_amount={d['token_amount']} ({d['token_amount']/1e6:.6f}) | quote_amount={d['quote_amount']} ({d['quote_amount']/1e6:.6f} USDC) | quote_fee={d['quote_fee']} | quote_creator_fee={d['quote_creator_fee']}")
        print(f"  Decoded Virtual/Real Reserves: v_quote={d['virtual_quote_reserves']} ({d['virtual_quote_reserves']/1e6:.6f} USDC) | r_quote={d['real_quote_reserves']} ({d['real_quote_reserves']/1e6:.6f} USDC) | v_tok={d['v_tok']/1e6:.6f}")
        for qd in u["quote_mint_balance_deltas"]:
            print(f"  On-Chain USDC Delta: owner={qd['owner']} | pre={qd['pre_raw']} | post={qd['post_raw']} | delta_raw={qd['delta_raw']:+d} ({qd['delta_ui']:+.6f} USDC)")
        for td in u["base_mint_balance_deltas"]:
            print(f"  On-Chain Token Delta: owner={td['owner']} | pre={td['pre_raw']} | post={td['post_raw']} | delta_raw={td['delta_raw']:+d} ({td['delta_ui']:+.6f} tokens)")

    # Update reports/zero_sol_buy_investigation.json with these 3+ USDC trades
    with open("reports/zero_sol_buy_investigation.json", "r", encoding="utf-8") as f:
        rep = json.load(f)
    rep["usdc_trades_verified"] = usdc_verified
    with open("reports/zero_sol_buy_investigation.json", "w", encoding="utf-8") as f:
        json.dump(rep, f, indent=2)
    print("\nSaved 3+ verified USDC trades to reports/zero_sol_buy_investigation.json.")


if __name__ == "__main__":
    main()

"""
Decode the COMPLETE Pump.fun TradeEvent struct (all bytes from 0 to len(raw))
for TX #1, TX #2, TX #3 and verify every field against the transaction's token/SOL balance deltas!
"""

import base64
import json
import struct
from src.onchain.trade_collector import TRADE_EVENT_DISCRIMINATOR, b58encode
from scripts.generate_route_b_price_paths import get_account_keys, load_fixture


def parse_complete_trade_event(raw: bytes) -> dict:
    """
    Complete Anchor TradeEvent layout on Pump.fun (6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P):
      0..8   : discriminator (bddb7fd34ee661ee)
      8..40  : mint (Pubkey, 32B)
      40..48 : sol_amount (u64, 8B) - populated for SOL-quoted curves, 0 for token/USDC-quoted curves
      48..56 : token_amount (u64, 8B)
      56..57 : is_buy (bool, 1B)
      57..89 : user (Pubkey, 32B)
      89..97 : timestamp (i64, 8B)
      97..105: virtual_sol_reserves (u64, 8B)
      105..113: virtual_token_reserves (u64, 8B)
      113..121: real_sol_reserves (u64, 8B)
      121..129: real_token_reserves (u64, 8B)
      129..161: fee_recipient (Pubkey, 32B)
      161..169: fee_basis_points (u64, 8B)
      169..177: fee (u64, 8B)
      177..209: creator (Pubkey, 32B)
      209..217: creator_fee_basis_points (u64, 8B)
      217..225: creator_fee (u64, 8B)
      225..226: track_volume (bool, 1B)
      226..234: total_unclaimed_tokens (u64, 8B)
      234..242: total_claimed_tokens (u64, 8B)
      242..250: current_sol_volume (u64, 8B)
      250..258: last_update_timestamp (i64, 8B)
      258..262: ix_name_len (u32, 4B)
      262..262+L: ix_name (utf-8 string, L bytes)
      --- Tail after ix_name (for V2 / quote-mint aware events, 125 bytes = len(raw) - (262+L)): ---
      Let's inspect the exact bytes from 262+L to len(raw) (and from len(raw)-88 to len(raw))!
    """
    mint = b58encode(raw[8:40])
    sol_amount = struct.unpack_from("<Q", raw, 40)[0]
    token_amount = struct.unpack_from("<Q", raw, 48)[0]
    is_buy = bool(raw[56])
    user = b58encode(raw[57:89])
    timestamp = struct.unpack_from("<q", raw, 89)[0]
    v_sol = struct.unpack_from("<Q", raw, 97)[0]
    v_tok = struct.unpack_from("<Q", raw, 105)[0]
    r_sol = struct.unpack_from("<Q", raw, 113)[0]
    r_tok = struct.unpack_from("<Q", raw, 121)[0]

    # Locate ix_name string around offset 258..270
    # Wait: let's also check from the end of `raw`!
    # In TX #3 (len=401):
    #   313..345 (len-88 .. len-56): quote_mint (32B)
    #   345..353 (len-56 .. len-48): quote_amount (u64, 8B)
    #   353..361 (len-48 .. len-40): virtual_quote_reserves (u64, 8B)
    #   361..369 (len-40 .. len-32): real_quote_reserves (u64, 8B)
    #   369..377 (len-32 .. len-24): fee_basis_points_v2 (u64, 8B)
    #   377..385 (len-24 .. len-16): quote_fee (u64, 8B)
    #   385..393 (len-16 .. len-8) : quote_creator_fee (u64, 8B)
    #   393..401 (len-8  .. len)   :cashback / protocol fee (u64, 8B)
    tail_offset = len(raw) - 88
    quote_mint = b58encode(raw[tail_offset:tail_offset + 32])
    quote_amount = struct.unpack_from("<Q", raw, tail_offset + 32)[0]
    v_quote = struct.unpack_from("<Q", raw, tail_offset + 40)[0]
    r_quote = struct.unpack_from("<Q", raw, tail_offset + 48)[0]
    q_fee_bps = struct.unpack_from("<Q", raw, tail_offset + 56)[0]
    q_fee = struct.unpack_from("<Q", raw, tail_offset + 64)[0]
    q_creator_fee = struct.unpack_from("<Q", raw, tail_offset + 72)[0]
    q_extra = struct.unpack_from("<Q", raw, tail_offset + 80)[0]

    return {
        "len": len(raw),
        "mint": mint,
        "sol_amount": sol_amount,
        "token_amount": token_amount,
        "is_buy": is_buy,
        "user": user,
        "timestamp": timestamp,
        "v_sol": v_sol,
        "v_tok": v_tok,
        "r_sol": r_sol,
        "r_tok": r_tok,
        "quote_mint": quote_mint,
        "quote_amount": quote_amount,
        "virtual_quote_reserves": v_quote,
        "real_quote_reserves": r_quote,
        "quote_fee_bps": q_fee_bps,
        "quote_fee": q_fee,
        "quote_creator_fee": q_creator_fee,
        "quote_extra": q_extra,
    }


def main():
    sigs = [
        "5p58kQ1QXCgbpQSmjiDH8SKu3Vcwfrahu8Zi9WuDECsqHQSUWcM2UjXGRAaG3S1Vt1iuMvx3V9a92Pe5r7VscXSE",
        "4X4afrdKGoJ2sffQMfrN91kEkXL2hXLK4c3v7UceMZRGeAbXBeAQ7v9C7B7Sny5XHy7r6R13bJ7fDdfX7bH8wG4p",
        "2dDUi2D7UFrm5aM3hRhN2oWRjqg1hGCWdkKH3H6aFo34xJZqciHjF8DkQt9zeJUgWBVoX1Cc4uM3jKxHsEHZsv7k",
    ]
    # Let's get the exact 3 sigs that investigate_v2_trades.py used
    import sqlite3
    conn = sqlite3.connect("data/curve_trades.db")
    cur = conn.cursor()
    cur.execute("SELECT DISTINCT signature FROM curve_trades WHERE sol_lamports = 0 LIMIT 5")
    db_sigs = [r[0] for r in cur.fetchall()]
    conn.close()
    target_sigs = ["5p58kQ1QXCgbpQSmjiDH8SKu3Vcwfrahu8Zi9WuDECsqHQSUWcM2UjXGRAaG3S1Vt1iuMvx3V9a92Pe5r7VscXSE"]
    for s in db_sigs:
        if s not in target_sigs and len(target_sigs) < 3:
            target_sigs.append(s)

    for idx, sig in enumerate(target_sigs, 1):
        tx = load_fixture(sig)
        meta = tx.get("meta") or {}
        keys = get_account_keys(tx)
        print("=" * 130)
        print(f"TX #{idx}: {sig}")
        for l_idx, line in enumerate(meta.get("logMessages") or []):
            if "Program data:" in line:
                raw = base64.b64decode(line.split("Program data:")[-1].strip())
                if raw[:8] == TRADE_EVENT_DISCRIMINATOR:
                    dec = parse_complete_trade_event(raw)
                    print(f"  Decoded TradeEvent (log[{l_idx}], len={dec['len']}):")
                    for k, v in dec.items():
                        print(f"    {k:<24}: {v}")

        # Compare against token balance deltas for quote_mint and mint!
        pre_tb = {(tb.get("accountIndex"), tb.get("mint")): tb for tb in (meta.get("preTokenBalances") or [])}
        post_tb = {(tb.get("accountIndex"), tb.get("mint")): tb for tb in (meta.get("postTokenBalances") or [])}
        all_tb_keys = sorted(set(pre_tb.keys()) | set(post_tb.keys()))
        print("  Token Balance Changes in Transaction:")
        for acc_idx, m in all_tb_keys:
            t_pre = pre_tb.get((acc_idx, m), {})
            t_post = post_tb.get((acc_idx, m), {})
            owner = t_post.get("owner") or t_pre.get("owner") or "?"
            raw_pre = int((t_pre.get("uiTokenAmount") or {}).get("amount") or 0)
            raw_post = int((t_post.get("uiTokenAmount") or {}).get("amount") or 0)
            dec_places = (t_post.get("uiTokenAmount") or t_pre.get("uiTokenAmount") or {}).get("decimals", 6)
            delta_raw = raw_post - raw_pre
            if delta_raw != 0:
                print(f"    owner={owner:<44} | mint={m:<44} | dec={dec_places} | delta_raw={delta_raw:+18d} ({delta_raw/(10**dec_places):+16.6f})")


if __name__ == "__main__":
    main()

import base64
import glob
import json
import os
import struct
import sys

repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if repo_root not in sys.path:
    sys.path.insert(0, repo_root)

POOLS = {
    "BNchF8GCxGKxsWbpkUE5D8RhGfB31QGT7DbAvMPY7RiV": ("qTFyfJiSQhMooT6LzybsWHjMXSGWsdkY3w8C9aXpump", 17.584010),
    "3uj1sQuyiwEzAXzN6FSXSGuzshmmkxoce5HLTeNrgvZb": ("125PmQ6TXqisrhdi2cTH9RL2za6EXGPYBqPX1E5Bpump", 17.583118),
    "3H1kDaJpr7twTSG2nWeSzcpa2FApAkN5DQkTuNB3bNxS": ("ocjMSsFzMf4anB91fVdHv1MDWoqZjkM48rGsx75pump", 17.584505),
    "6gSkeaNuTVyZ7CiCViVJZ99EVVyMvQxGL8LQ49QefjdN": ("GpACuhDe83JHRRhyNGm8zovfW1a9SrWdsCNVbLXTQ4GU", 17.583496),
    "Fj2LCUkacJzQosMBZHMVLrQ6bZmqn5CZTVTR2DUTns5H": ("4VXNQUEVq5BPHWAnKDrBN6zqqumKDVy6mYjvBtLipump", 17.584341),
    "FuxU8Uph4kSy6hTKkxXXzD1JF2xoYgkrgwu5B4FjfXoq": ("DPr39FjXbdf83rZzmephqjmyzM552782cUh2vTSXpump", 17.584492),
}

all_replays = []
for pool_addr, (mint, boost_sol) in POOLS.items():
    for f in sorted(glob.glob("tests/fixtures/txs/*.json")):
        sig = os.path.basename(f).replace(".json", "")
        with open(f, encoding="utf-8") as tf:
            tx_obj = json.load(tf)
        meta = tx_obj.get("meta") or {}
        if meta.get("err") is not None:
            continue
        pre_tb = meta.get("preTokenBalances") or []
        post_tb = meta.get("postTokenBalances") or []

        sol_pre, sol_post = None, None
        tok_pre, tok_post = None, None

        for b in pre_tb:
            if b.get("owner") == pool_addr:
                if b.get("mint") == "So11111111111111111111111111111111111111112":
                    sol_pre = float(b.get("uiTokenAmount", {}).get("uiAmount") or 0.0)
                elif b.get("mint") == mint:
                    tok_pre = float(b.get("uiTokenAmount", {}).get("uiAmount") or 0.0)

        for b in post_tb:
            if b.get("owner") == pool_addr:
                if b.get("mint") == "So11111111111111111111111111111111111111112":
                    sol_post = float(b.get("uiTokenAmount", {}).get("uiAmount") or 0.0)
                elif b.get("mint") == mint:
                    tok_post = float(b.get("uiTokenAmount", {}).get("uiAmount") or 0.0)

        if sol_pre is not None and sol_post is not None and tok_pre is not None and tok_post is not None:
            sol_diff = sol_post - sol_pre
            tok_diff = tok_post - tok_pre
            if abs(sol_diff) > 0.0001 and abs(tok_diff) > 0.1:
                lp_bps, proto_bps, creator_bps = 20.0, 5.0, 25.0
                for l in meta.get("logMessages", []):
                    if "Program return: pfee" in l:
                        b64 = l.split()[-1]
                        vals = struct.unpack("<QQQ", base64.b64decode(b64))
                        lp_bps, proto_bps, creator_bps = float(vals[0]), float(vals[1]), float(vals[2])
                        break

                if sol_diff > 0 and tok_diff < 0:
                    side = "BUY"
                    actual_tokens_out = abs(tok_diff)
                    E_a = sol_diff / (1.0 + lp_bps / 10000.0)
                    pred_tokens_a = tok_pre * E_a / (sol_pre + E_a)
                    err_a = abs(pred_tokens_a - actual_tokens_out) / actual_tokens_out * 100.0

                    eff_sol_pre = sol_pre + boost_sol
                    pred_tokens_b = tok_pre * E_a / (eff_sol_pre + E_a)
                    err_b = abs(pred_tokens_b - actual_tokens_out) / actual_tokens_out * 100.0

                elif sol_diff < 0 and tok_diff > 0:
                    side = "SELL"
                    tokens_in = tok_diff
                    actual_sol_withdrawn = abs(sol_diff)
                    actual_E = actual_sol_withdrawn / (1.0 - lp_bps / 10000.0)

                    pred_E_a = sol_pre * tokens_in / (tok_pre + tokens_in)
                    err_a = abs(pred_E_a - actual_E) / actual_E * 100.0

                    eff_sol_pre = sol_pre + boost_sol
                    pred_E_b = eff_sol_pre * tokens_in / (tok_pre + tokens_in)
                    err_b = abs(pred_E_b - actual_E) / actual_E * 100.0
                else:
                    continue

                all_replays.append({
                    "pool": pool_addr,
                    "sig": sig,
                    "slot": tx_obj.get("slot"),
                    "side": side,
                    "sol_pre": sol_pre,
                    "tok_pre": tok_pre,
                    "boost": boost_sol,
                    "sol_diff": sol_diff,
                    "tok_diff": tok_diff,
                    "err_vault_only_pct": err_a,
                    "err_vault_plus_boost_pct": err_b,
                })

print(f"\nTotal Swaps Replayed: {len(all_replays)}")
print("=" * 110)
print(f"{'POOL':<12} | {'SIG':<14} | {'SIDE':<4} | {'PRE-SOL':<10} | {'PRE-TOKENS':<14} | {'ERR (VAULT ONLY)':<18} | {'ERR (VAULT+BOOST)':<18}")
print("-" * 110)
for r in all_replays[:25]:
    print(f"{r['pool'][:12]} | {r['sig'][:14]} | {r['side']:<4} | {r['sol_pre']:<10.4f} | {r['tok_pre']:<14.1f} | {r['err_vault_only_pct']:<17.4f}% | {r['err_vault_plus_boost_pct']:<17.4f}%")
print("=" * 110)

avg_err_a = sum(r['err_vault_only_pct'] for r in all_replays) / max(1, len(all_replays))
avg_err_b = sum(r['err_vault_plus_boost_pct'] for r in all_replays) / max(1, len(all_replays))
print(f"Summary over {len(all_replays)} swaps across {len(set(r['pool'] for r in all_replays))} pools:")
print(f"  Mean Absolute Prediction Error (Vault Only):       {avg_err_a:.4f}%")
print(f"  Mean Absolute Prediction Error (Vault + Boost):    {avg_err_b:.4f}%")

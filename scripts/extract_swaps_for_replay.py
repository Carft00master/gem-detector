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

pool_swaps = {}
for pool_addr, (mint, boost_sol) in POOLS.items():
    swaps = []
    for f in sorted(glob.glob("tests/fixtures/txs/*.json")):
        sig = os.path.basename(f).replace(".json", "")
        with open(f, encoding="utf-8") as tf:
            tx_obj = json.load(tf)
        meta = tx_obj.get("meta") or {}
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
                fee_lp, fee_proto, fee_creator = 20, 5, 25
                for l in meta.get("logMessages", []):
                    if "Program return: pfee" in l:
                        b64 = l.split()[-1]
                        vals = struct.unpack("<QQQ", base64.b64decode(b64))
                        fee_lp, fee_proto, fee_creator = vals[0], vals[1], vals[2]
                        break

                swaps.append({
                    "sig": sig,
                    "slot": tx_obj.get("slot"),
                    "sol_pre": sol_pre,
                    "sol_post": sol_post,
                    "tok_pre": tok_pre,
                    "tok_post": tok_post,
                    "sol_diff": sol_diff,
                    "tok_diff": tok_diff,
                    "fee_bps": (fee_lp, fee_proto, fee_creator),
                    "boost": boost_sol
                })

    pool_swaps[pool_addr] = swaps
    print(f"Pool {pool_addr[:12]}...: extracted {len(swaps)} swaps")

os.makedirs("scratch", exist_ok=True)
with open("scratch/replay_swaps_data.json", "w", encoding="utf-8") as f:
    json.dump(pool_swaps, f, indent=2)
print("Saved replay swaps data to scratch/replay_swaps_data.json")

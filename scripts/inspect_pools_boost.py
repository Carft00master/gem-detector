from src.onchain.provider import SolanaProvider
import base64
import json
import os
import struct
import sys
import sqlite3

repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if repo_root not in sys.path:
    sys.path.insert(0, repo_root)

from src.utils.env_loader import load_env_file
from src.utils.ssl_context import get_verified_ssl_context
from src.onchain.provider import ProviderConfig, mask_endpoint_url

load_env_file()
cfg = ProviderConfig()
ssl_ctx = get_verified_ssl_context()
url = cfg.rpc_urls[0]

_solana_provider = None
def get_provider():
    global _solana_provider
    if _solana_provider is None:
        _solana_provider = SolanaProvider()
    return _solana_provider

def rpc_call(method, params):
    res = get_provider().execute_rpc(method, params)
    if 'error' in res:
        raise RuntimeError(res['error'])
    return res.get('result')



# 1. Read migrations from onchain_events.db read-only
uri = "file:data/onchain_events.db?mode=ro"
con = sqlite3.connect(uri, uri=True)
cur = con.cursor()
rows = cur.execute("SELECT mint, signature, pool_address, slot FROM onchain_events WHERE event_type='migration'").fetchall()
con.close()

print(f"Loaded {len(rows)} migrations from data/onchain_events.db")

# Let's inspect multiple migrations
pools_found = []
for mint, sig, pool_label, slot in rows:
    print(f"\nChecking migration: mint={mint} sig={sig[:16]}... slot={slot}")
    # Check if cached or fetch
    cache_file = f"scratch/audit_cache/txs/{sig}.json"
    tx_data = None
    if os.path.exists(cache_file):
        with open(cache_file, "r") as f:
            tx_data = json.load(f)
    else:
        try:
            tx_data = rpc_call("getTransaction", [sig, {"encoding": "json", "maxSupportedTransactionVersion": 0}])
            if tx_data:
                with open(cache_file, "w") as f:
                    json.dump(tx_data, f)
        except Exception as e:
            print(f"  Error fetching mig tx: {e}")
            continue

    if not tx_data:
        continue

    meta = tx_data.get("meta", {})
    post_tb = meta.get("postTokenBalances", [])
    
    # Identify pool accounts
    pool_cand = None
    wsol_vault = None
    token_vault = None
    boost_vault = None
    boost_amount = None

    for tb in post_tb:
        m = tb.get("mint")
        owner = tb.get("owner")
        amt = tb.get("uiTokenAmount", {}).get("uiAmount") or 0.0
        # If mint is token and amt ~ 206.9M
        if m == mint and amt > 100_000_000:
            pool_cand = owner
            token_vault = tb.get("accountIndex")
    
    for tb in post_tb:
        m = tb.get("mint")
        owner = tb.get("owner")
        amt = tb.get("uiTokenAmount", {}).get("uiAmount") or 0.0
        if m == "So11111111111111111111111111111111111111112":
            if owner == pool_cand:
                wsol_vault = tb.get("accountIndex")
                base_sol = amt
            elif 10.0 <= amt <= 30.0:
                boost_vault = tb.get("accountIndex")
                boost_amount = amt

    if pool_cand:
        print(f"  -> Discovered Pool: {pool_cand}")
        print(f"     Base WSOL in pool: {base_sol if 'base_sol' in locals() else 'N/A'}")
        print(f"     Boost amount: {boost_amount}")
        pools_found.append({
            "mint": mint,
            "pool": pool_cand,
            "mig_sig": sig,
            "mig_slot": slot,
            "boost": boost_amount
        })
        if len(pools_found) >= 8:
            break

print(f"\nDiscovered {len(pools_found)} candidate pools.")

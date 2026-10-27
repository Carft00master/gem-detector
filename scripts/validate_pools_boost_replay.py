from src.onchain.provider import SolanaProvider
import base64
import json
import math
import os
import struct
import sys
import sqlite3

repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if repo_root not in sys.path:
    sys.path.insert(0, repo_root)

from src.utils.env_loader import load_env_file
from src.utils.ssl_context import get_verified_ssl_context
from src.onchain.provider import ProviderConfig

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



# 1. Fetch 35 migrations
uri = "file:data/onchain_events.db?mode=ro"
con = sqlite3.connect(uri, uri=True)
cur = con.cursor()
migrations = cur.execute("SELECT mint, signature, pool_address, slot FROM onchain_events WHERE event_type='MIGRATION'").fetchall()
con.close()

print(f"Total migrations in database: {len(migrations)}")

# Also include NODF positive control
nodf_mint = "qTFyfJiSQhMooT6LzybsWHjMXSGWsdkY3w8C9aXpump"
nodf_sig = "3LXpRAvn5DNvVV1aP7e3Euw7Kbmxpq5xycyQkfHmJneVyjtFjKwsPh6c9JuckKQhuGG3TwFNfZ411ARiZoSpkbGQ"
nodf_pool = "BNchF8GCxGKxsWbpkUE5D8RhGfB31QGT7DbAvMPY7RiV"
all_targets = [("NODF", nodf_mint, nodf_sig, nodf_pool, 456718840)] + [(f"Mig_{i}", m[0], m[1], m[2], m[3]) for i, m in enumerate(migrations)]

pools_analyzed = []

for label, mint, sig, initial_pool, mig_slot in all_targets:
    tx_cache = f"scratch/audit_cache/txs/{sig}.json"
    if os.path.exists(tx_cache):
        with open(tx_cache, "r") as f:
            mig_tx = json.load(f)
    else:
        try:
            mig_tx = rpc_call("getTransaction", [sig, {"encoding": "json", "maxSupportedTransactionVersion": 0}])
            if mig_tx:
                with open(tx_cache, "w") as f:
                    json.dump(mig_tx, f)
        except Exception as e:
            continue

    if not mig_tx:
        continue

    meta = mig_tx.get("meta", {})
    post_tb = meta.get("postTokenBalances", [])
    
    # Derive real pool address
    pool_address = initial_pool if initial_pool and initial_pool != "pump-amm" else None
    token_vault_idx = None
    wsol_vault_idx = None
    boost_vault_idx = None
    boost_deposit_sol = None
    wsol_deposit_sol = None

    if not pool_address:
        # Find token balance with ~206.9M tokens
        for tb in post_tb:
            if tb.get("mint") == mint:
                amt = tb.get("uiTokenAmount", {}).get("uiAmount") or 0.0
                if amt > 100_000_000:
                    pool_address = tb.get("owner")
                    token_vault_idx = tb.get("accountIndex")
                    break

    if not pool_address:
        continue

    # Find pool token balances
    for tb in post_tb:
        m = tb.get("mint")
        owner = tb.get("owner")
        amt = tb.get("uiTokenAmount", {}).get("uiAmount") or 0.0
        if owner == pool_address:
            if m == "So11111111111111111111111111111111111111112":
                wsol_deposit_sol = amt
            elif m == mint:
                token_deposit = amt
        elif m == "So11111111111111111111111111111111111111112" and (10.0 <= amt <= 30.0):
            boost_deposit_sol = amt

    # Check pool account data via RPC or cache
    pool_acc_cache = f"scratch/audit_cache/pool_accs/{pool_address}.json"
    pool_acc_data = None
    if os.path.exists(pool_acc_cache):
        with open(pool_acc_cache, "r") as f:
            pool_acc_data = json.load(f)
    else:
        try:
            pool_acc_data = rpc_call("getAccountInfo", [pool_address, {"encoding": "base64"}])
            if pool_acc_data:
                with open(pool_acc_cache, "w") as f:
                    json.dump(pool_acc_data, f)
        except Exception as e:
            pass

    boost_stored_sol = None
    if pool_acc_data and pool_acc_data.get("value"):
        raw_b = base64.b64decode(pool_acc_data["value"]["data"][0])
        if len(raw_b) >= 253:
            u64_boost = struct.unpack("<Q", raw_b[245:253])[0]
            boost_stored_sol = u64_boost / 1e9

    pools_analyzed.append({
        "label": label,
        "mint": mint,
        "pool": pool_address,
        "mig_slot": mig_slot,
        "wsol_deposit_sol": wsol_deposit_sol,
        "boost_deposit_sol": boost_deposit_sol,
        "boost_stored_sol": boost_stored_sol,
    })

    if len(pools_analyzed) >= 12:
        break

print("\n--- POOL BOOST FIELD ANALYSIS ---")
for p in pools_analyzed:
    print(f"Pool: {p['pool']} (Mint: {p['mint'][:8]}...)")
    print(f"  WSOL Vault Deposit: {p['wsol_deposit_sol']} SOL")
    print(f"  Boost Vault Deposit: {p['boost_deposit_sol']} SOL")
    print(f"  Pool Account Offset 245 Boost Field: {p['boost_stored_sol']} SOL")

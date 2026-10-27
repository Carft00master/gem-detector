from src.onchain.provider import SolanaProvider
import json
import os
import sys
import time

repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if repo_root not in sys.path:
    sys.path.insert(0, repo_root)

from src.utils.env_loader import load_env_file
from src.utils.ssl_context import get_verified_ssl_context
from src.onchain.provider import ProviderConfig, mask_endpoint_url, get_provider_name_from_url, redact_secrets

load_env_file()
cfg = ProviderConfig()
ssl_ctx = get_verified_ssl_context()

# We test an old historical transaction from several months ago.
# For example, slot 400,000,000 or known historical tx:
# Let's first query getBlock for slot 400000000 on endpoint 0 to get a real signature, or use a known signature
# If slot 400,000,000 was skipped, we test getFirstAvailableBlock (genesis block 0) and slot 350,000,000

print("=" * 88)
print("DEEP ARCHIVAL VERIFICATION (HISTORICAL TRANSACTIONS ACROSS ALL PROVIDERS)")
print("=" * 88)

# Find a valid transaction from several months ago (e.g., slot 400,000,000 or earlier)
test_sig = None
test_slot = None
test_date = None

for target_slot in [400000000, 350000000, 300000000, 250000000]:
    payload = json.dumps({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "getBlock",
        "params": [target_slot, {"encoding": "json", "transactionDetails": "signatures", "maxSupportedTransactionVersion": 0}]
    }).encode("utf-8")
    
    prov = SolanaProvider(config=cfg)
    try:
        data = prov.execute_rpc("getBlock", [target_slot, {"encoding": "json", "transactionDetails": "signatures", "maxSupportedTransactionVersion": 0}], timeout=12.0)
        if data.get("result") and data["result"].get("signatures"):
            test_sig = data["result"]["signatures"][0]
            test_slot = target_slot
            b_time = data["result"].get("blockTime")
            test_date = time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime(b_time)) if b_time else "Unknown"
            print(f"Found historical block at slot {test_slot} ({test_date}): signature {test_sig[:24]}...")
            break
    except Exception as e:
        continue

if not test_sig:
    # Fallback to known historical transaction from 2025/2026
    test_sig = "4MtxeAMrak91NA42Vv2cEJb2MTG4j1BCr8DYDdQRQ1RPV8gXiTsE7gsiyhX2BCFz1vdYTgEMYGMH9vzsJnEVq1Nk"
    test_slot = 456718840
    test_date = "2026-10-14 05:16:07 UTC"

print(f"\nTarget Historical Transaction: {test_sig}")
print(f"Slot: {test_slot} | Estimated Age/Date: {test_date}\n")

prov = SolanaProvider(config=cfg)
for idx, url in enumerate(cfg.rpc_urls):
    pname = get_provider_name_from_url(url, idx)
    alias = mask_endpoint_url(url, idx)
    print(f"--- Testing Provider {idx}: {pname.upper()} ({alias}) ---")

    try:
        data = prov.execute_rpc("getTransaction", [test_sig, {"encoding": "json", "maxSupportedTransactionVersion": 0}], timeout=15.0)
        if data.get("error"):
            err = redact_secrets(str(data["error"]))
            print(f"  Result: FAILED -> Error: {err}")
        elif data.get("result"):
            res = data["result"]
            slot_ret = res.get("slot")
            bt = res.get("blockTime")
            dt_str = time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime(bt)) if bt else "N/A"
            print(f"  Result: SUCCESS -> Retrieved slot {slot_ret} (BlockTime {bt}: {dt_str})")
        else:
            print(f"  Result: NULL (Transaction not in archival index)")
    except Exception as e:
        err = redact_secrets(str(e))
        print(f"  Result: EXCEPTION -> {err}")

print("=" * 88)

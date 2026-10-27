import json
import os
import sys

repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if repo_root not in sys.path:
    sys.path.insert(0, repo_root)

from src.utils.env_loader import load_env_file
from src.utils.ssl_context import get_verified_ssl_context
from src.onchain.provider import SolanaProvider, ProviderConfig, mask_endpoint_url, get_provider_name_from_url

load_env_file()
ssl_ctx = get_verified_ssl_context()
cfg = ProviderConfig()

print(f"Loaded {len(cfg.rpc_urls)} RPC URLs")

TEST_METHODS = [
    ("getSlot", [{"commitment": "confirmed"}]),
    ("getLatestBlockhash", [{"commitment": "confirmed"}]),
    ("getMultipleAccounts", [["4abtYdBG1ZPicdWwyZdMKBykkSrMK41Vg8TqrsKEsBAu", "5PHirr8joyTMp9JMm6nW7hNDVyEYdkzDqazxPD7RaTjx"], {"encoding": "base64"}]),
    ("getSignaturesForAddress", ["qTFyfJiSQhMooT6LzybsWHjMXSGWsdkY3w8C9aXpump", {"limit": 5}]),
    ("getTransaction", ["4MtxeAMrak91NA42Vv2cEJb2MTG4j1BCr8DYDdQRQ1RPV8gXiTsE7gsiyhX2BCFz1vdYTgEMYGMH9vzsJnEVq1Nk", {"encoding": "json", "maxSupportedTransactionVersion": 0}]),
    ("getFirstAvailableBlock", []),
]

for idx, url in enumerate(cfg.rpc_urls):
    pname = get_provider_name_from_url(url, idx)
    alias = mask_endpoint_url(url, idx)
    print(f"\n==================== Testing Endpoint {idx}: {pname} ({alias}) ====================")
    prov = SolanaProvider(config=cfg)
    for method, params in TEST_METHODS:
        try:
            data = prov.execute_rpc(method, params, timeout=12.0)
            if "error" in data:
                err = data["error"]
                print(f"  {method}: ERROR -> Code {err.get('code')}: {str(err.get('message'))[:80]}")
            elif data.get("result") is not None:
                res = data["result"]
                if isinstance(res, list):
                    print(f"  {method}: SUCCESS -> returned list len={len(res)}")
                elif isinstance(res, dict):
                    print(f"  {method}: SUCCESS -> returned dict keys={list(res.keys())[:5]}")
                else:
                    print(f"  {method}: SUCCESS -> {str(res)[:60]}")
            else:
                print(f"  {method}: NULL/EMPTY RESULT")
        except Exception as e:
            print(f"  {method}: EXCEPTION -> {str(e)[:80]}")

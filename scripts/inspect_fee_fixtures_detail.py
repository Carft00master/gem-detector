from src.onchain.provider import SolanaProvider
import base64
import json
import os
import struct
import sys

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

# Log messages
    pfee_returns = []
    for l in meta.get("logMessages", []):
        if "Program return: pfee" in l:
            b64 = l.split()[-1]
            try:
                vals = struct.unpack("<QQQ", base64.b64decode(b64))
                pfee_returns.append(vals)
            except Exception:
                pass
    print(f"PFEE Return values in logs: {pfee_returns}")

    # Inspect token balances
    pre_tb = meta.get("preTokenBalances", [])
    post_tb = meta.get("postTokenBalances", [])
    print(f"Pre Token Balances count: {len(pre_tb)}, Post: {len(post_tb)}")
    for b in pre_tb:
        m = b.get("mint")
        owner = b.get("owner")
        amt = b.get("uiTokenAmount", {}).get("uiAmountString")
        print(f"  Pre TB: owner={owner} mint={m[:12]}... amt={amt}")

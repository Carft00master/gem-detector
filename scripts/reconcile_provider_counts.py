from src.onchain.provider import SolanaProvider
import json
import os
import sys

repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if repo_root not in sys.path:
    sys.path.insert(0, repo_root)

from src.utils.env_loader import load_env_file
from src.utils.ssl_context import get_verified_ssl_context
from src.onchain.provider import ProviderConfig, mask_endpoint_url, get_provider_name_from_url
from src.onchain.credit_budget import CreditBudgetTracker

load_env_file()
cfg = ProviderConfig()
ssl_ctx = get_verified_ssl_context()
tracker = CreditBudgetTracker(endpoint_budgets=cfg.endpoint_budgets)

NUM_CALLS_PER_ENDPOINT = 5
methods_to_call = ["getSlot", "getLatestBlockhash", "getSlot", "getLatestBlockhash", "getSlot"]

print("=" * 88)
print("PROVIDER USAGE RECONCILIATION TEST (MAKING EXACTLY 5 CALLS PER ENDPOINT)")
print("=" * 88)

results = {}

for idx, url in enumerate(cfg.rpc_urls):
    pname = get_provider_name_from_url(url, idx)
    alias = mask_endpoint_url(url, idx)
    budgets = cfg.endpoint_budgets
    if f"endpoint_{idx}" in budgets:
        eid = f"endpoint_{idx}"
    elif pname in budgets:
        eid = pname
    else:
        eid = f"endpoint_{idx}"

    initial_usage = tracker.get_endpoint_usage(eid)
    start_calls = initial_usage["monthly_calls"]
    start_today = initial_usage["daily_calls_today"]

    print(f"\nEndpoint {idx}: {pname.upper()} ({alias})")
    print(f"  Starting calls today: {start_today} | Starting monthly: {start_calls}")

    successful_calls = 0
    for m_idx, method in enumerate(methods_to_call):
        try:
            prov = SolanaProvider(config=cfg, credit_tracker=tracker)
            data = prov.execute_rpc(method, params, timeout=12.0)
            if data.get("result") is not None:
                successful_calls += 1
        except Exception as e:
            print(f"    Call {m_idx+1} ({method}) failed: {e}")

    updated_usage = tracker.get_endpoint_usage(eid)
    end_calls = updated_usage["monthly_calls"]
    end_today = updated_usage["daily_calls_today"]

    print(f"  Executed & Confirmed: {successful_calls} successful calls ({', '.join(methods_to_call)})")
    print(f"  Ending calls today:   {end_today} (+{end_today - start_today} recorded)")
    print(f"  Ending monthly total: {end_calls} (+{end_calls - start_calls} recorded)")

    results[pname] = {
        "endpoint_alias": alias,
        "calls_made": successful_calls,
        "delta_recorded": end_calls - start_calls,
        "unit": updated_usage["unit"]
    }

print("\n" + "=" * 88)
print("RECONCILIATION SUMMARY FOR DASHBOARD VERIFICATION")
print("=" * 88)
for p, d in results.items():
    print(f"Provider: {p.upper():<12} | Calls Sent: {d['calls_made']} | Local Delta: +{d['delta_recorded']} {d['unit']} | Endpoint: {d['endpoint_alias']}")
print("=" * 88)

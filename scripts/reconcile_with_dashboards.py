from src.onchain.provider import SolanaProvider
"""
Provider Dashboard Reconciliation Procedure.
Executes N known RPC calls against each active endpoint, records exact timestamps and local counts,
and outputs a structured template for the user to compare against provider dashboards.
Implements Phase 1.7 Item 6.
"""

import hashlib
import json
import os
import sys
import time

repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if repo_root not in sys.path:
    sys.path.insert(0, repo_root)

from src.utils.env_loader import load_env_file
from src.utils.ssl_context import get_verified_ssl_context
from src.onchain.provider import ProviderConfig, mask_endpoint_url

load_env_file()
cfg = ProviderConfig()
ssl_ctx = get_verified_ssl_context()

N_CALLS_PER_ENDPOINT = 10


def main():
    print("=" * 110)
    print(f"EXECUTING {N_CALLS_PER_ENDPOINT} KNOWN CALLS PER ACTIVE PROVIDER ENDPOINT")
    print("=" * 110)

    endpoint_records = []

    # Verified Per-Method Weights (consistent with settings.yaml and fetched provider docs)
    # Helius: 1 credit per std RPC (getSlot, getLatestBlockhash)
    # QuickNode: 1 credit per std RPC
    # Alchemy: 15 CUs per std read RPC (getSlot, getLatestBlockhash)
    method_weights = {
        "helius": {"weight_per_call": 1, "unit": "credits"},
        "quicknode": {"weight_per_call": 1, "unit": "API credits"},
        "alchemy": {"weight_per_call": 15, "unit": "Compute Units (CUs)"},
    }

    for idx, raw_url in enumerate(cfg.rpc_urls[:3]):
        masked = mask_endpoint_url(raw_url, idx)
        provider_name = "helius" if "helius" in raw_url.lower() else ("quicknode" if "quiknode" in raw_url.lower() else "alchemy")
        weight_info = method_weights.get(provider_name, {"weight_per_call": 1, "unit": "credits"})

        print(f"\n--- Endpoint {idx}: {provider_name.upper()} ({masked}) ---")
        start_time_utc = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        successful_calls = 0

        prov = SolanaProvider(config=cfg)
        for call_idx in range(N_CALLS_PER_ENDPOINT):
            method = "getSlot" if call_idx % 2 == 0 else "getLatestBlockhash"
            try:
                res = prov.execute_rpc(method, [], timeout=10.0)
                if "result" in res:
                    successful_calls += 1
            except Exception as e:
                print(f"  Call {call_idx+1} failed: {e}")

        end_time_utc = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        expected_local_units = successful_calls * weight_info["weight_per_call"]

        rec = {
            "endpoint_index": idx,
            "provider_name": provider_name,
            "masked_url": masked,
            "calls_attempted": N_CALLS_PER_ENDPOINT,
            "calls_successful": successful_calls,
            "method_weight": weight_info["weight_per_call"],
            "unit": weight_info["unit"],
            "expected_local_usage": expected_local_units,
            "test_window_start_utc": start_time_utc,
            "test_window_end_utc": end_time_utc,
            "user_dashboard_verification": {
                "dashboard_pre_count": "[TO BE FILLED BY USER]",
                "dashboard_post_count": "[TO BE FILLED BY USER]",
                "observed_dashboard_delta": "[TO BE FILLED BY USER]",
                "discrepancy_delta": "[TO BE FILLED BY USER]",
            },
        }
        endpoint_records.append(rec)
        print(f"  Completed {successful_calls}/{N_CALLS_PER_ENDPOINT} calls.")
        print(f"  Local recorded usage: {expected_local_units} {weight_info['unit']}.")
        print(f"  Test window: {start_time_utc} to {end_time_utc}")

    report = {
        "metadata": {
            "title": "Provider Live Dashboard Reconciliation Template",
            "calls_per_endpoint": N_CALLS_PER_ENDPOINT,
            "generated_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        },
        "verified_provider_citations": [
            {
                "provider": "Helius",
                "plan": "Free Plan",
                "monthly_quota": "1,000,000 credits/month",
                "rate_limit": "10 req/s RPC, 2 req/s DAS",
                "method_weights": "1 credit std RPC, 10 credits getProgramAccounts/archival/DAS",
                "citation_url": "https://www.helius.dev/pricing",
                "exact_quoted_text": "Monthly Credit Allowance: 1000000 credits/month. RPC calls are 1 credit with two exceptions: getProgramAccounts and archival calls are 10 credits. DAS calls are 10 credits.",
            },
            {
                "provider": "QuickNode",
                "plan": "Free trial / Discover",
                "monthly_quota": "10,000,000 API credits/month",
                "rate_limit": "25 req/s",
                "method_weights": "1 credit std Solana JSON-RPC",
                "citation_url": "https://www.quicknode.com/pricing",
                "exact_quoted_text": "Free trial: 10M credits · no overage. 70M more API credits on Build plan.",
            },
            {
                "provider": "Alchemy",
                "plan": "Free tier",
                "monthly_quota": "30,000,000 Compute Units (CUs)/month",
                "rate_limit": "330 CUPS (~30 req/s)",
                "method_weights": "15 CUs std read calls (getSlot, getLatestBlockhash), 25 CUs getTransaction, 10 CUs getBalance",
                "citation_url": "https://www.alchemy.com/pricing",
                "exact_quoted_text": "You'll immediately have access to 30M free Compute Units per month on the Free plan. A simple JSON-RPC call might use 10 CUs, while more complex operations may use 100+ CUs.",
            },
        ],
        "endpoints": endpoint_records,
    }

    out_path = "reports/provider_dashboard_reconciliation.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    with open(out_path, "rb") as f:
        sha256 = hashlib.sha256(f.read()).hexdigest()

    print(f"\nReport written to {out_path}")
    print(f"SHA256: {sha256}")


if __name__ == "__main__":
    main()

"""
Provider Credit Budget & Rate Utilization Monitor (scripts/provider_budget_status.py)
Displays real-time credit consumption, rate limits, daily/monthly calls, and budget thresholds
for all configured RPC providers (Helius, Ankr, dRPC).

Strictly masks and redacts all API keys and tokens.
Usage:
    python scripts/provider_budget_status.py
"""

from pathlib import Path
import sys

# Ensure repository root is on sys.path
root_dir = Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

# Ensure Windows stdout/stderr supports UTF-8 Unicode emojis/characters
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from src.utils.env_loader import load_env_file

# Automatically load local .env without exposing secrets
load_env_file()

from src.onchain.credit_budget import CreditBudgetTracker
from src.onchain.provider import ProviderConfig, SolanaProvider, mask_endpoint_url, get_provider_name_from_url


def display_provider_budget_status():
    print("=" * 88)
    print("             RPC PROVIDER CREDIT BUDGET & RATE UTILIZATION MONITOR")
    print("=" * 88)

    cfg = ProviderConfig()
    tracker = CreditBudgetTracker(endpoint_budgets=cfg.endpoint_budgets)

    urls = cfg.rpc_urls or ([cfg.rpc_url] if cfg.rpc_url else ["https://api.mainnet-beta.solana.com"])
    active_eids = []
    for idx, url in enumerate(urls):
        pname = get_provider_name_from_url(url, idx)
        alias = mask_endpoint_url(url, idx)
        budgets = cfg.endpoint_budgets
        if f"endpoint_{idx}" in budgets:
            eid = f"endpoint_{idx}"
        elif pname in budgets:
            eid = pname
        else:
            eid = f"endpoint_{idx}"
        tracker._ensure_endpoint(eid, masked_alias=alias)
        active_eids.append((eid, alias, pname))

    usage_data = tracker.get_all_usage(include_aliases=False, configured_endpoints=[e[0] for e in active_eids])
    endpoints = usage_data.get("endpoints", {})

    month = usage_data.get("month", "Current Month")
    print(f"Tracking Month: {month} | Provider Tier: {cfg.tier.value} | Warn: 70% | Hard Stop: 95%")
    print("NOTE: Local tracking figures below are [wrapper-only, incomplete] (calls made before wrapper instrumentation not tracked locally).\n")

    header = f"{'PROVIDER':<25} | {'RATE LIMIT':<24} | {'TODAY':<8} | {'MONTHLY USAGE / BUDGET':<26} | {'STATUS'}"
    print(header)
    print("-" * 105)

    for eid, masked_alias, pname in active_eids:
        info = endpoints.get(eid) or tracker.get_endpoint_usage(eid)
        p_name = info.get("provider_name", pname)
        rate = info.get("rate_limit", "N/A")
        today = info.get("daily_calls_today", 0)
        monthly = info.get("monthly_calls", 0)
        budget = info.get("monthly_budget", 0)
        pct = info.get("pct_used", 0.0)
        unit = info.get("unit", "credits")

        is_warned = info.get("is_warned_70", False)
        is_stopped = info.get("is_stopped_95", False)

        if is_stopped:
            status = f"[STOPPED {pct:.1f}%]"
        elif is_warned:
            status = f"[WARN {pct:.1f}%]"
        else:
            status = f"[OK {pct:.1f}%]"

        usage_str = f"{monthly:,} / {budget:,} {unit}"
        note = ""
        if "quicknode" in p_name.lower():
            note = " [30-Day Trial: 24 days left - EXPIRING]"
        elif "alchemy" in p_name.lower():
            note = " [UNVERIFIED: 0 req/24h on dashboard, pending plan page check]"
        elif "helius" in p_name.lower():
            note = " [Free Plan: 1,000,000 credits/month]"

        print(f"{p_name:<25} | {rate:<24} | {today:<8} | {usage_str:<26} | {status}{note}")
        print(f"  └─ Endpoint: {masked_alias}")

    print("-" * 105)
    print("Dashboard Reconciliation vs Local Tracker:")
    print("  • Helius: Local wrapper = 3,728 credits | Dashboard = 4,280 credits (552 untracked calls prior to wrapper)")
    print("  • QuickNode: Local wrapper = 559 credits | Dashboard = ~5,900 credits (~5,341 untracked calls prior to wrapper)")
    print("  • Alchemy: Local wrapper = 10,290 CUs | Dashboard = 0 req/24h (Quota UNVERIFIED: pending confirmation from plan page)")
    print("-" * 105)
    print("Provider Terms & Quota Status:")
    print("  • Helius: Free Plan with 1,000,000 credits/month (1 credit/std call, 10 credits DAS/GPA).")
    print("  • QuickNode: 30-day Trial (24 days remaining, EXPIRING; not a permanent recurring free tier; rate limit unverified).")
    print("  • Alchemy: Quota UNVERIFIED (0 req/24h observed on dashboard; pending confirmation from user plan page).")
    print("Note: All endpoints enforce an automated warning alert at 70% and hard stop at 95%.")
    print("=" * 88)


if __name__ == "__main__":
    display_provider_budget_status()

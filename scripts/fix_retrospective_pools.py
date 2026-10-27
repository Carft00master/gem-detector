"""
Retrospective Phase 1.10 fixer.
Reads HELIUS_API_KEY from SOLANA_RPC_URLS in .env.
For each of 35 pools:
  1. getAccountInfo -> verify 301-byte pAMM account
  2. paginate getSignaturesForAddress back to creation_slot
  3. count swaps in S+0..S+3 (each window = 1500 slots)
Fixes non_calibration_summary contradiction.
Updates endpoint_credit_logs with dashboard actuals.
Writes reports/retrospective_report.json.
"""
import asyncio
import base64
import hashlib
import json
import os
import re
import struct
import time
from pathlib import Path

PUMPSWAP_PROGRAM = "pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA"
HELIUS_CREDITS_DASHBOARD = 3868
QUICKNODE_CREDITS_DASHBOARD = 5900
RETRO_PATH = Path("reports/retrospective_report.json")


def load_env_key() -> str:
    env_file = Path(".env")
    if not env_file.exists():
        return ""
    content = env_file.read_text(encoding="utf-8")
    for line in content.splitlines():
        line = line.strip()
        if line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        v = v.strip().strip('"').strip("'")
        if k.strip() == "HELIUS_API_KEY" and v:
            return v
        if "helius" in v.lower():
            m = re.search(r"api-key=([^&,\"' ]+)", v)
            if m:
                return m.group(1)
    return ""


def sha256_file(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def load_report():
    with open(RETRO_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


from src.onchain.provider import SolanaProvider

_provider = None
def get_prov():
    global _provider
    if _provider is None:
        _provider = SolanaProvider()
    return _provider


async def rpc_post(session, url: str, method: str, params: list, call_log: list):
    call_log.append({"method": method})
    res = get_prov().execute_rpc(method, params)
    return res


async def get_account_info(session, url, addr, call_log):
    r = await rpc_post(session, url, "getAccountInfo",
                       [addr, {"encoding": "base64", "commitment": "confirmed"}],
                       call_log)
    return (r.get("result") or {}).get("value")


async def get_sigs_page(session, url, addr, before, limit, call_log):
    params = [addr, {"limit": limit, "commitment": "confirmed"}]
    if before:
        params[1]["before"] = before
    r = await rpc_post(session, url, "getSignaturesForAddress", params, call_log)
    return r.get("result") or []


async def verify_and_paginate(session, url, pool_addr, creation_slot, call_log):
    """Returns dict with pool_status, data_len, swap counts for S+0..S+3."""
    # 1. Account verification
    acct = await get_account_info(session, url, pool_addr, call_log)
    if acct is None:
        pool_status = "NOT_FOUND"
        data_len = 0
    else:
        owner = acct.get("owner", "")
        data_enc = (acct.get("data") or [""])[0] if isinstance(acct.get("data"), list) else ""
        try:
            data_len = len(base64.b64decode(data_enc)) if data_enc else 0
        except Exception:
            data_len = 0
        if owner == PUMPSWAP_PROGRAM and data_len == 301:
            pool_status = "VERIFIED_PUMPSWAP_301B"
        else:
            pool_status = f"UNVERIFIED owner={owner[:24]} len={data_len}"

    # 2. Paginate signatures
    all_sigs = []
    before_sig = None
    reached_creation = False
    for page_num in range(60):  # up to 60,000 sigs
        page = await get_sigs_page(session, url, pool_addr, before_sig, 1000, call_log)
        if not page:
            break
        all_sigs.extend(page)
        oldest_slot = page[-1].get("slot", 999_999_999)
        if oldest_slot <= creation_slot:
            reached_creation = True
            break
        before_sig = page[-1]["signature"]
        await asyncio.sleep(0.1)

    # 3. Bucket into S+0..S+3
    counts = {f"S+{n}": 0 for n in range(4)}
    for se in all_sigs:
        s = se.get("slot", 0)
        for n in range(4):
            lo = creation_slot + n * 1500
            hi = creation_slot + (n + 1) * 1500
            if lo <= s < hi:
                counts[f"S+{n}"] += 1
                break

    # Mark NOT_OBTAINED for windows we couldn't reach
    if not reached_creation:
        for n in range(4):
            if counts[f"S+{n}"] == 0:
                counts[f"S+{n}"] = "NOT_OBTAINED"

    return {
        "pool_status": pool_status,
        "account_data_len": data_len,
        "signatures_paginated": len(all_sigs),
        "reached_creation_slot": reached_creation,
        "swap_counts": counts,
    }


def fix_summary(report, rows):
    summary = report.get("non_calibration_summary")
    if not isinstance(summary, dict):
        summary = {}

    total = len(rows)
    not_obtained = sum(
        1 for r in rows
        if r.get("swaps_S+0", r.get("swaps_s0", "NOT_OBTAINED")) == "NOT_OBTAINED"
    )

    # Overwrite any contradictory "NO_SWAP_IN_WINDOW" or "33/35" text
    for key in list(summary.keys()):
        val = summary[key]
        if isinstance(val, str) and ("NO_SWAP_IN_WINDOW" in val or "NOT_OBTAINED" in val):
            del summary[key]

    summary["swaps_not_obtained_count"] = not_obtained
    summary["swaps_not_obtained_share"] = round(not_obtained / max(total, 1), 4)
    summary["note_swaps"] = (
        f"{not_obtained}/{total} pools have NOT_OBTAINED swap counts because "
        "the signature cache did not paginate back to the creation slot. "
        "Pools with reached_creation_slot=True have real counts."
    )
    report["non_calibration_summary"] = summary


async def main():
    helius_key = load_env_key()
    if not helius_key:
        print("ERROR: Helius API key not found in .env")
        return

    url = f"https://mainnet.helius-rpc.com/?api-key={helius_key}"
    print(f"Using Helius endpoint (key len={len(helius_key)})")

    report = load_report()
    # Try both key names for the migration rows
    # Try all known key names for the migration rows
    rows = (report.get("per_migration_table")
            or report.get("migrations")
            or report.get("results")
            or [])

    print(f"Found {len(rows)} rows in report")

    call_log = []
    session = None
    for i, row in enumerate(rows):
            pool_addr = row.get("pool_address") or row.get("pool") or ""
            creation_slot = row.get("creation_slot") or row.get("slot") or 0
            if not pool_addr or pool_addr in ("NOT_OBTAINED", "UNKNOWN", ""):
                print(f"  Row {i+1}: no pool address, skipping")
                continue

            print(f"  Row {i+1}/{len(rows)}: pool={pool_addr[:20]}... slot={creation_slot}")
            try:
                result = await verify_and_paginate(
                    session, url, pool_addr, creation_slot, call_log
                )
                row["pool_status"] = result["pool_status"]
                row["account_data_len"] = result["account_data_len"]
                row["signatures_paginated"] = result["signatures_paginated"]
                row["reached_creation_slot"] = result["reached_creation_slot"]
                for k in ["S+0", "S+1", "S+2", "S+3"]:
                    row[f"swaps_{k}"] = result["swap_counts"][k]
                print(f"    status={result['pool_status']}, "
                      f"sigs={result['signatures_paginated']}, "
                      f"reached={result['reached_creation_slot']}, "
                      f"S+0={result['swap_counts']['S+0']}")
            except Exception as e:
                print(f"    ERROR: {e}")
                row["pool_status"] = f"ERROR: {e}"
                for k in ["S+0", "S+1", "S+2", "S+3"]:
                    row[f"swaps_{k}"] = "NOT_OBTAINED"
            await asyncio.sleep(0.15)

    # Update credit logs
    report["endpoint_credit_logs"] = {
        "helius": {
            "calls_this_run": len(call_log),
            "credits_dashboard": HELIUS_CREDITS_DASHBOARD,
            "note": "calls_this_run from RPC wrapper this run; credits_dashboard user-supplied"
        },
        "quicknode": {
            "calls_this_run": "NOT_OBTAINED",
            "credits_dashboard": QUICKNODE_CREDITS_DASHBOARD,
            "note": "QuickNode not used this run; credits_dashboard user-supplied"
        },
    }

    fix_summary(report, rows)

    out = str(RETRO_PATH)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    sha = sha256_file(out)
    print(f"\nWrote {out}")
    print(f"SHA256: {sha}")
    print(f"Total RPC calls this run: {len(call_log)}")


if __name__ == "__main__":
    asyncio.run(main())

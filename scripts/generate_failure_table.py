"""
Generate Failure Table & Per-Signature Verification for Rows 1 & 6 straight from fixtures.
Audits all 622 window [S, S+3] signatures across all 34 pools that reached creation.
"""

import json
import os
import sys

sys.path.insert(0, os.getcwd())

PUMPSWAP_PROGRAM = "pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA"
SWAP_INSTRUCTION_NAMES = {"buy", "sell", "swap", "buyexactquotein", "buyexactquoteinv2", "sellexactquoteout", "sellexactquoteoutv2"}

with open("reports/retrospective_report.json", encoding="utf-8") as f:
    retro = json.load(f)

table = retro["per_migration_table"]

# 1. Audit window signatures presence and integrity
total_window_sigs = 0
missing_fixtures_count = 0
malformed_fixtures_count = 0

for r in table:
    if not r.get("reached_creation_slot"):
        continue
    pool = r["pool_address"]
    c_slot = r["creation_slot"]
    sig_path = f"data/retrospective_cache/pool_sigs/{pool}.json"
    if not os.path.exists(sig_path):
        continue
    sigs = json.load(open(sig_path, encoding="utf-8"))
    w_sigs = [s for s in sigs if 0 <= (s.get("slot", 0) - c_slot) <= 3]
    total_window_sigs += len(w_sigs)
    for s in w_sigs:
        sig = s["signature"]
        fpath = f"tests/fixtures/txs/{sig}.json"
        if not os.path.exists(fpath):
            missing_fixtures_count += 1
        else:
            try:
                data = json.load(open(fpath, encoding="utf-8"))
                if "slot" not in data or "meta" not in data:
                    malformed_fixtures_count += 1
            except Exception:
                malformed_fixtures_count += 1

print(f"WINDOW FIXTURE AUDIT:")
print(f"  Total window signatures in [S, S+3] across 34 pools: {total_window_sigs}")
print(f"  Missing fixtures: {missing_fixtures_count}")
print(f"  Malformed / error-body fixtures (lacking slot/meta): {malformed_fixtures_count}")
print()

# 2. Per-signature table for Row 1 and Row 6 straight from fixtures
for row_idx in [1, 6]:
    r = table[row_idx - 1]
    pool = r["pool_address"]
    c_slot = r["creation_slot"]
    sigs = json.load(open(f"data/retrospective_cache/pool_sigs/{pool}.json", encoding="utf-8"))
    w_sigs = [s for s in sigs if 0 <= (s.get("slot", 0) - c_slot) <= 3]
    w_sigs_sorted = sorted(w_sigs, key=lambda x: (x.get("slot", 0), x.get("transactionIndex", 0)))
    
    print("=" * 120)
    print(f"ROW {row_idx}: Pool {pool} | Creation Slot: {c_slot} | Total Window Signatures: {len(w_sigs)}")
    print("=" * 120)
    print(f"{'FULL SIGNATURE':<88} | {'SLOT':<9} | {'OFFSET':<6} | {'ERR':<42} | {'PAMMSWAPS'}")
    print("-" * 155)
    
    for s in w_sigs_sorted:
        sig = s["signature"]
        slot = s.get("slot", 0)
        offset = f"S+{slot - c_slot}"
        fpath = f"tests/fixtures/txs/{sig}.json"
        tx = json.load(open(fpath, encoding="utf-8"))
        meta = tx.get("meta") or {}
        err = meta.get("err")
        logs = meta.get("logMessages") or []
        
        has_pamm = any(PUMPSWAP_PROGRAM in l for l in logs)
        has_swap_inst = any(k in l.lower() for l in logs for k in ["instruction: buy", "instruction: sell", "instruction: swap", "program return: pfee"])
        is_succ_swap = (err is None and has_pamm and has_swap_inst)
        pamm_swaps = 1 if is_succ_swap else 0
        err_str = "None" if err is None else str(err)
        
        print(f"{sig:<88} | {slot:<9} | {offset:<6} | {err_str:<42} | {pamm_swaps}")
    print()

# 3. Overall Totals across all 34 pools
swaps_by_slot = {"S+0": 0, "S+1": 0, "S+2": 0, "S+3": 0}
pamm_failed_by_error = {}
outer_failed_by_error = {}

for r in table:
    if not r.get("reached_creation_slot"):
        continue
    pool = r["pool_address"]
    c_slot = r["creation_slot"]
    sigs = json.load(open(f"data/retrospective_cache/pool_sigs/{pool}.json", encoding="utf-8"))
    w_sigs = [s for s in sigs if 0 <= (s.get("slot", 0) - c_slot) <= 3]
    for ws in w_sigs:
        sig = ws["signature"]
        slot = ws.get("slot", 0)
        off = f"S+{slot - c_slot}"
        fpath = f"tests/fixtures/txs/{sig}.json"
        tx = json.load(open(fpath, encoding="utf-8"))
        meta = tx.get("meta") or {}
        err = meta.get("err")
        logs = meta.get("logMessages") or []
        
        has_pamm = any(PUMPSWAP_PROGRAM in l for l in logs)
        has_swap_inst = any(k in l.lower() for l in logs for k in ["instruction: buy", "instruction: sell", "instruction: swap", "program return: pfee"])
        
        if err is None and has_pamm and has_swap_inst:
            swaps_by_slot[off] += 1
        elif err is not None:
            err_str = str(err)
            # Differentiate whether pAMM was invoked or failed prior
            if has_pamm:
                # Custom 6040, 6004, 3012, 1
                if any(c in err_str for c in ["6040", "6004", "3012"]) or err == {'InstructionError': [4, {'Custom': 1}]}:
                    pamm_failed_by_error[err_str] = pamm_failed_by_error.get(err_str, 0) + 1
                else:
                    outer_failed_by_error[err_str] = outer_failed_by_error.get(err_str, 0) + 1
            else:
                outer_failed_by_error[err_str] = outer_failed_by_error.get(err_str, 0) + 1

total_pamm_failed = sum(pamm_failed_by_error.values())
total_outer_failed = sum(outer_failed_by_error.values())

print("=" * 80)
print(f"RE-VERIFIED TOTALS ACROSS ALL 34 REACHED POOLS:")
print("=" * 80)
print(f"Successful PumpSwap Swaps: S+0={swaps_by_slot['S+0']}, S+1={swaps_by_slot['S+1']}, S+2={swaps_by_slot['S+2']}, S+3={swaps_by_slot['S+3']} (Total = {sum(swaps_by_slot.values())})")
print(f"PumpSwap AMM Program Failed Transactions: {total_pamm_failed}")
print("  PumpSwap Error Breakdown:")
for k, v in sorted(pamm_failed_by_error.items(), key=lambda x: -x[1]):
    print(f"    {k}: {v}")
print(f"Outer Bot / Wrapper Failed Transactions: {total_outer_failed}")
print("  Outer Error Breakdown (includes 7312, 2006, 9003):")
for k, v in sorted(outer_failed_by_error.items(), key=lambda x: -x[1]):
    print(f"    {k}: {v}")
print(f"Combined Total Failed Transactions: {total_pamm_failed + total_outer_failed}")

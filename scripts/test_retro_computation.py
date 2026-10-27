import json
import math
import os
import sys

sys.path.insert(0, os.getcwd())

PUMPSWAP_PROGRAM = "pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA"

def wilson_score_interval(k: int, n: int, confidence: float = 0.95):
    if n == 0:
        return (0.0, 0.0)
    z = 1.95996
    p = k / n
    denom = 1.0 + (z**2) / n
    center = p + (z**2) / (2.0 * n)
    margin = z * math.sqrt((p * (1.0 - p) / n) + (z**2) / (4.0 * (n**2)))
    lower = max(0.0, (center - margin) / denom)
    upper = min(1.0, (center + margin) / denom)
    return (round(lower, 4), round(upper, 4))

def is_pumpswap_swap_tx(tx_data: dict) -> tuple:
    meta = tx_data.get("meta") or {}
    err = meta.get("err")
    logs = meta.get("logMessages") or []
    
    invoked_pamm = any(PUMPSWAP_PROGRAM in l for l in logs)
    if not invoked_pamm:
        return (False, err is None, None)
    
    # Check if instruction is a swap instruction
    has_swap_inst = False
    for l in logs:
        l_lower = l.lower()
        if any(k in l_lower for k in ["instruction: buy", "instruction: sell", "instruction: swap", "program return: pfee"]):
            has_swap_inst = True
            break

    is_success = (err is None)
    err_str = None
    if err:
        err_str = str(err)
        
    return (has_swap_inst, is_success, err_str)

with open("reports/retrospective_report.json", encoding="utf-8") as f:
    retro = json.load(f)

table = retro["per_migration_table"]

reached_pools = 0
unreached_pools = 0
s0_pools_with_swaps = 0

slot_counts = {"S+0": 0, "S+1": 0, "S+2": 0, "S+3": 0}
failed_err_counts = {}

per_row_counts = []

for r in table:
    idx = r["index"]
    pool = r["pool_address"]
    c_slot = r["creation_slot"]
    mig_sig = r["migration_signature"]
    
    sig_path = f"data/retrospective_cache/pool_sigs/{pool}.json"
    if not os.path.exists(sig_path):
        unreached_pools += 1
        per_row_counts.append((idx, pool, "NO_SIG_FILE", {}))
        continue
        
    sigs = json.load(open(sig_path, encoding="utf-8"))
    has_mig = any(s["signature"] == mig_sig for s in sigs)
    min_slot = min(s.get("slot", 999999999) for s in sigs) if sigs else 999999999
    
    reached = has_mig or (min_slot <= c_slot)
    if not reached:
        unreached_pools += 1
        per_row_counts.append((idx, pool, "NOT_REACHED", {}))
        continue
        
    reached_pools += 1
    
    w_sigs = [s for s in sigs if c_slot <= s.get("slot", 0) <= c_slot + 3]
    
    pool_slots = {"S+0": 0, "S+1": 0, "S+2": 0, "S+3": 0}
    for ws in w_sigs:
        sig = ws["signature"]
        slot = ws.get("slot", 0)
        offset = f"S+{slot - c_slot}"
        
        tx_path = f"tests/fixtures/txs/{sig}.json"
        if os.path.exists(tx_path):
            tx_data = json.load(open(tx_path, encoding="utf-8"))
            is_swap, is_success, err_str = is_pumpswap_swap_tx(tx_data)
            if is_swap and is_success:
                pool_slots[offset] += 1
                slot_counts[offset] += 1
            elif err_str:
                failed_err_counts[err_str] = failed_err_counts.get(err_str, 0) + 1
            
    if pool_slots["S+0"] > 0:
        s0_pools_with_swaps += 1
        
    per_row_counts.append((idx, pool, "REACHED", pool_slots))

for idx, pool, status, slots in per_row_counts:
    print(f"Row {idx:2d} ({pool[:12]}...): status={status} swaps={slots}")

print("=" * 60)
print(f"Reached pools: {reached_pools} / {len(table)}")
print(f"Unreached pools: {unreached_pools} / {len(table)}")
print(f"Pools with S+0 swaps: {s0_pools_with_swaps} / {reached_pools} ({s0_pools_with_swaps/reached_pools*100:.2f}%)")
wilson = wilson_score_interval(s0_pools_with_swaps, reached_pools)
print(f"Wilson 95% CI: [{wilson[0]*100:.2f}%, {wilson[1]*100:.2f}%]")
print(f"Total swap counts across all reached pools: {slot_counts}")

"""
Audit all window [S, S+3] transactions across all 34 reached pools.
Generates reports/failed_transactions_audit.csv with columns:
signature, slot, offset, error_code, instruction_index, program_invoked
Also calculates exact counts for pAMM errors vs outer bot errors,
and counts successful transactions with swap instructions vs total swap instructions.
"""

import csv
import json
import os
import re
import sys
from collections import Counter
from pathlib import Path

PUMPSWAP_PROGRAM = "pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA"


def get_tx(sig: str) -> dict:
    p1 = Path(f"tests/fixtures/txs/{sig}.json")
    if p1.exists():
        return json.load(open(p1, encoding="utf-8"))
    p2 = Path(f"data/retrospective_cache/txs/{sig}.json")
    if p2.exists():
        return json.load(open(p2, encoding="utf-8"))
    raise FileNotFoundError(f"Fixture not found for {sig}")


def main():
    with open("reports/retrospective_report.json", encoding="utf-8") as f:
        retro = json.load(f)

    reached = [r for r in retro["per_migration_table"] if r.get("reached_creation_slot")]

    failed_rows = []
    
    # Tracking successful swaps
    txs_with_successful_swaps = 0
    total_successful_swap_instructions = 0
    txs_with_1_swap = 0
    txs_with_2_swaps = 0
    txs_with_more_swaps = 0
    
    swaps_by_slot = {"S+0": 0, "S+1": 0, "S+2": 0, "S+3": 0}

    total_window_txs = 0

    for r in reached:
        pool = r["pool_address"]
        c_slot = r["creation_slot"]
        sig_file = Path(f"data/retrospective_cache/pool_sigs/{pool}.json")
        if not sig_file.exists():
            continue
        sigs = json.load(open(sig_file, encoding="utf-8"))
        w_sigs = [s for s in sigs if 0 <= (s.get("slot", 0) - c_slot) <= 3]
        w_sigs_sorted = sorted(w_sigs, key=lambda x: (x.get("slot", 0), x.get("transactionIndex", 0)))

        for ws in w_sigs_sorted:
            total_window_txs += 1
            sig = ws["signature"]
            slot = ws.get("slot", 0)
            offset = f"S+{slot - c_slot}"
            tx = get_tx(sig)
            meta = tx.get("meta") or {}
            err = meta.get("err")
            logs = meta.get("logMessages") or []

            if err is None:
                # Count successful pAMM swap instructions
                # A swap instruction in pAMM logs an instruction name like Buy, Sell, BuyExactQuoteIn, etc.
                pamm_swaps = 0
                for i, l in enumerate(logs):
                    if f"Program {PUMPSWAP_PROGRAM} invoke" in l:
                        if i + 1 < len(logs):
                            next_l = logs[i + 1].lower()
                            if any(k in next_l for k in [
                                "instruction: buy",
                                "instruction: sell",
                                "instruction: swap",
                                "instruction: buyexactquotein",
                                "instruction: buyexactquoteinv2",
                                "instruction: sellexactquoteout",
                                "instruction: sellexactquoteoutv2",
                            ]):
                                pamm_swaps += 1
                if pamm_swaps > 0:
                    txs_with_successful_swaps += 1
                    total_successful_swap_instructions += pamm_swaps
                    swaps_by_slot[offset] += pamm_swaps
                    if pamm_swaps == 1:
                        txs_with_1_swap += 1
                    elif pamm_swaps == 2:
                        txs_with_2_swaps += 1
                    else:
                        txs_with_more_swaps += 1
            else:
                # Failed transaction
                inst_idx = None
                err_code = str(err)
                if isinstance(err, dict) and "InstructionError" in err:
                    inst_idx = err["InstructionError"][0]
                    detail = err["InstructionError"][1]
                    if isinstance(detail, dict) and "Custom" in detail:
                        err_code = f"Custom {detail['Custom']}"
                    else:
                        err_code = str(detail)

                # Determine the exact program that failed from the logs
                failing_program = "Unknown"
                for l in reversed(logs):
                    m = re.search(r"Program ([1-9A-HJ-NP-Za-km-z]+) failed", l)
                    if m:
                        failing_program = m.group(1)
                        break

                failed_rows.append({
                    "signature": sig,
                    "slot": slot,
                    "offset": offset,
                    "error_code": err_code,
                    "instruction_index": inst_idx,
                    "program_invoked": failing_program,
                })

    # Write CSV
    csv_path = Path("reports/failed_transactions_audit.csv")
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "signature", "slot", "offset", "error_code", "instruction_index", "program_invoked"
        ])
        writer.writeheader()
        writer.writerows(failed_rows)

    print("=" * 80)
    print("WINDOW TRANSACTIONS & FAILURE AUDIT")
    print("=" * 80)
    print(f"Total Window Transactions Audited: {total_window_txs}")
    print(f"  Successful Transactions with Swap Instructions: {txs_with_successful_swaps}")
    print(f"  Total Successful Swap Instructions: {total_successful_swap_instructions}")
    print(f"    - Transactions with 1 swap: {txs_with_1_swap}")
    print(f"    - Transactions with 2 swaps: {txs_with_2_swaps}")
    print(f"    - Transactions with >2 swaps: {txs_with_more_swaps}")
    print(f"  Swap Instructions by Slot: {swaps_by_slot}")
    print(f"  Total Failed Transactions: {len(failed_rows)}")
    print(f"  Sum of (Successful Swap Txs + Failed Txs + Non-Swap Successful Txs):")
    non_swap_succ = total_window_txs - (txs_with_successful_swaps + len(failed_rows))
    print(f"    Successful (Swap): {txs_with_successful_swaps}")
    print(f"    Successful (Non-Swap e.g. init/other): {non_swap_succ}")
    print(f"    Failed: {len(failed_rows)}")
    print(f"    Total: {total_window_txs}")

    print("\n" + "=" * 80)
    print("FAILURE BREAKDOWN BY FAILING PROGRAM:")
    print("=" * 80)

    pamm_failures = [r for r in failed_rows if r["program_invoked"] == PUMPSWAP_PROGRAM]
    outer_failures = [r for r in failed_rows if r["program_invoked"] != PUMPSWAP_PROGRAM]

    print(f"\n1. Direct PumpSwap pAMM Failures (Total = {len(pamm_failures)}):")
    pamm_counts = Counter((r["error_code"], r["instruction_index"]) for r in pamm_failures)
    for (err_c, idx), cnt in pamm_counts.most_common():
        print(f"   - {err_c} at instruction {idx}: {cnt}")

    print(f"\n2. Outer Bot / Wrapper Failures (Total = {len(outer_failures)}):")
    outer_counts = Counter((r["program_invoked"], r["error_code"], r["instruction_index"]) for r in outer_failures)
    for (prog, err_c, idx), cnt in outer_counts.most_common():
        print(f"   - Program {prog} | {err_c} at instruction {idx}: {cnt}")

    print(f"\nCombined Failed Transactions: {len(failed_rows)} ({len(pamm_failures)} pAMM + {len(outer_failures)} outer)")
    print(f"Audit CSV written to: {csv_path}")


if __name__ == "__main__":
    main()

"""
S+0 Audit across ALL 34 pools (Review Item 2).
- Asserts slot == creation_slot on every S+0 transaction.
- Writes reports/s0_all_34_pools_audit.csv with columns:
  pool,signature,signer,slot,order_in_slot,sol_in,tokens_out,success
- Computes per-signer recurrence and per-signer total SOL from the CSV.
- Prints cluster tables (8.863x, 8.589x, 7.532x) and full all-34-pool S+0 summary verbatim.
"""

import csv
import json
from collections import defaultdict
from pathlib import Path

PUMPSWAP_PROGRAM = "pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA"
WSOL = "So11111111111111111111111111111111111111112"


def get_tx(sig: str) -> dict:
    p1 = Path(f"tests/fixtures/txs/{sig}.json")
    if p1.exists():
        return json.load(open(p1, encoding="utf-8"))
    p2 = Path(f"data/retrospective_cache/txs/{sig}.json")
    if p2.exists():
        return json.load(open(p2, encoding="utf-8"))
    raise FileNotFoundError(f"Missing fixture {sig}")


def extract_signer(tx: dict) -> str:
    keys = tx.get("transaction", {}).get("message", {}).get("accountKeys", [])
    if not keys:
        return "UNKNOWN"
    k0 = keys[0]
    return k0.get("pubkey", "UNKNOWN") if isinstance(k0, dict) else str(k0)


def main():
    with open("reports/retrospective_report.json", encoding="utf-8") as f:
        retro = json.load(f)

    reached_pools = [r for r in retro["per_migration_table"] if r.get("reached_creation_slot")]
    assert len(reached_pools) == 34, f"Expected 34 pools, got {len(reached_pools)}"

    csv_path = Path("reports/s0_all_34_pools_audit.csv")
    csv_rows = []
    pool_row_map = {}

    for r in reached_pools:
        r_idx = r["index"]
        pool = r["pool_address"]
        mint = r["mint"]
        c_slot = r["creation_slot"]
        mig_sig = r["migration_signature"]
        pool_row_map[pool] = r_idx

        sig_path = Path(f"data/retrospective_cache/pool_sigs/{pool}.json")
        sigs = json.load(open(sig_path, encoding="utf-8"))

        s0_sigs = [s for s in sigs if s.get("slot") == c_slot]
        s0_sigs_sorted = sorted(s0_sigs, key=lambda x: x.get("transactionIndex", 0))

        for s in s0_sigs_sorted:
            sig = s["signature"]
            if sig == mig_sig:
                # Skip the pool migration/creation tx itself; count only S+0 post-creation txs
                continue

            sig_slot = s.get("slot")
            assert sig_slot == c_slot, f"Signature slot {sig_slot} != creation_slot {c_slot} for pool {pool}"

            tx = get_tx(sig)
            tx_slot = tx.get("slot")
            assert tx_slot == c_slot, f"Fixture slot {tx_slot} != creation_slot {c_slot} for tx {sig}"

            order_in_slot = s.get("transactionIndex", 0)
            signer = extract_signer(tx)
            meta = tx.get("meta") or {}
            err = meta.get("err")
            is_success = err is None

            logs = meta.get("logMessages") or []
            has_pamm = any(PUMPSWAP_PROGRAM in l for l in logs)
            has_swap = any(
                k in l.lower()
                for l in logs
                for k in [
                    "instruction: buy",
                    "instruction: sell",
                    "instruction: swap",
                    "instruction: buyexactquotein",
                    "instruction: buyexactquoteinv2",
                    "program return: pfee",
                ]
            )

            # Skip non-pAMM successful transfers (e.g. AssociatedTokenAccount create without swap)
            if is_success and not (has_pamm and has_swap):
                continue

            sol_in = 0.0
            tok_out = 0.0
            if is_success:
                pre_tb = meta.get("preTokenBalances") or []
                post_tb = meta.get("postTokenBalances") or []
                pre_wsol, post_wsol = 0.0, 0.0
                pre_tok, post_tok = 0.0, 0.0

                for tb in pre_tb:
                    if tb.get("owner") == pool:
                        if tb.get("mint") == WSOL:
                            pre_wsol = float(tb.get("uiTokenAmount", {}).get("uiAmount") or 0.0)
                        elif tb.get("mint") == mint:
                            pre_tok = float(tb.get("uiTokenAmount", {}).get("uiAmount") or 0.0)

                for tb in post_tb:
                    if tb.get("owner") == pool:
                        if tb.get("mint") == WSOL:
                            post_wsol = float(tb.get("uiTokenAmount", {}).get("uiAmount") or 0.0)
                        elif tb.get("mint") == mint:
                            post_tok = float(tb.get("uiTokenAmount", {}).get("uiAmount") or 0.0)

                sol_in = round(post_wsol - pre_wsol, 6)
                tok_out = round(pre_tok - post_tok, 2)

            csv_rows.append({
                "pool": pool,
                "signature": sig,
                "signer": signer,
                "slot": tx_slot,
                "order_in_slot": order_in_slot,
                "sol_in": f"{sol_in:.6f}",
                "tokens_out": f"{tok_out:.2f}",
                "success": str(is_success),
            })

    fieldnames = ["pool", "signature", "signer", "slot", "order_in_slot", "sol_in", "tokens_out", "success"]
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(csv_rows)

    # Read back strictly from the CSV to compute per-pool and per-signer statistics
    with open(csv_path, "r", encoding="utf-8") as f:
        loaded_rows = list(csv.DictReader(f))

    print("=" * 120)
    print(f"S+0 ALL-34-POOLS AUDIT (Generated from {csv_path} with slot == creation_slot assertion)")
    print(f"Total S+0 Swap Transactions in CSV: {len(loaded_rows)} "
          f"(Success: {sum(1 for r in loaded_rows if r['success'] == 'True')}, "
          f"Failed: {sum(1 for r in loaded_rows if r['success'] == 'False')})")
    print("=" * 120)

    target_rows = [1, 4, 24, 2, 11, 5, 15]
    print("\n--- TARGET CLUSTERS SUCCESSFUL S+0 SWAPS (Rows 1, 4, 24 | Rows 2, 11 | Rows 5, 15) ---")
    for r_idx in target_rows:
        r_meta = next(r for r in reached_pools if r["index"] == r_idx)
        pool = r_meta["pool_address"]
        c_slot = r_meta["creation_slot"]
        p_rows = [x for x in loaded_rows if x["pool"] == pool and x["success"] == "True"]
        tot_buy_sol = sum(float(x["sol_in"]) for x in p_rows if float(x["sol_in"]) > 0)
        print(f"\nRow {r_idx:2d} | Pool: {pool} | Creation Slot: {c_slot} | Total S+0 Buy SOL: {tot_buy_sol:.6f}")
        print(f"  {'SLOT':<10} | {'ORDER':<6} | {'SIGNER':<44} | {'SOL IN':<14} | {'TOKENS OUT':<16} | {'SIGNATURE'}")
        print("  " + "-" * 114)
        for x in p_rows:
            assert int(x["slot"]) == c_slot
            print(f"  {int(x['slot']):<10d} | {int(x['order_in_slot']):6d} | {x['signer']:<44} | "
                  f"{float(x['sol_in']):10.6f} SOL | {float(x['tokens_out']):16,.2f} | {x['signature']}")

    print("\n" + "=" * 120)
    print("ALL 31 SUCCESSFUL S+0 SWAPS ACROSS ALL 34 POOLS (FROM CSV):")
    print("=" * 120)
    print(f"{'ROW':<4} | {'POOL':<44} | {'SLOT':<10} | {'ORDER':<5} | {'SIGNER':<44} | {'SOL IN':<12} | {'TOKENS OUT':<15} | {'SIGNATURE'}")
    print("-" * 160)
    for x in loaded_rows:
        if x["success"] == "True":
            r_idx = pool_row_map[x["pool"]]
            print(f"{r_idx:<4d} | {x['pool']:<44} | {int(x['slot']):<10d} | {int(x['order_in_slot']):5d} | "
                  f"{x['signer']:<44} | {float(x['sol_in']):12.6f} | {float(x['tokens_out']):15,.2f} | {x['signature']}")

    # Compute per-signer recurrence and total SOL from CSV
    signer_succ_pools = defaultdict(list)
    signer_succ_sol = defaultdict(float)
    signer_succ_txs = defaultdict(int)
    signer_fail_txs = defaultdict(int)
    signer_fail_pools = defaultdict(list)

    for x in loaded_rows:
        sgn = x["signer"]
        r_idx = pool_row_map[x["pool"]]
        if x["success"] == "True":
            signer_succ_txs[sgn] += 1
            signer_succ_sol[sgn] += float(x["sol_in"])
            signer_succ_pools[sgn].append(r_idx)
        else:
            signer_fail_txs[sgn] += 1
            signer_fail_pools[sgn].append(r_idx)

    all_signers = sorted(
        set(list(signer_succ_txs.keys()) + list(signer_fail_txs.keys())),
        key=lambda s: (-signer_succ_sol[s], -signer_succ_txs[s], -signer_fail_txs[s])
    )

    print("\n" + "=" * 120)
    print("PER-SIGNER RECURRENCE & TOTAL SOL IN S+0 ACROSS ALL 34 POOLS (COMPUTED FROM CSV):")
    print("=" * 120)
    print(f"{'SIGNER':<44} | {'SUCC TXS':<8} | {'FAIL TXS':<8} | {'TOTAL NET SOL IN':<16} | {'SUCC ROWS':<24} | {'FAIL ROWS'}")
    print("-" * 120)
    for sgn in all_signers:
        print(f"{sgn:<44} | {signer_succ_txs[sgn]:<8d} | {signer_fail_txs[sgn]:<8d} | "
              f"{signer_succ_sol[sgn]:12.6f} SOL | {str(sorted(set(signer_succ_pools[sgn]))):<24} | "
              f"{str(sorted(set(signer_fail_pools[sgn])))}")


if __name__ == "__main__":
    main()

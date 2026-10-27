"""
Audit S+0 clusters for rows 1, 4, 24 (8.863x), rows 2, 11 (8.589x), and rows 5, 15 (7.532x).
Prints every successful S+0 swap: signer, SOL in, tokens out, order in slot, pool total S+0 buy SOL,
and analyzes recurrence of signers across pools.
"""

import json
from pathlib import Path

PUMPSWAP_PROGRAM = "pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA"
WSOL = "So11111111111111111111111111111111111111112"

TARGET_ROWS = [1, 4, 24, 2, 11, 5, 15]


def get_tx(sig: str) -> dict:
    p1 = Path(f"tests/fixtures/txs/{sig}.json")
    if p1.exists():
        return json.load(open(p1, encoding="utf-8"))
    p2 = Path(f"data/retrospective_cache/txs/{sig}.json")
    if p2.exists():
        return json.load(open(p2, encoding="utf-8"))
    raise FileNotFoundError(f"Missing fixture {sig}")


def main():
    with open("reports/retrospective_report.json", encoding="utf-8") as f:
        retro = json.load(f)

    table = retro["per_migration_table"]
    all_swaps = []
    signer_pools = {}
    signer_buy_amounts = {}

    for r_idx in TARGET_ROWS:
        r = table[r_idx - 1]
        pool = r["pool_address"]
        mint = r["mint"]
        c_slot = r["creation_slot"]
        sig_path = Path(f"data/retrospective_cache/pool_sigs/{pool}.json")
        sigs = json.load(open(sig_path, encoding="utf-8"))

        s0_sigs = [s for s in sigs if s.get("slot", 0) == c_slot]
        s0_sigs_sorted = sorted(s0_sigs, key=lambda x: x.get("transactionIndex", 0))

        pool_total_sol_in = 0.0
        pool_swaps = []

        for s in s0_sigs_sorted:
            sig = s["signature"]
            tx_idx = s.get("transactionIndex", 0)
            try:
                tx = get_tx(sig)
            except Exception:
                continue

            meta = tx.get("meta") or {}
            if meta.get("err") is not None:
                continue

            logs = meta.get("logMessages") or []
            has_pamm = any(PUMPSWAP_PROGRAM in l for l in logs)
            has_swap = any(k in l.lower() for l in logs for k in [
                "instruction: buy", "instruction: sell", "instruction: swap",
                "instruction: buyexactquotein", "instruction: buyexactquoteinv2",
                "program return: pfee"
            ])
            if not (has_pamm and has_swap):
                continue

            signer = tx["transaction"]["message"]["accountKeys"][0]

            pre_tb = meta.get("preTokenBalances") or []
            post_tb = meta.get("postTokenBalances") or []

            pre_wsol = 0.0
            post_wsol = 0.0
            pre_tok = 0.0
            post_tok = 0.0

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

            sol_in = post_wsol - pre_wsol
            tok_out = pre_tok - post_tok

            if sol_in > 0:
                pool_total_sol_in += sol_in
                pool_swaps.append({
                    "row": r_idx,
                    "pool": pool,
                    "signature": sig,
                    "order": tx_idx,
                    "signer": signer,
                    "sol_in": round(sol_in, 6),
                    "tok_out": round(tok_out, 2),
                })
                signer_pools.setdefault(signer, set()).add(r_idx)
                signer_buy_amounts.setdefault(signer, []).append(round(sol_in, 4))

        all_swaps.append((r_idx, pool, pool_total_sol_in, pool_swaps))

    print("=" * 115)
    print("S+0 CLUSTER DETAILED SWAP AUDIT (Review 6 Item 4)")
    print("Clusters: 8.863x (Rows 1, 4, 24) | 8.589x (Rows 2, 11) | 7.532x (Rows 5, 15)")
    print("=" * 115)

    for r_idx, pool, tot_sol, swaps in all_swaps:
        print(f"\n--- ROW {r_idx}: Pool {pool} | Total S+0 Buy SOL: {tot_sol:.6f} SOL ---")
        print(f"  {'ORDER':<6} | {'SIGNER':<44} | {'SOL IN':<14} | {'TOKENS OUT':<18} | {'SIGNATURE'}")
        print("  " + "-" * 110)
        for sw in swaps:
            print(f"  {sw['order']:6d} | {sw['signer']:44} | {sw['sol_in']:10.6f} SOL | {sw['tok_out']:16,.2f} | {sw['signature']}")

    print("\n" + "=" * 115)
    print("SIGNER RECURRENCE & FIXED-SIZE HYPOTHESIS ANALYSIS:")
    print("=" * 115)
    for s, rows_seen in signer_pools.items():
        amts = signer_buy_amounts[s]
        print(f"  Signer: {s}")
        print(f"    - Recurred in Rows: {sorted(list(rows_seen))}")
        print(f"    - Observed Buy Sizes (SOL): {amts}")


if __name__ == "__main__":
    main()

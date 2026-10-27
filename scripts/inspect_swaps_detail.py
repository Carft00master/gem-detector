import json
import os
import struct
import base64

with open('reports/boost_replay_report.json', 'r', encoding='utf-8') as f:
    d = json.load(f)

swaps = d['swaps_replay_table']

print("--- ROWS 2, 3, 4, 11, 12, 22 (Buys with lp=20) ---")
for idx in [1, 2, 3, 10, 11, 21]:
    s = swaps[idx]
    print(f"Row {idx+1}: sig={s['signature']}")
    print(f"   pool={s['pool_address']}, side={s['side']}, fee={s['fee_return_bps']}, err_b={s['error_vault_plus_boost_pct']}%, err_a={s['error_vault_only_pct']}%")

print("\n--- DETAILED INSPECTION OF ROWS 5, 17, 18, 23, 24, 25 ---")
indices = [4, 16, 17, 22, 23, 24]  # 1-based 5, 17, 18, 23, 24, 25
for idx in indices:
    s = swaps[idx]
    sig = s["signature"]
    pool = s["pool_address"]
    side = s["side"]
    fee = s["fee_return_bps"]
    err_b = s["error_vault_plus_boost_pct"]
    err_a = s["error_vault_only_pct"]
    print(f"\n=======================================================")
    print(f"Row {idx+1}: sig={sig}")
    print(f"Pool: {pool} | Side: {side} | Logged Fee: {fee}")
    print(f"Vault SOL Pre: {s['pre_swap_vault_sol']} -> Post: {s['post_swap_vault_sol']} (Delta: {s['post_swap_vault_sol'] - s['pre_swap_vault_sol']})")
    print(f"Vault Tok Pre: {s['pre_swap_vault_tokens']} -> Post: {s['post_swap_vault_tokens']} (Delta: {s['post_swap_vault_tokens'] - s['pre_swap_vault_tokens']})")
    print(f"Vault-Only Err: {err_a}% | Vault+Boost Err: {err_b}%")

    tx_path = f"tests/fixtures/txs/{sig}.json"
    if os.path.exists(tx_path):
        with open(tx_path, "r", encoding="utf-8") as tf:
            tx = json.load(tf)
        meta = tx.get("meta", {})
        logs = meta.get("logMessages", [])
        print("Log messages:")
        for l in logs:
            if any(k in l for k in ["Instruction:", "Program return:", "Transfer", "pfee", "swap", "Swap"]):
                print("   ", l)

        # Inspect inner instructions
        inner_ixs = meta.get("innerInstructions", [])
        print(f"Inner instructions groups: {len(inner_ixs)}")
        for g in inner_ixs:
            for ix in g.get("instructions", []):
                prog = ix.get("programId") or ix.get("program")
                # print program if relevant

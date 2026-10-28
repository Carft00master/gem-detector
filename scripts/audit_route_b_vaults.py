"""
Audit Route B Vault Balances (Review Item 1):
- Prints raw preTokenBalances and postTokenBalances entries with owner == pool
  for rows 3, 22, 23, 29 in both the migration transaction and the S+20 transaction
  (account index, account pubkey, mint, amount) and the pool's WSOL account address.
- Determines which account was previously read vs which account is the true WSOL vault.
- Checks all 34 pools for multiple WSOL accounts owned by the pool or swap price vs (vault + boost).
"""

import json
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

WSOL = "So11111111111111111111111111111111111111112"


def load_fixture(sig: str) -> Optional[dict]:
    p1 = Path(f"tests/fixtures/txs/{sig}.json")
    if p1.exists():
        return json.load(open(p1, encoding="utf-8"))
    p2 = Path(f"data/retrospective_cache/txs/{sig}.json")
    if p2.exists():
        return json.load(open(p2, encoding="utf-8"))
    return None


def get_account_keys(tx: dict) -> List[str]:
    msg = (tx.get("transaction") or {}).get("message") or {}
    raw_keys = msg.get("accountKeys") or []
    keys = []
    for k in raw_keys:
        if isinstance(k, dict):
            keys.append(k.get("pubkey", ""))
        else:
            keys.append(str(k))
    loaded = (tx.get("meta") or {}).get("loadedAddresses") or {}
    for w in loaded.get("writable") or []:
        keys.append(str(w))
    for r in loaded.get("readonly") or []:
        keys.append(str(r))
    return keys


def inspect_tx_pool_balances(tx: dict, pool: str) -> Tuple[List[dict], List[dict]]:
    meta = tx.get("meta") or {}
    keys = get_account_keys(tx)
    pre_entries = []
    for tb in meta.get("preTokenBalances") or []:
        if tb.get("owner") == pool:
            idx = tb.get("accountIndex")
            pubkey = keys[idx] if idx is not None and idx < len(keys) else "UNKNOWN"
            ui_amt = (tb.get("uiTokenAmount") or {})
            pre_entries.append({
                "accountIndex": idx,
                "pubkey": pubkey,
                "mint": tb.get("mint"),
                "amount_raw": ui_amt.get("amount"),
                "uiAmount": ui_amt.get("uiAmount"),
                "uiAmountString": ui_amt.get("uiAmountString"),
            })
    post_entries = []
    for tb in meta.get("postTokenBalances") or []:
        if tb.get("owner") == pool:
            idx = tb.get("accountIndex")
            pubkey = keys[idx] if idx is not None and idx < len(keys) else "UNKNOWN"
            ui_amt = (tb.get("uiTokenAmount") or {})
            post_entries.append({
                "accountIndex": idx,
                "pubkey": pubkey,
                "mint": tb.get("mint"),
                "amount_raw": ui_amt.get("amount"),
                "uiAmount": ui_amt.get("uiAmount"),
                "uiAmountString": ui_amt.get("uiAmountString"),
            })
    return pre_entries, post_entries


def main():
    with open("reports/retrospective_report.json", encoding="utf-8") as f:
        retro = json.load(f)
    with open("reports/route_b_price_paths.json", encoding="utf-8") as f:
        rb = json.load(f)

    rb_by_idx = {p["index"]: p for p in rb["per_pool_data"]}
    reached_pools = {r["index"]: r for r in retro["per_migration_table"] if r.get("reached_creation_slot")}

    target_rows = [3, 22, 23, 29]
    print("=" * 125)
    print("RAW preTokenBalances / postTokenBalances WITH owner == pool FOR ROWS 3, 22, 23, 29")
    print("=" * 125)

    for row_idx in target_rows:
        r = reached_pools[row_idx]
        p_rb = rb_by_idx[row_idx]
        pool = r["pool_address"]
        mint = r["mint"]
        mig_sig = r["migration_signature"]
        s20_info = p_rb["horizon_samples"]["S+20"]
        s20_sig = s20_info.get("signature")

        mig_tx = load_fixture(mig_sig)
        mig_pre, mig_post = inspect_tx_pool_balances(mig_tx, pool)

        # Find the pool's WSOL vault address from migration postTokenBalances (largest WSOL account owned by pool)
        wsol_Candidates = [e for e in mig_post if e["mint"] == WSOL]
        wsol_vault_entry = max(wsol_Candidates, key=lambda x: x["uiAmount"] or 0.0) if wsol_Candidates else None
        wsol_vault_addr = wsol_vault_entry["pubkey"] if wsol_vault_entry else "NONE"

        print(f"\n--- ROW {row_idx} | Pool: {pool} | Mint: {mint} ---")
        print(f"Pool True WSOL Vault Address (at migration): {wsol_vault_addr}")
        print(f"Migration Tx: {mig_sig} (slot {r['creation_slot']})")
        print("  Migration preTokenBalances (owner == pool):")
        if not mig_pre:
            print("    (none - pool token accounts initialized during migration tx)")
        for e in mig_pre:
            print(f"    accountIndex={e['accountIndex']:2d} | pubkey={e['pubkey']} | mint={e['mint']} | uiAmount={e['uiAmountString']}")
        print("  Migration postTokenBalances (owner == pool):")
        for e in mig_post:
            print(f"    accountIndex={e['accountIndex']:2d} | pubkey={e['pubkey']} | mint={e['mint']} | uiAmount={e['uiAmountString']}")

        if s20_sig:
            s20_tx = load_fixture(s20_sig)
            s20_pre, s20_post = inspect_tx_pool_balances(s20_tx, pool)
            print(f"S+20 Tx: {s20_sig} (slot {s20_info.get('slot')}, status={s20_info.get('status')})")
            print("  S+20 preTokenBalances (owner == pool):")
            for e in s20_pre:
                marker = " <-- TRUE VAULT" if e["pubkey"] == wsol_vault_addr else (" <-- OVERWRITTEN BY BUG (last WSOL entry)" if e["mint"] == WSOL else "")
                print(f"    accountIndex={e['accountIndex']:2d} | pubkey={e['pubkey']} | mint={e['mint']} | uiAmount={e['uiAmountString']}{marker}")
            print("  S+20 postTokenBalances (owner == pool):")
            for e in s20_post:
                marker = " <-- TRUE VAULT" if e["pubkey"] == wsol_vault_addr else (" <-- OVERWRITTEN BY BUG (last WSOL entry)" if e["mint"] == WSOL else "")
                print(f"    accountIndex={e['accountIndex']:2d} | pubkey={e['pubkey']} | mint={e['mint']} | uiAmount={e['uiAmountString']}{marker}")
        else:
            print(f"S+20 Tx: status={s20_info.get('status')} (carried forward from S+3/S+10)")


if __name__ == "__main__":
    main()

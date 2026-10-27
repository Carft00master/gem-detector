import os
import json
import sqlite3

conn = sqlite3.connect('data/onchain_events.db')
cur = conn.cursor()
rows = cur.execute("SELECT mint, signature, slot FROM onchain_events WHERE event_type = 'MIGRATION'").fetchall()
conn.close()

pools_info = []
for idx, (mint, mig_sig, db_slot) in enumerate(rows):
    tx_path = f"tests/fixtures/txs/{mig_sig}.json"
    creation_slot = None
    pool_addr = None
    if os.path.exists(tx_path):
        with open(tx_path, "r", encoding="utf-8") as f:
            tx_obj = json.load(f)
        creation_slot = tx_obj.get("slot")
        meta = tx_obj.get("meta") or {}
        candidates = {}
        for tb in meta.get("postTokenBalances", []):
            owner = tb.get("owner")
            amt = (tb.get("uiTokenAmount", {}) or {}).get("uiAmount") or 0
            if tb.get("mint") == mint and amt > 50_000_000:
                candidates[owner] = amt
        if candidates:
            pool_addr = max(candidates, key=candidates.get)

    pool_fixture = f"tests/fixtures/pools/{pool_addr}.json" if pool_addr else None
    has_pool_fixture = os.path.exists(pool_fixture) if pool_fixture else False

    # Check pool sigs
    sig_cache = f"scratch/audit_cache/pool_sigs/{pool_addr}.json" if pool_addr else None
    has_sig_cache = os.path.exists(sig_cache) if sig_cache else False
    min_sig_slot = None
    sig_count = 0
    if has_sig_cache:
        with open(sig_cache, "r", encoding="utf-8") as f:
            sigs = json.load(f)
        sig_count = len(sigs)
        if sigs:
            min_sig_slot = min(s.get("slot", 999999999) for s in sigs)

    reached_creation = (min_sig_slot is not None and creation_slot is not None and min_sig_slot <= creation_slot)

    pools_info.append({
        "row": idx + 1,
        "mint": mint,
        "mig_sig": mig_sig,
        "creation_slot": creation_slot,
        "pool_addr": pool_addr,
        "has_pool_fixture": has_pool_fixture,
        "sig_count": sig_count,
        "min_sig_slot": min_sig_slot,
        "reached_creation": reached_creation,
    })

print(f"Analyzed {len(pools_info)} migrations:")
reached = [p for p in pools_info if p["reached_creation"]]
print(f"Pools where signatures reached creation slot: {len(reached)}")
for r in reached:
    print(f"   Row {r['row']}: pool={r['pool_addr']}, creation_slot={r['creation_slot']}, min_sig_slot={r['min_sig_slot']}, sig_count={r['sig_count']}")

unreached = [p for p in pools_info if not p["reached_creation"]]
print(f"Pools where signatures did NOT reach creation slot (or not fetched): {len(unreached)}")
for u in unreached[:5]:
    print(f"   Row {u['row']}: pool={u['pool_addr']}, creation_slot={u['creation_slot']}, min_sig_slot={u['min_sig_slot']}, sig_count={u['sig_count']}")

import json
import os

with open("reports/retrospective_report.json", encoding="utf-8") as f:
    retro = json.load(f)

for r in retro["per_migration_table"]:
    pool = r["pool_address"]
    c_slot = r["creation_slot"]
    sig_path = f"data/retrospective_cache/pool_sigs/{pool}.json"
    if not os.path.exists(sig_path):
        continue
    sigs = json.load(open(sig_path, encoding="utf-8"))
    s0_sigs = [s for s in sigs if s.get("slot") == c_slot]
    if s0_sigs:
        print(f"Row {r['index']} (c_slot={c_slot}): {len(s0_sigs)} sigs in S+0")
        for s in s0_sigs:
            sig = s["signature"]
            tx_path = f"tests/fixtures/txs/{sig}.json"
            if os.path.exists(tx_path):
                tx = json.load(open(tx_path, encoding="utf-8"))
                err = tx.get("meta", {}).get("err")
                logs = tx.get("meta", {}).get("logMessages", [])
                has_pamm = any("pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA" in l for l in logs)
                print(f"   {sig[:16]}... err={err is not None} has_pamm={has_pamm}")
            else:
                print(f"   {sig[:16]}... NOT IN FIXTURES")

import sqlite3
import json
import os

conn = sqlite3.connect('data/onchain_events.db')
cur = conn.cursor()
rows = cur.execute("SELECT mint, signature, slot FROM onchain_events WHERE event_type = 'MIGRATION'").fetchall()
conn.close()

zero_slots = [r for r in rows if r[2] == 0]
print(f"Total migration rows in db: {len(rows)}, with slot == 0: {len(zero_slots)}")

non_zero_from_fixtures = 0
for r in rows:
    mint, sig, slot = r
    tx_path = f"tests/fixtures/txs/{sig}.json"
    if os.path.exists(tx_path):
        with open(tx_path, "r", encoding="utf-8") as f:
            d = json.load(f)
        s = d.get("slot")
        if s and s > 0:
            non_zero_from_fixtures += 1
            # print first 3
            if non_zero_from_fixtures <= 3:
                print(f"Sample: sig={sig}, db_slot={slot}, fixture_slot={s}")
print(f"Fixtures with slot > 0: {non_zero_from_fixtures}/{len(rows)}")

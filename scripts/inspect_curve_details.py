import sqlite3
import json

conn = sqlite3.connect("file:data/onchain_events.db?mode=ro", uri=True)
cur = conn.cursor()
cur.execute("SELECT details_json FROM onchain_events WHERE event_type='CURVE_CREATE' LIMIT 5;")
for r in cur.fetchall():
    d = json.loads(r[0])
    for k, v in d.items():
        print(f"  {k}: {v}")
    print("-" * 40)
conn.close()

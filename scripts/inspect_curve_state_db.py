import sqlite3
import json

conn = sqlite3.connect("file:data/onchain_events.db?mode=ro", uri=True)
cur = conn.cursor()

# Get all column names
cur.execute("PRAGMA table_info(onchain_events);")
cols = [c[1] for c in cur.fetchall()]
print("Columns:", cols)

# Distinct event types
cur.execute("SELECT event_type, count(*) FROM onchain_events GROUP BY event_type;")
for r in cur.fetchall():
    print("Event type:", r)

# Check a few rows of CURVE_CREATE and MIGRATION
cur.execute("SELECT event_id, event_type, slot, block_time, mint, wallet, side, sol_amount, token_amount, sol_reserves_after, token_reserves_after, details_json FROM onchain_events WHERE event_type='CURVE_CREATE' LIMIT 3;")
print("\nSample CURVE_CREATE:")
for r in cur.fetchall():
    print(r[:11])
    try:
        dj = json.loads(r[11])
        print("   details keys:", list(dj.keys()))
    except:
        pass

cur.execute("SELECT event_id, event_type, slot, block_time, mint, wallet, side, sol_amount, token_amount, sol_reserves_after, token_reserves_after, details_json FROM onchain_events WHERE event_type='MIGRATION' LIMIT 3;")
print("\nSample MIGRATION:")
for r in cur.fetchall():
    print(r[:11])
    try:
        dj = json.loads(r[11])
        print("   details keys:", list(dj.keys()))
    except:
        pass

conn.close()

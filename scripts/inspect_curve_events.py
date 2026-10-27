import sqlite3
import json

conn = sqlite3.connect("file:data/onchain_events.db?mode=ro", uri=True)
cur = conn.cursor()

# Event types
cur.execute("SELECT event_type, count(*) FROM onchain_events GROUP BY event_type;")
for row in cur.fetchall():
    print(f"Event type: {row[0]} -> {row[1]}")

# Distinct mints
cur.execute("SELECT count(DISTINCT mint) FROM onchain_events;")
print(f"Distinct mints: {cur.fetchone()[0]}")

# Sample events
cur.execute("SELECT event_type, mint, wallet, side, sol_amount, token_amount, sol_reserves_after, token_reserves_after, details_json FROM onchain_events LIMIT 5;")
for r in cur.fetchall():
    print(r)

conn.close()

import sqlite3
import json

conn = sqlite3.connect("file:data/onchain_events.db?mode=ro", uri=True)
cur = conn.cursor()

cur.execute("SELECT mint, event_type, count(*) FROM onchain_events GROUP BY mint, event_type;")
rows = cur.fetchall()
print(f"Total mint x event_type pairs: {len(rows)}")

mints_with_multiple = {}
for m, et, cnt in rows:
    mints_with_multiple[m] = mints_with_multiple.get(m, 0) + cnt

multi_events = {m: c for m, c in mints_with_multiple.items() if c > 1}
print(f"Mints with multiple events: {len(multi_events)}")
for m, c in list(multi_events.items())[:5]:
    cur.execute("SELECT event_type, side, sol_amount, token_amount, sol_reserves_after, token_reserves_after, details_json FROM onchain_events WHERE mint=?", (m,))
    print(f"\nMint {m}: {c} events")
    for r in cur.fetchall():
        print(r[:6])

conn.close()

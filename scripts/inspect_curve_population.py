import sqlite3
import json

conn = sqlite3.connect("file:data/onchain_events.db?mode=ro", uri=True)
cur = conn.cursor()

cur.execute("SELECT mint, wallet, sol_amount, token_amount, sol_reserves_after, token_reserves_after, details_json FROM onchain_events WHERE event_type='CURVE_CREATE';")
create_rows = cur.fetchall()

print(f"Total CURVE_CREATE events: {len(create_rows)}")

# Analyze initial buy distribution and curve metrics
initial_buys = []
creator_holding_pcts = []
curve_progress_pcts = []

for r in create_rows:
    mint, wallet, sol_amt, tok_amt, sol_after, tok_after, dj_str = r
    d = json.loads(dj_str)
    init_buy = float(d.get("initialBuy", 0.0))
    # Total token supply is 1,000,000,000
    creator_pct = (init_buy / 1_000_000_000.0) * 100.0
    # Real sol reserve = vSol - 30.0
    vsol = float(d.get("vSolInBondingCurve", 30.0))
    real_sol = max(0.0, vsol - 30.0)
    # Target migration real SOL is 85.0 SOL
    progress = min(100.0, (real_sol / 85.0) * 100.0)
    
    initial_buys.append(init_buy)
    creator_holding_pcts.append(creator_pct)
    curve_progress_pcts.append(progress)

print(f"Zero initial buy count: {sum(1 for b in initial_buys if b == 0)}")
print(f"Non-zero initial buy count: {sum(1 for b in initial_buys if b > 0)}")
print(f"Max creator holding: {max(creator_holding_pcts):.2f}%")
print(f"Min creator holding: {min(creator_holding_pcts):.2f}%")
print(f"Mean creator holding: {sum(creator_holding_pcts)/len(creator_holding_pcts):.2f}%")

# Now check MIGRATION events
cur.execute("SELECT mint, details_json FROM onchain_events WHERE event_type='MIGRATION';")
mig_rows = cur.fetchall()
print(f"\nTotal MIGRATION events: {len(mig_rows)}")

conn.close()

import sqlite3
import pandas as pd
import numpy as np

# Connect to both databases
with sqlite3.connect("data/virtual_wallet.db") as conn_w:
    df_w = pd.read_sql_query("SELECT * FROM wallet_positions WHERE session_id = 'sess_4e197856' AND status = 'CLOSED'", conn_w)

with sqlite3.connect("data/paper_trading.db") as conn_p:
    df_p = pd.read_sql_query("SELECT * FROM paper_trades WHERE status = 'CLOSED'", conn_p)

print(f"Loaded {len(df_w)} closed trades from active wallet session sess_4e197856")
print(f"Loaded {len(df_p)} closed paper trades")

# Let's inspect recent paper trades (from 2026-10-05 onwards)
df_p_recent = df_p[df_p["timestamp"] >= "2026-10-05"].copy()
print(f"Recent paper trades (since 2026-10-05): {len(df_p_recent)}")

# Let's inspect the columns of both to join or merge features if needed
print("Wallet columns:", df_w.columns.tolist())
print("Paper columns:", df_p.columns.tolist())

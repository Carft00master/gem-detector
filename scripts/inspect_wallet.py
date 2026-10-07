import sqlite3
import pandas as pd

with sqlite3.connect("data/virtual_wallet.db") as conn:
    df_sessions = pd.read_sql_query("SELECT * FROM wallet_sessions", conn)
    print("=== SESSIONS ===")
    print(df_sessions[["session_id", "name", "starting_capital_usd", "current_cash_usd", "current_equity_usd", "is_active", "created_at"]])
    
    df_pos = pd.read_sql_query("SELECT * FROM wallet_positions", conn)
    print("\n=== WALLET POSITIONS ===")
    print(f"Total positions: {len(df_pos)}")
    print(df_pos["status"].value_counts())
    
    closed = df_pos[df_pos["status"] == "CLOSED"]
    print(f"Closed positions: {len(closed)}")
    print(f"Total Net PnL: ${closed['net_realized_pnl_usd'].sum():,.2f}")
    
    for s_id, s_df in closed.groupby("session_id"):
        s_name = df_sessions[df_sessions["session_id"] == s_id]["name"].values[0] if len(df_sessions[df_sessions["session_id"] == s_id]) else "Unknown"
        wins = s_df[s_df["net_realized_pnl_usd"] > 0]
        losses = s_df[s_df["net_realized_pnl_usd"] <= 0]
        print(f"\nSession {s_id} ({s_name}):")
        print(f"  Trades: {len(s_df)} | Wins: {len(wins)} ({len(wins)/len(s_df)*100:.1f}%) | Losses: {len(losses)} ({len(losses)/len(s_df)*100:.1f}%)")
        print(f"  Win PnL: +${wins['net_realized_pnl_usd'].sum():,.2f} | Loss PnL: -${abs(losses['net_realized_pnl_usd'].sum()):,.2f} | Net: ${s_df['net_realized_pnl_usd'].sum():,.2f}")

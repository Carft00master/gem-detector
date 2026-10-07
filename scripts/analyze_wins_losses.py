import sqlite3
import pandas as pd
import numpy as np
import json
from datetime import datetime

print("Loading data from paper_trading.db and virtual_wallet.db...")

# 1. Virtual Wallet Trades
wallet_trades = []
with sqlite3.connect("data/virtual_wallet.db") as conn:
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    # Get active session
    sessions = cur.execute("SELECT * FROM wallet_sessions ORDER BY created_at DESC").fetchall()
    print(f"Virtual Wallet Sessions: {len(sessions)}")
    for s in sessions:
        print(f"  Session {s['session_id']} ({s['session_name']}): Status={s['status']}, Initial={s['initial_capital_usd']}, Current={s['current_capital_usd']}")
    
    w_rows = cur.execute("SELECT * FROM wallet_trades ORDER BY opened_at ASC").fetchall()
    print(f"Total Virtual Wallet Trades: {len(w_rows)}")
    for r in w_rows:
        wallet_trades.append(dict(r))

df_wallet = pd.DataFrame(wallet_trades) if wallet_trades else pd.DataFrame()

# 2. Paper Trades
paper_trades = []
with sqlite3.connect("data/paper_trading.db") as conn:
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    p_rows = cur.execute("SELECT * FROM paper_trades ORDER BY timestamp ASC").fetchall()
    print(f"Total Paper Trades in paper_trading.db: {len(p_rows)}")
    for r in p_rows:
        paper_trades.append(dict(r))

df_paper = pd.DataFrame(paper_trades) if paper_trades else pd.DataFrame()

print(f"Loaded {len(df_wallet)} wallet trades and {len(df_paper)} paper trades.")

# Focus on closed trades
if not df_wallet.empty:
    closed_wallet = df_wallet[df_wallet["status"] == "CLOSED"].copy()
    print(f"\n--- VIRTUAL WALLET CLOSED TRADES: {len(closed_wallet)} ---")
    wins_w = closed_wallet[closed_wallet["net_pnl_usd"] > 0]
    losses_w = closed_wallet[closed_wallet["net_pnl_usd"] <= 0]
    print(f"Wins: {len(wins_w)} ({len(wins_w)/len(closed_wallet)*100:.1f}%) | Total Win PnL: +${wins_w['net_pnl_usd'].sum():,.2f}")
    print(f"Losses: {len(losses_w)} ({len(losses_w)/len(closed_wallet)*100:.1f}%) | Total Loss PnL: -${abs(losses_w['net_pnl_usd'].sum()):,.2f}")
    print(f"Net PnL: ${closed_wallet['net_pnl_usd'].sum():,.2f}")

if not df_paper.empty:
    closed_paper = df_paper[df_paper["status"] == "CLOSED"].copy()
    print(f"\n--- ALL PAPER CLOSED TRADES: {len(closed_paper)} ---")
    wins_p = closed_paper[closed_paper["net_realized_pnl_usd"] > 0]
    losses_p = closed_paper[closed_paper["net_realized_pnl_usd"] <= 0]
    print(f"Wins: {len(wins_p)} ({len(wins_p)/len(closed_paper)*100:.1f}%) | Total Win PnL: +${wins_p['net_realized_pnl_usd'].sum():,.2f}")
    print(f"Losses: {len(losses_p)} ({len(losses_p)/len(closed_paper)*100:.1f}%) | Total Loss PnL: -${abs(losses_p['net_realized_pnl_usd'].sum()):,.2f}")
    print(f"Net PnL: ${closed_paper['net_realized_pnl_usd'].sum():,.2f}")

    # Also look at recent trades (e.g. October 2026 or Selector V2.2 trades)
    v22_paper = closed_paper[closed_paper["entry_reason"].str.contains("SELECTOR_V2_2", na=False)].copy()
    print(f"\n--- SELECTOR V2.2 CLOSED TRADES: {len(v22_paper)} ---")
    if not v22_paper.empty:
        v22_wins = v22_paper[v22_paper["net_realized_pnl_usd"] > 0]
        v22_losses = v22_paper[v22_paper["net_realized_pnl_usd"] <= 0]
        print(f"V2.2 Wins: {len(v22_wins)} ({len(v22_wins)/len(v22_paper)*100:.1f}%) | Total Win PnL: +${v22_wins['net_realized_pnl_usd'].sum():,.2f}")
        print(f"V2.2 Losses: {len(v22_losses)} ({len(v22_losses)/len(v22_paper)*100:.1f}%) | Total Loss PnL: -${abs(v22_losses['net_realized_pnl_usd'].sum()):,.2f}")
        print(f"V2.2 Net PnL: ${v22_paper['net_realized_pnl_usd'].sum():,.2f}")

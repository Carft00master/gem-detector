import sqlite3
import pandas as pd
import numpy as np
import sys

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

with sqlite3.connect("data/virtual_wallet.db") as conn_w:
    df_w = pd.read_sql_query("SELECT * FROM wallet_positions WHERE session_id = 'sess_4e197856' AND status = 'CLOSED'", conn_w)

with sqlite3.connect("data/paper_trading.db") as conn_p:
    df_p = pd.read_sql_query("SELECT * FROM paper_trades", conn_p)

df = df_w.merge(df_p, left_on="paper_trade_id", right_on="trade_id", suffixes=("", "_paper"), how="left")
df['is_win'] = df['net_realized_pnl_usd'] > 0
df['liq_mc_ratio'] = df['entry_liquidity_usd'] / df['entry_market_cap_usd']

# Bin MC
bins = [0, 8000, 11000, 14000, 18000, 25000, 35000, 50000, 1000000]
labels = ['<8k', '8k-11k', '11k-14k', '14k-18k', '18k-25k', '25k-35k', '35k-50k', '>50k']
df['mc_bin'] = pd.cut(df['entry_market_cap_usd'], bins=bins, labels=labels)

print("="*85)
print("ENTRY MARKET CAP BRACKET BREAKDOWN")
print("="*85)
mc_grp = df.groupby('mc_bin', observed=False).agg(
    trades=('position_id', 'count'),
    wins=('is_win', 'sum'),
    win_rate=('is_win', lambda x: f"{x.mean()*100:.1f}%"),
    big_wins_100pct=('net_realized_return_pct', lambda x: (x >= 100).sum()),
    win_pnl=('net_realized_pnl_usd', lambda x: x[x > 0].sum()),
    loss_pnl=('net_realized_pnl_usd', lambda x: x[x <= 0].sum()),
    net_pnl=('net_realized_pnl_usd', 'sum')
).reset_index()
print(mc_grp.to_string(index=False))

print("\n" + "="*85)
print("VENUE BREAKDOWN")
print("="*85)
ven_grp = df.groupby('venue', observed=False).agg(
    trades=('position_id', 'count'),
    wins=('is_win', 'sum'),
    win_rate=('is_win', lambda x: f"{x.mean()*100:.1f}%"),
    win_pnl=('net_realized_pnl_usd', lambda x: x[x > 0].sum()),
    loss_pnl=('net_realized_pnl_usd', lambda x: x[x <= 0].sum()),
    net_pnl=('net_realized_pnl_usd', 'sum')
).reset_index()
print(ven_grp.to_string(index=False))

print("\n" + "="*85)
print("LIQUIDITY / MC RATIO BREAKDOWN")
print("="*85)
ratio_bins = [0, 0.40, 0.50, 0.58, 0.62, 0.70, 10.0]
ratio_labels = ['<0.40', '0.40-0.50', '0.50-0.58', '0.58-0.62 (PumpFun curve)', '0.62-0.70', '>0.70']
df['ratio_bin'] = pd.cut(df['liq_mc_ratio'], bins=ratio_bins, labels=ratio_labels)
r_grp = df.groupby('ratio_bin', observed=False).agg(
    trades=('position_id', 'count'),
    wins=('is_win', 'sum'),
    win_rate=('is_win', lambda x: f"{x.mean()*100:.1f}%"),
    win_pnl=('net_realized_pnl_usd', lambda x: x[x > 0].sum()),
    loss_pnl=('net_realized_pnl_usd', lambda x: x[x <= 0].sum()),
    net_pnl=('net_realized_pnl_usd', 'sum')
).reset_index()
print(r_grp.to_string(index=False))

print("\n" + "="*85)
print("ENTRY SIGNAL STATE BREAKDOWN")
print("="*85)
sig_grp = df.groupby('signal_state_at_entry', observed=False).agg(
    trades=('position_id', 'count'),
    wins=('is_win', 'sum'),
    win_rate=('is_win', lambda x: f"{x.mean()*100:.1f}%"),
    win_pnl=('net_realized_pnl_usd', lambda x: x[x > 0].sum()),
    loss_pnl=('net_realized_pnl_usd', lambda x: x[x <= 0].sum()),
    net_pnl=('net_realized_pnl_usd', 'sum')
).reset_index()
print(sig_grp.to_string(index=False))

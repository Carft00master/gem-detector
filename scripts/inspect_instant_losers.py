import sqlite3
import pandas as pd
import sys

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

with sqlite3.connect("data/virtual_wallet.db") as cw, sqlite3.connect("data/paper_trading.db") as cp:
    df_w = pd.read_sql_query("SELECT * FROM wallet_positions WHERE session_id = 'sess_4e197856' AND status = 'CLOSED'", cw)
    df_p = pd.read_sql_query("SELECT * FROM paper_trades", cp)

df = df_w.merge(df_p, left_on='paper_trade_id', right_on='trade_id', suffixes=('', '_paper'), how='left')
df['is_win'] = df['net_realized_pnl_usd'] > 0
df['liq_mc_ratio'] = df['entry_liquidity_usd'] / df['entry_market_cap_usd']

instant_losers = df[(~df['is_win']) & (df['mfe_ratio'] < 1.10)]
other_trades = df[~df['position_id'].isin(instant_losers['position_id'])]

print("="*85)
print(f"INSTANT LOSERS (MFE < 1.10): {len(instant_losers)} TRADES")
print("="*85)
print(f"Total Loss PnL: -${abs(instant_losers['net_realized_pnl_usd'].sum()):,.2f}")
print(f"Average Loss PnL: -${abs(instant_losers['net_realized_pnl_usd'].mean()):,.2f}")
print(f"Average Hold Time: {instant_losers['hold_duration_seconds'].mean():.1f}s ({instant_losers['hold_duration_seconds'].mean()/60:.1f} mins)")
print(f"Median Hold Time: {instant_losers['hold_duration_seconds'].median():.1f}s")

print("\nVenue Breakdown of Instant Losers:")
print(instant_losers['venue'].value_counts())

print("\nMarket Cap Distribution of Instant Losers:")
bins = [0, 8000, 11000, 14000, 18000, 25000, 35000, 50000, 1000000]
labels = ['<8k', '8k-11k', '11k-14k', '14k-18k', '18k-25k', '25k-35k', '35k-50k', '>50k']
instant_losers['mc_bin'] = pd.cut(instant_losers['entry_market_cap_usd'], bins=bins, labels=labels)
print(instant_losers['mc_bin'].value_counts().sort_index())

print("\nExit Reason Distribution of Instant Losers:")
print(instant_losers['exit_reason'].value_counts())

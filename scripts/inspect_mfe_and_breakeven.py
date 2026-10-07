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

losers = df[~df['is_win']]

print("="*85)
print("LOSING TRADES THAT HAD POSITIVE MAXIMUM FAVORABLE EXCURSION (MFE)")
print("="*85)

for thresh in [1.10, 1.20, 1.25, 1.30, 1.50, 2.00]:
    had_gain = losers[losers['mfe_ratio'] >= thresh]
    loss_amount = had_gain['net_realized_pnl_usd'].sum()
    print(f"Losers that peaked >= +{int((thresh-1)*100)}% (MFE >= {thresh:.2f}):")
    print(f"  Count: {len(had_gain)} trades | Total Realized Loss: -${abs(loss_amount):,.2f}")

print("\n" + "="*85)
print("BREAKEVEN LOSS INVESTIGATION")
print("="*85)
be_trades = df[df['exit_reason'] == 'STAGED_BREAKEVEN_PROTECTION']
print(f"Total trades exiting on STAGED_BREAKEVEN_PROTECTION: {len(be_trades)}")
be_wins = be_trades[be_trades['is_win']]
be_losses = be_trades[~be_trades['is_win']]
print(f"  Wins: {len(be_wins)} (+$ {be_wins['net_realized_pnl_usd'].sum():,.2f})")
print(f"  Losses: {len(be_losses)} (-$ {abs(be_losses['net_realized_pnl_usd'].sum()):,.2f})")
print(f"  Net PnL on Breakeven Protection: ${be_trades['net_realized_pnl_usd'].sum():,.2f}")
print("Sample of Breakeven trades that closed at loss:")
sample_be = be_losses[['symbol', 'venue', 'entry_market_cap_usd', 'hold_duration_seconds', 'mfe_ratio', 'net_realized_return_pct', 'net_realized_pnl_usd']].head(10)
print(sample_be.to_string(index=False))

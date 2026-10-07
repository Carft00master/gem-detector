import sqlite3
import pandas as pd
import sys

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

with sqlite3.connect("data/virtual_wallet.db") as cw, sqlite3.connect("data/paper_trading.db") as cp:
    df_w = pd.read_sql_query("SELECT * FROM wallet_positions WHERE session_id = 'sess_4e197856' AND status = 'CLOSED'", cw)
    df_p = pd.read_sql_query("SELECT * FROM paper_trades", cp)

df = df_w.merge(df_p, left_on='paper_trade_id', right_on='trade_id', suffixes=('', '_paper'), how='left')

print("="*85)
print("TOP 15 WINNERS (by Realized PnL)")
print("="*85)
top_wins = df.sort_values(by='net_realized_pnl_usd', ascending=False).head(15)
cols = ['symbol', 'venue', 'entry_market_cap_usd', 'entry_liquidity_usd', 'hold_duration_seconds', 'net_realized_return_pct', 'net_realized_pnl_usd', 'mfe_ratio', 'exit_reason']
print(top_wins[cols].to_string(index=False))

print("\n" + "="*85)
print("TOP 15 LOSERS (by Realized Loss)")
print("="*85)
top_losers = df.sort_values(by='net_realized_pnl_usd', ascending=True).head(15)
print(top_losers[cols].to_string(index=False))

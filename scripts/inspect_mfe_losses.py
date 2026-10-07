import sqlite3
import pandas as pd
import sys

sys.stdout.reconfigure(encoding='utf-8')

with sqlite3.connect("data/virtual_wallet.db") as conn_w:
    df_w = pd.read_sql_query("SELECT * FROM wallet_positions WHERE session_id = 'sess_4e197856' AND status = 'CLOSED'", conn_w)

with sqlite3.connect("data/paper_trading.db") as conn_p:
    df_p = pd.read_sql_query("SELECT * FROM paper_trades", conn_p)

merged = df_w.merge(df_p, left_on="paper_trade_id", right_on="trade_id", suffixes=("", "_paper"), how="left")
merged["is_win"] = merged["net_realized_pnl_usd"] > 0

profit_turned_losses = merged[(~merged["is_win"]) & (merged["mfe_ratio"] >= 1.25)].copy()
print(f"=== {len(profit_turned_losses)} TRADES THAT REACHED >= +25% PROFIT BUT CLOSED AS LOSSES ===")
print("Exit Reason Breakdown:")
print(profit_turned_losses["exit_reason"].value_counts())
print("\nExit Policy Breakdown:")
print(profit_turned_losses["exit_policy"].value_counts())

print("\nSample of 15 trades that reached >= +50% profit (mfe >= 1.50) but closed as losses:")
sample = profit_turned_losses[profit_turned_losses["mfe_ratio"] >= 1.50].head(15)
for r in sample.itertuples():
    print(f"Symbol: {r.symbol} | Venue: {r.venue} | Peak Gain: +{(r.mfe_ratio - 1)*100:.1f}% | Net Ret: {r.net_realized_return_pct:.1f}% | Net PnL: ${r.net_realized_pnl_usd:.2f} | Exit: {r.exit_reason} | Hold: {r.hold_duration_seconds:.0f}s")

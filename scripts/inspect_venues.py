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

print("=== VENUES: pump-fun vs pumpfun vs pumpswap ===")
for v in ["pump-fun", "pumpfun", "pumpswap"]:
    v_df = merged[merged["venue"] == v]
    wins = v_df[v_df["is_win"]]
    losses = v_df[~v_df["is_win"]]
    big_wins = wins[wins["net_realized_return_pct"] >= 100.0]
    print(f"\nVenue: {v} ({len(v_df)} trades):")
    print(f"  Wins: {len(wins)} | Losses: {len(losses)} | Win Rate: {len(wins)/len(v_df)*100:.1f}%")
    print(f"  Total PnL: ${v_df['net_realized_pnl_usd'].sum():,.2f}")
    print(f"  Win PnL: +${wins['net_realized_pnl_usd'].sum():,.2f} | Loss PnL: -${abs(losses['net_realized_pnl_usd'].sum()):,.2f}")
    print(f"  Big Wins (>= 100%): {len(big_wins)} | Big Win PnL: +${big_wins['net_realized_pnl_usd'].sum():,.2f}")
    if not big_wins.empty:
        for bw in big_wins.itertuples():
            print(f"    {bw.symbol}: +{bw.net_realized_return_pct:,.1f}% (+${bw.net_realized_pnl_usd:,.2f}), hold: {bw.hold_duration_seconds:.0f}s")

print("\n=== TOP 10 WINS IN ENTIRE SESSION ===")
top_wins = merged.sort_values("net_realized_pnl_usd", ascending=False).head(10)
for w in top_wins.itertuples():
    print(f"  {w.symbol} ({w.venue}): +{w.net_realized_return_pct:,.1f}% (+${w.net_realized_pnl_usd:,.2f}), MC: ${w.entry_market_cap_usd:,.0f}, Liq: ${w.entry_liquidity_usd:,.0f}, Hold: {w.hold_duration_seconds:.0f}s")

print("\n=== TOP 10 LOSSES IN ENTIRE SESSION ===")
top_losses = merged.sort_values("net_realized_pnl_usd", ascending=True).head(10)
for l in top_losses.itertuples():
    print(f"  {l.symbol} ({l.venue}): {l.net_realized_return_pct:.1f}% (-${abs(l.net_realized_pnl_usd):,.2f}), Exit: {l.exit_reason}, MC: ${l.entry_market_cap_usd:,.0f}, Liq: ${l.entry_liquidity_usd:,.0f}, Hold: {l.hold_duration_seconds:.0f}s")

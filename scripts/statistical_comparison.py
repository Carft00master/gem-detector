import sqlite3
import pandas as pd
import numpy as np
import sys

sys.stdout.reconfigure(encoding='utf-8')

with sqlite3.connect("data/virtual_wallet.db") as conn_w:
    df_w = pd.read_sql_query("SELECT * FROM wallet_positions WHERE session_id = 'sess_4e197856' AND status = 'CLOSED'", conn_w)

with sqlite3.connect("data/paper_trading.db") as conn_p:
    df_p = pd.read_sql_query("SELECT * FROM paper_trades", conn_p)

merged = df_w.merge(df_p, left_on="paper_trade_id", right_on="trade_id", suffixes=("", "_paper"), how="left")
merged["is_win"] = merged["net_realized_pnl_usd"] > 0
merged["liq_mc_ratio"] = merged["entry_liquidity_usd"] / merged["entry_market_cap_usd"]

print("="*80)
print("1. ENTRY MARKET CAP BUCKET ANALYSIS")
print("="*80)
mc_bins = [0, 8000, 12000, 15000, 20000, 30000, 50000, 1000000]
mc_labels = ["<8k", "8k-12k", "12k-15k", "15k-20k", "20k-30k", "30k-50k", ">50k"]
merged["mc_bucket"] = pd.cut(merged["entry_market_cap_usd"], bins=mc_bins, labels=mc_labels)

mc_grouped = merged.groupby("mc_bucket", observed=False).agg(
    trades=("position_id", "count"),
    wins=("is_win", "sum"),
    win_rate=("is_win", "mean"),
    total_pnl=("net_realized_pnl_usd", "sum"),
    win_pnl=("net_realized_pnl_usd", lambda x: x[x > 0].sum()),
    loss_pnl=("net_realized_pnl_usd", lambda x: x[x <= 0].sum()),
    avg_pnl=("net_realized_pnl_usd", "mean"),
    big_wins=("net_realized_return_pct", lambda x: (x >= 100).sum())
).reset_index()
mc_grouped["win_rate_pct"] = mc_grouped["win_rate"] * 100
print(mc_grouped[["mc_bucket", "trades", "wins", "win_rate_pct", "big_wins", "win_pnl", "loss_pnl", "total_pnl"]].to_string())

print("\n" + "="*80)
print("2. LIQUIDITY-TO-MC RATIO BUCKET ANALYSIS")
print("="*80)
ratio_bins = [0, 0.40, 0.60, 0.80, 1.00, 1.35, 10.0]
ratio_labels = ["<0.40", "0.40-0.60", "0.60-0.80", "0.80-1.00", "1.00-1.35", ">1.35"]
merged["ratio_bucket"] = pd.cut(merged["liq_mc_ratio"], bins=ratio_bins, labels=ratio_labels)

ratio_grouped = merged.groupby("ratio_bucket", observed=False).agg(
    trades=("position_id", "count"),
    wins=("is_win", "sum"),
    win_rate=("is_win", "mean"),
    total_pnl=("net_realized_pnl_usd", "sum"),
    win_pnl=("net_realized_pnl_usd", lambda x: x[x > 0].sum()),
    loss_pnl=("net_realized_pnl_usd", lambda x: x[x <= 0].sum()),
    big_wins=("net_realized_return_pct", lambda x: (x >= 100).sum())
).reset_index()
ratio_grouped["win_rate_pct"] = ratio_grouped["win_rate"] * 100
print(ratio_grouped[["ratio_bucket", "trades", "wins", "win_rate_pct", "big_wins", "win_pnl", "loss_pnl", "total_pnl"]].to_string())

print("\n" + "="*80)
print("3. MAXIMUM FAVORABLE EXCURSION (MFE) ANALYSIS")
print("Did losing trades enter profit before getting stopped out?")
print("="*80)
losses = merged[~merged["is_win"]].copy()
mfe_bins = [0, 1.00, 1.10, 1.25, 1.50, 2.00, 3.00, 1000.0]
mfe_labels = ["No profit (<=1.0x)", "Tiny (+0-10%)", "Modest (+10-25%)", "Good (+25-50%)", "Strong (+50-100%)", "Huge (+100-200%)", "Monster (>200%)"]
losses["mfe_bucket"] = pd.cut(losses["mfe_ratio"], bins=mfe_bins, labels=mfe_labels)
mfe_grouped = losses.groupby("mfe_bucket", observed=False).agg(
    trades=("position_id", "count"),
    total_loss=("net_realized_pnl_usd", "sum"),
    avg_loss=("net_realized_pnl_usd", "mean"),
    avg_mae=("mae_ratio", "mean"),
    avg_hold_s=("hold_duration_seconds", "mean")
).reset_index()
print(mfe_grouped.to_string())

print("\n" + "="*80)
print("4. HOLD DURATION BREAKDOWN ON LOSING TRADES")
print("="*80)
hold_bins = [0, 30, 60, 120, 300, 600, 1800, 86400 * 7]
hold_labels = ["<30s", "30-60s", "1-2m", "2-5m", "5-10m", "10-30m", ">30m"]
losses["hold_bucket"] = pd.cut(losses["hold_duration_seconds"], bins=hold_bins, labels=hold_labels)
hold_grouped = losses.groupby("hold_bucket", observed=False).agg(
    trades=("position_id", "count"),
    total_loss=("net_realized_pnl_usd", "sum"),
    avg_loss=("net_realized_pnl_usd", "mean"),
    avg_ret_pct=("net_realized_return_pct", "mean"),
).reset_index()
print(hold_grouped.to_string())

import sqlite3
import pandas as pd
import numpy as np

# Load wallet positions and paper trades
with sqlite3.connect("data/virtual_wallet.db") as conn_w:
    df_w = pd.read_sql_query("SELECT * FROM wallet_positions WHERE session_id = 'sess_4e197856' AND status = 'CLOSED'", conn_w)

with sqlite3.connect("data/paper_trading.db") as conn_p:
    df_p = pd.read_sql_query("SELECT * FROM paper_trades", conn_p)

# Merge
merged = df_w.merge(df_p, left_on="paper_trade_id", right_on="trade_id", suffixes=("", "_paper"), how="left")
print(f"Merged active session: {len(merged)} trades. Matched with paper: {merged['trade_id'].notna().sum()}")

# Fill missing columns from paper trade if needed
merged["is_win"] = merged["net_realized_pnl_usd"] > 0
merged["liq_mc_ratio"] = merged["entry_liquidity_usd"] / merged["entry_market_cap_usd"]

wins = merged[merged["is_win"]]
losses = merged[~merged["is_win"]]

print("\n" + "="*80)
print(f"ACTIVE WALLET SESSION sess_4e197856: {len(merged)} TRADES")
print(f"Wins: {len(wins)} ({len(wins)/len(merged)*100:.1f}%) | Total Win PnL: +${wins['net_realized_pnl_usd'].sum():,.2f}")
print(f"Losses: {len(losses)} ({len(losses)/len(merged)*100:.1f}%) | Total Loss PnL: -${abs(losses['net_realized_pnl_usd'].sum()):,.2f}")
print(f"Net Realized PnL: ${merged['net_realized_pnl_usd'].sum():,.2f}")
print("="*80)

# 1. Exit Reason Breakdown
print("\n--- EXIT REASONS BREAKDOWN ---")
exit_summary = merged.groupby(["exit_reason", "is_win"]).agg(
    count=("position_id", "count"),
    total_pnl=("net_realized_pnl_usd", "sum"),
    avg_pnl=("net_realized_pnl_usd", "mean"),
    avg_return=("net_realized_return_pct", "mean"),
    avg_hold_s=("hold_duration_seconds", "mean")
).reset_index()
print(exit_summary.to_string())

# 2. Venue Breakdown
print("\n--- VENUE BREAKDOWN ---")
venue_summary = merged.groupby("venue").agg(
    total_trades=("position_id", "count"),
    wins=("is_win", "sum"),
    win_rate=("is_win", "mean"),
    total_pnl=("net_realized_pnl_usd", "sum"),
    win_pnl=("net_realized_pnl_usd", lambda x: x[x > 0].sum()),
    loss_pnl=("net_realized_pnl_usd", lambda x: x[x <= 0].sum()),
).reset_index()
venue_summary["win_rate_pct"] = venue_summary["win_rate"] * 100
print(venue_summary[["venue", "total_trades", "wins", "win_rate_pct", "total_pnl", "win_pnl", "loss_pnl"]].to_string())

# 3. Entry Reason / Lane Breakdown
print("\n--- ENTRY REASON / LANE BREAKDOWN ---")
lane_summary = merged.groupby("entry_reason").agg(
    total_trades=("position_id", "count"),
    wins=("is_win", "sum"),
    win_rate=("is_win", "mean"),
    total_pnl=("net_realized_pnl_usd", "sum"),
    win_pnl=("net_realized_pnl_usd", lambda x: x[x > 0].sum()),
    loss_pnl=("net_realized_pnl_usd", lambda x: x[x <= 0].sum()),
).reset_index()
lane_summary["win_rate_pct"] = lane_summary["win_rate"] * 100
print(lane_summary[["entry_reason", "total_trades", "wins", "win_rate_pct", "total_pnl", "win_pnl", "loss_pnl"]].to_string())

# 4. Metric Distributions (Wins vs Losses)
print("\n--- METRIC DISTRIBUTIONS (WINS vs LOSSES) ---")
metrics = [
    "entry_market_cap_usd",
    "entry_liquidity_usd",
    "liq_mc_ratio",
    "hold_duration_seconds",
    "mfe_ratio",
    "mae_ratio",
    "p_reach_3m_at_entry",
    "p_reach_1m_at_entry",
    "p_reach_500k_at_entry",
    "p_reach_100k_at_entry",
    "rug_risk_at_entry",
    "data_confidence",
    "entry_price_impact_pct"
]

stats_data = []
for m in metrics:
    if m in merged.columns:
        w_col = wins[m].dropna()
        l_col = losses[m].dropna()
        if not w_col.empty and not l_col.empty:
            stats_data.append({
                "Metric": m,
                "Win Mean": w_col.mean(),
                "Win Median": w_col.median(),
                "Loss Mean": l_col.mean(),
                "Loss Median": l_col.median(),
                "Diff (W - L)": w_col.mean() - l_col.mean()
            })
df_stats = pd.DataFrame(stats_data)
print(df_stats.to_string())

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

# Merge wallet positions with paper trades
df = df_w.merge(df_p, left_on="paper_trade_id", right_on="trade_id", suffixes=("", "_paper"), how="left")
print(f"Total wallet closed trades: {len(df)} | Matched with paper_trades: {df['trade_id'].notna().sum()}")

# Query snapshots ONLY for these specific tokens
tokens = list(df['token_address'].unique())
placeholders = ','.join(['?'] * len(tokens))

with sqlite3.connect("data/research_dataset.db") as conn_r:
    query_snap = f"""
    SELECT token_address, timestamp, volume_5m_usd, txns_5m_buys, txns_5m_sells, 
           unique_buyers, unique_sellers, cabal_risk_score, wash_trade_risk, 
           volume_quality_score, top10_effective_pct, dev_holding_pct
    FROM snapshots
    WHERE token_address IN ({placeholders})
    """
    df_snap = pd.read_sql_query(query_snap, conn_r, params=tokens)

print(f"Fetched {len(df_snap)} matching snapshots for {len(tokens)} unique tokens")

df['entry_dt'] = pd.to_datetime(df['entry_timestamp'])
df_snap['snap_dt'] = pd.to_datetime(df_snap['timestamp'])

snap_records = []
for _, row in df.iterrows():
    snaps = df_snap[df_snap['token_address'] == row['token_address']]
    if len(snaps) > 0:
        diffs = (snaps['snap_dt'] - row['entry_dt']).abs()
        best_snap = snaps.loc[diffs.idxmin()]
        snap_records.append({
            'snap_volume_5m': best_snap['volume_5m_usd'],
            'snap_txns_buys': best_snap['txns_5m_buys'],
            'snap_txns_sells': best_snap['txns_5m_sells'],
            'snap_unique_buyers': best_snap['unique_buyers'],
            'snap_unique_sellers': best_snap['unique_sellers'],
            'snap_cabal_risk': best_snap['cabal_risk_score'],
            'snap_wash_risk': best_snap['wash_trade_risk'],
            'snap_vol_quality': best_snap['volume_quality_score'],
            'snap_top10_eff': best_snap['top10_effective_pct'],
            'snap_dev_holding': best_snap['dev_holding_pct']
        })
    else:
        snap_records.append({k: np.nan for k in [
            'snap_volume_5m', 'snap_txns_buys', 'snap_txns_sells',
            'snap_unique_buyers', 'snap_unique_sellers', 'snap_cabal_risk',
            'snap_wash_risk', 'snap_vol_quality', 'snap_top10_eff', 'snap_dev_holding'
        ]})

df_snap_features = pd.DataFrame(snap_records)
df = pd.concat([df, df_snap_features], axis=1)

df['is_win'] = df['net_realized_pnl_usd'] > 0
df['liq_mc_ratio'] = df['entry_liquidity_usd'] / df['entry_market_cap_usd']
df['buy_sell_ratio'] = df['snap_txns_buys'] / (df['snap_txns_sells'] + 1)
df['buyer_seller_ratio'] = df['snap_unique_buyers'] / (df['snap_unique_sellers'] + 1)

wins = df[df['is_win']]
losses = df[~df['is_win']]

print("\n" + "="*80)
print("1. SUMMARY METRICS: WINS VS LOSSES")
print("="*80)
print(f"Total Trades: {len(df)}")
print(f"Wins: {len(wins)} ({len(wins)/len(df)*100:.1f}%) | Total Win PnL: +${wins['net_realized_pnl_usd'].sum():,.2f}")
print(f"Losses: {len(losses)} ({len(losses)/len(df)*100:.1f}%) | Total Loss PnL: -${abs(losses['net_realized_pnl_usd'].sum()):,.2f}")
print(f"Net Realized PnL: +${df['net_realized_pnl_usd'].sum():,.2f}")
print(f"Profit Factor: {wins['net_realized_pnl_usd'].sum() / abs(losses['net_realized_pnl_usd'].sum()):.2f}")

num_cols = [
    'entry_market_cap_usd',
    'entry_liquidity_usd',
    'liq_mc_ratio',
    'p_reach_100k_at_entry',
    'p_reach_500k_at_entry',
    'p_reach_1m_at_entry',
    'p_reach_3m_at_entry',
    'rug_risk_at_entry',
    'manipulation_risk_at_entry',
    'cabal_risk_at_entry',
    'data_confidence_at_entry',
    'discovery_quality_at_entry',
    'entry_price_impact_pct',
    'entry_slippage_pct',
    'mfe_ratio',
    'mae_ratio',
    'hold_duration_seconds',
    'snap_volume_5m',
    'snap_txns_buys',
    'snap_txns_sells',
    'buy_sell_ratio',
    'snap_unique_buyers',
    'snap_unique_sellers',
    'buyer_seller_ratio',
    'snap_cabal_risk',
    'snap_wash_risk',
    'snap_vol_quality',
    'snap_top10_eff',
    'snap_dev_holding'
]

print("\n" + "="*80)
print("2. STATISTICAL COMPARISON TABLE (MEDIANS & MEANS)")
print("="*80)
rows = []
for col in num_cols:
    if col in df.columns:
        w_s = wins[col].dropna()
        l_s = losses[col].dropna()
        if len(w_s) > 0 and len(l_s) > 0:
            rows.append({
                'Metric': col,
                'Wins Med': round(w_s.median(), 3),
                'Losses Med': round(l_s.median(), 3),
                'Wins Mean': round(w_s.mean(), 3),
                'Losses Mean': round(l_s.mean(), 3),
                'Diff (Med)': round(w_s.median() - l_s.median(), 3)
            })
print(pd.DataFrame(rows).to_string(index=False))

print("\n" + "="*80)
print("3. EXTREME PERCENTILES (p25, p50, p75) FOR KEY METRICS")
print("="*80)
key_metrics = [
    'entry_market_cap_usd', 'entry_liquidity_usd', 'liq_mc_ratio',
    'p_reach_3m_at_entry', 'rug_risk_at_entry', 'cabal_risk_at_entry',
    'snap_volume_5m', 'buy_sell_ratio', 'snap_vol_quality', 'snap_dev_holding',
    'mfe_ratio', 'hold_duration_seconds'
]
for m in key_metrics:
    w_valid = wins[m].dropna()
    l_valid = losses[m].dropna()
    if len(w_valid) > 0 and len(l_valid) > 0:
        print(f"Metric: {m}")
        print(f"  Wins   (N={len(w_valid)}) -> p25: {w_valid.quantile(0.25):.2f} | p50: {w_valid.quantile(0.50):.2f} | p75: {w_valid.quantile(0.75):.2f}")
        print(f"  Losses (N={len(l_valid)}) -> p25: {l_valid.quantile(0.25):.2f} | p50: {l_valid.quantile(0.50):.2f} | p75: {l_valid.quantile(0.75):.2f}")

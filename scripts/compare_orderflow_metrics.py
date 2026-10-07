import sqlite3
import pandas as pd
import numpy as np
import sys

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

with sqlite3.connect("data/virtual_wallet.db") as cw, sqlite3.connect("data/paper_trading.db") as cp, sqlite3.connect("data/research_dataset.db") as cr:
    df_w = pd.read_sql_query("SELECT * FROM wallet_positions WHERE session_id = 'sess_4e197856' AND status = 'CLOSED'", cw)
    df_p = pd.read_sql_query("SELECT * FROM paper_trades", cp)
    df = df_w.merge(df_p, left_on='paper_trade_id', right_on='trade_id', suffixes=('', '_paper'), how='left')
    
    tokens = list(df['token_address'].unique())
    placeholders = ','.join(['?'] * len(tokens))
    query_snap = f"""
    SELECT token_address, timestamp, volume_5m_usd, txns_5m_buys, txns_5m_sells, 
           unique_buyers, unique_sellers, cabal_risk_score, wash_trade_risk, 
           volume_quality_score, top10_effective_pct, dev_holding_pct
    FROM snapshots
    WHERE token_address IN ({placeholders})
    """
    df_snap = pd.read_sql_query(query_snap, cr, params=tokens)

df['entry_dt'] = pd.to_datetime(df['entry_timestamp'])
df_snap['snap_dt'] = pd.to_datetime(df_snap['timestamp'])

snap_records = []
for _, row in df.iterrows():
    snaps = df_snap[df_snap['token_address'] == row['token_address']]
    if len(snaps) > 0:
        diffs = (snaps['snap_dt'] - row['entry_dt']).abs()
        best_snap = snaps.loc[diffs.idxmin()]
        snap_records.append(best_snap.to_dict())
    else:
        snap_records.append({})

df_snap_features = pd.DataFrame(snap_records)
for c in ['volume_5m_usd', 'txns_5m_buys', 'txns_5m_sells', 'unique_buyers', 'unique_sellers', 'cabal_risk_score', 'wash_trade_risk', 'volume_quality_score', 'top10_effective_pct', 'dev_holding_pct']:
    if c in df_snap_features.columns:
        df[c] = df_snap_features[c]

df['is_win'] = df['net_realized_pnl_usd'] > 0
df['liq_mc_ratio'] = df['entry_liquidity_usd'] / df['entry_market_cap_usd']
df['buy_sell_ratio'] = df['txns_5m_buys'] / (df['txns_5m_sells'] + 1)
df['buyer_seller_ratio'] = df['unique_buyers'] / (df['unique_sellers'] + 1)

# Group into 3 categories:
# 1. Monster Winners (PnL >= $1000 or Return >= 500%)
# 2. Moderate Winners (PnL > 0)
# 3. Instant Losers (PnL <= 0 and MFE < 1.10)
# 4. Round-Trip Losers (PnL <= 0 and MFE >= 1.25)

def categorize(row):
    if row['net_realized_pnl_usd'] >= 1000 or row['net_realized_return_pct'] >= 500:
        return 'Monster Winner'
    elif row['is_win']:
        return 'Moderate Winner'
    elif row['mfe_ratio'] >= 1.25:
        return 'Round-Trip Loser'
    elif row['mfe_ratio'] < 1.10:
        return 'Instant Loser'
    else:
        return 'Minor Loser'

df['category'] = df.apply(categorize, axis=1)

print("="*85)
print("COHORT BREAKDOWN (COUNT, TOTAL PNL, AVG HOLD TIME)")
print("="*85)
cohort_sum = df.groupby('category').agg(
    count=('position_id', 'count'),
    total_pnl=('net_realized_pnl_usd', 'sum'),
    avg_pnl=('net_realized_pnl_usd', 'mean'),
    median_hold=('hold_duration_seconds', 'median'),
    median_mc=('entry_market_cap_usd', 'median'),
    median_liq_mc=('liq_mc_ratio', 'median')
).reset_index()
print(cohort_sum.to_string(index=False))

print("\n" + "="*85)
print("ORDER FLOW METRICS BY COHORT (MEDIANS)")
print("="*85)
of_cols = ['volume_5m_usd', 'txns_5m_buys', 'txns_5m_sells', 'buy_sell_ratio', 'unique_buyers', 'unique_sellers', 'buyer_seller_ratio', 'top10_effective_pct', 'dev_holding_pct']
of_summary = df.groupby('category')[of_cols].median().reset_index()
print(of_summary.to_string(index=False))

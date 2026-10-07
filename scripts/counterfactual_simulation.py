import sqlite3
import pandas as pd
import numpy as np
import sys

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

with sqlite3.connect("data/virtual_wallet.db") as cw, sqlite3.connect("data/paper_trading.db") as cp:
    df_w = pd.read_sql_query("SELECT * FROM wallet_positions WHERE session_id = 'sess_4e197856' AND status = 'CLOSED'", cw)
    df_p = pd.read_sql_query("SELECT * FROM paper_trades", cp)

df = df_w.merge(df_p, left_on='paper_trade_id', right_on='trade_id', suffixes=('', '_paper'), how='left')
df['is_win'] = df['net_realized_pnl_usd'] > 0

print("="*85)
print("BASELINE (CURRENT ACTUAL PERFORMANCE)")
print("="*85)
base_trades = len(df)
base_wins = df['is_win'].sum()
base_wr = base_wins / base_trades * 100
base_win_pnl = df[df['is_win']]['net_realized_pnl_usd'].sum()
base_loss_pnl = df[~df['is_win']]['net_realized_pnl_usd'].sum()
base_net_pnl = df['net_realized_pnl_usd'].sum()
base_pf = base_win_pnl / abs(base_loss_pnl)

print(f"Total Trades: {base_trades} | Wins: {base_wins} ({base_wr:.1f}%) | Losses: {base_trades - base_wins}")
print(f"Total Win PnL:  +${base_win_pnl:,.2f}")
print(f"Total Loss PnL: -${abs(base_loss_pnl):,.2f}")
print(f"Net Realized:   +${base_net_pnl:,.2f}")
print(f"Profit Factor:  {base_pf:.2f}")

top_10_symbols = ['USTF', 'Elonhotdog', 'Open AI', 'Taylor', 'Odyssey', 'Elon Coin', 'OneShot', 'HOLD', 'ELEVEN', 'ขนุน']

def evaluate_subset(name, subset_mask):
    sub = df[subset_mask]
    n_trades = len(sub)
    wins = sub['is_win'].sum()
    wr = wins / n_trades * 100 if n_trades > 0 else 0
    w_pnl = sub[sub['is_win']]['net_realized_pnl_usd'].sum()
    l_pnl = sub[~sub['is_win']]['net_realized_pnl_usd'].sum()
    net = sub['net_realized_pnl_usd'].sum()
    pf = w_pnl / abs(l_pnl) if abs(l_pnl) > 0 else 999.0
    
    # Check top 10 monster wins
    sub_symbols = set(sub['symbol'])
    captured_top10 = sum(1 for s in top_10_symbols if s in sub_symbols)
    
    losses_avoided_count = (base_trades - base_wins) - (n_trades - wins)
    loss_dollars_saved = abs(base_loss_pnl) - abs(l_pnl)
    win_dollars_lost = base_win_pnl - w_pnl
    net_improvement = net - base_net_pnl
    
    print(f"\n--- {name} ---")
    print(f"Trades: {n_trades} (avoided {base_trades - n_trades} trades, {losses_avoided_count} were losses)")
    print(f"Win Rate: {wr:.1f}% (vs base {base_wr:.1f}%)")
    print(f"Win PnL:  +${w_pnl:,.2f} (lost ${win_dollars_lost:,.2f} in wins)")
    print(f"Loss PnL: -${abs(l_pnl):,.2f} (saved ${loss_dollars_saved:,.2f} in losses!)")
    print(f"Net PnL:  +${net:,.2f} (NET GAIN: {'+' if net_improvement>=0 else ''}${net_improvement:,.2f})")
    print(f"Profit Factor: {pf:.2f} (vs base {base_pf:.2f})")
    print(f"Monster Wins Kept: {captured_top10}/{len(top_10_symbols)} (100% of top 10: {captured_top10 == len(top_10_symbols)})")

# Simulation 1: Market Cap caps
evaluate_subset("1. Filter: MC <= $18,000", df['entry_market_cap_usd'] <= 18000)
evaluate_subset("2. Filter: MC <= $15,000", df['entry_market_cap_usd'] <= 15000)
evaluate_subset("3. Filter: MC <= $14,000", df['entry_market_cap_usd'] <= 14000)

# Simulation 2: Exclude pumpswap
evaluate_subset("4. Filter: Exclude pumpswap", df['venue'] != 'pumpswap')

# Simulation 3: Exclude pumpswap AND MC <= $18,000
evaluate_subset("5. Filter: No pumpswap AND MC <= $18,000", (df['venue'] != 'pumpswap') & (df['entry_market_cap_usd'] <= 18000))

# Simulation 4: Exclude pumpswap AND MC <= $15,000
evaluate_subset("6. Filter: No pumpswap AND MC <= $15,000", (df['venue'] != 'pumpswap') & (df['entry_market_cap_usd'] <= 15000))

# Simulation 5: Exclude pumpfun AMM / pumpswap, keep only pure pump-fun bonding curve <= $15k
evaluate_subset("7. Filter: pump-fun bonding curve only AND MC <= $15,000", (df['venue'] == 'pump-fun') & (df['entry_market_cap_usd'] <= 15000))


import sqlite3
import pandas as pd
import sys

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

with sqlite3.connect('data/paper_trading.db') as cp:
    trades = pd.read_sql_query("SELECT trade_id, symbol, timestamp, exit_timestamp, entry_price_usd, exit_price_usd, mfe_ratio, exit_reason FROM paper_trades WHERE symbol IN ('RESCUE', 'LEO', 'ORE', 'SHILL', 'CELOR')", cp)
    print("TRADES:")
    print(trades.to_string(index=False))
    
    trade_ids = tuple(trades['trade_id'].unique())
    if len(trade_ids) == 1:
        query = f"SELECT * FROM trade_events WHERE trade_id = '{trade_ids[0]}'"
    else:
        query = f"SELECT * FROM trade_events WHERE trade_id IN {trade_ids}"
    events = pd.read_sql_query(query, cp)
    print("\nEVENTS:")
    print(events[['trade_id', 'timestamp', 'event_type', 'price_usd', 'details']].to_string(index=False))

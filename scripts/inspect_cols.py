import sqlite3

with sqlite3.connect("data/virtual_wallet.db") as conn:
    cur = conn.cursor()
    print("wallet_positions columns:")
    for c in cur.execute("PRAGMA table_info(wallet_positions)").fetchall():
        print(f"  {c[1]} ({c[2]})")

with sqlite3.connect("data/paper_trading.db") as conn:
    cur = conn.cursor()
    print("\npaper_trades columns:")
    for c in cur.execute("PRAGMA table_info(paper_trades)").fetchall():
        print(f"  {c[1]} ({c[2]})")

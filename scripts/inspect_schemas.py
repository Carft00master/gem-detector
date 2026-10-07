import sqlite3

for db_path in ['data/virtual_wallet.db', 'data/paper_trading.db']:
    print(f"=== {db_path} ===")
    with sqlite3.connect(db_path) as conn:
        cur = conn.cursor()
        tables = [r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        for t in tables:
            cols = [c[1] for c in cur.execute(f"PRAGMA table_info({t})").fetchall()]
            cnt = cur.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
            print(f"Table {t} ({cnt} rows): {cols[:15]}...")

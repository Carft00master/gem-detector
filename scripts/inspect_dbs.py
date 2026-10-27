import sqlite3

for db_path in ['data/onchain_events.db', 'data/paper_trading.db']:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = cur.fetchall()
    print(f"=== {db_path} ===")
    for t in tables:
        tname = t[0]
        cur.execute(f"SELECT COUNT(*) FROM {tname};")
        cnt = cur.fetchone()[0]
        print(f"  {tname}: {cnt} rows")
        cur.execute(f"PRAGMA table_info({tname});")
        cols = [c[1] for c in cur.fetchall()]
        print(f"    cols: {cols}")

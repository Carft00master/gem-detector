import sqlite3
import json

for db_path in ['archive/pre_reset_20261014/data_paper_trading.db', 'archive/pre_reset_20261014/data_virtual_wallet.db']:
    print(f"\n==================== {db_path} ====================")
    uri = f"file:{db_path}?mode=ro"
    con = sqlite3.connect(uri, uri=True)
    cur = con.cursor()
    tables = [r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
    print("Tables:", tables)
    for t in tables:
        cur.execute(f"PRAGMA table_info({t})")
        cols = [r[1] for r in cur.fetchall()]
        matches = []
        for c in cols:
            try:
                cur.execute(f"SELECT rowid, * FROM {t} WHERE {c} LIKE '%qTFyfJi%' OR {c} LIKE '%NODF%' OR {c} LIKE '%15dd4ce0%'")
                rows = cur.fetchall()
                if rows:
                    matches.extend(rows)
            except Exception:
                pass
        if matches:
            print(f"\n--- Table {t} matched ({len(matches)} rows) ---")
            col_names = ['rowid'] + cols
            seen = set()
            for r in matches:
                if r[0] not in seen:
                    seen.add(r[0])
                    d = dict(zip(col_names, r))
                    print(json.dumps(d, indent=2, default=str))
    con.close()

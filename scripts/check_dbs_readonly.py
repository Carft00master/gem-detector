"""
Read-Only Database Inspector (scripts/check_dbs_readonly.py)
Inspects SQLite table names and row counts in data/ strictly using read-only connections.
Never modifies or deletes any records.
"""

import os
from pathlib import Path
import sqlite3

repo_root = Path(__file__).resolve().parent.parent

def check_db_readonly(relative_path: str):
    db_file = repo_root / relative_path
    if not db_file.exists():
        print(f"{relative_path}: DOES NOT EXIST")
        return
    # Connect strictly with read-only URI
    uri = f"file:{db_file.resolve().as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    try:
        cur = conn.cursor()
        tables = [r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        print(f"{relative_path} tables: {tables}")
        total_rows = 0
        for t in tables:
            cnt = cur.execute(f"SELECT count(*) FROM \"{t}\"").fetchone()[0]
            print(f"  {t}: {cnt} rows")
            total_rows += cnt
        print(f"  TOTAL ROWS: {total_rows}")
    finally:
        conn.close()

if __name__ == "__main__":
    check_db_readonly("data/paper_trading.db")
    check_db_readonly("data/onchain_events.db")

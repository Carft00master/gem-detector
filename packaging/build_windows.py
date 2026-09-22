import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys

root_dir = Path(__file__).resolve().parent.parent


from datetime import datetime, timezone
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys

root_dir = Path(__file__).resolve().parent.parent

DB_NAMES = [
    "paper_trading.db",
    "shadow_universe.db",
    "discovery_audit.db",
    "population_registry.db",
    "smart_money.db",
    "research_dataset.db",
]

JSONL_NAMES = [
    "paper_trades.jsonl",
    "trade_events.jsonl",
    "shadow_universe.jsonl",
    "snapshots.jsonl",
]


def sync_live_data_before_build():
    """Preserve all live user databases and JSONL files across PyInstaller rebuilds."""
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    backup_dir = root_dir / "data" / "backups" / f"pre_build_{ts}"
    backup_dir.mkdir(parents=True, exist_ok=True)

    data_dir = root_dir / "data"

    # 1. Archive current workspace data
    for db_name in DB_NAMES:
        p = data_dir / db_name
        if p.exists():
            shutil.copy2(p, backup_dir / db_name)
    for j_name in JSONL_NAMES:
        p = data_dir / j_name
        if p.exists():
            shutil.copy2(p, backup_dir / j_name)

    # 2. Check candidate dist directories for higher record counts
    dist_sources = [
        root_dir / "dist" / "MemecoinScanner" / "_internal" / "data",
        root_dir / "dist" / "MemecoinScanner" / "data",
    ]

    for dist_data in dist_sources:
        if not dist_data.exists():
            continue
        for db_name in DB_NAMES:
            dist_db = dist_data / db_name
            root_db = data_dir / db_name
            if dist_db.exists():
                # If root doesn't have it, copy over
                if not root_db.exists():
                    shutil.copy2(dist_db, root_db)
                    print(f"[+] Restored missing {db_name} from {dist_data} to root data/")
                    continue

                # If both exist, compare counts for paper_trading.db
                if db_name == "paper_trading.db":
                    try:
                        conn_dist = sqlite3.connect(dist_db)
                        conn_root = sqlite3.connect(root_db)
                        dist_cnt = 0
                        root_cnt = 0
                        try:
                            dist_cnt = conn_dist.execute("SELECT COUNT(*) FROM paper_trades").fetchone()[0]
                            root_cnt = conn_root.execute("SELECT COUNT(*) FROM paper_trades").fetchone()[0]
                        finally:
                            conn_dist.close()
                            conn_root.close()

                        if dist_cnt > root_cnt:
                            print(f"[+] Syncing {dist_cnt} live trades from {dist_data} to root workspace before packaging...")
                            shutil.copy2(dist_db, root_db)
                    except Exception as e:
                        print(f"[!] Warning checking {db_name}: {e}")

        for j_name in JSONL_NAMES:
            dist_j = dist_data / j_name
            root_j = data_dir / j_name
            if dist_j.exists() and not root_j.exists():
                shutil.copy2(dist_j, root_j)


def sync_live_data_after_build():
    """Restore all data files to the built application directory so packaged exe starts with 100% current data."""
    data_dir = root_dir / "data"
    destinations = [
        root_dir / "dist" / "MemecoinScanner" / "data",
        root_dir / "dist" / "MemecoinScanner" / "_internal" / "data",
    ]

    for dest in destinations:
        dest.mkdir(parents=True, exist_ok=True)
        for db_name in DB_NAMES:
            src_db = data_dir / db_name
            if src_db.exists():
                shutil.copy2(src_db, dest / db_name)
        for j_name in JSONL_NAMES:
            src_j = data_dir / j_name
            if src_j.exists():
                shutil.copy2(src_j, dest / j_name)

    # Verification check
    root_paper = data_dir / "paper_trading.db"
    dist_paper = root_dir / "dist" / "MemecoinScanner" / "data" / "paper_trading.db"
    if root_paper.exists() and dist_paper.exists():
        conn1 = sqlite3.connect(root_paper)
        conn2 = sqlite3.connect(dist_paper)
        try:
            cnt1 = conn1.execute("SELECT COUNT(*) FROM paper_trades").fetchone()[0]
            cnt2 = conn2.execute("SELECT COUNT(*) FROM paper_trades").fetchone()[0]
            print(f"[+] Post-build Data Verification: Root trades={cnt1}, Packaged trades={cnt2} (MATCH: {cnt1 == cnt2})")
        finally:
            conn1.close()
            conn2.close()


def build_executable():
    print(f"[+] Starting PyInstaller Build for MemecoinScanner...")
    sync_live_data_before_build()

    # Terminate any running MemecoinScanner instance to release file locks on Windows
    if sys.platform == "win32":
        os.system("taskkill /F /IM MemecoinScanner.exe >nul 2>&1")

    dist_dir = root_dir / "dist"
    build_dir = root_dir / "build"
    spec_file = root_dir / "packaging" / "scanner.spec"

    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--distpath",
        str(dist_dir),
        "--workpath",
        str(build_dir),
        str(spec_file),
    ]

    print(f"Executing: {' '.join(cmd)}")
    res = subprocess.run(cmd, cwd=str(root_dir))
    if res.returncode == 0:
        sync_live_data_after_build()
        print("\n[+] BUILD SUCCESSFUL AND DATA VERIFIED!")
        print(f"Standalone executable located at: {dist_dir / 'MemecoinScanner' / 'MemecoinScanner.exe'}")
    else:
        print(f"\n[!] Build failed with exit code: {res.returncode}")


if __name__ == "__main__":
    build_executable()



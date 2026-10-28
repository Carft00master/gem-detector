"""
Verify forced kill (taskkill /F) and supervisor (--forever) auto-restart with trade count actively increasing after restart (Review Item 2f).
Writes verbatim timeseries and results to reports/forced_kill_restart_verification.json.
"""

import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import time

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)


def get_db_counts(db_path: str) -> tuple[int, int]:
    if not os.path.exists(db_path):
        return 0, 0
    try:
        conn = sqlite3.connect(db_path, timeout=5.0)
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM curve_creations")
        c_cnt = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM curve_trades")
        t_cnt = cur.fetchone()[0]
        conn.close()
        return c_cnt, t_cnt
    except Exception:
        return 0, 0


def main():
    db_path = "data/curve_trades_kill_test.db"
    pid_file = "data/kill_test_worker.pid"
    for suffix in ["", "-wal", "-shm"]:
        p = Path(f"{db_path}{suffix}")
        if p.exists():
            p.unlink()
    if Path(pid_file).exists():
        Path(pid_file).unlink()

    cmd = [
        sys.executable,
        "scripts/run_trade_collector.py",
        "--forever",
        "--duration-seconds", "45",
        "--db-path", db_path,
        "--reset-db",
        "--pid-file", pid_file,
    ]
    print(f"Starting supervisor: {' '.join(cmd)}")
    sup_proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")

    t0 = time.time()
    worker_pid_1 = None
    c_before = 0
    t_before = 0

    # Wait until we have a worker PID and at least 15 trades stored (or 18s elapsed)
    while time.time() - t0 < 20.0:
        if os.path.exists(pid_file):
            try:
                worker_pid_1 = int(Path(pid_file).read_text(encoding="utf-8").strip())
            except Exception:
                pass
        c_before, t_before = get_db_counts(db_path)
        if worker_pid_1 and t_before >= 15 and c_before >= 1:
            break
        time.sleep(1.0)

    print(f"[Before Forced Kill] elapsed={time.time()-t0:.1f}s | worker_pid={worker_pid_1} | creations={c_before} | trades={t_before}")

    # Force-kill worker #1
    kill_res = subprocess.run(["taskkill", "/F", "/PID", str(worker_pid_1)], capture_output=True, text=True)
    kill_msg = (kill_res.stdout or kill_res.stderr).strip()
    print(f"[Executed taskkill /F] {kill_msg}")

    # Track trade count progression after restart
    post_kill_samples = []
    worker_pid_2 = None
    for step in range(1, 9):
        time.sleep(3.0)
        if os.path.exists(pid_file):
            try:
                pid_now = int(Path(pid_file).read_text(encoding="utf-8").strip())
                if pid_now != worker_pid_1:
                    worker_pid_2 = pid_now
            except Exception:
                pass
        c_now, t_now = get_db_counts(db_path)
        sample = {
            "seconds_after_kill": step * 3,
            "worker_pid": worker_pid_2 or worker_pid_1,
            "creations_in_db": c_now,
            "trades_in_db": t_now,
            "delta_trades_since_kill": t_now - t_before,
        }
        post_kill_samples.append(sample)
        print(
            f"[Post-Kill +{step*3:2d}s] worker_pid={sample['worker_pid']} | "
            f"creations={c_now} | trades={t_now} (delta={t_now - t_before:+d})"
        )

    out_text, _ = sup_proc.communicate(timeout=20)
    c_final, t_final = get_db_counts(db_path)

    report = {
        "supervisor_pid": sup_proc.pid,
        "worker_pid_before_kill": worker_pid_1,
        "worker_pid_after_restart": worker_pid_2,
        "taskkill_output": kill_msg,
        "creations_before_kill": c_before,
        "trades_before_kill": t_before,
        "post_kill_progression": post_kill_samples,
        "creations_final": c_final,
        "trades_final": t_final,
        "net_trades_added_after_restart": t_final - t_before,
        "trade_count_increased_after_restart": t_final > t_before,
    }
    Path("reports").mkdir(parents=True, exist_ok=True)
    with open("reports/forced_kill_restart_verification.json", "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    print("\n" + "=" * 100)
    print("SUPERVISOR & WORKER LOGS:")
    print("=" * 100)
    print(out_text)
    print("=" * 100)
    print(f"FINAL VERIFICATION: trades_before_kill={t_before} -> trades_final={t_final} (+{t_final - t_before} trades added after restart)")

    # Clean up temporary test DB files
    for suffix in ["", "-wal", "-shm"]:
        p = Path(f"{db_path}{suffix}")
        if p.exists():
            p.unlink()
    if Path(pid_file).exists():
        Path(pid_file).unlink()


if __name__ == "__main__":
    main()

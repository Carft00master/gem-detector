"""
Fetch missing horizon transactions for Route B analysis via SolanaProvider.execute_rpc.
Stores fetched transactions in data/retrospective_cache/txs/{signature}.json.
"""

import json
import os
import sys
import time
from pathlib import Path

# Ensure repository root is on sys.path
root_dir = Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from src.utils.env_loader import load_env_file
load_env_file()

from src.onchain.provider import SolanaProvider

HORIZONS = {
    "S+5": 5,
    "S+10": 10,
    "S+20": 20,
    "S+40": 40,
    "+30s": 139,
    "+2m": 554,
    "+5m": 1386,
    "+15m": 4158,
    "+60m": 16632,
}

CACHE_DIR = Path("data/retrospective_cache/txs")
CACHE_DIR.mkdir(parents=True, exist_ok=True)


def is_cached(sig: str) -> bool:
    p1 = Path(f"tests/fixtures/txs/{sig}.json")
    p2 = CACHE_DIR / f"{sig}.json"
    return p1.exists() or p2.exists()


def main():
    print("=" * 80)
    print("FETCHING ROUTE B HORIZON TRANSACTIONS VIA SolanaProvider.execute_rpc")
    print("=" * 80)

    with open("reports/retrospective_report.json", encoding="utf-8") as f:
        retro = json.load(f)

    reached = [r for r in retro["per_migration_table"] if r.get("reached_creation_slot")]
    print(f"Loaded {len(reached)} reached pools.")

    needed_sigs_map = {}  # sig -> list of (pool_idx, horizon)

    for r in reached:
        idx = r["index"]
        pool = r["pool_address"]
        c_slot = r["creation_slot"]
        sig_file = Path(f"data/retrospective_cache/pool_sigs/{pool}.json")
        if not sig_file.exists():
            continue
        sigs = json.load(open(sig_file, encoding="utf-8"))
        for h_label, offset in HORIZONS.items():
            target_slot = c_slot + offset
            cands = sorted(
                [s for s in sigs if s.get("slot", 0) >= target_slot and s.get("err") is None],
                key=lambda x: (x.get("slot", 0), x.get("transactionIndex", 0)),
            )
            if cands:
                sig = cands[0]["signature"]
                needed_sigs_map.setdefault(sig, []).append((idx, h_label))

    print(f"Total unique signatures needed across all horizons: {len(needed_sigs_map)}")
    missing = [s for s in needed_sigs_map if not is_cached(s)]
    print(f"Already cached: {len(needed_sigs_map) - len(missing)}")
    print(f"Missing to fetch: {len(missing)}")

    if not missing:
        print("All horizon transactions are already cached!")
        return

    provider = SolanaProvider()
    fetched_count = 0
    failed_count = 0

    for i, sig in enumerate(missing, 1):
        target_path = CACHE_DIR / f"{sig}.json"
        assoc = needed_sigs_map[sig]
        assoc_str = ", ".join([f"R{r[0]}:{r[1]}" for r in assoc])
        try:
            res = provider.execute_rpc(
                "getTransaction",
                [sig, {"encoding": "json", "maxSupportedTransactionVersion": 0}],
                timeout=15.0,
            )
            tx_data = res.get("result")
            if not tx_data:
                # Retry with maxSupportedTransactionVersion: 1
                res = provider.execute_rpc(
                    "getTransaction",
                    [sig, {"encoding": "json", "maxSupportedTransactionVersion": 1}],
                    timeout=15.0,
                )
                tx_data = res.get("result")

            if tx_data and tx_data.get("meta"):
                with open(target_path, "w", encoding="utf-8") as out_f:
                    json.dump(tx_data, out_f)
                fetched_count += 1
                if i % 10 == 0 or i == len(missing):
                    print(f"[{i}/{len(missing)}] Fetched {sig[:12]}... ({assoc_str}) | slot={tx_data.get('slot')} | ver={tx_data.get('version')}")
            else:
                print(f"[{i}/{len(missing)}] WARN: Null/invalid tx for {sig[:12]}... ({assoc_str}) -> result={res.get('result')}")
                failed_count += 1
        except Exception as e:
            print(f"[{i}/{len(missing)}] ERROR fetching {sig[:12]}...: {e}")
            failed_count += 1

        # Gentle throttling to stay well under rate limits
        time.sleep(0.08)

    print("-" * 80)
    print(f"Fetch completed: {fetched_count} fetched successfully, {failed_count} failed.")
    print(f"Credit tracker state saved.")


if __name__ == "__main__":
    main()

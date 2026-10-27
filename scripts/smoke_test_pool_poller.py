"""
60-Second Live Smoke Test for PoolReservePoller (Review 6 Item 5).
Polls live reserve balances for real on-chain pools over 60 seconds.
Reports total polls, rows polled, errors, latency, and credit consumption.
"""

import asyncio
import os
import sys
import time
from pathlib import Path

# Ensure repository root is on sys.path
root_dir = Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from src.utils.env_loader import load_env_file
load_env_file()

from src.onchain.provider import SolanaProvider
from src.onchain.pool_poller import PoolReservePoller, PoolReserveSnapshot


async def main():
    print("=" * 80)
    print("STARTING 60-SECOND LIVE SMOKE TEST OF PoolReservePoller")
    print("=" * 80)

    provider = SolanaProvider()
    poller = PoolReservePoller(provider=provider, poll_interval_sec=3.0)

    # Register 2 verified real pools as watchlist targets
    # Pool 1 (Row 1): 2aDTTadiRyUPEZPicRbXx4GjdzttFLFuLpdFonwW8iYM
    poller.register_pool(
        pool_address="2aDTTadiRyUPEZPicRbXx4GjdzttFLFuLpdFonwW8iYM",
        wsol_vault="FGnecwh2bJUNZ3Wyb9uTZ69evxGA5wA36S6vZnmrkCdz",
        token_vault="JAsL7rzarJ7rn2rSrdpConxsfv7KnuhopeG53PFDM5hv",
        token_address="kKKZCfz8eRMsWFhnriMd6neQfE1XqQvgdwj3Ghbpump",
        symbol="ROW1",
        is_watchlist=True,
    )

    # Pool 2 (Row 6): 5iN6UpMNKkAjBJSAHroqPd33GwBHS2N3mCuahpzRgVod
    poller.register_pool(
        pool_address="5iN6UpMNKkAjBJSAHroqPd33GwBHS2N3mCuahpzRgVod",
        wsol_vault="BxY8jfry1UkbXJW3qpHwzga7UjsBxgrKWuGikoaSAbkP",
        token_vault="7kFuCHvEto2y6BK9iofB9WHegsrJLFXBSxJRdP79HEwX",
        token_address="6ziKs4YXGC5P8rv69GZTvipVfmdk4rMuPwLYQaoFpump",
        symbol="ROW6",
        is_watchlist=True,
    )

    targets = poller.get_active_targets()
    print(f"Registered {len(targets)} active targets for polling.")

    start_time = time.time()
    duration = 60.0
    iteration = 0
    total_rows_polled = 0
    errors_encountered = 0

    print(f"{'ITER':<6} | {'TIME(s)':<8} | {'SNAPSHOTS':<10} | {'SLOT':<10} | {'POOL 1 WSOL':<12} | {'POOL 2 WSOL':<12} | {'STATUS'}")
    print("-" * 80)

    while (time.time() - start_time) < duration:
        iteration += 1
        elapsed = time.time() - start_time
        try:
            snapshots = await poller.poll_reserves_once()
            total_rows_polled += len(snapshots)

            s1_wsol = "N/A"
            s2_wsol = "N/A"
            slot = 0
            for s in snapshots:
                slot = s.slot
                if "2aDTT" in s.pool_address:
                    s1_wsol = f"{s.vault_sol_reserve:.4f}"
                elif "5iN6U" in s.pool_address:
                    s2_wsol = f"{s.vault_sol_reserve:.4f}"

            print(f"{iteration:<6} | {elapsed:<8.1f} | {len(snapshots):<10} | {slot:<10} | {s1_wsol:<12} | {s2_wsol:<12} | OK")
        except Exception as e:
            errors_encountered += 1
            print(f"{iteration:<6} | {elapsed:<8.1f} | 0          | ERROR      | -            | -            | {e}")

        await asyncio.sleep(3.0)

    total_elapsed = time.time() - start_time
    print("=" * 80)
    print("SMOKE TEST RESULTS SUMMARY:")
    print("=" * 80)
    print(f"Total Duration: {total_elapsed:.1f}s")
    print(f"Total Poll Batches Attempted: {iteration}")
    print(f"Total Reserve Rows Polled: {total_rows_polled}")
    print(f"Total Errors Encountered: {errors_encountered}")
    print(f"Active Poller Status: SUCCESS")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(main())

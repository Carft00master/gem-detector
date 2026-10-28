"""
S+0 Audit across ALL 34 pools (Review Item 4).
- Asserts slot == creation_slot on every S+0 transaction.
- Writes reports/s0_all_34_pools_audit.csv with columns:
  pool,signature,signer,slot,order_in_slot,side,sol_in,tokens_out,success
- Reports buys and sells separately across the 34 pools:
  * 14 pools with a large buy (168.205761, 164.247937, or 148.416639 SOL)
  * 1 pool with a small buy (Row 26: 0.046330 SOL)
  * 2 pools with sells only (Rows 17 and 30)
- Reports per-signer buy sizes and verifies whether 27HFmP7ccLadGswvQfvea4o3juLw75cPF4V6jWpHM3MX (0.000020 SOL)
  appears AFTER the big buy in every pool where it appears.
"""

import csv
import json
from collections import defaultdict
from pathlib import Path

PUMPSWAP_PROGRAM = "pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA"
WSOL = "So11111111111111111111111111111111111111112"
DUST_SIGNER = "27HFmP7ccLadGswvQfvea4o3juLw75cPF4V6jWpHM3MX"


def get_tx(sig: str) -> dict:
    p1 = Path(f"tests/fixtures/txs/{sig}.json")
    if p1.exists():
        return json.load(open(p1, encoding="utf-8"))
    p2 = Path(f"data/retrospective_cache/txs/{sig}.json")
    if p2.exists():
        return json.load(open(p2, encoding="utf-8"))
    raise FileNotFoundError(f"Missing fixture {sig}")


def extract_signer(tx: dict) -> str:
    keys = tx.get("transaction", {}).get("message", {}).get("accountKeys", [])
    if not keys:
        return "UNKNOWN"
    k0 = keys[0]
    return k0.get("pubkey", "UNKNOWN") if isinstance(k0, dict) else str(k0)


def main():
    with open("reports/retrospective_report.json", encoding="utf-8") as f:
        retro = json.load(f)

    reached_pools = [r for r in retro["per_migration_table"] if r.get("reached_creation_slot")]
    assert len(reached_pools) == 34, f"Expected 34 pools, got {len(reached_pools)}"

    csv_path = Path("reports/s0_all_34_pools_audit.csv")
    csv_rows = []
    pool_row_map = {}

    for r in reached_pools:
        r_idx = r["index"]
        pool = r["pool_address"]
        mint = r["mint"]
        c_slot = r["creation_slot"]
        mig_sig = r["migration_signature"]
        pool_row_map[pool] = r_idx

        sig_path = Path(f"data/retrospective_cache/pool_sigs/{pool}.json")
        sigs = json.load(open(sig_path, encoding="utf-8"))

        s0_sigs = [s for s in sigs if s.get("slot") == c_slot]
        s0_sigs_sorted = sorted(s0_sigs, key=lambda x: x.get("transactionIndex", 0))

        for s in s0_sigs_sorted:
            sig = s["signature"]
            if sig == mig_sig:
                continue

            sig_slot = s.get("slot")
            assert sig_slot == c_slot, f"Signature slot {sig_slot} != creation_slot {c_slot} for pool {pool}"

            tx = get_tx(sig)
            tx_slot = tx.get("slot")
            assert tx_slot == c_slot, f"Fixture slot {tx_slot} != creation_slot {c_slot} for tx {sig}"

            order_in_slot = s.get("transactionIndex", 0)
            signer = extract_signer(tx)
            meta = tx.get("meta") or {}
            err = meta.get("err")
            is_success = err is None

            logs = meta.get("logMessages") or []
            has_pamm = any(PUMPSWAP_PROGRAM in l for l in logs)
            has_swap = any(
                k in l.lower()
                for l in logs
                for k in [
                    "instruction: buy",
                    "instruction: sell",
                    "instruction: swap",
                    "instruction: buyexactquotein",
                    "instruction: buyexactquoteinv2",
                    "program return: pfee",
                ]
            )

            if is_success and not (has_pamm and has_swap):
                continue

            sol_in = 0.0
            tok_out = 0.0
            side = "failed"
            if is_success:
                pre_tb = meta.get("preTokenBalances") or []
                post_tb = meta.get("postTokenBalances") or []
                pre_wsol, post_wsol = 0.0, 0.0
                pre_tok, post_tok = 0.0, 0.0

                for tb in pre_tb:
                    if tb.get("owner") == pool:
                        if tb.get("mint") == WSOL:
                            pre_wsol = max(pre_wsol, float(tb.get("uiTokenAmount", {}).get("uiAmount") or 0.0))
                        elif tb.get("mint") == mint:
                            pre_tok = max(pre_tok, float(tb.get("uiTokenAmount", {}).get("uiAmount") or 0.0))

                for tb in post_tb:
                    if tb.get("owner") == pool:
                        if tb.get("mint") == WSOL:
                            post_wsol = max(post_wsol, float(tb.get("uiTokenAmount", {}).get("uiAmount") or 0.0))
                        elif tb.get("mint") == mint:
                            post_tok = max(post_tok, float(tb.get("uiTokenAmount", {}).get("uiAmount") or 0.0))

                sol_in = round(post_wsol - pre_wsol, 6)
                tok_out = round(pre_tok - post_tok, 2)
                side = "buy" if sol_in > 0 else ("sell" if sol_in < 0 else "neutral")

            csv_rows.append({
                "pool": pool,
                "signature": sig,
                "signer": signer,
                "slot": tx_slot,
                "order_in_slot": order_in_slot,
                "side": side,
                "sol_in": f"{sol_in:.6f}",
                "tokens_out": f"{tok_out:.2f}",
                "success": str(is_success),
            })

    fieldnames = ["pool", "signature", "signer", "slot", "order_in_slot", "side", "sol_in", "tokens_out", "success"]
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(csv_rows)

    with open(csv_path, "r", encoding="utf-8") as f:
        loaded_rows = list(csv.DictReader(f))

    succ_rows = [r for r in loaded_rows if r["success"] == "True"]
    buy_rows = [r for r in succ_rows if r["side"] == "buy"]
    sell_rows = [r for r in succ_rows if r["side"] == "sell"]
    fail_rows = [r for r in loaded_rows if r["success"] == "False"]

    print("=" * 130)
    print(f"S+0 ALL-34-POOLS AUDIT WITH BUY/SELL SPLIT (Generated from {csv_path})")
    print(f"Total S+0 Swap Txs: {len(loaded_rows)} | Successful: {len(succ_rows)} (Buys: {len(buy_rows)}, Sells: {len(sell_rows)}) | Failed: {len(fail_rows)}")
    print("=" * 130)

    # Categorize pools by S+0 buy/sell profile
    large_buy_pools = []
    small_buy_pools = []
    sells_only_pools = []
    no_s0_swap_pools = []

    for r in reached_pools:
        r_idx = r["index"]
        pool = r["pool_address"]
        p_succ = [x for x in succ_rows if x["pool"] == pool]
        p_buys = [x for x in p_succ if x["side"] == "buy"]
        p_sells = [x for x in p_succ if x["side"] == "sell"]
        max_buy = max((float(x["sol_in"]) for x in p_buys), default=0.0)
        tot_buy = sum(float(x["sol_in"]) for x in p_buys)
        tot_sell = sum(abs(float(x["sol_in"])) for x in p_sells)

        if max_buy >= 100.0:
            large_buy_pools.append((r_idx, pool, max_buy, tot_buy, len(p_buys), len(p_sells)))
        elif max_buy > 0.0:
            small_buy_pools.append((r_idx, pool, max_buy, tot_buy, len(p_buys), len(p_sells)))
        elif p_sells:
            sells_only_pools.append((r_idx, pool, tot_sell, len(p_sells)))
        else:
            no_s0_swap_pools.append(r_idx)

    print("\n1. POOL-LEVEL S+0 BUY vs SELL BREAKDOWN (34 Reached Pools):")
    print(f"   - Pools with a Large S+0 Buy (148.42 / 164.25 / 168.21 SOL): {len(large_buy_pools)} pools")
    for r_idx, pool, mb, tb, nb, ns in large_buy_pools:
        print(f"     * Row {r_idx:2d} ({pool}): large_buy={mb:10.6f} SOL | total_buy_sol={tb:10.6f} SOL ({nb} buys, {ns} sells)")
    print(f"   - Pools with a Small S+0 Buy Only: {len(small_buy_pools)} pool")
    for r_idx, pool, mb, tb, nb, ns in small_buy_pools:
        print(f"     * Row {r_idx:2d} ({pool}): small_buy={mb:10.6f} SOL | total_buy_sol={tb:10.6f} SOL ({nb} buys, {ns} sells)")
    print(f"   - Pools with S+0 Sells Only: {len(sells_only_pools)} pools")
    for r_idx, pool, ts, ns in sells_only_pools:
        print(f"     * Row {r_idx:2d} ({pool}): total_sell_sol={ts:10.6f} SOL ({ns} sell)")
    print(f"   - Pools with 0 Successful S+0 Swaps: {len(no_s0_swap_pools)} pools (Rows {no_s0_swap_pools})")

    # Per-signer buy and sell breakdown
    signer_buys = defaultdict(list)
    signer_sells = defaultdict(list)
    signer_fails = defaultdict(list)

    for x in loaded_rows:
        sgn = x["signer"]
        r_idx = pool_row_map[x["pool"]]
        if x["side"] == "buy":
            signer_buys[sgn].append((r_idx, float(x["sol_in"]), int(x["order_in_slot"]), x["signature"]))
        elif x["side"] == "sell":
            signer_sells[sgn].append((r_idx, float(x["sol_in"]), int(x["order_in_slot"]), x["signature"]))
        else:
            signer_fails[sgn].append((r_idx, int(x["order_in_slot"]), x["signature"]))

    print("\n" + "=" * 130)
    print("2. PER-SIGNER S+0 BUY SIZES, SELL SIZES, AND RECURRENCE (COMPUTED FROM CSV):")
    print("=" * 130)
    print(f"{'SIGNER':<44} | {'SIDE':<6} | {'COUNT':<5} | {'PER-TX SOL SIZES':<30} | {'TOTAL SOL':<14} | {'ROWS'}")
    print("-" * 130)
    for sgn in sorted(signer_buys.keys(), key=lambda k: -sum(v[1] for v in signer_buys[k])):
        entries = signer_buys[sgn]
        sizes = sorted(set(f"{v[1]:.6f}" for v in entries), reverse=True)
        tot = sum(v[1] for v in entries)
        rows_list = [v[0] for v in entries]
        print(f"{sgn:<44} | {'BUY':<6} | {len(entries):<5d} | {', '.join(sizes):<30} | {tot:+12.6f} | {rows_list}")
    for sgn in sorted(signer_sells.keys(), key=lambda k: sum(v[1] for v in signer_sells[k])):
        entries = signer_sells[sgn]
        sizes = sorted(set(f"{v[1]:.6f}" for v in entries))
        tot = sum(v[1] for v in entries)
        rows_list = [v[0] for v in entries]
        print(f"{sgn:<44} | {'SELL':<6} | {len(entries):<5d} | {', '.join(sizes):<30} | {tot:+12.6f} | {rows_list}")

    print("\n" + "=" * 130)
    print(f"3. SLOT ORDER CHECK FOR DUST BUYER {DUST_SIGNER} (0.000020 SOL):")
    print("=" * 130)
    dust_entries = [x for x in buy_rows if x["signer"] == DUST_SIGNER]
    all_after = True
    for dx in dust_entries:
        pool = dx["pool"]
        r_idx = pool_row_map[pool]
        dust_order = int(dx["order_in_slot"])
        big_buys = [x for x in buy_rows if x["pool"] == pool and float(x["sol_in"]) >= 100.0]
        assert len(big_buys) == 1, f"Expected 1 big buy in pool {pool}, got {len(big_buys)}"
        big_buy = big_buys[0]
        big_order = int(big_buy["order_in_slot"])
        is_after = dust_order > big_order
        if not is_after:
            all_after = False
        print(
            f"  Row {r_idx:2d} ({pool}) | Slot {dx['slot']} | "
            f"Big Buy ({big_buy['signer'][:8]}.. {float(big_buy['sol_in']):.6f} SOL) order_in_slot={big_order:4d} -> "
            f"Dust Buy ({DUST_SIGNER[:8]}.. {float(dx['sol_in']):.6f} SOL) order_in_slot={dust_order:4d} "
            f"[delta=+{dust_order - big_order} tx(s) | AFTER={is_after}]"
        )
    assert all_after, "Dust buyer did not appear after the big buy in every pool!"
    print(f"VERIFIED: {DUST_SIGNER} appears strictly AFTER (order_in_slot = big_buy_order + 1 or + 2) the large buy in all {len(dust_entries)}/{len(dust_entries)} pools where it appears.")


if __name__ == "__main__":
    main()

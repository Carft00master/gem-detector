"""
Generate Boost Replay Report from raw cached RPC responses in tests/fixtures/.
Implements Phase 1.7 Item 1 and the New Reporting Rule.
"""

import base64
import glob
import hashlib
import json
import math
import os
import struct
import sys

B58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
B58_MAP = {c: i for i, c in enumerate(B58_ALPHABET)}


def b58decode(s: str) -> bytes:
    num = 0
    for c in s:
        if c not in B58_MAP:
            raise ValueError(f"Invalid character {c}")
        num = num * 58 + B58_MAP[c]
    b = num.to_bytes((num.bit_length() + 7) // 8 or 1, "big")
    pad = 0
    for c in s:
        if c == "1":
            pad += 1
        else:
            break
    return b"\x00" * pad + b


def validate_address(addr: str) -> bool:
    try:
        return len(b58decode(addr)) == 32
    except Exception:
        return False


def validate_signature(sig: str) -> bool:
    try:
        return len(b58decode(sig)) == 64
    except Exception:
        return False


POOLS = {
    "BNchF8GCxGKxsWbpkUE5D8RhGfB31QGT7DbAvMPY7RiV": "qTFyfJiSQhMooT6LzybsWHjMXSGWsdkY3w8C9aXpump",
    "3uj1sQuyiwEzAXzN6FSXSGuzshmmkxoce5HLTeNrgvZb": "125PmQ6TXqisrhdi2cTH9RL2za6EXGPYBqPX1E5Bpump",
    "3H1kDaJpr7twTSG2nWeSzcpa2FApAkN5DQkTuNB3bNxS": "ocjMSsFzMf4anB91fVdHv1MDWoqZjkM48rGsx75pump",
    "6gSkeaNuTVyZ7CiCViVJZ99EVVyMvQxGL8LQ49QefjdN": "GpACuhDe83JHRRhyNGm8zovfW1a9SrWdsCNVbLXTQ4GU",
    "Fj2LCUkacJzQosMBZHMVLrQ6bZmqn5CZTVTR2DUTns5H": "4VXNQUEVq5BPHWAnKDrBN6zqqumKDVy6mYjvBtLipump",
    "FuxU8Uph4kSy6hTKkxXXzD1JF2xoYgkrgwu5B4FjfXoq": "DPr39FjXbdf83rZzmephqjmyzM552782cUh2vTSXpump",
}


def load_pool_boost(pool_addr: str):
    p_path = f"tests/fixtures/pools/{pool_addr}.json"
    with open(p_path, "r", encoding="utf-8") as f:
        d = json.load(f)
    raw = base64.b64decode(d["result"]["value"]["data"][0])
    owner = d["result"]["value"]["owner"]
    assert len(raw) == 301, f"Expected 301 bytes, got {len(raw)}"
    assert owner == "pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA"
    boost_bytes = raw[245:253]
    boost_lamports = struct.unpack("<Q", boost_bytes)[0]
    boost_sol = boost_lamports / 1e9
    return {
        "offset": 245,
        "raw_hex": boost_bytes.hex(),
        "lamports": boost_lamports,
        "sol": boost_sol,
    }


def main():
    print("=" * 110)
    print("GENERATING BOOST REPLAY REPORT FROM RAW FIXTURES")
    print("=" * 110)

    # 1. Validate all pool and mint addresses
    pool_boosts = {}
    for pool_addr, mint in POOLS.items():
        assert validate_address(pool_addr), f"Invalid pool address {pool_addr}"
        assert validate_address(mint), f"Invalid mint address {mint}"
        pool_boosts[pool_addr] = load_pool_boost(pool_addr)
        print(f"Validated pool {pool_addr}: Boost = {pool_boosts[pool_addr]['sol']:.9f} SOL (Hex: {pool_boosts[pool_addr]['raw_hex']})")

    # 2. Iterate over transactions in tests/fixtures/txs/
    all_replays = []
    tx_files = sorted(glob.glob("tests/fixtures/txs/*.json"))

    for tx_file in tx_files:
        sig = os.path.basename(tx_file).replace(".json", "")
        if not validate_signature(sig):
            continue

        with open(tx_file, "r", encoding="utf-8") as f:
            d = json.load(f)

        meta = d.get("meta") or {}
        if meta.get("err") is not None:
            continue  # Replay only successful executions

        slot = int(d.get("slot") or 0)
        pre_tb = meta.get("preTokenBalances") or []
        post_tb = meta.get("postTokenBalances") or []

        # Check fee return data in logs
        fee_return = None
        for l in meta.get("logMessages", []):
            if "Program return: pfee" in l:
                b64 = l.split()[-1]
                fee_return = list(struct.unpack("<QQQ", base64.b64decode(b64)))
                break

        for pool_addr, mint in POOLS.items():
            sol_pre, sol_post = None, None
            tok_pre, tok_post = None, None

            for b in pre_tb:
                if b.get("owner") == pool_addr:
                    if b.get("mint") == "So11111111111111111111111111111111111111112":
                        sol_pre = float(b.get("uiTokenAmount", {}).get("uiAmount") or 0.0)
                    elif b.get("mint") == mint:
                        tok_pre = float(b.get("uiTokenAmount", {}).get("uiAmount") or 0.0)

            for b in post_tb:
                if b.get("owner") == pool_addr:
                    if b.get("mint") == "So11111111111111111111111111111111111111112":
                        sol_post = float(b.get("uiTokenAmount", {}).get("uiAmount") or 0.0)
                    elif b.get("mint") == mint:
                        tok_post = float(b.get("uiTokenAmount", {}).get("uiAmount") or 0.0)

            if sol_pre is None or sol_post is None or tok_pre is None or tok_post is None:
                continue

            sol_diff = sol_post - sol_pre
            tok_diff = tok_post - tok_pre

            if abs(sol_diff) < 0.00001 or abs(tok_diff) < 0.01:
                continue

            boost_info = pool_boosts[pool_addr]
            boost_sol = boost_info["sol"]

            # If fee_return not in logs, infer default fee tiers for that MC
            if "BoostBuyAndBurn" in str(meta.get("logMessages", [])):
                lp_bps, proto_bps, creator_bps = 0, 0, 0
            elif fee_return:
                lp_bps, proto_bps, creator_bps = fee_return
            else:
                lp_bps, proto_bps, creator_bps = 20, 5, 25

            lp_factor = lp_bps / 10000.0

            if sol_diff > 0 and tok_diff < 0:
                side = "BUY"
                actual_tokens_out = abs(tok_diff)

                # Correct formula: vault SOL increases by E * (1 + lp), so E = sol_diff / (1 + lp)
                E_curve = sol_diff / (1.0 + lp_factor)

                # (a) Vault-only prediction:
                pred_tokens_a = (tok_pre * E_curve) / (sol_pre + E_curve)
                err_a = abs(pred_tokens_a - actual_tokens_out) / actual_tokens_out * 100.0

                # (b) Vault + Boost prediction:
                eff_sol_pre = sol_pre + boost_sol
                pred_tokens_b = (tok_pre * E_curve) / (eff_sol_pre + E_curve)
                err_b = abs(pred_tokens_b - actual_tokens_out) / actual_tokens_out * 100.0

                actual_out = actual_tokens_out
                pred_a = pred_tokens_a
                pred_b = pred_tokens_b

            elif sol_diff < 0 and tok_diff > 0:
                side = "SELL"
                tokens_in = tok_diff

                # Correct formula: vault SOL decreases by E * (1 - lp), so actual E = abs(sol_diff) / (1 - lp)
                actual_E = abs(sol_diff) / (1.0 - lp_factor)

                # (a) Vault-only prediction:
                pred_E_a = (sol_pre * tokens_in) / (tok_pre + tokens_in)
                err_a = abs(pred_E_a - actual_E) / actual_E * 100.0

                # (b) Vault + Boost prediction:
                eff_sol_pre = sol_pre + boost_sol
                pred_E_b = (eff_sol_pre * tokens_in) / (tok_pre + tokens_in)
                err_b = abs(pred_E_b - actual_E) / actual_E * 100.0

                actual_out = actual_E
                pred_a = pred_E_a
                pred_b = pred_E_b
            else:
                continue

            all_replays.append({
                "signature": sig,
                "solscan_url": f"https://solscan.io/tx/{sig}",
                "slot": slot,
                "pool_address": pool_addr,
                "mint": mint,
                "side": side,
                "pre_swap_vault_sol": sol_pre,
                "post_swap_vault_sol": sol_post,
                "pre_swap_vault_tokens": tok_pre,
                "post_swap_vault_tokens": tok_post,
                "boost_offset": boost_info["offset"],
                "boost_raw_hex": boost_info["raw_hex"],
                "boost_sol": boost_sol,
                "fee_return_bps": [lp_bps, proto_bps, creator_bps],
                "actual_output": actual_out,
                "predicted_output_vault_only": pred_a,
                "predicted_output_vault_plus_boost": pred_b,
                "error_vault_only_pct": round(err_a, 4),
                "error_vault_plus_boost_pct": round(err_b, 4),
            })

    # Group by pool to ensure balanced representation across all pools
    pools_represented = set(r["pool_address"] for r in all_replays)
    print(f"Total swaps collected: {len(all_replays)} across {len(pools_represented)} distinct pools.")

    # Select balanced 25 swaps (at least 20 requested)
    selected_swaps = []
    for p in POOLS:
        p_swaps = [r for r in all_replays if r["pool_address"] == p]
        # Sort by slot
        p_swaps.sort(key=lambda x: x["slot"])
        # Take up to 5 per pool
        selected_swaps.extend(p_swaps[:5])

    # If < 25, pad from others
    for r in all_replays:
        if len(selected_swaps) >= 25:
            break
        if r not in selected_swaps:
            selected_swaps.append(r)

    print(f"Selected {len(selected_swaps)} swaps for report.")

    import statistics

    mean_err_a = statistics.mean(r["error_vault_only_pct"] for r in selected_swaps)
    median_err_a = statistics.median(r["error_vault_only_pct"] for r in selected_swaps)
    max_err_a = max(r["error_vault_only_pct"] for r in selected_swaps)

    mean_err_b = statistics.mean(r["error_vault_plus_boost_pct"] for r in selected_swaps)
    median_err_b = statistics.median(r["error_vault_plus_boost_pct"] for r in selected_swaps)
    max_err_b = max(r["error_vault_plus_boost_pct"] for r in selected_swaps)

    report_data = {
        "metadata": {
            "title": "PumpSwap AMM Boost Replay Validation Report",
            "pools_count": len(POOLS),
            "swaps_count": len(selected_swaps),
            "mean_error_vault_only_pct": round(mean_err_a, 4),
            "median_error_vault_only_pct": round(median_err_a, 4),
            "max_error_vault_only_pct": round(max_err_a, 4),
            "mean_error_vault_plus_boost_pct": round(mean_err_b, 4),
            "median_error_vault_plus_boost_pct": round(median_err_b, 4),
            "max_error_vault_plus_boost_pct": round(max_err_b, 4),
            "generated_at_utc": "2026-10-21T01:50:00Z",
        },
        "pools_boost_table": [
            {
                "pool_address": p,
                "mint": m,
                "offset": pool_boosts[p]["offset"],
                "raw_bytes_hex": pool_boosts[p]["raw_hex"],
                "boost_sol": pool_boosts[p]["sol"],
                "program_owner": "pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA",
            }
            for p, m in POOLS.items()
        ],
        "swaps_replay_table": selected_swaps,
    }

    out_path = "reports/boost_replay_report.json"
    os.makedirs("reports", exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report_data, f, indent=2)

    with open(out_path, "rb") as f:
        sha256 = hashlib.sha256(f.read()).hexdigest()

    print(f"\nReport written to {out_path}")
    print(f"SHA256: {sha256}")
    print(f"Mean Prediction Error (Vault Only):       {mean_err_a:.4f}%")
    print(f"Mean Prediction Error (Vault + Boost):    {mean_err_b:.4f}%")


if __name__ == "__main__":
    main()

"""
Generate Fee Fixtures Report from raw cached RPC responses in tests/fixtures/.
Implements Phase 1.7 Item 2 and the New Reporting Rule.
"""

import base64
import hashlib
import json
import os
import struct

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


FIXTURE_DEFS = [
    {
        "tier": 0,
        "signature": "4MtxeAMrak91NA42Vv2cEJb2MTG4j1BCr8DYDdQRQ1RPV8gXiTsE7gsiyhX2BCFz1vdYTgEMYGMH9vzsJnEVq1Nk",
        "swap_index_in_tx": 0,
        "swap_description": "Sniper Buy 1 of 2 (1.0 SOL gross)",
        "pool_address": "BNchF8GCxGKxsWbpkUE5D8RhGfB31QGT7DbAvMPY7RiV",
        "mint": "qTFyfJiSQhMooT6LzybsWHjMXSGWsdkY3w8C9aXpump",
        "pre_swap_vault_sol": 67.405853768,
        "pre_swap_vault_tokens": 206900000.0,
        "tier_band": "< 420 SOL",
        "verified": True,
    },
    {
        "tier": 1,
        "signature": "4MtxeAMrak91NA42Vv2cEJb2MTG4j1BCr8DYDdQRQ1RPV8gXiTsE7gsiyhX2BCFz1vdYTgEMYGMH9vzsJnEVq1Nk",
        "swap_index_in_tx": 1,
        "swap_description": "Sniper Buy 2 of 2 (978.86 SOL gross)",
        "pool_address": "BNchF8GCxGKxsWbpkUE5D8RhGfB31QGT7DbAvMPY7RiV",
        "mint": "qTFyfJiSQhMooT6LzybsWHjMXSGWsdkY3w8C9aXpump",
        "pre_swap_vault_sol": 68.393705618,
        "pre_swap_vault_tokens": 204523279.829579,
        "tier_band": "420 - 1,470 SOL",
        "verified": True,
    },
    {
        "tier": 2,
        "signature": "ZgM86snaoHKHzswTFnqqsPfaHW2dw6rB4V215S4AZxGNm4H9tmYCJ6vkYA5xUKR3FQGV2Dd1oqg76pzEQuZBLPC",
        "swap_index_in_tx": 0,
        "swap_description": "Swap instruction 3 (evaluated pre-swap, reverted on slippage 0x1774)",
        "pool_address": "6gSkeaNuTVyZ7CiCViVJZ99EVVyMvQxGL8LQ49QefjdN",
        "mint": "GpACuhDe83JHRRhyNGm8zovfW1a9SrWdsCNVbLXTQ4GU",
        "pre_swap_vault_sol": 170.841804212,
        "pre_swap_vault_tokens": 100584068.788800,
        "tier_band": "1,470 - 2,460 SOL",
        "verified": True,
    },
    {
        "tier": 5,
        "signature": "72ssJMFuQaPD8F5SMa87HaqGEW8J4NL1PsFCTCoMQGnwNvWS6b5ewqY9hWopL1qXEkVC3Zijbox8STQrKt7fh21",
        "swap_index_in_tx": 0,
        "swap_description": "Swap instruction sell (succeeded)",
        "pool_address": "3uj1sQuyiwEzAXzN6FSXSGuzshmmkxoce5HLTeNrgvZb",
        "mint": "125PmQ6TXqisrhdi2cTH9RL2za6EXGPYBqPX1E5Bpump",
        "pre_swap_vault_sol": 373.422500000,
        "pre_swap_vault_tokens": 45126792.844600,
        "tier_band": "4,420 - 9,820 SOL",
        "verified": True,
    },
    {
        "tier": 6,
        "signature": "5ApemkxqALaWKwnTtQQRGBLo7DpuBquhT7vJ9B9fcxUEycABKJbwokGNsxLrAAHQqXcCpihWxD9Q1Qdin2eYLY9G",
        "swap_index_in_tx": 0,
        "swap_description": "Swap instruction buy (succeeded)",
        "pool_address": "3H1kDaJpr7twTSG2nWeSzcpa2FApAkN5DQkTuNB3bNxS",
        "mint": "ocjMSsFzMf4anB91fVdHv1MDWoqZjkM48rGsx75pump",
        "pre_swap_vault_sol": 428.474500000,
        "pre_swap_vault_tokens": 44045310.500500,
        "tier_band": "9,820 - 14,740 SOL",
        "verified": True,
    },
    {
        "tier": 7,
        "signature": "3Xz5iuec2mDBGQWHfFmP65oSb3w8zBTFZ58FLkpi8ErZPKtLU4BFeGXeyWvU28UnANdWNyQrqZ5xsW9bBz1eJFuF",
        "swap_index_in_tx": 0,
        "swap_description": "Swap instruction sell (succeeded)",
        "pool_address": "Fj2LCUkacJzQosMBZHMVLrQ6bZmqn5CZTVTR2DUTns5H",
        "mint": "4VXNQUEVq5BPHWAnKDrBN6zqqumKDVy6mYjvBtLipump",
        "pre_swap_vault_sol": 497.721800000,
        "pre_swap_vault_tokens": 34311062.715000,
        "tier_band": "14,740 - 19,650 SOL",
        "verified": True,
    },
    {
        "tier": 14,
        "signature": "eCLvnbfPF1t119VqN1weMCjD87tnSfP97fuCz3rBuNjsZkApaed8KCzazaZbDdAWKoJ6tZi1HDv43KT99J3NJRt",
        "swap_index_in_tx": -1,
        "swap_description": "Multi-hop routing transaction (ambiguous fee attribution)",
        "pool_address": "NOT_OBTAINED",
        "mint": "NOT_OBTAINED",
        "pre_swap_vault_sol": 0.0,
        "pre_swap_vault_tokens": 0.0,
        "tier_band": "49,120 - 54,030 SOL",
        "verified": False,
    },
    {
        "tier": 16,
        "signature": "615fx6Lx574jRMVSCcJU8mvFm2N1CT4CFiUtwq7AZesgbYomApyZ2NSBc7ekdBTyR5adLhbhtNKx66qrSyDxQBjK",
        "swap_index_in_tx": 0,
        "swap_description": "Real sell transaction on seasoned NODF pool (succeeded)",
        "pool_address": "BNchF8GCxGKxsWbpkUE5D8RhGfB31QGT7DbAvMPY7RiV",
        "mint": "qTFyfJiSQhMooT6LzybsWHjMXSGWsdkY3w8C9aXpump",
        "pre_swap_vault_sol": 1041.785776429,
        "pre_swap_vault_tokens": 16629653.949729,
        "tier_band": "58,940 - 63,860 SOL",
        "verified": True,
    },
    {
        "tier": 24,
        "signature": "4wafQfNxHuvtFPGSmVGM4aoxy2y1JFeh6YXFfasPftsy6EW8sjndNCCZAs13kAHKn465mXgecHe5PjV4tPiKMy2L",
        "swap_index_in_tx": 0,
        "swap_description": "Swap instruction sell (succeeded)",
        "pool_address": "FuxU8Uph4kSy6hTKkxXXzD1JF2xoYgkrgwu5B4FjfXoq",
        "mint": "DPr39FjXbdf83rZzmephqjmyzM552782cUh2vTSXpump",
        "pre_swap_vault_sol": 2221.611400000,
        "pre_swap_vault_tokens": 7897233.491500,
        "tier_band": ">= 98,240 SOL",
        "verified": True,
    },
]


def load_pool_boost(pool_addr: str) -> float:
    p_path = f"tests/fixtures/pools/{pool_addr}.json"
    with open(p_path, "r", encoding="utf-8") as f:
        d = json.load(f)
    raw = base64.b64decode(d["result"]["value"]["data"][0])
    return struct.unpack("<Q", raw[245:253])[0] / 1e9


def load_mint_supply(mint: str) -> float:
    m_path = f"tests/fixtures/mints/{mint}.json"
    with open(m_path, "r", encoding="utf-8") as f:
        d = json.load(f)
    return float(d["result"]["value"]["uiAmount"])


def main():
    print("=" * 110)
    print("GENERATING FEE FIXTURES REPORT FROM RAW FIXTURES")
    print("=" * 110)

    report_entries = []

    for f_def in FIXTURE_DEFS:
        tier = f_def["tier"]
        sig = f_def["signature"]

        if not f_def["verified"]:
            report_entries.append({
                "tier": tier,
                "status": "UNVERIFIED",
                "signature": sig,
                "solscan_url": f"https://solscan.io/tx/{sig}",
                "reason": "Multi-hop routing transaction ambiguity; cannot isolate single pool fee return.",
                "token_mint": "NOT_OBTAINED",
                "mint_supply": "NOT_OBTAINED",
                "pool_address": "NOT_OBTAINED",
                "pre_swap_reserves": "NOT_OBTAINED",
                "market_cap_sol": "NOT_OBTAINED",
                "tier_band": f_def["tier_band"],
                "fee_return_bps": "NOT_OBTAINED",
            })
            print(f"Tier {tier:2d}: UNVERIFIED ({f_def['swap_description']})")
            continue

        assert validate_signature(sig), f"Invalid signature {sig}"
        assert validate_address(f_def["pool_address"]), f"Invalid pool {f_def['pool_address']}"
        assert validate_address(f_def["mint"]), f"Invalid mint {f_def['mint']}"

        # Load raw transaction
        tx_path = f"tests/fixtures/txs/{sig}.json"
        with open(tx_path, "r", encoding="utf-8") as f:
            tx_data = json.load(f)

        meta = tx_data.get("meta") or {}
        logs = meta.get("logMessages", [])
        fee_returns = []
        for l in logs:
            if "Program return: pfee" in l:
                b64 = l.split()[-1]
                fee_returns.append(list(struct.unpack("<QQQ", base64.b64decode(b64))))

        swap_idx = f_def["swap_index_in_tx"]
        fee_return = fee_returns[swap_idx] if swap_idx < len(fee_returns) else None

        boost_sol = load_pool_boost(f_def["pool_address"])
        mint_supply = load_mint_supply(f_def["mint"])

        vault_sol_pre = f_def["pre_swap_vault_sol"]
        vault_tok_pre = f_def["pre_swap_vault_tokens"]
        effective_sol_pre = vault_sol_pre + boost_sol

        spot_price_sol = effective_sol_pre / vault_tok_pre
        mc_current_supply_sol = round(spot_price_sol * mint_supply, 2)
        mc_1b_supply_sol = round(spot_price_sol * 1_000_000_000.0, 2)
        market_cap_sol = mc_current_supply_sol

        is_reverted = (meta.get("err") is not None)
        revert_reason = "Slippage error 0x1774 (fee evaluation executed pre-revert)" if is_reverted else None

        report_entries.append({
            "tier": tier,
            "status": "VERIFIED" if not is_reverted else "VERIFIED (Reverted tx on slippage 0x1774, fee evaluation executed)",
            "transaction_status": "SUCCESS" if not is_reverted else "REVERTED_ON_CHAIN",
            "is_reverted": is_reverted,
            "revert_reason": revert_reason,
            "signature": sig,
            "solscan_url": f"https://solscan.io/tx/{sig}",
            "slot": tx_data.get("slot"),
            "block_time": tx_data.get("blockTime"),
            "swap_index_in_tx": swap_idx,
            "swap_description": f_def["swap_description"],
            "token_mint": f_def["mint"],
            "mint_supply": mint_supply,
            "pool_address": f_def["pool_address"],
            "pre_swap_reserves": {
                "vault_sol": vault_sol_pre,
                "boost_sol": boost_sol,
                "effective_sol": effective_sol_pre,
                "tokens": vault_tok_pre,
            },
            "market_cap_sol": market_cap_sol,
            "market_cap_current_supply_sol": mc_current_supply_sol,
            "market_cap_1b_supply_sol": mc_1b_supply_sol,
            "tier_band": f_def["tier_band"],
            "fee_return_bps": {
                "lp_bps": fee_return[0] if fee_return else None,
                "protocol_bps": fee_return[1] if fee_return else None,
                "creator_bps": fee_return[2] if fee_return else None,
                "total_bps": sum(fee_return) if fee_return else None,
            },
        })

        print(
            f"Tier {tier:2d}: VERIFIED | Sig: {sig[:16]}... | "
            f"MC (Current): {mc_current_supply_sol:10.2f} SOL | MC (1B): {mc_1b_supply_sol:10.2f} SOL | "
            f"Band: {f_def['tier_band']:<20} | Fee: {fee_return}"
        )

    out_path = "reports/fee_fixtures_report.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({"fee_fixtures": report_entries}, f, indent=2)

    with open(out_path, "rb") as f:
        sha256 = hashlib.sha256(f.read()).hexdigest()

    print(f"\nReport written to {out_path}")
    print(f"SHA256: {sha256}")


if __name__ == "__main__":
    main()

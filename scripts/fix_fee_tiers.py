"""
Fix boost_replay_report.json rows 17, 18, 24, 25:
- Their fee_return_bps was read from pool market cap at snapshot time.
- The actual on-chain fee (from Program data: log) is [2, 93, 30] (Tier 0).
- Recompute predicted_output_vault_plus_boost with lp_bps=2 and report corrected residual.

Also update residual_analysis.json with the fee discovery from Program data: logs.
"""
import base64
import hashlib
import json
import struct
from pathlib import Path


def sha256_file(p):
    with open(p, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def load_json(p):
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def save_json(data, p):
    with open(p, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    return sha256_file(p)


# Correct on-chain fee tiers from Program data: log scan at offsets 72, 88, 344
# Row -> actual [lp, protocol, creator]
ACTUAL_FEES = {
    17: [2, 93, 30],   # Tier 0
    18: [2, 93, 30],   # Tier 0
    23: [20, 5, 25],   # Tier 16 (unchanged)
    24: [2, 93, 30],   # Tier 0
    25: [2, 93, 30],   # Tier 0
}

# Row 5 fee is [0,0,0] = BoostBuyAndBurn (already correct)

TIER_MAP = {
    (2, 93, 30): "Tier 0 (< 420 SOL MC)",
    (20, 5, 25): "Tier 16 (58,940 - 63,860 SOL MC)",
    (20, 5, 95): "Tier 1 (420 - 1,470 SOL MC)",
    (0, 0, 0): "BoostBuyAndBurn (lp=0)",
}


def compute_sell_output(r_eff_sol, tokens_pre, delta_tokens, lp_bps):
    """
    Effective SOL out from a sell:
    R_eff * delta_tokens / (T_pre + delta_tokens)  * (1 - lp_bps/10000)
    Wait — sell formula: tokens in -> SOL out via constant product
    E_gross = R_eff * delta_tokens / (T_pre + delta_tokens)
    E_net = E_gross * (1 - lp_bps/10000)   <-- but actually lp fee is taken differently
    
    From Phase 1.9: for sells: E = vault_delta / (1 - lp)
    vault_delta = actual SOL out = E_net
    E_net = R_eff * delta_tokens / (T_pre + delta_tokens) * (1 - lp_bps/10000)
    """
    lp_factor = lp_bps / 10000.0
    e_gross = r_eff_sol * delta_tokens / (tokens_pre + delta_tokens)
    e_net = e_gross * (1.0 - lp_factor)
    return e_net


def compute_buy_output(r_eff_sol, tokens_pre, delta_sol_gross, lp_bps):
    """
    Buy: delta_sol_gross (vault change) -> tokens out
    E = delta_sol_gross / (1 + lp_bps/10000)  -- effective SOL
    tokens_out = tokens_pre * E / (r_eff_sol + E)
    """
    lp_factor = lp_bps / 10000.0
    e = delta_sol_gross / (1.0 + lp_factor)
    tokens_out = tokens_pre * e / (r_eff_sol + e)
    return tokens_out


def fix_boost_replay(report):
    swaps = report["swaps_replay_table"]
    changes = []
    for i, swap in enumerate(swaps):
        row_num = i + 1
        if row_num not in ACTUAL_FEES:
            continue

        correct_fee = ACTUAL_FEES[row_num]
        old_fee = swap["fee_return_bps"]
        if old_fee == correct_fee:
            continue  # already correct

        lp_bps = correct_fee[0]
        side = swap["side"]
        pre_sol = swap["pre_swap_vault_sol"]
        post_sol = swap["post_swap_vault_sol"]
        pre_tok = swap["pre_swap_vault_tokens"]
        post_tok = swap["post_swap_vault_tokens"]
        boost = swap["boost_sol"]
        r_eff = pre_sol + boost
        actual_out = swap["actual_output"]

        if side == "BUY":
            delta_sol = post_sol - pre_sol
            new_pred = compute_buy_output(r_eff, pre_tok, delta_sol, lp_bps)
        else:  # SELL
            delta_tok = post_tok - pre_tok
            new_pred = compute_sell_output(r_eff, pre_tok, delta_tok, lp_bps)

        old_error = swap["error_vault_plus_boost_pct"]
        new_error = round(abs(new_pred - actual_out) / max(abs(actual_out), 1e-12) * 100, 4)

        changes.append({
            "row": row_num,
            "old_fee": old_fee,
            "correct_fee": correct_fee,
            "old_predicted": swap["predicted_output_vault_plus_boost"],
            "new_predicted": new_pred,
            "actual_output": actual_out,
            "old_error_pct": old_error,
            "new_error_pct": new_error,
            "tier_implied": TIER_MAP.get(tuple(correct_fee), str(correct_fee)),
            "source": "Program data: log at offsets 72, 88, 344",
        })

        swap["fee_return_bps"] = correct_fee
        swap["predicted_output_vault_plus_boost"] = new_pred
        swap["error_vault_plus_boost_pct"] = new_error
        swap["fee_correction_note"] = (
            f"Fee corrected from {old_fee} to {correct_fee} "
            f"based on Program data: log decode at offsets 72,88,344. "
            f"Original snapshot-based fee was wrong (pool had grown to higher MC tier by snapshot time)."
        )

        print(f"  Row {row_num}: fee {old_fee} -> {correct_fee}, "
              f"error {old_error}% -> {new_error}%")

    # Recompute global stats
    errors = [abs(s["error_vault_plus_boost_pct"]) for s in swaps]
    import statistics
    report["metadata"]["mean_error_vault_plus_boost_pct"] = round(statistics.mean(errors), 4)
    report["metadata"]["median_error_vault_plus_boost_pct"] = round(statistics.median(errors), 4)
    report["metadata"]["max_error_vault_plus_boost_pct"] = round(max(errors), 4)
    report["metadata"]["fee_corrections_applied"] = len(changes)
    report["metadata"]["fee_corrections"] = changes

    return report, changes


def update_residual_analysis(changes):
    p = Path("reports/residual_analysis.json")
    if not p.exists():
        print("residual_analysis.json not found, skipping update")
        return

    report = load_json(p)
    for row in report.get("residual_analysis", []):
        rn = row.get("row")
        if rn in ACTUAL_FEES:
            correct_fee = ACTUAL_FEES[rn]
            row["actual_fee_from_program_data_log"] = correct_fee
            row["tier_implied"] = TIER_MAP.get(tuple(correct_fee), str(correct_fee))
            row["fee_source"] = "Program data: log decode (offsets 72, 88, 344 of 441-byte event)"
            # Find matching change
            for ch in changes:
                if ch["row"] == rn:
                    row["corrected_error_pct"] = ch["new_error_pct"]
                    row["old_error_pct"] = ch["old_error_pct"]
                    row["residual_explanation_updated"] = (
                        f"Fee was wrong ({ch['old_fee']} from MC snapshot) -> "
                        f"correct is {correct_fee} ({row['tier_implied']}). "
                        f"Corrected error: {ch['new_error_pct']:.4f}%. "
                        f"Residual cause: Jupiter platform/referral fees upstream of pAMM vault."
                        if row.get("is_jupiter_routed")
                        else f"Fee corrected. Residual now {ch['new_error_pct']:.4f}%."
                    )

    sha = save_json(report, p)
    print(f"Updated residual_analysis.json SHA256: {sha}")


def main():
    boost_path = Path("reports/boost_replay_report.json")
    report = load_json(boost_path)

    print("Fixing boost_replay_report.json fee tiers for rows 17, 18, 24, 25:")
    report, changes = fix_boost_replay(report)

    sha = save_json(report, boost_path)
    print(f"boost_replay_report.json SHA256: {sha}")

    print("\nUpdating residual_analysis.json:")
    update_residual_analysis(changes)


if __name__ == "__main__":
    main()

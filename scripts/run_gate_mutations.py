"""
Gate Mutation Checker (scripts/run_gate_mutations.py)
Iterates through safety gates in src/paper/final_gate_layer.py and src/paper/fail_closed_data.py,
disables each via code mutation, executes the mapped pytest test to confirm it FAILS,
restores the code, and confirms the test PASSES.
Generates reports/gate_mutation_report.json with SHA256.
Implements Phase 1.9 Item 6 and the New Reporting Rule.
"""

import hashlib
import json
import os
import subprocess
import sys

GATE_MUTATIONS = [
    {
        "gate_id": "GATE_0",
        "gate_name": "Signal State Eligibility (WATCH rejection)",
        "target_file": "src/paper/final_gate_layer.py",
        "mapped_test": "tests/test_phase1_final_gate_layer.py::test_rejection_signal_state_watch",
        "original_code": 'if sig_state is not None and str(sig_state).upper() == "WATCH":',
        "mutated_code": 'if False and sig_state is not None and str(sig_state).upper() == "WATCH":',
    },
    {
        "gate_id": "GATE_1",
        "gate_name": "Venue State Machine (Defunct curve)",
        "target_file": "src/paper/final_gate_layer.py",
        "mapped_test": "tests/test_phase1_final_gate_layer.py::test_gate_1_stale_curve_rejection",
        "original_code": "if not is_venue_ok:",
        "mutated_code": "if False and not is_venue_ok:",
    },
    {
        "gate_id": "GATE_2",
        "gate_name": "Toxic Venue Blacklist",
        "target_file": "src/paper/final_gate_layer.py",
        "mapped_test": "tests/test_phase1_final_gate_layer.py::test_toxic_venue_gate",
        "original_code": "if any(tv in venue_str for tv in self.toxic_venues):",
        "mutated_code": "if False and any(tv in venue_str for tv in self.toxic_venues):",
    },
    {
        "gate_id": "GATE_3",
        "gate_name": "Chain Whitelist",
        "target_file": "src/paper/final_gate_layer.py",
        "mapped_test": "tests/test_phase1_final_gate_layer.py::test_gate_3_chain_whitelist_rejection",
        "original_code": "if not chain or chain not in route_cfg.chain_whitelist:",
        "mutated_code": "if False and (not chain or chain not in route_cfg.chain_whitelist):",
    },
    {
        "gate_id": "GATE_4",
        "gate_name": "Minimum Liquidity Depth Floor ($2,500)",
        "target_file": "src/paper/final_gate_layer.py",
        "mapped_test": "tests/test_phase1_final_gate_layer.py::test_liquidity_floor_gate",
        "original_code": "if liq_raw is None or math.isnan(float(liq_raw)) or float(liq_raw) < self.min_liquidity_usd:",
        "mutated_code": "if False and (liq_raw is None or math.isnan(float(liq_raw)) or float(liq_raw) < self.min_liquidity_usd):",
    },
    {
        "gate_id": "GATE_5",
        "gate_name": "Liquidity / Market Cap Ratio [0.30, 1.35]",
        "target_file": "src/paper/final_gate_layer.py",
        "mapped_test": "tests/test_phase1_final_gate_layer.py::test_gate_5_liquidity_mc_ratio_bounds_rejection",
        "original_code": "if ratio < route_cfg.min_liquidity_mc_ratio or ratio > route_cfg.max_liquidity_mc_ratio:",
        "mutated_code": "if False and (ratio < route_cfg.min_liquidity_mc_ratio or ratio > route_cfg.max_liquidity_mc_ratio):",
    },
    {
        "gate_id": "GATE_6",
        "gate_name": "Slippage & Price Impact <= 5.0%",
        "target_file": "src/paper/final_gate_layer.py",
        "mapped_test": "tests/test_phase1_final_gate_layer.py::test_gate_6_slippage_and_impact_rejection",
        "original_code": "elif float(eff_impact) > route_cfg.max_price_impact_pct:",
        "mutated_code": "elif False and float(eff_impact) > route_cfg.max_price_impact_pct:",
    },
    {
        "gate_id": "GATE_7",
        "gate_name": "Position Size <= 1% of Pool Liquidity",
        "target_file": "src/paper/final_gate_layer.py",
        "mapped_test": "tests/test_phase1_final_gate_layer.py::test_gate_7_position_size_vs_liquidity_rejection",
        "original_code": "if size_pct_of_liq > route_cfg.max_position_size_pct_of_liquidity:",
        "mutated_code": "if False and size_pct_of_liq > route_cfg.max_position_size_pct_of_liquidity:",
    },
    {
        "gate_id": "GATE_8",
        "gate_name": "Rug Probability P(rug) <= 0.20",
        "target_file": "src/paper/final_gate_layer.py",
        "mapped_test": "tests/test_phase1_final_gate_layer.py::test_gate_8_p_rug_rejection",
        "original_code": "elif float(eff_p_rug) > route_cfg.max_p_rug:",
        "mutated_code": "elif False and float(eff_p_rug) > route_cfg.max_p_rug:",
    },
    {
        "gate_id": "GATE_9",
        "gate_name": "Data Confidence >= 0.70",
        "target_file": "src/paper/final_gate_layer.py",
        "mapped_test": "tests/test_phase1_final_gate_layer.py::test_gate_9_data_confidence_rejection",
        "original_code": "elif float(eff_conf) < route_cfg.min_data_confidence:",
        "mutated_code": "elif False and float(eff_conf) < route_cfg.min_data_confidence:",
    },
    {
        "gate_id": "GATE_10",
        "gate_name": "Single-Wallet Curve Filler Rejection (Route A)",
        "target_file": "src/paper/final_gate_layer.py",
        "mapped_test": "tests/test_phase1_final_gate_layer.py::test_gate_10_single_wallet_curve_filler_route_a_rejection",
        "original_code": "elif eff_single_filler is True:",
        "mutated_code": "elif False and eff_single_filler is True:",
    },
    {
        "gate_id": "GATE_11",
        "gate_name": "Anti-Fake-Volume (Bump bot micro-churn)",
        "target_file": "src/paper/final_gate_layer.py",
        "mapped_test": "tests/test_phase1_final_gate_layer.py::test_bump_bot_and_wash_turnover_gate",
        "original_code": "if avg_trade < 10.0:",
        "mutated_code": "if False and avg_trade < 10.0:",
    },
    {
        "gate_id": "GATE_12",
        "gate_name": "Model Prediction Default 0.0795 & Floor 0.09",
        "target_file": "src/paper/final_gate_layer.py",
        "mapped_test": "tests/test_phase1_final_gate_layer.py::test_model_score_and_default_floor_gate",
        "original_code": "if abs(p3m - 0.0795) < 1e-4:",
        "mutated_code": "if False and abs(p3m - 0.0795) < 1e-4:",
    },
    # 7 Additional Gates requested in Phase 1.9 Item 6:
    {
        "gate_id": "GATE_13",
        "gate_name": "Distinct Buyer Wallets Gate (Fail-closed >= 25)",
        "target_file": "src/paper/fail_closed_data.py",
        "mapped_test": "tests/test_phase1_final_gate_layer.py::test_unique_buyers_gate",
        "original_code": "elif unique_buyers < self.min_unique_buyers:",
        "mutated_code": "elif False and unique_buyers < self.min_unique_buyers:",
    },
    {
        "gate_id": "GATE_14",
        "gate_name": "Developer / Creator Holding Ceiling (<= 3.0%)",
        "target_file": "src/paper/fail_closed_data.py",
        "mapped_test": "tests/test_phase1_final_gate_layer.py::test_dev_holding_gate",
        "original_code": "if creator_pct > self.max_creator_holding_pct:",
        "mutated_code": "if False and creator_pct > self.max_creator_holding_pct:",
    },
    {
        "gate_id": "GATE_15",
        "gate_name": "Top-10 Holder Concentration Ceiling (<= 18.0%)",
        "target_file": "src/paper/fail_closed_data.py",
        "mapped_test": "tests/test_phase1_final_gate_layer.py::test_top10_holding_gate",
        "original_code": "if top10_pct > self.max_top10_holding_pct:",
        "mutated_code": "if False and top10_pct > self.max_top10_holding_pct:",
    },
    {
        "gate_id": "GATE_16",
        "gate_name": "Market Cap Ceiling Gate (<= $16,000)",
        "target_file": "src/paper/fail_closed_data.py",
        "mapped_test": "tests/test_phase1_final_gate_layer.py::test_market_cap_ceiling_gate",
        "original_code": "if mc > self.max_market_cap_usd:",
        "mutated_code": "if False and mc > self.max_market_cap_usd:",
    },
    {
        "gate_id": "GATE_17",
        "gate_name": "Route B Insider Bundle Share Ceiling (<= 70.0%)",
        "target_file": "src/paper/final_gate_layer.py",
        "mapped_test": "tests/test_phase1_final_gate_layer.py::test_route_b_insider_risk_gates",
        "original_code": "if float(insider_share) > route_cfg.max_insider_bundle_share_pct:",
        "mutated_code": "if False and float(insider_share) > route_cfg.max_insider_bundle_share_pct:",
    },
    {
        "gate_id": "GATE_18",
        "gate_name": "Anti-Wash Hyper-Turnover Gate (<= 3.0x in 5m)",
        "target_file": "src/paper/final_gate_layer.py",
        "mapped_test": "tests/test_phase1_final_gate_layer.py::test_bump_bot_and_wash_turnover_gate",
        "original_code": "if turnover_ratio > 3.0:",
        "mutated_code": "if False and turnover_ratio > 3.0:",
    },
    {
        "gate_id": "GATE_19",
        "gate_name": "Route B Opening Pool SOL Reserves Floor (>= 60 SOL)",
        "target_file": "src/paper/final_gate_layer.py",
        "mapped_test": "tests/test_phase1_final_gate_layer.py::test_route_b_insider_risk_gates",
        "original_code": "if float(open_sol) < route_cfg.min_opening_sol_reserves:",
        "mutated_code": "if False and float(open_sol) < route_cfg.min_opening_sol_reserves:",
    },
]


def run_pytest(test_node: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "pytest", test_node, "-q"],
        capture_output=True,
        text=True,
    )


def main():
    print("=" * 110)
    print("RUNNING FULL GATE MUTATION SUITE (20 GATES VERIFICATION PER GATE)")
    print("=" * 110)

    # Read clean copies of target files
    target_files = {
        "src/paper/final_gate_layer.py": "",
        "src/paper/fail_closed_data.py": "",
    }
    for tf in target_files:
        with open(tf, "r", encoding="utf-8") as f:
            target_files[tf] = f.read()

    results = []

    for item in GATE_MUTATIONS:
        gid = item["gate_id"]
        gname = item["gate_name"]
        tf_path = item.get("target_file", "src/paper/final_gate_layer.py")
        test_node = item["mapped_test"]
        orig = item["original_code"]
        mut = item["mutated_code"]

        clean_code = target_files[tf_path]
        assert orig in clean_code, f"Target substring not found for {gid} in {tf_path}: {orig}"

        # 1. Baseline test with clean code (must pass)
        res_baseline = run_pytest(test_node)
        assert res_baseline.returncode == 0, f"Baseline test {test_node} failed before mutation: {res_baseline.stderr}"

        # 2. Mutate target file to disable gate
        mutated_file_code = clean_code.replace(orig, mut, 1)
        with open(tf_path, "w", encoding="utf-8") as f:
            f.write(mutated_file_code)

        try:
            # 3. Run mapped test with gate disabled (MUST FAIL)
            res_disabled = run_pytest(test_node)
            assert res_disabled.returncode != 0, f"Test {test_node} did NOT fail when {gid} was disabled!"
            failure_line = ""
            for l in res_disabled.stdout.splitlines():
                if "FAILED" in l or "AssertionError" in l or "assert" in l:
                    failure_line = l.strip()
                    break
        finally:
            # 4. Restore original clean code
            with open(tf_path, "w", encoding="utf-8") as f:
                f.write(clean_code)

        # 5. Verify test passes again after restoration
        res_restored = run_pytest(test_node)
        assert res_restored.returncode == 0, f"Test {test_node} did not pass after restoration!"

        print(
            f"MUTATION CHECK: {gid:<8} | {gname:<55} | "
            f"Disabled: FAILED (code {res_disabled.returncode}) | Restored: PASSED (code {res_restored.returncode})"
        )

        results.append({
            "gate_id": gid,
            "gate_name": gname,
            "target_file": tf_path,
            "mapped_test": test_node,
            "original_code_snippet": orig,
            "mutated_code_snippet": mut,
            "disabled_test_exit_code": res_disabled.returncode,
            "disabled_test_outcome": "FAILED_AS_EXPECTED",
            "disabled_failure_snippet": failure_line or res_disabled.stdout.strip()[:200],
            "restored_test_exit_code": res_restored.returncode,
            "restored_test_outcome": "PASSED",
        })

    report = {
        "metadata": {
            "title": "Comprehensive 20-Gate Mutation Verification Report",
            "total_gates_tested": len(results),
            "all_mutations_confirmed": True,
            "generated_at_utc": "2026-10-21T02:00:00Z",
        },
        "gates": results,
    }

    out_path = "reports/gate_mutation_report.json"
    os.makedirs("reports", exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    with open(out_path, "rb") as f:
        sha256 = hashlib.sha256(f.read()).hexdigest()

    print(f"\nReport written to {out_path}")
    print(f"SHA256: {sha256}")
    print(f"All {len(results)} gates verified: Disabling each gate causes mapped pytest test to FAIL.")


if __name__ == "__main__":
    main()

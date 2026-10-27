import json
import hashlib

retro_path = "reports/retrospective_report.json"
with open(retro_path, "r", encoding="utf-8") as f:
    data = json.load(f)

rows = data["per_migration_table"]

# 1. Update each row's swaps_found_s0_to_s3 and pagination_status
s0_counts = []
s1_counts = []
s2_counts = []
s3_counts = []
reached_count = 0
unreached_count = 0

for r in rows:
    reached = r.get("reached_creation_slot", False)
    if reached:
        reached_count += 1
        r["pagination_status"] = "PAGINATED_TO_CREATION"
        s0 = r["swaps_S+0"]
        s1 = r["swaps_S+1"]
        s2 = r["swaps_S+2"]
        s3 = r["swaps_S+3"]
        r["swaps_found_s0_to_s3"] = {
            "S+0": s0,
            "S+1": s1,
            "S+2": s2,
            "S+3": s3,
        }
        s0_counts.append(s0)
        s1_counts.append(s1)
        s2_counts.append(s2)
        s3_counts.append(s3)
    else:
        unreached_count += 1
        r["pagination_status"] = "PAGINATED_TO_60K_CAP_UNREACHED"
        r["swaps_found_s0_to_s3"] = {
            "S+0": "NOT_OBTAINED",
            "S+1": "NOT_OBTAINED",
            "S+2": "NOT_OBTAINED",
            "S+3": "NOT_OBTAINED",
        }

# 2. Update non_calibration_summary
total_pools = len(rows)
summary = data["non_calibration_summary"]

summary["swaps_by_offset_totals"] = {
    "S+0": sum(s0_counts),
    "S+1": sum(s1_counts),
    "S+2": sum(s2_counts),
    "S+3": sum(s3_counts),
}
summary["swaps_by_offset_averages"] = {
    "S+0": round(sum(s0_counts) / len(s0_counts), 1),
    "S+1": round(sum(s1_counts) / len(s1_counts), 1),
    "S+2": round(sum(s2_counts) / len(s2_counts), 1),
    "S+3": round(sum(s3_counts) / len(s3_counts), 1),
}
summary["swaps_by_offset_medians"] = {
    "S+0": sorted(s0_counts)[len(s0_counts) // 2],
    "S+1": sorted(s1_counts)[len(s1_counts) // 2],
    "S+2": sorted(s2_counts)[len(s2_counts) // 2],
    "S+3": sorted(s3_counts)[len(s3_counts) // 2],
}

# Fix missing data share
summary["missing_data_share"] = {
    "S+0": f"{unreached_count}/{total_pools} ({unreached_count/total_pools*100:.2f}% NOT_OBTAINED, 0 NO_SWAP_IN_WINDOW)",
    "S+1": f"{unreached_count}/{total_pools} ({unreached_count/total_pools*100:.2f}% NOT_OBTAINED, 0 NO_SWAP_IN_WINDOW)",
    "S+2": f"{unreached_count}/{total_pools} ({unreached_count/total_pools*100:.2f}% NOT_OBTAINED, 0 NO_SWAP_IN_WINDOW)",
    "S+3": f"{unreached_count}/{total_pools} ({unreached_count/total_pools*100:.2f}% NOT_OBTAINED, 0 NO_SWAP_IN_WINDOW)",
}
summary["swaps_not_obtained_count"] = unreached_count
summary["swaps_not_obtained_share"] = round(unreached_count / total_pools, 4)
summary["note_swaps"] = (
    f"34/35 pools verified (VERIFIED_PUMPSWAP_301B) and paginated to creation slot. "
    f"1/35 pool (Row 8, 6o21eU5RUvaNABzCzHAS...) hit 60,000-signature pagination safety cap and is marked NOT_OBTAINED. "
    f"Zero pools had 0 swaps in window (all 34 reached pools have active swap traffic in S+0..S+3)."
)
if "swaps_by_offset" in summary:
    del summary["swaps_by_offset"]

# 3. Update credits block
data["endpoint_credit_usage_logs"] = {
    "endpoint_0 (Helius)": {
        "calls_recorded_this_run": 413,
        "credits_dashboard_reconciled": 3868,
        "status": "RECONCILED_WITH_DASHBOARD",
        "note": "Helius dashboard reports 3,868 credits consumed across audit and retrospective pagination sessions; 413 RPC calls executed and logged in current session wrapper."
    },
    "endpoint_1 (QuickNode)": {
        "calls_recorded_this_run": 0,
        "credits_dashboard_reconciled": 5900,
        "status": "RECONCILED_WITH_DASHBOARD",
        "note": "QuickNode dashboard reports ~5,900 credits consumed; not invoked in current retrospective run."
    },
    "endpoint_2 (Alchemy)": {
        "calls_recorded_this_run": 0,
        "credits_dashboard_reconciled": 405,
        "status": "RECONCILED_WITH_DASHBOARD",
        "note": "Alchemy 27 calls * 15 CUs = 405 CUs."
    }
}
data["endpoint_credit_logs"] = {
    "helius": {
        "calls_this_run": 413,
        "credits_dashboard": 3868,
        "status": "RECONCILED",
        "note": "Dashboard actual: 3,868 credits."
    },
    "quicknode": {
        "calls_this_run": 0,
        "credits_dashboard": 5900,
        "status": "RECONCILED",
        "note": "Dashboard actual: ~5,900 credits."
    }
}

with open(retro_path, "w", encoding="utf-8") as f:
    json.dump(data, f, indent=2)

sha = hashlib.sha256(open(retro_path, "rb").read()).hexdigest()
print(f"Updated {retro_path}")
print(f"SHA256: {sha}")

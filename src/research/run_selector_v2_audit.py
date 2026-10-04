import json
import os
from pathlib import Path
import sys
import time

root_dir = Path(__file__).resolve().parent.parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from src.research.selector_v2_high_conviction import run_full_walk_forward_evaluation


def main():
    t0 = time.time()
    print("=" * 80)
    print("EXECUTING SELECTOR_v2_HIGH_CONVICTION WALK-FORWARD RESEARCH AUDIT")
    print("=" * 80)

    res = run_full_walk_forward_evaluation()
    elapsed = time.time() - t0
    print(f"\n[+] Walk-forward evaluation completed in {elapsed:.2f} seconds!")
    print(f"[+] Total evaluated historical records: {res['sample_size']}")
    print(f"[+] Partitions (Entity-Disjoint):")
    print(f"    - Train (60%):       {res['partitions']['train_size']} trades")
    print(f"    - Validation (20%):  {res['partitions']['val_size']} trades")
    print(f"    - Locked Test (20%): {res['partitions']['locked_test_size']} trades")

    print("\n" + "=" * 80)
    print("1. WALK-FORWARD CHRONOLOGICAL PERFORMANCE (CHAMPION vs SELECTOR_v2)")
    print("=" * 80)

    header = f"{'PARTITION':<12} | {'SYSTEM':<14} | {'TRADES':<7} | {'WIN RATE':<9} | {'PF':<6} | {'MEAN RET':<9} | {'MEDIAN':<8} | {'P@10':<6} | {'P@25':<6} | {'RUNNERS':<7} | {'EXEC P&L':<10}"
    print(header)
    print("-" * len(header))

    partitions = ["train", "val", "locked_test", "overall"]
    for p in partitions:
        ch = res["champion_baseline"][p]
        cl = res["challenger_walk_forward"][p]
        p_name = p.upper()

        red_pct = (1.0 - cl['trade_count'] / max(ch['trade_count'], 1)) * 100.0
        wr_delta = cl['win_rate'] - ch['win_rate']

        print(f"{p_name:<12} | {'Champion v1.0':<14} | {ch['trade_count']:<7} | {ch['win_rate']:>6.2f}%   | {ch['profit_factor']:>5.2f} | {ch['mean_ret_pct']:>+7.2f}% | {ch['median_ret_pct']:>+6.2f}% | {ch['p_at_10']:>5.1f}% | {ch['p_at_25']:>5.1f}% | {ch['runners_3m_count']:<7} | ${ch['executable_pnl']:>9.2f}")
        print(f"{'':<12} | {'SELECTOR_v2':<14} | {cl['trade_count']:<7} | {cl['win_rate']:>6.2f}%   | {cl['profit_factor']:>5.2f} | {cl['mean_ret_pct']:>+7.2f}% | {cl['median_ret_pct']:>+6.2f}% | {cl['p_at_10']:>5.1f}% | {cl['p_at_25']:>5.1f}% | {cl['runners_3m_count']:<7} | ${cl['executable_pnl']:>9.2f}")
        print(f"{'':<12} | {'DELTA':<14} | -{red_pct:>5.1f}% | {wr_delta:>+6.2f}%   | {cl['profit_factor'] - ch['profit_factor']:>+5.2f} | {cl['mean_ret_pct'] - ch['mean_ret_pct']:>+7.2f}% | {cl['median_ret_pct'] - ch['median_ret_pct']:>+6.2f}% | {cl['p_at_10'] - ch['p_at_10']:>+5.1f}% | {cl['p_at_25'] - ch['p_at_25']:>+5.1f}% | {'':<7} | ${cl['executable_pnl'] - ch['executable_pnl']:>+9.2f}")
        print("-" * len(header))

    print("\n" + "=" * 80)
    print("2. TOP-K SELECTION BAND SENSITIVITY MATRIX (LOCKED TEST SET)")
    print("=" * 80)
    k_header = f"{'BAND':<10} | {'TRADES':<7} | {'WIN RATE':<9} | {'PROFIT FACTOR':<13} | {'PRECISION@10':<12} | {'PRECISION@25':<12} | {'MEAN RET':<9} | {'MAX DRAWDOWN':<12} | {'EXEC P&L':<10}"
    print(k_header)
    print("-" * len(k_header))
    for m in res["top_k_sensitivity_locked_test"]:
        print(f"{m['band_label']:<10} | {m['trade_count']:<7} | {m['win_rate']:>6.2f}%   | {m['profit_factor']:>12.2f}  | {m['p_at_10']:>11.1f}% | {m['p_at_25']:>11.1f}% | {m['mean_ret_pct']:>+7.2f}% | ${m['max_drawdown_pct']:>10.2f} | ${m['executable_pnl']:>9.2f}")

    print("\n" + "=" * 80)
    print("3. CONFLUENCE LEVEL BREAKDOWN (LOCKED TEST SET)")
    print("=" * 80)
    c_header = f"{'CONFLUENCE AXES':<16} | {'SAMPLE (N)':<10} | {'WIN RATE':<9} | {'PROFIT FACTOR':<13} | {'MEAN RET':<9} | {'EXEC P&L':<10}"
    print(c_header)
    print("-" * len(c_header))
    for m in res["confluence_breakdown"]:
        print(f"Level {m['level']:<10} | {m['trade_count']:<10} | {m['win_rate']:>6.2f}%   | {m['profit_factor']:>12.2f}  | {m['mean_ret_pct']:>+7.2f}% | ${m['executable_pnl']:>9.2f}")

    # Dump JSON report for documentation
    with open("data/selector_v2_audit_results.json", "w", encoding="utf-8") as f:
        json.dump(res, f, indent=2)
    print("\n[+] Detailed results serialized to data/selector_v2_audit_results.json")


if __name__ == "__main__":
    main()

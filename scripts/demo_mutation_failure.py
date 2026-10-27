import subprocess
import sys
import re

file_path = "src/paper/final_gate_layer.py"
with open(file_path, "r", encoding="utf-8") as f:
    original_code = f.read()

target_gate = "if liq_raw is None or math.isnan(float(liq_raw)) or float(liq_raw) < self.min_liquidity_usd:"
mutated_gate = "if False and (liq_raw is None or math.isnan(float(liq_raw)) or float(liq_raw) < self.min_liquidity_usd):"

print("=" * 80)
print("DEMONSTRATION: MUTATION CHECK ON GATE 4 (LIQUIDITY FLOOR $2,500)")
print("=" * 80)

# Step 1: Baseline run with Gate 4 ACTIVE
print("\n--- STEP 1: Running test_liquidity_floor_gate with Gate 4 ACTIVE (Expect PASS) ---")
res1 = subprocess.run([sys.executable, "-m", "pytest", "tests/test_phase1_final_gate_layer.py::test_liquidity_floor_gate", "-q"], capture_output=True, text=True)
print(res1.stdout)
assert res1.returncode == 0, "Baseline test failed!"

# Step 2: Disable Gate 4 by mutating final_gate_layer.py
print("--- STEP 2: Mutating final_gate_layer.py (Disabling Gate 4) ---")
mutated_code = original_code.replace(target_gate, mutated_gate)
assert mutated_code != original_code, "Could not find target gate in final_gate_layer.py!"
with open(file_path, "w", encoding="utf-8") as f:
    f.write(mutated_code)

try:
    print("--- STEP 3: Running test_liquidity_floor_gate with Gate 4 DISABLED (Expect FAIL) ---")
    res2 = subprocess.run([sys.executable, "-m", "pytest", "tests/test_phase1_final_gate_layer.py::test_liquidity_floor_gate", "-v"], capture_output=True, text=True)
    print(res2.stdout)
    if res2.stderr:
        print(res2.stderr)
    assert res2.returncode != 0, "Test did NOT fail when Gate 4 was disabled!"
    print("DEMONSTRATION SUCCEEDED: Disabling Gate 4 caused test_liquidity_floor_gate to FAIL as expected!")

finally:
    # Step 4: Re-enable Gate 4 by restoring original code
    print("\n--- STEP 4: Restoring original final_gate_layer.py (Re-enabling Gate 4) ---")
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(original_code)

# Step 5: Verify test passes again
print("--- STEP 5: Verifying test_liquidity_floor_gate PASSES again after restoration ---")
res3 = subprocess.run([sys.executable, "-m", "pytest", "tests/test_phase1_final_gate_layer.py::test_liquidity_floor_gate", "-q"], capture_output=True, text=True)
print(res3.stdout)
assert res3.returncode == 0, "Restoration failed!"
print("=" * 80)
print("MUTATION DEMONSTRATION COMPLETE: Gate 4 is 100% mapped and protective.")
print("=" * 80)

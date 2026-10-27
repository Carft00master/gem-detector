import glob
import json
import os
import re

referenced_sigs = set()

# 1. From reports
for r_file in glob.glob("reports/*.json"):
    with open(r_file, "r", encoding="utf-8") as f:
        text = f.read()
    sigs = re.findall(r"[1-9A-HJ-NP-Za-km-z]{87,88}", text)
    referenced_sigs.update(sigs)

# 2. From tests
for t_file in glob.glob("tests/**/*.py", recursive=True):
    with open(t_file, "r", encoding="utf-8") as f:
        text = f.read()
    sigs = re.findall(r"[1-9A-HJ-NP-Za-km-z]{87,88}", text)
    referenced_sigs.update(sigs)

# 3. From scripts
for s_file in glob.glob("scripts/**/*.py", recursive=True):
    with open(s_file, "r", encoding="utf-8") as f:
        text = f.read()
    sigs = re.findall(r"[1-9A-HJ-NP-Za-km-z]{87,88}", text)
    referenced_sigs.update(sigs)

print(f"Total referenced signatures: {len(referenced_sigs)}")

all_tx_fixtures = glob.glob("tests/fixtures/txs/*.json")
print(f"Total fixture files in tests/fixtures/txs: {len(all_tx_fixtures)}")

deleted = 0
kept = 0
for f in all_tx_fixtures:
    sig = os.path.basename(f).replace(".json", "")
    if sig not in referenced_sigs:
        os.remove(f)
        deleted += 1
    else:
        kept += 1

print(f"Pruning complete: kept {kept} referenced fixtures, deleted {deleted} unreferenced cached files.")

"""
scripts/check_text_identifiers.py
Verifies draft text against the strict repository identifier rule:
Every Base58-like string (32-88 chars) in the draft text MUST appear in:
- reports/*.json
- tests/fixtures/**/*.json
- data/retrospective_cache/**/*.json
or be a filename in those directories.
Fails otherwise.
"""

import json
import os
import re
import sys
from typing import Set

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

B58_CHARS = set("123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz")
HEX_PATTERN = re.compile(r"^[0-9a-f]{32,64}$")  # Exempt git commit hashes and sha256 checksums


def build_known_identifiers_set() -> Set[str]:
    """
    Build the set of known Base58 identifiers directly from:
    - reports/*.json
    - tests/fixtures/**/*.json
    - data/retrospective_cache/**/*.json
    and filenames in those directories.
    Uses a cache file for data/retrospective_cache and tests/fixtures, and always scans reports/*.json fresh.
    """
    cache_path = os.path.join(REPO_ROOT, "data", "retrospective_cache", "known_identifiers_cache.json")
    b58_regex = re.compile(r"[1-9A-HJ-NP-Za-km-z]{32,88}")
    known: Set[str] = set()

    if os.path.exists(cache_path):
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                cached = set(json.load(f))
                if len(cached) > 1000:
                    known.update(cached)
        except Exception:
            pass

    if not known:
        static_dirs = [
            os.path.join(REPO_ROOT, "tests", "fixtures"),
            os.path.join(REPO_ROOT, "data", "retrospective_cache"),
        ]
        for s_dir in static_dirs:
            for root, _, files in os.walk(s_dir):
                for fname in files:
                    if fname == "known_identifiers_cache.json":
                        continue
                    bname = os.path.splitext(fname)[0]
                    if 32 <= len(fname) <= 88:
                        known.add(fname)
                    if 32 <= len(bname) <= 88:
                        known.add(bname)
                    if fname.endswith(".json"):
                        fpath = os.path.join(root, fname)
                        try:
                            with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                                for m in b58_regex.findall(f.read()):
                                    known.add(m)
                        except Exception:
                            pass
        try:
            os.makedirs(os.path.dirname(cache_path), exist_ok=True)
            with open(cache_path, "w", encoding="utf-8") as f:
                json.dump(list(known), f)
        except Exception:
            pass

    # Always scan reports/*.json fresh (written by scripts)
    reports_dir = os.path.join(REPO_ROOT, "reports")
    if os.path.exists(reports_dir):
        for root, _, files in os.walk(reports_dir):
            for fname in files:
                bname = os.path.splitext(fname)[0]
                if 32 <= len(fname) <= 88:
                    known.add(fname)
                if 32 <= len(bname) <= 88:
                    known.add(bname)
                if fname.endswith(".json"):
                    fpath = os.path.join(root, fname)
                    try:
                        with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                            for m in b58_regex.findall(f.read()):
                                known.add(m)
                    except Exception:
                        pass

    return known


def check_text(text: str) -> bool:
    print("=" * 80)
    print("STRICT BASE58 IDENTIFIER REPOSITORY AUDIT")
    print("=" * 80)

    known_set = build_known_identifiers_set()
    print(f"Loaded {len(known_set)} verified repository identifiers from JSON files and fixtures.")

    # Find all alphanumeric tokens (32 to 88 chars) in draft text
    all_alnum = re.findall(r"\b[A-Za-z0-9]{32,88}\b", text)

    non_base58_skipped = []
    hex_skipped = []
    recognized = []
    unrecognized = []

    for c in all_alnum:
        if HEX_PATTERN.match(c):
            hex_skipped.append(c)
            continue

        if not set(c).issubset(B58_CHARS):
            non_base58_skipped.append(c)
            continue

        if c in known_set:
            recognized.append(c)
        else:
            unrecognized.append(c)

    b58_candidates_count = len(recognized) + len(unrecognized)
    assert len(all_alnum) == b58_candidates_count + len(non_base58_skipped) + len(hex_skipped)

    print(f"Total alphanumeric strings (32-88 chars) scanned : {len(all_alnum)}")
    print(f"  |-- Non-Base58 identifiers skipped (0/O/I/l)   : {len(non_base58_skipped)} {non_base58_skipped}")
    print(f"  |-- Hex hashes skipped                         : {len(hex_skipped)} {hex_skipped}")
    print(f"  |-- Valid Base58 candidate strings evaluated   : {b58_candidates_count}")
    print(f"        |-- Recognized repository identifiers    : {len(recognized)}")
    print(f"        |-- Unrecognized Base58 strings          : {len(unrecognized)} {unrecognized}")

    if unrecognized:
        print("\nVIOLATION: Found base58-like strings not present in reports, fixtures, or cache:")
        for u in sorted(set(unrecognized)):
            print(f"  FAILED: '{u}' (len={len(u)})")
        print("\nOVERALL IDENTIFIER AUDIT: FAIL")
        print("=" * 80)
        return False

    print("\nOVERALL IDENTIFIER AUDIT: PASS (All base58 identifiers match repository ground-truth)")
    print("=" * 80)
    return True


if __name__ == "__main__":
    if len(sys.argv) > 1:
        with open(sys.argv[1], "r", encoding="utf-8") as f:
            content = f.read()
    else:
        content = sys.stdin.read()
    ok = check_text(content)
    sys.exit(0 if ok else 1)

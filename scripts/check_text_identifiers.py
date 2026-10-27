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

import glob
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
    cache_path = os.path.join(REPO_ROOT, "data", "retrospective_cache", "known_identifiers_cache.json")
    if os.path.exists(cache_path):
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                cached = set(json.load(f))
                if len(cached) > 1000:
                    return cached
        except Exception:
            pass

    known = set()
    b58_regex = re.compile(r"[1-9A-HJ-NP-Za-km-z]{32,88}")

    search_dirs = [
        os.path.join(REPO_ROOT, "reports"),
        os.path.join(REPO_ROOT, "tests", "fixtures"),
        os.path.join(REPO_ROOT, "data", "retrospective_cache"),
    ]

    for s_dir in search_dirs:
        for root, _, files in os.walk(s_dir):
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
                            text = f.read()
                            for m in b58_regex.findall(text):
                                known.add(m)
                    except Exception:
                        pass

    # Save to cache for fast recurring audits
    try:
        os.makedirs(os.path.dirname(cache_path), exist_ok=True)
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(list(known), f)
    except Exception:
        pass

    return known


def check_text(text: str) -> bool:
    print("=" * 80)
    print("STRICT BASE58 IDENTIFIER REPOSITORY AUDIT")
    print("=" * 80)

    known_set = build_known_identifiers_set()
    print(f"Loaded {len(known_set)} verified repository identifiers from JSON files and fixtures.")

    # Find all base58-like tokens in draft text (32 to 88 alphanumeric chars)
    candidates = re.findall(r"\b[A-Za-z0-9]{32,88}\b", text)
    print(f"Total candidate strings (32-88 chars) found in draft: {len(candidates)}")

    unrecognized = []
    recognized = []

    for c in candidates:
        # Ignore sha256 checksums / git hashes (lowercase hex)
        if HEX_PATTERN.match(c):
            continue

        # Ignore if contains invalid base58 characters
        if not set(c).issubset(B58_CHARS):
            continue

        if c in known_set:
            recognized.append(c)
        else:
            unrecognized.append(c)

    print(f"Recognized repository identifiers: {len(recognized)}")
    print(f"Unrecognized base58 strings: {len(unrecognized)}")

    if unrecognized:
        print("\nVIOLATION: Found base58-like strings not present in reports, fixtures, or cache:")
        for u in set(unrecognized):
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

import os
import re

env_vars = {}
try:
    with open(".env", "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env_vars[k.strip()] = v.strip().strip('"').strip("'")
except FileNotFoundError:
    print("ERROR: .env not found")

for k in ["HELIUS_API_KEY", "QUICKNODE_URL", "SOLANA_RPC_URL", "SOLANA_RPC_URLS"]:
    v = env_vars.get(k, "")
    if v:
        print(f"{k}: SET len={len(v)}")
    else:
        print(f"{k}: NOT SET")

# Find helius URL
for k, v in env_vars.items():
    if "helius" in v.lower():
        m = re.search(r"api-key=([^&,\"' ]+)", v)
        if m:
            key = m.group(1)
            print(f"Helius API key in '{k}': len={len(key)}")

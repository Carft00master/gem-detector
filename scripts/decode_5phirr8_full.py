from src.onchain.provider import SolanaProvider
import base64
import json
import struct
import sys
import os

repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if repo_root not in sys.path:
    sys.path.insert(0, repo_root)

from src.utils.env_loader import load_env_file
from src.utils.ssl_context import get_verified_ssl_context
from src.onchain.provider import ProviderConfig

load_env_file()
cfg = ProviderConfig()
ssl_ctx = get_verified_ssl_context()
url = cfg.rpc_urls[0]

provider = SolanaProvider()
data = provider.execute_rpc("getAccountInfo", ["5PHirr8joyTMp9JMm6nW7hNDVyEYdkzDqazxPD7RaTjx", {"encoding": "base64"}])

acc = data["result"]["value"]
raw_b = base64.b64decode(acc["data"][0])
total_len = len(raw_b)
print(f"Account 5PHirr8... Total Data Length: {total_len} bytes, Lamports: {acc['lamports']}")

# Discriminator is 8 bytes
disc = raw_b[:8]
print(f"Discriminator: {disc.hex()}")

# Let's inspect the sections
# Earlier Phase 1.4 report claimed 2,105 decoded bytes.
# Total is 4,097 bytes!
# What are bytes 0..2105 vs 2105..4097?
print("\n--- NON-ZERO SECTIONS ---")
non_zero_chunks = []
start = None
for i in range(total_len):
    if raw_b[i] != 0:
        if start is None:
            start = i
    else:
        if start is not None:
            non_zero_chunks.append((start, i - 1, i - start))
            start = None
if start is not None:
    non_zero_chunks.append((start, total_len - 1, total_len - start))

for s, e, l in non_zero_chunks:
    print(f"  Range [{s:4d} .. {e:4d}] ({l:4d} bytes): hex={raw_b[s:min(s+32, e+1)].hex()}...")

# Let's decode the actual data structures
# In Solana Anchor accounts, vectors/arrays have a 4-byte or 8-byte length prefix.
print("\n--- VECTORS & LENGTH PREFIXES ---")
for offset in range(8, 128, 4):
    u32_val = struct.unpack("<I", raw_b[offset:offset+4])[0]
    if 0 < u32_val <= 100:
        print(f"  Possible vector len at offset {offset}: {u32_val}")

with open("scratch/5phirr8_raw.bin", "wb") as f:
    f.write(raw_b)
print("\nSaved raw binary to scratch/5phirr8_raw.bin")

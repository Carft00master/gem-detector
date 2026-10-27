import json
import base64
import struct

with open('scratch/audit_cache/txs/4MtxeAMrak91NA42Vv2cEJb2MTG4j1BCr8DYDdQRQ1RPV8gXiTsE7gsiyhX2BCFz1vdYTgEMYGMH9vzsJnEVq1Nk.json', 'r') as f:
    tx = json.load(f)

msg = tx.get('transaction', {}).get('message', {})
meta = tx.get('meta', {})

raw_keys = msg.get('accountKeys', [])
loaded = meta.get('loadedAddresses', {})
all_keys = []
if isinstance(raw_keys, list):
    for k in raw_keys:
        if isinstance(k, dict):
            all_keys.append(k.get('pubkey'))
        else:
            all_keys.append(str(k))
all_keys.extend(loaded.get('writable', []))
all_keys.extend(loaded.get('readonly', []))

print(f"Total account keys: {len(all_keys)}")

# Let's inspect the returns
for l in meta.get('logMessages', []):
    if 'Program return: pfeeUxB6jkeY1Hxd7CsFCAjcbHA9rWtchMGdZ6VojVZ' in l:
        b64 = l.split()[-1]
        raw_b = base64.b64decode(b64)
        vals = struct.unpack('<QQQ', raw_b)
        print(f"PFEE RETURN: {vals} -> LP={vals[0]} bps, PROTOCOL={vals[1]} bps, CREATOR={vals[2]} bps")

# Inner instructions
for g_idx, group in enumerate(meta.get('innerInstructions', [])):
    inst_idx = group.get('index')
    print(f"\n================ INNER GROUP {g_idx} (Top-level instruction index {inst_idx}) ================")
    for i_idx, inst in enumerate(group.get('instructions', [])):
        prog_id = inst.get('programId')
        if not prog_id and 'programIdIndex' in inst:
            p_idx = inst['programIdIndex']
            prog_id = all_keys[p_idx] if p_idx < len(all_keys) else f"idx_{p_idx}"
        
        parsed = inst.get('parsed')
        if parsed:
            itype = parsed.get('type')
            info = parsed.get('info', {})
            print(f"  [{i_idx}] {prog_id} -> {itype}: {info}")
        else:
            data = inst.get('data')
            accs = [all_keys[a] if isinstance(a, int) and a < len(all_keys) else str(a) for a in inst.get('accounts', [])]
            print(f"  [{i_idx}] {prog_id} -> raw data len={len(data) if data else 0}, accounts={accs[:3]}")

# Token balances
print("\n================ PRE & POST TOKEN BALANCES ================")
pre_tb = {tb['accountIndex']: tb for tb in meta.get('preTokenBalances', [])}
post_tb = {tb['accountIndex']: tb for tb in meta.get('postTokenBalances', [])}
for idx in sorted(set(pre_tb.keys()) | set(post_tb.keys())):
    pre_amt = pre_tb.get(idx, {}).get('uiTokenAmount', {}).get('uiAmount')
    post_amt = post_tb.get(idx, {}).get('uiTokenAmount', {}).get('uiAmount')
    mint = (pre_tb.get(idx) or post_tb.get(idx, {})).get('mint')
    owner = (pre_tb.get(idx) or post_tb.get(idx, {})).get('owner')
    print(f"  Account {idx} ({owner[:8]}... mint {mint[:8]}...): {pre_amt} -> {post_amt} (diff: {(post_amt or 0) - (pre_amt or 0)})")

import json
import base64
import struct

for tx_name in [
    '615fx6Lx574jRMVSCcJU8mvFm2N1CT4CFiUtwq7AZesgbYomApyZ2NSBc7ekdBTyR5adLhbhtNKx66qrSyDxQBjK.json',
    '2ZwL7P912RDzHn4PPxqfVknRJaVf7sE1C8DiX5fxSmMPNnXLDT4LKVaZ4NV6qFgdBxXwMyaKTNPEPVkEqLEsSwxR.json',
    '4Kazy2XHoAePuFQT8HD8jtjRbyXhWY3UAg7kq3FDTe8RzG6kRcyQoQ2SG3EVZVi9wZ7abPWxjB1feFjXEWGTpzT4.json'
]:
    path = f'scratch/audit_cache/txs/{tx_name}'
    with open(path, 'r') as fp:
        tx = json.load(fp)
    meta = tx.get('meta', {})
    print(f"\n================ TX: {tx_name[:20]}... ================")
    for l in meta.get('logMessages', []):
        if 'Program return: pfee' in l:
            b64 = l.split()[-1]
            raw_b = base64.b64decode(b64)
            vals = struct.unpack('<QQQ', raw_b)
            print(f"  PFEE RETURN: {vals} -> LP={vals[0]} bps, PROTOCOL={vals[1]} bps, CREATOR={vals[2]} bps")
    
    for g_idx, group in enumerate(meta.get('innerInstructions', [])):
        for i_idx, inst in enumerate(group.get('instructions', [])):
            parsed = inst.get('parsed')
            if parsed and parsed.get('type') in ('transfer', 'transferChecked'):
                info = parsed.get('info', {})
                print(f"  G{g_idx}[{i_idx}] {info.get('authority')} -> {info.get('destination')} | {info.get('tokenAmount', {}).get('uiAmountString')} (amt={info.get('tokenAmount', {}).get('amount')})")

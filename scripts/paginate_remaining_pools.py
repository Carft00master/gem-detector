import glob, json, os, sys, time
sys.path.insert(0, os.getcwd())
from src.onchain.provider import SolanaProvider

p = SolanaProvider()
with open('reports/retrospective_report.json', encoding='utf-8') as f:
    retro = json.load(f)

table = retro['per_migration_table']

for idx in [13, 16, 26, 22, 14, 27, 19, 9, 28, 18, 32, 17, 10, 24, 25, 35, 12, 34, 20, 30, 11, 15, 31, 21, 8]:
    r = table[idx - 1]
    pool = r['pool_address']
    c_slot = r['creation_slot']
    mig_sig = r['migration_signature']
    
    sigs_file = f'data/retrospective_cache/pool_sigs/{pool}.json'
    cached_sigs = json.load(open(sigs_file, encoding='utf-8'))
    has_mig = any(s['signature'] == mig_sig for s in cached_sigs)
    
    pages = 0
    while not has_mig:
        before = cached_sigs[-1]['signature']
        res = p.execute_rpc('getSignaturesForAddress', [pool, {'limit': 1000, 'before': before}])
        page = res.get('result') if (isinstance(res, dict) and 'result' in res) else []
        if not page:
            break
        cached_sigs.extend(page)
        pages += 1
        min_slot = page[-1].get('slot', 0)
        has_mig = any(s['signature'] == mig_sig for s in page)
        if has_mig or min_slot <= c_slot:
            break
        time.sleep(0.05)
        
    with open(sigs_file, 'w', encoding='utf-8') as f:
        json.dump(cached_sigs, f, indent=2)
    print(f"Row {idx} ({pool[:8]}...): reached={has_mig}, total_sigs={len(cached_sigs)}, pages_fetched={pages}")

print("Batch pagination complete!")

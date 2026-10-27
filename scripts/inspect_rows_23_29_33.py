import glob, json
retro = json.load(open('reports/retrospective_report.json', encoding='utf-8'))
for idx in [23, 29, 33]:
    row = retro['per_migration_table'][idx - 1]
    pool = row['pool_address']
    c_slot = row['creation_slot']
    mig_sig = row['migration_signature']
    cache_f = f'data/retrospective_cache/pool_sigs/{pool}.json'
    sigs = json.load(open(cache_f, encoding='utf-8'))
    in_w = [s for s in sigs if c_slot <= s['slot'] <= c_slot + 3]
    last_s = sigs[-1]['slot']
    print(f"Row {idx} ({pool[:8]}...): total sigs={len(sigs)}, min_slot={last_s}, in_w={len(in_w)}")
    for s in in_w:
        sig_str = s['signature'][:20]
        err_str = s.get('err')
        sl = s['slot']
        print(f"   slot={sl} {sig_str}... err={err_str}")

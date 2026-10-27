import glob, json, os, sys, time
sys.path.insert(0, os.getcwd())
from src.onchain.provider import SolanaProvider

p = SolanaProvider()
PUMPSWAP = 'pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA'

with open('reports/retrospective_report.json', encoding='utf-8') as f:
    retro = json.load(f)

table = retro['per_migration_table']

# Cache dirs
os.makedirs('data/retrospective_cache/pool_sigs', exist_ok=True)
os.makedirs('tests/fixtures/txs', exist_ok=True)

for r in table:
    idx = r['index']
    pool = r['pool_address']
    c_slot = r['creation_slot']
    mig_sig = r['migration_signature']
    
    sigs_file = f'data/retrospective_cache/pool_sigs/{pool}.json'
    cached_sigs = []
    if os.path.exists(sigs_file):
        cached_sigs = json.load(open(sigs_file, encoding='utf-8'))
        
    # Check if migration signature already in cached_sigs
    has_mig = any(s['signature'] == mig_sig for s in cached_sigs)
    
    if not has_mig:
        # Paginate via SolanaProvider.execute_rpc
        before = cached_sigs[-1]['signature'] if cached_sigs else None
        print(f"Row {idx} ({pool[:8]}...): starting pagination from {before[:16] if before else 'HEAD'} to slot {c_slot}...")
        while not has_mig:
            params = [pool, {'limit': 1000}]
            if before:
                params[1]['before'] = before
            res = p.execute_rpc('getSignaturesForAddress', params)
            page = res.get('result') if (isinstance(res, dict) and 'result' in res) else (res if isinstance(res, list) else [])
            if not page:
                print(f"Row {idx}: empty page, stopping.")
                break
            cached_sigs.extend(page)
            min_slot = page[-1].get('slot', 0)
            has_mig = any(s['signature'] == mig_sig for s in page)
            print(f"  fetched {len(page)} sigs, min_slot={min_slot}, has_mig={has_mig}")
            if has_mig or min_slot <= c_slot:
                break
            before = page[-1]['signature']
            time.sleep(0.05)
            
        with open(sigs_file, 'w', encoding='utf-8') as f:
            json.dump(cached_sigs, f, indent=2)

    # Filter signatures in window [c_slot, c_slot + 3]
    window_sigs = [s for s in cached_sigs if c_slot <= s.get('slot', 0) <= c_slot + 3]
    print(f"Row {idx}: window [S, S+3] sigs count = {len(window_sigs)}")

    # Fetch each transaction via p.execute_rpc if not in tests/fixtures/txs
    for ws in window_sigs:
        sig = ws['signature']
        dst = f'tests/fixtures/txs/{sig}.json'
        if not os.path.exists(dst):
            tx_res = p.execute_rpc('getTransaction', [sig, {'encoding': 'json', 'maxSupportedTransactionVersion': 1}])
            tx_data = tx_res.get('result') if (isinstance(tx_res, dict) and 'result' in tx_res) else (tx_res if isinstance(tx_res, dict) and 'slot' in tx_res else None)
            if tx_data:
                with open(dst, 'w', encoding='utf-8') as f:
                    json.dump(tx_data, f, indent=2)
            time.sleep(0.02)

print("Pagination and transaction fetching completed!")

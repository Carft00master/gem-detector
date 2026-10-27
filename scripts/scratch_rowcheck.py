import json
with open('reports/boost_replay_report.json', encoding='utf-8') as f:
    r = json.load(f)
swaps = r['swaps_replay_table']
for idx, s in enumerate(swaps, start=1):
    sig = s['signature']
    pool = s['pool_address']
    print(f"idx={idx} sig={sig} pool={pool} side={s['side']} fee={s['fee_return_bps']}")

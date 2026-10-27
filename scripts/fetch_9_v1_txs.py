import glob, json, os, sys
sys.path.insert(0, os.getcwd())
from src.onchain.provider import SolanaProvider

p = SolanaProvider()
sigs_9 = [
    'dZu1mAhLij2y8eS7M5dXEkgWdHQq31NTyQFMHzdaYdeJ5jA6fia2iQyHxH6Js7NP4hSkR6a85fSML9fY9SWwtGT',
    '5YizwDKxZQb5tipJ2jPy2WVewwC7jgsgNRer416wE2x8qh4aWWkj7uZ986T6VhPczNQemvxiMQVfRARiSKLCgMVw',
    '57YANs4hsRAjE58Wv88caht24i1WxxuKP38QdAwGaVY2BvWYfHxuY8vaXKMB2W4xv65ahiKUp9TLLUmzyXwzbVXk',
    '2xYEr8JECfZQeejScZeiDAfyiiHLXUmUupqkqd73f875XXYsrd7UqnsXKzWb9oqrSwsgpE7wLf7GQDRQVuyKyFKZ',
    '2ej3KBPs6orxX1YQBoXGMkHmnNeU17r5N2F5ieS1sjzfFHwbxDLg2Y6aNfYFQ6EmFrPnisQTbwJ8N87kwir83ysp',
    '37xqV6NjFDtq991KTZ6coiiQDoGZ1CaXp4eWEyqu4mXXeXa3c24enBsW7MEXt1PmTHp6EA2tVGZfr8KgbTh78qUr',
    '46MywxRiercpnPJGbZnqu7BSdeggaRypdmAZ1e5boua5AZi8ZZZz3K5XK9kzS6VxXEKV5vVaZUTJ133jmfxRj1cc',
    '5bizj5NPckfTLT6g36ybCptr5Vc8vCuzNHt9UisMhJWb55c1aS5VcLWaNXnuBGkq94UTesJ2orDqUiZi42nwH8rv',
    '4rhAgf4A8TrsQm1eFN723ZgsySJRRQUAcbZtjEMXL61SFCHmxsaYKPnK1qNrZ9qUuzCh9giPtd5B6wKohfbyhQUr'
]

saved = 0
for sig in sigs_9:
    dst = f'tests/fixtures/txs/{sig}.json'
    res = p.execute_rpc('getTransaction', [sig, {'encoding': 'json', 'maxSupportedTransactionVersion': 1}])
    if res and 'slot' in res:
        with open(dst, 'w', encoding='utf-8') as f:
            json.dump(res, f, indent=2)
        saved += 1
        slot = res.get('slot')
        err = res.get('meta', {}).get('err')
        print(f"Saved {sig[:16]}... slot={slot} err={err}")
print(f"Total saved: {saved}/9")

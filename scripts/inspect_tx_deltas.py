import json, base64, struct

rows = {
    17: "3T6TH9dQU9R5fTN5CKWwQ3N9tSYHi95XL7LCJL24eymjXxH7guTTDMt5MnijsA82gnw6gWKF46zLYkaLaoHbaW3s",
    18: "3VWmJ3srmMawZVJdg7y6rxiU2q2PEwvxZqGRRxUYwg2YgCBbQTNhKCfVn8sTwrGkj7gLwesTogE97yRXCMvGPFPG",
    23: "N1dkBrZgsKEzL8hMbppHpF6yUGUQehMF6NYRQQH9b5nMAfSTv4qivZjMzht34fi4fSzwSkqDwetgL7CaXU8fDAC",
    24: "5T9amsXN9qqdtf6Si5sxLT7GzV7KeFCKtMJKyhKnMYqxBb9i43XxL3Nica3fyaTkMByYg42kkgw62kTMpNodQFk2",
    25: "23eoo1tDUZ9C8572b5e4eQUv3ExigKDqbJSai6F1cQEQhNBaRP8vCUY6KiTN2uaGu9V3Jf3C8d5Mev7UC5XrdG9t",
}

for row_idx, sig in rows.items():
    print(f"\n=================== ROW {row_idx} ({sig[:12]}...) ===================")
    with open(f"tests/fixtures/txs/{sig}.json", encoding="utf-8") as f:
        tx = json.load(f)
    meta = tx.get("meta", {})
    logs = meta.get("logMessages", [])
    
    account_keys = tx.get("transaction", {}).get("message", {}).get("accountKeys", [])
    
    # Token balances delta
    pre_tok = meta.get("preTokenBalances", [])
    post_tok = meta.get("postTokenBalances", [])
    print("Token Balance Changes:")
    for post in post_tok:
        acc_idx = post["accountIndex"]
        owner = post.get("owner", "")
        mint = post.get("mint", "")
        post_amt = float(post.get("uiTokenAmount", {}).get("amount", 0))
        pre_amt = 0.0
        for pre in pre_tok:
            if pre["accountIndex"] == acc_idx:
                pre_amt = float(pre.get("uiTokenAmount", {}).get("amount", 0))
                break
        diff = post_amt - pre_amt
        if abs(diff) > 0:
            decimals = post.get("uiTokenAmount", {}).get("decimals", 6)
            print(f"  acc {acc_idx} ({owner[:12]}...) mint {mint[:8]}... delta: {diff / (10**decimals)} (raw: {diff})")
            
    # SOL balances delta
    pre_bal = meta.get("preBalances", [])
    post_bal = meta.get("postBalances", [])
    print("SOL Balance Changes (>0.0001 SOL):")
    for idx, (pre, post) in enumerate(zip(pre_bal, post_bal)):
        diff = (post - pre) / 1e9
        if abs(diff) > 0.0001:
            acc_name = account_keys[idx] if idx < len(account_keys) else str(idx)
            if isinstance(acc_name, dict):
                acc_name = acc_name.get("pubkey")
            print(f"  acc {idx} ({acc_name[:12]}...): {diff:+.6f} SOL (pre={pre/1e9:.6f}, post={post/1e9:.6f})")

    # Inspect the event data logs
    for l in logs:
        if l.startswith("Program data: "):
            raw = base64.b64decode(l[len("Program data: "):])
            disc = raw[:8].hex()
            print(f"  Program data disc: {disc} len={len(raw)}")

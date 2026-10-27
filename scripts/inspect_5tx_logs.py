import json, base64

PUMPSWAP = "pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA"

# Map 1-based index in boost_replay_report
rows = {
    17: "3T6TH9dQU9R5fTN5CKWwQ3N9tSYHi95XL7LCJL24eymjXxH7guTTDMt5MnijsA82gnw6gWKF46zLYkaLaoHbaW3s",
    18: "3VWmJ3srmMawZVJdg7y6rxiU2q2PEwvxZqGRRxUYwg2YgCBbQTNhKCfVn8sTwrGkj7gLwesTogE97yRXCMvGPFPG",
    23: "N1dkBrZgsKEzL8hMbppHpF6yUGUQehMF6NYRQQH9b5nMAfSTv4qivZjMzht34fi4fSzwSkqDwetgL7CaXU8fDAC",
    24: "5T9amsXN9qqdtf6Si5sxLT7GzV7KeFCKtMJKyhKnMYqxBb9i43XxL3Nica3fyaTkMByYg42kkgw62kTMpNodQFk2",
    25: "23eoo1tDUZ9C8572b5e4eQUv3ExigKDqbJSai6F1cQEQhNBaRP8vCUY6KiTN2uaGu9V3Jf3C8d5Mev7UC5XrdG9t",
}

for row_idx, sig in rows.items():
    print("=" * 80)
    print(f"ROW {row_idx}: {sig}")
    with open(f"tests/fixtures/txs/{sig}.json", encoding="utf-8") as f:
        tx = json.load(f)
    meta = tx.get("meta", {})
    logs = meta.get("logMessages", [])
    for idx, l in enumerate(logs):
        if PUMPSWAP in l or "Program data:" in l or "Instruction:" in l:
            print(f"  [{idx}] {l}")

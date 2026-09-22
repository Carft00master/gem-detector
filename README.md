# 💎 Research-Grade Sub-$10K to $3M+ Breakout Scanner & Predictive Radar

A quantitative crypto research engine and machine-learning predictive radar engineered to identify microcap tokens (**\$8K–\$35K Market Cap**) that possess the statistical, order-flow, and structural characteristics of coins that reach **\$3M+ Market Cap** (300x+ breakouts).

---

## 🔬 1. Research Architecture & Core Upgrades

Unlike simple heuristic threshold scanners, this system is built on **longitudinal empirical data, wallet clustering, and calibrated machine learning**:

```
Live Feeds (Solana / Base)
       │
       ▼
Longitudinal Observation Engine (Preserves Base Rate in SQLite)
       │
       ├──► Time-Series Feature Engine (Multi-Horizon Returns, Volatility, Acceleration)
       ├──► Order-Flow Quality Engine (Volume-Weighted Pressure, Shannon Entropy)
       ├──► Wallet Graph & Cabal Engine (Funder Clustering, Effective Top-10 Concentration)
       ├──► Wash-Trading Engine (Capital Turnover, Circular Loop Detection)
       ├──► Dev Behavior Engine (Longitudinal Dev Sell Timing, Classification)
       ├──► Price Structure Engine (Healthy Staircase vs Vertical Pump Trap)
       └──► Decoupled 4-Pillar Safety (Contract, Liquidity, Distribution, Behavioral)
       │
       ▼
Signal Adjustment Layer (Manipulation-Discounted Effective Volume & Pressure)
       │
       ▼
Calibrated Multi-Target Predictor [P(100K), P(500K), P(1M), P(3M), P(Rug)]
       │
       ├──► Multi-State Alert Dispatcher (WATCH | BREAKOUT | HIGH_CONVICTION | MANIP_WARN | RUG_WARN | EXIT)
       ├──► Upgraded Quantitative Terminal Radar (Rich UI)
       └──► Temporal Walk-Forward Backtester & Precision@K Validator
```

---

## 📊 2. Key Quantitative Engines

### A. Wallet Graph & Sybil Cabal Detection (`src/engine/wallet_graph.py`)
- **Funder Clustering**: Traces upstream funding sources using disjoint-set graphs. If 15 wallets each hold 2% but were funded by the same master wallet or within 60s of each other, they are merged into a single **30% cabal cluster**.
- **Effective Top-10 Concentration**: Calculates concentration after merging sybil clusters, preventing cabals from bypassing simple top-10 filters.
- **Wallet Independence Score**: Output in $[0, 1]$ measuring retail wallet entropy.

### B. Order Flow & Trade Size Entropy (`src/engine/order_flow.py`)
- **Shannon Entropy ($H$)**: Partitions trade sizes into logarithmic capital bins ($<\$25, \$25-\$100, \$100-\$500, \$500-\$2500, >\$2500$). Bot wash trading yields low entropy ($H < 0.4$), whereas organic retail yields high entropy ($H > 1.2$).
- **Volume-Weighted Buy Pressure**: Weights transactions by USD size rather than raw transaction counts.

### C. Wash-Trading & Capital Turnover (`src/engine/wash_trading.py`)
- **Capital Turnover Ratio**: $\frac{\text{Total Volume}}{\text{Total Unique Capital At Risk}}$. Ratios $> 8\text{x}$ indicate recycled liquidity.
- **Circular Loops**: Identifies rapid buy-then-sell roundtrips ($<\!60\text{s}$) by the same wallet.
- **Volume Quality Score**: Discounts raw volume: $\text{Effective Volume} = \text{Raw Volume} \times \text{Volume Quality Score}$.

### D. Multi-Horizon Time-Series (`src/engine/features.py`)
- Computes returns, price acceleration $\frac{\Delta r}{\Delta t}$, rolling volatility $\sigma$, higher highs/lows staircase geometry, and volume persistence ratios ($V_{5m} / (V_{1h}/12)$).

### E. Calibrated Machine Learning & Baseline Model (`src/models/predictor.py`)
- Generates **calibrated probabilities**:
  - $P(\text{Reach } \$50\text{K})$, $P(\text{Reach } \$100\text{K})$, $P(\text{Reach } \$500\text{K})$, $P(\text{Reach } \$1\text{M})$, $P(\text{Reach } \$3\text{M})$
  - $P(\text{Rug / Failure})$, $P(\text{Manipulation})$, $P(\text{Cabal})$, $P(\text{Liquidity Failure})$
- Strictly avoids misleading uncalibrated percentage claims.

---

## 🚀 3. Quickstart & CLI Commands

### Installation
```bash
pip install -r requirements.txt
```

### 1. Live Quantitative Terminal Radar
```bash
# Run multi-chain live scanner (Solana + Base)
python run_scanner.py

# Run single snapshot scan and display calibrated table
python run_scanner.py --once

# Run on specific chain
python run_scanner.py --chain solana
```

### 2. Temporal Walk-Forward Model Training
Trains calibrated models with strict chronological walk-forward splits (Train $\to$ Validation $\to$ Test) to eliminate future data leakage:
```bash
python run_scanner.py --train-model
```

### 3. Chronological Point-in-Time Backtesting
Replays historical token observations strictly at time $t$ to evaluate Precision@K, Base Rate Lift, Lead Times, and Drawdowns:
```bash
python run_scanner.py --backtest
# Or with options:
python backtest_scanner.py --model ml --min-prob 0.08
```

---

## 🎯 4. Multi-State Alert Architecture

The system dispatches 6 discrete alert states:

| Alert State | Trigger Conditions | Action |
| :--- | :--- | :--- |
| **`★ HIGH_CONVICTION`** | $P(3M) \ge 12\%$ or Score $\ge 80$, Safe LP, Clean Top-10, Healthy Staircase | Primary Buy Signal |
| **`🟢 EARLY_BREAKOUT`** | $P(100K) \ge 40\%$, Positive Momentum, Organic Order Flow | Momentum Setup |
| **`🟡 WATCH`** | Valuation in $\$8K-\$35K$ window, developing liquidity | Monitored Setup |
| **`⚠️ MANIPULATION_WARNING`** | High wash-trading turnover or sybil cabal clustering | Caution / Avoid |
| **`🚨 RUG_WARNING`** | Unlocked LP, mint authority enabled, or honeypot flag | Immediate Rejection |
| **`❌ EXIT_INVALIDATION`** | Distribution regime, capitulation dump, or dev exit dump | Exit / Invalidation |

---

## 🧪 5. Automated Test Suite

Run the full automated test suite:
```bash
python -m pytest tests/ -v
```

Tests cover:
- `tests/test_outcomes.py`: Multi-tier targets, MFE/MAE, persistence, and drawdowns.
- `tests/test_time_series.py`: Returns, volatility, volume persistence, staircase geometry.
- `tests/test_order_flow.py`: Volume-weighted pressure and trade entropy.
- `tests/test_wallet_graph.py`: Funder clustering and effective top-10 concentration.
- `tests/test_wash_trading.py`: Capital turnover anomalies and circular loops.
- `tests/test_dev_behavior.py`: Dev lifecycle tracking and classification.
- `tests/test_backtest_leakage.py`: Temporal chronological partitioning without future leakage.
- `tests/test_calibration.py`: Calibrated probabilities, Precision@K, ROC-AUC, and Lead-Time metrics.

# Pre-Registered Route A Strategy Test Specification (2026-10-28)

**Status:** Pre-registered and committed to git prior to outcome evaluation.
**Dataset:** `data/curve_trades.db` (6-hour confirmed `CurveTradeCollector` run, SOL-quoted cohort only, gap-boundary creations excluded).

## 1. Train / Test Split
- **Train Split (First 4 Hours):** Mints created in `[min_created_block_time, min_created_block_time + 14400)`. Used solely to choose 1 variant among the 5 pre-listed variants below.
- **Out-of-Sample Test Split (Last 2 Hours):** Mints created in `[min_created_block_time + 14400, max_block_time - 1800]` (ensuring full 30-minute observation maturity). Evaluated strictly once with no tuning on the test split.

## 2. Entry Gates (All 4 Required at Evaluation Time $t$)
1. **Distinct Non-Bot Buyers:** $\ge N$ distinct buying wallets in $[t_{\text{create}}, t_{\text{create}} + t]$, excluding high-frequency bot wallets (active in $\ge 50$ distinct mints in the 6h dataset) and excluding wallets that round-trip (buy and sell the same mint within $60\text{ s}$ up to time $t$).
2. **Creator Share:** $\le 3.0\%$ of total $1,000,000,000$ token supply ($\le 30,000,000$ tokens held by `creator` wallet from cumulative curve trade balances at time $t$).
3. **Top-10 Holder Share:** $\le 18.0\%$ of total $1,000,000,000$ token supply ($\le 180,000,000$ tokens held across the top 10 positive-balance wallets on the bonding curve at time $t$).
4. **Market Cap:** $\le \$16,000$ at $\$150/\text{SOL}$ ($\le 106.67\text{ SOL}$ implied market cap $v_{\text{SOL}} \times \frac{10^9}{v_{\text{tok}}}$ at time $t$).

## 3. Execution, Latency, Fee, and Failed-Landing Model
- **Latency:** $2\text{ slots}$ (primary) and $3\text{ slots}$ (sensitivity) after the trigger slot at time $t$. Reserves at entry are taken from the bonding curve state immediately after the last trade at or before $\text{trigger\_slot} + \Delta s$. (If the bonding curve has already completed/graduated at or before $\text{trigger\_slot} + \Delta s$, the curve entry cannot fill.)
- **Curve Constant-Product Simulator & Fees:** $1.25\%$ ($125\text{ bps}$) fee each way (`1.00%` protocol + `0.25%` creator fee) on a $0.50\text{ SOL}$ ($75) trade size:
  - Entry: $\text{SOL}_{\text{eff}} = \text{SOL}_{\text{in}} \times (1 - 0.0125)$, $\Delta \text{tok} = \lfloor \frac{v_{\text{tok}} \cdot \text{SOL}_{\text{eff}}}{v_{\text{SOL}} + \text{SOL}_{\text{eff}}} \rfloor$.
  - Exit: $\text{SOL}_{\text{gross}} = \frac{v_{\text{SOL,exit}} \cdot \Delta \text{tok}}{v_{\text{tok,exit}} + \Delta \text{tok}}$, $\text{SOL}_{\text{net}} = \text{SOL}_{\text{gross}} \times (1 - 0.0125) - 0.000005\text{ SOL}$.
- **Failed-Landing Rate:** Taken from the empirical $S+0$ failure data ($45 / 76 = 59.21\%$ failed at $S+0$, and $227 / 849 = 26.74\%$ failed across pAMM window attempts).

## 4. Exit Rules
- **Fixed Horizons:** $1\text{ min}$ ($60\text{ s}$), $2\text{ min}$ ($120\text{ s}$), $5\text{ min}$ ($300\text{ s}$), $10\text{ min}$ ($600\text{ s}$), and $30\text{ min}$ ($1800\text{ s}$) after entry.
- **Stop-Loss:** $-30.0\%$ stop-loss (triggered on the first subsequent trade where mark-to-market net exit value drops $\le -30.0\%$, executed with a $2\text{-slot}$ delay at the actual reserve state at $\text{stop\_slot} + 2$).

## 5. Pre-Listed Variants (Total = 5, Maximum Allowed = 5)
1. **`V1_t60s_N8`**: $t = 60\text{ s}$ ($+1\text{m}$), $N \ge 8$ distinct non-bot buyers, creator $\le 3\%$, top-10 $\le 18\%$, MC $\le \$16,000$.
2. **`V2_t60s_N12`**: $t = 60\text{ s}$ ($+1\text{m}$), $N \ge 12$ distinct non-bot buyers, creator $\le 3\%$, top-10 $\le 18\%$, MC $\le \$16,000$.
3. **`V3_t120s_N10`**: $t = 120\text{ s}$ ($+2\text{m}$), $N \ge 10$ distinct non-bot buyers, creator $\le 3\%$, top-10 $\le 18\%$, MC $\le \$16,000$.
4. **`V4_t120s_N15`**: $t = 120\text{ s}$ ($+2\text{m}$), $N \ge 15$ distinct non-bot buyers, creator $\le 3\%$, top-10 $\le 18\%$, MC $\le \$16,000$.
5. **`V5_t300s_N15`**: $t = 300\text{ s}$ ($+5\text{m}$), $N \ge 15$ distinct non-bot buyers, creator $\le 3\%$, top-10 $\le 18\%$, MC $\le \$16,000$.

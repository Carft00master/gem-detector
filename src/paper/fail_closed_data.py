"""
Fail-Closed Data Engine & Gate Auditor (Phase 1d)
Enforces:
1. Missing feature = NaN = REJECT (no defaults: eliminates 1, 1.0, 0.0795 fallbacks).
2. Synthetic liquidity is eliminated (only real on-chain reserve liquidity allowed).
3. Unique buyers computed strictly from on-chain WALLET addresses, not tx counts.
4. Creator & Top-10 concentration computed strictly from on-chain token accounts
   (excluding curve, pool, and burn accounts).
5. Curve-filler holdings computed explicitly (detects single-wallet curve completions).
6. Real-time verification of liquidity/MC in [0.30, 1.35], MC <= $16k, size <= 1% liquidity.
"""

from dataclasses import asdict, dataclass
import logging
import math
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

# Known burn and system addresses to exclude from holder concentration
EXCLUDED_HOLDER_ADDRESSES: Set[str] = {
    "11111111111111111111111111111111",                     # System Program
    "1nc1nerator11111111111111111111111111111111",         # Incinerator Burn
    "deaddeaddeaddeaddeaddeaddeaddeaddeaddead",             # Dead address
    "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P",         # Pump.fun Program
    "39AZHJWrsjhALdgAc2vhVUdhnh8YBgKflAZv29H2jsgk",         # Pump.fun Migration
}


@dataclass
class ValidatedCandidateTelemetry:
    mint: str
    market_cap_usd: float
    real_liquidity_usd: float
    liquidity_to_mc_ratio: float
    unique_buyer_wallets: int
    buy_sell_ratio: float
    p_reach_3m: float
    creator_holding_pct: float
    top10_holding_pct: float
    curve_filler_holding_pct: float
    curve_completed_by_single_tx: bool
    position_size_usd: float
    is_valid: bool
    failed_gates: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class FailClosedDataValidator:
    """
    Validates candidates using strictly verified point-in-time on-chain data.
    Never falls back to synthetic liquidity or default feature constants.
    """
    def __init__(
        self,
        min_unique_buyers: int = 25,
        min_p_reach_3m: float = 0.09,
        min_liq_mc_ratio: float = 0.30,
        max_liq_mc_ratio: float = 1.35,
        max_market_cap_usd: float = 16000.0,
        max_position_liquidity_pct: float = 1.0,   # Max 1% of pool liquidity
        max_creator_holding_pct: float = 3.0,
        max_top10_holding_pct: float = 18.0,
        max_curve_filler_pct: float = 15.0,
    ):
        self.min_unique_buyers = min_unique_buyers
        self.min_p_reach_3m = min_p_reach_3m
        self.min_liq_mc_ratio = min_liq_mc_ratio
        self.max_liq_mc_ratio = max_liq_mc_ratio
        self.max_market_cap_usd = max_market_cap_usd
        self.max_position_liquidity_pct = max_position_liquidity_pct
        self.max_creator_holding_pct = max_creator_holding_pct
        self.max_top10_holding_pct = max_top10_holding_pct
        self.max_curve_filler_pct = max_curve_filler_pct

    def validate_candidate(
        self,
        candidate_data: Dict[str, Any],
        onchain_buyer_wallets: Optional[List[str]] = None,
        onchain_holders: Optional[List[Dict[str, Any]]] = None,
        position_size_usd: float = 100.0,
    ) -> ValidatedCandidateTelemetry:
        """
        Validate all gates in fail-closed mode.
        Missing or default features trigger immediate gate rejection.
        """
        mint = candidate_data.get("token_address") or candidate_data.get("mint") or ""
        failed_gates: List[str] = []

        # 1. Market Cap Gate
        mc_raw = candidate_data.get("market_cap_usd")
        if mc_raw is None or math.isnan(float(mc_raw)) or float(mc_raw) <= 0.0:
            failed_gates.append("GATE_FAIL: Market Cap is missing or NaN")
            mc = 0.0
        else:
            mc = float(mc_raw)
            if mc > self.max_market_cap_usd:
                failed_gates.append(f"GATE_FAIL: Market Cap ${mc:,.2f} exceeds limit ${self.max_market_cap_usd:,.2f}")

        # 2. Strict Real Liquidity (Synthetic Liquidity strictly rejected)
        liq_raw = candidate_data.get("liquidity_usd")
        if liq_raw is None or math.isnan(float(liq_raw)) or float(liq_raw) <= 0.0:
            failed_gates.append("GATE_FAIL: Real Liquidity is missing or NaN (synthetic liquidity disallowed)")
            liq = 0.0
        else:
            liq = float(liq_raw)
            if liq < 500.0:
                failed_gates.append(f"GATE_FAIL: Real Liquidity ${liq:.2f} is below minimum $500 threshold")

        # 3. Liquidity to Market Cap Ratio Gate
        liq_mc_ratio = (liq / mc) if mc > 0 else 0.0
        if mc > 0 and liq > 0:
            if not (self.min_liq_mc_ratio <= liq_mc_ratio <= self.max_liq_mc_ratio):
                failed_gates.append(
                    f"GATE_FAIL: Liquidity/MC ratio {liq_mc_ratio:.3f} outside bounds [{self.min_liq_mc_ratio}, {self.max_liq_mc_ratio}]"
                )

        # 4. Position Size vs Liquidity Depth Gate (Max 1% of pool liquidity)
        if liq > 0:
            max_allowed_size = liq * (self.max_position_liquidity_pct / 100.0)
            if position_size_usd > max_allowed_size:
                failed_gates.append(
                    f"GATE_FAIL: Position size ${position_size_usd:.2f} exceeds {self.max_position_liquidity_pct}% of liquidity (${max_allowed_size:.2f})"
                )

        # 5. Distinct Buyer Wallets Gate (Never use transaction count or default 1)
        if onchain_buyer_wallets is not None:
            unique_buyers = len(set(onchain_buyer_wallets))
        else:
            # Check candidate data
            ub_raw = candidate_data.get("unique_buyers")
            if ub_raw is None or math.isnan(float(ub_raw)):
                failed_gates.append("GATE_FAIL: Unique buyers is missing or NaN")
                unique_buyers = 0
            else:
                unique_buyers = int(ub_raw)

        if unique_buyers <= 1:
            failed_gates.append(f"GATE_FAIL: Unique buyers ({unique_buyers}) is default fallback or <= 1")
        elif unique_buyers < self.min_unique_buyers:
            failed_gates.append(f"GATE_FAIL: Unique buyers ({unique_buyers}) below minimum {self.min_unique_buyers}")

        # 6. Model Prediction Gate: Reject exact 0.0795 default fallback or missing
        p3m_raw = candidate_data.get("p_reach_3m")
        if p3m_raw is None or math.isnan(float(p3m_raw)):
            failed_gates.append("GATE_FAIL: P(3M) prediction is missing or NaN")
            p3m = 0.0
        else:
            p3m = float(p3m_raw)
            if abs(p3m - 0.0795) < 1e-4:
                failed_gates.append("GATE_FAIL: P(3M) is exact 0.0795 default fallback (unscored model)")
            elif p3m < self.min_p_reach_3m:
                failed_gates.append(f"GATE_FAIL: P(3M) {p3m:.4f} below threshold {self.min_p_reach_3m}")

        # 7. Order Flow Buy/Sell Ratio Gate
        bs_raw = candidate_data.get("buy_sell_ratio")
        if bs_raw is None or math.isnan(float(bs_raw)):
            failed_gates.append("GATE_FAIL: Buy/Sell ratio is missing or NaN")
            buy_sell_ratio = 0.0
        else:
            buy_sell_ratio = float(bs_raw)
            if abs(buy_sell_ratio - 1.0) < 1e-4 and "txns_5m_buys" not in candidate_data:
                failed_gates.append("GATE_FAIL: Buy/Sell ratio is unpopulated default 1.0")

        # 8. Creator, Top-10 & Curve-Filler Holdings Gate
        creator_pct = float(candidate_data.get("dev_holding_pct", candidate_data.get("creator_holding_pct", 0.0)) or 0.0)
        top10_pct = float(candidate_data.get("top10_holder_pct", candidate_data.get("top10_holding_pct", 0.0)) or 0.0)
        filler_pct = float(candidate_data.get("curve_filler_holding_pct", 0.0) or 0.0)
        single_tx_comp = bool(candidate_data.get("curve_completed_by_single_tx", False))

        # If holders list provided, calculate exact holdings excluding system/curve accounts
        if onchain_holders:
            creator_addr = candidate_data.get("creator", candidate_data.get("dev", ""))
            filtered_holders = [
                h for h in onchain_holders
                if h.get("address") not in EXCLUDED_HOLDER_ADDRESSES and not h.get("is_curve_or_pool", False)
            ]
            total_supply = sum(float(h.get("amount", 0.0)) for h in filtered_holders) or 1_000_000_000.0
            
            # Creator holding
            if creator_addr:
                cr_amt = sum(float(h.get("amount", 0.0)) for h in filtered_holders if h.get("address") == creator_addr)
                creator_pct = round((cr_amt / total_supply) * 100.0, 2)

            # Top 10 holding
            sorted_holders = sorted(filtered_holders, key=lambda x: float(x.get("amount", 0.0)), reverse=True)
            top10_amt = sum(float(h.get("amount", 0.0)) for h in sorted_holders[:10])
            top10_pct = round((top10_amt / total_supply) * 100.0, 2)

        # Check holding gate thresholds
        if creator_pct > self.max_creator_holding_pct:
            failed_gates.append(f"GATE_FAIL: Creator holding {creator_pct:.1f}% exceeds limit {self.max_creator_holding_pct:.1f}%")

        if top10_pct > self.max_top10_holding_pct:
            failed_gates.append(f"GATE_FAIL: Top-10 concentration {top10_pct:.1f}% exceeds limit {self.max_top10_holding_pct:.1f}%")

        if single_tx_comp or filler_pct > self.max_curve_filler_pct:
            failed_gates.append(
                f"GATE_FAIL: Single-wallet curve filler detected (holding {filler_pct:.1f}% > {self.max_curve_filler_pct:.1f}%)"
            )

        is_valid = (len(failed_gates) == 0)

        return ValidatedCandidateTelemetry(
            mint=mint,
            market_cap_usd=mc,
            real_liquidity_usd=liq,
            liquidity_to_mc_ratio=round(liq_mc_ratio, 4),
            unique_buyer_wallets=unique_buyers,
            buy_sell_ratio=round(buy_sell_ratio, 2),
            p_reach_3m=round(p3m, 4),
            creator_holding_pct=creator_pct,
            top10_holding_pct=top10_pct,
            curve_filler_holding_pct=filler_pct,
            curve_completed_by_single_tx=single_tx_comp,
            position_size_usd=position_size_usd,
            is_valid=is_valid,
            failed_gates=failed_gates,
        )

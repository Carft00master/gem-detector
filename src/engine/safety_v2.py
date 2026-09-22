"""
Multi-Dimensional Safety & Venue-Aware Risk Engine
Decouples safety into 4 independent risk pillars (Contract, Liquidity, Distribution, Behavioral)
and normalizes across venues (Pump.fun, Raydium, Meteora, Uniswap, Aerodrome).
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
import aiohttp
from src.engine.safety import SecurityAuditor
from src.feeds.base_feed import TokenCandidate, TokenSecurityReport


@dataclass
class DecoupledSafetyReport:
    # 4 Independent Risk Scores (0.0 = Safe, 1.0 = Critical Risk)
    contract_risk: float = 0.0
    liquidity_risk: float = 0.0
    distribution_risk: float = 0.0
    behavioral_risk: float = 0.0

    # Composite Safety Index (0 to 100, where 100 = Cleanest)
    safety_index: float = 100.0

    # Venue-Specific Metadata
    venue_type: str = "amm"              # "pump_bonding_curve", "raydium_amm", "uniswap_v2", "aerodrome"
    bonding_curve_progress_pct: float = 0.0
    is_tradable_liquidity: bool = True
    virtual_to_real_reserve_ratio: float = 1.0

    signals: List[str] = field(default_factory=list)
    critical_flags: List[str] = field(default_factory=list)

    @property
    def is_safe_for_entry(self) -> bool:
        return (
            self.contract_risk < 0.25
            and self.liquidity_risk < 0.35
            and self.distribution_risk < 0.45
            and len(self.critical_flags) == 0
        )


class VenueAwareSafetyEngine:
    def __init__(self, auditor: Optional[SecurityAuditor] = None):
        self.auditor = auditor or SecurityAuditor()

    def evaluate_safety(
        self,
        candidate: TokenCandidate,
        cabal_risk_score: float = 0.0,
        wash_trade_risk: float = 0.0,
        effective_top10_pct: float = 0.0,
    ) -> DecoupledSafetyReport:
        """
        Compute decoupled 4-pillar risk scores with venue-specific calibrations.
        """
        rep = DecoupledSafetyReport()
        sec = candidate.security
        venue = (candidate.dex_id or "").lower()

        signals = []
        critical = []

        # 1. Determine Venue & Liquidity Architecture
        if "pump" in venue or "bonding" in venue:
            rep.venue_type = "pump_bonding_curve"
            # Bonding curve virtual liquidity calibration
            # Pump.fun tokens migrate to Raydium at ~69k market cap (85 SOL bonded)
            rep.bonding_curve_progress_pct = min(100.0, (candidate.market_cap_usd / 69000.0) * 100.0)
            rep.virtual_to_real_reserve_ratio = 4.0  # Approx ratio of virtual to real SOL in curve
            signals.append(f"PUMP_BONDING_CURVE_{rep.bonding_curve_progress_pct:.0f}%_PROGRESS")
        elif "raydium" in venue:
            rep.venue_type = "raydium_amm"
        elif "aerodrome" in venue:
            rep.venue_type = "aerodrome"
        else:
            rep.venue_type = "uniswap_v2"

        # 2. Pillar 1: Contract Risk
        c_risk = 0.0
        if sec.is_honeypot:
            c_risk += 1.0
            critical.append("HONEYPOT_DETECTED")
        if not sec.mint_renounced:
            c_risk += 0.50
            critical.append("MINT_AUTHORITY_ENABLED")
        if not sec.freeze_renounced:
            c_risk += 0.40
            critical.append("FREEZE_AUTHORITY_ENABLED")
        if sec.buy_tax_pct > 2.0 or sec.sell_tax_pct > 2.0:
            c_risk += 0.35
            signals.append(f"NON_ZERO_TAX_{sec.buy_tax_pct:.0f}/{sec.sell_tax_pct:.0f}")

        rep.contract_risk = round(min(1.0, c_risk), 3)

        # 3. Pillar 2: Liquidity Risk
        l_risk = 0.0
        if sec.lp_burned_or_locked_pct < 80.0 and rep.venue_type != "pump_bonding_curve":
            l_risk += 0.70
            critical.append("LP_NOT_LOCKED_RUG_RISK")
        elif sec.lp_burned_or_locked_pct >= 99.0:
            signals.append("LP_100_LOCKED_BURNED")

        if candidate.liquidity_mc_ratio < 0.12:
            l_risk += 0.40
            signals.append("THIN_LIQUIDITY_DEPTH")

        rep.liquidity_risk = round(min(1.0, l_risk), 3)

        # 4. Pillar 3: Distribution Risk
        d_risk = 0.0
        eff_top10 = effective_top10_pct if effective_top10_pct > 0 else sec.top10_holder_pct
        if eff_top10 >= 35.0:
            d_risk += 0.60
            critical.append(f"EFFECTIVE_TOP10_CRITICAL_{eff_top10:.0f}%")
        elif eff_top10 >= 24.0:
            d_risk += 0.30
            signals.append(f"ELEVATED_TOP10_{eff_top10:.0f}%")

        if sec.dev_holding_pct >= 5.0 and not sec.dev_sold_all:
            d_risk += 0.40
            signals.append(f"DEV_HOLDS_{sec.dev_holding_pct:.1f}%")

        if cabal_risk_score > 0.50:
            d_risk += 0.35
            signals.append("HIGH_CABAL_BUNDLING")

        rep.distribution_risk = round(min(1.0, d_risk), 3)

        # 5. Pillar 4: Behavioral Risk
        b_risk = 0.0
        if wash_trade_risk > 0.50:
            b_risk += 0.50
            signals.append("WASH_TRADING_BEHAVIOR")
        if cabal_risk_score > 0.60:
            b_risk += 0.40

        rep.behavioral_risk = round(min(1.0, b_risk), 3)

        # Composite Safety Index (0 to 100)
        total_risk_penalty = (
            rep.contract_risk * 40.0
            + rep.liquidity_risk * 30.0
            + rep.distribution_risk * 20.0
            + rep.behavioral_risk * 10.0
        )
        rep.safety_index = round(max(0.0, 100.0 - total_risk_penalty), 1)
        rep.signals = signals
        rep.critical_flags = critical

        return rep

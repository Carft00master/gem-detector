"""
Developer & Deployer Behavioral Engine
Tracks longitudinal dev balance, sell timing, transfer routes, and classifies dev risk:
STRONG | NEUTRAL | WARNING | CRITICAL.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional


@dataclass
class DevBehaviorReport:
    initial_allocation_pct: float = 0.0
    current_holding_pct: float = 0.0
    pct_supply_sold: float = 0.0
    number_of_dev_sells: int = 0
    dev_transferred_to_subwallets: bool = False
    dev_sold_all_fairly: bool = False
    classification: str = "NEUTRAL"      # STRONG, NEUTRAL, WARNING, CRITICAL
    dev_risk_score: float = 0.0          # 0.0 = Safest, 1.0 = Highest Risk
    signals: List[str] = field(default_factory=list)


class DevBehaviorEngine:
    @classmethod
    def evaluate_dev(
        cls,
        initial_allocation_pct: float,
        current_holding_pct: float,
        number_of_sells: int = 0,
        transferred_to_subwallets: bool = False,
        market_cap_usd: float = 0.0,
    ) -> DevBehaviorReport:
        """
        Evaluate dev/deployer risk based on allocation, sell patterns, and transfers.
        """
        rep = DevBehaviorReport()
        rep.initial_allocation_pct = initial_allocation_pct
        rep.current_holding_pct = current_holding_pct
        rep.number_of_dev_sells = number_of_sells
        rep.dev_transferred_to_subwallets = transferred_to_subwallets

        if initial_allocation_pct > 0:
            sold = max(0.0, initial_allocation_pct - current_holding_pct)
            rep.pct_supply_sold = (sold / initial_allocation_pct) * 100.0
        else:
            rep.pct_supply_sold = 100.0 if current_holding_pct == 0 else 0.0

        rep.dev_sold_all_fairly = (current_holding_pct == 0.0 and not transferred_to_subwallets)

        signals = []
        risk = 0.0

        # 1. Dev Still Holds Significant Supply
        if current_holding_pct >= 8.0:
            risk += 0.70
            signals.append("DEV_HOLDS_CRITICAL_SUPPLY")
        elif current_holding_pct >= 4.0:
            risk += 0.40
            signals.append("DEV_HOLDS_MODERATE_SUPPLY")
        elif current_holding_pct <= 1.0 and rep.dev_sold_all_fairly:
            signals.append("DEV_COMPLETELY_EXITED_CLEAN")

        # 2. High Initial Allocation
        if initial_allocation_pct >= 15.0:
            risk += 0.35
            signals.append("SUSPICIOUS_HIGH_DEV_MINT")
        elif initial_allocation_pct >= 6.0:
            risk += 0.15

        # 3. Sub-wallet transfers (Stealth dev dump risk)
        if transferred_to_subwallets:
            risk += 0.45
            signals.append("DEV_SUBWALLET_TRANSFER_STEALTH_RISK")

        # Final Classification
        risk = min(1.0, max(0.0, risk))
        rep.dev_risk_score = round(risk, 3)

        if risk >= 0.70:
            rep.classification = "CRITICAL"
        elif risk >= 0.40:
            rep.classification = "WARNING"
        elif risk <= 0.15 and rep.dev_sold_all_fairly:
            rep.classification = "STRONG"
        else:
            rep.classification = "NEUTRAL"

        rep.signals = signals
        return rep

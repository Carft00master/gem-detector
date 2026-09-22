"""
Real-Time Smart Wallet Entry Detector & Match Score Engine
Detects when a validated or emerging smart wallet buys a candidate token.
Captures the complete point-in-time token and order flow context at entry.
Computes WALLET_ENTRY_MATCH_SCORE based on similarity to wallet's historically successful entry conditions.
"""

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import logging
import math
from typing import Any, Dict, List, Optional
import uuid

logger = logging.getLogger(__name__)


@dataclass
class SmartWalletEntryEvent:
    event_id: str
    wallet_address: str
    token_address: str
    symbol: str
    chain: str
    venue: str
    entry_timestamp: str

    market_cap_usd: float
    liquidity_usd: float
    token_age_minutes: float
    curve_progress_pct: float
    activity_density_percentile: float
    trader_breadth_score: float
    buy_pressure_ratio: float
    two_sided_market_quality: float

    wallet_role: str
    wallet_archetype: str
    wallet_maturity_state: str
    wallet_skill_confidence: float
    wallet_shrunk_win_rate_pct: float

    wallet_entry_match_score: float      # 0.0 to 1.0 similarity to historically optimal setups
    knowledge_snapshot_timestamp: str
    is_research_only: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class SmartWalletEntryDetector:
    """Detects and scores on-chain smart wallet entry events in real-time."""

    @classmethod
    def calculate_entry_match_score(
        cls,
        token_state: Dict[str, Any],
        wallet_profile: Dict[str, Any],
    ) -> float:
        """
        Calculates WALLET_ENTRY_MATCH_SCORE (0.0 to 1.0) without look-ahead bias.
        Evaluates how closely current token conditions match the wallet's optimal entry conditions.
        """
        mc = float(token_state.get("market_cap_usd", 15000.0) or 15000.0)
        age = float(token_state.get("token_age_minutes", 5.0) or 5.0)
        curve = float(token_state.get("curve_progress_pct", 30.0) or 30.0)
        density = float(token_state.get("activity_density_percentile", 50.0) or 50.0)

        # Retrieve wallet sweet spot ranges if available
        opt_mc = wallet_profile.get("optimal_mc_range", [5000.0, 30000.0])
        opt_age = wallet_profile.get("optimal_token_age_range", [1.0, 20.0])
        opt_curve = wallet_profile.get("optimal_curve_progress_range", [10.0, 70.0])

        score = 0.0

        # MC fit (0.35 weight)
        if opt_mc[0] <= mc <= opt_mc[1]:
            score += 0.35
        elif opt_mc[0] * 0.5 <= mc <= opt_mc[1] * 1.5:
            score += 0.18

        # Token age fit (0.25 weight)
        if opt_age[0] <= age <= opt_age[1]:
            score += 0.25
        elif opt_age[0] * 0.5 <= age <= opt_age[1] * 1.5:
            score += 0.12

        # Curve progress fit (0.20 weight)
        if opt_curve[0] <= curve <= opt_curve[1]:
            score += 0.20
        elif opt_curve[0] * 0.5 <= curve <= opt_curve[1] * 1.5:
            score += 0.10

        # Activity density fit (0.20 weight)
        if density >= 60.0:
            score += 0.20
        elif density >= 40.0:
            score += 0.10

        return round(min(1.0, max(0.05, score)), 3)

    @classmethod
    def record_entry_event(
        cls,
        wallet: Dict[str, Any],
        token_state: Dict[str, Any],
    ) -> SmartWalletEntryEvent:
        """
        Creates and logs a point-in-time SMART_WALLET_ENTRY_EVENT.
        """
        now_str = datetime.now(timezone.utc).isoformat()
        w_addr = str(wallet.get("wallet_address", ""))
        t_addr = str(token_state.get("token_address", ""))

        match_score = cls.calculate_entry_match_score(token_state, wallet)

        return SmartWalletEntryEvent(
            event_id=f"entry_{str(uuid.uuid4())[:10]}",
            wallet_address=w_addr,
            token_address=t_addr,
            symbol=str(token_state.get("symbol", "TOKEN")),
            chain=str(token_state.get("chain", "solana")),
            venue=str(token_state.get("venue", "pumpfun")),
            entry_timestamp=now_str,
            market_cap_usd=float(token_state.get("market_cap_usd", 12000.0) or 12000.0),
            liquidity_usd=float(token_state.get("liquidity_usd", 4000.0) or 4000.0),
            token_age_minutes=float(token_state.get("token_age_minutes", 5.0) or 5.0),
            curve_progress_pct=float(token_state.get("curve_progress_pct", 25.0) or 25.0),
            activity_density_percentile=float(token_state.get("activity_density_percentile", 50.0) or 50.0),
            trader_breadth_score=float(token_state.get("trader_breadth_score", 0.75) or 0.75),
            buy_pressure_ratio=float(token_state.get("effective_buy_pressure", 0.65) or 0.65),
            two_sided_market_quality=float(token_state.get("two_sided_quality", 0.80) or 0.80),
            wallet_role=str(wallet.get("primary_role", "TRADER")),
            wallet_archetype=str(wallet.get("archetype", "TRACTION_TRADER")),
            wallet_maturity_state=str(wallet.get("maturity_state", "CANDIDATE")),
            wallet_skill_confidence=float(wallet.get("skill_confidence", 0.70) or 0.70),
            wallet_shrunk_win_rate_pct=float(wallet.get("shrunk_win_rate", 15.0) or 15.0),
            wallet_entry_match_score=match_score,
            knowledge_snapshot_timestamp=now_str,
            is_research_only=True,
        )

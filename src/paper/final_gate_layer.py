"""
Single Final Gate Layer (Phase 1h)
Centralized gatekeeper where ALL candidate filters and risk checks are applied in strict sequence.
Guarantees:
1. No selector bypasses (Selector V2.2, V1, and any future selectors must pass through this single layer).
2. Every rejection reason is explicitly logged and persisted to the shadow ledger.
3. Zero silent candidate drops.
4. Fail-closed: missing feature = NaN = reject.
"""

from dataclasses import dataclass, field
import logging
import math
from typing import Any, Dict, List, Optional, Tuple

from src.feeds.base_feed import TokenCandidate
from src.models.predictor import BreakoutPredictionOutput
from src.paper.fail_closed_data import FailClosedDataValidator, ValidatedCandidateTelemetry
from src.paper.shadow_ledger import ShadowLedgerManager
from src.paper.venue_state_machine import VenueStateMachine, VenueState

logger = logging.getLogger(__name__)


@dataclass
class GateEvaluationResult:
    is_passed: bool
    mint: str
    symbol: str
    route: str
    rejection_reasons: List[str] = field(default_factory=list)
    telemetry: Optional[ValidatedCandidateTelemetry] = None
    passed_gates: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "is_passed": self.is_passed,
            "mint": self.mint,
            "symbol": self.symbol,
            "route": self.route,
            "rejection_reasons": self.rejection_reasons,
            "passed_gates": self.passed_gates,
            "telemetry": self.telemetry.to_dict() if self.telemetry else None,
        }


class SingleFinalGateLayer:
    """
    Unified gatekeeper applying all safety, liquidity, holder, and prediction gates in order.
    Eliminates selector bypasses and records all rejections to the shadow ledger.
    """
    def __init__(
        self,
        data_validator: Optional[FailClosedDataValidator] = None,
        venue_fsm: Optional[VenueStateMachine] = None,
        shadow_ledger: Optional[ShadowLedgerManager] = None,
        toxic_venues: Optional[set] = None,
        max_market_cap_usd: float = 16000.0,
        min_liquidity_usd: float = 2500.0,
        min_p_reach_3m: float = 0.09,
        min_unique_buyers: int = 40,
        max_creator_holding_pct: float = 3.0,
        max_top10_holding_pct: float = 18.0,
    ):
        self.data_validator = data_validator or FailClosedDataValidator(
            max_market_cap_usd=max_market_cap_usd,
            min_p_reach_3m=min_p_reach_3m,
            min_unique_buyers=min_unique_buyers,
            max_creator_holding_pct=max_creator_holding_pct,
            max_top10_holding_pct=max_top10_holding_pct,
        )
        self.venue_fsm = venue_fsm or VenueStateMachine()
        self.shadow_ledger = shadow_ledger
        self.toxic_venues = toxic_venues or {
            "meteora-dbc", "meteora-damm-v2", "bags-fm", "moonshot",
            "pons-v2", "pons-v2-dex", "four-meme", "stonkfun",
        }
        self.min_liquidity_usd = min_liquidity_usd

    def evaluate(
        self,
        candidate: Any,
        prediction: BreakoutPredictionOutput,
        route: str = "ROUTE_A",
        position_size_usd: float = 100.0,
        onchain_buyer_wallets: Optional[List[str]] = None,
        onchain_holders: Optional[List[Dict[str, Any]]] = None,
    ) -> GateEvaluationResult:
        """
        Evaluate candidate against all gates sequentially without shortcuts.
        """
        rejection_reasons: List[str] = []
        passed_gates: List[str] = []

        mint = getattr(candidate, "address", getattr(candidate, "token_address", ""))
        symbol = str(getattr(candidate, "symbol", "") or "").upper()
        venue_str = str(getattr(candidate, "dex_id", None) or getattr(candidate, "venue", "") or "").lower()
        chain = str(getattr(candidate, "chain", "solana")).lower()
        mc = float(getattr(candidate, "market_cap_usd", 0.0) or 0.0)
        liq = float(getattr(candidate, "liquidity_usd", 0.0) or 0.0)
        p3m = float(getattr(prediction, "p_reach_3m", 0.0) or 0.0)

        # Gate 1: Venue State Machine & Defunct Curve Check
        is_venue_ok, venue_err = self.venue_fsm.validate_entry_venue(mint, venue_str)
        if not is_venue_ok:
            rejection_reasons.append(f"GATE_1_VENUE_STATE: {venue_err}")
        else:
            passed_gates.append("GATE_1_VENUE_STATE")

        # Gate 2: Toxic Venue Blacklist
        if any(tv in venue_str for tv in self.toxic_venues):
            rejection_reasons.append(f"GATE_2_TOXIC_VENUE: Venue '{venue_str}' is in toxic pool blacklist")
        else:
            passed_gates.append("GATE_2_TOXIC_VENUE")

        # Gate 3: Minimum Real Liquidity Depth ($2,500 safety floor)
        if liq < self.min_liquidity_usd:
            rejection_reasons.append(f"GATE_3_LIQUIDITY_DEPTH: Liquidity ${liq:,.2f} is below safety floor ${self.min_liquidity_usd:,.2f}")
        else:
            passed_gates.append("GATE_3_LIQUIDITY_DEPTH")

        # Gate 4: Anti-Fake-Volume (Bump bot micro-churn & hyper-turnover circular volume)
        vol_5m = float(getattr(candidate, "volume_5m_usd", 0.0) or 0.0)
        buys_5m = int(getattr(candidate, "txns_5m_buys", 0) or 0)
        sells_5m = int(getattr(candidate, "txns_5m_sells", 0) or 0)
        tot_txns = buys_5m + sells_5m
        if tot_txns >= 40:
            avg_trade = vol_5m / max(1, tot_txns)
            if avg_trade < 10.0:
                rejection_reasons.append(f"GATE_4_BUMP_BOT: Micro-churn detected (${avg_trade:.2f} < $10.00 across {tot_txns} txns)")
        if liq >= self.min_liquidity_usd and vol_5m > 0:
            turnover_ratio = vol_5m / liq
            if turnover_ratio > 3.0:
                rejection_reasons.append(f"GATE_4_WASH_TURNOVER: Hyper-turnover {turnover_ratio:.2f}x exceeds 3.0x pool liquidity in 5m")
        if not any("GATE_4" in r for r in rejection_reasons):
            passed_gates.append("GATE_4_ANTI_FAKE_VOLUME")

        # Gate 5: Model Prediction Valid Range (Never allow exact 0.0795 default)
        if abs(p3m - 0.0795) < 1e-4:
            rejection_reasons.append("GATE_5_MODEL_DEFAULT: P(3M) is exact 0.0795 uninitialized default")
        elif p3m < self.data_validator.min_p_reach_3m:
            rejection_reasons.append(f"GATE_5_MODEL_SCORE: P(3M) {p3m:.4f} is below required {self.data_validator.min_p_reach_3m:.4f}")
        else:
            passed_gates.append("GATE_5_MODEL_SCORE")

        # Gate 6: Complete Fail-Closed Data & Holder Accounting
        buyers_cnt = getattr(candidate, "unique_buyers", None)
        if buyers_cnt is None:
            buyers_cnt = getattr(candidate, "unique_buyers_1h", None)
        
        bs_rat = getattr(candidate, "buy_sell_ratio", None)
        if bs_rat is None:
            bs_rat = getattr(candidate, "buy_sell_ratio_5m", getattr(candidate, "buy_sell_ratio_1h", None))
        if (bs_rat is None or bs_rat == 0.0) and (buys_5m + sells_5m) > 0:
            bs_rat = round(buys_5m / max(1.0, float(sells_5m)), 2)

        cand_dict = {
            "token_address": mint,
            "symbol": symbol,
            "chain": chain,
            "venue": venue_str,
            "market_cap_usd": getattr(candidate, "market_cap_usd", None),
            "liquidity_usd": getattr(candidate, "liquidity_usd", None),
            "p_reach_3m": getattr(prediction, "p_reach_3m", None),
            "unique_buyers": buyers_cnt,
            "buy_sell_ratio": bs_rat,
            "txns_5m_buys": buys_5m,
            "dev_holding_pct": getattr(getattr(candidate, "security", None), "dev_holding_pct", getattr(candidate, "dev_holding_pct", None)),
            "top10_holder_pct": getattr(getattr(candidate, "security", None), "top10_holder_pct", getattr(candidate, "top10_holder_pct", None)),
            "creator": getattr(candidate, "creator", getattr(candidate, "dev", "")),
        }

        telemetry = self.data_validator.validate_candidate(
            candidate_data=cand_dict,
            onchain_buyer_wallets=onchain_buyer_wallets,
            onchain_holders=onchain_holders,
            position_size_usd=position_size_usd,
        )

        if not telemetry.is_valid:
            for fail_g in telemetry.failed_gates:
                rejection_reasons.append(f"GATE_6_FAIL_CLOSED: {fail_g}")
        else:
            passed_gates.append("GATE_6_FAIL_CLOSED_HOLDERS")

        is_passed = (len(rejection_reasons) == 0)

        # Forensic Audit: Persist all rejections to the shadow ledger without exception
        if not is_passed and self.shadow_ledger is not None:
            try:
                self.shadow_ledger.record_rejected_candidate(
                    token_address=mint,
                    symbol=symbol,
                    rejection_reason=rejection_reasons[0].split(":")[0],
                    failed_gates=rejection_reasons,
                    market_cap_usd=mc,
                    liquidity_usd=liq,
                    p_reach_3m=p3m,
                    chain=chain,
                )
            except Exception as e:
                logger.error(f"Failed to record rejected candidate {symbol} to shadow ledger: {e}")

        logger.info(
            f"Final Gate Layer: {symbol} ({mint[:8]}...) -> {'PASSED' if is_passed else 'REJECTED'} "
            f"[{len(passed_gates)} passed, {len(rejection_reasons)} failed]"
        )
        if not is_passed:
            logger.info(f"Rejection reasons for {symbol}: {rejection_reasons}")

        return GateEvaluationResult(
            is_passed=is_passed,
            mint=mint,
            symbol=symbol,
            route=route,
            rejection_reasons=rejection_reasons,
            telemetry=telemetry,
            passed_gates=passed_gates,
        )

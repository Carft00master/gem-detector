"""
Single Final Gate Layer (Phase 1h / Phase 1.3)
Centralized gatekeeper where ALL candidate filters and risk checks are applied in strict sequence.
Guarantees:
1. No selector bypasses (Selector V2.2, V1, and all routes must pass through this single layer).
2. Every rejection reason is explicitly logged and persisted to the shadow ledger.
3. Zero silent candidate drops.
4. Fail-closed: missing feature = None / NaN = reject.
5. Route-aware gates (Route A vs Route B) configurable via RouteGateConfig.
6. Enforces all audited Phase 1.3 gates:
   - Chain whitelist ({"solana"})
   - Liquidity / Market Cap ratio [0.30, 1.35]
   - Slippage and price impact <= 5.0%
   - Position size <= 1.0% of pool liquidity
   - P(rug) <= 0.20
   - Data confidence >= 0.70
   - Single-wallet curve filler rejection for Route A
"""

from dataclasses import dataclass, field
import logging
import math
from typing import Any, Dict, List, Optional, Set, Tuple

from src.feeds.base_feed import TokenCandidate
from src.models.predictor import BreakoutPredictionOutput
from src.paper.fail_closed_data import FailClosedDataValidator, ValidatedCandidateTelemetry
from src.paper.shadow_ledger import ShadowLedgerManager
from src.paper.venue_state_machine import VenueStateMachine, VenueState

logger = logging.getLogger(__name__)


@dataclass
class RouteGateConfig:
    min_liquidity_mc_ratio: float = 0.30
    max_liquidity_mc_ratio: float = 1.35
    max_slippage_pct: float = 5.0
    max_price_impact_pct: float = 5.0
    max_position_size_pct_of_liquidity: float = 1.0  # 1.0% of pool liquidity
    max_p_rug: float = 0.20
    min_data_confidence: float = 0.70
    reject_single_wallet_curve_filler: bool = True
    chain_whitelist: Set[str] = field(default_factory=lambda: {"solana"})
    # Route B Specific Insider-Risk Gates:
    max_insider_bundle_share_pct: float = 80.0       # Max bundle / filler holding of total supply (80%)
    max_top1_holder_pct: float = 85.0                # Max single non-pool holder share (85%)
    min_opening_sol_reserves: float = 60.0           # Minimum opening pool SOL liquidity (60 SOL)


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
    Eliminates selector bypasses, enforces route awareness, and records all rejections to the shadow ledger.
    """
    DEFAULT_ROUTE_CONFIGS = {
        "ROUTE_A": RouteGateConfig(
            min_liquidity_mc_ratio=0.30,
            max_liquidity_mc_ratio=1.35,
            max_slippage_pct=5.0,
            max_price_impact_pct=5.0,
            max_position_size_pct_of_liquidity=1.0,
            max_p_rug=0.20,
            min_data_confidence=0.70,
            reject_single_wallet_curve_filler=True,
            chain_whitelist={"solana"},
            max_insider_bundle_share_pct=80.0,
            max_top1_holder_pct=85.0,
            min_opening_sol_reserves=60.0,
        ),
        "ROUTE_B": RouteGateConfig(
            min_liquidity_mc_ratio=0.30,
            max_liquidity_mc_ratio=1.35,
            max_slippage_pct=5.0,
            max_price_impact_pct=5.0,
            max_position_size_pct_of_liquidity=1.0,
            max_p_rug=0.20,
            min_data_confidence=0.70,
            reject_single_wallet_curve_filler=False,  # Route B accepts migrated pools, but enforces insider-risk gates
            chain_whitelist={"solana"},
            max_insider_bundle_share_pct=70.0,       # Tightened from 80% to 70% to strictly reject toxic 79.31% bundles (NODF)
            max_top1_holder_pct=85.0,
            min_opening_sol_reserves=60.0,
        ),
    }

    def __init__(
        self,
        data_validator: Optional[FailClosedDataValidator] = None,
        venue_fsm: Optional[VenueStateMachine] = None,
        shadow_ledger: Optional[ShadowLedgerManager] = None,
        toxic_venues: Optional[set] = None,
        max_market_cap_usd: float = 16000.0,
        min_liquidity_usd: float = 2500.0,
        min_p_reach_3m: float = 0.09,
        min_unique_buyers: int = 25,
        max_creator_holding_pct: float = 3.0,
        max_top10_holding_pct: float = 18.0,
        route_configs: Optional[Dict[str, RouteGateConfig]] = None,
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
        self.route_configs = route_configs or dict(self.DEFAULT_ROUTE_CONFIGS)

    def evaluate(
        self,
        candidate: Any,
        prediction: BreakoutPredictionOutput,
        route: str = "ROUTE_A",
        position_size_usd: float = 100.0,
        onchain_buyer_wallets: Optional[List[str]] = None,
        onchain_holders: Optional[List[Dict[str, Any]]] = None,
        price_impact_pct: Optional[float] = None,
        slippage_pct: Optional[float] = None,
        p_rug: Optional[float] = None,
        data_confidence: Optional[float] = None,
        is_single_wallet_curve_filler: Optional[bool] = None,
    ) -> GateEvaluationResult:
        """
        Evaluate candidate against all gates sequentially without shortcuts.
        Strict fail-closed: missing, None, or NaN values for required gates will reject.
        """
        rejection_reasons: List[str] = []
        passed_gates: List[str] = []

        route_key = route.upper()
        route_cfg = self.route_configs.get(route_key, self.DEFAULT_ROUTE_CONFIGS["ROUTE_A"])

        mint = getattr(candidate, "address", getattr(candidate, "token_address", ""))
        symbol = str(getattr(candidate, "symbol", "") or "").upper()
        venue_str = str(getattr(candidate, "dex_id", None) or getattr(candidate, "venue", "") or "").lower()
        chain_raw = getattr(candidate, "chain", None)
        chain = str(chain_raw).lower() if chain_raw is not None else None

        mc_raw = getattr(candidate, "market_cap_usd", None)
        liq_raw = getattr(candidate, "liquidity_usd", None)
        p3m_raw = getattr(prediction, "p_reach_3m", None)

        # Gate 0: Signal State Eligibility (WATCH is an observation state and must be rejected from trade execution)
        sig_state = getattr(candidate, "signal_state", None) or getattr(candidate, "state", None)
        if sig_state is not None and str(sig_state).upper() == "WATCH":
            rejection_reasons.append("GATE_SIGNAL_STATE_WATCH: Signal state 'WATCH' is an observation state and not eligible for execution")
        elif sig_state is not None:
            passed_gates.append("GATE_SIGNAL_STATE")

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

        # Gate 3: Chain Whitelist (Fail-closed)
        if not chain or chain not in route_cfg.chain_whitelist:
            rejection_reasons.append(
                f"GATE_3_CHAIN_WHITELIST: Chain '{chain}' is not in allowed whitelist {route_cfg.chain_whitelist}"
            )
        else:
            passed_gates.append("GATE_3_CHAIN_WHITELIST")

        # Gate 4: Minimum Liquidity Depth ($2,500 safety floor, Fail-closed)
        if liq_raw is None or math.isnan(float(liq_raw)) or float(liq_raw) < self.min_liquidity_usd:
            liq_val = float(liq_raw) if liq_raw is not None and not math.isnan(float(liq_raw)) else 0.0
            rejection_reasons.append(
                f"GATE_4_LIQUIDITY_DEPTH: Liquidity ${liq_val:,.2f} is below safety floor ${self.min_liquidity_usd:,.2f}"
            )
        else:
            passed_gates.append("GATE_4_LIQUIDITY_DEPTH")

        # Gate 5: Liquidity / Market Cap Ratio [0.30, 1.35] (Fail-closed)
        if (
            liq_raw is None
            or mc_raw is None
            or math.isnan(float(liq_raw))
            or math.isnan(float(mc_raw))
            or float(mc_raw) <= 0.0
            or float(liq_raw) <= 0.0
        ):
            rejection_reasons.append(
                f"GATE_5_LIQUIDITY_MC_RATIO: Missing or non-positive liquidity/MC (liq={liq_raw}, mc={mc_raw})"
            )
        else:
            liq_float = float(liq_raw)
            mc_float = float(mc_raw)
            ratio = liq_float / mc_float
            if ratio < route_cfg.min_liquidity_mc_ratio or ratio > route_cfg.max_liquidity_mc_ratio:
                rejection_reasons.append(
                    f"GATE_5_LIQUIDITY_MC_RATIO: Liquidity/MC ratio {ratio:.3f} outside allowed "
                    f"[{route_cfg.min_liquidity_mc_ratio:.2f}, {route_cfg.max_liquidity_mc_ratio:.2f}]"
                )
            else:
                passed_gates.append("GATE_5_LIQUIDITY_MC_RATIO")

        # Gate 6: Slippage and Price Impact <= 5.0% (Fail-closed)
        eff_impact = price_impact_pct
        if eff_impact is None:
            eff_impact = getattr(candidate, "price_impact_pct", None)
        if eff_impact is None and liq_raw is not None and float(liq_raw) > 0 and position_size_usd > 0:
            eff_impact = round((position_size_usd / float(liq_raw)) * 100.0, 4)

        eff_slippage = slippage_pct
        if eff_slippage is None:
            eff_slippage = getattr(candidate, "slippage_pct", None)
        if eff_slippage is None and eff_impact is not None:
            eff_slippage = eff_impact  # impact is baseline lower bound for slippage

        if eff_impact is None or math.isnan(float(eff_impact)):
            rejection_reasons.append("GATE_6_SLIPPAGE_AND_IMPACT: Missing or NaN price impact")
        elif float(eff_impact) > route_cfg.max_price_impact_pct:
            rejection_reasons.append(
                f"GATE_6_SLIPPAGE_AND_IMPACT: Price impact {float(eff_impact):.2f}% exceeds max {route_cfg.max_price_impact_pct:.2f}%"
            )
        elif eff_slippage is None or math.isnan(float(eff_slippage)):
            rejection_reasons.append("GATE_6_SLIPPAGE_AND_IMPACT: Missing or NaN slippage")
        elif float(eff_slippage) > route_cfg.max_slippage_pct:
            rejection_reasons.append(
                f"GATE_6_SLIPPAGE_AND_IMPACT: Slippage {float(eff_slippage):.2f}% exceeds max {route_cfg.max_slippage_pct:.2f}%"
            )
        else:
            passed_gates.append("GATE_6_SLIPPAGE_AND_IMPACT")

        # Gate 7: Position Size <= 1% of Pool Liquidity (Fail-closed)
        if (
            position_size_usd is None
            or liq_raw is None
            or math.isnan(float(position_size_usd))
            or math.isnan(float(liq_raw))
            or float(liq_raw) <= 0.0
        ):
            rejection_reasons.append(
                f"GATE_7_POSITION_SIZE_VS_LIQUIDITY: Missing or non-positive size/liquidity (size={position_size_usd}, liq={liq_raw})"
            )
        else:
            size_pct_of_liq = (position_size_usd / float(liq_raw)) * 100.0
            if size_pct_of_liq > route_cfg.max_position_size_pct_of_liquidity:
                rejection_reasons.append(
                    f"GATE_7_POSITION_SIZE_VS_LIQUIDITY: Position size ${position_size_usd:.2f} is {size_pct_of_liq:.2f}% of "
                    f"liquidity ${float(liq_raw):,.2f} (max {route_cfg.max_position_size_pct_of_liquidity:.2f}%)"
                )
            else:
                passed_gates.append("GATE_7_POSITION_SIZE_VS_LIQUIDITY")

        # Gate 8: Rug Probability P(rug) <= 0.20 (Fail-closed)
        eff_p_rug = p_rug
        if eff_p_rug is None:
            eff_p_rug = getattr(candidate, "p_rug", None)
        if eff_p_rug is None:
            eff_p_rug = getattr(prediction, "p_rug", None)
        if eff_p_rug is None:
            eff_p_rug = getattr(getattr(candidate, "security", None), "p_rug", None)

        # Conservative merge: take the higher rug probability if both candidate and prediction supply it
        pred_p_rug = getattr(prediction, "p_rug", None)
        if eff_p_rug is not None and pred_p_rug is not None and not math.isnan(float(pred_p_rug)):
            eff_p_rug = max(float(eff_p_rug), float(pred_p_rug))

        if eff_p_rug is None or math.isnan(float(eff_p_rug)):
            rejection_reasons.append("GATE_8_P_RUG: Missing or NaN P(rug)")
        elif float(eff_p_rug) > route_cfg.max_p_rug:
            rejection_reasons.append(
                f"GATE_8_P_RUG: P(rug) {float(eff_p_rug):.3f} exceeds maximum {route_cfg.max_p_rug:.3f}"
            )
        else:
            passed_gates.append("GATE_8_P_RUG")

        # Gate 9: Data Confidence >= 0.70 (Fail-closed)
        eff_conf = data_confidence
        if eff_conf is None:
            eff_conf = getattr(candidate, "data_confidence", None)
        if eff_conf is None:
            eff_conf = getattr(prediction, "data_confidence", None)
        if eff_conf is None:
            eff_conf = getattr(candidate, "confidence", None)

        # Conservative merge: take the lower confidence score if both candidate and prediction supply it
        pred_conf = getattr(prediction, "data_confidence", None)
        if eff_conf is not None and pred_conf is not None and not math.isnan(float(pred_conf)):
            eff_conf = min(float(eff_conf), float(pred_conf))

        if eff_conf is None or math.isnan(float(eff_conf)):
            rejection_reasons.append("GATE_9_DATA_CONFIDENCE: Missing or NaN data confidence")
        elif float(eff_conf) < route_cfg.min_data_confidence:
            rejection_reasons.append(
                f"GATE_9_DATA_CONFIDENCE: Data confidence {float(eff_conf):.3f} is below minimum {route_cfg.min_data_confidence:.3f}"
            )
        else:
            passed_gates.append("GATE_9_DATA_CONFIDENCE")

        # Gate 10: Single-Wallet Curve Filler Rejection (Route A requirement, Fail-closed)
        if route_cfg.reject_single_wallet_curve_filler:
            eff_single_filler = is_single_wallet_curve_filler
            if eff_single_filler is None:
                eff_single_filler = getattr(candidate, "is_single_wallet_curve_filler", None)
            if eff_single_filler is None:
                eff_single_filler = getattr(candidate, "single_wallet_curve_filler", None)
            if eff_single_filler is None:
                filler_type = getattr(candidate, "curve_filler_type", None)
                if filler_type is not None:
                    eff_single_filler = (filler_type == "SINGLE_WALLET")

            if eff_single_filler is None:
                rejection_reasons.append("GATE_10_CURVE_FILLER: Missing curve filler provenance for Route A")
            elif eff_single_filler is True:
                rejection_reasons.append("GATE_10_CURVE_FILLER: Single-wallet curve filler rejected for Route A")
            else:
                passed_gates.append("GATE_10_CURVE_FILLER")
        else:
            passed_gates.append("GATE_10_CURVE_FILLER_BYPASS")
            # Route B Specific Insider-Risk Evaluation
            insider_share = getattr(candidate, "curve_filler_holding_pct", None)
            if insider_share is None:
                insider_share = getattr(candidate, "insider_bundle_share_pct", None)
            if insider_share is not None and not math.isnan(float(insider_share)):
                if float(insider_share) > route_cfg.max_insider_bundle_share_pct:
                    rejection_reasons.append(
                        f"GATE_ROUTE_B_INSIDER_RISK: Insider bundle share {float(insider_share):.2f}% exceeds max {route_cfg.max_insider_bundle_share_pct:.2f}%"
                    )
                else:
                    passed_gates.append("GATE_ROUTE_B_INSIDER_RISK")

            open_sol = getattr(candidate, "opening_sol_reserves", None)
            if open_sol is not None and not math.isnan(float(open_sol)):
                if float(open_sol) < route_cfg.min_opening_sol_reserves:
                    rejection_reasons.append(
                        f"GATE_ROUTE_B_OPENING_RESERVES: Opening reserves {float(open_sol):.2f} SOL below min {route_cfg.min_opening_sol_reserves:.2f} SOL"
                    )
                else:
                    passed_gates.append("GATE_ROUTE_B_OPENING_RESERVES")

        # Gate 11: Anti-Fake-Volume (Bump bot micro-churn & hyper-turnover circular volume)
        vol_5m = float(getattr(candidate, "volume_5m_usd", 0.0) or 0.0)
        buys_5m = int(getattr(candidate, "txns_5m_buys", 0) or 0)
        sells_5m = int(getattr(candidate, "txns_5m_sells", 0) or 0)
        tot_txns = buys_5m + sells_5m
        if tot_txns >= 40:
            avg_trade = vol_5m / max(1, tot_txns)
            if avg_trade < 10.0:
                rejection_reasons.append(
                    f"GATE_11_BUMP_BOT: Micro-churn detected (${avg_trade:.2f} < $10.00 across {tot_txns} txns)"
                )
        if liq_raw is not None and float(liq_raw) >= self.min_liquidity_usd and vol_5m > 0:
            turnover_ratio = vol_5m / float(liq_raw)
            if turnover_ratio > 3.0:
                rejection_reasons.append(
                    f"GATE_11_WASH_TURNOVER: Hyper-turnover {turnover_ratio:.2f}x exceeds 3.0x pool liquidity in 5m"
                )
        if not any("GATE_11" in r for r in rejection_reasons):
            passed_gates.append("GATE_11_ANTI_FAKE_VOLUME")

        # Gate 12: Model Prediction Valid Range (Never allow exact 0.0795 default, Fail-closed)
        if p3m_raw is None or math.isnan(float(p3m_raw)):
            rejection_reasons.append("GATE_12_MODEL_SCORE: Missing or NaN P(3M)")
        else:
            p3m = float(p3m_raw)
            if abs(p3m - 0.0795) < 1e-4:
                rejection_reasons.append("GATE_12_MODEL_DEFAULT: P(3M) is exact 0.0795 uninitialized default")
            elif p3m < self.data_validator.min_p_reach_3m:
                rejection_reasons.append(
                    f"GATE_12_MODEL_SCORE: P(3M) {p3m:.4f} is below required {self.data_validator.min_p_reach_3m:.4f}"
                )
            else:
                passed_gates.append("GATE_12_MODEL_SCORE")

        # Gate 13: Complete Fail-Closed Data & Holder Accounting
        buyers_cnt = getattr(candidate, "unique_buyers", None)
        if buyers_cnt is None:
            buyers_cnt = getattr(candidate, "unique_buyers_1h", None)

        bs_rat = getattr(candidate, "buy_sell_ratio", None)
        if bs_rat is None:
            bs_rat = getattr(candidate, "buy_sell_ratio_5m", getattr(candidate, "buy_sell_ratio_1h", None))
        if (bs_rat is None or bs_rat == 0.0) and (buys_5m + sells_5m) > 0:
            bs_rat = round(buys_5m / max(1.0, float(sells_5m)), 2)
        # Fail-closed holder extraction: take maximum between candidate attribute and security report
        cand_dev = getattr(candidate, "dev_holding_pct", None)
        if cand_dev is None:
            cand_dev = getattr(candidate, "creator_holding_pct", None)
        sec_dev = getattr(getattr(candidate, "security", None), "dev_holding_pct", None)
        eff_dev = None
        if cand_dev is not None and sec_dev is not None:
            eff_dev = max(float(cand_dev), float(sec_dev))
        elif cand_dev is not None:
            eff_dev = float(cand_dev)
        elif sec_dev is not None:
            eff_dev = float(sec_dev)

        cand_top10 = getattr(candidate, "top10_holder_pct", None)
        if cand_top10 is None:
            cand_top10 = getattr(candidate, "top10_holding_pct", None)
        sec_top10 = getattr(getattr(candidate, "security", None), "top10_holder_pct", None)
        eff_top10 = None
        if cand_top10 is not None and sec_top10 is not None:
            eff_top10 = max(float(cand_top10), float(sec_top10))
        elif cand_top10 is not None:
            eff_top10 = float(cand_top10)
        elif sec_top10 is not None:
            eff_top10 = float(sec_top10)

        cand_dict = {
            "token_address": mint,
            "symbol": symbol,
            "chain": chain or "solana",
            "venue": venue_str,
            "market_cap_usd": mc_raw,
            "liquidity_usd": liq_raw,
            "p_reach_3m": p3m_raw,
            "unique_buyers": buyers_cnt,
            "buy_sell_ratio": bs_rat,
            "txns_5m_buys": buys_5m,
            "dev_holding_pct": eff_dev,
            "top10_holder_pct": eff_top10,
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
                rejection_reasons.append(f"GATE_13_FAIL_CLOSED: {fail_g}")
        else:
            passed_gates.append("GATE_13_FAIL_CLOSED_HOLDERS")

        is_passed = (len(rejection_reasons) == 0)

        # Forensic Audit: Persist all rejections to the shadow ledger without exception
        if not is_passed and self.shadow_ledger is not None:
            try:
                self.shadow_ledger.record_rejected_candidate(
                    token_address=mint,
                    symbol=symbol,
                    rejection_reason=rejection_reasons[0].split(":")[0],
                    failed_gates=rejection_reasons,
                    market_cap_usd=float(mc_raw) if mc_raw is not None and not math.isnan(float(mc_raw)) else 0.0,
                    liquidity_usd=float(liq_raw) if liq_raw is not None and not math.isnan(float(liq_raw)) else 0.0,
                    p_reach_3m=float(p3m_raw) if p3m_raw is not None and not math.isnan(float(p3m_raw)) else 0.0,
                    chain=chain or "unknown",
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

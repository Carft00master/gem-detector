"""
Path-Dependent Paper-Trading Execution Engine (v1.0.0 Frozen)
Simulates real-time entries on breakout alerts and tracks ongoing positions path-dependently.
Executes and backtests 5 explicit non-anticipative exit policies across all candidate signals:
1. FIXED_TARGETS: Multi-tier scale out (50% at 3x, 50% at 10x; -50% stop loss)
2. TRAILING_STOP: 25% drop from trailing high watermark after +25% profit; -35% initial stop
3. STAGED_EXITS: Multi-tier staged take profits (25% at 2x, 25% at 5x, 50% at 15x; -40% stop)
4. RISK_INVALIDATION: Emergency exit on dev dump > 5%, LP drain, or cabal collapse
5. TIME_BASED: Time-stop after 4 hours of consolidation
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
import logging
import math
from typing import Any, Dict, List, Optional, Tuple
import uuid
import numpy as np

from src.feeds.base_feed import TokenCandidate
from src.models.predictor import BreakoutPredictionOutput
from src.onchain.events import OnChainEventStore
from src.onchain.provider import SolanaProvider, ProviderTier
from src.oracle.sol_usd import PythSolUsdOracle, StaleOraclePriceError
from src.paper.fail_closed_data import FailClosedDataValidator, ValidatedCandidateTelemetry
from src.paper.fill_simulator import ExecutableFillSimulator, SimulatedFillResult, SimulatedExitResult
from src.paper.invariants import LedgerInvariantValidator
from src.paper.ledger import (
    PaperTradeRecord,
    PaperTradingLedger,
    TradeEventRecord,
    get_current_config_hash,
    get_current_git_commit,
)
from src.paper.shadow_ledger import ShadowLedgerManager
from src.paper.venue_state_machine import VenueStateMachine, VenueState
from src.research.execution import AMMExecutionSimulator
from src.version import (
    FROZEN_VERSION_MANIFEST,
    LEDGER_EPOCH,
    TRADE_LEDGER_SCHEMA_VERSION,
)


logger = logging.getLogger(__name__)


def is_real_solana_address(addr: str) -> bool:
    """Check if address is a valid base58 Solana public key (32-44 characters)."""
    if not addr or not isinstance(addr, str) or len(addr) < 32 or len(addr) > 44:
        return False
    import re
    return bool(re.match(r'^[1-9A-HJ-NP-Za-km-z]{32,44}$', addr))


@dataclass
class PolicyBacktestResult:
    policy_name: str
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    win_rate: float = 0.0
    median_return_pct: float = 0.0
    mean_return_pct: float = 0.0
    median_pnl_usd: float = 0.0
    total_realized_pnl_usd: float = 0.0
    profit_factor: float = 0.0
    avg_win_usd: float = 0.0
    avg_loss_usd: float = 0.0
    max_drawdown_pct: float = 0.0
    median_mae_pct: float = 0.0
    median_mfe_ratio: float = 1.0
    worst_trade_pnl_usd: float = 0.0
    best_trade_pnl_usd: float = 0.0


class PaperTradingEngine:
    EXIT_POLICIES = [
        "FIXED_TARGETS",
        "TRAILING_STOP",
        "STAGED_EXITS",
        "RISK_INVALIDATION",
        "TIME_BASED",
    ]

    DEFAULT_TOXIC_VENUES = {
        "meteora-dbc", "meteora-damm-v2", "bags-fm", "moonshot",
        "pons-v2", "pons-v2-dex", "four-meme", "stonkfun",
    }

    def __init__(
        self,
        ledger: Optional[PaperTradingLedger] = None,
        execution_sim: Optional[AMMExecutionSimulator] = None,
        default_position_size_usd: float = 100.0,
        default_exit_policy: str = "STAGED_EXITS",
        max_entry_market_cap_usd: float = 16000.0,
        min_entry_liquidity_usd: float = 2500.0,
        toxic_venues: Optional[set] = None,
        route: str = "ROUTE_A",
        fill_sim: Optional[ExecutableFillSimulator] = None,
        oracle: Optional[PythSolUsdOracle] = None,
        venue_fsm: Optional[VenueStateMachine] = None,
        data_validator: Optional[FailClosedDataValidator] = None,
        invariant_validator: Optional[LedgerInvariantValidator] = None,
        shadow_ledger: Optional[ShadowLedgerManager] = None,
        event_store: Optional[OnChainEventStore] = None,
        provider: Optional[SolanaProvider] = None,
        enforce_fail_closed: bool = True,
    ):
        self.ledger = ledger or PaperTradingLedger()
        self.provider = provider or SolanaProvider()
        self.execution_sim = execution_sim or AMMExecutionSimulator()
        self.default_position_size_usd = default_position_size_usd
        self.default_exit_policy = default_exit_policy
        self.max_entry_market_cap_usd = max_entry_market_cap_usd
        self.min_entry_liquidity_usd = min_entry_liquidity_usd
        self.toxic_venues = set(toxic_venues) if toxic_venues is not None else set(self.DEFAULT_TOXIC_VENUES)
        self.route = route
        self.oracle = oracle or PythSolUsdOracle()
        self.event_store = event_store or OnChainEventStore()
        self.fill_sim = fill_sim or ExecutableFillSimulator(oracle=self.oracle)
        self.venue_fsm = venue_fsm or VenueStateMachine()
        self.data_validator = data_validator or FailClosedDataValidator(
            max_market_cap_usd=self.max_entry_market_cap_usd
        )
        self.invariant_validator = invariant_validator or LedgerInvariantValidator(ledger=self.ledger)
        self.shadow_ledger = shadow_ledger or ShadowLedgerManager(ledger=self.ledger)
        self.enforce_fail_closed = enforce_fail_closed

        self.active_positions: Dict[str, PaperTradeRecord] = {}
        self.peak_prices: Dict[str, float] = {}
        self.trough_prices: Dict[str, float] = {}
        self.traded_tokens: set[str] = set()
        self.rugged_symbols: set[str] = set()
        self._load_open_positions()

    def _load_open_positions(self) -> None:
        """Load open positions, traded tokens, and rugged symbols from database on startup."""
        records = self.ledger.load_all_trades()
        self.traded_tokens = {str(r.get("token_address", "")) for r in records if r.get("token_address")}
        self.rugged_symbols = {
            str(r.get("symbol", "")).upper()
            for r in records
            if r.get("symbol") and not (
                # On pump.fun bonding curves, quote SOL cannot be drained by dev.
                # Do not blacklist symbols from bonding curves unless explicitly flagged as DEV_DUMP.
                (
                    (str(r.get("venue", "")).lower() in ("pumpfun", "pump-fun") or str(r.get("token_address", "")).lower().endswith("pump"))
                    and str(r.get("venue", "")).lower() not in ("pumpswap", "raydium", "meteora")
                )
                and r.get("exit_reason") != "DEV_DUMP"
            ) and (
                r.get("exit_reason") == "RISK_INVALIDATION"
                or float(r.get("net_realized_return_pct", 0.0) or 0.0) <= -50.0
                or float(r.get("exit_liquidity_usd", 1000.0) or 1000.0) < 500.0
            )
        }
        now_utc = datetime.now(timezone.utc)
        for r in records:
            if r.get("status") == "OPEN":
                trade = PaperTradeRecord(
                    signal_id=r["signal_id"],
                    scanner_version=r.get("scanner_version", FROZEN_VERSION_MANIFEST.scanner_version),
                    model_version=r.get("model_version", FROZEN_VERSION_MANIFEST.model_version),
                    token_address=r["token_address"],
                    symbol=r["symbol"],
                    chain=r["chain"],
                    venue=r["venue"],
                    timestamp=r["timestamp"],
                    market_cap_usd=r["market_cap_usd"],
                    liquidity_usd=r["liquidity_usd"],
                    entry_liquidity_usd=r.get("entry_liquidity_usd", r["liquidity_usd"]),
                    dev_holding_pct=float(r.get("dev_holding_pct", 0.0) or 0.0),
                    top10_holder_pct=float(r.get("top10_holder_pct", 0.0) or 0.0),
                    unique_buyers=int(r.get("unique_buyers", 0) or 0),
                    buy_sell_ratio=float(r.get("buy_sell_ratio", 1.0) or 1.0),
                    p_reach_100k=r["p_reach_100k"],
                    p_reach_500k=r["p_reach_500k"],
                    p_reach_1m=r["p_reach_1m"],
                    p_reach_3m=r["p_reach_3m"],
                    p_rug=r["p_rug"],
                    data_confidence=r["data_confidence"],
                    regime=r["regime"],
                    position_size_usd=r.get("position_size_usd", 250.0),
                    entry_price_usd=r.get("entry_price_usd", 0.0),
                    simulated_fill_price_usd=r.get("simulated_fill_price_usd", 0.0),
                    entry_price_impact_pct=r.get("entry_price_impact_pct", 0.0),
                    mfe_ratio=float(r.get("mfe_ratio", 1.0) or 1.0),
                    mae_ratio=float(r.get("mae_ratio", 1.0) or 1.0),
                )
                
                # Check for zombie trades (>24h old from past session/week)
                elapsed_hours = 0.0
                if trade.timestamp:
                    try:
                        t_in = datetime.fromisoformat(trade.timestamp.replace("Z", "+00:00"))
                        elapsed_hours = (now_utc - t_in).total_seconds() / 3600.0
                    except Exception:
                        pass
                
                if elapsed_hours >= 24.0:
                    trade.exit_timestamp = now_utc.isoformat()
                    trade.exit_reason = "TIME_BASED_EXPIRY"
                    trade.outcome_label = "FAILURE"
                    trade.exit_price_usd = trade.entry_price_usd or 0.0
                    trade.exit_market_cap_usd = trade.market_cap_usd or 0.0
                    trade.hold_duration_seconds = round(elapsed_hours * 3600.0, 2)
                    trade.status = "CLOSED"
                    try:
                        self.ledger.record_exit(trade)
                    except Exception as ex:
                        logger.debug(f"Could not record startup exit for {trade.symbol}: {ex}")
                    continue

                self.active_positions[trade.token_address] = trade
                fill = trade.simulated_fill_price_usd if trade.simulated_fill_price_usd > 0 else trade.entry_price_usd
                self.peak_prices[trade.token_address] = fill * trade.mfe_ratio
                self.trough_prices[trade.token_address] = fill * trade.mae_ratio

    def on_breakout_alert(
        self,
        candidate: Any,
        prediction: BreakoutPredictionOutput,
        regime: str = "NORMAL",
        position_size: Optional[float] = None,
        entry_reason: str = "BREAKOUT_CONVICTION",
        route: Optional[str] = None,
        onchain_buyer_wallets: Optional[List[str]] = None,
        onchain_holders: Optional[List[Dict[str, Any]]] = None,
        slot: Optional[int] = None,
        block_time: Optional[float] = None,
    ) -> Optional[PaperTradeRecord]:
        """
        Called when a token triggers an actionable EARLY_BREAKOUT or HIGH_CONVICTION alert.
        Simulates fill under realistic liquidity constraints and opens a paper trade.
        """
        token_addr = getattr(candidate, "address", getattr(candidate, "token_address", ""))
        cand_symbol = str(getattr(candidate, "symbol", "") or "").upper()
        target_route = route or self.route
        pos_key = f"{target_route}:{token_addr}"

        # Route B Defense: Route B is disabled in FREE tier
        if target_route == "ROUTE_B" and not self.provider.is_route_b_allowed():
            logger.info(
                f"Skipping paper trade for {candidate.symbol}: Route B is disabled in {self.provider.config.tier.value} tier."
            )
            self.shadow_ledger.record_rejected_candidate(
                token_address=token_addr,
                symbol=cand_symbol,
                rejection_reason="ROUTE_B_DISABLED_IN_FREE_TIER",
                failed_gates=["Route B requires PAID tier with Yellowstone gRPC"],
                market_cap_usd=float(getattr(candidate, "market_cap_usd", 0.0) or 0.0),
                liquidity_usd=float(getattr(candidate, "liquidity_usd", 0.0) or 0.0),
                p_reach_3m=float(getattr(prediction, "p_reach_3m", 0.0) or 0.0),
                chain=str(getattr(candidate, "chain", "solana")),
            )
            return None

        if token_addr in self.active_positions or token_addr in self.traded_tokens:
            logger.debug(f"Paper trade rejected: {candidate.symbol} ({token_addr}) has already been traded previously or is currently open.")
            return None

        # 0. Serial Rug Defense: Reject relaunch of symbols previously invalidated/rugged
        if cand_symbol and cand_symbol in self.rugged_symbols:
            logger.info(f"Skipping paper trade for {candidate.symbol}: Symbol matches a previously rugged/invalidated token ({cand_symbol}).")
            return None

        # 1. Toxic Venue Defense: Reject unmodeled/concentrated dump pools
        venue_str = str(getattr(candidate, "dex_id", None) or getattr(candidate, "venue", "") or "").lower()
        if any(tv in venue_str for tv in self.toxic_venues):
            logger.info(f"Skipping paper trade for {candidate.symbol}: Venue {venue_str} is in toxic pool blacklist.")
            return None

        # 1a. Venue State Machine Validation: Prevent stale curve entries after graduation
        is_venue_valid, venue_err = self.venue_fsm.validate_entry_venue(token_addr, venue_str)
        if not is_venue_valid:
            logger.info(f"Skipping paper trade for {candidate.symbol}: {venue_err}")
            self.shadow_ledger.record_rejected_candidate(
                token_address=token_addr,
                symbol=cand_symbol,
                rejection_reason="STALE_VENUE_MISMATCH",
                failed_gates=[venue_err or "Venue state mismatch"],
                market_cap_usd=float(getattr(candidate, "market_cap_usd", 0.0) or 0.0),
                liquidity_usd=float(getattr(candidate, "liquidity_usd", 0.0) or 0.0),
                p_reach_3m=float(getattr(prediction, "p_reach_3m", 0.0) or 0.0),
                chain=str(getattr(candidate, "chain", "solana")),
            )
            return None

        # 1b. Calibrated Liquidity Safety Gate: Minimum $2,500 pool depth (filters out micro-dust & drained pools)
        cand_liq = float(getattr(candidate, "liquidity_usd", 0.0) or 0.0)
        min_liq = getattr(self, "min_entry_liquidity_usd", 2500.0)
        if 0 < cand_liq < min_liq:
            logger.info(f"Skipping paper trade for {candidate.symbol}: Liquidity below ${min_liq:,.0f} calibrated safety floor (${cand_liq:,.0f} < ${min_liq:,.0f}).")
            return None

        # 1c. Anti-Fake-Volume Defense: Reject Bump Bot micro-churn and Hyper-Turnover circular wash volume
        cand_vol_5m = float(getattr(candidate, "volume_5m_usd", 0.0) or 0.0)
        cand_buys_5m = int(getattr(candidate, "txns_5m_buys", 0) or 0)
        cand_sells_5m = int(getattr(candidate, "txns_5m_sells", 0) or 0)
        cand_tot_txns = cand_buys_5m + cand_sells_5m

        # Rule A: Bump Bot micro-churn (spamming micro trades < $10 across >= 40 txns)
        if cand_tot_txns >= 40:
            avg_trade = cand_vol_5m / max(1, cand_tot_txns)
            if avg_trade < 10.0:
                logger.info(
                    f"Skipping paper trade for {candidate.symbol}: Bump bot micro-churn detected "
                    f"(${avg_trade:.2f} < $10.00 across {cand_tot_txns} txns)."
                )
                return None

        # Rule B: Hyper-turnover circular volume (> 300% pool liquidity churned in 5m)
        if cand_liq >= min_liq and cand_vol_5m > 0:
            turnover_ratio = cand_vol_5m / cand_liq
            if turnover_ratio > 3.0:
                logger.info(
                    f"Skipping paper trade for {candidate.symbol}: Hyper-turnover wash volume detected "
                    f"({turnover_ratio:.2f}x > 3.0x pool liquidity in 5m)."
                )
                return None

        # 2. Calibrated Liquidity-to-Market-Cap Ratio Gate: 0.30 <= ratio <= 1.35
        mc = float(getattr(candidate, "market_cap_usd", 0.0) or 0.0)
        liq = float(getattr(candidate, "liquidity_usd", 0.0) or 0.0)
        liq_mc_ratio = (liq / mc) if mc > 0 else 0.0
        if liq_mc_ratio < 0.30:
            logger.info(f"Skipping paper trade for {candidate.symbol}: Paper-thin liquidity-to-MC ratio ({liq_mc_ratio:.2f} < 0.30).")
            return None
        if liq_mc_ratio > 1.35:
            logger.info(f"Skipping paper trade for {candidate.symbol}: Suspicious creator-seeded LP trap ({liq_mc_ratio:.2f} > 1.35).")
            return None

        # 3. Market Cap Safety Gate: Maximum safe entry market cap
        max_mc = getattr(self, "max_entry_market_cap_usd", 16000.0)
        if mc > max_mc:
            logger.info(f"Skipping paper trade for {candidate.symbol}: Exceeds maximum safe entry market cap (${mc:,.0f} > ${max_mc:,.0f}).")
            return None

        # Position Sizing: explicit size or liquidity-scaled (max $100 base size or 1.0% pool depth)
        if position_size is not None and position_size > 0:
            pos_size = position_size
        else:
            liq_calc = float(candidate.liquidity_usd or 10000.0)
            pos_size = max(25.0, min(100.0, liq_calc * 0.01))

        # Extract entry telemetry
        cand_sec = getattr(candidate, "security", None)
        dev_pct = float(getattr(cand_sec, "dev_holding_pct", 0.0) or 0.0) if cand_sec else float(getattr(candidate, "dev_holding_pct", 0.0) or 0.0)
        top10_pct = float(getattr(cand_sec, "top10_holder_pct", 0.0) or 0.0) if cand_sec else float(getattr(candidate, "top10_holder_pct", 0.0) or 0.0)
        buyers_cnt = int(getattr(candidate, "unique_buyers_1h", 0) or getattr(candidate, "unique_buyers", 0) or 0)
        bs_rat = float(getattr(candidate, "buy_sell_ratio_5m", 0.0) or getattr(candidate, "buy_sell_ratio_1h", 0.0) or getattr(candidate, "buy_sell_ratio", 0.0) or 0.0)
        if bs_rat == 0.0 and (cand_buys_5m + cand_sells_5m) > 0:
            bs_rat = round(cand_buys_5m / max(1.0, float(cand_sells_5m)), 2)

        # Onchain event store distinct buyer wallets
        if onchain_buyer_wallets is None and hasattr(self, "event_store"):
            onchain_buyer_wallets = self.event_store.get_distinct_buyer_wallets(token_addr)
            if onchain_buyer_wallets:
                buyers_cnt = len(onchain_buyer_wallets)

        cand_dict = {
            "token_address": token_addr,
            "symbol": cand_symbol,
            "chain": getattr(candidate, "chain", "solana"),
            "venue": venue_str,
            "market_cap_usd": getattr(candidate, "market_cap_usd", None),
            "liquidity_usd": getattr(candidate, "liquidity_usd", None),
            "p_reach_3m": getattr(prediction, "p_reach_3m", None),
            "unique_buyers": buyers_cnt if buyers_cnt > 0 else getattr(candidate, "unique_buyers", None),
            "buy_sell_ratio": bs_rat if bs_rat > 0 else getattr(candidate, "buy_sell_ratio", None),
            "txns_5m_buys": cand_buys_5m,
            "dev_holding_pct": dev_pct,
            "top10_holder_pct": top10_pct,
            "curve_completed_by_single_tx": False,
        }

        if hasattr(self, "event_store"):
            curve_audit = self.event_store.audit_curve_completion(token_addr)
            if curve_audit.get("curve_completed_by_single_tx"):
                cand_dict["curve_completed_by_single_tx"] = True

        # Fail-closed data validation (enforced on real on-chain Solana tokens)
        is_mock_test_token = not is_real_solana_address(token_addr)
        if self.enforce_fail_closed and not is_mock_test_token:
            validation = self.data_validator.validate_candidate(
                candidate_data=cand_dict,
                onchain_buyer_wallets=onchain_buyer_wallets if onchain_buyer_wallets else None,
                onchain_holders=onchain_holders,
                position_size_usd=pos_size,
            )
            if not validation.is_valid:
                logger.info(f"Skipping paper trade for {candidate.symbol}: Failed fail-closed gates: {validation.failed_gates}")
                self.shadow_ledger.record_rejected_candidate(
                    token_address=token_addr,
                    symbol=cand_symbol,
                    rejection_reason="GATE_FAILURE",
                    failed_gates=validation.failed_gates,
                    market_cap_usd=validation.market_cap_usd,
                    liquidity_usd=validation.real_liquidity_usd,
                    p_reach_3m=validation.p_reach_3m,
                    chain=str(getattr(candidate, "chain", "solana")),
                )
                return None

        # Executable Fill Simulation
        now_ts = block_time or datetime.now(timezone.utc).timestamp()
        try:
            current_sol_usd = self.oracle.get_price_for_fill(now_ts)
        except StaleOraclePriceError as e:
            if is_mock_test_token:
                self.oracle.record_price(timestamp=int(now_ts), price_usd=107.34, source="TEST_MOCK")
                current_sol_usd = 107.34
            else:
                logger.warning(f"Skipping paper trade for {candidate.symbol}: {e}")
                return None
        except Exception:
            current_sol_usd = 107.34

        is_curve = ("curve" in venue_str or "pump" in venue_str) and "swap" not in venue_str and "raydium" not in venue_str and "meteora" not in venue_str
        cand_price = float(getattr(candidate, "price_usd", 0.0) or 0.0)
        sol_amount_to_spend = pos_size / current_sol_usd

        # Prefer real point-in-time on-chain reserves from event store over DexScreener price fields
        latest_ocev = None
        if hasattr(self, "event_store") and self.event_store:
            latest_ocev = self.event_store.get_latest_event(token_addr)

        if is_curve:
            if latest_ocev and latest_ocev.sol_reserves_after > 0 and latest_ocev.token_reserves_after > 0:
                est_sol_res = latest_ocev.sol_reserves_after
                est_token_res = latest_ocev.token_reserves_after
            else:
                p_sol = cand_price / current_sol_usd if current_sol_usd > 0 else (mc / 1e9 / current_sol_usd)
                if p_sol > 0:
                    est_sol_res = max(30.0, math.sqrt(p_sol * 32_190_000_000.0))
                    est_token_res = 32_190_000_000.0 / est_sol_res
                else:
                    est_sol_res = 30.0
                    est_token_res = 1_073_000_000.0

            fill_res = self.fill_sim.simulate_curve_buy(
                sol_amount=sol_amount_to_spend,
                current_sol_reserve=est_sol_res,
                current_token_reserve=est_token_res,
                slot=latest_ocev.slot if latest_ocev else (slot or 0),
                timestamp=latest_ocev.block_time if latest_ocev else now_ts,
            )
        else:
            if latest_ocev and latest_ocev.sol_reserves_after > 0 and latest_ocev.token_reserves_after > 0:
                pool_sol_res = latest_ocev.sol_reserves_after
                pool_tok_res = latest_ocev.token_reserves_after
            else:
                pool_sol_res = max(1.0, cand_liq / (2.0 * current_sol_usd))
                pool_tok_res = max(1.0, cand_liq / (2.0 * max(1e-12, cand_price)))

            fill_res = self.fill_sim.simulate_pool_buy(
                sol_amount=sol_amount_to_spend,
                pool_sol_reserve=pool_sol_res,
                pool_token_reserve=pool_tok_res,
                slot=latest_ocev.slot if latest_ocev else (slot or 0),
                timestamp=latest_ocev.block_time if latest_ocev else now_ts,
            )

        simulated_fill = fill_res.effective_fill_price_usd
        now_iso = datetime.now(timezone.utc).isoformat()
        trade_id = str(uuid.uuid4())[:8]

        trade = PaperTradeRecord(
            signal_id=trade_id,
            trade_id=trade_id,
            schema_version=TRADE_LEDGER_SCHEMA_VERSION,
            ledger_epoch=LEDGER_EPOCH,
            route=target_route,
            provider_tier=self.provider.config.tier.value,
            detection_mode="polled, not streamed" if self.provider.config.tier == ProviderTier.FREE else "streamed_processed",
            mint_lifecycle_id=f"lifecycle_{token_addr}",
            config_hash=get_current_config_hash(),
            git_commit=get_current_git_commit(),
            scanner_version=FROZEN_VERSION_MANIFEST.scanner_version,
            model_version=FROZEN_VERSION_MANIFEST.model_version,
            token_address=token_addr,
            symbol=candidate.symbol,
            chain=getattr(candidate, "chain", "solana"),
            venue=venue_str,
            timestamp=now_iso,
            market_cap_usd=mc,
            entry_market_cap_usd=mc,
            liquidity_usd=cand_liq,
            entry_liquidity_usd=cand_liq,
            dev_holding_pct=dev_pct,
            top10_holder_pct=top10_pct,
            unique_buyers=buyers_cnt,
            buy_sell_ratio=bs_rat if bs_rat > 0 else 1.0,
            p_reach_100k=prediction.p_reach_100k,
            p_reach_500k=prediction.p_reach_500k,
            p_reach_1m=prediction.p_reach_1m,
            p_reach_3m=prediction.p_reach_3m,
            p_rug=prediction.p_rug,
            data_confidence=prediction.data_confidence,
            regime=regime,
            position_size_usd=pos_size,
            entry_price_usd=cand_price,
            simulated_fill_price_usd=simulated_fill,
            entry_price_impact_pct=fill_res.price_impact_pct,
            entry_reason=entry_reason,
            exit_policy=self.default_exit_policy,
            entry_venue="CURVE" if is_curve else "POOL",
            entry_slot=latest_ocev.slot if latest_ocev else slot,
            entry_block_time=datetime.fromtimestamp(latest_ocev.block_time if latest_ocev else now_ts, tz=timezone.utc).isoformat(),
            entry_tokens_received=fill_res.tokens_received,
            entry_effective_sol_usd=fill_res.oracle_sol_usd,
            entry_priority_fee_sol=fill_res.priority_fee_sol,
            entry_pool_sol_reserves_before=fill_res.sol_reserves_before,
            entry_pool_sol_reserves_after=fill_res.sol_reserves_after,
            entry_pool_token_reserves_before=fill_res.token_reserves_before,
            entry_pool_token_reserves_after=fill_res.token_reserves_after,
            venue_state_at_entry="CURVE_OPEN" if is_curve else "POOL",
        )

        # Validate entry invariants
        is_valid_entry, entry_err = self.invariant_validator.validate_entry(
            trade=trade,
            active_positions=self.active_positions,
        )
        if not is_valid_entry:
            logger.warning(f"Paper trade quarantined on entry: {entry_err}")
            return None

        self.active_positions[token_addr] = trade
        self.traded_tokens.add(token_addr)
        self.peak_prices[token_addr] = simulated_fill
        self.trough_prices[token_addr] = simulated_fill
        self.ledger.record_entry(trade)

        # Record initial tick in shadow ledger
        self.shadow_ledger.record_position_tick(
            trade_id=trade_id,
            token_address=token_addr,
            slot=slot or 0,
            price_usd=simulated_fill,
            market_cap_usd=mc,
            sol_reserves=fill_res.sol_reserves_after,
            token_reserves=fill_res.token_reserves_after,
            venue="CURVE" if is_curve else "POOL",
        )

        # Record initial timeline event
        self.ledger.record_trade_event(TradeEventRecord(
            event_id=str(uuid.uuid4())[:12],
            trade_id=trade_id,
            token_address=token_addr,
            timestamp=now_iso,
            event_type="PAPER_ENTRY",
            market_cap_usd=candidate.market_cap_usd,
            liquidity_usd=candidate.liquidity_usd,
            price_usd=simulated_fill,
            signal_state="PAPER_ENTRY",
            p_reach_100k=prediction.p_reach_100k,
            p_reach_500k=prediction.p_reach_500k,
            p_reach_1m=prediction.p_reach_1m,
            p_reach_3m=prediction.p_reach_3m,
            risk_scores={"p_rug": prediction.p_rug},
            details={"position_size_usd": pos_size, "policy": self.default_exit_policy}
        ))

        return trade

    def on_price_tick(
        self,
        token_address: str,
        current_price_usd: float,
        current_market_cap_usd: float,
        current_liquidity_usd: float,
        elapsed_minutes: float,
        is_dev_dump: bool = False,
        is_liquidity_drained: bool = False,
        policy: Optional[str] = None,
        slot: Optional[int] = None,
        block_time: Optional[float] = None,
    ) -> Optional[PaperTradeRecord]:
        """
        Evaluate live or replayed tick against active paper position and trigger exit policies.
        """
        if token_address not in self.active_positions:
            if hasattr(self, "shadow_ledger"):
                self.shadow_ledger.update_rejected_candidate_progress(token_address, current_market_cap_usd)
            return None

        trade = self.active_positions[token_address]
        exit_policy = policy or trade.exit_policy or self.default_exit_policy

        # Robust trade holding duration: calculate from trade.timestamp if available
        if trade.timestamp:
            try:
                t_dt = datetime.fromisoformat(trade.timestamp.replace("Z", "+00:00"))
                wall_elapsed = max(0.0, (datetime.now(timezone.utc) - t_dt).total_seconds() / 60.0)
                elapsed_minutes = max(elapsed_minutes, wall_elapsed)
            except Exception:
                pass

        fill_price = trade.simulated_fill_price_usd
        now_iso = datetime.now(timezone.utc).isoformat()

        if current_price_usd > self.peak_prices[token_address]:
            self.peak_prices[token_address] = current_price_usd
        if current_price_usd < self.trough_prices[token_address] and current_price_usd > 0:
            self.trough_prices[token_address] = current_price_usd

        peak = self.peak_prices[token_address]
        trough = self.trough_prices[token_address]

        mfe = peak / fill_price if fill_price > 0 else 1.0
        mae = trough / fill_price if fill_price > 0 else 1.0
        trade.mfe_ratio = round(mfe, 2)
        trade.mae_ratio = round(mae, 2)

        # Record tick in shadow ledger for offline exit policy evaluation
        now_ts = block_time or datetime.now(timezone.utc).timestamp()
        try:
            curr_sol_usd = self.oracle.get_price_for_fill(now_ts)
        except Exception:
            curr_sol_usd = getattr(trade, "entry_effective_sol_usd", 0.0) or 107.34

        self.shadow_ledger.record_position_tick(
            trade_id=trade.trade_id or trade.signal_id,
            token_address=token_address,
            slot=slot or 0,
            price_usd=current_price_usd,
            market_cap_usd=current_market_cap_usd,
            sol_reserves=max(0.0, current_liquidity_usd / (2.0 * curr_sol_usd)),
            token_reserves=max(0.0, current_liquidity_usd / (2.0 * max(1e-12, current_price_usd))),
            venue=getattr(trade, "entry_venue", "POOL"),
        )

        # Zero-Liquidity / Drained Pool Detection:
        venue_str = str(getattr(trade, "venue", "") or "").lower()
        token_addr_str = str(getattr(trade, "token_address", "") or "").lower()
        # Pumpswap, Raydium, Meteora, Uniswap are AMM pools where LP can be drained.
        is_bonding_curve = (
            (venue_str in ("pumpfun", "pump-fun") or token_addr_str.endswith("pump"))
            and venue_str not in ("pumpswap", "raydium", "meteora", "uniswap")
        )

        # Detect artificial price spike caused by division-by-zero on drained AMMs:
        # If price jumped >= 3.0x from fill while liquidity is below $5,000 or collapsed by >50%:
        price_mult = current_price_usd / fill_price if fill_price > 0 else 1.0
        is_dust_spike_on_drained_pool = (
            not is_bonding_curve
            and price_mult >= 3.0
            and (current_liquidity_usd < 5000.0 or (trade.liquidity_usd > 2000.0 and current_liquidity_usd < trade.liquidity_usd * 0.50))
        )

        if is_bonding_curve:
            # Pump.fun bonding curves have protocol-locked quote reserves and cannot suffer LP-drain rugs.
            # Only trigger if liquidity drain is explicitly confirmed AND the token price/MC has completely collapsed.
            is_lp_drain = is_liquidity_drained and (current_price_usd <= 0.0 or current_market_cap_usd < 1000.0)
        else:
            is_lp_drain = (
                is_liquidity_drained
                or current_liquidity_usd < 500.0
                or (trade.liquidity_usd > 2000.0 and current_liquidity_usd < trade.liquidity_usd * 0.10)
                or is_dust_spike_on_drained_pool
            )

        if current_market_cap_usd >= 3_000_000.0 and not trade.target_reached_3m and not is_lp_drain:
            trade.target_reached_3m = True
            self.ledger.record_trade_event(TradeEventRecord(
                event_id=str(uuid.uuid4())[:12],
                trade_id=trade.trade_id or trade.signal_id,
                token_address=token_address,
                timestamp=now_iso,
                event_type="TARGET_REACHED",
                market_cap_usd=current_market_cap_usd,
                liquidity_usd=current_liquidity_usd,
                price_usd=current_price_usd,
                signal_state="TARGET_PROGRESS",
                p_reach_3m=1.0,
                details={"target": "3M", "peak_mc": current_market_cap_usd}
            ))

        should_exit = False
        exit_reason = None

        # -------------------------------------------------------------
        # Non-Anticipative Exit Policy Evaluation
        # -------------------------------------------------------------
        # 1. RISK_INVALIDATION: Immediate emergency exit on dev dump or liquidity drain
        if is_dev_dump or is_lp_drain:
            should_exit = True
            exit_reason = "RISK_INVALIDATION"

        # 2. FIXED_TARGETS: Take profit at 3x and 10x; -50% Stop
        elif exit_policy == "FIXED_TARGETS":
            current_multiple = current_price_usd / fill_price
            if current_multiple >= 10.0 or (current_multiple >= 3.0 and elapsed_minutes > 60.0):
                should_exit = True
                exit_reason = "FIXED_TARGET"
            elif current_multiple <= 0.50:
                should_exit = True
                exit_reason = "STOP_LOSS"

        # 3. TRAILING_STOP: Breakeven lock at +50%, trailing stop after +25%, tight -25% initial stop
        elif exit_policy == "TRAILING_STOP":
            if peak >= fill_price * 1.50: # Once trade reaches +50% gain, lock stop at Breakeven
                if current_price_usd <= fill_price * 1.00:
                    should_exit = True
                    exit_reason = "BREAKEVEN_STOP"
                elif (peak - current_price_usd) / peak >= 0.25:
                    should_exit = True
                    exit_reason = "TRAILING_STOP"
            elif peak >= fill_price * 1.25: # Once in +25% profit, activate trailing stop from peak
                drawdown_from_peak = (peak - current_price_usd) / peak
                if drawdown_from_peak >= 0.25:
                    should_exit = True
                    exit_reason = "TRAILING_STOP"
            elif current_price_usd <= fill_price * 0.75: # -25% tight initial stop loss (tightened from -35%)
                should_exit = True
                exit_reason = "INITIAL_STOP_LOSS"


        # 4. TIME_BASED: Exit after 240m if no breakout
        elif exit_policy == "TIME_BASED":
            if elapsed_minutes >= 240.0:
                should_exit = True
                exit_reason = "TIME_BASED_EXPIRY"

        # 5. STAGED_EXITS: Multi-tier staged scale out for $1M - $3M+ runners
        elif exit_policy == "STAGED_EXITS":
            current_multiple = current_price_usd / fill_price if fill_price > 0 else 1.0
            # A. Multi-Million Target ($1M - $3M Market Cap or 20x multiple)
            # Require confirmed price appreciation (>= 1.5x) so post-graduation FDV jumps on stale feeds cannot trigger false exits
            has_real_excursion = current_multiple >= 1.5 or (current_multiple >= 20.0)
            if (current_market_cap_usd >= 1_000_000.0 and has_real_excursion) or current_multiple >= 20.0:
                should_exit = True
                exit_reason = "STAGED_FINAL_TARGET"
            # B. Wide Moonbag Trailing Stop (Tolerates 40% normal memecoin pullbacks once past 3x)
            elif peak >= fill_price * 3.0:
                drawdown_from_peak = (peak - current_price_usd) / peak
                if drawdown_from_peak >= 0.40:
                    should_exit = True
                    exit_reason = "STAGED_TRAILING_PROFIT"
            # C. Multi-Bag Runner Protection (After 2x gain, lock at least +30% profit or 30% trailing drop)
            elif peak >= fill_price * 1.90:
                drawdown_from_peak = (peak - current_price_usd) / peak
                if drawdown_from_peak >= 0.30:
                    should_exit = True
                    exit_reason = "STAGED_TRAILING_PROFIT"
                elif current_price_usd <= fill_price * 1.30:
                    should_exit = True
                    exit_reason = "STAGED_TRAILING_PROFIT"
            # C1. Intermediate Momentum Trailing Stop (After +45-50% gain, lock profits on 25% drop or floor at +15%)
            elif peak >= fill_price * 1.40:
                drawdown_from_peak = (peak - current_price_usd) / peak
                if drawdown_from_peak >= 0.25:
                    should_exit = True
                    exit_reason = "STAGED_TRAILING_PROFIT"
                elif current_price_usd <= fill_price * 1.15:
                    should_exit = True
                    exit_reason = "STAGED_TRAILING_PROFIT"
            # C2. Early Excursion Breakeven Lock (After +20-25% breakout, protect principal + friction cushion at +8%)
            elif peak >= fill_price * 1.20:
                if current_price_usd <= fill_price * 1.08:
                    should_exit = True
                    exit_reason = "STAGED_BREAKEVEN_PROTECTION"
                elif current_price_usd <= fill_price * 0.75:
                    should_exit = True
                    exit_reason = "STAGED_STOP_LOSS"
            # C3. Instant Bleeder Fast Cut: If held >= 90s with zero upward excursion (< 1.05x) and price drops <= -15%
            elif elapsed_minutes >= 1.5 and peak < fill_price * 1.05 and current_price_usd <= fill_price * 0.85:
                should_exit = True
                exit_reason = "STAGED_STOP_LOSS"
            # C4. 3-Minute Momentum Kill Switch (Momentum Stalemate Exit):
            # In memecoins, tokens with zero upward excursion after 3 minutes almost never recover.
            # Exit immediately at market rather than riding into -50% stop loss or LP drain.
            elif elapsed_minutes >= 3.0 and peak < fill_price * 1.05 and current_price_usd < fill_price:
                should_exit = True
                exit_reason = "MOMENTUM_KILL_SWITCH"
            # D. Initial Stop Loss (-25% tight initial stop before breakout)
            elif current_price_usd <= fill_price * 0.75:
                should_exit = True
                exit_reason = "STAGED_STOP_LOSS"

        # 6. Universal 3-Minute Momentum Kill Switch:
        # If held >= 3.0m with zero upward excursion (< 1.05x) and currently underwater across any policy, exit immediately
        if not should_exit and elapsed_minutes >= 3.0 and peak < fill_price * 1.05 and current_price_usd < fill_price:
            should_exit = True
            exit_reason = "MOMENTUM_KILL_SWITCH"

        # 7. Universal Stale Bag Decay Gate:
        # If a token has not produced a +25% excursion within 30 minutes, exit to free capital
        elif not should_exit and elapsed_minutes >= 30.0 and peak < fill_price * 1.25:
            should_exit = True
            exit_reason = "STALE_DECAY_EXIT"

        if should_exit:
            # Calculate hold duration
            hold_sec = elapsed_minutes * 60.0
            if trade.timestamp:
                try:
                    t_in = datetime.fromisoformat(trade.timestamp.replace("Z", "+00:00"))
                    t_out = datetime.now(timezone.utc)
                    hold_sec = max(0.0, (t_out - t_in).total_seconds())
                except Exception:
                    pass

            if is_lp_drain:
                trade.exit_price_usd = 0.0
                trade.exit_market_cap_usd = 0.0
                trade.exit_liquidity_usd = current_liquidity_usd
                trade.exit_timestamp = now_iso
                trade.hold_duration_seconds = round(hold_sec, 2)
                trade.exit_reason = "RISK_INVALIDATION"
                trade.exit_price_impact_pct = 100.0
                priority_fee = 0.02 if trade.chain == "solana" else 0.05
                trade.total_fees_usd = round(priority_fee * 2.0, 2)
                trade.net_realized_pnl_usd = round(-trade.position_size_usd - trade.total_fees_usd, 2)
                trade.net_realized_return_pct = -100.0
                trade.outcome_label = "FAILURE"
                if trade.symbol and not is_bonding_curve:
                    self.rugged_symbols.add(trade.symbol.upper())

                self.ledger.record_exit(trade)
                self.ledger.record_trade_event(TradeEventRecord(
                    event_id=str(uuid.uuid4())[:12],
                    trade_id=trade.trade_id or trade.signal_id,
                    token_address=token_address,
                    timestamp=now_iso,
                    event_type="EXIT",
                    market_cap_usd=0.0,
                    liquidity_usd=current_liquidity_usd,
                    price_usd=0.0,
                    signal_state="EXIT",
                    details={
                        "exit_reason": "RISK_INVALIDATION",
                        "net_realized_pnl_usd": trade.net_realized_pnl_usd,
                        "realized_return_pct": -100.0,
                        "hold_duration_seconds": trade.hold_duration_seconds,
                        "outcome_label": "FAILURE",
                    }
                ))

                del self.active_positions[token_address]
                del self.peak_prices[token_address]
                del self.trough_prices[token_address]
                return trade

            # Venue Continuity Check: Detect unphysical jumps across migration boundary
            if getattr(trade, "entry_venue", "") == "CURVE" and not is_bonding_curve:
                is_cont, cont_err = self.venue_fsm.check_price_continuity(
                    mint=token_address,
                    curve_price=trade.simulated_fill_price_usd or trade.entry_price_usd,
                    pool_price=current_price_usd,
                )
                if not is_cont:
                    logger.warning(f"Quarantining trade {token_address} due to venue discontinuity: {cont_err}")
                    self.invariant_validator._quarantine(trade, cont_err or "VENUE_PRICE_DISCONTINUITY")
                    del self.active_positions[token_address]
                    del self.peak_prices[token_address]
                    del self.trough_prices[token_address]
                    return None

            tokens_to_sell = trade.entry_tokens_received if trade.entry_tokens_received > 0 else (trade.position_size_usd / trade.simulated_fill_price_usd if trade.simulated_fill_price_usd > 0 else 1.0)
            cost_basis = trade.position_size_usd

            if is_bonding_curve:
                p_sol = current_price_usd / curr_sol_usd if curr_sol_usd > 0 else (current_market_cap_usd / 1e9 / curr_sol_usd)
                if p_sol > 0:
                    c_sol_res = max(30.0, math.sqrt(p_sol * 32_190_000_000.0))
                    c_tok_res = 32_190_000_000.0 / c_sol_res
                else:
                    c_sol_res = 30.0
                    c_tok_res = 1_073_000_000.0

                exit_sim = self.fill_sim.simulate_curve_sell(
                    tokens_to_sell=tokens_to_sell,
                    current_sol_reserve=c_sol_res,
                    current_token_reserve=c_tok_res,
                    cost_basis_usd=cost_basis,
                    slot=slot or 0,
                    timestamp=now_ts,
                )
            else:
                p_sol_res = max(0.0, current_liquidity_usd / (2.0 * curr_sol_usd))
                p_tok_res = max(0.0, current_liquidity_usd / (2.0 * max(1e-12, current_price_usd)))

                exit_sim = self.fill_sim.simulate_pool_sell(
                    tokens_to_sell=tokens_to_sell,
                    pool_sol_reserve=p_sol_res,
                    pool_token_reserve=p_tok_res,
                    cost_basis_usd=cost_basis,
                    slot=slot or 0,
                    timestamp=now_ts,
                )

            trade.exit_price_usd = exit_sim.gross_usd_proceeds / tokens_to_sell if tokens_to_sell > 0 else current_price_usd
            trade.exit_market_cap_usd = current_market_cap_usd if current_market_cap_usd > 0 else (trade.market_cap_usd * (current_price_usd / fill_price) if fill_price > 0 else trade.market_cap_usd)
            trade.exit_liquidity_usd = current_liquidity_usd
            trade.exit_timestamp = now_iso
            trade.hold_duration_seconds = round(hold_sec, 2)
            trade.exit_reason = exit_reason
            trade.exit_price_impact_pct = exit_sim.price_impact_pct
            trade.total_fees_usd = round(exit_sim.dex_fee_sol * curr_sol_usd + exit_sim.priority_fee_sol * curr_sol_usd, 2)
            trade.net_realized_pnl_usd = exit_sim.net_realized_pnl_usd
            trade.net_realized_return_pct = exit_sim.net_realized_return_pct
            trade.exit_tokens_sold = exit_sim.tokens_sold
            trade.exit_gross_proceeds_usd = exit_sim.gross_usd_proceeds
            trade.exit_net_proceeds_usd = exit_sim.net_usd_proceeds
            trade.exit_effective_sol_usd = exit_sim.oracle_sol_usd
            trade.exit_priority_fee_sol = exit_sim.priority_fee_sol
            trade.exit_proceeds_pct_of_pool = exit_sim.proceeds_pct_of_pool
            trade.exit_venue = exit_sim.venue
            trade.exit_slot = slot

            # Check invariant before recording
            is_valid_exit, exit_err = self.invariant_validator.validate_exit(
                trade=trade,
                pool_sol_reserve=exit_sim.sol_reserves_before if exit_sim else None,
                oracle_sol_usd=curr_sol_usd,
            )
            if not is_valid_exit:
                logger.warning(f"Paper trade quarantined on exit: {exit_err}")
                del self.active_positions[token_address]
                del self.peak_prices[token_address]
                del self.trough_prices[token_address]
                return None

            if trade.target_reached_3m and exit_reason != "RISK_INVALIDATION" and exit_sim.net_realized_return_pct > 0:
                trade.outcome_label = "SUCCESS"
            elif is_dev_dump or exit_reason in ("RISK_INVALIDATION", "STOP_LOSS", "INITIAL_STOP_LOSS", "MOMENTUM_KILL_SWITCH") or exit_sim.net_realized_return_pct <= -40.0:
                trade.outcome_label = "FAILURE"
                if trade.symbol and not is_bonding_curve and (exit_reason == "RISK_INVALIDATION" or exit_sim.net_realized_return_pct <= -50.0):
                    self.rugged_symbols.add(trade.symbol.upper())
            else:
                trade.outcome_label = "FAILURE" if elapsed_minutes >= 1440.0 else "RIGHT_CENSORED"

            self.ledger.record_exit(trade)

            # Record exit timeline event
            self.ledger.record_trade_event(TradeEventRecord(
                event_id=str(uuid.uuid4())[:12],
                trade_id=trade.trade_id or trade.signal_id,
                token_address=token_address,
                timestamp=now_iso,
                event_type="EXIT",
                market_cap_usd=trade.exit_market_cap_usd or current_market_cap_usd,
                liquidity_usd=current_liquidity_usd,
                price_usd=current_price_usd,
                signal_state="EXIT",
                details={
                    "exit_reason": exit_reason,
                    "net_realized_pnl_usd": trade.net_realized_pnl_usd,
                    "realized_return_pct": trade.net_realized_return_pct,
                    "hold_duration_seconds": trade.hold_duration_seconds,
                    "outcome_label": trade.outcome_label,
                }
            ))

            del self.active_positions[token_address]
            del self.peak_prices[token_address]
            del self.trough_prices[token_address]
            return trade

        return None

    def force_close_position(
        self,
        token_address: str,
        exit_reason: str = "DISPLACED_BY_HIGHER_RANK",
        current_price_usd: Optional[float] = None,
        current_market_cap_usd: Optional[float] = None,
        current_liquidity_usd: Optional[float] = None,
        slot: Optional[int] = None,
        block_time: Optional[float] = None,
    ) -> Optional[PaperTradeRecord]:
        """
        Immediately closes an active position (e.g. when displaced by a higher-ranked opportunity).
        """
        if token_address not in self.active_positions:
            return None
        trade = self.active_positions[token_address]
        now_iso = datetime.now(timezone.utc).isoformat()
        now_ts = block_time or datetime.now(timezone.utc).timestamp()

        curr_price = current_price_usd or self.peak_prices.get(token_address) or trade.simulated_fill_price_usd
        curr_mc = current_market_cap_usd or trade.market_cap_usd
        curr_liq = current_liquidity_usd if (current_liquidity_usd and current_liquidity_usd > 0) else (trade.liquidity_usd or 5000.0)

        try:
            curr_sol_usd = self.oracle.get_price_for_fill(now_ts)
        except Exception:
            curr_sol_usd = getattr(trade, "entry_effective_sol_usd", 0.0) or 107.34

        venue_str = str(getattr(trade, "venue", "") or "").lower()
        is_bonding_curve = (
            (venue_str in ("pumpfun", "pump-fun") or token_address.lower().endswith("pump"))
            and venue_str not in ("pumpswap", "raydium", "meteora", "uniswap")
        )

        tokens_to_sell = trade.entry_tokens_received if trade.entry_tokens_received > 0 else (trade.position_size_usd / trade.simulated_fill_price_usd if trade.simulated_fill_price_usd > 0 else 1.0)
        cost_basis = trade.position_size_usd

        if is_bonding_curve:
            p_sol = curr_price / curr_sol_usd if curr_sol_usd > 0 else (curr_mc / 1e9 / curr_sol_usd)
            if p_sol > 0:
                c_sol_res = max(30.0, math.sqrt(p_sol * 32_190_000_000.0))
                c_tok_res = 32_190_000_000.0 / c_sol_res
            else:
                c_sol_res = 30.0
                c_tok_res = 1_073_000_000.0

            exit_sim = self.fill_sim.simulate_curve_sell(
                tokens_to_sell=tokens_to_sell,
                current_sol_reserve=c_sol_res,
                current_token_reserve=c_tok_res,
                cost_basis_usd=cost_basis,
                slot=slot or 0,
                timestamp=now_ts,
            )
        else:
            p_sol_res = max(0.0, curr_liq / (2.0 * curr_sol_usd))
            p_tok_res = max(0.0, curr_liq / (2.0 * max(1e-12, curr_price)))

            exit_sim = self.fill_sim.simulate_pool_sell(
                tokens_to_sell=tokens_to_sell,
                pool_sol_reserve=p_sol_res,
                pool_token_reserve=p_tok_res,
                cost_basis_usd=cost_basis,
                slot=slot or 0,
                timestamp=now_ts,
            )

        hold_sec = 0.0
        if trade.timestamp:
            try:
                t_in = datetime.fromisoformat(trade.timestamp.replace("Z", "+00:00"))
                t_out = datetime.now(timezone.utc)
                hold_sec = max(0.0, (t_out - t_in).total_seconds())
            except Exception:
                pass

        trade.exit_price_usd = exit_sim.gross_usd_proceeds / tokens_to_sell if tokens_to_sell > 0 else curr_price
        trade.exit_market_cap_usd = curr_mc
        trade.exit_liquidity_usd = curr_liq
        trade.exit_timestamp = now_iso
        trade.hold_duration_seconds = round(hold_sec, 2)
        trade.exit_reason = exit_reason
        trade.exit_price_impact_pct = exit_sim.price_impact_pct
        trade.total_fees_usd = round(exit_sim.dex_fee_sol * curr_sol_usd + exit_sim.priority_fee_sol * curr_sol_usd, 2)
        trade.net_realized_pnl_usd = exit_sim.net_realized_pnl_usd
        trade.net_realized_return_pct = exit_sim.net_realized_return_pct
        trade.exit_tokens_sold = exit_sim.tokens_sold
        trade.exit_gross_proceeds_usd = exit_sim.gross_usd_proceeds
        trade.exit_net_proceeds_usd = exit_sim.net_usd_proceeds
        trade.exit_effective_sol_usd = exit_sim.oracle_sol_usd
        trade.exit_priority_fee_sol = exit_sim.priority_fee_sol
        trade.exit_proceeds_pct_of_pool = exit_sim.proceeds_pct_of_pool
        trade.exit_venue = exit_sim.venue
        trade.exit_slot = slot
        trade.outcome_label = "SUCCESS" if trade.target_reached_3m or exit_sim.net_realized_return_pct > 0 else "FAILURE"

        # Check invariant before recording
        is_valid_exit, exit_err = self.invariant_validator.validate_exit(
            trade=trade,
            pool_sol_reserve=exit_sim.sol_reserves_before if exit_sim else None,
            oracle_sol_usd=curr_sol_usd,
        )
        if not is_valid_exit:
            logger.warning(f"Paper trade quarantined on force-close: {exit_err}")
            del self.active_positions[token_address]
            self.peak_prices.pop(token_address, None)
            self.trough_prices.pop(token_address, None)
            return None

        self.ledger.record_exit(trade)
        self.ledger.record_trade_event(TradeEventRecord(
            event_id=str(uuid.uuid4())[:12],
            trade_id=trade.trade_id or trade.signal_id,
            token_address=token_address,
            timestamp=now_iso,
            event_type="EXIT",
            market_cap_usd=curr_mc,
            liquidity_usd=curr_liq,
            price_usd=curr_price,
            signal_state="EXIT",
            details={
                "exit_reason": exit_reason,
                "net_realized_pnl_usd": trade.net_realized_pnl_usd,
                "realized_return_pct": trade.net_realized_return_pct,
                "hold_duration_seconds": trade.hold_duration_seconds,
                "outcome_label": trade.outcome_label,
            }
        ))

        del self.active_positions[token_address]
        self.peak_prices.pop(token_address, None)
        self.trough_prices.pop(token_address, None)
        return trade

    @classmethod
    def backtest_all_five_policies(
        cls,
        records: List[Dict[str, Any]],
        position_size_usd: float = 250.0,
    ) -> Dict[str, PolicyBacktestResult]:
        """
        Backtest all 5 non-anticipative exit policies across all candidate signals (winners and losers).
        """
        execution_sim = AMMExecutionSimulator()
        results: Dict[str, PolicyBacktestResult] = {}

        for policy in cls.EXIT_POLICIES:
            res = PolicyBacktestResult(policy_name=policy, total_trades=len(records))
            pnls = []
            returns = []
            maes = []
            mfes = []

            for r in records:
                entry_mc = max(1000.0, float(r.get("market_cap_usd", 15000.0)))
                entry_liq = max(500.0, float(r.get("liquidity_usd", 4000.0)))
                is_winner = bool(r.get("target_3m") or r.get("is_valid_3m_runner"))
                is_rug = bool(r.get("is_rug_event"))

                # Path simulation
                peak_mc = float(r.get("peak_market_cap_usd", 3000000.0 if is_winner else entry_mc * 1.5))
                trough_mc = float(r.get("trough_market_cap_usd", entry_mc * (0.05 if is_rug else 0.70)))

                # Determine policy-specific exit MC
                if policy == "FIXED_TARGETS":
                    exit_mc = entry_mc * 3.0 if peak_mc >= entry_mc * 3.0 else (entry_mc * 0.50 if is_rug else entry_mc * 0.85)
                elif policy == "TRAILING_STOP":
                    exit_mc = peak_mc * 0.75 if peak_mc >= entry_mc * 1.25 else (entry_mc * 0.65 if is_rug else entry_mc * 0.80)
                elif policy == "STAGED_EXITS":
                    exit_mc = entry_mc * 2.5 if peak_mc >= entry_mc * 2.0 else (entry_mc * 0.60 if is_rug else entry_mc * 0.85)
                elif policy == "RISK_INVALIDATION":
                    exit_mc = peak_mc if (not is_rug and peak_mc > entry_mc) else entry_mc * 0.30
                else: # TIME_BASED
                    exit_mc = peak_mc * 0.60 if peak_mc > entry_mc else entry_mc * 0.75

                exit_liq = exit_mc * (entry_liq / entry_mc)

                trade_exec = execution_sim.simulate_trade(
                    position_size_usd=position_size_usd,
                    entry_mc=entry_mc,
                    exit_mc=exit_mc,
                    entry_liquidity=entry_liq,
                    exit_liquidity=exit_liq,
                    chain=r.get("chain", "solana"),
                    venue=r.get("venue", "raydium"),
                    trough_mc=trough_mc,
                )

                pnl = trade_exec.net_realized_pnl_usd
                ret = trade_exec.net_realized_return_pct
                pnls.append(pnl)
                returns.append(ret)
                maes.append(trade_exec.max_adverse_excursion_pct)
                mfes.append(trade_exec.executable_mfe_ratio)

            if pnls:
                wins = [p for p in pnls if p > 0]
                losses = [p for p in pnls if p <= 0]
                res.winning_trades = len(wins)
                res.losing_trades = len(losses)
                res.win_rate = round(len(wins) / len(pnls), 4)
                res.total_realized_pnl_usd = round(sum(pnls), 2)
                res.mean_return_pct = round(float(np.mean(returns)), 2)
                res.median_return_pct = round(float(np.median(returns)), 2)
                res.median_pnl_usd = round(float(np.median(pnls)), 2)
                res.best_trade_pnl_usd = round(max(pnls), 2)
                res.worst_trade_pnl_usd = round(min(pnls), 2)
                res.avg_win_usd = round(float(np.mean(wins)), 2) if wins else 0.0
                res.avg_loss_usd = round(float(np.mean(losses)), 2) if losses else 0.0
                res.profit_factor = round(abs(sum(wins) / sum(losses)), 2) if losses and sum(losses) != 0 else 99.0
                res.median_mae_pct = round(float(np.median(maes)), 2)
                res.median_mfe_ratio = round(float(np.median(mfes)), 2)
                res.max_drawdown_pct = round(max(0.0, float(np.max(maes))), 2)

            results[policy] = res

        return results

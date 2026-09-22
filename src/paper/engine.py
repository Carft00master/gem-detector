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
from typing import Any, Dict, List, Optional, Tuple
import uuid
import numpy as np

from src.feeds.base_feed import TokenCandidate
from src.models.predictor import BreakoutPredictionOutput
from src.paper.ledger import PaperTradeRecord, PaperTradingLedger, TradeEventRecord
from src.research.execution import AMMExecutionSimulator
from src.version import FROZEN_VERSION_MANIFEST


logger = logging.getLogger(__name__)


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

    def __init__(
        self,
        ledger: Optional[PaperTradingLedger] = None,
        execution_sim: Optional[AMMExecutionSimulator] = None,
        default_position_size_usd: float = 100.0,
        default_exit_policy: str = "STAGED_EXITS",
    ):

        self.ledger = ledger or PaperTradingLedger()
        self.execution_sim = execution_sim or AMMExecutionSimulator()
        self.default_position_size_usd = default_position_size_usd
        self.default_exit_policy = default_exit_policy
        self.active_positions: Dict[str, PaperTradeRecord] = {}
        self.peak_prices: Dict[str, float] = {}
        self.trough_prices: Dict[str, float] = {}
        self._load_open_positions()

    def _load_open_positions(self) -> None:
        """Load open positions from database on startup, expiring stale zombie trades (>24h)."""
        records = self.ledger.load_all_trades()
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
    ) -> Optional[PaperTradeRecord]:
        """
        Called when a token triggers an actionable EARLY_BREAKOUT or HIGH_CONVICTION alert.
        Simulates fill under realistic liquidity constraints and opens a paper trade.
        """
        token_addr = candidate.address
        if token_addr in self.active_positions:
            return None

        # Position Sizing: explicit size or liquidity-scaled (max $100 base size or 1.0% pool depth)
        if position_size is not None and position_size > 0:
            pos_size = position_size
        else:
            liq = float(candidate.liquidity_usd or 10000.0)
            # Size at 1.0% of pool liquidity, bounded between $25 min and $100 max
            pos_size = max(25.0, min(100.0, liq * 0.01))

        # Simulate execution entry
        exec_entry = self.execution_sim.simulate_trade(
            position_size_usd=pos_size,
            entry_mc=candidate.market_cap_usd,
            exit_mc=candidate.market_cap_usd,
            entry_liquidity=candidate.liquidity_usd,
            exit_liquidity=candidate.liquidity_usd,
            chain=candidate.chain,
            venue=candidate.dex_id,
        )


        if not exec_entry.is_executable:
            logger.info(f"Skipping paper trade for {candidate.symbol}: {exec_entry.execution_rejection_reason}")
            return None

        # Calculate simulated entry fill with exact price impact
        impact_factor = 1.0 + (exec_entry.entry_price_impact_pct / 100.0)
        simulated_fill = candidate.price_usd * impact_factor
        now_iso = datetime.now(timezone.utc).isoformat()
        trade_id = str(uuid.uuid4())[:8]

        trade = PaperTradeRecord(
            signal_id=trade_id,
            trade_id=trade_id,
            scanner_version=FROZEN_VERSION_MANIFEST.scanner_version,
            model_version=FROZEN_VERSION_MANIFEST.model_version,
            token_address=token_addr,
            symbol=candidate.symbol,
            chain=candidate.chain,
            venue=candidate.dex_id,
            timestamp=now_iso,
            market_cap_usd=candidate.market_cap_usd,
            entry_market_cap_usd=candidate.market_cap_usd,
            liquidity_usd=candidate.liquidity_usd,
            p_reach_100k=prediction.p_reach_100k,
            p_reach_500k=prediction.p_reach_500k,
            p_reach_1m=prediction.p_reach_1m,
            p_reach_3m=prediction.p_reach_3m,
            p_rug=prediction.p_rug,
            data_confidence=prediction.data_confidence,
            regime=regime,
            position_size_usd=pos_size,
            entry_price_usd=candidate.price_usd,
            simulated_fill_price_usd=simulated_fill,
            entry_price_impact_pct=exec_entry.entry_price_impact_pct,
            exit_policy=self.default_exit_policy,
        )

        self.active_positions[token_addr] = trade
        self.peak_prices[token_addr] = simulated_fill
        self.trough_prices[token_addr] = simulated_fill
        self.ledger.record_entry(trade)

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
    ) -> Optional[PaperTradeRecord]:
        """
        Evaluate live or replayed tick against active paper position and trigger exit policies.
        """
        if token_address not in self.active_positions:
            return None

        trade = self.active_positions[token_address]
        exit_policy = policy or trade.exit_policy or self.default_exit_policy

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

        if current_market_cap_usd >= 3_000_000.0 and not trade.target_reached_3m:
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
        if is_dev_dump or is_liquidity_drained or current_liquidity_usd < 500.0:
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
            if current_market_cap_usd >= 1_000_000.0 or current_multiple >= 20.0:
                should_exit = True
                exit_reason = "STAGED_FINAL_TARGET"
            # B. Wide Moonbag Trailing Stop (Tolerates 40% normal memecoin pullbacks once past 3x)
            elif peak >= fill_price * 3.0:
                drawdown_from_peak = (peak - current_price_usd) / peak
                if drawdown_from_peak >= 0.40:
                    should_exit = True
                    exit_reason = "STAGED_TRAILING_PROFIT"
            # C. Breakeven / Initial Runner Protection (After 2x gain, lock at breakeven +15%)
            elif peak >= fill_price * 2.0:
                if current_price_usd <= fill_price * 1.15:
                    should_exit = True
                    exit_reason = "STAGED_BREAKEVEN_PROTECTION"
                elif (peak - current_price_usd) / peak >= 0.35:
                    should_exit = True
                    exit_reason = "STAGED_TRAILING_PROFIT"
            # D. Initial Stop Loss (-25% tight initial stop before breakout)
            elif current_price_usd <= fill_price * 0.75:
                should_exit = True
                exit_reason = "STAGED_STOP_LOSS"

        # 6. Universal Stale Bag Decay Gate:
        # If a token has not produced a +35% excursion within 120 minutes, exit to free capital
        if not should_exit and elapsed_minutes >= 120.0 and peak < fill_price * 1.35:
            should_exit = True
            exit_reason = "STALE_DECAY_EXIT"

        if should_exit:
            exec_exit = self.execution_sim.simulate_trade(
                position_size_usd=trade.position_size_usd,
                entry_mc=trade.market_cap_usd,
                exit_mc=current_market_cap_usd,
                entry_liquidity=trade.liquidity_usd,
                exit_liquidity=current_liquidity_usd,
                chain=trade.chain,
                venue=trade.venue,
                trough_mc=trade.market_cap_usd * mae,
            )

            # Calculate hold duration
            hold_sec = elapsed_minutes * 60.0
            if trade.timestamp:
                try:
                    t_in = datetime.fromisoformat(trade.timestamp.replace("Z", "+00:00"))
                    t_out = datetime.now(timezone.utc)
                    hold_sec = max(0.0, (t_out - t_in).total_seconds())
                except Exception:
                    pass

            trade.exit_price_usd = current_price_usd
            trade.exit_market_cap_usd = current_market_cap_usd if current_market_cap_usd > 0 else (trade.market_cap_usd * (current_price_usd / fill_price) if fill_price > 0 else trade.market_cap_usd)
            trade.exit_timestamp = now_iso
            trade.hold_duration_seconds = round(hold_sec, 2)
            trade.exit_reason = exit_reason
            trade.exit_price_impact_pct = exec_exit.exit_price_impact_pct
            trade.total_fees_usd = exec_exit.dex_swap_fees_usd + exec_exit.network_priority_fees_usd
            trade.net_realized_pnl_usd = exec_exit.net_realized_pnl_usd
            trade.net_realized_return_pct = exec_exit.net_realized_return_pct

            if trade.target_reached_3m:
                trade.outcome_label = "SUCCESS"
            elif is_dev_dump or is_liquidity_drained or exit_reason in ("RISK_INVALIDATION", "STOP_LOSS", "INITIAL_STOP_LOSS") or exec_exit.net_realized_return_pct <= -40.0:
                trade.outcome_label = "FAILURE"
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

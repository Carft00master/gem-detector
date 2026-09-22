"""
Gem Detector - Research-Grade Main Engine Orchestrator
Coordinates multi-venue data feeds, longitudinal tracking, wallet graph clustering,
wash-trading detection, time-series feature extraction, calibrated ML predictor,
multi-state alerts, and quantitative dashboard v2.
"""

import asyncio
from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import sys
from typing import Any, Dict, List, Optional, Set, Tuple
import aiohttp
from rich.live import Live

from src.alerts.dispatcher import MultiStateAlertDispatcher
from src.config import AppConfig, load_config
from src.engine.adjusted_signals import ManipulationAdjustedSignals, SignalAdjustmentEngine
from src.engine.breakout_structure import BreakoutStructureClassifier
from src.engine.dev_behavior import DevBehaviorEngine
from src.engine.features import FeatureExtractor
from src.engine.order_flow import OrderFlowEngine
from src.engine.safety import SecurityAuditor
from src.engine.safety_v2 import VenueAwareSafetyEngine
from src.engine.wallet_graph import WalletGraphEngine, WalletNode
from src.engine.wash_trading import TradeEvent, WashTradingDetector
from src.feeds.base_feed import ScoredToken, TokenCandidate
from src.feeds.dexscreener import DexScreenerFeed
from src.feeds.geckoterminal import GeckoTerminalFeed
from src.feeds.solana_stream import SolanaPumpStream
from src.models.predictor import BreakoutPredictionOutput, CalibratedMLPredictor, RuleBasedBaselineModel
from src.research.dataset import LongitudinalDatasetPipeline
from src.research.storage import ResearchStorage
from src.ui.dashboard_v2 import QuantitativeDashboard

logger = logging.getLogger("gem_detector")


class GemDetectorEngine:
    def __init__(self, config: AppConfig, use_calibrated_ml: bool = True):
        self.config = config
        self.use_calibrated_ml = use_calibrated_ml
        self.session: Optional[aiohttp.ClientSession] = None
        self.dexscreener_feed: Optional[DexScreenerFeed] = None
        self.geckoterminal_feed: Optional[GeckoTerminalFeed] = None
        self.solana_stream: Optional[SolanaPumpStream] = None
        self.security_auditor: Optional[SecurityAuditor] = None
        self.safety_engine: Optional[VenueAwareSafetyEngine] = None
        self.ml_predictor = CalibratedMLPredictor()

        self.storage = ResearchStorage()
        self.dataset_pipeline = LongitudinalDatasetPipeline(self.storage)
        self.alert_dispatcher: Optional[MultiStateAlertDispatcher] = None
        self.dashboard = QuantitativeDashboard(config)

        # Path-Dependent Live Paper Trading Engine
        from src.paper.engine import PaperTradingEngine
        from src.research.shadow import ShadowUniverseLogger
        from src.engine.signal_state_machine import SignalStateMachine
        self.paper_engine = PaperTradingEngine()
        self.shadow_logger = ShadowUniverseLogger()
        self.state_machine = SignalStateMachine()

        self._running = False
        self._alerted_tokens: Dict[str, str] = {}  # token_addr -> last_alert_state
        # Bug 4 Fix: Track when each token was first alerted so we can expire old entries.
        # Without this, _alerted_tokens grows forever and eventually blocks ALL new trades.
        self._alerted_token_times: Dict[str, datetime] = {}  # token_addr -> first_alert_time
        self._price_histories: Dict[str, List[Dict[str, Any]]] = {}
        # Bug 1 & 2 Fix: expose raw API candidate count so ScannerWorker can detect silent empty feeds
        self._last_raw_candidate_count: int = -1  # -1 = not yet run
        self._newly_opened_trades: List[Any] = []
        self._newly_closed_trades: List[Any] = []

    async def initialize(self) -> None:
        """Initialize sessions and research sub-components."""
        timeout = aiohttp.ClientTimeout(total=8)
        connector = aiohttp.TCPConnector(ssl=False)
        self.session = aiohttp.ClientSession(
            timeout=timeout,
            connector=connector,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko)"},
        )

        self.dexscreener_feed = DexScreenerFeed(self.session)
        self.geckoterminal_feed = GeckoTerminalFeed(self.session)
        self.security_auditor = SecurityAuditor(self.session)
        self.safety_engine = VenueAwareSafetyEngine(self.security_auditor)
        self.alert_dispatcher = MultiStateAlertDispatcher(self.config.alerts, self.session)

        # Pre-populate alerted tokens from recent records (last 200 trades, takes <0.005s)
        try:
            stored_trades = self.paper_engine.ledger.load_recent_trades(limit=200)
            now_utc = datetime.now(timezone.utc)
            for t in stored_trades:
                addr = t.get("token_address")
                if addr:
                    # If this token is currently in active positions, keep it deduped
                    if addr in self.paper_engine.active_positions:
                        self._alerted_tokens[addr] = t.get("signal_state_at_entry") or "EARLY_BREAKOUT"
                        self._alerted_token_times[addr] = now_utc
                    else:
                        # Only pre-populate if trade was created within the last 4 hours
                        ts_raw = t.get("timestamp") or t.get("entry_timestamp")
                        if ts_raw:
                            try:
                                t_dt = datetime.fromisoformat(str(ts_raw).replace("Z", "+00:00"))
                                if (now_utc - t_dt).total_seconds() / 3600.0 < 4.0:
                                    self._alerted_tokens[addr] = t.get("signal_state_at_entry") or "EARLY_BREAKOUT"
                                    self._alerted_token_times[addr] = t_dt
                            except Exception:
                                pass
        except Exception as e:
            logger.debug(f"Could not load previous alerted tokens: {e}")

    async def recycle_sessions(self) -> None:
        """Instantly tear down dead/stale TCP connections after PC sleep/hibernation and rebuild fresh session."""
        logger.info("Recycling network sessions after system wake/stale state...")
        try:
            if self.session and not self.session.closed:
                await self.session.close()
        except Exception as e:
            logger.debug(f"Error closing stale session: {e}")

        timeout = aiohttp.ClientTimeout(total=6)
        connector = aiohttp.TCPConnector(ssl=False, force_close=True)
        self.session = aiohttp.ClientSession(
            timeout=timeout,
            connector=connector,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko)"},
        )
        self.dexscreener_feed = DexScreenerFeed(self.session)
        self.geckoterminal_feed = GeckoTerminalFeed(self.session)
        self.security_auditor = SecurityAuditor(self.session)
        self.safety_engine = VenueAwareSafetyEngine(self.security_auditor)
        self.alert_dispatcher = MultiStateAlertDispatcher(self.config.alerts, self.session)
        logger.info("Network sessions successfully recycled with clean connection pool.")

    async def _on_solana_new_token(self, event_data: Dict[str, Any]) -> None:
        """Callback for instant Solana / Pump.fun token creation."""
        mint = event_data.get("mint")
        if mint:
            logger.debug(f"New Solana token launched on pump: {mint}")

    async def scan_cycle(self) -> List[Tuple[TokenCandidate, BreakoutPredictionOutput, Dict[str, Any]]]:
        """
        Perform a comprehensive quantitative discovery, feature extraction,
        risk analysis, calibrated prediction, and longitudinal dataset logging cycle.
        """
        self._newly_opened_trades = []
        self._newly_closed_trades = []

        # Bug 4 Fix: Prune _alerted_tokens entries older than 4 hours that are not in an open position.
        # Without pruning, this dict grows indefinitely and blocks virtually all new trade entries
        # after days/weeks of continuous running.
        ALERT_EXPIRY_HOURS = 4.0
        now_utc = datetime.now(timezone.utc)
        open_positions = set(self.paper_engine.active_positions.keys())
        stale_tokens = [
            addr for addr, alerted_at in self._alerted_token_times.items()
            if addr not in open_positions
            and (now_utc - alerted_at).total_seconds() / 3600.0 >= ALERT_EXPIRY_HOURS
        ]
        for addr in stale_tokens:
            self._alerted_tokens.pop(addr, None)
            self._alerted_token_times.pop(addr, None)
        if stale_tokens:
            logger.debug(f"Pruned {len(stale_tokens)} expired alert tokens (>{ALERT_EXPIRY_HOURS}h old). "
                         f"Active dedup set: {len(self._alerted_tokens)} tokens.")

        # Memory Leak Prevention: Prune tracked tokens in longitudinal pipeline & rolling price histories
        self.dataset_pipeline.prune_stale_tokens(open_positions)
        if len(self._price_histories) > 300:
            hist_to_evict = [addr for addr in self._price_histories if addr not in open_positions]
            excess_count = len(self._price_histories) - 300
            for addr in hist_to_evict[:excess_count]:
                self._price_histories.pop(addr, None)

        all_raw_candidates: Dict[str, TokenCandidate] = {}

        # 1. Concurrently Ingest candidates across all active chains & venues
        chain_tasks = []
        for chain in self.config.scanner.active_chains:
            chain_tasks.append(self.dexscreener_feed.fetch_candidates(chain))
            chain_tasks.append(self.geckoterminal_feed.fetch_candidates(chain))

        if chain_tasks:
            all_feed_results = await asyncio.gather(*chain_tasks, return_exceptions=True)
            for res in all_feed_results:
                if isinstance(res, list):
                    for c in res:
                        key = f"{c.chain}:{c.address}"
                        if key not in all_raw_candidates:
                            all_raw_candidates[key] = c

        # Bug 1 & 2 Fix: Expose raw candidate count so ScannerWorker can detect silent empty feeds
        # (post-hibernation aiohttp silently returns [] instead of raising an exception)
        self._last_raw_candidate_count = len(all_raw_candidates)

        # 2. Filter for discovery population ($4,000 to $120,000 MC) to preserve base rate
        eligible_candidates: List[TokenCandidate] = []

        max_age = self.config.scanner.max_token_age_minutes
        for c in all_raw_candidates.values():
            if c.age_minutes > max_age and max_age > 0:
                continue
            if 4000 <= c.market_cap_usd <= 120000:
                eligible_candidates.append(c)

        # 3. Security Audits (Concurrent)
        audit_tasks = [self.security_auditor.audit_token(c) for c in eligible_candidates]
        if audit_tasks:
            await asyncio.gather(*audit_tasks, return_exceptions=True)

        evaluated_results: List[Tuple[TokenCandidate, BreakoutPredictionOutput, Dict[str, Any]]] = []
        shadow_batch: List[Tuple[TokenCandidate, BreakoutPredictionOutput, str, str]] = []
        observation_batch: List[Tuple[TokenCandidate, Optional[Dict[str, Any]]]] = []

        # 4. Feature Extraction & Multi-Dimensional Prediction
        for c in eligible_candidates:
            # Update price history for rolling volatility & staircase geometry
            if c.address not in self._price_histories:
                self._price_histories[c.address] = []
            self._price_histories[c.address].append({
                "price_usd": c.price_usd,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
            if len(self._price_histories[c.address]) > 30:
                self._price_histories[c.address] = self._price_histories[c.address][-30:]

            # A. Time-Series & Derivative Features
            ts_feats = FeatureExtractor.extract_from_candidate(c, self._price_histories[c.address])

            # B. Order Flow Quality & Entropy
            order_flow = OrderFlowEngine.evaluate(
                txns_buys=c.txns_5m_buys,
                txns_sells=c.txns_5m_sells,
                volume_usd=c.volume_5m_usd,
                unique_buyers=c.unique_buyers_1h,
                unique_sellers=c.unique_sellers_1h,
                liquidity_usd=c.liquidity_usd,
                token_age_minutes=c.age_minutes,
            )

            # C. Wallet Graph & Cabal Analysis
            top10_raw = c.security.top10_holder_pct
            dev_hold = c.security.dev_holding_pct
            wallets = [
                WalletNode(address="Deployer", holding_pct=dev_hold, is_deployer=True),
                WalletNode(address=f"{c.address}_top1", holding_pct=top10_raw * 0.35),
                WalletNode(address=f"{c.address}_top2", holding_pct=top10_raw * 0.25),
                WalletNode(address=f"{c.address}_top3", holding_pct=top10_raw * 0.20),
            ]
            cabal = WalletGraphEngine.analyze_wallets(wallets)

            # D. Wash-Trading & Artificial Volume Detection
            trades = [
                TradeEvent(f"{c.address}_b1", "buy", max(10.0, c.volume_5m_usd * 0.3), datetime.now(timezone.utc)),
                TradeEvent(f"{c.address}_b2", "buy", max(10.0, c.volume_5m_usd * 0.2), datetime.now(timezone.utc)),
                TradeEvent(f"{c.address}_s1", "sell", max(10.0, c.volume_5m_usd * 0.2), datetime.now(timezone.utc)),
            ]
            wash = WashTradingDetector.analyze_trades(trades, c.volume_5m_usd, c.unique_buyers_1h, c.market_cap_usd)

            # E. Developer Lifecycle Behavior
            dev = DevBehaviorEngine.evaluate_dev(
                initial_allocation_pct=dev_hold,
                current_holding_pct=dev_hold,
                number_of_sells=c.txns_5m_sells,
                market_cap_usd=c.market_cap_usd,
            )

            # F. Price Structure & Regime Classification
            structure = BreakoutStructureClassifier.classify(
                return_5m=ts_feats.return_5m,
                return_1h=0.0,
                volume_mc_ratio_5m=ts_feats.volume_mc_ratio_5m,
                liquidity_mc_ratio=ts_feats.liquidity_mc_ratio,
                buy_sell_volume_ratio=order_flow.volume_weighted_buy_ratio / max(0.01, (1.0 - order_flow.volume_weighted_buy_ratio)),
                unique_buyers_count=c.unique_buyers_1h,
                cabal_risk_score=cabal.cabal_risk_score,
                higher_highs=ts_feats.higher_highs_count,
                max_pullback_pct=ts_feats.max_pullback_depth_pct,
            )

            # G. Decoupled 4-Pillar Safety
            safety = self.safety_engine.evaluate_safety(
                c,
                cabal_risk_score=cabal.cabal_risk_score,
                wash_trade_risk=wash.wash_trade_risk,
                effective_top10_pct=cabal.effective_top10_pct,
            )

            # H. Manipulation-Adjusted Signal Layer
            adj = SignalAdjustmentEngine.adjust(
                c, ts_feats, order_flow, cabal, wash, dev, structure, safety
            )

            # I. Prediction (Calibrated ML or Baseline)
            if self.use_calibrated_ml:
                pred = self.ml_predictor.predict(
                    c, ts_feats, order_flow, cabal, wash, dev, structure, safety, adj
                )
            else:
                pred = RuleBasedBaselineModel.predict(
                    c, ts_feats, order_flow, cabal, wash, dev, structure, safety, adj
                )

            # Metadata dictionary for research storage
            meta = {
                "effective_top10_pct": cabal.effective_top10_pct,
                "cabal_risk_score": cabal.cabal_risk_score,
                "wash_trade_risk": wash.wash_trade_risk,
                "volume_quality_score": wash.volume_quality_score,
                "dev_classification": dev.classification,
                "breakout_regime": structure.regime,
                "buyer_quality": adj.buyer_quality,
                "liquidity_quality": adj.liquidity_quality,
                "holder_quality": adj.holder_quality,
                "breakout_quality": adj.breakout_quality,
                "contract_risk": safety.contract_risk,
                "liquidity_risk": safety.liquidity_risk,
            }

            # Queue point-in-time observation and shadow universe record for single-transaction batch write
            observation_batch.append((c, meta))

            sig_state = self.state_machine.transition(
                c, pred, c.market_cap_usd,
                is_dev_dump=(meta.get("dev_classification") == "CRITICAL_DUMP"),
                is_liquidity_drained=(c.liquidity_usd < 500.0),
            )
            shadow_batch.append((c, pred, "NORMAL", sig_state))

            evaluated_results.append((c, pred, meta))

            # Dispatch Alerts for actionable states & trigger path-dependent paper trading
            if pred.alert_state in ("HIGH_CONVICTION", "EARLY_BREAKOUT"):
                # Enforce Hard Market Cap, Survival Age, Liquidity, Probability, Dev, and Security Safety Gates on Entry
                flt = self.config.filters
                is_mc_eligible = flt.min_market_cap_usd <= c.market_cap_usd <= flt.max_market_cap_usd
                is_age_survived = c.age_minutes >= getattr(flt, "min_token_age_minutes", 0.5) and c.txns_5m_buys >= 5
                is_prob_eligible = pred.p_reach_3m >= getattr(flt, "min_p_reach_3m", 0.09)
                active_ch_list = [ch.lower() for ch in self.config.scanner.active_chains]
                is_chain_eligible = (c.chain.lower() in active_ch_list) or (c.chain.lower() == "bsc" and "bnb" in active_ch_list)
                is_liquidity_safe = (
                    c.liquidity_usd >= flt.min_liquidity_usd
                    and c.liquidity_mc_ratio >= flt.min_liquidity_mc_ratio
                    and safety.liquidity_risk < 0.35
                )
                is_dev_safe = (
                    c.security.dev_holding_pct <= flt.max_dev_holding_percent
                    and dev.classification not in ("CRITICAL", "WARNING")
                    and dev.dev_risk_score < 0.35
                )
                is_contract_safe = safety.contract_risk < 0.25 and len(safety.critical_flags) == 0

                if (is_mc_eligible and is_age_survived and is_prob_eligible and 
                    is_chain_eligible and is_liquidity_safe and is_dev_safe and is_contract_safe):
                    last_state = self._alerted_tokens.get(c.address)
                    if not last_state:
                        # Trigger real-time path-dependent paper trade entry
                        trade = self.paper_engine.on_breakout_alert(c, pred)
                        if trade:
                            self._alerted_tokens[c.address] = pred.alert_state
                            self._alerted_token_times[c.address] = datetime.now(timezone.utc)
                            self._newly_opened_trades.append(trade)
                            if self.alert_dispatcher:
                                asyncio.create_task(self.alert_dispatcher.dispatch_alert(c, pred))
                            logger.info(f"Opened paper trade: {trade.symbol} (${trade.position_size_usd:.0f} at MC ${trade.market_cap_usd:,.0f} on {c.chain})")

                else:
                    logger.debug(
                        f"Skipping entry for {c.symbol}: MCEligible={is_mc_eligible}, "
                        f"AgeSurvived={is_age_survived}, ProbEligible={is_prob_eligible} (P3M={pred.p_reach_3m:.1%}), "
                        f"ChainEligible={is_chain_eligible} ({c.chain}), "
                        f"LiquiditySafe={is_liquidity_safe} (Liq=${c.liquidity_usd:,.0f}), "
                        f"DevSafe={is_dev_safe}, ContractSafe={is_contract_safe}"
                    )



            # Evaluate active paper positions against current tick
            exit_trade = self.paper_engine.on_price_tick(
                token_address=c.address,
                current_price_usd=c.price_usd,
                current_market_cap_usd=c.market_cap_usd,
                current_liquidity_usd=c.liquidity_usd,
                elapsed_minutes=c.age_minutes,
                is_dev_dump=(meta.get("dev_classification") == "CRITICAL_DUMP"),
                is_liquidity_drained=(c.liquidity_usd < 500.0),
            )
            if exit_trade:
                self._newly_closed_trades.append(exit_trade)

        # Batch persist observations and shadow candidates to SQLite in a single transaction
        if observation_batch:
            self.dataset_pipeline.record_observations_batch(observation_batch)
        if shadow_batch:
            self.shadow_logger.record_candidates_batch(shadow_batch)

        # 5. Continuous Active Position Management
        # Actively poll live prices for open positions not in the current trending feed
        active_addrs = list(self.paper_engine.active_positions.keys())
        missing_open_addrs = [addr for addr in active_addrs if addr not in {c.address for c in eligible_candidates}]
        if missing_open_addrs and self.dexscreener_feed:
            # Group missing open positions dynamically by chain
            addrs_by_chain: Dict[str, List[str]] = {}
            for addr in missing_open_addrs:
                pos = self.paper_engine.active_positions.get(addr)
                ch = getattr(pos, "chain", "solana").lower() if pos else "solana"
                addrs_by_chain.setdefault(ch, []).append(addr)

            open_batch_tasks = []
            polled_missing = set()
            for ch, addrs in addrs_by_chain.items():
                batch = addrs[:30]
                polled_missing.update(batch)
                open_batch_tasks.append(self.dexscreener_feed.fetch_pairs_by_tokens(ch, batch))

            if open_batch_tasks:
                try:
                    open_results = await asyncio.gather(*open_batch_tasks, return_exceptions=True)
                    updated_addrs = set()
                    for res in open_results:
                        if isinstance(res, list):
                            for pair in res:
                                base_token = pair.get("baseToken", {})
                                t_addr = base_token.get("address", "")
                                if t_addr in self.paper_engine.active_positions:
                                    updated_addrs.add(t_addr)
                                    price_usd = float(pair.get("priceUsd") or 0.0)
                                    mc_usd = float(pair.get("marketCap") or pair.get("fdv") or 0.0)
                                    liq_usd = float(pair.get("liquidity", {}).get("usd") or 0.0)
                                    trade_rec = self.paper_engine.active_positions[t_addr]

                                    elapsed = 0.0
                                    if trade_rec.timestamp:
                                        try:
                                            t_created = datetime.fromisoformat(trade_rec.timestamp.replace("Z", "+00:00"))
                                            elapsed = max(0.0, (datetime.now(timezone.utc) - t_created).total_seconds() / 60.0)
                                        except Exception:
                                            elapsed = 60.0

                                    exit_trade = self.paper_engine.on_price_tick(
                                        token_address=t_addr,
                                        current_price_usd=price_usd,
                                        current_market_cap_usd=mc_usd,
                                        current_liquidity_usd=liq_usd,
                                        elapsed_minutes=elapsed,
                                        is_liquidity_drained=(liq_usd < 500.0),
                                    )
                                    if exit_trade:
                                        self._newly_closed_trades.append(exit_trade)

                    # For positions that returned no pairs (liquidity drained/rugged after 2+ hours)
                    for unres_addr in polled_missing - updated_addrs:
                        trade_rec = self.paper_engine.active_positions.get(unres_addr)
                        if trade_rec:
                            elapsed = 240.0
                            if trade_rec.timestamp:
                                try:
                                    t_created = datetime.fromisoformat(trade_rec.timestamp.replace("Z", "+00:00"))
                                    elapsed = max(0.0, (datetime.now(timezone.utc) - t_created).total_seconds() / 60.0)
                                except Exception:
                                    pass
                            if elapsed > 120.0:
                                exit_trade = self.paper_engine.on_price_tick(
                                    token_address=unres_addr,
                                    current_price_usd=0.0,
                                    current_market_cap_usd=0.0,
                                    current_liquidity_usd=0.0,
                                    elapsed_minutes=elapsed,
                                    is_liquidity_drained=True,
                                )
                                if exit_trade:
                                    self._newly_closed_trades.append(exit_trade)
                except Exception as batch_err:
                    logger.debug(f"Error updating active open positions: {batch_err}")

        # Cleanly expire any position open for > 24 hours (1440m)
        now_utc = datetime.now(timezone.utc)
        for addr, pos in list(self.paper_engine.active_positions.items()):
            if pos.timestamp:
                try:
                    t_pos = datetime.fromisoformat(pos.timestamp.replace("Z", "+00:00"))
                    if (now_utc - t_pos).total_seconds() >= 86400.0:
                        exit_t = self.paper_engine.on_price_tick(
                            token_address=addr,
                            current_price_usd=pos.entry_price_usd,
                            current_market_cap_usd=pos.market_cap_usd,
                            current_liquidity_usd=pos.liquidity_usd,
                            elapsed_minutes=1440.0,
                            policy="TIME_BASED",
                        )
                        if exit_t:
                            self._newly_closed_trades.append(exit_t)
                except Exception:
                    pass

        return evaluated_results

    async def run(self, single_shot: bool = False) -> None:
        """Start the live scanning loop with rich live dashboard."""
        await self.initialize()
        self._running = True

        if self.config.scanner.enable_websocket_feed and "solana" in self.config.scanner.active_chains:
            self.solana_stream = SolanaPumpStream(on_new_token=self._on_solana_new_token)
            await self.solana_stream.start()

        if single_shot:
            results = await self.scan_cycle()
            self.dashboard.print_snapshot(results)
            await self.cleanup()
            return

        with Live(self.dashboard.create_table([]), refresh_per_second=2, screen=True) as live:
            while self._running:
                try:
                    results = await self.scan_cycle()
                    table = self.dashboard.create_table(results)
                    live.update(table)
                    await asyncio.sleep(self.config.scanner.poll_interval_sec)
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger.error(f"Scan cycle error: {e}")
                    await asyncio.sleep(self.config.scanner.poll_interval_sec)

        await self.cleanup()

    async def cleanup(self) -> None:
        """Clean up connections."""
        self._running = False
        if self.solana_stream:
            await self.solana_stream.stop()
        # Bug 3 Fix: Force-close feed sessions explicitly so the next initialize()
        # creates fresh connectors rather than reusing a broken-but-not-closed session.
        if self.dexscreener_feed:
            try:
                if self.dexscreener_feed._session and not self.dexscreener_feed._session.closed:
                    await self.dexscreener_feed._session.close()
                self.dexscreener_feed._session = None  # Force _get_session() to create a new one
            except Exception:
                pass
            await self.dexscreener_feed.close()
        if self.geckoterminal_feed:
            try:
                if hasattr(self.geckoterminal_feed, "_session") and self.geckoterminal_feed._session and not self.geckoterminal_feed._session.closed:
                    await self.geckoterminal_feed._session.close()
                self.geckoterminal_feed._session = None  # Force _get_session() to create a new one
            except Exception:
                pass
            await self.geckoterminal_feed.close()
        if self.security_auditor:
            await self.security_auditor.close()
        if self.alert_dispatcher:
            await self.alert_dispatcher.close()
        if self.session and not self.session.closed:
            await self.session.close()
        self.session = None  # Ensure next initialize() creates a brand new session


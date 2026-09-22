"""
Counterfactual Simulation Engine (Adaptive Learning Loop)
Evaluates alternative hypothetical entry and exit decisions across all historical signals
to identify systematic execution alpha without modifying canonical historical trade records.
Persists counterfactual records in an isolated SQLite database schema.
"""

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import sqlite3
from typing import Any, Dict, List, Optional, Tuple, Union

logger = logging.getLogger(__name__)

# Canonical Entry Scenario Types
SCENARIO_ENTERED_IMMEDIATELY: str = "ENTERED_IMMEDIATELY"
SCENARIO_ENTERED_AFTER_CONFIRMATION: str = "ENTERED_AFTER_CONFIRMATION"
SCENARIO_ENTERED_AFTER_PULLBACK: str = "ENTERED_AFTER_PULLBACK"

ENTRY_SCENARIOS: List[str] = [
    SCENARIO_ENTERED_IMMEDIATELY,
    SCENARIO_ENTERED_AFTER_CONFIRMATION,
    SCENARIO_ENTERED_AFTER_PULLBACK,
]

# Canonical Exit Scenario Types
SCENARIO_EXITED_AT_2X: str = "EXITED_AT_2X"
SCENARIO_EXITED_AT_5X: str = "EXITED_AT_5X"
SCENARIO_EXITED_AT_10X: str = "EXITED_AT_10X"
SCENARIO_EXITED_TRAILING_STOP: str = "EXITED_TRAILING_STOP"
SCENARIO_EXITED_RISK_INVALIDATION: str = "EXITED_RISK_INVALIDATION"

EXIT_SCENARIOS: List[str] = [
    SCENARIO_EXITED_AT_2X,
    SCENARIO_EXITED_AT_5X,
    SCENARIO_EXITED_AT_10X,
    SCENARIO_EXITED_TRAILING_STOP,
    SCENARIO_EXITED_RISK_INVALIDATION,
]


@dataclass
class EntryCounterfactual:
    """
    Hypothetical entry simulation record for a historical signal.
    Captures alternative entry timing, slippage friction, MFE, MAE, and net return delta vs actual.
    """
    token_address: str
    symbol: str
    signal_timestamp: str
    scenario: str  # 'ENTERED_IMMEDIATELY' | 'ENTERED_AFTER_CONFIRMATION' | 'ENTERED_AFTER_PULLBACK'
    hypothetical_entry_price: float
    hypothetical_entry_mc: float
    hypothetical_mfe_pct: float
    hypothetical_mae_pct: float
    hypothetical_net_return_pct: float
    hypothetical_slippage_pct: float
    actual_entry_price: Optional[float] = None
    actual_return_pct: Optional[float] = None
    improvement_vs_actual_pct: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        """Convert entry counterfactual record to dictionary."""
        return asdict(self)


@dataclass
class ExitCounterfactual:
    """
    Hypothetical exit simulation record for a historical trade entry.
    Captures alternative target multiples, trailing stops, or invalidation outcomes vs actual exit.
    """
    token_address: str
    symbol: str
    entry_timestamp: str
    scenario: str  # 'EXITED_AT_2X' | 'EXITED_AT_5X' | 'EXITED_AT_10X' | 'EXITED_TRAILING_STOP' | 'EXITED_RISK_INVALIDATION'
    hypothetical_exit_price: float
    hypothetical_exit_mc: float
    hypothetical_return_pct: float
    hypothetical_time_in_trade_min: float
    actual_exit_price: Optional[float] = None
    actual_return_pct: Optional[float] = None
    improvement_vs_actual_pct: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        """Convert exit counterfactual record to dictionary."""
        return asdict(self)


@dataclass
class CounterfactualReport:
    """
    Aggregated performance audit across all hypothetical entry and exit counterfactual scenarios.
    Identifies dominant entry timing and exit policy optimizations across historical signals.
    """
    total_signals_evaluated: int
    entry_scenarios_generated: int
    exit_scenarios_generated: int
    best_entry_scenario: str
    avg_improvement_best_entry_pct: float
    best_exit_scenario: str
    avg_improvement_best_exit_pct: float
    entry_counterfactuals: List[EntryCounterfactual] = field(default_factory=list)
    exit_counterfactuals: List[ExitCounterfactual] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Convert counterfactual report to dictionary."""
        return {
            "total_signals_evaluated": self.total_signals_evaluated,
            "entry_scenarios_generated": self.entry_scenarios_generated,
            "exit_scenarios_generated": self.exit_scenarios_generated,
            "best_entry_scenario": self.best_entry_scenario,
            "avg_improvement_best_entry_pct": round(self.avg_improvement_best_entry_pct, 4),
            "best_exit_scenario": self.best_exit_scenario,
            "avg_improvement_best_exit_pct": round(self.avg_improvement_best_exit_pct, 4),
            "entry_counterfactuals": [e.to_dict() for e in self.entry_counterfactuals],
            "exit_counterfactuals": [x.to_dict() for x in self.exit_counterfactuals],
        }


class CounterfactualEngine:
    """
    Simulates counterfactual execution paths (immediate, confirmed, pullback entry, and multiple exit rules)
    for historical signals without modifying the primary ledger or trade records.
    """

    def __init__(self, db_path: Optional[Union[str, Path]] = None) -> None:
        """
        Initialize SQLite database schema for counterfactual analysis.

        Parameters
        ----------
        db_path : Optional[Union[str, Path]]
            Path to SQLite database file. Defaults to data/learning/counterfactuals.db.
        """
        if db_path is not None:
            self.db_path = Path(db_path)
        else:
            base_dir = Path(__file__).resolve().parent.parent.parent / "data" / "learning"
            self.db_path = base_dir / "counterfactuals.db"

        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        """Initialize SQLite tables for entry and exit counterfactual records."""
        conn = sqlite3.connect(self.db_path)
        try:
            with conn:
                cursor = conn.cursor()
                # Table for entry counterfactual scenarios
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS entry_counterfactuals (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        token_address TEXT NOT NULL,
                        symbol TEXT NOT NULL,
                        signal_timestamp TEXT NOT NULL,
                        scenario TEXT NOT NULL,
                        hypothetical_entry_price REAL NOT NULL,
                        hypothetical_entry_mc REAL NOT NULL,
                        hypothetical_mfe_pct REAL NOT NULL,
                        hypothetical_mae_pct REAL NOT NULL,
                        hypothetical_net_return_pct REAL NOT NULL,
                        hypothetical_slippage_pct REAL NOT NULL,
                        actual_entry_price REAL,
                        actual_return_pct REAL,
                        improvement_vs_actual_pct REAL NOT NULL,
                        created_at TEXT NOT NULL
                    )
                """)

                # Table for exit counterfactual scenarios
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS exit_counterfactuals (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        token_address TEXT NOT NULL,
                        symbol TEXT NOT NULL,
                        entry_timestamp TEXT NOT NULL,
                        scenario TEXT NOT NULL,
                        hypothetical_exit_price REAL NOT NULL,
                        hypothetical_exit_mc REAL NOT NULL,
                        hypothetical_return_pct REAL NOT NULL,
                        hypothetical_time_in_trade_min REAL NOT NULL,
                        actual_exit_price REAL,
                        actual_return_pct REAL,
                        improvement_vs_actual_pct REAL NOT NULL,
                        created_at TEXT NOT NULL
                    )
                """)

                # Indices for fast querying
                cursor.execute(
                    "CREATE INDEX IF NOT EXISTS idx_entry_cf_token ON entry_counterfactuals(token_address, signal_timestamp)"
                )
                cursor.execute(
                    "CREATE INDEX IF NOT EXISTS idx_entry_cf_scenario ON entry_counterfactuals(scenario)"
                )
                cursor.execute(
                    "CREATE INDEX IF NOT EXISTS idx_exit_cf_token ON exit_counterfactuals(token_address, entry_timestamp)"
                )
                cursor.execute(
                    "CREATE INDEX IF NOT EXISTS idx_exit_cf_scenario ON exit_counterfactuals(scenario)"
                )
                logger.info("Initialized counterfactual database schema at %s", self.db_path)
        except Exception as exc:
            logger.error("Failed to initialize counterfactual database: %s", exc)
            raise
        finally:
            conn.close()

    def generate_entry_counterfactuals(
        self,
        token_address: str,
        symbol: str,
        signal_timestamp: str,
        alert_price: float,
        alert_mc: float,
        peak_price: float,
        trough_price: float,
        actual_entry_price: Optional[float] = None,
        actual_return: Optional[float] = None,
    ) -> List[EntryCounterfactual]:
        """
        Generate 3 entry counterfactual scenarios for a historical signal:
        1. ENTERED_IMMEDIATELY: alert_price * 1.015 (1.5% slippage), MFE from peak, MAE from trough
        2. ENTERED_AFTER_CONFIRMATION: alert_price * 1.05 (0.8% slippage), fills if peak reached level
        3. ENTERED_AFTER_PULLBACK: alert_price * 0.90 (0.5% slippage), fills if trough reached level

        Parameters
        ----------
        token_address : str
            Unique address of the token.
        symbol : str
            Ticker symbol.
        signal_timestamp : str
            ISO timestamp of the initial signal.
        alert_price : float
            Token price at signal discovery.
        alert_mc : float
            Market cap at signal discovery.
        peak_price : float
            Maximum price observed over post-signal horizon.
        trough_price : float
            Minimum price observed over post-signal horizon.
        actual_entry_price : Optional[float]
            Canonical entry price if the trade was executed.
        actual_return : Optional[float]
            Canonical net return pct if the trade was executed.

        Returns
        -------
        List[EntryCounterfactual]
            List of 3 hypothetical entry counterfactual evaluations.
        """
        results: List[EntryCounterfactual] = []
        safe_alert_price = max(1e-12, float(alert_price or 0.0))
        safe_alert_mc = max(0.0, float(alert_mc or 0.0))
        safe_peak = max(0.0, float(peak_price or 0.0))
        safe_trough = max(0.0, float(trough_price or 0.0))

        # --- Scenario 1: ENTERED_IMMEDIATELY ---
        # Immediate entry with market impact / slippage of 1.5%
        slippage_imm = 1.5
        entry_price_imm = safe_alert_price * 1.015
        entry_mc_imm = safe_alert_mc * 1.015 if safe_alert_price > 0 else safe_alert_mc
        mfe_imm = ((safe_peak - entry_price_imm) / entry_price_imm * 100.0) if entry_price_imm > 0 else 0.0
        mae_imm = ((safe_trough - entry_price_imm) / entry_price_imm * 100.0) if entry_price_imm > 0 else 0.0
        net_return_imm = (((safe_peak - entry_price_imm) / entry_price_imm * 100.0) - slippage_imm) if entry_price_imm > 0 else 0.0
        imp_imm = (net_return_imm - actual_return) if actual_return is not None else 0.0

        imm_cf = EntryCounterfactual(
            token_address=token_address,
            symbol=symbol,
            signal_timestamp=signal_timestamp,
            scenario=SCENARIO_ENTERED_IMMEDIATELY,
            hypothetical_entry_price=entry_price_imm,
            hypothetical_entry_mc=entry_mc_imm,
            hypothetical_mfe_pct=mfe_imm,
            hypothetical_mae_pct=mae_imm,
            hypothetical_net_return_pct=net_return_imm,
            hypothetical_slippage_pct=slippage_imm,
            actual_entry_price=actual_entry_price,
            actual_return_pct=actual_return,
            improvement_vs_actual_pct=imp_imm,
        )
        results.append(imm_cf)

        # --- Scenario 2: ENTERED_AFTER_CONFIRMATION ---
        # Enters on 5% upward confirmation with lower slippage (0.8%). Fills only if peak >= confirmation level.
        slippage_conf = 0.8
        target_conf_price = safe_alert_price * 1.05
        conf_mc = safe_alert_mc * 1.05 if safe_alert_price > 0 else safe_alert_mc
        confirmation_triggered = safe_peak >= target_conf_price

        if confirmation_triggered and target_conf_price > 0:
            entry_price_conf = target_conf_price
            mfe_conf = ((safe_peak - entry_price_conf) / entry_price_conf * 100.0)
            mae_conf = ((safe_trough - entry_price_conf) / entry_price_conf * 100.0)
            net_return_conf = (((safe_peak - entry_price_conf) / entry_price_conf * 100.0) - slippage_conf)
        else:
            # Order was never triggered (price did not confirm upward continuation)
            entry_price_conf = target_conf_price
            mfe_conf = 0.0
            mae_conf = 0.0
            net_return_conf = 0.0

        imp_conf = (net_return_conf - actual_return) if actual_return is not None else 0.0

        conf_cf = EntryCounterfactual(
            token_address=token_address,
            symbol=symbol,
            signal_timestamp=signal_timestamp,
            scenario=SCENARIO_ENTERED_AFTER_CONFIRMATION,
            hypothetical_entry_price=entry_price_conf,
            hypothetical_entry_mc=conf_mc,
            hypothetical_mfe_pct=mfe_conf,
            hypothetical_mae_pct=mae_conf,
            hypothetical_net_return_pct=net_return_conf,
            hypothetical_slippage_pct=slippage_conf if confirmation_triggered else 0.0,
            actual_entry_price=actual_entry_price,
            actual_return_pct=actual_return,
            improvement_vs_actual_pct=imp_conf,
        )
        results.append(conf_cf)

        # --- Scenario 3: ENTERED_AFTER_PULLBACK ---
        # Limit buy on 10% pullback with best slippage (0.5%). Fills only if trough <= pullback level.
        slippage_pb = 0.5
        target_pb_price = safe_alert_price * 0.90
        pb_mc = safe_alert_mc * 0.90 if safe_alert_price > 0 else safe_alert_mc
        pullback_triggered = (safe_trough <= target_pb_price) and (safe_trough > 0.0)

        if pullback_triggered and target_pb_price > 0:
            entry_price_pb = target_pb_price
            mfe_pb = ((safe_peak - entry_price_pb) / entry_price_pb * 100.0)
            mae_pb = ((safe_trough - entry_price_pb) / entry_price_pb * 100.0)
            net_return_pb = (((safe_peak - entry_price_pb) / entry_price_pb * 100.0) - slippage_pb)
        else:
            # Order was never filled (price never dipped to -10% pullback)
            entry_price_pb = target_pb_price
            mfe_pb = 0.0
            mae_pb = 0.0
            net_return_pb = 0.0

        imp_pb = (net_return_pb - actual_return) if actual_return is not None else 0.0

        pb_cf = EntryCounterfactual(
            token_address=token_address,
            symbol=symbol,
            signal_timestamp=signal_timestamp,
            scenario=SCENARIO_ENTERED_AFTER_PULLBACK,
            hypothetical_entry_price=entry_price_pb,
            hypothetical_entry_mc=pb_mc,
            hypothetical_mfe_pct=mfe_pb,
            hypothetical_mae_pct=mae_pb,
            hypothetical_net_return_pct=net_return_pb,
            hypothetical_slippage_pct=slippage_pb if pullback_triggered else 0.0,
            actual_entry_price=actual_entry_price,
            actual_return_pct=actual_return,
            improvement_vs_actual_pct=imp_pb,
        )
        results.append(pb_cf)

        # Store to SQLite database
        self.save_entry_counterfactuals(results)
        return results

    def generate_exit_counterfactuals(
        self,
        token_address: str,
        symbol: str,
        entry_timestamp: str,
        entry_price: float,
        peak_price: float,
        trough_after_peak: float,
        actual_exit_price: Optional[float] = None,
        actual_return: Optional[float] = None,
        entry_mc: float = 0.0,
        time_in_trade_min: float = 0.0,
    ) -> List[ExitCounterfactual]:
        """
        Generate 5 exit counterfactual scenarios for a historical trade entry:
        1. EXITED_AT_2X: exit at entry * 2.0 if peak >= 2x, else exit at trough_after_peak
        2. EXITED_AT_5X: exit at entry * 5.0 if peak >= 5x, else exit at trough_after_peak
        3. EXITED_AT_10X: exit at entry * 10.0 if peak >= 10x, else exit at trough_after_peak
        4. EXITED_TRAILING_STOP: exit at peak * 0.75 (25% trailing stop from peak)
        5. EXITED_RISK_INVALIDATION: exit at trough_after_peak (worst case drawdown)

        Parameters
        ----------
        token_address : str
            Unique address of the token.
        symbol : str
            Ticker symbol.
        entry_timestamp : str
            ISO timestamp of position entry.
        entry_price : float
            Actual or baseline entry price.
        peak_price : float
            Maximum price observed during position lifecycle.
        trough_after_peak : float
            Post-peak trough price or terminal invalidation price.
        actual_exit_price : Optional[float]
            Canonical exit price realized in historical trade.
        actual_return : Optional[float]
            Canonical net return realized in historical trade.
        entry_mc : float
            Market cap at entry (optional, used to scale exit mc).
        time_in_trade_min : float
            Estimated or actual holding time in minutes.

        Returns
        -------
        List[ExitCounterfactual]
            List of 5 hypothetical exit counterfactual evaluations.
        """
        results: List[ExitCounterfactual] = []
        safe_entry = max(1e-12, float(entry_price or 0.0))
        safe_peak = max(0.0, float(peak_price or 0.0))
        safe_trough = max(0.0, float(trough_after_peak or 0.0))
        safe_entry_mc = max(0.0, float(entry_mc or 0.0))

        # Helper to compute market cap at exit
        def calc_exit_mc(price: float) -> float:
            if safe_entry > 0 and safe_entry_mc > 0:
                return safe_entry_mc * (price / safe_entry)
            return 0.0

        # Helper to compute return pct
        def calc_return_pct(exit_p: float) -> float:
            if safe_entry > 0:
                return ((exit_p - safe_entry) / safe_entry) * 100.0
            return 0.0

        # --- Scenario 1: EXITED_AT_2X ---
        target_2x = safe_entry * 2.0
        if safe_peak >= target_2x:
            exit_price_2x = target_2x
        else:
            exit_price_2x = safe_trough
        return_2x = calc_return_pct(exit_price_2x)
        imp_2x = (return_2x - actual_return) if actual_return is not None else 0.0

        results.append(
            ExitCounterfactual(
                token_address=token_address,
                symbol=symbol,
                entry_timestamp=entry_timestamp,
                scenario=SCENARIO_EXITED_AT_2X,
                hypothetical_exit_price=exit_price_2x,
                hypothetical_exit_mc=calc_exit_mc(exit_price_2x),
                hypothetical_return_pct=return_2x,
                hypothetical_time_in_trade_min=time_in_trade_min,
                actual_exit_price=actual_exit_price,
                actual_return_pct=actual_return,
                improvement_vs_actual_pct=imp_2x,
            )
        )

        # --- Scenario 2: EXITED_AT_5X ---
        target_5x = safe_entry * 5.0
        if safe_peak >= target_5x:
            exit_price_5x = target_5x
        else:
            exit_price_5x = safe_trough
        return_5x = calc_return_pct(exit_price_5x)
        imp_5x = (return_5x - actual_return) if actual_return is not None else 0.0

        results.append(
            ExitCounterfactual(
                token_address=token_address,
                symbol=symbol,
                entry_timestamp=entry_timestamp,
                scenario=SCENARIO_EXITED_AT_5X,
                hypothetical_exit_price=exit_price_5x,
                hypothetical_exit_mc=calc_exit_mc(exit_price_5x),
                hypothetical_return_pct=return_5x,
                hypothetical_time_in_trade_min=time_in_trade_min,
                actual_exit_price=actual_exit_price,
                actual_return_pct=actual_return,
                improvement_vs_actual_pct=imp_5x,
            )
        )

        # --- Scenario 3: EXITED_AT_10X ---
        target_10x = safe_entry * 10.0
        if safe_peak >= target_10x:
            exit_price_10x = target_10x
        else:
            exit_price_10x = safe_trough
        return_10x = calc_return_pct(exit_price_10x)
        imp_10x = (return_10x - actual_return) if actual_return is not None else 0.0

        results.append(
            ExitCounterfactual(
                token_address=token_address,
                symbol=symbol,
                entry_timestamp=entry_timestamp,
                scenario=SCENARIO_EXITED_AT_10X,
                hypothetical_exit_price=exit_price_10x,
                hypothetical_exit_mc=calc_exit_mc(exit_price_10x),
                hypothetical_return_pct=return_10x,
                hypothetical_time_in_trade_min=time_in_trade_min,
                actual_exit_price=actual_exit_price,
                actual_return_pct=actual_return,
                improvement_vs_actual_pct=imp_10x,
            )
        )

        # --- Scenario 4: EXITED_TRAILING_STOP ---
        # 25% trailing drawdown from highest peak price reached
        exit_price_ts = safe_peak * 0.75
        return_ts = calc_return_pct(exit_price_ts)
        imp_ts = (return_ts - actual_return) if actual_return is not None else 0.0

        results.append(
            ExitCounterfactual(
                token_address=token_address,
                symbol=symbol,
                entry_timestamp=entry_timestamp,
                scenario=SCENARIO_EXITED_TRAILING_STOP,
                hypothetical_exit_price=exit_price_ts,
                hypothetical_exit_mc=calc_exit_mc(exit_price_ts),
                hypothetical_return_pct=return_ts,
                hypothetical_time_in_trade_min=time_in_trade_min,
                actual_exit_price=actual_exit_price,
                actual_return_pct=actual_return,
                improvement_vs_actual_pct=imp_ts,
            )
        )

        # --- Scenario 5: EXITED_RISK_INVALIDATION ---
        # Worst-case exit at trough price (invalidation stop-out)
        exit_price_inv = safe_trough
        return_inv = calc_return_pct(exit_price_inv)
        imp_inv = (return_inv - actual_return) if actual_return is not None else 0.0

        results.append(
            ExitCounterfactual(
                token_address=token_address,
                symbol=symbol,
                entry_timestamp=entry_timestamp,
                scenario=SCENARIO_EXITED_RISK_INVALIDATION,
                hypothetical_exit_price=exit_price_inv,
                hypothetical_exit_mc=calc_exit_mc(exit_price_inv),
                hypothetical_return_pct=return_inv,
                hypothetical_time_in_trade_min=time_in_trade_min,
                actual_exit_price=actual_exit_price,
                actual_return_pct=actual_return,
                improvement_vs_actual_pct=imp_inv,
            )
        )

        # Store to SQLite database
        self.save_exit_counterfactuals(results)
        return results

    def save_entry_counterfactuals(self, entries: List[EntryCounterfactual]) -> None:
        """
        Persist a batch of entry counterfactuals to the isolated SQLite database.

        Parameters
        ----------
        entries : List[EntryCounterfactual]
            List of entry counterfactual records to insert.
        """
        if not entries:
            return

        now_iso = datetime.now(timezone.utc).isoformat()
        conn = sqlite3.connect(self.db_path)
        try:
            with conn:
                cursor = conn.cursor()
                cursor.executemany(
                    """
                    INSERT INTO entry_counterfactuals (
                        token_address, symbol, signal_timestamp, scenario,
                        hypothetical_entry_price, hypothetical_entry_mc,
                        hypothetical_mfe_pct, hypothetical_mae_pct,
                        hypothetical_net_return_pct, hypothetical_slippage_pct,
                        actual_entry_price, actual_return_pct,
                        improvement_vs_actual_pct, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (
                            e.token_address,
                            e.symbol,
                            e.signal_timestamp,
                            e.scenario,
                            e.hypothetical_entry_price,
                            e.hypothetical_entry_mc,
                            e.hypothetical_mfe_pct,
                            e.hypothetical_mae_pct,
                            e.hypothetical_net_return_pct,
                            e.hypothetical_slippage_pct,
                            e.actual_entry_price,
                            e.actual_return_pct,
                            e.improvement_vs_actual_pct,
                            now_iso,
                        )
                        for e in entries
                    ],
                )
        except Exception as exc:
            logger.error("Failed to save entry counterfactuals to SQLite: %s", exc)
        finally:
            conn.close()

    def save_exit_counterfactuals(self, exits: List[ExitCounterfactual]) -> None:
        """
        Persist a batch of exit counterfactuals to the isolated SQLite database.

        Parameters
        ----------
        exits : List[ExitCounterfactual]
            List of exit counterfactual records to insert.
        """
        if not exits:
            return

        now_iso = datetime.now(timezone.utc).isoformat()
        conn = sqlite3.connect(self.db_path)
        try:
            with conn:
                cursor = conn.cursor()
                cursor.executemany(
                    """
                    INSERT INTO exit_counterfactuals (
                        token_address, symbol, entry_timestamp, scenario,
                        hypothetical_exit_price, hypothetical_exit_mc,
                        hypothetical_return_pct, hypothetical_time_in_trade_min,
                        actual_exit_price, actual_return_pct,
                        improvement_vs_actual_pct, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (
                            x.token_address,
                            x.symbol,
                            x.entry_timestamp,
                            x.scenario,
                            x.hypothetical_exit_price,
                            x.hypothetical_exit_mc,
                            x.hypothetical_return_pct,
                            x.hypothetical_time_in_trade_min,
                            x.actual_exit_price,
                            x.actual_return_pct,
                            x.improvement_vs_actual_pct,
                            now_iso,
                        )
                        for x in exits
                    ],
                )
        except Exception as exc:
            logger.error("Failed to save exit counterfactuals to SQLite: %s", exc)
        finally:
            conn.close()

    def build_counterfactual_report(
        self,
        entries: List[EntryCounterfactual],
        exits: List[ExitCounterfactual],
    ) -> CounterfactualReport:
        """
        Build an aggregated diagnostic report comparing all entry and exit counterfactual policies.

        Parameters
        ----------
        entries : List[EntryCounterfactual]
            Collection of evaluated entry counterfactuals.
        exits : List[ExitCounterfactual]
            Collection of evaluated exit counterfactuals.

        Returns
        -------
        CounterfactualReport
            Comprehensive report identifying the highest alpha entry and exit scenarios.
        """
        # Calculate unique evaluated signals
        unique_signals = set()
        for e in entries:
            unique_signals.add((e.token_address, e.signal_timestamp))
        for x in exits:
            unique_signals.add((x.token_address, x.entry_timestamp))

        total_signals = len(unique_signals) if unique_signals else max(len(entries) // 3 if entries else 0, len(exits) // 5 if exits else 0)

        # Analyze Entry Scenarios
        entry_groups: Dict[str, List[EntryCounterfactual]] = {}
        for e in entries:
            entry_groups.setdefault(e.scenario, []).append(e)

        best_entry_scenario = "ENTERED_IMMEDIATELY"
        avg_improvement_best_entry = 0.0

        if entry_groups:
            scenario_entry_scores: Dict[str, float] = {}
            for scen, items in entry_groups.items():
                if items:
                    avg_imp = sum(item.improvement_vs_actual_pct for item in items) / len(items)
                    scenario_entry_scores[scen] = avg_imp

            if scenario_entry_scores:
                best_entry_scenario = max(scenario_entry_scores.keys(), key=lambda s: scenario_entry_scores[s])
                avg_improvement_best_entry = scenario_entry_scores[best_entry_scenario]

        # Analyze Exit Scenarios
        exit_groups: Dict[str, List[ExitCounterfactual]] = {}
        for x in exits:
            exit_groups.setdefault(x.scenario, []).append(x)

        best_exit_scenario = "EXITED_TRAILING_STOP"
        avg_improvement_best_exit = 0.0

        if exit_groups:
            scenario_exit_scores: Dict[str, float] = {}
            for scen, items in exit_groups.items():
                if items:
                    avg_imp = sum(item.improvement_vs_actual_pct for item in items) / len(items)
                    scenario_exit_scores[scen] = avg_imp

            if scenario_exit_scores:
                best_exit_scenario = max(scenario_exit_scores.keys(), key=lambda s: scenario_exit_scores[s])
                avg_improvement_best_exit = scenario_exit_scores[best_exit_scenario]

        return CounterfactualReport(
            total_signals_evaluated=total_signals,
            entry_scenarios_generated=len(entries),
            exit_scenarios_generated=len(exits),
            best_entry_scenario=best_entry_scenario,
            avg_improvement_best_entry_pct=avg_improvement_best_entry,
            best_exit_scenario=best_exit_scenario,
            avg_improvement_best_exit_pct=avg_improvement_best_exit,
            entry_counterfactuals=list(entries),
            exit_counterfactuals=list(exits),
        )

    def load_all_entry_counterfactuals(self) -> List[EntryCounterfactual]:
        """
        Retrieve all stored entry counterfactual records from the SQLite database.

        Returns
        -------
        List[EntryCounterfactual]
            All historical entry counterfactual records.
        """
        results: List[EntryCounterfactual] = []
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT token_address, symbol, signal_timestamp, scenario,
                       hypothetical_entry_price, hypothetical_entry_mc,
                       hypothetical_mfe_pct, hypothetical_mae_pct,
                       hypothetical_net_return_pct, hypothetical_slippage_pct,
                       actual_entry_price, actual_return_pct,
                       improvement_vs_actual_pct
                FROM entry_counterfactuals
                ORDER BY id ASC
            """)
            rows = cursor.fetchall()
            for row in rows:
                results.append(
                    EntryCounterfactual(
                        token_address=str(row[0]),
                        symbol=str(row[1]),
                        signal_timestamp=str(row[2]),
                        scenario=str(row[3]),
                        hypothetical_entry_price=float(row[4]),
                        hypothetical_entry_mc=float(row[5]),
                        hypothetical_mfe_pct=float(row[6]),
                        hypothetical_mae_pct=float(row[7]),
                        hypothetical_net_return_pct=float(row[8]),
                        hypothetical_slippage_pct=float(row[9]),
                        actual_entry_price=float(row[10]) if row[10] is not None else None,
                        actual_return_pct=float(row[11]) if row[11] is not None else None,
                        improvement_vs_actual_pct=float(row[12]),
                    )
                )
        except Exception as exc:
            logger.error("Failed to load entry counterfactuals from SQLite: %s", exc)
        finally:
            conn.close()
        return results

    def load_all_exit_counterfactuals(self) -> List[ExitCounterfactual]:
        """
        Retrieve all stored exit counterfactual records from the SQLite database.

        Returns
        -------
        List[ExitCounterfactual]
            All historical exit counterfactual records.
        """
        results: List[ExitCounterfactual] = []
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT token_address, symbol, entry_timestamp, scenario,
                       hypothetical_exit_price, hypothetical_exit_mc,
                       hypothetical_return_pct, hypothetical_time_in_trade_min,
                       actual_exit_price, actual_return_pct,
                       improvement_vs_actual_pct
                FROM exit_counterfactuals
                ORDER BY id ASC
            """)
            rows = cursor.fetchall()
            for row in rows:
                results.append(
                    ExitCounterfactual(
                        token_address=str(row[0]),
                        symbol=str(row[1]),
                        entry_timestamp=str(row[2]),
                        scenario=str(row[3]),
                        hypothetical_exit_price=float(row[4]),
                        hypothetical_exit_mc=float(row[5]),
                        hypothetical_return_pct=float(row[6]),
                        hypothetical_time_in_trade_min=float(row[7]),
                        actual_exit_price=float(row[8]) if row[8] is not None else None,
                        actual_return_pct=float(row[9]) if row[9] is not None else None,
                        improvement_vs_actual_pct=float(row[10]),
                    )
                )
        except Exception as exc:
            logger.error("Failed to load exit counterfactuals from SQLite: %s", exc)
        finally:
            conn.close()
        return results

    def load_entry_counterfactuals_for_token(self, token_address: str) -> List[EntryCounterfactual]:
        """Retrieve entry counterfactuals for a specific token address."""
        results: List[EntryCounterfactual] = []
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT token_address, symbol, signal_timestamp, scenario,
                       hypothetical_entry_price, hypothetical_entry_mc,
                       hypothetical_mfe_pct, hypothetical_mae_pct,
                       hypothetical_net_return_pct, hypothetical_slippage_pct,
                       actual_entry_price, actual_return_pct,
                       improvement_vs_actual_pct
                FROM entry_counterfactuals
                WHERE token_address = ?
                ORDER BY id ASC
            """, (token_address,))
            for row in cursor.fetchall():
                results.append(
                    EntryCounterfactual(
                        token_address=str(row[0]),
                        symbol=str(row[1]),
                        signal_timestamp=str(row[2]),
                        scenario=str(row[3]),
                        hypothetical_entry_price=float(row[4]),
                        hypothetical_entry_mc=float(row[5]),
                        hypothetical_mfe_pct=float(row[6]),
                        hypothetical_mae_pct=float(row[7]),
                        hypothetical_net_return_pct=float(row[8]),
                        hypothetical_slippage_pct=float(row[9]),
                        actual_entry_price=float(row[10]) if row[10] is not None else None,
                        actual_return_pct=float(row[11]) if row[11] is not None else None,
                        improvement_vs_actual_pct=float(row[12]),
                    )
                )
        except Exception as exc:
            logger.error("Failed to load entry counterfactuals for token %s: %s", token_address, exc)
        finally:
            conn.close()
        return results

    def load_exit_counterfactuals_for_token(self, token_address: str) -> List[ExitCounterfactual]:
        """Retrieve exit counterfactuals for a specific token address."""
        results: List[ExitCounterfactual] = []
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT token_address, symbol, entry_timestamp, scenario,
                       hypothetical_exit_price, hypothetical_exit_mc,
                       hypothetical_return_pct, hypothetical_time_in_trade_min,
                       actual_exit_price, actual_return_pct,
                       improvement_vs_actual_pct
                FROM exit_counterfactuals
                WHERE token_address = ?
                ORDER BY id ASC
            """, (token_address,))
            for row in cursor.fetchall():
                results.append(
                    ExitCounterfactual(
                        token_address=str(row[0]),
                        symbol=str(row[1]),
                        entry_timestamp=str(row[2]),
                        scenario=str(row[3]),
                        hypothetical_exit_price=float(row[4]),
                        hypothetical_exit_mc=float(row[5]),
                        hypothetical_return_pct=float(row[6]),
                        hypothetical_time_in_trade_min=float(row[7]),
                        actual_exit_price=float(row[8]) if row[8] is not None else None,
                        actual_return_pct=float(row[9]) if row[9] is not None else None,
                        improvement_vs_actual_pct=float(row[10]),
                    )
                )
        except Exception as exc:
            logger.error("Failed to load exit counterfactuals for token %s: %s", token_address, exc)
        finally:
            conn.close()
        return results

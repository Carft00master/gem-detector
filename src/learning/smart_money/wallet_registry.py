"""
Smart Money Wallet Registry & SQLite Persistence Layer (v1.0.0 Research Release with Temporal Quarantine)
Maintains the persistent database of tracked, candidate, emerging, validated, and declining wallets:
- Database: data/smart_money.db
- Categorization:
  - REFERENCE_WALLETS (Seed reference wallets supplied by user)
  - DISCOVERED_WALLETS (Autonomously discovered wallets from winning token milestones)
- Temporal Quarantine & Skill Decay integration
"""

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import sqlite3
from typing import Any, Dict, List, Optional, Set, Tuple

from src.learning.smart_money.maturity import DEFAULT_MATURITY_THRESHOLDS, WalletMaturityState
from src.learning.smart_money.wallet_performance import WalletPerformanceCalculator, WalletPerformanceMetrics
from src.learning.smart_money.wallet_roles import WalletRoleClassifier
from src.learning.smart_money.wallet_controls import MatchedControlEvaluator
from src.learning.smart_money.wallet_fingerprint import WalletFingerprintLearner, WalletEntryFingerprint
from src.learning.smart_money.skill_decay import WalletSkillDecayCalculator

logger = logging.getLogger(__name__)

# User supplied reference wallets to track by default
SEED_REFERENCE_WALLETS = [
    {
        "address": "GpwbW4ErcUyXFTZW4ozMCtMJSVaony9HFYNrxQjKhXj6",
        "tag": "USER_REFERENCE_WALLET_A",
        "source": "SEED_REFERENCE",
        "category": "REFERENCE_WALLETS",
    },
    {
        "address": "EBx24uAPtaS1SvHwRhKEktSgzaXdiVEyHuSVpAMVwrcD",
        "tag": "USER_REFERENCE_WALLET_B",
        "source": "SEED_REFERENCE",
        "category": "REFERENCE_WALLETS",
    },
]


class SmartMoneyRegistry:
    """
    Manages SQLite store for smart wallets, trade histories, roles, decay, and temporal quarantines.
    """

    def __init__(self, db_path: Optional[Path] = None):
        from src.utils.paths import get_data_dir
        base_dir = get_data_dir()
        base_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = db_path or (base_dir / "smart_money.db")
        self._init_db()
        self._seed_reference_wallets()

    def _init_db(self) -> None:
        """Create and migrate SQLite tables for smart money tracking."""
        with sqlite3.connect(self.db_path, timeout=30.0) as conn:
            c = conn.cursor()
            try:
                c.execute("PRAGMA journal_mode=WAL;")
            except Exception as e:
                logger.warning(f"Failed to set journal_mode=WAL for {self.db_path}: {e}")
            c.execute("PRAGMA synchronous=NORMAL;")
            c.execute("PRAGMA busy_timeout=30000;")

            # 1. Wallets table
            c.execute("""
                CREATE TABLE IF NOT EXISTS smart_wallets (
                    wallet_address TEXT PRIMARY KEY,
                    tag TEXT,
                    source TEXT,
                    wallet_category TEXT,
                    maturity_state TEXT,
                    primary_role TEXT,
                    role_confidence REAL,
                    total_trades INTEGER,
                    mature_trades INTEGER,
                    raw_win_rate REAL,
                    shrunk_win_rate REAL,
                    shrunk_target_3m_rate REAL,
                    skill_confidence REAL,
                    matched_lift_pct REAL,
                    skill_7d REAL,
                    skill_30d REAL,
                    skill_90d REAL,
                    skill_trend TEXT,
                    profit_factor REAL,
                    risk_adjusted_score REAL,
                    discovery_timestamp TEXT,
                    validation_timestamp TEXT,
                    first_eligible_signal_timestamp TEXT,
                    first_seen_timestamp TEXT,
                    last_updated_timestamp TEXT,
                    is_smart_money_eligible INTEGER
                )
            """)

            # Auto-migrate any new columns in smart_wallets
            c.execute("PRAGMA table_info(smart_wallets)")
            existing_cols = {row[1] for row in c.fetchall()}
            new_cols = {
                "wallet_category": "TEXT",
                "skill_7d": "REAL",
                "skill_30d": "REAL",
                "skill_90d": "REAL",
                "skill_trend": "TEXT",
                "discovery_timestamp": "TEXT",
                "validation_timestamp": "TEXT",
                "first_eligible_signal_timestamp": "TEXT",
            }
            for col, col_type in new_cols.items():
                if col not in existing_cols:
                    c.execute(f"ALTER TABLE smart_wallets ADD COLUMN {col} {col_type}")

            # 2. Wallet Interactions table
            c.execute("""
                CREATE TABLE IF NOT EXISTS wallet_interactions (
                    interaction_id TEXT PRIMARY KEY,
                    wallet_address TEXT NOT NULL,
                    token_address TEXT NOT NULL,
                    symbol TEXT,
                    chain TEXT,
                    venue TEXT,
                    entry_timestamp TEXT NOT NULL,
                    entry_market_cap_usd REAL,
                    entry_liquidity_usd REAL,
                    entry_price_usd REAL,
                    position_size_usd REAL,
                    exit_timestamp TEXT,
                    exit_price_usd REAL,
                    holding_time_sec REAL,
                    realized_pnl_usd REAL,
                    realized_return_pct REAL,
                    mfe_ratio REAL,
                    mae_ratio REAL,
                    market_regime TEXT,
                    target_100k INTEGER,
                    target_500k INTEGER,
                    target_1m INTEGER,
                    target_3m INTEGER,
                    is_rug INTEGER,
                    is_pre_milestone INTEGER,
                    milestone_trigger TEXT
                )
            """)
            c.execute("CREATE INDEX IF NOT EXISTS idx_interaction_wallet ON wallet_interactions(wallet_address)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_interaction_token ON wallet_interactions(token_address)")

            # Auto-migrate any new columns in wallet_interactions
            c.execute("PRAGMA table_info(wallet_interactions)")
            existing_inter_cols = {row[1] for row in c.fetchall()}
            if "market_regime" not in existing_inter_cols:
                c.execute("ALTER TABLE wallet_interactions ADD COLUMN market_regime TEXT")


            # 3. Quarantined Tokens table
            c.execute("""
                CREATE TABLE IF NOT EXISTS quarantined_tokens (
                    token_address TEXT PRIMARY KEY,
                    discovered_wallet TEXT,
                    quarantine_reason TEXT,
                    quarantine_timestamp TEXT
                )
            """)

            # 4. Entry Fingerprints table
            c.execute("""
                CREATE TABLE IF NOT EXISTS wallet_fingerprints (
                    wallet_address TEXT PRIMARY KEY,
                    optimal_mc_min REAL,
                    optimal_mc_max REAL,
                    optimal_age_min REAL,
                    optimal_age_max REAL,
                    optimal_liq_min REAL,
                    optimal_liq_max REAL,
                    preferred_regimes_json TEXT,
                    mean_winning_activity_density REAL,
                    mean_winning_two_sided_quality REAL,
                    mean_winning_buyer_pressure REAL,
                    last_updated TEXT
                )
            """)

            conn.commit()

    def _seed_reference_wallets(self) -> None:
        """Seed reference wallets if not already tracked, and ensure wallet categories are properly assigned."""
        now_str = datetime.now(timezone.utc).isoformat()
        with sqlite3.connect(self.db_path, timeout=30.0) as conn:
            c = conn.cursor()
            for seed in SEED_REFERENCE_WALLETS:
                c.execute("SELECT wallet_address FROM smart_wallets WHERE wallet_address = ?", (seed["address"],))
                if not c.fetchone():
                    c.execute("""
                        INSERT INTO smart_wallets (
                            wallet_address, tag, source, wallet_category, maturity_state, primary_role,
                            role_confidence, total_trades, mature_trades, raw_win_rate,
                            shrunk_win_rate, shrunk_target_3m_rate, skill_confidence,
                            matched_lift_pct, skill_7d, skill_30d, skill_90d, skill_trend,
                            profit_factor, risk_adjusted_score, first_seen_timestamp, last_updated_timestamp,
                            is_smart_money_eligible
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        seed["address"], seed["tag"], seed["source"], seed["category"], "CANDIDATE", "TRADER",
                        0.50, 0, 0, 0.0, 10.0, 5.0, 0.0, 0.0, 0.0, 0.0, 0.0, "INSUFFICIENT_DATA",
                        0.0, 0.0, now_str, now_str, 1
                    ))
                else:
                    c.execute("UPDATE smart_wallets SET wallet_category = ? WHERE wallet_address = ?", (seed["category"], seed["address"]))

            # Ensure any other wallets without category are marked DISCOVERED_WALLETS
            c.execute("UPDATE smart_wallets SET wallet_category = 'DISCOVERED_WALLETS' WHERE wallet_category IS NULL OR wallet_category = ''")
            conn.commit()


    def record_interaction(
        self,
        interaction: Dict[str, Any],
        is_discovery_token: bool = False,
    ) -> None:
        """Record or update a single wallet token interaction and handle discovery quarantine."""
        wallet = interaction.get("wallet_address")
        token = interaction.get("token_address")
        if not wallet:
            return

        now_str = datetime.now(timezone.utc).isoformat()
        entry_ts = interaction.get("entry_timestamp", now_str)

        with sqlite3.connect(self.db_path, timeout=30.0) as conn:
            c = conn.cursor()
            # Ensure wallet exists in smart_wallets
            c.execute("SELECT wallet_address, discovery_timestamp FROM smart_wallets WHERE wallet_address = ?", (wallet,))
            row = c.fetchone()
            if not row:
                c.execute("""
                    INSERT INTO smart_wallets (
                        wallet_address, tag, source, wallet_category, maturity_state, primary_role,
                        role_confidence, total_trades, mature_trades, raw_win_rate,
                        shrunk_win_rate, shrunk_target_3m_rate, skill_confidence,
                        matched_lift_pct, skill_7d, skill_30d, skill_90d, skill_trend,
                        profit_factor, risk_adjusted_score, discovery_timestamp,
                        first_eligible_signal_timestamp, first_seen_timestamp,
                        last_updated_timestamp, is_smart_money_eligible
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    wallet, "ON_CHAIN_DISCOVERED", "AUTONOMOUS_DISCOVERY", "DISCOVERED_WALLETS", "CANDIDATE", "UNKNOWN",
                    0.50, 0, 0, 0.0, 10.0, 5.0, 0.0, 0.0, 0.0, 0.0, 0.0, "INSUFFICIENT_DATA",
                    0.0, 0.0, entry_ts, entry_ts, now_str, now_str, 1
                ))

            if is_discovery_token and token:
                c.execute("""
                    INSERT OR REPLACE INTO quarantined_tokens (
                        token_address, discovered_wallet, quarantine_reason, quarantine_timestamp
                    ) VALUES (?, ?, ?, ?)
                """, (token, wallet, "DISCOVERY_TOKEN_QUARANTINE", entry_ts))

            c.execute("""
                INSERT OR REPLACE INTO wallet_interactions (
                    interaction_id, wallet_address, token_address, symbol, chain, venue,
                    entry_timestamp, entry_market_cap_usd, entry_liquidity_usd,
                    entry_price_usd, position_size_usd, exit_timestamp, exit_price_usd,
                    holding_time_sec, realized_pnl_usd, realized_return_pct, mfe_ratio,
                    mae_ratio, market_regime, target_100k, target_500k, target_1m, target_3m,
                    is_rug, is_pre_milestone, milestone_trigger
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                interaction.get("interaction_id") or f"{wallet[:6]}_{token[:6] if token else ''}",
                wallet,
                token or "",
                interaction.get("symbol", "UNKNOWN"),
                interaction.get("chain", "solana"),
                interaction.get("venue", "pumpfun"),
                entry_ts,
                float(interaction.get("entry_market_cap_usd") or interaction.get("entry_market_cap") or 0.0),
                float(interaction.get("entry_liquidity_usd") or interaction.get("entry_liquidity") or 0.0),
                float(interaction.get("entry_price_usd") or interaction.get("entry_price") or 0.0),
                float(interaction.get("position_size_usd") or interaction.get("position_size") or 100.0),
                interaction.get("exit_timestamp"),
                float(interaction.get("exit_price_usd") or 0.0) if interaction.get("exit_price_usd") is not None else None,
                float(interaction.get("holding_time_sec") or interaction.get("holding_time") or 0.0),
                float(interaction.get("realized_pnl_usd") or interaction.get("realized_pnl") or 0.0),
                float(interaction.get("realized_return_pct") or interaction.get("realized_return") or 0.0),
                float(interaction.get("mfe_ratio") or interaction.get("mfe") or 1.0),
                float(interaction.get("mae_ratio") or interaction.get("mae") or 1.0),
                interaction.get("market_regime", "NORMAL"),
                int(bool(interaction.get("target_100k"))),
                int(bool(interaction.get("target_500k"))),
                int(bool(interaction.get("target_1m"))),
                int(bool(interaction.get("target_3m"))),
                int(bool(interaction.get("is_rug"))),
                int(bool(interaction.get("is_pre_milestone", True))),
                interaction.get("milestone_trigger", ""),
            ))
            conn.commit()

        self.recalculate_wallet_metrics(wallet)

    def record_interactions_batch(
        self,
        interactions: List[Dict[str, Any]],
        is_discovery_token: bool = False,
        progress_callback: Optional[Any] = None,
    ) -> Set[str]:
        """Record multiple wallet token interactions in batch and update wallet metrics."""
        if not interactions:
            return set()

        now_str = datetime.now(timezone.utc).isoformat()
        affected_wallets: Set[str] = set()

        with sqlite3.connect(self.db_path, timeout=30.0) as conn:
            c = conn.cursor()
            c.execute("SELECT wallet_address FROM smart_wallets")
            existing_wallets = {r[0] for r in c.fetchall()}

            new_wallets = []
            quarantine_rows = []
            interaction_rows = []

            for inter in interactions:
                wallet = inter.get("wallet_address")
                token = inter.get("token_address")
                if not wallet:
                    continue
                affected_wallets.add(wallet)
                entry_ts = inter.get("entry_timestamp", now_str)

                if wallet not in existing_wallets:
                    existing_wallets.add(wallet)
                    new_wallets.append((
                        wallet, "ON_CHAIN_DISCOVERED", "AUTONOMOUS_DISCOVERY", "DISCOVERED_WALLETS", "CANDIDATE", "UNKNOWN",
                        0.50, 0, 0, 0.0, 10.0, 5.0, 0.0, 0.0, 0.0, 0.0, 0.0, "INSUFFICIENT_DATA",
                        0.0, 0.0, entry_ts, entry_ts, now_str, now_str, 1
                    ))

                if is_discovery_token and token:
                    quarantine_rows.append((token, wallet, "DISCOVERY_TOKEN_QUARANTINE", entry_ts))

                interaction_rows.append((
                    inter.get("interaction_id") or f"{wallet[:6]}_{token[:6] if token else ''}",
                    wallet,
                    token or "",
                    inter.get("symbol", "UNKNOWN"),
                    inter.get("chain", "solana"),
                    inter.get("venue", "pumpfun"),
                    entry_ts,
                    float(inter.get("entry_market_cap_usd") or inter.get("entry_market_cap") or 0.0),
                    float(inter.get("entry_liquidity_usd") or inter.get("entry_liquidity") or 0.0),
                    float(inter.get("entry_price_usd") or inter.get("entry_price") or 0.0),
                    float(inter.get("position_size_usd") or inter.get("position_size") or 100.0),
                    inter.get("exit_timestamp"),
                    float(inter.get("exit_price_usd") or 0.0) if inter.get("exit_price_usd") is not None else None,
                    float(inter.get("holding_time_sec") or inter.get("holding_time") or 0.0),
                    float(inter.get("realized_pnl_usd") or inter.get("realized_pnl") or 0.0),
                    float(inter.get("realized_return_pct") or inter.get("realized_return") or 0.0),
                    float(inter.get("mfe_ratio") or inter.get("mfe") or 1.0),
                    float(inter.get("mae_ratio") or inter.get("mae") or 1.0),
                    inter.get("market_regime", "NORMAL"),
                    int(bool(inter.get("target_100k"))),
                    int(bool(inter.get("target_500k"))),
                    int(bool(inter.get("target_1m"))),
                    int(bool(inter.get("target_3m"))),
                    int(bool(inter.get("is_rug"))),
                    int(bool(inter.get("is_pre_milestone", True))),
                    inter.get("milestone_trigger", ""),
                ))

            if new_wallets:
                c.executemany("""
                    INSERT INTO smart_wallets (
                        wallet_address, tag, source, wallet_category, maturity_state, primary_role,
                        role_confidence, total_trades, mature_trades, raw_win_rate,
                        shrunk_win_rate, shrunk_target_3m_rate, skill_confidence,
                        matched_lift_pct, skill_7d, skill_30d, skill_90d, skill_trend,
                        profit_factor, risk_adjusted_score, discovery_timestamp,
                        first_eligible_signal_timestamp, first_seen_timestamp,
                        last_updated_timestamp, is_smart_money_eligible
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, new_wallets)

            if quarantine_rows:
                c.executemany("""
                    INSERT OR REPLACE INTO quarantined_tokens (
                        token_address, discovered_wallet, quarantine_reason, quarantine_timestamp
                    ) VALUES (?, ?, ?, ?)
                """, quarantine_rows)

            if interaction_rows:
                c.executemany("""
                    INSERT OR REPLACE INTO wallet_interactions (
                        interaction_id, wallet_address, token_address, symbol, chain, venue,
                        entry_timestamp, entry_market_cap_usd, entry_liquidity_usd,
                        entry_price_usd, position_size_usd, exit_timestamp, exit_price_usd,
                        holding_time_sec, realized_pnl_usd, realized_return_pct, mfe_ratio,
                        mae_ratio, market_regime, target_100k, target_500k, target_1m, target_3m,
                        is_rug, is_pre_milestone, milestone_trigger
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, interaction_rows)

            conn.commit()

        # Recalculate metrics for affected wallets
        total_w = len(affected_wallets)
        for idx, w_addr in enumerate(affected_wallets):
            self.recalculate_wallet_metrics(w_addr)
            if progress_callback and total_w > 0:
                pct = 60 + int(35 * (idx + 1) / total_w)
                progress_callback(pct, f"Analyzing track record for wallet {idx+1}/{total_w}...")

        return affected_wallets

    def recalculate_wallet_metrics(self, wallet_address: str) -> None:
        """Recompute point-in-time metrics, roles, matched lift, skill decay, and fingerprints."""
        with sqlite3.connect(self.db_path, timeout=30.0) as conn:
            conn.row_factory = sqlite3.Row
            c = conn.cursor()
            c.execute("SELECT * FROM wallet_interactions WHERE wallet_address = ?", (wallet_address,))
            tx_rows = [dict(r) for r in c.fetchall()]

            perf = WalletPerformanceCalculator.calculate_performance(wallet_address, tx_rows)
            role_cls = WalletRoleClassifier.classify_wallet(wallet_address, tx_rows)
            lift_eval = MatchedControlEvaluator.evaluate_wallet_lift(wallet_address, tx_rows)
            fp = WalletFingerprintLearner.extract_fingerprint(wallet_address, tx_rows)
            decay = WalletSkillDecayCalculator.evaluate_wallet_decay(wallet_address, tx_rows)

            # Determine maturity state
            if not role_cls.is_smart_money_eligible or perf.rug_exposure_pct >= DEFAULT_MATURITY_THRESHOLDS.disqualification_rug_rate_max * 100.0:
                maturity = WalletMaturityState.DISQUALIFIED.value
            elif decay.is_actively_decaying:
                maturity = WalletMaturityState.DECLINING.value
            elif perf.mature_trades >= DEFAULT_MATURITY_THRESHOLDS.min_trades_validated and lift_eval.matched_lift_pct >= DEFAULT_MATURITY_THRESHOLDS.min_validated_matched_lift * 100.0 and perf.skill_confidence >= DEFAULT_MATURITY_THRESHOLDS.min_validated_confidence:
                maturity = WalletMaturityState.VALIDATED.value
            elif perf.mature_trades >= DEFAULT_MATURITY_THRESHOLDS.min_trades_emerging:
                maturity = WalletMaturityState.EMERGING.value
            elif perf.total_trades > 0:
                maturity = WalletMaturityState.OBSERVED.value
            else:
                maturity = WalletMaturityState.CANDIDATE.value

            now_str = datetime.now(timezone.utc).isoformat()

            c.execute("""
                UPDATE smart_wallets SET
                    maturity_state = ?,
                    primary_role = ?,
                    role_confidence = ?,
                    total_trades = ?,
                    mature_trades = ?,
                    raw_win_rate = ?,
                    shrunk_win_rate = ?,
                    shrunk_target_3m_rate = ?,
                    skill_confidence = ?,
                    matched_lift_pct = ?,
                    skill_7d = ?,
                    skill_30d = ?,
                    skill_90d = ?,
                    skill_trend = ?,
                    profit_factor = ?,
                    risk_adjusted_score = ?,
                    last_updated_timestamp = ?,
                    is_smart_money_eligible = ?
                WHERE wallet_address = ?
            """, (
                maturity, role_cls.primary_role, role_cls.role_confidence,
                perf.total_trades, perf.mature_trades, perf.raw_win_rate,
                perf.shrunk_win_rate, perf.shrunk_target_3m_rate, perf.skill_confidence,
                lift_eval.matched_lift_pct, decay.skill_7d_win_rate, decay.skill_30d_win_rate,
                decay.skill_90d_win_rate, decay.skill_trend, perf.profit_factor,
                perf.risk_adjusted_score, now_str, int(role_cls.is_smart_money_eligible), wallet_address
            ))

            # Store fingerprint
            c.execute("""
                INSERT OR REPLACE INTO wallet_fingerprints (
                    wallet_address, optimal_mc_min, optimal_mc_max,
                    optimal_age_min, optimal_age_max, optimal_liq_min,
                    optimal_liq_max, preferred_regimes_json,
                    mean_winning_activity_density, mean_winning_two_sided_quality,
                    mean_winning_buyer_pressure, last_updated
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                wallet_address, fp.optimal_mc_range_usd[0], fp.optimal_mc_range_usd[1],
                fp.optimal_age_range_min[0], fp.optimal_age_range_min[1],
                fp.optimal_liquidity_range_usd[0], fp.optimal_liquidity_range_usd[1],
                json.dumps(fp.preferred_regimes), fp.mean_winning_activity_density,
                fp.mean_winning_two_sided_quality, fp.mean_winning_buyer_pressure,
                now_str
            ))

            conn.commit()

    def get_all_wallets(self, category: Optional[str] = None) -> List[Dict[str, Any]]:
        """Return tracked wallets, optionally filtered by category ('REFERENCE_WALLETS' or 'DISCOVERED_WALLETS')."""
        with sqlite3.connect(self.db_path, timeout=30.0) as conn:
            conn.row_factory = sqlite3.Row
            c = conn.cursor()
            if category:
                c.execute("SELECT * FROM smart_wallets WHERE wallet_category = ? ORDER BY risk_adjusted_score DESC, shrunk_win_rate DESC", (category,))
            else:
                c.execute("SELECT * FROM smart_wallets ORDER BY risk_adjusted_score DESC, shrunk_win_rate DESC")
            return [dict(r) for r in c.fetchall()]

    def get_quarantined_tokens(self) -> List[Dict[str, Any]]:
        """Return all quarantined token records."""
        with sqlite3.connect(self.db_path, timeout=30.0) as conn:
            conn.row_factory = sqlite3.Row
            c = conn.cursor()
            c.execute("SELECT * FROM quarantined_tokens")
            return [dict(r) for r in c.fetchall()]

    def get_validated_fingerprints(self) -> List[WalletEntryFingerprint]:
        """Fetch fingerprints for all VALIDATED or EMERGING eligible smart wallets."""
        with sqlite3.connect(self.db_path, timeout=30.0) as conn:
            conn.row_factory = sqlite3.Row
            c = conn.cursor()
            c.execute("""
                SELECT f.* FROM wallet_fingerprints f
                JOIN smart_wallets w ON f.wallet_address = w.wallet_address
                WHERE w.maturity_state IN ('VALIDATED', 'EMERGING') AND w.is_smart_money_eligible = 1
            """)
            rows = c.fetchall()
            fps = []
            for r in rows:
                regimes = ["NORMAL"]
                try:
                    regimes = json.loads(r["preferred_regimes_json"])
                except Exception:
                    pass
                fps.append(WalletEntryFingerprint(
                    wallet_address=r["wallet_address"],
                    total_entries_analyzed=10,
                    winning_entries_count=5,
                    losing_entries_count=5,
                    optimal_mc_range_usd=(r["optimal_mc_min"], r["optimal_mc_max"]),
                    optimal_age_range_min=(r["optimal_age_min"], r["optimal_age_max"]),
                    optimal_liquidity_range_usd=(r["optimal_liq_min"], r["optimal_liq_max"]),
                    preferred_regimes=regimes,
                    mean_winning_activity_density=r["mean_winning_activity_density"],
                    mean_winning_two_sided_quality=r["mean_winning_two_sided_quality"],
                    mean_winning_buyer_pressure=r["mean_winning_buyer_pressure"],
                ))
            return fps

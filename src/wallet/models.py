"""
Data models for the Virtual Wallet Subsystem.
Tracks isolated capital allocation ($1,000 baseline), real-sized execution,
cash ledger transactions, and periodic equity snapshots.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional, Dict, Any


@dataclass
class WalletSessionRecord:
    session_id: str
    name: str = "Live Forward Test ($1,000 @ 5%)"
    starting_capital_usd: float = 1000.0
    risk_pct: float = 0.05                 # 5% (0.05) or 10% (0.10)
    sizing_mode: str = "COMPOUNDING"       # "COMPOUNDING" or "FIXED"
    current_cash_usd: float = 1000.0
    current_equity_usd: float = 1000.0
    peak_equity_usd: float = 1000.0
    max_drawdown_pct: float = 0.0
    is_active: bool = True
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    notes: Optional[str] = None


@dataclass
class WalletPositionRecord:
    position_id: str
    session_id: str
    paper_trade_id: str
    token_address: str
    symbol: str
    chain: str
    venue: str
    position_size_usd: float               # Actual dollar capital committed
    entry_price_usd: float                 # Dex quote price
    simulated_fill_price_usd: float        # Price after slippage & AMM impact for this specific size
    entry_market_cap_usd: float
    entry_liquidity_usd: float
    entry_timestamp: str
    entry_price_impact_pct: float = 0.0
    entry_fees_usd: float = 0.0            # DEX swap fee + Solana/Base priority fee
    status: str = "OPEN"                   # "OPEN" | "CLOSED" | "SKIPPED"
    skip_reason: Optional[str] = None      # "NO_CAPITAL" | "TOO_SMALL" | "LIQUIDITY_CAPPED"
    
    # Exit fields (populated on close)
    exit_price_usd: Optional[float] = None
    exit_market_cap_usd: Optional[float] = None
    exit_liquidity_usd: Optional[float] = None
    exit_timestamp: Optional[str] = None
    exit_reason: Optional[str] = None
    exit_price_impact_pct: float = 0.0
    exit_fees_usd: float = 0.0
    gross_exit_proceeds_usd: float = 0.0
    net_realized_pnl_usd: float = 0.0
    net_realized_return_pct: float = 0.0
    hold_duration_seconds: float = 0.0
    equity_before_usd: float = 1000.0
    equity_after_usd: float = 1000.0


@dataclass
class WalletLedgerRecord:
    entry_id: str
    session_id: str
    timestamp: str
    entry_type: str                        # "INITIAL_DEPOSIT" | "BUY" | "SELL" | "FEE" | "ADJUSTMENT"
    amount_usd: float                      # Signed (+ for inflows/sells, - for buys/fees)
    cash_balance_after_usd: float
    position_id: Optional[str] = None
    notes: Optional[str] = None


@dataclass
class WalletEquitySnapshotRecord:
    snapshot_id: str
    session_id: str
    timestamp: str
    cash_balance_usd: float
    deployed_capital_usd: float
    mark_to_market_value_usd: float
    total_equity_usd: float
    open_positions_count: int
    unrealized_pnl_usd: float = 0.0

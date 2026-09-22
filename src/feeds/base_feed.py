"""
Base Feed & Data Models
Defines normalized token structures, security reports, order flow stats, and feed interfaces.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


@dataclass
class TokenSocials:
    twitter: Optional[str] = None
    telegram: Optional[str] = None
    website: Optional[str] = None
    discord: Optional[str] = None

    @property
    def has_any(self) -> bool:
        return bool(self.twitter or self.telegram or self.website or self.discord)

    @property
    def count(self) -> int:
        return sum(1 for x in [self.twitter, self.telegram, self.website, self.discord] if x)


@dataclass
class TokenSecurityReport:
    is_honeypot: bool = False
    mint_renounced: bool = True
    freeze_renounced: bool = True
    lp_burned_or_locked_pct: float = 100.0
    top10_holder_pct: float = 0.0
    dev_holding_pct: float = 0.0
    dev_sold_all: bool = False
    buy_tax_pct: float = 0.0
    sell_tax_pct: float = 0.0
    flags: List[str] = field(default_factory=list)

    @property
    def is_safe(self) -> bool:
        return (
            not self.is_honeypot
            and self.mint_renounced
            and self.freeze_renounced
            and self.lp_burned_or_locked_pct >= 90.0
            and self.buy_tax_pct <= 2.0
            and self.sell_tax_pct <= 2.0
        )


@dataclass
class TokenCandidate:
    # Identifiers
    address: str
    pair_address: str
    symbol: str
    name: str
    chain: str  # e.g., "solana", "base", "ethereum"
    dex_id: str  # e.g., "raydium", "pumpfun", "uniswap"

    # Valuation & Liquidity
    market_cap_usd: float
    price_usd: float
    liquidity_usd: float
    liquidity_mc_ratio: float = 0.0

    # Volume & Transaction metrics (5m, 1h, 24h)
    volume_5m_usd: float = 0.0
    volume_1h_usd: float = 0.0
    volume_24h_usd: float = 0.0
    volume_mc_ratio_5m: float = 0.0
    volume_mc_ratio_1h: float = 0.0

    # Order flow / Tx Counts
    txns_5m_buys: int = 0
    txns_5m_sells: int = 0
    txns_1h_buys: int = 0
    txns_1h_sells: int = 0
    buy_sell_ratio_5m: float = 0.0
    buy_sell_ratio_1h: float = 0.0

    # Unique wallets & Velocity
    unique_buyers_1h: int = 0
    unique_sellers_1h: int = 0
    buyer_seller_ratio_1h: float = 0.0
    holder_count: int = 0
    holder_growth_pct_1h: float = 0.0

    # Timestamps & Age
    created_at: Optional[datetime] = None
    age_minutes: float = 0.0

    # Metadata & Security
    socials: TokenSocials = field(default_factory=TokenSocials)
    security: TokenSecurityReport = field(default_factory=TokenSecurityReport)
    raw_data: Dict[str, Any] = field(default_factory=dict)

    def calculate_ratios(self) -> None:
        """Derive secondary ratios from raw metrics."""
        if self.market_cap_usd > 0:
            self.liquidity_mc_ratio = self.liquidity_usd / self.market_cap_usd
            self.volume_mc_ratio_5m = self.volume_5m_usd / self.market_cap_usd
            self.volume_mc_ratio_1h = self.volume_1h_usd / self.market_cap_usd
        else:
            self.liquidity_mc_ratio = 0.0
            self.volume_mc_ratio_5m = 0.0
            self.volume_mc_ratio_1h = 0.0

        if self.txns_5m_sells > 0:
            self.buy_sell_ratio_5m = self.txns_5m_buys / self.txns_5m_sells
        else:
            self.buy_sell_ratio_5m = float(self.txns_5m_buys) if self.txns_5m_buys > 0 else 1.0

        if self.txns_1h_sells > 0:
            self.buy_sell_ratio_1h = self.txns_1h_buys / self.txns_1h_sells
        else:
            self.buy_sell_ratio_1h = float(self.txns_1h_buys) if self.txns_1h_buys > 0 else 1.0

        if self.unique_sellers_1h > 0:
            self.buyer_seller_ratio_1h = self.unique_buyers_1h / self.unique_sellers_1h
        else:
            self.buyer_seller_ratio_1h = float(self.unique_buyers_1h) if self.unique_buyers_1h > 0 else 1.0


@dataclass
class ScoringBreakdown:
    holder_distribution_score: float = 0.0   # max 25
    volume_momentum_score: float = 0.0       # max 25
    order_flow_score: float = 0.0            # max 20
    liquidity_health_score: float = 0.0      # max 20
    social_virality_score: float = 0.0       # max 10
    total_gem_score: float = 0.0             # 0 to 100
    signals: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


@dataclass
class ScoredToken:
    token: TokenCandidate
    score: ScoringBreakdown
    scanned_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    passed_filters: bool = True


class BaseFeed(ABC):
    """Abstract interface for token discovery feeds."""

    @abstractmethod
    async def fetch_candidates(self, chain: str) -> List[TokenCandidate]:
        """Fetch active token candidates for a given blockchain."""
        pass

    @abstractmethod
    async def close(self) -> None:
        """Clean up HTTP/WebSocket connections."""
        pass

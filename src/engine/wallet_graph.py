"""
Wallet Graph & Cabal Clustering Engine with Entity Classification
Constructs buyer/funder relationships, classifies funding sources (Exchange, Bridge, Router, Platform, Coordinator),
prevents false cabal clustering from shared exchange withdrawals, and computes EFFECTIVE_TOP10_CONCENTRATION.
"""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple


class FundingEntityType(str, Enum):
    EXCHANGE = "EXCHANGE"                # Binance, Coinbase, OKX, Bybit, Kraken
    BRIDGE = "BRIDGE"                    # Wormhole, deBridge, Across, Stargate
    ROUTER = "ROUTER"                    # Jupiter, Uniswap Universal Router, 1inch
    LAUNCH_PLATFORM = "LAUNCH_PLATFORM"  # Pump.fun Program, Raydium Deployer
    KNOWN_SERVICE = "KNOWN_SERVICE"      # MEV Bot, Public Faucet
    UNKNOWN_WALLET = "UNKNOWN_WALLET"    # Standard private wallet
    SUSPECTED_COORDINATOR = "SUSPECTED_COORDINATOR" # Private wallet funding multiple snipers


# Known Public Infrastructure / Exchange / Bridge Wallet Signatures & Prefixes
KNOWN_PUBLIC_ENTITIES: Dict[str, FundingEntityType] = {
    # Exchanges (Solana / EVM hot wallets)
    "5tzFkiKscXHK5ZXCGbXZxdw7gTjjD5mznz6zVj3d1y8M": FundingEntityType.EXCHANGE, # Binance Sol
    "2AQdpHJ2JpcEgPiATUXjQxA8QmaNakedHwzojpD879xM": FundingEntityType.EXCHANGE, # Coinbase Sol
    "FWznbcNXWQuHTawe9RxvQ2LdJF23mB6y9mK": FundingEntityType.EXCHANGE,          # OKX Sol
    "0x28c6c06298d514db089934071355e5743bf21d60": FundingEntityType.EXCHANGE, # Binance EVM
    "0x503828976d22510aad0201ac7ec88293211d23da": FundingEntityType.EXCHANGE, # Coinbase EVM
    # Bridges & Protocols
    "worm2ZoG2kUd4vFXhvjh93UUH596ayR1U2P5PPpeb9Z": FundingEntityType.BRIDGE,   # Wormhole Sol
    "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P": FundingEntityType.LAUNCH_PLATFORM, # Pump.fun
}


@dataclass
class WalletNode:
    address: str
    holding_pct: float = 0.0
    funding_source: Optional[str] = None
    funding_entity_type: FundingEntityType = FundingEntityType.UNKNOWN_WALLET
    funding_timestamp: Optional[datetime] = None
    first_buy_timestamp: Optional[datetime] = None
    buy_amount_usd: float = 0.0
    is_deployer: bool = False
    is_contract_or_pool: bool = False
    cluster_id: Optional[int] = None


@dataclass
class CabalAnalysisResult:
    raw_top10_pct: float = 0.0
    effective_top10_pct: float = 0.0
    exchange_source_adjusted_concentration: float = 0.0
    wallet_independence_score: float = 1.0  # 1.0 = Highly independent, 0.0 = Bundled cabal
    cabal_risk_score: float = 0.0           # 0.0 = Safe, 1.0 = High cabal bundling risk
    cabal_probability: float = 0.0          # Calibrated probability of malicious cabal control
    cluster_count: int = 0
    largest_cluster_pct: float = 0.0
    synchronized_buyers_count: int = 0
    exchange_funded_wallets_count: int = 0
    coordinator_wallets: List[str] = field(default_factory=list)
    common_funder_wallets: List[str] = field(default_factory=list)
    signals: List[str] = field(default_factory=list)


class WalletGraphEngine:
    @classmethod
    def classify_funding_entity(cls, funder_address: Optional[str]) -> FundingEntityType:
        """Classify a funding address into entity category."""
        if not funder_address:
            return FundingEntityType.UNKNOWN_WALLET

        # Exact match lookup
        if funder_address in KNOWN_PUBLIC_ENTITIES:
            return KNOWN_PUBLIC_ENTITIES[funder_address]

        # Name / Tag heuristics
        lower_addr = funder_address.lower()
        if "binance" in lower_addr or "coinbase" in lower_addr or "kraken" in lower_addr or "okx" in lower_addr:
            return FundingEntityType.EXCHANGE
        if "wormhole" in lower_addr or "debridge" in lower_addr or "across" in lower_addr or "bridge" in lower_addr:
            return FundingEntityType.BRIDGE
        if "pump" in lower_addr or "raydium" in lower_addr or "router" in lower_addr:
            return FundingEntityType.LAUNCH_PLATFORM

        return FundingEntityType.UNKNOWN_WALLET

    @classmethod
    def analyze_wallets(
        cls,
        wallets: List[WalletNode],
        sync_window_seconds: float = 3.0,
        funding_time_window_seconds: float = 120.0,
    ) -> CabalAnalysisResult:
        """
        Analyze wallet cluster relationships with exchange/bridge awareness.
        """
        res = CabalAnalysisResult()
        if not wallets:
            return res

        # Filter out liquidity pools and zero balances
        eligible_wallets = [w for w in wallets if not w.is_contract_or_pool and w.holding_pct > 0]
        if not eligible_wallets:
            return res

        # 1. Compute Raw Top 10 Concentration
        sorted_by_hold = sorted(eligible_wallets, key=lambda w: w.holding_pct, reverse=True)
        res.raw_top10_pct = round(sum(w.holding_pct for w in sorted_by_hold[:10]), 2)

        # 2. Classify Funding Entities for all wallets
        exchange_funded_count = 0
        for w in eligible_wallets:
            if w.funding_source:
                w.funding_entity_type = cls.classify_funding_entity(w.funding_source)
                if w.funding_entity_type in (FundingEntityType.EXCHANGE, FundingEntityType.BRIDGE):
                    exchange_funded_count += 1

        res.exchange_funded_wallets_count = exchange_funded_count

        # 3. Disjoint Set Graph Construction
        parent: Dict[str, str] = {node.address: node.address for node in eligible_wallets}

        def find(u: str) -> str:
            if parent[u] != u:
                parent[u] = find(parent[u])
            return parent[u]

        def union(u: str, v: str) -> None:
            root_u = find(u)
            root_v = find(v)
            if root_u != root_v:
                parent[root_v] = root_u

        # A. Cluster by Common Private Funding Source (Excluding Public Exchanges & Bridges!)
        funder_map: Dict[str, List[WalletNode]] = defaultdict(list)
        for w in eligible_wallets:
            if w.funding_source and w.funding_source != w.address:
                # Do NOT union wallets simply because they both funded from Binance or Coinbase!
                if w.funding_entity_type not in (
                    FundingEntityType.EXCHANGE,
                    FundingEntityType.BRIDGE,
                    FundingEntityType.LAUNCH_PLATFORM,
                    FundingEntityType.ROUTER,
                ):
                    funder_map[w.funding_source].append(w)

        coordinators = []
        for funder, members in funder_map.items():
            if len(members) >= 2:
                coordinators.append(funder)
                base = members[0].address
                for m in members[1:]:
                    union(base, m.address)

        res.coordinator_wallets = coordinators
        res.common_funder_wallets = coordinators

        # B. Cluster by Synchronized Buy Timing (< 3 seconds apart in launch block)
        timed_wallets = [w for w in eligible_wallets if w.first_buy_timestamp]
        timed_wallets.sort(key=lambda w: w.first_buy_timestamp) # type: ignore

        synchronized_count = 0
        for i in range(len(timed_wallets)):
            w1 = timed_wallets[i]
            for j in range(i + 1, len(timed_wallets)):
                w2 = timed_wallets[j]
                delta = (w2.first_buy_timestamp - w1.first_buy_timestamp).total_seconds() # type: ignore
                if delta <= sync_window_seconds:
                    union(w1.address, w2.address)
                    synchronized_count += 1
                else:
                    break

        res.synchronized_buyers_count = synchronized_count

        # 4. Aggregate Clusters into Economic Units
        clusters: Dict[str, float] = defaultdict(float)
        for w in eligible_wallets:
            root = find(w.address)
            clusters[root] += w.holding_pct

        cluster_shares = sorted(clusters.values(), reverse=True)
        res.cluster_count = len(cluster_shares)
        res.largest_cluster_pct = round(cluster_shares[0], 2) if cluster_shares else 0.0
        res.effective_top10_pct = round(sum(cluster_shares[:10]), 2)
        res.exchange_source_adjusted_concentration = res.effective_top10_pct

        # 5. Independence and Cabal Scoring
        signals = []
        cabal_risk = 0.0

        concentration_gap = max(0.0, res.effective_top10_pct - res.raw_top10_pct)
        if concentration_gap >= 15.0:
            signals.append("HEAVY_SYBIL_BUNDLING_DETECTED")
        elif concentration_gap >= 8.0:
            signals.append("MODERATE_WALLET_CLUSTERING")

        if coordinators:
            signals.append("PRIVATE_COORDINATOR_CABAL_RISK")
            signals.append("COMMON_FUNDER_CABAL_RISK")

        if exchange_funded_count >= 3:
            signals.append("ORGANIC_EXCHANGE_FUNDED_WALLETS")

        if res.synchronized_buyers_count >= 3:
            signals.append("SYNCHRONIZED_SNIPER_BOTS")

        # Score calculation
        if res.largest_cluster_pct >= 25.0:
            cabal_risk += 0.45
        elif res.largest_cluster_pct >= 15.0:
            cabal_risk += 0.25
        elif res.largest_cluster_pct >= 10.0:
            cabal_risk += 0.15

        if concentration_gap >= 12.0:
            cabal_risk += 0.35
        elif concentration_gap >= 6.0:
            cabal_risk += 0.20

        if coordinators:
            cabal_risk += 0.15 + min(0.20, len(coordinators) * 0.10)

        if res.synchronized_buyers_count >= 3:
            cabal_risk += 0.15

        res.cabal_risk_score = round(min(1.0, max(0.0, cabal_risk)), 3)
        res.wallet_independence_score = round(max(0.0, 1.0 - res.cabal_risk_score), 3)
        res.cabal_probability = round(min(0.99, cabal_risk * 1.15), 3)
        res.signals = signals

        return res

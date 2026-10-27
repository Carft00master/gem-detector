"""
On-Chain Event Provider & Connection Layer (Phase 1a)
Manages connections to Solana RPC, WebSocket, and Yellowstone gRPC endpoints.
Enforces secure credential handling, commitment levels, program ID verification,
and latency telemetry tracking.
"""

from dataclasses import dataclass, field
from enum import Enum
import logging
import os
import re
from typing import Any, Dict, Optional, Tuple

from src.utils.env_loader import load_env_file

# Automatically load .env from project root into os.environ if present
load_env_file()

logger = logging.getLogger(__name__)


class ProviderType(str, Enum):
    GRPC = "GRPC"
    WEBSOCKET = "WEBSOCKET"
    RPC = "RPC"


class CommitmentLevel(str, Enum):
    PROCESSED = "processed"
    CONFIRMED = "confirmed"
    FINALIZED = "finalized"


# Official Program IDs verified on Solana Mainnet via getAccountInfo (executable = True where applicable)
PROGRAM_IDS = {
    # Pump.fun Core
    "PUMP_FUN_PROGRAM": "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P",                # Executable (BPFLoaderUpgradeab1e)
    "PUMPSWAP_AMM_PROGRAM": "pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA",            # Executable (BPFLoaderUpgradeab1e)
    "PUMP_FEE_PROGRAM": "pfeeUxB6jkeY1Hxd7CsFCAjcbHA9rWtchMGdZ6VojVZ",                # Executable (BPFLoaderUpgradeab1e)
    "PUMP_FUN_MIGRATION_AUTHORITY": "39azUYFWPz3VHgKCf3VChUwbpURdCHRxjWVowf5jUJjg",    # System Account (Migration Authority, not executable BPF program)
    "PUMP_FUN_MIGRATION_PROGRAM": "39azUYFWPz3VHgKCf3VChUwbpURdCHRxjWVowf5jUJjg",      # Deprecated alias for PUMP_FUN_MIGRATION_AUTHORITY
    "PUMP_FUN_FEE_RECIPIENT": "CebN5WGQ4jvEPvsVU4EoHEpgzq1VV7AbicfhtW4xC9iM",          # Fee Recipient
    "PUMP_FUN_GLOBAL_CONFIG": "4wTV1YmiEkRvAtNtsSGPtUrqRYQMe5SKy2uB4Jjaxnjf",          # Curve Global Config (95 bps fee)
    # External DEXs
    "RAYDIUM_AMM_V4": "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8",                # Executable (BPFLoaderUpgradeab1e)
    "RAYDIUM_CPMM": "CPMMoo8L3F4NbTegBCKVNunggL7H1ZpdTHKxQB5qKP1C",                  # Executable (BPFLoaderUpgradeab1e)
    "RAYDIUM_SOL_USDC_POOL": "58oQChx4yWmvKdwLLZzBi4ChoCc2fqCUWBkwMihLYQo2",         # SOL/USDC Pool
    # Pyth Oracle
    "PYTH_SOLANA_RECEIVER_PROGRAM": "rec5EKMGg6MxZYaMdyBfgwp4d5rB9T1VQH5pJv5LtFJ",    # Executable (BPFLoaderUpgradeab1e)
    "PYTH_SOL_USD_PRICE_UPDATE": "7UVimffxr9ow1uXYxsr4LHAcV58mLzhmwaeKvJ1pjLiE",       # Live PriceUpdateV2 Account
    "PYTH_LEGACY_SOL_USD_ORACLE": "H6ARHf6YXhGYeQfUzQNGk6rDNnLBQKrenN712K4AQJEG",     # Deprecated (frozen slot 299058484)
}


def redact_secrets(text: str) -> str:
    """Redact API keys, tokens, and credentials from logs and strings."""
    if not text:
        return ""
    # Redact query string API keys
    text = re.sub(r'([?&](?:api[-_]?key|token|auth)=)[a-zA-Z0-9_-]+', r'\1[REDACTED]', text, flags=re.IGNORECASE)
    # Redact URL embedded credentials e.g. https://...api-key=...
    text = re.sub(r'(helius\.xyz/\?api-key=)[a-zA-Z0-9_-]+', r'\1[REDACTED]', text, flags=re.IGNORECASE)
    # Redact path-based API keys e.g. dRPC /solana/KEY, Ankr /multichain/KEY, Alchemy /v2/KEY, or QuickNode
    text = re.sub(r'((?:drpc\.live|drpc\.org)/solana/)[a-zA-Z0-9_-]+', r'\1[REDACTED]', text, flags=re.IGNORECASE)
    text = re.sub(r'((?:rpc\.ankr\.com/multichain/))[a-zA-Z0-9_-]+', r'\1[REDACTED]', text, flags=re.IGNORECASE)
    text = re.sub(r'((?:alchemy\.com/v2/))[a-zA-Z0-9_-]+', r'\1[REDACTED]', text, flags=re.IGNORECASE)
    text = re.sub(r'((?:quiknode\.pro|quicknode\.pro)/)[a-zA-Z0-9_-]+', r'\1[REDACTED]', text, flags=re.IGNORECASE)
    # Redact generic long hex/base58/alphanumeric path tokens (>=24 chars)
    text = re.sub(r'(https?://[^/\s]+/[^/\s]*/)[a-fA-F0-9]{24,}', r'\1[REDACTED]', text)
    # Redact Bearer tokens
    text = re.sub(r'(Bearer\s+)[a-zA-Z0-9._-]+', r'\1[REDACTED]', text, flags=re.IGNORECASE)
    return text


class ProviderTier(str, Enum):
    FREE = "FREE"
    PAID = "PAID"


def mask_endpoint_url(url: str, index: int) -> str:
    """Return safe display alias for an RPC endpoint without exposing keys or credentials."""
    if not url:
        return f"endpoint_{index} (unconfigured)"
    try:
        from urllib.parse import urlparse
        parsed = urlparse(url)
        host = parsed.netloc or "unknown_host"
        if "@" in host:
            host = host.split("@")[-1]
        scheme = parsed.scheme or "https"
        if "quiknode.pro" in host or "quicknode.pro" in host:
            parts = host.split(".")
            if len(parts) >= 3:
                masked_host = f"[REDACTED].{'.'.join(parts[-3:])}"
            else:
                masked_host = host
            return f"endpoint_{index} ({scheme}://{masked_host}/[REDACTED])"
        return f"endpoint_{index} ({scheme}://{host}/[REDACTED])"
    except Exception:
        return f"endpoint_{index} ([REDACTED])"


def get_provider_name_from_url(url: str, idx: int = 0) -> str:
    """Identify named provider from URL hostname, fallback to endpoint_{idx}."""
    if not url:
        return f"endpoint_{idx}"
    url_lower = url.lower()
    if "helius" in url_lower:
        return "helius"
    if "ankr" in url_lower:
        return "ankr"
    if "drpc" in url_lower:
        return "drpc"
    if "alchemy" in url_lower:
        return "alchemy"
    if "quicknode" in url_lower or "quiknode" in url_lower:
        return "quicknode"
    return f"endpoint_{idx}"


class AllEndpointsExhaustedError(Exception):
    """Raised when all configured RPC endpoints have exceeded their 95% credit budget limit."""
    pass


@dataclass
class ProviderConfig:
    tier: Optional[ProviderTier] = None
    rpc_urls: list[str] = field(default_factory=list)
    rpc_url: str = field(default_factory=lambda: os.environ.get("SOLANA_RPC_URL", ""))
    ws_url: str = field(default_factory=lambda: os.environ.get("SOLANA_WS_URL", ""))
    grpc_endpoint: Optional[str] = field(default_factory=lambda: os.environ.get("SOLANA_GRPC_ENDPOINT"))
    grpc_token: Optional[str] = field(default_factory=lambda: os.environ.get("SOLANA_GRPC_TOKEN"))
    detection_commitment: CommitmentLevel = CommitmentLevel.PROCESSED
    confirmation_commitment: CommitmentLevel = CommitmentLevel.CONFIRMED
    enable_live_route_b: bool = False  # Disabled by default in FREE tier
    endpoint_budgets: Dict[str, int] = field(default_factory=dict)

    def __post_init__(self):
        # Determine tier: if not explicitly specified by caller, check PROVIDER_TIER env var
        # or auto-detect PAID tier if gRPC endpoint is configured. Default to FREE.
        if self.tier is None:
            env_tier = os.environ.get("PROVIDER_TIER", "").strip().upper()
            if env_tier == "FREE":
                self.tier = ProviderTier.FREE
            elif env_tier == "PAID":
                self.tier = ProviderTier.PAID
            elif self.grpc_endpoint or os.environ.get("SOLANA_GRPC_ENDPOINT"):
                self.tier = ProviderTier.PAID
            else:
                self.tier = ProviderTier.FREE

        # Support multiple comma-separated RPC URLs from SOLANA_RPC_URLS if not explicitly passed
        if not self.rpc_urls:
            env_multi = os.environ.get("SOLANA_RPC_URLS", "").strip()
            if env_multi:
                self.rpc_urls = [u.strip() for u in env_multi.split(",") if u.strip()]
            elif self.rpc_url:
                self.rpc_urls = [self.rpc_url]
            else:
                single = os.environ.get("SOLANA_RPC_URL", "").strip()
                if single:
                    self.rpc_urls = [single]

        # Load explicit per-endpoint budgets from settings.yaml if not provided directly
        if not self.endpoint_budgets:
            try:
                import yaml
                from src.utils.paths import get_project_root
                cfg_path = get_project_root() / "config" / "settings.yaml"
                if cfg_path.exists():
                    raw_cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
                    self.endpoint_budgets = raw_cfg.get("provider", {}).get("endpoint_budgets", {})
            except Exception:
                pass

        # Strict validation: Every configured endpoint MUST have an explicit budget > 0 (by name or index)
        urls = self.rpc_urls or ([self.rpc_url] if self.rpc_url else ["https://api.mainnet-beta.solana.com"])
        keys = list(self.endpoint_budgets.keys())
        for idx, url in enumerate(urls):
            pname = get_provider_name_from_url(url, idx)
            has_budget = (
                (pname in self.endpoint_budgets and self.endpoint_budgets[pname] is not None and self.endpoint_budgets[pname] > 0)
                or (f"endpoint_{idx}" in self.endpoint_budgets and self.endpoint_budgets[f"endpoint_{idx}"] is not None and self.endpoint_budgets[f"endpoint_{idx}"] > 0)
                or (idx < len(keys) and self.endpoint_budgets[keys[idx]] is not None and self.endpoint_budgets[keys[idx]] > 0)
            )
            if not has_budget:
                raise ValueError(
                    f"Configuration error: Endpoint 'endpoint_{idx}' has no explicit credit budget configured in endpoint_budgets "
                    f"(provider '{pname}'). Configured: {self.endpoint_budgets}. Startup halted."
                )

        # In PAID tier with gRPC, live Route B can be active
        if self.tier == ProviderTier.PAID:
            self.enable_live_route_b = True

    def get_preferred_provider(self) -> Tuple[ProviderType, str]:
        """
        Preference order:
        1. gRPC if SOLANA_GRPC_ENDPOINT is set.
        2. WebSocket if SOLANA_WS_URL is set.
        3. Archival RPC as fallback.
        """
        if self.grpc_endpoint:
            return ProviderType.GRPC, self.grpc_endpoint
        if self.ws_url:
            return ProviderType.WEBSOCKET, self.ws_url
        if self.rpc_urls:
            return ProviderType.RPC, self.rpc_urls[0]
        if self.rpc_url:
            return ProviderType.RPC, self.rpc_url
        # If none set, warn and return public RPC for testing
        logger.warning("No private Solana provider configured in env. Falling back to default RPC.")
        return ProviderType.RPC, "https://api.mainnet-beta.solana.com"

    def is_route_b_latency_upper_bound(self) -> bool:
        """
        Route B must be tagged as 'latency upper-bound' if running without Yellowstone gRPC.
        """
        provider_type, _ = self.get_preferred_provider()
        return provider_type != ProviderType.GRPC


class SolanaProvider:
    """
    Manages connections to Solana RPC / WebSocket / gRPC endpoints.
    Provides sanitization, program address validation, round-robin multi-RPC pooling,
    per-endpoint credit budgeting, and latency tagging.
    """
    def __init__(self, config: Optional[ProviderConfig] = None, credit_tracker: Optional[Any] = None):
        self.config = config or ProviderConfig()
        from src.onchain.credit_budget import CreditBudgetTracker
        self.credit_tracker = credit_tracker or CreditBudgetTracker(
            endpoint_budgets=self.config.endpoint_budgets
        )
        self.provider_type, self.active_endpoint = self.config.get_preferred_provider()
        self.is_upper_bound = self.config.is_route_b_latency_upper_bound()
        self._endpoint_index = 0
        
        sanitized_endpoint = mask_endpoint_url(self.active_endpoint, 0)
        logger.info(
            f"SolanaProvider initialized: Tier={self.config.tier.value} | "
            f"Type={self.provider_type.value} | "
            f"Endpoint={sanitized_endpoint} | "
            f"Endpoints Count={len(self.config.rpc_urls) or 1} | "
            f"Route B Mode={'DISABLED (FREE TIER)' if not self.is_route_b_allowed() else ('LATENCY_UPPER_BOUND' if self.is_upper_bound else 'SUB_SLOT_GRPC')}"
        )

    def is_route_b_allowed(self) -> bool:
        """Route B is disabled in FREE tier."""
        if self.config.tier == ProviderTier.FREE:
            return False
        return self.config.enable_live_route_b

    def get_next_rpc_endpoint(self) -> Tuple[str, str, str]:
        """
        Round-robin selection of RPC endpoints respecting per-endpoint credit budgets.
        Returns (endpoint_id, masked_alias, full_url).
        Never prints or logs full URLs or API keys.
        Raises AllEndpointsExhaustedError if all endpoints have reached 95% hard stop.
        """
        urls = self.config.rpc_urls or [self.active_endpoint]
        if not urls:
            urls = ["https://api.mainnet-beta.solana.com"]

        num_endpoints = len(urls)
        for attempt in range(num_endpoints):
            idx = (self._endpoint_index + attempt) % num_endpoints
            url = urls[idx]
            pname = get_provider_name_from_url(url, idx)
            budgets = getattr(self.credit_tracker, "endpoint_budgets", {}) or getattr(self.credit_tracker, "budgets", {})
            if f"endpoint_{idx}" in budgets:
                eid = f"endpoint_{idx}"
            elif pname in budgets:
                eid = pname
            else:
                eid = f"endpoint_{idx}"
            alias = mask_endpoint_url(url, idx)

            if self.credit_tracker.can_call(eid, masked_alias=alias) and not getattr(self.credit_tracker, "is_blocked", lambda e: False)(eid):
                self._endpoint_index = (idx + 1) % num_endpoints
                return eid, alias, url

        raise AllEndpointsExhaustedError(
            f"All {num_endpoints} configured Solana RPC endpoints have reached their 95% monthly credit budget limit. "
            f"Halting calls."
        )

    def get_program_id(self, program_name: str) -> str:
        """Fetch verified program ID with documentation provenance."""
        if program_name not in PROGRAM_IDS:
            raise KeyError(f"Unknown program {program_name}. Verified programs: {list(PROGRAM_IDS.keys())}")
        return PROGRAM_IDS[program_name]

    def get_detection_metadata(self) -> Dict[str, Any]:
        """Telemetry metadata to attach to every recorded on-chain event."""
        is_free = (self.config.tier == ProviderTier.FREE)
        return {
            "provider_tier": self.config.tier.value,
            "detection_source": self.provider_type.value,
            "detection_mode": "polled, not streamed" if is_free else "streamed_processed",
            "commitment": self.config.detection_commitment.value,
            "is_latency_upper_bound": True if is_free else self.is_upper_bound,
            "latency_timing_caveat": (
                "Slot-level timing requires Yellowstone gRPC / shreds; "
                "FREE tier timings are upper-bound estimates." if is_free else ""
            ),
        }

    def execute_rpc(self, method: str, params: Optional[list] = None, timeout: float = 10.0) -> Dict[str, Any]:
        """
        Synchronous wrapped RPC client method.
        Selects next available endpoint respecting credit budget limits, performs request,
        and automatically logs credit consumption in the CreditBudgetTracker.
        Never exposes secrets in logs or exceptions.
        """
        import requests
        endpoint_id, alias, url = self.get_next_rpc_endpoint()
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": method,
            "params": params or [],
        }
        headers = {"Content-Type": "application/json"}
        resp = requests.post(url, json=payload, headers=headers, timeout=timeout)
        resp.raise_for_status()
        self.credit_tracker.record_call(endpoint_id, method=method, masked_alias=alias)
        return resp.json()

    async def execute_rpc_async(
        self,
        session: Any,
        method: str,
        params: Optional[list] = None,
        timeout: float = 10.0,
    ) -> Dict[str, Any]:
        """
        Asynchronous wrapped RPC client method.
        Selects next available endpoint respecting credit budget limits, performs request,
        and automatically logs credit consumption in the CreditBudgetTracker.
        """
        import aiohttp
        endpoint_id, alias, url = self.get_next_rpc_endpoint()
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": method,
            "params": params or [],
        }
        headers = {"Content-Type": "application/json"}
        async with session.post(url, json=payload, headers=headers, timeout=aiohttp.ClientTimeout(total=timeout)) as resp:
            resp.raise_for_status()
            res_json = await resp.json()
            self.credit_tracker.record_call(endpoint_id, method=method, masked_alias=alias)
            return res_json

    def create_async_session(self, timeout: float = 10.0) -> Any:
        """Create managed aiohttp.ClientSession within provider boundary."""
        import aiohttp
        from src.utils.ssl_context import get_verified_ssl_context
        connector = aiohttp.TCPConnector(ssl=get_verified_ssl_context())
        return aiohttp.ClientSession(
            connector=connector,
            timeout=aiohttp.ClientTimeout(total=timeout),
        )


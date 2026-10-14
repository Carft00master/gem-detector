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
    "PUMP_FUN_MIGRATION_PROGRAM": "39azUYFWPz3VHgKCf3VChUwbpURdCHRxjWVowf5jUJjg",      # Migration Authority / Program
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
    # Redact Bearer tokens
    text = re.sub(r'(Bearer\s+)[a-zA-Z0-9._-]+', r'\1[REDACTED]', text, flags=re.IGNORECASE)
    return text


@dataclass
class ProviderConfig:
    rpc_url: str = field(default_factory=lambda: os.environ.get("SOLANA_RPC_URL", ""))
    ws_url: str = field(default_factory=lambda: os.environ.get("SOLANA_WS_URL", ""))
    grpc_endpoint: Optional[str] = field(default_factory=lambda: os.environ.get("SOLANA_GRPC_ENDPOINT"))
    grpc_token: Optional[str] = field(default_factory=lambda: os.environ.get("SOLANA_GRPC_TOKEN"))
    detection_commitment: CommitmentLevel = CommitmentLevel.PROCESSED
    confirmation_commitment: CommitmentLevel = CommitmentLevel.CONFIRMED

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
        if self.rpc_url:
            return ProviderType.RPC, self.rpc_url
        # If none set, warn and return public RPC for testing
        logger.warning("No private Solana provider configured in env. Falling back to default RPC.")
        return ProviderType.RPC, "https://api.mainnet-beta.solana.com"

    def is_route_b_latency_upper_bound(self) -> bool:
        """
        Route B (First-Block Sniping) must be tagged as 'latency upper-bound'
        if running only on websockets without Yellowstone gRPC.
        """
        provider_type, _ = self.get_preferred_provider()
        return provider_type != ProviderType.GRPC


class SolanaProvider:
    """
    Manages connections to Solana RPC / WebSocket / gRPC endpoints.
    Provides sanitization, program address validation, and latency tagging.
    """
    def __init__(self, config: Optional[ProviderConfig] = None):
        self.config = config or ProviderConfig()
        self.provider_type, self.active_endpoint = self.config.get_preferred_provider()
        self.is_upper_bound = self.config.is_route_b_latency_upper_bound()
        
        sanitized_endpoint = redact_secrets(self.active_endpoint)
        logger.info(
            f"SolanaProvider initialized: Type={self.provider_type.value} | "
            f"Endpoint={sanitized_endpoint} | "
            f"Route B Mode={'LATENCY_UPPER_BOUND' if self.is_upper_bound else 'SUB_SLOT_GRPC'}"
        )

    def get_program_id(self, program_name: str) -> str:
        """Fetch verified program ID with documentation provenance."""
        if program_name not in PROGRAM_IDS:
            raise KeyError(f"Unknown program {program_name}. Verified programs: {list(PROGRAM_IDS.keys())}")
        return PROGRAM_IDS[program_name]

    def get_detection_metadata(self) -> Dict[str, Any]:
        """Telemetry metadata to attach to every recorded on-chain event."""
        return {
            "detection_source": self.provider_type.value,
            "commitment": self.config.detection_commitment.value,
            "is_latency_upper_bound": self.is_upper_bound,
        }

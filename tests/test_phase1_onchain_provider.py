"""
Phase 1a Tests: On-Chain Event Provider & Connection Layer
Tests provider preference, env handling, secret redaction, verified program IDs,
and Route B latency upper-bound tagging.
"""

import os
import pytest
from src.onchain.provider import (
    SolanaProvider,
    ProviderConfig,
    ProviderType,
    CommitmentLevel,
    PROGRAM_IDS,
    redact_secrets,
)


def test_provider_preference_grpc_first(monkeypatch):
    monkeypatch.setenv("SOLANA_GRPC_ENDPOINT", "https://grpc.mainnet.helius.xyz:443")
    monkeypatch.setenv("SOLANA_GRPC_TOKEN", "secret-grpc-token")
    monkeypatch.setenv("SOLANA_WS_URL", "wss://atlas-mainnet.helius-rpc.com?api-key=testkey")
    monkeypatch.setenv("SOLANA_RPC_URL", "https://mainnet.helius-rpc.com?api-key=testkey")

    cfg = ProviderConfig()
    p_type, endpoint = cfg.get_preferred_provider()
    assert p_type == ProviderType.GRPC
    assert endpoint == "https://grpc.mainnet.helius.xyz:443"
    assert not cfg.is_route_b_latency_upper_bound()


def test_provider_preference_ws_when_no_grpc(monkeypatch):
    monkeypatch.delenv("SOLANA_GRPC_ENDPOINT", raising=False)
    monkeypatch.delenv("SOLANA_GRPC_TOKEN", raising=False)
    monkeypatch.setenv("SOLANA_WS_URL", "wss://atlas-mainnet.helius-rpc.com?api-key=testkey")
    monkeypatch.setenv("SOLANA_RPC_URL", "https://mainnet.helius-rpc.com?api-key=testkey")

    cfg = ProviderConfig()
    p_type, endpoint = cfg.get_preferred_provider()
    assert p_type == ProviderType.WEBSOCKET
    assert "wss://" in endpoint
    # When running only on websocket, Route B must be tagged as latency upper-bound
    assert cfg.is_route_b_latency_upper_bound()


def test_provider_preference_rpc_fallback(monkeypatch):
    monkeypatch.delenv("SOLANA_GRPC_ENDPOINT", raising=False)
    monkeypatch.delenv("SOLANA_WS_URL", raising=False)
    monkeypatch.setenv("SOLANA_RPC_URL", "https://archival.helius-rpc.com?api-key=testkey")

    cfg = ProviderConfig()
    p_type, endpoint = cfg.get_preferred_provider()
    assert p_type == ProviderType.RPC
    assert "https://archival" in endpoint
    assert cfg.is_route_b_latency_upper_bound()


def test_secret_redaction():
    text1 = "Connecting to https://mainnet.helius-rpc.com/?api-key=12345-abcde-secret"
    redacted1 = redact_secrets(text1)
    assert "12345-abcde-secret" not in redacted1
    assert "[REDACTED]" in redacted1

    text2 = "Authorization: Bearer my-top-secret-grpc-bearer-token"
    redacted2 = redact_secrets(text2)
    assert "my-top-secret-grpc-bearer-token" not in redacted2
    assert "[REDACTED]" in redacted2

    text3 = "Failed request to https://mainnet.helius.xyz/?api-key=compromised-key-789"
    redacted3 = redact_secrets(text3)
    assert "compromised-key-789" not in redacted3
    assert "[REDACTED]" in redacted3


def test_official_program_ids_verified():
    provider = SolanaProvider()
    
    # Official Pump.fun program ID
    assert provider.get_program_id("PUMP_FUN_PROGRAM") == "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"
    # Migration program ID
    assert provider.get_program_id("PUMP_FUN_MIGRATION_PROGRAM") == "39AZHJWrsjhALdgAc2vhVUdhnh8YBgKflAZv29H2jsgk"
    # Migration fee vault
    assert provider.get_program_id("PUMP_FUN_MIGRATION_FEE_VAULT") == "49TqRqqk3cS8bBnA91kjcnUBy8bTHdP2wc79TQwciBeb"
    # Raydium AMM V4
    assert provider.get_program_id("RAYDIUM_AMM_V4") == "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8"
    # Pyth SOL/USD on-chain account
    assert provider.get_program_id("PYTH_SOL_USD_ORACLE") == "H6ARHf6YXhGYeQfUzQNGk6rDNnLBQKrenN712K4AQJEG"

    with pytest.raises(KeyError):
        provider.get_program_id("NON_EXISTENT_PROGRAM")


def test_detection_telemetry_metadata(monkeypatch):
    monkeypatch.delenv("SOLANA_GRPC_ENDPOINT", raising=False)
    monkeypatch.setenv("SOLANA_WS_URL", "wss://atlas-mainnet.helius-rpc.com")

    provider = SolanaProvider()
    meta = provider.get_detection_metadata()
    assert meta["detection_source"] == "WEBSOCKET"
    assert meta["commitment"] == "processed"
    assert meta["is_latency_upper_bound"] is True

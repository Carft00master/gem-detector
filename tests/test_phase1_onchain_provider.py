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
    monkeypatch.delenv("SOLANA_RPC_URLS", raising=False)
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

    text4 = "Connecting to https://lb.drpc.live/solana/my-secret-drpc-key-999"
    redacted4 = redact_secrets(text4)
    assert "my-secret-drpc-key-999" not in redacted4
    assert "[REDACTED]" in redacted4


def test_official_program_ids_verified():
    provider = SolanaProvider()
    
    # Pump.fun Core
    assert provider.get_program_id("PUMP_FUN_PROGRAM") == "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"
    assert provider.get_program_id("PUMPSWAP_AMM_PROGRAM") == "pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA"
    assert provider.get_program_id("PUMP_FEE_PROGRAM") == "pfeeUxB6jkeY1Hxd7CsFCAjcbHA9rWtchMGdZ6VojVZ"
    assert provider.get_program_id("PUMP_FUN_MIGRATION_AUTHORITY") == "39azUYFWPz3VHgKCf3VChUwbpURdCHRxjWVowf5jUJjg"
    assert provider.get_program_id("PUMP_FUN_MIGRATION_PROGRAM") == "39azUYFWPz3VHgKCf3VChUwbpURdCHRxjWVowf5jUJjg"
    assert provider.get_program_id("PUMP_FUN_FEE_RECIPIENT") == "CebN5WGQ4jvEPvsVU4EoHEpgzq1VV7AbicfhtW4xC9iM"
    assert provider.get_program_id("PUMP_FUN_GLOBAL_CONFIG") == "4wTV1YmiEkRvAtNtsSGPtUrqRYQMe5SKy2uB4Jjaxnjf"

    # External DEXs
    assert provider.get_program_id("RAYDIUM_AMM_V4") == "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8"
    assert provider.get_program_id("RAYDIUM_CPMM") == "CPMMoo8L3F4NbTegBCKVNunggL7H1ZpdTHKxQB5qKP1C"

    # Pyth Oracle (Receiver Program & Price Accounts)
    assert provider.get_program_id("PYTH_SOLANA_RECEIVER_PROGRAM") == "rec5EKMGg6MxZYaMdyBfgwp4d5rB9T1VQH5pJv5LtFJ"
    assert provider.get_program_id("PYTH_SOL_USD_PRICE_UPDATE") == "7UVimffxr9ow1uXYxsr4LHAcV58mLzhmwaeKvJ1pjLiE"
    assert provider.get_program_id("PYTH_LEGACY_SOL_USD_ORACLE") == "H6ARHf6YXhGYeQfUzQNGk6rDNnLBQKrenN712K4AQJEG"

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
    assert meta["provider_tier"] == "FREE"
    assert "Slot-level timing requires Yellowstone gRPC" in meta["latency_timing_caveat"]


def test_free_tier_disables_route_b_and_tags_route_a():
    from src.onchain.provider import ProviderTier

    cfg_free = ProviderConfig(tier=ProviderTier.FREE)
    prov_free = SolanaProvider(config=cfg_free)
    assert prov_free.is_route_b_allowed() is False
    meta = prov_free.get_detection_metadata()
    assert meta["provider_tier"] == "FREE"
    assert meta["detection_mode"] == "polled, not streamed"

    cfg_paid = ProviderConfig(tier=ProviderTier.PAID, enable_live_route_b=True)
    prov_paid = SolanaProvider(config=cfg_paid)
    assert prov_paid.is_route_b_allowed() is True


def test_multi_rpc_urls_round_robin_and_masking(monkeypatch, tmp_path):
    from src.onchain.provider import mask_endpoint_url, AllEndpointsExhaustedError
    from src.onchain.credit_budget import CreditBudgetTracker

    url1 = "https://mainnet.helius-rpc.com/?api-key=secret-key-1"
    url2 = "https://solana-mainnet.g.alchemy.com/v2/secret-key-2"
    monkeypatch.setenv("SOLANA_RPC_URLS", f"{url1},{url2}")

    cfg = ProviderConfig()
    assert len(cfg.rpc_urls) == 2
    assert "secret-key-1" not in mask_endpoint_url(cfg.rpc_urls[0], 0)
    assert "[REDACTED]" in mask_endpoint_url(cfg.rpc_urls[0], 0)

    # Tracker with 100 call monthly budget
    tracker = CreditBudgetTracker(storage_path=tmp_path / "budget.json", monthly_budget_per_endpoint=100)
    provider = SolanaProvider(config=cfg, credit_tracker=tracker)

    # First call goes to endpoint_0
    eid0, alias0, full0 = provider.get_next_rpc_endpoint()
    assert eid0 == "endpoint_0"
    assert "secret-key-1" in full0
    assert "secret-key-1" not in alias0

    # Second call goes to endpoint_1 (round-robin)
    eid1, alias1, full1 = provider.get_next_rpc_endpoint()
    assert eid1 == "endpoint_1"
    assert "secret-key-2" in full1
    assert "secret-key-2" not in alias1

    # Third call wraps around to endpoint_0
    eid0_again, _, _ = provider.get_next_rpc_endpoint()
    assert eid0_again == "endpoint_0"

    # Exhaust endpoint_0 to 95% (95 calls)
    tracker.record_call("endpoint_0", credits=95, masked_alias=alias0)
    # Next call should automatically skip exhausted endpoint_0 and return endpoint_1
    eid_next, _, _ = provider.get_next_rpc_endpoint()
    assert eid_next == "endpoint_1"

    # Exhaust endpoint_1 to 95% (95 calls)
    tracker.record_call("endpoint_1", credits=95, masked_alias=alias1)
    # When all endpoints are exhausted, provider raises AllEndpointsExhaustedError
    with pytest.raises(AllEndpointsExhaustedError):
        provider.get_next_rpc_endpoint()


def test_missing_explicit_endpoint_budget_fails_startup(monkeypatch):
    """ProviderConfig must fail startup if any configured endpoint has no explicit budget."""
    url1 = "https://mainnet.helius-rpc.com/?api-key=test1"
    url2 = "https://solana-mainnet.g.alchemy.com/v2/test2"
    url3 = "https://rpc.ankr.com/solana/test3"
    monkeypatch.setenv("SOLANA_RPC_URLS", f"{url1},{url2},{url3}")

    # Explicit budget only provided for endpoint_0 and endpoint_1, endpoint_2 missing
    partial_budgets = {
        "endpoint_0": 5_000_000,
        "endpoint_1": 5_000_000,
    }

    with pytest.raises(ValueError) as excinfo:
        ProviderConfig(endpoint_budgets=partial_budgets)

    assert "Endpoint 'endpoint_2' has no explicit credit budget configured" in str(excinfo.value)


def test_no_direct_rpc_network_calls_outside_provider():
    """
    Ensure no onchain module or script outside provider.py directly invokes raw
    urllib.request, requests, aiohttp, or http.client.
    All RPC communication must route through SolanaProvider.execute_rpc.
    """
    import ast
    import os
    from pathlib import Path

    target_dirs = [Path("src/onchain"), Path("scripts")]
    forbidden_modules = {"urllib.request", "requests", "http.client", "urllib3", "aiohttp"}

    violations = []
    for t_dir in target_dirs:
        for py_file in t_dir.glob("*.py"):
            norm = py_file.as_posix()
            if norm == "src/onchain/provider.py":
                continue
            tree = ast.parse(py_file.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if any(alias.name == m or alias.name.startswith(m + ".") for m in forbidden_modules) or alias.name == "urllib":
                            violations.append(f"{norm}: imports {alias.name}")
                elif isinstance(node, ast.ImportFrom):
                    mod = node.module or ""
                    if any(mod == m or mod.startswith(m + ".") for m in forbidden_modules):
                        violations.append(f"{norm}: imports from {mod}")

    assert not violations, f"Forbidden direct network calls detected outside provider.py: {violations}"



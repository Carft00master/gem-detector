"""
On-Chain Event Subscriber & Transaction Parser (Phase 1a)
Connects to Solana WebSocket or Yellowstone gRPC streams, parses instructions
for pump.fun and PumpSwap/Raydium, and dispatches structured events to OnChainEventStore.
"""

import asyncio
from datetime import datetime, timezone
import json
import logging
from typing import Any, Callable, Dict, List, Optional

from src.onchain.provider import SolanaProvider, CommitmentLevel, ProviderType
from src.onchain.events import OnChainEvent, OnChainEventStore

logger = logging.getLogger(__name__)


class OnChainEventSubscriber:
    """
    Subscribes to live Solana transactions and account mutations.
    Parses curve creations, swaps, migrations, and pool transactions in real-time.
    """
    def __init__(
        self,
        provider: Optional[SolanaProvider] = None,
        store: Optional[OnChainEventStore] = None,
        on_event: Optional[Callable[[OnChainEvent], Any]] = None,
    ):
        self.provider = provider or SolanaProvider()
        self.store = store or OnChainEventStore()
        self.on_event = on_event
        self._is_running = False

    def parse_pump_portal_payload(self, data: Dict[str, Any], current_slot: Optional[int] = None) -> Optional[OnChainEvent]:
        """
        Parse raw PumpPortal / Solana stream JSON payloads into standardized OnChainEvent.
        """
        tx_type = data.get("txType", "").lower()
        mint = data.get("mint", "")
        if not mint:
            return None

        now_ts = datetime.now(timezone.utc).timestamp()
        slot = current_slot or data.get("slot", 0)
        sig = data.get("signature", data.get("tx", ""))
        wallet = data.get("traderPublicKey", data.get("user", data.get("wallet", "")))
        sol_amount = float(data.get("solAmount", data.get("sol_amount", 0.0)) or 0.0)
        token_amount = float(data.get("tokenAmount", data.get("token_amount", 0.0)) or 0.0)
        sol_reserves = float(data.get("vSolInBondingCurve", data.get("sol_reserves_after", 0.0)) or 0.0)
        token_reserves = float(data.get("vTokensInBondingCurve", data.get("token_reserves_after", 0.0)) or 0.0)

        meta = self.provider.get_detection_metadata()

        if tx_type == "create" or "initialBuy" in data:
            ev = OnChainEvent(
                event_type="CURVE_CREATE",
                slot=slot,
                block_time=int(data.get("blockTime", now_ts)),
                signature=sig,
                mint=mint,
                wallet=wallet,
                side="CREATE",
                sol_amount=sol_amount,
                token_amount=token_amount,
                sol_reserves_after=sol_reserves or 30.0,
                token_reserves_after=token_reserves or 1_073_000_000.0,
                detection_source=meta["detection_source"],
                commitment=meta["commitment"],
                received_at=now_ts,
                details=data,
            )
        elif tx_type == "buy":
            ev = OnChainEvent(
                event_type="CURVE_BUY",
                slot=slot,
                block_time=int(data.get("blockTime", now_ts)),
                signature=sig,
                mint=mint,
                wallet=wallet,
                side="BUY",
                sol_amount=sol_amount,
                token_amount=token_amount,
                sol_reserves_after=sol_reserves,
                token_reserves_after=token_reserves,
                detection_source=meta["detection_source"],
                commitment=meta["commitment"],
                received_at=now_ts,
                details=data,
            )
        elif tx_type == "sell":
            ev = OnChainEvent(
                event_type="CURVE_SELL",
                slot=slot,
                block_time=int(data.get("blockTime", now_ts)),
                signature=sig,
                mint=mint,
                wallet=wallet,
                side="SELL",
                sol_amount=sol_amount,
                token_amount=token_amount,
                sol_reserves_after=sol_reserves,
                token_reserves_after=token_reserves,
                detection_source=meta["detection_source"],
                commitment=meta["commitment"],
                received_at=now_ts,
                details=data,
            )
        elif tx_type in ("migrate", "migration"):
            ev = OnChainEvent(
                event_type="MIGRATION",
                slot=slot,
                block_time=int(data.get("blockTime", now_ts)),
                signature=sig,
                mint=mint,
                wallet=wallet,
                side="MIGRATE",
                sol_amount=sol_amount,
                token_amount=token_amount,
                sol_reserves_after=sol_reserves,
                token_reserves_after=token_reserves,
                pool_address=data.get("pool", data.get("pool_address")),
                detection_source=meta["detection_source"],
                commitment=meta["commitment"],
                received_at=now_ts,
                details=data,
            )
        else:
            return None

        # Persist to event store
        self.store.record_event(ev)

        # Dispatch
        if self.on_event:
            try:
                self.on_event(ev)
            except Exception as e:
                logger.error(f"Error in on_event callback: {e}")

        return ev

    def parse_pool_swap(
        self,
        pool_address: str,
        mint: str,
        wallet: str,
        side: str,
        sol_amount: float,
        token_amount: float,
        sol_reserves_after: float,
        token_reserves_after: float,
        slot: int,
        signature: str,
        block_time: Optional[int] = None,
        tx_index_in_slot: Optional[int] = None,
    ) -> OnChainEvent:
        """Parse and persist an execution swap on a migrated PumpSwap / Raydium pool."""
        now_ts = datetime.now(timezone.utc).timestamp()
        meta = self.provider.get_detection_metadata()

        ev = OnChainEvent(
            event_type="POOL_SWAP",
            slot=slot,
            block_time=block_time or int(now_ts),
            signature=signature,
            tx_index_in_slot=tx_index_in_slot,
            mint=mint,
            wallet=wallet,
            side=side.upper(),
            sol_amount=sol_amount,
            token_amount=token_amount,
            sol_reserves_after=sol_reserves_after,
            token_reserves_after=token_reserves_after,
            pool_address=pool_address,
            detection_source=meta["detection_source"],
            commitment=meta["commitment"],
            received_at=now_ts,
        )
        self.store.record_event(ev)
        if self.on_event:
            try:
                self.on_event(ev)
            except Exception as e:
                logger.error(f"Error in on_event callback: {e}")
        return ev

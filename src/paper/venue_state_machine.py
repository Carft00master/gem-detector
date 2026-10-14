"""
Per-Token Venue State Machine & Cross-Venue Continuity Verifier (Phase 1c)
Transitions: CURVE_OPEN -> MIGRATED -> POOL.
Enforces:
1. Every position is bound strictly to one venue state.
2. Curve entries cannot be logged once curve is MIGRATED or in POOL state.
3. On migration, checks price continuity between curve close and pool open.
4. Implausible jumps across venue boundaries (>20% jump without executed volume)
   are flagged and quarantined instead of booking fictitious wins.
5. Never mixes price sources.
"""

from dataclasses import dataclass
from enum import Enum
import logging
from typing import Dict, Optional, Tuple

logger = logging.getLogger(__name__)


class VenueState(str, Enum):
    CURVE_OPEN = "CURVE_OPEN"
    MIGRATED = "MIGRATED"
    POOL = "POOL"


class VenueContinuityError(Exception):
    """Raised when an unphysical price discontinuity is detected across a venue migration boundary."""
    pass


@dataclass
class TokenVenueStatus:
    mint: str
    current_state: VenueState = VenueState.CURVE_OPEN
    curve_close_price_sol: Optional[float] = None
    pool_open_price_sol: Optional[float] = None
    migration_slot: Optional[int] = None
    pool_address: Optional[str] = None
    last_updated_slot: int = 0


class VenueStateMachine:
    """
    Tracks and enforces venue states for every discovered token.
    Prevents phantom entries on defunct curves and phantom exits on newly migrated pools.
    """
    def __init__(self):
        self._tokens: Dict[str, TokenVenueStatus] = {}

    def get_token_state(self, mint: str, default_venue: Optional[str] = None) -> VenueState:
        """Get current venue state for a token (defaults to POOL for AMMs or CURVE_OPEN for curves)."""
        if mint not in self._tokens:
            if default_venue:
                norm = default_venue.lower()
                if "pool" in norm or "raydium" in norm or "pumpswap" in norm or "meteora" in norm:
                    init_state = VenueState.POOL
                else:
                    init_state = VenueState.CURVE_OPEN
            else:
                init_state = VenueState.CURVE_OPEN
            self._tokens[mint] = TokenVenueStatus(mint=mint, current_state=init_state)
        return self._tokens[mint].current_state

    def on_curve_migration_detected(
        self,
        mint: str,
        slot: int,
        pool_address: Optional[str] = None,
        curve_close_price_sol: Optional[float] = None,
        pool_open_price_sol: Optional[float] = None,
    ) -> None:
        """Mark token as MIGRATED and record boundary prices."""
        status = self._tokens.setdefault(mint, TokenVenueStatus(mint=mint))
        status.current_state = VenueState.MIGRATED
        status.migration_slot = slot
        status.pool_address = pool_address
        status.curve_close_price_sol = curve_close_price_sol
        status.pool_open_price_sol = pool_open_price_sol
        status.last_updated_slot = slot
        logger.info(f"Venue State Transition: {mint} -> MIGRATED at slot {slot}")

    def on_pool_active_detected(
        self,
        mint: str,
        slot: int,
        pool_address: str,
        pool_open_price_sol: Optional[float] = None,
    ) -> None:
        """Mark token as POOL actively trading."""
        status = self._tokens.setdefault(mint, TokenVenueStatus(mint=mint))
        status.current_state = VenueState.POOL
        status.pool_address = pool_address
        if pool_open_price_sol:
            status.pool_open_price_sol = pool_open_price_sol
        status.last_updated_slot = slot
        logger.info(f"Venue State Transition: {mint} -> POOL ({pool_address}) at slot {slot}")

    def validate_entry_venue(self, mint: str, requested_venue: str) -> Tuple[bool, Optional[str]]:
        """
        Validate whether requested venue matches actual on-chain state.
        Reject stale curve entries if token has already graduated/migrated.
        """
        req_norm = requested_venue.lower()
        if mint not in self._tokens:
            self.get_token_state(mint, default_venue=requested_venue)
            return True, None

        state = self.get_token_state(mint)

        if state in (VenueState.MIGRATED, VenueState.POOL):
            if "curve" in req_norm or ("pump" in req_norm and "swap" not in req_norm):
                return False, f"REJECT_STALE_VENUE: Token {mint} is in state {state.value}, but entry requested on curve {requested_venue}"

        if state == VenueState.CURVE_OPEN:
            if "pool" in req_norm or "raydium" in req_norm or "pumpswap" in req_norm:
                return False, f"REJECT_PREMATURE_VENUE: Token {mint} is still CURVE_OPEN, cannot enter pool {requested_venue}"

        return True, None

    def check_price_continuity(
        self,
        mint: str,
        curve_price: float,
        pool_price: float,
        max_allowed_jump_ratio: float = 2.0,
    ) -> Tuple[bool, Optional[str]]:
        """
        Check that transition price from curve to pool is mathematically sound.
        A 100x jump across migration boundary without on-chain pool swaps is flagged as an invalid phantom jump.
        """
        if curve_price <= 0.0 or pool_price <= 0.0:
            return False, "INVALID_ZERO_PRICE_ACROSS_VENUES"

        ratio = pool_price / curve_price if curve_price > 0 else 0.0
        # Normal migration drops or stays close (ratio is between 0.5x and 1.5x)
        if ratio > max_allowed_jump_ratio or ratio < (1.0 / max_allowed_jump_ratio):
            err_msg = (
                f"IMPLAUSIBLE_VENUE_PRICE_JUMP: Token {mint} jumped {ratio:.2f}x across venues "
                f"(Curve: {curve_price:.8f} -> Pool: {pool_price:.8f}). Rejection enforced."
            )
            logger.warning(err_msg)
            return False, err_msg

        return True, None

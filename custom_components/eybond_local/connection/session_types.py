"""Shared types and constants for the callback session registry.

This module contains the shared types and constants used by session_registry,
session_observer, and ownership_manager to avoid circular imports.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

from ..collector_identity import (
    identity_source_is_strong as _identity_source_is_strong,
    normalize_pn as _normalize_pn,
)

# Normalized session lifecycle states.
SESSION_STATE_ACCEPTED = "accepted"
SESSION_STATE_IDENTIFIED_WEAK = "identified_weak"
SESSION_STATE_IDENTIFIED_STRONG = "identified_strong"
SESSION_STATE_CLAIMED = "claimed"
SESSION_STATE_ACTIVE = "active"
SESSION_STATE_CLOSED = "closed"

# Listener inventory states that mean the socket is routed/live.
_ACTIVE_INVENTORY_STATES = frozenset({"routed_at_text", "routed_framed"})
_CLAIMED_INVENTORY_STATES = frozenset({"claimed"})
_CLOSED_INVENTORY_STATES = frozenset(
    {"closed_disconnected", "closed_no_payload", "parked_peer_closed"}
)
_UNDISCOVERABLE_INVENTORY_STATES = frozenset(
    {
        "route_identity_mismatch",
        "waiting_for_route_identity",
        "parked_waiting_for_identity",
    }
)


def _state_from_inventory(inventory_state: str, identity_source: str) -> str:
    """Map a listener inventory state + identity source to a registry state."""

    if inventory_state in _ACTIVE_INVENTORY_STATES:
        return SESSION_STATE_ACTIVE
    if inventory_state in _CLAIMED_INVENTORY_STATES:
        return SESSION_STATE_CLAIMED
    if inventory_state in _CLOSED_INVENTORY_STATES:
        return SESSION_STATE_CLOSED
    if _identity_source_is_strong(identity_source):
        return SESSION_STATE_IDENTIFIED_STRONG
    return SESSION_STATE_IDENTIFIED_WEAK


@dataclass(frozen=True, slots=True)
class PermanentOwnedSessionCertification:
    """A registry-issued permanent-owner recovery capability (Batch 8).

    The typed, exact-type capability a recovery run UNDER an existing permanent
    owner produces — deliberately DISTINCT from the onboarding prepared-handoff
    slot. It certifies exactly one ``(owner_id, session_id, collector_pn)``
    triple and asserts nothing about an ownership transfer. Only the registry
    constructs it (``certify_permanent_owned_session``) and only the registry
    re-verifies it (``reverify_permanent_owned_session``); a forged look-alike
    fails the strict ``type() is`` re-check at commit time.
    """

    owner_id: str
    session_id: str
    collector_pn: str


@dataclass(frozen=True, slots=True)
class CallbackSession:
    """One normalized inbound collector session with ownership state."""

    session_id: str
    peer_ip: str = ""
    peer_port: int = 0
    listener_port: int = 0
    protocol_shape: str = ""
    session_protocol: str = ""
    collector_pn: str = ""
    identity_source: str = ""
    state: str = SESSION_STATE_ACCEPTED
    owner_entry_id: str = ""
    # The original observed session mapping (listener inventory shape), kept so
    # consumers can work with the raw dict without re-deriving fields. Coalescing
    # keeps the winning session's raw mapping.
    raw: Mapping[str, object] = field(default_factory=dict)

    @property
    def has_strong_identity(self) -> bool:
        return _identity_source_is_strong(self.identity_source)

    @property
    def claimed(self) -> bool:
        return bool(self.owner_entry_id)

    @property
    def discoverable(self) -> bool:
        """Return whether this session is safe to publish as a device candidate."""

        inventory_state = str(self.raw.get("state") or "").strip().lower()
        if inventory_state == "route_identity_mismatch":
            # A weak mismatch is only an ambiguous heartbeat prefix. A strong
            # mismatch, however, is positive evidence that this is a different
            # fully identified collector and therefore a valid new candidate.
            return self.state != SESSION_STATE_CLOSED and self.has_strong_identity
        return (
            self.state != SESSION_STATE_CLOSED
            and inventory_state not in _UNDISCOVERABLE_INVENTORY_STATES
        )


@dataclass(slots=True)
class _Claim:
    """One owner's claim over a session and/or durable collector identity."""

    entry_id: str
    collector_pn: str = ""
    session_id: str = ""
    session_protocol: str = ""
    handoff_pending: bool = False

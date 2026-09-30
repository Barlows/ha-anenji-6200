"""Session observation and coalescing for the callback session registry.

This module extracts the session observation, normalization, and coalescing
logic from CallbackSessionRegistry into a focused helper class.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field, replace
from types import MappingProxyType

from ..collector_identity import (
    identity_source_is_strong as _identity_source_is_strong,
    normalize_pn as _normalize_pn,
    pn_is_same_identity as _pn_is_same_identity,
    prefer_full_pn as _prefer_full_pn,
)
from .session_registry import (
    SESSION_STATE_ACCEPTED,
    SESSION_STATE_ACTIVE,
    SESSION_STATE_CLAIMED,
    SESSION_STATE_CLOSED,
    SESSION_STATE_IDENTIFIED_STRONG,
    SESSION_STATE_IDENTIFIED_WEAK,
    CallbackSession,
    _ACTIVE_INVENTORY_STATES,
    _CLAIMED_INVENTORY_STATES,
    _CLOSED_INVENTORY_STATES,
    _UNDISCOVERABLE_INVENTORY_STATES,
    _state_from_inventory,
)


@dataclass(slots=True)
class SessionObserver:
    """Observes, normalizes, and coalesces inbound collector sessions.

    This class handles the read-only session observation pipeline:
    raw session dicts -> normalized CallbackSession -> coalesced view.

    It does NOT own any mutable state (claims, handoffs) -- it is a pure
    observer that can be unit-tested independently.
    """

    sessions_source: Callable[[], Iterable[Mapping[str, object]]] | None = None

    def raw_sessions(self) -> tuple[Mapping[str, object], ...]:
        """Return raw session dicts from the listener inventory."""
        if self.sessions_source is None:
            return ()
        try:
            return tuple(self.sessions_source() or ())
        except Exception:
            return ()

    @staticmethod
    def normalize(raw: Mapping[str, object]) -> CallbackSession:
        """Normalize a raw session dict into a CallbackSession."""
        identity_source = str(raw.get("collector_identity_source") or "").strip()
        inventory_state = str(raw.get("state") or "").strip()
        return CallbackSession(
            session_id=str(raw.get("session_id") or "").strip(),
            peer_ip=str(raw.get("peer_ip") or "").strip(),
            peer_port=int(raw.get("peer_port") or 0),
            listener_port=int(raw.get("listener_port") or 0),
            protocol_shape=str(raw.get("protocol_shape") or "").strip(),
            session_protocol=str(raw.get("session_protocol") or "").strip(),
            collector_pn=_normalize_pn(raw.get("collector_pn")),
            identity_source=identity_source,
            state=_state_from_inventory(inventory_state, identity_source),
            raw=MappingProxyType(dict(raw)),
        )

    def coalesce(
        self,
        sessions: Iterable[CallbackSession],
    ) -> list[CallbackSession]:
        """Collapse short/full PN duplicates of one collector into one session.

        Distinct full PNs are always kept distinct -- this is what keeps two
        collectors behind one NAT peer IP separate. Peer IP is never used to
        merge or split.
        """
        coalesced: list[CallbackSession] = []
        pn_index: dict[str, int] = {}
        for session in sessions:
            if not session.collector_pn:
                coalesced.append(session)
                continue
            pn = session.collector_pn
            idx = pn_index.get(pn)
            if idx is not None:
                existing = coalesced[idx]
                if existing.collector_pn and _pn_is_same_identity(existing.collector_pn, pn):
                    keep_new = False
                    if session.has_strong_identity and not existing.has_strong_identity:
                        keep_new = True
                    elif (
                        session.has_strong_identity == existing.has_strong_identity
                        and len(pn) > len(existing.collector_pn)
                    ):
                        keep_new = True
                    if keep_new:
                        merged_pn = _prefer_full_pn(existing.collector_pn, pn)
                        coalesced[idx] = replace(session, collector_pn=merged_pn)
                    continue
            pn_index[pn] = len(coalesced)
            coalesced.append(session)
        return coalesced

    def normalized_sessions(self) -> list[CallbackSession]:
        """Return per-socket normalized sessions (pre-coalesce) with owner attached."""
        normalized = [self.normalize(raw) for raw in self.raw_sessions()]
        return [session for session in normalized if session.session_id]

    def observed_sessions(self) -> tuple[CallbackSession, ...]:
        """Return coalesced observed sessions with ownership state attached."""
        return tuple(self.coalesce(self.normalized_sessions()))

    def observed_sessions_per_socket(self) -> tuple[CallbackSession, ...]:
        """Return per-socket sessions (no short/full coalescing), owner attached."""
        return tuple(self.normalized_sessions())

    def list_unclaimed_sessions(self) -> tuple[CallbackSession, ...]:
        """Return observed sessions that no config entry owns yet."""
        return tuple(
            session
            for session in self.observed_sessions()
            if not session.owner_entry_id and session.discoverable
        )

    def current_session_for_pn(
        self,
        collector_pn: object,
        *,
        require_exact: bool = False,
    ) -> CallbackSession | None:
        """Return the best currently observed socket for one collector PN."""
        pn = _normalize_pn(collector_pn)
        if not pn:
            return None
        best: CallbackSession | None = None
        best_rank: tuple[int, int, int] | None = None
        for session in self.normalized_sessions():
            if session.state == SESSION_STATE_CLOSED:
                continue
            if require_exact:
                if session.collector_pn != pn:
                    continue
            elif not _pn_is_same_identity(session.collector_pn, pn):
                continue
            raw_state = str(session.raw.get("state") or "").strip().lower()
            rank = (
                1 if raw_state in _ACTIVE_INVENTORY_STATES else 0,
                1 if session.has_strong_identity else 0,
                len(session.collector_pn),
            )
            if best_rank is None or rank >= best_rank:
                best = session
                best_rank = rank
        return best

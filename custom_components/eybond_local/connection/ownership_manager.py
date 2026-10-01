"""Ownership claim management for the callback session registry.

This module extracts the ownership claim logic from CallbackSessionRegistry
into a focused helper class that handles claims, single-owner enforcement,
and identity enrichment.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..collector_identity import (
    normalize_pn as _normalize_pn,
    pn_is_same_identity as _pn_is_same_identity,
    prefer_full_pn as _prefer_full_pn,
)
from .session_types import (
    SESSION_STATE_ACTIVE,
    SESSION_STATE_CLAIMED,
    SESSION_STATE_CLOSED,
    CallbackSession,
    _Claim,
)


@dataclass(slots=True)
class OwnershipManager:
    """Manages ownership claims and single-owner enforcement.

    This class handles the mutable claim state: creating claims, enriching
    them, enforcing single ownership, and releasing claims.

    It does NOT own the session observation pipeline -- it receives sessions
    from the caller (via SessionObserver) and attaches ownership state.
    """

    _claims: dict[str, _Claim] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self._claims is None:
            self._claims = {}

    def _owner_for_session(self, session: CallbackSession) -> str:
        """Return the entry id that owns this session, or empty string."""
        for entry_id, claim in self._claims.items():
            if claim.session_id and claim.session_id == session.session_id:
                return entry_id
            if claim.collector_pn and _pn_is_same_identity(
                claim.collector_pn, session.collector_pn
            ):
                return entry_id
        return ""

    def owner_for_pn(self, collector_pn: object) -> str:
        """Return the entry id that owns a durable PN identity, if any."""
        pn = _normalize_pn(collector_pn)
        if not pn:
            return ""
        for entry_id, claim in self._claims.items():
            if claim.collector_pn and _pn_is_same_identity(claim.collector_pn, pn):
                return entry_id
        return ""

    def attach_owner(self, session: CallbackSession) -> CallbackSession:
        """Attach ownership state to a session."""
        owner = self._owner_for_session(session)
        if not owner:
            return session
        state = session.state
        if state not in (SESSION_STATE_ACTIVE, SESSION_STATE_CLOSED):
            state = SESSION_STATE_CLAIMED
        from dataclasses import replace
        return replace(session, owner_entry_id=owner, state=state)

    def claim(
        self,
        entry_id: str,
        *,
        collector_pn: object = "",
        session_id: object = "",
        session_protocol: object = "",
        observed: tuple[CallbackSession, ...] = (),
    ) -> CallbackSession | None:
        """Claim a session for one entry by durable PN and/or transient session id."""
        entry_id = str(entry_id or "").strip()
        if not entry_id:
            raise ValueError("entry_id_required")
        pn = _normalize_pn(collector_pn)
        sid = str(session_id or "").strip()

        if pn:
            other = self.owner_for_pn(pn)
            if other and other != entry_id:
                raise ValueError(f"session_already_claimed:{pn}:{other}")

        existing = self._claims.get(entry_id)
        if existing is not None:
            if pn and existing.collector_pn and not _pn_is_same_identity(
                existing.collector_pn, pn
            ):
                raise ValueError(f"claim_identity_mismatch:{existing.collector_pn}:{pn}")
            if sid and existing.session_id and sid != existing.session_id:
                raise ValueError(f"claim_session_mismatch:{existing.session_id}:{sid}")

        matched: CallbackSession | None = None
        for session in observed:
            if sid and session.session_id == sid:
                matched = session
                break
            if pn and _pn_is_same_identity(pn, session.collector_pn):
                if matched is None or (
                    session.has_strong_identity and not matched.has_strong_identity
                ):
                    matched = session

        if matched is not None and matched.collector_pn:
            for known in (pn, existing.collector_pn if existing is not None else ""):
                if known and not _pn_is_same_identity(known, matched.collector_pn):
                    raise ValueError(
                        f"claim_session_identity_mismatch:{known}:{matched.collector_pn}"
                    )
        if matched is not None:
            if matched.collector_pn:
                pn = _prefer_full_pn(pn, matched.collector_pn)
            if not sid:
                sid = matched.session_id
        protocol = str(session_protocol or "").strip() or (
            matched.session_protocol if matched else ""
        )

        if existing is None:
            self._claims[entry_id] = _Claim(
                entry_id=entry_id,
                collector_pn=pn,
                session_id=sid,
                session_protocol=protocol,
            )
        else:
            if pn and existing.collector_pn and not _pn_is_same_identity(
                existing.collector_pn, pn
            ):
                raise ValueError(f"claim_identity_mismatch:{existing.collector_pn}:{pn}")
            existing.collector_pn = _prefer_full_pn(existing.collector_pn, pn)
            if not existing.session_id:
                existing.session_id = sid
            if not existing.session_protocol:
                existing.session_protocol = protocol
        if matched is None:
            return None
        return self.attach_owner(matched)

    def claim_identity(self, entry_id: str, collector_pn: object) -> None:
        """Record a PN-ONLY durable ownership claim WITHOUT scanning sessions."""
        entry_id = str(entry_id or "").strip()
        if not entry_id:
            raise ValueError("entry_id_required")
        pn = _normalize_pn(collector_pn)
        if not pn:
            raise ValueError("collector_pn_required")
        other = self.owner_for_pn(pn)
        if other and other != entry_id:
            raise ValueError(f"session_already_claimed:{pn}:{other}")
        existing = self._claims.get(entry_id)
        if existing is None:
            self._claims[entry_id] = _Claim(entry_id=entry_id, collector_pn=pn)
            return None
        if existing.collector_pn:
            if not _pn_is_same_identity(existing.collector_pn, pn):
                raise ValueError(
                    f"claim_identity_mismatch:{existing.collector_pn}:{pn}"
                )
            existing.collector_pn = _prefer_full_pn(existing.collector_pn, pn)
            return None
        if existing.session_id or existing.session_protocol or existing.handoff_pending:
            raise ValueError("claim_identity_transient_claim_conflict")
        existing.collector_pn = pn
        return None

    def claim_session(
        self,
        entry_id: str,
        *,
        session_id: object,
        observed: tuple[CallbackSession, ...] = (),
    ) -> None:
        """Record a TRANSIENT claim that owns exactly one session id."""
        entry_id = str(entry_id or "").strip()
        if not entry_id:
            raise ValueError("entry_id_required")
        sid = str(session_id or "").strip()
        if not sid:
            raise ValueError("session_id_required")

        for other_id, other in self._claims.items():
            if other_id != entry_id and other.session_id == sid:
                raise ValueError(f"session_already_claimed:{sid}:{other_id}")

        observed_pn = ""
        for session in observed:
            if session.session_id != sid:
                continue
            observed_pn = session.collector_pn
            if observed_pn:
                owner = self.owner_for_pn(observed_pn)
                if owner and owner != entry_id:
                    raise ValueError(f"session_already_claimed:{observed_pn}:{owner}")
            break

        existing = self._claims.get(entry_id)
        if existing is not None:
            if existing.session_id and existing.session_id != sid:
                raise ValueError(f"claim_session_mismatch:{existing.session_id}:{sid}")
            if (
                existing.collector_pn
                and observed_pn
                and not _pn_is_same_identity(existing.collector_pn, observed_pn)
            ):
                raise ValueError(
                    f"claim_session_identity_mismatch:{existing.collector_pn}:{observed_pn}"
                )
            existing.session_id = sid
            return
        self._claims[entry_id] = _Claim(entry_id=entry_id, session_id=sid)

    def promote_claim_to_full_pn(self, entry_id: str, full_pn: object) -> bool:
        """Promote a claim to the confirmed full durable PN of the SAME collector."""
        entry_id = str(entry_id or "").strip()
        claim = self._claims.get(entry_id)
        if claim is None:
            return False
        pn = _normalize_pn(full_pn)
        if not pn:
            return False
        other = self.owner_for_pn(pn)
        if other and other != entry_id:
            raise ValueError(f"session_already_claimed:{pn}:{other}")
        current = claim.collector_pn
        if current and not _pn_is_same_identity(current, pn):
            raise ValueError(f"promote_identity_mismatch:{current}:{pn}")
        claim.collector_pn = _prefer_full_pn(current, pn)
        return True

    def claimed_session_id(self, entry_id: str) -> str:
        """Return the transient session id recorded on one entry's claim."""
        claim = self._claims.get(str(entry_id or "").strip())
        return claim.session_id if claim is not None else ""

    def release(self, entry_id: str) -> bool:
        """Release the claim held by exactly one owner."""
        return self._claims.pop(str(entry_id or "").strip(), None) is not None

    def claimed_identity(self, entry_id: str) -> str:
        """Return the durable PN currently claimed by one entry."""
        claim = self._claims.get(str(entry_id or "").strip())
        return claim.collector_pn if claim else ""

    def get_claim(self, entry_id: str) -> _Claim | None:
        """Return the claim for one entry, or None."""
        return self._claims.get(str(entry_id or "").strip())

    def get_all_claims(self) -> dict[str, _Claim]:
        """Return all claims (for diagnostics)."""
        return self._claims

"""Owner reference counting for the shared collector listener.

This module extracts the owner counting logic from _SharedEybondListener
into a focused helper class that manages reference counts for payload
owners, AT owners, and session protocol owners.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class OwnerCounter:
    """Manages owner reference counts for the shared listener.

    This class handles the mutable owner count state: registering and
    unregistering owners, and decrementing counts safely.

    It does NOT own the connection or session state -- it is a pure
    counter that can be unit-tested independently.
    """

    _payload_owner_counts: dict[str, int] = field(default_factory=dict)
    _at_owner_counts: dict[str, int] = field(default_factory=dict)
    _payload_pn_owner_counts: dict[str, int] = field(default_factory=dict)
    _at_pn_owner_counts: dict[str, int] = field(default_factory=dict)
    _session_protocol_owner_counts: dict[str, int] = field(default_factory=dict)

    def register_payload_owner(self, collector_ip: str) -> None:
        """Register a payload owner by collector IP."""
        owner = str(collector_ip or "").strip()
        self._payload_owner_counts[owner] = self._payload_owner_counts.get(owner, 0) + 1

    def unregister_payload_owner(self, collector_ip: str) -> None:
        """Unregister a payload owner by collector IP."""
        self._decrement_owner_count(self._payload_owner_counts, collector_ip)

    def register_payload_pn_owner(self, collector_pn: str) -> None:
        """Register a payload owner by collector PN."""
        owner = str(collector_pn or "").strip()
        if not owner:
            return
        self._payload_pn_owner_counts[owner] = self._payload_pn_owner_counts.get(owner, 0) + 1

    def unregister_payload_pn_owner(self, collector_pn: str) -> None:
        """Unregister a payload owner by collector PN."""
        self._decrement_owner_count(self._payload_pn_owner_counts, collector_pn)

    def register_at_owner(self, collector_ip: str) -> None:
        """Register an AT owner by collector IP."""
        owner = str(collector_ip or "").strip()
        self._at_owner_counts[owner] = self._at_owner_counts.get(owner, 0) + 1

    def unregister_at_owner(self, collector_ip: str) -> None:
        """Unregister an AT owner by collector IP."""
        self._decrement_owner_count(self._at_owner_counts, collector_ip)

    def register_at_pn_owner(self, collector_pn: str) -> None:
        """Register an AT owner by collector PN."""
        owner = str(collector_pn or "").strip()
        if not owner:
            return
        self._at_pn_owner_counts[owner] = self._at_pn_owner_counts.get(owner, 0) + 1

    def unregister_at_pn_owner(self, collector_pn: str) -> None:
        """Unregister an AT owner by collector PN."""
        self._decrement_owner_count(self._at_pn_owner_counts, collector_pn)

    def register_session_protocol_owner(self, session_protocol: str) -> None:
        """Register a session protocol owner."""
        owner = str(session_protocol or "").strip().lower()
        if not owner:
            return
        self._session_protocol_owner_counts[owner] = (
            self._session_protocol_owner_counts.get(owner, 0) + 1
        )

    def unregister_session_protocol_owner(self, session_protocol: str) -> None:
        """Unregister a session protocol owner."""
        self._decrement_owner_count(self._session_protocol_owner_counts, session_protocol)

    def _decrement_owner_count(self, counts: dict[str, int], key: str) -> None:
        """Decrement an owner count, removing the entry when it reaches zero.

        An empty key is a legitimate owner: ``register_payload_owner("")`` and
        ``register_at_owner("")`` register one (a listener owner with no fixed
        collector IP, which ``_has_owner_for_remote_ip`` treats as owning every
        collector). It must therefore be removable too, or the entry leaks and
        the listener claims all incoming collectors until Home Assistant
        restarts.
        """
        owner = str(key or "").strip()
        current = counts.get(owner, 0)
        if current <= 1:
            counts.pop(owner, None)
        else:
            counts[owner] = current - 1

    def clear(self) -> None:
        """Clear all owner counts."""
        self._payload_owner_counts.clear()
        self._at_owner_counts.clear()
        self._payload_pn_owner_counts.clear()
        self._at_pn_owner_counts.clear()
        self._session_protocol_owner_counts.clear()

    def get_payload_owner_count(self, collector_ip: str) -> int:
        """Return the payload owner count for a collector IP."""
        return self._payload_owner_counts.get(str(collector_ip or "").strip(), 0)

    def get_at_owner_count(self, collector_ip: str) -> int:
        """Return the AT owner count for a collector IP."""
        return self._at_owner_counts.get(str(collector_ip or "").strip(), 0)

"""Route reservation management for the shared collector listener.

This module extracts the exclusive route reservation logic from
_SharedEybondListener into a focused helper class.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class ExclusiveCollectorRouteReservation:
    """One temporary route that must win over normal runtime activation."""

    collector_ip: str
    collector_pn: str
    baseline_session_ids: frozenset[str]
    transparent: bool
    expected_session_protocol: str


@dataclass(slots=True)
class RouteReservationManager:
    """Manages exclusive route reservations for the shared listener.

    This class handles the mutable route reservation state: reserving
    routes, releasing routes, and checking route matches.

    It does NOT own the listener or the connection state -- it is a pure
    route manager that can be unit-tested independently.
    """

    _exclusive_route_seq: int = 0
    _exclusive_routes: dict[int, ExclusiveCollectorRouteReservation] = field(default_factory=dict)
    _pending_route_lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    def register_exclusive_collector_route(
        self,
        *,
        collector_ip: str,
        collector_pn: str,
        transparent: bool = False,
        expected_session_protocol: str = "",
        baseline_session_ids: frozenset[str] = frozenset(),
    ) -> int:
        """Reserve matching new callbacks for a temporary proxy route.

        Runtime transports remain registered so they can resume immediately
        after the tool stops, but they must not consume the reconnect that a
        proxy/shadow route is waiting for.
        """
        self._exclusive_route_seq += 1
        token = self._exclusive_route_seq
        self._exclusive_routes[token] = ExclusiveCollectorRouteReservation(
            collector_ip=str(collector_ip or "").strip(),
            collector_pn=str(collector_pn or "").strip(),
            baseline_session_ids=baseline_session_ids,
            transparent=transparent,
            expected_session_protocol=str(expected_session_protocol or "").strip(),
        )
        return token

    def release_exclusive_collector_route(self, token: int) -> bool:
        """Release an exclusive route reservation."""
        return self._exclusive_routes.pop(token, None) is not None

    def get_active_routes(self) -> dict[int, ExclusiveCollectorRouteReservation]:
        """Get all active route reservations."""
        return self._exclusive_routes

    def clear(self) -> None:
        """Clear all route reservations."""
        self._exclusive_routes.clear()

    def has_active_routes(self) -> bool:
        """Return whether any route reservations are active."""
        return bool(self._exclusive_routes)

    def get_route_for_session(
        self,
        session_id: str,
        collector_ip: str,
        collector_pn: str,
    ) -> ExclusiveCollectorRouteReservation | None:
        """Get the active route reservation matching a session, if any."""
        for route in self._exclusive_routes.values():
            if route.baseline_session_ids and session_id in route.baseline_session_ids:
                continue
            if route.collector_ip and route.collector_ip != collector_ip:
                continue
            if route.collector_pn and route.collector_pn != collector_pn:
                continue
            return route
        return None

"""Connection management for the shared collector listener.

This module extracts the connection and pending socket management logic
from _SharedEybondListener into a focused helper class.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Callable

from .connections import _CollectorAtConnection, _CollectorConnection

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ConnectionManager:
    """Manages connections and pending sockets for the shared listener.

    This class handles the mutable connection state: tracking connections
    by session ID and PN, managing pending sockets, and providing
    connection lifecycle operations.

    It does NOT own the listener or the owner counting -- it is a pure
    connection manager that can be unit-tested independently.
    """

    _connections: dict[str, _CollectorConnection] = field(default_factory=dict)
    _at_connections: dict[str, _CollectorAtConnection] = field(default_factory=dict)
    _connections_by_pn: dict[str, _CollectorConnection] = field(default_factory=dict)
    _at_connections_by_pn: dict[str, _CollectorAtConnection] = field(default_factory=dict)
    _session_payload_connections: dict[str, _CollectorConnection] = field(default_factory=dict)
    _session_at_connections: dict[str, _CollectorAtConnection] = field(default_factory=dict)
    _pending_sockets: dict[str, "_PendingCollectorSocket"] = field(default_factory=dict)
    _last_connection_ip: str = ""
    _last_at_connection_ip: str = ""
    _last_pending_ip: str = ""

    def add_connection(self, session_id: str, connection: _CollectorConnection) -> None:
        """Add a framed connection."""
        self._connections[session_id] = connection

    def add_at_connection(self, session_id: str, connection: _CollectorAtConnection) -> None:
        """Add an AT connection."""
        self._at_connections[session_id] = connection

    def add_connection_by_pn(self, collector_pn: str, connection: _CollectorConnection) -> None:
        """Add a framed connection by PN."""
        self._connections_by_pn[collector_pn] = connection

    def add_at_connection_by_pn(self, collector_pn: str, connection: _CollectorAtConnection) -> None:
        """Add an AT connection by PN."""
        self._at_connections_by_pn[collector_pn] = connection

    def add_session_payload_connection(self, session_id: str, connection: _CollectorConnection) -> None:
        """Add a session payload connection."""
        self._session_payload_connections[session_id] = connection

    def add_session_at_connection(self, session_id: str, connection: _CollectorAtConnection) -> None:
        """Add a session AT connection."""
        self._session_at_connections[session_id] = connection

    def get_connection(self, session_id: str) -> _CollectorConnection | None:
        """Get a framed connection by session ID."""
        return self._connections.get(session_id)

    def get_at_connection(self, session_id: str) -> _CollectorAtConnection | None:
        """Get an AT connection by session ID."""
        return self._at_connections.get(session_id)

    def get_connection_by_pn(self, collector_pn: str) -> _CollectorConnection | None:
        """Get a framed connection by PN."""
        return self._connections_by_pn.get(collector_pn)

    def get_at_connection_by_pn(self, collector_pn: str) -> _CollectorAtConnection | None:
        """Get an AT connection by PN."""
        return self._at_connections_by_pn.get(collector_pn)

    def remove_connection(self, session_id: str) -> None:
        """Remove a framed connection."""
        self._connections.pop(session_id, None)
        self._session_payload_connections.pop(session_id, None)

    def remove_at_connection(self, session_id: str) -> None:
        """Remove an AT connection."""
        self._at_connections.pop(session_id, None)
        self._session_at_connections.pop(session_id, None)

    def add_pending_socket(self, session_id: str, socket: "_PendingCollectorSocket") -> None:
        """Add a pending socket."""
        self._pending_sockets[session_id] = socket
        self._last_pending_ip = socket.remote_ip

    def get_pending_socket(self, session_id: str) -> "_PendingCollectorSocket | None":
        """Get a pending socket by session ID."""
        return self._pending_sockets.get(session_id)

    def remove_pending_socket(self, session_id: str) -> "_PendingCollectorSocket | None":
        """Remove and return a pending socket."""
        return self._pending_sockets.pop(session_id, None)

    def get_pending_sockets(self) -> dict[str, "_PendingCollectorSocket"]:
        """Get all pending sockets."""
        return self._pending_sockets

    def unique_connections(self) -> list[_CollectorConnection]:
        """Get all unique framed connections."""
        seen: set[str] = set()
        result: list[_CollectorConnection] = []
        for conn in self._connections.values():
            if id(conn) not in seen:
                seen.add(id(conn))
                result.append(conn)
        return result

    def unique_at_connections(self) -> list[_CollectorAtConnection]:
        """Get all unique AT connections."""
        seen: set[str] = set()
        result: list[_CollectorAtConnection] = []
        for conn in self._at_connections.values():
            if id(conn) not in seen:
                seen.add(id(conn))
                result.append(conn)
        return result

    def set_last_connection_ip(self, ip: str) -> None:
        """Set the last connection IP."""
        self._last_connection_ip = ip

    def set_last_at_connection_ip(self, ip: str) -> None:
        """Set the last AT connection IP."""
        self._last_at_connection_ip = ip

    def get_last_connection_ip(self) -> str:
        """Get the last connection IP."""
        return self._last_connection_ip

    def get_last_at_connection_ip(self) -> str:
        """Get the last AT connection IP."""
        return self._last_at_connection_ip

    def get_last_pending_ip(self) -> str:
        """Get the last pending IP."""
        return self._last_pending_ip

    async def disconnect_all(self) -> None:
        """Disconnect all connections and clear pending sockets."""
        for pending in tuple(self._pending_sockets.values()):
            if hasattr(pending, "writer") and pending.writer is not None:
                try:
                    pending.writer.close()
                except Exception:
                    logger.debug("Failed to close pending socket", exc_info=True)
        self._pending_sockets.clear()

        for connection in self.unique_connections():
            try:
                await connection.disconnect()
            except Exception:
                logger.debug("Failed to disconnect connection", exc_info=True)
        self._connections.clear()
        self._connections_by_pn.clear()
        self._session_payload_connections.clear()

        for connection in self.unique_at_connections():
            try:
                await connection.disconnect()
            except Exception:
                logger.debug("Failed to disconnect AT connection", exc_info=True)
        self._at_connections.clear()
        self._at_connections_by_pn.clear()
        self._session_at_connections.clear()

        self._last_connection_ip = ""
        self._last_at_connection_ip = ""
        self._last_pending_ip = ""

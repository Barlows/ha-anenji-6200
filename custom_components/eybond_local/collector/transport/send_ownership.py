"""Pin a queued operation to its physical socket, not a mutable connection slot."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Protocol


class SocketConnection(Protocol):
    _writer: asyncio.StreamWriter | None
    _run_epoch: int

    @property
    def connected(self) -> bool: ...


@dataclass(frozen=True, slots=True)
class SocketSendOwner:
    writer: asyncio.StreamWriter
    epoch: int

    @classmethod
    def capture(cls, connection: SocketConnection) -> SocketSendOwner:
        writer = connection._writer
        if writer is None or not connection.connected:
            raise ConnectionError("collector_not_connected")
        return cls(writer, connection._run_epoch)

    def check(self, connection: SocketConnection) -> None:
        if connection._writer is not self.writer or connection._run_epoch != self.epoch:
            # Not a request to reconnect/retry: the successor owns its own work.
            raise ConnectionError("collector_session_changed")
        if not connection.connected:
            raise ConnectionError("collector_not_connected")

    def check_reply(self, connection: SocketConnection) -> None:
        """A completed reply remains valid if that same peer closed after it.

        EOF alone does not undo an acknowledged operation. A successor run,
        however, must never acquire old reply metadata or bootstrap state.
        """
        if connection._run_epoch != self.epoch or (
            connection._writer is not None and connection._writer is not self.writer
        ):
            raise ConnectionError("collector_session_changed")


def finish_request_future(future: asyncio.Future) -> None:
    """Consume a disconnect error even if a queued write failed before awaiting it."""

    if not future.done():
        future.cancel()
    elif not future.cancelled():
        future.exception()

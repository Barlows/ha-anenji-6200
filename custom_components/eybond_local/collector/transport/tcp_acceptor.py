"""Owned TCP admission without asyncio.Server's accept/close race (CPython #109564).

Only socket admission lives here. Identity, framing and established stream
ownership belong to the shared collector listener. No event-loop monkeypatches.
"""

from __future__ import annotations

import asyncio
import errno
import logging
import socket
from collections.abc import Awaitable, Callable

from .common import _close_writer_bounded

logger = logging.getLogger(__name__)

_BACKLOG = 100
_MAX_ADMISSIONS = 100
_RESOURCE_ERRORS = {errno.EMFILE, errno.ENFILE, errno.ENOBUFS, errno.ENOMEM}


class CollectorTcpAcceptor:
    """Accept, prepare and hand off streams; stop joins every uncommitted handoff."""

    def __init__(
        self,
        sockets: list[socket.socket],
        handler: Callable[[asyncio.StreamReader, asyncio.StreamWriter], Awaitable[None]],
    ) -> None:
        self._sockets = sockets
        self._handler = handler
        self._loop = asyncio.get_running_loop()
        self._closing = False
        self._admissions: dict[asyncio.Task[None], socket.socket] = {}
        self._retry_handles: dict[socket.socket, asyncio.TimerHandle] = {}
        self._close_task: asyncio.Task[None] | None = None

    @classmethod
    async def start(cls, handler, host: str, port: int) -> CollectorTcpAcceptor:
        """Bind all resolved addresses, rolling back the whole bind on failure."""
        loop = asyncio.get_running_loop()
        addresses = await loop.getaddrinfo(
            host or None, port, type=socket.SOCK_STREAM, flags=socket.AI_PASSIVE,
        )
        sockets: list[socket.socket] = []
        try:
            for family, sock_type, proto, _, address in dict.fromkeys(addresses):
                sock = socket.socket(family, sock_type, proto)
                sockets.append(sock)
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                if family == socket.AF_INET6:
                    sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
                sock.setblocking(False)
                sock.bind(address)
                sock.listen(_BACKLOG)
            if not sockets:
                raise OSError("collector_listener_no_bind_addresses")
            acceptor = cls(sockets, handler)
            try:
                for sock in sockets:
                    acceptor._resume_accept(sock)
            except BaseException:
                acceptor.close()
                await acceptor.wait_closed()
                raise
            return acceptor
        except BaseException:
            for sock in sockets:
                sock.close()
            raise

    @property
    def sockets(self) -> tuple[socket.socket, ...]:
        return tuple(self._sockets) if not self._closing else ()

    def _resume_accept(self, sock: socket.socket) -> None:
        self._retry_handles.pop(sock, None)
        if not self._closing:
            self._loop.add_reader(sock.fileno(), self._accept_ready, sock)

    def _accept_ready(self, sock: socket.socket) -> None:
        if self._closing:
            return
        # Acceptance and raw-socket ownership are synchronous. Cancelling an
        # await of sock_accept after its future completed could lose the result.
        for _ in range(_BACKLOG + 1):
            try:
                client, _ = sock.accept()
            except ConnectionAbortedError:
                continue
            except (BlockingIOError, InterruptedError):
                return
            except OSError as exc:
                # Back off resource exhaustion without a busy selector loop.
                # The retry remains owned/cancellable by this acceptor.
                self._loop.remove_reader(sock.fileno())
                logger.warning("Collector listener cannot accept a socket: %s", exc)
                if exc.errno in _RESOURCE_ERRORS:
                    self._retry_handles[sock] = self._loop.call_later(1, self._resume_accept, sock)
                else:
                    self.close()
                return
            if self._closing or len(self._admissions) >= _MAX_ADMISSIONS:
                client.close()
            else:
                # The record exists outside the coroutine too: cancellation
                # before its first instruction must not leak the raw socket.
                admission = self._admit(client)
                try:
                    client.setblocking(False)
                    task = asyncio.create_task(admission, name="collector_tcp_admit")
                except BaseException:
                    admission.close()
                    client.close()
                    raise
                self._admissions[task] = client
                task.add_done_callback(self._admission_done)

    async def _admit(self, client: socket.socket) -> None:
        writer: asyncio.StreamWriter | None = None
        handed_off = False
        try:
            # Public socket-to-stream API. Unlike start_server, this transport
            # has no asyncio.Server to attach to after it has been closed.
            reader, writer = await asyncio.open_connection(sock=client)
            if not self._closing:
                await self._handler(reader, writer)
                handed_off = True
        finally:
            if not handed_off:
                if writer is None:
                    client.close()
                else:
                    await _close_writer_bounded(writer)

    def _admission_done(self, task: asyncio.Task[None]) -> None:
        client = self._admissions.pop(task, None)
        if client is None:
            return
        if task.cancelled():
            if client is not None:
                client.close()
            return
        error = task.exception()
        if error is not None:
            if client is not None:
                client.close()
            logger.error("Collector TCP admission failed", exc_info=error)

    def close(self) -> None:
        """Fence new handoffs before cancelling accept and closing bind sockets."""
        if self._closing:
            return
        self._closing = True
        for retry in self._retry_handles.values():
            retry.cancel()
        self._retry_handles.clear()
        for sock in self._sockets:
            self._loop.remove_reader(sock.fileno())
            sock.close()
        for task in tuple(self._admissions):
            task.cancel()
        self._close_task = asyncio.create_task(self._drain(), name="collector_tcp_close")

    async def _drain(self) -> None:
        # Any already-queued readiness callback sees _closing before accept.
        tasks = tuple(self._admissions)
        await asyncio.gather(*tasks, return_exceptions=True)
        for task in tasks:
            self._admission_done(task)
        self._sockets.clear()

    async def wait_closed(self) -> None:
        if self._close_task is None:
            raise RuntimeError("collector_listener_close_not_started")
        cancelled = False
        while not self._close_task.done():
            try:
                await asyncio.shield(self._close_task)
            except asyncio.CancelledError:
                cancelled = True
        self._close_task.result()
        if cancelled:
            raise asyncio.CancelledError

"""Real loopback sockets at the shared listener's close/admission boundary."""

import asyncio
import errno
import socket
from unittest.mock import AsyncMock, Mock, patch

import pytest

from custom_components.eybond_local.collector.transport import tcp_acceptor
from custom_components.eybond_local.collector.transport.tcp_acceptor import CollectorTcpAcceptor
from custom_components.eybond_local.collector.transport.listener import _SharedEybondListener


async def connect(server):
    return await asyncio.wait_for(
        asyncio.open_connection("127.0.0.1", server.sockets[0].getsockname()[1]), 2,
    )


async def close_writer(writer):
    writer.close()
    await writer.wait_closed()


async def test_accepted_stream_remains_owned_by_handler_after_acceptor_closes(hass, socket_enabled):
    accepted = asyncio.Future()

    async def handle(reader, writer):
        accepted.set_result((reader, writer))

    with patch("asyncio.start_server", side_effect=AssertionError("unowned Server accept path")):
        server = await CollectorTcpAcceptor.start(handle, "127.0.0.1", 0)
    reader, writer = await connect(server)
    peer_reader, peer_writer = await asyncio.wait_for(accepted, 2)
    try:
        server.close()
        await server.wait_closed()
        writer.write(b"collector\x00bytes")
        await writer.drain()
        assert await asyncio.wait_for(peer_reader.readexactly(15), 2) == b"collector\x00bytes"
        peer_writer.write(b"reply")
        await peer_writer.drain()
        assert await asyncio.wait_for(reader.readexactly(5), 2) == b"reply"
        assert server._admissions == {}
    finally:
        server.close()
        await server.wait_closed()
        await close_writer(writer)
        await close_writer(peer_writer)


async def test_close_between_accept_and_stream_task_first_step(hass, socket_enabled):
    """Force the exact old race window, rather than hope timing triggers it."""
    handler = AsyncMock()
    server = await CollectorTcpAcceptor.start(handler, "127.0.0.1", 0)
    loop = asyncio.get_running_loop()
    original_factory = loop.get_task_factory()
    raw_clients = []

    def factory(loop, coro, **kwargs):
        if getattr(coro, "__qualname__", "").endswith("._admit"):
            # This public scheduler hook closes the listener after kernel accept
            # but before the scheduled stream conversion starts.
            raw_clients.append(coro.cr_frame.f_locals["client"])
            loop.call_soon(server.close)
        if original_factory:
            return original_factory(loop, coro, **kwargs)
        return asyncio.Task(coro, loop=loop, **kwargs)

    loop.set_task_factory(factory)
    try:
        reader, writer = await connect(server)
        await asyncio.wait_for(server.wait_closed(), 2)
        assert await asyncio.wait_for(reader.read(1), 2) == b""
        await close_writer(writer)
        handler.assert_not_awaited()
        assert raw_clients and all(client.fileno() == -1 for client in raw_clients)
        assert server._admissions == {}
    finally:
        loop.set_task_factory(original_factory)
        server.close()
        await server.wait_closed()


async def test_close_during_stream_conversion_drains_socket(hass, socket_enabled):
    original_open = asyncio.open_connection
    entered = asyncio.Event()
    raw_clients = []

    async def delayed_open(*args, **kwargs):
        if "sock" in kwargs:
            raw_clients.append(kwargs["sock"])
            entered.set()
            await asyncio.Future()
        return await original_open(*args, **kwargs)

    handler = AsyncMock()
    server = await CollectorTcpAcceptor.start(handler, "127.0.0.1", 0)
    try:
        with patch.object(tcp_acceptor.asyncio, "open_connection", delayed_open):
            reader, writer = await connect(server)
            await asyncio.wait_for(entered.wait(), 2)
            server.close()
            await asyncio.wait_for(server.wait_closed(), 2)
            assert await asyncio.wait_for(reader.read(1), 2) == b""
            await close_writer(writer)
        handler.assert_not_awaited()
        assert all(client.fileno() == -1 for client in raw_clients)
        assert server._admissions == {}
    finally:
        server.close()
        await server.wait_closed()


async def test_repeated_waiter_cancellation_cannot_abandon_close(hass, socket_enabled):
    entered = asyncio.Event()
    cleaning = asyncio.Event()
    finish = asyncio.Event()

    async def handle(reader, writer):
        entered.set()
        try:
            await asyncio.Future()
        finally:
            cleaning.set()
            await finish.wait()

    server = await CollectorTcpAcceptor.start(handle, "127.0.0.1", 0)
    reader, writer = await connect(server)
    await asyncio.wait_for(entered.wait(), 2)
    server.close()
    waiter = asyncio.create_task(server.wait_closed())
    try:
        await asyncio.wait_for(cleaning.wait(), 2)
        for _ in range(3):
            waiter.cancel()
            await asyncio.sleep(0)
            assert not waiter.done()
            assert server._admissions
        finish.set()
        with pytest.raises(asyncio.CancelledError):
            await waiter
        assert server._admissions == {}
        assert await asyncio.wait_for(reader.read(1), 2) == b""
    finally:
        finish.set()
        await server.wait_closed()
        await close_writer(writer)


async def test_bind_failure_keeps_existing_listener_and_new_port_can_rebind(hass, socket_enabled):
    server = await CollectorTcpAcceptor.start(AsyncMock(), "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    try:
        with pytest.raises(OSError):
            await CollectorTcpAcceptor.start(AsyncMock(), "127.0.0.1", port)
    finally:
        server.close()
        await server.wait_closed()
    replacement = await CollectorTcpAcceptor.start(AsyncMock(), "127.0.0.1", port)
    replacement.close()
    await replacement.wait_closed()


async def test_queued_readiness_callback_after_close_cannot_admit(hass, socket_enabled):
    handler = AsyncMock()
    server = await CollectorTcpAcceptor.start(handler, "127.0.0.1", 0)
    old_socket = server.sockets[0]
    asyncio.get_running_loop().call_soon(server._accept_ready, old_socket)
    server.close()
    await server.wait_closed()
    handler.assert_not_awaited()
    assert old_socket.fileno() == -1


async def test_wildcard_ipv4_and_ipv6_loopback_binding(hass, socket_enabled):
    for host in ("0.0.0.0", "::1"):
        if host == "::1" and not socket.has_ipv6:
            continue
        server = await CollectorTcpAcceptor.start(AsyncMock(), host, 0)
        try:
            assert server.sockets[0].getsockname()[0] == host
            family = socket.AF_INET6 if host == "::1" else socket.AF_INET
            assert server.sockets[0].family == family
        finally:
            server.close()
            await server.wait_closed()


async def test_shared_release_fences_admission_before_session_cleanup(hass, socket_enabled):
    listener = _SharedEybondListener(host="127.0.0.1", port=0)
    await listener.acquire()
    server = listener._server
    port = server.sockets[0].getsockname()[1]
    arrived = asyncio.Event()
    listener.add_connection_watcher("", lambda _ip: arrived.set())
    reader, writer = await connect(server)
    await asyncio.wait_for(arrived.wait(), 2)
    cleaning = asyncio.Event()
    finish = asyncio.Event()
    original_close = listener._close_pending_socket

    async def delayed_close(pending):
        cleaning.set()
        await finish.wait()
        await original_close(pending)

    try:
        with patch.object(listener, "_close_pending_socket", delayed_close):
            release = asyncio.create_task(listener.release())
            await asyncio.wait_for(cleaning.wait(), 2)
            assert server.sockets == ()
            with pytest.raises(OSError):
                await asyncio.wait_for(asyncio.open_connection("127.0.0.1", port), 2)
            finish.set()
            assert await asyncio.wait_for(release, 2)
        assert listener._pending_sockets == {}
        assert listener._session_inventory == {}
        assert await asyncio.wait_for(reader.read(1), 2) == b""
    finally:
        finish.set()
        await listener.release()
        await close_writer(writer)


async def test_resource_retry_cannot_reinstall_reader_after_close(hass, socket_enabled):
    server = await CollectorTcpAcceptor.start(AsyncMock(), "127.0.0.1", 0)
    sock = server.sockets[0]
    fake_socket = Mock()
    fake_socket.fileno.return_value = sock.fileno()
    fake_socket.accept.side_effect = OSError(errno.EMFILE, "synthetic descriptor pressure")
    server._accept_ready(fake_socket)
    retry = server._retry_handles[fake_socket]
    server.close()
    await server.wait_closed()
    assert retry.cancelled()
    server._resume_accept(fake_socket)  # A callback already queued before cancellation.
    assert server._retry_handles == {}
    assert fake_socket.accept.call_count == 1


async def test_provisional_admission_limit_does_not_accumulate_clients(hass, socket_enabled):
    original_open = asyncio.open_connection
    preparing = asyncio.Event()

    async def delayed_open(*args, **kwargs):
        if "sock" in kwargs:
            preparing.set()
            await asyncio.Future()
        return await original_open(*args, **kwargs)

    server = await CollectorTcpAcceptor.start(AsyncMock(), "127.0.0.1", 0)
    try:
        with patch.object(tcp_acceptor, "_MAX_ADMISSIONS", 1), \
             patch.object(tcp_acceptor.asyncio, "open_connection", delayed_open):
            reader, writer = await connect(server)
            await asyncio.wait_for(preparing.wait(), 2)
            rejected_reader, rejected_writer = await connect(server)
            assert await asyncio.wait_for(rejected_reader.read(1), 2) == b""
            await close_writer(rejected_writer)
            assert len(server._admissions) == 1
            server.close()
            await server.wait_closed()
            assert await asyncio.wait_for(reader.read(1), 2) == b""
            await close_writer(writer)
    finally:
        server.close()
        await server.wait_closed()


async def test_partial_multi_address_bind_rolls_back_previous_socket(hass, socket_enabled):
    loop = asyncio.get_running_loop()
    occupied = await CollectorTcpAcceptor.start(AsyncMock(), "127.0.0.1", 0)
    port = occupied.sockets[0].getsockname()[1]
    addresses = [
        (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("127.0.0.2", port)),
        (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("127.0.0.1", port)),
    ]
    try:
        with patch.object(loop, "getaddrinfo", new=AsyncMock(return_value=addresses)):
            with pytest.raises(OSError):
                await CollectorTcpAcceptor.start(AsyncMock(), "synthetic.invalid", port)
        rebound = await CollectorTcpAcceptor.start(AsyncMock(), "127.0.0.2", port)
        rebound.close()
        await rebound.wait_closed()
    finally:
        occupied.close()
        await occupied.wait_closed()

from __future__ import annotations

import asyncio
import socket
import sys
import types
from time import monotonic
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


from custom_components.eybond_local.collector.transport import (
    CollectorListenerBindError,
    SharedCollectorAtTransport,
    SharedEybondTransport,
    SharedProxyCaptureRoute,
    _BACKGROUND_TASKS,
    _LISTENERS,
    _CollectorAtConnection,
    _CollectorConnection,
    _PendingCollectorSocket,
    _SharedEybondListener,
    _collector_pn_from_initial_chunk,
    _parse_fc2_collector_pn,
)
from custom_components.eybond_local.collector.transport.common import (
    _classify_initial_protocol_shape,
)
from custom_components.eybond_local.collector.at import CollectorAtResponse
from custom_components.eybond_local.collector.protocol import (
    HEADER_SIZE,
    build_collector_request,
    build_heartbeat_request,
    decode_header,
    parse_heartbeat_pn,
)
from custom_components.eybond_local.connection.session_registry import (
    CallbackSessionRegistry,
)
from custom_components.eybond_local.link_models import AtMixedLinkRoute, EybondLinkRoute, RawSerialLinkRoute
from custom_components.eybond_local.models import CollectorInfo
from custom_components.eybond_local.payload.ascii_line import build_ascii_line_request
from custom_components.eybond_local.payload.modbus import (
    build_read_request,
    crc16_modbus,
)
from custom_components.eybond_local.payload.pi30 import build_request, crc16_xmodem
from custom_components.eybond_local.runtime.link import EybondRuntimeLinkManager


def _free_tcp_port() -> int:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


class _FakeWriter:
    def __init__(self) -> None:
        self.closed = False
        self.buffer = bytearray()

    def is_closing(self) -> bool:
        return self.closed

    def write(self, data: bytes) -> None:
        self.buffer.extend(data)

    async def drain(self) -> None:
        return None

    def close(self) -> None:
        self.closed = True

    async def wait_closed(self) -> None:
        self.closed = True

    def get_extra_info(self, name: str, default=None):
        if name == "peername":
            return ("203.0.113.10", 41000)
        return default


async def _wait_for_writer_buffer(writer: _FakeWriter, expected: bytes) -> None:
    deadline = monotonic() + 1.0
    while bytes(writer.buffer) != expected:
        if monotonic() >= deadline:
            break
        await asyncio.sleep(0.01)


class ParkedUnclaimedCallbackTests(unittest.IsolatedAsyncioTestCase):
    def _heartbeat_frame(self) -> bytes:
        return build_collector_request(
            7,
            b"E5000020000000",
            devcode=2376,
            collector_addr=1,
            fcode=1,
        )

    def _pending(
        self,
        listener,
        *,
        session_id: str,
        remote_ip: str,
        eof: bool = False,
        strong_identity: bool = False,
    ):
        listener._remember_session(
            session_id=session_id,
            remote_ip=remote_ip,
            remote_port=41000,
        )
        reader = asyncio.StreamReader()
        reader.feed_data(
            build_collector_request(
                7,
                b"\x00\x02E5000020000000",
                devcode=2376,
                collector_addr=1,
                fcode=2,
            )
            if strong_identity
            else self._heartbeat_frame()
        )
        if eof:
            reader.feed_eof()
        pending = _PendingCollectorSocket(
            remote_ip=remote_ip,
            remote_port=41000,
            session_id=session_id,
            reader=reader,
            writer=_FakeWriter(),  # type: ignore[arg-type]
        )
        listener._pending_sockets[session_id] = pending
        return pending

    async def test_activate_pending_payload_reuses_collector_pn_placeholder(self) -> None:
        listener = _SharedEybondListener(host="127.0.0.1", port=_free_tcp_port())
        collector_pn = "V001020SYN62344022"
        public_ip = "195.138.86.175"
        placeholder = listener.ensure_connection(
            "",
            heartbeat_interval=60.0,
            write_timeout=0.5,
            collector_pn=collector_pn,
        )
        pending = self._pending(listener, session_id="s1", remote_ip=public_ip)

        with patch.object(placeholder, "run", new=AsyncMock()) as run_mock:
            connection = await listener.activate_pending_connection(
                pending,
                collector_ip="",
                collector_pn=collector_pn,
                heartbeat_interval=60.0,
                write_timeout=0.5,
            )
            await asyncio.sleep(0)

        self.assertIs(connection, placeholder)
        self.assertIs(listener._connections_by_pn[collector_pn], placeholder)
        self.assertNotIn(public_ip, listener._connections)
        self.assertIs(listener._session_payload_connections["s1"], placeholder)
        run_mock.assert_awaited_once()

    async def test_activate_pending_at_reuses_collector_pn_placeholder(self) -> None:
        listener = _SharedEybondListener(host="127.0.0.1", port=_free_tcp_port())
        collector_pn = "V001020SYN62344022"
        public_ip = "195.138.86.175"
        placeholder = listener.ensure_at_connection(
            "",
            write_timeout=0.5,
            collector_pn=collector_pn,
        )
        pending = self._pending(listener, session_id="s1", remote_ip=public_ip)

        with patch.object(placeholder, "run", new=AsyncMock()) as run_mock:
            connection = await listener.activate_pending_at_connection(
                pending,
                collector_ip="",
                collector_pn=collector_pn,
                write_timeout=0.5,
            )
            await asyncio.sleep(0)

        self.assertIs(connection, placeholder)
        self.assertIs(listener._at_connections_by_pn[collector_pn], placeholder)
        self.assertNotIn(public_ip, listener._at_connections)
        self.assertIs(listener._session_at_connections["s1"], placeholder)
        run_mock.assert_awaited_once()

    async def test_two_live_sessions_never_share_one_mutable_connection(self) -> None:
        """Exact session-pinned I/O stays on the socket the registry selected."""

        listener = _SharedEybondListener(host="127.0.0.1", port=_free_tcp_port())
        collector_pn = "E50000200000000001"
        placeholder = listener.ensure_connection(
            "",
            heartbeat_interval=3600.0,
            write_timeout=0.5,
            collector_pn=collector_pn,
        )
        first_pending = listener._claim_pending_socket(
            self._pending(
                listener,
                session_id="session-first",
                remote_ip="192.168.1.55",
            )
        )
        first = await listener.activate_pending_connection(
            first_pending,
            collector_ip="",
            collector_pn=collector_pn,
            heartbeat_interval=3600.0,
            write_timeout=0.5,
        )
        self.assertIs(first, placeholder)
        self.assertTrue(first.connected)

        second_pending = listener._claim_pending_socket(
            self._pending(
                listener,
                session_id="session-second",
                remote_ip="192.168.1.55",
            )
        )
        second = await listener.activate_pending_connection(
            second_pending,
            collector_ip="",
            collector_pn=collector_pn,
            heartbeat_interval=3600.0,
            write_timeout=0.5,
        )

        self.assertIsNot(second, first)
        self.assertIs(
            listener.payload_connection_for_session("session-first"), first
        )
        self.assertIs(
            listener.payload_connection_for_session("session-second"), second
        )
        self.assertTrue(first.connected)
        self.assertTrue(second.connected)

        # Closing the newer sibling cannot close, replace or retarget the exact
        # older session a recovery transaction pinned before sending restart.
        await second.disconnect()
        for _ in range(20):
            if not second.connected:
                break
            await asyncio.sleep(0.01)
        self.assertFalse(second.connected)
        self.assertTrue(first.connected)
        self.assertIs(
            listener.payload_connection_for_session("session-first"), first
        )

        await first.disconnect()

    async def test_two_automatically_routed_sessions_keep_exact_transports(self) -> None:
        """The listener's normal accept path preserves the same invariant."""

        listener = _SharedEybondListener(host="127.0.0.1", port=_free_tcp_port())
        collector_pn = "E5000020000000"
        listener.register_payload_pn_owner(collector_pn)
        first_pending = self._pending(
            listener,
            session_id="session-first",
            remote_ip="192.168.1.55",
            strong_identity=True,
        )
        first_task = asyncio.create_task(listener._sniff_pending_socket(first_pending))
        for _ in range(20):
            if listener.payload_connection_for_session("session-first") is not None:
                break
            await asyncio.sleep(0.01)

        second_pending = self._pending(
            listener,
            session_id="session-second",
            remote_ip="192.168.1.55",
            strong_identity=True,
        )
        second_task = asyncio.create_task(listener._sniff_pending_socket(second_pending))
        for _ in range(20):
            if listener.payload_connection_for_session("session-second") is not None:
                break
            await asyncio.sleep(0.01)

        first = listener.payload_connection_for_session("session-first")
        second = listener.payload_connection_for_session("session-second")
        self.assertIsNotNone(first)
        self.assertIsNotNone(second)
        self.assertIsNot(first, second)
        self.assertTrue(first.connected)
        self.assertTrue(second.connected)

        first_pending.reader.feed_eof()
        second_pending.reader.feed_eof()
        await asyncio.wait_for(first_task, timeout=2.0)
        await asyncio.wait_for(second_task, timeout=2.0)
        listener.unregister_payload_pn_owner(collector_pn)

    async def test_unclaimed_callback_is_parked_instead_of_closed(self) -> None:
        listener = _SharedEybondListener(host="127.0.0.1", port=_free_tcp_port())
        pending = self._pending(listener, session_id="s1", remote_ip="203.0.113.10")

        sniff = asyncio.create_task(listener._sniff_pending_socket(pending))
        pending.sniff_task = sniff
        await asyncio.sleep(0.4)

        self.assertFalse(pending.writer.closed)
        self.assertTrue(pending.parked)
        self.assertTrue(listener._pending_socket_still_registered(pending))
        states = {
            session["session_id"]: session["state"]
            for session in listener.session_inventory_diagnostics()["sessions"]
        }
        self.assertEqual(states["s1"], "parked_no_payload_owner")

        # Peer close releases the parked socket.
        pending.reader.feed_eof()
        await asyncio.wait_for(sniff, timeout=2.0)
        self.assertTrue(pending.writer.closed)
        self.assertFalse(listener._pending_socket_still_registered(pending))

    async def test_parked_callback_stays_claimable_with_buffered_identity(self) -> None:
        listener = _SharedEybondListener(host="127.0.0.1", port=_free_tcp_port())
        pending = self._pending(listener, session_id="s1", remote_ip="203.0.113.10")

        sniff = asyncio.create_task(listener._sniff_pending_socket(pending))
        pending.sniff_task = sniff
        await asyncio.sleep(0.4)
        self.assertTrue(pending.parked)

        claimed = listener._claim_pending_socket(pending)

        self.assertIs(claimed, pending)
        # The sniffed heartbeat is preserved for the claiming transport.
        self.assertIn(b"E5000020000000", claimed.initial_bytes)
        self.assertFalse(pending.writer.closed)
        with self.assertRaises(asyncio.CancelledError):
            await sniff

    async def test_activated_parked_socket_replays_buffered_identity(self) -> None:
        listener = _SharedEybondListener(host="127.0.0.1", port=_free_tcp_port())
        pending = self._pending(listener, session_id="s1", remote_ip="203.0.113.10")
        sniff = asyncio.create_task(listener._sniff_pending_socket(pending))
        pending.sniff_task = sniff
        await asyncio.sleep(0.4)
        self.assertTrue(pending.parked)

        claimed = listener._claim_pending_socket(pending)
        try:
            await sniff
        except asyncio.CancelledError:
            pass

        connection = await listener.activate_pending_connection(
            claimed,
            collector_ip="203.0.113.10",
            heartbeat_interval=60.0,
            write_timeout=1.5,
        )

        # The heartbeat buffered while parked must be replayed on activation:
        # identity is learned without waiting for the next heartbeat.
        for _ in range(40):
            if connection.collector_info.collector_pn:
                break
            await asyncio.sleep(0.05)
        self.assertEqual(connection.collector_info.collector_pn, "E5000020000000")
        self.assertEqual(claimed.initial_bytes, b"")

        pending.reader.feed_eof()
        await asyncio.sleep(0.1)

    async def test_same_ip_parked_sockets_coexist_by_session_id(self) -> None:
        listener = _SharedEybondListener(host="127.0.0.1", port=_free_tcp_port())
        first = self._pending(listener, session_id="s1", remote_ip="203.0.113.10")
        sniff_first = asyncio.create_task(listener._sniff_pending_socket(first))
        first.sniff_task = sniff_first
        await asyncio.sleep(0.4)
        self.assertTrue(first.parked)

        second = self._pending(listener, session_id="s2", remote_ip="203.0.113.10")
        sniff_second = asyncio.create_task(listener._sniff_pending_socket(second))
        second.sniff_task = sniff_second
        await asyncio.sleep(0.4)

        self.assertTrue(second.parked)
        self.assertFalse(first.writer.closed)
        self.assertTrue(listener._pending_socket_still_registered(first))
        self.assertTrue(listener._pending_socket_still_registered(second))

        first.reader.feed_eof()
        second.reader.feed_eof()
        await asyncio.wait_for(sniff_first, timeout=2.0)
        await asyncio.wait_for(sniff_second, timeout=2.0)



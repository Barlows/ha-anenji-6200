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


class SharedTransportTests(unittest.IsolatedAsyncioTestCase):
    def test_initial_protocol_shape_exposes_ambiguous_and_malformed_prefixes(self) -> None:
        cases = (
            (b"AT+DTUPN:E5000020000000" + bytes((13, 10)), "at_text"),
            (bytes((1, 3, 2)), "unknown"),
            (bytes.fromhex("0103180000000000"), "raw_tcp"),
            (bytes.fromhex("01036c0000000200"), "raw_tcp"),
            (
                build_collector_request(
                    0x0103,
                    b"payload",
                    devcode=0x1800,
                    collector_addr=0,
                    fcode=4,
                ),
                "eybond_framed",
            ),
            (b"", "unknown"),
        )
        for chunk, expected in cases:
            with self.subTest(chunk=chunk):
                self.assertEqual(_classify_initial_protocol_shape(chunk), expected)

    def test_scanner_control_payload_is_not_a_heartbeat_identity(self) -> None:
        scanner_payload = b"\x13\x03\x13\x02+/,"
        frame = build_collector_request(
            1,
            scanner_payload,
            devcode=0,
            collector_addr=1,
            fcode=1,
        )

        self.assertEqual(parse_heartbeat_pn(scanner_payload), "")
        self.assertEqual(_collector_pn_from_initial_chunk(frame), ("", ""))

    def test_wire_identity_parsers_accept_real_short_and_full_pns(self) -> None:
        self.assertEqual(
            parse_heartbeat_pn(b"V001020SYN6234"),
            "V001020SYN6234",
        )
        self.assertEqual(
            _parse_fc2_collector_pn(b"\x00\x02V001020SYN62344022"),
            "V001020SYN62344022",
        )

    def test_fc2_identity_rejects_control_non_ascii_and_padded_text(self) -> None:
        for payload in (
            b"\x00\x02\x13\x03\x13\x02+/",
            b"\x00\x02E500002SYN84\xff199645",
            b"\x00\x02 E500002SYN84199645",
            b"\x00\x02E500002SYN84199645 ",
        ):
            with self.subTest(payload=payload):
                self.assertEqual(_parse_fc2_collector_pn(payload), "")

    def test_listener_refuses_non_wire_safe_identity_before_inventory_mutation(
        self,
    ) -> None:
        listener = _SharedEybondListener(host="127.0.0.1", port=_free_tcp_port())
        listener._remember_session(
            session_id="scanner-session",
            remote_ip="69.5.169.178",
            remote_port=41000,
        )

        listener._mark_session_identity(
            "scanner-session",
            "\x13\x03\x13\x02+/ ,",
            "framed_heartbeat",
        )

        entry = listener._session_inventory["scanner-session"]
        self.assertEqual(entry.collector_pn, "")
        self.assertEqual(entry.collector_identity_source, "")

    async def test_proxy_route_rejects_malformed_wire_before_route_lease(
        self,
    ) -> None:
        manager = EybondRuntimeLinkManager(
            server_ip="127.0.0.1",
            collector_ip="192.168.1.55",
            collector_pn="E50000200000000001",
            tcp_port=8899,
            udp_port=58899,
            discovery_target="192.168.1.255",
            discovery_interval=3,
            heartbeat_interval=60,
            collector_configured_session_protocol="eybond_framed",
            collector_identity_strategy="fc2_parameter_2",
        )
        common = {
            "collector_ip": "192.168.1.55",
            "collector_pn": "E50000200000000001",
            "expected_session_protocol": "at_text",
            "listen_port": 8899,
            "upstream_host": "dtu_ess.eybond.com",
            "upstream_port": 18899,
            "output_path": Path("/tmp/proxy-bridge-invalid.jsonl"),
        }

        for overrides in (
            {"proxy_wire_mode": "unknown"},
            {"expected_session_protocol": ""},
            {"expected_session_protocol": " AT_TEXT "},
            {"expected_session_protocol": object()},
        ):
            kwargs = {**common, **overrides}
            with self.assertRaises(ValueError):
                await manager.async_start_proxy_capture_route(
                    **kwargs,
                )
            self.assertIsNone(manager.route_lease)

    async def test_collector_connection_wait_until_heartbeat_requires_fresh_sample(self) -> None:
        connection = _CollectorConnection(
            remote_ip_hint="127.0.0.1",
            heartbeat_interval=60.0,
            write_timeout=0.5,
        )

        class _OpenWriter:
            def is_closing(self) -> bool:
                return False

        connection._writer = _OpenWriter()  # type: ignore[assignment]
        connection._last_heartbeat_monotonic = monotonic() - 999.0

        self.assertFalse(await connection.wait_until_heartbeat(0.02))
        self.assertFalse(connection.collector_info.heartbeat_fresh)

    async def test_collector_connection_wait_until_heartbeat_accepts_fresh_sample(self) -> None:
        connection = _CollectorConnection(
            remote_ip_hint="127.0.0.1",
            heartbeat_interval=60.0,
            write_timeout=0.5,
        )
        connection._last_heartbeat_monotonic = monotonic()

        self.assertTrue(await connection.wait_until_heartbeat(0.02))
        self.assertTrue(connection.collector_info.heartbeat_fresh)
        self.assertIsNotNone(connection.collector_info.heartbeat_age_seconds)

    async def test_correlated_framed_response_proves_liveness_not_heartbeat(self) -> None:
        connection = _CollectorConnection(
            remote_ip_hint="127.0.0.1",
            heartbeat_interval=60.0,
            write_timeout=0.5,
        )
        connection._writer = _FakeWriter()  # type: ignore[assignment]
        future = asyncio.get_running_loop().create_future()
        connection._pending[23] = future
        connection._pending_fcode[23] = 4
        reader = asyncio.StreamReader()
        reader.feed_data(
            build_collector_request(
                23,
                b"valid-inverter-response",
                devcode=2376,
                collector_addr=1,
                fcode=4,
            )
        )
        reader.feed_eof()

        await connection._read_loop(reader)

        self.assertEqual((await future)[1], b"valid-inverter-response")
        self.assertTrue(await connection.wait_until_liveness(0.02))
        self.assertFalse(await connection.wait_until_heartbeat(0.02))
        self.assertFalse(connection.collector_info.heartbeat_fresh)
        self.assertIsNone(connection.collector_info.heartbeat_age_seconds)

    async def test_unmatched_framed_response_does_not_prove_liveness(self) -> None:
        connection = _CollectorConnection(
            remote_ip_hint="127.0.0.1",
            heartbeat_interval=60.0,
            write_timeout=0.5,
        )
        connection._writer = _FakeWriter()  # type: ignore[assignment]
        reader = asyncio.StreamReader()
        reader.feed_data(
            build_collector_request(
                24,
                b"unsolicited",
                devcode=2376,
                collector_addr=1,
                fcode=4,
            )
        )
        reader.feed_eof()

        await connection._read_loop(reader)

        self.assertFalse(await connection.wait_until_liveness(0.02))

    async def test_correlated_at_response_proves_framed_session_liveness(self) -> None:
        connection = _CollectorConnection(
            remote_ip_hint="127.0.0.1",
            heartbeat_interval=60.0,
            write_timeout=0.5,
        )
        connection._writer = _FakeWriter()  # type: ignore[assignment]
        future = asyncio.get_running_loop().create_future()
        connection._pending_at_response = future
        reader = asyncio.StreamReader()
        reader.feed_data(b"AT+DTUPN:E50000200000000001\r\n")
        reader.feed_eof()

        await connection._read_loop(reader)

        self.assertEqual((await future).value, "E50000200000000001")
        self.assertTrue(await connection.wait_until_liveness(0.02))
        self.assertFalse(connection.collector_info.heartbeat_fresh)

    async def test_delimiterless_at_response_preserves_following_framed_response(
        self,
    ) -> None:
        connection = _CollectorConnection(
            remote_ip_hint="127.0.0.1",
            heartbeat_interval=60.0,
            write_timeout=0.5,
        )
        at_future = asyncio.get_running_loop().create_future()
        framed_future = asyncio.get_running_loop().create_future()
        connection._pending_at_response = at_future
        # A long-running connection can have a transaction id whose two bytes
        # are printable. The decoder must preserve the complete binary header,
        # not merely the first control byte it happens to encounter later.
        printable_tid = 0x4142
        connection._pending[printable_tid] = framed_future
        connection._pending_fcode[printable_tid] = 4
        reader = asyncio.StreamReader()
        reader.feed_data(
            b"AT+INTPARA:41,GRooVE"
            + build_collector_request(
                printable_tid,
                b"framed-after-delimiterless-at",
                devcode=2376,
                collector_addr=1,
                fcode=4,
            )
        )
        reader.feed_eof()

        await connection._read_loop(reader)

        self.assertEqual((await at_future).command, "INTPARA")
        self.assertEqual((await at_future).value, "41,GRooVE")
        self.assertEqual(
            (await framed_future)[1],
            b"framed-after-delimiterless-at",
        )
        self.assertTrue(await connection.wait_until_liveness(0.02))

    async def test_delimiterless_at_response_completes_after_idle_gap(self) -> None:
        connection = _CollectorConnection(
            remote_ip_hint="127.0.0.1",
            heartbeat_interval=60.0,
            write_timeout=0.5,
        )
        future = asyncio.get_running_loop().create_future()
        connection._pending_at_response = future
        reader = asyncio.StreamReader()
        task = asyncio.create_task(connection._read_loop(reader))
        try:
            reader.feed_data(b"AT+INTPARA:41,GRooVE")
            response = await asyncio.wait_for(future, timeout=0.5)
            self.assertEqual(response.value, "41,GRooVE")
        finally:
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task

    async def test_at_transport_delimiterless_response_keeps_mixed_frame_aligned(
        self,
    ) -> None:
        connection = _CollectorAtConnection(
            remote_ip_hint="127.0.0.1",
            write_timeout=0.5,
        )
        at_future = asyncio.get_running_loop().create_future()
        framed_future = asyncio.get_running_loop().create_future()
        connection._pending_response = at_future
        connection._pending_framed_response[32] = framed_future
        connection._pending_framed_fcode[32] = 2
        reader = asyncio.StreamReader()
        reader.feed_data(
            b"AT+INTPARA:41,Home WiFi"
            + build_collector_request(
                32,
                b"\x00\x02E50000253745448949",
                devcode=2376,
                collector_addr=1,
                fcode=2,
            )
        )
        reader.feed_eof()

        await connection._read_loop(reader)

        self.assertEqual((await at_future).value, "41,Home WiFi")
        self.assertEqual(
            (await framed_future)[1],
            b"\x00\x02E50000253745448949",
        )

    async def test_actual_heartbeat_proves_both_heartbeat_and_liveness(self) -> None:
        connection = _CollectorConnection(
            remote_ip_hint="127.0.0.1",
            heartbeat_interval=60.0,
            write_timeout=0.5,
        )
        reader = asyncio.StreamReader()
        reader.feed_data(
            build_collector_request(
                25,
                b"E5000020000000",
                devcode=2376,
                collector_addr=1,
                fcode=1,
            )
        )
        reader.feed_eof()

        await connection._read_loop(reader)

        self.assertTrue(await connection.wait_until_heartbeat(0.02))
        self.assertTrue(await connection.wait_until_liveness(0.02))

    async def test_collector_connection_passively_reports_at_dtupn_identity(self) -> None:
        seen: list[tuple[str, str, str]] = []
        connection = _CollectorConnection(
            remote_ip_hint="127.0.0.1",
            heartbeat_interval=60.0,
            write_timeout=0.5,
        )
        connection._session_id = "session-1"
        connection._session_identity_callback = lambda session_id, pn, source: seen.append(
            (session_id, pn, source)
        )
        reader = asyncio.StreamReader()
        reader.feed_data(b"AT+DTUPN:E5000020000000\r\n")
        reader.feed_eof()

        await connection._read_loop(reader)

        self.assertEqual(
            seen,
            [("session-1", "E5000020000000", "at_dtupn")],
        )

    async def test_collector_connection_passively_reports_heartbeat_identity(self) -> None:
        seen: list[tuple[str, str, str]] = []
        connection = _CollectorConnection(
            remote_ip_hint="127.0.0.1",
            heartbeat_interval=60.0,
            write_timeout=0.5,
        )
        connection._session_id = "session-2"
        connection._session_identity_callback = lambda session_id, pn, source: seen.append(
            (session_id, pn, source)
        )
        reader = asyncio.StreamReader()
        reader.feed_data(
            build_collector_request(
                7,
                b"E5000020000000",
                devcode=2376,
                collector_addr=1,
                fcode=1,
            )
        )
        reader.feed_eof()

        await connection._read_loop(reader)

        self.assertEqual(
            seen,
            [("session-2", "E5000020000000", "framed_heartbeat")],
        )

    async def test_collector_connection_passively_reports_fc2_parameter_2_identity(self) -> None:
        seen: list[tuple[str, str, str]] = []
        connection = _CollectorConnection(
            remote_ip_hint="127.0.0.1",
            heartbeat_interval=60.0,
            write_timeout=0.5,
        )
        connection._session_id = "session-3"
        connection._session_identity_callback = lambda session_id, pn, source: seen.append(
            (session_id, pn, source)
        )
        reader = asyncio.StreamReader()
        reader.feed_data(
            build_collector_request(
                8,
                b"\x00\x02E50000200000000001",
                devcode=2376,
                collector_addr=1,
                fcode=2,
            )
        )
        reader.feed_eof()

        await connection._read_loop(reader)

        self.assertEqual(
            seen,
            [("session-3", "E50000200000000001", "fc2_parameter_2")],
        )

    async def test_collector_connection_write_timeout_raises_connection_error(self) -> None:
        connection = _CollectorConnection(
            remote_ip_hint="127.0.0.1",
            heartbeat_interval=60.0,
            write_timeout=0.01,
        )

        class _BlockingWriter:
            def __init__(self) -> None:
                self.frames: list[bytes] = []

            def is_closing(self) -> bool:
                return False

            def write(self, frame: bytes) -> None:
                self.frames.append(frame)

            async def drain(self) -> None:
                await asyncio.Future()

        connection._writer = _BlockingWriter()  # type: ignore[assignment]

        with self.assertRaisesRegex(ConnectionError, "collector_write_timeout"):
            await connection._async_write(b"abc")

    async def test_two_transports_share_one_listener(self) -> None:
        port = _free_tcp_port()
        first = SharedEybondTransport(
            host="127.0.0.1",
            port=port,
            request_timeout=1.0,
            heartbeat_interval=60.0,
            collector_ip="",
        )
        second = SharedEybondTransport(
            host="127.0.0.1",
            port=port,
            request_timeout=1.0,
            heartbeat_interval=60.0,
            collector_ip="",
        )

        await first.start()
        await second.start()

        reader = writer = None
        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            writer.write(
                build_collector_request(
                    1,
                    b"",
                    devcode=0x0994,
                    collector_addr=1,
                    fcode=4,
                )
            )
            await writer.drain()
            self.assertTrue(await first.wait_until_connected(1.0))
            self.assertTrue(await second.wait_until_connected(1.0))
            self.assertTrue(first.connected)
            self.assertTrue(second.connected)
            self.assertEqual(first.collector_info.remote_ip, "127.0.0.1")
            self.assertEqual(second.collector_info.remote_ip, "127.0.0.1")
        finally:
            if writer is not None:
                writer.close()
                await writer.wait_closed()
            await first.stop()
            await second.stop()

    async def test_specific_host_request_reuses_wildcard_listener(self) -> None:
        # The runtime binds its callback listener on 0.0.0.0; options-flow
        # helpers (collector Wi-Fi change, restart) historically request the
        # entry's server IP on the same port. The registry must hand back the
        # wildcard listener instead of binding the specific address — that bind
        # fails with EADDRINUSE while the wildcard socket holds the port
        # (the "collector_listener_bind_failed ... address in use" regression).
        port = _free_tcp_port()
        runtime_like = SharedEybondTransport(
            host="0.0.0.0",
            port=port,
            request_timeout=1.0,
            heartbeat_interval=60.0,
            collector_ip="",
        )
        options_like = SharedEybondTransport(
            host="127.0.0.1",
            port=port,
            request_timeout=1.0,
            heartbeat_interval=60.0,
            collector_ip="",
        )

        await runtime_like.start()
        try:
            # Must NOT raise CollectorListenerBindError: the wildcard listener
            # already serves this port.
            await options_like.start()
            self.assertIs(options_like._listener, runtime_like._listener)
            self.assertEqual(len(_LISTENERS), 1)
        finally:
            await options_like.stop()
            await runtime_like.stop()
        self.assertEqual(len(_LISTENERS), 0)

    async def test_listener_session_inventory_keeps_multiple_same_ip_pending_sessions(self) -> None:
        port = _free_tcp_port()
        transport = SharedEybondTransport(
            host="127.0.0.1",
            port=port,
            request_timeout=1.0,
            heartbeat_interval=60.0,
            collector_ip="",
        )

        first_writer = None
        second_writer = None
        await transport.start()
        try:
            listener = transport._listener
            self.assertIsNotNone(listener)
            assert listener is not None

            _first_reader, first_writer = await asyncio.open_connection("127.0.0.1", port)
            await asyncio.sleep(0.05)
            _second_reader, second_writer = await asyncio.open_connection("127.0.0.1", port)
            await asyncio.sleep(0.05)

            diagnostics = listener.session_inventory_diagnostics()
            self.assertEqual(diagnostics["pending_session_count"], 2)
            self.assertEqual(diagnostics["recent_session_count"], 2)
            self.assertEqual(diagnostics["duplicate_peer_ip_count"], 1)
            self.assertEqual(diagnostics["duplicate_peer_ips"], ["127.0.0.1"])
            states = {
                item["state"]
                for item in diagnostics["sessions"]
                if isinstance(item, dict)
            }
            self.assertEqual(states, {"pending"})
        finally:
            for writer in (first_writer, second_writer):
                if writer is not None:
                    writer.close()
                    await writer.wait_closed()
            await transport.stop()

    async def test_transport_can_select_connected_session_by_collector_pn(self) -> None:
        listener = _SharedEybondListener(host="127.0.0.1", port=_free_tcp_port())

        class _OpenWriter:
            def is_closing(self) -> bool:
                return False

        first = _CollectorConnection(
            remote_ip_hint="203.0.113.10",
            heartbeat_interval=60.0,
            write_timeout=0.5,
        )
        first._writer = _OpenWriter()  # type: ignore[assignment]
        first._collector.remote_ip = "203.0.113.10"
        first._collector.collector_pn = "PN-ONE"

        second = _CollectorConnection(
            remote_ip_hint="203.0.113.10",
            heartbeat_interval=60.0,
            write_timeout=0.5,
        )
        second._writer = _OpenWriter()  # type: ignore[assignment]
        second._collector.remote_ip = "203.0.113.10"
        second._collector.collector_pn = "PN-TWO"

        listener._connections["203.0.113.10:first"] = first
        listener._connections["203.0.113.10:second"] = second
        listener._connections_by_pn["PN-ONE"] = first
        listener._connections_by_pn["PN-TWO"] = second

        transport = SharedEybondTransport(
            host="127.0.0.1",
            port=listener._port,
            request_timeout=1.0,
            heartbeat_interval=60.0,
            collector_ip="",
            collector_pn="PN-TWO",
        )
        transport._listener = listener

        self.assertTrue(transport.connected)
        self.assertEqual(transport.collector_info.collector_pn, "PN-TWO")

    async def test_transport_prefers_collector_pn_over_same_nat_ip_index(self) -> None:
        listener = _SharedEybondListener(host="127.0.0.1", port=_free_tcp_port())

        class _OpenWriter:
            def is_closing(self) -> bool:
                return False

        first = _CollectorConnection(
            remote_ip_hint="203.0.113.10",
            heartbeat_interval=60.0,
            write_timeout=0.5,
        )
        first._writer = _OpenWriter()  # type: ignore[assignment]
        first._collector.remote_ip = "203.0.113.10"
        first._collector.collector_pn = "PN-ONE"

        second = _CollectorConnection(
            remote_ip_hint="203.0.113.10",
            heartbeat_interval=60.0,
            write_timeout=0.5,
        )
        second._writer = _OpenWriter()  # type: ignore[assignment]
        second._collector.remote_ip = "203.0.113.10"
        second._collector.collector_pn = "PN-TWO"

        listener._connections["203.0.113.10"] = first
        listener._connections["203.0.113.10:second"] = second
        listener._connections_by_pn["PN-ONE"] = first
        listener._connections_by_pn["PN-TWO"] = second

        transport = SharedEybondTransport(
            host="127.0.0.1",
            port=listener._port,
            request_timeout=1.0,
            heartbeat_interval=60.0,
            collector_ip="203.0.113.10",
            collector_pn="PN-TWO",
        )
        transport._listener = listener

        self.assertTrue(transport.connected)
        self.assertEqual(transport.collector_info.collector_pn, "PN-TWO")

    async def test_at_transport_prefers_collector_pn_over_same_nat_ip_index(self) -> None:
        listener = _SharedEybondListener(host="127.0.0.1", port=_free_tcp_port())

        class _OpenWriter:
            def is_closing(self) -> bool:
                return False

        first = _CollectorAtConnection(remote_ip_hint="203.0.113.10", write_timeout=0.5)
        first._writer = _OpenWriter()  # type: ignore[assignment]
        first._collector.remote_ip = "203.0.113.10"
        first._collector.collector_pn = "PN-ONE"

        second = _CollectorAtConnection(remote_ip_hint="203.0.113.10", write_timeout=0.5)
        second._writer = _OpenWriter()  # type: ignore[assignment]
        second._collector.remote_ip = "203.0.113.10"
        second._collector.collector_pn = "PN-TWO"

        listener._at_connections["203.0.113.10"] = first
        listener._at_connections["203.0.113.10:second"] = second
        listener._at_connections_by_pn["PN-ONE"] = first
        listener._at_connections_by_pn["PN-TWO"] = second

        transport = SharedCollectorAtTransport(
            host="127.0.0.1",
            port=listener._port,
            request_timeout=1.0,
            collector_ip="203.0.113.10",
            collector_pn="PN-TWO",
            collector_session_protocol="at_text",
            collector_identity_strategy="at_dtupn",
        )
        transport._listener = listener

        self.assertTrue(transport.connected)
        self.assertEqual(transport.collector_info.collector_pn, "PN-TWO")

    async def test_transport_prefers_pn_session_over_configured_ip_placeholder(self) -> None:
        listener = _SharedEybondListener(host="127.0.0.1", port=_free_tcp_port())

        class _OpenWriter:
            def is_closing(self) -> bool:
                return False

        connection = _CollectorConnection(
            remote_ip_hint="192.168.1.6",
            heartbeat_interval=60.0,
            write_timeout=0.5,
        )
        connection._writer = _OpenWriter()  # type: ignore[assignment]
        connection._collector.remote_ip = "192.168.1.6"
        connection._collector.collector_pn = "A1234567890123"
        listener._connections["192.168.1.6"] = connection
        listener._connections_by_pn["A1234567890123"] = connection

        transport = SharedEybondTransport(
            host="127.0.0.1",
            port=listener._port,
            request_timeout=1.0,
            heartbeat_interval=60.0,
            collector_ip="192.168.2.209",
            collector_pn="A1234567890123",
        )
        transport._listener = listener

        self.assertTrue(transport.connected)
        self.assertEqual(transport.collector_info.remote_ip, "192.168.1.6")
        self.assertEqual(transport.collector_info.collector_pn, "A1234567890123")

    async def test_at_transport_prefers_pn_session_over_configured_ip_placeholder(self) -> None:
        listener = _SharedEybondListener(host="127.0.0.1", port=_free_tcp_port())

        class _OpenWriter:
            def is_closing(self) -> bool:
                return False

        connection = _CollectorAtConnection(
            remote_ip_hint="192.168.1.6",
            write_timeout=0.5,
        )
        connection._writer = _OpenWriter()  # type: ignore[assignment]
        connection._collector.remote_ip = "192.168.1.6"
        connection._collector.collector_pn = "A1234567890123"
        listener._at_connections["192.168.1.6"] = connection
        listener._at_connections_by_pn["A1234567890123"] = connection

        transport = SharedCollectorAtTransport(
            host="127.0.0.1",
            port=listener._port,
            request_timeout=1.0,
            collector_ip="192.168.2.209",
            collector_pn="A1234567890123",
            collector_session_protocol="at_text",
            collector_identity_strategy="at_dtupn",
        )
        transport._listener = listener

        self.assertTrue(transport.connected)
        self.assertEqual(transport.collector_info.remote_ip, "192.168.1.6")
        self.assertEqual(transport.collector_info.collector_pn, "A1234567890123")

    async def test_runtime_selection_does_not_pin_remote_ip_when_collector_pn_known(self) -> None:
        manager = EybondRuntimeLinkManager(
            server_ip="192.168.1.98",
            collector_ip="192.168.2.209",
            collector_pn="A1234567890123",
            tcp_port=8899,
            udp_port=58899,
            discovery_target="192.168.1.255",
            discovery_interval=3,
            heartbeat_interval=60,
            collector_configured_session_protocol="at_text",
            collector_identity_strategy="at_dtupn",
        )

        self.assertEqual(manager._selected_connected_remote_ip(), ("", False))

    async def test_listener_indexes_passive_identity_for_pn_routing(self) -> None:
        listener = _SharedEybondListener(host="127.0.0.1", port=_free_tcp_port())
        connection = _CollectorConnection(
            remote_ip_hint="203.0.113.10",
            heartbeat_interval=60.0,
            write_timeout=0.5,
        )
        listener._session_payload_connections["session-1"] = connection

        listener._mark_session_identity("session-1", "E5000020000000", "framed_heartbeat")

        self.assertIs(
            listener.ensure_connection(
                "",
                heartbeat_interval=60.0,
                write_timeout=0.5,
                collector_pn="E5000020000000",
            ),
            connection,
        )

    async def test_heartbeat_does_not_downgrade_strong_identity_evidence(self) -> None:
        listener = _SharedEybondListener(host="127.0.0.1", port=_free_tcp_port())
        listener._remember_session(
            session_id="session-strong",
            remote_ip="203.0.113.10",
            remote_port=41000,
        )
        listener._pending_sockets["session-strong"] = _PendingCollectorSocket(
            session_id="session-strong",
            remote_ip="203.0.113.10",
            remote_port=41000,
            reader=asyncio.StreamReader(),
            writer=_FakeWriter(),  # type: ignore[arg-type]
        )

        listener._mark_session_identity(
            "session-strong",
            "V001020SYN62344022",
            "at_dtupn",
        )
        listener._mark_session_identity(
            "session-strong",
            "V001020SYN6234",
            "framed_heartbeat",
        )

        session = listener.discovered_collector_sessions()[0]
        self.assertEqual(session["collector_pn"], "V001020SYN62344022")
        self.assertEqual(session["collector_identity_source"], "at_dtupn")

    async def test_release_collector_connections_drops_session_identity_indexes(self) -> None:
        listener = _SharedEybondListener(host="127.0.0.1", port=_free_tcp_port())
        connection = _CollectorConnection(
            remote_ip_hint="203.0.113.10",
            heartbeat_interval=60.0,
            write_timeout=0.5,
        )
        connection._writer = _FakeWriter()  # type: ignore[assignment]
        listener._connections["203.0.113.10"] = connection
        listener._connections_by_pn["PN-ONE"] = connection
        listener._session_payload_connections["session-one"] = connection

        await listener.release_collector_connections(
            "",
            "PN-ONE",
            close_payload=True,
        )

        self.assertNotIn("203.0.113.10", listener._connections)
        self.assertNotIn("PN-ONE", listener._connections_by_pn)
        self.assertNotIn("session-one", listener._session_payload_connections)

    async def test_release_collector_connections_closes_target_pn_on_shared_peer_ip(self) -> None:
        listener = _SharedEybondListener(host="127.0.0.1", port=_free_tcp_port())
        listener.register_payload_owner("203.0.113.10")
        listener.register_payload_pn_owner("PN-TWO")

        removed_connection = _CollectorConnection(
            remote_ip_hint="203.0.113.10",
            heartbeat_interval=60.0,
            write_timeout=0.5,
        )
        removed_writer = _FakeWriter()
        removed_connection._writer = removed_writer  # type: ignore[assignment]
        remaining_connection = _CollectorConnection(
            remote_ip_hint="203.0.113.10",
            heartbeat_interval=60.0,
            write_timeout=0.5,
        )
        remaining_writer = _FakeWriter()
        remaining_connection._writer = remaining_writer  # type: ignore[assignment]
        listener._connections["203.0.113.10:one"] = removed_connection
        listener._connections["203.0.113.10:two"] = remaining_connection
        listener._connections_by_pn["PN-ONE"] = removed_connection
        listener._connections_by_pn["PN-TWO"] = remaining_connection
        listener._session_payload_connections["session-one"] = removed_connection
        listener._session_payload_connections["session-two"] = remaining_connection

        await listener.release_collector_connections(
            "203.0.113.10",
            "PN-ONE",
            close_payload=True,
            close_pending=True,
        )

        self.assertTrue(removed_writer.closed)
        self.assertFalse(remaining_writer.closed)
        self.assertNotIn("203.0.113.10:one", listener._connections)
        self.assertIn("203.0.113.10:two", listener._connections)
        self.assertNotIn("PN-ONE", listener._connections_by_pn)
        self.assertIn("PN-TWO", listener._connections_by_pn)
        self.assertNotIn("session-one", listener._session_payload_connections)
        self.assertIn("session-two", listener._session_payload_connections)

    async def test_release_preserves_only_the_exact_scan_session(self) -> None:
        listener = _SharedEybondListener(host="127.0.0.1", port=_free_tcp_port())
        stale = _CollectorConnection(
            remote_ip_hint="203.0.113.10",
            heartbeat_interval=60.0,
            write_timeout=0.5,
        )
        stale_writer = _FakeWriter()
        stale._writer = stale_writer  # type: ignore[assignment]
        observed = _CollectorConnection(
            remote_ip_hint="203.0.113.10",
            heartbeat_interval=60.0,
            write_timeout=0.5,
        )
        observed_writer = _FakeWriter()
        observed._writer = observed_writer  # type: ignore[assignment]
        # Both private peers are eligible aliases for the same public trigger
        # route.  The preservation decision must therefore come from session_id,
        # never from peer/route matching.
        listener._connections["192.168.1.1"] = stale
        listener._connections["192.168.1.2"] = observed
        listener._session_payload_connections["session-stale"] = stale
        listener._session_payload_connections["session-observed"] = observed

        await listener.release_collector_connections(
            "8.8.8.8",
            close_payload=True,
            preserve_session_id="session-observed",
        )

        self.assertTrue(stale_writer.closed)
        self.assertFalse(observed_writer.closed)
        self.assertNotIn("session-stale", listener._session_payload_connections)
        self.assertIs(
            listener._session_payload_connections["session-observed"], observed
        )

        await listener.release_collector_connections(
            "8.8.8.8",
            close_payload=True,
        )
        self.assertTrue(observed_writer.closed)
        self.assertNotIn("session-observed", listener._session_payload_connections)

    async def test_release_collector_connections_keeps_connection_when_pn_prefix_owner_remains(self) -> None:
        listener = _SharedEybondListener(host="127.0.0.1", port=_free_tcp_port())
        listener.register_payload_pn_owner("E5000020000000")
        connection = _CollectorConnection(
            remote_ip_hint="203.0.113.10",
            heartbeat_interval=60.0,
            write_timeout=0.5,
        )
        writer = _FakeWriter()
        connection._writer = writer  # type: ignore[assignment]
        listener._connections["203.0.113.10"] = connection
        listener._connections_by_pn["E50000200000009777"] = connection

        await listener.release_collector_connections(
            "",
            "E50000200000009777",
            close_payload=True,
        )

        self.assertFalse(writer.closed)
        self.assertIn("203.0.113.10", listener._connections)
        self.assertIn("E50000200000009777", listener._connections_by_pn)

    async def test_collector_pn_prefix_match_requires_long_stable_prefix(self) -> None:
        listener = _SharedEybondListener(host="127.0.0.1", port=_free_tcp_port())

        self.assertTrue(
            listener._collector_pn_matches(
                "V001020SYN",
                "V001020SYN62344022",
            )
        )
        self.assertTrue(
            listener._collector_pn_matches(
                "E5000020000000",
                "E50000200000009777",
            )
        )
        self.assertFalse(
            listener._collector_pn_matches(
                "PN",
                "PN-ONE",
            )
        )

    async def test_disconnected_connection_drops_all_listener_indexes(self) -> None:
        listener = _SharedEybondListener(host="127.0.0.1", port=_free_tcp_port())
        connection = _CollectorConnection(
            remote_ip_hint="203.0.113.10",
            heartbeat_interval=60.0,
            write_timeout=0.5,
        )
        listener._connections["203.0.113.10"] = connection
        listener._connections["192.168.1.50"] = connection
        listener._connections_by_pn["E50000200000009777"] = connection
        listener._session_payload_connections["session-one"] = connection
        listener._remember_session(
            session_id="session-one",
            remote_ip="203.0.113.10",
            remote_port=41000,
        )
        listener._mark_session_state("session-one", "routed_framed")
        listener._mark_session_identity(
            "session-one",
            "E50000200000009777",
            "framed_heartbeat",
        )
        listener._last_connection_ip = "203.0.113.10"

        listener._drop_connection_indexes_for_connection(connection)

        self.assertNotIn("203.0.113.10", listener._connections)
        self.assertNotIn("192.168.1.50", listener._connections)
        self.assertNotIn("E50000200000009777", listener._connections_by_pn)
        self.assertNotIn("session-one", listener._session_payload_connections)
        self.assertEqual(listener._session_inventory["session-one"].state, "closed_disconnected")
        self.assertEqual(listener.discovered_collector_sessions(), ())
        self.assertEqual(listener._last_connection_ip, "")

    async def test_next_session_id_increments_once(self) -> None:
        listener = _SharedEybondListener(host="127.0.0.1", port=_free_tcp_port())

        self.assertEqual(
            listener._next_session_id(),
            f"listener-{listener._port}-1",
        )
        self.assertEqual(
            listener._next_session_id(),
            f"listener-{listener._port}-2",
        )

    async def test_release_at_connections_closes_target_pn_on_shared_peer_ip(self) -> None:
        listener = _SharedEybondListener(host="127.0.0.1", port=_free_tcp_port())
        listener.register_at_owner("203.0.113.10")
        listener.register_at_pn_owner("PN-TWO")

        removed_connection = _CollectorAtConnection(
            remote_ip_hint="203.0.113.10",
            write_timeout=0.5,
        )
        removed_writer = _FakeWriter()
        removed_connection._writer = removed_writer  # type: ignore[assignment]
        remaining_connection = _CollectorAtConnection(
            remote_ip_hint="203.0.113.10",
            write_timeout=0.5,
        )
        remaining_writer = _FakeWriter()
        remaining_connection._writer = remaining_writer  # type: ignore[assignment]
        listener._at_connections["203.0.113.10:one"] = removed_connection
        listener._at_connections["203.0.113.10:two"] = remaining_connection
        listener._at_connections_by_pn["PN-ONE"] = removed_connection
        listener._at_connections_by_pn["PN-TWO"] = remaining_connection

        await listener.release_collector_connections(
            "203.0.113.10",
            "PN-ONE",
            close_at=True,
        )

        self.assertTrue(removed_writer.closed)
        self.assertFalse(remaining_writer.closed)
        self.assertNotIn("203.0.113.10:one", listener._at_connections)
        self.assertIn("203.0.113.10:two", listener._at_connections)
        self.assertNotIn("PN-ONE", listener._at_connections_by_pn)
        self.assertIn("PN-TWO", listener._at_connections_by_pn)

    async def test_listener_routes_initial_framed_identity_to_pn_owner(self) -> None:
        listener = _SharedEybondListener(host="127.0.0.1", port=_free_tcp_port())
        listener._remember_session(
            session_id="session-1",
            remote_ip="203.0.113.10",
            remote_port=41000,
        )
        reader = asyncio.StreamReader()
        reader.feed_data(
            build_collector_request(
                7,
                b"E5000020000000",
                devcode=2376,
                collector_addr=1,
                fcode=1,
            )
        )
        reader.feed_eof()
        pending = _PendingCollectorSocket(
            remote_ip="203.0.113.10",
            remote_port=41000,
            session_id="session-1",
            reader=reader,
            writer=_FakeWriter(),  # type: ignore[arg-type]
        )
        listener._pending_sockets[pending.remote_ip] = pending

        await listener._sniff_pending_socket(pending)

        diagnostics = listener.session_inventory_diagnostics()
        self.assertEqual(diagnostics["pending_session_count"], 0)
        self.assertEqual(diagnostics["sessions"][0]["collector_identity_source"], "framed_heartbeat")
        self.assertEqual(
            diagnostics["sessions"][0]["collector_identity_masked"],
            "E50********000",
        )
        self.assertNotIn("E5000020000000", listener._connections_by_pn)
        self.assertNotIn("session-1", listener._session_payload_connections)

    async def test_listener_active_probe_routes_silent_at_session_to_pn_owner(self) -> None:
        listener = _SharedEybondListener(host="127.0.0.1", port=_free_tcp_port())
        listener.register_session_protocol_owner("at_text")
        listener.register_at_pn_owner("E5000020000000")
        listener._remember_session(
            session_id="session-1",
            remote_ip="203.0.113.10",
            remote_port=41000,
        )
        reader = asyncio.StreamReader()

        class _ProbeWriter(_FakeWriter):
            async def drain(self) -> None:
                reader.feed_data(b"AT+DTUPN:E5000020000000\r\n")
                reader.feed_eof()

        writer = _ProbeWriter()
        pending = _PendingCollectorSocket(
            remote_ip="203.0.113.10",
            remote_port=41000,
            session_id="session-1",
            reader=reader,
            writer=writer,  # type: ignore[arg-type]
        )
        listener._pending_sockets[pending.remote_ip] = pending

        await listener._sniff_pending_socket(pending)

        self.assertEqual(bytes(writer.buffer), b"AT+DTUPN?\r\n")
        diagnostics = listener.session_inventory_diagnostics()
        self.assertEqual(diagnostics["pending_session_count"], 0)
        self.assertEqual(diagnostics["sessions"][0]["collector_identity_source"], "at_dtupn")
        self.assertNotIn("E5000020000000", listener._at_connections_by_pn)
        self.assertNotIn("session-1", listener._session_at_connections)

    async def test_listener_active_probe_routes_silent_framed_session_to_pn_owner(self) -> None:
        listener = _SharedEybondListener(host="127.0.0.1", port=_free_tcp_port())
        listener.register_session_protocol_owner("eybond_framed")
        listener.register_payload_pn_owner("E5000020000000")
        listener._remember_session(
            session_id="session-1",
            remote_ip="203.0.113.10",
            remote_port=41000,
        )
        reader = asyncio.StreamReader()

        class _ProbeWriter(_FakeWriter):
            async def drain(self) -> None:
                reader.feed_data(
                    build_collector_request(
                        1,
                        b"\x00\x02E5000020000000",
                        devcode=2376,
                        collector_addr=1,
                        fcode=2,
                    )
                )
                reader.feed_eof()

        writer = _ProbeWriter()
        pending = _PendingCollectorSocket(
            remote_ip="203.0.113.10",
            remote_port=41000,
            session_id="session-1",
            reader=reader,
            writer=writer,  # type: ignore[arg-type]
        )
        listener._pending_sockets[pending.remote_ip] = pending

        await listener._sniff_pending_socket(pending)

        written = bytes(writer.buffer)
        header = decode_header(written[:HEADER_SIZE])
        self.assertEqual(header.fcode, 2)
        self.assertEqual(written[HEADER_SIZE:header.total_len], b"\x02")
        diagnostics = listener.session_inventory_diagnostics()
        self.assertEqual(diagnostics["pending_session_count"], 0)
        self.assertEqual(diagnostics["sessions"][0]["collector_identity_source"], "fc2_parameter_2")
        self.assertNotIn("E5000020000000", listener._connections_by_pn)
        self.assertNotIn("session-1", listener._session_payload_connections)

    async def test_listener_does_not_active_probe_when_registered_protocols_are_mixed(self) -> None:
        listener = _SharedEybondListener(host="127.0.0.1", port=_free_tcp_port())
        listener.register_session_protocol_owner("at_text")
        listener.register_session_protocol_owner("eybond_framed")
        listener._remember_session(
            session_id="session-1",
            remote_ip="203.0.113.10",
            remote_port=41000,
        )
        reader = asyncio.StreamReader()
        writer = _FakeWriter()
        pending = _PendingCollectorSocket(
            remote_ip="203.0.113.10",
            remote_port=41000,
            session_id="session-1",
            reader=reader,
            writer=writer,  # type: ignore[arg-type]
        )
        listener._pending_sockets[pending.remote_ip] = pending

        sniff = asyncio.create_task(listener._sniff_pending_socket(pending))
        pending.sniff_task = sniff
        await asyncio.sleep(0.4)

        # No active probe was sent (mixed protocols make one ambiguous), and
        # the identityless socket stays registered — parked under a watcher.
        self.assertEqual(bytes(writer.buffer), b"")
        self.assertIn(pending.remote_ip, listener._pending_sockets)
        self.assertEqual(
            listener.session_inventory_diagnostics()["sessions"][0]["state"],
            "parked_waiting_for_identity",
        )

        reader.feed_eof()
        await asyncio.wait_for(sniff, timeout=2.0)

    async def test_listener_routes_two_silent_at_collectors_from_same_peer_ip_by_pn(self) -> None:
        listener = _SharedEybondListener(host="127.0.0.1", port=_free_tcp_port())
        listener.register_session_protocol_owner("at_text")
        listener.register_at_pn_owner("PN-ONE")
        listener.register_at_pn_owner("PN-TWO")

        async def _run_pending(session_id: str, pn: str, port: int) -> _FakeWriter:
            listener._remember_session(
                session_id=session_id,
                remote_ip="203.0.113.10",
                remote_port=port,
            )
            reader = asyncio.StreamReader()

            class _ProbeWriter(_FakeWriter):
                async def drain(self) -> None:
                    reader.feed_data(f"AT+DTUPN:{pn}\r\n".encode("ascii"))
                    reader.feed_eof()

            writer = _ProbeWriter()
            pending = _PendingCollectorSocket(
                remote_ip="203.0.113.10",
                remote_port=port,
                session_id=session_id,
                reader=reader,
                writer=writer,  # type: ignore[arg-type]
            )
            listener._pending_sockets[session_id] = pending
            await listener._sniff_pending_socket(pending)
            return writer

        first_writer = await _run_pending("session-1", "PN-ONE", 41001)
        second_writer = await _run_pending("session-2", "PN-TWO", 41002)

        self.assertEqual(bytes(first_writer.buffer), b"AT+DTUPN?\r\n")
        self.assertEqual(bytes(second_writer.buffer), b"AT+DTUPN?\r\n")
        self.assertNotIn("PN-ONE", listener._at_connections_by_pn)
        self.assertNotIn("PN-TWO", listener._at_connections_by_pn)
        self.assertFalse(listener._session_at_connections)
        diagnostics = listener.session_inventory_diagnostics()
        self.assertEqual(diagnostics["pending_session_count"], 0)
        self.assertEqual(diagnostics["recent_session_count"], 2)
        self.assertEqual(diagnostics["duplicate_peer_ip_count"], 1)

    async def test_listener_routes_many_simultaneous_at_collectors_from_same_peer_ip_by_pn(self) -> None:
        listener = _SharedEybondListener(host="127.0.0.1", port=_free_tcp_port())
        listener.register_session_protocol_owner("at_text")
        pns = tuple(f"E50000200000{index:02d}" for index in range(8))
        for pn in pns:
            listener.register_at_pn_owner(pn)

        async def _run_pending(index: int, pn: str) -> _FakeWriter:
            session_id = f"session-{index}"
            listener._remember_session(
                session_id=session_id,
                remote_ip="203.0.113.10",
                remote_port=41000 + index,
            )
            reader = asyncio.StreamReader()

            class _ProbeWriter(_FakeWriter):
                async def drain(self) -> None:
                    await asyncio.sleep(0)
                    reader.feed_data(f"AT+DTUPN:{pn}\r\n".encode("ascii"))
                    reader.feed_eof()

            writer = _ProbeWriter()
            pending = _PendingCollectorSocket(
                remote_ip="203.0.113.10",
                remote_port=41000 + index,
                session_id=session_id,
                reader=reader,
                writer=writer,  # type: ignore[arg-type]
            )
            listener._pending_sockets[session_id] = pending
            await listener._sniff_pending_socket(pending)
            return writer

        writers = await asyncio.gather(
            *(_run_pending(index, pn) for index, pn in enumerate(pns))
        )

        self.assertTrue(all(bytes(writer.buffer) == b"AT+DTUPN?\r\n" for writer in writers))
        self.assertFalse(listener._at_connections_by_pn)
        self.assertFalse(listener._session_at_connections)
        diagnostics = listener.session_inventory_diagnostics()
        self.assertEqual(diagnostics["pending_session_count"], 0)
        self.assertEqual(diagnostics["recent_session_count"], len(pns))
        self.assertEqual(diagnostics["duplicate_peer_ip_count"], 1)

    async def test_bind_failure_rolls_back_shared_listener_registry(self) -> None:
        port = 19099
        transport = SharedEybondTransport(
            host="127.0.0.1",
            port=port,
            request_timeout=1.0,
            heartbeat_interval=60.0,
            collector_ip="",
        )
        key = ("127.0.0.1", port)

        with patch(
            "custom_components.eybond_local.collector.transport.listener.CollectorTcpAcceptor.start",
            new=AsyncMock(side_effect=OSError("could not bind on any address")),
        ):
            with self.assertRaises(CollectorListenerBindError):
                await transport.start()

        self.assertIsNone(transport._listener)
        self.assertNotIn(key, _LISTENERS)

    async def test_transport_stop_releases_listener_even_when_cancelled(self) -> None:
        port = _free_tcp_port()
        transport = SharedEybondTransport(
            host="127.0.0.1",
            port=port,
            request_timeout=1.0,
            heartbeat_interval=60.0,
            collector_ip="",
        )

        await transport.start()
        listener = transport._listener
        self.assertIsNotNone(listener)
        assert listener is not None

        release_started = asyncio.Event()
        original_release = listener.release

        async def _slow_release() -> bool:
            release_started.set()
            await asyncio.sleep(0.01)
            return await original_release()

        key = ("127.0.0.1", port)
        try:
            with patch.object(listener, "release", new=_slow_release):
                stop_task = asyncio.create_task(transport.stop())
                await asyncio.wait_for(release_started.wait(), timeout=1.0)
                stop_task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await stop_task

            self.assertIsNone(listener._server)
            self.assertNotIn(key, _LISTENERS)
            self.assertIsNone(transport._listener)
        finally:
            leaked = _LISTENERS.get(key)
            if leaked is not None:
                await leaked.release()
                _LISTENERS.pop(key, None)

    async def test_transport_routes_by_collector_ip(self) -> None:
        port = _free_tcp_port()
        targeted = SharedEybondTransport(
            host="127.0.0.1",
            port=port,
            request_timeout=1.0,
            heartbeat_interval=60.0,
            collector_ip="127.0.0.1",
        )
        other = SharedEybondTransport(
            host="127.0.0.1",
            port=port,
            request_timeout=1.0,
            heartbeat_interval=60.0,
            collector_ip="127.0.0.2",
        )

        await targeted.start()
        await other.start()

        writer = None
        try:
            _, writer = await asyncio.open_connection("127.0.0.1", port)
            writer.write(b"\x00")
            await writer.drain()
            self.assertTrue(await targeted.wait_until_connected(1.0))
            self.assertFalse(await other.wait_until_connected(0.2))
            self.assertTrue(targeted.connected)
            self.assertFalse(other.connected)
        finally:
            if writer is not None:
                writer.close()
                await writer.wait_closed()
            await targeted.stop()
            await other.stop()

    async def test_targeted_transport_stop_closes_only_own_shared_connection(self) -> None:
        port = _free_tcp_port()
        removed = SharedEybondTransport(
            host="127.0.0.1",
            port=port,
            request_timeout=1.0,
            heartbeat_interval=60.0,
            collector_ip="127.0.0.1",
        )
        remaining = SharedEybondTransport(
            host="127.0.0.1",
            port=port,
            request_timeout=1.0,
            heartbeat_interval=60.0,
            collector_ip="127.0.0.2",
        )

        await removed.start()
        await remaining.start()
        listener = removed._listener
        self.assertIsNotNone(listener)
        assert listener is not None

        removed_connection = _CollectorConnection(
            remote_ip_hint="127.0.0.1",
            heartbeat_interval=60.0,
            write_timeout=0.5,
        )
        removed_writer = _FakeWriter()
        removed_connection._writer = removed_writer  # type: ignore[assignment]
        remaining_connection = _CollectorConnection(
            remote_ip_hint="127.0.0.2",
            heartbeat_interval=60.0,
            write_timeout=0.5,
        )
        remaining_writer = _FakeWriter()
        remaining_connection._writer = remaining_writer  # type: ignore[assignment]
        listener._connections["127.0.0.1"] = removed_connection
        listener._connections["127.0.0.2"] = remaining_connection

        try:
            await removed.stop()

            self.assertTrue(removed_writer.closed)
            self.assertFalse(remaining_writer.closed)
            self.assertNotIn("127.0.0.1", listener._connections)
            self.assertIn("127.0.0.2", listener._connections)
            self.assertIn(("127.0.0.1", port), _LISTENERS)
        finally:
            await remaining.stop()

    async def test_targeted_transport_stop_closes_own_pending_socket(self) -> None:
        port = _free_tcp_port()
        removed = SharedEybondTransport(
            host="127.0.0.1",
            port=port,
            request_timeout=1.0,
            heartbeat_interval=60.0,
            collector_ip="127.0.0.1",
        )
        remaining = SharedEybondTransport(
            host="127.0.0.1",
            port=port,
            request_timeout=1.0,
            heartbeat_interval=60.0,
            collector_ip="127.0.0.2",
        )

        await removed.start()
        await remaining.start()
        listener = removed._listener
        self.assertIsNotNone(listener)
        assert listener is not None

        pending_writer = _FakeWriter()
        listener._pending_sockets["127.0.0.1"] = _PendingCollectorSocket(
            remote_ip="127.0.0.1",
            reader=asyncio.StreamReader(),
            writer=pending_writer,  # type: ignore[arg-type]
        )

        try:
            await removed.stop()

            self.assertTrue(pending_writer.closed)
            self.assertNotIn("127.0.0.1", listener._pending_sockets)
            self.assertIn(("127.0.0.1", port), _LISTENERS)
        finally:
            await remaining.stop()

    async def test_unowned_callback_does_not_create_orphan_connection_on_targeted_listener(self) -> None:
        port = _free_tcp_port()
        remaining = SharedEybondTransport(
            host="127.0.0.1",
            port=port,
            request_timeout=1.0,
            heartbeat_interval=60.0,
            collector_ip="127.0.0.2",
        )

        await remaining.start()
        listener = remaining._listener
        self.assertIsNotNone(listener)
        assert listener is not None

        reader = writer = None
        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            writer.write(b"\x00")
            await writer.drain()
            await asyncio.sleep(0.6)

            # The unowned callback is parked (held open), never routed into a
            # collector connection and never reported as transport-connected.
            self.assertNotIn("127.0.0.1", listener._connections)
            self.assertFalse(await remaining.wait_until_connected(0.05))
            states = {
                session["session_id"]: session["state"]
                for session in listener.session_inventory_diagnostics()["sessions"]
            }
            self.assertIn("waiting_for_more_initial_bytes", states.values())
            self.assertTrue(listener._server is not None)
        finally:
            if writer is not None:
                writer.close()
                await writer.wait_closed()
            await remaining.stop()

    async def test_targeted_at_transport_stop_closes_only_own_at_connection(self) -> None:
        port = _free_tcp_port()
        removed = SharedCollectorAtTransport(
            host="127.0.0.1",
            port=port,
            request_timeout=1.0,
            collector_ip="127.0.0.1",
        )
        remaining = SharedCollectorAtTransport(
            host="127.0.0.1",
            port=port,
            request_timeout=1.0,
            collector_ip="127.0.0.2",
        )

        await removed.start()
        await remaining.start()
        listener = removed._listener
        self.assertIsNotNone(listener)
        assert listener is not None

        removed_connection = _CollectorAtConnection(
            remote_ip_hint="127.0.0.1",
            write_timeout=0.5,
        )
        removed_writer = _FakeWriter()
        removed_connection._writer = removed_writer  # type: ignore[assignment]
        remaining_connection = _CollectorAtConnection(
            remote_ip_hint="127.0.0.2",
            write_timeout=0.5,
        )
        remaining_writer = _FakeWriter()
        remaining_connection._writer = remaining_writer  # type: ignore[assignment]
        listener._at_connections["127.0.0.1"] = removed_connection
        listener._at_connections["127.0.0.2"] = remaining_connection

        try:
            await removed.stop()

            self.assertTrue(removed_writer.closed)
            self.assertFalse(remaining_writer.closed)
            self.assertNotIn("127.0.0.1", listener._at_connections)
            self.assertIn("127.0.0.2", listener._at_connections)
            self.assertIn(("127.0.0.1", port), _LISTENERS)
        finally:
            await remaining.stop()

    async def test_targeted_transport_can_disconnect_its_new_shared_connection(self) -> None:
        port = _free_tcp_port()
        owner = SharedEybondTransport(
            host="127.0.0.1",
            port=port,
            request_timeout=1.0,
            heartbeat_interval=60.0,
            collector_ip="",
        )
        targeted = SharedEybondTransport(
            host="127.0.0.1",
            port=port,
            request_timeout=1.0,
            heartbeat_interval=60.0,
            collector_ip="127.0.0.1",
        )

        connected = asyncio.Event()
        disconnected = asyncio.Event()

        async def _collector_client() -> None:
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            connected.set()
            try:
                self.assertEqual(await reader.read(1), b"")
                disconnected.set()
            finally:
                writer.close()
                await writer.wait_closed()

        async def _quiet_heartbeat(self) -> None:
            return None

        client_task: asyncio.Task[None] | None = None
        with patch.object(_CollectorConnection, "_heartbeat_loop", new=_quiet_heartbeat):
            await owner.start()
            snapshot = await targeted.async_snapshot_shared_connection()
            await targeted.start()
            try:
                client_task = asyncio.create_task(_collector_client())
                await asyncio.wait_for(connected.wait(), timeout=1.0)
                self.assertTrue(await targeted.wait_until_connected(0.2))
                self.assertTrue(owner.connected)

                await targeted.async_disconnect_if_new_shared_connection(snapshot)

                await asyncio.wait_for(disconnected.wait(), timeout=0.5)
                self.assertFalse(owner.connected)
                self.assertIsNotNone(owner._listener)
            finally:
                await targeted.stop()
                await owner.stop()
                if client_task is not None:
                    await client_task

    async def test_wait_until_connected_activates_pending_socket(self) -> None:
        port = _free_tcp_port()
        transport = SharedEybondTransport(
            host="127.0.0.1",
            port=port,
            request_timeout=1.0,
            heartbeat_interval=60.0,
            collector_ip="127.0.0.1",
        )

        connected = asyncio.Event()
        release_client = asyncio.Event()

        async def _collector_client() -> None:
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            connected.set()
            try:
                header = decode_header(await asyncio.wait_for(reader.readexactly(HEADER_SIZE), timeout=1.0))
                payload = await asyncio.wait_for(reader.readexactly(header.payload_len), timeout=1.0)
                self.assertEqual(header.fcode, 2)
                self.assertEqual(payload, b"\x05")
                writer.write(
                    build_collector_request(
                        header.tid,
                        b"OK",
                        devcode=header.devcode,
                        collector_addr=header.devaddr,
                        fcode=header.fcode,
                    )
                )
                await writer.drain()
                await release_client.wait()
            finally:
                writer.close()
                await writer.wait_closed()

        async def _quiet_heartbeat(self) -> None:
            return None

        with patch.object(_CollectorConnection, "_heartbeat_loop", new=_quiet_heartbeat):
            await transport.start()
            client_task = asyncio.create_task(_collector_client())
            try:
                await asyncio.wait_for(connected.wait(), timeout=1.0)
                self.assertTrue(await transport.wait_until_connected(0.2))
                self.assertTrue(transport.connected)
                header, payload = await transport.async_send_collector(fcode=2, payload=b"\x05")
                self.assertEqual(header.fcode, 2)
                self.assertEqual(payload, b"OK")
                self.assertTrue(transport.connected)
            finally:
                release_client.set()
                await client_task
                await transport.stop()

    async def test_sniffed_initial_heartbeat_preserves_frame_order_for_follow_up_queries(self) -> None:
        port = _free_tcp_port()
        transport = SharedEybondTransport(
            host="127.0.0.1",
            port=port,
            request_timeout=1.0,
            heartbeat_interval=60.0,
            collector_ip="127.0.0.1",
        )

        connected = asyncio.Event()
        heartbeat_sent = asyncio.Event()

        async def _collector_client() -> None:
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            connected.set()
            try:
                writer.write(
                    build_collector_request(
                        1,
                        b"E5000099990003",
                        devcode=0x0994,
                        collector_addr=1,
                        fcode=1,
                    )
                )
                await writer.drain()
                heartbeat_sent.set()

                header = decode_header(await asyncio.wait_for(reader.readexactly(HEADER_SIZE), timeout=1.0))
                payload = await asyncio.wait_for(reader.readexactly(header.payload_len), timeout=1.0)
                self.assertEqual(header.fcode, 2)
                self.assertEqual(payload, b"\x05")
                writer.write(
                    build_collector_request(
                        header.tid,
                        b"\x01\x05",
                        devcode=header.devcode,
                        collector_addr=header.devaddr,
                        fcode=header.fcode,
                    )
                )
                await writer.drain()
            finally:
                writer.close()
                await writer.wait_closed()

        async def _quiet_heartbeat(self) -> None:
            return None

        with patch.object(_CollectorConnection, "_heartbeat_loop", new=_quiet_heartbeat):
            await transport.start()
            client_task = asyncio.create_task(_collector_client())
            try:
                await asyncio.wait_for(connected.wait(), timeout=1.0)
                await asyncio.wait_for(heartbeat_sent.wait(), timeout=1.0)
                await asyncio.sleep(0.05)
                self.assertTrue(await transport.wait_until_connected(0.2))
                self.assertTrue(await transport.wait_until_heartbeat(0.2))
                self.assertEqual(transport.collector_info.collector_pn, "E5000099990003")

                header, payload = await transport.async_send_collector(
                    fcode=2,
                    payload=b"\x05",
                    devcode=1,
                    collector_addr=1,
                )
                self.assertEqual(header.fcode, 2)
                self.assertEqual(payload, b"\x01\x05")
            finally:
                await client_task
                await transport.stop()

    async def test_wait_until_heartbeat_activates_pending_socket(self) -> None:
        port = _free_tcp_port()
        transport = SharedEybondTransport(
            host="127.0.0.1",
            port=port,
            request_timeout=1.0,
            heartbeat_interval=60.0,
            collector_ip="127.0.0.1",
        )

        connected = asyncio.Event()
        release = asyncio.Event()

        async def _collector_client() -> None:
            _reader, writer = await asyncio.open_connection("127.0.0.1", port)
            connected.set()
            try:
                await asyncio.wait_for(release.wait(), timeout=1.0)
            finally:
                writer.close()
                await writer.wait_closed()

        async def _quiet_heartbeat(self) -> None:
            return None

        with patch.object(_CollectorConnection, "_heartbeat_loop", new=_quiet_heartbeat):
            await transport.start()
            client_task = asyncio.create_task(_collector_client())
            try:
                await asyncio.wait_for(connected.wait(), timeout=1.0)
                self.assertTrue(await transport.wait_until_connected(0.2))
                self.assertTrue(transport.connected)
                self.assertFalse(await transport.wait_until_heartbeat(0.02))
                self.assertTrue(transport.connected)
            finally:
                release.set()
                await client_task
                await transport.stop()

    async def test_listener_aliases_single_public_placeholder_for_hairpin_callback(self) -> None:
        listener = _SharedEybondListener(host="127.0.0.1", port=_free_tcp_port())
        placeholder = listener.ensure_connection(
            "93.184.216.34",
            heartbeat_interval=60.0,
            write_timeout=0.5,
        )

        aliased = listener._resolve_public_placeholder_alias("192.168.1.1")

        self.assertIs(aliased, placeholder)
        self.assertIs(listener._connections["93.184.216.34"], placeholder)
        self.assertIs(listener._connections["192.168.1.1"], placeholder)

    async def test_listener_skips_hairpin_alias_when_public_placeholders_are_ambiguous(self) -> None:
        listener = _SharedEybondListener(host="127.0.0.1", port=_free_tcp_port())
        listener.ensure_connection(
            "93.184.216.34",
            heartbeat_interval=60.0,
            write_timeout=0.5,
        )
        listener.ensure_connection(
            "1.1.1.1",
            heartbeat_interval=60.0,
            write_timeout=0.5,
        )

        aliased = listener._resolve_public_placeholder_alias("192.168.1.1")

        self.assertIsNone(aliased)
        self.assertNotIn("192.168.1.1", listener._connections)

    async def test_listener_aliases_single_default_broadcast_placeholder_for_callback(self) -> None:
        listener = _SharedEybondListener(host="127.0.0.1", port=_free_tcp_port())
        placeholder = listener.ensure_connection(
            "192.168.1.255",
            heartbeat_interval=60.0,
            write_timeout=0.5,
        )

        aliased = listener._resolve_public_placeholder_alias("192.168.1.55")

        self.assertIs(aliased, placeholder)
        self.assertIs(listener._connections["192.168.1.255"], placeholder)
        self.assertIs(listener._connections["192.168.1.55"], placeholder)

    async def test_listener_does_not_alias_private_gateway_callback_to_collector_ip(self) -> None:
        listener = _SharedEybondListener(host="127.0.0.1", port=_free_tcp_port())
        listener.ensure_connection(
            "192.168.1.55",
            heartbeat_interval=60.0,
            write_timeout=0.5,
        )

        aliased = listener._resolve_public_placeholder_alias("192.168.1.1")

        self.assertIsNone(aliased)
        self.assertNotIn("192.168.1.1", listener._connections)

    async def test_listener_rejects_ambiguous_pending_sockets_for_default_broadcast_placeholder(self) -> None:
        listener = _SharedEybondListener(host="127.0.0.1", port=_free_tcp_port())
        listener.ensure_connection(
            "192.168.1.255",
            heartbeat_interval=60.0,
            write_timeout=0.5,
        )
        first = _PendingCollectorSocket(
            remote_ip="192.168.1.55",
            reader=asyncio.StreamReader(),
            writer=object(),
        )
        second = _PendingCollectorSocket(
            remote_ip="192.168.1.14",
            reader=asyncio.StreamReader(),
            writer=object(),
        )
        listener._pending_sockets[first.remote_ip] = first
        listener._pending_sockets[second.remote_ip] = second
        listener._last_pending_ip = second.remote_ip

        selected = listener.pop_pending_socket("192.168.1.255")

        self.assertIsNone(selected)
        self.assertIn(first.remote_ip, listener._pending_sockets)
        self.assertIn(second.remote_ip, listener._pending_sockets)

    async def test_listener_matching_callback_ips_returns_connected_and_pending_broadcast_matches(self) -> None:
        listener = _SharedEybondListener(host="127.0.0.1", port=_free_tcp_port())
        listener.ensure_connection(
            "192.168.1.255",
            heartbeat_interval=60.0,
            write_timeout=0.5,
        )
        connected = listener.ensure_connection(
            "192.168.1.55",
            heartbeat_interval=60.0,
            write_timeout=0.5,
        )

        class _OpenWriter:
            def is_closing(self) -> bool:
                return False

        connected._writer = _OpenWriter()  # type: ignore[assignment]
        listener._pending_sockets["192.168.1.14"] = _PendingCollectorSocket(
            remote_ip="192.168.1.14",
            reader=asyncio.StreamReader(),
            writer=object(),
        )

        self.assertEqual(
            set(listener.matching_callback_ips("192.168.1.255")),
            {"192.168.1.55", "192.168.1.14"},
        )

    async def test_listener_current_connection_returns_none_when_multiple_active_connections_exist(self) -> None:
        listener = _SharedEybondListener(host="127.0.0.1", port=_free_tcp_port())
        first = listener.ensure_connection(
            "127.0.0.1",
            heartbeat_interval=60.0,
            write_timeout=0.5,
        )
        second = listener.ensure_connection(
            "127.0.0.2",
            heartbeat_interval=60.0,
            write_timeout=0.5,
        )

        class _OpenWriter:
            def is_closing(self) -> bool:
                return False

        first._writer = _OpenWriter()  # type: ignore[assignment]
        second._writer = _OpenWriter()  # type: ignore[assignment]
        listener._last_connection_ip = "127.0.0.2"

        self.assertIsNone(listener.current_connection(heartbeat_interval=60.0, write_timeout=0.5))

    async def test_listener_current_at_connection_returns_none_when_multiple_active_connections_exist(self) -> None:
        listener = _SharedEybondListener(host="127.0.0.1", port=_free_tcp_port())
        first = listener.ensure_at_connection(
            "127.0.0.1",
            write_timeout=0.5,
        )
        second = listener.ensure_at_connection(
            "127.0.0.2",
            write_timeout=0.5,
        )

        class _OpenWriter:
            def is_closing(self) -> bool:
                return False

        first._writer = _OpenWriter()  # type: ignore[assignment]
        second._writer = _OpenWriter()  # type: ignore[assignment]
        listener._last_at_connection_ip = "127.0.0.2"

        self.assertIsNone(listener.current_at_connection(write_timeout=0.5))

    async def test_listener_current_connection_sees_collector_pn_only_connection(self) -> None:
        listener = _SharedEybondListener(host="127.0.0.1", port=_free_tcp_port())
        connection = listener.ensure_connection(
            "",
            heartbeat_interval=60.0,
            write_timeout=0.5,
            collector_pn="V001020SYN62344022",
        )

        class _OpenWriter:
            def is_closing(self) -> bool:
                return False

        connection._writer = _OpenWriter()  # type: ignore[assignment]

        self.assertIs(
            listener.current_connection(heartbeat_interval=60.0, write_timeout=0.5),
            connection,
        )

    async def test_listener_current_at_connection_sees_collector_pn_only_connection(self) -> None:
        listener = _SharedEybondListener(host="127.0.0.1", port=_free_tcp_port())
        connection = listener.ensure_at_connection(
            "",
            write_timeout=0.5,
            collector_pn="V001020SYN62344022",
        )

        class _OpenWriter:
            def is_closing(self) -> bool:
                return False

        connection._writer = _OpenWriter()  # type: ignore[assignment]

        self.assertIs(listener.current_at_connection(write_timeout=0.5), connection)

    async def test_listener_collector_pn_lookup_prefers_connected_short_alias_over_disconnected_exact_placeholder(self) -> None:
        listener = _SharedEybondListener(host="127.0.0.1", port=_free_tcp_port())
        full_pn = "V001020SYN62344022"
        short_pn = "V001020SYN6234"
        placeholder = listener.ensure_at_connection(
            "",
            write_timeout=0.5,
            collector_pn=full_pn,
        )
        active = _CollectorAtConnection(
            remote_ip_hint="195.138.86.175",
            write_timeout=0.5,
        )

        class _OpenWriter:
            def is_closing(self) -> bool:
                return False

        active._writer = _OpenWriter()  # type: ignore[assignment]
        listener._at_connections_by_pn[short_pn] = active

        self.assertIsNot(placeholder, active)
        self.assertIs(
            listener.ensure_at_connection(
                "",
                write_timeout=0.5,
                collector_pn=full_pn,
            ),
            active,
        )

    async def test_listener_payload_pn_lookup_prefers_connected_short_alias_over_disconnected_exact_placeholder(self) -> None:
        listener = _SharedEybondListener(host="127.0.0.1", port=_free_tcp_port())
        full_pn = "V001020SYN62344022"
        short_pn = "V001020SYN6234"
        placeholder = listener.ensure_connection(
            "",
            heartbeat_interval=60.0,
            write_timeout=0.5,
            collector_pn=full_pn,
        )
        active = _CollectorConnection(
            remote_ip_hint="195.138.86.175",
            heartbeat_interval=60.0,
            write_timeout=0.5,
        )

        class _OpenWriter:
            def is_closing(self) -> bool:
                return False

        active._writer = _OpenWriter()  # type: ignore[assignment]
        listener._connections_by_pn[short_pn] = active

        self.assertIsNot(placeholder, active)
        self.assertIs(
            listener.ensure_connection(
                "",
                heartbeat_interval=60.0,
                write_timeout=0.5,
                collector_pn=full_pn,
            ),
            active,
        )

    async def test_listener_pop_pending_socket_without_collector_ip_returns_none_when_multiple_pending_exist(self) -> None:
        listener = _SharedEybondListener(host="127.0.0.1", port=_free_tcp_port())
        listener._pending_sockets["127.0.0.1"] = _PendingCollectorSocket(
            remote_ip="127.0.0.1",
            reader=asyncio.StreamReader(),
            writer=object(),
        )
        listener._pending_sockets["127.0.0.2"] = _PendingCollectorSocket(
            remote_ip="127.0.0.2",
            reader=asyncio.StreamReader(),
            writer=object(),
        )
        listener._last_pending_ip = "127.0.0.2"

        self.assertIsNone(listener.pop_pending_socket(""))

    async def test_transport_without_collector_ip_rejects_ambiguous_pending_send(self) -> None:
        port = _free_tcp_port()
        transport = SharedEybondTransport(
            host="127.0.0.1",
            port=port,
            request_timeout=1.0,
            heartbeat_interval=60.0,
            collector_ip="",
        )

        class _IdleWriter:
            def close(self) -> None:
                return None

            async def wait_closed(self) -> None:
                return None

        await transport.start()
        try:
            listener = transport._listener
            assert listener is not None
            listener._pending_sockets["127.0.0.1"] = _PendingCollectorSocket(
                remote_ip="127.0.0.1",
                reader=asyncio.StreamReader(),
                writer=_IdleWriter(),
            )
            listener._pending_sockets["127.0.0.2"] = _PendingCollectorSocket(
                remote_ip="127.0.0.2",
                reader=asyncio.StreamReader(),
                writer=_IdleWriter(),
            )

            with self.assertRaisesRegex(ConnectionError, "collector_not_connected"):
                await transport.async_send_collector(fcode=2, payload=b"\x05")
        finally:
            await transport.stop()

    async def test_at_transport_without_collector_ip_rejects_ambiguous_pending_query(self) -> None:
        port = _free_tcp_port()
        transport = SharedCollectorAtTransport(
            host="127.0.0.1",
            port=port,
            request_timeout=1.0,
            collector_ip="",
        )

        class _IdleWriter:
            def close(self) -> None:
                return None

            async def wait_closed(self) -> None:
                return None

        await transport.start()
        try:
            listener = transport._listener
            assert listener is not None
            listener._pending_sockets["127.0.0.1"] = _PendingCollectorSocket(
                remote_ip="127.0.0.1",
                reader=asyncio.StreamReader(),
                writer=_IdleWriter(),
            )
            listener._pending_sockets["127.0.0.2"] = _PendingCollectorSocket(
                remote_ip="127.0.0.2",
                reader=asyncio.StreamReader(),
                writer=_IdleWriter(),
            )

            with self.assertRaisesRegex(ConnectionError, "collector_not_connected"):
                await transport.async_query("WFSS")
        finally:
            await transport.stop()

    async def test_at_text_transport_ignores_connected_framed_connection(self) -> None:
        transport = SharedCollectorAtTransport(
            host="127.0.0.1",
            port=_free_tcp_port(),
            request_timeout=1.0,
            collector_ip="",
            collector_session_protocol="at_text",
        )
        framed = types.SimpleNamespace(
            connected=True,
            collector_info=CollectorInfo(remote_ip="framed"),
            async_query=AsyncMock(
                return_value=CollectorAtResponse(command="DTUPN", value="framed", raw="")
            ),
        )
        at = types.SimpleNamespace(
            connected=True,
            collector_info=CollectorInfo(remote_ip="at"),
            async_query=AsyncMock(
                return_value=CollectorAtResponse(command="DTUPN", value="at", raw="")
            ),
        )
        transport._framed_connection = lambda create_placeholder: framed  # type: ignore[method-assign]
        transport._at_connection = lambda create_placeholder: at  # type: ignore[method-assign]

        self.assertTrue(transport.connected)
        self.assertEqual(transport.collector_info.remote_ip, "at")
        response = await transport.async_query("DTUPN")

        self.assertEqual(response.value, "at")
        framed.async_query.assert_not_awaited()
        at.async_query.assert_awaited_once()

    async def test_listener_uses_hairpin_alias_during_connection_handling(self) -> None:
        listener = _SharedEybondListener(host="127.0.0.1", port=_free_tcp_port())
        placeholder = listener.ensure_connection(
            "93.184.216.34",
            heartbeat_interval=60.0,
            write_timeout=0.5,
        )

        class _FakeWriter:
            def get_extra_info(self, name: str):
                if name == "peername":
                    return ("192.168.1.1", 12345)
                return None

            def close(self) -> None:
                return None

            async def wait_closed(self) -> None:
                return None

        reader = asyncio.StreamReader()

        with patch.object(placeholder, "run", new=AsyncMock()) as run_mock:
            await listener._handle_connection(reader, _FakeWriter())
            pending = await listener.pop_pending_socket_for_route(
                collector_ip="93.184.216.34",
            )
            self.assertIsNotNone(pending)
            assert pending is not None
            await listener.activate_pending_connection(
                pending,
                collector_ip="93.184.216.34",
                heartbeat_interval=60.0,
                write_timeout=0.5,
            )
            await asyncio.sleep(0)

        run_mock.assert_awaited_once()
        self.assertEqual(listener._last_connection_ip, "192.168.1.1")
        self.assertIs(listener._connections["192.168.1.1"], placeholder)

    async def test_listener_uses_default_broadcast_alias_during_connection_handling(self) -> None:
        listener = _SharedEybondListener(host="127.0.0.1", port=_free_tcp_port())
        placeholder = listener.ensure_connection(
            "192.168.1.255",
            heartbeat_interval=60.0,
            write_timeout=0.5,
        )

        class _FakeWriter:
            def get_extra_info(self, name: str):
                if name == "peername":
                    return ("192.168.1.55", 12345)
                return None

            def close(self) -> None:
                return None

            async def wait_closed(self) -> None:
                return None

        reader = asyncio.StreamReader()

        with patch.object(placeholder, "run", new=AsyncMock()) as run_mock:
            await listener._handle_connection(reader, _FakeWriter())
            pending = await listener.pop_pending_socket_for_route(
                collector_ip="192.168.1.255",
            )
            self.assertIsNotNone(pending)
            assert pending is not None
            await listener.activate_pending_connection(
                pending,
                collector_ip="192.168.1.255",
                heartbeat_interval=60.0,
                write_timeout=0.5,
            )
            await asyncio.sleep(0)

        run_mock.assert_awaited_once()
        self.assertEqual(listener._last_connection_ip, "192.168.1.55")
        self.assertIs(listener._connections["192.168.1.55"], placeholder)

    async def test_proxy_capture_route_passes_matching_pending_socket_to_handler(self) -> None:
        handled_chunks: list[bytes] = []

        class _FakeWriter:
            def __init__(self) -> None:
                self.buffer = bytearray()
                self.closed = False

            def write(self, data: bytes) -> None:
                self.buffer.extend(data)

            async def drain(self) -> None:
                return None

            def close(self) -> None:
                self.closed = True

            async def wait_closed(self) -> None:
                return None

        class _FakeListener:
            def __init__(self, pending: _PendingCollectorSocket) -> None:
                self._pending = pending
                self.calls: list[tuple[str, str, str]] = []

            async def pop_pending_socket_for_route(
                self,
                *,
                collector_ip: str = "",
                collector_pn: str = "",
                session_protocol: str = "",
            ) -> _PendingCollectorSocket | None:
                self.calls.append((collector_ip, collector_pn, session_protocol))
                pending = self._pending
                self._pending = None  # type: ignore[assignment]
                return pending

        reader = asyncio.StreamReader()
        reader.feed_data(b"ping")
        reader.feed_eof()
        writer = _FakeWriter()
        pending = _PendingCollectorSocket(
            remote_ip="127.0.0.1",
            reader=reader,
            writer=writer,  # type: ignore[arg-type]
        )

        async def _handler(
            pending_reader: asyncio.StreamReader,
            pending_writer: asyncio.StreamWriter,
        ) -> None:
            handled_chunks.append(await pending_reader.readexactly(4))
            pending_writer.write(b"pong")
            await pending_writer.drain()
            route._running = False
            pending_writer.close()
            await pending_writer.wait_closed()

        route = SharedProxyCaptureRoute(
            host="127.0.0.1",
            port=8899,
            collector_ip="127.0.0.1",
            expected_session_protocol="at_text",
            handler=_handler,
        )
        route._listener = _FakeListener(pending)  # type: ignore[assignment]
        route._running = True

        await route._route_loop()

        self.assertEqual(handled_chunks, [b"ping"])
        self.assertEqual(bytes(writer.buffer), b"pong")
        self.assertTrue(writer.closed)

    async def test_proxy_capture_route_owns_listener_reservation_for_its_lifetime(
        self,
    ) -> None:
        port = _free_tcp_port()

        async def _handler(
            _reader: asyncio.StreamReader,
            _writer: asyncio.StreamWriter,
        ) -> None:
            return None

        route = SharedProxyCaptureRoute(
            host="127.0.0.1",
            port=port,
            collector_ip="192.168.1.55",
            collector_pn="E50000200000000001",
            expected_session_protocol="at_text",
            handler=_handler,
        )
        await route.start()
        listener = route._listener
        assert listener is not None
        self.assertEqual(len(listener._exclusive_routes), 1)
        self.assertIsNotNone(route._reservation_token)

        await route.stop()

        self.assertEqual(listener._exclusive_routes, {})
        self.assertIsNone(route._reservation_token)
        self.assertNotIn(("127.0.0.1", port), _LISTENERS)

    async def test_transparent_route_claims_fresh_silent_socket_without_probe(self) -> None:
        listener = _SharedEybondListener(host="127.0.0.1", port=8899)
        old_reader = asyncio.StreamReader()
        old_pending = _PendingCollectorSocket(
            session_id="baseline-session",
            remote_ip="192.168.1.1",
            reader=old_reader,
            writer=_FakeWriter(),  # type: ignore[arg-type]
        )
        listener._pending_sockets[old_pending.session_id] = old_pending
        token = listener.register_exclusive_collector_route(
            collector_ip="192.168.1.55",
            collector_pn="E50000200000000001",
            transparent=True,
            expected_session_protocol="at_text",
        )

        new_reader = asyncio.StreamReader()
        new_writer = _FakeWriter()
        new_pending = _PendingCollectorSocket(
            session_id="fresh-session",
            remote_ip="192.168.1.1",
            reader=new_reader,
            writer=new_writer,  # type: ignore[arg-type]
        )
        listener._remember_session(
            session_id=new_pending.session_id,
            remote_ip=new_pending.remote_ip,
            remote_port=41000,
        )
        listener._pending_sockets[new_pending.session_id] = new_pending
        sniff = asyncio.create_task(listener._sniff_pending_socket(new_pending))
        new_pending.sniff_task = sniff

        # The passive sniffer stays live while the route reservation exists;
        # this lets an initially ambiguous framed socket reveal itself later.
        await asyncio.sleep(0.35)
        self.assertEqual(bytes(new_writer.buffer), b"")
        self.assertFalse(sniff.done())

        claimed = await listener.pop_pending_socket_for_transparent_route(token)

        self.assertIs(claimed, new_pending)
        self.assertEqual(claimed.initial_bytes, b"")
        self.assertIn("baseline-session", listener._pending_sockets)
        self.assertNotIn("fresh-session", listener._pending_sockets)
        with self.assertRaises(asyncio.CancelledError):
            await sniff

    async def test_runtime_cannot_probe_fresh_transparent_route_socket(self) -> None:
        listener = _SharedEybondListener(host="127.0.0.1", port=8899)
        collector_pn = "E50000200000000001"
        token = listener.register_exclusive_collector_route(
            collector_ip="192.168.1.55",
            collector_pn=collector_pn,
            transparent=True,
            expected_session_protocol="at_text",
        )

        reader = asyncio.StreamReader()
        writer = _FakeWriter()
        pending = _PendingCollectorSocket(
            session_id="fresh-cloud-session",
            remote_ip="192.168.1.1",
            reader=reader,
            writer=writer,  # type: ignore[arg-type]
        )
        listener._remember_session(
            session_id=pending.session_id,
            remote_ip=pending.remote_ip,
            remote_port=41000,
        )
        listener._pending_sockets[pending.session_id] = pending
        sniff = asyncio.create_task(listener._sniff_pending_socket(pending))
        pending.sniff_task = sniff

        await asyncio.sleep(0.35)
        claimed_by_runtime = await listener.pop_pending_socket_for_route(
            collector_ip="192.168.1.55",
            collector_pn=collector_pn,
            session_protocol="eybond_framed",
        )

        self.assertIsNone(claimed_by_runtime)
        self.assertEqual(bytes(writer.buffer), b"")
        claimed_by_proxy = await listener.pop_pending_socket_for_transparent_route(
            token
        )
        self.assertIs(claimed_by_proxy, pending)
        with self.assertRaises(asyncio.CancelledError):
            await sniff

    async def test_transparent_route_refuses_ambiguous_or_strong_foreign_socket(
        self,
    ) -> None:
        listener = _SharedEybondListener(host="127.0.0.1", port=8899)
        token = listener.register_exclusive_collector_route(
            collector_ip="192.168.1.55",
            collector_pn="E50000200000000001",
            transparent=True,
            expected_session_protocol="at_text",
        )
        for session_id in ("fresh-one", "fresh-two"):
            listener._remember_session(
                session_id=session_id,
                remote_ip="192.168.1.1",
                remote_port=41000,
            )
            listener._pending_sockets[session_id] = _PendingCollectorSocket(
                session_id=session_id,
                remote_ip="192.168.1.1",
                reader=asyncio.StreamReader(),
                writer=_FakeWriter(),  # type: ignore[arg-type]
            )

        self.assertIsNone(
            await listener.pop_pending_socket_for_transparent_route(token)
        )

        listener._pending_sockets.pop("fresh-two")
        listener._mark_session_identity(
            "fresh-one",
            "V001020SYN62344022",
            "fc2_parameter_2",
        )
        self.assertIsNone(
            await listener.pop_pending_socket_for_transparent_route(token)
        )

    async def test_transparent_at_route_ignores_fresh_framed_ha_session(
        self,
    ) -> None:
        listener = _SharedEybondListener(host="127.0.0.1", port=8899)
        collector_pn = "E50000200000000001"
        token = listener.register_exclusive_collector_route(
            collector_ip="192.168.1.55",
            collector_pn=collector_pn,
            transparent=True,
            expected_session_protocol="at_text",
        )

        framed = _PendingCollectorSocket(
            session_id="fresh-framed-ha",
            remote_ip="192.168.1.1",
            reader=asyncio.StreamReader(),
            writer=_FakeWriter(),  # type: ignore[arg-type]
        )
        listener._remember_session(
            session_id=framed.session_id,
            remote_ip=framed.remote_ip,
            remote_port=41001,
        )
        listener._mark_session_first_bytes(
            framed.session_id,
            build_collector_request(
                1,
                collector_pn[:16].encode("ascii"),
                devcode=2376,
                collector_addr=1,
                fcode=1,
            ),
        )
        listener._mark_session_identity(
            framed.session_id,
            collector_pn,
            "fc2_parameter_2",
        )
        listener._pending_sockets[framed.session_id] = framed

        cloud = _PendingCollectorSocket(
            session_id="fresh-at-cloud",
            remote_ip="192.168.1.1",
            reader=asyncio.StreamReader(),
            writer=_FakeWriter(),  # type: ignore[arg-type]
        )
        listener._remember_session(
            session_id=cloud.session_id,
            remote_ip=cloud.remote_ip,
            remote_port=41002,
        )
        listener._mark_session_first_bytes(
            cloud.session_id,
            f"AT+DTUPN:{collector_pn}\r\n".encode("ascii"),
        )
        listener._mark_session_identity(
            cloud.session_id,
            collector_pn,
            "at_dtupn",
        )
        listener._pending_sockets[cloud.session_id] = cloud

        claimed = await listener.pop_pending_socket_for_transparent_route(token)

        self.assertIs(claimed, cloud)
        self.assertIn(framed.session_id, listener._pending_sockets)
        self.assertNotIn(cloud.session_id, listener._pending_sockets)

    async def test_ambiguous_silent_pair_resolves_when_framed_socket_heartbeats(
        self,
    ) -> None:
        listener = _SharedEybondListener(host="127.0.0.1", port=8899)
        collector_pn = "E50000200000000001"
        token = listener.register_exclusive_collector_route(
            collector_ip="192.168.1.55",
            collector_pn=collector_pn,
            transparent=True,
            expected_session_protocol="at_text",
        )

        framed_reader = asyncio.StreamReader()
        framed_writer = _FakeWriter()
        framed = _PendingCollectorSocket(
            session_id="fresh-framed-ha",
            remote_ip="192.168.1.1",
            reader=framed_reader,
            writer=framed_writer,  # type: ignore[arg-type]
        )
        cloud_writer = _FakeWriter()
        cloud = _PendingCollectorSocket(
            session_id="fresh-silent-cloud",
            remote_ip="192.168.1.1",
            reader=asyncio.StreamReader(),
            writer=cloud_writer,  # type: ignore[arg-type]
        )
        for port, pending in ((41001, framed), (41002, cloud)):
            listener._remember_session(
                session_id=pending.session_id,
                remote_ip=pending.remote_ip,
                remote_port=port,
            )
            listener._pending_sockets[pending.session_id] = pending
            pending.sniff_task = asyncio.create_task(
                listener._sniff_pending_socket(pending)
            )

        await asyncio.sleep(0.35)
        self.assertIsNone(
            await listener.pop_pending_socket_for_transparent_route(token)
        )
        self.assertFalse(framed.sniff_task.done())
        self.assertFalse(cloud.sniff_task.done())
        self.assertEqual(bytes(framed_writer.buffer), b"")
        self.assertEqual(bytes(cloud_writer.buffer), b"")

        framed_reader.feed_data(
            build_collector_request(
                1,
                collector_pn[:16].encode("ascii"),
                devcode=2376,
                collector_addr=1,
                fcode=1,
            )
        )
        deadline = asyncio.get_running_loop().time() + 1.0
        while asyncio.get_running_loop().time() < deadline:
            entry = listener._session_inventory[framed.session_id]
            if entry.protocol_shape == "eybond_framed":
                break
            await asyncio.sleep(0.01)
        self.assertEqual(
            listener._session_inventory[framed.session_id].protocol_shape,
            "eybond_framed",
        )

        claimed = await listener.pop_pending_socket_for_transparent_route(token)

        self.assertIs(claimed, cloud)
        self.assertEqual(bytes(cloud_writer.buffer), b"")
        self.assertNotIn(cloud.session_id, listener._pending_sockets)
        self.assertIn(framed.session_id, listener._pending_sockets)
        framed.sniff_task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await framed.sniff_task

    async def test_proxy_capture_route_selects_same_peer_pending_by_collector_pn(self) -> None:
        listener = _SharedEybondListener(host="127.0.0.1", port=_free_tcp_port())
        listener._remember_session(
            session_id="session-one",
            remote_ip="203.0.113.10",
            remote_port=41001,
        )
        listener._remember_session(
            session_id="session-two",
            remote_ip="203.0.113.10",
            remote_port=41002,
        )

        first_reader = asyncio.StreamReader()
        second_reader = asyncio.StreamReader()

        class _ProbeWriter(_FakeWriter):
            def __init__(self, reader: asyncio.StreamReader, pn: str) -> None:
                super().__init__()
                self._reader = reader
                self._pn = pn

            async def drain(self) -> None:
                # The peer answers the identity probe but keeps the socket
                # open, like a real collector between frames.
                self._reader.feed_data(f"AT+DTUPN:{self._pn}\r\n".encode("ascii"))

        first_pending = _PendingCollectorSocket(
            remote_ip="203.0.113.10",
            remote_port=41001,
            session_id="session-one",
            reader=first_reader,
            writer=_ProbeWriter(first_reader, "PN-ONE"),  # type: ignore[arg-type]
        )
        second_pending = _PendingCollectorSocket(
            remote_ip="203.0.113.10",
            remote_port=41002,
            session_id="session-two",
            reader=second_reader,
            writer=_ProbeWriter(second_reader, "PN-TWO"),  # type: ignore[arg-type]
        )
        listener._pending_sockets["session-one"] = first_pending
        listener._pending_sockets["session-two"] = second_pending

        handled = asyncio.Event()
        handled_writer: _FakeWriter | None = None

        async def _handler(
            pending_reader: asyncio.StreamReader,
            pending_writer: asyncio.StreamWriter,
        ) -> None:
            nonlocal handled_writer
            handled_writer = pending_writer  # type: ignore[assignment]
            route._running = False
            handled.set()

        route = SharedProxyCaptureRoute(
            host="127.0.0.1",
            port=8899,
            collector_ip="203.0.113.10",
            collector_pn="PN-TWO",
            expected_session_protocol="at_text",
            handler=_handler,
        )
        route._listener = listener
        route._running = True

        await route._route_loop()

        self.assertTrue(handled.is_set())
        self.assertIs(handled_writer, second_pending.writer)
        self.assertIn("session-one", listener._pending_sockets)
        self.assertNotIn("session-two", listener._pending_sockets)
        self.assertEqual(first_pending.initial_bytes, b"")
        self.assertEqual(second_pending.initial_bytes, b"")
        self.assertEqual(
            listener.session_inventory_diagnostics()["pending_session_count"],
            1,
        )

        # The mismatched socket is watched again after the paused sniff.
        watch = first_pending.sniff_task
        self.assertIsNotNone(watch)
        self.assertFalse(watch.done())
        first_reader.feed_eof()
        await asyncio.wait_for(watch, timeout=2.0)
        self.assertNotIn("session-one", listener._pending_sockets)

    async def test_exclusive_route_reservation_wins_over_runtime_pn_owner(self) -> None:
        listener = _SharedEybondListener(host="127.0.0.1", port=_free_tcp_port())
        full_pn = "E50000200000000001"
        heartbeat_pn = full_pn[:16]
        runtime_connection = listener.ensure_connection(
            "",
            heartbeat_interval=60.0,
            write_timeout=0.5,
            collector_pn=full_pn,
        )
        listener.register_payload_pn_owner(full_pn)
        token = listener.register_exclusive_collector_route(
            collector_ip="192.168.1.55",
            collector_pn=full_pn,
        )
        listener._remember_session(
            session_id="exclusive-s1",
            remote_ip="192.168.1.55",
            remote_port=41000,
        )
        reader = asyncio.StreamReader()
        reader.feed_data(
            build_collector_request(
                1,
                heartbeat_pn.encode("ascii"),
                devcode=2376,
                collector_addr=1,
                fcode=1,
            )
        )
        pending = _PendingCollectorSocket(
            session_id="exclusive-s1",
            remote_ip="192.168.1.55",
            remote_port=41000,
            reader=reader,
            writer=_FakeWriter(),  # type: ignore[arg-type]
        )
        listener._pending_sockets[pending.session_id] = pending

        with patch.object(runtime_connection, "run", new=AsyncMock()) as runtime_run:
            sniff = asyncio.create_task(listener._sniff_pending_socket(pending))
            pending.sniff_task = sniff
            await asyncio.sleep(0.05)

            states = {
                item["session_id"]: item["state"]
                for item in listener.session_inventory_diagnostics()["sessions"]
            }
            self.assertEqual(states["exclusive-s1"], "waiting_for_exclusive_route")
            runtime_run.assert_not_awaited()

            claimed = await listener.pop_pending_socket_for_route(
                collector_ip="192.168.1.55",
                collector_pn=full_pn,
                session_protocol="eybond_framed",
            )
            self.assertIs(claimed, pending)
            self.assertIn(heartbeat_pn.encode("ascii"), claimed.initial_bytes)
            with self.assertRaises(asyncio.CancelledError):
                await sniff

        await listener.unregister_exclusive_collector_route(token)

    async def test_exclusive_route_never_steals_observed_foreign_pn_by_ip(self) -> None:
        listener = _SharedEybondListener(host="127.0.0.1", port=_free_tcp_port())
        target_pn = "E50000200000000001"
        foreign_pn = "V001020SYN62344022"
        runtime_connection = listener.ensure_connection(
            "",
            heartbeat_interval=60.0,
            write_timeout=0.5,
            collector_pn=foreign_pn,
        )
        listener.register_payload_pn_owner(foreign_pn)
        token = listener.register_exclusive_collector_route(
            collector_ip="192.168.1.1",
            collector_pn=target_pn,
        )
        listener._remember_session(
            session_id="foreign-s1",
            remote_ip="192.168.1.1",
            remote_port=41001,
        )
        reader = asyncio.StreamReader()
        reader.feed_data(
            build_collector_request(
                1,
                b"\x00\x02" + foreign_pn.encode("ascii"),
                devcode=2376,
                collector_addr=1,
                fcode=2,
            )
        )
        pending = _PendingCollectorSocket(
            session_id="foreign-s1",
            remote_ip="192.168.1.1",
            remote_port=41001,
            reader=reader,
            writer=_FakeWriter(),  # type: ignore[arg-type]
        )
        listener._pending_sockets[pending.session_id] = pending

        with patch.object(runtime_connection, "run", new=AsyncMock()) as runtime_run:
            await listener._sniff_pending_socket(pending)

        runtime_run.assert_awaited_once()
        self.assertFalse(listener._pending_socket_still_registered(pending))
        await listener.unregister_exclusive_collector_route(token)

    async def test_at_transport_wait_until_connected_activates_pending_socket(self) -> None:
        port = _free_tcp_port()
        at_transport = SharedCollectorAtTransport(
            host="127.0.0.1",
            port=port,
            request_timeout=1.0,
            collector_ip="127.0.0.1",
        )

        connected = asyncio.Event()
        release = asyncio.Event()

        async def _collector_client() -> None:
            _reader, writer = await asyncio.open_connection("127.0.0.1", port)
            connected.set()
            try:
                await asyncio.wait_for(release.wait(), timeout=1.0)
            finally:
                writer.close()
                await writer.wait_closed()

        async def _quiet_heartbeat(self) -> None:
            return None

        with patch.object(_CollectorConnection, "_heartbeat_loop", new=_quiet_heartbeat):
            await at_transport.start()
            client_task = asyncio.create_task(_collector_client())
            try:
                await asyncio.wait_for(connected.wait(), timeout=1.0)
                self.assertTrue(await at_transport.wait_until_connected(0.2))
                self.assertTrue(at_transport.connected)
            finally:
                release.set()
                await client_task
                await at_transport.stop()

    async def test_at_transport_queries_server_first_session_on_shared_listener(self) -> None:
        port = _free_tcp_port()
        framed = SharedEybondTransport(
            host="127.0.0.1",
            port=port,
            request_timeout=1.0,
            heartbeat_interval=60.0,
            collector_ip="127.0.0.1",
        )
        at_transport = SharedCollectorAtTransport(
            host="127.0.0.1",
            port=port,
            request_timeout=1.0,
            collector_ip="127.0.0.1",
        )

        connected = asyncio.Event()
        release = asyncio.Event()

        async def _collector_client() -> None:
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            connected.set()
            try:
                query = await asyncio.wait_for(reader.readuntil(b"\n"), timeout=1.0)
                self.assertEqual(query, b"AT+WFSS?\r\n")
                writer.write(b"AT+WFSS:-55\r\n")
                await writer.drain()
                await asyncio.wait_for(release.wait(), timeout=1.0)
            finally:
                writer.close()
                await writer.wait_closed()

        async def _quiet_heartbeat(self) -> None:
            return None

        with patch.object(_CollectorConnection, "_heartbeat_loop", new=_quiet_heartbeat):
            await framed.start()
            await at_transport.start()
            client_task = asyncio.create_task(_collector_client())
            try:
                await asyncio.wait_for(connected.wait(), timeout=1.0)
                response = await at_transport.async_query("WFSS")
                self.assertEqual(response.command, "WFSS")
                self.assertEqual(response.value, "-55")
                self.assertTrue(framed.connected)
                self.assertTrue(at_transport.connected)
                self.assertTrue(await at_transport.wait_until_connected(0.2))
            finally:
                release.set()
                await client_task
                await at_transport.stop()
                await framed.stop()

    async def test_at_connection_skips_binary_heartbeat_before_at_response(self) -> None:
        reader = asyncio.StreamReader()
        writer = _FakeWriter()
        connection = _CollectorAtConnection(
            remote_ip_hint="127.0.0.1",
            write_timeout=0.5,
        )
        run_task = asyncio.create_task(
            connection.run(reader, writer),
            name="test_at_connection_mixed_heartbeat",
        )
        try:
            self.assertTrue(await connection.wait_until_connected(0.2))
            query_task = asyncio.create_task(connection.async_query("VDTU", request_timeout=1.0))
            await asyncio.sleep(0)
            self.assertEqual(bytes(writer.buffer), b"AT+VDTU?\r\n")

            reader.feed_data(build_heartbeat_request(7, 60))
            reader.feed_data(
                b"AT+VDTU:esp-collector,0.1.2;features=local_only,no_cloud;"
                b"uart=2400,8,1,NONE\r\n"
            )

            response = await query_task

            self.assertEqual(response.command, "VDTU")
            self.assertTrue(response.value.startswith("esp-collector,0.1.2"))
            self.assertEqual(connection.collector_info.heartbeat_devcode, 0)
        finally:
            await connection.disconnect()
            run_task.cancel()

    async def test_at_connection_can_query_framed_collector_metadata(self) -> None:
        reader = asyncio.StreamReader()
        writer = _FakeWriter()
        connection = _CollectorAtConnection(
            remote_ip_hint="127.0.0.1",
            write_timeout=0.5,
        )
        run_task = asyncio.create_task(
            connection.run(reader, writer),
            name="test_at_connection_framed_metadata",
        )
        try:
            self.assertTrue(await connection.wait_until_connected(0.2))
            query_task = asyncio.create_task(
                connection.async_send_bridge_identity_probe(
                    fcode=2,
                    payload=b"\x06",
                    request_timeout=1.0,
                )
            )
            deadline = monotonic() + 1.0
            while len(writer.buffer) < HEADER_SIZE + 1:
                if monotonic() >= deadline:
                    self.fail(f"timed out waiting for framed request, got {writer.buffer!r}")
                await asyncio.sleep(0)
            request = bytes(writer.buffer)
            self.assertGreaterEqual(len(request), HEADER_SIZE)
            request_header = decode_header(request[:HEADER_SIZE])
            self.assertEqual(request_header.fcode, 2)
            self.assertEqual(request[HEADER_SIZE:], b"\x06")

            response_payload = b"\x00\x06esp-collector/0.1.8/ESP8266"
            reader.feed_data(
                build_collector_request(
                    request_header.tid,
                    response_payload,
                    devcode=0,
                    collector_addr=1,
                    fcode=2,
                )
            )

            header, payload = await query_task

            self.assertEqual(header.tid, request_header.tid)
            self.assertEqual(header.fcode, 2)
            self.assertEqual(payload, response_payload)
            self.assertTrue(connection.mixed_frame_observed)
        finally:
            await connection.disconnect()
            run_task.cancel()

    async def test_at_primary_session_prefers_fc4_after_exact_framed_observation(self) -> None:
        reader = asyncio.StreamReader()
        writer = _FakeWriter()
        connection = _CollectorAtConnection(
            remote_ip_hint="127.0.0.1",
            write_timeout=0.5,
            raw_passthrough_bootstrap="none",
        )
        run_task = asyncio.create_task(
            connection.run(reader, writer),
            name="test_at_connection_fc4_observation_order",
        )
        transport = SharedCollectorAtTransport(
            host="127.0.0.1",
            port=18899,
            request_timeout=0.2,
            collector_ip="127.0.0.1",
        )
        transport.set_negotiated_wire("at_text")
        route = AtMixedLinkRoute(
            devcode=0x0001,
            collector_addr=0x01,
            protocol="modbus_rtu",
        )
        try:
            self.assertTrue(await connection.wait_until_connected(0.2))
            identity_task = asyncio.create_task(
                connection.async_send_bridge_identity_probe(
                    fcode=2,
                    payload=b"\x06",
                    request_timeout=0.2,
                )
            )
            deadline = monotonic() + 1.0
            while len(writer.buffer) < HEADER_SIZE + 1:
                if monotonic() >= deadline:
                    self.fail("timed out waiting for framed identity request")
                await asyncio.sleep(0.005)
            identity_frame = bytes(writer.buffer)
            identity_header = decode_header(identity_frame[:HEADER_SIZE])
            reader.feed_data(
                build_collector_request(
                    identity_header.tid,
                    b"\x00\x06esp-collector/0.1.8/ESP8266",
                    devcode=0,
                    collector_addr=1,
                    fcode=2,
                )
            )
            await identity_task
            identity_len = len(writer.buffer)

            request = build_read_request(1, 2, 6)
            payload_task = asyncio.create_task(
                transport._async_send_payload_on_connection(
                    connection,
                    request,
                    route=route,
                    request_timeout=0.2,
                )
            )
            deadline = monotonic() + 1.0
            while len(writer.buffer) < identity_len + HEADER_SIZE + len(request):
                if monotonic() >= deadline:
                    self.fail("timed out waiting for preferred FC4 request")
                await asyncio.sleep(0.005)
            forwarded = bytes(writer.buffer[identity_len:])
            forward_header = decode_header(forwarded[:HEADER_SIZE])
            self.assertEqual(forward_header.fcode, 4)
            self.assertEqual(forwarded[HEADER_SIZE:], request)

            response = bytearray((1, 3, 12, 1, 4))
            response.extend(b"2407260015")
            response.extend(crc16_modbus(response).to_bytes(2, "little"))
            reader.feed_data(
                build_collector_request(
                    forward_header.tid,
                    bytes(response),
                    devcode=forward_header.devcode,
                    collector_addr=forward_header.devaddr,
                    fcode=4,
                )
            )

            self.assertEqual(await payload_task, bytes(response))
            self.assertEqual(
                connection.collector_info.inverter_forward_mode,
                "eybond_fc4",
            )
        finally:
            await connection.disconnect()
            run_task.cancel()

    async def test_at_primary_session_falls_back_to_fc4_and_pins_exact_socket(self) -> None:
        reader = asyncio.StreamReader()
        writer = _FakeWriter()
        connection = _CollectorAtConnection(
            remote_ip_hint="127.0.0.1",
            write_timeout=0.5,
            raw_passthrough_bootstrap="none",
        )
        run_task = asyncio.create_task(
            connection.run(reader, writer),
            name="test_at_connection_fc4_data_plane",
        )
        transport = SharedCollectorAtTransport(
            host="127.0.0.1",
            port=18899,
            request_timeout=0.05,
            collector_ip="127.0.0.1",
        )
        transport.set_negotiated_wire("at_text")
        logical_route = EybondLinkRoute(devcode=0x0001, collector_addr=0x01)
        try:
            self.assertTrue(await connection.wait_until_connected(0.2))
            with patch.object(transport, "_at_connection", return_value=connection):
                selected = transport.select_payload_route(
                    logical_route,
                    payload_family="modbus_rtu",
                )
            self.assertEqual(
                selected,
                AtMixedLinkRoute(
                    devcode=0x0001,
                    collector_addr=0x01,
                    protocol="modbus_rtu",
                ),
            )

            request = build_read_request(1, 2, 6)
            query_task = asyncio.create_task(
                transport._async_send_payload_on_connection(
                    connection,
                    request,
                    route=selected,
                    request_timeout=0.05,
                )
            )
            deadline = monotonic() + 1.0
            while len(writer.buffer) < len(request) + HEADER_SIZE + len(request):
                if monotonic() >= deadline:
                    self.fail(f"FC4 fallback was not written: {writer.buffer.hex()}")
                await asyncio.sleep(0.005)

            # The legacy raw attempt remains first for compatibility. Its
            # timeout does not itself mint a capability; the exact FC4 reply does.
            self.assertEqual(bytes(writer.buffer[: len(request)]), request)
            framed = bytes(writer.buffer[len(request) :])
            header = decode_header(framed[:HEADER_SIZE])
            self.assertEqual(header.fcode, 4)
            self.assertEqual(framed[HEADER_SIZE:], request)

            response = bytearray((1, 3, 12, 1, 4))
            response.extend(b"2407260015")
            response.extend(crc16_modbus(response).to_bytes(2, "little"))
            reader.feed_data(
                build_collector_request(
                    header.tid,
                    bytes(response),
                    devcode=header.devcode,
                    collector_addr=header.devaddr,
                    fcode=4,
                )
            )

            self.assertEqual(await query_task, bytes(response))
            self.assertEqual(
                connection.collector_info.inverter_forward_mode,
                "eybond_fc4",
            )
            with patch.object(transport, "_at_connection", return_value=connection):
                self.assertIs(
                    transport.select_payload_route(
                        logical_route,
                        payload_family="modbus_rtu",
                    ),
                    logical_route,
                )
        finally:
            await connection.disconnect()
            run_task.cancel()

    async def test_at_connection_supports_raw_pi30_payload_response(self) -> None:
        reader = asyncio.StreamReader()
        writer = _FakeWriter()
        connection = _CollectorAtConnection(
            remote_ip_hint="127.0.0.1",
            write_timeout=0.5,
        )
        run_task = asyncio.create_task(
            connection.run(reader, writer),
            name="test_at_connection_pi30_raw_payload",
        )
        try:
            self.assertTrue(await connection.wait_until_connected(0.2))
            request = build_request("QPI")
            query_task = asyncio.create_task(
                connection.async_send_raw_payload(request, request_timeout=1.0)
            )
            await asyncio.sleep(0)
            self.assertEqual(bytes(writer.buffer), b"AT+UART?\r\n")

            reader.feed_data(b"AT+UART:2400,8,1,NONE\r\n")
            await _wait_for_writer_buffer(
                writer,
                b"AT+UART?\r\nAT+UART=2400,8,1,NONE\r\n",
            )
            self.assertEqual(
                bytes(writer.buffer),
                b"AT+UART?\r\nAT+UART=2400,8,1,NONE\r\n",
            )

            reader.feed_data(b"AT+UART:W000\r\n")
            await _wait_for_writer_buffer(
                writer,
                b"AT+UART?\r\nAT+UART=2400,8,1,NONE\r\n" + request,
            )
            self.assertEqual(
                bytes(writer.buffer),
                b"AT+UART?\r\nAT+UART=2400,8,1,NONE\r\n" + request,
            )

            reader.feed_data(b"(PI30\x8f\x0b\r")
            response = await query_task

            self.assertEqual(response, b"(PI30\x8f\x0b\r")
        finally:
            await connection.disconnect()
            run_task.cancel()

    async def test_at_connection_supports_typed_raw_modbus_response(self) -> None:
        reader = asyncio.StreamReader()
        writer = _FakeWriter()
        connection = _CollectorAtConnection(
            remote_ip_hint="127.0.0.1",
            write_timeout=0.5,
            raw_passthrough_bootstrap="none",
            raw_passthrough_frame_format="transparent",
        )
        run_task = asyncio.create_task(
            connection.run(reader, writer),
            name="test_at_connection_modbus_raw_payload",
        )
        try:
            self.assertTrue(await connection.wait_until_connected(0.2))
            request = build_read_request(1, 171, 1)
            query_task = asyncio.create_task(
                connection.async_send_raw_payload(
                    request,
                    request_timeout=1.0,
                    payload_protocol="modbus_rtu",
                )
            )
            await _wait_for_writer_buffer(writer, request)

            response = bytearray((1, 3, 2, 0x73, 0x00))
            response.extend(crc16_modbus(response).to_bytes(2, "little"))
            reader.feed_data(bytes(response))

            self.assertEqual(await query_task, bytes(response))
            self.assertEqual(
                connection.collector_info.raw_last_parser,
                "raw_modbus_rtu",
            )
            self.assertEqual(
                connection.collector_info.inverter_forward_mode,
                "raw_serial",
            )
        finally:
            await connection.disconnect()
            run_task.cancel()

    async def test_at_connection_supports_eybond_g_ascii_raw_payload_response(self) -> None:
        reader = asyncio.StreamReader()
        writer = _FakeWriter()
        connection = _CollectorAtConnection(
            remote_ip_hint="127.0.0.1",
            write_timeout=0.5,
            raw_passthrough_bootstrap="none",
        )
        run_task = asyncio.create_task(
            connection.run(reader, writer),
            name="test_at_connection_eybond_g_ascii_raw_payload",
        )
        try:
            self.assertTrue(await connection.wait_until_connected(0.2))
            request = build_ascii_line_request("GPV")
            query_task = asyncio.create_task(
                connection.async_send_raw_payload(request, request_timeout=1.0)
            )
            await _wait_for_writer_buffer(writer, b"GPV\r")
            self.assertEqual(bytes(writer.buffer), b"GPV\r")

            reader.feed_data(b"(040.6 026.0\r")
            response = await query_task
            self.assertEqual(response, b"(040.6 026.0\r")
        finally:
            await connection.disconnect()
            run_task.cancel()

    async def test_at_connection_does_not_merge_short_eybond_g_ascii_response(self) -> None:
        reader = asyncio.StreamReader()
        writer = _FakeWriter()
        connection = _CollectorAtConnection(
            remote_ip_hint="127.0.0.1",
            write_timeout=0.5,
            raw_passthrough_bootstrap="none",
        )
        run_task = asyncio.create_task(
            connection.run(reader, writer),
            name="test_at_connection_eybond_g_ascii_short_raw_response",
        )
        try:
            self.assertTrue(await connection.wait_until_connected(0.2))

            gmod_task = asyncio.create_task(
                connection.async_send_raw_payload(
                    build_ascii_line_request("GMOD"),
                    request_timeout=1.0,
                )
            )
            await _wait_for_writer_buffer(writer, b"GMOD\r")
            reader.feed_data(b"(B\r")
            gmod_response = await gmod_task
            self.assertEqual(gmod_response, b"(B\r")

            gdat0_task = asyncio.create_task(
                connection.async_send_raw_payload(
                    build_ascii_line_request("GPDAT0"),
                    request_timeout=1.0,
                )
            )
            await _wait_for_writer_buffer(writer, b"GMOD\rGPDAT0\r")
            reader.feed_data(b"(0 5 4003 0 00 220.4 50.02\r")
            gdat0_response = await gdat0_task
            self.assertEqual(gdat0_response, b"(0 5 4003 0 00 220.4 50.02\r")
        finally:
            await connection.disconnect()
            run_task.cancel()

    async def test_at_connection_supports_valuecloud_plain_line_raw_payload_response(self) -> None:
        reader = asyncio.StreamReader()
        writer = _FakeWriter()
        connection = _CollectorAtConnection(
            remote_ip_hint="127.0.0.1",
            write_timeout=0.5,
            raw_passthrough_bootstrap="none",
            raw_passthrough_frame_format="plain_line",
        )
        run_task = asyncio.create_task(
            connection.run(reader, writer),
            name="test_at_connection_valuecloud_plain_line_raw_payload",
        )
        try:
            self.assertTrue(await connection.wait_until_connected(0.2))

            gmod_task = asyncio.create_task(
                connection.async_send_raw_payload(
                    build_ascii_line_request("GMOD"),
                    request_timeout=1.0,
                )
            )
            await _wait_for_writer_buffer(writer, b"GMOD\r")
            reader.feed_data(b"B\r")
            gmod_response = await gmod_task
            self.assertEqual(gmod_response, b"B\r")

            gpv_task = asyncio.create_task(
                connection.async_send_raw_payload(
                    build_ascii_line_request("GPV"),
                    request_timeout=1.0,
                )
            )
            await _wait_for_writer_buffer(writer, b"GMOD\rGPV\r")
            reader.feed_data(b"176.3 027.6 25.64 06.90 01216\r")
            gpv_response = await gpv_task
            self.assertEqual(gpv_response, b"176.3 027.6 25.64 06.90 01216\r")
        finally:
            await connection.disconnect()
            run_task.cancel()

    async def test_valuecloud_plain_line_mode_keeps_printable_binary_frame_prefixes(self) -> None:
        reader = asyncio.StreamReader()
        writer = _FakeWriter()
        connection = _CollectorAtConnection(
            remote_ip_hint="127.0.0.1",
            write_timeout=0.5,
            raw_passthrough_bootstrap="none",
            raw_passthrough_frame_format="plain_line",
        )
        run_task = asyncio.create_task(
            connection.run(reader, writer),
            name="test_at_connection_valuecloud_printable_binary_prefix",
        )
        try:
            self.assertTrue(await connection.wait_until_connected(0.2))
            query_task = asyncio.create_task(connection.async_query("VDTU", request_timeout=1.0))
            await _wait_for_writer_buffer(writer, b"AT+VDTU?\r\n")

            reader.feed_data(
                build_collector_request(
                    0x4142,
                    b"\x00\x00",
                    devcode=0,
                    collector_addr=1,
                    fcode=1,
                )
            )
            reader.feed_data(b"AT+VDTU:valuecloud-at-test\r\n")

            response = await query_task
            self.assertEqual(response.command, "VDTU")
            self.assertEqual(response.value, "valuecloud-at-test")
            self.assertEqual(connection.collector_info.heartbeat_devcode, 0)
        finally:
            await connection.disconnect()
            run_task.cancel()

    async def test_valuecloud_plain_line_unhandled_bare_token_does_not_desync_reader(self) -> None:
        reader = asyncio.StreamReader()
        writer = _FakeWriter()
        connection = _CollectorAtConnection(
            remote_ip_hint="127.0.0.1",
            write_timeout=0.5,
            raw_passthrough_bootstrap="none",
            raw_passthrough_frame_format="plain_line",
        )
        run_task = asyncio.create_task(
            connection.run(reader, writer),
            name="test_at_connection_valuecloud_unhandled_bare_token",
        )
        try:
            self.assertTrue(await connection.wait_until_connected(0.2))

            reader.feed_data(b"BL050\r")
            deadline = monotonic() + 1.0
            while connection.collector_info.raw_unhandled_line_count != 1:
                if monotonic() >= deadline:
                    break
                await asyncio.sleep(0.01)
            self.assertEqual(connection.collector_info.raw_unhandled_line_count, 1)
            self.assertEqual(connection.collector_info.raw_last_response_ascii, "BL050.")

            gmod_task = asyncio.create_task(
                connection.async_send_raw_payload(
                    build_ascii_line_request("GMOD"),
                    request_timeout=1.0,
                )
            )
            await _wait_for_writer_buffer(writer, b"GMOD\r")
            reader.feed_data(b"(B\r")
            self.assertEqual(await gmod_task, b"(B\r")
            self.assertEqual(connection.collector_info.raw_response_count, 1)
        finally:
            await connection.disconnect()
            run_task.cancel()

    async def test_valuecloud_plain_line_unhandled_numeric_line_does_not_desync_reader(self) -> None:
        reader = asyncio.StreamReader()
        writer = _FakeWriter()
        connection = _CollectorAtConnection(
            remote_ip_hint="127.0.0.1",
            write_timeout=0.5,
            raw_passthrough_bootstrap="none",
            raw_passthrough_frame_format="plain_line",
        )
        run_task = asyncio.create_task(
            connection.run(reader, writer),
            name="test_at_connection_valuecloud_unhandled_numeric_line",
        )
        try:
            self.assertTrue(await connection.wait_until_connected(0.2))

            reader.feed_data(b"229.9 49.98 264.0 185.0\r")
            deadline = monotonic() + 1.0
            while connection.collector_info.raw_unhandled_line_count != 1:
                if monotonic() >= deadline:
                    break
                await asyncio.sleep(0.01)
            self.assertEqual(connection.collector_info.raw_unhandled_line_count, 1)
            self.assertEqual(
                connection.collector_info.raw_last_parser,
                "raw_plain_line_stale_unhandled",
            )
            self.assertEqual(
                connection.collector_info.raw_last_response_ascii,
                "229.9 49.98 264.0 185.0.",
            )

            gmod_task = asyncio.create_task(
                connection.async_send_raw_payload(
                    build_ascii_line_request("GMOD"),
                    request_timeout=1.0,
                )
            )
            await _wait_for_writer_buffer(writer, b"GMOD\r")
            reader.feed_data(b"B\r")
            self.assertEqual(await gmod_task, b"B\r")
            self.assertEqual(connection.collector_info.raw_response_count, 1)
        finally:
            await connection.disconnect()
            run_task.cancel()

    async def test_valuecloud_plain_line_partial_unknown_fragment_does_not_stall_reader(self) -> None:
        reader = asyncio.StreamReader()
        writer = _FakeWriter()
        connection = _CollectorAtConnection(
            remote_ip_hint="127.0.0.1",
            write_timeout=0.5,
            raw_passthrough_bootstrap="none",
            raw_passthrough_frame_format="plain_line",
        )
        run_task = asyncio.create_task(
            connection.run(reader, writer),
            name="test_at_connection_valuecloud_partial_unknown_fragment",
        )
        try:
            self.assertTrue(await connection.wait_until_connected(0.2))

            reader.feed_data(b"#22")
            deadline = monotonic() + 1.0
            while connection.collector_info.raw_last_parser != "mixed_frame_header_timeout":
                if monotonic() >= deadline:
                    break
                await asyncio.sleep(0.01)
            self.assertEqual(
                connection.collector_info.raw_last_parser,
                "mixed_frame_header_timeout",
            )

            gmod_task = asyncio.create_task(
                connection.async_send_raw_payload(
                    build_ascii_line_request("GMOD"),
                    request_timeout=1.0,
                )
            )
            await _wait_for_writer_buffer(writer, b"GMOD\r")
            reader.feed_data(b"(B\r")
            self.assertEqual(await gmod_task, b"(B\r")
            self.assertEqual(connection.collector_info.raw_response_count, 1)
        finally:
            await connection.disconnect()
            run_task.cancel()

    async def test_at_connection_handles_valuecloud_metadata_nak_before_raw_payload(self) -> None:
        reader = asyncio.StreamReader()
        writer = _FakeWriter()
        connection = _CollectorAtConnection(
            remote_ip_hint="127.0.0.1",
            write_timeout=0.5,
            raw_passthrough_bootstrap="none",
            raw_passthrough_frame_format="plain_line",
        )
        run_task = asyncio.create_task(
            connection.run(reader, writer),
            name="test_at_connection_valuecloud_nak_before_raw",
        )
        try:
            self.assertTrue(await connection.wait_until_connected(0.2))

            query_task = asyncio.create_task(connection.async_query("VDTU", request_timeout=0.3))
            await _wait_for_writer_buffer(writer, b"AT+VDTU?\r\n")
            reader.feed_data(b"NAK\r")
            with self.assertRaises(asyncio.TimeoutError):
                await query_task

            gmod_task = asyncio.create_task(
                connection.async_send_raw_payload(
                    build_ascii_line_request("GMOD"),
                    request_timeout=1.0,
                )
            )
            await _wait_for_writer_buffer(writer, b"AT+VDTU?\r\nGMOD\r")
            reader.feed_data(b"(B\r")
            self.assertEqual(await gmod_task, b"(B\r")
        finally:
            await connection.disconnect()
            run_task.cancel()

    async def test_at_connection_with_finished_reader_task_is_not_connected(self) -> None:
        connection = _CollectorAtConnection(
            remote_ip_hint="127.0.0.1",
            write_timeout=0.5,
        )

        async def _done() -> None:
            return None

        task = asyncio.create_task(_done())
        await task
        connection._writer = _FakeWriter()
        connection._reader_task = task

        self.assertFalse(connection.connected)

    async def test_at_connection_disconnect_fails_pending_raw_response(self) -> None:
        connection = _CollectorAtConnection(
            remote_ip_hint="127.0.0.1",
            write_timeout=0.5,
        )
        future: asyncio.Future[bytes] = asyncio.get_running_loop().create_future()
        connection._pending_raw_response = future

        await connection.disconnect()

        self.assertTrue(future.done())
        with self.assertRaisesRegex(ConnectionError, "collector_disconnected"):
            future.result()

    async def test_at_connection_returns_eybond_g_ascii_negative_response_unchanged(self) -> None:
        reader = asyncio.StreamReader()
        writer = _FakeWriter()
        connection = _CollectorAtConnection(
            remote_ip_hint="127.0.0.1",
            write_timeout=0.5,
            raw_passthrough_bootstrap="none",
        )
        run_task = asyncio.create_task(
            connection.run(reader, writer),
            name="test_at_connection_eybond_g_ascii_negative_response",
        )
        try:
            self.assertTrue(await connection.wait_until_connected(0.2))
            query_task = asyncio.create_task(
                connection.async_send_raw_payload(
                    build_ascii_line_request("QPI"),
                    request_timeout=1.0,
                )
            )
            await _wait_for_writer_buffer(writer, b"QPI\r")

            reader.feed_data(b"NAK\r")
            response = await query_task
            self.assertEqual(response, b"NAK\r")
        finally:
            await connection.disconnect()
            run_task.cancel()

    async def test_at_connection_supports_raw_pi18_payload_response(self) -> None:
        reader = asyncio.StreamReader()
        writer = _FakeWriter()
        connection = _CollectorAtConnection(
            remote_ip_hint="127.0.0.1",
            write_timeout=0.5,
        )
        run_task = asyncio.create_task(
            connection.run(reader, writer),
            name="test_at_connection_pi18_raw_payload",
        )
        try:
            self.assertTrue(await connection.wait_until_connected(0.2))
            request = b"^P005PI\xde\xad\r"
            query_task = asyncio.create_task(
                connection.async_send_raw_payload(request, request_timeout=1.0)
            )
            await asyncio.sleep(0)
            self.assertEqual(bytes(writer.buffer), b"AT+UART?\r\n")

            reader.feed_data(b"AT+UART:2400,8,1,NONE\r\n")
            await _wait_for_writer_buffer(
                writer,
                b"AT+UART?\r\nAT+UART=2400,8,1,NONE\r\n",
            )
            self.assertEqual(
                bytes(writer.buffer),
                b"AT+UART?\r\nAT+UART=2400,8,1,NONE\r\n",
            )

            reader.feed_data(b"AT+UART:W000\r\n")
            await _wait_for_writer_buffer(
                writer,
                b"AT+UART?\r\nAT+UART=2400,8,1,NONE\r\n" + request,
            )
            self.assertEqual(
                bytes(writer.buffer),
                b"AT+UART?\r\nAT+UART=2400,8,1,NONE\r\n" + request,
            )

            body = b"^D00518"
            crc = crc16_xmodem(body)
            response_frame = body + bytes(((crc >> 8) & 0xFF, crc & 0xFF)) + b"\r"
            reader.feed_data(response_frame)
            response = await query_task

            self.assertEqual(response, response_frame)
        finally:
            await connection.disconnect()
            run_task.cancel()

    async def test_at_transport_sends_payload_as_raw_ascii(self) -> None:
        port = _free_tcp_port()
        transport = SharedCollectorAtTransport(
            host="127.0.0.1",
            port=port,
            request_timeout=1.0,
            collector_ip="127.0.0.1",
            collector_session_protocol="at_text",
            collector_identity_strategy="at_dtupn",
        )
        connected = asyncio.Event()
        release = asyncio.Event()

        async def _collector_client() -> None:
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            try:
                connected.set()
                data = await asyncio.wait_for(reader.readuntil(b"\n"), timeout=1.0)
                self.assertEqual(data, b"AT+UART?\r\n")
                writer.write(b"AT+UART:2400,8,1,NONE\r\n")
                await writer.drain()
                data = await asyncio.wait_for(reader.readuntil(b"\n"), timeout=1.0)
                self.assertEqual(data, b"AT+UART=2400,8,1,NONE\r\n")
                writer.write(b"AT+UART:W000\r\n")
                await writer.drain()
                data = await asyncio.wait_for(reader.readuntil(b"\r"), timeout=1.0)
                self.assertEqual(data, build_request("QPI"))
                writer.write(b"(PI30\x8f\x0b\r")
                await writer.drain()
                await asyncio.wait_for(release.wait(), timeout=1.0)
            finally:
                writer.close()
                await writer.wait_closed()

        await transport.start()
        client_task = asyncio.create_task(_collector_client())
        try:
            await asyncio.wait_for(connected.wait(), timeout=1.0)
            self.assertTrue(await transport.wait_until_connected(1.0))
            selected_route = transport.select_payload_route(
                EybondLinkRoute(devcode=0x0994, collector_addr=0xFF),
                payload_family="pi30_ascii",
            )
            self.assertEqual(
                selected_route,
                AtMixedLinkRoute(
                    devcode=0x0994,
                    collector_addr=0xFF,
                    protocol="pi30_ascii",
                ),
            )
            response = await transport.async_send_payload(
                build_request("QPI"),
                route=selected_route,
            )
            self.assertEqual(response, b"(PI30\x8f\x0b\r")
        finally:
            release.set()
            await client_task
            await transport.stop()

    async def test_at_connection_records_valuecloud_endpoint_metadata(self) -> None:
        reader = asyncio.StreamReader()
        writer = _FakeWriter()
        connection = _CollectorAtConnection(
            remote_ip_hint="127.0.0.1",
            write_timeout=0.5,
        )
        run_task = asyncio.create_task(
            connection.run(reader, writer),
            name="test_at_connection_valuecloud_endpoint",
        )
        try:
            self.assertTrue(await connection.wait_until_connected(0.2))
            query_task = asyncio.create_task(
                connection.async_query("CLDSRVHOST1", request_timeout=1.0)
            )
            await asyncio.sleep(0)
            self.assertEqual(bytes(writer.buffer), b"AT+CLDSRVHOST1?\r\n")

            reader.feed_data(b"AT+CLDSRVHOST1:iot.eybond.com,18899,TCP\r\n")
            response = await query_task

            self.assertEqual(response.command, "CLDSRVHOST1")
            collector = connection.collector_info
            self.assertEqual(collector.collector_server_endpoint, "iot.eybond.com,18899,TCP")
            self.assertEqual(collector.collector_cloud_family, "valuecloud_at")
            self.assertEqual(collector.collector_cloud_family_source, "endpoint_host")
            self.assertEqual(collector.collector_cloud_family_confidence, "high")
        finally:
            await connection.disconnect()
            run_task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await run_task



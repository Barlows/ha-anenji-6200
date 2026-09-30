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


class TransportLifecycleHardeningTests(unittest.IsolatedAsyncioTestCase):
    async def test_released_pending_socket_cannot_remain_a_registry_live_session(
        self,
    ) -> None:
        """Closing the physical pending socket terminalizes its inventory row."""

        listener = _SharedEybondListener(host="127.0.0.1", port=_free_tcp_port())
        collector_pn = "E50000200000009777"
        listener._remember_session(
            session_id="listener-8899-2",
            remote_ip="192.168.0.102",
            remote_port=58197,
        )
        listener._mark_session_identity(
            "listener-8899-2",
            collector_pn,
            "fc2_parameter_2",
        )
        listener._mark_session_state(
            "listener-8899-2",
            "probing_route_identity_framed_fc2",
        )
        pending = _PendingCollectorSocket(
            remote_ip="192.168.0.102",
            remote_port=58197,
            session_id="listener-8899-2",
            reader=asyncio.StreamReader(),
            writer=_FakeWriter(),  # type: ignore[arg-type]
        )
        listener._pending_sockets[pending.session_id] = pending

        await listener.release_collector_connections(
            "192.168.0.102",
            collector_pn,
            close_payload=True,
            close_pending=True,
        )

        self.assertTrue(pending.writer.closed)
        self.assertEqual(
            listener._session_inventory[pending.session_id].state,
            "closed_disconnected",
        )
        self.assertEqual(listener.discovered_collector_sessions(), ())
        registry = CallbackSessionRegistry(
            sessions_source=listener.discovered_collector_sessions
        )
        registry.claim_identity("entry-sandisolar", collector_pn)
        self.assertIsNone(registry.owned_session_location("entry-sandisolar"))

    def test_unbacked_probe_inventory_is_diagnostic_history_not_live_authority(
        self,
    ) -> None:
        """The exact issue-13 ghost shape cannot suppress a future callback."""

        listener = _SharedEybondListener(host="127.0.0.1", port=_free_tcp_port())
        collector_pn = "E50000200000009777"
        listener._remember_session(
            session_id="listener-8899-2",
            remote_ip="192.168.0.102",
            remote_port=58197,
        )
        listener._mark_session_identity(
            "listener-8899-2",
            collector_pn,
            "fc2_parameter_2",
        )
        listener._mark_session_state(
            "listener-8899-2",
            "probing_route_identity_framed_fc2",
        )

        # The support archive had exactly this contradiction: no pending socket
        # and no activated exact-session connection, but a non-terminal inventory
        # row. Keep it in diagnostics, never in the live registry projection.
        self.assertEqual(
            listener.session_inventory_diagnostics()["recent_session_count"],
            1,
        )
        self.assertEqual(listener.discovered_collector_sessions(), ())
        registry = CallbackSessionRegistry(
            sessions_source=listener.discovered_collector_sessions
        )
        registry.claim_identity("entry-sandisolar", collector_pn)
        self.assertEqual(registry.claimed_session_id("entry-sandisolar"), "")
        self.assertIsNone(registry.owned_session_location("entry-sandisolar"))

    async def test_exact_identity_probe_settles_state_and_rearms_close_watch(
        self,
    ) -> None:
        listener = _SharedEybondListener(host="127.0.0.1", port=_free_tcp_port())
        listener._remember_session(
            session_id="listener-8899-2",
            remote_ip="192.168.0.102",
            remote_port=58197,
        )
        reader = asyncio.StreamReader()

        class _ProbeWriter(_FakeWriter):
            async def drain(self) -> None:
                reader.feed_data(
                    build_collector_request(
                        1,
                        b"\x00\x02E50000200000009777",
                        devcode=2376,
                        collector_addr=1,
                        fcode=2,
                    )
                )

        pending = _PendingCollectorSocket(
            remote_ip="192.168.0.102",
            remote_port=58197,
            session_id="listener-8899-2",
            reader=reader,
            writer=_ProbeWriter(),  # type: ignore[arg-type]
        )
        listener._pending_sockets[pending.session_id] = pending

        identified = await listener.async_identify_pending_session(
            pending.session_id,
            session_protocol="eybond_framed",
        )

        self.assertEqual(identified, "E50000200000009777")
        self.assertEqual(
            listener._session_inventory[pending.session_id].state,
            "parked_identified_strong",
        )
        self.assertIsNotNone(pending.sniff_task)
        self.assertFalse(pending.sniff_task.done())

        reader.feed_eof()
        await asyncio.wait_for(pending.sniff_task, timeout=2.0)
        self.assertTrue(pending.writer.closed)
        self.assertEqual(listener.discovered_collector_sessions(), ())

    async def test_cancelled_exact_identity_probe_rearms_close_watch(self) -> None:
        listener = _SharedEybondListener(host="127.0.0.1", port=_free_tcp_port())
        listener._remember_session(
            session_id="listener-8899-2",
            remote_ip="192.168.0.102",
            remote_port=58197,
        )
        reader = asyncio.StreamReader()
        writer = _FakeWriter()
        pending = _PendingCollectorSocket(
            remote_ip="192.168.0.102",
            remote_port=58197,
            session_id="listener-8899-2",
            reader=reader,
            writer=writer,  # type: ignore[arg-type]
        )
        listener._pending_sockets[pending.session_id] = pending

        probe = asyncio.create_task(
            listener.async_identify_pending_session(
                pending.session_id,
                session_protocol="eybond_framed",
            )
        )
        deadline = monotonic() + 1.0
        while not writer.buffer and monotonic() < deadline:
            await asyncio.sleep(0.01)
        self.assertTrue(writer.buffer)

        probe.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await probe

        self.assertTrue(listener._pending_socket_still_registered(pending))
        self.assertEqual(
            listener._session_inventory[pending.session_id].state,
            "waiting_for_route_identity",
        )
        self.assertIsNotNone(pending.sniff_task)
        self.assertFalse(pending.sniff_task.done())

        reader.feed_eof()
        await asyncio.wait_for(pending.sniff_task, timeout=2.0)
        self.assertTrue(writer.closed)
        self.assertEqual(listener.discovered_collector_sessions(), ())

    async def test_cancel_during_sniff_pause_drains_child_then_propagates(self) -> None:
        listener = _SharedEybondListener(host="127.0.0.1", port=_free_tcp_port())
        listener._remember_session(
            session_id="listener-8899-2",
            remote_ip="192.168.0.102",
            remote_port=58197,
        )
        reader = asyncio.StreamReader()
        pending = _PendingCollectorSocket(
            remote_ip="192.168.0.102",
            remote_port=58197,
            session_id="listener-8899-2",
            reader=reader,
            writer=_FakeWriter(),  # type: ignore[arg-type]
        )
        listener._pending_sockets[pending.session_id] = pending
        sniff_cancelled = asyncio.Event()
        release_sniff = asyncio.Event()

        async def _slow_sniff_cleanup() -> None:
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                sniff_cancelled.set()
                await release_sniff.wait()
                raise

        pending.sniff_task = asyncio.create_task(_slow_sniff_cleanup())
        probe = asyncio.create_task(
            listener.async_identify_pending_session(
                pending.session_id,
                session_protocol="eybond_framed",
            )
        )
        await asyncio.wait_for(sniff_cancelled.wait(), timeout=1.0)

        probe.cancel()
        await asyncio.sleep(0)
        self.assertFalse(probe.done())
        release_sniff.set()
        with self.assertRaises(asyncio.CancelledError):
            await probe
        self.assertTrue(probe.cancelled())

        # The public probe boundary re-arms the physical close watcher even
        # though cancellation arrived while its previous watcher was draining.
        self.assertTrue(listener._pending_socket_still_registered(pending))
        self.assertIsNotNone(pending.sniff_task)
        self.assertFalse(pending.sniff_task.done())
        reader.feed_eof()
        await asyncio.wait_for(pending.sniff_task, timeout=2.0)
        self.assertTrue(pending.writer.closed)

    async def test_callback_storm_is_bounded_and_releases_process_descriptors(self) -> None:
        """Repeated ownerless accepts never accumulate sockets after teardown."""

        fd_dir = Path("/proc/self/fd")
        if not fd_dir.is_dir():
            self.skipTest("process descriptor accounting requires procfs")

        baseline_fd_count = len(tuple(fd_dir.iterdir()))
        port = _free_tcp_port()
        key = ("127.0.0.1", port)
        transport = SharedEybondTransport(
            host="127.0.0.1",
            port=port,
            request_timeout=1.0,
            heartbeat_interval=60.0,
            collector_ip="",
        )
        client_writers: list[asyncio.StreamWriter] = []

        await transport.start()
        listener = transport._listener
        self.assertIsNotNone(listener)
        assert listener is not None
        try:
            # Model repeated callback redials with no initial payload. Every
            # accepted stream is initially independent, but the listener must
            # converge to its explicit parked-socket cap instead of retaining
            # one descriptor per historical callback.
            for _ in range(listener._MAX_PARKED_SOCKETS * 4):
                _reader, writer = await asyncio.open_connection("127.0.0.1", port)
                client_writers.append(writer)

            deadline = monotonic() + 2.0
            while (
                len(listener._pending_sockets) > listener._MAX_PARKED_SOCKETS
                and monotonic() < deadline
            ):
                await asyncio.sleep(0.01)

            self.assertLessEqual(
                len(listener._pending_sockets),
                listener._MAX_PARKED_SOCKETS,
            )
        finally:
            for writer in client_writers:
                writer.close()
            await asyncio.gather(
                *(writer.wait_closed() for writer in client_writers),
                return_exceptions=True,
            )
            await transport.stop()

        await asyncio.sleep(0)
        self.assertNotIn(key, _LISTENERS)
        self.assertFalse(
            [
                task
                for task in _BACKGROUND_TASKS
                if not task.done()
                and task.get_name().startswith(
                    ("collector_pending_sniff_", "collector_parked_watch_")
                )
            ]
        )
        self.assertLessEqual(
            len(tuple(fd_dir.iterdir())),
            baseline_fd_count + 1,
        )

    """Session-epoch, bounded teardown, and pending-socket ownership rules."""

    async def test_replaced_run_finally_does_not_tear_down_successor(self) -> None:
        connection = _CollectorConnection(
            remote_ip_hint="203.0.113.10",
            heartbeat_interval=60.0,
            write_timeout=0.5,
        )
        drops: list[object] = []
        closed_sessions: list[str] = []

        def _session_closed(session_id: str, _connection: object) -> None:
            closed_sessions.append(session_id)

        reader1 = asyncio.StreamReader()
        writer1 = _FakeWriter()
        run1 = asyncio.create_task(
            connection.run(
                reader1,
                writer1,
                session_id="session-old",
                session_closed_callback=_session_closed,
                disconnect_callback=drops.append,
            )  # type: ignore[arg-type]
        )
        self.assertTrue(await connection.wait_until_connected(1.0))

        reader2 = asyncio.StreamReader()
        writer2 = _FakeWriter()
        run2 = asyncio.create_task(
            connection.run(
                reader2,
                writer2,
                session_id="session-new",
                session_closed_callback=_session_closed,
                disconnect_callback=drops.append,
            )  # type: ignore[arg-type]
        )
        with self.assertRaises(asyncio.CancelledError):
            await asyncio.wait_for(run1, timeout=2.0)

        # By the time the replaced session finishes, its writer must already
        # be closed — the reader cancellation that wakes it fires only after
        # the old session was detached and its writer torn down.
        self.assertTrue(writer1.closed)

        # The replaced session's finally must leave the successor alone: no
        # index drop (the field symptom was a live collector "vanishing"),
        # no closed writer, connection still up.
        self.assertTrue(await connection.wait_until_connected(1.0))
        self.assertEqual(drops, [])
        self.assertEqual(closed_sessions, ["session-old"])
        self.assertFalse(writer2.closed)
        self.assertTrue(connection.connected)

        # A normal end still runs the teardown + unindex exactly once.
        reader2.feed_eof()
        await asyncio.wait_for(run2, timeout=2.0)
        self.assertEqual(drops, [connection])
        self.assertEqual(closed_sessions, ["session-old", "session-new"])
        self.assertTrue(writer2.closed)

    async def test_unwrapped_rtu_response_closes_only_corrupted_framed_session(
        self,
    ) -> None:
        """Regression for #39: raw RTU must not consume later EyeBond frames."""

        async def _quiet_heartbeat(self) -> None:
            return None

        connection = _CollectorConnection(
            remote_ip_hint="203.0.113.10",
            heartbeat_interval=60.0,
            write_timeout=0.5,
        )
        connection._tid._value = 0x6AED
        reader1 = asyncio.StreamReader()
        writer1 = _FakeWriter()

        with patch.object(
            _CollectorConnection,
            "_heartbeat_loop",
            new=_quiet_heartbeat,
        ):
            run1 = asyncio.create_task(
                connection.run(reader1, writer1)  # type: ignore[arg-type]
            )
            self.assertTrue(await connection.wait_until_connected(1.0))
            request1 = asyncio.create_task(
                connection.async_send_forward(
                    b"\x01\x03\x00\xAB\x00\x01\xF5\xEA",
                    devcode=0x0200,
                    collector_addr=1,
                    request_timeout=1.0,
                )
            )
            await _wait_for_writer_buffer(
                writer1,
                build_collector_request(
                    0x6AEE,
                    b"\x01\x03\x00\xAB\x00\x01\xF5\xEA",
                    devcode=0x0200,
                    collector_addr=1,
                    fcode=4,
                ),
            )

            # The first seven bytes are the exact CRC-valid raw Modbus response
            # from the issue capture. The old reader borrowed 0x6A from the next
            # valid frame, decoded a 364-byte pseudo-payload, and stalled while
            # consuming every response that followed.
            raw_rtu = bytes.fromhex("01030235016ed4")
            valid_later = build_collector_request(
                0x6AEE,
                b"\x01\x03\x02\x35\x01\x6E\xD4",
                devcode=0x0200,
                collector_addr=1,
                fcode=4,
            )
            reader1.feed_data(raw_rtu + valid_later)

            await asyncio.wait_for(run1, timeout=1.0)
            with self.assertRaisesRegex(ConnectionError, "collector_disconnected"):
                await request1

            first_snapshot = connection.collector_info
            self.assertEqual(
                first_snapshot.last_disconnect_reason,
                "collector_frame_function_invalid",
            )
            self.assertEqual(first_snapshot.pending_request_drop_count, 1)
            self.assertTrue(writer1.closed)

            # A fresh callback session on the same connection facade accepts a
            # normally fragmented frame and resumes request dispatch.
            reader2 = asyncio.StreamReader()
            writer2 = _FakeWriter()
            run2 = asyncio.create_task(
                connection.run(reader2, writer2)  # type: ignore[arg-type]
            )
            self.assertTrue(await connection.wait_until_connected(1.0))
            request2 = asyncio.create_task(
                connection.async_send_forward(
                    b"\x01\x03\x00\xAC\x00\x01\x44\x2A",
                    devcode=0x0200,
                    collector_addr=1,
                    request_timeout=1.0,
                )
            )
            expected_request = build_collector_request(
                0x6AEF,
                b"\x01\x03\x00\xAC\x00\x01\x44\x2A",
                devcode=0x0200,
                collector_addr=1,
                fcode=4,
            )
            await _wait_for_writer_buffer(writer2, expected_request)
            response_payload = b"\x01\x03\x02\x12\x34\xB5\x33"
            response = build_collector_request(
                0x6AEF,
                response_payload,
                devcode=0x0200,
                collector_addr=1,
                fcode=4,
            )
            reader2.feed_data(response[:1])
            await asyncio.sleep(0.01)
            reader2.feed_data(response[1:HEADER_SIZE])
            await asyncio.sleep(0.01)
            reader2.feed_data(response[HEADER_SIZE:])
            self.assertEqual(await request2, response_payload)
            reader2.feed_eof()
            await asyncio.wait_for(run2, timeout=1.0)

    async def test_framed_reader_bounds_partial_header_and_payload(self) -> None:
        async def _quiet_heartbeat(self) -> None:
            return None

        async def _run_failure(
            wire: bytes,
            *,
            expected_reason: str,
            header_timeout: float = 2.0,
            payload_timeout: float = 5.0,
        ) -> None:
            connection = _CollectorConnection(
                remote_ip_hint="203.0.113.10",
                heartbeat_interval=60.0,
                write_timeout=0.5,
            )
            reader = asyncio.StreamReader()
            writer = _FakeWriter()
            with (
                patch.object(
                    _CollectorConnection,
                    "_heartbeat_loop",
                    new=_quiet_heartbeat,
                ),
                patch(
                    "custom_components.eybond_local.collector.transport.connections._FRAMED_HEADER_COMPLETION_TIMEOUT",
                    header_timeout,
                ),
                patch(
                    "custom_components.eybond_local.collector.transport.connections._FRAMED_PAYLOAD_COMPLETION_TIMEOUT",
                    payload_timeout,
                ),
            ):
                run = asyncio.create_task(
                    connection.run(reader, writer)  # type: ignore[arg-type]
                )
                self.assertTrue(await connection.wait_until_connected(1.0))
                reader.feed_data(wire)
                await asyncio.wait_for(run, timeout=1.0)
            self.assertEqual(
                connection.collector_info.last_disconnect_reason,
                expected_reason,
            )
            self.assertTrue(writer.closed)

        await _run_failure(
            b"\x00",
            expected_reason="collector_frame_header_timeout",
            header_timeout=0.05,
        )
        await _run_failure(
            bytes.fromhex("010302"),
            expected_reason="collector_frame_header_timeout",
            header_timeout=0.05,
        )
        await _run_failure(
            bytes.fromhex("0103180000000000"),
            expected_reason="collector_frame_length_invalid",
        )
        await _run_failure(
            bytes.fromhex("01036c0000000200"),
            expected_reason="collector_frame_length_invalid",
        )
        await _run_failure(
            build_collector_request(
                1,
                b"\x00" * 8,
                devcode=0x0200,
                collector_addr=1,
                fcode=4,
            )[: HEADER_SIZE + 2],
            expected_reason="collector_frame_payload_timeout",
            payload_timeout=0.05,
        )
        await _run_failure(
            build_collector_request(
                1,
                b"\x00" * 4097,
                devcode=0x0200,
                collector_addr=1,
                fcode=4,
            )[:HEADER_SIZE],
            expected_reason="collector_frame_payload_too_large",
        )

    async def test_disconnect_reason_survives_a_reconnect(self) -> None:
        # The fault reason is the whole point of the diagnostic, and the most
        # interesting time to read it is after the collector has already
        # reconnected. run() resets last_disconnect_reason on attach, so the
        # retained field must be the one that survives.
        connection = _CollectorConnection(
            remote_ip_hint="203.0.113.10",
            heartbeat_interval=60.0,
            write_timeout=0.5,
        )
        reader = asyncio.StreamReader()
        writer = _FakeWriter()

        async def _quiet_heartbeat(self) -> None:
            return None

        with (
            patch.object(
                _CollectorConnection,
                "_heartbeat_loop",
                new=_quiet_heartbeat,
            ),
            patch(
                "custom_components.eybond_local.collector.transport.connections._FRAMED_HEADER_COMPLETION_TIMEOUT",
                0.05,
            ),
        ):
            run = asyncio.create_task(
                connection.run(reader, writer)  # type: ignore[arg-type]
            )
            self.assertTrue(await connection.wait_until_connected(1.0))
            reader.feed_data(bytes.fromhex("010302"))
            await asyncio.wait_for(run, timeout=1.0)

        self.assertEqual(
            connection.collector_info.last_disconnect_reason,
            "collector_frame_header_timeout",
        )
        self.assertEqual(
            connection.collector_info.retained_disconnect_reason,
            "collector_frame_header_timeout",
        )

        # Reconnect: run() clears the live-session field on attach.
        # collector_info is a copy, so mutate the instance the connection owns.
        connection._collector.last_disconnect_reason = ""

        self.assertEqual(connection.collector_info.last_disconnect_reason, "")
        self.assertEqual(
            connection.collector_info.retained_disconnect_reason,
            "collector_frame_header_timeout",
        )

    async def test_unwrapped_modbus_rtu_reply_gets_an_honest_log_reason(self) -> None:
        # Field-observed bytes: Modbus slave 0x01, function 0x03 (read
        # holding registers), byte count 0x14 — a real, valid RTU reply
        # header, not corruption, arriving outside any EyeBond envelope.
        # last_disconnect_reason (the stored/reported value) is unchanged by
        # this recognition; only the human-readable log line differs.
        connection = _CollectorConnection(
            remote_ip_hint="203.0.113.10",
            heartbeat_interval=60.0,
            write_timeout=0.5,
        )
        reader = asyncio.StreamReader()
        writer = _FakeWriter()

        async def _quiet_heartbeat(self) -> None:
            return None

        with (
            patch.object(_CollectorConnection, "_heartbeat_loop", new=_quiet_heartbeat),
            self.assertLogs(
                "custom_components.eybond_local.collector.transport.connections",
                level="WARNING",
            ) as captured,
        ):
            run = asyncio.create_task(
                connection.run(reader, writer)  # type: ignore[arg-type]
            )
            self.assertTrue(await connection.wait_until_connected(1.0))
            reader.feed_data(bytes.fromhex("0103140000000000"))
            await asyncio.wait_for(run, timeout=1.0)

        self.assertEqual(
            connection.collector_info.last_disconnect_reason,
            "collector_frame_length_invalid",
        )
        joined = "\n".join(captured.output)
        self.assertIn("unwrapped Modbus RTU reply", joined)
        self.assertNotIn("malformed frame header", joined)

    async def test_genuine_garbage_header_keeps_the_original_wording(self) -> None:
        connection = _CollectorConnection(
            remote_ip_hint="203.0.113.10",
            heartbeat_interval=60.0,
            write_timeout=0.5,
        )
        reader = asyncio.StreamReader()
        writer = _FakeWriter()

        async def _quiet_heartbeat(self) -> None:
            return None

        with (
            patch.object(_CollectorConnection, "_heartbeat_loop", new=_quiet_heartbeat),
            self.assertLogs(
                "custom_components.eybond_local.collector.transport.connections",
                level="WARNING",
            ) as captured,
        ):
            run = asyncio.create_task(
                connection.run(reader, writer)  # type: ignore[arg-type]
            )
            self.assertTrue(await connection.wait_until_connected(1.0))
            reader.feed_data(bytes.fromhex("aabbccddeeff0011"))
            await asyncio.wait_for(run, timeout=1.0)

        joined = "\n".join(captured.output)
        self.assertIn("malformed frame header", joined)
        self.assertNotIn("unwrapped Modbus RTU reply", joined)

    async def test_replaced_socket_closes_only_its_session_inventory(self) -> None:
        listener = _SharedEybondListener(host="127.0.0.1", port=_free_tcp_port())
        connection = _CollectorConnection(
            remote_ip_hint="203.0.113.10",
            heartbeat_interval=60.0,
            write_timeout=0.5,
        )
        listener._remember_session(
            session_id="session-old", remote_ip="203.0.113.10", remote_port=41000
        )
        listener._remember_session(
            session_id="session-new", remote_ip="203.0.113.10", remote_port=41001
        )
        listener._mark_session_state("session-old", "routed_framed")
        listener._mark_session_state("session-new", "routed_framed")
        listener._session_payload_connections["session-old"] = connection
        listener._session_payload_connections["session-new"] = connection
        connection._collector.last_disconnect_reason = (
            "collector_frame_function_invalid"
        )

        listener._mark_socket_session_closed("session-old", connection)

        inventory = {
            item["session_id"]: item
            for item in listener.session_inventory_diagnostics()["sessions"]
        }
        self.assertEqual(inventory["session-old"]["state"], "closed_disconnected")
        self.assertEqual(
            inventory["session-old"]["close_reason"],
            "collector_frame_function_invalid",
        )
        self.assertEqual(inventory["session-new"]["state"], "routed_framed")
        self.assertNotIn("session-old", listener._session_payload_connections)
        self.assertIs(
            listener._session_payload_connections["session-new"], connection
        )

    async def test_late_route_result_cannot_resurrect_closed_socket(self) -> None:
        """A stale async route result cannot make a dead session live again."""

        listener = _SharedEybondListener(host="127.0.0.1", port=_free_tcp_port())
        connection = _CollectorConnection(
            remote_ip_hint="203.0.113.10",
            heartbeat_interval=60.0,
            write_timeout=0.5,
        )
        listener._remember_session(
            session_id="session-rebooted",
            remote_ip="203.0.113.10",
            remote_port=41000,
        )
        listener._mark_session_identity(
            "session-rebooted",
            "E50000200000009777",
            "fc2_parameter_2",
        )
        listener._mark_session_state("session-rebooted", "routed_framed")
        listener._session_payload_connections["session-rebooted"] = connection

        # Physical EOF wins.  These are representative late writes from the
        # route and identity coroutines that can still be unwinding while an
        # E500 replacement socket is accepted.
        listener._mark_socket_session_closed("session-rebooted", connection)
        listener._mark_session_state("session-rebooted", "route_identity_mismatch")
        listener._mark_session_state("session-rebooted", "routed_framed")

        inventory = {
            item["session_id"]: item
            for item in listener.session_inventory_diagnostics()["sessions"]
        }
        self.assertEqual(
            inventory["session-rebooted"]["state"], "closed_disconnected"
        )
        self.assertEqual(listener.discovered_collector_sessions(), ())
        self.assertNotIn("session-rebooted", listener._session_payload_connections)

    async def test_disconnect_does_not_wait_for_dead_peer_tcp_timeout(self) -> None:
        class _HangingCloseWriter(_FakeWriter):
            async def wait_closed(self) -> None:
                await asyncio.Event().wait()

        connection = _CollectorConnection(
            remote_ip_hint="203.0.113.10",
            heartbeat_interval=60.0,
            write_timeout=0.5,
        )
        reader = asyncio.StreamReader()
        writer = _HangingCloseWriter()
        run = asyncio.create_task(connection.run(reader, writer))  # type: ignore[arg-type]
        self.assertTrue(await connection.wait_until_connected(1.0))

        with patch(
            "custom_components.eybond_local.collector.transport.common._WRITER_CLOSE_TIMEOUT",
            0.05,
        ):
            reader.feed_eof()
            await asyncio.wait_for(run, timeout=2.0)
        self.assertTrue(writer.closed)

    async def test_physical_disconnect_closes_inventory_before_writer_cleanup(self) -> None:
        """EOF is visible to recovery without inheriting wait_closed latency."""

        class _DelayedCloseWriter(_FakeWriter):
            def __init__(self) -> None:
                super().__init__()
                self.cleanup_started = asyncio.Event()
                self.release_cleanup = asyncio.Event()

            async def wait_closed(self) -> None:
                self.cleanup_started.set()
                await self.release_cleanup.wait()

        connection = _CollectorConnection(
            remote_ip_hint="203.0.113.10",
            heartbeat_interval=60.0,
            write_timeout=0.5,
        )
        reader = asyncio.StreamReader()
        writer = _DelayedCloseWriter()
        session_closed = asyncio.Event()
        closed_sessions: list[str] = []

        def _closed(session_id: str, _connection: object) -> None:
            closed_sessions.append(session_id)
            session_closed.set()

        run = asyncio.create_task(
            connection.run(
                reader,
                writer,
                session_id="session-rebooted",
                session_closed_callback=_closed,
            )  # type: ignore[arg-type]
        )
        self.assertTrue(await connection.wait_until_connected(1.0))

        reader.feed_eof()
        await asyncio.wait_for(writer.cleanup_started.wait(), timeout=1.0)
        await asyncio.wait_for(session_closed.wait(), timeout=0.1)
        self.assertEqual(closed_sessions, ["session-rebooted"])
        self.assertFalse(run.done())

        writer.release_cleanup.set()
        await asyncio.wait_for(run, timeout=1.0)
        self.assertEqual(closed_sessions, ["session-rebooted"])

    async def test_identityless_pending_socket_is_parked_and_watched(self) -> None:
        listener = _SharedEybondListener(host="127.0.0.1", port=_free_tcp_port())
        listener._remember_session(
            session_id="s1", remote_ip="203.0.113.10", remote_port=41000
        )
        reader = asyncio.StreamReader()
        pending = _PendingCollectorSocket(
            remote_ip="203.0.113.10",
            remote_port=41000,
            session_id="s1",
            reader=reader,
            writer=_FakeWriter(),  # type: ignore[arg-type]
        )
        listener._pending_sockets["s1"] = pending
        sniff = asyncio.create_task(listener._sniff_pending_socket(pending))
        pending.sniff_task = sniff

        await asyncio.sleep(0.4)
        self.assertTrue(pending.parked)
        self.assertTrue(listener._pending_socket_still_registered(pending))
        states = {
            session["session_id"]: session["state"]
            for session in listener.session_inventory_diagnostics()["sessions"]
        }
        self.assertEqual(states["s1"], "parked_waiting_for_identity")

        # The watcher notices the peer close and releases the socket — an
        # unwatched dead socket would block same-IP routing as a duplicate.
        reader.feed_eof()
        await asyncio.wait_for(sniff, timeout=2.0)
        self.assertTrue(pending.writer.closed)
        self.assertFalse(listener._pending_socket_still_registered(pending))

    async def test_route_identity_mismatch_rearms_the_pending_watch(self) -> None:
        listener = _SharedEybondListener(host="127.0.0.1", port=_free_tcp_port())
        listener._remember_session(
            session_id="s1", remote_ip="203.0.113.10", remote_port=41000
        )
        listener._mark_session_identity("s1", "V0000000000001", "framed_heartbeat")
        reader = asyncio.StreamReader()
        pending = _PendingCollectorSocket(
            remote_ip="203.0.113.10",
            remote_port=41000,
            session_id="s1",
            reader=reader,
            writer=_FakeWriter(),  # type: ignore[arg-type]
        )
        listener._pending_sockets["s1"] = pending

        claimed = await listener.pop_pending_socket_for_route(
            collector_ip="203.0.113.10",
            collector_pn="Z9999999999999",
        )

        self.assertIsNone(claimed)
        self.assertTrue(listener._pending_socket_still_registered(pending))
        self.assertIsNotNone(pending.sniff_task)
        self.assertFalse(pending.sniff_task.done())

        reader.feed_eof()
        await asyncio.wait_for(pending.sniff_task, timeout=2.0)
        self.assertTrue(pending.writer.closed)
        self.assertFalse(listener._pending_socket_still_registered(pending))

    async def test_weak_route_identity_is_probed_before_strong_mismatch(self) -> None:
        listener = _SharedEybondListener(host="127.0.0.1", port=_free_tcp_port())
        listener.register_session_protocol_owner("eybond_framed")
        listener._remember_session(
            session_id="s-weak", remote_ip="203.0.113.10", remote_port=41000
        )
        listener._mark_session_identity(
            "s-weak", "V001020SYN6234", "framed_heartbeat"
        )
        reader = asyncio.StreamReader()

        class _ProbeWriter(_FakeWriter):
            async def drain(self) -> None:
                reader.feed_data(
                    build_collector_request(
                        1,
                        b"\x00\x02V001020SYN62344022",
                        devcode=2376,
                        collector_addr=1,
                        fcode=2,
                    )
                )

        writer = _ProbeWriter()
        pending = _PendingCollectorSocket(
            remote_ip="203.0.113.10",
            remote_port=41000,
            session_id="s-weak",
            reader=reader,
            writer=writer,  # type: ignore[arg-type]
        )
        listener._pending_sockets["s-weak"] = pending

        claimed = await listener.pop_pending_socket_for_route(
            collector_ip="203.0.113.10",
            collector_pn="V000405SYN94677058",
            session_protocol="eybond_framed",
        )

        self.assertIsNone(claimed)
        session = listener.discovered_collector_sessions()[0]
        self.assertEqual(session["collector_pn"], "V001020SYN62344022")
        self.assertEqual(session["collector_identity_source"], "fc2_parameter_2")
        self.assertEqual(session["state"], "route_identity_mismatch")
        self.assertTrue(listener._pending_socket_still_registered(pending))

        reader.feed_eof()
        await asyncio.wait_for(pending.sniff_task, timeout=2.0)

    async def test_sniff_does_not_route_at_shaped_bytes_framed_for_framed_owner(
        self,
    ) -> None:
        listener = _SharedEybondListener(host="127.0.0.1", port=_free_tcp_port())
        listener.register_payload_pn_owner("E5000020000000")
        listener._remember_session(
            session_id="s1", remote_ip="203.0.113.10", remote_port=41000
        )
        reader = asyncio.StreamReader()
        reader.feed_data(b"AT+DTUPN:E5000020000000\r\n")
        pending = _PendingCollectorSocket(
            remote_ip="203.0.113.10",
            remote_port=41000,
            session_id="s1",
            reader=reader,
            writer=_FakeWriter(),  # type: ignore[arg-type]
        )
        listener._pending_sockets["s1"] = pending
        sniff = asyncio.create_task(listener._sniff_pending_socket(pending))
        pending.sniff_task = sniff

        await asyncio.sleep(0.3)
        self.assertNotIn("203.0.113.10", listener._connections)
        self.assertNotIn("203.0.113.10", listener._at_connections)
        self.assertTrue(listener._pending_socket_still_registered(pending))
        self.assertEqual(
            listener._session_inventory["s1"].state,
            "parked_no_at_owner",
        )

        reader.feed_eof()
        await asyncio.wait_for(sniff, timeout=2.0)

    async def test_sniff_routes_raw_bytes_to_at_for_registered_at_owner(self) -> None:
        listener = _SharedEybondListener(host="127.0.0.1", port=_free_tcp_port())
        listener.register_at_owner("203.0.113.10")
        listener._remember_session(
            session_id="s1", remote_ip="203.0.113.10", remote_port=41000
        )
        reader = asyncio.StreamReader()
        reader.feed_data(b"(230.0 50.0 230.0 50.0\r")
        pending = _PendingCollectorSocket(
            remote_ip="203.0.113.10",
            remote_port=41000,
            session_id="s1",
            reader=reader,
            writer=_FakeWriter(),  # type: ignore[arg-type]
        )
        listener._pending_sockets["s1"] = pending
        sniff = asyncio.create_task(listener._sniff_pending_socket(pending))
        pending.sniff_task = sniff

        await asyncio.sleep(0.3)
        self.assertIn("203.0.113.10", listener._at_connections)
        self.assertNotIn("203.0.113.10", listener._connections)

        reader.feed_eof()
        await asyncio.wait_for(sniff, timeout=2.0)

    async def test_short_non_at_prefix_waits_for_more_bytes_not_raw_tcp(self) -> None:
        listener = _SharedEybondListener(host="127.0.0.1", port=_free_tcp_port())
        listener.register_payload_owner("203.0.113.10")
        listener._remember_session(
            session_id="s1", remote_ip="203.0.113.10", remote_port=41000
        )
        frame = build_collector_request(
            1,
            b"",
            devcode=0x0994,
            collector_addr=1,
            fcode=4,
        )
        reader = asyncio.StreamReader()
        reader.feed_data(frame[:2])
        pending = _PendingCollectorSocket(
            remote_ip="203.0.113.10",
            remote_port=41000,
            session_id="s1",
            reader=reader,
            writer=_FakeWriter(),  # type: ignore[arg-type]
        )
        listener._pending_sockets["s1"] = pending
        sniff = asyncio.create_task(listener._sniff_pending_socket(pending))
        pending.sniff_task = sniff

        await asyncio.sleep(0.3)
        self.assertTrue(listener._pending_socket_still_registered(pending))
        self.assertNotIn("203.0.113.10", listener._at_connections)
        self.assertNotIn("203.0.113.10", listener._connections)
        entry = listener._session_inventory["s1"]
        self.assertEqual(entry.protocol_shape, "unknown")
        self.assertEqual(entry.state, "waiting_for_more_initial_bytes")

        reader.feed_data(frame[2:])
        await asyncio.sleep(0.3)
        self.assertIn("203.0.113.10", listener._connections)
        self.assertNotIn("203.0.113.10", listener._at_connections)
        self.assertEqual(listener._session_inventory["s1"].protocol_shape, "eybond_framed")

        reader.feed_eof()
        await asyncio.wait_for(sniff, timeout=2.0)

    async def test_partial_heartbeat_payload_is_completed_before_owner_lookup(self) -> None:
        listener = _SharedEybondListener(host="127.0.0.1", port=_free_tcp_port())
        listener._remember_session(
            session_id="s-partial-payload",
            remote_ip="203.0.113.10",
            remote_port=41000,
        )
        frame = build_collector_request(
            7,
            b"E5000020000000",
            devcode=0,
            collector_addr=1,
            fcode=1,
        )
        reader = asyncio.StreamReader()
        # A complete header plus only part of the PN payload reproduces the
        # real TCP split that previously parked the socket without identity
        # until the next 60-second heartbeat.
        split = 12
        reader.feed_data(frame[:split])
        pending = _PendingCollectorSocket(
            remote_ip="203.0.113.10",
            remote_port=41000,
            session_id="s-partial-payload",
            reader=reader,
            writer=_FakeWriter(),  # type: ignore[arg-type]
        )
        listener._pending_sockets[pending.session_id] = pending
        sniff = asyncio.create_task(listener._sniff_pending_socket(pending))
        pending.sniff_task = sniff

        await asyncio.sleep(0.05)
        reader.feed_data(frame[split:])
        await asyncio.sleep(0.15)

        session = listener.discovered_collector_sessions()[0]
        self.assertEqual(session["collector_pn"], "E5000020000000")
        self.assertEqual(session["collector_identity_source"], "framed_heartbeat")
        self.assertEqual(session["state"], "parked_no_payload_owner")

        reader.feed_eof()
        await asyncio.wait_for(sniff, timeout=2.0)

    async def test_partial_raw_passthrough_waits_then_routes_to_at_owner(self) -> None:
        listener = _SharedEybondListener(host="127.0.0.1", port=_free_tcp_port())
        listener.register_at_owner("203.0.113.10")
        listener._remember_session(
            session_id="s1", remote_ip="203.0.113.10", remote_port=41000
        )
        reader = asyncio.StreamReader()
        reader.feed_data(b"(")
        pending = _PendingCollectorSocket(
            remote_ip="203.0.113.10",
            remote_port=41000,
            session_id="s1",
            reader=reader,
            writer=_FakeWriter(),  # type: ignore[arg-type]
        )
        listener._pending_sockets["s1"] = pending
        sniff = asyncio.create_task(listener._sniff_pending_socket(pending))
        pending.sniff_task = sniff

        await asyncio.sleep(0.3)
        self.assertTrue(listener._pending_socket_still_registered(pending))
        self.assertNotIn("203.0.113.10", listener._at_connections)
        self.assertEqual(
            listener._session_inventory["s1"].state,
            "waiting_for_more_initial_bytes",
        )

        reader.feed_data(b"230.0 50.0 230.0 50.0\r")
        await asyncio.sleep(0.3)
        self.assertIn("203.0.113.10", listener._at_connections)
        self.assertNotIn("203.0.113.10", listener._connections)
        self.assertEqual(listener._session_inventory["s1"].protocol_shape, "raw_tcp")

        reader.feed_eof()
        await asyncio.wait_for(sniff, timeout=2.0)

    async def test_sniff_shape_decides_when_both_owner_kinds_registered(self) -> None:
        listener = _SharedEybondListener(host="127.0.0.1", port=_free_tcp_port())
        listener.register_payload_pn_owner("E5000020000000")
        listener.register_at_pn_owner("E5000020000000")
        listener._remember_session(
            session_id="s1", remote_ip="203.0.113.10", remote_port=41000
        )
        reader = asyncio.StreamReader()
        reader.feed_data(b"AT+DTUPN:E5000020000000\r\n")
        pending = _PendingCollectorSocket(
            remote_ip="203.0.113.10",
            remote_port=41000,
            session_id="s1",
            reader=reader,
            writer=_FakeWriter(),  # type: ignore[arg-type]
        )
        listener._pending_sockets["s1"] = pending
        sniff = asyncio.create_task(listener._sniff_pending_socket(pending))
        pending.sniff_task = sniff

        await asyncio.sleep(0.3)
        self.assertIn("203.0.113.10", listener._at_connections)

        reader.feed_eof()
        await asyncio.wait_for(sniff, timeout=2.0)



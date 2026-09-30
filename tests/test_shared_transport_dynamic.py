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


class DynamicConfirmedProtocolOwnerTests(unittest.IsolatedAsyncioTestCase):
    """set_confirmed_session_protocol dynamically (un)registers the listener owner.

    This is the durable-probe-permission channel: the runtime hands the CONFIRMED
    wire down after a live observation so the listener may identity-probe a later
    SILENT same-PN reconnect -- WITHOUT an HA restart and WITHOUT rebuilding the
    TCP listener. It is distinct from the live-wire activation (set_negotiated_wire)
    and must NEVER carry the inferred/expected cloud-family protocol.
    """

    def _owner_counts(self, transport: SharedEybondTransport) -> dict[str, int]:
        listener = transport._listener
        assert listener is not None
        return dict(listener._session_protocol_owner_counts)

    async def test_not_started_only_stores_then_applies_on_start(self) -> None:
        port = _free_tcp_port()
        transport = SharedEybondTransport(
            host="127.0.0.1",
            port=port,
            request_timeout=1.0,
            heartbeat_interval=60.0,
            collector_ip="",
        )
        # Before start there is no listener: the value is only stored, nothing is
        # registered, and nothing raises.
        transport.set_confirmed_session_protocol("eybond_framed")
        self.assertIsNone(transport._listener)
        self.assertEqual(transport._collector_session_protocol, "eybond_framed")

        await transport.start()
        try:
            # start() applies the stored confirmed protocol as the listener owner.
            self.assertEqual(
                self._owner_counts(transport), {"eybond_framed": 1}
            )
            self.assertEqual(
                transport._listener._single_registered_session_protocol(),
                "eybond_framed",
            )
        finally:
            await transport.stop()

    async def test_live_protocol_change_replaces_owner_without_rebuild(self) -> None:
        port = _free_tcp_port()
        transport = SharedEybondTransport(
            host="127.0.0.1",
            port=port,
            request_timeout=1.0,
            heartbeat_interval=60.0,
            collector_ip="",
        )
        await transport.start()
        try:
            listener_before = transport._listener
            transport.set_confirmed_session_protocol("eybond_framed")
            self.assertEqual(self._owner_counts(transport), {"eybond_framed": 1})

            # A genuine framed->at_text change: old owner gone, new owner in, and
            # the SAME listener object -- no rebuild.
            transport.set_confirmed_session_protocol("at_text")
            self.assertEqual(self._owner_counts(transport), {"at_text": 1})
            self.assertIs(transport._listener, listener_before)

            # Re-setting the same value is a pure no-op (no churn in the counts).
            transport.set_confirmed_session_protocol("at_text")
            self.assertEqual(self._owner_counts(transport), {"at_text": 1})
            self.assertIs(transport._listener, listener_before)
        finally:
            await transport.stop()

    async def test_clear_removes_owner(self) -> None:
        port = _free_tcp_port()
        transport = SharedEybondTransport(
            host="127.0.0.1",
            port=port,
            request_timeout=1.0,
            heartbeat_interval=60.0,
            collector_ip="",
        )
        await transport.start()
        try:
            transport.set_confirmed_session_protocol("at_text")
            self.assertEqual(self._owner_counts(transport), {"at_text": 1})

            # A dropped binding (durable-PN change) clears the owner entirely.
            transport.set_confirmed_session_protocol("")
            self.assertEqual(self._owner_counts(transport), {})
            self.assertEqual(
                transport._listener._single_registered_session_protocol(), ""
            )
        finally:
            await transport.stop()

    async def test_inferred_protocol_value_never_becomes_owner(self) -> None:
        port = _free_tcp_port()
        transport = SharedEybondTransport(
            host="127.0.0.1",
            port=port,
            request_timeout=1.0,
            heartbeat_interval=60.0,
            collector_ip="",
        )
        await transport.start()
        try:
            # Anything that is not a confirmed wire (an expected/cloud-family
            # label, junk, whitespace) can never register an owner.
            for value in ("smartess_at", "unknown", "at", "framed", "  ", "PI30"):
                transport.set_confirmed_session_protocol(value)
                self.assertEqual(
                    self._owner_counts(transport), {}, msg=f"value={value!r}"
                )
                self.assertEqual(transport._collector_session_protocol, "")
        finally:
            await transport.stop()

    async def test_stop_unregisters_exactly_once_no_leak(self) -> None:
        # Two transports sharing ONE listener. Each owns a distinct confirmed
        # protocol; stopping one must not steal or leak the other's owner, and a
        # second stop must not double-unregister.
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
        try:
            first.set_confirmed_session_protocol("eybond_framed")
            second.set_confirmed_session_protocol("at_text")
            self.assertIs(first._listener, second._listener)
            self.assertEqual(
                dict(first._listener._session_protocol_owner_counts),
                {"eybond_framed": 1, "at_text": 1},
            )

            listener = second._listener
            await first.stop()
            # first's owner removed; second's owner untouched (no steal).
            self.assertEqual(
                dict(listener._session_protocol_owner_counts), {"at_text": 1}
            )

            # Idempotent stop: no double-unregister of an already-released owner.
            await first.stop()
            self.assertEqual(
                dict(listener._session_protocol_owner_counts), {"at_text": 1}
            )
        finally:
            await second.stop()
            self.assertEqual(dict(listener._session_protocol_owner_counts), {})

    async def test_two_entries_same_confirmed_protocol_do_not_steal_ownership(self) -> None:
        # Two entries confirming the SAME wire on one listener are ref-counted:
        # one stopping leaves the owner registered for the other (mixed/ambiguous
        # is avoided, but a shared single protocol survives a partial teardown).
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
        try:
            first.set_confirmed_session_protocol("at_text")
            second.set_confirmed_session_protocol("at_text")
            listener = first._listener
            self.assertEqual(
                dict(listener._session_protocol_owner_counts), {"at_text": 1 + 1}
            )
            self.assertEqual(listener._single_registered_session_protocol(), "at_text")

            await first.stop()
            # Still one owner left for the surviving entry: probe permission holds.
            self.assertEqual(
                dict(listener._session_protocol_owner_counts), {"at_text": 1}
            )
            self.assertEqual(listener._single_registered_session_protocol(), "at_text")
        finally:
            await second.stop()

    async def test_at_transport_dynamic_owner_registration(self) -> None:
        # The AT transport exposes the same durable-probe-permission surface.
        port = _free_tcp_port()
        transport = SharedCollectorAtTransport(
            host="127.0.0.1",
            port=port,
            request_timeout=1.0,
            collector_ip="",
        )
        await transport.start()
        try:
            transport.set_confirmed_session_protocol("at_text")
            listener = transport._listener
            assert listener is not None
            self.assertEqual(
                dict(listener._session_protocol_owner_counts), {"at_text": 1}
            )
            transport.set_confirmed_session_protocol("")
            self.assertEqual(dict(listener._session_protocol_owner_counts), {})
        finally:
            await transport.stop()

    async def test_confirmed_framed_enables_silent_reconnect_probe_no_rebuild(self) -> None:
        # End-to-end (framed): a confirmed framed wire pushed down via
        # set_confirmed_session_protocol lets the SAME listener actively identity-
        # probe a later SILENT same-PN reconnect -- no rebuild, no HA restart.
        pn = b"E5000020000000"
        transport = SharedEybondTransport(
            host="127.0.0.1",
            port=_free_tcp_port(),
            request_timeout=1.0,
            heartbeat_interval=60.0,
            collector_ip="",
            collector_pn=pn.decode("ascii"),
        )
        await transport.start()
        try:
            listener = transport._listener
            assert listener is not None
            # No confirmed evidence yet: no session-protocol owner.
            self.assertEqual(listener._single_registered_session_protocol(), "")

            # The runtime adopts the live framed wire and hands it down.
            transport.set_confirmed_session_protocol("eybond_framed")
            self.assertEqual(
                listener._single_registered_session_protocol(), "eybond_framed"
            )
            self.assertIs(transport._listener, listener)  # no rebuild

            # A later SILENT same-PN socket (no identity bytes until probed).
            listener._remember_session(
                session_id="reconnect-1",
                remote_ip="203.0.113.10",
                remote_port=41000,
            )
            reader = asyncio.StreamReader()

            class _ProbeWriter(_FakeWriter):
                async def drain(self) -> None:
                    reader.feed_data(
                        build_collector_request(
                            1,
                            b"\x00\x02" + pn,
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
                session_id="reconnect-1",
                reader=reader,
                writer=writer,  # type: ignore[arg-type]
            )
            listener._pending_sockets[pending.remote_ip] = pending

            await listener._sniff_pending_socket(pending)

            # The confirmed owner drove an active framed identity probe (fc=2).
            header = decode_header(bytes(writer.buffer)[:HEADER_SIZE])
            self.assertEqual(header.fcode, 2)
            sessions = listener.session_inventory_diagnostics()["sessions"]
            self.assertEqual(sessions[0]["collector_identity_source"], "fc2_parameter_2")
            self.assertIs(transport._listener, listener)  # still no rebuild
        finally:
            await transport.stop()

    async def test_confirmed_at_enables_silent_reconnect_probe_no_rebuild(self) -> None:
        # End-to-end (AT): the identical chain for an at_text collector.
        pn = "E5000020000000"
        transport = SharedCollectorAtTransport(
            host="127.0.0.1",
            port=_free_tcp_port(),
            request_timeout=1.0,
            collector_ip="",
            collector_pn=pn,
        )
        await transport.start()
        try:
            listener = transport._listener
            assert listener is not None
            self.assertEqual(listener._single_registered_session_protocol(), "")

            transport.set_confirmed_session_protocol("at_text")
            self.assertEqual(
                listener._single_registered_session_protocol(), "at_text"
            )
            self.assertIs(transport._listener, listener)

            listener._remember_session(
                session_id="reconnect-at-1",
                remote_ip="203.0.113.11",
                remote_port=41010,
            )
            reader = asyncio.StreamReader()

            class _ProbeWriter(_FakeWriter):
                async def drain(self) -> None:
                    reader.feed_data(f"AT+DTUPN:{pn}\r\n".encode("ascii"))
                    reader.feed_eof()

            writer = _ProbeWriter()
            pending = _PendingCollectorSocket(
                remote_ip="203.0.113.11",
                remote_port=41010,
                session_id="reconnect-at-1",
                reader=reader,
                writer=writer,  # type: ignore[arg-type]
            )
            listener._pending_sockets[pending.remote_ip] = pending

            await listener._sniff_pending_socket(pending)

            # The confirmed owner drove an active AT identity probe.
            self.assertEqual(bytes(writer.buffer), b"AT+DTUPN?\r\n")
            sessions = listener.session_inventory_diagnostics()["sessions"]
            self.assertEqual(sessions[0]["collector_identity_source"], "at_dtupn")
            self.assertIs(transport._listener, listener)
        finally:
            await transport.stop()



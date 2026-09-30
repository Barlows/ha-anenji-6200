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


class Phase2TransportOwnershipCloseTests(unittest.IsolatedAsyncioTestCase):
    """Phase 2 completion: registry-mediated claim + wire authority + PN stability."""

    _PN_A = "V00AAA1111111111"
    _PN_B = "V00BBB2222222222"
    _SHORT_A = "V00AAA11111"  # a >=10-char prefix of _PN_A

    def _pending(self, listener, *, session_id, remote_ip, port):
        reader = asyncio.StreamReader()
        pending = _PendingCollectorSocket(
            remote_ip=remote_ip,
            remote_port=port,
            session_id=session_id,
            reader=reader,
            writer=_FakeWriter(),  # type: ignore[arg-type]
        )
        listener._pending_sockets[session_id] = pending
        return pending, reader

    async def test_pop_by_session_id_claims_exactly_that_socket(self) -> None:
        # Registry-mediated claim: the runtime passes the registry-chosen
        # session id and the listener claims exactly that socket.
        listener = _SharedEybondListener(host="127.0.0.1", port=_free_tcp_port())
        listener._remember_session(session_id="s1", remote_ip="203.0.113.10", remote_port=41000)
        pending, _reader = self._pending(listener, session_id="s1", remote_ip="203.0.113.10", port=41000)

        self.assertIsNone(
            await listener.pop_pending_socket_for_route(session_id="does-not-exist")
        )
        self.assertTrue(listener._pending_socket_still_registered(pending))

        claimed = await listener.pop_pending_socket_for_route(session_id="s1")
        self.assertIs(claimed, pending)
        self.assertFalse(listener._pending_socket_still_registered(pending))

    async def test_pn_present_never_touches_other_collector_on_shared_ip(self) -> None:
        # Two collectors behind one NAT/public IP. Claiming by PN-A must not
        # probe, mark, or claim the PN-B socket -- peer IP is not ownership.
        listener = _SharedEybondListener(host="127.0.0.1", port=_free_tcp_port())
        for sid, pn in (("sa", self._PN_A), ("sb", self._PN_B)):
            listener._remember_session(session_id=sid, remote_ip="203.0.113.10", remote_port=41000)
            listener._mark_session_identity(sid, pn, "at_dtupn")
        pending_a, _ra = self._pending(listener, session_id="sa", remote_ip="203.0.113.10", port=41000)
        pending_b, _rb = self._pending(listener, session_id="sb", remote_ip="203.0.113.10", port=41000)

        claimed = await listener.pop_pending_socket_for_route(
            collector_ip="203.0.113.10",
            collector_pn=self._PN_A,
        )
        self.assertIs(claimed, pending_a)
        # PN-B's socket is untouched: still registered, not marked mismatch.
        self.assertTrue(listener._pending_socket_still_registered(pending_b))
        entry_b = listener._session_inventory.get("sb")
        self.assertNotEqual(getattr(entry_b, "state", ""), "route_identity_mismatch")

    async def test_at_transport_wire_prefers_negotiated_over_persisted(self) -> None:
        transport = SharedCollectorAtTransport(
            host="127.0.0.1",
            port=_free_tcp_port(),
            request_timeout=1.0,
            collector_ip="",
            collector_pn=self._PN_A,
            collector_session_protocol="at_text",  # persisted (stale)
        )
        # Persisted says at_text, but the live negotiated wire is framed.
        transport.set_negotiated_wire("framed")
        self.assertFalse(transport._uses_at_text_session())
        transport.set_negotiated_wire("at_text")
        self.assertTrue(transport._uses_at_text_session())
        # Cleared -> falls back to the persisted hint.
        transport.set_negotiated_wire("")
        self.assertTrue(transport._uses_at_text_session())

    def test_listener_key_is_stable_public_identity(self) -> None:
        transport = SharedCollectorAtTransport(
            host="127.0.0.1",
            port=18899,
            request_timeout=1.0,
            collector_ip="",
            collector_pn=self._PN_A,
            collector_session_protocol="at_text",
        )
        # Public, stable, and hashable -- runtime dedups listeners with this
        # instead of id(transport._listener).
        self.assertNotIn("object at 0x", transport.listener_key)



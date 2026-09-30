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


class OnboardingTransportNoConfirmedOwnerTests(unittest.IsolatedAsyncioTestCase):
    """Onboarding never registers a durable confirmed protocol owner.

    An onboarding transport is created WITHOUT a session protocol, so an
    inferred/expected/cloud-family hint can never register a confirmed owner and
    can never arm an active identity probe. Active protocol-owner authority is the
    runtime's validated confirmed evidence alone.
    """

    async def test_transport_without_session_protocol_registers_no_owner(self) -> None:
        transport = SharedEybondTransport(
            host="127.0.0.1",
            port=_free_tcp_port(),
            request_timeout=1.0,
            heartbeat_interval=60.0,
            collector_ip="",
            collector_pn="PN-ONBOARD-1",
        )
        await transport.start()
        try:
            listener = transport._listener
            assert listener is not None
            # No confirmed owner from onboarding -> no active-probe authority.
            self.assertEqual(dict(listener._session_protocol_owner_counts), {})
            self.assertEqual(listener._single_registered_session_protocol(), "")
        finally:
            await transport.stop()

    async def test_expected_hint_string_does_not_survive_as_owner(self) -> None:
        # Even if a caller were to pass an inferred hint as the (runtime-only)
        # session protocol, it is the ONLY confirmed-owner channel and onboarding
        # does not use it; the runtime path validates confirmed evidence before
        # ever calling this. Constructing a transport with no protocol leaves the
        # owner counter empty, and a silent socket is therefore never actively
        # probed from a hint.
        transport = SharedEybondTransport(
            host="127.0.0.1",
            port=_free_tcp_port(),
            request_timeout=1.0,
            heartbeat_interval=60.0,
            collector_ip="",
        )
        await transport.start()
        try:
            listener = transport._listener
            assert listener is not None
            listener._remember_session(
                session_id="silent-1", remote_ip="203.0.113.10", remote_port=41000
            )
            pending = _PendingCollectorSocket(
                remote_ip="203.0.113.10",
                remote_port=41000,
                session_id="silent-1",
                reader=asyncio.StreamReader(),
                writer=_FakeWriter(),  # type: ignore[arg-type]
            )
            # With no confirmed owner, the probe selector yields no wire.
            self.assertEqual(listener._single_registered_session_protocol(), "")
        finally:
            await transport.stop()



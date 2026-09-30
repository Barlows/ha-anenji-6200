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


class SessionCapabilityInventoryTests(unittest.TestCase):
    def test_later_at_identity_is_supplemental_and_never_rewrites_framed_primary(self) -> None:
        listener = _SharedEybondListener(host="127.0.0.1", port=8899)
        session_id = "hybrid-e500"
        pn = "E50000200000000001"
        listener._remember_session(
            session_id=session_id,
            remote_ip="192.0.2.55",
            remote_port=41000,
        )
        listener._pending_sockets[session_id] = _PendingCollectorSocket(
            session_id=session_id,
            remote_ip="192.0.2.55",
            remote_port=41000,
            reader=object(),  # type: ignore[arg-type]
            writer=_FakeWriter(),  # type: ignore[arg-type]
        )
        listener._mark_session_first_bytes(
            session_id,
            build_collector_request(
                1,
                pn[:16].encode("ascii"),
                devcode=2376,
                collector_addr=1,
                fcode=1,
            ),
        )
        listener._mark_session_identity(session_id, pn, "framed_heartbeat")
        first_prefix = listener._session_inventory[session_id].first_bytes_prefix_hex
        listener._mark_session_first_bytes(
            session_id,
            f"AT+DTUPN:{pn}\r\n".encode("ascii"),
        )
        listener._mark_session_identity(session_id, pn, "at_dtupn")

        entry = listener._session_inventory[session_id]
        self.assertEqual(entry.protocol_shape, "eybond_framed")
        self.assertEqual(entry.first_bytes_prefix_hex, first_prefix)
        self.assertEqual(
            entry.observed_protocol_shapes,
            {"eybond_framed", "at_text"},
        )
        self.assertEqual(
            entry.collector_identity_sources,
            {"framed_heartbeat", "at_dtupn"},
        )
        observed = listener.discovered_collector_sessions()[0]
        self.assertEqual(observed["protocol_shape"], "eybond_framed")
        self.assertEqual(
            set(observed["collector_identity_sources"]),
            {"framed_heartbeat", "at_dtupn"},
        )


if __name__ == "__main__":
    unittest.main()

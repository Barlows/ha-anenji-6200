from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
import asyncio
import sys
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


from custom_components.eybond_local.connection.models import EybondConnectionSpec
from custom_components.eybond_local.connection.collector_endpoint_operation import (
    COLLECTOR_ENDPOINT_OPERATION_AUTHORITY,
    OPERATION_COLLECTOR_SYSTEM_ACTION,
    OPERATION_RUNTIME_LINK_BAUD_SWEEP,
)
from custom_components.eybond_local.collector.at import CollectorAtResponse
from custom_components.eybond_local.collector.management import (
    CollectorManagementUnsupportedError,
)
from custom_components.eybond_local.models import (
    CollectorInfo,
    DetectedInverter,
    DriverMatch,
    ProbeTarget,
    RuntimeSnapshot,
)
from custom_components.eybond_local.runtime.driver_detection import (
    DetectedDriverContext,
    DriverCandidateScan,
    DriverSweepNoMatch,
)
from custom_components.eybond_local.drivers.modbus_write_error import ModbusWriteErrorMixin
from custom_components.eybond_local.drivers.local_register_evidence import (
    LocalRegisterBlockObservation,
    LocalRegisterReadPlan,
    LocalRegisterSnapshot,
)
from custom_components.eybond_local.payload.modbus import ModbusError
from custom_components.eybond_local.runtime.hub import EybondHub
from custom_components.eybond_local.runtime.hub.common import _write_readback_matches
from custom_components.eybond_local.metadata.profile_loader import load_driver_profile
from custom_components.eybond_local.const import DRIVER_DETECTION_FULL_SCAN


class HubAtTextAsciiProbeTests(unittest.TestCase):
    @staticmethod
    def _build_hub(session_protocol: str) -> EybondHub:
        return EybondHub(
            connection=EybondConnectionSpec(
                server_ip="192.168.1.98",
                collector_ip="192.168.2.209",
                tcp_port=8899,
                udp_port=58899,
                discovery_target="192.168.1.255",
                discovery_interval=30,
                heartbeat_interval=60,
                request_timeout=5.0,
                collector_configured_session_protocol=session_protocol,
            ),
        )

    def test_at_text_ascii_probe_records_raw_attempts(self) -> None:
        from custom_components.eybond_local.link_models import RawSerialLinkRoute
        from custom_components.eybond_local.payload.pi30 import crc16_xmodem

        class _AtTransport:
            def select_payload_route(self, route, *, payload_family=""):
                return RawSerialLinkRoute(protocol=payload_family)

            async def async_send_payload(self, payload, *, route, request_timeout=None):
                assert isinstance(route, RawSerialLinkRoute)
                if payload.startswith(b"QPIRI") or payload.startswith(b"QPIGS"):
                    raise asyncio.TimeoutError
                if payload.startswith(b"QPI"):
                    body = b"(PI30"
                    crc = crc16_xmodem(body)
                    return body + bytes(((crc >> 8) & 0xFF, crc & 0xFF)) + b"\r"
                raise asyncio.TimeoutError

        async def _run() -> None:
            hub = self._build_hub("at_text")
            link = _FakeLinkManager()
            link.transport = _AtTransport()
            hub._link_manager = link

            probe = await hub._async_capture_at_text_ascii_probe()

            assert probe is not None
            self.assertEqual(probe["session_protocol"], "at_text")
            attempts = {item["command"]: item for item in probe["attempts"]}
            self.assertIn("QPI", attempts)
            self.assertIn("QPIRI", attempts)
            self.assertIn("GPV", attempts)
            self.assertEqual(attempts["QPI"]["payload_family"], "pi30_ascii")
            self.assertTrue(attempts["QPI"]["response_ascii"].startswith("(PI30"))
            self.assertEqual(attempts["QPIRI"]["error"], "request_timeout")
            self.assertTrue(attempts["QPI"]["request_hex"])

        asyncio.run(_run())

    def test_at_text_ascii_probe_skipped_for_framed_sessions(self) -> None:
        async def _run() -> None:
            hub = self._build_hub("eybond_framed")
            hub._link_manager = _FakeLinkManager()

            probe = await hub._async_capture_at_text_ascii_probe()

            self.assertIsNone(probe)

        asyncio.run(_run())


class _SuccessDriver:
    def __init__(self) -> None:
        self.calls = 0

    async def async_read_values(
        self,
        transport,
        inverter,
        *,
        runtime_state=None,
        poll_interval=None,
        now_monotonic=None,
    ):
        self.calls += 1
        return {"output_power": 100, "battery_average_power": -50}



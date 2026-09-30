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


class WriteReadbackConfirmationTests(unittest.TestCase):
    def setUp(self) -> None:
        profile = load_driver_profile(
            "modbus_smg/models/anenji_anj_11kw_48v_wifi_p.json"
        )
        self.time_capability = profile.get_capability("inverter_time_write")
        self.scalar_capability = profile.get_capability("max_ac_charge_current")

    def test_running_clock_confirms_within_measured_operation_time(self) -> None:
        self.assertTrue(
            _write_readback_matches(
                self.time_capability,
                requested_value="19:04:04",
                written_value="19:04:04",
                readback_value="19:04:08",
                confirmation_elapsed_seconds=3.0,
            )
        )

    def test_running_clock_rejects_values_outside_measured_operation_time(self) -> None:
        self.assertFalse(
            _write_readback_matches(
                self.time_capability,
                requested_value="19:04:04",
                written_value="19:04:04",
                readback_value="19:04:09",
                confirmation_elapsed_seconds=3.0,
            )
        )
        self.assertFalse(
            _write_readback_matches(
                self.time_capability,
                requested_value="19:04:04",
                written_value="19:04:04",
                readback_value="19:04:03",
                confirmation_elapsed_seconds=3.0,
            )
        )

    def test_running_clock_confirmation_handles_midnight_rollover(self) -> None:
        self.assertTrue(
            _write_readback_matches(
                self.time_capability,
                requested_value="23:59:59",
                written_value="23:59:59",
                readback_value="00:00:03",
                confirmation_elapsed_seconds=3.0,
            )
        )

    def test_running_clock_confirmation_fails_closed_on_malformed_inputs(self) -> None:
        for malformed in ("19:04", " 19:04:04", "24:00:00", object(), None):
            with self.subTest(malformed=malformed):
                self.assertFalse(
                    _write_readback_matches(
                        self.time_capability,
                        requested_value="19:04:04",
                        written_value="19:04:04",
                        readback_value=malformed,
                        confirmation_elapsed_seconds=3.0,
                    )
                )
        for malformed_elapsed in (True, "3", float("nan"), float("inf")):
            with self.subTest(malformed_elapsed=malformed_elapsed):
                self.assertFalse(
                    _write_readback_matches(
                        self.time_capability,
                        requested_value="19:04:04",
                        written_value="19:04:04",
                        readback_value="19:04:08",
                        confirmation_elapsed_seconds=malformed_elapsed,
                    )
                )

    def test_elapsed_confirmation_does_not_relax_scalar_writes(self) -> None:
        self.assertFalse(
            _write_readback_matches(
                self.scalar_capability,
                requested_value=30,
                written_value=30,
                readback_value=31,
                confirmation_elapsed_seconds=300.0,
            )
        )

    def test_hub_accepts_clock_that_advanced_during_real_readback_path(self) -> None:
        async def _run() -> None:
            profile = load_driver_profile(
                "modbus_smg/models/anenji_anj_11kw_48v_wifi_p.json"
            )
            hub = EybondHub(
                connection=EybondConnectionSpec(
                    server_ip="192.168.1.10",
                    collector_ip="192.168.1.14",
                    tcp_port=8899,
                    udp_port=58899,
                    discovery_target="192.168.1.255",
                    discovery_interval=30,
                    heartbeat_interval=60,
                    request_timeout=5.0,
                ),
            )
            hub._link_manager = _FakeLinkManager()
            hub._driver = _AdvancingClockWriteDriver(readback="19:04:08")
            hub._inverter = DetectedInverter(
                driver_key="modbus_smg",
                protocol_family="modbus_smg",
                model_name="Anenji ANJ-11KW-48V-WIFI-P",
                serial_number="92632500000001",
                probe_target=ProbeTarget(
                    devcode=0x0001,
                    collector_addr=0x02,
                    device_addr=0x01,
                ),
                capabilities=profile.capabilities,
                capability_groups=profile.groups,
                capability_presets=profile.presets,
            )

            with patch(
                "custom_components.eybond_local.runtime.hub.management.monotonic",
                side_effect=(100.0, 104.0),
            ):
                written = await hub.async_write_capability(
                    "inverter_time_write",
                    "19:04:04",
                )

            self.assertEqual(written, "19:04:04")
            self.assertEqual(hub._driver.write_calls, 1)
            self.assertEqual(hub._driver.read_calls, 2)

        asyncio.run(_run())



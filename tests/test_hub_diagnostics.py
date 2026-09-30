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


class CollectorDevcodeDiagnosticsTests(unittest.TestCase):
    """Diagnostics/devcode split: stable identity vs volatile frame vs route."""

    def _hub(self) -> EybondHub:
        hub = EybondHub(
            connection=EybondConnectionSpec(
                server_ip="192.168.1.10",
                collector_ip="192.168.1.14",
                collector_pn="V001020SYN62344022",
                tcp_port=8899,
                udp_port=58899,
                discovery_target="192.168.1.255",
                discovery_interval=30,
                heartbeat_interval=60,
                request_timeout=5.0,
            ),
        )
        hub._link_manager = _FakeLinkManager()
        return hub

    def test_zero_heartbeat_devcode_is_preserved_as_0x0000(self) -> None:
        hub = self._hub()
        hub._link_manager.collector_info.heartbeat_devcode = 0x0000
        hub._link_manager.collector_info.last_devcode = 0x0994  # volatile last frame

        snapshot = hub._build_snapshot()

        # 0x0000 is a valid identity, not "no data": collector_devcode stays 0x0000
        # and never falls through to the volatile last-frame devcode.
        self.assertEqual(snapshot.values["collector_devcode"], "0x0000")
        self.assertEqual(snapshot.values["collector_heartbeat_devcode"], "0x0000")
        self.assertEqual(snapshot.values["collector_last_frame_devcode"], "0x0994")

    def test_last_frame_devcode_changes_without_changing_identity(self) -> None:
        hub = self._hub()
        hub._link_manager.collector_info.heartbeat_devcode = 0x0994  # stable identity

        hub._link_manager.collector_info.last_devcode = 0x0001
        first = hub._build_snapshot()
        hub._last_snapshot = first
        hub._link_manager.collector_info.last_devcode = 0x0002
        second = hub._build_snapshot()

        # Stable identity is unchanged across frames; only the frame diagnostic moves.
        self.assertEqual(first.values["collector_devcode"], "0x0994")
        self.assertEqual(second.values["collector_devcode"], "0x0994")
        self.assertEqual(first.values["collector_last_frame_devcode"], "0x0001")
        self.assertEqual(second.values["collector_last_frame_devcode"], "0x0002")

    def test_inverter_route_devcode_distinct_from_collector_devcode(self) -> None:
        hub = self._hub()
        hub._link_manager.collector_info.heartbeat_devcode = 0x0000  # collector identity
        hub._link_manager.collector_info.smartess_device_address = 4  # mgmt addr
        hub._inverter = DetectedInverter(
            driver_key="modbus_smg",
            protocol_family="modbus_smg",
            model_name="SMG 6200",
            serial_number="92632500000001",
            probe_target=ProbeTarget(devcode=0x0994, collector_addr=1, device_addr=0),
        )

        snapshot = hub._build_snapshot()

        # The inverter payload route (probe target) is distinct from the collector
        # identity/management devcode.
        self.assertEqual(snapshot.values["inverter_route_devcode"], "0x0994")
        self.assertEqual(snapshot.values["collector_devcode"], "0x0000")
        self.assertNotEqual(
            snapshot.values["inverter_route_devcode"],
            snapshot.values["collector_devcode"],
        )
        self.assertEqual(snapshot.values["smartess_device_address"], 4)

    def test_snapshot_exposes_separate_heartbeat_frame_route_diagnostics(self) -> None:
        hub = self._hub()
        hub._link_manager.collector_info.heartbeat_devcode = 0x0001
        hub._link_manager.collector_info.last_devcode = 0x0994
        hub._inverter = DetectedInverter(
            driver_key="modbus_smg",
            protocol_family="modbus_smg",
            model_name="SMG 6200",
            serial_number="92632500000001",
            probe_target=ProbeTarget(devcode=0x0002, collector_addr=1, device_addr=0),
        )

        snapshot = hub._build_snapshot()

        self.assertEqual(snapshot.values["collector_heartbeat_devcode"], "0x0001")
        self.assertEqual(snapshot.values["collector_last_frame_devcode"], "0x0994")
        self.assertEqual(snapshot.values["inverter_route_devcode"], "0x0002")
        # 0 collector/device addr are preserved (is-not-None, not falsy).
        self.assertEqual(snapshot.values["inverter_route_collector_addr"], 1)
        self.assertEqual(snapshot.values["inverter_route_device_addr"], 0)

    def test_stable_devcode_does_not_mask_last_frame_devcode(self) -> None:
        hub = self._hub()
        hub._link_manager.collector_info.heartbeat_devcode = 0x0994
        hub._link_manager.collector_info.last_devcode = 0x0001

        snapshot = hub._build_snapshot()

        # The stable collector_devcode and the volatile last-frame field coexist
        # as distinct, clearer fields -- neither masks the other.
        self.assertIn("collector_devcode", snapshot.values)
        self.assertIn("collector_last_frame_devcode", snapshot.values)
        self.assertNotEqual(
            snapshot.values["collector_devcode"],
            snapshot.values["collector_last_frame_devcode"],
        )

    def test_metadata_semantic_ownership_is_flattened_for_support(self) -> None:
        hub = self._hub()
        hub.collector_metadata_diagnostics = lambda: {
            "routes": [
                {
                    "channel_id": "collector:fc_metadata",
                    "effective_excluded_semantic_fields": ["collector_ssid"],
                    "unsupported_semantic_fields": ["collector_ssid"],
                },
                {
                    "channel_id": "collector:at_metadata",
                    "effective_excluded_semantic_fields": [
                        "collector_wifi_gateway",
                        "collector_wifi_ip",
                    ],
                    "unsupported_semantic_fields": [],
                },
            ],
            "semantic_ownership": {
                "binding_generation": 4,
                "at_owned_fields": [
                    "collector_signal_strength",
                    "collector_signal_strength_raw",
                ],
                "framed_unsupported_fields": ["collector_ssid"],
            },
        }
        values: dict[str, object] = {}

        hub._apply_collector_metadata_diagnostics(values)

        self.assertEqual(
            values["collector_metadata_effective_exclusions"],
            "collector:fc_metadata=collector_ssid, "
            "collector:at_metadata=collector_wifi_gateway|collector_wifi_ip",
        )
        self.assertEqual(
            values["collector_metadata_unsupported_fields"],
            "collector:fc_metadata=collector_ssid",
        )
        self.assertEqual(values["collector_metadata_semantic_binding_generation"], 4)
        self.assertEqual(
            values["collector_metadata_at_owned_fields"],
            "collector_signal_strength, collector_signal_strength_raw",
        )
        self.assertEqual(
            values["collector_metadata_framed_unsupported_fields"],
            "collector_ssid",
        )



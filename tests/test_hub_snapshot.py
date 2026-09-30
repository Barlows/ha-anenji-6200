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


class HubSnapshotTests(unittest.TestCase):
    def test_listener_diagnostics_delegate_to_link_manager(self) -> None:
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

        diagnostics = hub.listener_diagnostics()

        self.assertEqual(diagnostics["collector_configured_session_protocol"], "at_text")
        self.assertEqual(diagnostics["collector_callback_identity_strategy"], "at_dtupn")

    def test_initial_inverter_binding_seeds_runtime_driver_state(self) -> None:
        hub = EybondHub(
            connection=EybondConnectionSpec(
                server_ip="192.168.1.10",
                collector_ip="",
                collector_pn="V001020SYN62344022",
                tcp_port=18899,
                udp_port=58899,
                discovery_target="192.168.1.255",
                discovery_interval=30,
                heartbeat_interval=60,
                request_timeout=5.0,
                collector_configured_session_protocol="at_text",
            ),
        )
        hub._link_manager = _FakeLinkManager()
        driver = _SeedDriver()
        inverter = DetectedInverter(
            driver_key="pi30",
            protocol_family="pi30",
            model_name="PI30 3500",
            variant_key="default",
            serial_number="55355535553555",
            probe_target=ProbeTarget(devcode=0x0994, collector_addr=0x01, device_addr=0),
            profile_name="pi30_ascii/models/smartess_0925_compat.json",
            register_schema_name="pi30_ascii/models/smartess_0925_compat.json",
        )

        hub.set_initial_inverter_binding(driver, inverter)  # type: ignore[arg-type]
        snapshot = hub._build_snapshot()

        self.assertIs(hub._driver, driver)
        self.assertIs(hub._inverter, inverter)
        self.assertEqual(snapshot.values["runtime_driver_state"], "driver_bound")
        self.assertEqual(snapshot.values["driver_key"], "pi30")

    def test_build_snapshot_includes_effective_profile_and_schema_names(self) -> None:
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
        hub._inverter = DetectedInverter(
            driver_key="pi30",
            protocol_family="pi30",
            model_name="PowMr 4.2kW",
            variant_key="vmii_nxpw5kw",
            serial_number="553555355535552",
            probe_target=ProbeTarget(devcode=0x0994, collector_addr=0x01, device_addr=0),
            profile_name="pi30_ascii/models/vmii_nxpw5kw.json",
            register_schema_name="pi30_ascii/models/vmii_nxpw5kw.json",
        )

        snapshot = hub._build_snapshot()

        self.assertEqual(snapshot.values["driver_key"], "pi30")
        self.assertEqual(snapshot.values["runtime_driver_state"], "driver_bound")
        self.assertEqual(snapshot.values["variant_key"], "vmii_nxpw5kw")
        self.assertEqual(snapshot.values["profile_name"], "pi30_ascii/models/vmii_nxpw5kw.json")
        self.assertEqual(
            snapshot.values["register_schema_name"],
            "pi30_ascii/models/vmii_nxpw5kw.json",
        )

    def test_build_snapshot_synchronizes_fresh_endpoint_into_collector_info(self) -> None:
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
        hub._link_manager.collector_info.collector_server_endpoint = (
            "old.example,18899,TCP"
        )

        snapshot = hub._build_snapshot(
            extra_values={
                "collector_server_endpoint": "fresh.example,18899,TCP",
            }
        )

        self.assertEqual(
            snapshot.collector.collector_server_endpoint,
            "fresh.example,18899,TCP",
        )
        self.assertEqual(
            snapshot.values["collector_server_endpoint"],
            "fresh.example,18899,TCP",
        )

    def test_build_snapshot_refuses_foreign_collector_pn_override(self) -> None:
        durable_pn = "V001020SYN62344022"
        foreign_pn = "V001020ABC99999999"
        hub = EybondHub(
            connection=EybondConnectionSpec(
                server_ip="192.168.1.10",
                collector_ip="192.168.1.14",
                collector_pn=durable_pn,
                tcp_port=8899,
                udp_port=58899,
                discovery_target="192.168.1.255",
                discovery_interval=30,
                heartbeat_interval=60,
                request_timeout=5.0,
            ),
        )
        hub._link_manager = _FakeLinkManager()
        hub._link_manager.collector_info.collector_pn = durable_pn

        snapshot = hub._build_snapshot(
            extra_values={"collector_pn": foreign_pn}
        )

        self.assertEqual(snapshot.collector.collector_pn, durable_pn)
        self.assertEqual(snapshot.values["collector_pn"], durable_pn)
        self.assertTrue(snapshot.values["collector_pn_identity_conflict"])

    def test_build_snapshot_synchronizes_fresh_cloud_profile_as_one_value(self) -> None:
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
        hub._link_manager.collector_info.collector_cloud_profile_key = "stale"
        hub._link_manager.collector_info.collector_cloud_profile_label = "Stale"
        hub._link_manager.collector_info.collector_cloud_profile_source = "entry_persisted"
        hub._link_manager.collector_info.collector_cloud_profile_confidence = "low"

        snapshot = hub._build_snapshot(
            extra_values={
                "collector_cloud_profile_key": "valuecloud_at",
                "collector_cloud_profile_label": "ValueCloud AT",
                "collector_cloud_profile_source": "transport_sniff",
                "collector_cloud_profile_confidence": "high",
            }
        )

        self.assertEqual(snapshot.collector_cloud_profile.key, "valuecloud_at")
        self.assertEqual(snapshot.collector_cloud_profile.label, "ValueCloud AT")
        self.assertEqual(snapshot.collector_cloud_profile.source, "transport_sniff")
        self.assertEqual(snapshot.collector_cloud_profile.confidence, "high")
        self.assertEqual(
            snapshot.collector.collector_cloud_profile_key,
            "valuecloud_at",
        )
        self.assertEqual(
            snapshot.values["collector_cloud_profile_key"],
            "valuecloud_at",
        )

    def test_build_snapshot_synchronizes_stronger_cloud_family_provenance(self) -> None:
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
        collector = hub._link_manager.collector_info
        collector.collector_cloud_family = "smartess_at"
        collector.collector_cloud_family_source = "endpoint_host"
        collector.collector_cloud_family_confidence = "low"

        snapshot = hub._build_snapshot(
            extra_values={
                "collector_cloud_family": "valuecloud_at",
                "collector_cloud_family_source": "transport_sniff",
                "collector_cloud_family_confidence": "high",
            }
        )

        self.assertEqual(snapshot.collector.collector_cloud_family, "valuecloud_at")
        self.assertEqual(
            snapshot.collector.collector_cloud_family_source,
            "transport_sniff",
        )
        self.assertEqual(snapshot.values["collector_cloud_family"], "valuecloud_at")
        self.assertEqual(
            snapshot.values["collector_cloud_family_confidence"],
            "high",
        )

    def test_build_snapshot_does_not_reuse_stale_collector_identity_values(self) -> None:
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
        hub._last_snapshot = RuntimeSnapshot(
            values={
                "smartess_collector_version": "8.50.12.3",
                "collector_type": "Wi-Fi.DTU",
                "collector_server_endpoint": "dtu_ess.eybond.com,18899,TCP",
                "collector_signal_quality": "excellent",
                "collector_virtual_bridge": True,
                "collector_bridge_version": "0.4.0",
                "collector_reboot_required": "1",
                "collector_upload_mode": "ON",
                "collector_system_time": "20250120120000",
                "collector_serial_baudrate": "2400,8,1,NONE",
                "smartess_protocol_asset_id": "0925",
            }
        )

        snapshot = hub._build_snapshot()

        self.assertNotIn("smartess_collector_version", snapshot.values)
        self.assertNotIn("collector_type", snapshot.values)
        self.assertNotIn("collector_server_endpoint", snapshot.values)
        self.assertNotIn("collector_signal_quality", snapshot.values)
        self.assertNotIn("collector_virtual_bridge", snapshot.values)
        self.assertNotIn("collector_bridge_version", snapshot.values)
        self.assertNotIn("collector_reboot_required", snapshot.values)
        self.assertNotIn("collector_upload_mode", snapshot.values)
        self.assertNotIn("collector_system_time", snapshot.values)
        self.assertNotIn("collector_serial_baudrate", snapshot.values)
        self.assertNotIn("smartess_protocol_asset_id", snapshot.values)

    def test_bound_collector_phase_does_not_publish_stale_inverter_values(self) -> None:
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
        hub._inverter = DetectedInverter(
            driver_key="pi30",
            protocol_family="pi30",
            model_name="PowMr 4.2kW",
            serial_number="553555355535552",
            probe_target=ProbeTarget(devcode=0x0994, collector_addr=0x01, device_addr=0),
        )
        hub._last_snapshot = RuntimeSnapshot(
            connected=True,
            values={
                "grid_voltage": 230.0,
                "collector_serial_baudrate": "2400,8,1,NONE",
            },
        )
        observed: list[RuntimeSnapshot] = []
        hub.set_runtime_snapshot_observer(observed.append)

        hub._publish_intermediate_snapshot(
            {"collector_serial_baudrate": "9600,8,1,NONE"},
            status="",
        )

        self.assertEqual(observed, [])
        self.assertEqual(hub._last_snapshot.values["grid_voltage"], 230.0)
        self.assertEqual(
            hub._last_snapshot.values["collector_serial_baudrate"],
            "2400,8,1,NONE",
        )

    def test_detection_phase_publish_reports_collector_state(self) -> None:
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
        hub._last_snapshot = RuntimeSnapshot(
            connected=True,
            values={
                "collector_serial_baudrate": "2400,8,1,NONE",
            },
        )
        observed: list[RuntimeSnapshot] = []
        hub.set_runtime_snapshot_observer(observed.append)

        hub._publish_intermediate_snapshot(
            {"collector_serial_baudrate": "9600,8,1,NONE"},
            status="detecting_inverter",
        )

        self.assertEqual(len(observed), 1)
        self.assertEqual(
            observed[0].values["collector_serial_baudrate"],
            "9600,8,1,NONE",
        )
        self.assertEqual(
            observed[0].values["runtime_detection_status"],
            "detecting_inverter",
        )

    def test_build_snapshot_adds_canonical_common_values_for_pi30(self) -> None:
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
        hub._inverter = DetectedInverter(
            driver_key="pi30",
            protocol_family="pi30",
            model_name="PowMr 4.2kW",
            variant_key="vmii_nxpw5kw",
            serial_number="553555355535552",
            probe_target=ProbeTarget(devcode=0x0994, collector_addr=0x01, device_addr=0),
        )

        snapshot = hub._build_snapshot(
            extra_values={
                "input_voltage": 230.0,
                "input_frequency": 50.0,
                "output_active_power": 1400,
                "pv_input_voltage": 118.0,
                "pv_input_current": 8.5,
                "pv_input_power": 1003,
                "battery_voltage": 51.2,
                "battery_charge_current": 12.0,
                "battery_discharge_current": 0.0,
            }
        )

        self.assertEqual(snapshot.values["grid_voltage"], 230.0)
        self.assertEqual(snapshot.values["grid_frequency"], 50.0)
        self.assertEqual(snapshot.values["output_power"], 1400)
        self.assertEqual(snapshot.values["pv_voltage"], 118.0)
        self.assertEqual(snapshot.values["pv_current"], 8.5)
        self.assertEqual(snapshot.values["pv_power"], 1003)
        self.assertEqual(snapshot.values["battery_power"], 614.4)

    def test_build_snapshot_includes_collector_churn_markers(self) -> None:
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
        hub._link_manager.collector_info.connection_count = 3
        hub._link_manager.collector_info.connection_replace_count = 1
        hub._link_manager.collector_info.disconnect_count = 2
        hub._link_manager.collector_info.pending_request_drop_count = 4
        hub._link_manager.collector_info.last_disconnect_reason = "collector_connection_reset"
        hub._link_manager.collector_info.discovery_restart_count = 5
        hub._link_manager.collector_info.last_discovery_reason = "heartbeat_timeout"

        snapshot = hub._build_snapshot()

        self.assertEqual(snapshot.values["collector_connection_count"], 3)
        self.assertEqual(snapshot.values["collector_connection_replace_count"], 1)
        self.assertEqual(snapshot.values["collector_disconnect_count"], 2)
        self.assertEqual(snapshot.values["collector_pending_request_drop_count"], 4)
        self.assertEqual(
            snapshot.values["collector_last_disconnect_reason"],
            "collector_connection_reset",
        )
        self.assertEqual(snapshot.values["collector_discovery_restart_count"], 5)
        self.assertEqual(
            snapshot.values["collector_last_discovery_reason"],
            "heartbeat_timeout",
        )

    def test_build_snapshot_reports_none_instead_of_dropping_fault_entities(self) -> None:
        # These entities are enabled by default. Popping the key made a healthy
        # system surface them as "unavailable", which reads as a fault.
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

        snapshot = hub._build_snapshot()

        self.assertEqual(snapshot.values["last_error"], "none")
        self.assertEqual(snapshot.values["collector_retained_disconnect_reason"], "none")
        # The live-session field stays absent while no session has torn down.
        self.assertNotIn("collector_last_disconnect_reason", snapshot.values)

    def test_build_snapshot_retains_disconnect_reason_across_reconnects(self) -> None:
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
        collector = hub._link_manager.collector_info
        collector.disconnect_count = 1
        collector.retained_disconnect_reason = "collector_frame_header_timeout"
        # A reconnect resets the live-session field but must not lose the fault.
        collector.last_disconnect_reason = ""

        snapshot = hub._build_snapshot()

        self.assertEqual(
            snapshot.values["collector_retained_disconnect_reason"],
            "collector_frame_header_timeout",
        )
        self.assertNotIn("collector_last_disconnect_reason", snapshot.values)

    def test_build_snapshot_prefers_more_complete_runtime_collector_pn(self) -> None:
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
        hub._link_manager.collector_info.collector_pn = "E5000020000000"

        snapshot = hub._build_snapshot(
            extra_values={"collector_pn": "E50000200000000001"}
        )

        self.assertEqual(snapshot.collector.collector_pn, "E50000200000000001")
        self.assertEqual(snapshot.collector.collector_pn_prefix, "E")
        self.assertEqual(snapshot.collector.collector_pn_digits, "50000200000000001")
        self.assertEqual(snapshot.values["collector_pn"], "E50000200000000001")

    def test_support_evidence_skips_generic_scan_for_bridge_probe_timeout(self) -> None:
        async def _run() -> dict[str, object]:
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
            hub._link_manager.collector_info.collector_virtual_bridge = True
            hub._driver = None
            hub._inverter = None

            async def _detect_driver() -> str:
                return "smartess_local:probe_timeout"

            async def _generic_support_evidence(_detect_error: str) -> dict[str, object]:
                raise AssertionError("generic register scan must be skipped")

            hub._async_detect_driver = _detect_driver
            hub._async_capture_generic_support_evidence = _generic_support_evidence
            return await hub.async_capture_support_evidence()

        evidence = asyncio.run(_run())

        self.assertEqual(evidence["capture_kind"], "collector_only")
        self.assertEqual(evidence["detection_error"], "smartess_local:probe_timeout")
        self.assertEqual(evidence["captures"], [])

    def test_local_register_snapshot_uses_live_identity_and_exact_driver_result(self) -> None:
        async def _run() -> tuple[LocalRegisterSnapshot, object]:
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
            hub._link_manager.collector_info.collector_pn = "E50000200000000001"
            hub._inverter = DetectedInverter(
                driver_key="smg",
                protocol_family="modbus",
                model_name="SMG",
                serial_number="serial",
                probe_target=ProbeTarget(
                    devcode=2376,
                    collector_addr=1,
                    device_addr=1,
                ),
            )
            snapshot = LocalRegisterSnapshot(
                collector_pn="E50000200000000001",
                driver_key="smg",
                started_at="2026-08-22T10:00:00+00:00",
                completed_at="2026-08-22T10:00:02+00:00",
                planned_block_count=1,
                failed_block_count=0,
                blocks=(
                    LocalRegisterBlockObservation(
                        plan=LocalRegisterReadPlan(
                            devcode=2376,
                            collector_addr=1,
                            device_addr=1,
                            function=3,
                            start=300,
                            count=1,
                        ),
                        observed_at="2026-08-22T10:00:01+00:00",
                        values=(2305,),
                    ),
                ),
            )
            driver = SimpleNamespace(
                async_capture_local_register_snapshot=AsyncMock(
                    return_value=snapshot
                )
            )
            hub._driver = driver

            captured = await hub.async_capture_local_register_snapshot()
            return captured, driver

        captured, driver = asyncio.run(_run())

        self.assertEqual(captured.collector_pn, "E50000200000000001")
        driver.async_capture_local_register_snapshot.assert_awaited_once()
        self.assertEqual(
            driver.async_capture_local_register_snapshot.await_args.kwargs,
            {"collector_pn": "E50000200000000001"},
        )

    def test_local_register_snapshot_rejects_duck_driver_result(self) -> None:
        async def _run() -> None:
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
            hub._link_manager.collector_info.collector_pn = "E50000200000000001"
            hub._inverter = DetectedInverter(
                driver_key="smg",
                protocol_family="modbus",
                model_name="SMG",
                serial_number="serial",
                probe_target=ProbeTarget(2376, 1, 1),
            )
            hub._driver = SimpleNamespace(
                async_capture_local_register_snapshot=AsyncMock(
                    return_value={"authority": "live_local_wire_observation"}
                )
            )

            with self.assertRaisesRegex(
                TypeError,
                "driver_local_register_snapshot_invalid",
            ):
                await hub.async_capture_local_register_snapshot()

        asyncio.run(_run())

    def test_generic_support_evidence_keeps_compiled_identity_point_reads(self) -> None:
        async def _run() -> tuple[dict[str, object], list[tuple[int, int]]]:
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
                driver_hint="modbus_smg",
            )
            hub._link_manager = _FakeLinkManager()
            reads: list[tuple[int, int]] = []

            class _RecordingSession:
                def __init__(self, *_args, **_kwargs) -> None:
                    pass

                async def read_holding(self, start: int, count: int) -> list[int]:
                    reads.append((start, count))
                    return [0] * count

            with (
                patch(
                    "custom_components.eybond_local.runtime.hub.support.ModbusSession",
                    _RecordingSession,
                ),
                patch.object(
                    hub,
                    "_async_capture_at_text_ascii_probe",
                    AsyncMock(return_value=None),
                ),
            ):
                evidence = await hub._async_capture_generic_support_evidence(
                    "modbus_smg:no_match"
                )
            return evidence, reads

        evidence, reads = asyncio.run(_run())

        captures = evidence["captures"]
        self.assertEqual(len(captures), 1)
        planned = [
            (item["start"], item["count"])
            for item in captures[0]["planned_ranges"]
        ]
        self.assertEqual(planned[:2], [(171, 1), (184, 1)])
        self.assertNotIn((171, 14), planned)
        self.assertIn((643, 2), planned)
        self.assertIn((643, 1), planned)
        self.assertEqual(reads, planned)

    def test_build_snapshot_recomputes_smg_canonical_battery_power(self) -> None:
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
        hub._inverter = DetectedInverter(
            driver_key="modbus_smg",
            protocol_family="modbus_smg",
            model_name="SMG 6200",
            serial_number="92632500000001",
            probe_target=ProbeTarget(devcode=0x0001, collector_addr=0x02, device_addr=0x01),
        )
        hub._last_snapshot = hub._build_snapshot(
            extra_values={
                "battery_average_power": -216.0,
            }
        )

        snapshot = hub._build_snapshot(
            extra_values={
                "battery_average_power": -144.0,
            }
        )

        self.assertEqual(snapshot.values["battery_average_power"], -144.0)
        self.assertEqual(snapshot.values["battery_power"], -144.0)

    def test_async_refresh_keeps_collector_connected_on_inverter_request_timeout(self) -> None:
        async def _run() -> None:
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
            hub._driver = _TimeoutDriver()
            hub._inverter = DetectedInverter(
                driver_key="modbus_smg",
                protocol_family="modbus_smg",
                model_name="SMG 6200",
                serial_number="92632500000001",
                probe_target=ProbeTarget(devcode=0x0001, collector_addr=0x02, device_addr=0x01),
            )
            hub._last_snapshot = hub._build_snapshot(
                extra_values={
                    "output_power": 50,
                    "battery_average_power": -71,
                }
            )

            snapshot = await hub.async_refresh(poll_interval=3.0)

            self.assertTrue(snapshot.connected)
            self.assertEqual(snapshot.last_error, "request_timeout")
            self.assertEqual(snapshot.values["output_power"], 50)
            self.assertEqual(snapshot.values["battery_power"], -71)
            self.assertEqual(snapshot.values["runtime_recovery_streak"], 0)
            self.assertEqual(snapshot.values["runtime_backoff_seconds"], 0)
            self.assertEqual(snapshot.values["runtime_payload_error"], "request_timeout")
            self.assertEqual(hub._link_manager.reset_calls, 0)
            self.assertEqual(hub._driver.calls, 2)

        asyncio.run(_run())

    def test_async_refresh_merges_safe_collector_runtime_queries(self) -> None:
        async def _run() -> None:
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
            link_manager = _FakeLinkManager()
            link_manager.transport = _CollectorQueryTransport(
                {
                    (2, b"\x04"): b"\x00\x041.11",
                    (2, b"\x05"): b"\x00\x058.50.12.3",
                    (2, b"\x06"): b"\x00\x061.0",
                    (2, b"\x0e"): b"\x00\x0e0925#Hybrid",
                    (2, b"\x10"): b"\x00\x10192.168.1.55",
                    (2, b"\x15"): b"\x00\x15192.168.1.193,18899,TCP",
                    (2, b"\x1e"): b"\x00\x1e1",
                    (2, b"\x20"): b"\x00\x20RTU",
                    (2, b"\x22"): b"\x00\x229600,8,1,NONE",
                    (2, b"\x30"): b"\x00\x30STA:-67",
                    (2, b"\x37"): b"\x00\x37-67",
                }
            )
            hub._link_manager = link_manager
            hub._driver = _RuntimeValuesDriver()
            hub._inverter = DetectedInverter(
                driver_key="modbus_smg",
                protocol_family="modbus_smg",
                model_name="SMG 6200",
                serial_number="INV123",
                probe_target=ProbeTarget(devcode=1, collector_addr=1, device_addr=1),
                profile_name="builtin:profiles/modbus_smg/default.json",
                register_schema_name="builtin:register_schemas/modbus_smg/models/smg_6200.json",
            )

            snapshot = await hub.async_refresh(poll_interval=3.0)

            self.assertEqual(snapshot.values["smartess_collector_version"], "8.50.12.3")
            self.assertEqual(snapshot.values["collector_protocol_version"], "1.11")
            self.assertEqual(snapshot.values["collector_hardware_version"], "1.0")
            self.assertEqual(snapshot.values["collector_local_ip_address"], "192.168.1.55")
            self.assertEqual(snapshot.values["collector_server_endpoint"], "192.168.1.193,18899,TCP")
            self.assertEqual(snapshot.values["collector_reboot_required"], "1")
            self.assertEqual(snapshot.values["collector_transmission_mode"], "RTU")
            self.assertEqual(snapshot.values["collector_serial_baudrate"], "9600,8,1,NONE")
            self.assertEqual(snapshot.values["collector_network_diagnostics"], "STA:-67")
            self.assertEqual(snapshot.values["collector_signal_strength"], -67)
            self.assertEqual(snapshot.values["collector_signal_strength_raw"], "-67")
            self.assertEqual(snapshot.values["collector_signal_strength_source"], "Wi-Fi RSSI")
            self.assertEqual(snapshot.values["collector_signal_quality"], "excellent")
            self.assertEqual(snapshot.values["collector_callback_owner"], "Custom endpoint")
            self.assertEqual(snapshot.values["smartess_protocol_asset_id"], "0925")
            self.assertEqual(snapshot.values["smartess_protocol_profile_key"], "smartess_0925")

        asyncio.run(_run())

    def test_async_refresh_uses_framed_owner_and_at_only_for_supplemental_fields(self) -> None:
        async def _run() -> None:
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
            link_manager = _FakeLinkManager()
            link_manager.transport = _CollectorQueryTransport(
                {
                    (2, b"\x15"): b"\x00\x15fc.example,18899,TCP",
                    (2, b"\x29"): b"\x00\x29MyWiFi",
                    (2, b"\x30"): b"\x00\x301",
                    (2, b"\x37"): b"\x00\x371",
                }
            )
            link_manager.collector_at_transport = _CollectorAtQueryTransport(
                {
                    "ATVER": "2.05",
                    "CLDSRVHOST1": "at.example,18899,TCP",
                    "DTUPN": "E1234567890",
                    "DTUTYPE": "Wi-Fi.DTU",
                    "ENUPMODE": "ON",
                    "FWVER": "8.50.12.3",
                    "HTBT": "60",
                    "INTPARA41": "MyWiFi",
                    "INTPARA49": "ssid1,-55;ssid2,-71",
                    "LINK": "STA,CONNECTED",
                    "SYST": "20250120120000",
                    "UART": "9600,8,1,NONE",
                    "WFSS": "-55",
                }
            )
            hub._link_manager = link_manager
            hub._driver = _RuntimeValuesDriver()
            hub._inverter = DetectedInverter(
                driver_key="modbus_smg",
                protocol_family="modbus_smg",
                model_name="SMG 6200",
                serial_number="INV123",
                probe_target=ProbeTarget(devcode=1, collector_addr=1, device_addr=1),
                profile_name="builtin:profiles/modbus_smg/default.json",
                register_schema_name="builtin:register_schemas/modbus_smg/models/smg_6200.json",
            )

            snapshot = await hub.async_refresh(poll_interval=3.0)

            self.assertEqual(snapshot.values["collector_server_endpoint"], "fc.example,18899,TCP")
            self.assertEqual(snapshot.values["collector_signal_strength"], -55)
            self.assertEqual(snapshot.values["collector_signal_strength_raw"], "-55")
            self.assertEqual(snapshot.values["collector_signal_strength_source"], "Wi-Fi RSSI")
            self.assertEqual(snapshot.values["collector_signal_quality"], "excellent")
            self.assertEqual(snapshot.values["collector_type"], "Wi-Fi.DTU")
            self.assertEqual(snapshot.values["collector_upload_mode"], "ON")
            self.assertEqual(snapshot.values["collector_system_time"], "20250120120000")
            self.assertEqual(snapshot.values["collector_cloud_heartbeat_value"], "60")
            self.assertEqual(snapshot.values["collector_ssid"], "MyWiFi")
            self.assertEqual(snapshot.values["collector_link_status"], "STA,CONNECTED")
            self.assertEqual(snapshot.values["collector_wifi_scan_list"], "ssid1,-55;ssid2,-71")

        asyncio.run(_run())

    def test_async_refresh_returns_live_collector_at_snapshot_when_framed_link_is_missing(self) -> None:
        async def _run() -> None:
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
            at_transport = _CollectorAtQueryTransport(
                {
                    "ATVER": "2.05",
                    "CLDSRVHOST1": "at.example,18899,TCP",
                    "DTUPN": "E1234567890",
                    "DTUTYPE": "Wi-Fi.DTU",
                    "ENUPMODE": "ON",
                    "FWVER": "8.50.12.3",
                    "HTBT": "60",
                    "INTPARA41": "MyWiFi",
                    "INTPARA49": "ssid1,-55;ssid2,-71",
                    "LINK": "STA,CONNECTED",
                    "SYST": "20250120120000",
                    "UART": "9600,8,1,NONE",
                    "WFSS": "-55",
                },
                connected=False,
            )
            hub._link_manager = _CollectorOnlyLinkManager(at_transport)

            snapshot = await hub.async_refresh(poll_interval=3.0)

            self.assertTrue(snapshot.connected)
            self.assertEqual(snapshot.last_error, "inverter_heartbeat_missing")
            self.assertEqual(snapshot.values["runtime_driver_state"], "driver_unbound")
            self.assertEqual(snapshot.values["collector_protocol_version"], "2.05")
            self.assertEqual(snapshot.values["collector_server_endpoint"], "at.example,18899,TCP")
            self.assertEqual(snapshot.values["collector_signal_strength"], -55)
            self.assertEqual(snapshot.values["collector_signal_quality"], "excellent")
            self.assertEqual(snapshot.values["collector_type"], "Wi-Fi.DTU")
            self.assertEqual(snapshot.values["collector_upload_mode"], "ON")
            self.assertEqual(snapshot.values["collector_cloud_heartbeat_value"], "60")
            self.assertEqual(snapshot.values["collector_ssid"], "MyWiFi")
            self.assertEqual(snapshot.values["collector_link_status"], "STA,CONNECTED")
            self.assertEqual(snapshot.values["collector_wifi_scan_list"], "ssid1,-55;ssid2,-71")

        asyncio.run(_run())

    def test_async_refresh_does_not_reuse_stale_collector_runtime_cache_when_offline(self) -> None:
        async def _run() -> None:
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
            hub._collector_runtime_values = {
                "collector_server_endpoint": "dtu_ess.eybond.com,18899,TCP",
                "collector_reboot_required": "1",
                "collector_upload_mode": "ON",
                "collector_system_time": "20250120120000",
            }
            hub._collector_at_runtime_values = {
                "smartess_collector_version": "8.50.12.3",
                "collector_type": "Wi-Fi.DTU",
            }
            hub._link_manager = _CollectorOnlyLinkManager(
                _CollectorAtQueryTransport({}, connected=False)
            )

            snapshot = await hub.async_refresh(poll_interval=3.0)

            self.assertFalse(snapshot.connected)
            self.assertEqual(snapshot.last_error, "waiting_for_collector")
            self.assertNotIn("collector_server_endpoint", snapshot.values)
            self.assertNotIn("collector_reboot_required", snapshot.values)
            self.assertNotIn("collector_upload_mode", snapshot.values)
            self.assertNotIn("collector_system_time", snapshot.values)
            self.assertNotIn("smartess_collector_version", snapshot.values)
            self.assertNotIn("collector_type", snapshot.values)

        asyncio.run(_run())

    def test_invalidate_collector_runtime_values_clears_cached_uart(self) -> None:
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
        hub._collector_runtime_values = {
            "collector_serial_baudrate": "2400,8,1,NONE",
        }
        hub._collector_at_runtime_values = {
            "collector_link_status": "STA,CONNECTED",
        }
        hub._collector_runtime_values_dirty = False

        hub.invalidate_collector_runtime_values()

        self.assertEqual(hub._collector_runtime_values, {})
        self.assertEqual(hub._collector_at_runtime_values, {})
        self.assertTrue(hub._collector_runtime_values_dirty)

    def test_async_refresh_skips_runtime_collector_queries_when_active_transports_are_ambiguous(self) -> None:
        async def _run() -> None:
            hub = EybondHub(
                connection=EybondConnectionSpec(
                    server_ip="192.168.1.10",
                    collector_ip="",
                    tcp_port=8899,
                    udp_port=58899,
                    discovery_target="192.168.1.255",
                    discovery_interval=30,
                    heartbeat_interval=60,
                    request_timeout=5.0,
                ),
            )
            transport = _CollectorQueryTransport(
                {
                    (2, b"\x15"): b"\x00\x15wrong.example,18899,TCP",
                }
            )
            at_transport = _CollectorAtQueryTransport(
                {
                    "ATVER": "2.05",
                }
            )
            hub._link_manager = _AmbiguousActiveLinkManager(transport, at_transport)

            snapshot = await hub.async_refresh(poll_interval=3.0)

            self.assertFalse(snapshot.connected)
            self.assertEqual(snapshot.last_error, "waiting_for_collector")
            self.assertEqual(transport.requests, [])
            self.assertEqual(at_transport.queries, [])
            self.assertNotIn("collector_protocol_version", snapshot.values)
            self.assertNotIn("collector_server_endpoint", snapshot.values)

        asyncio.run(_run())

    def test_async_refresh_bootstraps_virtual_bridge_metadata_without_heartbeat(self) -> None:
        async def _run() -> None:
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
            transport = _CollectorQueryTransport(
                {
                    (2, b"\x06"): b"\x00\x06esp-collector/0.1.5/ESP32",
                }
            )
            hub._link_manager = _InactiveActiveLinkManager(transport)

            snapshot = await hub.async_refresh(poll_interval=10.0)

            self.assertTrue(snapshot.connected)
            self.assertEqual(snapshot.last_error, "inverter_heartbeat_missing")
            self.assertEqual(snapshot.values["runtime_driver_state"], "driver_unbound")
            self.assertIn((2, b"\x06"), transport.requests)
            self.assertTrue(snapshot.collector.collector_virtual_bridge)
            self.assertEqual(snapshot.collector.collector_bridge_kind, "esp-collector")
            self.assertEqual(snapshot.collector.collector_bridge_version, "0.1.5")
            self.assertTrue(snapshot.values["collector_virtual_bridge"])
            self.assertEqual(snapshot.values["collector_bridge_kind"], "esp-collector")
            self.assertEqual(snapshot.values["collector_bridge_version"], "0.1.5")

        asyncio.run(_run())

    def test_build_snapshot_normalizes_signal_quality_for_gprs_csq(self) -> None:
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

        snapshot = hub._build_snapshot(
            extra_values={
                "collector_signal_strength": -111,
                "collector_signal_strength_source": "gprs_csq",
                "collector_signal_strength_raw": "1",
            }
        )

        self.assertEqual(snapshot.values["collector_signal_strength"], -111)
        self.assertEqual(snapshot.values["collector_signal_strength_source"], "GPRS CSQ")
        self.assertEqual(snapshot.values["collector_signal_quality"], "weak")

    def test_build_snapshot_marks_proxy_callback_on_home_assistant_as_home_assistant(self) -> None:
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

        snapshot = hub._build_snapshot(
            extra_values={
                "collector_server_endpoint": "192.168.1.10,18899,TCP",
            }
        )

        self.assertEqual(snapshot.values["collector_callback_owner"], "Home Assistant")

    def test_proxy_capture_route_methods_delegate_to_link_manager(self) -> None:
        async def _run() -> None:
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
            link_manager = _ProxyRouteLinkManager()
            hub._link_manager = link_manager

            hub.set_reverse_discovery_enabled(False)
            await hub.async_ensure_callback_listener(18899)
            await hub.async_trigger_reverse_discovery(timeout=1.25)
            await hub.async_start_proxy_capture_route(
                collector_ip="192.168.1.14",
                expected_session_protocol="at_text",
                listen_port=18899,
                upstream_host="dtu_ess.eybond.com",
                upstream_port=18899,
                output_path=Path("/tmp/proxy-capture.jsonl"),
                masked_endpoint="dtu_ess.eybond.com,18899,TCP",
                restore_trigger_path=Path("/tmp/proxy-capture.restore"),
            )
            await hub.async_disconnect_collector_connections(reason="proxy_capture_start")

            self.assertEqual(link_manager.reverse_discovery_flags, [False])
            self.assertEqual(link_manager.callback_listener_ports, [18899])
            self.assertEqual(
                link_manager.reverse_discovery_calls,
                [{"port": 0, "timeout": 1.25}],
            )
            self.assertTrue(hub.proxy_capture_route_running())
            self.assertEqual(
                link_manager.proxy_route_start_calls,
                [
                    {
                        "collector_ip": "192.168.1.14",
                        "collector_pn": "",
                        "expected_session_protocol": "at_text",
                        "proxy_wire_mode": "transparent",
                        "listen_port": 18899,
                        "upstream_host": "dtu_ess.eybond.com",
                        "upstream_port": 18899,
                        "output_path": Path("/tmp/proxy-capture.jsonl"),
                        "masked_endpoint": "dtu_ess.eybond.com,18899,TCP",
                        "restore_trigger_path": Path("/tmp/proxy-capture.restore"),
                    }
                ],
            )
            self.assertEqual(link_manager.disconnect_reasons, ["proxy_capture_start"])

            await hub.async_stop_proxy_capture_route()

            self.assertEqual(link_manager.proxy_route_stop_calls, 1)
            self.assertFalse(hub.proxy_capture_route_running())

        asyncio.run(_run())

    def test_async_set_collector_server_endpoint_stages_and_applies_parameter_21(self) -> None:
        async def _run() -> None:
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
            link_manager = _FakeLinkManager()
            transport = _CollectorManagementTransport()
            link_manager.transport = transport
            hub._link_manager = link_manager

            result = await hub.async_set_collector_server_endpoint(
                "192.168.1.193,18899,TCP",
                apply_changes=True,
            )

            self.assertEqual(result["status"], "applied")
            self.assertEqual(result["previous_endpoint"], "47.91.67.66,18899,TCP")
            self.assertEqual(result["requested_endpoint"], "192.168.1.193,18899,TCP")
            self.assertEqual(result["readback_endpoint"], "192.168.1.193,18899,TCP")
            self.assertEqual(hub._collector_runtime_values["collector_server_endpoint"], "192.168.1.193,18899,TCP")
            self.assertEqual(hub._collector_runtime_values["collector_reboot_required"], "1")
            self.assertEqual(
                transport.requests,
                [
                    (2, b"\x15"),
                    (3, b"\x15192.168.1.193,18899,TCP"),
                    (2, b"\x15"),
                    (2, b"\x1e"),
                    (3, b"\x1d1"),
                ],
            )

        asyncio.run(_run())

    def test_async_set_collector_server_endpoint_uses_at_management_when_fc_path_is_missing(self) -> None:
        async def _run() -> None:
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
            link_manager = _FakeLinkManager()
            link_manager.transport = object()
            at_transport = _CollectorAtQueryTransport(
                {"CLDSRVHOST1": "iot.eybond.com,18899,TCP"}
            )
            link_manager.collector_at_transport = at_transport
            hub._link_manager = link_manager

            result = await hub.async_set_collector_server_endpoint(
                "192.168.8.113,18899,TCP",
                apply_changes=True,
            )

            self.assertEqual(result["status"], "applied")
            self.assertEqual(result["management_protocol"], "at_text")
            self.assertEqual(result["at_apply_response"], "W000")
            self.assertEqual(result["previous_endpoint"], "iot.eybond.com,18899,TCP")
            self.assertEqual(result["requested_endpoint"], "192.168.8.113,18899,TCP")
            self.assertEqual(result["readback_endpoint"], "192.168.8.113,18899,TCP")
            self.assertEqual(
                hub._collector_runtime_values["collector_server_endpoint"],
                "192.168.8.113,18899,TCP",
            )
            self.assertEqual(at_transport.queries, ["CLDSRVHOST1", "CLDSRVHOST1"])
            self.assertEqual(
                at_transport.writes,
                [
                    ("CLDSRVHOST1", "192.168.8.113,18899,TCP"),
                    ("INTPARA", "29,1"),
                ],
            )

        asyncio.run(_run())

    def test_async_apply_collector_changes_triggers_parameter_29_without_endpoint_change(self) -> None:
        async def _run() -> None:
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
            link_manager = _FakeLinkManager()
            transport = _CollectorManagementTransport()
            transport.reboot_required = "1"
            link_manager.transport = transport
            hub._link_manager = link_manager

            result = await hub.async_apply_collector_changes()

            self.assertEqual(result["status"], "applied")
            self.assertEqual(result["action"], "apply")
            self.assertEqual(result["current_endpoint"], "47.91.67.66,18899,TCP")
            self.assertEqual(result["reboot_required_before"], "1")
            self.assertEqual(hub._collector_runtime_values["collector_reboot_required"], "0")
            self.assertEqual(
                transport.requests,
                [
                    (2, b"\x15"),
                    (2, b"\x1e"),
                    (3, b"\x1d1"),
                ],
            )

        asyncio.run(_run())

    def test_async_reboot_collector_allows_virtual_bridge_without_reboot_feature(self) -> None:
        async def _run() -> None:
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
            link_manager = _FakeLinkManager()
            transport = _CollectorManagementTransport()
            link_manager.transport = transport
            link_manager.collector_info.collector_virtual_bridge = True
            link_manager.collector_info.collector_bridge_kind = "esp-collector"
            hub._link_manager = link_manager

            result = await hub.async_reboot_collector()

            self.assertEqual(result["status"], "reboot_triggered")
            self.assertEqual(result["action"], "reboot")
            self.assertEqual(
                transport.requests,
                [
                    (2, b"\x15"),
                    (2, b"\x1e"),
                    (3, b"\x1d1"),
                ],
            )

        asyncio.run(_run())

    def test_async_reboot_collector_allows_virtual_bridge_with_reboot_feature(self) -> None:
        async def _run() -> None:
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
            link_manager = _FakeLinkManager()
            transport = _CollectorManagementTransport()
            link_manager.transport = transport
            link_manager.collector_info.collector_virtual_bridge = True
            link_manager.collector_info.collector_bridge_kind = "esp-collector"
            hub._link_manager = link_manager

            result = await hub.async_reboot_collector()

            self.assertEqual(result["status"], "reboot_triggered")
            self.assertEqual(result["action"], "reboot")
            self.assertEqual(
                transport.requests,
                [
                    (2, b"\x15"),
                    (2, b"\x1e"),
                    (3, b"\x1d1"),
                ],
            )

        asyncio.run(_run())

    def test_async_rollback_collector_server_endpoint_uses_session_cached_previous_value(self) -> None:
        async def _run() -> None:
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
            link_manager = _FakeLinkManager()
            transport = _CollectorManagementTransport()
            link_manager.transport = transport
            hub._link_manager = link_manager

            await hub.async_set_collector_server_endpoint(
                "192.168.1.193,18899,TCP",
                apply_changes=False,
            )
            result = await hub.async_rollback_collector_server_endpoint(apply_changes=False)

            self.assertEqual(result["status"], "rollback_staged")
            self.assertEqual(result["rollback_source"], "session_cached_previous_endpoint")
            self.assertEqual(result["rollback_endpoint"], "47.91.67.66,18899,TCP")
            self.assertEqual(result["readback_endpoint"], "47.91.67.66,18899,TCP")
            self.assertEqual(hub._collector_runtime_values["collector_server_endpoint"], "47.91.67.66,18899,TCP")

        asyncio.run(_run())

    def test_async_rollback_collector_server_endpoint_preserves_host_only_previous_value(self) -> None:
        async def _run() -> None:
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
            link_manager = _FakeLinkManager()
            transport = _CollectorManagementTransport()
            transport.endpoint = "ess.eybond.com"
            link_manager.transport = transport
            hub._link_manager = link_manager

            await hub.async_set_collector_server_endpoint(
                "192.168.1.193,18899,TCP",
                apply_changes=False,
            )
            result = await hub.async_rollback_collector_server_endpoint(apply_changes=False)

            self.assertEqual(result["rollback_source"], "session_cached_previous_endpoint")
            self.assertEqual(result["rollback_endpoint"], "ess.eybond.com")
            self.assertEqual(result["readback_endpoint"], "ess.eybond.com")
            self.assertEqual(hub._collector_runtime_values["collector_server_endpoint"], "ess.eybond.com")

        asyncio.run(_run())

    def test_async_rollback_collector_server_endpoint_requires_cached_previous_value(self) -> None:
        async def _run() -> None:
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
            link_manager = _FakeLinkManager()
            transport = _CollectorManagementTransport()
            transport.server_endpoint = "192.168.1.10,18899,TCP"
            link_manager.transport = transport
            hub._link_manager = link_manager
            hub._collector_runtime_values["collector_server_endpoint"] = "192.168.1.10,18899,TCP"

            with self.assertRaisesRegex(RuntimeError, "collector_rollback_endpoint_unavailable"):
                await hub.async_rollback_collector_server_endpoint(apply_changes=False)

        asyncio.run(_run())



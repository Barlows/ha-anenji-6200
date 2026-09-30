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


class HubWriteBlockerTests(unittest.TestCase):
    def test_exception_code_3_returns_friendly_error_without_persistent_blocker(self) -> None:
        async def _run() -> None:
            profile = load_driver_profile("smg_modbus.json")
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
            hub._driver = _IllegalDataValueDriver()
            hub._inverter = DetectedInverter(
                driver_key="modbus_smg",
                protocol_family="modbus_smg",
                model_name="SMG 6200",
                serial_number="92632500000001",
                probe_target=ProbeTarget(devcode=0x0001, collector_addr=0x02, device_addr=0x01),
                capabilities=profile.capabilities,
                capability_groups=profile.groups,
                capability_presets=profile.presets,
            )

            with self.assertRaisesRegex(
                ValueError,
                r"illegal_data_value:max_ac_charge_current:.*Profile UI range:",
            ):
                await hub.async_write_capability("max_ac_charge_current", 0)

            self.assertEqual(hub._write_blockers, {})
            self.assertEqual(hub._driver.write_calls, 1)

        asyncio.run(_run())

    def test_async_write_capability_returns_when_readback_confirms_value(self) -> None:
        async def _run() -> None:
            profile = load_driver_profile("smg_modbus.json")
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
            hub._driver = _WriteConfirmedDriver()
            hub._inverter = DetectedInverter(
                driver_key="modbus_smg",
                protocol_family="modbus_smg",
                model_name="SMG 6200",
                serial_number="92632500000001",
                probe_target=ProbeTarget(devcode=0x0001, collector_addr=0x02, device_addr=0x01),
                capabilities=profile.capabilities,
                capability_groups=profile.groups,
                capability_presets=profile.presets,
            )

            written = await hub.async_write_capability("max_ac_charge_current", 30)

            self.assertEqual(written, 30)
            self.assertEqual(hub._driver.write_calls, 1)
            self.assertEqual(hub._driver.read_calls, 2)

        asyncio.run(_run())

    def test_async_write_capability_confirms_delayed_readback_without_resending(self) -> None:
        async def _run() -> None:
            profile = load_driver_profile("smg_modbus.json")
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
            hub._driver = _WriteDelayedConfirmationDriver()
            hub._inverter = DetectedInverter(
                driver_key="modbus_smg",
                protocol_family="modbus_smg",
                model_name="SMG 6200",
                serial_number="92632500000001",
                probe_target=ProbeTarget(devcode=0x0001, collector_addr=0x02, device_addr=0x01),
                capabilities=profile.capabilities,
                capability_groups=profile.groups,
                capability_presets=profile.presets,
            )

            written = await hub.async_write_capability("max_ac_charge_current", 30)

            self.assertEqual(written, 30)
            self.assertEqual(hub._driver.write_calls, 1)
            self.assertEqual(hub._driver.read_calls, 3)

        asyncio.run(_run())

    def test_async_write_capability_raises_when_readback_stays_old(self) -> None:
        async def _run() -> None:
            profile = load_driver_profile("smg_modbus.json")
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
            hub._driver = _WriteUnconfirmedDriver()
            hub._inverter = DetectedInverter(
                driver_key="modbus_smg",
                protocol_family="modbus_smg",
                model_name="SMG 6200",
                serial_number="92632500000001",
                probe_target=ProbeTarget(devcode=0x0001, collector_addr=0x02, device_addr=0x01),
                capabilities=profile.capabilities,
                capability_groups=profile.groups,
                capability_presets=profile.presets,
            )

            with self.assertRaisesRegex(
                RuntimeError,
                r"write_not_confirmed:max_ac_charge_current:Command accepted, but 'Max AC Charge Current' did not confirm by readback.",
            ):
                await hub.async_write_capability("max_ac_charge_current", 30)

            self.assertEqual(hub._driver.write_calls, 1)
            self.assertEqual(hub._driver.read_calls, 3)

        asyncio.run(_run())

    def test_async_write_capability_allows_write_attempt_while_soft_gate_is_active(self) -> None:
        async def _run() -> None:
            profile = load_driver_profile("smg_modbus.json")
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
            hub._driver = _WriteConfirmedWhileChargingDriver()
            hub._inverter = DetectedInverter(
                driver_key="modbus_smg",
                protocol_family="modbus_smg",
                model_name="SMG 6200",
                serial_number="92632500000001",
                probe_target=ProbeTarget(devcode=0x0001, collector_addr=0x02, device_addr=0x01),
                capabilities=profile.capabilities,
                capability_groups=profile.groups,
                capability_presets=profile.presets,
            )

            written = await hub.async_write_capability("max_ac_charge_current", 30)

            self.assertEqual(written, 30)
            self.assertEqual(hub._driver.write_calls, 1)
            self.assertEqual(hub._driver.read_calls, 2)

        asyncio.run(_run())

    def test_async_refresh_repeated_payload_timeout_does_not_enter_backoff(self) -> None:
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

            first = await hub.async_refresh(poll_interval=3.0)
            second = await hub.async_refresh(poll_interval=3.0)

            self.assertTrue(first.connected)
            self.assertTrue(second.connected)
            self.assertEqual(second.last_error, "request_timeout")
            self.assertEqual(hub._driver.calls, 4)
            self.assertEqual(hub._link_manager.reset_calls, 0)
            self.assertEqual(second.values["runtime_recovery_streak"], 0)
            self.assertEqual(second.values["runtime_backoff_seconds"], 0)

        asyncio.run(_run())

    def test_async_refresh_marks_snapshot_disconnected_on_collector_disconnect(self) -> None:
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
            hub._driver = _DisconnectedDriver()
            hub._inverter = DetectedInverter(
                driver_key="modbus_smg",
                protocol_family="modbus_smg",
                model_name="SMG 6200",
                serial_number="92632500000001",
                probe_target=ProbeTarget(devcode=0x0001, collector_addr=0x02, device_addr=0x01),
            )

            snapshot = await hub.async_refresh(poll_interval=3.0)

            self.assertFalse(snapshot.connected)
            self.assertEqual(snapshot.last_error, "collector_not_connected")
            self.assertEqual(snapshot.values["runtime_recovery_streak"], 1)
            self.assertEqual(hub._driver.calls, 2)

        asyncio.run(_run())

    def test_async_refresh_marks_snapshot_disconnected_on_heartbeat_timeout(self) -> None:
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
            hub._link_manager = _FakeLinkManager(heartbeat_result=False)

            snapshot = await hub.async_refresh(poll_interval=3.0)

            self.assertFalse(snapshot.connected)
            self.assertEqual(snapshot.last_error, "collector_heartbeat_timeout")
            self.assertEqual(hub._link_manager.reset_calls, 1)
            self.assertEqual(snapshot.values["runtime_reconnect_count"], 1)
            self.assertEqual(snapshot.values["runtime_recovery_streak"], 1)

        asyncio.run(_run())

    def test_async_refresh_keeps_collector_live_when_unbound_heartbeat_is_missing(self) -> None:
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
            link = _FakeLinkManager(heartbeat_result=False)
            link.transport = _CollectorQueryTransport(
                {
                    (2, b"\x06"): b"\x00\x06esp-collector/0.1.5/ESP32",
                }
            )
            hub._link_manager = link

            snapshot = await hub.async_refresh(poll_interval=3.0)

            self.assertTrue(snapshot.connected)
            self.assertEqual(snapshot.last_error, "inverter_heartbeat_missing")
            self.assertEqual(snapshot.values["runtime_driver_state"], "driver_unbound")
            self.assertEqual(hub._link_manager.reset_calls, 0)
            self.assertTrue(snapshot.values["collector_virtual_bridge"])

        asyncio.run(_run())

    def test_outage_cache_clear_runs_once_per_outage(self) -> None:
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
        clears: list[int] = []
        original = hub._clear_collector_runtime_value_caches
        hub._clear_collector_runtime_value_caches = lambda: (clears.append(1), original())[1]

        hub._clear_collector_value_caches_for_outage()
        hub._clear_collector_value_caches_for_outage()
        self.assertEqual(len(clears), 1)

        hub._record_refresh_success()
        hub._clear_collector_value_caches_for_outage()
        self.assertEqual(len(clears), 2)

    def test_empty_at_metadata_result_respects_attempt_cadence(self) -> None:
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

            class _DeadAtTransport:
                connected = True

                def __init__(self) -> None:
                    self.queries = 0

                async def async_query(self, command: str):
                    self.queries += 1
                    raise asyncio.TimeoutError()

            at_transport = _DeadAtTransport()
            link = _FakeLinkManager()
            link.collector_at_transport = at_transport
            hub._link_manager = link

            await hub._async_read_collector_runtime_values(poll_interval=10.0)
            first_attempt_queries = at_transport.queries
            self.assertGreaterEqual(first_attempt_queries, 1)

            # Second read within the refresh interval: the dead AT link is
            # NOT re-swept just because the previous sweep yielded nothing.
            await hub._async_read_collector_runtime_values(poll_interval=10.0)
            self.assertEqual(at_transport.queries, first_attempt_queries)

        asyncio.run(_run())

    def test_at_text_metadata_bootstrap_reads_bridge_hardware_version(self) -> None:
        async def _run() -> None:
            hub = EybondHub(
                connection=EybondConnectionSpec(
                    server_ip="192.168.1.10",
                    collector_ip="192.168.1.14",
                    tcp_port=18899,
                    udp_port=58899,
                    discovery_target="192.168.1.255",
                    discovery_interval=30,
                    heartbeat_interval=60,
                    request_timeout=5.0,
                ),
            )

            class _AtTextFcBootstrapTransport:
                connected = True

                def __init__(self) -> None:
                    self.fc_requests: list[tuple[int, bytes]] = []

                async def async_query_bridge_hardware_version(self):
                    self.fc_requests.append((2, b"\x06"))
                    return (None, b"\x00\x06esp-collector/0.1.8/ESP8266")

                async def async_query(self, command: str):
                    raise asyncio.TimeoutError()

            at_transport = _AtTextFcBootstrapTransport()
            link = _FakeLinkManager()
            link.transport = object()
            link.collector_at_transport = at_transport
            hub._link_manager = link

            values = await hub._async_read_collector_runtime_values(poll_interval=10.0)

            self.assertEqual(at_transport.fc_requests, [(2, b"\x06")])
            self.assertEqual(
                values["collector_hardware_version"],
                "esp-collector/0.1.8/ESP8266",
            )
            snapshot = hub._build_snapshot(extra_values=values)
            self.assertTrue(snapshot.collector.collector_virtual_bridge)
            self.assertEqual(snapshot.collector.collector_bridge_version, "0.1.8")

        asyncio.run(_run())

    def test_dead_at_metadata_channel_is_learned_and_skipped(self) -> None:
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

            # Dead-channel truth (Phase-4 semantics): a channel becomes dead when
            # it DELIVERS commands over a live link yet answers with no metadata
            # (blank values), NOT when it times out (that is a transport error).
            class _EmptyAnsweringAtTransport:
                connected = True

                def __init__(self) -> None:
                    self.sweeps = 0
                    self._pending = False

                async def async_query(self, command: str):
                    if not self._pending:
                        self.sweeps += 1
                        self._pending = True
                    if command == "INTPARA49":  # last non-overlapping command
                        self._pending = False
                    return CollectorAtResponse(command=command, value="", raw=f"AT+{command}:")

            at_transport = _EmptyAnsweringAtTransport()
            link = _FakeLinkManager()
            link.collector_at_transport = at_transport
            link.transport = _CollectorQueryTransport(
                {(2, b"\x06"): b"\x00\x06esp-collector/0.1.5/ESP32"}
            )
            hub._link_manager = link

            for _ in range(4):
                # Force each attempt through the cadence gate.
                hub._collector_at_runtime_last_attempt_monotonic = -1000.0
                hub._collector_runtime_last_refresh_monotonic = -1000.0
                await hub._async_read_collector_runtime_values(poll_interval=10.0)

            learned_sweeps = at_transport.sweeps
            self.assertGreaterEqual(learned_sweeps, 4)

            # Dead: the channel verdict blocks the sweep entirely, even with the
            # cadence forced open.
            hub._collector_at_runtime_last_attempt_monotonic = -1000.0
            hub._collector_runtime_last_refresh_monotonic = -1000.0
            await hub._async_read_collector_runtime_values(poll_interval=10.0)
            self.assertEqual(at_transport.sweeps, learned_sweeps)

            # The re-check path clears the verdict and probes again.
            hub.clear_unsupported_command_cache()
            hub._collector_at_runtime_last_attempt_monotonic = -1000.0
            hub._collector_runtime_last_refresh_monotonic = -1000.0
            await hub._async_read_collector_runtime_values(poll_interval=10.0)
            self.assertEqual(at_transport.sweeps, learned_sweeps + 1)

        asyncio.run(_run())

    def test_persistent_unsupported_commands_survive_runtime_state_reset(self) -> None:
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
        from custom_components.eybond_local.drivers.command_support import (
            command_skipped_as_unsupported,
        )

        hub.set_persistent_unsupported_commands(("QPIWS", "QET"))
        self.assertTrue(
            command_skipped_as_unsupported(hub._runtime_read_state, "QPIWS")
        )

        # A reconnect clears the session state but must re-seed device facts.
        hub._reset_runtime_read_state()
        self.assertTrue(
            command_skipped_as_unsupported(hub._runtime_read_state, "QET")
        )

        hub.clear_unsupported_command_cache()
        hub._reset_runtime_read_state()
        self.assertFalse(
            command_skipped_as_unsupported(hub._runtime_read_state, "QPIWS")
        )

    def _metadata_hub(self) -> "EybondHub":
        return EybondHub(
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

    def test_persistent_unsupported_commands_filter_out_metadata_channels(self) -> None:
        from custom_components.eybond_local.drivers.command_support import (
            command_skipped_as_unsupported,
        )

        hub = self._metadata_hub()
        hub.set_persistent_unsupported_commands(("QPIWS", "collector:at_metadata"))
        # The driver negative cache gets the real command but NOT the metadata key.
        self.assertTrue(command_skipped_as_unsupported(hub._runtime_read_state, "QPIWS"))
        self.assertFalse(
            command_skipped_as_unsupported(hub._runtime_read_state, "collector:at_metadata")
        )

    def test_metadata_dead_channels_seed_and_revive(self) -> None:
        hub = self._metadata_hub()
        hub.set_persistent_metadata_dead_channels(("collector:at_metadata",))
        self.assertEqual(
            hub.collector_metadata_dead_channels(), ("collector:at_metadata",)
        )
        self.assertTrue(hub._collector_metadata_service.at_channel_disabled())
        # The re-check action revives the metadata channel (separate store).
        hub.clear_unsupported_command_cache()
        self.assertEqual(hub.collector_metadata_dead_channels(), ())
        self.assertFalse(hub._collector_metadata_service.at_channel_disabled())

    def test_async_refresh_keeps_bound_inverter_offline_when_framed_link_is_missing(self) -> None:
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
            at_transport = _CollectorAtQueryTransport({"ATVER": "2.05"}, connected=False)
            link = _CollectorOnlyLinkManager(at_transport)
            hub._link_manager = link
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

            snapshot = await hub.async_refresh(poll_interval=3.0)

            self.assertFalse(snapshot.connected)
            self.assertEqual(snapshot.last_error, "waiting_for_collector")
            self.assertEqual(snapshot.values["runtime_driver_state"], "collector_offline")
            self.assertNotIn("collector_udp_reply", snapshot.values)
            self.assertNotIn("collector_udp_reply_from", snapshot.values)
            self.assertEqual(link.collector_info.last_udp_reply_from, "")

        asyncio.run(_run())

    def test_async_refresh_recovers_after_stale_heartbeat_reset(self) -> None:
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
            hub._link_manager = _StaleHeartbeatThenRecoveredLinkManager()
            hub._driver = _RuntimeValuesDriver()
            hub._inverter = DetectedInverter(
                driver_key="modbus_smg",
                protocol_family="modbus_smg",
                model_name="SMG 6200",
                serial_number="92632500000001",
                probe_target=ProbeTarget(devcode=0x0001, collector_addr=0x02, device_addr=0x01),
            )

            snapshot = await hub.async_refresh(poll_interval=3.0)

            self.assertTrue(snapshot.connected)
            self.assertIsNone(snapshot.last_error)
            self.assertEqual(snapshot.runtime_value("output_power"), 420)
            self.assertNotIn("output_power", snapshot.values)
            self.assertEqual(snapshot.values["runtime_reconnect_count"], 1)
            self.assertEqual(snapshot.values["runtime_recovery_streak"], 0)

        asyncio.run(_run())

    def test_async_refresh_retries_request_timeout_without_reconnect(self) -> None:
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
            hub._driver = _TimeoutThenSuccessDriver()
            hub._inverter = DetectedInverter(
                driver_key="modbus_smg",
                protocol_family="modbus_smg",
                model_name="SMG 6200",
                serial_number="92632500000001",
                probe_target=ProbeTarget(devcode=0x0001, collector_addr=0x02, device_addr=0x01),
            )

            snapshot = await hub.async_refresh(poll_interval=3.0)

            self.assertTrue(snapshot.connected)
            self.assertIsNone(snapshot.last_error)
            self.assertEqual(snapshot.runtime_value("output_power"), 420)
            self.assertEqual(snapshot.runtime_value("battery_power"), -180)
            self.assertNotIn("output_power", snapshot.values)
            self.assertNotIn("battery_power", snapshot.values)
            self.assertEqual(snapshot.values["runtime_recovery_streak"], 0)
            self.assertEqual(snapshot.values["runtime_reconnect_count"], 0)
            self.assertEqual(hub._link_manager.reset_calls, 0)

        asyncio.run(_run())



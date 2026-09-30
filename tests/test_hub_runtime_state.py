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


class RuntimeStateMachineTests(unittest.TestCase):
    """Runtime state-machine hardening: explicit states + sticky inverter identity."""

    _MODEL = "SMG 6200"
    # Pure-digit synthetic serials (no leading letter -> not PN-shaped identifiers).
    _SERIAL = "92632500000001"
    _OTHER_SERIAL = "92632599999999"

    def _hub(self, *, full_scan: bool = False) -> EybondHub:
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
            driver_detection_strategy=(
                DRIVER_DETECTION_FULL_SCAN if full_scan else "first_match"
            ),
        )
        hub._link_manager = _FakeLinkManager()
        hub.set_callback_ownership(None, "entry-runtime-state-machine")
        # The UART-sweep authority keys on this attribute (detection.py reads
        # `_collector_operation_entry_id`). Production sets it during
        # ownership handover; without it the hub keys on "" and an acquire
        # against "entry-runtime-state-machine" targets a different owner
        # slot than the sweep actually holds.
        hub._collector_operation_entry_id = "entry-runtime-state-machine"
        return hub

    def _inverter(
        self,
        *,
        serial: str | None = None,
        model: str | None = None,
        driver_key: str = "modbus_smg",
        detection_status: str = "",
    ) -> DetectedInverter:
        details: dict[str, object] = {}
        if detection_status:
            details["runtime_detection_status"] = detection_status
        return DetectedInverter(
            driver_key=driver_key,
            protocol_family=driver_key,
            model_name=model or self._MODEL,
            serial_number=serial or self._SERIAL,
            probe_target=ProbeTarget(devcode=0x0001, collector_addr=0x02, device_addr=0x01),
            details=details,
        )

    def _fake_detection(self, inverter: DetectedInverter, driver: object):
        async def _detect(_transport, *, driver_hint=""):
            return SimpleNamespace(
                driver=driver,
                inverter=inverter,
                match=SimpleNamespace(confidence="high"),
            )

        return _detect

    def _candidate_context(
        self,
        *,
        driver_key: str,
        protocol_family: str,
        model: str,
    ) -> DetectedDriverContext:
        inverter = self._inverter(
            driver_key=driver_key,
            model=model,
            serial=self._SERIAL,
        )
        inverter.protocol_family = protocol_family
        return DetectedDriverContext(
            driver=SimpleNamespace(key=driver_key),
            inverter=inverter,
            match=DriverMatch(
                driver_key=driver_key,
                protocol_family=protocol_family,
                model_name=model,
                serial_number=self._SERIAL,
                probe_target=inverter.probe_target,
            ),
        )

    def test_default_detection_stops_at_first_confirmed_match(self) -> None:
        async def _run() -> None:
            hub = self._hub()
            context = self._candidate_context(
                driver_key="smartess_local",
                protocol_family="0925",
                model="Hybrid 5K",
            )
            with (
                patch(
                    "custom_components.eybond_local.runtime.hub.detection.async_detect_inverter",
                    return_value=context,
                ) as first_match,
                patch(
                    "custom_components.eybond_local.runtime.hub.detection.async_detect_inverter_candidates",
                    side_effect=AssertionError("full scan must not run"),
                ),
            ):
                result = await hub._async_detect_driver()

            self.assertEqual(result, "")
            first_match.assert_awaited_once()
            self.assertIs(hub._driver, context.driver)
            self.assertEqual(hub.inverter_protocol_candidates, ())

        asyncio.run(_run())

    def test_auto_detection_keeps_multi_protocol_result_unbound(self) -> None:
        async def _run() -> None:
            hub = self._hub(full_scan=True)
            hub._link_manager.owned_session_generation = 7
            scan_calls = 0
            scan = DriverCandidateScan(
                candidates=(
                    self._candidate_context(
                        driver_key="smartess_local",
                        protocol_family="0925",
                        model="Hybrid 5K",
                    ),
                    self._candidate_context(
                        driver_key="pi30",
                        protocol_family="pi30",
                        model="Hybrid 5K",
                    ),
                ),
                probe_log=(
                    {
                        "driver": "smartess_local",
                        "elapsed_ms": 800,
                        "outcome": "matched",
                        "saw_response": True,
                    },
                    {
                        "driver": "pi30",
                        "elapsed_ms": 900,
                        "outcome": "matched",
                        "saw_response": True,
                    },
                ),
            )

            async def _scan(*_args, **_kwargs):
                nonlocal scan_calls
                scan_calls += 1
                return scan

            with patch(
                "custom_components.eybond_local.runtime.hub.detection.async_detect_inverter_candidates",
                side_effect=_scan,
            ):
                first = await hub._async_detect_driver()
                second = await hub._async_detect_driver()

            self.assertEqual(first, "inverter_protocol_ambiguous")
            self.assertEqual(second, "inverter_protocol_ambiguous")
            self.assertEqual(scan_calls, 1)
            self.assertIsNone(hub._driver)
            self.assertIsNone(hub._inverter)
            self.assertEqual(
                [item.driver_key for item in hub.inverter_protocol_candidates],
                ["smartess_local", "pi30"],
            )
            snapshot = hub._build_snapshot(last_error=first)
            self.assertEqual(snapshot.values["runtime_inverter_state"], "ambiguous")
            self.assertEqual(snapshot.values["runtime_inverter_candidate_count"], 2)
            self.assertEqual(snapshot.values["runtime_inverter_probe_total_ms"], 1700)

        asyncio.run(_run())

    def test_auto_detection_resolves_declared_exact_catalog_overlap(self) -> None:
        async def _run() -> None:
            hub = self._hub(full_scan=True)
            smg = self._candidate_context(
                driver_key="modbus_smg",
                protocol_family="modbus_smg",
                model="False-positive SMG surface",
            )
            target = smg.inverter.probe_target
            inverter = DetectedInverter(
                driver_key="modbus_catalog",
                protocol_family="modbus_catalog",
                model_name="Deye-Compatible Three-Phase Hybrid 8 kW (Modbus)",
                serial_number="",
                probe_target=target,
                variant_key="deye_3ph_high_80kw",
                profile_name="modbus_catalog/deye_3ph_high_80kw.json",
                register_schema_name="deye_3ph_high_80kw/base.json",
                details={
                    "catalog_detection": {
                        "resolution": "exact",
                        "surface_key": "deye_3ph_high_80kw_untested",
                        "confidence": "high",
                    }
                },
            )
            catalog = DetectedDriverContext(
                driver=SimpleNamespace(key="modbus_catalog"),
                inverter=inverter,
                match=DriverMatch(
                    driver_key="modbus_catalog",
                    protocol_family="modbus_catalog",
                    model_name=inverter.model_name,
                    serial_number="",
                    probe_target=target,
                    variant_key=inverter.variant_key,
                ),
            )

            with patch(
                "custom_components.eybond_local.runtime.hub.detection."
                "async_detect_inverter_candidates",
                return_value=DriverCandidateScan(candidates=(smg, catalog)),
            ):
                result = await hub._async_detect_driver()

            self.assertEqual(result, "")
            self.assertIs(hub._driver, catalog.driver)
            self.assertIs(hub._inverter, catalog.inverter)
            self.assertEqual(hub.inverter_protocol_candidates, ())
            self.assertEqual(
                hub._inverter.details["driver_candidate_selection"],
                {
                    "kind": "catalog_protocol_precedence",
                    "catalog_entry_key": "deye_3ph_high_80kw",
                    "superseded_protocols": ["modbus_smg"],
                },
            )

        asyncio.run(_run())

    def test_auto_detection_binds_the_only_runtime_candidate(self) -> None:
        async def _run() -> None:
            hub = self._hub(full_scan=True)
            context = self._candidate_context(
                driver_key="pi30",
                protocol_family="pi30",
                model="Hybrid 5K",
            )
            with patch(
                "custom_components.eybond_local.runtime.hub.detection.async_detect_inverter_candidates",
                return_value=DriverCandidateScan(candidates=(context,)),
            ):
                result = await hub._async_detect_driver()

            self.assertEqual(result, "")
            self.assertIs(hub._driver, context.driver)
            self.assertIs(hub._inverter, context.inverter)
            self.assertEqual(hub.inverter_protocol_candidates, ())

        asyncio.run(_run())

    def test_runtime_probe_log_is_sanitized_and_published_for_support(self) -> None:
        async def _run() -> None:
            hub = self._hub(full_scan=True)
            hub._link_manager.owned_session_generation = 7
            context = self._candidate_context(
                driver_key="pi30",
                protocol_family="pi30",
                model="Hybrid 5K",
            )
            # A raw details log must never bypass the runtime diagnostics
            # projection, even if a driver supplied it.
            context.inverter.details["probe_log"] = [
                {"outcome": "error:route 192.0.2.10"}
            ]
            scan = DriverCandidateScan(
                candidates=(context,),
                budget_exhausted=True,
                probe_log=(
                    {
                        "driver": "modbus_smg",
                        "elapsed_ms": 45000,
                        "outcome": "error:route 192.0.2.10 refused",
                        "saw_response": False,
                    },
                    {
                        "driver": "pi30",
                        "elapsed_ms": 1234,
                        "outcome": "matched",
                        "saw_response": True,
                        "routes": [
                            {
                                "family": "eybond",
                                "devcode": 0x0994,
                                "collector_addr": 1,
                                "attempts": 4,
                                "responses": 4,
                                "endpoint": "192.0.2.10",
                            },
                            {
                                "family": "eybond",
                                "devcode": True,
                                "collector_addr": 1,
                                "attempts": 1,
                                "responses": 1,
                            },
                        ],
                    },
                ),
            )

            with patch(
                "custom_components.eybond_local.runtime.hub.detection.async_detect_inverter_candidates",
                return_value=scan,
            ):
                self.assertEqual(await hub._async_detect_driver(), "")

            snapshot = hub._build_snapshot()
            self.assertNotIn("probe_log", context.inverter.details)
            self.assertNotIn("probe_log", snapshot.values)
            self.assertEqual(
                snapshot.values["runtime_inverter_probe_log"],
                [
                    {
                        "driver": "modbus_smg",
                        "elapsed_ms": 45000,
                        "outcome": "error",
                        "saw_response": False,
                    },
                    {
                        "driver": "pi30",
                        "elapsed_ms": 1234,
                        "outcome": "matched",
                        "saw_response": True,
                        "routes": [
                            {
                                "family": "eybond",
                                "devcode": 0x0994,
                                "collector_addr": 1,
                                "attempts": 4,
                                "responses": 4,
                            }
                        ],
                    },
                ],
            )
            self.assertEqual(
                snapshot.values["runtime_inverter_probe_total_ms"], 46234
            )
            self.assertTrue(
                snapshot.values["runtime_inverter_probe_budget_exhausted"]
            )
            self.assertTrue(
                snapshot.values["runtime_inverter_probe_current_session"]
            )
            self.assertNotIn("192.0.2.10", str(snapshot.values))

            hub._link_manager.owned_session_generation = 8
            self.assertFalse(
                hub._build_snapshot().values[
                    "runtime_inverter_probe_current_session"
                ]
            )

        asyncio.run(_run())

    def test_failed_runtime_sweep_keeps_probe_log_in_snapshot(self) -> None:
        async def _run() -> None:
            hub = self._hub(full_scan=True)
            failure = DriverSweepNoMatch(
                "pi30:probe_timeout",
                silent=False,
                probe_log=(
                    {
                        "driver": "modbus_smg",
                        "elapsed_ms": 45000,
                        "outcome": "no_match",
                        "saw_response": True,
                        "diagnostic": {
                            "kind": "catalog_identity",
                            "status": "partial_identity",
                            "protocol": "modbus_smg",
                            "model_code": 0x4321,
                            "executed_actions": ["modbus_smg.identity.171"],
                            "failed_actions": ["modbus_smg.identity.184"],
                            "action_failures": [
                                {
                                    "action": "modbus_smg.identity.184",
                                    "reason": "modbus_exception",
                                    "exception_code": 2,
                                }
                            ],
                            "endpoint": "must-not-survive",
                        },
                    },
                    {
                        "driver": "pi30",
                        "elapsed_ms": 45000,
                        "outcome": "probe_timeout",
                        "saw_response": False,
                    },
                ),
            )
            with patch(
                "custom_components.eybond_local.runtime.hub.detection.async_detect_inverter_candidates",
                side_effect=failure,
            ):
                result = await hub._async_detect_driver()

            self.assertEqual(result, "pi30:probe_timeout")
            snapshot = hub._build_snapshot(last_error=result)
            self.assertEqual(
                snapshot.values["runtime_inverter_probe_total_ms"], 90000
            )
            self.assertEqual(
                [
                    entry["outcome"]
                    for entry in snapshot.values["runtime_inverter_probe_log"]
                ],
                ["no_match", "probe_timeout"],
            )
            diagnostic = snapshot.values["runtime_inverter_probe_log"][0][
                "diagnostic"
            ]
            self.assertEqual(diagnostic["model_code"], 0x4321)
            self.assertNotIn("endpoint", diagnostic)

            hub._link_manager.owned_session_generation = 1
            stale_snapshot = hub._build_snapshot()
            self.assertFalse(
                stale_snapshot.values["runtime_inverter_probe_current_session"]
            )
            self.assertEqual(
                stale_snapshot.values["runtime_inverter_probe_log"][0][
                    "diagnostic"
                ]["model_code"],
                0x4321,
            )

        asyncio.run(_run())

    def test_full_scan_silence_adopts_runtime_uart_sweep_match(self) -> None:
        async def _run() -> None:
            hub = self._hub(full_scan=True)
            hub._link_manager.owned_session_generation = 7
            context = self._candidate_context(
                driver_key="pi30",
                protocol_family="pi30",
                model="Hybrid 5K",
            )
            failure = DriverSweepNoMatch(
                "pi30:probe_timeout",
                silent=True,
                probe_log=(
                    {
                        "driver": "pi30",
                        "elapsed_ms": 45000,
                        "outcome": "probe_timeout",
                        "saw_response": False,
                    },
                ),
            )
            recovered = DriverCandidateScan(candidates=(context,))

            with (
                patch(
                    "custom_components.eybond_local.runtime.hub.detection."
                    "async_detect_inverter_candidates",
                    side_effect=failure,
                ),
                patch.object(
                    hub,
                    "_async_attempt_runtime_link_baud_sweep",
                    new=AsyncMock(return_value=recovered),
                ) as baud_sweep,
            ):
                result = await hub._async_detect_driver()

            self.assertEqual(result, "")
            baud_sweep.assert_awaited_once_with(detection_generation=7)
            self.assertIs(hub._driver, context.driver)
            self.assertIs(hub._inverter, context.inverter)

        asyncio.run(_run())

    def test_first_match_silence_never_changes_runtime_uart(self) -> None:
        async def _run() -> None:
            hub = self._hub(full_scan=False)
            failure = DriverSweepNoMatch(
                "pi30:probe_timeout",
                silent=True,
            )
            with (
                patch(
                    "custom_components.eybond_local.runtime.hub.detection."
                    "async_detect_inverter",
                    side_effect=failure,
                ),
                patch.object(
                    hub,
                    "_async_attempt_runtime_link_baud_sweep",
                    new=AsyncMock(
                        side_effect=AssertionError(
                            "first-match detection must not change UART"
                        )
                    ),
                ),
            ):
                result = await hub._async_detect_driver()

            self.assertEqual(result, "pi30:probe_timeout")

        asyncio.run(_run())

    def test_runtime_uart_sweep_is_once_per_owned_esp_session(self) -> None:
        async def _run() -> None:
            hub = self._hub(full_scan=True)
            hub._link_manager.owned_session_generation = 7
            hub._link_manager.transport = SimpleNamespace(
                async_send_collector=AsyncMock()
            )
            hub._collector_metadata_service.framed_values = {
                "collector_hardware_version": "esp-collector/0.1.5/ESP32"
            }
            context = self._candidate_context(
                driver_key="pi30",
                protocol_family="pi30",
                model="Hybrid 5K",
            )
            recovered = DriverCandidateScan(candidates=(context,))
            channel = AsyncMock()
            channel.async_read_current_baud.return_value = 2400
            channel.async_set_baud.return_value = True

            with (
                patch(
                    "custom_components.eybond_local.runtime.hub.detection."
                    "RuntimeLinkBaudChannel",
                    return_value=channel,
                ),
                patch(
                    "custom_components.eybond_local.runtime.hub.detection."
                    "catalog_link_baud_hints",
                    return_value=(2400, 9600),
                ),
                patch(
                    "custom_components.eybond_local.runtime.hub.detection."
                    "driver_keys_for_link_baud",
                    return_value=("pi30",),
                ),
                patch(
                    "custom_components.eybond_local.runtime.hub.detection."
                    "async_detect_inverter_candidates",
                    return_value=recovered,
                ) as detect,
            ):
                first = await hub._async_attempt_runtime_link_baud_sweep(
                    detection_generation=7
                )
                second = await hub._async_attempt_runtime_link_baud_sweep(
                    detection_generation=7
                )

            self.assertIs(first, recovered)
            self.assertIsNone(second)
            channel.async_set_baud.assert_awaited_once_with(9600)
            detect.assert_awaited_once()

        asyncio.run(_run())

    def test_runtime_uart_sweep_skips_busy_authority_without_consuming_session(self) -> None:
        async def _run() -> None:
            hub = self._hub(full_scan=True)
            hub._link_manager.owned_session_generation = 7
            hub._link_manager.transport = SimpleNamespace(
                async_send_collector=AsyncMock()
            )
            hub._collector_metadata_service.framed_values = {
                "collector_hardware_version": "esp-collector/0.1.5/ESP32"
            }
            held = COLLECTOR_ENDPOINT_OPERATION_AUTHORITY.acquire(
                "entry-runtime-state-machine",
                OPERATION_COLLECTOR_SYSTEM_ACTION,
            )
            self.assertTrue(held.acquired)
            try:
                with patch(
                    "custom_components.eybond_local.runtime.hub.detection."
                    "RuntimeLinkBaudChannel",
                ) as channel_type:
                    result = await hub._async_attempt_runtime_link_baud_sweep(
                        detection_generation=7
                    )
                self.assertIsNone(result)
                self.assertEqual(hub._link_baud_sweep_generation, -1)
                channel_type.assert_not_called()
            finally:
                self.assertTrue(
                    COLLECTOR_ENDPOINT_OPERATION_AUTHORITY.release(
                        "entry-runtime-state-machine",
                        held.token,
                    )
                )

        asyncio.run(_run())

    def test_runtime_uart_sweep_holds_and_releases_shared_authority(self) -> None:
        async def _run() -> None:
            hub = self._hub(full_scan=True)
            hub._link_manager.owned_session_generation = 7
            hub._link_manager.transport = SimpleNamespace(
                async_send_collector=AsyncMock()
            )
            hub._collector_metadata_service.framed_values = {
                "collector_hardware_version": "esp-collector/0.1.5/ESP32"
            }
            entered = asyncio.Event()
            finish = asyncio.Event()

            async def blocked_sweep(**_kwargs):
                entered.set()
                await finish.wait()
                return SimpleNamespace(matched=False)

            with (
                patch.object(
                    hub,
                    "_collector_management_adapter",
                    return_value=object(),
                ),
                patch(
                    "custom_components.eybond_local.runtime.hub.detection."
                    "async_run_link_baud_sweep",
                    side_effect=blocked_sweep,
                ),
            ):
                task = asyncio.create_task(
                    hub._async_attempt_runtime_link_baud_sweep(
                        detection_generation=7
                    )
                )
                # Bounded: an unbounded wait turns any precondition failure
                # (stale process-global state from another module, a changed
                # guard) into a suite-wide hang instead of a clear failure.
                await asyncio.wait_for(entered.wait(), timeout=5.0)
                self.assertEqual(
                    COLLECTOR_ENDPOINT_OPERATION_AUTHORITY.active_operation(
                        "entry-runtime-state-machine"
                    ),
                    OPERATION_RUNTIME_LINK_BAUD_SWEEP,
                )
                competing = COLLECTOR_ENDPOINT_OPERATION_AUTHORITY.acquire(
                    "entry-runtime-state-machine",
                    OPERATION_COLLECTOR_SYSTEM_ACTION,
                )
                self.assertFalse(competing.acquired)
                self.assertEqual(
                    competing.busy_operation,
                    OPERATION_RUNTIME_LINK_BAUD_SWEEP,
                )
                finish.set()
                self.assertIsNone(await task)

            self.assertEqual(
                COLLECTOR_ENDPOINT_OPERATION_AUTHORITY.active_operation(
                    "entry-runtime-state-machine"
                ),
                "",
            )

        asyncio.run(_run())

    def test_runtime_uart_sweep_releases_authority_when_cancelled(self) -> None:
        async def _run() -> None:
            hub = self._hub(full_scan=True)
            hub._link_manager.owned_session_generation = 7
            hub._link_manager.transport = SimpleNamespace(
                async_send_collector=AsyncMock()
            )
            hub._collector_metadata_service.framed_values = {
                "collector_hardware_version": "esp-collector/0.1.5/ESP32"
            }
            with (
                patch.object(
                    hub,
                    "_collector_management_adapter",
                    return_value=object(),
                ),
                patch(
                    "custom_components.eybond_local.runtime.hub.detection."
                    "async_run_link_baud_sweep",
                    new=AsyncMock(side_effect=asyncio.CancelledError),
                ),
            ):
                with self.assertRaises(asyncio.CancelledError):
                    await hub._async_attempt_runtime_link_baud_sweep(
                        detection_generation=7
                    )

            self.assertEqual(
                COLLECTOR_ENDPOINT_OPERATION_AUTHORITY.active_operation(
                    "entry-runtime-state-machine"
                ),
                "",
            )

        asyncio.run(_run())

    def test_runtime_uart_sweep_never_writes_factory_collector(self) -> None:
        asyncio.run(
            self._assert_runtime_uart_hardware_is_read_only(
                "Eybond Wi-Fi DTU V2.4"
            )
        )

    def test_runtime_uart_sweep_never_writes_bk72xx_bridge(self) -> None:
        asyncio.run(
            self._assert_runtime_uart_hardware_is_read_only(
                "esp-collector/0.1.5/BK72xx/RTL87xx"
            )
        )

    async def _assert_runtime_uart_hardware_is_read_only(
        self,
        hardware_text: str,
    ) -> None:
        hub = self._hub(full_scan=True)
        hub._link_manager.owned_session_generation = 7
        hub._link_manager.transport = SimpleNamespace(
            async_send_collector=AsyncMock()
        )
        hub._collector_metadata_service.framed_values = {
            "collector_hardware_version": hardware_text
        }

        with (
            patch(
                "custom_components.eybond_local.runtime.hub.detection."
                "RuntimeLinkBaudChannel",
            ) as channel_type,
            patch(
                "custom_components.eybond_local.runtime.hub.detection."
                "async_detect_inverter_candidates",
                new=AsyncMock(
                    side_effect=AssertionError(
                        "unsupported collector must not enter UART re-sweep"
                    )
                ),
            ),
        ):
            result = await hub._async_attempt_runtime_link_baud_sweep(
                detection_generation=7
            )

        self.assertIsNone(result)
        channel_type.assert_not_called()

    # 1. detected inverter + first poll timeout keeps inverter identity.
    def test_first_poll_timeout_after_detection_keeps_inverter_identity(self) -> None:
        async def _run() -> None:
            hub = self._hub()
            hub._driver = _TimeoutDriver()
            hub._inverter = self._inverter()
            # A first bound+connected snapshot records the driver-bound identity.
            hub._last_snapshot = hub._build_snapshot()
            self.assertEqual(
                hub._last_snapshot.values["runtime_driver_state"], "driver_bound"
            )

            snapshot = await hub.async_refresh(poll_interval=3.0)

            # Identity survives the first-poll timeout; the entry is not collapsed.
            self.assertIsNotNone(snapshot.inverter)
            self.assertEqual(snapshot.inverter.serial_number, self._SERIAL)
            self.assertEqual(snapshot.inverter.model_name, self._MODEL)
            self.assertTrue(snapshot.connected)
            self.assertNotEqual(snapshot.values["runtime_poll_state"], "offline")
            self.assertEqual(
                snapshot.values["runtime_last_driver_bound_identity"],
                "modbus_smg|SMG 6200|92632500000001",
            )

        asyncio.run(_run())

    # 2. collector-only build after driver-bound does not erase the inverter.
    def test_collector_only_build_keeps_confirmed_inverter(self) -> None:
        hub = self._hub()
        hub.set_initial_inverter_binding(_SuccessDriver(), self._inverter())
        hub._last_snapshot = hub._build_snapshot()

        # A subsequent snapshot (e.g. a collector-metadata-only refresh) keeps the
        # confirmed inverter; the inverter track is independent of the collector.
        snapshot = hub._build_snapshot(extra_values={"collector_signal_strength": -55})

        self.assertIsNotNone(snapshot.inverter)
        self.assertEqual(snapshot.inverter.serial_number, self._SERIAL)
        self.assertEqual(snapshot.values["runtime_inverter_state"], "live_confirmed")
        self.assertEqual(snapshot.values["runtime_driver_state"], "driver_bound")

    # 3. startup persisted identity is provisional; live detection promotes it.
    def test_startup_persisted_identity_is_provisional_then_promoted(self) -> None:
        async def _run() -> None:
            hub = self._hub()
            hub.set_initial_inverter_binding(
                _SuccessDriver(),
                self._inverter(detection_status="startup_persisted_identity"),
            )
            provisional = hub._build_snapshot()
            self.assertEqual(
                provisional.values["runtime_inverter_state"], "provisional"
            )
            self.assertTrue(hub._inverter_binding_needs_live_detection_refresh)

            # Live detection confirms the SAME identity -> promote to live-confirmed.
            live_inverter = self._inverter()
            with patch(
                "custom_components.eybond_local.runtime.hub.detection.async_detect_inverter",
                new=self._fake_detection(live_inverter, _SuccessDriver()),
            ):
                snapshot = await hub.async_refresh(poll_interval=3.0)

            self.assertFalse(hub._inverter_binding_needs_live_detection_refresh)
            self.assertEqual(snapshot.values["runtime_inverter_state"], "live_confirmed")
            self.assertNotIn("runtime_identity_conflict", snapshot.values)

        asyncio.run(_run())

    def test_catalog_alias_rename_promotes_live_identity_without_conflict(self) -> None:
        async def _run() -> None:
            hub = self._hub()
            probe_target = ProbeTarget(
                devcode=0x0001,
                collector_addr=0x02,
                device_addr=0x01,
            )
            durable = DetectedInverter(
                driver_key="modbus_catalog",
                protocol_family="modbus_catalog",
                model_name="Deye-Compatible Three-Phase Hybrid 80 kW (Modbus)",
                serial_number="",
                probe_target=probe_target,
                details={"runtime_detection_status": "startup_persisted_identity"},
            )
            live = DetectedInverter(
                driver_key="modbus_catalog",
                protocol_family="modbus_catalog",
                model_name="Deye-Compatible Three-Phase Hybrid 8 kW (Modbus)",
                serial_number="",
                probe_target=probe_target,
                details={},
            )
            hub.set_initial_inverter_binding(_SuccessDriver(), durable)

            with patch(
                "custom_components.eybond_local.runtime.hub.detection.async_detect_inverter",
                new=self._fake_detection(live, _SuccessDriver()),
            ):
                snapshot = await hub.async_refresh(poll_interval=3.0)

            self.assertEqual(snapshot.inverter.model_name, live.model_name)
            self.assertEqual(snapshot.values["runtime_inverter_state"], "live_confirmed")
            self.assertNotIn("runtime_identity_conflict", snapshot.values)
            self.assertFalse(hub._inverter_binding_needs_live_detection_refresh)

        asyncio.run(_run())

    def test_catalog_restored_identity_keeps_binding_and_probe_error(self) -> None:
        async def _run() -> None:
            hub = self._hub()
            hub.set_initial_inverter_binding(
                _SuccessDriver(),
                self._inverter(
                    detection_status="persisted_model_probe_degraded"
                ),
            )

            async def _probe_timeout(_transport, *, driver_hint=""):
                raise RuntimeError("modbus_catalog:probe_timeout")

            with patch(
                "custom_components.eybond_local.runtime.hub.detection.async_detect_inverter",
                new=_probe_timeout,
            ):
                snapshot = await hub.async_refresh(poll_interval=3.0)

            self.assertIsNotNone(snapshot.inverter)
            self.assertEqual(snapshot.values["runtime_driver_state"], "driver_bound")
            self.assertEqual(snapshot.values["runtime_inverter_state"], "provisional")
            self.assertEqual(snapshot.last_error, "modbus_catalog:probe_timeout")

        asyncio.run(_run())

    # 4. startup persisted identity + different live full identity reports conflict.
    def test_startup_persisted_identity_conflict_keeps_durable(self) -> None:
        async def _run() -> None:
            hub = self._hub()
            hub.set_initial_inverter_binding(
                _SuccessDriver(),
                self._inverter(detection_status="startup_persisted_identity"),
            )

            # Live detection reports a DIFFERENT serial (different physical inverter).
            other = self._inverter(serial=self._OTHER_SERIAL)
            with patch(
                "custom_components.eybond_local.runtime.hub.detection.async_detect_inverter",
                new=self._fake_detection(other, _SuccessDriver()),
            ):
                snapshot = await hub.async_refresh(poll_interval=3.0)

            # Durable identity kept, not silently swapped; conflict published.
            self.assertEqual(snapshot.inverter.serial_number, self._SERIAL)
            self.assertEqual(snapshot.values["runtime_inverter_state"], "conflict")
            self.assertIn("runtime_identity_conflict", snapshot.values)
            self.assertIn(self._SERIAL, snapshot.values["runtime_identity_conflict"])
            self.assertIn(self._OTHER_SERIAL, snapshot.values["runtime_identity_conflict"])
            self.assertFalse(hub._inverter_binding_needs_live_detection_refresh)

        asyncio.run(_run())

    # 5. reconnect after offline preserves driver and resumes polling.
    def test_reconnect_after_offline_resumes_driver_bound_polling(self) -> None:
        async def _run() -> None:
            hub = self._hub()
            hub.set_initial_inverter_binding(_SuccessDriver(), self._inverter())
            hub._last_snapshot = hub._build_snapshot()

            # Simulate an offline gap; the fake link reconnects on the next attempt.
            hub._link_manager.connected = False

            snapshot = await hub.async_refresh(poll_interval=3.0)

            self.assertTrue(snapshot.connected)
            self.assertIsNotNone(snapshot.inverter)
            self.assertEqual(snapshot.inverter.serial_number, self._SERIAL)
            self.assertEqual(snapshot.values["runtime_driver_state"], "driver_bound")
            self.assertEqual(snapshot.values["runtime_poll_state"], "polling")

        asyncio.run(_run())

    def test_owned_session_replacement_gets_one_bounded_handover_grace(self) -> None:
        async def _run() -> None:
            hub = self._hub()
            link = _OwnedSessionHandoverLinkManager()
            hub._link_manager = link
            hub.set_initial_inverter_binding(_SuccessDriver(), self._inverter())

            # Establish the generation that completed a normal driver poll.
            initial = await hub.async_refresh(poll_interval=3.0)
            self.assertTrue(initial.connected)
            self.assertEqual(hub._stable_owned_session_generation, 1)

            # The same PN replaces its TCP socket. The regular 0.75s connect
            # budget is insufficient in this fake; lifecycle evidence grants
            # exactly one bounded 5s handover attempt for generation 2.
            link.connected = False
            link.owned_session_generation = 2
            recovered = await hub.async_refresh(poll_interval=3.0)

            self.assertTrue(recovered.connected)
            self.assertEqual(recovered.values["runtime_driver_state"], "driver_bound")
            self.assertNotEqual(recovered.values["runtime_poll_state"], "offline")
            self.assertIn(5.0, link.connect_timeouts)
            self.assertEqual(hub._stable_owned_session_generation, 2)

        asyncio.run(_run())

    def test_double_replacement_recovers_per_owned_session_generation(self) -> None:
        async def _run() -> None:
            hub = self._hub()
            link = _DoubleReplacementLinkManager()
            hub._link_manager = link
            hub.set_initial_inverter_binding(_SuccessDriver(), self._inverter())
            await hub.async_refresh(poll_interval=3.0)

            link.connected = False
            link.owned_session_generation = 2
            recovered = await hub.async_refresh(poll_interval=3.0)

            self.assertTrue(recovered.connected)
            self.assertEqual(recovered.values["runtime_driver_state"], "driver_bound")
            self.assertEqual(hub._stable_owned_session_generation, 3)
            self.assertGreaterEqual(link.connect_timeouts.count(5.0), 2)

        asyncio.run(_run())

    # 6. short PN / partial metadata does not downgrade durable identity.
    def test_short_collector_pn_does_not_downgrade_durable_identity(self) -> None:
        hub = self._hub()
        hub.set_initial_inverter_binding(_SuccessDriver(), self._inverter())
        # Live session reports only the short heartbeat PN prefix.
        hub._link_manager.collector_info.collector_pn = "V001020SYN6234"

        snapshot = hub._build_snapshot()

        self.assertEqual(snapshot.collector.collector_pn, "V001020SYN62344022")
        self.assertEqual(snapshot.values["collector_pn"], "V001020SYN62344022")
        self.assertEqual(snapshot.values["runtime_collector_state"], "identified")
        self.assertNotIn("runtime_identity_conflict", snapshot.values)

    # 7. no infinite live-detection refresh loop.
    def test_provisional_refresh_is_bounded_when_detection_keeps_failing(self) -> None:
        async def _run() -> None:
            hub = self._hub()
            hub.set_initial_inverter_binding(
                _SuccessDriver(),
                self._inverter(detection_status="startup_persisted_identity"),
            )

            detect_calls = 0

            async def _always_fail(_transport, *, driver_hint=""):
                nonlocal detect_calls
                detect_calls += 1
                raise RuntimeError("probe_timeout")

            with patch(
                "custom_components.eybond_local.runtime.hub.detection.async_detect_inverter",
                new=_always_fail,
            ):
                for _ in range(6):
                    await hub.async_refresh(poll_interval=3.0)

            # Bounded: detection stops re-running after the max attempts, and the
            # provisional identity is kept rather than lost.
            self.assertEqual(detect_calls, 3)
            self.assertFalse(hub._inverter_binding_needs_live_detection_refresh)
            self.assertIsNotNone(hub._inverter)
            self.assertEqual(hub._inverter.serial_number, self._SERIAL)

        asyncio.run(_run())

    # 8. support diagnostics include the explicit runtime state fields.
    def test_snapshot_exposes_all_runtime_state_fields(self) -> None:
        hub = self._hub()
        hub.set_initial_inverter_binding(_SuccessDriver(), self._inverter())

        snapshot = hub._build_snapshot()

        for key in (
            "runtime_session_state",
            "runtime_collector_state",
            "runtime_inverter_state",
            "runtime_driver_state",
            "runtime_poll_state",
            "runtime_last_driver_bound_identity",
            "runtime_state_transitions",
        ):
            self.assertIn(key, snapshot.values, key)
        self.assertEqual(snapshot.values["runtime_session_state"], "online")
        self.assertEqual(snapshot.values["runtime_collector_state"], "identified")
        self.assertEqual(snapshot.values["runtime_inverter_state"], "live_confirmed")

    def test_state_transition_history_is_bounded(self) -> None:
        hub = self._hub()
        hub.set_initial_inverter_binding(_SuccessDriver(), self._inverter())
        # Force many distinct composite states so the ring would overflow.
        for index in range(40):
            hub._link_manager.connected = bool(index % 2)
            hub._build_snapshot()

        self.assertLessEqual(len(hub._state_transition_history), 20)

    def test_driver_detection_is_cancelled_when_owned_session_changes(self) -> None:
        async def _run() -> None:
            hub = self._hub(full_scan=True)

            class _SessionChangingLink(_FakeLinkManager):
                def __init__(self) -> None:
                    super().__init__()
                    self.owned_session_generation = 1
                    self.changed = asyncio.Event()

                async def async_wait_for_owned_session_change(self, generation: int) -> None:
                    while self.owned_session_generation == generation:
                        await self.changed.wait()

            link = _SessionChangingLink()
            hub._link_manager = link
            started = asyncio.Event()
            cancelled = asyncio.Event()

            async def _slow_detection(*_args, **_kwargs):
                started.set()
                try:
                    await asyncio.Event().wait()
                except asyncio.CancelledError:
                    cancelled.set()
                    raise

            with patch(
                "custom_components.eybond_local.runtime.hub.detection.async_detect_inverter_candidates",
                side_effect=_slow_detection,
            ):
                detection = asyncio.create_task(hub._async_detect_driver())
                await asyncio.wait_for(started.wait(), timeout=1.0)
                link.owned_session_generation += 1
                link.changed.set()
                result = await asyncio.wait_for(detection, timeout=1.0)

            self.assertEqual(result, "collector_session_changed")
            self.assertTrue(cancelled.is_set())

        asyncio.run(_run())

    def test_cancelled_refresh_drains_late_driver_detection_failure(self) -> None:
        async def _run() -> None:
            hub = self._hub(full_scan=False)
            started = asyncio.Event()
            child_cancelled = asyncio.Event()
            finish_child = asyncio.Event()
            loop_errors: list[dict[str, object]] = []
            loop = asyncio.get_running_loop()
            previous_handler = loop.get_exception_handler()
            loop.set_exception_handler(
                lambda _loop, context: loop_errors.append(context)
            )

            async def _late_failure(*_args, **_kwargs):
                started.set()
                try:
                    await asyncio.Event().wait()
                except asyncio.CancelledError:
                    child_cancelled.set()
                    await finish_child.wait()
                    raise DriverSweepNoMatch(
                        "no_supported_driver_matched",
                        silent=True,
                    )

            try:
                with patch(
                    "custom_components.eybond_local.runtime.hub.detection."
                    "async_detect_inverter",
                    side_effect=_late_failure,
                ):
                    detection = asyncio.create_task(hub._async_detect_driver())
                    await asyncio.wait_for(started.wait(), timeout=1.0)
                    detection.cancel()
                    await asyncio.wait_for(child_cancelled.wait(), timeout=1.0)
                    self.assertFalse(detection.done())
                    detection.cancel()
                    await asyncio.sleep(0)
                    self.assertFalse(detection.done())
                    finish_child.set()
                    try:
                        result = await asyncio.wait_for(detection, timeout=1.0)
                    except asyncio.CancelledError:
                        pass
                    else:
                        self.fail(f"cancelled detection returned {result!r}")

                await asyncio.sleep(0)
                self.assertTrue(detection.cancelled())
                self.assertEqual(loop_errors, [])
            finally:
                loop.set_exception_handler(previous_handler)

        asyncio.run(_run())



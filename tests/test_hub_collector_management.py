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


class HubCollectorManagementTests(unittest.TestCase):
    """Hub delegation of collector-management ACTIONS to the negotiated adapter."""

    def _hub(self) -> EybondHub:
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

    def _framed_hub(self):
        hub = self._hub()
        link = _FakeLinkManager()
        link.transport = _CollectorManagementTransport()
        hub._link_manager = link
        return hub, link

    def _at_hub(self):
        hub = self._hub()
        link = _FakeLinkManager()
        link.transport = object()  # no async_send_collector -> not framed
        link.collector_at_transport = _CollectorAtQueryTransport(
            {"CLDSRVHOST1": "iot.eybond.com,18899,TCP"}
        )
        hub._link_manager = link
        return hub, link

    def test_framed_capabilities_all_true(self) -> None:
        hub, _ = self._framed_hub()
        caps = hub.collector_management_capabilities()
        self.assertTrue(caps.read_endpoint_state)
        self.assertTrue(caps.write_endpoint)
        self.assertTrue(caps.apply_changes)
        self.assertTrue(caps.reboot)

    def test_wifi_management_uses_the_exact_runtime_owned_framed_session(
        self,
    ) -> None:
        class _WifiTransport:
            def __init__(self) -> None:
                self.values = {7: "Old SSID", 8: "old-password"}
                self.requests: list[tuple[int, bytes]] = []

            async def async_send_collector(
                self,
                *,
                fcode: int,
                payload: bytes = b"",
                devcode: int = 0,
                collector_addr: int = 1,
            ):
                del devcode, collector_addr
                self.requests.append((fcode, payload))
                parameter = payload[0]
                if fcode == 2:
                    return (
                        None,
                        bytes((0, parameter))
                        + self.values.get(parameter, "").encode("ascii"),
                    )
                if fcode == 3:
                    value = payload[1:].decode("ascii")
                    if parameter != 29:
                        self.values[parameter] = value
                    return (None, bytes((0, parameter)))
                raise KeyError((fcode, payload))

        async def _run() -> None:
            hub = self._hub()
            link = _FakeLinkManager()
            transport = _WifiTransport()
            link.transport = transport
            link.active_transport = transport
            hub._link_manager = link

            before = await hub.async_query_collector_parameters((7, 8))
            applied_ssid = await hub.async_set_collector_wifi_credentials(
                ssid="New SSID",
                password="new-password",
                ssid_parameter=7,
                password_parameter=8,
            )

            self.assertEqual(before, {7: "Old SSID", 8: "old-password"})
            self.assertEqual(applied_ssid, "New SSID")
            self.assertEqual(transport.values[7], "New SSID")
            self.assertEqual(transport.values[8], "new-password")
            self.assertIn((3, bytes((29,)) + b"1"), transport.requests)

        asyncio.run(_run())

    def test_uart_management_uses_the_exact_runtime_owned_framed_session(self) -> None:
        async def _run() -> None:
            hub = self._hub()
            link = _FakeLinkManager()
            transport = _CollectorManagementTransport()
            link.transport = transport
            link.active_transport = transport
            hub._link_manager = link

            before = await hub.async_query_collector_parameters((34,))
            readback = await hub.async_set_collector_uart_baudrate("9600")

            self.assertEqual(before, {34: "2400,8,1,NONE"})
            self.assertEqual(readback, "9600,8,1,NONE")
            self.assertEqual(transport.uart, "9600,8,1,NONE")

        asyncio.run(_run())

    def test_wifi_management_never_uses_a_stale_fallback_transport(self) -> None:
        async def _run() -> None:
            hub, link = self._framed_hub()
            link.active_transport = None

            with self.assertRaisesRegex(
                CollectorManagementUnsupportedError,
                "collector_local_management_not_supported",
            ):
                await hub.async_query_collector_parameters((7,))

            self.assertEqual(link.transport.requests, [])

        asyncio.run(_run())

    def test_at_capabilities_include_vendor_restart(self) -> None:
        hub, _ = self._at_hub()
        caps = hub.collector_management_capabilities()
        self.assertTrue(caps.read_endpoint_state)
        self.assertTrue(caps.write_endpoint)
        self.assertTrue(caps.apply_changes)
        self.assertTrue(caps.reboot)

    def test_capabilities_follow_live_handover_without_reload(self) -> None:
        # Start framed, then the SAME hub sees the wire hand over to AT:
        # capabilities remain live and update without a config-entry reload.
        hub, link = self._framed_hub()
        self.assertTrue(hub.collector_management_capabilities().reboot)
        link.transport = object()
        link.collector_at_transport = _CollectorAtQueryTransport(
            {"CLDSRVHOST1": "iot.eybond.com,18899,TCP"}
        )
        self.assertTrue(hub.collector_management_capabilities().reboot)
        self.assertTrue(hub.collector_management_capabilities().write_endpoint)

    def test_unavailable_when_adapter_is_none(self) -> None:
        hub = self._hub()
        link = _FakeLinkManager()
        link.transport = object()  # neither framed nor AT
        hub._link_manager = link
        caps = hub.collector_management_capabilities()
        self.assertFalse(
            any((caps.read_endpoint_state, caps.write_endpoint, caps.apply_changes, caps.reboot))
        )

    def test_live_conflict_with_binding_is_none_capabilities_false_provenance_conflict(self) -> None:
        # Even with an existing (framed) confirmed binding, a live conflict yields
        # none adapter, all-false capabilities, provenance "conflict", and the
        # diagnostics never show framed/AT as the effective management adapter.
        hub = self._hub()
        link = _FakeLinkManager()
        link.transport = _CollectorManagementTransport()  # framed transport present

        def _adapter_id() -> str:
            from custom_components.eybond_local.connection.session_handle import ADAPTER_NONE

            return ADAPTER_NONE

        link.collector_management_adapter_id = _adapter_id
        link.collector_management_adapter_provenance = lambda: "conflict"
        hub._link_manager = link

        caps = hub.collector_management_capabilities()
        self.assertFalse(
            any((caps.read_endpoint_state, caps.write_endpoint, caps.apply_changes, caps.reboot))
        )
        diag = hub.collector_management_diagnostics()
        self.assertEqual(diag["collector_management_adapter_id"], "none")
        self.assertEqual(diag["collector_management_adapter_provenance"], "conflict")
        self.assertNotIn("framed_collector_commands", str(diag))
        self.assertNotIn("at_commands", str(diag))

    def test_at_write_uses_cldsrvhost1_and_intpara(self) -> None:
        async def _run() -> None:
            hub, link = self._at_hub()
            result = await hub.async_set_collector_server_endpoint(
                "192.168.8.113,18899,TCP", apply_changes=True
            )
            at = link.collector_at_transport
            self.assertIn(("CLDSRVHOST1", "192.168.8.113,18899,TCP"), at.writes)
            self.assertIn(("INTPARA", "29,1"), at.writes)
            self.assertEqual(result["status"], "applied")
            self.assertEqual(result["management_protocol"], "at_text")
            self.assertTrue(result["apply_performed"])

        asyncio.run(_run())

    def test_at_read_endpoint_state(self) -> None:
        async def _run() -> None:
            hub, link = self._at_hub()
            state = await hub.async_get_collector_server_endpoint_state()
            self.assertEqual(state["current_endpoint"], "iot.eybond.com,18899,TCP")
            self.assertIn("CLDSRVHOST1", link.collector_at_transport.queries)

        asyncio.run(_run())

    def test_at_reboot_uses_soft_reset_and_returns_confirmed_result(self) -> None:
        async def _run() -> None:
            hub, link = self._at_hub()

            result = await hub.async_reboot_collector()

            self.assertEqual(result["status"], "reboot_triggered")
            self.assertEqual(result["action"], "reboot")
            self.assertIn("CLDSRVHOST1", link.collector_at_transport.queries)
            self.assertIn(("RESET", "S"), link.collector_at_transport.writes)

        asyncio.run(_run())

    def test_framed_staged_when_apply_not_requested(self) -> None:
        async def _run() -> None:
            hub, _ = self._framed_hub()
            result = await hub.async_set_collector_server_endpoint(
                "192.168.1.193,18899,TCP", apply_changes=False
            )
            self.assertEqual(result["status"], "staged")
            self.assertFalse(result["apply_performed"])
            self.assertTrue(result["write_confirmed"])

        asyncio.run(_run())

    def test_last_operation_recorded_on_success(self) -> None:
        async def _run() -> None:
            hub, _ = self._framed_hub()
            await hub.async_set_collector_server_endpoint(
                "192.168.1.193,18899,TCP", apply_changes=False
            )
            diag = hub.collector_management_diagnostics()
            op = diag["collector_management_last_operation"]
            self.assertEqual(op["operation"], "write_endpoint")
            self.assertEqual(op["status"], "ok")
            self.assertEqual(op["error_class"], "")
            self.assertIn("duration_ms", op)
            # No endpoint value leaked into diagnostics.
            self.assertNotIn("192.168.1.193", str(diag))

        asyncio.run(_run())

    def test_last_operation_records_at_reboot_success(self) -> None:
        async def _run() -> None:
            hub, _ = self._at_hub()
            await hub.async_reboot_collector()
            op = hub.collector_management_diagnostics()["collector_management_last_operation"]
            self.assertEqual(op["operation"], "reboot")
            self.assertEqual(op["status"], "ok")
            self.assertEqual(op["error_class"], "")

        asyncio.run(_run())

    def test_failed_endpoint_subrequest_is_recorded_without_values(self) -> None:
        from custom_components.eybond_local.collector.management import CollectorManagementTransportError

        async def _run():
            hub, _ = self._framed_hub()
            hub._link_manager.owned_session_generation = 17
            for parameter in (21, 30):
                async def failed():
                    hub._link_manager.owned_session_generation += 1
                    raise CollectorManagementTransportError("TimeoutError", query_parameter=parameter)

                with self.assertRaises(CollectorManagementTransportError):
                    await hub._run_management_operation("read_endpoint_state", failed)
                op = hub.collector_management_diagnostics()["collector_management_last_operation"]
                self.assertEqual(op["failed_request"], {"protocol": "eybond_framed", "function": 2, "parameter": parameter})
                self.assertEqual(op["session_generation_end"], op["session_generation_start"] + 1)
                self.assertEqual(op["error_code"], "TimeoutError")
            await hub._run_management_operation("read_endpoint_state", AsyncMock())
            op = hub.collector_management_diagnostics()["collector_management_last_operation"]
            self.assertNotIn("failed_request", op)
            self.assertEqual(op["status"], "ok")
            with self.assertRaises(asyncio.CancelledError):
                await hub._run_management_operation("read_endpoint_state", AsyncMock(side_effect=asyncio.CancelledError()))
            self.assertEqual(hub._last_management_operation["status"], "cancelled")

        asyncio.run(_run())

    def test_diagnostics_have_no_endpoint_or_credentials(self) -> None:
        hub, _ = self._framed_hub()
        diag = hub.collector_management_diagnostics()
        self.assertIn("collector_management_adapter_id", diag)
        self.assertIn("collector_management_capabilities", diag)
        blob = str(diag)
        for secret in ("password", "ssid", "18899", "eybond.com"):
            self.assertNotIn(secret, blob)


if __name__ == "__main__":
    unittest.main()

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


class HubEvidenceAdmissionAndRecoveryTests(unittest.IsolatedAsyncioTestCase):
    def make_hub(self):
        from custom_components.eybond_local.drivers.srne import SrneModbusDriver

        hub = EybondHub(connection=EybondConnectionSpec(
            server_ip="192.0.2.10", collector_ip="192.0.2.14", tcp_port=8899,
            udp_port=58899, discovery_target="192.0.2.255", discovery_interval=30,
            heartbeat_interval=60, request_timeout=5.0,
        ))
        hub._link_manager = _FakeLinkManager()
        hub._link_manager.collector_info.collector_pn = "E50000200000000001"
        hub._driver = SrneModbusDriver()
        hub._inverter = DetectedInverter(
            driver_key="srne_modbus", protocol_family="srne_modbus", model_name="SRNE Test",
            serial_number="TEST", probe_target=ProbeTarget(1, 255, 1),
            register_schema_name="srne_modbus/base.json",
        )
        hub._accept_inverter_binding_identity()
        return hub

    async def test_payload_error_survives_empty_delta_and_clears_on_new_read(self):
        from custom_components.eybond_local.drivers.read_result import DriverReadResult, DriverReadMode

        hub = self.make_hub()
        outcomes = [ModbusError("request_timeout"), ModbusError("request_timeout"),
                    DriverReadResult({}, mode=DriverReadMode.DELTA),
                    DriverReadResult({"output_power": 420}),
                    ModbusError("request_timeout"), ModbusError("exception_code:2")]
        with patch.object(hub._driver, "async_read_values", side_effect=outcomes):
            failed = await hub.async_refresh(poll_interval=3)
            self.assertEqual(failed.values["runtime_payload_error"], "request_timeout")
            metadata = hub._build_snapshot(extra_values={"collector_wifi_ssid": "test"})
            self.assertEqual(metadata.values["runtime_payload_error"], "request_timeout")
            empty = await hub.async_refresh(poll_interval=3)
            self.assertEqual(empty.values["runtime_payload_error"], "request_timeout")
            recovered = await hub.async_refresh(poll_interval=3)
            self.assertIsNone(recovered.last_error)
            self.assertEqual(recovered.telemetry.values()["output_power"], 420)
            self.assertNotIn("runtime_payload_error", recovered.values)
            failed_again = await hub.async_refresh(poll_interval=3)
            self.assertEqual(failed_again.values["runtime_payload_error"], "exception_code:2")
        self.assertEqual(hub._link_manager.reset_calls, 0)

    async def test_payload_error_does_not_cross_identity_boundary(self):
        from dataclasses import replace

        hub = self.make_hub()
        with patch.object(hub._driver, "async_read_values", side_effect=ModbusError("request_timeout")):
            await hub.async_refresh()
        hub._accept_inverter_binding_identity()
        self.assertEqual(hub._build_snapshot().values["runtime_payload_error"], "request_timeout")
        hub._inverter = replace(hub._inverter, serial_number="REPLACEMENT")
        hub._accept_inverter_binding_identity()
        self.assertNotIn("runtime_payload_error", hub._build_snapshot().values)

    def test_local_evidence_admission_uses_plan_not_cloud_or_connectivity(self):
        hub = self.make_hub()
        self.assertTrue(hub.local_register_collection_availability.available)
        hub._link_manager.connected = False  # existing collection can reconnect
        self.assertTrue(hub.local_register_collection_availability.available)
        with patch.object(hub._driver, "local_register_read_plans", return_value=()):
            self.assertEqual(hub.local_register_collection_availability.reason, "read_plan_unavailable")
        with patch.object(hub._driver, "local_register_read_plans", side_effect=FileNotFoundError()):
            self.assertEqual(hub.local_register_collection_availability.reason, "read_plan_unavailable")
        hub._link_manager.collector_info.collector_pn = ""
        self.assertEqual(hub.local_register_collection_availability.reason, "collector_identity_unavailable")
        hub._driver = None
        self.assertEqual(hub.local_register_collection_availability.reason, "inverter_unidentified")


class _FakeLinkManager:
    def __init__(self, *, heartbeat_result: bool = True) -> None:
        self.connected = True
        self.reset_calls = 0
        self.heartbeat_result = heartbeat_result
        self.collector_info = CollectorInfo(
            remote_ip="192.168.1.14",
            last_udp_reply="collector-reply",
            last_udp_reply_from="192.168.1.14",
        )
        self.transport = object()
        self.collector_at_transport = None
        # Stand-in for the configured collector target the real link uses to gate
        # a disconnected collector-only bootstrap read. Non-empty by default (the
        # base fake is used connected, so it is irrelevant there); the ambiguous
        # link fake blanks it to model an unconfigured collector.
        self.configured_collector_ip = "192.168.1.14"

    async def async_try_connect(self, *, timeout: float, require_heartbeat: bool = False) -> bool:
        if require_heartbeat and not self.heartbeat_result:
            return False
        self.connected = True
        return self.connected

    def collector_metadata_routes(self):
        """Reproduce the pre-service transport selection for characterization.

        The real link decides metadata routes from trusted session evidence; this
        test fake preserves the historical hasattr/collector_ip gating so the hub
        characterization tests still exercise the exact same channel selection.
        """

        from custom_components.eybond_local.collector.metadata import (
            build_collector_metadata_routes,
        )

        missing = object()
        collector_ip = str(getattr(self, "configured_collector_ip", "") or "").strip()
        active_transport = getattr(self, "active_transport", missing)
        if active_transport is missing:
            transport = self.transport if self.connected else None
        else:
            transport = active_transport
            if transport is None and not self.connected and collector_ip:
                transport = getattr(self, "transport", None)
        active_at = getattr(self, "active_collector_at_transport", missing)
        if active_at is missing:
            at_transport = getattr(self, "collector_at_transport", None)
        else:
            at_transport = active_at
            if at_transport is None and not self.connected and collector_ip:
                at_transport = getattr(self, "collector_at_transport", None)
        allow_disconnected = (
            at_transport is not None and not self.connected and bool(collector_ip)
        )
        fc_ok = transport is not None and hasattr(transport, "async_send_collector")
        at_usable = at_transport is not None and (
            getattr(at_transport, "connected", False) or allow_disconnected
        )
        framed = transport if fc_ok else None
        at = at_transport if at_usable else None
        bootstrap = (
            at_transport
            if (
                not fc_ok
                and at_usable
                and hasattr(at_transport, "async_query_bridge_hardware_version")
            )
            else None
        )
        return build_collector_metadata_routes(
            framed_transport=framed,
            at_transport=at,
            bootstrap_transport=bootstrap,
            generation=int(getattr(self, "owned_session_generation", 0) or 0),
            provenance="live" if self.connected else "bootstrap_claimable",
            # This test double exposes an AT transport only when its scripted
            # session is intended to have confirmed that management dialect.
            at_capability_confirmed=at is not None,
        )

    async def async_ensure_connected(
        self,
        *,
        timeout: float,
        require_heartbeat: bool = False,
    ) -> None:
        ok = await self.async_try_connect(timeout=timeout, require_heartbeat=require_heartbeat)
        if not ok:
            if require_heartbeat and self.connected:
                raise ConnectionError("collector_heartbeat_timeout")
            raise ConnectionError("collector_not_connected")

    async def async_reset_connection(self, *, reason: str = "") -> None:
        self.reset_calls += 1
        self.connected = False

    def listener_diagnostics(self) -> dict[str, object]:
        return {
            "collector_configured_session_protocol": "at_text",
            "collector_callback_identity_strategy": "at_dtupn",
        }

    def collector_management_adapter_id(self) -> str:
        from custom_components.eybond_local.connection.session_handle import (
            ADAPTER_COLLECTOR_AT_COMMANDS,
            ADAPTER_COLLECTOR_FRAMED_COMMANDS,
            ADAPTER_NONE,
        )

        if hasattr(self.transport, "async_send_collector"):
            return ADAPTER_COLLECTOR_FRAMED_COMMANDS
        if hasattr(self.collector_at_transport, "async_query"):
            return ADAPTER_COLLECTOR_AT_COMMANDS
        return ADAPTER_NONE


class _StaleHeartbeatThenRecoveredLinkManager(_FakeLinkManager):
    def __init__(self) -> None:
        super().__init__()
        self.heartbeat_attempts = 0

    async def async_try_connect(self, *, timeout: float, require_heartbeat: bool = False) -> bool:
        if require_heartbeat:
            self.heartbeat_attempts += 1
            if self.heartbeat_attempts == 1:
                self.connected = True
                return False
        self.connected = True
        return True


class _OwnedSessionHandoverLinkManager(_FakeLinkManager):
    """Expose a registry generation change before reconnecting the same collector."""

    def __init__(self) -> None:
        super().__init__()
        self.owned_session_generation = 1
        self.connect_timeouts: list[float] = []

    def has_confirmed_wire_binding(self) -> bool:
        return True

    async def async_try_connect(
        self,
        *,
        timeout: float,
        require_heartbeat: bool = False,
    ) -> bool:
        self.connect_timeouts.append(float(timeout))
        if not self.connected and timeout < 5.0:
            return False
        self.connected = True
        return True


class _DoubleReplacementLinkManager(_OwnedSessionHandoverLinkManager):
    """First replacement disappears; the next generation becomes usable."""

    def __init__(self) -> None:
        super().__init__()
        self.fail_first_handover_generation = True

    async def async_try_connect(
        self,
        *,
        timeout: float,
        require_heartbeat: bool = False,
    ) -> bool:
        self.connect_timeouts.append(float(timeout))
        if (
            not self.connected
            and self.owned_session_generation == 2
            and self.fail_first_handover_generation
        ):
            self.fail_first_handover_generation = False
            self.owned_session_generation = 3
            return False
        self.connected = True
        return True


class _ProxyRouteLinkManager(_FakeLinkManager):
    def __init__(self) -> None:
        super().__init__()
        self.reverse_discovery_flags: list[bool] = []
        self.reverse_discovery_calls: list[dict[str, float | int]] = []
        self.callback_listener_ports: list[int] = []
        self.proxy_route_start_calls: list[dict[str, object]] = []
        self.proxy_route_stop_calls = 0
        self.proxy_route_running_value = False
        self.disconnect_reasons: list[str] = []

    def set_reverse_discovery_enabled(self, enabled: bool) -> None:
        self.reverse_discovery_flags.append(bool(enabled))

    async def async_ensure_callback_listener(self, port: int) -> None:
        self.callback_listener_ports.append(int(port))

    async def async_trigger_reverse_discovery(
        self,
        *,
        port: int = 0,
        timeout: float = 0.75,
    ) -> dict[str, object]:
        self.reverse_discovery_calls.append({"port": int(port), "timeout": float(timeout)})
        return {"status": "probe_sent"}

    async def async_start_proxy_capture_route(self, **kwargs) -> None:
        self.proxy_route_start_calls.append(dict(kwargs))
        self.proxy_route_running_value = True

    async def async_stop_proxy_capture_route(self) -> None:
        self.proxy_route_stop_calls += 1
        self.proxy_route_running_value = False

    def proxy_capture_route_running(self) -> bool:
        return self.proxy_route_running_value

    async def async_disconnect_collector_connections(self, *, reason: str = "") -> None:
        self.disconnect_reasons.append(str(reason))


class _TimeoutDriver:
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
        raise ModbusError("request_timeout")


class _DisconnectedDriver:
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
        raise ConnectionError("collector_not_connected")


class _TimeoutThenSuccessDriver:
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
        if self.calls == 1:
            raise ModbusError("request_timeout")
        return {
            "output_power": 420,
            "battery_average_power": -180,
        }


class _TimeoutThenDisconnectedDriver:
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
        if self.calls == 1:
            raise ModbusError("request_timeout")
        raise ConnectionError("collector_not_connected")


class _IllegalDataValueDriver(ModbusWriteErrorMixin):
    def __init__(self) -> None:
        self.read_calls = 0
        self.write_calls = 0

    async def async_read_values(
        self,
        transport,
        inverter,
        *,
        runtime_state=None,
        poll_interval=None,
        now_monotonic=None,
    ):
        self.read_calls += 1
        return {
            "battery_connected": True,
            "utility_charging_allowed": True,
            "charging_active": False,
            "charging_inactive": True,
            "operating_mode": "Off-Grid",
            "max_ac_charge_current": 20,
        }

    async def async_write_capability(
        self,
        transport,
        inverter,
        capability_key,
        value,
        *,
        runtime_state=None,
    ):
        self.write_calls += 1
        raise ModbusError("exception_code:3")


class _WriteConfirmedDriver:
    def __init__(self) -> None:
        self.read_calls = 0
        self.write_calls = 0
        self._current_value = 20

    async def async_read_values(
        self,
        transport,
        inverter,
        *,
        runtime_state=None,
        poll_interval=None,
        now_monotonic=None,
    ):
        self.read_calls += 1
        return {
            "battery_connected": True,
            "utility_charging_allowed": True,
            "charging_active": False,
            "charging_inactive": True,
            "operating_mode": "Off-Grid",
            "max_ac_charge_current": self._current_value,
        }

    async def async_write_capability(
        self,
        transport,
        inverter,
        capability_key,
        value,
        *,
        runtime_state=None,
    ):
        self.write_calls += 1
        self._current_value = value
        return value


class _WriteUnconfirmedDriver:
    def __init__(self) -> None:
        self.read_calls = 0
        self.write_calls = 0

    async def async_read_values(
        self,
        transport,
        inverter,
        *,
        runtime_state=None,
        poll_interval=None,
        now_monotonic=None,
    ):
        self.read_calls += 1
        return {
            "battery_connected": True,
            "utility_charging_allowed": True,
            "charging_active": False,
            "charging_inactive": True,
            "operating_mode": "Off-Grid",
            "max_ac_charge_current": 20,
        }

    async def async_write_capability(
        self,
        transport,
        inverter,
        capability_key,
        value,
        *,
        runtime_state=None,
    ):
        self.write_calls += 1
        return value


class _WriteDelayedConfirmationDriver:
    def __init__(self) -> None:
        self.read_calls = 0
        self.write_calls = 0
        self._written_value = 20

    async def async_read_values(
        self,
        transport,
        inverter,
        *,
        runtime_state=None,
        poll_interval=None,
        now_monotonic=None,
    ):
        self.read_calls += 1
        # Read 1 is the editability snapshot. Read 2 is the first post-write
        # full poll and still exposes the old value. Read 3 converges.
        readback = self._written_value if self.read_calls >= 3 else 20
        return {
            "battery_connected": True,
            "utility_charging_allowed": True,
            "charging_active": False,
            "charging_inactive": True,
            "operating_mode": "Off-Grid",
            "max_ac_charge_current": readback,
        }

    async def async_write_capability(
        self,
        transport,
        inverter,
        capability_key,
        value,
        *,
        runtime_state=None,
    ):
        self.write_calls += 1
        self._written_value = value
        return value


class _AdvancingClockWriteDriver:
    def __init__(self, *, readback: str) -> None:
        self.read_calls = 0
        self.write_calls = 0
        self._written = False
        self._readback = readback

    async def async_read_values(
        self,
        transport,
        inverter,
        *,
        runtime_state=None,
        poll_interval=None,
        now_monotonic=None,
    ):
        self.read_calls += 1
        return {
            "battery_connected": True,
            "utility_charging_allowed": True,
            "charging_active": False,
            "charging_inactive": True,
            "operating_mode": "Off-Grid",
            "inverter_time": self._readback if self._written else "19:04:03",
        }

    async def async_write_capability(
        self,
        transport,
        inverter,
        capability_key,
        value,
        *,
        runtime_state=None,
    ):
        self.write_calls += 1
        self._written = True
        return value


class _WriteConfirmedWhileChargingDriver:
    def __init__(self) -> None:
        self.read_calls = 0
        self.write_calls = 0
        self._current_value = 20

    async def async_read_values(
        self,
        transport,
        inverter,
        *,
        runtime_state=None,
        poll_interval=None,
        now_monotonic=None,
    ):
        self.read_calls += 1
        return {
            "battery_connected": True,
            "utility_charging_allowed": True,
            "charging_active": True,
            "charging_inactive": False,
            "operating_mode": "Off-Grid",
            "max_ac_charge_current": self._current_value,
        }

    async def async_write_capability(
        self,
        transport,
        inverter,
        capability_key,
        value,
        *,
        runtime_state=None,
    ):
        self.write_calls += 1
        self._current_value = value
        return value


class _CollectorQueryTransport:
    def __init__(self, responses: dict[tuple[int, bytes], bytes]) -> None:
        self._responses = dict(responses)
        self.requests: list[tuple[int, bytes]] = []

    async def async_send_collector(
        self,
        *,
        fcode: int,
        payload: bytes = b"",
        devcode: int = 0,
        collector_addr: int = 1,
    ):
        self.requests.append((fcode, payload))
        return (None, self._responses[(fcode, payload)])


class _CollectorManagementTransport:
    def __init__(self) -> None:
        self.endpoint = "47.91.67.66,18899,TCP"
        self.reboot_required = "0"
        self.uart = "2400,8,1,NONE"
        self.requests: list[tuple[int, bytes]] = []

    async def async_send_collector(
        self,
        *,
        fcode: int,
        payload: bytes = b"",
        devcode: int = 0,
        collector_addr: int = 1,
    ):
        self.requests.append((fcode, payload))
        if fcode == 2:
            parameter = payload[0]
            if parameter == 21:
                return (None, bytes((0, 21)) + self.endpoint.encode("ascii"))
            if parameter == 30:
                return (None, bytes((0, 30)) + self.reboot_required.encode("ascii"))
            if parameter == 34:
                return (None, bytes((0, 34)) + self.uart.encode("ascii"))
            raise KeyError((fcode, payload))
        if fcode == 3:
            parameter = payload[0]
            value = payload[1:].decode("ascii")
            if parameter == 21:
                self.endpoint = value
                self.reboot_required = "1"
                return (None, bytes((0, 21)))
            if parameter == 29:
                self.reboot_required = "0"
                return (None, bytes((0, 29)))
            if parameter == 34:
                self.uart = f"{value},8,1,NONE"
                return (None, bytes((0, 34)))
            raise KeyError((fcode, payload))
        raise KeyError((fcode, payload))


class _CollectorAtQueryTransport:
    def __init__(self, responses: dict[str, str], *, connected: bool = True) -> None:
        self._responses = dict(responses)
        self.connected = connected
        self.queries: list[str] = []
        self.writes: list[tuple[str, str]] = []

    async def async_query(self, command: str) -> CollectorAtResponse:
        self.queries.append(command)
        value = self._responses[command]
        return CollectorAtResponse(command=command, value=value, raw=f"AT+{command}:{value}")

    async def async_write(self, command: str, value: str) -> CollectorAtResponse:
        self.writes.append((command, value))
        self._responses[command] = value
        return CollectorAtResponse(command=command, value="W000", raw=f"AT+{command}:W000")


class _CollectorOnlyLinkManager(_FakeLinkManager):
    def __init__(self, at_transport: _CollectorAtQueryTransport) -> None:
        super().__init__()
        self.connected = False
        self.transport = object()
        self.collector_at_transport = at_transport

    async def async_try_connect(self, *, timeout: float, require_heartbeat: bool = False) -> bool:
        return False


class _AmbiguousActiveLinkManager(_FakeLinkManager):
    def __init__(
        self,
        transport: _CollectorQueryTransport,
        at_transport: _CollectorAtQueryTransport,
    ) -> None:
        super().__init__()
        self.connected = False
        self.transport = transport
        self.collector_at_transport = at_transport
        self.active_transport = None
        self.active_collector_at_transport = None
        # No configured collector target: the disconnected collector-only read is
        # not allowed, so an ambiguous inactive session yields no metadata reads.
        self.configured_collector_ip = ""

    async def async_try_connect(self, *, timeout: float, require_heartbeat: bool = False) -> bool:
        return False


class _InactiveActiveLinkManager(_FakeLinkManager):
    def __init__(
        self,
        transport: _CollectorQueryTransport,
        at_transport: _CollectorAtQueryTransport | None = None,
    ) -> None:
        super().__init__()
        self.connected = False
        self.transport = transport
        self.collector_at_transport = at_transport
        self.active_transport = None
        self.active_collector_at_transport = None

    async def async_try_connect(self, *, timeout: float, require_heartbeat: bool = False) -> bool:
        return False


class _RuntimeValuesDriver:
    async def async_read_values(
        self,
        transport,
        inverter,
        *,
        runtime_state=None,
        poll_interval=None,
        now_monotonic=None,
    ):
        return {"output_power": 420}


class _SeedDriver:
    pass



from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import importlib
import json
from datetime import datetime
from pathlib import Path
import sys
import tempfile
import types
import unittest


@dataclasses.dataclass
class _FakeInverter:
    """Minimal inverter stand-in supporting dataclasses.replace for overlay-merge tests."""

    capabilities: tuple = ()
    capability_groups: tuple = ()
    register_schema_name: str = ""
from unittest.mock import AsyncMock, PropertyMock, patch

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
# `helpers` lives beside this file, so the tests directory itself must be
# importable for `from helpers...` to resolve when a module is run
# directly (unittest discover happens to add it; direct runs do not).
TESTS_ROOT = Path(__file__).resolve().parent
if str(TESTS_ROOT) not in sys.path:
    sys.path.insert(0, str(TESTS_ROOT))

from helpers.homeassistant_stubs import ensure_module

from custom_components.eybond_local.support.proxy_capture import proxy_capture_overview_values


def _install_coordinator_stubs() -> None:
    custom_components = ensure_module("custom_components")
    eybond_local = ensure_module("custom_components.eybond_local")
    runtime_package = ensure_module("custom_components.eybond_local.runtime")
    homeassistant = ensure_module("homeassistant")
    components = ensure_module("homeassistant.components")
    components_network = ensure_module("homeassistant.components.network")
    components_network_util = ensure_module("homeassistant.components.network.util")
    persistent_notification = ensure_module(
        "homeassistant.components.persistent_notification"
    )
    config_entries = ensure_module("homeassistant.config_entries")
    ha_const = ensure_module("homeassistant.const")
    helpers = ensure_module("homeassistant.helpers")
    device_registry = ensure_module("homeassistant.helpers.device_registry")
    entity_registry = ensure_module("homeassistant.helpers.entity_registry")
    network = ensure_module("homeassistant.helpers.network")
    update_coordinator = ensure_module("homeassistant.helpers.update_coordinator")
    util = ensure_module("homeassistant.util")
    dt = ensure_module("homeassistant.util.dt")
    util_logging = ensure_module("homeassistant.util.logging")

    class ConfigEntry:
        pass

    class ConfigEntryState:
        LOADED = "loaded"
        SETUP_IN_PROGRESS = "setup_in_progress"

    class DeviceInfo(dict):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)

    class DataUpdateCoordinator:
        def __class_getitem__(cls, _item):
            return cls

        def __init__(self, *args, **kwargs):
            self.hass = args[0] if args else kwargs.get("hass")

    config_entries.ConfigEntry = ConfigEntry
    config_entries.ConfigEntryState = ConfigEntryState
    ha_const.EVENT_COMPONENT_LOADED = "component_loaded"
    device_registry.DeviceInfo = DeviceInfo
    device_registry.async_get = lambda hass: None
    entity_registry.async_get = lambda hass: None
    entity_registry.async_entries_for_device = lambda *args, **kwargs: ()
    update_coordinator.DataUpdateCoordinator = DataUpdateCoordinator
    util.dt = dt
    util.logging = util_logging
    util_logging.log_exception = lambda *args, **kwargs: None

    custom_components.__path__ = [str(REPO_ROOT / "custom_components")]
    eybond_local.__path__ = [str(REPO_ROOT / "custom_components" / "eybond_local")]
    runtime_package.__path__ = [
        str(REPO_ROOT / "custom_components" / "eybond_local" / "runtime")
    ]

    custom_components.eybond_local = eybond_local
    eybond_local.runtime = runtime_package
    homeassistant.components = components
    homeassistant.config_entries = config_entries
    homeassistant.const = ha_const
    homeassistant.helpers = helpers
    homeassistant.util = util
    components.persistent_notification = persistent_notification
    components.network = components_network
    components_network.util = components_network_util
    components_network_util.async_get_source_ip = lambda *args, **kwargs: "10.10.10.10"
    helpers.device_registry = device_registry
    helpers.entity_registry = entity_registry
    helpers.network = network
    helpers.update_coordinator = update_coordinator
    network.NoURLAvailableError = RuntimeError
    network.get_url = lambda *args, **kwargs: "http://127.0.0.1:8123"

    const = ensure_module("custom_components.eybond_local.const")
    const.CONF_COLLECTOR_IP = "collector_ip"
    const.CONF_ADVERTISED_SERVER_IP = "advertised_server_ip"
    const.CONF_ADVERTISED_TCP_PORT = "advertised_tcp_port"
    const.CONF_STRATEGY_TRANSITION_STATE = "connection_strategy_transition_state"
    const.CONF_COLLECTOR_CLOUD_FAMILY = "collector_cloud_family"
    const.CONF_COLLECTOR_OPERATION_MODE = "collector_operation_mode"
    const.CONF_COLLECTOR_ORIGINAL_SERVER_ENDPOINT = "collector_original_server_endpoint"
    const.CONF_COLLECTOR_ORIGINAL_SERVER_ENDPOINT_OBSERVED_AT = "collector_original_server_endpoint_observed_at"
    const.CONF_COLLECTOR_ORIGINAL_SERVER_ENDPOINT_PROFILE_KEY = "collector_original_server_endpoint_profile_key"
    const.CONF_COLLECTOR_ORIGINAL_SERVER_ENDPOINT_SOURCE = "collector_original_server_endpoint_source"
    const.CONF_COLLECTOR_PN = "collector_pn"
    const.CONF_COLLECTOR_CONFIRMED_SESSION_PROTOCOL = "collector_confirmed_session_protocol"
    const.CONF_COLLECTOR_CONFIRMED_SESSION_PROTOCOL_OBSERVED_AT = "collector_confirmed_session_protocol_observed_at"
    const.CONF_COLLECTOR_CONFIRMED_SESSION_PROTOCOL_PN = "collector_confirmed_session_protocol_pn"
    const.CONF_COLLECTOR_CONFIRMED_SESSION_PROTOCOL_SOURCE = "collector_confirmed_session_protocol_source"
    const.COLLECTOR_CONFIRMED_SESSION_PROTOCOL_SOURCE_LIVE = "live_session"
    const.CONF_CONNECTION_TYPE = "connection_type"
    const.CONF_CONNECTION_MODE = "connection_mode"
    const.CONF_ENTRY_ROLE = "entry_role"
    const.ENTRY_ROLE_LISTENER = "listener"
    const.CONF_CONTROL_MODE = "control_mode"
    const.CONF_DETECTED_MODEL = "detected_model"
    const.CONF_DETECTED_DRIVER = "detected_driver"
    const.CONF_DETECTED_SERIAL = "detected_serial"
    const.CONF_DETECTION_CONFIDENCE = "detection_confidence"
    const.CONF_DISCOVERY_INTERVAL = "discovery_interval"
    const.CONF_DISCOVERY_TARGET = "discovery_target"
    const.CONF_DRIVER_HINT = "driver_hint"
    const.CONF_DRIVER_DETECTION_STRATEGY = "driver_detection_strategy"
    const.DEFAULT_DRIVER_DETECTION_STRATEGY = "first_match"
    const.DRIVER_DETECTION_STRATEGIES = frozenset({"first_match", "full_scan"})
    const.CONF_HEARTBEAT_INTERVAL = "heartbeat_interval"
    const.CONF_POLL_INTERVAL = "poll_interval"
    const.CONF_POLL_MODE = "poll_mode"
    const.CONF_PROXY_CAPTURE_DURATION_MINUTES = "proxy_capture_duration_minutes"
    const.CONF_SERVER_IP = "server_ip"
    const.CONF_SMARTESS_COLLECTOR_VERSION = "smartess_collector_version"
    const.CONF_SMARTESS_DEVICE_ADDRESS = "smartess_device_address"
    const.CONF_SMARTESS_PROFILE_KEY = "smartess_profile_key"
    const.CONF_SMARTESS_PROTOCOL_ASSET_ID = "smartess_protocol_asset_id"
    const.CONF_TCP_PORT = "tcp_port"
    const.CONF_UDP_PORT = "udp_port"
    const.BUILTIN_SCHEMA_PREFIX = "builtin:"
    const.DEFAULT_COLLECTOR_IP = ""
    const.DEFAULT_COLLECTOR_OPERATION_MODE = "smartess_cloud_home_assistant"
    const.DEFAULT_CONTROL_MODE = "limited"
    const.DEFAULT_DISCOVERY_INTERVAL = 30
    const.DEFAULT_DISCOVERY_TARGET = ""
    const.DEFAULT_HEARTBEAT_INTERVAL = 30
    const.DEFAULT_POLL_INTERVAL = 30
    const.DEFAULT_POLL_MODE = "auto"
    const.DEFAULT_PROXY_CAPTURE_DURATION_MINUTES = 10
    const.DEFAULT_TCP_PORT = 8899
    const.DEFAULT_UDP_PORT = 48899
    const.COLLECTOR_OPERATION_CLOUD_AND_HA = "smartess_cloud_home_assistant"
    const.COLLECTOR_OPERATION_HA_ONLY = "home_assistant_only"
    const.CONTROL_MODE_AUTO = "auto"
    const.CONTROL_MODE_FULL = "full"
    const.CONTROL_MODE_READ_ONLY = "read_only"
    const.DOMAIN = "eybond_local"
    const.DRIVER_HINT_AUTO = "auto"
    const.POLL_MODE_AUTO = "auto"
    const.POLL_MODE_MANUAL = "manual"
    const.LOCAL_DIAGNOSTIC_RUNS_DIR = "diagnostic_runs"
    const.LOCAL_METADATA_DIR = "eybond_local"
    const.COLLECTOR_OPERATION_MODES = (
        "smartess_cloud_home_assistant",
        "home_assistant_only",
    )
    const.CONF_CONNECTION_STRATEGY = "connection_strategy"
    const.CONF_CONNECTION_STRATEGY_EVIDENCE = "connection_strategy_evidence"
    const.CONNECTION_STRATEGY_EVIDENCE_REBOOT_RECONNECT = "reboot_reconnect"
    const.CONNECTION_STRATEGY_EVIDENCE_CALLBACK_TRIGGER = "callback_trigger"
    const.CONNECTION_STRATEGY_EVIDENCE_USER_CONFIRMED_SESSION = "user_confirmed_session"
    const.CONNECTION_STRATEGY_INBOUND = "inbound"
    const.CONNECTION_STRATEGY_CALLBACK_ON_DEMAND = "callback_on_demand"
    const.CONNECTION_STRATEGIES = {"inbound", "callback_on_demand"}
    const.DEFAULT_CONNECTION_STRATEGY = "inbound"
    const.CONF_ENDPOINT_CONTROL_POLICY = "endpoint_control_policy"
    const.ENDPOINT_CONTROL_EXTERNAL = "external"
    const.ENDPOINT_CONTROL_INTEGRATION_MANAGED = "integration_managed"
    const.ENDPOINT_CONTROL_POLICIES = {"external", "integration_managed"}
    const.DEFAULT_ENDPOINT_CONTROL_POLICY = "external"
    const.CONF_PROXY_ENABLED = "proxy_enabled"
    const.DEFAULT_PROXY_ENABLED = False
    const.CONF_ENDPOINT_WRITTEN_VALUE = "endpoint_written_value"
    const.CONF_ENDPOINT_WRITTEN_AT = "endpoint_written_at"
    const.MAX_PROXY_CAPTURE_DURATION_MINUTES = 120
    const.MIN_PROXY_CAPTURE_DURATION_MINUTES = 1
    const.LOCAL_METADATA_DIR = "eybond_local"

    connection_models = ensure_module("custom_components.eybond_local.connection.models")
    connection_spec_factory = ensure_module(
        "custom_components.eybond_local.connection.spec_factory"
    )
    connection_spec_factory.build_connection_spec = lambda *args, **kwargs: None

    entity_scope = importlib.import_module(
        "custom_components.eybond_local.collector.entity_scope"
    )

    control_policy = ensure_module("custom_components.eybond_local.control_policy")
    control_policy.can_expose_capability = lambda *args, **kwargs: True
    control_policy.can_expose_preset = lambda *args, **kwargs: True
    control_policy.controls_enabled = lambda *args, **kwargs: True
    control_policy.controls_reason = lambda *args, **kwargs: ""
    control_policy.controls_summary = lambda *args, **kwargs: ""

    drivers_registry = ensure_module("custom_components.eybond_local.drivers.registry")
    # ensure_module() returns the REAL module when one is already imported, so
    # these doubles overwrite production functions on the live module object.
    # Record the originals once so the harness can put them back; without that,
    # every later test module sees a registry whose get_driver() always
    # returns None and whose support_marker() is a stub that never dispatches.
    _MUTATED_REGISTRY_ATTRS.setdefault("originals", {}).update(
        {
            name: getattr(drivers_registry, name)
            for name in ("get_driver", "all_write_capabilities", "support_marker")
            if name not in _MUTATED_REGISTRY_ATTRS.get("originals", {})
        }
    )
    drivers_registry.get_driver = lambda *args, **kwargs: None
    drivers_registry.all_write_capabilities = lambda *args, **kwargs: []
    # A realistic test double for the neutral policy resolver: mirrors what each
    # real driver declares via ``poll_policy_for`` (the coordinator only consumes
    # the resolved policy, so the double encodes the expected driver mapping).
    # The concrete policies now live in the driver modules; the neutral contract
    # exports only PollPolicy + DEFAULT, so the double builds the envelopes here.
    from custom_components.eybond_local.poll_policy import (
        DEFAULT_POLL_POLICY as _DEFAULT_POLL_POLICY,
        PollPolicy as _PollPolicy,
    )

    _SMG_POLICY = _PollPolicy(min_auto_interval=3.0, max_auto_interval=60.0)
    _FAST_POLICY = _PollPolicy(min_auto_interval=5.0, max_auto_interval=90.0)
    _PI30_POLICY = _PollPolicy(
        min_auto_interval=2.0, max_auto_interval=120.0, min_manual_interval=2.0
    )
    _STUB_DRIVER_POLICIES = {
        "modbus_smg": _SMG_POLICY,
        "srne_modbus": _FAST_POLICY,
        "must_pv_ph18": _FAST_POLICY,
        "smartess_local": _FAST_POLICY,
        # eybond_g_ascii / pi18 inherit the neutral default (ASCII == DEFAULT).
        "eybond_g_ascii": _DEFAULT_POLL_POLICY,
        "pi18": _DEFAULT_POLL_POLICY,
        "pi30": _PI30_POLICY,
    }
    drivers_registry.poll_policy_for_driver_key = (
        lambda driver_key="", inverter=None: _STUB_DRIVER_POLICIES.get(
            str(driver_key or "").strip(), _DEFAULT_POLL_POLICY
        )
    )
    def _serial_is_stable(driver_key="", inverter=None):
        if str(getattr(inverter, "variant_key", "") or "").strip() == "smartess_0925":
            return False
        details = getattr(inverter, "details", {})
        if str(driver_key or "").strip() == "pi30" and isinstance(details, dict):
            trust = details.get("serial_identity_trust")
            if trust is not None:
                return bool(
                    str(getattr(inverter, "serial_number", "") or "").strip()
                    and trust == "trusted"
                )
        return True

    drivers_registry.serial_is_stable = _serial_is_stable
    # Neutral support-marker resolver double: the coordinator only projects the
    # driver's verdict, so the double returns no special marker.
    drivers_registry.support_marker = (
        lambda driver_key="", variant_key="", profile_name="": None
    )

    fixtures_utils = ensure_module("custom_components.eybond_local.fixtures.utils")
    fixtures_utils.anonymize_fixture_json = lambda *args, **kwargs: None
    fixtures_utils.build_command_fixture_responses = lambda *args, **kwargs: None

    effective_metadata = ensure_module(
        "custom_components.eybond_local.metadata.effective_metadata"
    )
    effective_metadata.resolve_effective_metadata_selection = (
        lambda *args, **kwargs: None
    )

    local_metadata = ensure_module("custom_components.eybond_local.metadata.local_metadata")
    local_metadata.clear_local_metadata_loader_caches = lambda *args, **kwargs: None
    local_metadata.create_local_profile_draft = lambda *args, **kwargs: None
    local_metadata.create_local_schema_draft = lambda *args, **kwargs: None
    local_metadata.rollback_local_metadata_overrides = lambda *args, **kwargs: None

    smartess_draft = ensure_module("custom_components.eybond_local.metadata.smartess_draft")

    class SmartEssKnownFamilyDraftPlan:
        pass

    smartess_draft.SmartEssKnownFamilyDraftPlan = SmartEssKnownFamilyDraftPlan
    smartess_draft.create_smartess_known_family_draft = lambda *args, **kwargs: None
    smartess_draft.resolve_smartess_known_family_draft_plan = (
        lambda *args, **kwargs: None
    )

    smartess_smg_bridge = ensure_module(
        "custom_components.eybond_local.metadata.smartess_smg_bridge"
    )

    class SmartEssSmgBridgePlan:
        pass

    smartess_smg_bridge.SmartEssSmgBridgePlan = SmartEssSmgBridgePlan
    smartess_smg_bridge.create_smartess_smg_bridge_draft = lambda *args, **kwargs: None
    smartess_smg_bridge.resolve_smartess_smg_bridge_plan = (
        lambda *args, **kwargs: None
    )

    models = ensure_module("custom_components.eybond_local.models")

    class CapabilityChoice:
        pass

    class CapabilityCondition:
        pass

    class CapabilityGroup:
        pass

    class CapabilityPreset:
        pass

    class CapabilityPresetItem:
        pass

    class CapabilityRecommendation:
        pass

    class BinarySensorDescription:
        pass

    class MeasurementDescription:
        pass

    class RegisterValueSpec:
        pass

    class WriteCapability:
        pass

    class ProbeTarget:
        def __init__(self, devcode=0, collector_addr=0, device_addr=0):
            self.devcode = devcode
            self.collector_addr = collector_addr
            self.device_addr = device_addr

        @property
        def link_route(self):
            from custom_components.eybond_local.link_models import EybondLinkRoute

            return EybondLinkRoute(
                devcode=self.devcode,
                collector_addr=self.collector_addr,
            )

    class DetectedInverter:
        def __init__(
            self,
            *,
            driver_key,
            protocol_family,
            model_name,
            serial_number,
            probe_target,
            variant_key="default",
            details=None,
            profile_name="",
            register_schema_name="",
            capability_groups=(),
            capabilities=(),
            capability_presets=(),
        ):
            self.driver_key = driver_key
            self.protocol_family = protocol_family
            self.model_name = model_name
            self.serial_number = serial_number
            self.probe_target = probe_target
            self.variant_key = variant_key
            self.details = details or {}
            self.profile_name = profile_name
            self.register_schema_name = register_schema_name
            self.capability_groups = capability_groups
            self.capabilities = capabilities
            self.capability_presets = capability_presets

    class RuntimeSnapshot:
        def __init__(self, values=None, inverter=None, collector=None, connected=True):
            self.values = values or {}
            self.inverter = inverter
            self.collector = collector
            self.connected = connected

        @property
        def collector_server_endpoint(self):
            candidate = getattr(self.collector, "collector_server_endpoint", "")
            return candidate or self.values.get("collector_server_endpoint", "")

        def set_collector_server_endpoint(self, endpoint):
            if self.collector is not None:
                self.collector.collector_server_endpoint = endpoint
            if endpoint:
                self.values["collector_server_endpoint"] = endpoint
            else:
                self.values.pop("collector_server_endpoint", None)

        @property
        def collector_cloud_profile(self):
            key = getattr(self.collector, "collector_cloud_profile_key", "")
            key = key or getattr(self.collector, "smartess_protocol_profile_key", "")
            if not key:
                key = self.values.get("collector_cloud_profile_key", "")
            if not key:
                key = self.values.get("smartess_protocol_profile_key", "")
            if not key:
                return CollectorCloudProfile()
            return CollectorCloudProfile(
                key=key,
                label=(
                    getattr(self.collector, "collector_cloud_profile_label", "")
                    or getattr(self.collector, "smartess_protocol_name", "")
                    or getattr(self.collector, "smartess_protocol_asset_name", "")
                    or self.values.get("collector_cloud_profile_label", "")
                    or self.values.get("smartess_protocol_name", "")
                ),
                source=(
                    getattr(self.collector, "collector_cloud_profile_source", "")
                    or self.values.get("collector_cloud_profile_source", "")
                    or "runtime_observed"
                ),
                confidence=(
                    getattr(self.collector, "collector_cloud_profile_confidence", "")
                    or self.values.get("collector_cloud_profile_confidence", "")
                    or "high"
                ),
            )

        def set_collector_cloud_profile(self, profile):
            if self.collector is not None:
                self.collector.collector_cloud_profile_key = profile.key
                self.collector.collector_cloud_profile_label = profile.label
                self.collector.collector_cloud_profile_source = profile.source
                self.collector.collector_cloud_profile_confidence = profile.confidence
            for key, value in {
                "collector_cloud_profile_key": profile.key,
                "collector_cloud_profile_label": profile.label,
                "collector_cloud_profile_source": profile.source,
                "collector_cloud_profile_confidence": profile.confidence,
            }.items():
                if value:
                    self.values[key] = value
                else:
                    self.values.pop(key, None)

    class CollectorInfo:
        collector_server_endpoint = ""

    class CollectorCloudProfile:
        def __init__(self, key="", label="", source="", confidence=""):
            self.key = key
            self.label = label
            self.source = source
            self.confidence = confidence

        @property
        def known(self):
            return bool(self.key)

    models.CollectorInfo = CollectorInfo
    models.CollectorCloudProfile = CollectorCloudProfile
    models.CapabilityChoice = CapabilityChoice
    models.CapabilityCondition = CapabilityCondition
    models.CapabilityGroup = CapabilityGroup
    models.CapabilityPreset = CapabilityPreset
    models.CapabilityPresetItem = CapabilityPresetItem
    models.CapabilityRecommendation = CapabilityRecommendation
    models.BinarySensorDescription = BinarySensorDescription
    models.DetectedInverter = DetectedInverter
    models.MeasurementDescription = MeasurementDescription
    models.ProbeTarget = ProbeTarget
    models.RegisterValueSpec = RegisterValueSpec
    models.RuntimeSnapshot = RuntimeSnapshot
    models.WriteCapability = WriteCapability
    models.decimals_for_divisor = lambda _divisor: 0

    runtime_factory = ensure_module("custom_components.eybond_local.runtime.factory")
    runtime_factory.create_runtime_manager = lambda *args, **kwargs: None

    runtime_manager = ensure_module("custom_components.eybond_local.runtime.manager")

    class RuntimeManager:
        pass

    runtime_manager.RuntimeManager = RuntimeManager

    schema = ensure_module("custom_components.eybond_local.schema")
    schema.build_runtime_ui_schema = lambda *args, **kwargs: None
    schema.capability_write_exposure_allowed = lambda *args, **kwargs: True
    schema.preset_write_exposure_allowed = lambda *args, **kwargs: True

    support_bundle = ensure_module("custom_components.eybond_local.support.bundle")
    support_bundle.build_support_bundle_payload = lambda *args, **kwargs: None
    support_bundle.export_support_bundle = lambda *args, **kwargs: None

    support_cloud = ensure_module("custom_components.eybond_local.support.cloud_evidence")
    support_cloud.infer_evidence_provider = lambda payload: (
        str((payload or {}).get("provider") or "").strip().lower()
        if isinstance(payload, dict)
        else ""
    )
    support_cloud.fetch_and_export_smartess_device_bundle_cloud_evidence = (
        lambda *args, **kwargs: None
    )
    support_cloud.fetch_and_export_valuecloud_device_bundle_cloud_evidence = (
        lambda *args, **kwargs: None
    )
    support_cloud.load_latest_cloud_evidence = lambda *args, **kwargs: None

    class _CloudEvidenceRecord:  # minimal stand-in for the neutral provider module
        def __init__(self, path="", payload=None) -> None:
            self.path = path
            self.payload = payload

    support_cloud.CloudEvidenceRecord = _CloudEvidenceRecord

    support_package = ensure_module("custom_components.eybond_local.support.package")
    support_package.export_support_package = lambda *args, **kwargs: None
    support_package.support_packages_root = (
        lambda config_dir: Path(config_dir) / "eybond_local" / "support_packages"
    )

    support_proxy_capture = ensure_module(
        "custom_components.eybond_local.support.proxy_capture"
    )
    support_proxy_capture.PROXY_WIRE_TRANSPARENT = "transparent"
    support_proxy_capture.build_proxy_capture_overview = lambda *args, **kwargs: None
    support_proxy_capture.proxy_capture_overview_values = proxy_capture_overview_values
    support_proxy_capture.resolve_proxy_wire_mode = (
        lambda collector, cloud: (
            "transparent" if collector and cloud in {"at_text", "eybond_framed"} else ""
        )
    )

    support_proxy_session = ensure_module(
        "custom_components.eybond_local.support.proxy_capture.session"
    )
    support_proxy_session.build_proxy_capture_command = lambda *args, **kwargs: []
    support_proxy_session.build_proxy_capture_restore_trigger_path = (
        lambda *args, **kwargs: None
    )
    support_proxy_session.build_proxy_capture_trace_path = (
        lambda *args, **kwargs: None
    )
    support_proxy_session.inspect_proxy_capture_start_status = (
        lambda *args, **kwargs: {}
    )
    support_proxy_session.inspect_proxy_capture_trace = lambda *args, **kwargs: {}
    support_proxy_session.open_proxy_trace_output_file = lambda path: None
    support_proxy_session.summarize_proxy_capture_trace = (
        lambda *args, **kwargs: {}
    )

    support_proxy_trace = ensure_module(
        "custom_components.eybond_local.support.proxy_capture.trace"
    )
    support_proxy_trace.build_proxy_capture_lease_deadline = (
        lambda *args, **kwargs: "2026-04-28T12:10:00+00:00"
    )
    support_proxy_trace.build_proxy_capture_session_state = (
        lambda *args, **kwargs: None
    )
    support_proxy_trace.build_proxy_trace_manifest = lambda *args, **kwargs: {}
    support_proxy_trace.clear_proxy_capture_session_state = (
        lambda *args, **kwargs: None
    )
    support_proxy_trace.export_proxy_trace_bundle = lambda *args, **kwargs: None
    support_proxy_trace.export_proxy_trace_manifest = lambda *args, **kwargs: None
    support_proxy_trace.load_latest_proxy_trace_manifest = (
        lambda *args, **kwargs: None
    )
    support_proxy_trace.load_proxy_capture_session_state = (
        lambda *args, **kwargs: None
    )
    support_proxy_trace.parse_proxy_capture_session_timestamp = (
        lambda *args, **kwargs: None
    )
    support_proxy_trace.proxy_capture_restore_guard_reason = (
        lambda *args, **kwargs: ""
    )
    support_proxy_trace.proxy_capture_session_is_active = (
        lambda state: bool(state)
    )
    support_proxy_trace.proxy_capture_session_is_expired = (
        lambda *args, **kwargs: False
    )
    support_proxy_trace.proxy_trace_root = (
        lambda config_dir: Path(config_dir) / "eybond_local" / "proxy_traces"
    )
    support_proxy_trace.refresh_proxy_capture_session_lease = (
        lambda state, **kwargs: state
    )
    support_proxy_trace.save_proxy_capture_session_state = (
        lambda *args, **kwargs: None
    )

    support_shadow_backend = ensure_module(
        "custom_components.eybond_local.support.shadow_learning.backend"
    )
    support_shadow_backend.build_shadow_learning_preflight = (
        lambda *args, **kwargs: types.SimpleNamespace(can_start=True, blockers=[])
    )
    support_shadow_backend.build_shadow_learning_seed = (
        lambda *args, **kwargs: (types.SimpleNamespace(write_response_mode="exception"), [])
    )
    support_shadow_backend.build_shadow_learning_trace_path = (
        lambda *args, **kwargs: Path("/tmp/shadow-learning.jsonl")
    )

    support_shadow_proxy = ensure_module(
        "custom_components.eybond_local.support.shadow_learning.proxy"
    )
    support_shadow_proxy.route_status_indicates_control_ready = (
        lambda status: bool(status.get("collector_connected"))
        and (
            bool(status.get("ready"))
            or bool(status.get("route_protocol_activity"))
            or bool(status.get("collector_protocol_ingress"))
        )
    )

    support_shadow_session = ensure_module(
        "custom_components.eybond_local.support.shadow_learning.session"
    )
    support_shadow_session.build_shadow_learning_lease_deadline = (
        lambda *args, **kwargs: "2026-06-05T12:20:00+00:00"
    )
    support_shadow_session.build_shadow_learning_session_state = (
        lambda **kwargs: types.SimpleNamespace(
            **{
                "route_owner_id": "",
                "expires_at": "",
                "restore_attempt_count": 0,
                "last_restore_attempt_at": "",
                "last_restore_error": "",
                "status": "",
                **kwargs,
            }
        )
    )
    support_shadow_session.clear_shadow_learning_session_state = (
        lambda *args, **kwargs: None
    )
    support_shadow_session.load_shadow_learning_session_state = (
        lambda *args, **kwargs: None
    )
    support_shadow_session.save_shadow_learning_session_state = (
        lambda *args, **kwargs: None
    )
    support_shadow_session.shadow_learning_session_is_active = (
        lambda state: bool(state) and str(getattr(state, "status", "")) in {
            "preflight",
            "starting",
            "waiting_for_collector",
            "connecting_upstream",
            "ready",
            "learning",
            "degraded",
            "restoring",
        }
    )
    support_shadow_session.shadow_learning_session_is_expired = (
        lambda *args, **kwargs: False
    )
    support_shadow_session.shadow_learning_session_timestamp = (
        lambda: "2026-06-05T12:00:00+00:00"
    )

    support_workflow = ensure_module("custom_components.eybond_local.support.workflow")
    support_workflow.build_support_workflow_state = lambda *args, **kwargs: {}

    support_diagnostic_export = ensure_module(
        "custom_components.eybond_local.support.diagnostic_export"
    )
    support_diagnostic_export.export_diagnostic_run = lambda *args, **kwargs: None

    support_diagnostic_runner = ensure_module(
        "custom_components.eybond_local.support.diagnostic_runner"
    )

    @dataclasses.dataclass
    class DiagnosticRuntimeContext:
        transport: object | None = None

    @dataclasses.dataclass
    class DiagnosticRunResult:
        success: bool
        output: str
        results: list
        context: dict
        started_at: str
        finished_at: str
        error: str | None = None

    class DiagnosticSingleFlight:
        def __init__(self, **_kwargs) -> None:
            pass

        @property
        def running(self) -> bool:
            return False

        async def cancel(self) -> None:
            return None

        async def run(self, factory, **_kwargs):
            return await factory()

    async def run_scenario(*_args, **_kwargs):
        return DiagnosticRunResult(True, "", [], {}, "", "")

    support_diagnostic_runner.DiagnosticRuntimeContext = DiagnosticRuntimeContext
    support_diagnostic_runner.DiagnosticRunResult = DiagnosticRunResult
    support_diagnostic_runner.DiagnosticSingleFlight = DiagnosticSingleFlight
    support_diagnostic_runner.run_scenario = run_scenario

# Production attributes this harness overwrites on the real drivers.registry
# module. Captured on first use and restored in tearDownClass.
_MUTATED_REGISTRY_ATTRS: dict[str, dict[str, object]] = {}


def _restore_mutated_registry() -> None:
    """Put back the real drivers.registry functions this harness replaced."""

    registry = sys.modules.get("custom_components.eybond_local.drivers.registry")
    originals = _MUTATED_REGISTRY_ATTRS.get("originals") or {}
    if registry is None:
        return
    for name, value in originals.items():
        setattr(registry, name, value)


_STUBBED_MODULE_NAMES: tuple[str, ...] = (
    "custom_components",
    "custom_components.eybond_local",
    "custom_components.eybond_local.runtime",
    "custom_components.eybond_local.runtime.shadow_learning_facade",
    "custom_components.eybond_local.const",
    "custom_components.eybond_local.connection.models",
    "custom_components.eybond_local.collector.entity_scope",
    "custom_components.eybond_local.control_policy",
    "custom_components.eybond_local.drivers.registry",
    "custom_components.eybond_local.fixtures.utils",
    "custom_components.eybond_local.metadata.effective_metadata",
    "custom_components.eybond_local.metadata.local_metadata",
    "custom_components.eybond_local.metadata.smartess_draft",
    "custom_components.eybond_local.metadata.smartess_smg_bridge",
    "custom_components.eybond_local.models",
    "custom_components.eybond_local.runtime.factory",
    "custom_components.eybond_local.runtime.manager",
    "custom_components.eybond_local.schema",
    "custom_components.eybond_local.support.bundle",
    "custom_components.eybond_local.support.cloud_evidence",
    "custom_components.eybond_local.support.diagnostic_export",
    "custom_components.eybond_local.support.diagnostic_runner",
    "custom_components.eybond_local.support.package",
    "custom_components.eybond_local.support.proxy_capture",
    "custom_components.eybond_local.support.proxy_capture.session",
    "custom_components.eybond_local.support.proxy_capture.trace",
    "custom_components.eybond_local.support.shadow_learning",
    "custom_components.eybond_local.support.shadow_learning.backend",
    "custom_components.eybond_local.support.shadow_learning.proxy",
    "custom_components.eybond_local.support.shadow_learning.runtime",
    "custom_components.eybond_local.support.shadow_learning.session",
    "custom_components.eybond_local.support.workflow",
    "custom_components.eybond_local.runtime.coordinator",
    "homeassistant",
    "homeassistant.components",
    "homeassistant.components.network",
    "homeassistant.components.network.util",
    "homeassistant.components.persistent_notification",
    "homeassistant.config_entries",
    "homeassistant.helpers",
    "homeassistant.helpers.device_registry",
    "homeassistant.helpers.network",
    "homeassistant.helpers.update_coordinator",
    "homeassistant.util",
    "homeassistant.util.dt",
    "homeassistant.util.logging",
)


class FakeDevice:
    def __init__(self, device_id: str, identifiers: set[tuple[str, str]]) -> None:
        self.id = device_id
        self.identifiers = identifiers
        self.name = None
        self.model = None
        self.manufacturer = None
        self.serial_number = None
        self.sw_version = None
        self.hw_version = None
        self.via_device_id = None
        self.config_entries: set[str] = set()
        self.name_by_user = None


class FakeRegistry:
    def __init__(self) -> None:
        self._devices_by_key: dict[frozenset[tuple[str, str]], FakeDevice] = {}
        self._counter = 0
        self.removed_device_ids: list[str] = []

    @property
    def devices(self):
        return {device.id: device for device in self._devices_by_key.values()}

    def async_get_device(self, identifiers=None, connections=None):
        del connections
        if not identifiers:
            return None
        return self._devices_by_key.get(frozenset(identifiers))

    def async_get_or_create(self, config_entry_id=None, **info):
        identifiers = set(info.get("identifiers") or set())
        key = frozenset(identifiers)
        device = self._devices_by_key.get(key)
        if device is None:
            self._counter += 1
            device = FakeDevice(f"device-{self._counter}", identifiers)
            self._devices_by_key[key] = device

        if type(config_entry_id) is str and config_entry_id:
            device.config_entries.add(config_entry_id)

        device.name = info.get("name")
        device.model = info.get("model")
        device.manufacturer = info.get("manufacturer")
        device.serial_number = info.get("serial_number")
        device.sw_version = info.get("sw_version")
        device.hw_version = info.get("hw_version")

        via_device = info.get("via_device")
        if via_device is not None:
            parent = self.async_get_device(identifiers={via_device})
            device.via_device_id = None if parent is None else parent.id

        return device

    def async_update_device(self, device_id, **kwargs):
        for device in self._devices_by_key.values():
            if device.id != device_id:
                continue
            for key, value in kwargs.items():
                if hasattr(device, key):
                    setattr(device, key, value)
            return device
        return None

    def async_remove_device(self, device_id: str) -> bool:
        for key, device in list(self._devices_by_key.items()):
            if device.id != device_id:
                continue
            self.removed_device_ids.append(device_id)
            del self._devices_by_key[key]
            return True
        return False




class CoordinatorDeviceHierarchyTests(unittest.TestCase):
    def test_remember_collector_server_endpoint_writes_registry_by_pn(self) -> None:
        from custom_components.eybond_local.support.collector_registry import (
            get_collector_registry_record,
        )

        async def _run() -> None:
            with tempfile.TemporaryDirectory() as tmp:
                updated_options: list[dict[str, str]] = []

                async def _async_add_executor_job(func, *args):
                    return func(*args)

                coordinator = object.__new__(self.coordinator_module.EybondLocalCoordinator)
                coordinator.hass = types.SimpleNamespace(
                    config=types.SimpleNamespace(config_dir=tmp),
                    async_add_executor_job=_async_add_executor_job,
                )
                coordinator._async_update_entry_without_reload = lambda **kwargs: updated_options.append(
                    kwargs["options"]
                )
                coordinator._connection_spec = types.SimpleNamespace(
                    effective_advertised_server_ip="192.168.1.50",
                    effective_advertised_tcp_port=8899,
                )
                coordinator._runtime = types.SimpleNamespace(
                    collector_server_endpoint_rollback_target="",
                )
                coordinator._remembered_collector_server_endpoint = ""
                coordinator.config_entry = types.SimpleNamespace(
                    data={},
                    options={},
                )
                snapshot = self.RuntimeSnapshot(
                    collector=types.SimpleNamespace(
                        collector_pn="PN12345",
                        remote_ip="192.168.1.55",
                    ),
                    values={"collector_server_endpoint": "dtu_ess.eybond.com,18899,TCP"},
                )

                await coordinator._async_remember_collector_server_endpoint(snapshot)

                record = get_collector_registry_record(
                    config_dir=Path(tmp),
                    collector_pn="PN12345",
                )
                self.assertIsNotNone(record)
                assert record is not None
                self.assertEqual(record.original_endpoint_raw, "dtu_ess.eybond.com,18899,TCP")
                self.assertEqual(record.cloud_profile_key, "smartess_at")
                self.assertEqual(record.source, "runtime_observed")
                self.assertEqual(record.last_seen_ip, "192.168.1.55")

        import asyncio

        asyncio.run(_run())

    def test_host_only_external_endpoint_is_preserved_for_rollback_and_bind_shape(self) -> None:
        coordinator = object.__new__(self.coordinator_module.EybondLocalCoordinator)
        coordinator._connection_spec = types.SimpleNamespace(
            effective_advertised_server_ip="192.168.1.50",
            effective_advertised_tcp_port=8899,
        )
        coordinator._runtime = types.SimpleNamespace(
            collector_server_endpoint_rollback_target="ess.eybond.com",
        )
        coordinator._remembered_collector_server_endpoint = ""
        coordinator.config_entry = types.SimpleNamespace(data={}, options={})
        coordinator.data = self.RuntimeSnapshot(
            values={"collector_server_endpoint": "ess.eybond.com"}
        )

        self.assertEqual(coordinator.collector_server_endpoint_rollback_target, "ess.eybond.com")
        self.assertEqual(coordinator.collector_callback_target_endpoint, "192.168.1.50")
        self.assertEqual(coordinator.proxy_capture_target_endpoint, "192.168.1.50")

    def test_host_only_endpoint_shape_exposes_implicit_legacy_port(self) -> None:
        coordinator = object.__new__(self.coordinator_module.EybondLocalCoordinator)
        coordinator._connection_spec = types.SimpleNamespace(
            effective_advertised_server_ip="192.168.1.50",
            effective_advertised_tcp_port=8899,
        )
        coordinator._runtime = types.SimpleNamespace(
            collector_server_endpoint_rollback_target="ess.eybond.com",
        )
        coordinator._remembered_collector_server_endpoint = ""
        coordinator.config_entry = types.SimpleNamespace(
            data={"collector_cloud_family": "legacy_binary"}, options={}
        )
        coordinator.data = self.RuntimeSnapshot(
            values={"collector_server_endpoint": "192.168.1.50"}
        )

        shape = coordinator.collector_endpoint_write_shape

        self.assertEqual(shape.write_format, "host_only")
        self.assertEqual(shape.fixed_port, 502)
        self.assertTrue(shape.port_is_fixed)

    def test_prepare_listener_uses_legacy_port_for_host_only_family(self) -> None:
        listener_ports: list[int] = []

        async def _ensure_listener(port: int) -> None:
            listener_ports.append(port)

        coordinator = object.__new__(self.coordinator_module.EybondLocalCoordinator)
        coordinator._connection_spec = types.SimpleNamespace(
            effective_advertised_server_ip="192.168.1.50",
            effective_advertised_tcp_port=8899,
        )
        coordinator._runtime = types.SimpleNamespace(
            effective_advertised_server_ip="192.168.1.50",
            collector_server_endpoint_rollback_target="",
            async_ensure_callback_listener=_ensure_listener,
        )
        coordinator._remembered_collector_server_endpoint = ""
        coordinator.config_entry = types.SimpleNamespace(data={}, options={})
        coordinator.data = self.RuntimeSnapshot(
            values={"collector_server_endpoint": "ess.eybond.com"}
        )

        asyncio.run(
            coordinator._async_prepare_home_assistant_callback_listener(
                coordinator.collector_callback_target_endpoint
            )
        )

        self.assertEqual(coordinator.collector_callback_target_endpoint, "192.168.1.50")
        self.assertEqual(listener_ports, [502])

    def test_legacy_mode_lock_clears_after_reconnect_without_endpoint_readback(self) -> None:
        async def _run() -> None:
            listener_ports: list[int] = []

            async def _ensure_listener(port: int) -> None:
                listener_ports.append(port)

            coordinator = object.__new__(self.coordinator_module.EybondLocalCoordinator)
            coordinator._connection_spec = types.SimpleNamespace(
                effective_advertised_server_ip="192.168.1.50",
                effective_advertised_tcp_port=8899,
            )
            coordinator._runtime = types.SimpleNamespace(
                effective_advertised_server_ip="192.168.1.50",
                collector_server_endpoint_rollback_target="ess.eybond.com",
                async_ensure_callback_listener=_ensure_listener,
            )
            coordinator._remembered_collector_server_endpoint = ""
            coordinator._collector_operation_pending_target_endpoint = "192.168.1.50"
            coordinator.config_entry = types.SimpleNamespace(
                data={},
                options={
                    "collector_operation_mode": "home_assistant_only",
                    # The automatic endpoint reconcile only runs when the
                    # integration manages the endpoint (it previously wrote it).
                    "endpoint_control_policy": "integration_managed",
                },
            )

            disconnected_snapshot = self.RuntimeSnapshot(
                connected=False,
                values={"collector_server_endpoint": "192.168.1.50"},
            )
            coordinator.data = disconnected_snapshot

            await coordinator._async_reconcile_managed_collector_endpoint(
                disconnected_snapshot
            )

            self.assertEqual(
                disconnected_snapshot.values["collector_operation_endpoint_sync_status"],
                "waiting_for_collector",
            )
            self.assertEqual(
                coordinator._collector_operation_pending_target_endpoint,
                "192.168.1.50",
            )

            connected_snapshot = self.RuntimeSnapshot(connected=True, values={})
            coordinator.data = connected_snapshot

            await coordinator._async_reconcile_managed_collector_endpoint(
                connected_snapshot
            )

            self.assertEqual(connected_snapshot.values["collector_server_endpoint"], "192.168.1.50")
            self.assertEqual(
                connected_snapshot.values["collector_operation_endpoint_sync_status"],
                "aligned",
            )
            self.assertEqual(coordinator._collector_operation_pending_target_endpoint, "")
            self.assertEqual(listener_ports, [502, 502])

        asyncio.run(_run())

    def test_reconcile_integration_managed_aligns_to_ha_regardless_of_operation_mode(self) -> None:
        # Phase 5: the reconcile targets Home Assistant purely from
        # endpoint_control_policy=integration_managed. The legacy operation mode
        # (here the legacy cloud+HA mode) is no longer consulted, and the endpoint is never
        # auto-restored to the previous/cloud endpoint here.
        async def _run() -> None:
            endpoint_writes: list[str] = []

            async def _ensure_listener(port: int) -> None:
                return None

            async def _set_endpoint(endpoint: str, *, apply_changes: bool = True):
                endpoint_writes.append(endpoint)
                return {"readback_endpoint": endpoint, "status": "applied"}

            coordinator = object.__new__(self.coordinator_module.EybondLocalCoordinator)
            coordinator._connection_spec = types.SimpleNamespace(
                effective_advertised_server_ip="192.168.1.50",
                effective_advertised_tcp_port=8899,
            )
            coordinator._runtime = types.SimpleNamespace(
                effective_advertised_server_ip="192.168.1.50",
                collector_server_endpoint_rollback_target="203.0.113.9,18899,TCP",
                async_ensure_callback_listener=_ensure_listener,
                async_set_collector_server_endpoint=_set_endpoint,
            )
            coordinator._remembered_collector_server_endpoint = ""
            coordinator._collector_operation_pending_target_endpoint = ""
            coordinator._ha_primary_reconcile_last_signature = None
            coordinator._ha_primary_reconcile_last_attempt_monotonic = 0.0
            coordinator.config_entry = types.SimpleNamespace(
                entry_id="entry-reconcile",
                data={},
                options={
                    # Legacy cloud-primary mode: must NOT drive the reconcile.
                    "collector_operation_mode": "smartess_cloud_home_assistant",
                    "endpoint_control_policy": "integration_managed",
                },
            )
            snapshot = self.RuntimeSnapshot(
                connected=True,
                values={"collector_server_endpoint": "203.0.113.9,18899,TCP"},
            )
            coordinator.data = snapshot

            await coordinator._async_reconcile_managed_collector_endpoint(snapshot)

            # It wrote the Home Assistant endpoint, not restored to the previous.
            self.assertEqual(len(endpoint_writes), 1)
            self.assertIn("192.168.1.50", endpoint_writes[0])
            self.assertNotIn("203.0.113.9", endpoint_writes[0])

        asyncio.run(_run())

    def test_reconcile_external_never_writes_endpoint(self) -> None:
        # Phase 5: endpoint_control_policy=external must never auto-write/restore.
        async def _run() -> None:
            wrote = False

            async def _set_endpoint(endpoint: str, *, apply_changes: bool = True):
                nonlocal wrote
                wrote = True
                return {"readback_endpoint": endpoint, "status": "applied"}

            coordinator = object.__new__(self.coordinator_module.EybondLocalCoordinator)
            coordinator._connection_spec = types.SimpleNamespace(
                effective_advertised_server_ip="192.168.1.50",
                effective_advertised_tcp_port=8899,
            )
            coordinator._runtime = types.SimpleNamespace(
                effective_advertised_server_ip="192.168.1.50",
                collector_server_endpoint_rollback_target="203.0.113.9,18899,TCP",
                async_set_collector_server_endpoint=_set_endpoint,
            )
            coordinator._collector_operation_pending_target_endpoint = "stale"
            coordinator.config_entry = types.SimpleNamespace(
                data={},
                options={"endpoint_control_policy": "external"},
            )
            snapshot = self.RuntimeSnapshot(
                connected=True,
                values={"collector_server_endpoint": "192.168.1.50,8899,TCP"},
            )
            coordinator.data = snapshot

            await coordinator._async_reconcile_managed_collector_endpoint(snapshot)

            self.assertFalse(wrote)
            self.assertEqual(
                snapshot.values["collector_operation_endpoint_sync_status"],
                "external_not_managed",
            )
            self.assertEqual(coordinator._collector_operation_pending_target_endpoint, "")

        asyncio.run(_run())

    def test_setup_prepares_listener_from_connection_axes_not_operation_mode(self) -> None:
        # Phase 5: listener preparation is runtime behavior and must follow the
        # explicit connection axes. A legacy cloud-primary operation mode must
        # not suppress the listener for an inbound entry.
        async def _run() -> None:
            listener_ports: list[int] = []
            started: list[bool] = []

            async def _async_start() -> None:
                started.append(True)

            async def _ensure_listener(port: int) -> None:
                listener_ports.append(port)

            async def _noop_async(*_args, **_kwargs) -> None:
                return None

            coordinator = object.__new__(self.coordinator_module.EybondLocalCoordinator)
            coordinator._connection_spec = types.SimpleNamespace(
                effective_advertised_server_ip="192.168.1.50",
                effective_advertised_tcp_port=18899,
            )
            coordinator._runtime = types.SimpleNamespace(
                effective_advertised_server_ip="192.168.1.50",
                async_start=_async_start,
                async_ensure_callback_listener=_ensure_listener,
            )
            coordinator.config_entry = types.SimpleNamespace(
                data={},
                options={
                    "collector_operation_mode": "smartess_cloud_home_assistant",
                    "connection_strategy": "inbound",
                    "endpoint_control_policy": "external",
                },
            )
            coordinator.data = self.RuntimeSnapshot(
                values={"collector_server_endpoint": "203.0.113.9,18899,TCP"}
            )
            coordinator._configure_reverse_discovery_mode = lambda: None
            coordinator._configure_callback_ownership = lambda: None
            coordinator._async_recover_proxy_capture_state = _noop_async
            coordinator._async_recover_shadow_learning_state = _noop_async
            coordinator._async_warm_smartess_cloud_evidence_cache = _noop_async
            coordinator._async_warm_effective_metadata_cache = _noop_async

            await coordinator.async_setup()

            self.assertEqual(started, [True])
            self.assertEqual(listener_ports, [18899])

        asyncio.run(_run())

    def test_shadow_learning_blocks_cloud_mode_endpoint_restore_reconcile(self) -> None:
        async def _run() -> None:
            set_endpoint_calls: list[tuple[str, bool]] = []

            async def _async_set_collector_server_endpoint(
                endpoint: str, *, apply_changes: bool = True
            ) -> dict[str, object]:
                set_endpoint_calls.append((endpoint, apply_changes))
                return {"readback_endpoint": endpoint, "status": "applied"}

            async def _async_active_shadow_learning_state(*, require_process: bool = True):
                self.assertFalse(require_process)
                return types.SimpleNamespace(status="learning")

            coordinator = object.__new__(self.coordinator_module.EybondLocalCoordinator)
            coordinator._connection_spec = types.SimpleNamespace(
                effective_advertised_server_ip="192.168.1.50",
                effective_advertised_tcp_port=8899,
            )
            coordinator._runtime = types.SimpleNamespace(
                effective_advertised_server_ip="192.168.1.50",
                collector_server_endpoint_rollback_target="dtu_ess.eybond.com,18899,TCP",
                async_set_collector_server_endpoint=_async_set_collector_server_endpoint,
            )
            coordinator._collector_operation_pending_target_endpoint = ""
            coordinator._remembered_collector_server_endpoint = (
                "dtu_ess.eybond.com,18899,TCP"
            )
            coordinator._shadow_learning_process_running = lambda: False
            coordinator._async_active_shadow_learning_state = (
                _async_active_shadow_learning_state
            )
            coordinator.config_entry = types.SimpleNamespace(
                data={
                    "collector_ip": "192.168.1.55",
                    "collector_operation_mode": "smartess_cloud_home_assistant",
                },
                options={
                    "collector_operation_mode": "smartess_cloud_home_assistant",
                    "collector_original_server_endpoint": "dtu_ess.eybond.com,18899,TCP",
                },
            )
            snapshot = self.RuntimeSnapshot(
                connected=True,
                values={
                    "collector_server_endpoint": "192.168.1.50,18899,TCP",
                    "collector_cloud_family": "smartess_at",
                },
            )
            coordinator.data = snapshot

            await coordinator._async_reconcile_managed_collector_endpoint(snapshot)

            self.assertEqual(set_endpoint_calls, [])
            self.assertEqual(
                snapshot.values["collector_operation_endpoint_sync_status"],
                "shadow_learning_active",
            )
            self.assertEqual(
                snapshot.values["collector_server_endpoint"],
                "192.168.1.50,18899,TCP",
            )

        import asyncio

        asyncio.run(_run())

    def test_home_assistant_callback_target_pins_listener_port_over_cloud_port(self) -> None:
        # The callback target must always carry THIS entry's listener port:
        # inheriting the cloud/proxy port (18899) from the collector-reported
        # endpoint pointed collectors at the proxy-capture listener while the
        # UDP announcer advertised the real one, fighting on every reconnect.
        coordinator = object.__new__(self.coordinator_module.EybondLocalCoordinator)
        coordinator._connection_spec = types.SimpleNamespace(
            effective_advertised_server_ip="192.168.1.50",
            effective_advertised_tcp_port=8899,
        )
        coordinator._runtime = types.SimpleNamespace(
            collector_server_endpoint_rollback_target="",
        )
        coordinator._remembered_collector_server_endpoint = ""
        coordinator.data = self.RuntimeSnapshot(
            values={"collector_server_endpoint": "47.91.67.66,18899,TCP"}
        )

        self.assertEqual(
            coordinator.collector_callback_target_endpoint,
            "192.168.1.50,8899,TCP",
        )

    def test_proxy_capture_upstream_endpoint_uses_default_smartess_fallback(self) -> None:
        coordinator = object.__new__(self.coordinator_module.EybondLocalCoordinator)
        coordinator._connection_spec = types.SimpleNamespace(
            effective_advertised_server_ip="192.168.1.50",
            effective_advertised_tcp_port=8899,
        )
        coordinator._runtime = types.SimpleNamespace(
            collector_server_endpoint_rollback_target="",
        )
        coordinator._remembered_collector_server_endpoint = ""
        coordinator.data = self.RuntimeSnapshot(
            values={
                "collector_server_endpoint": "192.168.1.50,18899,TCP",
                "collector_cloud_family": "smartess_at",
            }
        )

        self.assertEqual(
            coordinator.proxy_capture_upstream_endpoint,
            "dtu_ess.eybond.com,18899,TCP",
        )

    def test_proxy_capture_upstream_endpoint_ignores_stale_local_callback_after_ha_ip_change(self) -> None:
        coordinator = object.__new__(self.coordinator_module.EybondLocalCoordinator)
        coordinator._connection_spec = types.SimpleNamespace(
            effective_advertised_server_ip="192.168.1.104",
            effective_advertised_tcp_port=8899,
        )
        coordinator._runtime = types.SimpleNamespace(
            effective_advertised_server_ip="192.168.1.104",
            collector_server_endpoint_rollback_target="",
        )
        coordinator._remembered_collector_server_endpoint = "47.91.67.66,18899,TCP"
        coordinator.config_entry = types.SimpleNamespace(
            data={"collector_ip": "192.168.1.55"},
            options={},
        )
        coordinator.data = self.RuntimeSnapshot(
            values={"collector_server_endpoint": "192.168.1.50,18899,TCP"}
        )

        self.assertEqual(
            coordinator.proxy_capture_upstream_endpoint,
            "47.91.67.66,18899,TCP",
        )

    def test_configure_reverse_discovery_turns_off_for_ha_only_mode(self) -> None:
        reverse_discovery_flags: list[bool] = []

        coordinator = object.__new__(self.coordinator_module.EybondLocalCoordinator)
        coordinator._connection_spec = types.SimpleNamespace(
            effective_advertised_server_ip="192.168.1.104",
            effective_advertised_tcp_port=8899,
        )
        coordinator._runtime = types.SimpleNamespace(
            effective_advertised_server_ip="192.168.1.104",
            collector_server_endpoint_rollback_target="",
            set_reverse_discovery_enabled=reverse_discovery_flags.append,
        )
        coordinator.config_entry = types.SimpleNamespace(
            data={"collector_operation_mode": "home_assistant_only"},
            options={"collector_operation_mode": "home_assistant_only"},
        )
        coordinator.data = self.RuntimeSnapshot(
            values={"collector_server_endpoint": "192.168.1.50,18899,TCP"}
        )

        coordinator._configure_reverse_discovery_mode()

        self.assertEqual(reverse_discovery_flags, [False])

    def test_bridge_with_legacy_cloud_axes_is_reported_custom(self) -> None:
        coordinator = object.__new__(self.coordinator_module.EybondLocalCoordinator)
        coordinator.config_entry = types.SimpleNamespace(
            data={"collector_operation_mode": "smartess_cloud_home_assistant"},
            options={"collector_operation_mode": "smartess_cloud_home_assistant"},
        )
        coordinator.data = self.RuntimeSnapshot(
            values={},
            collector=types.SimpleNamespace(collector_virtual_bridge=True),
        )

        self.assertEqual(coordinator.collector_operation_mode, "custom")
        self.assertTrue(coordinator.collector_uses_home_assistant_route)

    def test_unproven_external_inbound_is_reported_custom(self) -> None:
        # Inbound alone cannot claim the complete HA-only product profile when
        # the integration neither owns the endpoint nor has an inbound proof.
        coordinator = object.__new__(self.coordinator_module.EybondLocalCoordinator)
        coordinator.config_entry = types.SimpleNamespace(
            data={
                "collector_kind": "factory_eybond",
                "connection_strategy": "inbound",
                "collector_operation_mode": "smartess_cloud_home_assistant",
            },
            options={"collector_operation_mode": "smartess_cloud_home_assistant"},
        )
        coordinator.data = self.RuntimeSnapshot(values={}, collector=None)
        # Precondition: a factory collector never forces HA-only by capability,
        # so the projection is driven purely by the canonical strategy.
        self.assertFalse(coordinator.collector_capabilities.ha_only_required)
        self.assertEqual(coordinator.collector_operation_mode, "custom")
        self.assertTrue(coordinator.collector_uses_home_assistant_route)

    def test_operation_mode_projects_callback_ignoring_stale_ha_only_mode(self) -> None:
        # CP2A Test B: an entry that declares the canonical CALLBACK strategy
        # projects smartess_cloud_home_assistant, IGNORING a stale HA-only mode.
        coordinator = object.__new__(self.coordinator_module.EybondLocalCoordinator)
        coordinator.config_entry = types.SimpleNamespace(
            data={
                "collector_kind": "factory_eybond",
                "connection_strategy": "callback_on_demand",
                "collector_operation_mode": "home_assistant_only",
            },
            options={"collector_operation_mode": "home_assistant_only"},
        )
        coordinator.data = self.RuntimeSnapshot(values={}, collector=None)
        self.assertFalse(coordinator.collector_capabilities.ha_only_required)
        self.assertEqual(
            coordinator.collector_operation_mode, "smartess_cloud_home_assistant"
        )
        self.assertFalse(coordinator.collector_uses_home_assistant_route)

    def test_runtime_route_uses_canonical_legacy_strategy_derivation(self) -> None:
        # A pre-schema manual entry with a stale HA-only compatibility value is
        # callback-on-demand. The coordinator must use the central resolver;
        # directly re-reading the old mode would incorrectly classify it inbound.
        coordinator = object.__new__(self.coordinator_module.EybondLocalCoordinator)
        coordinator.config_entry = types.SimpleNamespace(
            data={
                "collector_kind": "factory_eybond",
                "connection_mode": "manual",
                "collector_operation_mode": "home_assistant_only",
            },
            options={},
        )
        coordinator.data = self.RuntimeSnapshot(values={}, collector=None)

        self.assertEqual(coordinator.connection_strategy, "callback_on_demand")
        self.assertFalse(coordinator.collector_uses_home_assistant_route)

    def test_legacy_mode_without_proven_axes_is_reported_custom(self) -> None:
        # The legacy field can derive transport compatibility, but it is not
        # sufficient evidence for a normal user-facing operating profile.
        coordinator = object.__new__(self.coordinator_module.EybondLocalCoordinator)
        coordinator.config_entry = types.SimpleNamespace(
            data={
                "collector_kind": "factory_eybond",
                "collector_operation_mode": "home_assistant_only",
            },
            options={},
        )
        coordinator.data = self.RuntimeSnapshot(values={}, collector=None)
        self.assertFalse(coordinator.collector_capabilities.ha_only_required)
        self.assertEqual(coordinator.collector_operation_mode, "custom")
        self.assertTrue(coordinator.collector_uses_home_assistant_route)

    def _rollback_boundary_coordinator(self, *, data, options, values):
        """Build a bare coordinator wired for the read-only rollback boundary.

        Any config-entry write is a test failure. The registry read is routed
        through a fake executor at a non-existent config dir, so the existing
        read-only registry API returns nothing without touching the filesystem.
        """

        coordinator = object.__new__(self.coordinator_module.EybondLocalCoordinator)
        coordinator.config_entry = types.SimpleNamespace(data=dict(data), options=dict(options))
        coordinator.data = self.RuntimeSnapshot(values=dict(values), collector=None)
        coordinator._runtime = types.SimpleNamespace(effective_advertised_server_ip="192.168.1.50")
        coordinator._connection_spec = types.SimpleNamespace(effective_advertised_server_ip="192.168.1.50")

        def _forbidden_write(**kwargs):
            raise AssertionError("read-only rollback boundary must not write the entry")

        coordinator._async_update_entry_without_reload = _forbidden_write

        async def _run_executor(func, *args):
            return func(*args)

        coordinator.hass = types.SimpleNamespace(
            config=types.SimpleNamespace(config_dir="/nonexistent-cp2b1-test-config-dir"),
            async_add_executor_job=_run_executor,
        )
        return coordinator

    @staticmethod
    def _proof_backed_inbound_data(*, pn: str = "E5000025SYN0000000001"):
        timestamp = "2026-07-21T10:00:00+00:00"
        return {
            "collector_kind": "factory_eybond",
            "collector_pn": pn,
            "connection_strategy": "inbound",
            "advertised_server_ip": "192.168.1.50",
            "advertised_tcp_port": 8899,
            "recovery_contract": {
                "schema_version": 1,
                "collector_pn": pn,
                "collector_identity_source": "fc2_parameter_2",
                "updated_at": timestamp,
                "inbound": {
                    "method": "reboot_reconnect_no_trigger",
                    "collector_pn": pn,
                    "identity_source": "fc2_parameter_2",
                    "verified_at": timestamp,
                    "session_protocol": "eybond_framed",
                },
            },
        }

    @staticmethod
    def _proof_backed_callback_data(*, pn: str = "E5000025SYN0000000001"):
        timestamp = "2026-07-21T10:00:00+00:00"
        return {
            "collector_kind": "factory_eybond",
            "collector_pn": pn,
            "connection_strategy": "callback_on_demand",
            "advertised_server_ip": "195.191.72.37",
            "advertised_tcp_port": 18899,
            "recovery_contract": {
                "schema_version": 1,
                "collector_pn": pn,
                "collector_identity_source": "fc2_parameter_2",
                "updated_at": timestamp,
                "callback": {
                    "method": "reset_unicast_reconnect_same_pn",
                    "collector_pn": pn,
                    "identity_source": "fc2_parameter_2",
                    "verified_at": timestamp,
                    "trigger_target": "203.0.113.10:58899",
                    "advertised_ha_endpoint": "195.191.72.37:18899",
                    "listener_port": 8899,
                },
            },
        }

    def test_cloud_rollback_context_returns_durable_original_read_only(self) -> None:
        # CP2B.1 Test E: the read-only boundary returns a typed context from the
        # durable original endpoint and NEVER writes the entry/registry/runtime.
        from custom_components.eybond_local.connection.strategy_transition_context import (
            CloudRollbackEndpoint,
        )

        async def _run() -> None:
            coordinator = self._rollback_boundary_coordinator(
                data={"collector_kind": "factory_eybond", "collector_pn": "E5000025SYN0000000001"},
                options={"collector_original_server_endpoint": "ess.eybond.com,18899,TCP"},
                values={"collector_server_endpoint": "ess.eybond.com,18899,TCP"},
            )
            context = await coordinator.collector_cloud_rollback_context()
            self.assertIsInstance(context, CloudRollbackEndpoint)
            self.assertEqual(context.provenance, "original_cloud_endpoint")
            self.assertEqual(context.endpoint, "ess.eybond.com,18899,TCP")

        asyncio.run(_run())

    def test_cloud_rollback_context_none_when_no_facts(self) -> None:
        # No durable/registry/observed-external fact -> honest none, still no write.
        async def _run() -> None:
            coordinator = self._rollback_boundary_coordinator(
                data=self._proof_backed_inbound_data(),
                options={},
                # Complete endpoint equals the proof-backed HA endpoint.
                values={"collector_server_endpoint": "192.168.1.50,8899,TCP"},
            )
            context = await coordinator.collector_cloud_rollback_context()
            self.assertEqual(context.provenance, "none")
            self.assertEqual(context.endpoint, "")

        asyncio.run(_run())

    def test_cloud_rollback_context_observed_external_when_no_durable(self) -> None:
        # Durable/registry absent; the current endpoint differs from the HA host
        # -> observed external candidate. Still read-only.
        async def _run() -> None:
            coordinator = self._rollback_boundary_coordinator(
                data=self._proof_backed_inbound_data(),
                options={},
                values={"collector_server_endpoint": "dtu.example,18899,TCP"},
            )
            context = await coordinator.collector_cloud_rollback_context()
            self.assertEqual(context.provenance, "observed_current_external_endpoint")
            self.assertEqual(context.endpoint, "dtu.example,18899,TCP")

        asyncio.run(_run())

    def test_cloud_rollback_context_same_host_other_port_is_external(self) -> None:
        async def _run() -> None:
            coordinator = self._rollback_boundary_coordinator(
                data=self._proof_backed_inbound_data(),
                options={},
                values={"collector_server_endpoint": "192.168.1.50,18899,TCP"},
            )
            context = await coordinator.collector_cloud_rollback_context()
            self.assertEqual(
                context.provenance, "observed_current_external_endpoint"
            )

        asyncio.run(_run())

    def test_cloud_rollback_context_does_not_coerce_observed_duck(self) -> None:
        class EndpointDuck:
            def __str__(self) -> str:
                return "dtu.example,18899,TCP"

        async def _run() -> None:
            coordinator = self._rollback_boundary_coordinator(
                data=self._proof_backed_inbound_data(),
                options={},
                values={"collector_server_endpoint": EndpointDuck()},
            )
            context = await coordinator.collector_cloud_rollback_context()
            self.assertEqual(context.provenance, "none")

        asyncio.run(_run())

    def test_cloud_rollback_context_uses_nat_proof_not_runtime_local_host(self) -> None:
        async def _run() -> None:
            coordinator = self._rollback_boundary_coordinator(
                data=self._proof_backed_callback_data(),
                options={},
                # This is exactly the public endpoint certified by the callback
                # proof, while the runtime stub still advertises 192.168.1.50.
                values={"collector_server_endpoint": "195.191.72.37,18899,TCP"},
            )
            context = await coordinator.collector_cloud_rollback_context()
            self.assertEqual(context.provenance, "none")

        asyncio.run(_run())

    # ---- CP2B.2: persistence-before-write for the typed rollback selection ----
    def _catalog_selection(self):
        from custom_components.eybond_local.connection.strategy_transition_context import (
            CLOUD_PROVENANCE_EXPLICIT_USER,
            CloudRollbackEndpoint,
            CloudRollbackSelection,
            ROLLBACK_SELECTION_CATALOG,
        )

        return CloudRollbackSelection(
            endpoint=CloudRollbackEndpoint("dtu.example,18899,TCP", CLOUD_PROVENANCE_EXPLICIT_USER),
            selection_kind=ROLLBACK_SELECTION_CATALOG,
            catalog_profile_key="smartess_at",
            user_confirmed=True,
        )

    def _persist_coordinator(self, *, data, options, config_dir, executor_raises=False):
        from custom_components.eybond_local.connection.recovery_contract import (
            RecoveryContract,
        )

        order: list[str] = []
        data = dict(data)
        durable_pn = data.get("collector_pn")
        if durable_pn and not data.get("collector_virtual_bridge"):
            RecoveryContract.empty_for_pn(
                durable_pn, identity_source="fc2_parameter_2"
            ).write_to(data)
        coordinator = object.__new__(self.coordinator_module.EybondLocalCoordinator)
        coordinator.config_entry = types.SimpleNamespace(data=dict(data), options=dict(options))
        coordinator.data = self.RuntimeSnapshot(
            values={},
            collector=types.SimpleNamespace(
                remote_ip="192.168.1.55",
                collector_pn=str(data.get("collector_pn", "")),
                collector_virtual_bridge=bool(data.get("collector_virtual_bridge")),
            ),
        )

        def _update(**kwargs):
            order.append("entry")
            coordinator.config_entry = types.SimpleNamespace(
                data=kwargs.get("data", coordinator.config_entry.data),
                options=kwargs.get("options", coordinator.config_entry.options),
            )

        coordinator._async_update_entry_without_reload = _update

        async def _run_executor(func, *args):
            order.append("registry")
            if executor_raises:
                raise OSError("simulated registry failure")
            return func(*args)

        coordinator.hass = types.SimpleNamespace(
            config=types.SimpleNamespace(config_dir=str(config_dir)),
            async_add_executor_job=_run_executor,
        )
        return coordinator, order

    def test_persist_selection_writes_data_then_registry_in_order(self) -> None:
        from custom_components.eybond_local.support.collector_registry import (
            get_collector_registry_record,
        )

        async def _run() -> None:
            tmp = Path(tempfile.mkdtemp())
            coordinator, order = self._persist_coordinator(
                data={"collector_kind": "factory_eybond", "collector_pn": "E5000025SYN0000000001"},
                # A stale options copy of the original endpoint must be dropped.
                options={"collector_original_server_endpoint": "old.example,18899,TCP"},
                config_dir=tmp,
            )
            error = await coordinator._async_persist_cloud_rollback_selection(
                self._catalog_selection()
            )
            self.assertEqual(error, "")
            # §5 ordering: entry whole-record BEFORE the PN registry.
            self.assertEqual(order, ["entry", "registry"])
            # Canonical entry.data holds the honest whole record.
            new_data = coordinator.config_entry.data
            self.assertEqual(new_data["collector_original_server_endpoint"], "dtu.example,18899,TCP")
            self.assertEqual(new_data["collector_original_server_endpoint_source"], "user_selected_catalog")
            self.assertEqual(new_data["collector_original_server_endpoint_profile_key"], "smartess_at")
            self.assertTrue(new_data["collector_original_server_endpoint_observed_at"])
            # Stale options copy dropped so it cannot shadow.
            self.assertNotIn("collector_original_server_endpoint", coordinator.config_entry.options)
            # PN-bound registry holds the selected endpoint.
            record = get_collector_registry_record(
                config_dir=tmp, collector_pn="E5000025SYN0000000001"
            )
            self.assertIsNotNone(record)
            self.assertEqual(record.original_endpoint_raw, "dtu.example,18899,TCP")
            self.assertEqual(record.source, "user_selected_catalog")

        asyncio.run(_run())

    def test_persist_selection_registry_forces_over_prior_observed(self) -> None:
        from custom_components.eybond_local.support.collector_registry import (
            get_collector_registry_record,
            remember_collector_original_endpoint,
        )

        async def _run() -> None:
            tmp = Path(tempfile.mkdtemp())
            # A prior auto-observed original already exists for this PN.
            remember_collector_original_endpoint(
                config_dir=tmp,
                collector_pn="E5000025SYN0000000001",
                original_endpoint_raw="observed.old,18899,TCP",
                source="runtime_observed",
            )
            coordinator, _order = self._persist_coordinator(
                data={"collector_kind": "factory_eybond", "collector_pn": "E5000025SYN0000000001"},
                options={},
                config_dir=tmp,
            )
            error = await coordinator._async_persist_cloud_rollback_selection(
                self._catalog_selection()
            )
            self.assertEqual(error, "")
            record = get_collector_registry_record(
                config_dir=tmp, collector_pn="E5000025SYN0000000001"
            )
            # The explicit user choice replaced the prior observed record.
            self.assertEqual(record.original_endpoint_raw, "dtu.example,18899,TCP")

        asyncio.run(_run())

    def test_persist_selection_pn_required_when_missing(self) -> None:
        from custom_components.eybond_local.connection.strategy_transition import (
            TRANSITION_ROLLBACK_REGISTRY_PN_REQUIRED,
        )

        async def _run() -> None:
            coordinator, order = self._persist_coordinator(
                data={"collector_kind": "factory_eybond"},  # no collector_pn
                options={},
                config_dir="/nonexistent-cp2b2",
            )
            error = await coordinator._async_persist_cloud_rollback_selection(
                self._catalog_selection()
            )
            self.assertEqual(error, TRANSITION_ROLLBACK_REGISTRY_PN_REQUIRED)
            self.assertEqual(order, [])  # zero writes before wire

        asyncio.run(_run())

    def test_persist_selection_rejects_entry_pn_without_strong_contract(self) -> None:
        from custom_components.eybond_local.connection.strategy_transition import (
            TRANSITION_ROLLBACK_REGISTRY_PN_REQUIRED,
        )

        async def _run() -> None:
            coordinator, order = self._persist_coordinator(
                data={"collector_kind": "factory_eybond", "collector_pn": "WEAK"},
                options={},
                config_dir="/nonexistent-cp2b2",
            )
            coordinator.config_entry.data.pop("recovery_contract", None)
            error = await coordinator._async_persist_cloud_rollback_selection(
                self._catalog_selection(), collector_pn="WEAK"
            )
            self.assertEqual(error, TRANSITION_ROLLBACK_REGISTRY_PN_REQUIRED)
            self.assertEqual(order, [])

        asyncio.run(_run())

    def test_persist_selection_rejects_foreign_strong_contract(self) -> None:
        from custom_components.eybond_local.connection.recovery_contract import (
            RecoveryContract,
        )
        from custom_components.eybond_local.connection.strategy_transition import (
            TRANSITION_ROLLBACK_REGISTRY_PN_REQUIRED,
        )

        async def _run() -> None:
            coordinator, order = self._persist_coordinator(
                data={
                    "collector_kind": "factory_eybond",
                    "collector_pn": "E5000025SYN0000000001",
                },
                options={},
                config_dir="/nonexistent-cp2b2",
            )
            RecoveryContract.empty_for_pn(
                "V001020SYN62344022", identity_source="fc2_parameter_2"
            ).write_to(coordinator.config_entry.data)
            error = await coordinator._async_persist_cloud_rollback_selection(
                self._catalog_selection(),
                collector_pn="E5000025SYN0000000001",
            )
            self.assertEqual(error, TRANSITION_ROLLBACK_REGISTRY_PN_REQUIRED)
            self.assertEqual(order, [])

        asyncio.run(_run())

    def test_durable_transition_pn_accepts_exact_owned_strong_session_for_legacy_entry(self) -> None:
        from custom_components.eybond_local.connection.session_registry import (
            CallbackSessionRegistry,
        )

        pn = "E5000025SYN0000000001"
        inventory = (
            {
                "session_id": "legacy-live-session",
                "collector_pn": pn,
                "collector_identity_source": "fc2_parameter_2",
                "state": "routed_framed",
                "protocol_shape": "eybond_framed",
            },
        )
        registry = CallbackSessionRegistry(sessions_source=lambda: inventory)
        registry.claim_session("entry-id", session_id="legacy-live-session")
        registry.promote_claim_to_full_pn("entry-id", pn)
        coordinator = object.__new__(self.coordinator_module.EybondLocalCoordinator)
        coordinator.config_entry = types.SimpleNamespace(
            data={"collector_pn": pn}, options={}
        )
        self.assertEqual(
            coordinator._durable_transition_collector_pn(
                identity_registry=registry, owner_id="entry-id"
            ),
            pn,
        )

    def test_durable_transition_pn_rejects_weak_owned_session(self) -> None:
        from custom_components.eybond_local.connection.session_registry import (
            CallbackSessionRegistry,
        )

        pn = "E5000025SYN0000000001"
        inventory = (
            {
                "session_id": "weak-live-session",
                "collector_pn": pn,
                "collector_identity_source": "framed_heartbeat",
                "state": "routed_framed",
                "protocol_shape": "eybond_framed",
            },
        )
        registry = CallbackSessionRegistry(sessions_source=lambda: inventory)
        registry.claim_session("entry-id", session_id="weak-live-session")
        registry.promote_claim_to_full_pn("entry-id", pn)
        coordinator = object.__new__(self.coordinator_module.EybondLocalCoordinator)
        coordinator.config_entry = types.SimpleNamespace(
            data={"collector_pn": pn}, options={}
        )
        self.assertEqual(
            coordinator._durable_transition_collector_pn(
                identity_registry=registry, owner_id="entry-id"
            ),
            "",
        )

    def test_persist_selection_pn_required_for_bridge(self) -> None:
        from custom_components.eybond_local.connection.strategy_transition import (
            TRANSITION_ROLLBACK_REGISTRY_PN_REQUIRED,
        )

        async def _run() -> None:
            coordinator, order = self._persist_coordinator(
                data={"collector_virtual_bridge": True, "collector_pn": "E5000025SYN0000000001"},
                options={},
                config_dir="/nonexistent-cp2b2",
            )
            error = await coordinator._async_persist_cloud_rollback_selection(
                self._catalog_selection()
            )
            self.assertEqual(error, TRANSITION_ROLLBACK_REGISTRY_PN_REQUIRED)
            self.assertEqual(order, [])

        asyncio.run(_run())

    def test_bridge_endpoint_relocation_needs_no_cloud_rollback_record(self) -> None:
        async def _run() -> None:
            pn = "E5000025SYN0000000001"
            coordinator, order = self._persist_coordinator(
                data={
                    "collector_virtual_bridge": True,
                    "collector_kind": "esp_eybond_bridge",
                    "collector_pn": pn,
                },
                options={},
                config_dir="/nonexistent-local-bridge-relocation",
            )
            coordinator._durable_transition_collector_pn = lambda **_kwargs: pn

            refusal = await coordinator._async_persist_inbound_rollback_endpoint(
                "192.168.1.50,8899,TCP",
                collector_pn=pn,
            )

            self.assertEqual(refusal, "")
            self.assertEqual(order, [])
            self.assertNotIn(
                "collector_original_server_endpoint", coordinator.config_entry.data
            )

        asyncio.run(_run())

    def test_persist_selection_registry_failure_keeps_entry_intent_no_wire(self) -> None:
        from custom_components.eybond_local.connection.strategy_transition import (
            TRANSITION_ROLLBACK_PERSIST_FAILED,
        )

        async def _run() -> None:
            coordinator, order = self._persist_coordinator(
                data={"collector_kind": "factory_eybond", "collector_pn": "E5000025SYN0000000001"},
                options={},
                config_dir="/nonexistent-cp2b2",
                executor_raises=True,
            )
            error = await coordinator._async_persist_cloud_rollback_selection(
                self._catalog_selection()
            )
            self.assertEqual(error, TRANSITION_ROLLBACK_PERSIST_FAILED)
            # The safe local entry intent was written (retryable); registry failed.
            self.assertEqual(order, ["entry", "registry"])
            self.assertEqual(
                coordinator.config_entry.data["collector_original_server_endpoint"],
                "dtu.example,18899,TCP",
            )

        asyncio.run(_run())

    def test_inbound_overwrite_without_live_endpoint_requires_saved_original(self) -> None:
        from custom_components.eybond_local.connection.strategy_transition import (
            TRANSITION_INBOUND_ROLLBACK_PERSIST_FAILED,
        )

        async def _run() -> None:
            tmp = Path(tempfile.mkdtemp())
            coordinator, order = self._persist_coordinator(
                data={
                    "collector_kind": "factory_eybond",
                    "collector_pn": "E5000025SYN0000000001",
                },
                options={},
                config_dir=tmp,
            )
            refusal = await coordinator._async_persist_inbound_rollback_endpoint(
                "", collector_pn="E5000025SYN0000000001"
            )
            self.assertEqual(
                refusal, TRANSITION_INBOUND_ROLLBACK_PERSIST_FAILED
            )
            self.assertEqual(order, ["registry"])

        asyncio.run(_run())

    def test_inbound_overwrite_accepts_existing_durable_original_when_live_is_empty(self) -> None:
        async def _run() -> None:
            tmp = Path(tempfile.mkdtemp())
            coordinator, order = self._persist_coordinator(
                data={
                    "collector_kind": "factory_eybond",
                    "collector_pn": "E5000025SYN0000000001",
                    "collector_original_server_endpoint": "saved.example,18899,TCP",
                    "collector_original_server_endpoint_source": "runtime_observed",
                },
                options={},
                config_dir=tmp,
            )
            refusal = await coordinator._async_persist_inbound_rollback_endpoint(
                "", collector_pn="E5000025SYN0000000001"
            )
            self.assertEqual(refusal, "")
            self.assertEqual(order, ["registry"])

        asyncio.run(_run())

    def test_inbound_remembers_external_endpoint_before_any_overwrite(self) -> None:
        # CP2B.2 §9 audit: the EXISTING continuous remember (run on every snapshot
        # prepare, BEFORE any inbound transition) durably saves the current
        # external endpoint into the entry (options whole-record) AND the PN
        # registry. This is the mechanism the inbound overwrite relies on -- it is
        # proven here so the switch never loses the original cloud endpoint.
        from custom_components.eybond_local.support.collector_registry import (
            get_collector_registry_record,
        )

        async def _run() -> None:
            tmp = Path(tempfile.mkdtemp())
            coordinator = object.__new__(self.coordinator_module.EybondLocalCoordinator)
            coordinator.config_entry = types.SimpleNamespace(
                data={
                    "collector_kind": "factory_eybond",
                    "collector_pn": "E5000025SYN0000000001",
                    "collector_ip": "192.168.1.55",
                },
                options={},
            )
            coordinator.data = self.RuntimeSnapshot(
                values={"collector_server_endpoint": "ess.eybond.com,18899,TCP"},
                collector=types.SimpleNamespace(
                    remote_ip="192.168.1.55",
                    collector_pn="E5000025SYN0000000001",
                    collector_virtual_bridge=False,
                ),
            )
            # HA's own advertised host (the endpoint we would OVERWRITE to) differs
            # from the external endpoint, so the external one is remembered.
            coordinator._runtime = types.SimpleNamespace(effective_advertised_server_ip="192.168.1.50")
            coordinator._connection_spec = types.SimpleNamespace(effective_advertised_server_ip="192.168.1.50")
            coordinator._remembered_collector_server_endpoint = ""

            def _update(**kwargs):
                if "options" in kwargs:
                    coordinator.config_entry = types.SimpleNamespace(
                        data=coordinator.config_entry.data, options=kwargs["options"]
                    )

            coordinator._async_update_entry_without_reload = _update

            async def _run_executor(func, *args):
                return func(*args)

            coordinator.hass = types.SimpleNamespace(
                config=types.SimpleNamespace(config_dir=str(tmp)),
                async_add_executor_job=_run_executor,
            )

            await coordinator._async_remember_collector_server_endpoint(coordinator.data)

            # Saved as the durable original in the entry (options whole-record).
            self.assertEqual(
                coordinator.config_entry.options.get("collector_original_server_endpoint"),
                "ess.eybond.com,18899,TCP",
            )
            # Saved PN-bound in the registry.
            record = get_collector_registry_record(
                config_dir=tmp, collector_pn="E5000025SYN0000000001"
            )
            self.assertIsNotNone(record)
            self.assertEqual(record.original_endpoint_raw, "ess.eybond.com,18899,TCP")

        asyncio.run(_run())

    # ---- CP2C: endpoint-operation authority mutual exclusion ----
    def _full_control_coordinator(self, entry_id: str):
        coordinator = object.__new__(self.coordinator_module.EybondLocalCoordinator)
        coordinator.config_entry = types.SimpleNamespace(
            entry_id=entry_id, data={}, options={"control_mode": "full"}
        )
        writes: list[tuple] = []

        async def _write(*args, **kwargs):
            writes.append((args, kwargs))
            return {"readback_endpoint": args[0] if args else ""}

        coordinator._runtime = types.SimpleNamespace(
            async_set_collector_server_endpoint=_write
        )
        return coordinator, writes

    def test_5_6_7_manual_write_refused_with_zero_wire_when_busy(self) -> None:
        from custom_components.eybond_local.connection.collector_endpoint_operation import (
            COLLECTOR_ENDPOINT_OPERATION_AUTHORITY as AUTH,
            OPERATION_PROXY_CAPTURE,
            OPERATION_SHADOW_LEARNING,
            OPERATION_STRATEGY_TRANSITION,
        )

        async def _run() -> None:
            for op in (
                OPERATION_PROXY_CAPTURE,
                OPERATION_SHADOW_LEARNING,
                OPERATION_STRATEGY_TRANSITION,
            ):
                entry_id = f"cp2c-manual-{op}"
                coordinator, writes = self._full_control_coordinator(entry_id)
                held = AUTH.acquire(entry_id, op)
                try:
                    with self.assertRaises(RuntimeError) as ctx:
                        await coordinator.async_set_raw_collector_server_endpoint(
                            endpoint="dtu.example,18899,TCP", confirm_redirect=True
                        )
                    self.assertEqual(str(ctx.exception), "collector_endpoint_operation_busy")
                    self.assertEqual(writes, [], f"{op} allowed a wire write")
                finally:
                    AUTH.release(entry_id, held.token)

        asyncio.run(_run())

    def test_7_transition_lease_is_blocked_by_a_foreign_endpoint_owner(self) -> None:
        # The transition facade acquires via STRATEGY_TRANSITION_LEASES, which
        # delegates to the ONE authority. While proxy/shadow (or a manual write)
        # owns the entry, that lease cannot be acquired -> the facade returns a
        # typed busy. (The full facade is not driven here because its
        # passive_discovery import needs the real const module, unavailable under
        # this stub harness; the exclusion itself is proven at the lease/authority
        # boundary the facade uses.)
        from custom_components.eybond_local.connection.collector_endpoint_operation import (
            COLLECTOR_ENDPOINT_OPERATION_AUTHORITY as AUTH,
            OPERATION_PROXY_CAPTURE,
            OPERATION_SHADOW_LEARNING,
            OPERATION_STRATEGY_TRANSITION,
        )
        from custom_components.eybond_local.connection.strategy_transition import (
            STRATEGY_TRANSITION_LEASES,
        )

        del OPERATION_STRATEGY_TRANSITION  # imported for documentation of the mapping
        for op in (OPERATION_PROXY_CAPTURE, OPERATION_SHADOW_LEARNING):
            entry_id = f"cp2c-transition-lease-{op}"
            held = AUTH.acquire(entry_id, op)
            try:
                # A foreign endpoint owner blocks the transition lease...
                self.assertFalse(STRATEGY_TRANSITION_LEASES.acquire(entry_id))
                # ...and the active owner the facade reads is that foreign op, so
                # the facade surfaces the neutral busy reason (not "already
                # running", which is reserved for a concurrent strategy op).
                self.assertEqual(AUTH.active_operation(entry_id), op)
            finally:
                AUTH.release(entry_id, held.token)

    def test_3_transient_operation_releases_lease_on_error_and_cancel(self) -> None:
        from custom_components.eybond_local.connection.collector_endpoint_operation import (
            COLLECTOR_ENDPOINT_OPERATION_AUTHORITY as AUTH,
            OPERATION_MANUAL_ENDPOINT_WRITE,
        )

        async def _run() -> None:
            entry_id = "cp2c-cm-lifecycle"
            coordinator = object.__new__(self.coordinator_module.EybondLocalCoordinator)
            coordinator.config_entry = types.SimpleNamespace(entry_id=entry_id)

            # An error inside the guarded block releases the lease (finally).
            with self.assertRaises(ValueError):
                async with coordinator._collector_endpoint_operation(
                    OPERATION_MANUAL_ENDPOINT_WRITE
                ):
                    raise ValueError("inner boom")
            self.assertFalse(AUTH.is_held(entry_id))

            # Cancellation inside the guarded block releases the lease too.
            async def _hold() -> None:
                async with coordinator._collector_endpoint_operation(
                    OPERATION_MANUAL_ENDPOINT_WRITE
                ):
                    await asyncio.sleep(10)

            task = asyncio.ensure_future(_hold())
            await asyncio.sleep(0)
            self.assertTrue(AUTH.is_held(entry_id))
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
            self.assertFalse(AUTH.is_held(entry_id))

            # Busy raise happens BEFORE the block body (zero side effects).
            other = AUTH.acquire(entry_id, OPERATION_MANUAL_ENDPOINT_WRITE)
            try:
                entered = False
                with self.assertRaises(RuntimeError):
                    async with coordinator._collector_endpoint_operation(
                        OPERATION_MANUAL_ENDPOINT_WRITE
                    ):
                        entered = True
                self.assertFalse(entered)
            finally:
                AUTH.release(entry_id, other.token)

        asyncio.run(_run())

    def test_runtime_identity_promotes_unknown_collector_to_factory(self) -> None:
        updates: list[dict[str, object]] = []

        coordinator = object.__new__(self.coordinator_module.EybondLocalCoordinator)
        coordinator.config_entry = types.SimpleNamespace(
            data={
                "collector_kind": "unknown",
                "connection_strategy": "callback_on_demand",
                "collector_operation_mode": "home_assistant_only",
            },
            options={"collector_kind": "unknown"},
        )
        coordinator.data = self.RuntimeSnapshot(
            values={
                "model_name": "SMG 6200",
                "serial_number": "SMGSYN240001",
            },
            collector=None,
        )
        coordinator._async_update_entry_without_reload = lambda **kwargs: updates.append(kwargs)

        self.assertTrue(coordinator.collector_capabilities.proxy_capture)
        self.assertTrue(coordinator.collector_capabilities.shadow_learning)
        self.assertEqual(
            coordinator.collector_operation_mode,
            "smartess_cloud_home_assistant",
        )

        coordinator._sync_collector_capability_profile()

        self.assertEqual(len(updates), 1)
        self.assertEqual(updates[0]["data"]["collector_kind"], "factory_eybond")
        self.assertEqual(updates[0]["options"]["collector_kind"], "factory_eybond")
        # Capability enrichment never rewrites either architecture axis.
        self.assertEqual(
            updates[0]["data"]["connection_strategy"], "callback_on_demand"
        )
        self.assertEqual(
            updates[0]["data"]["collector_operation_mode"],
            "home_assistant_only",
        )

    def test_runtime_bridge_syncs_profile_without_persisting_operation_mode(self) -> None:
        updates: list[dict[str, object]] = []

        coordinator = object.__new__(self.coordinator_module.EybondLocalCoordinator)
        coordinator.config_entry = types.SimpleNamespace(
            data={"collector_operation_mode": "smartess_cloud_home_assistant"},
            options={"collector_operation_mode": "smartess_cloud_home_assistant"},
        )
        coordinator.data = self.RuntimeSnapshot(
            values={},
            collector=types.SimpleNamespace(collector_virtual_bridge=True),
        )
        coordinator._async_update_entry_without_reload = lambda **kwargs: updates.append(kwargs)

        coordinator._sync_collector_capability_profile()

        self.assertEqual(len(updates), 1)
        data = updates[0]["data"]
        options = updates[0]["options"]
        self.assertEqual(
            data["collector_operation_mode"], "smartess_cloud_home_assistant"
        )
        self.assertEqual(
            options["collector_operation_mode"], "smartess_cloud_home_assistant"
        )
        self.assertTrue(data["collector_virtual_bridge"])
        self.assertTrue(options["collector_virtual_bridge"])
        # A bridge combined with legacy cloud/callback axes is not silently
        # relabelled HA-only; the read-only profile reports the mismatch.
        self.assertEqual(coordinator.collector_operation_mode, "custom")

    def test_runtime_bridge_sync_requests_reload_after_platform_setup(self) -> None:
        updates: list[dict[str, object]] = []
        reloads: list[str] = []

        coordinator = object.__new__(self.coordinator_module.EybondLocalCoordinator)
        coordinator.config_entry = types.SimpleNamespace(
            entry_id="entry-1",
            data={"collector_operation_mode": "smartess_cloud_home_assistant"},
            options={"collector_operation_mode": "smartess_cloud_home_assistant"},
        )
        coordinator.hass = types.SimpleNamespace(
            async_create_task=lambda coroutine: reloads.append("scheduled"),
            config_entries=types.SimpleNamespace(
                async_reload=lambda entry_id: entry_id,
            ),
        )
        coordinator.data = self.RuntimeSnapshot(
            values={},
            collector=types.SimpleNamespace(collector_virtual_bridge=True),
        )
        coordinator._entity_platforms_initialized = True
        coordinator._entity_platform_reload_requested = False
        coordinator._async_update_entry_without_reload = lambda **kwargs: updates.append(kwargs)

        coordinator._sync_collector_capability_profile()

        self.assertEqual(len(updates), 1)
        self.assertEqual(reloads, ["scheduled"])
        self.assertTrue(coordinator._entity_platform_reload_requested)

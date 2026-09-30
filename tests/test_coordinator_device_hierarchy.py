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



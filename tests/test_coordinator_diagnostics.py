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
    def test_reverse_discovery_off_for_inbound_strategy_even_for_bridge(self) -> None:
        # Architecture invariant: the UDP callback gate is keyed purely on the
        # explicit connection_strategy, NOT on the collector type. An inbound
        # entry (the collector dials Home Assistant by itself) never runs reverse
        # discovery -- even a virtual bridge. This replaces the old collector-type
        # exception that kept reverse discovery on for HA-only bridges.
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
            data={"connection_strategy": "inbound"},
            options={},
        )
        coordinator.data = self.RuntimeSnapshot(
            values={"collector_server_endpoint": "192.168.1.50,18899,TCP"},
            collector=types.SimpleNamespace(collector_virtual_bridge=True),
        )

        coordinator._configure_reverse_discovery_mode()

        self.assertEqual(reverse_discovery_flags, [False])

    def test_reverse_discovery_ignores_endpoint_hostname_for_callback_strategy(self) -> None:
        # Architecture invariant: the endpoint string is opaque and never drives
        # transport behavior. A callback_on_demand entry keeps reverse discovery
        # ENABLED regardless of whether the live endpoint hostname happens to
        # point at this Home Assistant host. This replaces the old
        # endpoint-hostname decision that turned discovery off.
        reverse_discovery_flags: list[bool] = []

        coordinator = object.__new__(self.coordinator_module.EybondLocalCoordinator)
        coordinator._connection_spec = types.SimpleNamespace(
            server_ip="192.168.1.50",
            effective_advertised_server_ip="192.168.1.50",
            effective_advertised_tcp_port=8899,
        )
        coordinator._runtime = types.SimpleNamespace(
            effective_advertised_server_ip="192.168.1.50",
            collector_server_endpoint_rollback_target="",
            set_reverse_discovery_enabled=reverse_discovery_flags.append,
        )
        coordinator.config_entry = types.SimpleNamespace(
            data={"connection_strategy": "callback_on_demand"},
            options={},
        )
        coordinator.data = self.RuntimeSnapshot(
            values={"collector_server_endpoint": "192.168.1.50,18899,TCP"}
        )

        coordinator._configure_reverse_discovery_mode()

        self.assertEqual(reverse_discovery_flags, [True])

    def test_configure_reverse_discovery_keeps_on_when_endpoint_targets_cloud(self) -> None:
        reverse_discovery_flags: list[bool] = []

        coordinator = object.__new__(self.coordinator_module.EybondLocalCoordinator)
        coordinator._connection_spec = types.SimpleNamespace(
            server_ip="192.168.1.50",
            effective_advertised_server_ip="192.168.1.50",
            effective_advertised_tcp_port=8899,
        )
        coordinator._runtime = types.SimpleNamespace(
            effective_advertised_server_ip="192.168.1.50",
            collector_server_endpoint_rollback_target="",
            set_reverse_discovery_enabled=reverse_discovery_flags.append,
        )
        coordinator.config_entry = types.SimpleNamespace(
            data={"collector_operation_mode": "smartess_cloud_home_assistant"},
            options={"collector_operation_mode": "smartess_cloud_home_assistant"},
        )
        coordinator.data = self.RuntimeSnapshot(
            values={"collector_server_endpoint": "dtu_ess.eybond.com,18899,TCP"}
        )

        coordinator._configure_reverse_discovery_mode()

        self.assertEqual(reverse_discovery_flags, [True])

    def test_async_trigger_collector_rediscovery_keeps_bootstrap_transport_separate(self) -> None:
        async def _run() -> None:
            reverse_discovery_calls: list[dict[str, float | int]] = []
            prepared_targets: list[str] = []
            refresh_calls: list[bool] = []

            async def _trigger_reverse_discovery(
                *,
                port: int = 0,
                timeout: float = 0.75,
            ) -> dict[str, object]:
                reverse_discovery_calls.append(
                    {"port": int(port), "timeout": float(timeout)}
                )
                return {
                    "status": "probe_sent",
                    "advertised_endpoint": "192.168.1.104:8899",
                }

            async def _prepare_listener(endpoint: str) -> None:
                prepared_targets.append(endpoint)

            async def _request_refresh() -> None:
                refresh_calls.append(True)

            coordinator = object.__new__(self.coordinator_module.EybondLocalCoordinator)
            coordinator._connection_spec = types.SimpleNamespace(
                effective_advertised_server_ip="192.168.1.104",
                effective_advertised_tcp_port=8899,
            )
            coordinator._runtime = types.SimpleNamespace(
                effective_advertised_server_ip="192.168.1.104",
                collector_server_endpoint_rollback_target="",
                async_trigger_reverse_discovery=_trigger_reverse_discovery,
            )
            coordinator.config_entry = types.SimpleNamespace(
                entry_id="entry-rediscovery",
                data={
                    "collector_ip": "192.168.1.55",
                    "collector_operation_mode": "home_assistant_only",
                },
                options={"collector_operation_mode": "home_assistant_only"},
            )
            coordinator.data = self.RuntimeSnapshot(
                connected=False,
                values={"collector_server_endpoint": "192.168.1.50,18899,TCP"},
            )
            coordinator._async_prepare_home_assistant_callback_listener = _prepare_listener
            coordinator.async_request_refresh = _request_refresh

            with patch.object(
                self.coordinator_module.EybondLocalCoordinator,
                "proxy_capture_overview",
                new_callable=PropertyMock,
                return_value=types.SimpleNamespace(status="ready"),
            ):
                result = await coordinator.async_trigger_collector_rediscovery()

            self.assertEqual(prepared_targets, ["192.168.1.104,8899,TCP"])
            self.assertEqual(
                reverse_discovery_calls,
                [{"port": 0, "timeout": 0.75}],
            )
            self.assertEqual(
                result["collector_callback_target_endpoint"],
                "192.168.1.104,8899,TCP",
            )
            self.assertEqual(result["target_role"], "bootstrap")
            self.assertEqual(refresh_calls, [True])

        asyncio.run(_run())

    def test_collector_server_endpoint_rollback_target_ignores_stale_runtime_local_callback(self) -> None:
        coordinator = object.__new__(self.coordinator_module.EybondLocalCoordinator)
        coordinator._connection_spec = types.SimpleNamespace(
            effective_advertised_server_ip="192.168.1.104",
            effective_advertised_tcp_port=8899,
        )
        coordinator._runtime = types.SimpleNamespace(
            effective_advertised_server_ip="192.168.1.104",
            collector_server_endpoint_rollback_target="192.168.1.50,18899,TCP",
        )
        coordinator._remembered_collector_server_endpoint = "47.91.67.66,18899,TCP"
        coordinator.config_entry = types.SimpleNamespace(
            data={"collector_ip": "192.168.1.55"},
            options={},
        )
        coordinator.data = self.RuntimeSnapshot(values={})

        self.assertEqual(
            coordinator.collector_server_endpoint_rollback_target,
            "47.91.67.66,18899,TCP",
        )

    def test_proxy_capture_overview_passes_upstream_endpoint(self) -> None:
        coordinator = object.__new__(self.coordinator_module.EybondLocalCoordinator)
        coordinator._connection_spec = types.SimpleNamespace(
            effective_advertised_server_ip="192.168.1.50",
            effective_advertised_tcp_port=8899,
        )
        coordinator._runtime = types.SimpleNamespace(
            collector_server_endpoint_rollback_target="",
        )
        coordinator._remembered_collector_server_endpoint = "47.91.67.66,18899,TCP"
        coordinator.data = self.RuntimeSnapshot(
            values={"collector_server_endpoint": "192.168.1.50,18899,TCP"},
            connected=True,
        )
        coordinator.config_entry = types.SimpleNamespace(
            data={"detection_confidence": "none"},
            options={"control_mode": "auto"},
        )
        coordinator._active_proxy_capture_state = lambda: None
        coordinator._proxy_capture_runtime_values = lambda: {}

        captured: dict[str, object] = {}
        original_builder = self.coordinator_cloud_tools_module.build_proxy_capture_overview

        def _fake_build_proxy_capture_overview(**kwargs):
            captured.update(kwargs)
            return types.SimpleNamespace(
                can_start=bool(kwargs["upstream_endpoint"]),
                can_stop=False,
                blocking_reason="",
                redirect_required=True,
            )

        self.coordinator_cloud_tools_module.build_proxy_capture_overview = (
            _fake_build_proxy_capture_overview
        )
        try:
            overview = coordinator.proxy_capture_overview
        finally:
            self.coordinator_cloud_tools_module.build_proxy_capture_overview = original_builder

        self.assertEqual(captured["upstream_endpoint"], "47.91.67.66,18899,TCP")
        self.assertTrue(overview.can_start)

    def test_proxy_capture_duration_properties_follow_config_and_runtime_values(self) -> None:
        coordinator = object.__new__(self.coordinator_module.EybondLocalCoordinator)
        coordinator.config_entry = types.SimpleNamespace(
            data={"proxy_capture_duration_minutes": 10},
            options={"proxy_capture_duration_minutes": 15},
        )
        coordinator.data = self.RuntimeSnapshot(
            values={"proxy_capture_remaining_seconds": 125},
            connected=True,
        )
        coordinator._tooling_values = {}

        with patch.object(
            self.coordinator_module.EybondLocalCoordinator,
            "proxy_capture_overview",
            new_callable=PropertyMock,
            return_value=types.SimpleNamespace(
                can_stop=True,
                critical_phase=False,
                can_start=False,
                blocking_reason="",
            ),
        ):
            self.assertEqual(coordinator.proxy_capture_configured_duration_minutes, 15)
            self.assertEqual(coordinator.proxy_capture_remaining_seconds, 125)
            self.assertEqual(coordinator.proxy_capture_remaining_minutes, 3)
            self.assertEqual(coordinator.proxy_capture_display_duration_minutes, 3)
            self.assertIsNone(coordinator.proxy_capture_duration_availability_reason())

    def test_cloud_tools_share_the_exact_live_endpoint_context(self) -> None:
        async def _run() -> None:
            coordinator = object.__new__(
                self.coordinator_module.EybondLocalCoordinator
            )

            async def _live_endpoint_state():
                return {"current_endpoint": "eu.smartess.io,18899,TCP"}

            coordinator._runtime = types.SimpleNamespace(
                async_get_collector_server_endpoint_state=_live_endpoint_state,
            )
            coordinator.config_entry = types.SimpleNamespace(entry_id="entry-id")
            coordinator.data = self.RuntimeSnapshot(
                values={
                    "collector_server_endpoint": "stale.example,18899,TCP",
                }
            )

            with patch.object(
                self.coordinator_module.EybondLocalCoordinator,
                "collector_cloud_family",
                new_callable=PropertyMock,
                return_value="smartess",
            ), patch.object(
                self.coordinator_module.EybondLocalCoordinator,
                "proxy_capture_upstream_endpoint",
                new_callable=PropertyMock,
                return_value="eu.smartess.io,18899,TCP",
            ), patch.object(
                self.coordinator_module.EybondLocalCoordinator,
                "proxy_capture_target_endpoint",
                new_callable=PropertyMock,
                return_value="192.168.1.50,18899,TCP",
            ):
                context = (
                    await coordinator._async_prepare_cloud_tool_endpoint_context()
                )

            self.assertEqual(
                context.current_endpoint,
                "eu.smartess.io,18899,TCP",
            )
            self.assertEqual(
                context.upstream_endpoint,
                "eu.smartess.io,18899,TCP",
            )
            self.assertEqual(
                context.target_endpoint,
                "192.168.1.50,18899,TCP",
            )
            self.assertEqual(
                coordinator.data.values["collector_server_endpoint"],
                "eu.smartess.io,18899,TCP",
            )

        asyncio.run(_run())

    def test_cloud_tool_endpoint_context_never_falls_back_to_stale_snapshot(
        self,
    ) -> None:
        async def _run() -> None:
            coordinator = object.__new__(
                self.coordinator_module.EybondLocalCoordinator
            )

            async def _live_endpoint_state():
                raise RuntimeError("collector_not_connected")

            coordinator._runtime = types.SimpleNamespace(
                async_get_collector_server_endpoint_state=_live_endpoint_state,
            )
            coordinator.config_entry = types.SimpleNamespace(entry_id="entry-id")
            coordinator.data = self.RuntimeSnapshot(
                values={
                    "collector_server_endpoint": "stale.example,18899,TCP",
                }
            )

            with self.assertRaisesRegex(
                RuntimeError,
                "cloud_tool_collector_not_connected",
            ):
                await coordinator._async_prepare_cloud_tool_endpoint_context()

            self.assertEqual(
                coordinator.data.values["collector_server_endpoint"],
                "stale.example,18899,TCP",
            )

        asyncio.run(_run())

    def test_proxy_capture_values_pass_upstream_endpoint(self) -> None:
        import asyncio

        async def _run() -> None:
            coordinator = object.__new__(self.coordinator_module.EybondLocalCoordinator)
            coordinator._connection_spec = types.SimpleNamespace(
                effective_advertised_server_ip="192.168.1.50",
                effective_advertised_tcp_port=8899,
            )
            coordinator._runtime = types.SimpleNamespace(
                collector_server_endpoint_rollback_target="",
            )
            coordinator._remembered_collector_server_endpoint = "47.91.67.66,18899,TCP"
            coordinator.data = self.RuntimeSnapshot(
                values={"collector_server_endpoint": "192.168.1.50,18899,TCP"},
                connected=True,
            )
            coordinator.config_entry = types.SimpleNamespace(
                data={"detection_confidence": "none"},
                options={"control_mode": "auto"},
            )

            async def _async_none(*args, **kwargs):
                del args, kwargs
                return None

            async def _async_add_executor_job(func):
                return func()

            async def _async_download_details(_manifest_path: str):
                return "", ""

            coordinator.hass = types.SimpleNamespace(
                async_add_executor_job=_async_add_executor_job,
            )
            coordinator._async_active_proxy_capture_state = _async_none
            coordinator._async_latest_proxy_trace_record = _async_none
            coordinator._async_proxy_trace_manifest_download_details = _async_download_details

            captured: dict[str, object] = {}
            original_builder = (
                self.coordinator_snapshot_projection_module.build_proxy_capture_overview
            )

            def _fake_build_proxy_capture_overview(**kwargs):
                captured.update(kwargs)
                return types.SimpleNamespace(
                    status="ready",
                    status_label="Ready",
                    summary="",
                    blocking_reason="",
                    can_start=bool(kwargs["upstream_endpoint"]),
                    can_reconnect_for_start=False,
                    can_stop=False,
                    critical_phase=False,
                    redirect_required=True,
                    current_endpoint=kwargs["current_endpoint"],
                    target_endpoint=kwargs["target_endpoint"],
                    masked_endpoint=kwargs["current_endpoint"],
                    latest_trace_path=kwargs["latest_trace_path"],
                    latest_manifest_path=kwargs["latest_manifest_path"],
                )

            self.coordinator_snapshot_projection_module.build_proxy_capture_overview = (
                _fake_build_proxy_capture_overview
            )
            try:
                values = await coordinator._proxy_capture_values()
            finally:
                self.coordinator_snapshot_projection_module.build_proxy_capture_overview = (
                    original_builder
                )

            self.assertEqual(captured["upstream_endpoint"], "47.91.67.66,18899,TCP")
            self.assertTrue(values["proxy_capture_can_start"])

        asyncio.run(_run())

    def test_proxy_trace_manifest_download_uses_signed_authenticated_api(self) -> None:
        async def _run() -> None:
            coordinator = object.__new__(self.coordinator_module.EybondLocalCoordinator)
            coordinator._proxy_trace_download_manifest_path = ""
            coordinator._proxy_trace_download_details = ("", "")
            coordinator.config_entry = types.SimpleNamespace(entry_id="entry-id")

            async def _async_add_executor_job(func):
                return func()

            with tempfile.TemporaryDirectory() as tmp:
                manifest_path = Path(tmp) / "manifest.json"
                manifest_path.write_text("{}", encoding="utf-8")
                coordinator.hass = types.SimpleNamespace(
                    config=types.SimpleNamespace(config_dir=tmp),
                    async_add_executor_job=_async_add_executor_job,
                )
                bundle_path = Path(tmp) / "capture.zip"
                signed_url = (
                    "/api/eybond_local/proxy_capture/entry-id/capture.zip"
                    "?authSig=signed"
                )
                with patch.object(
                    self.coordinator_cloud_tools_module,
                    "export_proxy_trace_bundle",
                    return_value=bundle_path,
                ), patch.object(
                    self.coordinator_cloud_tools_module,
                    "sign_proxy_capture_download_url",
                    return_value=signed_url,
                ):
                    result = await coordinator._async_proxy_trace_manifest_download_details(
                        str(manifest_path)
                    )

            self.assertEqual(result, (str(bundle_path), signed_url))

        asyncio.run(_run())

    def test_proxy_download_paths_do_not_call_removed_absolute_url_helper(self) -> None:
        self.assertNotIn(
            "_absolute_local_download_url",
            self.coordinator_module.EybondLocalCoordinator.async_stop_proxy_capture.__code__.co_names,
        )
        self.assertNotIn(
            "_absolute_local_download_url",
            self.coordinator_module.EybondLocalCoordinator._async_proxy_trace_manifest_download_details.__code__.co_names,
        )

    def test_collector_device_info_prefers_more_complete_configured_pn(self) -> None:
        coordinator = object.__new__(self.coordinator_module.EybondLocalCoordinator)
        coordinator.config_entry = types.SimpleNamespace(
            entry_id="entry-1",
            data={
                "collector_pn": "E50000200000000001",
                "collector_ip": "192.168.1.55",
            },
            options={},
            title="Collector PN E50000200000000001",
        )
        coordinator.data = self.RuntimeSnapshot(
            values={},
            collector=types.SimpleNamespace(
                collector_pn="E5000020000000",
                profile_name="EyeBond ASCII PN v1",
                smartess_protocol_name=None,
                smartess_protocol_asset_name=None,
                smartess_collector_version="1.2.3",
            ),
        )

        info = coordinator.collector_device_info()

        self.assertEqual(info["name"], "Collector PN E50000200000000001")
        self.assertEqual(info["serial_number"], "E50000200000000001")

    def test_collector_device_info_does_not_use_configured_firmware_fallback(self) -> None:
        coordinator = object.__new__(self.coordinator_module.EybondLocalCoordinator)
        coordinator.config_entry = types.SimpleNamespace(
            entry_id="entry-1",
            data={
                "collector_pn": "V0000000000001",
                "collector_ip": "192.168.1.51",
                "smartess_collector_version": "8.50.12.3",
            },
            options={},
            title="Collector PN V0000000000001",
        )
        coordinator.data = self.RuntimeSnapshot(
            values={},
            collector=types.SimpleNamespace(
                collector_pn="V0000000000001",
                profile_name="",
                smartess_protocol_name=None,
                smartess_protocol_asset_name=None,
                smartess_collector_version="",
                collector_virtual_bridge=False,
            ),
        )

        info = coordinator.collector_device_info()

        self.assertNotIn("sw_version", info)

    def test_collector_device_info_uses_honest_identity_for_virtual_bridge(self) -> None:
        coordinator = object.__new__(self.coordinator_module.EybondLocalCoordinator)
        coordinator.config_entry = types.SimpleNamespace(
            entry_id="entry-bridge",
            data={
                "collector_pn": "E50000200000000001",
                "collector_ip": "192.0.2.55",
            },
            options={},
            title="Collector PN E50000200000000001",
        )
        coordinator.data = self.RuntimeSnapshot(
            values={"collector_virtual_bridge": True},
            collector=types.SimpleNamespace(
                collector_pn="E50000200000000001",
                profile_name="",
                smartess_protocol_name=None,
                smartess_protocol_asset_name=None,
                smartess_collector_version="",
                collector_virtual_bridge=True,
                collector_bridge_kind="esp-collector",
                collector_bridge_version="0.4.0",
            ),
        )

        info = coordinator.collector_device_info()

        self.assertEqual(info["manufacturer"], "ESP EyeBond Collector (community)")
        self.assertEqual(info["model"], "ESP EyeBond Collector")
        self.assertEqual(info["sw_version"], "0.4.0")
        self.assertEqual(
            info["configuration_url"],
            "https://github.com/groove-max/esp-eybond-collector",
        )
        self.assertEqual(info["serial_number"], "E50000200000000001")

    def test_collector_device_info_uses_persisted_bridge_profile(self) -> None:
        coordinator = object.__new__(self.coordinator_module.EybondLocalCoordinator)
        coordinator.config_entry = types.SimpleNamespace(
            entry_id="entry-bridge",
            data={
                "collector_pn": "V000405SYN94677058",
                "collector_ip": "195.138.86.175",
                "collector_kind": "esp_eybond_bridge",
                "collector_hardware_version": "esp-collector/0.1.8/ESP8266",
                "collector_bridge_version": "0.1.8",
            },
            options={},
            title="Collector PN V000405SYN94677058",
        )
        coordinator.data = self.RuntimeSnapshot(
            values={"collector_hardware_version": "esp-collector/0.1.8/ESP8266"},
            collector=types.SimpleNamespace(
                collector_pn="V000405SYN94677058",
                profile_name="",
                smartess_protocol_name=None,
                smartess_protocol_asset_name=None,
                smartess_collector_version="",
                collector_virtual_bridge=False,
                collector_bridge_kind="",
                collector_bridge_version="",
            ),
        )

        info = coordinator.collector_device_info()

        self.assertEqual(info["manufacturer"], "ESP EyeBond Collector (community)")
        self.assertEqual(info["model"], "ESP EyeBond Collector")
        self.assertEqual(info["sw_version"], "0.1.8")
        self.assertEqual(info["hw_version"], "esp-collector/0.1.8/ESP8266")

    def test_collector_device_info_does_not_use_oem_eybond_manufacturer_fallback(self) -> None:
        coordinator = object.__new__(self.coordinator_module.EybondLocalCoordinator)
        coordinator.config_entry = types.SimpleNamespace(
            entry_id="entry-unknown",
            data={"collector_pn": "V001107SYN8229"},
            options={},
            title="Collector PN V001107SYN8229",
        )
        coordinator.data = self.RuntimeSnapshot(
            values={},
            collector=types.SimpleNamespace(
                collector_pn="V001107SYN8229",
                profile_name="Unknown Collector 0x0000",
                smartess_protocol_name=None,
                smartess_protocol_asset_name=None,
                smartess_collector_version="",
                collector_virtual_bridge=False,
                collector_bridge_kind="",
                collector_bridge_version="",
            ),
        )

        info = coordinator.collector_device_info()

        self.assertNotIn("manufacturer", info)
        self.assertEqual(info["model"], "Unknown Collector 0x0000")

    def test_collector_device_registry_clears_stale_oem_eybond_fallback(self) -> None:
        registry = FakeRegistry()
        self.coordinator_module.dr.async_get = lambda hass: registry

        coordinator = object.__new__(self.coordinator_module.EybondLocalCoordinator)
        coordinator.hass = object()
        coordinator.config_entry = types.SimpleNamespace(
            entry_id="entry-unknown",
            data={"collector_pn": "V001107SYN8229"},
            options={},
            title="Collector PN V001107SYN8229",
        )
        coordinator.data = self.RuntimeSnapshot(
            values={},
            collector=types.SimpleNamespace(
                collector_pn="V001107SYN8229",
                profile_name="Unknown Collector 0x0000",
                smartess_protocol_name=None,
                smartess_protocol_asset_name=None,
                smartess_collector_version="",
                collector_virtual_bridge=False,
                collector_bridge_kind="",
                collector_bridge_version="",
            ),
        )
        coordinator._last_synced_collector_device_meta = ("", "", "", "", "", "")
        stale = registry.async_get_or_create(
            config_entry_id="entry-unknown",
            identifiers={("eybond_local", "entry-unknown:collector")},
            name="Collector PN V001107SYN8229",
            manufacturer="OEM / EyeBond",
            model="Unknown Collector 0x0000",
        )
        self.assertEqual(stale.manufacturer, "OEM / EyeBond")

        coordinator._async_sync_collector_device_registry()

        device = registry.async_get_device(
            identifiers={("eybond_local", "entry-unknown:collector")}
        )
        self.assertIsNotNone(device)
        self.assertIsNone(device.manufacturer)

    def test_remember_runtime_identity_strengthens_pending_entry_metadata(self) -> None:
        updated_entries: list[dict[str, object]] = []

        class _ConfigEntries:
            def async_update_entry(self, entry, *, title=None, data=None, options=None) -> None:
                if data is not None:
                    entry.data = dict(data)
                if options is not None:
                    entry.options = dict(options)
                if title is not None:
                    entry.title = title
                updated_entries.append(
                    {
                        "title": entry.title,
                        "data": dict(entry.data),
                    }
                )

        coordinator = object.__new__(self.coordinator_module.EybondLocalCoordinator)
        coordinator.hass = types.SimpleNamespace(config_entries=_ConfigEntries())
        coordinator.config_entry = types.SimpleNamespace(
            entry_id="entry-2",
            data={
                "collector_ip": "192.168.1.14",
                "collector_pn": "",
                "detected_model": "",
                "detected_serial": "",
                "server_ip": "192.168.1.104",
                "control_mode": "read_only",
            },
            options={"control_mode": "read_only"},
            title="Collector 192.168.1.14",
        )
        coordinator.data = self.RuntimeSnapshot()

        snapshot = self.RuntimeSnapshot(
            values={},
            inverter=types.SimpleNamespace(
                model_name="PowMr 4.2kW",
                serial_number="55355535553555",
                driver_key="pi30",
                variant_key="default",
            ),
            collector=types.SimpleNamespace(
                collector_pn="Q0000000000001",
                profile_name="EyeBond ASCII PN v1",
                smartess_protocol_name=None,
                smartess_protocol_asset_name=None,
                smartess_collector_version="8.50.12.3",
                smartess_protocol_profile_key="smartess_at",
            ),
        )

        import asyncio

        asyncio.run(coordinator._async_remember_runtime_identity(snapshot))

        self.assertEqual(
            coordinator.config_entry.data["collector_pn"],
            "Q0000000000001",
        )
        self.assertEqual(
            coordinator.config_entry.data["detected_model"],
            "PowMr 4.2kW",
        )
        self.assertEqual(
            coordinator.config_entry.data["detected_serial"],
            "55355535553555",
        )
        self.assertEqual(coordinator.config_entry.data["detected_driver"], "pi30")
        self.assertEqual(coordinator.config_entry.data["control_mode"], "read_only")
        self.assertEqual(coordinator.config_entry.options["control_mode"], "read_only")
        self.assertNotIn("driver_hint", coordinator.config_entry.data)
        self.assertEqual(
            coordinator.config_entry.data["collector_cloud_profile_key"],
            "smartess_at",
        )
        self.assertEqual(
            coordinator.config_entry.data["collector_cloud_profile_source"],
            "runtime_observed",
        )
        self.assertEqual(
            coordinator.config_entry.data["collector_cloud_profile_confidence"],
            "high",
        )
        self.assertEqual(
            coordinator.config_entry.title,
            "Collector PN Q0000000000001",
        )
        self.assertEqual(len(updated_entries), 1)

    def test_remember_runtime_identity_collector_only_does_not_erase_inverter(self) -> None:
        # Runtime state-machine invariant: a collector-only snapshot (no inverter)
        # must not erase a previously confirmed inverter identity.
        class _ConfigEntries:
            def async_update_entry(self, entry, *, title=None, data=None, options=None) -> None:
                del title, options
                if data is not None:
                    entry.data = dict(data)

        coordinator = object.__new__(self.coordinator_module.EybondLocalCoordinator)
        coordinator.hass = types.SimpleNamespace(config_entries=_ConfigEntries())
        coordinator.config_entry = types.SimpleNamespace(
            entry_id="entry-3",
            data={
                "collector_ip": "192.168.1.14",
                "collector_pn": "Q0000000000001",
                "detected_model": "PowMr 4.2kW",
                "detected_serial": "55355535553555",
                "detection_confidence": "high",
                "driver_hint": "pi30",
                "server_ip": "192.168.1.104",
            },
            options={},
            title="PowMr 4.2kW (55355535553555)",
        )
        coordinator.data = self.RuntimeSnapshot()

        collector_only = self.RuntimeSnapshot(
            values={},
            inverter=None,
            collector=types.SimpleNamespace(
                collector_pn="Q0000000000001",
                profile_name="EyeBond ASCII PN v1",
                smartess_protocol_name=None,
                smartess_protocol_asset_name=None,
                smartess_collector_version="8.50.12.3",
                smartess_protocol_profile_key="smartess_at",
            ),
        )

        import asyncio

        asyncio.run(coordinator._async_remember_runtime_identity(collector_only))

        self.assertEqual(coordinator.config_entry.data["detected_model"], "PowMr 4.2kW")
        self.assertEqual(
            coordinator.config_entry.data["detected_serial"], "55355535553555"
        )

    def test_remember_runtime_identity_different_serial_keeps_durable(self) -> None:
        # Runtime state-machine invariant 6: a different confirmed serial is a
        # conflict, not a silent swap of the durable inverter identity.
        class _ConfigEntries:
            def async_update_entry(self, entry, *, title=None, data=None, options=None) -> None:
                del title, options
                if data is not None:
                    entry.data = dict(data)

        coordinator = object.__new__(self.coordinator_module.EybondLocalCoordinator)
        coordinator.hass = types.SimpleNamespace(config_entries=_ConfigEntries())
        coordinator.config_entry = types.SimpleNamespace(
            entry_id="entry-4",
            data={
                "collector_ip": "192.168.1.14",
                "collector_pn": "Q0000000000001",
                "detected_model": "PowMr 4.2kW",
                "detected_serial": "55355535553555",
                "detection_confidence": "high",
                "driver_hint": "pi30",
                "server_ip": "192.168.1.104",
            },
            options={},
            title="PowMr 4.2kW (55355535553555)",
        )
        coordinator.data = self.RuntimeSnapshot()

        conflicting = self.RuntimeSnapshot(
            values={},
            inverter=types.SimpleNamespace(
                model_name="PowMr 4.2kW",
                serial_number="55355599999999",
                driver_key="pi30",
                variant_key="default",
            ),
            collector=types.SimpleNamespace(
                collector_pn="Q0000000000001",
                profile_name="EyeBond ASCII PN v1",
                smartess_protocol_name=None,
                smartess_protocol_asset_name=None,
                smartess_collector_version="8.50.12.3",
                smartess_protocol_profile_key="smartess_at",
            ),
        )

        import asyncio

        asyncio.run(coordinator._async_remember_runtime_identity(conflicting))

        # Durable serial is kept; the different serial is not silently swapped in.
        self.assertEqual(
            coordinator.config_entry.data["detected_serial"], "55355535553555"
        )

    def test_remember_runtime_identity_does_not_persist_callback_peer_ip(self) -> None:
        updated_entries: list[dict[str, object]] = []

        class _ConfigEntries:
            def async_update_entry(self, entry, *, title=None, data=None, options=None) -> None:
                del options
                if data is not None:
                    entry.data = dict(data)
                if title is not None:
                    entry.title = title
                updated_entries.append(
                    {
                        "title": entry.title,
                        "data": dict(entry.data),
                    }
                )

        coordinator = object.__new__(self.coordinator_module.EybondLocalCoordinator)
        coordinator.hass = types.SimpleNamespace(config_entries=_ConfigEntries())
        coordinator.config_entry = types.SimpleNamespace(
            entry_id="entry-callback",
            data={
                "connection_mode": "callback_listener",
                "collector_pn": "V001020SYN62344022",
                "detected_model": "",
                "detected_serial": "",
                "server_ip": "192.168.1.104",
            },
            options={},
            title="Collector PN V001020SYN62344022",
        )
        coordinator.data = self.RuntimeSnapshot()

        snapshot = self.RuntimeSnapshot(
            values={},
            inverter=types.SimpleNamespace(
                model_name="PowMr 4.2kW",
                serial_number="55355535553555",
            ),
            collector=types.SimpleNamespace(
                remote_ip="195.138.86.175",
                collector_pn="V001020SYN62344022",
                profile_name="",
                smartess_protocol_name=None,
                smartess_protocol_asset_name=None,
                smartess_collector_version="",
                smartess_protocol_profile_key="smartess_at",
            ),
        )

        asyncio.run(coordinator._async_remember_runtime_identity(snapshot))

        self.assertNotIn("collector_ip", coordinator.config_entry.data)
        self.assertEqual(
            coordinator.config_entry.data["collector_pn"],
            "V001020SYN62344022",
        )
        self.assertEqual(len(updated_entries), 1)

    def test_remember_runtime_identity_does_not_replace_routed_ip_with_nat_peer(
        self,
    ) -> None:
        """A live TCP peer is observation, not the configured collector route."""

        updated_entries: list[dict[str, object]] = []

        class _ConfigEntries:
            def async_update_entry(
                self,
                entry,
                *,
                title=None,
                data=None,
                options=None,
            ) -> None:
                del options
                if data is not None:
                    entry.data = dict(data)
                if title is not None:
                    entry.title = title
                updated_entries.append(dict(entry.data))

        coordinator = object.__new__(self.coordinator_module.EybondLocalCoordinator)
        coordinator.hass = types.SimpleNamespace(config_entries=_ConfigEntries())
        coordinator.config_entry = types.SimpleNamespace(
            entry_id="entry-routed",
            data={
                "connection_mode": "known_ip",
                "collector_ip": "192.168.8.52",
                "collector_pn": "V001020SYN62344022",
                "detected_model": "",
                "detected_serial": "",
                "server_ip": "192.168.2.50",
            },
            options={},
            title="Collector PN V001020SYN62344022",
        )
        coordinator.data = self.RuntimeSnapshot()

        snapshot = self.RuntimeSnapshot(
            values={},
            inverter=types.SimpleNamespace(
                model_name="PowMr 6.2kW",
                serial_number="55355535553555",
            ),
            collector=types.SimpleNamespace(
                remote_ip="192.168.2.1",
                collector_pn="V001020SYN62344022",
                profile_name="",
                smartess_protocol_name=None,
                smartess_protocol_asset_name=None,
                smartess_collector_version="",
                smartess_protocol_profile_key="smartess_at",
            ),
        )

        asyncio.run(coordinator._async_remember_runtime_identity(snapshot))

        self.assertEqual(
            coordinator.config_entry.data["collector_ip"],
            "192.168.8.52",
        )
        self.assertNotEqual(
            coordinator.config_entry.data["collector_ip"],
            snapshot.collector.remote_ip,
        )
        self.assertEqual(updated_entries[-1]["collector_ip"], "192.168.8.52")

    def test_remember_runtime_identity_upgrades_collector_unique_id_to_full_pn(self) -> None:
        updated_entries: list[dict[str, object]] = []

        class _ConfigEntries:
            def async_update_entry(
                self,
                entry,
                *,
                title=None,
                data=None,
                options=None,
                unique_id=None,
            ) -> None:
                del options
                if data is not None:
                    entry.data = dict(data)
                if title is not None:
                    entry.title = title
                if unique_id is not None:
                    entry.unique_id = unique_id
                updated_entries.append(
                    {
                        "title": entry.title,
                        "data": dict(entry.data),
                        "unique_id": entry.unique_id,
                    }
                )

        coordinator = object.__new__(self.coordinator_module.EybondLocalCoordinator)
        coordinator.hass = types.SimpleNamespace(config_entries=_ConfigEntries())
        coordinator.config_entry = types.SimpleNamespace(
            entry_id="entry-callback",
            unique_id="collector:V001107SYN8229",
            data={
                "connection_mode": "callback_listener",
                "collector_pn": "V001107SYN82291016",
                "detected_model": "",
                "detected_serial": "",
                "server_ip": "192.168.1.104",
            },
            options={},
            title="Collector PN V001107SYN82291016",
        )
        coordinator.data = self.RuntimeSnapshot()

        snapshot = self.RuntimeSnapshot(
            values={},
            collector=types.SimpleNamespace(
                remote_ip="192.168.1.1",
                collector_pn="V001107SYN82291016",
                profile_name="",
                smartess_protocol_name=None,
                smartess_protocol_asset_name=None,
                smartess_collector_version="",
                smartess_protocol_profile_key="smartess_at",
            ),
        )

        asyncio.run(coordinator._async_remember_runtime_identity(snapshot))

        self.assertEqual(
            coordinator.config_entry.data["collector_pn"],
            "V001107SYN82291016",
        )
        self.assertEqual(
            coordinator.config_entry.unique_id,
            "collector:V001107SYN82291016",
        )
        self.assertEqual(
            updated_entries[-1]["unique_id"],
            "collector:V001107SYN82291016",
        )

    def test_remember_runtime_identity_requests_reload_after_platform_setup(self) -> None:
        updated_entries: list[dict[str, object]] = []
        reload_requests: list[str] = []

        class _ConfigEntries:
            def async_update_entry(self, entry, *, title=None, data=None, options=None) -> None:
                del options
                if data is not None:
                    entry.data = dict(data)
                if title is not None:
                    entry.title = title
                updated_entries.append(
                    {
                        "title": entry.title,
                        "data": dict(entry.data),
                    }
                )

            async def async_reload(self, entry_id: str) -> None:
                reload_requests.append(entry_id)

        coordinator = object.__new__(self.coordinator_module.EybondLocalCoordinator)
        coordinator.hass = types.SimpleNamespace(
            config_entries=_ConfigEntries(),
            async_create_task=lambda coro: asyncio.create_task(coro),
        )
        coordinator.config_entry = types.SimpleNamespace(
            entry_id="entry-3",
            data={
                "collector_ip": "192.168.1.14",
                "collector_pn": "",
                "detected_model": "",
                "detected_serial": "",
                "server_ip": "192.168.1.104",
            },
            options={},
            title="Collector 192.168.1.14",
        )
        coordinator.data = self.RuntimeSnapshot()
        coordinator._entity_platforms_initialized = True
        coordinator._entity_platform_reload_requested = False
        coordinator._entity_platforms_loaded_with_inverter_identity = True

        snapshot = self.RuntimeSnapshot(
            values={},
            inverter=types.SimpleNamespace(
                model_name="PowMr 4.2kW",
                serial_number="55355535553555",
            ),
            collector=types.SimpleNamespace(
                collector_pn="Q0000000000001",
                profile_name="EyeBond ASCII PN v1",
                smartess_protocol_name=None,
                smartess_protocol_asset_name=None,
                smartess_collector_version="8.50.12.3",
            ),
        )

        async def _run() -> None:
            await coordinator._async_remember_runtime_identity(snapshot)
            await asyncio.sleep(0)

        asyncio.run(_run())

        self.assertEqual(
            coordinator.config_entry.data["detected_model"],
            "PowMr 4.2kW",
        )
        self.assertEqual(len(updated_entries), 1)
        self.assertEqual(reload_requests, ["entry-3"])
        self.assertTrue(coordinator._entity_platform_reload_requested)

    def test_remember_runtime_identity_clears_stale_0925_register_serial(self) -> None:
        updated_entries: list[dict[str, object]] = []

        class _ConfigEntries:
            def async_update_entry(self, entry, *, title=None, data=None, options=None) -> None:
                if data is not None:
                    entry.data = dict(data)
                if options is not None:
                    entry.options = dict(options)
                if title is not None:
                    entry.title = title
                updated_entries.append({"title": entry.title, "data": dict(entry.data)})

        coordinator = object.__new__(self.coordinator_module.EybondLocalCoordinator)
        coordinator.hass = types.SimpleNamespace(config_entries=_ConfigEntries())
        coordinator.config_entry = types.SimpleNamespace(
            entry_id="entry-0925",
            data={
                "collector_ip": "192.168.1.14",
                "collector_pn": "Q0000000000001",
                "detected_model": "PowMr 4.2kW / VMII-NXPW5KW (SmartESS 0925)",
                "detected_serial": "55355535553555",
                "server_ip": "192.168.1.50",
            },
            options={},
            title="Collector PN Q0000000000001",
        )
        coordinator.data = self.RuntimeSnapshot()

        snapshot = self.RuntimeSnapshot(
            values={},
            inverter=types.SimpleNamespace(
                driver_key="smartess_local",
                model_name="PowMr 4.2kW / VMII-NXPW5KW (SmartESS 0925)",
                serial_number="",
                variant_key="smartess_0925",
            ),
            collector=types.SimpleNamespace(
                collector_pn="Q0000000000001",
                profile_name="EyeBond ASCII PN v1",
                smartess_protocol_name=None,
                smartess_protocol_asset_name=None,
                smartess_collector_version="3.6.7.6",
            ),
        )

        import asyncio

        asyncio.run(coordinator._async_remember_runtime_identity(snapshot))

        self.assertEqual(coordinator.config_entry.data["detected_serial"], "")
        self.assertEqual(len(updated_entries), 1)

    def test_remember_runtime_identity_clears_stale_pi30_placeholder(self) -> None:
        updated_entries: list[dict[str, object]] = []

        class _ConfigEntries:
            def async_update_entry(self, entry, *, title=None, data=None, options=None) -> None:
                if data is not None:
                    entry.data = dict(data)
                if options is not None:
                    entry.options = dict(options)
                if title is not None:
                    entry.title = title
                updated_entries.append({"title": entry.title, "data": dict(entry.data)})

        coordinator = object.__new__(self.coordinator_module.EybondLocalCoordinator)
        coordinator.hass = types.SimpleNamespace(config_entries=_ConfigEntries())
        coordinator.config_entry = types.SimpleNamespace(
            entry_id="entry-pi30-placeholder",
            data={
                "collector_ip": "192.168.1.14",
                "collector_pn": "Q0000000000001",
                "detected_model": "PI30 4200",
                "detected_serial": "55355535553555",
                "server_ip": "192.168.1.50",
            },
            options={},
            title="Collector PN Q0000000000001",
        )
        coordinator.data = self.RuntimeSnapshot()
        snapshot = self.RuntimeSnapshot(
            values={},
            inverter=types.SimpleNamespace(
                driver_key="pi30",
                model_name="PI30 4200",
                serial_number="",
                variant_key="default",
                details={
                    "reported_serial_number": "55355535553555",
                    "serial_identity_source": "qid",
                    "serial_identity_trust": "untrusted",
                    "serial_identity_reason": "known_placeholder",
                },
            ),
            collector=types.SimpleNamespace(
                collector_pn="Q0000000000001",
                profile_name="EyeBond ASCII PN v1",
                smartess_protocol_name=None,
                smartess_protocol_asset_name=None,
                smartess_collector_version="3.6.7.6",
            ),
        )

        import asyncio

        asyncio.run(coordinator._async_remember_runtime_identity(snapshot))

        self.assertEqual(coordinator.config_entry.data["detected_serial"], "")
        self.assertEqual(len(updated_entries), 1)

    def test_remember_runtime_identity_persists_effective_snapshot_in_options(self) -> None:
        updated_entries: list[dict[str, object]] = []
        from custom_components.eybond_local.metadata.compiled_detection_catalog import (
            load_compiled_detection_catalog,
        )

        catalog = load_compiled_detection_catalog()
        descriptor_revision = catalog.devices["smg_6200"].revision

        class _ConfigEntries:
            def async_update_entry(self, entry, *, title=None, data=None, options=None) -> None:
                if data is not None:
                    entry.data = dict(data)
                if options is not None:
                    entry.options = dict(options)
                if title is not None:
                    entry.title = title
                updated_entries.append(
                    {
                        "title": entry.title,
                        "data": dict(entry.data),
                        "options": dict(entry.options),
                    }
                )

        coordinator = object.__new__(self.coordinator_module.EybondLocalCoordinator)
        coordinator.hass = types.SimpleNamespace(config_entries=_ConfigEntries())
        coordinator.config_entry = types.SimpleNamespace(
            entry_id="entry-6",
            data={
                "collector_ip": "192.168.1.14",
                "collector_pn": "",
                "detected_model": "",
                "detected_serial": "",
                "detection_confidence": "medium",
                "server_ip": "192.168.1.104",
                "driver_hint": "auto",
            },
            options={},
            title="Collector 192.168.1.14",
        )
        coordinator.data = self.RuntimeSnapshot()
        coordinator._entity_platforms_initialized = False
        coordinator._entity_platform_reload_requested = False
        coordinator._entity_platforms_loaded_with_inverter_identity = True

        snapshot = self.RuntimeSnapshot(
            values={},
            inverter=types.SimpleNamespace(
                model_name="PowMr 4.2kW",
                serial_number="55355535553555",
                driver_key="modbus_smg",
                variant_key="default",
                profile_name="modbus_smg/models/smg_6200.json",
                register_schema_name="modbus_smg/models/smg_6200.json",
                details={
                    "catalog_detection": {
                        "candidate_keys": ["smg_6200"],
                        "resolution": "exact",
                        "surface_key": "smg_6200_full",
                        "evidence_fingerprint": "fingerprint",
                        "catalog_version": catalog.catalog_version,
                        "descriptor_revisions": [
                            f"smg_6200:{descriptor_revision}"
                        ],
                    }
                },
            ),
            collector=types.SimpleNamespace(
                collector_pn="Q0000000000001",
                profile_name="EyeBond ASCII PN v1",
                smartess_protocol_name=None,
                smartess_protocol_asset_name=None,
                smartess_collector_version="8.50.12.3",
            ),
        )

        asyncio.run(coordinator._async_remember_runtime_identity(snapshot))

        self.assertEqual(coordinator.config_entry.data["detected_model"], "PowMr 4.2kW")
        self.assertEqual(coordinator.config_entry.data["detected_serial"], "55355535553555")
        self.assertEqual(coordinator.config_entry.data["detection_confidence"], "high")

        persisted_snapshot = coordinator.config_entry.options.get("effective_metadata_snapshot")
        self.assertIsInstance(persisted_snapshot, dict)
        assert isinstance(persisted_snapshot, dict)
        self.assertEqual(persisted_snapshot.get("effective_owner_key"), "modbus_smg")
        self.assertEqual(
            persisted_snapshot.get("profile_name"),
            "modbus_smg/models/smg_6200.json",
        )
        self.assertEqual(
            persisted_snapshot.get("register_schema_name"),
            "modbus_smg/models/smg_6200.json",
        )
        self.assertNotIn("collector_cloud_profile_key", persisted_snapshot)
        self.assertNotIn("collector_cloud_profile_label", persisted_snapshot)
        self.assertNotIn("collector_cloud_profile_source", persisted_snapshot)
        self.assertNotIn("collector_cloud_profile_confidence", persisted_snapshot)
        self.assertEqual(persisted_snapshot.get("confidence"), "high")
        self.assertEqual(persisted_snapshot.get("candidate_keys"), ["smg_6200"])
        self.assertEqual(persisted_snapshot.get("resolution_level"), "exact")
        self.assertEqual(persisted_snapshot.get("surface_key"), "smg_6200_full")
        self.assertEqual(
            persisted_snapshot.get("evidence_fingerprint"),
            "fingerprint",
        )
        self.assertEqual(
            persisted_snapshot.get("catalog_version"),
            catalog.catalog_version,
        )
        self.assertEqual(
            persisted_snapshot.get("descriptor_revisions"),
            [f"smg_6200:{descriptor_revision}"],
        )
        self.assertEqual(persisted_snapshot.get("generation"), 1)
        self.assertTrue(str(persisted_snapshot.get("generated_at") or ""))
        self.assertEqual(len(updated_entries), 1)

    def test_remember_runtime_identity_skips_snapshot_rewrite_when_unchanged(self) -> None:
        updated_entries: list[dict[str, object]] = []

        class _ConfigEntries:
            def async_update_entry(self, entry, *, title=None, data=None, options=None) -> None:
                if data is not None:
                    entry.data = dict(data)
                if options is not None:
                    entry.options = dict(options)
                if title is not None:
                    entry.title = title
                updated_entries.append(
                    {
                        "title": entry.title,
                        "data": dict(entry.data),
                        "options": dict(entry.options),
                    }
                )

        coordinator = object.__new__(self.coordinator_module.EybondLocalCoordinator)
        coordinator.hass = types.SimpleNamespace(config_entries=_ConfigEntries())
        coordinator.config_entry = types.SimpleNamespace(
            entry_id="entry-6b",
            data={
                "collector_ip": "192.168.1.14",
                "collector_pn": "",
                "detected_model": "",
                "detected_serial": "",
                "detection_confidence": "medium",
                "server_ip": "192.168.1.104",
                "driver_hint": "auto",
            },
            options={},
            title="Collector 192.168.1.14",
        )
        coordinator.data = self.RuntimeSnapshot()
        coordinator._entity_platforms_initialized = False
        coordinator._entity_platform_reload_requested = False
        coordinator._entity_platforms_loaded_with_inverter_identity = True

        snapshot = self.RuntimeSnapshot(
            values={},
            inverter=types.SimpleNamespace(
                model_name="PowMr 4.2kW",
                serial_number="55355535553555",
                driver_key="modbus_smg",
                variant_key="powmr_4200_protocol_1",
                profile_name="modbus_smg/models/powmr_4200_protocol_1.json",
                register_schema_name="modbus_smg/models/powmr_4200_protocol_1.json",
            ),
            collector=types.SimpleNamespace(
                collector_pn="Q0000000000001",
                profile_name="EyeBond ASCII PN v1",
                smartess_protocol_name=None,
                smartess_protocol_asset_name=None,
                smartess_collector_version="8.50.12.3",
            ),
        )

        asyncio.run(coordinator._async_remember_runtime_identity(snapshot))
        first_snapshot = dict(
            coordinator.config_entry.options.get("effective_metadata_snapshot") or {}
        )
        self.assertTrue(first_snapshot)
        self.assertEqual(first_snapshot.get("generation"), 1)
        self.assertEqual(len(updated_entries), 1)

        asyncio.run(coordinator._async_remember_runtime_identity(snapshot))

        second_snapshot = dict(
            coordinator.config_entry.options.get("effective_metadata_snapshot") or {}
        )
        self.assertEqual(len(updated_entries), 1)
        self.assertEqual(second_snapshot, first_snapshot)
        self.assertEqual(second_snapshot.get("generation"), 1)

    def test_remember_runtime_identity_does_not_persist_snapshot_without_live_identity(self) -> None:
        update_calls: list[dict[str, object]] = []

        class _ConfigEntries:
            def async_update_entry(self, entry, *, title=None, data=None, options=None) -> None:
                if data is not None:
                    entry.data = dict(data)
                if options is not None:
                    entry.options = dict(options)
                if title is not None:
                    entry.title = title
                update_calls.append(
                    {
                        "title": entry.title,
                        "data": dict(entry.data),
                        "options": dict(entry.options),
                    }
                )

        coordinator = object.__new__(self.coordinator_module.EybondLocalCoordinator)
        coordinator.hass = types.SimpleNamespace(config_entries=_ConfigEntries())
        coordinator.config_entry = types.SimpleNamespace(
            entry_id="entry-7",
            data={
                "collector_ip": "192.168.1.14",
                "collector_pn": "Q0000000000001",
                "detected_model": "",
                "detected_serial": "",
                "driver_hint": "modbus_smg",
                "detection_confidence": "none",
                "server_ip": "192.168.1.104",
            },
            options={"driver_hint": "modbus_smg"},
            title="Collector PN Q0000000000001",
        )
        coordinator.data = self.RuntimeSnapshot()
        coordinator._entity_platforms_initialized = False
        coordinator._entity_platform_reload_requested = False
        coordinator._entity_platforms_loaded_with_inverter_identity = True

        snapshot = self.RuntimeSnapshot(
            values={},
            inverter=types.SimpleNamespace(
                model_name="",
                serial_number="",
                driver_key="modbus_smg",
                variant_key="powmr_4200_protocol_1",
                profile_name="modbus_smg/models/powmr_4200_protocol_1.json",
                register_schema_name="modbus_smg/models/powmr_4200_protocol_1.json",
            ),
            collector=types.SimpleNamespace(
                collector_pn="Q0000000000001",
                profile_name="EyeBond ASCII PN v1",
                smartess_protocol_name=None,
                smartess_protocol_asset_name=None,
                smartess_collector_version="8.50.12.3",
            ),
        )

        asyncio.run(coordinator._async_remember_runtime_identity(snapshot))

        self.assertEqual(len(update_calls), 1)
        self.assertNotIn(
            "effective_metadata_snapshot",
            update_calls[0]["options"],
        )
        self.assertNotIn("effective_metadata_snapshot", coordinator.config_entry.options)

    def test_remember_runtime_identity_requests_reload_when_platforms_loaded_collector_only(self) -> None:
        reload_requests: list[str] = []

        class _ConfigEntries:
            def async_update_entry(self, entry, *, title=None, data=None, options=None) -> None:
                if data is not None:
                    entry.data = dict(data)
                if title is not None:
                    entry.title = title

            async def async_reload(self, entry_id: str) -> None:
                reload_requests.append(entry_id)

        coordinator = object.__new__(self.coordinator_module.EybondLocalCoordinator)
        coordinator.hass = types.SimpleNamespace(
            config_entries=_ConfigEntries(),
            async_create_task=lambda coro: asyncio.create_task(coro),
        )
        coordinator.config_entry = types.SimpleNamespace(
            entry_id="entry-5",
            data={
                "collector_ip": "192.168.1.14",
                "collector_pn": "Q0000000000001",
                "detected_model": "PowMr 4.2kW",
                "detected_serial": "55355535553555",
                "server_ip": "192.168.1.104",
            },
            options={},
            title="Collector PN Q0000000000001",
        )
        coordinator.data = self.RuntimeSnapshot()
        coordinator._entity_platforms_initialized = True
        coordinator._entity_platform_reload_requested = False
        coordinator._entity_platforms_loaded_with_inverter_identity = False

        snapshot = self.RuntimeSnapshot(
            values={},
            inverter=types.SimpleNamespace(
                model_name="PowMr 4.2kW",
                serial_number="55355535553555",
            ),
            collector=types.SimpleNamespace(
                collector_pn="Q0000000000001",
                profile_name="EyeBond ASCII PN v1",
                smartess_protocol_name=None,
                smartess_protocol_asset_name=None,
                smartess_collector_version="8.50.12.3",
            ),
        )

        async def _run() -> None:
            await coordinator._async_remember_runtime_identity(snapshot)
            await asyncio.sleep(0)

        asyncio.run(_run())

        self.assertEqual(reload_requests, ["entry-5"])
        self.assertTrue(coordinator._entity_platform_reload_requested)

    def test_mark_entity_platforms_initialized_requests_reload_when_identity_arrived_during_setup(self) -> None:
        reload_requests: list[str] = []

        class _ConfigEntries:
            async def async_reload(self, entry_id: str) -> None:
                reload_requests.append(entry_id)

        coordinator = object.__new__(self.coordinator_module.EybondLocalCoordinator)
        coordinator.hass = types.SimpleNamespace(
            config_entries=_ConfigEntries(),
            async_create_task=lambda coro: asyncio.create_task(coro),
        )
        coordinator.config_entry = types.SimpleNamespace(entry_id="entry-4")
        coordinator.data = self.RuntimeSnapshot(
            inverter=types.SimpleNamespace(
                model_name="PowMr 4.2kW",
                serial_number="55355535553555",
            )
        )
        coordinator._entity_platforms_initialized = False
        coordinator._entity_platform_reload_requested = False

        async def _run() -> None:
            coordinator.mark_entity_platforms_initialized(has_inverter_identity=False)
            await asyncio.sleep(0)

        asyncio.run(_run())

        self.assertTrue(coordinator._entity_platforms_initialized)
        self.assertFalse(coordinator._entity_platforms_loaded_with_inverter_identity)
        self.assertTrue(coordinator._entity_platform_reload_requested)
        self.assertEqual(reload_requests, ["entry-4"])

    def test_identity_reload_waits_until_config_entry_is_loaded(self) -> None:
        reload_requests: list[str] = []
        state_callbacks: list[object] = []
        config_entry_state = sys.modules[
            "homeassistant.config_entries"
        ].ConfigEntryState

        class _ConfigEntries:
            async def async_reload(self, entry_id: str) -> None:
                reload_requests.append(entry_id)

        entry = types.SimpleNamespace(
            entry_id="entry-setup-race",
            state=config_entry_state.SETUP_IN_PROGRESS,
        )

        def _on_state_change(callback):
            state_callbacks.append(callback)
            return lambda: state_callbacks.remove(callback)

        entry.async_on_state_change = _on_state_change
        coordinator = object.__new__(self.coordinator_module.EybondLocalCoordinator)
        coordinator.hass = types.SimpleNamespace(
            config_entries=_ConfigEntries(),
            async_create_task=lambda coro: asyncio.create_task(coro),
            loop=types.SimpleNamespace(
                call_later=lambda delay, callback: asyncio.get_running_loop().call_later(
                    delay, callback
                )
            ),
        )
        coordinator.config_entry = entry
        coordinator.data = self.RuntimeSnapshot(
            inverter=types.SimpleNamespace(
                model_name="PowMr 4.2kW",
                serial_number="55355535553555",
            )
        )
        coordinator._entity_platforms_initialized = False
        coordinator._entity_platform_reload_requested = False
        coordinator._entity_platform_reload_dispatched = False
        coordinator._entry_loaded_reload_unsub = None
        coordinator._shutdown_complete = False

        async def _run() -> None:
            coordinator.mark_entity_platforms_initialized(
                has_inverter_identity=False
            )
            await asyncio.sleep(0)
            self.assertEqual(reload_requests, [])
            self.assertEqual(len(state_callbacks), 1)

            entry.state = config_entry_state.LOADED
            state_callbacks[0]()
            self.assertEqual(reload_requests, [])
            await asyncio.sleep(0)
            await asyncio.sleep(0)

        asyncio.run(_run())

        self.assertEqual(reload_requests, ["entry-setup-race"])
        self.assertTrue(coordinator._entity_platform_reload_dispatched)

    def test_identity_reload_waits_on_component_readiness_without_event_race(self) -> None:
        reload_requests: list[str] = []
        waiters: set[object] = set()

        class _ConfigEntries:
            async def async_reload(self, entry_id: str) -> None:
                reload_requests.append(entry_id)

        coordinator = object.__new__(self.coordinator_module.EybondLocalCoordinator)
        coordinator.hass = types.SimpleNamespace(
            data={
                "eybond_local": {
                    "component_setup_complete": False,
                    "component_setup_reload_waiters": waiters,
                }
            },
            config_entries=_ConfigEntries(),
            async_create_task=lambda coro: asyncio.create_task(coro),
            loop=types.SimpleNamespace(
                is_closed=lambda: False,
                call_soon_threadsafe=lambda callback: asyncio.get_running_loop().call_soon(
                    callback
                ),
            ),
        )
        coordinator.config_entry = types.SimpleNamespace(entry_id="entry-component-race")
        coordinator.data = self.RuntimeSnapshot(
            inverter=types.SimpleNamespace(
                model_name="PowMr 4.2kW",
                serial_number="55355535553555",
            )
        )
        coordinator._entity_platforms_initialized = False
        coordinator._entity_platform_reload_requested = False
        coordinator._entity_platform_reload_dispatched = False
        coordinator._component_loaded_reload_unsub = None
        coordinator._shutdown_complete = False

        async def _run() -> None:
            coordinator.mark_entity_platforms_initialized(
                has_inverter_identity=False
            )
            self.assertEqual(reload_requests, [])
            self.assertEqual(len(waiters), 1)

            # EVENT_COMPONENT_LOADED has already been delivered, but its
            # call_soon readiness marker has not run yet. Publishing readiness
            # must wake the registered reload without requiring a second event.
            domain_data = coordinator.hass.data["eybond_local"]
            domain_data["component_setup_complete"] = True
            callbacks = tuple(waiters)
            waiters.clear()
            for callback in callbacks:
                callback()
            await asyncio.sleep(0)
            await asyncio.sleep(0)

        asyncio.run(_run())

        self.assertEqual(reload_requests, ["entry-component-race"])
        self.assertTrue(coordinator._entity_platform_reload_dispatched)

    def test_remember_runtime_identity_requests_reload_on_effective_metadata_drift(self) -> None:
        reload_requests: list[str] = []

        class _ConfigEntries:
            def async_update_entry(self, entry, *, title=None, data=None, options=None) -> None:
                if data is not None:
                    entry.data = dict(data)
                if options is not None:
                    entry.options = dict(options)
                if title is not None:
                    entry.title = title

            async def async_reload(self, entry_id: str) -> None:
                reload_requests.append(entry_id)

        coordinator = object.__new__(self.coordinator_module.EybondLocalCoordinator)
        coordinator.hass = types.SimpleNamespace(
            config_entries=_ConfigEntries(),
            async_create_task=lambda coro: asyncio.create_task(coro),
        )
        coordinator.config_entry = types.SimpleNamespace(
            entry_id="entry-drift",
            data={
                "collector_ip": "192.168.1.14",
                "collector_pn": "Q0000000000001",
                "detected_model": "SMG 6200",
                "detected_serial": "SMG-123",
                "detection_confidence": "high",
                "server_ip": "192.168.1.104",
                "driver_hint": "modbus_smg",
            },
            options={
                "effective_metadata_snapshot": {
                    "effective_owner_key": "modbus_smg",
                    "effective_owner_name": "modbus_smg",
                    "variant_key": "smg_default",
                    "profile_name": "modbus_smg/models/smg_default.json",
                    "register_schema_name": "modbus_smg/models/smg_default.json",
                    "confidence": "high",
                    "generation": 1,
                    "generated_at": "2026-06-01T00:00:00+00:00",
                }
            },
            title="Collector PN Q0000000000001",
        )
        coordinator.data = self.RuntimeSnapshot(
            inverter=types.SimpleNamespace(
                model_name="SMG 6200",
                serial_number="SMG-123",
            )
        )
        coordinator._entity_platforms_initialized = False
        coordinator._entity_platform_reload_requested = False
        coordinator._entity_platforms_loaded_with_inverter_identity = False
        coordinator._platform_loaded_effective_metadata_signature = ("", "", "")

        coordinator.mark_entity_platforms_initialized(has_inverter_identity=True)

        snapshot = self.RuntimeSnapshot(
            values={},
            inverter=types.SimpleNamespace(
                model_name="SMG 6200",
                serial_number="SMG-123",
                driver_key="modbus_smg",
                variant_key="anenji_4200_protocol_1",
                profile_name="modbus_smg/models/anenji_4200_protocol_1.json",
                register_schema_name="modbus_smg/models/anenji_4200_protocol_1.json",
            ),
            collector=types.SimpleNamespace(
                collector_pn="Q0000000000001",
                profile_name="EyeBond ASCII PN v1",
                smartess_protocol_name=None,
                smartess_protocol_asset_name=None,
                smartess_collector_version="8.50.12.3",
            ),
        )

        async def _run() -> None:
            await coordinator._async_remember_runtime_identity(snapshot)
            await asyncio.sleep(0)

        asyncio.run(_run())

        self.assertEqual(reload_requests, ["entry-drift"])
        self.assertTrue(coordinator._entity_platform_reload_requested)

    def test_remember_runtime_identity_requests_reload_for_first_runtime_signature_after_upgrade(self) -> None:
        reload_requests: list[str] = []

        class _ConfigEntries:
            def async_update_entry(self, entry, *, title=None, data=None, options=None) -> None:
                if data is not None:
                    entry.data = dict(data)
                if options is not None:
                    entry.options = dict(options)
                if title is not None:
                    entry.title = title

            async def async_reload(self, entry_id: str) -> None:
                reload_requests.append(entry_id)

        coordinator = object.__new__(self.coordinator_module.EybondLocalCoordinator)
        coordinator.hass = types.SimpleNamespace(
            config_entries=_ConfigEntries(),
            async_create_task=lambda coro: asyncio.create_task(coro),
        )
        coordinator.config_entry = types.SimpleNamespace(
            entry_id="entry-upgrade-first-runtime-signature",
            data={
                "collector_ip": "192.168.1.14",
                "collector_pn": "Q0000000000001",
                "detected_model": "SMG 6200",
                "detected_serial": "SMG-123",
                "detection_confidence": "high",
                "server_ip": "192.168.1.104",
                "driver_hint": "modbus_smg",
            },
            options={},
            title="Collector PN Q0000000000001",
        )
        coordinator.data = self.RuntimeSnapshot(
            inverter=types.SimpleNamespace(
                model_name="SMG 6200",
                serial_number="SMG-123",
            )
        )
        coordinator._entity_platforms_initialized = False
        coordinator._entity_platform_reload_requested = False
        coordinator._entity_platforms_loaded_with_inverter_identity = False
        coordinator._entity_platforms_loaded_with_driver_fallback = False
        coordinator._platform_loaded_effective_metadata_signature = ("", "", "")

        coordinator.mark_entity_platforms_initialized(has_inverter_identity=True)

        snapshot = self.RuntimeSnapshot(
            values={},
            inverter=types.SimpleNamespace(
                model_name="SMG 6200",
                serial_number="SMG-123",
                driver_key="modbus_smg",
                variant_key="anenji_4200_protocol_1",
                profile_name="modbus_smg/models/anenji_4200_protocol_1.json",
                register_schema_name="modbus_smg/models/anenji_4200_protocol_1.json",
            ),
            collector=types.SimpleNamespace(
                collector_pn="Q0000000000001",
                profile_name="EyeBond ASCII PN v1",
                smartess_protocol_name=None,
                smartess_protocol_asset_name=None,
                smartess_collector_version="8.50.12.3",
            ),
        )

        async def _run() -> None:
            await coordinator._async_remember_runtime_identity(snapshot)
            await coordinator._async_remember_runtime_identity(snapshot)
            await asyncio.sleep(0)

        asyncio.run(_run())

        self.assertEqual(reload_requests, ["entry-upgrade-first-runtime-signature"])
        self.assertTrue(coordinator._entity_platform_reload_requested)

    def test_metadata_drift_reload_allows_first_runtime_signature_for_driver_fallback_setup(self) -> None:
        reload_requests: list[str] = []

        class _ConfigEntries:
            async def async_reload(self, entry_id: str) -> None:
                reload_requests.append(entry_id)

        coordinator = object.__new__(self.coordinator_module.EybondLocalCoordinator)
        coordinator.hass = types.SimpleNamespace(
            config_entries=_ConfigEntries(),
            async_create_task=lambda coro: asyncio.create_task(coro),
        )
        coordinator.config_entry = types.SimpleNamespace(entry_id="entry-driver-fallback")
        coordinator._entity_platforms_initialized = True
        coordinator._entity_platform_reload_requested = False
        coordinator._entity_platforms_loaded_with_inverter_identity = False
        coordinator._entity_platforms_loaded_with_driver_fallback = True

        async def _run() -> None:
            coordinator._request_entry_reload_for_metadata_drift(
                setup_signature=("", "", ""),
                runtime_signature=(
                    "anenji_4200_protocol_1",
                    "modbus_smg/models/anenji_4200_protocol_1.json",
                    "modbus_smg/models/anenji_4200_protocol_1.json",
                ),
            )
            await asyncio.sleep(0)

        asyncio.run(_run())

        self.assertEqual(reload_requests, ["entry-driver-fallback"])
        self.assertTrue(coordinator._entity_platform_reload_requested)

    def test_remember_runtime_identity_does_not_reload_on_identical_effective_metadata(self) -> None:
        reload_requests: list[str] = []

        class _ConfigEntries:
            def async_update_entry(self, entry, *, title=None, data=None, options=None) -> None:
                if data is not None:
                    entry.data = dict(data)
                if options is not None:
                    entry.options = dict(options)
                if title is not None:
                    entry.title = title

            async def async_reload(self, entry_id: str) -> None:
                reload_requests.append(entry_id)

        coordinator = object.__new__(self.coordinator_module.EybondLocalCoordinator)
        coordinator.hass = types.SimpleNamespace(
            config_entries=_ConfigEntries(),
            async_create_task=lambda coro: asyncio.create_task(coro),
        )
        coordinator.config_entry = types.SimpleNamespace(
            entry_id="entry-same",
            data={
                "collector_ip": "192.168.1.14",
                "collector_pn": "Q0000000000001",
                "detected_model": "SMG 6200",
                "detected_serial": "SMG-123",
                "detection_confidence": "high",
                "server_ip": "192.168.1.104",
                "driver_hint": "modbus_smg",
            },
            options={
                "effective_metadata_snapshot": {
                    "effective_owner_key": "modbus_smg",
                    "effective_owner_name": "modbus_smg",
                    "variant_key": "anenji_4200_protocol_1",
                    "profile_name": "modbus_smg/models/anenji_4200_protocol_1.json",
                    "register_schema_name": "modbus_smg/models/anenji_4200_protocol_1.json",
                    "confidence": "high",
                    "generation": 2,
                    "generated_at": "2026-06-01T00:00:00+00:00",
                }
            },
            title="Collector PN Q0000000000001",
        )
        coordinator.data = self.RuntimeSnapshot(
            inverter=types.SimpleNamespace(
                model_name="SMG 6200",
                serial_number="SMG-123",
            )
        )
        coordinator._entity_platforms_initialized = False
        coordinator._entity_platform_reload_requested = False
        coordinator._entity_platforms_loaded_with_inverter_identity = False
        coordinator._platform_loaded_effective_metadata_signature = ("", "", "")

        coordinator.mark_entity_platforms_initialized(has_inverter_identity=True)

        snapshot = self.RuntimeSnapshot(
            values={"smartess_profile_key": "hint-only-change"},
            inverter=types.SimpleNamespace(
                model_name="SMG 6200",
                serial_number="SMG-123",
                driver_key="modbus_smg",
                variant_key="anenji_4200_protocol_1",
                profile_name="modbus_smg/models/anenji_4200_protocol_1.json",
                register_schema_name="modbus_smg/models/anenji_4200_protocol_1.json",
            ),
            collector=types.SimpleNamespace(
                collector_pn="Q0000000000001",
                profile_name="EyeBond ASCII PN v1",
                smartess_protocol_name="changed-hint-only",
                smartess_protocol_asset_name="changed-hint-only",
                smartess_collector_version="8.50.12.3",
            ),
        )

        async def _run() -> None:
            await coordinator._async_remember_runtime_identity(snapshot)
            await coordinator._async_remember_runtime_identity(snapshot)
            await asyncio.sleep(0)

        asyncio.run(_run())

        self.assertEqual(reload_requests, [])
        self.assertFalse(coordinator._entity_platform_reload_requested)

    def test_clear_proxy_capture_session_runtime_values_drops_stale_session_keys(self) -> None:
        coordinator = object.__new__(self.coordinator_module.EybondLocalCoordinator)
        coordinator.data = self.RuntimeSnapshot(
            values={
                "proxy_capture_session_status": "running",
                "proxy_capture_session_started_at": "2026-04-30T00:00:00+00:00",
                "proxy_capture_session_expires_at": "2026-04-30T00:10:00+00:00",
                "proxy_capture_session_anonymized": True,
                "proxy_trace_path": "/config/trace.jsonl",
            }
        )
        coordinator._tooling_values = {
            "proxy_capture_session_status": "running",
            "proxy_capture_session_started_at": "2026-04-30T00:00:00+00:00",
            "proxy_capture_session_expires_at": "2026-04-30T00:10:00+00:00",
            "proxy_capture_session_anonymized": True,
            "proxy_trace_path": "/config/trace.jsonl",
        }

        coordinator._clear_proxy_capture_session_runtime_values()

        self.assertNotIn("proxy_capture_session_status", coordinator.data.values)
        self.assertNotIn("proxy_capture_session_started_at", coordinator.data.values)
        self.assertNotIn("proxy_capture_session_expires_at", coordinator.data.values)
        self.assertNotIn("proxy_capture_session_anonymized", coordinator.data.values)
        self.assertEqual(coordinator.data.values["proxy_trace_path"], "/config/trace.jsonl")
        self.assertNotIn("proxy_capture_session_status", coordinator._tooling_values)

    def test_proxy_capture_deadline_scheduler_uses_trace_timestamp_parser(self) -> None:
        coordinator = object.__new__(self.coordinator_module.EybondLocalCoordinator)
        scheduled: list[tuple[float, object]] = []
        handle = types.SimpleNamespace(cancel=lambda: None)
        coordinator._proxy_capture_deadline_refresh_handle = None
        coordinator.hass = types.SimpleNamespace(
            loop=types.SimpleNamespace(
                call_later=lambda delay, callback: (
                    scheduled.append((delay, callback)) or handle
                )
            )
        )
        deadline = datetime.now().astimezone()

        with patch.object(
            self.coordinator_cloud_tools_module,
            "parse_proxy_capture_session_timestamp",
            return_value=deadline,
        ) as parser:
            coordinator._schedule_proxy_capture_deadline_refresh(
                "2026-08-21T12:00:00+00:00"
            )

        parser.assert_called_once_with("2026-08-21T12:00:00+00:00")
        self.assertEqual(len(scheduled), 1)
        self.assertIs(coordinator._proxy_capture_deadline_refresh_handle, handle)

    def test_active_proxy_capture_state_ignores_stale_running_session_without_route(self) -> None:
        coordinator = object.__new__(self.coordinator_module.EybondLocalCoordinator)
        coordinator.config_entry = types.SimpleNamespace(entry_id="entry-id", data={})
        coordinator._runtime = types.SimpleNamespace(proxy_capture_route_running=lambda: False)
        coordinator.data = self.RuntimeSnapshot(
            values={
                "proxy_capture_session_status": "running",
                "proxy_capture_session_started_at": "2026-04-30T00:00:00+00:00",
                "proxy_capture_session_expires_at": "2026-04-30T00:10:00+00:00",
                "proxy_capture_session_anonymized": True,
                "proxy_capture_redirect_required": True,
                "proxy_capture_target_endpoint": "127.0.0.1:18899",
                "proxy_capture_masked_endpoint": "cloud.example:1883",
                "proxy_trace_path": "/config/trace.jsonl",
            }
        )
        coordinator._tooling_values = {}

        self.assertIsNone(coordinator._active_proxy_capture_state())

    def test_active_proxy_capture_state_prefers_cached_session_state(self) -> None:
        coordinator = object.__new__(self.coordinator_module.EybondLocalCoordinator)
        cached_state = types.SimpleNamespace(
            status="running",
            trace_path="/config/trace.jsonl",
            original_endpoint="cloud.example,18899,TCP",
            proxy_endpoint="192.168.1.50,18899,TCP",
        )
        coordinator._cached_proxy_capture_session_state = cached_state
        coordinator.data = self.RuntimeSnapshot(
            values={
                "proxy_capture_session_status": "running",
            }
        )
        coordinator._tooling_values = {}

        self.assertIs(coordinator._active_proxy_capture_state(), cached_state)

    def test_start_proxy_capture_fails_early_when_shadow_learning_owns_route(self) -> None:
        async def _run() -> None:
            coordinator = object.__new__(self.coordinator_module.EybondLocalCoordinator)
            active_shadow_state = types.SimpleNamespace(status="ready")
            save_calls: list[bool] = []
            stop_shadow_calls: list[dict[str, object]] = []

            async def _async_active_shadow_learning_state(*, require_process: bool = True):
                self.assertFalse(require_process)
                return active_shadow_state

            async def _async_save_proxy_capture_session_state(_state) -> None:
                save_calls.append(True)

            async def _async_stop_shadow_learning(**kwargs):
                stop_shadow_calls.append(dict(kwargs))

            coordinator._async_active_shadow_learning_state = _async_active_shadow_learning_state
            coordinator._async_save_proxy_capture_session_state = _async_save_proxy_capture_session_state
            coordinator.async_stop_shadow_learning = _async_stop_shadow_learning
            coordinator._shadow_learning_process_running = lambda: False
            coordinator._proxy_capture_process_running = lambda: False
            coordinator.collector_endpoint_sync_lock_code = lambda: None

            with patch.object(
                self.coordinator_module.EybondLocalCoordinator,
                "proxy_capture_overview",
                new_callable=PropertyMock,
                return_value=types.SimpleNamespace(
                    can_start=True,
                    blocking_reason="",
                    redirect_required=False,
                ),
            ):
                with self.assertRaisesRegex(RuntimeError, "shadow_learning_route_running"):
                    await coordinator.async_start_proxy_capture()

            self.assertEqual(save_calls, [])
            self.assertEqual(stop_shadow_calls, [])

        import asyncio

        asyncio.run(_run())

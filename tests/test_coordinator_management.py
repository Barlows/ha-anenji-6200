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
    def test_start_shadow_learning_fails_early_when_proxy_capture_owns_route(self) -> None:
        async def _run() -> None:
            coordinator = object.__new__(self.coordinator_module.EybondLocalCoordinator)
            active_proxy_state = types.SimpleNamespace(status="running")
            save_calls: list[bool] = []
            start_shadow_calls: list[dict[str, object]] = []

            async def _async_active_proxy_capture_state(*, require_process: bool = True):
                self.assertFalse(require_process)
                return active_proxy_state

            async def _async_save_shadow_learning_session_state(_state) -> None:
                save_calls.append(True)

            async def _async_start_shadow_learning_route(**kwargs) -> None:
                start_shadow_calls.append(dict(kwargs))

            coordinator._async_active_proxy_capture_state = _async_active_proxy_capture_state
            coordinator._async_save_shadow_learning_session_state = (
                _async_save_shadow_learning_session_state
            )
            coordinator._runtime = types.SimpleNamespace(
                proxy_capture_route_running=lambda: False,
                async_start_shadow_learning_route=_async_start_shadow_learning_route,
            )
            coordinator._shadow_learning_process_running = lambda: False

            with patch.object(
                self.coordinator_module.EybondLocalCoordinator,
                "support_acquisition_readiness",
                new_callable=PropertyMock,
                return_value=self._support_readiness(),
            ), patch.object(
                self.coordinator_module.EybondLocalCoordinator,
                "collector_actions_enabled",
                new_callable=PropertyMock,
                return_value=True,
            ):
                with self.assertRaisesRegex(
                    RuntimeError,
                    "proxy_capture_route_running",
                ):
                    await coordinator.async_start_shadow_learning(
                        output_path=Path("/tmp/shadow.jsonl"),
                        raw_capture={},
                    )

            self.assertEqual(save_calls, [])
            self.assertEqual(start_shadow_calls, [])

        import asyncio

        asyncio.run(_run())

    def test_support_readiness_does_not_require_an_identified_inverter(self) -> None:
        coordinator = object.__new__(self.coordinator_module.EybondLocalCoordinator)
        coordinator.config_entry = types.SimpleNamespace(
            entry_id="entry-unbound-support",
            data={
                "collector_pn": "E50000200000000001",
                "connection_strategy": "callback_on_demand",
                "endpoint_control_policy": "external",
                "detected_model": "",
                "detected_serial": "",
            },
            options={},
        )
        coordinator.data = self.RuntimeSnapshot(values={"driver_key": "auto"})

        with patch.object(
            self.coordinator_module.EybondLocalCoordinator,
            "smartess_collector_pn",
            new_callable=PropertyMock,
            return_value="E50000200000000001",
        ), patch.object(
            self.coordinator_module.EybondLocalCoordinator,
            "cloud_evidence_provider",
            new_callable=PropertyMock,
            return_value="smartess",
        ), patch.object(
            self.coordinator_module.EybondLocalCoordinator,
            "collector_capabilities",
            new_callable=PropertyMock,
            return_value=types.SimpleNamespace(virtual_bridge=False),
        ):
            readiness = coordinator.support_acquisition_readiness

        self.assertTrue(readiness.collector_identified)
        self.assertFalse(readiness.inverter_identified)
        self.assertTrue(readiness.cloud_metadata_read.can_start)
        self.assertTrue(readiness.proxy_capture.can_start)
        self.assertTrue(readiness.active_control_learning.can_start)

    def test_start_shadow_learning_requires_cloud_and_ha_profile(self) -> None:
        async def _run() -> None:
            coordinator = object.__new__(
                self.coordinator_module.EybondLocalCoordinator
            )
            downstream_calls: list[bool] = []

            async def _async_active_proxy_capture_state(
                *,
                require_process: bool = True,
            ):
                downstream_calls.append(require_process)
                return None

            coordinator._async_active_proxy_capture_state = (
                _async_active_proxy_capture_state
            )

            with patch.object(
                self.coordinator_module.EybondLocalCoordinator,
                "support_acquisition_readiness",
                new_callable=PropertyMock,
                return_value=self._support_readiness(active_can_start=False),
            ):
                with self.assertRaisesRegex(
                    RuntimeError,
                    "shadow_learning_requires_cloud_and_ha_profile",
                ):
                    await coordinator.async_start_shadow_learning(
                        output_path=Path("/tmp/shadow.jsonl"),
                        raw_capture={},
                    )

            self.assertEqual(downstream_calls, [])

        import asyncio

        asyncio.run(_run())

    def test_start_shadow_learning_fails_early_when_memory_is_low(self) -> None:
        async def _run() -> None:
            coordinator = object.__new__(self.coordinator_module.EybondLocalCoordinator)
            start_shadow_calls: list[dict[str, object]] = []

            async def _async_active_proxy_capture_state(*, require_process: bool = True):
                self.assertFalse(require_process)
                return None

            async def _async_start_shadow_learning_route(**kwargs) -> None:
                start_shadow_calls.append(dict(kwargs))

            coordinator._async_active_proxy_capture_state = _async_active_proxy_capture_state
            coordinator._runtime = types.SimpleNamespace(
                proxy_capture_route_running=lambda: False,
                async_start_shadow_learning_route=_async_start_shadow_learning_route,
            )
            coordinator._shadow_learning_process_running = lambda: False

            with patch.object(
                self.coordinator_module.EybondLocalCoordinator,
                "support_acquisition_readiness",
                new_callable=PropertyMock,
                return_value=self._support_readiness(),
            ), patch.object(
                self.coordinator_module.EybondLocalCoordinator,
                "collector_actions_enabled",
                new_callable=PropertyMock,
                return_value=True,
            ), patch.object(
                self.coordinator_cloud_tools_module,
                "read_available_memory_mib",
                return_value=128,
            ):
                with self.assertRaisesRegex(
                    RuntimeError,
                    "shadow_learning_preflight_blocked:insufficient_memory:128MiB",
                ):
                    await coordinator.async_start_shadow_learning(
                        output_path=Path("/tmp/shadow.jsonl"),
                        raw_capture={},
                    )

            self.assertEqual(start_shadow_calls, [])

        import asyncio

        asyncio.run(_run())

    def test_reconcile_expired_proxy_session_prefers_proxy_restore_trigger(self) -> None:
        async def _run() -> None:
            coordinator = object.__new__(self.coordinator_module.EybondLocalCoordinator)
            calls: list[dict[str, object]] = []
            refreshed_snapshots: list[float] = []
            snapshot = self.RuntimeSnapshot(values={"collector_server_endpoint": "192.168.1.50,18899,TCP"})
            active_state = types.SimpleNamespace(status="running")
            coordinator.config_entry = types.SimpleNamespace(
                entry_id="entry-id",
                options={"poll_interval": 30},
            )

            async def _async_active_proxy_capture_state(*, require_process: bool = True):
                self.assertFalse(require_process)
                return active_state

            async def _async_stop_proxy_capture(**kwargs):
                calls.append(dict(kwargs))

            async def _async_refresh(*, poll_interval: float):
                refreshed_snapshots.append(poll_interval)
                return snapshot

            coordinator._async_active_proxy_capture_state = _async_active_proxy_capture_state
            coordinator.async_stop_proxy_capture = _async_stop_proxy_capture
            coordinator._runtime = types.SimpleNamespace(async_refresh=_async_refresh)

            with patch.object(
                self.coordinator_cloud_tools_module,
                "proxy_capture_session_is_active",
                return_value=True,
            ), patch.object(
                self.coordinator_cloud_tools_module,
                "proxy_capture_session_is_expired",
                return_value=True,
            ), patch.object(
                coordinator,
                "_proxy_capture_process_running",
                return_value=True,
            ):
                result = await coordinator._async_reconcile_proxy_capture_session(snapshot)

            self.assertIs(result, snapshot)
            self.assertEqual(
                calls,
                [
                    {
                        "reason": "expired_lease",
                        "prefer_proxy_restore_trigger": True,
                        "request_refresh": False,
                    }
                ],
            )
            self.assertEqual(refreshed_snapshots, [30.0])

        import asyncio

        asyncio.run(_run())

    def test_reconcile_expired_shadow_session_stops_with_expired_lease(self) -> None:
        async def _run() -> None:
            coordinator = object.__new__(self.coordinator_module.EybondLocalCoordinator)
            calls: list[dict[str, object]] = []
            refreshed_snapshots: list[float] = []
            snapshot = self.RuntimeSnapshot(values={})
            active_state = types.SimpleNamespace(status="ready")
            coordinator.config_entry = types.SimpleNamespace(
                entry_id="entry-id",
                options={"poll_interval": 45},
            )

            async def _async_active_shadow_learning_state(*, require_process: bool = True):
                self.assertFalse(require_process)
                return active_state

            async def _async_stop_shadow_learning(**kwargs):
                calls.append(dict(kwargs))

            async def _async_refresh(*, poll_interval: float):
                refreshed_snapshots.append(poll_interval)
                return snapshot

            coordinator._async_active_shadow_learning_state = _async_active_shadow_learning_state
            coordinator.async_stop_shadow_learning = _async_stop_shadow_learning
            coordinator._runtime = types.SimpleNamespace(async_refresh=_async_refresh)

            with patch.object(
                self.coordinator_cloud_tools_module,
                "shadow_learning_session_is_active",
                return_value=True,
            ), patch.object(
                self.coordinator_cloud_tools_module,
                "shadow_learning_session_is_expired",
                return_value=True,
            ):
                result = await coordinator._async_reconcile_shadow_learning_session(snapshot)

            self.assertIs(result, snapshot)
            self.assertEqual(
                calls,
                [
                    {
                        "reason": "expired_lease",
                        "request_refresh": False,
                        "raise_when_not_running": False,
                    }
                ],
            )
            self.assertEqual(refreshed_snapshots, [45.0])

        import asyncio

        asyncio.run(_run())

    def test_reconcile_does_not_terminalize_proxy_transitional_states(self) -> None:
        async def _run() -> None:
            snapshot = self.RuntimeSnapshot(values={})
            for status in ("starting", "stopping", "restoring"):
                coordinator = object.__new__(
                    self.coordinator_module.EybondLocalCoordinator
                )
                state = types.SimpleNamespace(status=status)
                stop_calls: list[dict[str, object]] = []
                coordinator._async_active_proxy_capture_state = (
                    lambda *, require_process=False, state=state: asyncio.sleep(
                        0,
                        result=state,
                    )
                )
                coordinator._proxy_capture_process_running = lambda: False
                coordinator.async_stop_proxy_capture = (
                    lambda **kwargs: asyncio.sleep(
                        0,
                        result=stop_calls.append(dict(kwargs)),
                    )
                )
                with patch.object(
                    self.coordinator_cloud_tools_module,
                    "proxy_capture_session_is_active",
                    return_value=True,
                ), patch.object(
                    self.coordinator_cloud_tools_module,
                    "proxy_capture_session_is_expired",
                    return_value=False,
                ):
                    result = (
                        await coordinator._async_reconcile_proxy_capture_session(
                            snapshot
                        )
                    )
                self.assertIs(result, snapshot)
                self.assertEqual(stop_calls, [], status)

        asyncio.run(_run())

    def test_reconcile_does_not_terminalize_shadow_transitional_states(self) -> None:
        async def _run() -> None:
            snapshot = self.RuntimeSnapshot(values={})
            for status in ("preflight", "starting", "restoring"):
                coordinator = object.__new__(
                    self.coordinator_module.EybondLocalCoordinator
                )
                state = types.SimpleNamespace(status=status)
                stop_calls: list[dict[str, object]] = []
                coordinator._async_active_shadow_learning_state = (
                    lambda *, require_process=False, state=state: asyncio.sleep(
                        0,
                        result=state,
                    )
                )
                coordinator._shadow_learning_process_running = lambda: False
                coordinator.async_stop_shadow_learning = (
                    lambda **kwargs: asyncio.sleep(
                        0,
                        result=stop_calls.append(dict(kwargs)),
                    )
                )
                with patch.object(
                    self.coordinator_cloud_tools_module,
                    "shadow_learning_session_is_active",
                    return_value=True,
                ), patch.object(
                    self.coordinator_cloud_tools_module,
                    "shadow_learning_session_is_expired",
                    return_value=False,
                ):
                    result = (
                        await coordinator._async_reconcile_shadow_learning_session(
                            snapshot
                        )
                    )
                self.assertIs(result, snapshot)
                self.assertEqual(stop_calls, [], status)

        asyncio.run(_run())

    def test_recover_shadow_learning_state_retries_restore_failed_session(self) -> None:
        async def _run() -> None:
            coordinator = object.__new__(self.coordinator_module.EybondLocalCoordinator)
            calls: list[dict[str, object]] = []
            state = types.SimpleNamespace(status="restore_failed")
            coordinator.config_entry = types.SimpleNamespace(entry_id="entry-id")

            async def _async_active_shadow_learning_state(*, require_process: bool = True):
                self.assertFalse(require_process)
                return state

            async def _async_stop_shadow_learning(**kwargs):
                calls.append(dict(kwargs))

            coordinator._async_active_shadow_learning_state = _async_active_shadow_learning_state
            coordinator.async_stop_shadow_learning = _async_stop_shadow_learning

            with patch.object(
                self.coordinator_cloud_tools_module,
                "shadow_learning_session_is_active",
                return_value=False,
            ), patch.object(
                self.coordinator_cloud_tools_module,
                "shadow_learning_session_is_expired",
                return_value=False,
            ):
                await coordinator._async_recover_shadow_learning_state()

            self.assertEqual(
                calls,
                [
                    {
                        "reason": "recovered_after_restart",
                        "request_refresh": False,
                        "raise_when_not_running": False,
                    }
                ],
            )

        import asyncio

        asyncio.run(_run())

    def test_stop_shadow_learning_keeps_recoverable_state_when_restore_fails(self) -> None:
        async def _run() -> None:
            coordinator = object.__new__(self.coordinator_module.EybondLocalCoordinator)
            saved_states: list[object] = []
            clear_calls: list[bool] = []
            notify_calls: list[bool] = []
            published: list[dict[str, object]] = []
            state = types.SimpleNamespace(
                entry_id="entry-id",
                collector_pn="E5000020000000",
                trace_path="/tmp/shadow.jsonl",
                original_endpoint="eu.smartess.io,18899,TCP",
                proxy_endpoint="192.168.1.50,18899,TCP",
                upstream_endpoint="eu.smartess.io,18899,TCP",
                restore_required=True,
                started_at="2026-06-05T12:00:00+00:00",
                expires_at="2026-06-05T12:20:00+00:00",
                restore_attempt_count=1,
                last_restore_attempt_at="",
                last_restore_error="",
                route_owner_id="shadow_learning:entry-id:1",
            )
            coordinator.config_entry = types.SimpleNamespace(entry_id="entry-id")
            coordinator._runtime = types.SimpleNamespace(
                async_stop_shadow_learning_route=lambda **kwargs: asyncio.sleep(0)
            )

            async def _async_active_shadow_learning_state(*, require_process: bool = True):
                self.assertFalse(require_process)
                return state

            async def _async_restore_proxy_capture_endpoint(_endpoint: str):
                raise RuntimeError("restore_failed")

            async def _async_save_shadow_learning_session_state(new_state):
                saved_states.append(new_state)

            async def _async_clear_shadow_learning_session_state():
                clear_calls.append(True)

            async def _async_request_refresh():
                return None

            coordinator._async_active_shadow_learning_state = _async_active_shadow_learning_state
            coordinator._async_restore_proxy_capture_endpoint = _async_restore_proxy_capture_endpoint
            coordinator._async_save_shadow_learning_session_state = _async_save_shadow_learning_session_state
            coordinator._async_clear_shadow_learning_session_state = _async_clear_shadow_learning_session_state
            coordinator.async_request_refresh = _async_request_refresh
            coordinator._notify_proxy_capture_restore_unconfirmed = lambda: notify_calls.append(True)
            coordinator._publish_tooling_values = lambda **kwargs: published.append(dict(kwargs))

            result = await coordinator.async_stop_shadow_learning()

            self.assertEqual(result["status"], "restore_unconfirmed")
            self.assertEqual(result["restore_confirmed"], False)
            self.assertFalse(clear_calls)
            self.assertEqual(saved_states[-1].status, "restore_failed")
            self.assertEqual(saved_states[-1].restore_attempt_count, 2)
            self.assertTrue(notify_calls)
            self.assertEqual(published[-1]["shadow_learning_session_status"], "restore_failed")

        import asyncio

        asyncio.run(_run())

    def test_stop_shadow_learning_clears_state_after_confirmed_restore(self) -> None:
        async def _run() -> None:
            coordinator = object.__new__(self.coordinator_module.EybondLocalCoordinator)
            saved_states: list[object] = []
            clear_calls: list[bool] = []
            state = types.SimpleNamespace(
                entry_id="entry-id",
                collector_pn="E5000020000000",
                trace_path="/tmp/shadow.jsonl",
                original_endpoint="eu.smartess.io,18899,TCP",
                proxy_endpoint="192.168.1.50,18899,TCP",
                upstream_endpoint="eu.smartess.io,18899,TCP",
                restore_required=True,
                started_at="2026-06-05T12:00:00+00:00",
                expires_at="2026-06-05T12:20:00+00:00",
                restore_attempt_count=0,
                last_restore_attempt_at="",
                last_restore_error="",
                route_owner_id="shadow_learning:entry-id:1",
            )
            coordinator.config_entry = types.SimpleNamespace(entry_id="entry-id")
            coordinator._runtime = types.SimpleNamespace(
                async_stop_shadow_learning_route=lambda **kwargs: asyncio.sleep(0)
            )

            async def _async_active_shadow_learning_state(*, require_process: bool = True):
                self.assertFalse(require_process)
                return state

            async def _async_restore_proxy_capture_endpoint(endpoint: str):
                return endpoint

            async def _async_verify_restored_collector_endpoint(endpoint: str):
                return {
                    "restore_confirmed": True,
                    "observed_endpoint": endpoint,
                    "restore_error": "",
                }

            async def _async_save_shadow_learning_session_state(new_state):
                saved_states.append(new_state)

            async def _async_clear_shadow_learning_session_state():
                clear_calls.append(True)

            async def _async_request_refresh():
                return None

            coordinator._async_active_shadow_learning_state = _async_active_shadow_learning_state
            coordinator._async_restore_proxy_capture_endpoint = _async_restore_proxy_capture_endpoint
            coordinator._async_verify_restored_collector_endpoint = (
                _async_verify_restored_collector_endpoint
            )
            coordinator._async_save_shadow_learning_session_state = _async_save_shadow_learning_session_state
            coordinator._async_clear_shadow_learning_session_state = _async_clear_shadow_learning_session_state
            coordinator.async_request_refresh = _async_request_refresh
            coordinator._notify_proxy_capture_restore_unconfirmed = lambda: None
            coordinator._publish_tooling_values = lambda **kwargs: None

            result = await coordinator.async_stop_shadow_learning()

            self.assertEqual(result["status"], "stopped")
            self.assertEqual(result["restore_confirmed"], True)
            self.assertEqual(result["restored_endpoint"], "eu.smartess.io,18899,TCP")
            self.assertTrue(clear_calls)
            self.assertEqual(saved_states[0].status, "restoring")

        import asyncio

        asyncio.run(_run())

    # ---- CP2C blocker 9: production-level endpoint-operation guarantees ----

    def _acquire_foreign_owner(self, entry_id: str):
        """Acquire the ONE authority for ``entry_id`` under a foreign operation."""
        from custom_components.eybond_local.connection.collector_endpoint_operation import (
            COLLECTOR_ENDPOINT_OPERATION_AUTHORITY as AUTH,
            OPERATION_STRATEGY_TRANSITION,
        )

        outcome = AUTH.acquire(entry_id, OPERATION_STRATEGY_TRANSITION, owner_ref="foreign:1")
        self.assertTrue(outcome.acquired)
        return AUTH, outcome.token

    def test_public_system_actions_refuse_with_zero_wire_when_busy(self) -> None:
        # apply / reboot / rediscovery / rollback are route-affecting full-control
        # actions: when a FOREIGN operation owns the entry each must typed-refuse
        # BEFORE touching the wire (no apply, reboot, UDP, or endpoint write).
        async def _run() -> None:
            entry_id = "entry-busy-public"
            AUTH, token = self._acquire_foreign_owner(entry_id)
            self.addCleanup(lambda: AUTH.release(entry_id, token))
            wire_calls: list[str] = []

            def _fail(name):
                async def _f(*args, **kwargs):
                    wire_calls.append(name)
                    raise AssertionError(f"{name} must not run while busy")

                return _f

            coordinator = object.__new__(self.coordinator_module.EybondLocalCoordinator)
            coordinator.config_entry = types.SimpleNamespace(entry_id=entry_id)
            coordinator._raise_if_high_level_collector_actions_disabled = lambda: None
            coordinator.collector_configuration_lock_code = lambda: "collector_configuration_ready"
            coordinator._runtime = types.SimpleNamespace(
                async_apply_collector_changes=_fail("apply"),
                async_reboot_collector=_fail("reboot"),
                async_trigger_reverse_discovery=_fail("rediscovery"),
                async_set_collector_server_endpoint=_fail("set_endpoint"),
            )

            from custom_components.eybond_local.connection.collector_endpoint_operation import (
                COLLECTOR_ENDPOINT_OPERATION_BUSY,
            )

            for coro in (
                coordinator.async_apply_collector_changes(confirm_restart=True),
                coordinator.async_reboot_collector(confirm_restart=True),
                coordinator.async_trigger_collector_rediscovery(),
                coordinator.async_rollback_collector_server_endpoint(confirm_redirect=True),
            ):
                with self.assertRaises(RuntimeError) as ctx:
                    await coro
                self.assertEqual(str(ctx.exception), COLLECTOR_ENDPOINT_OPERATION_BUSY)

            self.assertEqual(wire_calls, [], "no wire action may run while the entry is busy")

        import asyncio

        asyncio.run(_run())

    def test_automatic_reconcile_silently_skips_write_when_entry_is_busy(self) -> None:
        # The best-effort operation-mode reconcile must NOT break the refresh when
        # another endpoint operation owns the entry: it records an honest
        # operation_busy status and performs ZERO endpoint writes (no cooldown
        # stamp either, so it retries once the owner frees the entry).
        async def _run() -> None:
            entry_id = "entry-busy-reconcile"
            AUTH, token = self._acquire_foreign_owner(entry_id)
            self.addCleanup(lambda: AUTH.release(entry_id, token))
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
                entry_id=entry_id,
                data={},
                options={
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

            self.assertEqual(endpoint_writes, [], "busy reconcile must not write the endpoint")
            self.assertEqual(
                snapshot.values.get("collector_operation_endpoint_sync_status"),
                "operation_busy",
            )

        import asyncio

        asyncio.run(_run())

    def test_stop_proxy_capture_refuses_with_zero_mutation_under_foreign_owner(self) -> None:
        # A stop while a FOREIGN operation owns the entry (adopt cannot prove
        # ownership) refuses BEFORE the first state/route/restore mutation.
        async def _run() -> None:
            entry_id = "entry-foreign-proxy-stop"
            AUTH, token = self._acquire_foreign_owner(entry_id)
            self.addCleanup(lambda: AUTH.release(entry_id, token))
            saved_states: list[object] = []

            state = types.SimpleNamespace(
                entry_id=entry_id,
                route_owner_id=f"proxy_capture:{entry_id}:ts",
                collector_pn="E5000020000000",
                trace_path="/tmp/proxy.jsonl",
                original_endpoint="eu.smartess.io,18899,TCP",
                proxy_endpoint="192.168.1.50,18899,TCP",
                restore_required=True,
                anonymized=False,
                started_at="2026-06-05T12:00:00+00:00",
                expires_at="2026-06-05T12:20:00+00:00",
                status="running",
            )
            coordinator = object.__new__(self.coordinator_module.EybondLocalCoordinator)
            coordinator.config_entry = types.SimpleNamespace(entry_id=entry_id)

            async def _async_active_proxy_capture_state(*, require_process: bool = True):
                return state

            async def _async_save_proxy_capture_session_state(new_state):
                saved_states.append(new_state)

            def _guarded_restore(*args, **kwargs):
                raise AssertionError("restore must not run under a foreign owner")

            coordinator._async_active_proxy_capture_state = _async_active_proxy_capture_state
            coordinator._async_save_proxy_capture_session_state = (
                _async_save_proxy_capture_session_state
            )
            coordinator._async_guarded_proxy_capture_restore = _guarded_restore

            from custom_components.eybond_local.connection.collector_endpoint_operation import (
                COLLECTOR_ENDPOINT_OPERATION_BUSY,
            )

            with self.assertRaises(RuntimeError) as ctx:
                await coordinator.async_stop_proxy_capture()
            self.assertEqual(str(ctx.exception), COLLECTOR_ENDPOINT_OPERATION_BUSY)
            self.assertEqual(saved_states, [], "no state may be written under a foreign owner")
            # The foreign owner still holds the entry, untouched.
            self.assertEqual(AUTH.active_operation(entry_id), "strategy_transition")

        import asyncio

        asyncio.run(_run())

    def test_stop_shadow_learning_refuses_with_zero_mutation_under_foreign_owner(self) -> None:
        async def _run() -> None:
            entry_id = "entry-foreign-shadow-stop"
            AUTH, token = self._acquire_foreign_owner(entry_id)
            self.addCleanup(lambda: AUTH.release(entry_id, token))
            saved_states: list[object] = []
            route_stops: list[object] = []

            state = types.SimpleNamespace(
                entry_id=entry_id,
                collector_pn="E5000020000000",
                trace_path="/tmp/shadow.jsonl",
                original_endpoint="eu.smartess.io,18899,TCP",
                proxy_endpoint="192.168.1.50,18899,TCP",
                upstream_endpoint="eu.smartess.io,18899,TCP",
                restore_required=True,
                started_at="2026-06-05T12:00:00+00:00",
                expires_at="2026-06-05T12:20:00+00:00",
                restore_attempt_count=0,
                last_restore_attempt_at="",
                last_restore_error="",
                route_owner_id=f"shadow_learning:{entry_id}:1",
            )
            coordinator = object.__new__(self.coordinator_module.EybondLocalCoordinator)
            coordinator.config_entry = types.SimpleNamespace(entry_id=entry_id)

            async def _route_stop(**kwargs):
                route_stops.append(kwargs)

            coordinator._runtime = types.SimpleNamespace(
                async_stop_shadow_learning_route=_route_stop
            )

            async def _async_active_shadow_learning_state(*, require_process: bool = True):
                return state

            async def _async_save_shadow_learning_session_state(new_state):
                saved_states.append(new_state)

            def _restore_must_not_run(*args, **kwargs):
                raise AssertionError("restore must not run under a foreign owner")

            coordinator._async_active_shadow_learning_state = _async_active_shadow_learning_state
            coordinator._async_save_shadow_learning_session_state = (
                _async_save_shadow_learning_session_state
            )
            coordinator._async_restore_proxy_capture_endpoint = _restore_must_not_run

            from custom_components.eybond_local.connection.collector_endpoint_operation import (
                COLLECTOR_ENDPOINT_OPERATION_BUSY,
            )

            with self.assertRaises(RuntimeError) as ctx:
                await coordinator.async_stop_shadow_learning()
            self.assertEqual(str(ctx.exception), COLLECTOR_ENDPOINT_OPERATION_BUSY)
            self.assertEqual(saved_states, [])
            self.assertEqual(route_stops, [])
            self.assertEqual(AUTH.active_operation(entry_id), "strategy_transition")

        import asyncio

        asyncio.run(_run())

    def test_startup_recovery_failure_keeps_proxy_state_and_token(self) -> None:
        # B4: when a recovery-stop raises, the recovery must NOT force-clear the
        # session -- the recoverable state stays and the authority stays owned, so
        # a later recovery/stop can finish the restore.
        async def _run() -> None:
            entry_id = "entry-recovery-fail"
            from custom_components.eybond_local.connection.collector_endpoint_operation import (
                COLLECTOR_ENDPOINT_OPERATION_AUTHORITY as AUTH,
                OPERATION_PROXY_CAPTURE,
            )

            # The interrupted mode still owns the entry (adopted at recovery start).
            owner = AUTH.acquire(
                entry_id, OPERATION_PROXY_CAPTURE, owner_ref=f"proxy_capture:{entry_id}:ts"
            )
            self.assertTrue(owner.acquired)
            self.addCleanup(lambda: AUTH.release(entry_id, owner.token))
            clear_calls: list[bool] = []
            notify_calls: list[bool] = []

            state = types.SimpleNamespace(
                entry_id=entry_id,
                route_owner_id=f"proxy_capture:{entry_id}:ts",
                status="running",
            )
            coordinator = object.__new__(self.coordinator_module.EybondLocalCoordinator)
            coordinator.config_entry = types.SimpleNamespace(entry_id=entry_id)

            async def _async_active_proxy_capture_state(*, require_process: bool = True):
                return state

            async def _async_stop_proxy_capture(**kwargs):
                raise RuntimeError("restore_failed")

            async def _async_clear_proxy_capture_session_state():
                clear_calls.append(True)

            coordinator._async_active_proxy_capture_state = _async_active_proxy_capture_state
            coordinator.async_stop_proxy_capture = _async_stop_proxy_capture
            coordinator._async_clear_proxy_capture_session_state = (
                _async_clear_proxy_capture_session_state
            )
            coordinator._notify_proxy_capture_restore_unconfirmed = lambda: notify_calls.append(True)

            await coordinator._async_recover_proxy_capture_state()

            self.assertFalse(clear_calls, "recovery failure must NOT clear the session")
            self.assertTrue(notify_calls)
            # The authority stays owned by the interrupted route owner.
            self.assertEqual(AUTH.active_operation(entry_id), OPERATION_PROXY_CAPTURE)

        import asyncio

        asyncio.run(_run())

    # ---- CP2C final: REAL-method start/stop cancellation atomicity ----
    #
    # These drive the production async_start_* / async_stop_* on a bare
    # coordinator with controllable async seams (NOT a hand-rolled model of the
    # algorithm), so they prove the shielded finalization the methods actually run.

    @contextlib.contextmanager
    def _shadow_start_env(self, rec, **seams):
        """Bare-coordinator harness that drives the REAL async_start_shadow_learning.

        ``rec`` accumulates observable effects; ``seams`` overrides any async seam
        (save / route / redirect / wait / restore / stop_route / clear) so a test
        can inject a cancel or a rendezvous at an exact point.
        """

        coordinator = object.__new__(self.coordinator_module.EybondLocalCoordinator)

        async def d_route(**kwargs):
            rec["route"].append(kwargs.get("owner_id"))

        async def d_redirect(endpoint, *, apply_changes=True):
            rec["redirect"].append((endpoint, apply_changes))
            return {"readback_endpoint": endpoint}

        async def d_stop_route(**kwargs):
            rec["stop_route"].append(kwargs.get("owner_id"))

        async def d_disconnect(*, reason):
            rec["disconnect"].append(reason)

        async def d_preflight(**kwargs):
            return None

        async def d_save(state):
            rec["saved"].append(state)
            rec["present"] = True

        async def d_active_proxy(*, require_process=True):
            return None

        async def d_wait(**kwargs):
            return None

        async def d_restore(_endpoint):
            return True, ""

        async def d_clear():
            rec["clear"].append(True)
            rec["present"] = False

        async def d_refresh():
            rec["refresh"].append(True)

        async def d_endpoint_context():
            return types.SimpleNamespace(
                current_endpoint="eu.smartess.io,18899,TCP",
                upstream_endpoint="eu.smartess.io,18899,TCP",
                target_endpoint="192.168.1.50,18899,TCP",
            )

        pick = lambda key, default: seams.get(key, default)
        coordinator.config_entry = types.SimpleNamespace(
            entry_id="entry-cancel",
            data={"collector_kind": "factory_eybond"},
            options={"proxy_capture_duration_minutes": 10},
        )
        coordinator.data = self.RuntimeSnapshot(
            connected=False,
            values={"collector_server_endpoint": "eu.smartess.io,18899,TCP"},
        )
        coordinator._runtime = types.SimpleNamespace(
            proxy_capture_route_running=lambda: False,
            async_start_shadow_learning_route=pick("route", d_route),
            async_set_collector_server_endpoint=pick("redirect", d_redirect),
            async_stop_shadow_learning_route=pick("stop_route", d_stop_route),
            async_disconnect_collector_connections=pick("disconnect", d_disconnect),
        )
        coordinator._shadow_learning_process_running = lambda: False
        coordinator._async_preflight_proxy_capture_network = pick("preflight", d_preflight)
        coordinator._async_active_proxy_capture_state = d_active_proxy
        coordinator._async_save_shadow_learning_session_state = pick("save", d_save)
        coordinator._async_wait_for_shadow_learning_ready = pick("wait", d_wait)
        coordinator._async_best_effort_restore_after_start_failure = pick("restore", d_restore)
        coordinator._async_clear_shadow_learning_session_state = pick("clear", d_clear)
        coordinator._async_prepare_cloud_tool_endpoint_context = pick(
            "endpoint_context", d_endpoint_context
        )
        coordinator.async_request_refresh = d_refresh
        coordinator._publish_tooling_values = lambda **kwargs: rec["published"].append(dict(kwargs))
        coordinator._proxy_capture_collector_ip = lambda: "192.168.1.55"

        prop = lambda name, value: patch.object(
            self.coordinator_module.EybondLocalCoordinator,
            name,
            new_callable=PropertyMock,
            return_value=value,
        )
        patchers = [
            prop("support_acquisition_readiness", self._support_readiness()),
            prop("smartess_collector_pn", "E5000020000000"),
            prop("collector_cloud_tools_allowed", True),
            prop("collector_actions_enabled", True),
            prop("collector_callback_target_endpoint", "192.168.1.50,18899,TCP"),
            prop("proxy_capture_target_endpoint", "192.168.1.50,18899,TCP"),
            prop("proxy_capture_upstream_endpoint", "eu.smartess.io,18899,TCP"),
            prop("collector_cloud_profile_key", "smartess-default"),
            prop("collector_cloud_profile_label", "SmartESS Default"),
            prop("collector_cloud_profile_source", "runtime"),
            prop("collector_cloud_profile_confidence", "high"),
            prop("effective_metadata_snapshot", {}),
            prop(
                "shadow_learning_effective_metadata",
                {"register_schema_name": "modbus_smg/base.json"},
            ),
            prop("collector_cloud_family", "smartess_at"),
            prop("_effective_callback_server_host", "192.168.1.50"),
            patch.object(
                self.coordinator_cloud_tools_module,
                "build_shadow_learning_seed",
                return_value=(types.SimpleNamespace(write_response_mode="exception"), []),
            ),
            patch.object(
                self.coordinator_cloud_tools_module,
                "build_shadow_learning_preflight",
                return_value=types.SimpleNamespace(can_start=True, blockers=[]),
            ),
        ]
        with contextlib.ExitStack() as stack:
            for patcher in patchers:
                stack.enter_context(patcher)
            yield coordinator

    @staticmethod
    def _fresh_rec() -> dict:
        return {
            "route": [],
            "redirect": [],
            "disconnect": [],
            "stop_route": [],
            "saved": [],
            "clear": [],
            "refresh": [],
            "published": [],
            "present": False,
        }

    def _authority(self):
        from custom_components.eybond_local.connection.collector_endpoint_operation import (
            COLLECTOR_ENDPOINT_OPERATION_AUTHORITY as AUTH,
        )

        return AUTH

    def _assert_state_token_consistent(self, rec: dict, entry_id: str) -> None:
        """The core invariant: a persisted session and a held token move together.

        Forbidden pairs: (record present AND authority free) and (record absent AND
        authority held). Either the mode owns both, or it owns neither.
        """

        held = self._authority().is_held(entry_id)
        self.assertFalse(
            rec["present"] and not held,
            "persisted session left with a FREE authority",
        )
        self.assertFalse(
            (not rec["present"]) and held,
            "authority held with NO recoverable session",
        )

    def test_shadow_start_cancel_during_first_persistence_never_restores_endpoint(self) -> None:
        # A cancel during the first persistence is still BEFORE any endpoint wire
        # mutation. Cleanup clears the tentative record and releases ownership;
        # issuing a speculative restore here could reboot/disconnect the collector.
        async def _run() -> None:
            rec = self._fresh_rec()
            calls = {"save": 0}

            async def _save(state):
                rec["saved"].append(state)
                rec["present"] = True
                calls["save"] += 1
                if calls["save"] == 1:
                    raise asyncio.CancelledError()

            async def _restore(_endpoint):
                raise AssertionError("endpoint restore must not run before endpoint mutation")

            with self._shadow_start_env(rec, save=_save, restore=_restore) as coord:
                with self.assertRaises(asyncio.CancelledError):
                    await coord.async_start_shadow_learning(
                        output_path=Path("/tmp/shadow-cancel-persist.jsonl"),
                        raw_capture={},
                    )
            self._assert_state_token_consistent(rec, "entry-cancel")
            self.assertTrue(rec["clear"])
            self.assertFalse(rec["present"])
            self.assertFalse(self._authority().is_held("entry-cancel"))

        asyncio.run(_run())

    def test_shadow_start_cancel_during_route_start_stops_exact_route(self) -> None:
        # Blocker 5: a route-start await that is cancelled AFTER creating the route
        # (before route_started could be set) must still be stopped by its EXACT
        # owner id in the finalization.
        async def _run() -> None:
            rec = self._fresh_rec()

            async def _route(**kwargs):
                rec["route"].append(kwargs.get("owner_id"))  # the route now exists
                raise asyncio.CancelledError()

            async def _restore(_endpoint):
                raise AssertionError("endpoint restore must not run before endpoint mutation")

            with self._shadow_start_env(rec, route=_route, restore=_restore) as coord:
                with self.assertRaises(asyncio.CancelledError):
                    await coord.async_start_shadow_learning(
                        output_path=Path("/tmp/shadow-cancel-route.jsonl"),
                        raw_capture={},
                    )
            owner = rec["route"][0]
            self.assertTrue(owner and owner.startswith("shadow_learning:"))
            self.assertEqual(
                rec["stop_route"],
                [owner],
                "the exact route owner must be stopped even when route_started was never set",
            )
            self.assertEqual(
                rec["redirect"],
                [],
                "a cancelled route start must not reach the endpoint write",
            )
            self._assert_state_token_consistent(rec, "entry-cancel")
            self.assertFalse(self._authority().is_held("entry-cancel"))

        asyncio.run(_run())

    def test_shadow_start_redirects_cloud_route_and_persists_restore_contract(self) -> None:
        async def _run() -> None:
            rec = self._fresh_rec()
            with self._shadow_start_env(rec) as coord:
                result = await coord.async_start_shadow_learning(
                    output_path=Path("/tmp/shadow-cloud-route.jsonl"),
                    raw_capture={},
                )

            self.assertEqual(
                rec["redirect"],
                [("192.168.1.50,18899,TCP", True)],
            )
            self.assertEqual(rec["disconnect"], ["shadow_learning_start"])
            self.assertTrue(result["restore_required"])
            self.assertEqual(rec["saved"][-1].status, "ready")
            self.assertEqual(
                rec["saved"][-1].original_endpoint,
                "eu.smartess.io,18899,TCP",
            )
            self.assertEqual(
                rec["saved"][-1].proxy_endpoint,
                "192.168.1.50,18899,TCP",
            )
            authority = self._authority()
            token = authority.adopt(
                "entry-cancel",
                "shadow_learning",
                str(result["session_id"]),
            )
            self.assertIsNotNone(token)
            self.assertTrue(authority.release("entry-cancel", token))

        asyncio.run(_run())

    def test_proxy_start_disconnects_runtime_after_redirect_before_wait(self) -> None:
        async def _run() -> None:
            rec = self._fresh_rec()
            order: list[str] = []

            async def _redirect(endpoint, *, apply_changes=True):
                order.append("redirect")
                rec["redirect"].append((endpoint, apply_changes))
                return {"readback_endpoint": endpoint}

            async def _disconnect(*, reason):
                order.append("disconnect")
                rec["disconnect"].append(reason)

            async def _wait(*_args, **_kwargs):
                order.append("wait")

            with self._proxy_start_env(
                rec,
                redirect=_redirect,
                disconnect=_disconnect,
                wait=_wait,
            ) as coord:
                result = await coord.async_start_proxy_capture(confirm_redirect=True)

            self.assertEqual(order, ["redirect", "disconnect", "wait"])
            self.assertEqual(rec["disconnect"], ["proxy_capture_start"])
            self.assertEqual(result["status"], "running")

            authority = self._authority()
            owner_ref = str(rec["saved"][-1].route_owner_id)
            token = authority.adopt("entry-cancel", "proxy_capture", owner_ref)
            self.assertIsNotNone(token)
            self.assertTrue(authority.release("entry-cancel", token))

        asyncio.run(_run())

    def test_proxy_start_routes_new_cloud_session_transparently(self) -> None:
        async def _run() -> None:
            rec = self._fresh_rec()
            route_kwargs: list[dict[str, object]] = []

            async def _route(**kwargs):
                route_kwargs.append(dict(kwargs))
                rec["route"].append(kwargs.get("owner_id"))

            with self._proxy_start_env(
                rec,
                route=_route,
                collector_session_protocol="eybond_framed",
            ) as coord:
                result = await coord.async_start_proxy_capture(
                    confirm_redirect=True
                )

            self.assertEqual(result["status"], "running")
            self.assertEqual(
                route_kwargs[0]["proxy_wire_mode"],
                "transparent",
            )
            self.assertEqual(
                route_kwargs[0]["expected_session_protocol"],
                "at_text",
            )
            self.assertNotIn("bridge_context", route_kwargs[0])
            self.assertEqual(
                rec["saved"][0].proxy_wire_mode,
                "transparent",
            )
            self.assertEqual(
                rec["saved"][-1].proxy_wire_mode,
                "transparent",
            )

            authority = self._authority()
            token = authority.adopt(
                "entry-cancel",
                "proxy_capture",
                str(rec["saved"][-1].route_owner_id),
            )
            self.assertIsNotNone(token)
            self.assertTrue(authority.release("entry-cancel", token))

        asyncio.run(_run())

    def test_shadow_start_failed_restore_keeps_state_and_authority(self) -> None:
        async def _run() -> None:
            rec = self._fresh_rec()

            async def _redirect(_endpoint, *, apply_changes=True):
                raise asyncio.CancelledError()

            async def _restore(_endpoint):
                return False, "restore_write_timeout"

            with self._shadow_start_env(
                rec,
                redirect=_redirect,
                restore=_restore,
            ) as coord:
                with self.assertRaises(asyncio.CancelledError):
                    await coord.async_start_shadow_learning(
                        output_path=Path("/tmp/shadow-restore-failed.jsonl"),
                        raw_capture={},
                    )

            self._assert_state_token_consistent(rec, "entry-cancel")
            self.assertTrue(rec["present"])
            self.assertFalse(rec["clear"])
            self.assertTrue(self._authority().is_held("entry-cancel"))
            self.assertEqual(rec["saved"][-1].status, "restore_failed")
            self.assertEqual(
                rec["saved"][-1].last_restore_error,
                "restore_write_timeout",
            )

        asyncio.run(_run())

    def test_shadow_start_two_cancels_finalization_runs_to_completion(self) -> None:
        # Blocker 2: the first cancel enters the shielded finalization; a second
        # cancel arrives while it is blocked; the finalization still runs to the
        # end once the rendezvous releases; the caller then receives CancelledError
        # and the state/token pair is consistent.
        async def _run() -> None:
            rec = self._fresh_rec()
            reached_route = asyncio.Event()
            route_gate = asyncio.Event()
            reached_cleanup = asyncio.Event()
            cleanup_gate = asyncio.Event()

            async def _route(**kwargs):
                rec["route"].append(kwargs.get("owner_id"))
                reached_route.set()
                await route_gate.wait()  # cancel #1 lands here

            async def _stop_route(**kwargs):
                rec["stop_route"].append(kwargs.get("owner_id"))
                reached_cleanup.set()
                await cleanup_gate.wait()  # cancel #2 arrives while blocked here

            async def _restore(_endpoint):
                return True, ""

            with self._shadow_start_env(
                rec, route=_route, stop_route=_stop_route, restore=_restore
            ) as coord:
                task = asyncio.ensure_future(
                    coord.async_start_shadow_learning(
                        output_path=Path("/tmp/shadow-two-cancel.jsonl"),
                        raw_capture={},
                    )
                )
                await asyncio.wait_for(reached_route.wait(), 2.0)
                task.cancel()  # #1 -> finalization begins
                await asyncio.wait_for(reached_cleanup.wait(), 2.0)
                task.cancel()  # #2 -> absorbed by the shield; cleanup keeps running
                cleanup_gate.set()  # release the rendezvous -> cleanup completes
                with self.assertRaises(asyncio.CancelledError):
                    await task

            self.assertEqual(rec["stop_route"], [rec["route"][0]])
            self.assertTrue(rec["clear"])
            self.assertFalse(rec["present"])
            self._assert_state_token_consistent(rec, "entry-cancel")
            self.assertFalse(self._authority().is_held("entry-cancel"))

        asyncio.run(_run())

    def test_shadow_stop_atomic_clear_and_release_survives_cancel(self) -> None:
        # Blocker 3: in a stop success path the clear+release is ONE shielded
        # critical section. Even if clear removes the record then blocks and the
        # task is cancelled, after the boundary the record is absent AND the
        # authority is free (never absent + held), and the caller gets CancelledError.
        async def _run() -> None:
            AUTH = self._authority()
            entry_id = "entry-stop-clear"
            rec = self._fresh_rec()
            rec["present"] = True
            reached_clear = asyncio.Event()
            clear_gate = asyncio.Event()

            state = types.SimpleNamespace(
                entry_id=entry_id,
                collector_pn="E5000020000000",
                trace_path="/tmp/shadow.jsonl",
                original_endpoint="eu.smartess.io,18899,TCP",
                proxy_endpoint="192.168.1.50,18899,TCP",
                upstream_endpoint="eu.smartess.io,18899,TCP",
                restore_required=True,
                started_at="2026-06-05T12:00:00+00:00",
                expires_at="2026-06-05T12:20:00+00:00",
                restore_attempt_count=0,
                last_restore_attempt_at="",
                last_restore_error="",
                route_owner_id=f"shadow_learning:{entry_id}:1",
            )
            coordinator = object.__new__(self.coordinator_module.EybondLocalCoordinator)
            coordinator.config_entry = types.SimpleNamespace(entry_id=entry_id)

            async def _stop_route(**kwargs):
                return None

            coordinator._runtime = types.SimpleNamespace(
                async_stop_shadow_learning_route=_stop_route
            )

            async def _active(*, require_process: bool = True):
                return state

            async def _save(new_state):
                rec["saved"].append(new_state)
                rec["present"] = True

            async def _restore(_endpoint):
                return "eu.smartess.io,18899,TCP"

            async def _verify(endpoint):
                return {
                    "restore_confirmed": True,
                    "observed_endpoint": endpoint,
                    "restore_error": "",
                }

            async def _clear():
                rec["present"] = False  # record actually removed
                reached_clear.set()
                await clear_gate.wait()  # blocks BEFORE returning
                rec["clear"].append(True)

            async def _refresh():
                rec["refresh"].append(True)

            coordinator._async_active_shadow_learning_state = _active
            coordinator._async_save_shadow_learning_session_state = _save
            coordinator._async_restore_proxy_capture_endpoint = _restore
            coordinator._async_verify_restored_collector_endpoint = _verify
            coordinator._async_clear_shadow_learning_session_state = _clear
            coordinator.async_request_refresh = _refresh
            coordinator._publish_tooling_values = lambda **kwargs: None
            coordinator._notify_proxy_capture_restore_unconfirmed = lambda: None

            task = asyncio.ensure_future(coordinator.async_stop_shadow_learning())
            await asyncio.wait_for(reached_clear.wait(), 2.0)
            # The record is already gone; the authority is still held until release.
            self.assertFalse(rec["present"])
            task.cancel()
            clear_gate.set()  # let the shielded clear+release finish
            with self.assertRaises(asyncio.CancelledError):
                await task

            # After the critical boundary: record absent AND authority free.
            self.assertFalse(rec["present"])
            self.assertFalse(AUTH.is_held(entry_id))
            self.assertTrue(rec["clear"])

        asyncio.run(_run())

    def test_proxy_stop_atomic_clear_and_release_survives_cancel(self) -> None:
        """The proxy stop has its own production branch and must be equally atomic."""

        async def _run() -> None:
            AUTH = self._authority()
            entry_id = "entry-proxy-stop-clear"
            rec = self._fresh_rec()
            rec["present"] = True
            reached_clear = asyncio.Event()
            clear_gate = asyncio.Event()
            tmp_dir = tempfile.mkdtemp(prefix="cp2c-proxy-stop-")
            trace_path = Path(tmp_dir) / "proxy.jsonl"
            state = types.SimpleNamespace(
                entry_id=entry_id,
                route_owner_id=f"proxy_capture:{entry_id}:1",
                collector_pn="E5000020000000",
                trace_path=str(trace_path),
                original_endpoint="eu.smartess.io,18899,TCP",
                proxy_endpoint="192.168.1.50,18899,TCP",
                restore_required=True,
                anonymized=False,
                started_at="2026-06-05T12:00:00+00:00",
                expires_at="2026-06-05T12:20:00+00:00",
                status="running",
            )
            coordinator = object.__new__(self.coordinator_module.EybondLocalCoordinator)
            coordinator.config_entry = types.SimpleNamespace(entry_id=entry_id)

            async def _executor(func, *args):
                return func(*args)

            coordinator.hass = types.SimpleNamespace(
                config=types.SimpleNamespace(config_dir=tmp_dir),
                async_add_executor_job=_executor,
            )

            async def _active(*, require_process: bool = True):
                return state

            async def _save(new_state):
                rec["saved"].append(new_state)
                rec["present"] = True

            async def _restore(**kwargs):
                return {
                    "restored_endpoint": state.original_endpoint,
                    "restore_confirmed": True,
                    "restore_mode": "direct",
                    "restore_skipped_reason": "",
                    "current_endpoint": state.original_endpoint,
                }

            async def _clear():
                rec["present"] = False
                reached_clear.set()
                await clear_gate.wait()
                rec["clear"].append(True)

            coordinator._async_active_proxy_capture_state = _active
            coordinator._async_save_proxy_capture_session_state = _save
            coordinator._async_guarded_proxy_capture_restore = _restore
            coordinator._async_clear_proxy_capture_session_state = _clear
            coordinator._proxy_capture_result_status = lambda *a, **k: "stopped"
            coordinator._proxy_capture_local_status = lambda *a, **k: "stopped"
            coordinator._proxy_capture_overview_runtime_values = lambda **kwargs: {}
            coordinator._publish_tooling_values = lambda **kwargs: None
            coordinator.async_request_refresh = lambda: asyncio.sleep(0)

            with patch.object(
                self.coordinator_module.EybondLocalCoordinator,
                "smartess_collector_pn",
                new_callable=PropertyMock,
                return_value="E5000020000000",
            ), patch.object(
                self.coordinator_cloud_tools_module,
                "build_proxy_capture_session_state",
                lambda *a, **k: types.SimpleNamespace(**k),
            ), patch.object(
                self.coordinator_cloud_tools_module,
                "summarize_proxy_capture_trace",
                return_value={},
            ), patch.object(
                self.coordinator_cloud_tools_module,
                "export_proxy_trace_manifest",
                return_value=Path(tmp_dir) / "manifest.json",
            ), patch.object(
                self.coordinator_cloud_tools_module,
                "export_proxy_trace_bundle",
                return_value=Path(tmp_dir) / "bundle.zip",
            ), patch.object(
                self.coordinator_cloud_tools_module,
                "sign_proxy_capture_download_url",
                return_value=(
                    "/api/eybond_local/proxy_capture/entry-id/bundle.zip"
                    "?authSig=signed"
                ),
            ):
                task = asyncio.ensure_future(coordinator.async_stop_proxy_capture())
                await asyncio.wait_for(reached_clear.wait(), 2.0)
                self.assertFalse(rec["present"])
                task.cancel()
                clear_gate.set()
                with self.assertRaises(asyncio.CancelledError):
                    await task

            self.assertFalse(rec["present"])
            self.assertFalse(AUTH.is_held(entry_id))
            self.assertTrue(rec["clear"])

        asyncio.run(_run())

    @contextlib.contextmanager
    def _proxy_start_env(self, rec, **seams):
        """Bare-coordinator harness that drives the REAL async_start_proxy_capture."""

        coordinator = object.__new__(self.coordinator_module.EybondLocalCoordinator)
        tmp_dir = tempfile.mkdtemp(prefix="cp2c-proxy-")

        async def _executor(func, *args):
            return func(*args)

        async def d_route(**kwargs):
            rec["route"].append(kwargs.get("owner_id"))

        async def d_redirect(endpoint, *, apply_changes=True):
            rec["redirect"].append((endpoint, apply_changes))
            return {"readback_endpoint": endpoint}

        async def d_stop_process(*, owner_id="", force=False):
            rec["stop_route"].append(owner_id)

        async def d_disconnect(*, reason):
            rec["disconnect"].append(reason)

        async def d_preflight(**kwargs):
            return None

        async def d_save(state):
            rec["saved"].append(state)
            rec["present"] = True

        async def d_active_shadow(*, require_process=True):
            return None

        async def d_wait(*args, **kwargs):
            return None

        async def d_restore(_endpoint):
            return True, ""

        async def d_clear():
            rec["clear"].append(True)
            rec["present"] = False

        async def d_refresh():
            rec["refresh"].append(True)

        async def d_endpoint_context():
            return types.SimpleNamespace(
                current_endpoint=overview.current_endpoint,
                upstream_endpoint="eu.smartess.io,18899,TCP",
                target_endpoint=overview.target_endpoint,
            )

        pick = lambda key, default: seams.get(key, default)
        overview = types.SimpleNamespace(
            can_start=True,
            blocking_reason=None,
            redirect_required=seams.get("redirect_required", True),
            target_endpoint="192.168.1.50,18899,TCP",
            current_endpoint="eu.smartess.io,18899,TCP",
            masked_endpoint="masked.example,18899,TCP",
        )
        coordinator.config_entry = types.SimpleNamespace(
            entry_id="entry-cancel", data={}, options={}
        )
        coordinator.hass = types.SimpleNamespace(
            config=types.SimpleNamespace(config_dir=tmp_dir),
            async_add_executor_job=_executor,
        )
        coordinator._runtime = types.SimpleNamespace(
            async_start_proxy_capture_route=pick("route", d_route),
            async_set_collector_server_endpoint=pick("redirect", d_redirect),
            async_disconnect_collector_connections=pick("disconnect", d_disconnect),
        )
        coordinator.collector_endpoint_sync_lock_code = lambda: None
        coordinator._async_active_shadow_learning_state = d_active_shadow
        coordinator._shadow_learning_process_running = lambda: False
        coordinator._proxy_capture_process_running = lambda: False
        coordinator._async_save_proxy_capture_session_state = pick("save", d_save)
        coordinator._async_preflight_proxy_capture_network = pick("preflight", d_preflight)
        coordinator._proxy_capture_collector_ip = lambda: "192.168.1.55"
        coordinator._async_wait_for_proxy_capture_reconnect = pick("wait", d_wait)
        coordinator._async_best_effort_restore_after_start_failure = pick("restore", d_restore)
        coordinator._async_stop_proxy_capture_process = pick("stop_route", d_stop_process)
        coordinator._async_clear_proxy_capture_session_state = pick("clear", d_clear)
        coordinator._async_prepare_cloud_tool_endpoint_context = pick(
            "endpoint_context", d_endpoint_context
        )
        coordinator._proxy_capture_overview_for_live_context = lambda _context: overview
        coordinator.async_request_refresh = d_refresh
        coordinator._publish_tooling_values = lambda **kwargs: rec["published"].append(dict(kwargs))
        coordinator._proxy_capture_overview_runtime_values = lambda **kwargs: {}

        prop = lambda name, value: patch.object(
            self.coordinator_module.EybondLocalCoordinator,
            name,
            new_callable=PropertyMock,
            return_value=value,
        )
        patchers = [
            prop("support_acquisition_readiness", self._support_readiness()),
            prop("proxy_capture_overview", overview),
            prop("smartess_collector_pn", "E5000020000000"),
            prop("collector_cloud_tools_allowed", True),
            prop(
                "collector_capabilities",
                types.SimpleNamespace(proxy_capture=True),
            ),
            prop("collector_actions_enabled", True),
            prop("proxy_capture_upstream_endpoint", "eu.smartess.io,18899,TCP"),
            prop("collector_cloud_family", "smartess"),
            prop(
                "collector_session_protocol",
                seams.get("collector_session_protocol", "at_text"),
            ),
            prop("proxy_capture_configured_duration_minutes", 10),
            # The stub harness returns None for these path builders; give the real
            # method usable paths (nothing is written -- the route seam is stubbed).
            patch.object(
                self.coordinator_cloud_tools_module,
                "build_proxy_capture_trace_path",
                lambda *a, **k: Path(tmp_dir) / "proxy-trace.jsonl",
            ),
            patch.object(
                self.coordinator_cloud_tools_module,
                "build_proxy_capture_restore_trigger_path",
                lambda trace_path, *a, **k: Path(str(trace_path) + ".restore"),
            ),
            patch.object(
                self.coordinator_cloud_tools_module,
                "resolve_collector_cloud_session_protocol",
                lambda _family: "at_text",
            ),
            # The stub harness returns None for the session-state builder; give the
            # real method a namespace that carries route_owner_id/status/etc.
            patch.object(
                self.coordinator_cloud_tools_module,
                "build_proxy_capture_session_state",
                lambda *a, **k: types.SimpleNamespace(**k),
            ),
        ]
        with contextlib.ExitStack() as stack:
            for patcher in patchers:
                stack.enter_context(patcher)
            yield coordinator

    def test_proxy_start_failed_live_recheck_never_mutates_endpoint(self) -> None:
        async def _run() -> None:
            for error in (
                RuntimeError("cloud_tool_collector_not_connected"),
                RuntimeError("cloud_tool_current_endpoint_unavailable"),
                asyncio.CancelledError(),
            ):
                with self.subTest(error=type(error).__name__):
                    rec = self._fresh_rec()

                    async def _endpoint_context():
                        raise error

                    with self._proxy_start_env(rec, endpoint_context=_endpoint_context) as coord:
                        with self.assertRaises(type(error)):
                            await coord.async_start_proxy_capture(confirm_redirect=True)
                    self.assertEqual(rec["route"], [])
                    self.assertEqual(rec["redirect"], [])
                    self.assertEqual(rec["saved"], [])
                    self.assertEqual(rec["disconnect"], [])
                    self.assertFalse(self._authority().is_held("entry-cancel"))

        asyncio.run(_run())

    def test_proxy_start_cancel_during_first_persistence_never_restores_endpoint(self) -> None:
        # Same pre-wire boundary for proxy capture: tentative persistence may be
        # cleared, but the collector endpoint must not be rewritten.
        async def _run() -> None:
            rec = self._fresh_rec()
            calls = {"save": 0}

            async def _save(state):
                rec["saved"].append(state)
                rec["present"] = True
                calls["save"] += 1
                if calls["save"] == 1:
                    raise asyncio.CancelledError()

            async def _restore(_endpoint):
                raise AssertionError("endpoint restore must not run before endpoint mutation")

            with self._proxy_start_env(rec, save=_save, restore=_restore) as coord:
                with self.assertRaises(asyncio.CancelledError):
                    await coord.async_start_proxy_capture(confirm_redirect=True)
            self._assert_state_token_consistent(rec, "entry-cancel")
            self.assertTrue(rec["clear"])
            self.assertFalse(self._authority().is_held("entry-cancel"))

        asyncio.run(_run())

    def test_proxy_start_cancel_during_endpoint_write_failed_restore_is_recoverable(self) -> None:
        # After the endpoint-write await begins, a failed restore must retain the
        # recoverable record and authority because the wire result is uncertain.
        async def _run() -> None:
            rec = self._fresh_rec()
            async def _save(state):
                rec["saved"].append(state)
                rec["present"] = True

            async def _redirect(_endpoint, *, apply_changes=True):
                raise asyncio.CancelledError()

            async def _restore(_endpoint):
                return False, "restore_write_timeout"

            with self._proxy_start_env(
                rec, save=_save, redirect=_redirect, restore=_restore
            ) as coord:
                with self.assertRaises(asyncio.CancelledError):
                    await coord.async_start_proxy_capture(confirm_redirect=True)
            self._assert_state_token_consistent(rec, "entry-cancel")
            self.assertTrue(rec["present"])
            self.assertFalse(rec["clear"])
            self.assertTrue(self._authority().is_held("entry-cancel"))
            self.assertEqual(rec["saved"][-1].status, "restoring")

        asyncio.run(_run())

    def test_proxy_start_cancel_during_route_start_stops_exact_route(self) -> None:
        # Blocker 5 for proxy: a cancelled route-start (route created, route_started
        # never set) is still stopped by its EXACT owner id in the finalization.
        async def _run() -> None:
            rec = self._fresh_rec()

            async def _route(**kwargs):
                rec["route"].append(kwargs.get("owner_id"))
                raise asyncio.CancelledError()

            async def _restore(_endpoint):
                raise AssertionError("endpoint restore must not run before endpoint mutation")

            with self._proxy_start_env(rec, route=_route, restore=_restore) as coord:
                with self.assertRaises(asyncio.CancelledError):
                    await coord.async_start_proxy_capture(confirm_redirect=True)
            owner = rec["route"][0]
            self.assertTrue(owner and owner.startswith("proxy_capture:"))
            self.assertEqual(rec["stop_route"], [owner])
            self._assert_state_token_consistent(rec, "entry-cancel")
            self.assertFalse(self._authority().is_held("entry-cancel"))

        asyncio.run(_run())

    def test_wait_for_shadow_learning_ready_rejects_stale_collector_connection(self) -> None:
        async def _run() -> None:
            coordinator = object.__new__(self.coordinator_module.EybondLocalCoordinator)
            statuses = [
                {
                    "running": True,
                    "collector_connected": True,
                    "collector_connection_sequence": 7,
                    "collector_protocol_ingress": True,
                    "route_protocol_activity": True,
                    "upstream_connected": False,
                    "ready": False,
                    "upstream_error": "",
                },
                {
                    "running": True,
                    "collector_connected": True,
                    "collector_connection_sequence": 8,
                    "collector_protocol_ingress": True,
                    "route_protocol_activity": True,
                    "upstream_connected": False,
                    "ready": False,
                    "upstream_error": "",
                },
            ]
            sleeps: list[float] = []

            coordinator._shadow_learning_process_running = lambda: True
            coordinator._shadow_learning_route_status = lambda: statuses.pop(0)

            original_sleep = self.coordinator_module.asyncio.sleep

            async def _sleep(duration: float) -> None:
                sleeps.append(duration)

            self.coordinator_module.asyncio.sleep = _sleep
            try:
                await coordinator._async_wait_for_shadow_learning_ready(
                    trace_path=Path("/tmp/shadow-stale-connection.jsonl"),
                    timeout_seconds=5.0,
                    min_collector_connection_sequence=7,
                )
            finally:
                self.coordinator_module.asyncio.sleep = original_sleep

            self.assertEqual(sleeps, [1.0])
            self.assertEqual(statuses, [])

        import asyncio

        asyncio.run(_run())

    def test_best_effort_restore_after_start_failure_reports_unconfirmed_restore(self) -> None:
        async def _run() -> None:
            coordinator = object.__new__(self.coordinator_module.EybondLocalCoordinator)
            notifications: list[bool] = []
            coordinator.config_entry = types.SimpleNamespace(entry_id="entry-id")

            async def _async_restore_proxy_capture_endpoint(_endpoint: str):
                raise RuntimeError("write_timeout")

            coordinator._async_restore_proxy_capture_endpoint = _async_restore_proxy_capture_endpoint
            coordinator._notify_proxy_capture_restore_unconfirmed = lambda: notifications.append(True)

            confirmed, reason = await coordinator._async_best_effort_restore_after_start_failure(
                "eu.smartess.io,18899,TCP"
            )

            self.assertFalse(confirmed)
            self.assertEqual(reason, "write_timeout")
            self.assertTrue(notifications)

        import asyncio

        asyncio.run(_run())

    def test_start_failure_restore_ack_without_live_postcondition_is_unconfirmed(
        self,
    ) -> None:
        async def _run() -> None:
            coordinator = object.__new__(
                self.coordinator_module.EybondLocalCoordinator
            )
            coordinator.config_entry = types.SimpleNamespace(entry_id="entry-id")
            notifications: list[bool] = []

            coordinator._async_restore_proxy_capture_endpoint = (
                lambda endpoint: asyncio.sleep(0, result=endpoint)
            )
            coordinator._async_verify_restored_collector_endpoint = (
                lambda endpoint: asyncio.sleep(
                    0,
                    result={
                        "restore_confirmed": False,
                        "observed_endpoint": "",
                        "restore_error": "restore_live_endpoint_unavailable",
                    },
                )
            )
            coordinator._notify_proxy_capture_restore_unconfirmed = (
                lambda: notifications.append(True)
            )

            confirmed, reason = (
                await coordinator._async_best_effort_restore_after_start_failure(
                    "eu.smartess.io,18899,TCP"
                )
            )

            self.assertFalse(confirmed)
            self.assertEqual(reason, "restore_live_endpoint_unavailable")
            self.assertEqual(notifications, [True])

        asyncio.run(_run())

    def test_restore_verification_requires_live_matching_endpoint(self) -> None:
        async def _run() -> None:
            coordinator = object.__new__(
                self.coordinator_module.EybondLocalCoordinator
            )
            coordinator.config_entry = types.SimpleNamespace(entry_id="entry-id")
            calls: list[float] = []

            async def _endpoint_state(
                *,
                timeout: float = 0.0,
                require_heartbeat: bool = True,
            ):
                calls.append(timeout)
                self.assertFalse(require_heartbeat)
                return {
                    "current_endpoint": "eu.smartess.io,18899,TCP",
                }

            coordinator._runtime = types.SimpleNamespace(
                async_get_collector_server_endpoint_state=_endpoint_state
            )
            with patch.object(
                self.coordinator_module.EybondLocalCoordinator,
                "collector_cloud_family",
                new_callable=PropertyMock,
                return_value="",
            ):
                result = (
                    await coordinator._async_verify_restored_collector_endpoint(
                        "eu.smartess.io,18899,TCP"
                    )
                )

            self.assertTrue(result["restore_confirmed"])
            self.assertEqual(
                calls,
                [
                    self.coordinator_module.DEFAULT_ONBOARDING_TIMEOUT_POLICY.callback_recovery_session_wait
                ],
            )

        asyncio.run(_run())

    def test_restore_verification_fails_closed_on_mismatch_or_timeout(self) -> None:
        async def _run() -> None:
            coordinator = object.__new__(
                self.coordinator_module.EybondLocalCoordinator
            )
            coordinator.config_entry = types.SimpleNamespace(entry_id="entry-id")

            async def _mismatch(
                *,
                timeout: float = 0.0,
                require_heartbeat: bool = True,
            ):
                self.assertFalse(require_heartbeat)
                return {
                    "current_endpoint": "192.168.1.50,18899,TCP",
                }

            coordinator._runtime = types.SimpleNamespace(
                async_get_collector_server_endpoint_state=_mismatch
            )
            with patch.object(
                self.coordinator_module.EybondLocalCoordinator,
                "collector_cloud_family",
                new_callable=PropertyMock,
                return_value="",
            ):
                mismatch = (
                    await coordinator._async_verify_restored_collector_endpoint(
                        "eu.smartess.io,18899,TCP"
                    )
                )
                self.assertFalse(mismatch["restore_confirmed"])
                self.assertEqual(
                    mismatch["restore_error"],
                    "restore_live_endpoint_mismatch",
                )

                async def _timeout(
                    *,
                    timeout: float = 0.0,
                    require_heartbeat: bool = True,
                ):
                    self.assertFalse(require_heartbeat)
                    raise TimeoutError("collector_not_connected")

                coordinator._runtime = types.SimpleNamespace(
                    async_get_collector_server_endpoint_state=_timeout
                )
                timed_out = (
                    await coordinator._async_verify_restored_collector_endpoint(
                        "eu.smartess.io,18899,TCP"
                    )
                )
                self.assertFalse(timed_out["restore_confirmed"])
                self.assertIn(
                    "collector_not_connected",
                    timed_out["restore_error"],
                )

        asyncio.run(_run())

    def test_proxy_restore_ack_without_live_read_falls_back_to_direct_restore(self) -> None:
        async def _run() -> None:
            coordinator = object.__new__(
                self.coordinator_module.EybondLocalCoordinator
            )
            state = types.SimpleNamespace(
                trace_path="/tmp/proxy.jsonl",
                route_owner_id="proxy_capture:entry-id:1",
                restore_required=True,
                original_endpoint="eu.smartess.io,18899,TCP",
                proxy_endpoint="192.168.1.50,18899,TCP",
            )
            coordinator._async_read_live_collector_server_endpoint = (
                lambda: asyncio.sleep(
                    0,
                    result="192.168.1.50,18899,TCP",
                )
            )
            coordinator._proxy_capture_process_running = lambda: True
            coordinator._async_trigger_proxy_capture_restore = (
                lambda **kwargs: asyncio.sleep(0, result=True)
            )
            coordinator._async_verify_restored_collector_endpoint = (
                AsyncMock(
                    side_effect=(
                        {
                            "restore_confirmed": False,
                            "observed_endpoint": "",
                            "restore_error": "restore_live_endpoint_unavailable",
                        },
                        {
                            "restore_confirmed": True,
                            "observed_endpoint": "eu.smartess.io,18899,TCP",
                            "restore_error": "",
                        },
                    )
                )
            )
            stop_calls: list[str] = []
            coordinator._async_stop_proxy_capture_process = (
                lambda *, owner_id: asyncio.sleep(
                    0,
                    result=stop_calls.append(owner_id),
                )
            )
            direct_calls: list[str] = []
            coordinator._async_restore_proxy_capture_endpoint = (
                lambda endpoint: asyncio.sleep(
                    0,
                    result=(
                        direct_calls.append(endpoint)
                        or endpoint
                    ),
                )
            )

            result = await coordinator._async_guarded_proxy_capture_restore(
                state=state,
                prefer_proxy_restore_trigger=True,
            )

            self.assertTrue(result["restore_confirmed"])
            self.assertEqual(result["restore_mode"], "proxy_trigger_then_direct")
            self.assertEqual(direct_calls, ["eu.smartess.io,18899,TCP"])
            self.assertEqual(
                stop_calls,
                ["proxy_capture:entry-id:1"],
            )

        asyncio.run(_run())

    def test_unavailable_current_endpoint_runs_owned_direct_restore(self) -> None:
        async def _run() -> None:
            coordinator = object.__new__(
                self.coordinator_module.EybondLocalCoordinator
            )
            state = types.SimpleNamespace(
                trace_path="/tmp/proxy.jsonl",
                route_owner_id="proxy_capture:entry-id:2",
                restore_required=True,
                original_endpoint="dtu_ess.eybond.com,18899,TCP",
                proxy_endpoint="192.168.1.50,18899,TCP",
            )
            coordinator.config_entry = types.SimpleNamespace(entry_id="entry-id")
            coordinator._async_read_live_collector_server_endpoint = (
                lambda: asyncio.sleep(0, result="")
            )
            coordinator._proxy_capture_process_running = lambda: False
            stop_calls: list[str] = []
            coordinator._async_stop_proxy_capture_process = (
                lambda *, owner_id: asyncio.sleep(
                    0,
                    result=stop_calls.append(owner_id),
                )
            )
            direct_calls: list[str] = []
            coordinator._async_restore_proxy_capture_endpoint = (
                lambda endpoint: asyncio.sleep(
                    0,
                    result=(
                        direct_calls.append(endpoint)
                        or endpoint
                    ),
                )
            )
            coordinator._async_verify_restored_collector_endpoint = (
                lambda endpoint: asyncio.sleep(
                    0,
                    result={
                        "restore_confirmed": True,
                        "observed_endpoint": endpoint,
                        "restore_error": "",
                    },
                )
            )

            with patch.object(
                self.coordinator_cloud_tools_module,
                "proxy_capture_restore_guard_reason",
                return_value="current_endpoint_unavailable",
            ):
                result = await coordinator._async_guarded_proxy_capture_restore(
                    state=state,
                    prefer_proxy_restore_trigger=True,
                )

            self.assertTrue(result["restore_confirmed"])
            self.assertEqual(result["restore_mode"], "direct")
            self.assertEqual(
                direct_calls,
                ["dtu_ess.eybond.com,18899,TCP"],
            )
            self.assertEqual(
                stop_calls,
                ["proxy_capture:entry-id:2"],
            )

        asyncio.run(_run())

    def test_endpoint_terminalization_is_serialized_across_same_owner_calls(self) -> None:
        async def _run() -> None:
            coordinator = object.__new__(
                self.coordinator_module.EybondLocalCoordinator
            )
            entered = asyncio.Event()
            release = asyncio.Event()
            active = 0
            max_active = 0

            async def _stop_once(**kwargs):
                nonlocal active, max_active
                active += 1
                max_active = max(max_active, active)
                entered.set()
                await release.wait()
                active -= 1
                return {"status": "stopped"}

            coordinator._async_stop_proxy_capture_once = _stop_once
            first = asyncio.create_task(coordinator.async_stop_proxy_capture())
            await entered.wait()
            second = asyncio.create_task(coordinator.async_stop_proxy_capture())
            await asyncio.sleep(0)
            self.assertEqual(max_active, 1)
            release.set()
            await asyncio.gather(first, second)
            self.assertEqual(max_active, 1)

        asyncio.run(_run())

    def test_restore_proxy_capture_endpoint_bypasses_transition_lock(self) -> None:
        async def _run() -> None:
            coordinator = object.__new__(self.coordinator_module.EybondLocalCoordinator)
            calls: list[tuple[str, bool, float, bool]] = []
            disconnect_reasons: list[str] = []

            async def _async_set_collector_server_endpoint(
                endpoint: str,
                *,
                apply_changes: bool = True,
                timeout: float = 0.0,
                require_heartbeat: bool = True,
            ):
                calls.append(
                    (endpoint, apply_changes, timeout, require_heartbeat)
                )
                return {"readback_endpoint": endpoint}

            async def _async_disconnect_collector_connections(*, reason: str):
                disconnect_reasons.append(reason)

            coordinator._runtime = types.SimpleNamespace(
                async_set_collector_server_endpoint=_async_set_collector_server_endpoint,
                async_disconnect_collector_connections=(
                    _async_disconnect_collector_connections
                ),
            )

            def _raise_if_high_level_collector_actions_disabled() -> None:
                raise AssertionError("restore should bypass high-level collector locks")

            coordinator._raise_if_high_level_collector_actions_disabled = (
                _raise_if_high_level_collector_actions_disabled
            )

            restored_endpoint = await coordinator._async_restore_proxy_capture_endpoint(
                "ess.eybond.com"
            )

            self.assertEqual(restored_endpoint, "ess.eybond.com")
            self.assertEqual(
                calls,
                [
                    (
                        "ess.eybond.com",
                        True,
                        self.coordinator_module.DEFAULT_ONBOARDING_TIMEOUT_POLICY.callback_recovery_session_wait,
                        False,
                    )
                ],
            )
            self.assertEqual(
                disconnect_reasons,
                ["collector_endpoint_restore"],
            )

        import asyncio

        asyncio.run(_run())

    def test_collector_onboarding_values_publish_status_label(self) -> None:
        coordinator = object.__new__(self.coordinator_module.EybondLocalCoordinator)
        coordinator.config_entry = types.SimpleNamespace(
            entry_id="entry-1",
            data={},
            options={},
        )
        coordinator.data = self.RuntimeSnapshot(
            values={"support_workflow_level_label": "Pending confirmation"}
        )
        coordinator._connection_spec = types.SimpleNamespace(
            effective_advertised_server_ip="192.168.1.50",
        )
        coordinator._runtime = types.SimpleNamespace(
            collector_server_endpoint_rollback_target="",
        )
        coordinator._remembered_collector_server_endpoint = "47.91.67.66,18899,TCP"

        values = coordinator._collector_onboarding_values(coordinator.data)

        self.assertEqual(values["collector_onboarding_status"], "Pending confirmation")
        self.assertTrue(values["collector_original_endpoint_known"])
        self.assertEqual(values["collector_original_endpoint_profile_key"], "")
        self.assertEqual(values["collector_original_endpoint_source"], "")
        self.assertEqual(values["collector_original_endpoint_observed_at"], "")

    def test_publish_snapshot_endpoint_keeps_collector_and_legacy_in_sync(self) -> None:
        coordinator = object.__new__(self.coordinator_module.EybondLocalCoordinator)
        collector = types.SimpleNamespace(
            collector_server_endpoint="old.example,18899,TCP"
        )
        coordinator.data = self.RuntimeSnapshot(
            collector=collector,
            values={"collector_server_endpoint": "old.example,18899,TCP"},
        )
        published: list[object] = []
        coordinator.async_set_updated_data = published.append

        coordinator._publish_snapshot_values(
            collector_server_endpoint="new.example,18899,TCP"
        )

        self.assertEqual(
            collector.collector_server_endpoint,
            "new.example,18899,TCP",
        )
        self.assertEqual(
            coordinator.data.values["collector_server_endpoint"],
            "new.example,18899,TCP",
        )
        self.assertEqual(published, [coordinator.data])

    def test_prime_startup_snapshot_publishes_detection_pending_collector_state(self) -> None:
        coordinator = object.__new__(self.coordinator_module.EybondLocalCoordinator)
        coordinator.config_entry = types.SimpleNamespace(
            entry_id="entry-1",
            data={
                "connection_type": "eybond",
                "connection_mode": "manual",
                "collector_operation_mode": "home_assistant_only",
                "control_mode": "read_only",
                "detection_confidence": "none",
            },
            options={},
        )
        coordinator.data = self.RuntimeSnapshot(values={})
        coordinator._connection_spec = types.SimpleNamespace(
            collector_ip="192.168.1.51",
            collector_pn="V0000000000001",
            collector_cloud_family="smartess_at",
            server_ip="192.168.1.50",
            tcp_port=18899,
            effective_advertised_server_ip="192.168.1.50",
            effective_advertised_tcp_port=18899,
        )

        primed = coordinator.prime_startup_snapshot()

        self.assertTrue(primed)
        self.assertTrue(coordinator.data.connected)
        self.assertEqual(coordinator.data.collector.remote_ip, "192.168.1.51")
        self.assertEqual(coordinator.data.values["collector_pn"], "V0000000000001")
        self.assertEqual(
            coordinator.data.collector.collector_server_endpoint,
            coordinator.data.values["collector_server_endpoint"],
        )
        self.assertEqual(coordinator.data.values["runtime_driver_state"], "driver_unbound")
        self.assertEqual(
            coordinator.data.values["runtime_detection_status"],
            "detecting_inverter",
        )
        self.assertEqual(coordinator.data.values["collector_poll_context"], "detection")
        self.assertEqual(coordinator.data.values["last_error"], "startup_detection_pending")
        collector_info = coordinator.collector_device_info()
        self.assertEqual(collector_info["model"], "EyeBond Collector")

    def test_driver_unbound_interlocks_writes_without_changing_user_mode(self) -> None:
        coordinator = object.__new__(self.coordinator_module.EybondLocalCoordinator)
        capability = types.SimpleNamespace(key="output_source_priority")
        inverter = types.SimpleNamespace(
            model_name="Bound inverter",
            serial_number="SERIAL-1",
            capabilities=(capability,),
        )
        coordinator.config_entry = types.SimpleNamespace(
            data={
                "control_mode": "full",
                "detection_confidence": "high",
            },
            options={"control_mode": "full"},
        )
        coordinator.data = self.RuntimeSnapshot(
            connected=True,
            inverter=inverter,
            values={"runtime_driver_state": "driver_unbound"},
        )
        coordinator._write_exposure_context = lambda: {
            "variant_key": "",
            "profile_source_scope": "builtin",
            "schema_source_scope": "builtin",
            "profile_name": "",
            "device_scoped_overlay_active": False,
            "selected_control_keys": None,
        }

        self.assertEqual(coordinator.control_mode, "full")
        self.assertFalse(coordinator.controls_enabled)
        self.assertEqual(coordinator.controls_reason, "driver_unbound")
        self.assertFalse(coordinator.can_expose_capability(capability))

        coordinator.data.values["runtime_driver_state"] = "driver_bound"

        self.assertEqual(coordinator.control_mode, "full")
        self.assertTrue(coordinator.controls_enabled)
        self.assertTrue(coordinator.can_expose_capability(capability))

        coordinator.data.values["runtime_driver_state"] = "collector_offline"

        self.assertTrue(coordinator.controls_enabled)
        self.assertTrue(coordinator.can_expose_capability(capability))

    def test_prime_startup_snapshot_includes_persisted_inverter_capabilities(self) -> None:
        capability = types.SimpleNamespace(key="output_source_priority")
        group = types.SimpleNamespace(key="power_source")
        profile = types.SimpleNamespace(
            driver_key="pi30",
            protocol_family="pi30",
            groups=(group,),
            capabilities=(capability,),
            presets=(),
        )
        driver = types.SimpleNamespace(
            key="pi30",
            probe_targets=(
                self.coordinator_module.ProbeTarget(
                    devcode=0x0994,
                    collector_addr=0x01,
                    device_addr=0,
                ),
            ),
        )
        coordinator = object.__new__(self.coordinator_module.EybondLocalCoordinator)
        coordinator.config_entry = types.SimpleNamespace(
            entry_id="entry-1",
            data={
                "connection_type": "eybond",
                "connection_mode": "manual",
                "collector_operation_mode": "home_assistant_only",
                "control_mode": "auto",
                "detection_confidence": "high",
                "detected_model": "PI30 3500",
                "detected_serial": "55355535553555",
                "driver_hint": "pi30",
            },
            options={
                "effective_metadata_snapshot": {
                    "effective_owner_key": "pi30",
                    "variant_key": "default",
                    "profile_name": "pi30_ascii/models/smartess_0925_compat.json",
                    "register_schema_name": "pi30_ascii/models/smartess_0925_compat.json",
                    "confidence": "high",
                }
            },
        )
        coordinator.data = self.RuntimeSnapshot(values={})
        coordinator._connection_spec = types.SimpleNamespace(
            collector_ip="192.168.1.51",
            collector_pn="V0000000000001",
            collector_cloud_family="smartess_at",
            server_ip="192.168.1.50",
            tcp_port=18899,
            effective_advertised_server_ip="192.168.1.50",
            effective_advertised_tcp_port=18899,
        )

        with (
            patch.object(self.coordinator_startup_module, "get_driver", return_value=driver),
            patch.object(
                self.coordinator_startup_module,
                "load_driver_profile",
                return_value=profile,
            ),
        ):
            primed = coordinator.prime_startup_snapshot()

        self.assertTrue(primed)
        self.assertIsNotNone(coordinator.data.inverter)
        self.assertEqual(coordinator.data.inverter.driver_key, "pi30")
        self.assertEqual(coordinator.data.inverter.model_name, "PI30 3500")
        self.assertEqual(coordinator.data.inverter.serial_number, "55355535553555")
        self.assertEqual(
            coordinator.data.inverter.profile_name,
            "pi30_ascii/models/smartess_0925_compat.json",
        )
        self.assertEqual(coordinator.data.inverter.capabilities, (capability,))
        self.assertEqual(coordinator.data.inverter.capability_groups, (group,))

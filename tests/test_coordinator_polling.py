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
    def test_prime_startup_restores_high_confidence_auto_model_from_catalog(self) -> None:
        capability = types.SimpleNamespace(key="output_source_priority")
        group = types.SimpleNamespace(key="power_source")
        profile = types.SimpleNamespace(
            driver_key="modbus_smg",
            protocol_family="modbus_smg",
            groups=(group,),
            capabilities=(capability,),
            presets=(),
        )
        register_schema = types.SimpleNamespace(driver_key="modbus_smg")
        surface = types.SimpleNamespace(
            driver_key="modbus_smg",
            variant_key="anenji_anj_11kw_48v_wifi_p",
            profile_name="modbus_smg/models/anenji_anj_11kw_48v_wifi_p.json",
            register_schema_name="modbus_smg/models/anenji_anj_11kw_48v_wifi_p.json",
        )
        driver = types.SimpleNamespace(
            key="modbus_smg",
            probe_targets=(
                self.coordinator_module.ProbeTarget(
                    devcode=1,
                    collector_addr=255,
                    device_addr=1,
                ),
            ),
        )
        coordinator = object.__new__(self.coordinator_module.EybondLocalCoordinator)
        coordinator.config_entry = types.SimpleNamespace(
            entry_id="entry-1",
            data={
                "connection_type": "eybond",
                "control_mode": "auto",
                "detected_model": "Anenji ANJ-11KW-48V-WIFI-P",
                "detected_serial": "92B32500004401",
                "detection_confidence": "high",
                "driver_hint": "auto",
            },
            options={},
        )
        coordinator.data = self.RuntimeSnapshot(values={})
        coordinator._connection_spec = types.SimpleNamespace(
            collector_ip="192.0.2.11",
            collector_pn="E5000SYNTHETIC5507",
            collector_cloud_family="smartess_at",
            server_ip="192.0.2.56",
            tcp_port=8899,
            effective_advertised_server_ip="192.0.2.56",
            effective_advertised_tcp_port=8899,
        )

        with (
            patch.object(
                self.coordinator_startup_module,
                "resolve_unique_persisted_model_surface",
                return_value=(types.SimpleNamespace(), surface),
            ),
            patch.object(self.coordinator_startup_module, "get_driver", return_value=driver),
            patch.object(
                self.coordinator_startup_module,
                "load_driver_profile",
                return_value=profile,
            ),
            patch.object(
                self.coordinator_startup_module,
                "load_register_schema",
                return_value=register_schema,
            ),
        ):
            primed = coordinator.prime_startup_snapshot()

        self.assertTrue(primed)
        inverter = coordinator.data.inverter
        self.assertIsNotNone(inverter)
        self.assertEqual(inverter.driver_key, "modbus_smg")
        self.assertEqual(inverter.variant_key, "anenji_anj_11kw_48v_wifi_p")
        self.assertEqual(inverter.capabilities, (capability,))
        self.assertEqual(
            inverter.details["runtime_detection_status"],
            "persisted_model_probe_degraded",
        )
        self.assertEqual(
            inverter.details["identity_source"], "persisted_detected_model"
        )
        self.assertEqual(
            coordinator.data.values["runtime_driver_state"], "driver_bound"
        )
        self.assertEqual(
            coordinator.data.values["effective_profile_name"],
            "modbus_smg/models/anenji_anj_11kw_48v_wifi_p.json",
        )
        self.assertEqual(
            coordinator.data.values["effective_variant_key"],
            "anenji_anj_11kw_48v_wifi_p",
        )
        self.assertEqual(
            coordinator.data.values["effective_inverter_capability_count"], 1
        )

    def test_prime_startup_catalog_fallback_requires_high_confidence(self) -> None:
        coordinator = object.__new__(self.coordinator_module.EybondLocalCoordinator)
        coordinator.config_entry = types.SimpleNamespace(
            data={
                "detected_model": "Anenji ANJ-11KW-48V-WIFI-P",
                "detection_confidence": "medium",
                "driver_hint": "auto",
            },
            options={},
        )

        with patch.object(
            self.coordinator_startup_module, "resolve_unique_persisted_model_surface"
        ) as resolver:
            inverter = coordinator._prime_startup_inverter_from_persisted_metadata()

        self.assertIsNone(inverter)
        resolver.assert_not_called()

    def test_prime_startup_restores_exact_catalog_telemetry_and_controls(self) -> None:
        capability = types.SimpleNamespace(key="grid_charge_enable")
        profile = types.SimpleNamespace(
            driver_key="modbus_catalog",
            protocol_family="deye_3ph_high_80kw",
            groups=(),
            capabilities=(capability,),
            presets=(),
        )
        surface = types.SimpleNamespace(
            driver_key="modbus_catalog",
            variant_key="deye_3ph_high_80kw",
            profile_name="modbus_catalog/deye_3ph_high_80kw.json",
            register_schema_name="deye_3ph_high_80kw/base.json",
            read_only=False,
        )
        driver = types.SimpleNamespace(
            key="modbus_catalog",
            profile_name="",
            register_schema_name="",
            probe_targets=(
                self.coordinator_module.ProbeTarget(
                    devcode=1,
                    collector_addr=255,
                    device_addr=1,
                ),
            ),
        )
        register_schema = types.SimpleNamespace(driver_key="modbus_catalog")
        coordinator = object.__new__(self.coordinator_module.EybondLocalCoordinator)
        coordinator.config_entry = types.SimpleNamespace(
            data={
                "detected_model": "Deye-Compatible Three-Phase Hybrid 80 kW (Modbus)",
                "detected_serial": "",
                "detection_confidence": "high",
                "detected_driver": "modbus_catalog",
                "driver_hint": "auto",
            },
            options={},
        )

        with (
            patch.object(
                self.coordinator_startup_module,
                "resolve_unique_persisted_model_surface",
                return_value=(types.SimpleNamespace(), surface),
            ),
            patch.object(self.coordinator_startup_module, "get_driver", return_value=driver),
            patch.object(
                self.coordinator_startup_module,
                "load_register_schema",
                return_value=register_schema,
            ),
            patch.object(
                self.coordinator_startup_module,
                "load_driver_profile",
                return_value=profile,
            ) as profile_loader,
        ):
            inverter = coordinator._prime_startup_inverter_from_persisted_metadata()

        self.assertIsNotNone(inverter)
        self.assertEqual(inverter.driver_key, "modbus_catalog")
        self.assertEqual(inverter.variant_key, "deye_3ph_high_80kw")
        self.assertEqual(
            inverter.profile_name,
            "modbus_catalog/deye_3ph_high_80kw.json",
        )
        self.assertEqual(
            inverter.register_schema_name,
            "deye_3ph_high_80kw/base.json",
        )
        self.assertEqual(inverter.capabilities, (capability,))
        self.assertEqual(
            inverter.details["identity_source"],
            "persisted_detected_model",
        )
        profile_loader.assert_called_once_with(
            "modbus_catalog/deye_3ph_high_80kw.json"
        )

    def test_prime_startup_snapshot_adds_persisted_inverter_when_values_already_exist(self) -> None:
        capability = types.SimpleNamespace(key="output_source_priority")
        profile = types.SimpleNamespace(
            driver_key="pi30",
            protocol_family="pi30",
            groups=(),
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
        coordinator.data = self.RuntimeSnapshot(
            values={"proxy_capture_status": "idle"},
            inverter=None,
        )
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
        self.assertEqual(coordinator.data.values["proxy_capture_status"], "idle")
        self.assertIsNotNone(coordinator.data.inverter)
        self.assertEqual(coordinator.data.inverter.capabilities, (capability,))

    def test_collector_onboarding_values_keep_cloud_metadata_wire_neutral(self) -> None:
        coordinator = object.__new__(self.coordinator_module.EybondLocalCoordinator)
        coordinator.config_entry = types.SimpleNamespace(
            entry_id="entry-1",
            data={
                "collector_cloud_family": "smartess_at",
                "driver_hint": "auto",
            },
            options={},
        )
        coordinator.data = self.RuntimeSnapshot(values={})
        coordinator._connection_spec = types.SimpleNamespace(
            collector_cloud_family="smartess_at",
            collector_configured_session_protocol="at_text",
            collector_identity_strategy="at_dtupn",
        )
        coordinator._runtime = types.SimpleNamespace(
            collector_server_endpoint_rollback_target="",
            listener_diagnostics=lambda: {
                "collector_configured_session_protocol": "",
                "collector_callback_identity_strategy": "",
            },
        )
        coordinator._remembered_collector_server_endpoint = ""

        values = coordinator._collector_transport_profile_runtime_values()

        self.assertEqual(values["collector_resolved_cloud_family"], "smartess_at")
        self.assertEqual(values["collector_resolved_session_protocol"], "")
        self.assertEqual(values["collector_resolved_identity_strategy"], "")
        self.assertEqual(values["collector_connection_session_protocol"], "at_text")
        self.assertEqual(values["collector_connection_identity_strategy"], "at_dtupn")
        self.assertEqual(values["collector_runtime_link_session_protocol"], "")
        self.assertEqual(values["collector_runtime_link_identity_strategy"], "")

    def test_live_framed_session_inventory_overrides_at_text_profile(self) -> None:
        coordinator = object.__new__(self.coordinator_module.EybondLocalCoordinator)
        coordinator.config_entry = types.SimpleNamespace(
            entry_id="entry-1",
            data={
                "collector_cloud_family": "smartess_at",
                "collector_virtual_bridge": True,
                "collector_bridge_kind": "esp-collector",
                "collector_session_protocol": "eybond_framed",
                "driver_hint": "pi30",
            },
            options={},
        )
        coordinator.data = self.RuntimeSnapshot(values={})
        coordinator._runtime = types.SimpleNamespace(
            listener_diagnostics=lambda: {
                # This configured value is not the observation; the live
                # inventory below is. A framed ESP bridge must be allowed to
                # override an at_text cloud-family default.
                "collector_configured_session_protocol": "eybond_framed",
                "collector_callback_identity_strategy": "framed_heartbeat_then_fc2_pn",
                "collector_callback_session_inventory": [
                    {
                        "state": "routed_framed",
                        "protocol_shape": "eybond_framed_or_binary",
                        "collector_identity_masked": "V001…1016",
                    }
                ],
            },
        )
        coordinator._remembered_collector_server_endpoint = ""

        profile = coordinator.collector_transport_profile

        self.assertEqual(profile.cloud_family, "smartess_at")
        self.assertEqual(profile.runtime_owner_key, "pi30")
        self.assertEqual(profile.session_protocol, "eybond_framed")
        self.assertEqual(profile.identity_strategy, "framed_heartbeat_then_fc2_pn")

    def test_virtual_bridge_at_management_session_is_not_collector_kind_framed_override(self) -> None:
        coordinator = object.__new__(self.coordinator_module.EybondLocalCoordinator)
        coordinator.config_entry = types.SimpleNamespace(
            entry_id="entry-1",
            data={
                "collector_cloud_family": "smartess_at",
                "collector_virtual_bridge": True,
                "collector_bridge_kind": "esp-collector",
                "collector_session_protocol": "eybond_framed",
                "driver_hint": "auto",
            },
            options={},
        )
        coordinator.data = self.RuntimeSnapshot(values={})
        coordinator._runtime = types.SimpleNamespace(
            listener_diagnostics=lambda: {
                "collector_configured_session_protocol": "eybond_framed",
                "collector_callback_observed_session_protocol": "at_text",
                "collector_callback_session_inventory": [
                    {
                        "state": "routed_at_text",
                        "protocol_shape": "eybond_framed_or_binary",
                        "collector_identity_masked": "V001…4022",
                    }
                ],
            },
        )
        coordinator._remembered_collector_server_endpoint = ""

        profile = coordinator.collector_transport_profile

        self.assertEqual(profile.cloud_family, "smartess_at")
        # collector_transport_profile is a legacy callback-profile hint, not
        # inverter payload authority. It must not hardcode "virtual bridge =>
        # framed"; payload routing is handled by SessionHandle adapters.
        self.assertEqual(profile.session_protocol, "at_text")
        self.assertEqual(profile.identity_strategy, "at_dtupn")
        self.assertEqual(profile.raw_passthrough_frame_format, "transparent")

    def test_live_session_inventory_overrides_configured_callback_protocol(self) -> None:
        coordinator = object.__new__(self.coordinator_module.EybondLocalCoordinator)
        coordinator.config_entry = types.SimpleNamespace(
            entry_id="entry-1",
            data={
                "collector_cloud_family": "smartess_at",
                "collector_session_protocol": "eybond_framed",
                "driver_hint": "auto",
            },
            options={},
        )
        coordinator.data = self.RuntimeSnapshot(values={})
        coordinator._runtime = types.SimpleNamespace(
            listener_diagnostics=lambda: {
                # This is the link manager's configured protocol, not an
                # observation. It must not mask the live byte-shape inventory.
                "collector_configured_session_protocol": "eybond_framed",
                "collector_callback_identity_strategy": "framed_heartbeat_then_fc2_pn",
                "collector_callback_session_inventory": [
                    {
                        "state": "pending",
                        "protocol_shape": "at_text",
                        "collector_identity_masked": "V001…1016",
                    }
                ],
            },
        )
        coordinator._remembered_collector_server_endpoint = ""

        profile = coordinator.collector_transport_profile

        self.assertEqual(profile.cloud_family, "smartess_at")
        self.assertEqual(profile.session_protocol, "at_text")
        self.assertEqual(profile.identity_strategy, "at_dtupn")

    def test_global_session_inventory_does_not_override_entry_with_pn(self) -> None:
        coordinator = object.__new__(self.coordinator_module.EybondLocalCoordinator)
        coordinator.config_entry = types.SimpleNamespace(
            entry_id="entry-1",
            data={
                "collector_cloud_family": "smartess_at",
                "collector_pn": "V001107SYN82291016",
                "driver_hint": "auto",
            },
            options={},
        )
        coordinator.data = self.RuntimeSnapshot(values={})
        coordinator._runtime = types.SimpleNamespace(
            listener_diagnostics=lambda: {
                "collector_configured_session_protocol": "at_text",
                "collector_callback_observed_session_protocol": "",
                "collector_callback_session_inventory": [
                    {
                        "state": "routed_framed",
                        "protocol_shape": "eybond_framed_or_binary",
                        "collector_identity_masked": "V000…7777",
                    }
                ],
            },
        )
        coordinator._remembered_collector_server_endpoint = ""

        profile = coordinator.collector_transport_profile

        self.assertEqual(profile.session_protocol, "")
        self.assertEqual(profile.identity_strategy, "")

    def test_owned_observed_session_protocol_overrides_entry_with_pn(self) -> None:
        coordinator = object.__new__(self.coordinator_module.EybondLocalCoordinator)
        coordinator.config_entry = types.SimpleNamespace(
            entry_id="entry-1",
            data={
                "collector_cloud_family": "smartess_at",
                "collector_pn": "V001107SYN82291016",
                "driver_hint": "auto",
            },
            options={},
        )
        coordinator.data = self.RuntimeSnapshot(values={})
        coordinator._runtime = types.SimpleNamespace(
            listener_diagnostics=lambda: {
                "collector_configured_session_protocol": "at_text",
                "collector_callback_observed_session_protocol": "eybond_framed",
                "collector_callback_session_inventory": [
                    {
                        "state": "routed_framed",
                        "protocol_shape": "eybond_framed_or_binary",
                        "collector_identity_masked": "V001…1016",
                    }
                ],
            },
        )
        coordinator._remembered_collector_server_endpoint = ""

        profile = coordinator.collector_transport_profile

        self.assertEqual(profile.session_protocol, "eybond_framed")
        self.assertEqual(profile.identity_strategy, "framed_heartbeat_then_fc2_pn")

    def test_update_reconciles_transport_after_runtime_endpoint_discovery(self) -> None:
        async def _run() -> None:
            coordinator = object.__new__(self.coordinator_module.EybondLocalCoordinator)
            refresh_count = 0
            reconcile_calls: list[tuple[str, str, str]] = []

            async def _async_refresh(*, poll_interval: float | None = None):
                nonlocal refresh_count
                del poll_interval
                refresh_count += 1
                return self.RuntimeSnapshot(
                    connected=True,
                    values={
                        "collector_server_endpoint": "dtu_ess.eybond.com,18899,TCP",
                        "refresh_count": refresh_count,
                    },
                )

            async def _async_reconcile_collector_session_profile(
                *,
                collector_session_protocol: str,
                collector_identity_strategy: str,
                collector_raw_passthrough_bootstrap: str = "",
                collector_raw_passthrough_frame_format: str = "",
                collector_raw_passthrough_min_interval_ms: int = 0,
                reason: str,
            ) -> bool:
                del (
                    collector_raw_passthrough_bootstrap,
                    collector_raw_passthrough_frame_format,
                    collector_raw_passthrough_min_interval_ms,
                )
                reconcile_calls.append(
                    (collector_session_protocol, collector_identity_strategy, reason)
                )
                return (
                    reason == "post_refresh_profile_discovery"
                    and collector_session_protocol == "at_text"
                    and collector_identity_strategy == "at_dtupn"
                )

            coordinator.config_entry = types.SimpleNamespace(
                entry_id="entry-1",
                data={
                    "driver_hint": "auto",
                    "poll_interval": 10,
                },
                options={},
                title="Collector PN A0000000000001",
            )
            coordinator.hass = types.SimpleNamespace()
            coordinator.data = self.RuntimeSnapshot()
            coordinator._runtime = types.SimpleNamespace(
                async_refresh=_async_refresh,
                async_reconcile_collector_session_profile=(
                    _async_reconcile_collector_session_profile
                ),
                listener_diagnostics=lambda: {
                    "collector_configured_session_protocol": "",
                    "collector_callback_identity_strategy": "",
                },
            )
            coordinator._remembered_collector_server_endpoint = ""
            coordinator._device_overlay_merge_status = ""
            coordinator._tooling_values = {}
            coordinator._async_reconcile_network = AsyncMock(return_value=False)
            coordinator._async_reconcile_proxy_capture_session = AsyncMock(
                side_effect=lambda snapshot: snapshot
            )
            coordinator._async_reconcile_shadow_learning_session = AsyncMock(
                side_effect=lambda snapshot: snapshot
            )
            coordinator._async_restore_collector_original_endpoint_from_registry = AsyncMock()
            coordinator._async_remember_collector_server_endpoint = AsyncMock()
            coordinator._async_remember_runtime_identity = AsyncMock()
            coordinator._sync_collector_capability_profile = lambda: None
            coordinator._configure_reverse_discovery_mode = lambda: None
            coordinator._async_warm_effective_metadata_cache = AsyncMock()
            coordinator._async_reconcile_managed_collector_endpoint = AsyncMock()
            coordinator._write_exposure_context = lambda: {
                "variant_key": "",
                "profile_name": "",
                "profile_source_scope": "",
                "schema_source_scope": "",
                "device_scoped_overlay_active": False,
                "device_scoped_overlay_scope": "",
                "selected_control_keys": None,
                "effective_capabilities_experimental": False,
            }
            coordinator._support_workflow_values = lambda _snapshot: {}
            coordinator._collector_onboarding_values = lambda _snapshot: {}
            coordinator._proxy_capture_values = AsyncMock(return_value={})
            coordinator._prune_collector_values_for_connection = lambda _snapshot: None
            coordinator.async_sync_device_registry = lambda _snapshot: None

            with patch.object(
                self.coordinator_module.EybondLocalCoordinator,
                "collector_cloud_profile_key",
                new_callable=PropertyMock,
                return_value="",
            ), patch.object(
                self.coordinator_module.EybondLocalCoordinator,
                "collector_cloud_profile_label",
                new_callable=PropertyMock,
                return_value="",
            ), patch.object(
                self.coordinator_module.EybondLocalCoordinator,
                "collector_cloud_profile_source",
                new_callable=PropertyMock,
                return_value="",
            ), patch.object(
                self.coordinator_module.EybondLocalCoordinator,
                "collector_cloud_profile_confidence",
                new_callable=PropertyMock,
                return_value="",
            ):
                snapshot = await coordinator._async_update_data_with_runtime_lock()

            self.assertEqual(refresh_count, 1)
            self.assertEqual(reconcile_calls, [])
            self.assertEqual(snapshot.values["collector_cloud_family"], "smartess_at")
            self.assertEqual(snapshot.values["refresh_count"], 1)

        asyncio.run(_run())

    def test_refresh_before_support_export_updates_snapshot_best_effort(self) -> None:
        async def _run() -> None:
            coordinator = object.__new__(self.coordinator_module.EybondLocalCoordinator)
            coordinator.config_entry = types.SimpleNamespace(entry_id="entry-1")
            refreshed = self.RuntimeSnapshot(values={"collector_resolved_session_protocol": "at_text"})
            coordinator.data = self.RuntimeSnapshot(values={})
            coordinator._async_update_data = AsyncMock(return_value=refreshed)

            await coordinator._async_refresh_before_support_export()

            self.assertIs(coordinator.data, refreshed)

        asyncio.run(_run())

    def test_refresh_before_support_export_is_fail_open(self) -> None:
        async def _run() -> None:
            coordinator = object.__new__(self.coordinator_module.EybondLocalCoordinator)
            coordinator.config_entry = types.SimpleNamespace(entry_id="entry-1")
            original = self.RuntimeSnapshot(values={"existing": True})
            coordinator.data = original
            coordinator._async_update_data = AsyncMock(side_effect=RuntimeError("boom"))

            await coordinator._async_refresh_before_support_export()

            self.assertIs(coordinator.data, original)

        asyncio.run(_run())

    def test_collector_original_endpoint_values_include_registry_summary(self) -> None:
        from custom_components.eybond_local.support.collector_registry import (
            remember_collector_original_endpoint,
        )

        with tempfile.TemporaryDirectory() as tmp:
            remember_collector_original_endpoint(
                config_dir=Path(tmp),
                collector_pn="PN12345",
                original_endpoint_raw="dtu_ess.eybond.com,18899,TCP",
                cloud_profile_key="smartess_at",
                source="test_registry",
                observed_at="2026-06-22T10:00:00+00:00",
                last_seen_ip="192.168.2.209",
            )
            coordinator = object.__new__(self.coordinator_module.EybondLocalCoordinator)
            coordinator.hass = types.SimpleNamespace(
                config=types.SimpleNamespace(path=lambda: tmp),
            )
            coordinator.config_entry = types.SimpleNamespace(
                data={"collector_pn": "PN12345"},
                options={},
            )
            coordinator.data = self.RuntimeSnapshot(values={})
            coordinator._remembered_collector_server_endpoint = ""

            values = coordinator._collector_original_endpoint_runtime_values(
                include_registry=True
            )

        self.assertEqual(values["collector_registry_record_status"], "found")
        self.assertTrue(values["collector_registry_record_pn_known"])
        self.assertEqual(
            values["collector_registry_original_endpoint"],
            "dtu_ess.eybond.com,18899,TCP",
        )
        self.assertEqual(values["collector_registry_cloud_profile_key"], "smartess_at")
        self.assertEqual(values["collector_registry_source"], "test_registry")
        self.assertEqual(values["collector_registry_last_seen_ip"], "192.168.2.209")

    def test_integration_build_runtime_values_read_embedded_build_info(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            package_dir = Path(tmp)
            (package_dir / "manifest.json").write_text(
                '{"version": "0.2.0-test"}',
                encoding="utf-8",
            )
            (package_dir / "BUILD_INFO.txt").write_text(
                "eybond_local build\n"
                "manifest_version: 0.2.0-test\n"
                "git_describe:     v0.2.0-test-1-gabcdef0\n"
                "git_commit:       abcdef0\n"
                "commit_date:      2026-06-23\n"
                "built_at:         20260623T194735Z\n",
                encoding="utf-8",
            )

            with patch.object(
                self.coordinator_tooling_projection_module,
                "_package_dir",
                return_value=package_dir,
            ):
                values = self.coordinator_module._integration_build_runtime_values()

        self.assertEqual(values["integration_manifest_version"], "0.2.0-test")
        self.assertTrue(values["integration_build_info_present"])
        self.assertEqual(
            values["integration_build_git_describe"],
            "v0.2.0-test-1-gabcdef0",
        )
        self.assertEqual(values["integration_build_git_commit"], "abcdef0")
        self.assertEqual(values["integration_build_commit_date"], "2026-06-23")
        self.assertEqual(values["integration_build_built_at"], "20260623T194735Z")

    def test_integration_build_runtime_values_read_real_manifest(self) -> None:
        package_dir = self.coordinator_tooling_projection_module._package_dir()
        manifest_path = package_dir / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

        values = self.coordinator_module._integration_build_runtime_values()

        self.assertEqual(package_dir.name, "eybond_local")
        self.assertEqual(
            Path(values["integration_package_dir"]),
            package_dir,
        )
        self.assertEqual(
            values["integration_manifest_version"],
            manifest["version"],
        )

    def test_build_diagnostics_report_loaded_backup_path_not_expected_domain_path(self) -> None:
        """A renamed backup remains visible as the actual source of loaded code."""
        with tempfile.TemporaryDirectory() as tmp:
            package_dir = Path(tmp) / "custom_components" / "eybond_local_backup"
            module_path = package_dir / "runtime" / "coordinator" / "tooling_projection.py"
            with patch.object(self.coordinator_tooling_projection_module, "__file__", str(module_path)):
                values = self.coordinator_module._integration_build_runtime_values()
        self.assertEqual(Path(values["integration_package_dir"]), package_dir.resolve())
        self.assertFalse(values["integration_build_info_present"])

    def test_bind_apply_persists_inbound_integration_managed(self) -> None:
        # Item 2: a successful bind write makes the entry inbound +
        # integration_managed and records write provenance.
        async def _run() -> None:
            coordinator = object.__new__(self.coordinator_module.EybondLocalCoordinator)
            coordinator.config_entry = types.SimpleNamespace(
                entry_id="entry-1",
                data={"control_mode": "full"},
                options={"control_mode": "full"},
            )
            coordinator.data = self.RuntimeSnapshot(
                connected=True,
                values={"collector_server_endpoint": "47.91.67.66,18899,TCP"},
            )
            coordinator._connection_spec = types.SimpleNamespace(
                effective_advertised_server_ip="192.168.1.50",
            )

            async def _async_set_collector_server_endpoint(endpoint, *, apply_changes=True):
                return {"readback_endpoint": endpoint, "status": "applied"}

            def _async_update_entry(entry, **kwargs):
                if "data" in kwargs:
                    entry.data = dict(kwargs["data"])

            coordinator._runtime = types.SimpleNamespace(
                async_set_collector_server_endpoint=_async_set_collector_server_endpoint,
                collector_server_endpoint_rollback_target="47.91.67.66,18899,TCP",
            )
            coordinator._async_prepare_home_assistant_callback_listener = AsyncMock()
            coordinator.hass = types.SimpleNamespace(
                config_entries=types.SimpleNamespace(async_update_entry=_async_update_entry)
            )

            with patch.object(
                self.coordinator_module.EybondLocalCoordinator,
                "proxy_capture_overview",
                new_callable=PropertyMock,
                return_value=types.SimpleNamespace(status="ready"),
            ):
                await coordinator.async_bind_collector_to_home_assistant(
                    confirm_redirect=True,
                )

            data = coordinator.config_entry.data
            # Batch 8: a bind records the endpoint-write FACTS only. The
            # connection strategy changes exclusively through the verified
            # transition authority (a bind is not a reconnect proof).
            self.assertNotIn("connection_strategy", data)
            self.assertEqual(data.get("endpoint_control_policy"), "integration_managed")
            self.assertEqual(data.get("endpoint_written_value"), "192.168.1.50,18899,TCP")
            self.assertIn("endpoint_written_at", data)

        asyncio.run(_run())

    def test_bind_already_bound_does_not_claim_endpoint_ownership(self) -> None:
        # Item 1/2: already pointing at HA, no write -> inbound, but NOT
        # integration_managed and no write provenance.
        async def _run() -> None:
            coordinator = object.__new__(self.coordinator_module.EybondLocalCoordinator)
            coordinator.config_entry = types.SimpleNamespace(
                entry_id="entry-1",
                data={"control_mode": "full"},
                options={"control_mode": "full"},
            )
            coordinator.data = self.RuntimeSnapshot(
                connected=True,
                values={"collector_server_endpoint": "192.168.1.50,18899,TCP"},
            )
            coordinator._connection_spec = types.SimpleNamespace(
                effective_advertised_server_ip="192.168.1.50",
            )

            def _async_update_entry(entry, **kwargs):
                if "data" in kwargs:
                    entry.data = dict(kwargs["data"])

            coordinator._runtime = types.SimpleNamespace(
                collector_server_endpoint_rollback_target="47.91.67.66,18899,TCP",
            )
            coordinator._async_prepare_home_assistant_callback_listener = AsyncMock()
            coordinator.hass = types.SimpleNamespace(
                config_entries=types.SimpleNamespace(async_update_entry=_async_update_entry)
            )

            with patch.object(
                self.coordinator_module.EybondLocalCoordinator,
                "proxy_capture_overview",
                new_callable=PropertyMock,
                return_value=types.SimpleNamespace(status="ready"),
            ):
                result = await coordinator.async_bind_collector_to_home_assistant(
                    confirm_redirect=True,
                )

            self.assertEqual(result["status"], "already_bound")
            data = coordinator.config_entry.data
            # Nothing was written, so NOTHING was earned: no axis of any kind.
            self.assertNotIn("connection_strategy", data)
            self.assertNotIn("endpoint_control_policy", data)
            self.assertNotIn("endpoint_written_value", data)

        asyncio.run(_run())

    def test_rollback_apply_persists_callback_external_and_clears_written(self) -> None:
        # Item 2: a successful rollback hands control back -> callback_on_demand
        # + external, with write provenance cleared.
        async def _run() -> None:
            coordinator = object.__new__(self.coordinator_module.EybondLocalCoordinator)
            coordinator.config_entry = types.SimpleNamespace(
                entry_id="entry-1",
                data={
                    "control_mode": "full",
                    "connection_strategy": "inbound",
                    "endpoint_control_policy": "integration_managed",
                    "endpoint_written_value": "192.168.1.50,18899,TCP",
                    "endpoint_written_at": "2026-01-01T00:00:00+00:00",
                },
                options={"control_mode": "full"},
            )
            coordinator.data = self.RuntimeSnapshot(
                connected=True,
                values={"collector_server_endpoint": "192.168.1.50,18899,TCP"},
            )
            coordinator._connection_spec = types.SimpleNamespace(
                effective_advertised_server_ip="192.168.1.50",
            )
            coordinator._remembered_collector_server_endpoint = "47.91.67.66,18899,TCP"

            async def _async_set_collector_server_endpoint(endpoint, *, apply_changes=True):
                return {"readback_endpoint": endpoint, "status": "applied"}

            def _async_update_entry(entry, **kwargs):
                if "data" in kwargs:
                    entry.data = dict(kwargs["data"])

            coordinator._runtime = types.SimpleNamespace(
                async_set_collector_server_endpoint=_async_set_collector_server_endpoint,
                collector_server_endpoint_rollback_target="47.91.67.66,18899,TCP",
            )
            coordinator.hass = types.SimpleNamespace(
                config_entries=types.SimpleNamespace(async_update_entry=_async_update_entry)
            )

            with patch.object(
                self.coordinator_module.EybondLocalCoordinator,
                "proxy_capture_overview",
                new_callable=PropertyMock,
                return_value=types.SimpleNamespace(status="ready"),
            ):
                await coordinator.async_rollback_collector_server_endpoint(
                    apply_changes=True,
                    confirm_redirect=True,
                )

            data = coordinator.config_entry.data
            # Batch 8: the rollback records the restore FACT (external, cleared
            # provenance); the strategy stays what it was — only the verified
            # transition authority may change it, after a callback proof.
            self.assertEqual(data.get("connection_strategy"), "inbound")
            self.assertEqual(data.get("endpoint_control_policy"), "external")
            self.assertNotIn("endpoint_written_value", data)
            self.assertNotIn("endpoint_written_at", data)

        asyncio.run(_run())

    def test_rollback_staged_does_not_change_durable_axes(self) -> None:
        # Item 2: apply_changes=False stages nothing on the collector, so it must
        # not change the durable axes.
        async def _run() -> None:
            coordinator = object.__new__(self.coordinator_module.EybondLocalCoordinator)
            coordinator.config_entry = types.SimpleNamespace(
                entry_id="entry-1",
                data={
                    "control_mode": "full",
                    "connection_strategy": "inbound",
                    "endpoint_control_policy": "integration_managed",
                    "endpoint_written_value": "192.168.1.50,18899,TCP",
                },
                options={"control_mode": "full"},
            )
            coordinator.data = self.RuntimeSnapshot(
                connected=True,
                values={"collector_server_endpoint": "192.168.1.50,18899,TCP"},
            )
            coordinator._connection_spec = types.SimpleNamespace(
                effective_advertised_server_ip="192.168.1.50",
            )
            coordinator._remembered_collector_server_endpoint = "47.91.67.66,18899,TCP"

            async def _async_set_collector_server_endpoint(endpoint, *, apply_changes=True):
                return {"requested_endpoint": endpoint, "status": "rollback_staged"}

            async def _async_request_refresh() -> None:
                return None

            def _async_update_entry(entry, **kwargs):
                if "data" in kwargs:
                    entry.data = dict(kwargs["data"])

            coordinator._runtime = types.SimpleNamespace(
                async_set_collector_server_endpoint=_async_set_collector_server_endpoint,
                collector_server_endpoint_rollback_target="47.91.67.66,18899,TCP",
            )
            coordinator.async_request_refresh = _async_request_refresh
            coordinator.hass = types.SimpleNamespace(
                config_entries=types.SimpleNamespace(async_update_entry=_async_update_entry)
            )

            with patch.object(
                self.coordinator_module.EybondLocalCoordinator,
                "proxy_capture_overview",
                new_callable=PropertyMock,
                return_value=types.SimpleNamespace(status="ready"),
            ):
                await coordinator.async_rollback_collector_server_endpoint(
                    apply_changes=False,
                    confirm_redirect=True,
                )

            data = coordinator.config_entry.data
            self.assertEqual(data.get("connection_strategy"), "inbound")
            self.assertEqual(data.get("endpoint_control_policy"), "integration_managed")
            self.assertEqual(data.get("endpoint_written_value"), "192.168.1.50,18899,TCP")

        asyncio.run(_run())

    def test_raw_collector_endpoint_stage_publishes_pending_override(self) -> None:
        async def _run() -> None:
            calls: list[tuple[str, bool]] = []
            refresh_calls: list[bool] = []

            async def _async_set_collector_server_endpoint(
                endpoint: str, *, apply_changes: bool = True
            ) -> dict[str, object]:
                calls.append((endpoint, apply_changes))
                return {"requested_endpoint": endpoint, "status": "staged"}

            async def _async_request_refresh() -> None:
                refresh_calls.append(True)

            coordinator = object.__new__(self.coordinator_module.EybondLocalCoordinator)
            coordinator.config_entry = types.SimpleNamespace(
                entry_id="cp2c-writer-guard",
                data={"control_mode": "full"},
                options={"control_mode": "full"},
            )
            coordinator.data = self.RuntimeSnapshot(
                connected=True,
                values={"collector_server_endpoint": "192.168.1.50,8899,TCP"},
            )
            coordinator._runtime = types.SimpleNamespace(
                async_set_collector_server_endpoint=_async_set_collector_server_endpoint,
            )
            coordinator._async_prepare_home_assistant_callback_listener = AsyncMock()
            coordinator.async_request_refresh = _async_request_refresh

            with patch.object(
                self.coordinator_module.EybondLocalCoordinator,
                "proxy_capture_overview",
                new_callable=PropertyMock,
                return_value=types.SimpleNamespace(status="ready"),
            ):
                await coordinator.async_set_raw_collector_server_endpoint(
                    endpoint="10.0.0.25,18899",
                    apply_changes=False,
                    confirm_redirect=True,
                )

            self.assertEqual(calls, [("10.0.0.25,18899", False)])
            self.assertEqual(refresh_calls, [True])
            self.assertEqual(
                coordinator.data.values["collector_callback_endpoint_pending"],
                "10.0.0.25,18899",
            )
            self.assertTrue(
                coordinator.data.values["collector_callback_endpoint_pending_apply_required"]
            )

        asyncio.run(_run())

    def test_raw_collector_endpoint_apply_clears_pending_override(self) -> None:
        async def _run() -> None:
            async def _async_set_collector_server_endpoint(
                endpoint: str, *, apply_changes: bool = True
            ) -> dict[str, object]:
                return {"requested_endpoint": endpoint, "status": "applied"}

            coordinator = object.__new__(self.coordinator_module.EybondLocalCoordinator)
            coordinator.config_entry = types.SimpleNamespace(
                entry_id="cp2c-writer-guard",
                data={"control_mode": "full"},
                options={"control_mode": "full"},
            )
            coordinator.data = self.RuntimeSnapshot(
                connected=True,
                values={
                    "collector_server_endpoint": "192.168.1.50,8899,TCP",
                    "collector_callback_endpoint_pending": "10.0.0.25,18899",
                    "collector_callback_endpoint_pending_apply_required": True,
                },
            )
            coordinator._runtime = types.SimpleNamespace(
                async_set_collector_server_endpoint=_async_set_collector_server_endpoint,
            )
            coordinator._async_prepare_home_assistant_callback_listener = AsyncMock()

            with patch.object(
                self.coordinator_module.EybondLocalCoordinator,
                "proxy_capture_overview",
                new_callable=PropertyMock,
                return_value=types.SimpleNamespace(status="ready"),
            ):
                await coordinator.async_set_raw_collector_server_endpoint(
                    endpoint="10.0.0.25,18899",
                    apply_changes=True,
                    confirm_redirect=True,
                )

            self.assertNotIn("collector_callback_endpoint_pending", coordinator.data.values)
            self.assertNotIn(
                "collector_callback_endpoint_pending_apply_required",
                coordinator.data.values,
            )

        asyncio.run(_run())

    def test_bind_collector_to_home_assistant_clears_pending_endpoint_override(self) -> None:
        async def _run() -> None:
            calls: list[tuple[str, bool]] = []

            async def _async_set_collector_server_endpoint(
                endpoint: str, *, apply_changes: bool = True
            ) -> dict[str, object]:
                calls.append((endpoint, apply_changes))
                return {"requested_endpoint": endpoint, "status": "applied"}

            coordinator = object.__new__(self.coordinator_module.EybondLocalCoordinator)
            coordinator.config_entry = types.SimpleNamespace(
                entry_id="cp2c-writer-guard",
                data={"control_mode": "full"},
                options={"control_mode": "full"},
            )
            coordinator.data = self.RuntimeSnapshot(
                connected=True,
                values={
                    "collector_server_endpoint": "47.91.67.66,18899,TCP",
                    "collector_callback_endpoint_pending": "10.0.0.25,18899",
                    "collector_callback_endpoint_pending_apply_required": True,
                },
            )
            coordinator._connection_spec = types.SimpleNamespace(
                effective_advertised_server_ip="192.168.1.50",
            )
            coordinator._runtime = types.SimpleNamespace(
                async_set_collector_server_endpoint=_async_set_collector_server_endpoint,
                collector_server_endpoint_rollback_target="47.91.67.66,18899,TCP",
            )
            coordinator._async_prepare_home_assistant_callback_listener = AsyncMock()

            with patch.object(
                self.coordinator_module.EybondLocalCoordinator,
                "proxy_capture_overview",
                new_callable=PropertyMock,
                return_value=types.SimpleNamespace(status="ready"),
            ):
                await coordinator.async_bind_collector_to_home_assistant(
                    confirm_redirect=True,
                )

            self.assertEqual(calls, [("192.168.1.50,18899,TCP", True)])
            self.assertNotIn("collector_callback_endpoint_pending", coordinator.data.values)
            self.assertNotIn(
                "collector_callback_endpoint_pending_apply_required",
                coordinator.data.values,
            )

        asyncio.run(_run())

    def test_rollback_collector_endpoint_stage_publishes_pending_override(self) -> None:
        async def _run() -> None:
            refresh_calls: list[bool] = []

            async def _async_set_collector_server_endpoint(
                endpoint: str, *, apply_changes: bool = True
            ) -> dict[str, object]:
                return {"requested_endpoint": endpoint, "status": "rollback_staged"}

            async def _async_request_refresh() -> None:
                refresh_calls.append(True)

            coordinator = object.__new__(self.coordinator_module.EybondLocalCoordinator)
            coordinator.config_entry = types.SimpleNamespace(
                entry_id="cp2c-writer-guard",
                data={"control_mode": "full"},
                options={"control_mode": "full"},
            )
            coordinator.data = self.RuntimeSnapshot(
                connected=True,
                values={"collector_server_endpoint": "192.168.1.50,18899,TCP"},
            )
            coordinator._connection_spec = types.SimpleNamespace(
                effective_advertised_server_ip="192.168.1.50",
            )
            coordinator._runtime = types.SimpleNamespace(
                async_set_collector_server_endpoint=_async_set_collector_server_endpoint,
                collector_server_endpoint_rollback_target="47.91.67.66,18899,TCP",
            )
            coordinator.async_request_refresh = _async_request_refresh

            with patch.object(
                self.coordinator_module.EybondLocalCoordinator,
                "proxy_capture_overview",
                new_callable=PropertyMock,
                return_value=types.SimpleNamespace(status="ready"),
            ):
                await coordinator.async_rollback_collector_server_endpoint(
                    apply_changes=False,
                    confirm_redirect=True,
                )

            self.assertEqual(refresh_calls, [True])
            self.assertEqual(
                coordinator.data.values["collector_callback_endpoint_pending"],
                "47.91.67.66,18899,TCP",
            )
            self.assertTrue(
                coordinator.data.values["collector_callback_endpoint_pending_apply_required"]
            )

        asyncio.run(_run())

    def test_async_set_control_mode_persists_mode_via_standard_entry_update(self) -> None:
        async def _run() -> None:
            coordinator = object.__new__(self.coordinator_module.EybondLocalCoordinator)
            coordinator.config_entry = types.SimpleNamespace(
                entry_id="entry-1",
                data={"control_mode": "auto"},
                options={"control_mode": "auto"},
            )
            calls: list[tuple[str, object]] = []

            def _async_update_entry(entry, **kwargs) -> None:
                calls.append(("update", dict(kwargs)))
                if "data" in kwargs:
                    entry.data = dict(kwargs["data"])
                if "options" in kwargs:
                    entry.options = dict(kwargs["options"])

            reloads: list[str] = []

            coordinator.hass = types.SimpleNamespace(
                config_entries=types.SimpleNamespace(
                    async_update_entry=_async_update_entry,
                    async_schedule_reload=reloads.append,
                )
            )

            result = await coordinator.async_set_control_mode("full")

            self.assertEqual(result, "full")
            self.assertEqual(coordinator.config_entry.data["control_mode"], "full")
            self.assertEqual(coordinator.config_entry.options["control_mode"], "full")
            self.assertEqual(calls, [("update", {"data": {"control_mode": "full"}, "options": {"control_mode": "full"}})])
            # The capability-entity surface depends on the mode, and platforms
            # materialize entities once at setup: the switch must reload.
            self.assertEqual(reloads, ["entry-1"])

            # A no-op mode change must not reload.
            result = await coordinator.async_set_control_mode("full")
            self.assertEqual(result, "full")
            self.assertEqual(reloads, ["entry-1"])

        asyncio.run(_run())

    def test_poll_recommended_interval_keeps_headroom_after_overrun(self) -> None:
        recommended = self.coordinator_module._poll_recommended_interval_seconds(
            current_interval=10,
            observed_duration=11.2,
        )

        self.assertEqual(recommended, 16)

    def test_poll_metrics_reports_overrun_without_auto_adjusting_interval(self) -> None:
        coordinator = object.__new__(self.coordinator_module.EybondLocalCoordinator)
        entry = types.SimpleNamespace(
            entry_id="entry-poll",
            options={"poll_interval": 10},
        )
        updates: list[dict[str, object]] = []
        notifications: list[dict[str, object]] = []

        def _async_update_entry(config_entry, **kwargs) -> None:
            updates.append(dict(kwargs))
            if "options" in kwargs:
                config_entry.options = dict(kwargs["options"])

        def _async_create(hass, body, *, title, notification_id) -> None:
            del hass
            notifications.append(
                {
                    "body": body,
                    "title": title,
                    "notification_id": notification_id,
                }
            )

        coordinator.config_entry = entry
        coordinator.hass = types.SimpleNamespace(
            config=types.SimpleNamespace(language="en"),
            config_entries=types.SimpleNamespace(async_update_entry=_async_update_entry),
        )
        coordinator._suppress_entry_reload_count = 0
        coordinator._poll_duration_ewma_seconds = 0.0
        coordinator._poll_duration_max_seconds = 0.0
        coordinator._poll_recent_durations_seconds = []
        coordinator._collector_poll_overrun_streak = 0
        coordinator._collector_poll_high_utilization_streak = 0
        coordinator._poll_last_notification_monotonic = 0.0
        self.coordinator_module.persistent_notification.async_create = _async_create

        async def _run() -> list[object]:
            snapshots = [
                self.RuntimeSnapshot(
                    values={
                        "collector_poll_duration_ms": 12000,
                        "runtime_driver_state": "driver_bound",
                    },
                    connected=True,
                    inverter=object(),
                )
                for _ in range(3)
            ]
            for snapshot in snapshots:
                coordinator._record_poll_cycle_metrics(
                    snapshot,
                    poll_interval_seconds=10,
                )
            return snapshots

        snapshots = asyncio.run(_run())

        self.assertEqual(entry.options["poll_interval"], 10)
        self.assertEqual(updates, [])
        self.assertEqual(len(notifications), 1)
        self.assertNotIn("collector_poll_interval_auto_adjusted", snapshots[-1].values)
        self.assertEqual(
            snapshots[-1].values["collector_poll_recommended_min_interval_seconds"],
            18,
        )

    def test_poll_metrics_can_use_full_coordinator_cycle_duration(self) -> None:
        coordinator = object.__new__(self.coordinator_module.EybondLocalCoordinator)
        coordinator._poll_duration_ewma_seconds = 0.0
        coordinator._poll_duration_max_seconds = 0.0
        coordinator._poll_recent_durations_seconds = []
        coordinator._collector_poll_overrun_streak = 0
        coordinator._collector_poll_high_utilization_streak = 0
        coordinator._poll_last_notification_monotonic = 0.0
        snapshot = self.RuntimeSnapshot(
            values={"collector_poll_duration_ms": 700}
        )

        coordinator._record_poll_cycle_metrics(
            snapshot,
            poll_interval_seconds=10,
            duration_seconds=5.2,
            start_interval_seconds=10.1,
        )

        self.assertEqual(snapshot.values["collector_driver_poll_duration_ms"], 700)
        self.assertEqual(snapshot.values["collector_poll_duration_ms"], 5200)
        self.assertEqual(snapshot.values["collector_poll_utilization_percent"], 52)
        self.assertEqual(snapshot.values["collector_poll_start_interval_ms"], 10100)
        self.assertEqual(snapshot.values["collector_poll_target_start_interval_seconds"], 10)

    def test_poll_metrics_reports_scheduler_next_interval_as_target(self) -> None:
        coordinator = object.__new__(self.coordinator_module.EybondLocalCoordinator)
        coordinator._poll_duration_ewma_seconds = 0.0
        coordinator._poll_duration_max_seconds = 0.0
        coordinator._poll_recent_durations_seconds = []
        coordinator._collector_poll_overrun_streak = 0
        coordinator._collector_poll_high_utilization_streak = 0
        coordinator._poll_last_notification_monotonic = 0.0
        coordinator.config_entry = types.SimpleNamespace(
            options={"poll_mode": "auto", "poll_interval": 10}
        )
        snapshot = self.RuntimeSnapshot(values={"collector_poll_duration_ms": 700})
        decision = self.coordinator_module.PollDecision(
            mode="auto",
            effective_interval=16,
            manual_interval=10,
            recommended_interval=16,
            utilization_percent=120,
            policy_min_interval=10,
            policy_max_interval=120,
            observed_duration=12,
            sample_count=1,
        )

        coordinator._record_poll_cycle_metrics(
            snapshot,
            poll_interval_seconds=10,
            duration_seconds=12.0,
            decision=decision,
        )

        self.assertEqual(snapshot.values["collector_poll_current_interval_seconds"], 10)
        self.assertEqual(snapshot.values["collector_poll_next_interval_seconds"], 16)
        self.assertEqual(snapshot.values["collector_poll_target_start_interval_seconds"], 16)

    def test_driver_unbound_manual_poll_suppresses_high_utilization_warning(self) -> None:
        coordinator = object.__new__(self.coordinator_module.EybondLocalCoordinator)
        entry = types.SimpleNamespace(
            entry_id="entry-poll",
            options={"poll_mode": "manual", "poll_interval": 10},
        )
        notifications: list[dict[str, object]] = []

        def _async_create(hass, body, *, title, notification_id) -> None:
            del hass
            notifications.append(
                {
                    "body": body,
                    "title": title,
                    "notification_id": notification_id,
                }
            )

        coordinator.config_entry = entry
        coordinator.hass = types.SimpleNamespace(
            config=types.SimpleNamespace(language="en"),
            config_entries=types.SimpleNamespace(async_update_entry=lambda *_args, **_kwargs: None),
        )
        coordinator._poll_duration_ewma_seconds = 0.0
        coordinator._poll_duration_max_seconds = 0.0
        coordinator._poll_recent_durations_seconds = []
        coordinator._collector_poll_overrun_streak = 0
        coordinator._collector_poll_high_utilization_streak = 0
        coordinator._poll_last_notification_monotonic = 0.0
        self.coordinator_module.persistent_notification.async_create = _async_create

        snapshot = self.RuntimeSnapshot(
            values={
                "collector_poll_duration_ms": 81533,
                "runtime_driver_state": "driver_unbound",
            },
            connected=True,
        )
        for _ in range(3):
            coordinator._record_poll_cycle_metrics(
                snapshot,
                poll_interval_seconds=10,
            )

        self.assertEqual(notifications, [])
        self.assertEqual(snapshot.values["collector_poll_context"], "detection")
        self.assertEqual(snapshot.values["collector_poll_utilization_percent"], 815)
        self.assertEqual(snapshot.values["collector_poll_high_utilization_streak"], 0)
        self.assertEqual(snapshot.values["collector_poll_overrun_streak"], 0)

    def test_driver_unbound_auto_uses_retry_interval_without_polluting_scheduler(self) -> None:
        coordinator = object.__new__(self.coordinator_module.EybondLocalCoordinator)
        coordinator.config_entry = types.SimpleNamespace(
            data={},
            options={"poll_mode": "auto", "poll_interval": 10},
        )
        coordinator._poll_scheduler_driver_key = "auto"
        coordinator._poll_non_runtime_retry_interval_seconds = 0
        coordinator._ensure_poll_scheduler()

        current_interval = coordinator._current_poll_cycle_interval_seconds()
        decision = coordinator._poll_scheduler.observe(81.533, success=False)
        next_interval = coordinator._next_poll_cycle_interval_seconds(
            current_interval=current_interval,
            duration_seconds=81.533,
            poll_context="detection",
            decision=decision,
        )
        snapshot = self.RuntimeSnapshot(
            values={
                "collector_poll_duration_ms": 81533,
                "runtime_driver_state": "driver_unbound",
            },
            connected=True,
        )
        coordinator._poll_duration_ewma_seconds = 0.0
        coordinator._poll_duration_max_seconds = 0.0
        coordinator._poll_recent_durations_seconds = []
        coordinator._collector_poll_overrun_streak = 0
        coordinator._collector_poll_high_utilization_streak = 0
        coordinator._poll_last_notification_monotonic = 0.0

        coordinator._record_poll_cycle_metrics(
            snapshot,
            poll_interval_seconds=current_interval,
            duration_seconds=81.533,
            decision=decision,
            runtime_driver_state="driver_unbound",
            poll_context="detection",
            next_interval_seconds=next_interval,
        )

        self.assertEqual(decision.effective_interval, 10)
        self.assertEqual(coordinator._poll_scheduler.current_interval(), 10)
        self.assertEqual(next_interval, 106)
        self.assertEqual(coordinator._current_poll_cycle_interval_seconds(), 106)
        self.assertEqual(snapshot.values["collector_poll_context"], "detection")
        self.assertEqual(snapshot.values["collector_poll_next_interval_seconds"], 106)
        self.assertEqual(snapshot.values["collector_poll_detection_retry_interval_seconds"], 106)
        self.assertEqual(snapshot.values["collector_poll_high_utilization_streak"], 0)

    def test_collector_offline_poll_reports_collector_context(self) -> None:
        coordinator = object.__new__(self.coordinator_module.EybondLocalCoordinator)
        coordinator.config_entry = types.SimpleNamespace(
            entry_id="entry-poll",
            options={"poll_mode": "manual", "poll_interval": 10},
        )
        coordinator._poll_duration_ewma_seconds = 0.0
        coordinator._poll_duration_max_seconds = 0.0
        coordinator._poll_recent_durations_seconds = []
        coordinator._collector_poll_overrun_streak = 0
        coordinator._collector_poll_high_utilization_streak = 0
        coordinator._poll_last_notification_monotonic = 0.0
        snapshot = self.RuntimeSnapshot(
            values={"runtime_driver_state": "collector_offline"},
            connected=False,
        )

        coordinator._record_poll_cycle_metrics(
            snapshot,
            poll_interval_seconds=10,
            duration_seconds=4.5,
        )

        self.assertEqual(snapshot.values["collector_poll_context"], "collector")
        self.assertEqual(snapshot.values["collector_poll_high_utilization_streak"], 0)
        self.assertEqual(snapshot.values["collector_poll_overrun_streak"], 0)

    def test_first_bound_cycle_after_unbound_does_not_train_auto_scheduler(self) -> None:
        async def _run() -> None:
            coordinator = object.__new__(self.coordinator_module.EybondLocalCoordinator)
            coordinator.config_entry = types.SimpleNamespace(
                entry_id="entry-poll",
                data={},
                options={"poll_mode": "auto", "poll_interval": 10},
            )
            coordinator.data = self.RuntimeSnapshot(
                values={"runtime_driver_state": "driver_unbound"},
                connected=True,
            )
            coordinator._diagnostic_active = False
            coordinator._runtime_operation_lock = asyncio.Lock()
            coordinator._poll_scheduler_driver_key = "auto"
            coordinator._poll_scheduler = self.coordinator_module.PollScheduler(
                policy=self.coordinator_module.poll_policy_for_driver_key("auto"),
                mode="auto",
                manual_interval=10,
            )
            observe_calls: list[dict[str, object]] = []
            original_observe = coordinator._poll_scheduler.observe

            def _observe(duration_seconds, *, success=True):
                observe_calls.append(
                    {
                        "duration_seconds": duration_seconds,
                        "success": success,
                    }
                )
                return original_observe(duration_seconds, success=success)

            coordinator._poll_scheduler.observe = _observe
            coordinator._poll_non_runtime_retry_interval_seconds = 0
            coordinator._poll_duration_ewma_seconds = 0.0
            coordinator._poll_duration_max_seconds = 0.0
            coordinator._poll_recent_durations_seconds = []
            coordinator._poll_last_cycle_started_monotonic = 0.0
            coordinator._collector_poll_overrun_streak = 0
            coordinator._collector_poll_high_utilization_streak = 0
            coordinator._poll_last_notification_monotonic = 0.0

            async def _poll_with_lock(**_kwargs):
                return self.RuntimeSnapshot(
                    values={
                        "runtime_driver_state": "driver_bound",
                        "collector_poll_duration_ms": 1000,
                    },
                    connected=True,
                    inverter=object(),
                )

            coordinator._async_update_data_with_runtime_lock = _poll_with_lock

            snapshot = await coordinator._async_update_data()

            self.assertEqual(snapshot.values["collector_poll_context"], "runtime")
            self.assertEqual(observe_calls[-1]["success"], False)
            self.assertEqual(coordinator._poll_scheduler.current_interval(), 10)
            self.assertNotIn(
                "collector_poll_detection_retry_interval_seconds",
                snapshot.values,
            )

        asyncio.run(_run())

    def test_unsupported_commands_persist_once_and_recheck_clears(self) -> None:
        coordinator = object.__new__(self.coordinator_module.EybondLocalCoordinator)
        entry = types.SimpleNamespace(
            entry_id="entry-1",
            options={},
        )
        updates: list[dict[str, object]] = []

        def _async_update_entry(config_entry, **kwargs) -> None:
            updates.append(dict(kwargs))
            if "options" in kwargs:
                config_entry.options = dict(kwargs["options"])

        coordinator.config_entry = entry
        coordinator.hass = types.SimpleNamespace(
            config_entries=types.SimpleNamespace(async_update_entry=_async_update_entry),
        )
        coordinator._suppress_entry_reload_count = 0
        runtime_calls: list[tuple[str, object]] = []
        coordinator._runtime = types.SimpleNamespace(
            set_persistent_unsupported_commands=(
                lambda commands: runtime_calls.append(("set", commands))
            ),
            clear_unsupported_command_cache=(
                lambda: runtime_calls.append(("clear", None))
            ),
        )

        snapshot = self.RuntimeSnapshot(
            values={"driver_unsupported_commands": "QPIWS, Q1, QET"},
            connected=True,
            inverter=object(),
        )
        coordinator._maybe_persist_unsupported_commands(snapshot)
        self.assertEqual(entry.options["driver_unsupported_commands"], ["Q1", "QET", "QPIWS"])
        self.assertEqual(entry.options["driver_unsupported_commands_version"], 2)
        self.assertEqual(runtime_calls, [("set", ("Q1", "QET", "QPIWS"))])
        self.assertEqual(len(updates), 1)

        # Unchanged set: no second write.
        coordinator._maybe_persist_unsupported_commands(snapshot)
        self.assertEqual(len(updates), 1)

        async def _run() -> None:
            refreshes: list[bool] = []

            async def _request_refresh() -> None:
                refreshes.append(True)

            coordinator.async_request_refresh = _request_refresh
            await coordinator.async_recheck_supported_commands()
            self.assertEqual(refreshes, [True])

        asyncio.run(_run())
        self.assertNotIn("driver_unsupported_commands", entry.options)
        self.assertNotIn("driver_unsupported_commands_version", entry.options)
        self.assertIn(("clear", None), runtime_calls)

    def test_collector_connection_watcher_refreshes_only_when_not_bound(self) -> None:
        coordinator = object.__new__(self.coordinator_module.EybondLocalCoordinator)
        coordinator._shutdown_complete = False
        scheduled: list[object] = []

        def _create_task(coro):
            scheduled.append(coro)
            coro.close()
            return None

        async def _fake_refresh():
            return None

        coordinator.hass = types.SimpleNamespace(async_create_task=_create_task)
        coordinator.async_request_refresh = _fake_refresh
        invalidations: list[str] = []
        coordinator._runtime = types.SimpleNamespace(
            invalidate_collector_runtime_values=lambda: invalidations.append("invalidate")
        )

        coordinator.data = self.RuntimeSnapshot(
            values={"runtime_driver_state": "driver_unbound"},
            connected=True,
        )
        coordinator._on_collector_connection_established("192.168.1.14")
        self.assertEqual(len(scheduled), 1)
        self.assertEqual(invalidations, ["invalidate"])

        coordinator.data = self.RuntimeSnapshot(
            values={"runtime_driver_state": "collector_offline"},
            connected=False,
        )
        coordinator._on_collector_connection_established("192.168.1.14")
        self.assertEqual(len(scheduled), 2)
        self.assertEqual(invalidations, ["invalidate", "invalidate"])

        coordinator.data = self.RuntimeSnapshot(
            values={"runtime_driver_state": "driver_bound"},
            connected=True,
            inverter=object(),
        )
        coordinator._on_collector_connection_established("192.168.1.14")
        self.assertEqual(len(scheduled), 2)
        self.assertEqual(invalidations, ["invalidate", "invalidate"])

        coordinator._shutdown_complete = True
        coordinator.data = self.RuntimeSnapshot(
            values={"runtime_driver_state": "driver_unbound"},
            connected=True,
        )
        coordinator._on_collector_connection_established("192.168.1.14")
        self.assertEqual(len(scheduled), 2)
        self.assertEqual(invalidations, ["invalidate", "invalidate"])

    def test_is_clean_runtime_poll_cycle_matrix(self) -> None:
        clean = self.coordinator_module._is_clean_runtime_poll_cycle

        self.assertTrue(
            clean(
                previous_runtime_driver_state="driver_bound",
                runtime_driver_state="driver_bound",
                previous_reconnect_count=2,
                reconnect_count=2,
            )
        )
        # Recovery happened inside the cycle: reconnect counter advanced.
        self.assertFalse(
            clean(
                previous_runtime_driver_state="driver_bound",
                runtime_driver_state="driver_bound",
                previous_reconnect_count=2,
                reconnect_count=3,
            )
        )
        # Transition cycle: detection ran inside it.
        self.assertFalse(
            clean(
                previous_runtime_driver_state="driver_unbound",
                runtime_driver_state="driver_bound",
                previous_reconnect_count=0,
                reconnect_count=0,
            )
        )
        self.assertFalse(
            clean(
                previous_runtime_driver_state="driver_bound",
                runtime_driver_state="collector_offline",
                previous_reconnect_count=0,
                reconnect_count=0,
            )
        )

    def test_recovery_cycle_does_not_feed_scheduler_or_warning(self) -> None:
        async def _run() -> None:
            coordinator = object.__new__(self.coordinator_module.EybondLocalCoordinator)
            coordinator.config_entry = types.SimpleNamespace(
                entry_id="entry-poll",
                data={},
                options={"poll_mode": "manual", "poll_interval": 10},
            )
            coordinator.data = self.RuntimeSnapshot(
                values={
                    "runtime_driver_state": "driver_bound",
                    "runtime_reconnect_count": 1,
                },
                connected=True,
                inverter=object(),
            )
            coordinator._diagnostic_active = False
            coordinator._runtime_operation_lock = asyncio.Lock()
            coordinator._poll_scheduler_driver_key = "auto"
            coordinator._poll_scheduler = self.coordinator_module.PollScheduler(
                policy=self.coordinator_module.poll_policy_for_driver_key("auto"),
                mode="manual",
                manual_interval=10,
            )
            observe_calls: list[dict[str, object]] = []
            original_observe = coordinator._poll_scheduler.observe

            def _observe(duration_seconds, *, success=True):
                observe_calls.append({"success": success})
                return original_observe(duration_seconds, success=success)

            coordinator._poll_scheduler.observe = _observe
            coordinator._poll_non_runtime_retry_interval_seconds = 0
            coordinator._poll_duration_ewma_seconds = 0.0
            coordinator._poll_duration_max_seconds = 0.0
            coordinator._poll_recent_durations_seconds = []
            coordinator._poll_last_cycle_started_monotonic = 0.0
            coordinator._collector_poll_overrun_streak = 0
            coordinator._collector_poll_high_utilization_streak = 0
            coordinator._poll_last_notification_monotonic = 0.0

            async def _poll_with_lock(**_kwargs):
                return self.RuntimeSnapshot(
                    values={
                        "runtime_driver_state": "driver_bound",
                        "runtime_reconnect_count": 2,
                        "collector_poll_duration_ms": 66000,
                    },
                    connected=True,
                    inverter=object(),
                )

            coordinator._async_update_data_with_runtime_lock = _poll_with_lock

            snapshot = await coordinator._async_update_data()

            self.assertEqual(snapshot.values["collector_poll_context"], "runtime")
            self.assertEqual(observe_calls[-1]["success"], False)
            self.assertEqual(
                snapshot.values["collector_poll_high_utilization_streak"], 0
            )
            self.assertEqual(coordinator._poll_recent_durations_seconds, [])
            self.assertEqual(coordinator._poll_duration_max_seconds, 0.0)

        asyncio.run(_run())

    def test_recovery_cycles_do_not_trigger_high_utilization_notification(self) -> None:
        coordinator = object.__new__(self.coordinator_module.EybondLocalCoordinator)
        coordinator.config_entry = types.SimpleNamespace(
            entry_id="entry-poll",
            options={"poll_mode": "manual", "poll_interval": 10},
        )
        notifications: list[str] = []

        def _async_create(hass, body, *, title, notification_id) -> None:
            del hass, title, notification_id
            notifications.append(body)

        coordinator.hass = types.SimpleNamespace(
            config=types.SimpleNamespace(language="en"),
        )
        coordinator._poll_duration_ewma_seconds = 0.0
        coordinator._poll_duration_max_seconds = 0.0
        coordinator._poll_recent_durations_seconds = []
        coordinator._collector_poll_overrun_streak = 0
        coordinator._collector_poll_high_utilization_streak = 0
        coordinator._poll_last_notification_monotonic = 0.0
        self.coordinator_module.persistent_notification.async_create = _async_create

        async def _run() -> None:
            for _ in range(3):
                snapshot = self.RuntimeSnapshot(
                    values={
                        "collector_poll_duration_ms": 66000,
                        "runtime_driver_state": "driver_bound",
                    },
                    connected=True,
                    inverter=object(),
                )
                coordinator._record_poll_cycle_metrics(
                    snapshot,
                    poll_interval_seconds=10,
                    duration_seconds=66.0,
                    clean_runtime_poll=False,
                )
                self.assertEqual(
                    snapshot.values["collector_poll_high_utilization_streak"], 0
                )

        asyncio.run(_run())

        self.assertEqual(notifications, [])
        self.assertEqual(coordinator._poll_recent_durations_seconds, [])
        self.assertEqual(coordinator._poll_duration_ewma_seconds, 0.0)

    def test_high_utilization_notification_dismissed_after_normalization(self) -> None:
        coordinator = object.__new__(self.coordinator_module.EybondLocalCoordinator)
        coordinator.config_entry = types.SimpleNamespace(
            entry_id="entry-poll",
            options={"poll_mode": "manual", "poll_interval": 10},
        )
        notifications: list[str] = []
        dismissals: list[str] = []

        def _async_create(hass, body, *, title, notification_id) -> None:
            del hass, body, title
            notifications.append(notification_id)

        def _async_dismiss(hass, notification_id) -> None:
            del hass
            dismissals.append(notification_id)

        coordinator.hass = types.SimpleNamespace(
            config=types.SimpleNamespace(language="en"),
        )
        coordinator._poll_duration_ewma_seconds = 0.0
        coordinator._poll_duration_max_seconds = 0.0
        coordinator._poll_recent_durations_seconds = []
        coordinator._collector_poll_overrun_streak = 0
        coordinator._collector_poll_high_utilization_streak = 0
        coordinator._poll_last_notification_monotonic = 0.0
        self.coordinator_module.persistent_notification.async_create = _async_create
        self.coordinator_module.persistent_notification.async_dismiss = _async_dismiss

        def _bound_snapshot(duration_ms: int):
            return self.RuntimeSnapshot(
                values={
                    "collector_poll_duration_ms": duration_ms,
                    "runtime_driver_state": "driver_bound",
                },
                connected=True,
                inverter=object(),
            )

        async def _run() -> None:
            for _ in range(3):
                coordinator._record_poll_cycle_metrics(
                    _bound_snapshot(12000),
                    poll_interval_seconds=10,
                    duration_seconds=12.0,
                )
            self.assertEqual(len(notifications), 1)
            self.assertEqual(dismissals, [])

            for _ in range(3):
                coordinator._record_poll_cycle_metrics(
                    _bound_snapshot(1000),
                    poll_interval_seconds=10,
                    duration_seconds=1.0,
                )

        asyncio.run(_run())

        self.assertEqual(dismissals, notifications)
        self.assertFalse(coordinator._poll_notification_active)

    def test_poll_scheduler_policy_updates_from_detected_driver_key(self) -> None:
        coordinator = object.__new__(self.coordinator_module.EybondLocalCoordinator)
        coordinator.config_entry = types.SimpleNamespace(
            data={},
            options={"poll_mode": "auto", "poll_interval": 10},
        )
        coordinator._poll_scheduler_driver_key = "auto"
        coordinator._ensure_poll_scheduler()

        self.assertEqual(coordinator._poll_scheduler.policy.min_auto_interval, 10)

        coordinator._update_poll_scheduler_policy_from_snapshot(
            self.RuntimeSnapshot(values={"driver_key": "modbus_smg"})
        )
        for _ in range(10):
            coordinator._poll_scheduler.observe(0.7)

        self.assertEqual(coordinator._poll_scheduler_driver_key, "modbus_smg")
        self.assertEqual(coordinator._poll_scheduler.policy.min_auto_interval, 3)
        self.assertEqual(coordinator._poll_scheduler.effective_interval, 3)

    def test_poll_scheduler_applies_model_specific_policy_for_same_driver_key(self) -> None:
        # A catalog driver keeps the SAME driver key but resolves a different
        # policy once the model/variant is known. The scheduler must switch even
        # though the driver key did not change (the old early-return bug applied
        # only the family/default policy forever).
        from custom_components.eybond_local.poll_policy import PollPolicy

        fast = PollPolicy(min_auto_interval=2.0, max_auto_interval=30.0)
        slow = PollPolicy(min_auto_interval=20.0, max_auto_interval=200.0)

        def _model_aware_resolver(driver_key="", inverter=None):
            if str(driver_key or "").strip() != "modbus_catalog":
                return PollPolicy(min_auto_interval=10.0, max_auto_interval=120.0)
            return fast if getattr(inverter, "variant_key", "") == "fast" else slow

        original = self.coordinator_polling_module.poll_policy_for_driver_key
        self.coordinator_polling_module.poll_policy_for_driver_key = _model_aware_resolver
        try:
            coordinator = object.__new__(self.coordinator_module.EybondLocalCoordinator)
            coordinator.config_entry = types.SimpleNamespace(
                data={},
                options={"poll_mode": "auto", "poll_interval": 10},
            )
            coordinator._poll_scheduler_driver_key = "auto"
            # Scheduler created BEFORE model identity is known.
            coordinator._runtime = types.SimpleNamespace(detected_inverter=None)
            coordinator._ensure_poll_scheduler()

            # First snapshot: driver known, no model yet -> family/default policy.
            coordinator._update_poll_scheduler_policy_from_snapshot(
                self.RuntimeSnapshot(values={"driver_key": "modbus_catalog"})
            )
            self.assertEqual(coordinator._poll_scheduler_driver_key, "modbus_catalog")
            self.assertEqual(coordinator._poll_scheduler.policy.min_auto_interval, 20)

            # Accumulate observations; they must survive the policy switch.
            for _ in range(5):
                coordinator._poll_scheduler.observe(0.7)
            samples_before = coordinator._poll_scheduler._durations[-1]

            # The SAME driver later resolves a model-specific (variant) policy.
            coordinator._runtime.detected_inverter = types.SimpleNamespace(
                variant_key="fast"
            )
            coordinator._update_poll_scheduler_policy_from_snapshot(
                self.RuntimeSnapshot(values={"driver_key": "modbus_catalog"})
            )

            # Switched despite the unchanged driver key, samples preserved.
            self.assertEqual(coordinator._poll_scheduler_driver_key, "modbus_catalog")
            self.assertEqual(coordinator._poll_scheduler.policy.min_auto_interval, 2)
            self.assertEqual(coordinator._poll_scheduler._durations[-1], samples_before)
        finally:
            self.coordinator_polling_module.poll_policy_for_driver_key = original

    def test_persist_confirmed_session_protocol_is_pn_validated_and_live_sourced(self) -> None:
        coordinator = object.__new__(self.coordinator_module.EybondLocalCoordinator)
        coordinator.hass = object()  # non-None gate
        coordinator.config_entry = types.SimpleNamespace(
            data={"collector_pn": "PNALPHA-FULL-0001"}
        )
        recorded: dict = {}
        coordinator._persist_connection_axes = (
            lambda updates=None, **kwargs: recorded.update(updates or {})
        )

        # Matching PN + live evidence -> persisted with live_session provenance.
        coordinator._runtime = types.SimpleNamespace(
            confirmed_session_protocol_evidence=lambda: (
                "eybond_framed",
                "PNALPHA-FULL-0001",
            )
        )
        coordinator._persist_confirmed_session_protocol_from_runtime()
        self.assertEqual(
            recorded.get("collector_confirmed_session_protocol"), "eybond_framed"
        )
        self.assertEqual(
            recorded.get("collector_confirmed_session_protocol_source"), "live_session"
        )
        self.assertEqual(
            recorded.get("collector_confirmed_session_protocol_pn"), "PNALPHA-FULL-0001"
        )

        # A DIFFERENT PN is never persisted.
        recorded.clear()
        coordinator._runtime = types.SimpleNamespace(
            confirmed_session_protocol_evidence=lambda: ("eybond_framed", "PNBETA-FULL-0002")
        )
        coordinator._persist_confirmed_session_protocol_from_runtime()
        self.assertEqual(recorded, {})

        # No confirmed evidence -> nothing persisted.
        coordinator._runtime = types.SimpleNamespace(
            confirmed_session_protocol_evidence=lambda: ("", "")
        )
        coordinator._persist_confirmed_session_protocol_from_runtime()
        self.assertEqual(recorded, {})

    def test_persist_confirmed_session_protocol_stamps_observed_at_only_on_new_evidence(
        self,
    ) -> None:
        coordinator = object.__new__(self.coordinator_module.EybondLocalCoordinator)
        coordinator.hass = object()
        coordinator.config_entry = types.SimpleNamespace(
            data={"collector_pn": "PNALPHA-FULL-0001"}
        )
        recorded: dict = {}
        coordinator._persist_connection_axes = (
            lambda updates=None, **kwargs: recorded.update(updates or {})
        )
        coordinator._runtime = types.SimpleNamespace(
            confirmed_session_protocol_evidence=lambda: (
                "eybond_framed",
                "PNALPHA-FULL-0001",
            )
        )

        # NEW evidence: an observed-at UTC timestamp is stamped exactly once.
        coordinator._persist_confirmed_session_protocol_from_runtime()
        observed_at = recorded.get("collector_confirmed_session_protocol_observed_at")
        self.assertTrue(observed_at)
        # A real ISO-8601 UTC timestamp (parseable, tz-aware).
        parsed = datetime.fromisoformat(observed_at)
        self.assertIsNotNone(parsed.tzinfo)

        # The evidence is now already persisted (unchanged): a later poll must be
        # a pure no-op -- the timestamp is NOT rewritten each refresh.
        coordinator.config_entry = types.SimpleNamespace(
            data={
                "collector_pn": "PNALPHA-FULL-0001",
                "collector_confirmed_session_protocol": "eybond_framed",
                "collector_confirmed_session_protocol_source": "live_session",
                "collector_confirmed_session_protocol_pn": "PNALPHA-FULL-0001",
                "collector_confirmed_session_protocol_observed_at": observed_at,
            }
        )
        recorded.clear()
        coordinator._persist_confirmed_session_protocol_from_runtime()
        self.assertEqual(recorded, {})

    def test_fixed_rate_poll_scheduler_sets_remaining_post_refresh_delay(self) -> None:
        coordinator = object.__new__(self.coordinator_module.EybondLocalCoordinator)
        snapshot = self.RuntimeSnapshot(values={})

        coordinator._sync_fixed_rate_poll_update_interval(
            snapshot,
            poll_interval_seconds=10,
            duration_seconds=5.2,
        )

        self.assertAlmostEqual(coordinator.update_interval.total_seconds(), 4.8)
        self.assertEqual(snapshot.values["collector_poll_scheduler_mode"], "fixed_rate")
        self.assertEqual(snapshot.values["collector_poll_effective_update_delay_ms"], 4800)

        coordinator._sync_fixed_rate_poll_update_interval(
            snapshot,
            poll_interval_seconds=10,
            duration_seconds=12.0,
        )

        self.assertEqual(coordinator.update_interval.total_seconds(), 1.0)
        self.assertEqual(snapshot.values["collector_poll_effective_update_delay_ms"], 1000)

    def test_old_entry_without_poll_mode_stays_manual_and_warns_high_utilization(self) -> None:
        coordinator = object.__new__(self.coordinator_module.EybondLocalCoordinator)
        entry = types.SimpleNamespace(
            entry_id="entry-poll",
            options={"poll_interval": 10},
        )
        updates: list[dict[str, object]] = []
        notifications: list[dict[str, object]] = []

        def _async_create(hass, body, *, title, notification_id) -> None:
            del hass
            notifications.append(
                {
                    "body": body,
                    "title": title,
                    "notification_id": notification_id,
                }
            )

        coordinator.config_entry = entry
        coordinator.hass = types.SimpleNamespace(
            config=types.SimpleNamespace(language="en"),
            config_entries=types.SimpleNamespace(
                async_update_entry=lambda *_args, **kwargs: updates.append(dict(kwargs))
            ),
        )
        coordinator._poll_duration_ewma_seconds = 0.0
        coordinator._poll_duration_max_seconds = 0.0
        coordinator._poll_recent_durations_seconds = []
        coordinator._collector_poll_overrun_streak = 0
        coordinator._collector_poll_high_utilization_streak = 0
        coordinator._poll_last_notification_monotonic = 0.0
        self.coordinator_module.persistent_notification.async_create = _async_create

        self.assertEqual(coordinator._configured_poll_mode(), "manual")

        async def _run() -> None:
            for _ in range(3):
                coordinator._record_poll_cycle_metrics(
                    self.RuntimeSnapshot(
                        values={
                            "collector_poll_duration_ms": 9200,
                            "runtime_driver_state": "driver_bound",
                        },
                        connected=True,
                        inverter=object(),
                    ),
                    poll_interval_seconds=10,
                )

        asyncio.run(_run())

        self.assertEqual(updates, [])
        self.assertEqual(entry.options["poll_interval"], 10)
        self.assertEqual(len(notifications), 1)
        self.assertIn("polling cycle is using", notifications[0]["body"])

    def test_support_package_refreshes_snapshot_after_capture_reconnect(self) -> None:
        async def _run() -> None:
            coordinator = object.__new__(self.coordinator_module.EybondLocalCoordinator)
            coordinator.config_entry = types.SimpleNamespace(entry_id="entry-support")
            coordinator._runtime_operation_lock = asyncio.Lock()
            coordinator.data = self.RuntimeSnapshot(connected=False)
            events: list[str] = []
            snapshots = iter(
                (
                    self.RuntimeSnapshot(
                        connected=False,
                        values={"runtime_session_state": "offline"},
                    ),
                    self.RuntimeSnapshot(
                        connected=True,
                        values={"runtime_session_state": "online"},
                    ),
                )
            )

            async def _refresh():
                snapshot = next(snapshots)
                events.append(f"refresh:{snapshot.connected}")
                return snapshot

            async def _registry_lookup():
                events.append("registry")
                return ("found", object())

            async def _capture():
                events.append("capture")
                return {
                    "capture_kind": "modbus_register_dump",
                    "captured_ranges": [{"start": 100, "count": 10}],
                    "range_failures": [],
                }

            def _build_payload(**_kwargs):
                events.append("build")
                return {
                    "runtime": {
                        "connected": coordinator.data.connected,
                        "values": dict(coordinator.data.values),
                    }
                }

            coordinator._async_update_data_with_runtime_lock = _refresh
            coordinator._async_collector_registry_lookup = _registry_lookup
            coordinator._runtime = types.SimpleNamespace(
                async_capture_support_evidence=_capture
            )
            coordinator._build_support_bundle_payload = _build_payload

            payload, raw_capture = await coordinator._async_build_support_package_payloads(
                integration_build_values={}
            )

            self.assertEqual(
                events,
                ["refresh:False", "registry", "capture", "refresh:True", "build"],
            )
            self.assertTrue(payload["runtime"]["connected"])
            self.assertEqual(
                payload["runtime"]["values"]["runtime_session_state"],
                "online",
            )
            self.assertEqual(raw_capture["capture_kind"], "modbus_register_dump")

        asyncio.run(_run())


if __name__ == "__main__":
    unittest.main()

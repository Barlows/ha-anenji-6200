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
    def test_di_inbound_commit_persists_route_strategy_contract_one_update(self) -> None:
        c, entry, updates, reloads = self._commit_coordinator(
            options={"advertised_server_ip": "stale", "advertised_tcp_port": 1, "control_mode": "manual"},
        )
        refusal = c._apply_transition_commit(
            {"connection_strategy": "inbound"},
            self._inbound_terminal(),
            {},
            advertised_host="192.168.1.50",
            advertised_port=8899,
        )
        self.assertEqual(refusal, "")
        # route + strategy + contract land in the ONE data update.
        self.assertEqual(entry.data["advertised_server_ip"], "192.168.1.50")
        self.assertEqual(entry.data["advertised_tcp_port"], 8899)
        self.assertEqual(entry.data["connection_strategy"], "inbound")
        self.assertIn("recovery_contract", entry.data)
        # stale options route dropped; unrelated option preserved.
        self.assertNotIn("advertised_server_ip", entry.options)
        self.assertNotIn("advertised_tcp_port", entry.options)
        self.assertEqual(entry.options["control_mode"], "manual")
        # exactly one update + one reload.
        self.assertEqual(len(updates), 1)
        self.assertEqual(reloads, ["entry-cp1b"])

    def test_di_callback_commit_persists_route_from_proof(self) -> None:
        c, entry, updates, reloads = self._commit_coordinator(
            options={"advertised_server_ip": "stale", "advertised_tcp_port": 1},
        )
        refusal = c._apply_transition_commit(
            {"connection_strategy": "callback_on_demand"},
            self._callback_terminal("195.191.72.37:18899"),
            {},
            advertised_host="195.191.72.37",
            advertised_port=18899,
        )
        self.assertEqual(refusal, "")
        # persisted route == the callback proof's advertised endpoint.
        self.assertEqual(entry.data["advertised_server_ip"], "195.191.72.37")
        self.assertEqual(entry.data["advertised_tcp_port"], 18899)
        self.assertNotIn("advertised_server_ip", entry.options)
        self.assertEqual(len(updates), 1)
        self.assertEqual(len(reloads), 1)

    def test_di_callback_proof_mismatch_commits_nothing(self) -> None:
        c, entry, updates, reloads = self._commit_coordinator(options={})
        refusal = c._apply_transition_commit(
            {"connection_strategy": "callback_on_demand"},
            self._callback_terminal("1.2.3.4:9000"),  # proof != attempted
            {},
            advertised_host="195.191.72.37",
            advertised_port=18899,
        )
        self.assertEqual(refusal, "transition_callback_route_mismatch")
        # NOTHING committed: no route, no strategy change, no update, no reload.
        self.assertNotIn("advertised_server_ip", entry.data)
        self.assertEqual(entry.data["connection_strategy"], "callback_on_demand")
        self.assertEqual(updates, [])
        self.assertEqual(reloads, [])

    def test_di_inbound_missing_proof_commits_nothing(self) -> None:
        c, entry, updates, reloads = self._commit_coordinator(options={})
        refusal = c._apply_transition_commit(
            {"connection_strategy": "inbound"},
            self._callback_terminal("192.168.1.50:8899"),  # wrong proof type
            {},
            advertised_host="192.168.1.50",
            advertised_port=8899,
        )
        self.assertEqual(refusal, "transition_inbound_route_unproven")
        self.assertEqual(updates, [])
        self.assertEqual(reloads, [])

    def test_di_non_strategy_merge_persists_no_route(self) -> None:
        # An inbound_recovered_after_restore merge (no strategy in updates) earns
        # no advertised route, even with a valid inbound proof.
        c, entry, updates, reloads = self._commit_coordinator(options={})
        refusal = c._apply_transition_commit(
            {},  # no connection_strategy committed
            self._inbound_terminal(),
            {},
            advertised_host="192.168.1.50",
            advertised_port=8899,
        )
        self.assertEqual(refusal, "")
        self.assertNotIn("advertised_server_ip", entry.data)
        self.assertEqual(updates[0]["options"], {})

    def test_di_invalid_committed_strategy_commits_nothing(self) -> None:
        # A bogus committed strategy is refused BEFORE any write -- it is never a
        # harmless merge that could persist "connection_strategy=bogus".
        c, entry, updates, reloads = self._commit_coordinator(options={})
        refusal = c._apply_transition_commit(
            {"connection_strategy": "bogus"},
            self._inbound_terminal(),
            {},
            advertised_host="192.168.1.50",
            advertised_port=8899,
        )
        self.assertEqual(refusal, "transition_committed_strategy_invalid")
        self.assertEqual(updates, [])
        self.assertEqual(reloads, [])
        # entry is unchanged -- the bogus strategy never reached the entry.
        self.assertEqual(entry.data["connection_strategy"], "callback_on_demand")

    def test_proxy_capture_notification_id_uses_capture_trace_stem(self) -> None:
        notification_id = self.coordinator_module._proxy_capture_notification_id(
            "entry-1",
            "/config/eybond_local/proxy_traces/session_trace.jsonl",
        )

        self.assertEqual(
            notification_id,
            "eybond_local_proxy_capture_entry-1_session_trace",
        )

    def test_cloud_evidence_export_available_supports_valuecloud_provider(self) -> None:
        coordinator = object.__new__(self.coordinator_module.EybondLocalCoordinator)
        coordinator.config_entry = types.SimpleNamespace(
            data={
                "collector_pn": "A0000000000001",
                "collector_cloud_family": "valuecloud_at",
            },
            options={},
        )
        coordinator.data = self.RuntimeSnapshot(values={})
        coordinator._runtime = types.SimpleNamespace(
            collector_server_endpoint_rollback_target="",
        )
        coordinator._remembered_collector_server_endpoint = ""

        self.assertEqual(coordinator.cloud_evidence_provider, "valuecloud")
        self.assertTrue(coordinator.cloud_evidence_export_available)

    def test_init_discards_stale_unsupported_cache_without_reload_suppression(self) -> None:
        entry = types.SimpleNamespace(
            entry_id="entry-1",
            data={},
            options={
                "driver_unsupported_commands": ["GLINE"],
                "driver_unsupported_commands_version": 1,
            },
        )
        updates: list[dict[str, object]] = []

        def _async_update_entry(config_entry, **kwargs) -> bool:
            updates.append(dict(kwargs))
            if "options" in kwargs:
                config_entry.options = dict(kwargs["options"])
            return True

        hass = types.SimpleNamespace(
            config_entries=types.SimpleNamespace(async_update_entry=_async_update_entry),
        )

        coordinator = self.coordinator_module.EybondLocalCoordinator(hass, entry)

        self.assertEqual(updates, [{"options": {}}])
        self.assertEqual(entry.options, {})
        self.assertEqual(coordinator._suppress_entry_reload_count, 0)
        self.assertFalse(coordinator.consume_entry_reload_suppression())

    def test_pre_listener_persistence_does_not_leave_reload_suppression(self) -> None:
        """A startup write before listener registration cannot consume a token."""

        entry = types.SimpleNamespace(data={}, options={}, update_listeners=[])

        def _async_update_entry(config_entry, **kwargs) -> bool:
            if "data" in kwargs:
                config_entry.data = dict(kwargs["data"])
            return True

        coordinator = object.__new__(self.coordinator_module.EybondLocalCoordinator)
        coordinator.config_entry = entry
        coordinator.hass = types.SimpleNamespace(
            config_entries=types.SimpleNamespace(async_update_entry=_async_update_entry)
        )
        coordinator._suppress_entry_reload_count = 0

        coordinator._async_update_entry_without_reload(data={"detected": True})

        self.assertEqual(entry.data, {"detected": True})
        self.assertEqual(coordinator._suppress_entry_reload_count, 0)
        self.assertFalse(coordinator.consume_entry_reload_suppression())

    def test_runtime_persistence_with_listener_arms_one_reload_suppression(self) -> None:
        """Once setup registered a listener, one changed write arms one token."""

        entry = types.SimpleNamespace(
            data={}, options={}, update_listeners=[object()]
        )

        def _async_update_entry(config_entry, **kwargs) -> bool:
            if "data" in kwargs:
                config_entry.data = dict(kwargs["data"])
            return True

        coordinator = object.__new__(self.coordinator_module.EybondLocalCoordinator)
        coordinator.config_entry = entry
        coordinator.hass = types.SimpleNamespace(
            config_entries=types.SimpleNamespace(async_update_entry=_async_update_entry)
        )
        coordinator._suppress_entry_reload_count = 0

        coordinator._async_update_entry_without_reload(data={"detected": True})

        self.assertEqual(coordinator._suppress_entry_reload_count, 1)
        self.assertTrue(coordinator.consume_entry_reload_suppression())
        self.assertFalse(coordinator.consume_entry_reload_suppression())

    def test_legacy_metadata_channel_migrates_out_of_driver_option(self) -> None:
        # A legacy entry persisted the AT-metadata dead-channel verdict inside the
        # driver negative-cache option under a ``collector:`` namespace. It must
        # migrate into the dedicated metadata option and leave the driver option.
        entry = types.SimpleNamespace(
            entry_id="entry-1",
            data={},
            options={
                "driver_unsupported_commands": ["GLINE", "collector:at_metadata"],
                "driver_unsupported_commands_version": 2,
            },
        )
        updates: list[dict[str, object]] = []

        def _async_update_entry(config_entry, **kwargs) -> bool:
            updates.append(dict(kwargs))
            if "options" in kwargs:
                config_entry.options = dict(kwargs["options"])
            return True

        hass = types.SimpleNamespace(
            config_entries=types.SimpleNamespace(async_update_entry=_async_update_entry),
        )

        coordinator = self.coordinator_module.EybondLocalCoordinator(hass, entry)

        # The runtime reports the migrated dead channel from its OWN health store
        # (a stub here; the real hub split is covered in test_hub).
        coordinator._runtime = types.SimpleNamespace(
            collector_metadata_dead_channels=lambda: ("collector:at_metadata",)
        )

        # The one-time option rewrite happens on the first persist pass: the
        # legacy ``collector:`` key leaves the driver option and lands in the
        # dedicated metadata option.
        coordinator._maybe_persist_metadata_dead_channels()
        self.assertEqual(entry.options.get("driver_unsupported_commands"), ["GLINE"])
        self.assertEqual(
            entry.options.get("collector_metadata_dead_channels"),
            ["collector:at_metadata"],
        )
        self.assertEqual(
            entry.options.get("collector_metadata_dead_channels_version"), 1
        )

        # Idempotent: a settled entry produces no further write.
        updates.clear()
        coordinator._maybe_persist_metadata_dead_channels()
        self.assertEqual(updates, [])

    def test_cloud_evidence_export_available_supports_smartess_provider(self) -> None:
        coordinator = object.__new__(self.coordinator_module.EybondLocalCoordinator)
        coordinator.config_entry = types.SimpleNamespace(
            data={
                "collector_pn": "E5000020000000",
                "collector_cloud_family": "smartess_at",
            },
            options={},
        )
        coordinator.data = self.RuntimeSnapshot(values={})
        coordinator._runtime = types.SimpleNamespace(
            collector_server_endpoint_rollback_target="",
        )
        coordinator._remembered_collector_server_endpoint = ""

        self.assertEqual(coordinator.cloud_evidence_provider, "smartess")
        self.assertTrue(coordinator.cloud_evidence_export_available)

    def test_cloud_evidence_export_available_rejects_unknown_provider(self) -> None:
        coordinator = object.__new__(self.coordinator_module.EybondLocalCoordinator)
        coordinator.config_entry = types.SimpleNamespace(
            data={
                "collector_pn": "A9999999999999",
                "collector_cloud_family": "unknown",
            },
            options={},
        )
        coordinator.data = self.RuntimeSnapshot(values={})
        coordinator._runtime = types.SimpleNamespace(
            collector_server_endpoint_rollback_target="",
        )
        coordinator._remembered_collector_server_endpoint = ""

        self.assertEqual(coordinator.cloud_evidence_provider, "")
        self.assertFalse(coordinator.cloud_evidence_export_available)

    def test_cached_evidence_ignored_when_active_provider_changes(self) -> None:
        # The active provider is SmartESS, but the cached record was loaded for
        # ValueCloud: the cache is ignored so one provider's evidence never leaks
        # (also what keeps a support bundle from embedding foreign evidence).
        coordinator = object.__new__(self.coordinator_module.EybondLocalCoordinator)
        coordinator.config_entry = types.SimpleNamespace(
            data={"collector_pn": "E5000020000000", "collector_cloud_family": "smartess_at"},
            options={},
        )
        coordinator.data = self.RuntimeSnapshot(values={})
        cached_record = types.SimpleNamespace(path="/x.json", payload={"provider": "valuecloud"})
        coordinator._cached_smartess_cloud_evidence_record = cached_record
        coordinator._cached_cloud_evidence_provider = "valuecloud"

        self.assertEqual(coordinator.cloud_evidence_provider, "smartess")
        # Stale (foreign-provider) cache -> not returned.
        self.assertIsNone(coordinator._latest_smartess_cloud_evidence_record())

        # Once the cache belongs to the active provider it is returned again.
        coordinator._cached_cloud_evidence_provider = "smartess"
        self.assertIs(coordinator._latest_smartess_cloud_evidence_record(), cached_record)

    def test_warm_cache_race_stamps_fetching_provider_not_reread(self) -> None:
        # The active cloud family changes WHILE the (SmartESS) load runs: the
        # cache must be stamped with the fetching provider so the result stays
        # invisible to the new provider (no re-read of a dynamic value).
        async def _run() -> None:
            from custom_components.eybond_local.support.cloud_evidence_providers import (
                CloudEvidenceContext,
            )

            coordinator = object.__new__(self.coordinator_module.EybondLocalCoordinator)
            coordinator.config_entry = types.SimpleNamespace(
                data={"collector_pn": "E1", "collector_cloud_family": "smartess_at"},
                options={},
            )
            coordinator.data = self.RuntimeSnapshot(values={})
            coordinator._cached_smartess_cloud_evidence_record = None
            coordinator._cached_cloud_evidence_provider = ""
            coordinator._cached_smartess_cloud_evidence_warmed = False

            record = types.SimpleNamespace(path="/x.json", payload={"provider": "smartess"})

            def _load_latest(_context):
                coordinator.config_entry.data["collector_cloud_family"] = "valuecloud_at"
                return record

            coordinator._cloud_evidence_provider_impl = lambda: types.SimpleNamespace(
                provider_id="smartess", load_latest=_load_latest
            )
            coordinator._cloud_evidence_context = lambda: CloudEvidenceContext(
                config_dir=Path("."), entry_id="e", collector_pn="E1"
            )

            async def _executor(fn, *args):
                return fn(*args)

            coordinator.hass = types.SimpleNamespace(async_add_executor_job=_executor)

            await coordinator._async_warm_smartess_cloud_evidence_cache()

            self.assertEqual(coordinator._cached_cloud_evidence_provider, "smartess")
            self.assertIs(coordinator._cached_smartess_cloud_evidence_record, record)
            self.assertEqual(coordinator.cloud_evidence_provider, "valuecloud")
            self.assertIsNone(coordinator._latest_smartess_cloud_evidence_record())

        asyncio.run(_run())

    def test_export_provider_change_does_not_publish_foreign_tooling_path(self) -> None:
        async def _run() -> None:
            from custom_components.eybond_local.support.cloud_evidence_providers import (
                CloudEvidenceContext,
            )

            coordinator = object.__new__(self.coordinator_module.EybondLocalCoordinator)
            coordinator.config_entry = types.SimpleNamespace(
                data={"collector_pn": "E1", "collector_cloud_family": "smartess_at"},
                options={},
            )
            coordinator.data = self.RuntimeSnapshot(values={})
            coordinator._cached_smartess_cloud_evidence_record = None
            coordinator._cached_cloud_evidence_provider = ""
            coordinator._cached_smartess_cloud_evidence_warmed = False
            published: list[dict[str, object]] = []
            record = types.SimpleNamespace(path="/smartess.json", payload={"provider": "smartess"})

            def _export(_context, *, username, password):
                coordinator.config_entry.data["collector_cloud_family"] = "valuecloud_at"
                return record

            provider = types.SimpleNamespace(
                provider_id="smartess",
                export_available=lambda _context: True,
                export=_export,
                export_status_label="SmartESS cloud evidence exported",
            )
            coordinator._cloud_evidence_provider_impl = lambda: provider
            coordinator._cloud_evidence_context = lambda: CloudEvidenceContext(
                config_dir=Path("."), entry_id="e", collector_pn="E1"
            )
            coordinator._publish_tooling_values = lambda **kwargs: published.append(kwargs)

            async def _executor(fn, *args):
                return fn(*args)

            coordinator.hass = types.SimpleNamespace(async_add_executor_job=_executor)
            result = await coordinator.async_export_cloud_evidence(
                username="u", password="p"
            )

            self.assertEqual(result, "/smartess.json")
            self.assertEqual(coordinator._cached_cloud_evidence_provider, "smartess")
            self.assertEqual(coordinator.cloud_evidence_provider, "valuecloud")
            self.assertIsNone(coordinator._latest_smartess_cloud_evidence_record())
            self.assertEqual(published, [])

        asyncio.run(_run())

    def test_diagnostic_waits_for_in_progress_runtime_refresh(self) -> None:
        async def _run() -> None:
            coordinator = object.__new__(
                self.coordinator_module.EybondLocalCoordinator
            )
            coordinator.data = types.SimpleNamespace()
            coordinator._diagnostic_active = False
            coordinator._runtime_operation_lock = asyncio.Lock()

            poll_started = asyncio.Event()
            release_poll = asyncio.Event()
            diagnostic_started = asyncio.Event()

            async def _poll_with_lock(**_kwargs):
                poll_started.set()
                await release_poll.wait()
                return coordinator.data

            async def _fake_run_scenario(_commands, _context):
                diagnostic_started.set()
                return types.SimpleNamespace(
                    success=True,
                    output="ok\n",
                    results=[],
                    context={},
                    started_at="start",
                    finished_at="finish",
                    error=None,
                )

            coordinator._async_update_data_with_runtime_lock = _poll_with_lock
            coordinator.config_entry = types.SimpleNamespace(entry_id="entry-1")

            async def _run_executor_job(job):
                return job()

            coordinator.hass = types.SimpleNamespace(
                config=types.SimpleNamespace(config_dir="/tmp"),
                async_add_executor_job=_run_executor_job,
            )
            export = types.SimpleNamespace(
                result_path=Path("/tmp/result.json"),
                shareable_path=Path("/tmp/result.share.json"),
            )

            poll_task = asyncio.create_task(coordinator._async_update_data())
            await poll_started.wait()
            with patch.object(
                self.coordinator_diagnostics_module,
                "run_scenario",
                _fake_run_scenario,
            ), patch.object(
                self.coordinator_diagnostics_module,
                "export_diagnostic_run",
                return_value=export,
            ):
                diagnostic_task = asyncio.create_task(
                    coordinator._async_execute_diagnostic(
                        "read 1",
                        types.SimpleNamespace(),
                    )
                )
                await asyncio.sleep(0)
                self.assertFalse(diagnostic_started.is_set())

                release_poll.set()
                await poll_task
                await diagnostic_task
                self.assertTrue(diagnostic_started.is_set())

        asyncio.run(_run())

    def test_diagnostic_download_uses_signed_entry_scoped_api_url(self) -> None:
        async def _run() -> None:
            coordinator = object.__new__(
                self.coordinator_module.EybondLocalCoordinator
            )
            coordinator._runtime_operation_lock = asyncio.Lock()
            coordinator.config_entry = types.SimpleNamespace(entry_id="entry-1")

            async def _run_executor_job(job):
                return job()

            coordinator.hass = types.SimpleNamespace(
                config=types.SimpleNamespace(config_dir="/tmp"),
                async_add_executor_job=_run_executor_job,
            )
            result = types.SimpleNamespace(
                success=True,
                output="ok\n",
                results=[],
                context={},
                started_at="start",
                finished_at="finish",
                error=None,
            )
            export = types.SimpleNamespace(
                result_path=Path("/tmp/result.json"),
                shareable_path=Path(
                    "/tmp/diagnostic_entry-1_20260823T125052279675Z.share.json"
                ),
            )
            signed = "https://ha.example/api/eybond_local/diagnostic_run/signed"

            with patch.object(
                self.coordinator_diagnostics_module,
                "run_scenario",
                return_value=result,
            ), patch.object(
                self.coordinator_diagnostics_module,
                "export_diagnostic_run",
                return_value=export,
            ), patch.object(
                self.coordinator_diagnostics_module,
                "sign_diagnostic_run_download_url",
                return_value=signed,
            ) as signer:
                payload = await coordinator._async_execute_diagnostic(
                    "read 1",
                    types.SimpleNamespace(transport=None),
                    publish_download_copy=True,
                )

            signer.assert_called_once_with(
                coordinator.hass,
                "entry-1",
                export.shareable_path.name,
            )
            self.assertEqual(payload["download_url"], signed)

        asyncio.run(_run())

    def test_write_capability_serializes_against_runtime_refresh(self) -> None:
        # A control write must take the same _runtime_operation_lock the polling
        # loop holds, so a write and a refresh never interleave on the shared
        # transport (a mis-correlated read-back on a safety-critical write).
        async def _run() -> None:
            coordinator = object.__new__(
                self.coordinator_module.EybondLocalCoordinator
            )
            coordinator.data = types.SimpleNamespace(
                inverter=types.SimpleNamespace(
                    get_capability=lambda key: types.SimpleNamespace(key=key)
                )
            )
            coordinator._diagnostic_active = False
            coordinator._runtime_operation_lock = asyncio.Lock()
            coordinator.can_expose_capability = lambda _cap: True

            poll_started = asyncio.Event()
            release_poll = asyncio.Event()
            write_started = asyncio.Event()

            async def _poll_with_lock(**_kwargs):
                poll_started.set()
                await release_poll.wait()
                return coordinator.data

            coordinator._async_update_data_with_runtime_lock = _poll_with_lock

            async def _runtime_write(_key, value):
                write_started.set()
                # The write only runs while it holds the operation lock.
                assert coordinator._runtime_operation_lock.locked()
                return value

            coordinator._runtime = types.SimpleNamespace(
                async_write_capability=_runtime_write
            )

            async def _noop_refresh():
                return None

            coordinator.async_request_refresh = _noop_refresh

            poll_task = asyncio.create_task(coordinator._async_update_data())
            await poll_started.wait()  # poll now holds the lock

            write_task = asyncio.create_task(
                coordinator.async_write_capability("op2_enable", 1)
            )
            await asyncio.sleep(0)
            # The write must be blocked on the lock while the poll holds it.
            self.assertFalse(write_started.is_set())

            release_poll.set()
            await poll_task
            result = await write_task
            self.assertTrue(write_started.is_set())
            self.assertEqual(result, 1)

        asyncio.run(_run())

    def test_local_register_snapshot_serializes_against_runtime_refresh(self) -> None:
        async def _run() -> None:
            coordinator = object.__new__(
                self.coordinator_module.EybondLocalCoordinator
            )
            coordinator._runtime_operation_lock = asyncio.Lock()
            capture_started = asyncio.Event()

            async def _capture():
                self.assertTrue(coordinator._runtime_operation_lock.locked())
                capture_started.set()
                return None

            coordinator._runtime = types.SimpleNamespace(
                async_capture_local_register_snapshot=_capture,
            )
            await coordinator._runtime_operation_lock.acquire()
            task = asyncio.create_task(
                coordinator.async_capture_local_register_snapshot()
            )
            await asyncio.sleep(0)
            self.assertFalse(capture_started.is_set())

            coordinator._runtime_operation_lock.release()
            self.assertIsNone(await task)
            self.assertTrue(capture_started.is_set())

        asyncio.run(_run())

    def test_local_register_collection_uses_public_capture_and_publishes_typed_series(
        self,
    ) -> None:
        async def _run() -> None:
            from custom_components.eybond_local.drivers.local_register_evidence import (
                LocalRegisterBlockObservation,
                LocalRegisterReadPlan,
                LocalRegisterSnapshot,
            )
            from custom_components.eybond_local.drivers.local_register_series import (
                LocalRegisterSeriesPlan,
                LocalRegisterSnapshotSeries,
            )
            import custom_components.eybond_local.support.local_register_collection as collection_module
            from custom_components.eybond_local.support.local_register_collection import (
                LocalRegisterCollectionManager,
            )

            coordinator = object.__new__(
                self.coordinator_module.EybondLocalCoordinator
            )
            coordinator._runtime_operation_lock = asyncio.Lock()
            coordinator._shutdown_complete = False
            coordinator._tooling_values = {}
            coordinator.data = self.RuntimeSnapshot(values={})
            snapshots: list[LocalRegisterSnapshot] = []
            plan = LocalRegisterReadPlan(
                devcode=2376,
                collector_addr=1,
                device_addr=1,
                function=3,
                start=100,
                count=1,
            )
            for index in range(3):
                snapshots.append(
                    LocalRegisterSnapshot(
                        collector_pn="E50000200000000001",
                        driver_key="smg_modbus",
                        started_at=f"2026-08-22T10:00:{index * 10:02d}+00:00",
                        completed_at=f"2026-08-22T10:00:{index * 10 + 1:02d}+00:00",
                        planned_block_count=1,
                        failed_block_count=0,
                        blocks=(
                            LocalRegisterBlockObservation(
                                plan=plan,
                                observed_at=(
                                    f"2026-08-22T10:00:{index * 10 + 1:02d}+00:00"
                                ),
                                values=(2300 + index,),
                            ),
                        ),
                    )
                )

            async def _capture():
                self.assertTrue(coordinator._runtime_operation_lock.locked())
                return snapshots.pop(0)

            from custom_components.eybond_local.drivers.local_register_evidence import (
                LocalRegisterCollectionAvailability,
            )

            coordinator._runtime = types.SimpleNamespace(
                async_capture_local_register_snapshot=_capture,
                local_register_collection_availability=(
                    LocalRegisterCollectionAvailability("ready")
                ),
            )
            coordinator._local_register_collection = LocalRegisterCollectionManager(
                capture_snapshot=coordinator.async_capture_local_register_snapshot,
                on_update=coordinator._publish_local_register_collection_update,
            )

            async def _immediate_series(**kwargs):
                captured = [
                    await kwargs["capture_snapshot"]() for _ in range(3)
                ]
                return LocalRegisterSnapshotSeries(
                    collector_pn="E50000200000000001",
                    driver_key="smg_modbus",
                    sample_interval_seconds=kwargs["sample_interval_seconds"],
                    snapshots=tuple(captured),
                )

            with patch.object(
                collection_module,
                "async_capture_local_register_series",
                side_effect=_immediate_series,
            ):
                started = coordinator.start_local_register_collection(
                    LocalRegisterSeriesPlan(3, 1)
                )
                self.assertTrue(started.active)
                await asyncio.sleep(0)

            self.assertTrue(coordinator.local_register_collection_status.series_available)
            self.assertIs(
                type(coordinator.latest_local_register_series),
                LocalRegisterSnapshotSeries,
            )
            status_record = coordinator.data.values["local_register_collection"]
            series_record = coordinator.data.values[
                "local_register_series_evidence"
            ]
            self.assertIs(status_record["read_only"], True)
            self.assertIs(status_record["activation_allowed"], False)
            self.assertIs(series_record["cloud_mapping_proven"], False)
            self.assertEqual(series_record["snapshot_count"], 3)

            previous = coordinator.local_register_collection_status
            with self.assertRaises(TypeError):
                coordinator.start_local_register_collection(object())
            self.assertIs(coordinator.local_register_collection_status, previous)

        asyncio.run(_run())

    def test_proxy_capture_notification_body_without_link_uses_saved_path(self) -> None:
        hass = types.SimpleNamespace(config=types.SimpleNamespace(language="uk"))

        message = self.coordinator_module._localized_runtime_text(
            hass,
            "proxy_capture_notification_body_no_link",
            saved_path="/config/eybond_local/proxy_traces/session_bundle.zip",
        )

        self.assertIn("/config/eybond_local/proxy_traces/session_bundle.zip", message)
        self.assertIn("Збережений архів", message)

    def test_capability_enabled_by_default_enables_exposed_learned_control(self) -> None:
        # The overlay generator bakes enabled_default=False onto every learned capability
        # so it stays inactive until activation. Once activated + selected (exposable), the
        # entity must be enabled by default -- otherwise it is registered disabled and stays
        # hidden under "disabled entities" on the device page. Built-ins keep their default.
        coordinator = object.__new__(self.coordinator_module.EybondLocalCoordinator)
        learned = types.SimpleNamespace(
            is_device_scoped_experimental=True, enabled_default=False
        )
        builtin = types.SimpleNamespace(
            is_device_scoped_experimental=False, enabled_default=True
        )

        coordinator.can_expose_capability = lambda _cap: True
        self.assertTrue(coordinator.capability_enabled_by_default(learned))
        self.assertTrue(coordinator.capability_enabled_by_default(builtin))

        coordinator.can_expose_capability = lambda _cap: False
        self.assertFalse(coordinator.capability_enabled_by_default(learned))

    def test_apply_device_overlay_merges_learned_capabilities(self) -> None:
        # Regression: the runtime detects the inverter against built-in bindings, so its
        # capabilities never include the activated learned overlay controls. Without
        # merging them in, the learned control exists only in effective metadata and
        # never becomes an entity (every entity/write path reads inverter.capabilities).
        coordinator = object.__new__(self.coordinator_module.EybondLocalCoordinator)
        coordinator.config_entry = types.SimpleNamespace(data={}, options={})

        builtin_cap = types.SimpleNamespace(key="battery_float_voltage")
        inverter = _FakeInverter(
            capabilities=(builtin_cap,),
            capability_groups=(types.SimpleNamespace(key="battery"),),
            register_schema_name="modbus_smg/models/smg_6200.json",
        )

        learned_cap = types.SimpleNamespace(
            key="learned_x_304", is_device_scoped_experimental=True, group="config"
        )
        learned_schema_name = "learned/shadow_learning/dev/smg_6200_session.json"
        stub_metadata = types.SimpleNamespace(
            device_scoped_overlay_active=True,
            register_schema_name=learned_schema_name,
            profile_metadata=types.SimpleNamespace(
                capabilities=(learned_cap,),
                groups=(types.SimpleNamespace(key="config"),),
            ),
        )
        original = self.coordinator_inverter_profile_module.resolve_effective_metadata_selection
        self.coordinator_inverter_profile_module.resolve_effective_metadata_selection = (
            lambda **_kwargs: stub_metadata
        )
        try:
            result = coordinator.apply_device_overlay_to_inverter(inverter, None)
        finally:
            self.coordinator_inverter_profile_module.resolve_effective_metadata_selection = original

        self.assertIn("learned_x_304", {cap.key for cap in result.capabilities})
        self.assertIn("battery_float_voltage", {cap.key for cap in result.capabilities})
        self.assertIn("config", {group.key for group in result.capability_groups})
        # CRITICAL: the overlay merge must NOT change register_schema_name. Pointing it at the
        # learned overlay schema flips the metadata scope to external and fails the
        # write-exposure proof for EVERY capability (builtin included) -- every control then
        # disappears. The builtin schema stays; learned-register read-back is done in the driver.
        self.assertEqual(result.register_schema_name, "modbus_smg/models/smg_6200.json")

    def test_entity_setup_merges_active_overlay_into_inverter(self) -> None:
        # The single place every platform reads at setup must apply the overlay merge,
        # so activated learned controls materialize regardless of detection timing.
        pc = self.platform_context_module
        inverter = _FakeInverter(capabilities=(types.SimpleNamespace(key="builtin"),))
        merged = _FakeInverter(
            capabilities=(
                types.SimpleNamespace(key="builtin"),
                types.SimpleNamespace(key="learned_x"),
            )
        )
        coordinator = types.SimpleNamespace(
            apply_device_overlay_to_inverter=lambda inv, collector: merged,
            data=types.SimpleNamespace(collector=None),
        )

        self.assertIs(pc._merge_active_device_overlay(coordinator, inverter), merged)
        # No applier / no inverter -> unchanged, never raises.
        self.assertIs(
            pc._merge_active_device_overlay(types.SimpleNamespace(), inverter), inverter
        )
        self.assertIsNone(pc._merge_active_device_overlay(coordinator, None))

    def test_apply_device_overlay_returns_inverter_unchanged_when_inactive(self) -> None:
        coordinator = object.__new__(self.coordinator_module.EybondLocalCoordinator)
        coordinator.config_entry = types.SimpleNamespace(data={}, options={})
        inverter = _FakeInverter()

        stub_metadata = types.SimpleNamespace(device_scoped_overlay_active=False)
        original = self.coordinator_inverter_profile_module.resolve_effective_metadata_selection
        self.coordinator_inverter_profile_module.resolve_effective_metadata_selection = (
            lambda **_kwargs: stub_metadata
        )
        try:
            result = coordinator._apply_device_overlay_to_inverter(inverter, None)
        finally:
            self.coordinator_inverter_profile_module.resolve_effective_metadata_selection = original

        self.assertIs(result, inverter)

    def test_write_exposure_context_uses_warmed_effective_metadata_cache(self) -> None:
        # Regression: after activating a learned overlay, write-exposure checks run in the
        # event loop. They must use the executor-warmed effective metadata selection instead
        # of re-resolving the overlay and reading external profile/schema JSON synchronously.
        coordinator = object.__new__(self.coordinator_module.EybondLocalCoordinator)
        coordinator.config_entry = types.SimpleNamespace(data={}, options={})
        coordinator.data = types.SimpleNamespace(
            collector=None,
            inverter=types.SimpleNamespace(model_name="SMG 6200", variant_key="smg_6200"),
        )
        coordinator._cached_effective_metadata = types.SimpleNamespace(
            profile_name="learned/shadow_learning/device/profile.json",
            profile_metadata=types.SimpleNamespace(source_scope="external"),
            register_schema_metadata=types.SimpleNamespace(source_scope="external"),
            device_scoped_overlay_active=True,
            device_scoped_overlay_scope="device",
            device_scoped_overlay_selected_control_keys={"learned_a"},
        )

        with patch.object(
            self.coordinator_inverter_profile_module,
            "resolve_effective_metadata_selection",
            side_effect=AssertionError("sync resolver should not run after warm-up"),
        ):
            context = coordinator.write_exposure_context

        self.assertEqual(context["variant_key"], "smg_6200")
        self.assertEqual(context["profile_source_scope"], "external")
        self.assertEqual(context["schema_source_scope"], "external")
        self.assertTrue(context["device_scoped_overlay_active"])
        self.assertEqual(context["selected_control_keys"], {"learned_a"})

    def test_sync_device_registry_sets_inverter_parent_to_collector(self) -> None:
        registry = FakeRegistry()
        self.coordinator_module.dr.async_get = lambda hass: registry

        coordinator = object.__new__(self.coordinator_module.EybondLocalCoordinator)
        coordinator.hass = types.SimpleNamespace(
            config_entries=types.SimpleNamespace(
                async_get_entry=lambda entry_id: (
                    object() if entry_id == "entry-1" else None
                )
            )
        )
        coordinator.config_entry = types.SimpleNamespace(
            entry_id="entry-1",
            data={},
            options={},
            title="SMG 6200",
        )
        coordinator.data = self.RuntimeSnapshot(
            values={
                "collector_hardware_version": "HW-7",
                "collector_type": "Wi-Fi.DTU",
            },
            inverter=types.SimpleNamespace(model_name="SMG 6200", serial_number="INV-001"),
            collector=types.SimpleNamespace(
                collector_pn="COL-001",
                profile_name="EyeBond ASCII PN v1",
                smartess_protocol_name=None,
                smartess_protocol_asset_name=None,
                smartess_collector_version="1.2.3",
            ),
        )
        coordinator._last_synced_device_meta = ("", "", "", "", "")
        coordinator._last_synced_collector_device_meta = ("", "", "", "", "")

        coordinator.async_sync_device_registry()

        collector = registry.async_get_device(
            identifiers={("eybond_local", "entry-1:collector")}
        )
        inverter = registry.async_get_device(
            identifiers={("eybond_local", "entry-1")}
        )

        self.assertIsNotNone(collector)
        self.assertIsNotNone(inverter)
        self.assertEqual(collector.name, "Collector PN COL-001")
        self.assertEqual(collector.model, "Wi-Fi.DTU")
        self.assertEqual(collector.hw_version, "HW-7")
        self.assertEqual(inverter.via_device_id, collector.id)

    def test_device_registry_diagnostics_exposes_duplicate_children_without_identifiers(self) -> None:
        registry = FakeRegistry()
        self.coordinator_module.dr.async_get = lambda hass: registry

        collector = registry.async_get_or_create(
            config_entry_id="entry-1",
            identifiers={("eybond_local", "entry-1:collector")},
            name="Collector PN SECRET",
        )
        inverter = registry.async_get_or_create(
            config_entry_id="entry-1",
            identifiers={("eybond_local", "entry-1")},
            name="Anenji SECRET",
            model="Anenji ANJ-11KW-48V-WIFI-P",
            serial_number="SECRET-SERIAL",
            via_device=("eybond_local", "entry-1:collector"),
        )
        duplicate = registry.async_get_or_create(
            config_entry_id="legacy-entry",
            identifiers={("eybond_local", "legacy-inverter")},
            name="User Secret Name",
            model="Anenji ANJ-11KW-48V-WIFI-P",
            via_device=("eybond_local", "entry-1:collector"),
        )

        class _EntityRegistry:
            entries_by_device = {
                inverter.id: (
                    types.SimpleNamespace(disabled_by=None),
                    types.SimpleNamespace(disabled_by="integration"),
                ),
                duplicate.id: (),
            }

        entity_registry_module = sys.modules["homeassistant.helpers.entity_registry"]
        entity_registry_module.async_get = lambda hass: _EntityRegistry()
        entity_registry_module.async_entries_for_device = (
            lambda entity_registry, device_id, **kwargs: (
                entity_registry.entries_by_device.get(device_id, ())
            )
        )

        coordinator = object.__new__(self.coordinator_module.EybondLocalCoordinator)
        coordinator.hass = types.SimpleNamespace(
            config_entries=types.SimpleNamespace(
                async_get_entry=lambda entry_id: (
                    object() if entry_id == "entry-1" else None
                )
            )
        )
        coordinator.config_entry = types.SimpleNamespace(
            entry_id="entry-1",
            data={},
            options={},
            title="Anenji",
        )
        coordinator.data = self.RuntimeSnapshot(
            inverter=types.SimpleNamespace(
                model_name="Anenji ANJ-11KW-48V-WIFI-P",
                serial_number="92632500000001",
            )
        )

        diagnostics = coordinator.device_registry_diagnostics()

        self.assertEqual(
            diagnostics["topology_status"],
            "duplicate_inverter_children",
        )
        self.assertEqual(diagnostics["direct_child_count"], 2)
        self.assertEqual(diagnostics["unexpected_direct_child_count"], 1)
        self.assertEqual(diagnostics["relevant_device_count"], 3)
        self.assertEqual(
            [record["role"] for record in diagnostics["devices"]],
            [
                "canonical_collector",
                "canonical_inverter",
                "unexpected_collector_child",
            ],
        )
        self.assertEqual(diagnostics["devices"][1]["entity_count"], 2)
        self.assertEqual(diagnostics["devices"][1]["disabled_entity_count"], 1)
        self.assertFalse(diagnostics["devices"][2]["belongs_to_current_entry"])
        self.assertEqual(diagnostics["devices"][2]["live_config_entry_count"], 0)
        self.assertEqual(diagnostics["devices"][2]["missing_config_entry_count"], 1)
        self.assertTrue(diagnostics["devices"][2]["safe_cleanup_candidate"])
        serialized = str(diagnostics)
        self.assertNotIn("SECRET", serialized)
        self.assertNotIn("entry-1", serialized)
        self.assertNotIn("legacy-entry", serialized)

    def test_sync_removes_only_empty_orphaned_inverter_children(self) -> None:
        registry = FakeRegistry()
        self.coordinator_module.dr.async_get = lambda hass: registry

        collector = registry.async_get_or_create(
            config_entry_id="entry-1",
            identifiers={("eybond_local", "entry-1:collector")},
            name="Collector",
        )
        orphan = registry.async_get_or_create(
            config_entry_id="removed-entry",
            identifiers={("eybond_local", "removed-entry")},
            name="Old inverter",
            via_device=("eybond_local", "entry-1:collector"),
        )
        live_foreign = registry.async_get_or_create(
            config_entry_id="live-entry",
            identifiers={("eybond_local", "live-entry")},
            name="Live inverter",
            via_device=("eybond_local", "entry-1:collector"),
        )
        orphan_with_entity = registry.async_get_or_create(
            config_entry_id="removed-with-entity",
            identifiers={("eybond_local", "removed-with-entity")},
            name="Old inverter with entity",
            via_device=("eybond_local", "entry-1:collector"),
        )
        customized_orphan = registry.async_get_or_create(
            config_entry_id="removed-customized",
            identifiers={("eybond_local", "removed-customized")},
            name="Customized old inverter",
            via_device=("eybond_local", "entry-1:collector"),
        )
        customized_orphan.name_by_user = "Keep me"

        class _EntityRegistry:
            entries_by_device = {
                orphan_with_entity.id: (types.SimpleNamespace(disabled_by=None),),
            }

        entity_registry_module = sys.modules["homeassistant.helpers.entity_registry"]
        entity_registry_module.async_get = lambda hass: _EntityRegistry()
        entity_registry_module.async_entries_for_device = (
            lambda entity_registry, device_id, **kwargs: (
                entity_registry.entries_by_device.get(device_id, ())
            )
        )

        live_entries = {"entry-1", "live-entry"}
        coordinator = object.__new__(self.coordinator_module.EybondLocalCoordinator)
        coordinator.hass = types.SimpleNamespace(
            config_entries=types.SimpleNamespace(
                async_get_entry=lambda entry_id: (
                    object() if entry_id in live_entries else None
                )
            )
        )
        coordinator.config_entry = types.SimpleNamespace(
            entry_id="entry-1",
            data={
                "detected_model": "Anenji ANJ-11KW-48V-WIFI-P",
                "detected_serial": "INV-001",
            },
            options={},
            title="Anenji",
        )
        coordinator.data = self.RuntimeSnapshot(
            inverter=types.SimpleNamespace(
                model_name="Anenji ANJ-11KW-48V-WIFI-P",
                serial_number="INV-001",
                details={},
            )
        )
        coordinator._last_synced_device_meta = ("", "", "", "", "")

        coordinator._async_sync_inverter_device_registry()

        inverter = registry.async_get_device(
            identifiers={("eybond_local", "entry-1")}
        )
        self.assertIsNotNone(inverter)
        self.assertEqual(inverter.via_device_id, collector.id)
        self.assertEqual(registry.removed_device_ids, [orphan.id])
        self.assertIsNone(
            registry.async_get_device(
                identifiers={("eybond_local", "removed-entry")}
            )
        )
        for retained in (live_foreign, orphan_with_entity, customized_orphan):
            retained_device = registry.async_get_device(
                identifiers=retained.identifiers
            )
            self.assertIsNotNone(retained_device)
            self.assertIsNone(retained_device.via_device_id)

    def test_sync_device_registry_clears_untrusted_pi30_placeholder(self) -> None:
        class _PreservingRegistry(FakeRegistry):
            def async_get_or_create(self, config_entry_id=None, **info):
                identifiers = set(info.get("identifiers") or set())
                existing = self.async_get_device(identifiers=identifiers)
                prior_serial = None if existing is None else existing.serial_number
                device = super().async_get_or_create(config_entry_id, **info)
                if "serial_number" not in info:
                    device.serial_number = prior_serial
                return device

        registry = _PreservingRegistry()
        self.coordinator_module.dr.async_get = lambda hass: registry
        inverter_device = registry.async_get_or_create(
            config_entry_id="entry-1",
            identifiers={("eybond_local", "entry-1")},
            name="PI30 4200",
            serial_number="55355535553555",
        )

        coordinator = object.__new__(self.coordinator_module.EybondLocalCoordinator)
        coordinator.hass = object()
        coordinator.config_entry = types.SimpleNamespace(
            entry_id="entry-1",
            data={
                "detected_model": "PI30 4200",
                "detected_serial": "55355535553555",
            },
            options={},
            title="Collector PN Q0000000000001",
        )
        coordinator.data = self.RuntimeSnapshot(
            inverter=types.SimpleNamespace(
                driver_key="pi30",
                model_name="PI30 4200",
                serial_number="",
                details={
                    "reported_serial_number": "55355535553555",
                    "serial_identity_source": "qid",
                    "serial_identity_trust": "untrusted",
                    "serial_identity_reason": "known_placeholder",
                },
            )
        )
        coordinator._last_synced_device_meta = ("", "", "", "", "")

        coordinator._async_sync_inverter_device_registry()

        self.assertIsNone(inverter_device.serial_number)

    def test_pending_entry_uses_collector_scope_until_inverter_identity_exists(self) -> None:
        registry = FakeRegistry()
        self.coordinator_module.dr.async_get = lambda hass: registry

        coordinator = object.__new__(self.coordinator_module.EybondLocalCoordinator)
        coordinator.hass = object()
        coordinator.config_entry = types.SimpleNamespace(
            entry_id="entry-1",
            data={
                "collector_pn": "COL-001",
                "detected_model": "",
                "detected_serial": "",
                "driver_hint": "modbus_smg",
            },
            options={},
            title="Collector PN COL-001",
        )
        coordinator.data = self.RuntimeSnapshot(
            values={"collector_type": "Wi-Fi.DTU"},
            inverter=types.SimpleNamespace(
                model_name="",
                serial_number="",
                driver_key="modbus_smg",
                register_schema_name="smg_v1",
                capabilities=(),
                capability_presets=(),
            ),
            collector=types.SimpleNamespace(
                collector_pn="COL-001",
                profile_name="EyeBond ASCII PN v1",
                smartess_protocol_name=None,
                smartess_protocol_asset_name=None,
                smartess_collector_version="1.2.3",
            ),
        )
        coordinator._last_synced_device_meta = ("", "", "", "", "")
        coordinator._last_synced_collector_device_meta = ("", "", "", "", "", "")

        stale_inverter = registry.async_get_or_create(
            config_entry_id="entry-1",
            identifiers={("eybond_local", "entry-1")},
            name="Collector PN COL-001",
            manufacturer="OEM / EyeBond",
        )

        with patch.object(self.coordinator_module, "get_driver") as get_driver:
            self.assertIsNone(coordinator.identified_inverter)
            self.assertFalse(coordinator.has_inverter_identity)
            self.assertIsNone(coordinator.current_driver)
            get_driver.assert_not_called()
            self.assertEqual(
                coordinator.inverter_device_info()["identifiers"],
                {("eybond_local", "entry-1:collector")},
            )

        coordinator.async_sync_device_registry()

        collector = registry.async_get_device(
            identifiers={("eybond_local", "entry-1:collector")}
        )
        inverter = registry.async_get_device(
            identifiers={("eybond_local", "entry-1")}
        )

        self.assertIsNotNone(collector)
        self.assertIsNone(inverter)
        self.assertEqual(registry.removed_device_ids, [stale_inverter.id])

    def test_snapshot_backed_setup_uses_persisted_anenji_metadata_without_live_inverter(self) -> None:
        fake_driver = types.SimpleNamespace(key="modbus_smg", name="SMG / Modbus")
        fake_selection = types.SimpleNamespace(
            effective_owner_key="modbus_smg",
            effective_owner_name="SMG-family runtime",
            profile_name="modbus_smg/models/anenji_4200_protocol_1.json",
            register_schema_name="modbus_smg/models/anenji_4200_protocol_1.json",
            profile_metadata=types.SimpleNamespace(
                driver_key="modbus_smg",
                protocol_family="modbus_smg",
                source_name="modbus_smg/models/anenji_4200_protocol_1.json",
                groups=(types.SimpleNamespace(key="config", title="Config", order=1),),
                capabilities=(types.SimpleNamespace(key="boot_method"),),
                presets=(types.SimpleNamespace(key="normal"),),
            ),
            register_schema_metadata=types.SimpleNamespace(
                driver_key="modbus_smg",
                protocol_family="modbus_smg",
                source_name="modbus_smg/models/anenji_4200_protocol_1.json",
            ),
        )

        coordinator = object.__new__(self.coordinator_module.EybondLocalCoordinator)
        coordinator.hass = object()
        coordinator.config_entry = types.SimpleNamespace(
            entry_id="entry-1",
            data={"driver_hint": "auto"},
            options={
                "effective_metadata_snapshot": {
                    "effective_owner_key": "modbus_smg",
                    "effective_owner_name": "SMG-family runtime",
                    "profile_name": "modbus_smg/models/anenji_4200_protocol_1.json",
                    "register_schema_name": "modbus_smg/models/anenji_4200_protocol_1.json",
                    "confidence": "high",
                    "generation": 4,
                    "generated_at": "2026-06-03T19:00:00+00:00",
                }
            },
            title="SMG 6200",
        )
        coordinator.data = self.RuntimeSnapshot(values={}, inverter=None, collector=None)

        with patch.object(
            self.coordinator_inverter_profile_module,
            "resolve_effective_metadata_selection",
            return_value=fake_selection,
        ), patch.object(
            self.platform_context_module,
            "get_driver",
            side_effect=lambda key: fake_driver if key == fake_driver.key else None,
        ):
            driver, inverter, has_inverter_identity = self.platform_context_module.entity_setup_context(
                coordinator.config_entry,
                coordinator,
            )

        self.assertIsNotNone(driver)
        self.assertEqual(getattr(driver, "key", ""), "modbus_smg")
        self.assertIsNotNone(inverter)
        self.assertEqual(inverter.profile_name, "modbus_smg/models/anenji_4200_protocol_1.json")
        self.assertEqual(
            inverter.register_schema_name,
            "modbus_smg/models/anenji_4200_protocol_1.json",
        )
        self.assertGreater(len(inverter.capabilities), 0)
        self.assertFalse(has_inverter_identity)

    def test_snapshot_backed_setup_is_not_synthesized_without_persisted_snapshot(self) -> None:
        coordinator = object.__new__(self.coordinator_module.EybondLocalCoordinator)
        coordinator.hass = object()
        coordinator.config_entry = types.SimpleNamespace(
            entry_id="entry-1",
            data={"driver_hint": "auto"},
            options={},
            title="SMG 6200",
        )
        coordinator.data = self.RuntimeSnapshot(values={}, inverter=None, collector=None)

        with patch.object(
            self.coordinator_inverter_profile_module,
            "resolve_effective_metadata_selection",
            side_effect=AssertionError("resolver must not run without valid snapshot"),
        ), patch.object(
            self.platform_context_module,
            "get_driver",
            side_effect=AssertionError("driver lookup must not run without valid snapshot"),
        ):
            driver, inverter, has_inverter_identity = self.platform_context_module.entity_setup_context(
                coordinator.config_entry,
                coordinator,
            )

        self.assertIsNone(driver)
        self.assertIsNone(inverter)
        self.assertFalse(has_inverter_identity)

    def test_shadow_learning_effective_metadata_falls_back_to_live_for_partial_tier(self) -> None:
        # Partial-tier devices persist NO snapshot, so the learning start path
        # must fall back to the LIVE effective metadata (base schema) instead of
        # seeding with the empty persisted snapshot — otherwise it blocks with
        # missing_effective_metadata_snapshot on exactly the devices learning is
        # for. This property is the single source of truth shared with the
        # config-flow preflight.
        coordinator = object.__new__(self.coordinator_module.EybondLocalCoordinator)
        coordinator.hass = object()
        coordinator.config_entry = types.SimpleNamespace(
            entry_id="entry-1",
            data={"driver_hint": "auto"},
            options={},
            title="SMG Family",
        )
        coordinator.data = self.RuntimeSnapshot(values={}, inverter=None, collector=None)

        family_selection = types.SimpleNamespace(
            effective_owner_key="modbus_smg",
            effective_owner_name="SMG-family runtime",
            profile_name="",
            register_schema_name="modbus_smg/base.json",
        )
        with patch.object(
            self.coordinator_inverter_profile_module,
            "resolve_effective_metadata_selection",
            return_value=family_selection,
        ):
            result = coordinator.shadow_learning_effective_metadata

        self.assertEqual(result["register_schema_name"], "modbus_smg/base.json")
        self.assertEqual(result["profile_name"], "")

    def test_shadow_learning_effective_metadata_prefers_persisted_snapshot(self) -> None:
        coordinator = object.__new__(self.coordinator_module.EybondLocalCoordinator)
        coordinator.hass = object()
        coordinator.config_entry = types.SimpleNamespace(
            entry_id="entry-1",
            data={"driver_hint": "auto"},
            options={
                "effective_metadata_snapshot": {
                    "effective_owner_key": "modbus_smg",
                    "effective_owner_name": "SMG-family runtime",
                    "profile_name": "smg_modbus.json",
                    "register_schema_name": "modbus_smg/models/smg_6200.json",
                    "confidence": "high",
                    "generation": 4,
                    "generated_at": "2026-06-03T19:00:00+00:00",
                }
            },
            title="SMG 6200",
        )
        coordinator.data = self.RuntimeSnapshot(values={}, inverter=None, collector=None)

        result = coordinator.shadow_learning_effective_metadata

        self.assertEqual(result.register_schema_name, "modbus_smg/models/smg_6200.json")

    def test_snapshot_backed_setup_is_not_synthesized_for_invalid_snapshot_payload(self) -> None:
        coordinator = object.__new__(self.coordinator_module.EybondLocalCoordinator)
        coordinator.hass = object()
        coordinator.config_entry = types.SimpleNamespace(
            entry_id="entry-1",
            data={"driver_hint": "auto"},
            options={
                "effective_metadata_snapshot": {
                    "effective_owner_key": "modbus_smg",
                    "profile_name": "modbus_smg/models/anenji_4200_protocol_1.json",
                    "register_schema_name": "modbus_smg/models/anenji_4200_protocol_1.json",
                    "confidence": "none",
                }
            },
            title="SMG 6200",
        )
        coordinator.data = self.RuntimeSnapshot(values={}, inverter=None, collector=None)

        with patch.object(
            self.coordinator_inverter_profile_module,
            "resolve_effective_metadata_selection",
            side_effect=AssertionError("resolver must not run for invalid snapshot payload"),
        ), patch.object(
            self.platform_context_module,
            "get_driver",
            side_effect=AssertionError("driver lookup must not run for invalid snapshot payload"),
        ):
            driver, inverter, has_inverter_identity = self.platform_context_module.entity_setup_context(
                coordinator.config_entry,
                coordinator,
            )

        self.assertIsNone(driver)
        self.assertIsNone(inverter)
        self.assertFalse(has_inverter_identity)

    def test_remembered_external_endpoint_is_persisted_and_reused_for_rollback(self) -> None:
        updated_options: list[dict[str, object]] = []

        class _ConfigEntries:
            def async_update_entry(self, entry, *, title=None, data=None, options=None) -> None:
                del title, data
                entry.options = dict(options or {})
                updated_options.append(dict(entry.options))

        coordinator = object.__new__(self.coordinator_module.EybondLocalCoordinator)
        coordinator.hass = types.SimpleNamespace(config_entries=_ConfigEntries())
        coordinator.config_entry = types.SimpleNamespace(
            entry_id="entry-1",
            data={},
            options={},
            title="Collector PN COL-001",
        )
        coordinator._connection_spec = types.SimpleNamespace(
            effective_advertised_server_ip="192.168.1.50",
            effective_advertised_tcp_port=8899,
        )
        coordinator._runtime = types.SimpleNamespace(
            collector_server_endpoint_rollback_target="",
        )
        coordinator._remembered_collector_server_endpoint = ""

        snapshot = self.RuntimeSnapshot(
            values={"collector_server_endpoint": "47.91.67.66,18899,TCP"}
        )

        import asyncio

        asyncio.run(coordinator._async_remember_collector_server_endpoint(snapshot))

        self.assertEqual(
            coordinator.collector_server_endpoint_rollback_target,
            "47.91.67.66,18899,TCP",
        )
        self.assertEqual(len(updated_options), 1)
        self.assertEqual(
            updated_options[0]["collector_original_server_endpoint"],
            "47.91.67.66,18899,TCP",
        )
        self.assertEqual(
            updated_options[0]["collector_original_server_endpoint_profile_key"],
            "smartess_at",
        )
        self.assertEqual(
            updated_options[0]["collector_original_server_endpoint_source"],
            "runtime_observed",
        )
        self.assertTrue(updated_options[0]["collector_original_server_endpoint_observed_at"])

    def test_remember_collector_server_endpoint_does_not_replace_existing_original(self) -> None:
        coordinator = object.__new__(self.coordinator_module.EybondLocalCoordinator)
        updated_options: list[dict[str, str]] = []
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
        coordinator._remembered_collector_server_endpoint = "ess.eybond.com"
        coordinator.config_entry = types.SimpleNamespace(
            data={},
            options={
                "collector_original_server_endpoint": "ess.eybond.com",
                "collector_original_server_endpoint_profile_key": "legacy_binary",
            },
        )

        snapshot = self.RuntimeSnapshot(
            values={"collector_server_endpoint": "dtu_ess.eybond.com,18899,TCP"}
        )

        import asyncio

        asyncio.run(coordinator._async_remember_collector_server_endpoint(snapshot))

        self.assertEqual(coordinator.collector_server_endpoint_rollback_target, "ess.eybond.com")
        self.assertEqual(updated_options, [])

    def test_restore_collector_original_endpoint_from_registry(self) -> None:
        from custom_components.eybond_local.support.collector_registry import (
            remember_collector_original_endpoint,
        )

        async def _run() -> None:
            with tempfile.TemporaryDirectory() as tmp:
                remember_collector_original_endpoint(
                    config_dir=Path(tmp),
                    collector_pn="PN12345",
                    original_endpoint_raw="ess.eybond.com",
                    cloud_profile_key="legacy_binary",
                    source="test_registry",
                    observed_at="2026-06-22T10:00:00+00:00",
                    last_seen_ip="192.168.1.55",
                )
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
                    data={"collector_pn": "PN12345"},
                    options={},
                )
                snapshot = self.RuntimeSnapshot(values={})

                await coordinator._async_restore_collector_original_endpoint_from_registry(
                    snapshot
                )

                self.assertEqual(
                    coordinator.collector_server_endpoint_rollback_target,
                    "ess.eybond.com",
                )
                self.assertEqual(len(updated_options), 1)
                self.assertEqual(
                    updated_options[0]["collector_original_server_endpoint"],
                    "ess.eybond.com",
                )
                self.assertEqual(
                    updated_options[0]["collector_original_server_endpoint_profile_key"],
                    "legacy_binary",
                )
                self.assertEqual(
                    updated_options[0]["collector_original_server_endpoint_source"],
                    "test_registry",
                )

        import asyncio

        asyncio.run(_run())

    def test_restore_collector_original_endpoint_from_registry_by_unique_last_seen_ip(self) -> None:
        from custom_components.eybond_local.support.collector_registry import (
            remember_collector_original_endpoint,
        )

        async def _run() -> None:
            with tempfile.TemporaryDirectory() as tmp:
                remember_collector_original_endpoint(
                    config_dir=Path(tmp),
                    collector_pn="E50000200000000001",
                    original_endpoint_raw="iot.eybond.com,18899,TCP",
                    cloud_profile_key="valuecloud_at",
                    source="test_registry",
                    observed_at="2026-06-24T20:52:14+00:00",
                    last_seen_ip="192.168.8.110",
                )
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
                    effective_advertised_server_ip="192.168.8.113",
                    effective_advertised_tcp_port=8899,
                )
                coordinator._runtime = types.SimpleNamespace(
                    collector_server_endpoint_rollback_target="",
                )
                coordinator._remembered_collector_server_endpoint = ""
                coordinator.config_entry = types.SimpleNamespace(
                    data={
                        "collector_pn": "E5000020000000",
                        "collector_ip": "192.168.8.110",
                    },
                    options={},
                )
                snapshot = self.RuntimeSnapshot(
                    collector=types.SimpleNamespace(remote_ip="192.168.8.110"),
                    values={},
                )

                await coordinator._async_restore_collector_original_endpoint_from_registry(
                    snapshot
                )

                self.assertEqual(
                    coordinator.collector_server_endpoint_rollback_target,
                    "iot.eybond.com,18899,TCP",
                )
                self.assertEqual(len(updated_options), 1)
                self.assertEqual(
                    updated_options[0]["collector_original_server_endpoint"],
                    "iot.eybond.com,18899,TCP",
                )
                self.assertEqual(
                    updated_options[0]["collector_original_server_endpoint_profile_key"],
                    "valuecloud_at",
                )

        import asyncio

        asyncio.run(_run())

    def test_restore_collector_original_endpoint_by_ip_fails_closed_when_ambiguous(self) -> None:
        from custom_components.eybond_local.support.collector_registry import (
            remember_collector_original_endpoint,
        )

        async def _run() -> None:
            with tempfile.TemporaryDirectory() as tmp:
                for pn in ("PN12345", "PN67890"):
                    remember_collector_original_endpoint(
                        config_dir=Path(tmp),
                        collector_pn=pn,
                        original_endpoint_raw="iot.eybond.com,18899,TCP",
                        cloud_profile_key="valuecloud_at",
                        last_seen_ip="192.168.8.110",
                    )
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
                    effective_advertised_server_ip="192.168.8.113",
                    effective_advertised_tcp_port=8899,
                )
                coordinator._runtime = types.SimpleNamespace(
                    collector_server_endpoint_rollback_target="",
                )
                coordinator._remembered_collector_server_endpoint = ""
                coordinator.config_entry = types.SimpleNamespace(
                    data={"collector_ip": "192.168.8.110"},
                    options={},
                )
                snapshot = self.RuntimeSnapshot(
                    collector=types.SimpleNamespace(remote_ip="192.168.8.110"),
                    values={},
                )

                await coordinator._async_restore_collector_original_endpoint_from_registry(
                    snapshot
                )

                self.assertEqual(coordinator.collector_server_endpoint_rollback_target, "")
                self.assertEqual(updated_options, [])

        import asyncio

        asyncio.run(_run())

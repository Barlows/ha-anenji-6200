from __future__ import annotations

import ast
import asyncio
from dataclasses import dataclass, replace
import json
from pathlib import Path
import subprocess
import enum
import itertools
import sys
import tempfile
import threading
import types
import unittest
from contextlib import contextmanager, suppress
from unittest.mock import AsyncMock, Mock, patch, sentinel
import zipfile


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _install_homeassistant_stubs() -> None:
    voluptuous = types.ModuleType("voluptuous")
    ha = sys.modules.get("homeassistant") or types.ModuleType("homeassistant")
    config_entries = types.ModuleType("homeassistant.config_entries")
    core = types.ModuleType("homeassistant.core")
    data_entry_flow = types.ModuleType("homeassistant.data_entry_flow")
    helpers = types.ModuleType("homeassistant.helpers")
    entity_registry = types.ModuleType("homeassistant.helpers.entity_registry")
    selector = types.ModuleType("homeassistant.helpers.selector")
    util = types.ModuleType("homeassistant.util")
    util_ulid = types.ModuleType("homeassistant.util.ulid")

    _ulid_counter = itertools.count(1)

    def ulid_now() -> str:
        """Deterministic ULID-shaped id for tests (26 chars, Crockford base32)."""

        return f"01TEST{next(_ulid_counter):020d}"[:26].upper()

    util_ulid.ulid_now = ulid_now
    util.ulid = util_ulid

    class ConfigFlow:
        def __init_subclass__(cls, **kwargs):
            return super().__init_subclass__()

        def async_show_menu(self, *, step_id, menu_options, description_placeholders=None):
            return {
                "type": "menu",
                "step_id": step_id,
                "menu_options": list(menu_options),
                "description_placeholders": description_placeholders or {},
            }

        def async_show_form(self, *, step_id, data_schema=None, errors=None, description_placeholders=None):
            return {
                "type": "form",
                "step_id": step_id,
                "data_schema": data_schema,
                "errors": errors or {},
                "description_placeholders": description_placeholders or {},
            }

        def async_show_progress(self, *, step_id, progress_action, progress_task, description_placeholders=None):
            return {
                "type": "progress",
                "step_id": step_id,
                "progress_action": progress_action,
                "progress_task": progress_task,
                "description_placeholders": description_placeholders or {},
            }

        def async_show_progress_done(self, *, next_step_id):
            return {
                "type": "progress_done",
                "next_step_id": next_step_id,
            }

        def async_update_progress(self, progress):
            self._test_progress = progress

        async def async_set_unique_id(self, unique_id):
            self._test_unique_id = unique_id

        def _abort_if_unique_id_configured(self):
            return None

        def async_create_entry(self, *, title, data, options=None):
            result = {"type": "create_entry", "title": title, "data": data}
            if options is not None:
                result["options"] = options
            return result

        def async_abort(self, *, reason):
            return {"type": "abort", "reason": reason}

        def async_update_reload_and_abort(
            self, entry, *, unique_id=None, title=None, data=None, options=None, **_kwargs
        ):
            if data is not None:
                entry.data = data
            if options is not None:
                entry.options = options
            if unique_id is not None:
                entry.unique_id = unique_id
                self._test_unique_id = unique_id
            if title is not None:
                entry.title = title
            return {
                "type": "abort",
                "reason": "reconfigure_successful",
                "entry": entry,
                "unique_id": unique_id,
                "data": data,
            }

    class OptionsFlow:
        def async_show_menu(self, *, step_id, menu_options, description_placeholders=None):
            return {
                "type": "menu",
                "step_id": step_id,
                "menu_options": list(menu_options),
                "description_placeholders": description_placeholders or {},
            }

        def async_show_form(self, *, step_id, data_schema=None, errors=None, description_placeholders=None):
            return {
                "type": "form",
                "step_id": step_id,
                "data_schema": data_schema,
                "errors": errors or {},
                "description_placeholders": description_placeholders or {},
            }

        def async_show_progress(self, *, step_id, progress_action, progress_task, description_placeholders=None):
            return {
                "type": "progress",
                "step_id": step_id,
                "progress_action": progress_action,
                "progress_task": progress_task,
                "description_placeholders": description_placeholders or {},
            }

        def async_show_progress_done(self, *, next_step_id):
            return {
                "type": "progress_done",
                "next_step_id": next_step_id,
            }

        def async_update_progress(self, progress):
            self._test_progress = progress

        def async_create_entry(self, *, data):
            return {"type": "create_entry", "data": data}

    def callback(func):
        return func

    class HomeAssistant:
        pass

    def split_entity_id(entity_id):
        return tuple(str(entity_id).split(".", 1))

    class SupportsResponse:
        ONLY = "only"

    def section(schema, _options=None):
        return schema

    class _SelectorConfig:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs

    class _Selector:
        def __init__(self, config=None):
            self.config = config

    class SelectOptionDict(dict):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)

    class Schema:
        def __init__(self, schema):
            self.schema = schema

    _UNDEFINED_DEFAULT = object()

    class _RequiredWithDefault(str):
        """String-compatible stub preserving Voluptuous default metadata."""

        def __new__(cls, key, default):
            value = super().__new__(cls, key)
            value.schema = key
            value._default = default
            return value

        def default(self):
            return self._default

    def Required(key, default=_UNDEFINED_DEFAULT):
        if default is _UNDEFINED_DEFAULT:
            return key
        return _RequiredWithDefault(key, default)

    def Optional(key, default=None):
        return key

    def All(*validators):
        return validators

    def Range(**kwargs):
        return kwargs

    def In(value):
        return value

    config_entries.ConfigFlow = ConfigFlow
    config_entries.ConfigFlowResult = dict
    config_entries.OptionsFlow = OptionsFlow

    class ConfigEntryState(enum.Enum):
        LOADED = "loaded"
        NOT_LOADED = "not_loaded"
        SETUP_ERROR = "setup_error"
        SETUP_RETRY = "setup_retry"
        MIGRATION_ERROR = "migration_error"
        FAILED_UNLOAD = "failed_unload"

    config_entries.ConfigEntryState = ConfigEntryState
    core.HomeAssistant = HomeAssistant
    core.callback = callback
    core.split_entity_id = split_entity_id
    core.SupportsResponse = SupportsResponse
    data_entry_flow.section = section

    selector.BooleanSelector = _Selector
    selector.NumberSelector = _Selector
    selector.NumberSelectorConfig = _SelectorConfig
    selector.NumberSelectorMode = types.SimpleNamespace(BOX="box", SLIDER="slider")
    selector.SelectOptionDict = SelectOptionDict
    selector.SelectSelector = _Selector
    selector.SelectSelectorConfig = _SelectorConfig
    selector.SelectSelectorMode = types.SimpleNamespace(DROPDOWN="dropdown", LIST="list")
    selector.TextSelector = _Selector
    selector.TextSelectorConfig = _SelectorConfig

    entity_registry.async_get = lambda _hass: None
    entity_registry.async_entries_for_config_entry = lambda *_args, **_kwargs: []
    helpers.entity_registry = entity_registry

    voluptuous.Schema = Schema
    voluptuous.Required = Required
    voluptuous.Optional = Optional
    voluptuous.All = All
    voluptuous.Range = Range
    voluptuous.In = In

    sys.modules["voluptuous"] = voluptuous
    sys.modules["homeassistant"] = ha
    sys.modules["homeassistant.config_entries"] = config_entries
    sys.modules["homeassistant.core"] = core
    sys.modules["homeassistant.data_entry_flow"] = data_entry_flow
    sys.modules["homeassistant.helpers"] = helpers
    sys.modules["homeassistant.helpers.entity_registry"] = entity_registry
    sys.modules["homeassistant.helpers.selector"] = selector
    sys.modules["homeassistant.util"] = util
    sys.modules["homeassistant.util.ulid"] = util_ulid


_install_homeassistant_stubs()


import custom_components.eybond_local.flows.config.admission as config_admission_module
import custom_components.eybond_local.flows.config.ble as config_ble_module
import custom_components.eybond_local.flows.config.common as config_common_module
import custom_components.eybond_local.flows.config.network as config_network_module
import custom_components.eybond_local.flows.config.scan as config_scan_module
import custom_components.eybond_local.connection.admission_transaction as admission_transaction_module
import custom_components.eybond_local.const as const_module
import custom_components.eybond_local.options_flow as options_flow_module
import custom_components.eybond_local.flows.options.proxy as options_proxy_module
import custom_components.eybond_local.flows.options.shadow_inactive_draft as options_shadow_inactive_draft_module
import custom_components.eybond_local.flows.options.shadow_review as options_shadow_review_module
import custom_components.eybond_local.flows.options.shadow_run as options_shadow_run_module
import custom_components.eybond_local.flows.options.shadow_runtime as options_shadow_runtime_module
import custom_components.eybond_local.flows.options.shared as options_shared_module
import custom_components.eybond_local.support.cloud_control_discovery as cloud_control_discovery_module
import custom_components.eybond_local.support.cloud_read_only_workflow as cloud_read_only_workflow_module
from custom_components.eybond_local.dessmonitor_history import (
    DESSMONITOR_HISTORY_SOURCE_SOLE_CHART,
)
from custom_components.eybond_local.support.cloud_history_evidence import (
    CLOUD_HISTORY_AUTHORITY,
    CloudHistoryCollection,
    CloudHistoryIdentity,
    CloudHistoryPoint,
    CloudHistorySeries,
)
from custom_components.eybond_local.support.cloud_semantic_evidence import (
    CLOUD_FIELD_KIND_CHART,
)
from custom_components.eybond_local.support.cloud_local_history_draft_writer import (
    CloudLocalReadDraftArtifact,
)
from custom_components.eybond_local.drivers.local_register_evidence import (
    LocalRegisterBlockObservation,
    LocalRegisterReadPlan,
    LocalRegisterSnapshot,
)
from custom_components.eybond_local.drivers.local_register_series import (
    LocalRegisterSeriesPlan,
    LocalRegisterSnapshotSeries,
)
from custom_components.eybond_local.drivers.local_register_evidence import LocalRegisterCollectionAvailability
from custom_components.eybond_local.support.local_register_collection import (
    LOCAL_REGISTER_COLLECTION_STATE_RUNNING,
    LocalRegisterCollectionStatus,
)
from custom_components.eybond_local.support.cloud_local_history_representability import (
    LocalRegisterOverlayContext,
)
from custom_components.eybond_local.support.cloud_learning_runner import CloudLearningOutcome
from custom_components.eybond_local.support.cloud_learning_models import (
    LEARNING_METHOD_ACTIVE_CORRELATION,
    LEARNING_METHOD_READ_ONLY_EVIDENCE,
)
from custom_components.eybond_local.telemetry import (
    TelemetryFreshness,
    TelemetryPoint,
    TypedTelemetryFrame,
)
from custom_components.eybond_local.flows.config.ble import (
    BLE_ACTION_APPLY,
    BLE_ACTION_RESCAN,
    BLE_ACTION_REFRESH_WIFI,
    CONF_BLE_ACTION,
)
from custom_components.eybond_local.config_flow import EybondLocalConfigFlow
from custom_components.eybond_local.flows.config.scan import CONF_RESULT_KEY
from custom_components.eybond_local.flows.common.presentation import (
    CONF_WIFI_PASSWORD,
    CONF_WIFI_SSID,
    _flatten_sections,
    _poll_interval_selector,
)
from custom_components.eybond_local.network_interfaces import (
    get_ipv4_interfaces as _get_ipv4_interfaces,
)
from custom_components.eybond_local.flows.options.diagnostics import (
    CONF_SUPPORT_ARCHIVE_SMARTESS_CLOUD_MODE,
    SUPPORT_ARCHIVE_SMARTESS_CLOUD_MODE_ARCHIVE_ONLY,
    SUPPORT_ARCHIVE_SMARTESS_CLOUD_MODE_REFRESH,
    SUPPORT_ARCHIVE_SMARTESS_CLOUD_MODE_USE_SAVED,
)
from custom_components.eybond_local.options_flow import EybondLocalOptionsFlow
from custom_components.eybond_local.flows.options.runtime import (
    COLLECTOR_UART_ACTION_APPLY,
    COLLECTOR_WIFI_ACTION_APPLY,
    COLLECTOR_WIFI_ACTION_REFRESH,
    CONF_COLLECTOR_UART_ACTION,
    CONF_COLLECTOR_UART_BAUDRATE,
    CONF_COLLECTOR_WIFI_ACTION,
    CONF_CONFIRM_COLLECTOR_UART_APPLY,
    CONF_CONFIRM_COLLECTOR_WIFI_APPLY,
)


def _adopt_recovery_for_test(flow, outcome):
    """Place a produced recovery outcome at the real transaction boundary.

    Older scenario tests construct the outcome directly instead of running the
    wire authority. They still exercise the production transaction's exact-object
    adoption and owner replacement; no properties or methods are added to the
    config-flow class.
    """

    txn = flow._callback_continuation
    previous_registry = txn.registry
    previous_owner = txn.owner
    txn._produced_recovery_outcome = outcome
    txn._recovery_outcome = None
    txn._state = "recovery_consumed"
    adopted = txn.adopt_recovery(outcome)
    if adopted and previous_registry is not None and previous_owner:
        if previous_owner != txn.owner:
            previous_registry.release(previous_owner)
    return adopted
from custom_components.eybond_local.support.bundle import build_support_bundle_payload
from custom_components.eybond_local.support.package import (
    build_shadow_learning_runtime_values,
    export_support_package,
)
from custom_components.eybond_local.support.shadow_learning.review_model import (
    attach_learned_read_review_model,
    build_learned_control_review_model,
)
from custom_components.eybond_local.collector.smartess_ble import SmartEssBleCandidate
from custom_components.eybond_local.collector.smartess_ble import (
    SmartEssBleError,
    SmartEssBleProvisionBranch,
    SmartEssBleProvisioningInfo,
    SmartEssBleProvisionOutcome,
    SmartEssBleProvisionResult,
    SmartEssBleWifiNetwork,
)
from custom_components.eybond_local.collector.collector_wire import (
    QUERY_HARDWARE_VERSION,
    QUERY_SERIAL_BAUDRATE,
    SET_TARGET_PASSWORD,
    SET_TARGET_SSID,
)
from custom_components.eybond_local.collector.capabilities import (
    COLLECTOR_KIND_ESP_EYBOND_BRIDGE,
    COLLECTOR_KIND_UNKNOWN,
)
from custom_components.eybond_local.const import (
    COLLECTOR_OPERATION_HA_ONLY,
    CONF_COLLECTOR_CLOUD_FAMILY,
    CONF_COLLECTOR_IP,
    CONF_COLLECTOR_ORIGINAL_SERVER_ENDPOINT,
    CONF_COLLECTOR_ORIGINAL_SERVER_ENDPOINT_OBSERVED_AT,
    CONF_COLLECTOR_ORIGINAL_SERVER_ENDPOINT_PROFILE_KEY,
    CONF_COLLECTOR_ORIGINAL_SERVER_ENDPOINT_SOURCE,
    CONF_COLLECTOR_OPERATION_MODE,
    CONF_CONNECTION_STRATEGY,
    CONF_DRIVER_DETECTION_STRATEGY,
    CONF_PROXY_CAPTURE_DURATION_MINUTES,
    CONF_PROXY_ENABLED,
    CONNECTION_STRATEGY_CALLBACK_ON_DEMAND,
    CONNECTION_STRATEGY_INBOUND,
    DOMAIN,
    DRIVER_DETECTION_FULL_SCAN,
    DEFAULT_PROXY_CAPTURE_DURATION_MINUTES,
    CONF_DRIVER_HINT,
    CONF_SMARTESS_COLLECTOR_VERSION,
    CONF_SMARTESS_DEVICE_ADDRESS,
    CONF_SMARTESS_PROFILE_KEY,
    CONF_SMARTESS_PROTOCOL_ASSET_ID,
)
from custom_components.eybond_local.metadata.local_metadata import (
    local_profile_path,
    local_register_schema_path,
)
from custom_components.eybond_local.metadata.profile_loader import load_driver_profile
from custom_components.eybond_local.metadata.register_schema_loader import load_register_schema
from custom_components.eybond_local.connection.admission import (
    CollectorAdmissionRequest,
    ObservedCollectorSession,
)
from custom_components.eybond_local.connection.recovery.verification import (
    CallbackRecoveryRoute,
)
from custom_components.eybond_local.models import (
    CollectorCandidate,
    CollectorInfo,
    DriverMatch,
    OnboardingResult,
    ProbeTarget,
    TargetDetectionEvidence,
)
from custom_components.eybond_local.onboarding.detection import DiscoveryTarget
from custom_components.eybond_local.support.workflow import build_support_workflow_state
from custom_components.eybond_local.support.cloud_evidence import CloudEvidenceRecord, build_cloud_evidence_payload
from custom_components.eybond_local.support.shadow_learning import (
    ShadowWriteObservation,
)
from custom_components.eybond_local.support.shadow_learning.runtime import (
    ShadowLearningRouteStatus,
    ShadowLearningRuntimeView,
)
from custom_components.eybond_local.runtime.manager import RuntimeInverterCandidate
from custom_components.eybond_local.runtime.shadow_learning_facade import (
    ShadowLearningRuntimeFacade,
)


def _shadow_runtime_facade(
    route_status: ShadowLearningRouteStatus,
) -> ShadowLearningRuntimeFacade:
    runtime = types.SimpleNamespace(
        shadow_learning_route_status=route_status.to_mapping,
        shadow_learning_write_observations=lambda: (),
    )
    return ShadowLearningRuntimeFacade(
        runtime=runtime,
        cloud_evidence_provider=lambda: None,
    )


class _FakeEntry:
    def __init__(self, entry_id: str, *, server_ip: str, tcp_port: int) -> None:
        self.entry_id = entry_id
        self.data = {"server_ip": server_ip, "tcp_port": tcp_port}
        self.options = {}


class _FakeSetupEntry:
    """Minimal ConfigEntry double for exercising the runtime setup claim path."""

    def __init__(self, entry_id: str, data: dict, options: dict | None = None) -> None:
        self.entry_id = entry_id
        self.data = dict(data)
        self.options = dict(options or {})
        self.unique_id = None
        self.title = None
        self._unloads: list = []

    def async_on_unload(self, callback):
        self._unloads.append(callback)
        return callback


class _FakeConfigEntries:
    def __init__(self, entries=None) -> None:
        self._entries = list(entries or [])
        self.unloaded: list[str] = []
        self.reloaded: list[str] = []
        # Every async_update_entry(**kwargs) recorded, so tests can assert that
        # data+options are committed in ONE atomic update (one reload).
        self.updates: list[dict] = []

    def async_update_entry(self, entry, **kwargs):
        """Mirror HA: apply the update and report whether anything changed."""

        self.updates.append(dict(kwargs))
        changed = False
        for key in ("data", "options"):
            if key in kwargs and kwargs[key] is not None:
                new = dict(kwargs[key])
                if dict(getattr(entry, key, {}) or {}) != new:
                    changed = True
                setattr(entry, key, new)
        for key, value in kwargs.items():
            if key in ("data", "options"):
                continue
            if getattr(entry, key, None) != value:
                changed = True
            setattr(entry, key, value)
        return changed

    def async_entries(self, _domain):
        return list(self._entries)

    def async_get_entry(self, entry_id: str):
        for entry in self._entries:
            if getattr(entry, "entry_id", None) == entry_id:
                return entry
        return None

    async def async_unload(self, entry_id: str):
        self.unloaded.append(entry_id)
        return True

    async def async_reload(self, entry_id: str):
        self.reloaded.append(entry_id)
        return True


class _FakeHass:
    def __init__(self, entries=None) -> None:
        class _Services:
            def __init__(self) -> None:
                self.registered: list[tuple[str, str]] = []

            def async_register(self, domain, service, _handler, **_kwargs) -> None:
                self.registered.append((domain, service))

        self.config_entries = _FakeConfigEntries(entries)
        self.config = types.SimpleNamespace(language="en", config_dir="/config", time_zone="UTC")
        self.data: dict[str, object] = {}
        self.services = _Services()
        self.executor_job_calls: list[tuple[object, tuple[object, ...]]] = []

    async def async_add_executor_job(self, func, *args):
        self.executor_job_calls.append((func, args))
        return func(*args)

    def async_create_task(self, coro):
        return asyncio.create_task(coro)


class _DoneTask:
    def __init__(self, exception=None) -> None:
        self._exception = exception

    def done(self) -> bool:
        return True

    def exception(self):
        return self._exception


class _PendingTask:
    def done(self) -> bool:
        return False


@dataclass(frozen=True)
class _SmartEssDraftPlan:
    source_profile_name: str
    source_schema_name: str
    driver_label: str
    reason: str


@dataclass(frozen=True)
class _SmartEssSmgBridgePlan:
    source_profile_name: str
    source_schema_name: str
    bridge_label: str
    reason: str
    profile_enable_keys: tuple[str, ...] = ()
    measurement_enable_keys: tuple[str, ...] = ()
    blocked_field_titles: tuple[str, ...] = ()
    skipped_field_titles: tuple[str, ...] = ()


def _schema_select_options(data_schema, field_name: str) -> list[str]:
    """Extract SelectSelector option values for one schema field."""

    for key, validator in data_schema.schema.items():
        if str(key) != field_name:
            continue
        config = getattr(validator, "config", None)
        # The stubbed SelectSelectorConfig keeps kwargs; real HA uses a dict.
        if hasattr(config, "kwargs"):
            options = config.kwargs.get("options", [])
        else:
            options = (config or {}).get("options", [])
        values = []
        for option in options:
            if isinstance(option, dict):
                values.append(str(option["value"]))
            else:
                values.append(str(option))
        return values
    raise AssertionError(f"field {field_name} not found in schema")


def _fast_identity_policy():
    """The central onboarding policy with the callback wait budgets shrunk.

    Budgets live in OnboardingTimeoutPolicy, so tests tune the policy rather than
    a module constant. Without this a flow test that never gets a session sits out
    the real 20s link budget.
    """

    from dataclasses import replace

    from custom_components.eybond_local.onboarding.timeouts import (
        DEFAULT_ONBOARDING_TIMEOUT_POLICY,
    )

    return replace(
        DEFAULT_ONBOARDING_TIMEOUT_POLICY,
        callback_identity_session_wait=0.05,
        callback_causality_lease_wait=2.0,
    )


def _install_fast_identity_policy(testcase):
    import custom_components.eybond_local.connection.callback_identity as ci

    patcher = patch.object(
        ci, "DEFAULT_ONBOARDING_TIMEOUT_POLICY", _fast_identity_policy()
    )
    patcher.start()
    testcase.addCleanup(patcher.stop)


def _wire_session(
    session_id: str,
    pn: str,
    state: str = "identified",
    *,
    identity_source: str = "at_dtupn",
    protocol_shape: str = "eybond_framed",
    peer_ip: str = "203.0.113.10",
    listener_port: int = 18899,
) -> dict[str, object]:
    """One observed-session inventory mapping, as the shared listener reports it."""

    return {
        "session_id": session_id,
        "peer_ip": peer_ip,
        "listener_port": listener_port,
        "collector_pn": pn,
        "state": state,
        "protocol_shape": protocol_shape,
        "collector_identity_source": identity_source,
    }


def _install_domain_registry(flow, inventory: list[dict[str, object]]):
    """Install the domain callback-session registry over a mutable inventory."""

    from custom_components.eybond_local.connection.session_registry import (
        CallbackSessionRegistry,
    )

    registry = CallbackSessionRegistry(
        sessions_source=lambda: tuple(dict(session) for session in inventory)
    )
    flow.hass.data.setdefault("eybond_local", {})[
        "callback_session_registry"
    ] = registry
    return registry


@contextmanager
def _stub_identity_wire(
    inventory,
    *,
    answers=(),
    read_pn=None,
    read_error=None,
    own_sends=1,
    foreign_sends=0,
):
    """Drive the REAL identity transaction with only its two wire edges stubbed.

    The causality lease, session claim, matcher, promote and prepare_handoff all
    run for real; the stubs stand in for the UDP trigger (``answers`` appear
    only AFTER it, like a collector dialing in) and the on-session PN read.
    """

    import custom_components.eybond_local.connection.callback_identity as ci
    from custom_components.eybond_local.connection.callback_ledger import (
        get_callback_trigger_ledger,
    )

    class _Sender:
        async def async_send(self, request):
            ledger = get_callback_trigger_ledger()
            for _ in range(own_sends):
                ledger.record(target=request.target_ip, source="test_attempt")
            for _ in range(foreign_sends):
                ledger.record(target="other", source="runtime", attempt_id="")
            inventory.extend(answers)

    class _Reader:
        async def async_read_full_pn(self, **_kwargs):
            if read_error is not None:
                raise read_error
            if read_pn is None:
                return ("", "")
            return (read_pn, "fc2_parameter_2")

    with patch.object(ci, "_ProductionTriggerSender", return_value=_Sender()), patch.object(
        ci, "_SessionPinnedIdentityReader", return_value=_Reader()
    ), patch.object(ci, "DEFAULT_ONBOARDING_TIMEOUT_POLICY", _fast_identity_policy()):
        yield


@contextmanager
def _capture_identity_requests(result=None):
    """Record every CallbackIdentityRequest the flow hands to the transaction.

    The transaction itself is NOT run (its mechanics are pinned in
    tests/test_callback_identity.py); this seam is for tests about the FLOW's
    request construction and failure routing only.
    """

    from custom_components.eybond_local.connection.callback_identity import (
        CallbackIdentityOutcome,
    )

    captured: list = []
    outcome = result or CallbackIdentityOutcome(result="callback_timeout")

    async def _recorder(_hass, request, **_kwargs):
        captured.append(request)
        return outcome

    with patch.object(
        admission_transaction_module,
        "async_run_callback_identity_transaction",
        new=_recorder,
    ):
        yield captured


def _proxy_overview(**overrides):
    """Complete readiness DTO, not a partial view with contradictory cache flags."""
    from custom_components.eybond_local.support.proxy_capture import ProxyCaptureOverview
    values = dict(status="ready", status_label="Ready", summary="Collector proxy capture is ready.",
        blocking_reason="", can_start=True, can_stop=False, critical_phase=False,
        redirect_required=False, collector_connected=True,
        current_endpoint="collector-cloud.smartess.example,18899,TCP",
        upstream_endpoint="collector-cloud.smartess.example,18899,TCP",
        target_endpoint="192.168.1.50,18899,TCP",
        masked_endpoint="collector-cloud.smartess.example,18899,TCP",
        latest_trace_path="", latest_manifest_path="")
    values.update(overrides)
    return ProxyCaptureOverview(**values)


class ConfigFlowTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        super().setUp()
        _install_fast_identity_policy(self)

    def _make_flow(self, *, entries=None) -> EybondLocalConfigFlow:
        flow = EybondLocalConfigFlow()
        flow.hass = _FakeHass(entries)
        flow.context = {}
        flow._local_ip = "192.168.1.50"
        flow._auto_config = {"server_ip": "192.168.1.50"}
        flow._interface_options = [
            {
                "name": "eth0",
                "ip": "192.168.1.50",
                "label": "eth0 - 192.168.1.50",
                "network": "192.168.0.0/16",
                "broadcast": "192.168.255.255",
            },
        ]
        return flow

    def _make_options_flow(self) -> EybondLocalOptionsFlow:
        entry = type("_Entry", (), {})()
        entry.entry_id = "entry-options"
        entry.data = {
            "connection_type": "eybond",
            "server_ip": "192.168.1.50",
            "collector_ip": "192.168.1.55",
            "tcp_port": 8899,
            "udp_port": 58899,
            "discovery_target": "192.168.1.255",
            "discovery_interval": 3,
            "heartbeat_interval": 60,
            "driver_hint": "auto",
            "detected_model": "SMG 6200",
            "detected_serial": "12345",
            "detection_confidence": "high",
            "control_mode": "auto",
        }
        entry.options = {}
        entry.runtime_data = {}
        options = EybondLocalOptionsFlow(entry)
        options.hass = _FakeHass()
        options.context = {}
        return options

    def test_pi30_manual_poll_selector_uses_driver_policy_floor(self) -> None:
        selector = _poll_interval_selector("pi30")

        self.assertEqual(selector.config.kwargs["min"], 2)

    async def test_scanning_without_results_routes_to_scan_results(self) -> None:
        flow = self._make_flow()
        flow._scan_task = _DoneTask()
        flow._scan_progress_visible = True
        flow._autodetect_results = {}

        result = await flow.async_step_scanning()

        self.assertEqual(result["type"], "progress_done")
        self.assertEqual(result["next_step_id"], "scan_results")
        self.assertTrue(flow._scan_error)

    async def test_scanning_progress_shows_estimated_progress_bar(self) -> None:
        flow = self._make_flow()
        flow._scan_task = _PendingTask()
        flow._scan_started_monotonic = 100.0
        flow._scan_progress_stage = "discovering"

        with patch(
            "custom_components.eybond_local.flows.config.network.time.monotonic",
            return_value=112.0,
        ):
            result = await flow.async_step_scanning()

        self.assertEqual(result["type"], "progress")
        placeholders = result["description_placeholders"]
        self.assertEqual(placeholders["scan_progress_phase"], "Sending discovery probes")
        self.assertIn("[", placeholders["scan_progress_bar"])
        self.assertIn("%", placeholders["scan_progress_bar"])
        self.assertIn("12s elapsed", placeholders["scan_progress_detail"])
        self.assertNotIn("remaining", placeholders["scan_progress_detail"])

    def test_get_ipv4_interfaces_parses_busybox_oneline_output(self) -> None:
        output = (
            "1: lo    inet 127.0.0.1/8 scope host lo\\       valid_lft forever preferred_lft forever\n"
            "2: docker0    inet 172.17.0.1/16 brd 172.17.255.255 scope global docker0\\       valid_lft forever preferred_lft forever\n"
            "3: wlan0    inet 192.168.1.50/24 brd 192.168.1.255 scope global dynamic noprefixroute wlan0\\       valid_lft 42620sec preferred_lft 42620sec\n"
            "4: hassio    inet 172.30.32.1/23 brd 172.30.33.255 scope global hassio\\       valid_lft forever preferred_lft forever\n"
        )

        with patch(
            "custom_components.eybond_local.network_interfaces.subprocess.check_output",
            side_effect=[subprocess.CalledProcessError(1, ["ip"]), output],
        ):
            interfaces = _get_ipv4_interfaces()

        wlan0 = next(interface for interface in interfaces if interface["name"] == "wlan0")
        self.assertEqual(wlan0["ip"], "192.168.1.50")
        self.assertEqual(wlan0["network"], "192.168.1.0/24")
        self.assertEqual(wlan0["broadcast"], "192.168.1.255")
        self.assertFalse(any(interface["name"] == "docker0" for interface in interfaces))
        self.assertFalse(any(interface["name"] == "hassio" for interface in interfaces))

    async def test_scanning_shows_progress_once_even_if_task_finishes_immediately(self) -> None:
        flow = self._make_flow()

        def _done_task(coro):
            coro.close()
            return _DoneTask()

        flow.hass.async_create_task = _done_task

        first = await flow.async_step_scanning()
        second = await flow.async_step_scanning()

        self.assertEqual(first["type"], "progress")
        self.assertEqual(second["type"], "progress_done")

    async def test_async_ensure_network_defaults_heals_stale_auto_server_ip(self) -> None:
        flow = self._make_flow()
        flow._auto_config = {"connection_type": "eybond", "server_ip": "192.168.2.50"}

        with patch(
            "custom_components.eybond_local.network_interfaces.get_ipv4_interfaces",
            return_value=[
                {
                    "name": "eth0",
                    "ip": "192.168.1.50",
                    "label": "eth0 - 192.168.1.50",
                    "network": "192.168.0.0/16",
                    "broadcast": "192.168.255.255",
                },
            ],
        ), patch(
            "custom_components.eybond_local.network_interfaces.get_local_ip",
            return_value="192.168.1.50",
        ):
            await flow._async_ensure_network_defaults()

        self.assertEqual(flow._auto_config["server_ip"], "192.168.1.50")
        self.assertEqual(flow._scan_discovery_targets()[0].ip, "192.168.255.255")

    async def test_user_step_skips_welcome_for_single_connection_type(self) -> None:
        flow = self._make_flow()

        result = await flow.async_step_user()

        # One supported connection type: no welcome form, straight to readiness.
        self.assertEqual(result["type"], "menu")
        self.assertEqual(result["step_id"], "collector_network")
        self.assertEqual(flow._auto_config["connection_type"], "eybond")

    async def test_user_step_preloads_translation_bundle_via_executor(self) -> None:
        flow = self._make_flow()

        await flow.async_step_user()

        self.assertIn(
            "load_translation_bundle",
            [getattr(func, "__name__", "") for func, _args in flow.hass.executor_job_calls],
        )

    async def test_cold_flow_metadata_preparation_runs_once_off_event_loop(self) -> None:
        flow = self._make_flow()
        flow.hass.config.path = lambda name: f"/config/{name}"
        worker_threads: list[str] = []

        def _prime(_config_root: Path) -> None:
            worker_threads.append(threading.current_thread().name)

        async def _run_in_executor(func, *args):
            flow.hass.executor_job_calls.append((func, args))
            return await asyncio.to_thread(func, *args)

        flow.hass.async_add_executor_job = _run_in_executor
        with patch(
            "custom_components.eybond_local.integration_metadata._prime_metadata_caches",
            side_effect=_prime,
        ) as prime:
            await flow._async_prepare_metadata_caches()
            await flow._async_prepare_metadata_caches()

        prime.assert_called_once_with(Path("/config/eybond_local"))
        self.assertEqual(len(worker_threads), 1)
        self.assertNotEqual(worker_threads[0], threading.main_thread().name)

    async def test_user_step_routes_to_interface_selection_when_multiple_interfaces(self) -> None:
        flow = self._make_flow()
        flow._interface_options = [
            {"name": "eth0", "ip": "192.168.1.50", "label": "eth0 - 192.168.1.50"},
            {"name": "wlan0", "ip": "192.168.2.50", "label": "wlan0 - 192.168.2.50"},
        ]

        result = await flow.async_step_user({"connection_type": "eybond"})

        self.assertEqual(result["type"], "menu")
        self.assertEqual(result["step_id"], "collector_network")
        self.assertEqual(flow._auto_config["connection_type"], "eybond")

    async def test_collector_network_is_shown_as_menu(self) -> None:
        flow = self._make_flow()

        result = await flow.async_step_collector_network()

        self.assertEqual(result["type"], "menu")
        self.assertEqual(result["step_id"], "collector_network")
        self.assertEqual(
            result["menu_options"],
            ["auto", "bluetooth_setup", "listener"],
        )

    async def test_listener_menu_option_creates_bootstrap_entry(self) -> None:
        flow = self._make_flow()

        result = await flow.async_step_listener()

        self.assertEqual(result["type"], "create_entry")
        self.assertEqual(result["title"], "EyeBond Local — Discovery")
        self.assertEqual(result["data"], {"entry_role": "listener"})
        self.assertEqual(flow._test_unique_id, "eybond_local:listener")

    async def test_listener_menu_option_refreshes_existing_background_discovery(self) -> None:
        entry = _FakeEntry("listener", server_ip="", tcp_port=0)
        entry.data = {"entry_role": "listener"}
        entry.unique_id = "eybond_local:listener"
        flow = self._make_flow(entries=[entry])
        service = types.SimpleNamespace(
            async_show_discovered_devices_again=AsyncMock()
        )
        flow._abort_if_unique_id_configured = Mock(
            side_effect=AssertionError("existing listener must be handled before HA abort")
        )

        with patch(
            "custom_components.eybond_local.passive_discovery.get_passive_callback_discovery",
            return_value=service,
        ):
            result = await flow.async_step_listener()

        service.async_show_discovered_devices_again.assert_awaited_once_with()
        self.assertEqual(result["type"], "abort")
        self.assertEqual(result["reason"], "background_discovery_refreshed")
        flow._abort_if_unique_id_configured.assert_not_called()

    async def test_listener_menu_recognizes_listener_unique_id_without_role(self) -> None:
        entry = _FakeEntry("listener", server_ip="", tcp_port=0)
        entry.unique_id = "eybond_local:listener"
        flow = self._make_flow(entries=[entry])

        result = await flow.async_step_listener()

        self.assertEqual(result["type"], "abort")
        self.assertEqual(result["reason"], "background_discovery_refreshed")

    async def test_listener_import_uses_same_unique_bootstrap_entry(self) -> None:
        flow = self._make_flow()

        result = await flow.async_step_import({"entry_role": "listener"})

        self.assertEqual(result["type"], "create_entry")
        self.assertEqual(result["data"], {"entry_role": "listener"})
        self.assertEqual(flow._test_unique_id, "eybond_local:listener")

    async def test_listener_entry_exposes_friendly_rediscovery_action(self) -> None:
        entry = types.SimpleNamespace(
            data={"entry_role": "listener"},
            options={},
        )

        options_flow = EybondLocalConfigFlow.async_get_options_flow(entry)
        result = await options_flow.async_step_init()

        self.assertEqual(type(options_flow).__name__, "ListenerOptionsFlow")
        self.assertEqual(result["type"], "menu")
        self.assertEqual(result["step_id"], "listener")
        self.assertEqual(result["menu_options"], ["rediscover_devices"])
        self.assertTrue(callable(getattr(options_flow, "async_step_listener", None)))

    async def test_listener_rediscovery_requires_confirmation_and_reports_result(self) -> None:
        entry = types.SimpleNamespace(
            data={"entry_role": "listener"},
            options={},
        )
        options_flow = EybondLocalConfigFlow.async_get_options_flow(entry)
        options_flow.hass = _FakeHass()
        service = types.SimpleNamespace(
            async_show_discovered_devices_again=AsyncMock(
                return_value=types.SimpleNamespace(
                    connected_unclaimed_count=3,
                    suppressed_candidate_count=2,
                )
            )
        )

        unconfirmed = await options_flow.async_step_rediscover_devices(
            {"confirm_rediscover_devices": False}
        )
        self.assertEqual(
            unconfirmed["errors"],
            {"confirm_rediscover_devices": "required"},
        )

        with patch(
            "custom_components.eybond_local.passive_discovery.get_passive_callback_discovery",
            return_value=service,
        ):
            completed = await options_flow.async_step_rediscover_devices(
                {"confirm_rediscover_devices": True}
            )

        service.async_show_discovered_devices_again.assert_awaited_once_with()
        self.assertEqual(completed["type"], "form")
        self.assertEqual(completed["step_id"], "rediscover_devices_done")
        self.assertEqual(
            completed["description_placeholders"],
            {"connected_count": "3"},
        )
        closed = await options_flow.async_step_rediscover_devices_done({})
        self.assertEqual(closed["type"], "create_entry")

    async def test_collector_network_routes_to_bluetooth_setup_when_collector_is_not_connected(self) -> None:
        flow = self._make_flow()

        menu_result = await flow.async_step_collector_network()

        with patch(
            "custom_components.eybond_local.flows.config.ble.async_probe_ble_host_capability",
            new=AsyncMock(return_value=types.SimpleNamespace(available=True)),
        ), patch.object(flow, "_async_discover_smartess_ble_candidates", new=AsyncMock(return_value=())):
            result = await flow.async_step_bluetooth_setup()

        self.assertEqual(menu_result["type"], "menu")
        self.assertIn("bluetooth_setup", menu_result["menu_options"])
        self.assertEqual(result["type"], "form")
        self.assertEqual(result["step_id"], "bluetooth_setup")

    async def test_collector_network_stays_put_when_ble_host_is_unavailable(self) -> None:
        flow = self._make_flow()

        menu_result = await flow.async_step_collector_network()

        with patch(
            "custom_components.eybond_local.flows.config.ble.async_probe_ble_host_capability",
            new=AsyncMock(
                return_value=types.SimpleNamespace(
                    available=False,
                    reason="adapter_not_found",
                    detail="No Bluetooth adapters found",
                )
            ),
        ), patch.object(flow, "_async_discover_smartess_ble_candidates", new=AsyncMock(return_value=())) as discover:
            result = await flow.async_step_bluetooth_setup()

        discover.assert_not_awaited()
        self.assertEqual(menu_result["type"], "menu")
        self.assertEqual(result["type"], "form")
        self.assertEqual(result["step_id"], "bluetooth_setup")
        self.assertEqual(result["errors"], {"base": "ble_unavailable"})
        self.assertEqual(flow._ble_last_error, "No Bluetooth adapters found")

    async def test_collector_network_accepts_home_assistant_bluetooth_proxy_without_local_adapter(self) -> None:
        flow = self._make_flow()
        components_module = types.ModuleType("homeassistant.components")
        bluetooth_module = types.ModuleType("homeassistant.components.bluetooth")
        bluetooth_module.async_scanner_count = Mock(return_value=1)
        bluetooth_module.async_discovered_service_info = Mock(return_value=())
        bluetooth_module.async_scanner_devices_by_address = Mock(return_value={})

        with patch.dict(
            sys.modules,
            {
                "homeassistant.components": components_module,
                "homeassistant.components.bluetooth": bluetooth_module,
            },
        ), patch(
            "custom_components.eybond_local.flows.config.ble.async_probe_ble_host_capability",
            new=AsyncMock(
                return_value=types.SimpleNamespace(
                    available=False,
                    reason="adapter_not_found",
                    detail="No Bluetooth adapters found",
                )
            ),
        ), patch.object(flow, "_async_discover_smartess_ble_candidates", new=AsyncMock(return_value=())):
            result = await flow.async_step_bluetooth_setup()

        self.assertEqual(result["type"], "form")
        self.assertEqual(result["step_id"], "bluetooth_setup")

    async def test_collector_network_auto_advances_to_scanning_with_one_interface(self) -> None:
        flow = self._make_flow()

        async def _fake_scanning(user_input=None):
            return {"type": "progress", "step_id": "scanning"}

        flow.async_step_scanning = _fake_scanning

        menu_result = await flow.async_step_collector_network()
        result = await flow.async_step_auto()

        self.assertEqual(menu_result["type"], "menu")
        self.assertIn("auto", menu_result["menu_options"])
        # One interface: the interface-picker form is skipped entirely.
        self.assertEqual(result["type"], "progress")
        self.assertEqual(result["step_id"], "scanning")

    async def test_user_step_routes_to_auto_when_one_interface(self) -> None:
        flow = self._make_flow()

        result = await flow.async_step_user({"connection_type": "eybond"})

        self.assertEqual(result["type"], "menu")
        self.assertEqual(result["step_id"], "collector_network")
        self.assertEqual(flow._auto_config["connection_type"], "eybond")
        self.assertEqual(flow._auto_config["server_ip"], "192.168.1.50")

    async def test_auto_step_uses_localized_interface_hint(self) -> None:
        flow = self._make_flow()
        flow.hass.config.language = "ru"
        flow._auto_config = {"connection_type": "eybond", "server_ip": "192.168.1.50"}
        # Two interfaces => the picker form is shown (no auto-advance).
        flow._interface_options = [
            {"name": "eth0", "ip": "192.168.1.50", "label": "eth0 - 192.168.1.50"},
            {"name": "wlan0", "ip": "10.0.0.2", "label": "wlan0 - 10.0.0.2"},
        ]

        result = await flow.async_step_auto()

        self.assertEqual(result["type"], "form")
        hint = result["description_placeholders"]["interface_hint"]
        self.assertIn("Выберите", hint)
        self.assertNotIn("Home Assistant will use", hint)

    async def test_auto_step_starts_unified_scan(self) -> None:
        flow = self._make_flow()
        flow._auto_config = {"connection_type": "eybond", "server_ip": "192.168.1.50"}

        async def _fake_scanning(user_input=None):
            return {"type": "progress", "step_id": "scanning"}

        flow.async_step_scanning = _fake_scanning

        result = await flow.async_step_auto({"server_ip": "192.168.1.50"})

        self.assertEqual(result["type"], "progress")
        self.assertEqual(flow._auto_config["server_ip"], "192.168.1.50")

    async def test_auto_step_heals_stale_submitted_server_ip(self) -> None:
        flow = self._make_flow()
        flow._auto_config = {"connection_type": "eybond", "server_ip": "192.168.1.104"}

        async def _fake_scanning(user_input=None):
            return {"type": "progress", "step_id": "scanning"}

        flow.async_step_scanning = _fake_scanning

        result = await flow.async_step_auto({"server_ip": "192.168.1.104"})

        self.assertEqual(result["type"], "progress")
        self.assertEqual(flow._auto_config["server_ip"], "192.168.1.50")

    async def test_bluetooth_setup_shows_capability_error_when_host_is_unavailable(self) -> None:
        flow = self._make_flow()

        with patch(
            "custom_components.eybond_local.flows.config.ble.async_probe_ble_host_capability",
            new=AsyncMock(return_value=types.SimpleNamespace(available=False)),
        ):
            result = await flow.async_step_bluetooth_setup(
                {"ble_address": "AA:BB:CC:DD:EE:FF"}
            )

        self.assertEqual(result["type"], "form")
        self.assertEqual(result["step_id"], "bluetooth_setup")
        self.assertEqual(result["errors"], {"base": "ble_unavailable"})

    async def test_bluetooth_setup_uses_discovered_collectors_selector(self) -> None:
        flow = self._make_flow()
        candidates = (
            SmartEssBleCandidate(
                address="BB:CC:DD:EE:FF:00",
                local_pn="A1234567890123",
                local_name="Zulu Collector",
            ),
            SmartEssBleCandidate(
                address="AA:BB:CC:DD:EE:FF",
                local_pn="A0000000000001",
                local_name="Alpha Collector",
            ),
        )

        with patch(
            "custom_components.eybond_local.flows.config.ble.async_probe_ble_host_capability",
            new=AsyncMock(return_value=types.SimpleNamespace(available=True)),
        ), patch.object(
            flow,
            "_async_discover_smartess_ble_candidates",
            new=AsyncMock(return_value=candidates),
        ), patch.object(
            flow,
            "_async_scan_smartess_ble_wifi_networks",
            new=AsyncMock(return_value=()),
        ):
            result = await flow.async_step_bluetooth_setup()

        ble_selector = result["data_schema"].schema["ble_address"]
        options = ble_selector.config.kwargs["options"]
        self.assertEqual(
            [option["value"] for option in options],
            ["AA:BB:CC:DD:EE:FF", "BB:CC:DD:EE:FF:00"],
        )
        self.assertEqual(
            [option["label"] for option in options],
            [
                "Alpha Collector - A0000000000001 - AA:BB:CC:DD:EE:FF",
                "Zulu Collector - A1234567890123 - BB:CC:DD:EE:FF:00",
            ],
        )

    async def test_bluetooth_setup_uses_home_assistant_bluetooth_cache(self) -> None:
        flow = self._make_flow()

        components_module = types.ModuleType("homeassistant.components")
        bluetooth_module = types.ModuleType("homeassistant.components.bluetooth")
        bluetooth_module.async_discovered_service_info = Mock(
            return_value=(
                types.SimpleNamespace(
                    address="AA:BB:CC:DD:EE:47",
                    name="E50000200000000001\u200b",
                    manufacturer_data={0x3545: b"0000200000000001"},
                    service_uuids=(),
                    device=object(),
                ),
            )
        )

        with patch.dict(
            sys.modules,
            {
                "homeassistant.components": components_module,
                "homeassistant.components.bluetooth": bluetooth_module,
            },
        ), patch(
            "custom_components.eybond_local.flows.config.ble.async_probe_ble_host_capability",
            new=AsyncMock(return_value=types.SimpleNamespace(available=True)),
        ), patch(
            "custom_components.eybond_local.flows.config.ble.BleakSmartEssBleScanner",
        ) as scanner_cls, patch.object(
            flow,
            "_async_scan_smartess_ble_wifi_networks",
            new=AsyncMock(return_value=()),
        ):
            result = await flow.async_step_bluetooth_setup()

        scanner_cls.assert_not_called()
        ble_selector = result["data_schema"].schema["ble_address"]
        options = ble_selector.config.kwargs["options"]
        self.assertEqual(
            [option["value"] for option in options],
            ["AA:BB:CC:DD:EE:47"],
        )
        self.assertIn("E50000200000000001", options[0]["label"])

    async def test_bluetooth_setup_uses_home_assistant_bluetooth_advertisement_callback(self) -> None:
        flow = self._make_flow()

        components_module = types.ModuleType("homeassistant.components")
        bluetooth_module = types.ModuleType("homeassistant.components.bluetooth")
        bluetooth_module.async_discovered_service_info = Mock(return_value=())
        bluetooth_module.async_scanner_devices_by_address = Mock(return_value=())
        bluetooth_module.BluetoothScanningMode = types.SimpleNamespace(ACTIVE=sentinel.active_scan)
        service_info = types.SimpleNamespace(
            address="AA:BB:CC:DD:EE:47",
            name="E50000200000000001\u200b",
            manufacturer_data={0x3545: b"0000200000000001"},
            service_uuids=(),
            device=object(),
        )

        def async_register_callback(hass, callback, matcher, mode):
            self.assertIs(hass, flow.hass)
            self.assertEqual(mode, sentinel.active_scan)
            self.assertIn(matcher["connectable"], (False, True))
            callback(service_info, sentinel.bluetooth_change)
            return Mock()

        bluetooth_module.async_register_callback = Mock(side_effect=async_register_callback)

        with patch.dict(
            sys.modules,
            {
                "homeassistant.components": components_module,
                "homeassistant.components.bluetooth": bluetooth_module,
            },
        ), patch(
            "custom_components.eybond_local.flows.config.ble.async_probe_ble_host_capability",
            new=AsyncMock(return_value=types.SimpleNamespace(available=True)),
        ), patch(
            "custom_components.eybond_local.flows.config.ble.BleakSmartEssBleScanner",
        ) as scanner_cls, patch(
            "custom_components.eybond_local.flows.config.ble.asyncio.sleep",
            new=AsyncMock(),
        ), patch.object(
            flow,
            "_async_scan_smartess_ble_wifi_networks",
            new=AsyncMock(return_value=()),
        ):
            result = await flow.async_step_bluetooth_setup()

        scanner_cls.assert_not_called()
        self.assertEqual(bluetooth_module.async_register_callback.call_count, 8)
        registered_matchers = [
            call.args[2] for call in bluetooth_module.async_register_callback.call_args_list
        ]
        self.assertIn({"local_name": "E50*", "connectable": False}, registered_matchers)
        self.assertIn({"local_name": "E50*", "connectable": True}, registered_matchers)
        self.assertIn({"local_name": "V00*", "connectable": False}, registered_matchers)
        self.assertIn({"local_name": "V00*", "connectable": True}, registered_matchers)
        ble_selector = result["data_schema"].schema["ble_address"]
        options = ble_selector.config.kwargs["options"]
        self.assertEqual(
            [option["value"] for option in options],
            ["AA:BB:CC:DD:EE:47"],
        )
        self.assertIn("E50000200000000001", options[0]["label"])

    async def test_bluetooth_setup_skips_raw_bleak_fallback_when_only_ha_proxy_scanners_exist(self) -> None:
        flow = self._make_flow()

        components_module = types.ModuleType("homeassistant.components")
        bluetooth_module = types.ModuleType("homeassistant.components.bluetooth")
        bluetooth_module.async_scanner_count = Mock(return_value=1)
        bluetooth_module.async_discovered_service_info = Mock(return_value=())
        bluetooth_module.async_scanner_devices_by_address = Mock(return_value={})

        with patch.dict(
            sys.modules,
            {
                "homeassistant.components": components_module,
                "homeassistant.components.bluetooth": bluetooth_module,
            },
        ), patch(
            "custom_components.eybond_local.flows.config.ble.async_probe_ble_host_capability",
            new=AsyncMock(return_value=types.SimpleNamespace(available=False)),
        ), patch(
            "custom_components.eybond_local.flows.config.ble.BleakSmartEssBleScanner",
        ) as scanner_cls:
            result = await flow.async_step_bluetooth_setup()

        scanner_cls.assert_not_called()
        self.assertEqual(result["type"], "form")
        self.assertEqual(result["step_id"], "bluetooth_setup")

    async def test_bluetooth_setup_uses_collector_wifi_selector_when_scan_returns_networks(self) -> None:
        flow = self._make_flow()
        candidates = (
            SmartEssBleCandidate(
                address="AA:BB:CC:DD:EE:FF",
                local_pn="E50000200000000001",
                local_name="Collector PN",
            ),
        )
        wifi_networks = (
            SmartEssBleWifiNetwork(ssid="Neighbor", signal=-75),
            SmartEssBleWifiNetwork(ssid="HomeNet", signal=-44),
            SmartEssBleWifiNetwork(ssid="Office", signal=-58),
        )

        with patch(
            "custom_components.eybond_local.flows.config.ble.async_probe_ble_host_capability",
            new=AsyncMock(return_value=types.SimpleNamespace(available=True)),
        ), patch.object(
            flow,
            "_async_discover_smartess_ble_candidates",
            new=AsyncMock(return_value=candidates),
        ), patch.object(
            flow,
            "_async_scan_smartess_ble_wifi_networks",
            new=AsyncMock(return_value=wifi_networks),
        ):
            result = await flow.async_step_bluetooth_setup(
                {
                    "ble_address": "AA:BB:CC:DD:EE:FF",
                    CONF_BLE_ACTION: BLE_ACTION_REFRESH_WIFI,
                }
            )

        wifi_selector = result["data_schema"].schema["wifi_ssid"]
        options = wifi_selector.config.kwargs["options"]
        self.assertTrue(wifi_selector.config.kwargs["custom_value"])
        self.assertEqual(
            set(result["data_schema"].schema),
            {"ble_address", "wifi_ssid", "wifi_password", CONF_BLE_ACTION},
        )
        self.assertEqual(
            [option["value"] for option in options],
            ["Neighbor", "HomeNet", "Office"],
        )
        self.assertEqual(
            [option["label"] for option in options],
            ["Neighbor (-75 dBm)", "HomeNet (-44 dBm)", "Office (-58 dBm)"],
        )
        self.assertEqual(result["errors"], {})

    async def test_bluetooth_setup_scans_default_collector_wifi_on_first_entry(self) -> None:
        flow = self._make_flow()
        candidates = (
            SmartEssBleCandidate(
                address="AA:BB:CC:DD:EE:FF",
                local_pn="E50000200000000001",
                local_name="Collector PN",
            ),
        )

        with patch(
            "custom_components.eybond_local.flows.config.ble.async_probe_ble_host_capability",
            new=AsyncMock(return_value=types.SimpleNamespace(available=True)),
        ), patch.object(
            flow,
            "_async_discover_smartess_ble_candidates",
            new=AsyncMock(return_value=candidates),
        ), patch.object(
            flow,
            "_async_scan_smartess_ble_wifi_networks",
            new=AsyncMock(return_value=(SmartEssBleWifiNetwork(ssid="HomeNet", signal=98),)),
        ) as wifi_scan:
            result = await flow.async_step_bluetooth_setup()

        wifi_scan.assert_awaited_once_with("AA:BB:CC:DD:EE:FF", ble_device=None)
        wifi_selector = result["data_schema"].schema["wifi_ssid"]
        options = wifi_selector.config.kwargs["options"]
        self.assertEqual(options[0]["value"], "HomeNet")
        self.assertEqual(options[0]["label"], "HomeNet (98%)")
        self.assertTrue(wifi_selector.config.kwargs["custom_value"])
        self.assertEqual(
            set(result["data_schema"].schema),
            {"ble_address", "wifi_ssid", "wifi_password", CONF_BLE_ACTION},
        )
        self.assertEqual(result["errors"], {})

    async def test_bluetooth_setup_scans_wifi_for_newly_selected_collector(self) -> None:
        flow = self._make_flow()
        candidates = (
            SmartEssBleCandidate(
                address="AA:BB:CC:DD:EE:FF",
                local_pn="E50000200000000001",
                local_name="Alpha Collector",
            ),
            SmartEssBleCandidate(
                address="11:22:33:44:55:66",
                local_pn="E50000200000009777",
                local_name="Bravo Collector",
            ),
        )

        with patch(
            "custom_components.eybond_local.flows.config.ble.async_probe_ble_host_capability",
            new=AsyncMock(return_value=types.SimpleNamespace(available=True)),
        ), patch.object(
            flow,
            "_async_discover_smartess_ble_candidates",
            new=AsyncMock(return_value=candidates),
        ), patch.object(
            flow,
            "_async_scan_smartess_ble_wifi_networks",
            new=AsyncMock(
                side_effect=(
                    (SmartEssBleWifiNetwork(ssid="Alpha WiFi", signal=92),),
                    (SmartEssBleWifiNetwork(ssid="Bravo WiFi", signal=88),),
                )
            ),
        ) as wifi_scan:
            await flow.async_step_bluetooth_setup()
            result = await flow.async_step_bluetooth_setup(
                {
                    "ble_address": "11:22:33:44:55:66",
                    CONF_BLE_ACTION: BLE_ACTION_REFRESH_WIFI,
                }
            )

        self.assertEqual(
            [call.args[0] for call in wifi_scan.await_args_list],
            ["AA:BB:CC:DD:EE:FF", "11:22:33:44:55:66"],
        )
        wifi_selector = result["data_schema"].schema["wifi_ssid"]
        options = wifi_selector.config.kwargs["options"]
        self.assertEqual(options[0]["value"], "Bravo WiFi")

    async def test_bluetooth_setup_switching_collectors_ignores_stale_wifi_submission(self) -> None:
        flow = self._make_flow()
        candidates = (
            SmartEssBleCandidate(
                address="AA:BB:CC:DD:EE:FF",
                local_pn="E50000200000000001",
                local_name="Alpha Collector",
            ),
            SmartEssBleCandidate(
                address="11:22:33:44:55:66",
                local_pn="E50000200000009777",
                local_name="Bravo Collector",
            ),
        )

        with patch(
            "custom_components.eybond_local.flows.config.ble.async_probe_ble_host_capability",
            new=AsyncMock(return_value=types.SimpleNamespace(available=True)),
        ), patch.object(
            flow,
            "_async_discover_smartess_ble_candidates",
            new=AsyncMock(return_value=candidates),
        ), patch.object(
            flow,
            "_async_scan_smartess_ble_wifi_networks",
            new=AsyncMock(
                side_effect=(
                    (SmartEssBleWifiNetwork(ssid="Alpha WiFi", signal=92),),
                    (SmartEssBleWifiNetwork(ssid="Bravo WiFi", signal=88),),
                )
            ),
        ) as wifi_scan, patch.object(
            flow,
            "_async_run_smartess_ble_bootstrap",
            new=AsyncMock(return_value=None),
        ) as bootstrap:
            await flow.async_step_bluetooth_setup()
            result = await flow.async_step_bluetooth_setup(
                {
                    "ble_address": "11:22:33:44:55:66",
                    "wifi_ssid": "Alpha WiFi",
                    "wifi_password": "Secret123",
                    CONF_BLE_ACTION: BLE_ACTION_REFRESH_WIFI,
                }
            )

        self.assertEqual(
            [call.args[0] for call in wifi_scan.await_args_list],
            ["AA:BB:CC:DD:EE:FF", "11:22:33:44:55:66"],
        )
        bootstrap.assert_not_awaited()
        self.assertEqual(result["errors"], {})
        wifi_selector = result["data_schema"].schema["wifi_ssid"]
        options = wifi_selector.config.kwargs["options"]
        self.assertEqual(options[0]["value"], "Bravo WiFi")

    async def test_bluetooth_setup_marks_and_rejects_already_added_ble_candidate(self) -> None:
        existing_entry = types.SimpleNamespace(
            entry_id="existing",
            unique_id="collector:E50000200000000001",
            data={"collector_pn": "E50000200000000001"},
            options={},
        )
        flow = self._make_flow(entries=[existing_entry])
        flow.context = {"entry_id": "existing"}
        candidates = (
            SmartEssBleCandidate(
                address="AA:BB:CC:DD:EE:FF",
                local_pn="E50000200000000001",
                local_name="Collector PN",
            ),
        )

        with patch(
            "custom_components.eybond_local.flows.config.ble.async_probe_ble_host_capability",
            new=AsyncMock(return_value=types.SimpleNamespace(available=True)),
        ), patch.object(
            flow,
            "_async_discover_smartess_ble_candidates",
            new=AsyncMock(return_value=candidates),
        ), patch.object(
            flow,
            "_async_scan_smartess_ble_wifi_networks",
            new=AsyncMock(return_value=()),
        ) as wifi_scan:
            first_result = await flow.async_step_bluetooth_setup()
            submit_result = await flow.async_step_bluetooth_setup(
                {"ble_address": "AA:BB:CC:DD:EE:FF"}
            )

        wifi_scan.assert_not_awaited()
        ble_selector = first_result["data_schema"].schema["ble_address"]
        options = ble_selector.config.kwargs["options"]
        self.assertIn("Already added", options[0]["label"])
        self.assertEqual(submit_result["errors"], {"ble_address": "already_added_candidate"})

    async def test_bluetooth_setup_reports_unstable_link_when_collector_wifi_scan_fails(self) -> None:
        flow = self._make_flow()
        candidates = (
            SmartEssBleCandidate(
                address="AA:BB:CC:DD:EE:FF",
                local_pn="E50000200000000001",
                local_name="Collector PN",
            ),
        )

        with patch(
            "custom_components.eybond_local.flows.config.ble.async_probe_ble_host_capability",
            new=AsyncMock(return_value=types.SimpleNamespace(available=True)),
        ), patch.object(
            flow,
            "_async_discover_smartess_ble_candidates",
            new=AsyncMock(return_value=candidates),
        ), patch.object(
            flow,
            "_async_scan_smartess_ble_wifi_networks",
            new=AsyncMock(side_effect=SmartEssBleError("ble_wifi_scan_failed:timeout")),
        ) as wifi_scan, patch.object(
            flow,
            "_async_run_smartess_ble_bootstrap",
            new=AsyncMock(return_value=None),
        ) as bootstrap:
            result = await flow.async_step_bluetooth_setup(
                {
                    "ble_address": "AA:BB:CC:DD:EE:FF",
                    "wifi_ssid": "Home WiFi",
                    "wifi_password": "Secret123",
                    CONF_BLE_ACTION: BLE_ACTION_REFRESH_WIFI,
                }
            )

        bootstrap.assert_not_awaited()
        self.assertEqual(result["type"], "form")
        self.assertEqual(result["step_id"], "bluetooth_setup")
        self.assertEqual(result["errors"], {"base": "ble_wifi_scan_failed"})
        self.assertEqual(flow._ble_last_error, "ble_wifi_scan_failed:timeout")

    async def test_bluetooth_setup_reports_unstable_link_on_first_entry_scan_failure(self) -> None:
        flow = self._make_flow()
        candidates = (
            SmartEssBleCandidate(
                address="AA:BB:CC:DD:EE:FF",
                local_pn="E50000200000000001",
                local_name="Collector PN",
            ),
        )

        with patch(
            "custom_components.eybond_local.flows.config.ble.async_probe_ble_host_capability",
            new=AsyncMock(return_value=types.SimpleNamespace(available=True)),
        ), patch.object(
            flow,
            "_async_discover_smartess_ble_candidates",
            new=AsyncMock(return_value=candidates),
        ), patch.object(
            flow,
            "_async_scan_smartess_ble_wifi_networks",
            new=AsyncMock(side_effect=SmartEssBleError("ble_wifi_scan_failed:timeout")),
        ):
            result = await flow.async_step_bluetooth_setup()

        self.assertEqual(result["type"], "form")
        self.assertEqual(result["errors"], {"base": "ble_wifi_scan_failed"})
        self.assertEqual(flow._ble_last_error, "ble_wifi_scan_failed:timeout")

    async def test_smartess_ble_wifi_scan_times_out(self) -> None:
        flow = self._make_flow()
        session = Mock()

        async def wait_forever() -> None:
            await asyncio.Event().wait()

        session.connect = AsyncMock(side_effect=wait_forever)
        session.disconnect = AsyncMock(return_value=None)

        with patch(
            "custom_components.eybond_local.flows.config.ble._BLE_CONNECT_TIMEOUT",
            0.001,
        ), patch(
            "custom_components.eybond_local.flows.config.ble.BleakSmartEssBleLink",
            return_value=sentinel.ble_link,
        ), patch(
            "custom_components.eybond_local.flows.config.ble.SmartEssBleSession",
            return_value=session,
        ):
            with self.assertRaisesRegex(SmartEssBleError, "ble_wifi_scan_failed:timeout"):
                await flow._async_scan_smartess_ble_wifi_networks("AA:BB:CC:DD:EE:FF")

        session.disconnect.assert_awaited_once()

    async def test_smartess_ble_wifi_scan_times_out_after_connect(self) -> None:
        flow = self._make_flow()
        session = Mock()
        provisioner = Mock()

        async def wait_forever() -> None:
            await asyncio.Event().wait()

        session.connect = AsyncMock(return_value=None)
        session.disconnect = AsyncMock(return_value=None)
        provisioner.scan_wifi_networks = AsyncMock(side_effect=wait_forever)

        with patch(
            "custom_components.eybond_local.flows.config.ble._BLE_WIFI_SCAN_TIMEOUT",
            0.001,
        ), patch(
            "custom_components.eybond_local.flows.config.ble.BleakSmartEssBleLink",
            return_value=sentinel.ble_link,
        ), patch(
            "custom_components.eybond_local.flows.config.ble.SmartEssBleSession",
            return_value=session,
        ), patch(
            "custom_components.eybond_local.flows.config.ble.SmartEssBleProvisioner",
            return_value=provisioner,
        ):
            with self.assertRaisesRegex(SmartEssBleError, "ble_wifi_scan_failed:timeout"):
                await flow._async_scan_smartess_ble_wifi_networks("AA:BB:CC:DD:EE:FF")

        session.disconnect.assert_awaited_once()

    async def test_smartess_ble_wifi_scan_maps_notification_timeout_to_scan_failure(self) -> None:
        flow = self._make_flow()
        session = Mock()
        provisioner = Mock()

        session.connect = AsyncMock(return_value=None)
        session.disconnect = AsyncMock(return_value=None)
        provisioner.scan_wifi_networks = AsyncMock(side_effect=SmartEssBleError("ble_notification_timeout"))

        with patch(
            "custom_components.eybond_local.flows.config.ble.BleakSmartEssBleLink",
            return_value=sentinel.ble_link,
        ), patch(
            "custom_components.eybond_local.flows.config.ble.SmartEssBleSession",
            return_value=session,
        ), patch(
            "custom_components.eybond_local.flows.config.ble.SmartEssBleProvisioner",
            return_value=provisioner,
        ), patch.object(
            flow,
            "_async_discover_smartess_ble_candidates",
            new=AsyncMock(return_value=()),
        ):
            with self.assertRaisesRegex(SmartEssBleError, "ble_wifi_scan_failed:notification_timeout"):
                await flow._async_scan_smartess_ble_wifi_networks("AA:BB:CC:DD:EE:FF")

        self.assertEqual(session.connect.await_count, 3)
        self.assertEqual(provisioner.scan_wifi_networks.await_count, 3)
        self.assertEqual(session.disconnect.await_count, 3)

    async def test_smartess_ble_wifi_scan_retries_once_after_transient_not_connected(self) -> None:
        flow = self._make_flow()
        session = Mock()
        provisioner = Mock()

        session.connect = AsyncMock(return_value=None)
        session.disconnect = AsyncMock(return_value=None)
        provisioner.scan_wifi_networks = AsyncMock(
            side_effect=(
                SmartEssBleError("ble_not_connected"),
                (SmartEssBleWifiNetwork(ssid="HomeNet", signal=98),),
            )
        )

        with patch(
            "custom_components.eybond_local.flows.config.ble.BleakSmartEssBleLink",
            return_value=sentinel.ble_link,
        ), patch(
            "custom_components.eybond_local.flows.config.ble.SmartEssBleSession",
            return_value=session,
        ), patch(
            "custom_components.eybond_local.flows.config.ble.SmartEssBleProvisioner",
            return_value=provisioner,
        ), patch.object(
            flow,
            "_async_discover_smartess_ble_candidates",
            new=AsyncMock(return_value=()),
        ):
            result = await flow._async_scan_smartess_ble_wifi_networks("AA:BB:CC:DD:EE:FF")

        self.assertEqual(result, (SmartEssBleWifiNetwork(ssid="HomeNet", signal=98),))
        self.assertEqual(session.connect.await_count, 2)
        self.assertEqual(provisioner.scan_wifi_networks.await_count, 2)
        self.assertEqual(session.disconnect.await_count, 2)

    async def test_smartess_ble_wifi_scan_retries_once_after_transient_gatt_error(self) -> None:
        flow = self._make_flow()
        first_session = Mock()
        second_session = Mock()
        first_provisioner = Mock()
        second_provisioner = Mock()

        first_session.connect = AsyncMock(return_value=None)
        first_session.disconnect = AsyncMock(return_value=None)
        first_provisioner.scan_wifi_networks = AsyncMock(
            side_effect=RuntimeError(
                "Bluetooth GATT Error address=AA:BB:CC:DD:EE:FF handle=30 error=133 description=Error"
            )
        )

        second_session.connect = AsyncMock(return_value=None)
        second_session.disconnect = AsyncMock(return_value=None)
        second_provisioner.scan_wifi_networks = AsyncMock(
            return_value=(SmartEssBleWifiNetwork(ssid="HomeNet", signal=98),)
        )
        refreshed_candidate = SmartEssBleCandidate(
            address="AA:BB:CC:DD:EE:FF",
            local_pn="E50000200000000001",
            local_name="Collector",
            device=sentinel.refreshed_ble_device,
        )
        discover = AsyncMock(return_value=(refreshed_candidate,))

        with patch(
            "custom_components.eybond_local.flows.config.ble.BleakSmartEssBleLink",
            side_effect=(sentinel.ble_link_first, sentinel.ble_link_second),
        ) as link_cls, patch(
            "custom_components.eybond_local.flows.config.ble.SmartEssBleSession",
            side_effect=(first_session, second_session),
        ), patch(
            "custom_components.eybond_local.flows.config.ble.SmartEssBleProvisioner",
            side_effect=(first_provisioner, second_provisioner),
        ), patch.object(
            flow,
            "_async_discover_smartess_ble_candidates",
            new=discover,
        ):
            result = await flow._async_scan_smartess_ble_wifi_networks("AA:BB:CC:DD:EE:FF")

        self.assertEqual(result, (SmartEssBleWifiNetwork(ssid="HomeNet", signal=98),))
        self.assertEqual(link_cls.call_count, 2)
        self.assertIsNone(link_cls.call_args_list[0].kwargs["device"])
        self.assertIs(link_cls.call_args_list[1].kwargs["device"], sentinel.refreshed_ble_device)
        discover.assert_awaited_once_with(force_active_scan=True)
        first_session.disconnect.assert_awaited_once()
        second_session.disconnect.assert_awaited_once()

    async def test_smartess_ble_wifi_scan_uses_home_assistant_device_lookup_for_manual_address(self) -> None:
        flow = self._make_flow()
        components_module = types.ModuleType("homeassistant.components")
        bluetooth_module = types.ModuleType("homeassistant.components.bluetooth")
        resolved_device = object()
        bluetooth_module.async_ble_device_from_address = Mock(return_value=resolved_device)

        session = Mock()
        provisioner = Mock()
        session.connect = AsyncMock(return_value=None)
        session.disconnect = AsyncMock(return_value=None)
        provisioner.scan_wifi_networks = AsyncMock(
            return_value=(SmartEssBleWifiNetwork(ssid="HomeNet", signal=98),)
        )

        with patch.dict(
            sys.modules,
            {
                "homeassistant.components": components_module,
                "homeassistant.components.bluetooth": bluetooth_module,
            },
        ), patch(
            "custom_components.eybond_local.flows.config.ble.BleakSmartEssBleLink",
        ) as link_cls, patch(
            "custom_components.eybond_local.flows.config.ble.SmartEssBleSession",
            return_value=session,
        ), patch(
            "custom_components.eybond_local.flows.config.ble.SmartEssBleProvisioner",
            return_value=provisioner,
        ):
            result = await flow._async_scan_smartess_ble_wifi_networks("AA:BB:CC:DD:EE:FF")

        link_cls.assert_called_once_with("AA:BB:CC:DD:EE:FF", device=resolved_device)
        self.assertEqual(result[0].ssid, "HomeNet")

    async def test_smartess_ble_wifi_scan_prefers_home_assistant_device_lookup_over_candidate_device(self) -> None:
        flow = self._make_flow()
        components_module = types.ModuleType("homeassistant.components")
        bluetooth_module = types.ModuleType("homeassistant.components.bluetooth")
        candidate_device = object()
        resolved_device = types.SimpleNamespace(name="Collector BLE")
        bluetooth_module.async_ble_device_from_address = Mock(return_value=resolved_device)

        session = Mock()
        provisioner = Mock()
        session.connect = AsyncMock(return_value=None)
        session.disconnect = AsyncMock(return_value=None)
        provisioner.scan_wifi_networks = AsyncMock(
            return_value=(SmartEssBleWifiNetwork(ssid="HomeNet", signal=98),)
        )

        with patch.dict(
            sys.modules,
            {
                "homeassistant.components": components_module,
                "homeassistant.components.bluetooth": bluetooth_module,
            },
        ), patch(
            "custom_components.eybond_local.flows.config.ble.BleakSmartEssBleLink",
        ) as link_cls, patch(
            "custom_components.eybond_local.flows.config.ble.SmartEssBleSession",
            return_value=session,
        ), patch(
            "custom_components.eybond_local.flows.config.ble.SmartEssBleProvisioner",
            return_value=provisioner,
        ):
            await flow._async_scan_smartess_ble_wifi_networks(
                "AA:BB:CC:DD:EE:FF",
                ble_device=candidate_device,
            )

        link_cls.assert_called_once_with("AA:BB:CC:DD:EE:FF", device=resolved_device)

    async def test_smartess_ble_wifi_scan_still_uses_home_assistant_device_when_name_is_missing(
        self,
    ) -> None:
        flow = self._make_flow()
        components_module = types.ModuleType("homeassistant.components")
        bluetooth_module = types.ModuleType("homeassistant.components.bluetooth")
        candidate_device = object()
        resolved_device = types.SimpleNamespace(name=None)
        bluetooth_module.async_ble_device_from_address = Mock(return_value=resolved_device)

        session = Mock()
        provisioner = Mock()
        session.connect = AsyncMock(return_value=None)
        session.disconnect = AsyncMock(return_value=None)
        provisioner.scan_wifi_networks = AsyncMock(
            return_value=(SmartEssBleWifiNetwork(ssid="HomeNet", signal=98),)
        )

        with patch.dict(
            sys.modules,
            {
                "homeassistant.components": components_module,
                "homeassistant.components.bluetooth": bluetooth_module,
            },
        ), patch(
            "custom_components.eybond_local.flows.config.ble.BleakSmartEssBleLink",
        ) as link_cls, patch(
            "custom_components.eybond_local.flows.config.ble.SmartEssBleSession",
            return_value=session,
        ), patch(
            "custom_components.eybond_local.flows.config.ble.SmartEssBleProvisioner",
            return_value=provisioner,
        ):
            await flow._async_scan_smartess_ble_wifi_networks(
                "AA:BB:CC:DD:EE:FF",
                ble_device=candidate_device,
            )

        link_cls.assert_called_once_with("AA:BB:CC:DD:EE:FF", device=resolved_device)

    async def test_smartess_ble_wifi_scan_uses_connectable_home_assistant_lookup_only(self) -> None:
        flow = self._make_flow()
        components_module = types.ModuleType("homeassistant.components")
        bluetooth_module = types.ModuleType("homeassistant.components.bluetooth")
        candidate_device = object()
        bluetooth_module.async_ble_device_from_address = Mock(return_value=None)

        session = Mock()
        provisioner = Mock()
        session.connect = AsyncMock(return_value=None)
        session.disconnect = AsyncMock(return_value=None)
        provisioner.scan_wifi_networks = AsyncMock(
            return_value=(SmartEssBleWifiNetwork(ssid="HomeNet", signal=98),)
        )

        with patch.dict(
            sys.modules,
            {
                "homeassistant.components": components_module,
                "homeassistant.components.bluetooth": bluetooth_module,
            },
        ), patch(
            "custom_components.eybond_local.flows.config.ble.BleakSmartEssBleLink",
        ) as link_cls, patch(
            "custom_components.eybond_local.flows.config.ble.SmartEssBleSession",
            return_value=session,
        ), patch(
            "custom_components.eybond_local.flows.config.ble.SmartEssBleProvisioner",
            return_value=provisioner,
        ):
            await flow._async_scan_smartess_ble_wifi_networks(
                "AA:BB:CC:DD:EE:FF",
                ble_device=candidate_device,
            )

        bluetooth_module.async_ble_device_from_address.assert_called_once_with(
            flow.hass,
            "AA:BB:CC:DD:EE:FF",
            connectable=True,
        )
        link_cls.assert_called_once_with("AA:BB:CC:DD:EE:FF", device=None)

    async def test_smartess_ble_wifi_scan_falls_back_to_candidate_device_without_home_assistant_lookup(self) -> None:
        flow = self._make_flow()
        candidate_device = object()

        session = Mock()
        provisioner = Mock()
        session.connect = AsyncMock(return_value=None)
        session.disconnect = AsyncMock(return_value=None)
        provisioner.scan_wifi_networks = AsyncMock(
            return_value=(SmartEssBleWifiNetwork(ssid="HomeNet", signal=98),)
        )

        with patch.object(
            config_ble_module,
            "BleakSmartEssBleLink",
        ) as link_cls, patch.object(
            config_ble_module.importlib,
            "import_module",
            side_effect=ImportError,
        ), patch.object(
            config_ble_module,
            "SmartEssBleSession",
            return_value=session,
        ), patch.object(
            config_ble_module,
            "SmartEssBleProvisioner",
            return_value=provisioner,
        ):
            await flow._async_scan_smartess_ble_wifi_networks(
                "AA:BB:CC:DD:EE:FF",
                ble_device=candidate_device,
            )

        link_cls.assert_called_once_with("AA:BB:CC:DD:EE:FF", device=candidate_device)

    async def test_smartess_ble_bootstrap_times_out(self) -> None:
        flow = self._make_flow()
        session = Mock()
        provisioner = Mock()

        async def wait_forever(*args, **kwargs) -> None:
            await asyncio.Event().wait()

        session.connect = AsyncMock(return_value=None)
        session.disconnect = AsyncMock(return_value=None)
        provisioner.provision_wifi = AsyncMock(side_effect=wait_forever)

        with patch(
            "custom_components.eybond_local.flows.config.ble._BLE_PROVISION_TIMEOUT",
            0.001,
        ), patch(
            "custom_components.eybond_local.flows.config.ble.BleakSmartEssBleLink",
            return_value=sentinel.ble_link,
        ), patch(
            "custom_components.eybond_local.flows.config.ble.SmartEssBleSession",
            return_value=session,
        ), patch(
            "custom_components.eybond_local.flows.config.ble.SmartEssBleProvisioner",
            return_value=provisioner,
        ):
            with self.assertRaisesRegex(SmartEssBleError, "ble_provision_failed:timeout"):
                await flow._async_run_smartess_ble_bootstrap(
                    ble_address="AA:BB:CC:DD:EE:FF",
                    ssid="Home WiFi",
                    password="Secret123",
                )

        session.disconnect.assert_awaited_once()

    async def test_smartess_ble_bootstrap_maps_notification_timeout_to_provision_failure(self) -> None:
        flow = self._make_flow()
        session = Mock()
        provisioner = Mock()

        session.connect = AsyncMock(return_value=None)
        session.disconnect = AsyncMock(return_value=None)
        provisioner.provision_wifi = AsyncMock(side_effect=SmartEssBleError("ble_notification_timeout"))

        with patch(
            "custom_components.eybond_local.flows.config.ble.BleakSmartEssBleLink",
            return_value=sentinel.ble_link,
        ), patch(
            "custom_components.eybond_local.flows.config.ble.SmartEssBleSession",
            return_value=session,
        ), patch(
            "custom_components.eybond_local.flows.config.ble.SmartEssBleProvisioner",
            return_value=provisioner,
        ):
            with self.assertRaisesRegex(SmartEssBleError, "ble_provision_failed:notification_timeout"):
                await flow._async_run_smartess_ble_bootstrap(
                    ble_address="AA:BB:CC:DD:EE:FF",
                    ssid="Home WiFi",
                    password="Secret123",
                )

        session.disconnect.assert_awaited_once()

    async def test_smartess_ble_wifi_scan_caches_firmware_version_from_preflight(self) -> None:
        flow = self._make_flow()
        session = Mock()
        provisioner = Mock()

        session.connect = AsyncMock(return_value=None)
        session.disconnect = AsyncMock(return_value=None)
        provisioner.scan_wifi_networks = AsyncMock(
            return_value=(SmartEssBleWifiNetwork(ssid="HomeNet", signal=98),)
        )
        provisioner.last_firmware_version = "8.50.8.18"

        with patch(
            "custom_components.eybond_local.flows.config.ble.BleakSmartEssBleLink",
            return_value=sentinel.ble_link,
        ), patch(
            "custom_components.eybond_local.flows.config.ble.SmartEssBleSession",
            return_value=session,
        ), patch(
            "custom_components.eybond_local.flows.config.ble.SmartEssBleProvisioner",
            return_value=provisioner,
        ):
            result = await flow._async_scan_smartess_ble_wifi_networks("AA:BB:CC:DD:EE:FF")

        self.assertEqual(result, (SmartEssBleWifiNetwork(ssid="HomeNet", signal=98),))
        self.assertEqual(flow._ble_fw_version_by_address["AA:BB:CC:DD:EE:FF"], "8.50.8.18")

    async def test_smartess_ble_bootstrap_reuses_cached_firmware_version_for_branch_probe(self) -> None:
        flow = self._make_flow()
        flow._ble_fw_version_by_address["AA:BB:CC:DD:EE:FF"] = "8.50.8.18"
        session = Mock()
        provisioner = Mock()
        resolved_info = SmartEssBleProvisioningInfo(
            fw_version="8.50.8.18",
            at_version="1.11",
            branch=SmartEssBleProvisionBranch.WFLKAP,
            requires_restart=False,
        )

        session.connect = AsyncMock(return_value=None)
        session.disconnect = AsyncMock(return_value=None)
        provisioner.query_device_info = AsyncMock(return_value=resolved_info)
        provisioner.provision_wifi = AsyncMock(
            return_value=SmartEssBleProvisionResult(
                branch=SmartEssBleProvisionBranch.WFLKAP,
                outcome=SmartEssBleProvisionOutcome.SUCCESS,
                status_code="W000",
                raw_response="AT+LINK:W000",
                details=None,
            )
        )
        provisioner.last_firmware_version = "8.50.8.18"

        with patch(
            "custom_components.eybond_local.flows.config.ble.BleakSmartEssBleLink",
            return_value=sentinel.ble_link,
        ), patch(
            "custom_components.eybond_local.flows.config.ble.SmartEssBleSession",
            return_value=session,
        ), patch(
            "custom_components.eybond_local.flows.config.ble.SmartEssBleProvisioner",
            return_value=provisioner,
        ):
            await flow._async_run_smartess_ble_bootstrap(
                ble_address="AA:BB:CC:DD:EE:FF",
                ssid="Home WiFi",
                password="Secret123",
            )

        provisioner.query_device_info.assert_awaited_once_with(known_fw_version="8.50.8.18")
        provisioner.provision_wifi.assert_awaited_once_with(
            ssid="Home WiFi",
            password="Secret123",
            info=resolved_info,
        )
        self.assertEqual(flow._ble_fw_version_by_address["AA:BB:CC:DD:EE:FF"], "8.50.8.18")

    async def test_smartess_ble_bootstrap_reuses_selected_result_firmware_when_cache_is_empty(self) -> None:
        flow = self._make_flow()
        flow._selected_result = OnboardingResult(
            collector=CollectorCandidate(
                target_ip="192.168.1.55",
                source="manual",
                ip="192.168.1.55",
                connected=True,
                collector=CollectorInfo(
                    collector_pn="PN123",
                    smartess_collector_version="8.50.12.3",
                ),
            )
        )
        session = Mock()
        provisioner = Mock()
        resolved_info = SmartEssBleProvisioningInfo(
            fw_version="8.50.12.3",
            at_version="1.10",
            branch=SmartEssBleProvisionBranch.WFLKAP,
            requires_restart=False,
        )

        session.connect = AsyncMock(return_value=None)
        session.disconnect = AsyncMock(return_value=None)
        provisioner.query_device_info = AsyncMock(return_value=resolved_info)
        provisioner.provision_wifi = AsyncMock(
            return_value=SmartEssBleProvisionResult(
                branch=SmartEssBleProvisionBranch.WFLKAP,
                outcome=SmartEssBleProvisionOutcome.SUCCESS,
                status_code="W000",
                raw_response="AT+LINK:W000",
                details=None,
            )
        )
        provisioner.last_firmware_version = ""

        with patch(
            "custom_components.eybond_local.flows.config.ble.BleakSmartEssBleLink",
            return_value=sentinel.ble_link,
        ), patch(
            "custom_components.eybond_local.flows.config.ble.SmartEssBleSession",
            return_value=session,
        ), patch(
            "custom_components.eybond_local.flows.config.ble.SmartEssBleProvisioner",
            return_value=provisioner,
        ):
            await flow._async_run_smartess_ble_bootstrap(
                ble_address="AA:BB:CC:DD:EE:FF",
                ssid="Home WiFi",
                password="Secret123",
            )

        provisioner.query_device_info.assert_awaited_once_with(known_fw_version="8.50.12.3")
        provisioner.provision_wifi.assert_awaited_once_with(
            ssid="Home WiFi",
            password="Secret123",
            info=resolved_info,
        )
        self.assertNotIn("AA:BB:CC:DD:EE:FF", flow._ble_fw_version_by_address)

    async def test_bluetooth_setup_falls_back_to_manual_address_when_scan_is_empty(self) -> None:
        flow = self._make_flow()

        with patch(
            "custom_components.eybond_local.flows.config.ble.async_probe_ble_host_capability",
            new=AsyncMock(return_value=types.SimpleNamespace(available=True)),
        ), patch.object(
            flow,
            "_async_discover_smartess_ble_candidates",
            new=AsyncMock(return_value=()),
        ):
            result = await flow.async_step_bluetooth_setup({CONF_BLE_ACTION: BLE_ACTION_REFRESH_WIFI})

        ble_selector = result["data_schema"].schema["ble_address"]
        self.assertNotIn("options", ble_selector.config.kwargs)
        wifi_selector = result["data_schema"].schema["wifi_ssid"]
        self.assertEqual(wifi_selector.config.kwargs["options"], [])
        self.assertTrue(wifi_selector.config.kwargs["custom_value"])

    async def test_bluetooth_setup_refresh_action_refreshes_candidates_without_bootstrap(self) -> None:
        flow = self._make_flow()

        with patch(
            "custom_components.eybond_local.flows.config.ble.async_probe_ble_host_capability",
            new=AsyncMock(return_value=types.SimpleNamespace(available=True)),
        ), patch.object(
            flow,
            "_async_discover_smartess_ble_candidates",
            new=AsyncMock(
                return_value=(
                    SmartEssBleCandidate(
                        address="11:22:33:44:55:66",
                        local_pn="A9999999999999",
                        local_name="Rescanned Collector",
                    ),
                )
            ),
        ) as discover, patch.object(
            flow,
            "_async_scan_smartess_ble_wifi_networks",
            new=AsyncMock(
                return_value=(
                    SmartEssBleWifiNetwork(ssid="HomeNet", signal=-42),
                )
            ),
        ) as wifi_scan, patch.object(
            flow,
            "_async_run_smartess_ble_bootstrap",
            new=AsyncMock(return_value=None),
        ) as bootstrap:
            result = await flow.async_step_bluetooth_setup(
                {
                    CONF_BLE_ACTION: BLE_ACTION_REFRESH_WIFI,
                }
            )

        discover.assert_awaited_once_with(force_active_scan=True)
        wifi_scan.assert_awaited_once_with("11:22:33:44:55:66", ble_device=None)
        bootstrap.assert_not_awaited()
        self.assertEqual(result["type"], "form")
        self.assertEqual(result["step_id"], "bluetooth_setup")
        ble_selector = result["data_schema"].schema["ble_address"]
        options = ble_selector.config.kwargs["options"]
        self.assertEqual([option["value"] for option in options], ["11:22:33:44:55:66"])
        wifi_selector = result["data_schema"].schema["wifi_ssid"]
        self.assertEqual(wifi_selector.config.kwargs["options"][0]["value"], "HomeNet")

    async def test_bluetooth_setup_rescan_action_refreshes_collectors_without_wifi_scan(self) -> None:
        flow = self._make_flow()

        with patch(
            "custom_components.eybond_local.flows.config.ble.async_probe_ble_host_capability",
            new=AsyncMock(return_value=types.SimpleNamespace(available=True)),
        ), patch.object(
            flow,
            "_async_discover_smartess_ble_candidates",
            new=AsyncMock(
                return_value=(
                    SmartEssBleCandidate(
                        address="11:22:33:44:55:66",
                        local_pn="A9999999999999",
                        local_name="Rescanned Collector",
                    ),
                )
            ),
        ) as discover, patch.object(
            flow,
            "_async_scan_smartess_ble_wifi_networks",
            new=AsyncMock(return_value=()),
        ) as wifi_scan, patch.object(
            flow,
            "_async_run_smartess_ble_bootstrap",
            new=AsyncMock(return_value=None),
        ) as bootstrap:
            result = await flow.async_step_bluetooth_setup(
                {
                    CONF_BLE_ACTION: BLE_ACTION_RESCAN,
                }
            )

        discover.assert_awaited_once_with(force_active_scan=True)
        wifi_scan.assert_not_awaited()
        bootstrap.assert_not_awaited()
        self.assertEqual(result["type"], "form")
        self.assertEqual(result["step_id"], "bluetooth_setup")
        action_selector = result["data_schema"].schema[CONF_BLE_ACTION]
        self.assertEqual(
            [option["value"] for option in action_selector.config.kwargs["options"]],
            [BLE_ACTION_RESCAN, BLE_ACTION_REFRESH_WIFI, BLE_ACTION_APPLY],
        )

    async def test_bluetooth_setup_refresh_action_keeps_selected_collector_when_still_available(self) -> None:
        flow = self._make_flow()
        candidates = (
            SmartEssBleCandidate(
                address="AA:BB:CC:DD:EE:FF",
                local_pn="E50000200000000001",
                local_name="Alpha Collector",
            ),
            SmartEssBleCandidate(
                address="11:22:33:44:55:66",
                local_pn="E50000200000009777",
                local_name="Bravo Collector",
            ),
        )

        with patch(
            "custom_components.eybond_local.flows.config.ble.async_probe_ble_host_capability",
            new=AsyncMock(return_value=types.SimpleNamespace(available=True)),
        ), patch.object(
            flow,
            "_async_discover_smartess_ble_candidates",
            new=AsyncMock(return_value=candidates),
        ) as discover, patch.object(
            flow,
            "_async_scan_smartess_ble_wifi_networks",
            new=AsyncMock(
                side_effect=(
                    (SmartEssBleWifiNetwork(ssid="Alpha WiFi", signal=92),),
                    (SmartEssBleWifiNetwork(ssid="Bravo WiFi", signal=88),),
                    (SmartEssBleWifiNetwork(ssid="Bravo WiFi Refreshed", signal=86),),
                )
            ),
        ) as wifi_scan:
            await flow.async_step_bluetooth_setup()
            await flow.async_step_bluetooth_setup(
                {
                    "ble_address": "11:22:33:44:55:66",
                    CONF_BLE_ACTION: BLE_ACTION_REFRESH_WIFI,
                }
            )
            result = await flow.async_step_bluetooth_setup(
                {
                    "ble_address": "11:22:33:44:55:66",
                    CONF_BLE_ACTION: BLE_ACTION_REFRESH_WIFI,
                }
            )

        self.assertEqual(discover.await_count, 3)
        self.assertEqual(
            [call.args[0] for call in wifi_scan.await_args_list],
            ["AA:BB:CC:DD:EE:FF", "11:22:33:44:55:66", "11:22:33:44:55:66"],
        )
        wifi_selector = result["data_schema"].schema["wifi_ssid"]
        self.assertEqual(
            wifi_selector.config.kwargs["options"][0]["value"],
            "Bravo WiFi Refreshed",
        )

    async def test_bluetooth_setup_keeps_cached_wifi_networks_when_refresh_scan_fails(self) -> None:
        flow = self._make_flow()
        candidates = (
            SmartEssBleCandidate(
                address="AA:BB:CC:DD:EE:FF",
                local_pn="E50000200000000001",
                local_name="Collector PN",
            ),
        )
        cached_networks = (
            SmartEssBleWifiNetwork(ssid="HomeNet", signal=92),
            SmartEssBleWifiNetwork(ssid="Office", signal=58),
        )

        with patch(
            "custom_components.eybond_local.flows.config.ble.async_probe_ble_host_capability",
            new=AsyncMock(return_value=types.SimpleNamespace(available=True)),
        ), patch.object(
            flow,
            "_async_discover_smartess_ble_candidates",
            new=AsyncMock(return_value=candidates),
        ) as discover, patch.object(
            flow,
            "_async_scan_smartess_ble_wifi_networks",
            new=AsyncMock(
                side_effect=(
                    cached_networks,
                    SmartEssBleError("ble_wifi_scan_failed:timeout"),
                )
            ),
        ) as wifi_scan:
            first_result = await flow.async_step_bluetooth_setup()
            refreshed_result = await flow.async_step_bluetooth_setup(
                {
                    "ble_address": "AA:BB:CC:DD:EE:FF",
                    CONF_BLE_ACTION: BLE_ACTION_REFRESH_WIFI,
                }
            )

        self.assertEqual(discover.await_count, 2)
        self.assertEqual(wifi_scan.await_count, 2)
        self.assertEqual(first_result["errors"], {})
        self.assertEqual(refreshed_result["errors"], {})
        refreshed_wifi_selector = refreshed_result["data_schema"].schema["wifi_ssid"]
        refreshed_options = refreshed_wifi_selector.config.kwargs["options"]
        self.assertEqual([option["value"] for option in refreshed_options], ["HomeNet", "Office"])
        self.assertEqual(refreshed_result["description_placeholders"]["ble_last_error"], "ble_wifi_scan_failed:timeout")

    async def test_bluetooth_setup_keeps_detailed_provision_failure_code(self) -> None:
        flow = self._make_flow()
        flow._auto_config = {"connection_type": "eybond", "server_ip": "192.168.1.50"}

        with patch(
            "custom_components.eybond_local.flows.config.ble.async_probe_ble_host_capability",
            new=AsyncMock(return_value=types.SimpleNamespace(available=True)),
        ), patch.object(
            flow,
            "_async_discover_smartess_ble_candidates",
            new=AsyncMock(
                return_value=(
                    SmartEssBleCandidate(
                        address="AA:BB:CC:DD:EE:FF",
                        local_pn="E50000200000000001",
                        local_name="Collector PN",
                    ),
                )
            ),
        ), patch.object(
            flow,
            "_async_scan_smartess_ble_wifi_networks",
            new=AsyncMock(return_value=()),
        ), patch.object(
            flow,
            "_async_run_smartess_ble_bootstrap",
            new=AsyncMock(side_effect=SmartEssBleError("ble_provision_failed:wflkap:W008")),
        ):
            result = await flow.async_step_bluetooth_setup(
                {
                    "ble_address": "AA:BB:CC:DD:EE:FF",
                    "wifi_ssid": "HomeNet",
                    "wifi_password": "55555555",
                    CONF_BLE_ACTION: BLE_ACTION_APPLY,
                }
            )

        self.assertEqual(result["type"], "form")
        self.assertEqual(result["errors"], {"base": "ble_provision_failed"})
        self.assertEqual(flow._ble_last_error, "ble_provision_failed:wflkap:W008")

    async def test_bluetooth_setup_runs_bootstrap_then_returns_to_scan_interface(self) -> None:
        flow = self._make_flow()
        async def _fake_scanning(user_input=None):
            return {"type": "progress", "step_id": "scanning"}

        flow.async_step_scanning = _fake_scanning
        flow._auto_config = {"connection_type": "eybond", "server_ip": "192.168.1.50"}

        with patch(
            "custom_components.eybond_local.flows.config.ble.async_probe_ble_host_capability",
            new=AsyncMock(return_value=types.SimpleNamespace(available=True)),
        ), patch.object(
            flow,
            "_async_discover_smartess_ble_candidates",
            new=AsyncMock(
                return_value=(
                    SmartEssBleCandidate(
                        address="AA:BB:CC:DD:EE:FF",
                        local_pn="A0000000000001",
                        local_name="Alpha Collector",
                    ),
                )
            ),
        ), patch.object(
            flow,
            "_async_scan_smartess_ble_wifi_networks",
            new=AsyncMock(
                return_value=(
                    SmartEssBleWifiNetwork(ssid="Home WiFi", signal=-42),
                )
            ),
        ), patch.object(
            flow,
            "_async_run_smartess_ble_bootstrap",
            new=AsyncMock(return_value=None),
        ) as bootstrap:
            result = await flow.async_step_bluetooth_setup(
                {
                    "ble_address": "AA:BB:CC:DD:EE:FF",
                    "wifi_ssid": "Manual WiFi",
                    "wifi_password": "Secret123",
                    CONF_BLE_ACTION: BLE_ACTION_APPLY,
                }
            )

        bootstrap.assert_awaited_once_with(
            ble_address="AA:BB:CC:DD:EE:FF",
            ssid="Manual WiFi",
            password="Secret123",
            ble_device=None,
        )
        # One interface: provisioning returns to auto, which auto-advances to scan.
        self.assertEqual(result["type"], "progress")
        self.assertEqual(result["step_id"], "scanning")

    async def test_bluetooth_setup_accepts_hidden_wifi_name_with_single_custom_selector(
        self,
    ) -> None:
        flow = self._make_flow()
        async def _fake_scanning(user_input=None):
            return {"type": "progress", "step_id": "scanning"}

        flow.async_step_scanning = _fake_scanning
        flow._auto_config = {"connection_type": "eybond", "server_ip": "192.168.1.50"}

        with patch(
            "custom_components.eybond_local.flows.config.ble.async_probe_ble_host_capability",
            new=AsyncMock(return_value=types.SimpleNamespace(available=True)),
        ), patch.object(
            flow,
            "_async_discover_smartess_ble_candidates",
            new=AsyncMock(
                return_value=(
                    SmartEssBleCandidate(
                        address="AA:BB:CC:DD:EE:FF",
                        local_pn="A0000000000001",
                        local_name="Alpha Collector",
                    ),
                )
            ),
        ), patch.object(
            flow,
            "_async_scan_smartess_ble_wifi_networks",
            new=AsyncMock(
                return_value=(
                    SmartEssBleWifiNetwork(ssid="HomeNet", signal=-42),
                    SmartEssBleWifiNetwork(ssid="Office", signal=-58),
                )
            ),
        ), patch.object(
            flow,
            "_async_run_smartess_ble_bootstrap",
            new=AsyncMock(return_value=None),
        ) as bootstrap:
            result = await flow.async_step_bluetooth_setup(
                {
                    "ble_address": "AA:BB:CC:DD:EE:FF",
                    "wifi_ssid": "Hidden WiFi",
                    "wifi_password": "Secret123",
                    CONF_BLE_ACTION: BLE_ACTION_APPLY,
                }
            )

        bootstrap.assert_awaited_once_with(
            ble_address="AA:BB:CC:DD:EE:FF",
            ssid="Hidden WiFi",
            password="Secret123",
            ble_device=None,
        )
        self.assertEqual(result["type"], "progress")
        self.assertEqual(result["step_id"], "scanning")

    async def test_change_scan_interface_preserves_connection_type(self) -> None:
        flow = self._make_flow()
        flow._auto_config = {"connection_type": "eybond", "server_ip": "192.168.1.50"}

        async def _fake_scanning(user_input=None):
            return {"type": "progress", "step_id": "scanning"}

        flow.async_step_scanning = _fake_scanning

        result = await flow.async_step_change_scan_interface({"server_ip": "192.168.2.50"})

        self.assertEqual(result["type"], "progress")
        self.assertEqual(flow._auto_config["connection_type"], "eybond")
        self.assertEqual(flow._auto_config["server_ip"], "192.168.2.50")

    async def test_scan_results_without_results_offers_advanced_setup(self) -> None:
        flow = self._make_flow()
        flow._autodetect_results = {}
        flow._scan_error = True

        result = await flow.async_step_scan_results()

        self.assertEqual(result["type"], "form")
        self.assertEqual(result["step_id"], "scan_results")
        options = _schema_select_options(result["data_schema"], "result_key")
        self.assertEqual(
            list(options),
            ["action:refresh_scan", "action:advanced_setup"],
        )

    async def test_advanced_setup_submenu_exposes_manual_and_refresh_only(self) -> None:
        flow = self._make_flow()

        result = await flow.async_step_advanced_setup()

        self.assertEqual(result["type"], "menu")
        self.assertEqual(result["step_id"], "advanced_setup")
        self.assertEqual(result["menu_options"], ["manual", "refresh_scan"])

    async def test_advanced_setup_offers_change_interface_with_multiple(self) -> None:
        flow = self._make_flow()
        flow._interface_options = [
            {"name": "eth0", "ip": "192.168.1.50", "label": "eth0 - 192.168.1.50"},
            {"name": "wlan0", "ip": "192.168.2.50", "label": "wlan0 - 192.168.2.50"},
        ]

        result = await flow.async_step_advanced_setup()

        self.assertIn("change_scan_interface", result["menu_options"])

    async def test_scan_results_always_offers_advanced_setup(self) -> None:
        flow = self._make_flow()

        result = await flow.async_step_scan_results()

        options = _schema_select_options(result["data_schema"], "result_key")
        self.assertIn("action:advanced_setup", options)

    def test_collapse_merges_skip_marker_with_pn_result_for_same_collector(self) -> None:
        flow = self._make_flow()
        skip_marker = OnboardingResult(
            collector=CollectorCandidate(
                target_ip="192.168.1.14",
                source="subnet_unicast",
                ip="192.168.1.14",
            ),
            connection_mode="subnet_unicast",
            last_error="already_configured",
        )
        inventory_result = OnboardingResult(
            collector=CollectorCandidate(
                target_ip="192.168.1.255",
                source="broadcast",
                ip="192.168.1.14",
                collector=CollectorInfo(
                    remote_ip="192.168.1.14",
                    collector_pn="Q0000000000001",
                ),
            ),
            connection_mode="broadcast",
            next_action="manual_driver_selection",
            last_error="collector_detected_without_driver",
        )
        other = OnboardingResult(
            collector=CollectorCandidate(
                target_ip="192.168.1.51",
                source="subnet_unicast",
                ip="192.168.1.51",
                collector=CollectorInfo(remote_ip="192.168.1.51", collector_pn="V0000000000001"),
            ),
            connection_mode="subnet_unicast",
        )

        collapsed = flow._collapse_scan_results([skip_marker, inventory_result, other])

        self.assertEqual(len(collapsed), 2)
        merged = next(r for r in collapsed if r.collector.ip == "192.168.1.14")
        # The PN-carrying duplicate wins so the line shows the identity.
        self.assertEqual(merged.collector.collector.collector_pn, "Q0000000000001")

    async def test_scan_results_refresh_label_names_unified_scan(self) -> None:
        flow = self._make_flow()
        flow._autodetect_results = {}

        self.assertEqual(
            flow._refresh_scan_action_label(), "Refresh scan results"
        )
        placeholders = flow._scan_results_placeholders()
        self.assertIn(
            "Refresh scan results",
            placeholders["scan_next_hint"],
        )

    async def test_scan_results_with_available_results_offers_direct_selection(self) -> None:
        flow = self._make_flow()
        flow._autodetect_results = {
            "0": OnboardingResult(
                collector=CollectorCandidate(target_ip="192.168.1.14", source="udp", ip="192.168.1.14", connected=True),
                match=DriverMatch(
                    driver_key="pi30",
                    protocol_family="pi30",
                    model_name="PowMr 4.2kW",
                    serial_number="553555355535552",
                    probe_target=ProbeTarget(devcode=0x0994, collector_addr=0x01, device_addr=0),
                ),
                connection_mode="known_ip",
            )
        }

        result = await flow.async_step_scan_results()

        self.assertEqual(result["type"], "form")
        self.assertEqual(result["step_id"], "scan_results")
        options = _schema_select_options(result["data_schema"], "result_key")
        self.assertEqual(
            list(options),
            ["0", "action:refresh_scan", "action:advanced_setup"],
        )
        self.assertIn("scan_summary", result["description_placeholders"])

        with patch.object(flow, "_existing_entry_for_result", return_value=None):
            submit = await flow.async_step_scan_results({"result_key": "0"})

        self.assertEqual(submit["step_id"], "confirm")
        self.assertIs(flow._selected_result, flow._autodetect_results["0"])

    async def test_scan_results_udp_only_route_is_selectable_for_identification(self) -> None:
        flow = self._make_flow()
        flow._autodetect_results = {
            "0": OnboardingResult(
                collector=CollectorCandidate(
                    target_ip="192.168.1.14",
                    source="subnet_unicast",
                    ip="192.168.1.14",
                    udp_reply="rsp>server=1;",
                    connected=False,
                ),
                connection_mode="subnet_unicast",
                next_action="manual_input",
                last_error="collector_not_connected",
            )
        }

        result = await flow.async_step_scan_results()

        self.assertEqual(result["type"], "form")
        options = _schema_select_options(result["data_schema"], "result_key")
        self.assertIn("0", options)
        self.assertIn(
            "Check address 192.168.1.14",
            flow._result_label(flow._autodetect_results["0"]),
        )
        self.assertIn("action:refresh_scan", options)
        self.assertIn("192.168.1.14", result["description_placeholders"]["candidate_list"])
        self.assertIn(
            "no device has been identified yet",
            result["description_placeholders"]["scan_summary"],
        )

    async def test_scan_results_nat_peer_and_route_have_distinct_safe_actions(self) -> None:
        flow = self._make_flow()
        flow.hass.config.language = "uk"
        full_pn = "E50000200000000001"
        flow._autodetect_results = {
            "0": OnboardingResult(
                collector=CollectorCandidate(
                    target_ip="192.168.1.255",
                    source="callback_listener",
                    ip="192.168.1.1",
                    connected=True,
                    collector=CollectorInfo(
                        remote_ip="192.168.1.1",
                        collector_pn=full_pn,
                    ),
                ),
                connection_mode="callback_listener",
                observed_session=ObservedCollectorSession(
                    collector_pn=full_pn,
                    identity_source="fc2_parameter_2",
                    session_id="listener-8899-2",
                    listener_port=8899,
                    protocol_shape="eybond_framed",
                    peer_hint="192.168.1.1",
                ),
            ),
            "1": OnboardingResult(
                collector=CollectorCandidate(
                    target_ip="192.168.1.55",
                    source="subnet_unicast",
                    ip="192.168.1.55",
                    udp_reply="rsp>server=1;",
                    udp_reply_from="192.168.1.1:58899",
                    connected=False,
                ),
                connection_mode="subnet_unicast",
                next_action="manual_input",
                last_error="collector_not_connected",
            ),
        }

        result = await flow.async_step_scan_results()

        options = _schema_select_options(result["data_schema"], "result_key")
        self.assertIn("0", options)
        self.assertIn("1", options)
        self.assertIn(
            "Перевірити адресу 192.168.1.55",
            flow._result_label(flow._autodetect_results["1"]),
        )
        candidate_list = result["description_placeholders"]["candidate_list"]
        self.assertIn(f"PN {full_pn}", candidate_list)
        self.assertIn("з’єднання від 192.168.1.1", candidate_list)
        self.assertIn("Потребує уточнення", candidate_list)
        self.assertNotIn("вкажіть адресу", candidate_list)
        self.assertIn("192.168.1.55", candidate_list)
        self.assertIn(
            "Доступні для налаштування: **1**",
            result["description_placeholders"]["scan_summary"],
        )

    def test_scan_discovery_targets_use_selected_broadcast_only(self) -> None:
        flow = self._make_flow()

        targets = flow._scan_discovery_targets()

        self.assertEqual(
            targets,
            (DiscoveryTarget(ip="192.168.255.255", source="broadcast"),),
        )

    async def test_choose_step_shows_selector_form(self) -> None:
        flow = self._make_flow()
        flow._autodetect_results = {
            "0": OnboardingResult(
                collector=CollectorCandidate(target_ip="192.168.1.14", source="udp", ip="192.168.1.14", connected=True),
                match=DriverMatch(
                    driver_key="pi30",
                    protocol_family="pi30",
                    model_name="PowMr 4.2kW",
                    serial_number="553555355535552",
                    probe_target=ProbeTarget(devcode=0x0994, collector_addr=0x01, device_addr=0),
                ),
                connection_mode="known_ip",
            ),
            "1": OnboardingResult(
                collector=CollectorCandidate(target_ip="192.168.1.55", source="udp", ip="192.168.1.55", connected=True),
                match=DriverMatch(
                    driver_key="modbus_smg",
                    protocol_family="modbus_smg",
                    model_name="SMG 6200",
                    serial_number="92632500000001",
                    probe_target=ProbeTarget(devcode=0x0001, collector_addr=0x01, device_addr=1),
                ),
                connection_mode="known_ip",
            ),
        }

        result = await flow.async_step_choose()

        self.assertEqual(result["type"], "form")
        self.assertEqual(result["step_id"], "choose")

    async def test_confirm_step_exposes_poll_mode_field(self) -> None:
        flow = self._make_flow()
        flow._selected_result = OnboardingResult(
            collector=CollectorCandidate(target_ip="192.168.1.55", source="udp", ip="192.168.1.55", connected=True),
            match=DriverMatch(
                driver_key="modbus_smg",
                protocol_family="modbus_smg",
                model_name="SMG 6200",
                serial_number="92632500000001",
                probe_target=ProbeTarget(devcode=0x0001, collector_addr=0x01, device_addr=1),
            ),
            connection_mode="known_ip",
        )

        result = await flow.async_step_confirm()

        self.assertEqual(result["type"], "form")
        self.assertEqual(result["step_id"], "confirm")
        self.assertIn(CONF_DRIVER_DETECTION_STRATEGY, result["data_schema"].schema)
        self.assertIn("poll_mode", result["data_schema"].schema)
        self.assertNotIn("poll_interval", result["data_schema"].schema)
        self.assertNotIn(CONF_COLLECTOR_OPERATION_MODE, result["data_schema"].schema)

        manual_result = await flow.async_step_confirm({"poll_mode": "manual"})

        self.assertEqual(manual_result["type"], "form")
        self.assertEqual(manual_result["step_id"], "confirm_poll_interval")
        self.assertIn("poll_interval", manual_result["data_schema"].schema)

    async def test_confirm_step_defers_scan_time_inverter_identity_to_runtime(self) -> None:
        flow = self._make_flow()
        flow._selected_result = OnboardingResult(
            collector=CollectorCandidate(
                target_ip="192.168.1.55",
                source="udp",
                ip="192.168.1.55",
                connected=True,
                collector=CollectorInfo(collector_pn="PN123"),
            ),
            match=DriverMatch(
                driver_key="modbus_smg",
                protocol_family="modbus_smg",
                model_name="SMG 6200",
                serial_number="92632500000001",
                probe_target=ProbeTarget(devcode=0x0001, collector_addr=0x01, device_addr=1),
                details={
                    "rated_power": 6200,
                    "collector_signal_strength": -67,
                    "battery_connected": True,
                    "battery_percent": 78,
                },
            ),
            connection_mode="known_ip",
        )

        result = await flow.async_step_confirm()

        self.assertEqual(result["type"], "form")
        placeholders = result["description_placeholders"]
        self.assertIn("**Collector**", placeholders["collector_confirm_table"])
        self.assertIn("| Collector PN | PN123 |", placeholders["collector_confirm_table"])
        self.assertIn("| Collector IP | 192.168.1.55 |", placeholders["collector_confirm_table"])
        self.assertNotIn("Collector Signal Strength", placeholders["collector_confirm_table"])
        self.assertIn("**Inverter**", placeholders["inverter_confirm_table"])
        self.assertIn("will detect the connected inverter", placeholders["inverter_confirm_table"])
        self.assertNotIn("SMG 6200", placeholders["inverter_confirm_table"])
        self.assertNotIn("92632500000001", placeholders["inverter_confirm_table"])

    async def test_confirm_step_passive_callback_without_match_defers_inverter_table(self) -> None:
        flow = self._make_flow()
        flow.hass.config.language = "uk"
        flow._selected_result = OnboardingResult(
            collector=CollectorCandidate(
                target_ip="192.168.1.50",
                source="callback_listener",
                ip="195.138.86.175",
                connected=True,
                collector=CollectorInfo(collector_pn="V001020SYN62344022"),
            ),
            connection_mode="callback_listener",
            next_action="manual_driver_selection",
        )

        result = await flow.async_step_confirm()

        self.assertEqual(result["type"], "form")
        placeholders = result["description_placeholders"]
        self.assertIn("**Колектор**", placeholders["collector_confirm_table"])
        self.assertIn("**Інвертор**", placeholders["inverter_confirm_table"])
        self.assertIn("Після додавання пристрою", placeholders["inverter_confirm_table"])
        self.assertNotIn("| Модель |", placeholders["inverter_confirm_table"])
        self.assertNotIn("Непідтверджений інвертор", placeholders["inverter_confirm_table"])
        self.assertEqual(placeholders["control_summary"], "")

    async def test_confirm_step_has_no_pre_entry_capability_probe(self) -> None:
        flow = self._make_flow()
        selected = OnboardingResult(
            collector=CollectorCandidate(
                target_ip="192.168.1.50",
                source="callback_listener",
                ip="195.138.86.175",
                connected=True,
                collector=CollectorInfo(collector_pn="V001020SYN62344022"),
            ),
            connection_mode="callback_listener",
            next_action="manual_driver_selection",
        )
        flow._autodetect_results = {"0": selected}
        flow._selected_result = selected

        result = await flow.async_step_confirm()

        self.assertEqual(result["type"], "form")
        self.assertFalse(
            hasattr(flow, "_async_refresh_selected_result_collector_capabilities")
        )

    async def test_confirm_step_passive_callback_submit_creates_ha_only_entry_without_binding(self) -> None:
        flow = self._make_flow()
        selected = OnboardingResult(
            collector=CollectorCandidate(
                target_ip="192.168.1.50",
                source="callback_listener",
                ip="195.138.86.175",
                connected=True,
                collector=CollectorInfo(collector_pn="V001020SYN62344022"),
            ),
            connection_mode="callback_listener",
            next_action="manual_driver_selection",
        )
        flow._selected_result = selected

        result = await flow.async_step_confirm({"poll_mode": "auto"})

        self.assertEqual(result["type"], "create_entry")
        self.assertEqual(result["data"]["connection_mode"], "callback_listener")
        self.assertNotIn("collector_ip", result["data"])
        self.assertNotIn(CONF_COLLECTOR_OPERATION_MODE, result["data"])
        self.assertNotIn(CONF_COLLECTOR_OPERATION_MODE, result["options"])
        self.assertEqual(
            result["data"][CONF_CONNECTION_STRATEGY], CONNECTION_STRATEGY_INBOUND
        )

    async def test_confirm_step_does_not_present_missing_scan_time_inverter_fields(self) -> None:
        flow = self._make_flow()
        flow._selected_result = OnboardingResult(
            collector=CollectorCandidate(
                target_ip="192.168.1.55",
                source="udp",
                ip="192.168.1.55",
                connected=True,
                collector=CollectorInfo(collector_pn="PN123"),
            ),
            match=DriverMatch(
                driver_key="modbus_smg",
                protocol_family="modbus_smg",
                model_name="SMG 6200",
                serial_number="92632500000001",
                probe_target=ProbeTarget(devcode=0x0001, collector_addr=0x01, device_addr=1),
            ),
            connection_mode="known_ip",
        )

        result = await flow.async_step_confirm()

        self.assertEqual(result["type"], "form")
        placeholders = result["description_placeholders"]
        self.assertNotIn("Collector Signal Strength", placeholders["collector_confirm_table"])
        self.assertIn("will detect the connected inverter", placeholders["inverter_confirm_table"])
        self.assertNotIn("Rated Power", placeholders["inverter_confirm_table"])

    async def test_confirm_step_uses_collector_pn_from_enriched_match_details(self) -> None:
        flow = self._make_flow()
        flow._selected_result = OnboardingResult(
            collector=CollectorCandidate(
                target_ip="192.168.1.55",
                source="udp",
                ip="192.168.1.55",
                connected=True,
                collector=CollectorInfo(),
            ),
            match=DriverMatch(
                driver_key="modbus_smg",
                protocol_family="modbus_smg",
                model_name="SMG 6200",
                serial_number="92632500000001",
                probe_target=ProbeTarget(devcode=0x0001, collector_addr=0x01, device_addr=1),
                details={
                    "collector_pn": "PN999",
                },
            ),
            connection_mode="known_ip",
        )

        result = await flow.async_step_confirm()

        self.assertEqual(result["type"], "form")
        placeholders = result["description_placeholders"]
        self.assertIn("| Collector PN | PN999 |", placeholders["collector_confirm_table"])

    async def test_confirm_step_does_not_refresh_runtime_details_for_autodetected_result(self) -> None:
        flow = self._make_flow()
        selected_result = OnboardingResult(
            collector=CollectorCandidate(
                target_ip="192.168.1.55",
                source="broadcast",
                ip="192.168.1.55",
                connected=True,
                collector=CollectorInfo(collector_pn="PN123"),
            ),
            match=DriverMatch(
                driver_key="modbus_smg",
                protocol_family="modbus_smg",
                model_name="SMG 6200",
                serial_number="92632500000001",
                probe_target=ProbeTarget(devcode=0x0001, collector_addr=0x01, device_addr=1),
            ),
            connection_mode="broadcast",
        )
        flow._autodetect_results = {"0": selected_result}
        flow._selected_result = selected_result
        with patch(
            "custom_components.eybond_local.flows.config.scan.create_onboarding_manager",
            return_value=object(),
        ) as create_manager:
            result = await flow.async_step_confirm()

        self.assertEqual(result["type"], "form")
        placeholders = result["description_placeholders"]
        self.assertNotIn("Collector Signal Strength", placeholders["collector_confirm_table"])
        self.assertIn("will detect the connected inverter", placeholders["inverter_confirm_table"])
        self.assertNotIn("Rated Power", placeholders["inverter_confirm_table"])
        create_manager.assert_not_called()

    async def test_confirm_step_skips_smartess_cloud_assist_for_low_confidence_result(self) -> None:
        flow = self._make_flow()
        flow._selected_result = OnboardingResult(
            collector=CollectorCandidate(
                target_ip="192.168.1.55",
                source="udp",
                ip="192.168.1.55",
                connected=True,
                collector=CollectorInfo(collector_pn="E5000020000000"),
            ),
            match=DriverMatch(
                driver_key="pi30",
                protocol_family="pi30",
                model_name="PowMr 4.2kW",
                serial_number="553555355535552",
                probe_target=ProbeTarget(devcode=0x0994, collector_addr=0x01, device_addr=0),
                confidence="medium",
            ),
            connection_mode="known_ip",
        )

        result = await flow.async_step_confirm()

        self.assertEqual(result["type"], "form")
        self.assertEqual(result["step_id"], "confirm")

    async def test_confirm_step_skips_smartess_cloud_assist_for_collector_only_result(self) -> None:
        flow = self._make_flow()
        flow._selected_result = OnboardingResult(
            collector=CollectorCandidate(
                target_ip="192.168.1.55",
                source="udp",
                ip="192.168.1.55",
                connected=True,
                collector=CollectorInfo(collector_pn="E5000020000000"),
            ),
            connection_mode="known_ip",
        )

        result = await flow.async_step_confirm()

        self.assertEqual(result["type"], "form")
        self.assertEqual(result["step_id"], "confirm")

    async def test_choose_step_selects_specific_result(self) -> None:
        flow = self._make_flow()
        flow._autodetect_results = {
            "0": OnboardingResult(
                collector=CollectorCandidate(target_ip="192.168.1.14", source="udp", ip="192.168.1.14", connected=True),
                match=DriverMatch(
                    driver_key="pi30",
                    protocol_family="pi30",
                    model_name="PowMr 4.2kW",
                    serial_number="553555355535552",
                    probe_target=ProbeTarget(devcode=0x0994, collector_addr=0x01, device_addr=0),
                ),
                connection_mode="known_ip",
            ),
            "1": OnboardingResult(
                collector=CollectorCandidate(target_ip="192.168.1.55", source="udp", ip="192.168.1.55", connected=True),
                match=DriverMatch(
                    driver_key="modbus_smg",
                    protocol_family="modbus_smg",
                    model_name="SMG 6200",
                    serial_number="92632500000001",
                    probe_target=ProbeTarget(devcode=0x0001, collector_addr=0x01, device_addr=1),
                ),
                connection_mode="known_ip",
            ),
        }

        result = await flow.async_step_choose({CONF_RESULT_KEY: "1"})

        self.assertEqual(result["type"], "form")
        self.assertEqual(result["step_id"], "confirm")
        self.assertIsNotNone(flow._selected_result)
        self.assertEqual(flow._selected_result.match.model_name, "SMG 6200")

    async def test_choose_step_udp_only_route_enters_callback_identification(self) -> None:
        flow = self._make_flow()
        flow._auto_config = {
            "server_ip": "192.168.1.104",
            "collector_ip": "",
            "driver_hint": "auto",
            "tcp_port": 8899,
            "udp_port": 58899,
            "discovery_target": "192.168.1.255",
            "discovery_interval": 3,
            "heartbeat_interval": 60,
        }
        flow._autodetect_results = {
            "0": OnboardingResult(
                collector=CollectorCandidate(
                    target_ip="192.168.1.14",
                    source="subnet_unicast",
                    ip="192.168.1.14",
                    udp_reply="rsp>server=1;",
                    connected=False,
                ),
                connection_mode="subnet_unicast",
                next_action="manual_input",
                last_error="collector_not_connected",
            )
        }

        result = await flow.async_step_choose({CONF_RESULT_KEY: "0"})

        # A UDP response is a route observation, not a collector identity. Its
        # selection opens the existing callback identity path with the address
        # prefilled; it never reaches entry creation directly.
        self.assertEqual(result["type"], "form")
        self.assertEqual(result["step_id"], "manual")
        self.assertIs(flow._selected_result, flow._autodetect_results["0"])
        self.assertEqual(
            flow._manual_preselected_strategy,
            CONNECTION_STRATEGY_CALLBACK_ON_DEMAND,
        )
        self.assertEqual(flow._manual_defaults["collector_ip"], "192.168.1.14")

    async def test_create_entry_persists_collector_cloud_family_from_onboarding(self) -> None:
        flow = self._make_flow()
        flow._auto_config = {
            "server_ip": "192.168.1.104",
            "collector_ip": "",
            "driver_hint": "auto",
            "tcp_port": 8899,
            "udp_port": 58899,
            "discovery_target": "192.168.1.255",
            "discovery_interval": 3,
            "heartbeat_interval": 60,
        }
        flow._selected_result = OnboardingResult(
            collector=CollectorCandidate(
                target_ip="192.168.1.14",
                source="broadcast",
                ip="192.168.1.14",
                connected=True,
                collector=CollectorInfo(
                    collector_pn="E5000099990001",
                    collector_cloud_family="valuecloud_at",
                    collector_cloud_family_source="endpoint_host",
                    collector_cloud_family_confidence="high",
                    collector_server_endpoint="iot.eybond.com,18899,TCP",
                ),
            ),
            match=DriverMatch(
                driver_key="modbus_smg",
                protocol_family="modbus_smg",
                model_name="SMG 6200",
                serial_number="92632500000001",
                probe_target=ProbeTarget(devcode=0x0001, collector_addr=0x01, device_addr=1),
                details={},
            ),
            connection_mode="known_ip",
        )

        result = await flow._async_create_entry_from_result({"poll_interval": 30})

        self.assertEqual(result["type"], "create_entry")
        self.assertEqual(result["data"][CONF_COLLECTOR_CLOUD_FAMILY], "valuecloud_at")

    async def test_choose_step_link_down_result_shows_retryable_error(self) -> None:
        flow = self._make_flow()
        flow._autodetect_results = {
            "0": OnboardingResult(
                collector=CollectorCandidate(
                    target_ip="192.168.1.55",
                    source="udp",
                    ip="192.168.1.55",
                    connected=True,
                ),
                connection_mode="known_ip",
                next_action="manual_driver_selection",
                last_error="inverter_link_down",
            )
        }

        result = await flow.async_step_choose({CONF_RESULT_KEY: "0"})

        self.assertEqual(result["type"], "form")
        self.assertEqual(result["step_id"], "choose")
        self.assertEqual(result["errors"], {"base": "inverter_link_down"})
        self.assertIsNone(flow._selected_result)

    async def test_choose_step_single_link_down_result_does_not_auto_advance(self) -> None:
        flow = self._make_flow()
        flow._autodetect_results = {
            "0": OnboardingResult(
                collector=CollectorCandidate(
                    target_ip="192.168.1.55",
                    source="udp",
                    ip="192.168.1.55",
                    connected=True,
                ),
                connection_mode="known_ip",
                last_error="inverter_link_down",
            )
        }

        result = await flow.async_step_choose()

        self.assertEqual(result["type"], "form")
        self.assertEqual(result["step_id"], "choose")
        self.assertEqual(result["errors"], {"base": "inverter_link_down"})

    def _result_with_catalog_details(self, catalog: dict | None) -> OnboardingResult:
        details = {}
        if catalog is not None:
            details["device_catalog"] = catalog
        return OnboardingResult(
            collector=CollectorCandidate(
                target_ip="192.168.1.55", source="udp", ip="192.168.1.55", connected=True
            ),
            match=DriverMatch(
                driver_key="modbus_smg",
                protocol_family="modbus_smg",
                model_name="SMG 6200",
                serial_number="92632500000001",
                probe_target=ProbeTarget(devcode=0x0001, collector_addr=0x01, device_addr=1),
                details=details,
            ),
            connection_mode="known_ip",
        )

    async def test_detection_summary_full_tier_placeholders(self) -> None:
        flow = self._make_flow()
        flow._selected_result = self._result_with_catalog_details(
            {"kind": "device", "tier": "full", "entry_key": "smg_6200"}
        )

        result = await flow.async_step_detection_summary()

        self.assertEqual(result["step_id"], "detection_summary")
        placeholders = result["description_placeholders"]
        self.assertEqual(placeholders["model"], "SMG 6200")
        self.assertIn("Full support", placeholders["tier_headline"])

    async def test_detection_summary_offers_cloud_assist_only_as_optional_menu(self) -> None:
        flow = self._make_flow()
        flow._selected_result = self._result_with_catalog_details(
            {"kind": "family", "tier": "partial"}
        )
        flow._detection_summary_context = "auto"

        # Default: cloud assist is not offered -> plain info form, no auto-pop.
        plain = await flow.async_step_detection_summary()
        self.assertEqual(plain["type"], "form")

        # When it can be offered, it appears as an explicit choice, not before confirm.
        flow._can_offer_smartess_cloud_assist = lambda _result: True
        menu = await flow.async_step_detection_summary()
        self.assertEqual(menu["type"], "menu")
        self.assertEqual(menu["menu_options"], ["confirm", "smartess_cloud_assist"])

    async def test_confirm_does_not_auto_pop_cloud_assist(self) -> None:
        flow = self._make_flow()
        flow._selected_result = self._result_with_catalog_details(
            {"kind": "device", "tier": "full"}
        )
        flow._can_offer_smartess_cloud_assist = lambda _result: True

        result = await flow.async_step_confirm()

        # confirm shows its own form directly; cloud assist never interrupts it.
        self.assertEqual(result["type"], "form")
        self.assertEqual(result["step_id"], "confirm")

    async def test_detection_summary_partial_tier_mentions_learning(self) -> None:
        flow = self._make_flow()
        flow._selected_result = self._result_with_catalog_details(
            {"kind": "family", "tier": "partial"}
        )

        result = await flow.async_step_detection_summary()

        placeholders = result["description_placeholders"]
        self.assertIn("Partial support", placeholders["tier_headline"])
        self.assertIn("learning", placeholders["tier_details"])

    async def test_detection_summary_collector_only_does_not_suggest_learning(self) -> None:
        flow = self._make_flow()
        flow._selected_result = OnboardingResult(
            collector=CollectorCandidate(
                target_ip="192.168.1.51",
                source="udp",
                ip="192.168.1.51",
                connected=True,
                collector=CollectorInfo(collector_pn="ESP32COLLECTOR"),
            ),
            connection_mode="known_ip",
            next_action="create_entry",
        )

        result = await flow.async_step_detection_summary()

        placeholders = result["description_placeholders"]
        self.assertIn("Device not recognized", placeholders["tier_headline"])
        self.assertIn("no inverter was detected", placeholders["tier_details"])
        self.assertIn("Support Archive", placeholders["tier_details"])
        self.assertNotIn("Add controls", placeholders["tier_details"])
        self.assertNotIn("device learning", placeholders["tier_details"])

    async def test_detection_summary_passive_callback_defers_inverter_detection(self) -> None:
        flow = self._make_flow()
        flow._selected_result = OnboardingResult(
            collector=CollectorCandidate(
                target_ip="0.0.0.0",
                source="callback_listener",
                ip="195.138.86.175",
                connected=True,
                collector=CollectorInfo(collector_pn="V001020SYN62344022"),
            ),
            connection_mode="callback_listener",
            next_action="manual_driver_selection",
        )

        result = await flow.async_step_detection_summary()

        placeholders = result["description_placeholders"]
        self.assertIn("Collector connected", placeholders["tier_headline"])
        self.assertIn("runtime owns this session", placeholders["tier_details"])
        self.assertNotIn("no inverter was detected", placeholders["tier_details"])
        self.assertNotIn("Device not recognized", placeholders["tier_headline"])

    async def test_detection_summary_passive_callback_uses_localized_text(self) -> None:
        flow = self._make_flow()
        flow.hass.config.language = "uk"
        flow._selected_result = OnboardingResult(
            collector=CollectorCandidate(
                target_ip="0.0.0.0",
                source="callback_listener",
                ip="192.168.1.1",
                connected=True,
                collector=CollectorInfo(collector_pn="V001107SYN8229"),
            ),
            connection_mode="callback_listener",
            next_action="manual_driver_selection",
        )

        result = await flow.async_step_detection_summary()

        placeholders = result["description_placeholders"]
        self.assertIn("Колектор підключений", placeholders["tier_headline"])
        self.assertIn("вхідним підключенням", placeholders["tier_details"])
        self.assertNotIn("Collector connected", placeholders["tier_headline"])

    async def test_detection_summary_without_catalog_details_uses_driver_text(self) -> None:
        flow = self._make_flow()
        flow._selected_result = self._result_with_catalog_details(None)

        result = await flow.async_step_detection_summary()

        placeholders = result["description_placeholders"]
        self.assertIn("driver", placeholders["tier_headline"].lower())

    async def test_detection_summary_submit_continues_to_confirm(self) -> None:
        flow = self._make_flow()
        flow._selected_result = self._result_with_catalog_details(
            {"kind": "device", "tier": "full"}
        )

        result = await flow.async_step_detection_summary({})

        self.assertEqual(result["step_id"], "confirm")

    async def test_confirm_step_persists_poll_interval_in_entry_options(self) -> None:
        flow = self._make_flow()
        flow._selected_result = OnboardingResult(
            collector=CollectorCandidate(
                target_ip="192.168.1.55",
                source="udp",
                ip="192.168.1.55",
                connected=True,
                collector=CollectorInfo(
                    collector_pn="PN123",
                    smartess_collector_version="1.2.3",
                    smartess_protocol_asset_id="0925",
                    smartess_protocol_profile_key="smartess_0925",
                    smartess_device_address=5,
                ),
            ),
            match=DriverMatch(
                driver_key="modbus_smg",
                protocol_family="modbus_smg",
                model_name="SMG 6200",
                serial_number="92632500000001",
                probe_target=ProbeTarget(devcode=0x0001, collector_addr=0x01, device_addr=1),
                details={
                    "smartess_collector_version": "1.2.3",
                    "smartess_protocol_asset_id": "0925",
                    "smartess_profile_key": "smartess_0925",
                    "smartess_device_address": 5,
                },
            ),
            connection_mode="known_ip",
        )

        interval_form = await flow.async_step_confirm(
            {
                "poll_mode": "manual",
                CONF_DRIVER_DETECTION_STRATEGY: DRIVER_DETECTION_FULL_SCAN,
            }
        )
        self.assertEqual(interval_form["step_id"], "confirm_poll_interval")
        result = await flow.async_step_confirm_poll_interval({"poll_interval": 15})

        self.assertEqual(result["type"], "create_entry")
        self.assertEqual(result["options"]["poll_interval"], 15)
        self.assertEqual(
            result["data"][CONF_DRIVER_DETECTION_STRATEGY],
            DRIVER_DETECTION_FULL_SCAN,
        )
        self.assertEqual(result["data"][CONF_SMARTESS_COLLECTOR_VERSION], "1.2.3")
        self.assertEqual(result["data"][CONF_SMARTESS_PROTOCOL_ASSET_ID], "0925")
        self.assertEqual(result["data"][CONF_SMARTESS_PROFILE_KEY], "smartess_0925")
        self.assertEqual(result["data"][CONF_SMARTESS_DEVICE_ADDRESS], 5)

    async def test_confirm_step_ignores_stale_pre_entry_endpoint_state(self) -> None:
        flow = self._make_flow()
        # Old flow-local state must not mint endpoint provenance. Runtime learns
        # the real endpoint after the exact session handoff.
        flow._collector_endpoint_bind_applied = True
        flow._collector_original_server_endpoint = "collector-cloud.smartess.example,18899,TCP"
        flow._collector_target_server_endpoint = "192.168.1.50,18899,TCP"
        flow._selected_result = OnboardingResult(
            collector=CollectorCandidate(
                target_ip="192.168.1.55",
                source="udp",
                ip="192.168.1.55",
                connected=True,
                collector=CollectorInfo(collector_pn="PN123"),
            ),
            match=DriverMatch(
                driver_key="modbus_smg",
                protocol_family="modbus_smg",
                model_name="SMG 6200",
                serial_number="92632500000001",
                probe_target=ProbeTarget(devcode=0x0001, collector_addr=0x01, device_addr=1),
            ),
            connection_mode="known_ip",
        )

        result = await flow.async_step_confirm(
            {
                "poll_interval": 15,
            }
        )

        self.assertEqual(result["type"], "create_entry")
        self.assertNotIn(CONF_COLLECTOR_ORIGINAL_SERVER_ENDPOINT, result["options"])
        self.assertNotIn(
            CONF_COLLECTOR_ORIGINAL_SERVER_ENDPOINT_PROFILE_KEY,
            result["options"],
        )
        self.assertNotIn(
            CONF_COLLECTOR_ORIGINAL_SERVER_ENDPOINT_SOURCE,
            result["options"],
        )
        self.assertNotIn(
            CONF_COLLECTOR_ORIGINAL_SERVER_ENDPOINT_OBSERVED_AT,
            result["options"],
        )

    def _bridge_confirm_result(self, *, is_bridge: bool) -> OnboardingResult:
        details = {"collector_virtual_bridge": True} if is_bridge else {}
        return OnboardingResult(
            collector=CollectorCandidate(
                target_ip="192.168.1.55",
                source="udp",
                ip="192.168.1.55",
                connected=True,
                collector=CollectorInfo(collector_pn="PN123"),
            ),
            match=DriverMatch(
                driver_key="modbus_smg",
                protocol_family="modbus_smg",
                model_name="SMG 6200",
                serial_number="92632500000001",
                probe_target=ProbeTarget(devcode=0x0001, collector_addr=0x01, device_addr=1),
                details=details,
            ),
            connection_mode="known_ip",
        )

    def _bridge_confirm_result_from_collector_info(self) -> OnboardingResult:
        result = self._bridge_confirm_result(is_bridge=False)
        result.collector.collector.collector_virtual_bridge = True
        result.collector.collector.collector_bridge_kind = "esp-collector"
        return result

    def _bridge_confirm_result_from_hardware_token(self) -> OnboardingResult:
        result = self._bridge_confirm_result(is_bridge=False)
        result.match.details["collector_hardware_version"] = "esp-collector/0.1.2/ESP32"
        result.match.details["collector_virtual_bridge"] = True
        result.match.details["collector_bridge_kind"] = "esp-collector"
        result.match.details["collector_bridge_version"] = "0.1.2"
        return result

    def _collector_only_bridge_result(self) -> OnboardingResult:
        return OnboardingResult(
            collector=CollectorCandidate(
                target_ip="192.168.1.51",
                source="udp",
                ip="192.168.1.51",
                connected=True,
                collector=CollectorInfo(
                    collector_pn="ESP32COLLECTOR",
                    collector_virtual_bridge=True,
                    collector_bridge_kind="esp-collector",
                    collector_bridge_version="dev",
                ),
            ),
            connection_mode="known_ip",
            next_action="create_entry",
        )

    async def test_confirm_step_hides_operation_mode_selector_for_detected_bridge(self) -> None:
        # Item 1: a detected bridge forces HA-only and hides the cloud+HA /
        # HA-only choice, showing an informational note instead.
        flow = self._make_flow()
        flow._selected_result = self._bridge_confirm_result(is_bridge=True)

        result = await flow.async_step_confirm()

        self.assertEqual(result["type"], "form")
        self.assertEqual(result["step_id"], "confirm")
        self.assertIn("poll_mode", result["data_schema"].schema)
        self.assertNotIn("poll_interval", result["data_schema"].schema)
        self.assertNotIn(CONF_COLLECTOR_OPERATION_MODE, result["data_schema"].schema)
        self.assertTrue(
            result["description_placeholders"]["collector_connection_note"].strip()
        )

    async def test_confirm_step_hides_operation_mode_selector_for_bridge_collector_info(self) -> None:
        flow = self._make_flow()
        flow._selected_result = self._bridge_confirm_result_from_collector_info()

        result = await flow.async_step_confirm()

        self.assertEqual(result["type"], "form")
        self.assertNotIn(CONF_COLLECTOR_OPERATION_MODE, result["data_schema"].schema)

    async def test_confirm_step_hides_operation_mode_selector_for_hardware_token_bridge(self) -> None:
        flow = self._make_flow()
        flow._selected_result = self._bridge_confirm_result_from_hardware_token()

        result = await flow.async_step_confirm()

        self.assertEqual(result["type"], "form")
        self.assertNotIn(CONF_COLLECTOR_OPERATION_MODE, result["data_schema"].schema)

    async def test_confirm_step_hides_operation_mode_selector_for_collector_only_bridge(self) -> None:
        flow = self._make_flow()
        flow._selected_result = self._collector_only_bridge_result()

        result = await flow.async_step_confirm()

        self.assertEqual(result["type"], "form")
        self.assertEqual(result["step_id"], "confirm")
        self.assertNotIn(CONF_COLLECTOR_OPERATION_MODE, result["data_schema"].schema)
        self.assertTrue(
            result["description_placeholders"]["collector_connection_note"].strip()
        )

    async def test_confirm_step_does_not_infer_strategy_from_collector_kind(self) -> None:
        flow = self._make_flow()
        flow._selected_result = self._collector_only_bridge_result()

        result = await flow.async_step_confirm({"poll_mode": "auto"})

        self.assertEqual(result["type"], "create_entry")
        self.assertEqual(result["data"]["connection_mode"], "known_ip")
        self.assertNotIn(CONF_COLLECTOR_OPERATION_MODE, result["data"])
        self.assertNotIn(CONF_COLLECTOR_OPERATION_MODE, result["options"])
        self.assertEqual(
            result["data"][CONF_CONNECTION_STRATEGY],
            CONNECTION_STRATEGY_CALLBACK_ON_DEMAND,
        )
        self.assertTrue(result["data"]["collector_virtual_bridge"])

    async def test_confirm_step_does_not_persist_original_endpoint_for_bridge(self) -> None:
        flow = self._make_flow()
        flow._selected_result = self._collector_only_bridge_result()

        with tempfile.TemporaryDirectory() as tempdir:
            flow.hass.config.config_dir = tempdir

            result = await flow.async_step_confirm({"poll_mode": "auto"})

            self.assertEqual(result["type"], "create_entry")
            self.assertNotIn(
                CONF_COLLECTOR_ORIGINAL_SERVER_ENDPOINT,
                result["options"],
            )
            self.assertFalse(
                (Path(tempdir) / ".storage" / "eybond_local.collectors").exists()
            )

    async def test_confirm_step_does_not_rewrite_endpoint_for_passive_callback_bridge(self) -> None:
        flow = self._make_flow()
        selected = self._collector_only_bridge_result()
        selected.collector.source = "callback_listener"
        selected = replace(selected, connection_mode="callback_listener")
        flow._selected_result = selected

        result = await flow.async_step_confirm({"poll_mode": "auto"})

        self.assertEqual(result["type"], "create_entry")
        self.assertNotIn(CONF_COLLECTOR_OPERATION_MODE, result["data"])
        self.assertNotIn(CONF_COLLECTOR_OPERATION_MODE, result["options"])
        self.assertEqual(
            result["data"][CONF_CONNECTION_STRATEGY], CONNECTION_STRATEGY_INBOUND
        )

    async def test_confirm_step_hides_operation_mode_selector_for_factory_collector(self) -> None:
        flow = self._make_flow()
        flow._selected_result = self._bridge_confirm_result(is_bridge=False)

        result = await flow.async_step_confirm()

        self.assertEqual(result["type"], "form")
        self.assertNotIn(CONF_COLLECTOR_OPERATION_MODE, result["data_schema"].schema)
        self.assertEqual(
            result["description_placeholders"]["collector_connection_note"], ""
        )

    async def test_confirm_step_bridge_never_runs_pre_entry_endpoint_bind(self) -> None:
        flow = self._make_flow()
        flow._selected_result = self._bridge_confirm_result(is_bridge=True)

        result = await flow.async_step_confirm(
            {
                CONF_COLLECTOR_OPERATION_MODE: COLLECTOR_OPERATION_HA_ONLY,
                "poll_interval": 15,
            }
        )

        self.assertEqual(result["type"], "create_entry")
        self.assertNotIn(CONF_COLLECTOR_OPERATION_MODE, result["data"])
        self.assertNotIn(CONF_COLLECTOR_OPERATION_MODE, result["options"])
        self.assertEqual(
            result["data"][CONF_CONNECTION_STRATEGY],
            CONNECTION_STRATEGY_CALLBACK_ON_DEMAND,
        )

    async def test_confirm_step_ignores_stale_operation_mode_for_factory_collector(self) -> None:
        flow = self._make_flow()
        flow._selected_result = self._bridge_confirm_result(is_bridge=False)

        result = await flow.async_step_confirm(
            {
                CONF_COLLECTOR_OPERATION_MODE: COLLECTOR_OPERATION_HA_ONLY,
                "poll_interval": 15,
            }
        )

        self.assertEqual(result["type"], "create_entry")
        self.assertNotIn(CONF_COLLECTOR_OPERATION_MODE, result["data"])
        self.assertNotIn(CONF_COLLECTOR_OPERATION_MODE, result["options"])
        self.assertEqual(
            result["data"][CONF_CONNECTION_STRATEGY],
            CONNECTION_STRATEGY_CALLBACK_ON_DEMAND,
        )

    async def test_first_add_has_no_flow_local_endpoint_management_api(self) -> None:
        flow = self._make_flow()
        for name in (
            "_async_with_selected_collector_session",
            "_async_read_selected_collector_server_endpoint",
            "_async_bind_selected_collector_to_home_assistant",
            "_collector_original_endpoint_options",
            "_collector_callback_target_endpoint",
        ):
            self.assertFalse(hasattr(flow, name), name)

    async def test_do_scan_keeps_matching_entries_loaded(self) -> None:
        matching = _FakeEntry("match", server_ip="192.168.1.50", tcp_port=8899)
        other = _FakeEntry("other", server_ip="192.168.1.60", tcp_port=8899)
        flow = self._make_flow(entries=[matching, other])

        class _FakeDetector:
            def __init__(self, **kwargs) -> None:
                self.kwargs = kwargs

            async def async_scan(self, **kwargs):
                return (OnboardingResult(),)

        with patch("custom_components.eybond_local.flows.config.scan.create_onboarding_manager", return_value=_FakeDetector()):
            await flow._async_do_scan()

        self.assertEqual(flow.hass.config_entries.unloaded, [])
        self.assertEqual(flow.hass.config_entries.reloaded, [])

    async def test_do_scan_builds_connection_spec_through_generic_builder(self) -> None:
        flow = self._make_flow()

        class _FakeDetector:
            async def async_scan(self, **kwargs):
                return ()

        with patch(
            "custom_components.eybond_local.flows.config.scan.build_connection_spec_from_values",
            return_value=sentinel.connection_spec,
        ) as build_spec, patch(
            "custom_components.eybond_local.flows.config.scan.create_onboarding_manager",
            return_value=_FakeDetector(),
        ) as create_manager:
            await flow._async_do_scan()

        build_spec.assert_called_once()
        create_manager.assert_called_once_with(sentinel.connection_spec)

    async def test_do_scan_uses_one_collector_inventory_contract(self) -> None:
        flow = self._make_flow()
        captured_kwargs: dict[str, object] = {}

        class _FakeDetector:
            async def async_scan(self, **kwargs):
                captured_kwargs.update(kwargs)
                return ()

        with patch(
            "custom_components.eybond_local.flows.config.scan.create_onboarding_manager",
            return_value=_FakeDetector(),
        ):
            await flow._async_do_scan()

        self.assertNotIn("attempts", captured_kwargs)
        self.assertNotIn("enrich_runtime_details", captured_kwargs)
        self.assertNotIn("identify_collector_only", captured_kwargs)
        self.assertNotIn("return_after_first_identity", captured_kwargs)
        self.assertEqual(
            captured_kwargs["total_timeout"],
            max(5.0, flow._scan_timeout_seconds - 5.0),
        )

    async def test_do_scan_scopes_active_probe_against_passive_discovery(self) -> None:
        flow = self._make_flow()
        events: list[str] = []

        class _FakePassiveDiscovery:
            def begin_active_probe_scope(self, scope_id: str) -> None:
                self.scope_id = scope_id
                events.append("begin")

            def end_active_probe_scope(self, scope_id: str) -> None:
                self.end_scope_id = scope_id
                events.append("end")

        class _FakeDetector:
            async def async_scan(self, **kwargs):
                events.append("detect")
                return ()

        passive = _FakePassiveDiscovery()
        with patch(
            "custom_components.eybond_local.flows.config.scan.create_onboarding_manager",
            return_value=_FakeDetector(),
        ), patch(
            "custom_components.eybond_local.passive_discovery.get_passive_callback_discovery",
            return_value=passive,
        ):
            await flow._async_do_scan()

        self.assertEqual(events, ["begin", "detect", "end"])
        self.assertEqual(passive.scope_id, passive.end_scope_id)

    async def test_do_scan_keeps_active_probe_when_addable_passive_callback_exists(self) -> None:
        flow = self._make_flow()
        passive_result = OnboardingResult(
            collector=CollectorCandidate(
                target_ip="192.168.1.50",
                source="callback_listener",
                ip="195.138.86.175",
                connected=True,
                collector=CollectorInfo(collector_pn="V000405SYN94677058"),
            ),
            connection_mode="callback_listener",
            next_action="manual_driver_selection",
        )

        class _FakeDetector:
            def __init__(self) -> None:
                self.auto_called = False

            async def async_passive_detect(self, **kwargs):
                return (passive_result,)

            async def async_scan(self, **kwargs):
                self.auto_called = True
                return ()

        detector = _FakeDetector()
        with patch(
            "custom_components.eybond_local.flows.config.scan.create_onboarding_manager",
            return_value=detector,
        ):
            await flow._async_do_scan()

        self.assertTrue(detector.auto_called)
        self.assertEqual(len(flow._autodetect_results), 1)
        result = next(iter(flow._autodetect_results.values()))
        self.assertEqual(result.connection_mode, "callback_listener")
        self.assertEqual(result.collector.collector.collector_pn, "V000405SYN94677058")

    async def test_do_scan_includes_strong_session_arriving_during_active_scan(self) -> None:
        from custom_components.eybond_local.passive_discovery import (
            PassiveCallbackDiscovery,
        )

        flow = self._make_flow()
        discovery = PassiveCallbackDiscovery(flow.hass)
        sessions: list[dict[str, object]] = []

        class _Listener:
            def discovered_collector_sessions(self):
                return tuple(sessions)

        discovery._listeners[18899] = _Listener()
        flow.hass.data[DOMAIN] = {"passive_callback_discovery": discovery}

        class _FakeDetector:
            async def async_scan(self, **_kwargs):
                sessions.append(
                    _wire_session(
                        "listener-18899-during-scan",
                        "V001020SYN62344022",
                        peer_ip="198.51.100.17",
                    )
                )
                return ()

        with patch(
            "custom_components.eybond_local.flows.config.scan.create_onboarding_manager",
            return_value=_FakeDetector(),
        ):
            await flow._async_do_scan()

        self.assertEqual(len(flow._autodetect_results), 1)
        result = next(iter(flow._autodetect_results.values()))
        self.assertEqual(
            result.observed_session.session_id,
            "listener-18899-during-scan",
        )
        self.assertEqual(
            result.collector.collector.collector_pn,
            "V001020SYN62344022",
        )

    async def test_scan_results_adds_session_arriving_before_first_render(self) -> None:
        from custom_components.eybond_local.passive_discovery import (
            PassiveCallbackDiscovery,
        )

        flow = self._make_flow()
        discovery = PassiveCallbackDiscovery(flow.hass)
        sessions: list[dict[str, object]] = []

        class _Listener:
            def discovered_collector_sessions(self):
                return tuple(sessions)

        discovery._listeners[18899] = _Listener()
        flow.hass.data[DOMAIN] = {"passive_callback_discovery": discovery}
        sessions.append(
            _wire_session(
                "listener-18899-after-scan",
                "V000405SYN94677058",
                peer_ip="203.0.113.25",
            )
        )

        rendered = await flow.async_step_scan_results()

        options = _schema_select_options(rendered["data_schema"], CONF_RESULT_KEY)
        self.assertIn("0", options)
        self.assertEqual(
            flow._autodetect_results["0"].observed_session.session_id,
            "listener-18899-after-scan",
        )

    def test_active_typed_route_wins_same_pn_inventory_projection(self) -> None:
        pn = "E50000200000000001"
        observed = ObservedCollectorSession(
            collector_pn=pn,
            identity_source="fc2_parameter_2",
            session_id="listener-8899-exact",
            listener_port=8899,
            protocol_shape="eybond_framed",
            peer_hint="192.168.1.1",
        )
        route = CallbackRecoveryRoute(
            bind_ip="192.168.1.50",
            trigger_target_ip="192.168.1.55",
            trigger_udp_port=58899,
            advertised_ha_host="192.168.1.50",
            advertised_ha_port=8899,
            listener_port=8899,
        )
        inventory = OnboardingResult(
            collector=CollectorCandidate(
                target_ip="192.168.1.50",
                source="callback_listener",
                ip="192.168.1.1",
                connected=True,
                collector=CollectorInfo(collector_pn=pn),
            ),
            connection_mode="callback_listener",
            observed_session=observed,
        )
        active = replace(
            inventory,
            collector=replace(
                inventory.collector,
                target_ip="192.168.1.55",
                source="subnet_unicast",
            ),
            callback_route=route,
        )

        (collapsed,) = self._make_flow()._collapse_scan_results(
            [inventory, active]
        )

        self.assertIs(collapsed.callback_route, route)
        self.assertEqual(collapsed.collector.target_ip, "192.168.1.55")

    async def test_do_scan_does_not_bypass_removed_entry_session_quarantine(self) -> None:
        from custom_components.eybond_local.passive_discovery import (
            PassiveCallbackDiscovery,
        )

        flow = self._make_flow()
        discovery = PassiveCallbackDiscovery(flow.hass)
        session = {
            "session_id": "listener-18899-retired-v0011",
            "peer_ip": "203.0.113.17",
            "collector_pn": "V001107SYN282291016",
            "state": "routed_framed",
            "protocol_shape": "eybond_framed",
            "collector_identity_source": "fc2_parameter_2",
        }

        class _Listener:
            def discovered_collector_sessions(self):
                return (session,)

        discovery._listeners[18899] = _Listener()
        flow.hass.data[DOMAIN] = {"passive_callback_discovery": discovery}
        discovery.registry.claim(
            "removed-v0011",
            collector_pn="V001107SYN282291016",
        )
        discovery.retire_entry_sessions("removed-v0011")
        discovery.registry.release("removed-v0011")

        active_result = OnboardingResult(
            collector=CollectorCandidate(
                target_ip="192.168.1.255",
                source="broadcast",
                ip="192.168.1.55",
                connected=True,
                collector=CollectorInfo(collector_pn="E50000200000009777"),
            ),
            connection_mode="broadcast",
            next_action="manual_driver_selection",
        )

        class _FakeDetector:
            async def async_passive_detect(self, **_kwargs):
                # The scan's selected listener is 8899; this session lives on a
                # different domain listener and is visible only through the
                # shared candidate source.
                return ()

            async def async_scan(self, **_kwargs):
                return (active_result,)

        with patch(
            "custom_components.eybond_local.flows.config.scan.create_onboarding_manager",
            return_value=_FakeDetector(),
        ):
            await flow._async_do_scan()

        # An exact socket retired by an unload is quarantined until either a
        # successful reload resumes the entry or permanent removal restarts it.
        # Interactive search must not reinterpret that stale callback socket as
        # a new durable inbound collector.
        self.assertEqual(len(flow._autodetect_results), 1)
        self.assertTrue(
            all(
                candidate.observed_session is None
                for candidate in flow._autodetect_results.values()
            )
        )

    async def test_do_scan_with_passive_seed_runs_progress_updater(self) -> None:
        flow = self._make_flow()
        passive_result = OnboardingResult(
            collector=CollectorCandidate(
                target_ip="192.168.1.50",
                source="callback_listener",
                ip="195.138.86.175",
                connected=True,
                collector=CollectorInfo(collector_pn="V000405SYN94677058"),
            ),
            connection_mode="callback_listener",
            next_action="manual_driver_selection",
        )

        class _FakeDetector:
            async def async_passive_detect(self, **kwargs):
                return (passive_result,)

            async def async_scan(self, **kwargs):
                return ()

        progress_loop = AsyncMock(return_value=None)

        with patch(
            "custom_components.eybond_local.flows.config.scan.create_onboarding_manager",
            return_value=_FakeDetector(),
        ), patch.object(
            flow,
            "_async_update_scan_progress_loop",
            new=progress_loop,
        ):
            await flow._async_do_scan()

        progress_loop.assert_called_once_with()
        self.assertEqual(len(flow._autodetect_results), 1)
        self.assertEqual(flow._scan_progress_stage, "finalizing")

    async def test_do_scan_merges_passive_callback_with_active_results_when_passive_is_existing(self) -> None:
        existing = _FakeEntry("existing", server_ip="192.168.1.50", tcp_port=8899)
        existing.data.update({"collector_pn": "V000405SYN94677058"})
        existing.unique_id = "collector:V000405SYN94677058"
        flow = self._make_flow(entries=[existing])
        passive_existing = OnboardingResult(
            collector=CollectorCandidate(
                target_ip="192.168.1.50",
                source="callback_listener",
                ip="195.138.86.175",
                connected=True,
                collector=CollectorInfo(collector_pn="V000405SYN94677058"),
            ),
            connection_mode="callback_listener",
        )
        active_new = OnboardingResult(
            collector=CollectorCandidate(
                target_ip="192.168.255.255",
                source="broadcast",
                ip="195.138.86.175",
                connected=True,
                collector=CollectorInfo(collector_pn="V000405SYN94677059"),
            ),
            connection_mode="broadcast",
            next_action="manual_driver_selection",
        )

        class _FakeDetector:
            async def async_passive_detect(self, **kwargs):
                return (passive_existing,)

            async def async_scan(self, **kwargs):
                return (active_new,)

        with patch(
            "custom_components.eybond_local.flows.config.scan.create_onboarding_manager",
            return_value=_FakeDetector(),
        ):
            await flow._async_do_scan()

        self.assertEqual(
            {
                result.collector.collector.collector_pn
                for result in flow._autodetect_results.values()
                if result.collector is not None and result.collector.collector is not None
            },
            {"V000405SYN94677058", "V000405SYN94677059"},
        )
        self.assertEqual(
            {
                result.collector.collector.collector_pn
                for result in flow._available_autodetect_results().values()
                if result.collector is not None and result.collector.collector is not None
            },
            {"V000405SYN94677059"},
        )

    async def test_integration_discovery_selects_passive_callback_candidate(self) -> None:
        flow = self._make_flow()
        with patch(
            "custom_components.eybond_local.flows.config.scan.create_onboarding_manager",
            side_effect=AssertionError(
                "integration_discovery must use the concrete discovery_info session"
            ),
        ):
            result = await flow.async_step_integration_discovery(
                {
                    "tcp_port": 18899,
                    "collector_pn": "V000405SYN94677058",
                    "peer_ip": "195.138.86.175",
                }
            )

        self.assertEqual(flow._test_unique_id, "collector:V000405SYN94677058")
        self.assertEqual(
            flow.context["title_placeholders"],
            {"name": "Collector PN V000405SYN94677058"},
        )
        assert flow._selected_result is not None
        assert flow._selected_result.collector is not None
        self.assertIsNone(flow._selected_result.match)
        self.assertEqual(flow._selected_result.connection_mode, "callback_listener")
        self.assertEqual(flow._selected_result.collector.source, "callback_listener")
        self.assertEqual(flow._selected_result.collector.ip, "195.138.86.175")
        self.assertEqual(
            flow._selected_result.collector.collector.collector_pn,
            "V000405SYN94677058",
        )
        self.assertIn(result["type"], {"form", "menu"})

    async def test_integration_discovery_does_not_runtime_enrich_passive_callback_candidate(self) -> None:
        flow = self._make_flow()
        factory_specs: list[object] = []

        def _fake_create_onboarding_manager(spec, **kwargs):
            factory_specs.append(spec)
            raise AssertionError("passive discovery preview must not create a detector")

        with patch(
            "custom_components.eybond_local.flows.config.scan.create_onboarding_manager",
            side_effect=_fake_create_onboarding_manager,
        ):
            await flow.async_step_integration_discovery(
                {
                    "tcp_port": 18899,
                    "collector_pn": "V001020SYN62344022",
                    "peer_ip": "195.138.86.175",
                    "collector_session_protocol": "at_text",
                }
            )

        self.assertEqual(factory_specs, [])
        assert flow._selected_result is not None
        self.assertIsNone(flow._selected_result.match)
        self.assertEqual(flow._selected_result.connection_mode, "callback_listener")
        assert flow._selected_result.collector is not None
        self.assertEqual(flow._selected_result.collector.source, "callback_listener")
        self.assertEqual(flow._selected_result.collector.session_protocol, "at_text")

    async def test_integration_discovery_aborts_existing_passive_collector(self) -> None:
        existing = _FakeEntry("existing", server_ip="192.168.1.50", tcp_port=18899)
        existing.data.update({"collector_pn": "V000405SYN94677058"})
        existing.unique_id = "collector:V000405SYN94677058"
        flow = self._make_flow(entries=[existing])

        class _FakeDetector:
            async def async_passive_detect(self, **kwargs):
                return ()

        with patch(
            "custom_components.eybond_local.flows.config.scan.create_onboarding_manager",
            return_value=_FakeDetector(),
        ):
            result = await flow.async_step_integration_discovery(
                {
                    "tcp_port": 18899,
                    "collector_pn": "V000405SYN94677058",
                    "peer_ip": "195.138.86.175",
                }
            )

        self.assertEqual(result, {"type": "abort", "reason": "already_configured"})

    async def test_do_scan_preserves_new_collector_only_result_alongside_existing_matched_entry(self) -> None:
        existing = _FakeEntry("existing", server_ip="192.168.1.50", tcp_port=8899)
        existing.data.update(
            {
                "collector_ip": "192.168.1.55",
                "collector_pn": "E5000020000000",
                "detected_serial": "92632500000001",
            }
        )
        existing.unique_id = "collector:E5000020000000"
        flow = self._make_flow(entries=[existing])

        matched_result = OnboardingResult(
            collector=CollectorCandidate(
                target_ip="192.168.1.255",
                source="broadcast",
                ip="192.168.1.55",
                connected=True,
                collector=CollectorInfo(collector_pn="E5000020000000"),
            ),
            match=DriverMatch(
                driver_key="modbus_smg",
                protocol_family="modbus_smg",
                model_name="SMG 6200",
                serial_number="92632500000001",
                probe_target=ProbeTarget(devcode=0x0001, collector_addr=0xFF, device_addr=1),
            ),
            connection_mode="broadcast",
        )
        collector_only_result = OnboardingResult(
            collector=CollectorCandidate(
                target_ip="192.168.1.255",
                source="broadcast",
                ip="192.168.1.193",
                connected=True,
                collector=CollectorInfo(collector_pn="E5000099990002"),
            ),
            connection_mode="broadcast",
            next_action="manual_driver_selection",
            last_error="no_supported_driver_matched",
        )

        class _FakeDetector:
            async def async_scan(self, **kwargs):
                return (matched_result, collector_only_result)

        with patch(
            "custom_components.eybond_local.flows.config.scan.create_onboarding_manager",
            return_value=_FakeDetector(),
        ):
            await flow._async_do_scan()

        self.assertEqual(
            {result.collector.ip for result in flow._autodetect_results.values() if result.collector is not None},
            {"192.168.1.55", "192.168.1.193"},
        )
        self.assertEqual(
            {result.collector.ip for result in flow._available_autodetect_results().values() if result.collector is not None},
            {"192.168.1.193"},
        )

    async def test_do_scan_collapses_prefix_and_full_collector_pn_duplicates(self) -> None:
        flow = self._make_flow()
        matched_result = OnboardingResult(
            collector=CollectorCandidate(
                target_ip="192.168.1.255",
                source="broadcast",
                ip="192.168.1.51",
                connected=True,
                collector=CollectorInfo(collector_pn="Q0000000000001"),
            ),
            match=DriverMatch(
                driver_key="modbus_smg",
                protocol_family="modbus_smg",
                model_name="SMG 6200",
                serial_number="92632500000001",
                probe_target=ProbeTarget(devcode=0x0001, collector_addr=0xFF, device_addr=1),
            ),
            connection_mode="broadcast",
        )
        collector_only_result = OnboardingResult(
            collector=CollectorCandidate(
                target_ip="192.168.1.255",
                source="broadcast",
                ip="192.168.1.51",
                connected=True,
                collector=CollectorInfo(collector_pn="Q00000000000010001"),
            ),
            connection_mode="broadcast",
            next_action="manual_driver_selection",
            last_error="collector_detected_without_driver",
        )

        class _FakeDetector:
            async def async_scan(self, **kwargs):
                return (collector_only_result, matched_result)

        with patch(
            "custom_components.eybond_local.flows.config.scan.create_onboarding_manager",
            return_value=_FakeDetector(),
        ):
            await flow._async_do_scan()

        self.assertEqual(len(flow._autodetect_results), 1)
        result = next(iter(flow._autodetect_results.values()))
        self.assertIsNotNone(result.match)
        self.assertEqual(result.match.model_name, "SMG 6200")

    async def test_existing_entry_does_not_claim_different_collector_pn_on_same_nat_ip(self) -> None:
        existing = _FakeEntry("existing", server_ip="192.168.1.50", tcp_port=8899)
        existing.data.update(
            {
                "collector_ip": "192.168.1.193",
                "collector_pn": "E5000099990001",
            }
        )
        existing.unique_id = "collector:E5000099990001"
        flow = self._make_flow(entries=[existing])
        result = OnboardingResult(
            collector=CollectorCandidate(
                target_ip="192.168.1.255",
                source="broadcast",
                ip="192.168.1.193",
                connected=True,
                collector=CollectorInfo(collector_pn="E5000099990002"),
            ),
            connection_mode="broadcast",
        )

        self.assertIsNone(flow._existing_entry_for_result(result))

    async def test_existing_entry_does_not_claim_foreign_pn_with_shared_placeholder_serial(
        self,
    ) -> None:
        existing = _FakeEntry("existing", server_ip="192.168.1.50", tcp_port=8899)
        existing.data.update(
            {
                "collector_ip": "192.168.1.51",
                "collector_pn": "Q00000000000010001",
                "detected_serial": "55355535553555",
            }
        )
        existing.unique_id = "collector:Q00000000000010001"
        flow = self._make_flow(entries=[existing])
        result = OnboardingResult(
            collector=CollectorCandidate(
                target_ip="192.168.1.52",
                source="broadcast",
                ip="192.168.1.52",
                connected=True,
                collector=CollectorInfo(collector_pn="E50000200000000001"),
            ),
            match=DriverMatch(
                driver_key="pi30",
                protocol_family="pi30",
                model_name="PowMr 4.2kW",
                serial_number="55355535553555",
                probe_target=ProbeTarget(
                    devcode=0x0994,
                    collector_addr=0xFF,
                    device_addr=0,
                ),
            ),
            connection_mode="broadcast",
        )

        self.assertIsNone(flow._existing_entry_for_result(result))

    async def test_existing_entry_with_pn_does_not_claim_unknown_candidate_on_same_nat_ip(self) -> None:
        existing = _FakeEntry("existing", server_ip="192.168.1.50", tcp_port=8899)
        existing.data.update(
            {
                "collector_ip": "195.138.86.175",
                "collector_pn": "V000405SYN94677058",
            }
        )
        existing.unique_id = "manual:195.138.86.175"
        flow = self._make_flow(entries=[existing])
        result = OnboardingResult(
            collector=CollectorCandidate(
                target_ip="195.138.86.175",
                source="manual",
                ip="195.138.86.175",
                connected=True,
            ),
            connection_mode="manual",
            next_action="create_entry",
        )

        self.assertIsNone(flow._existing_entry_for_result(result))


    async def test_existing_entry_matches_prefix_and_full_collector_pn(self) -> None:
        existing = _FakeEntry("existing", server_ip="192.168.1.50", tcp_port=8899)
        existing.data.update({"collector_pn": "Q00000000000010001"})
        existing.unique_id = "collector:Q00000000000010001"
        flow = self._make_flow(entries=[existing])
        result = OnboardingResult(
            collector=CollectorCandidate(
                target_ip="192.168.1.255",
                source="broadcast",
                ip="192.168.1.51",
                connected=True,
                collector=CollectorInfo(collector_pn="Q0000000000001"),
            ),
            connection_mode="broadcast",
        )

        self.assertIs(flow._existing_entry_for_result(result), existing)

    async def test_do_scan_publishes_determinate_progress_updates(self) -> None:
        flow = self._make_flow()
        seen_progress: list[float] = []
        flow.async_update_progress = seen_progress.append

        class _FakeDetector:
            async def async_scan(self, **kwargs):
                await asyncio.sleep(0.4)
                return (
                    OnboardingResult(
                        collector=CollectorCandidate(
                            target_ip="192.168.1.55",
                            source="udp",
                            ip="192.168.1.55",
                            connected=True,
                        ),
                        connection_mode="known_ip",
                    ),
                )

        with patch(
            "custom_components.eybond_local.flows.config.scan.create_onboarding_manager",
            return_value=_FakeDetector(),
        ):
            await flow._async_do_scan()

        self.assertTrue(seen_progress)
        self.assertEqual(seen_progress[-1], 1.0)
        self.assertGreaterEqual(max(seen_progress), 0.99)

    def test_scan_progress_fraction_starts_near_zero_for_discovery(self) -> None:
        flow = self._make_flow()
        flow._scan_progress_stage = "preparing"
        self.assertEqual(flow._scan_progress_fraction(0.0), 0.0)

        flow._scan_progress_stage = "discovering"
        self.assertLessEqual(flow._scan_progress_fraction(0.0), 0.02)

    async def test_do_scan_timeout_returns_without_hanging(self) -> None:
        flow = self._make_flow()
        flow._scan_timeout_seconds = 0.001

        class _SlowDetector:
            async def async_scan(self, **kwargs):
                await asyncio.sleep(0.05)
                return ()

        with patch(
            "custom_components.eybond_local.flows.config.scan.create_onboarding_manager",
            return_value=_SlowDetector(),
        ):
            await flow._async_do_scan()

        self.assertEqual(flow._autodetect_results, {})

    # ---- the manual callback attempt (the ONE identity transaction) ----
    #
    # The old `_async_probe_manual_target` (detector.async_scan before
    # any identity) is gone: a manual callback attempt is exactly one identity
    # transaction and NO pre-entry driver detection. These tests pin the FLOW's
    # side of that contract -- request construction, routing, and "the passive
    # inventory never substitutes for an answer" -- while the transaction's own
    # mechanics live in tests/test_callback_identity.py.

    def _manual_callback_input(self, collector_ip="192.168.1.55", **overrides):
        values = {
            "server_ip": "192.168.1.50",
            "tcp_port": 8899,
            "udp_port": 58899,
            "collector_ip": collector_ip,
            "discovery_target": "192.168.1.255",
            "discovery_interval": 3,
            "heartbeat_interval": 60,
            "driver_hint": "auto",
            "connection_strategy": "callback_on_demand",
        }
        values.update(overrides)
        return values

    async def test_manual_callback_attempt_builds_request_from_settings(self) -> None:
        flow = self._make_flow()

        with _capture_identity_requests() as captured:
            result = await flow.async_step_manual(self._manual_callback_input())

        # A timeout is an observation, not a form error: the flow routes to the
        # actionable result menu.
        self.assertEqual(result["type"], "menu")
        self.assertEqual(result["step_id"], "manual_confirm")
        (request,) = captured
        self.assertEqual(request.server_ip, "192.168.1.50")
        self.assertEqual(request.tcp_port, 8899)
        self.assertEqual(request.udp_port, 58899)
        self.assertEqual(request.target_ip, "192.168.1.55")
        self.assertEqual(request.strategy, "callback_on_demand")
        self.assertEqual(request.owner_prefix, "callback_verification")
        # Production never hardcodes wait budgets; they resolve from the policy.
        self.assertEqual(request.session_wait_timeout, 0.0)
        self.assertEqual(request.lease_wait_timeout, 0.0)

    async def test_manual_callback_targets_collector_ip_never_broadcast(self) -> None:
        flow = self._make_flow()

        with _capture_identity_requests() as captured:
            await flow.async_step_manual(
                self._manual_callback_input(collector_ip="192.168.1.14")
            )

        (request,) = captured
        # The single trigger is aimed at the collector the user typed; the
        # broadcast discovery_target plays no part in a callback attempt -- the
        # request cannot even carry one.
        self.assertEqual(request.target_ip, "192.168.1.14")
        self.assertFalse(hasattr(request, "discovery_target"))

    async def test_manual_callback_never_accepts_a_passive_candidate(self) -> None:
        # BLOCKER 1 regression, transaction edition: the listener inventory is
        # not bound to collector_ip, so a lone passive candidate says nothing
        # about the collector the user typed an address for. When nothing NEW
        # answers the trigger the attempt fails closed -- the passive session is
        # never adopted, never claimed.
        flow = self._make_flow()
        passive_pn = "V000405SYN94677058"
        inventory = [_wire_session("s-passive", passive_pn)]
        registry = _install_domain_registry(flow, inventory)

        with _stub_identity_wire(inventory, answers=()):
            result = await flow.async_step_manual(
                self._manual_callback_input(collector_ip="195.138.86.175")
            )

        self.assertEqual(result["type"], "menu")
        self.assertEqual(result["step_id"], "manual_confirm")
        self.assertEqual(flow._manual_result.last_error, "callback_timeout")
        self.assertEqual(flow._callback_continuation._certified_pn, "")
        self.assertEqual(registry.owner_for_pn(passive_pn), "")

    async def test_manual_preexisting_sessions_never_create_ambiguity(self) -> None:
        # Two passive candidates already exist; the attempt's answer is a THIRD,
        # genuinely new session. Pre-baseline sessions can neither be adopted
        # nor manufacture an "ambiguous" verdict.
        flow = self._make_flow()
        answered_pn = "V001020SYN62344022"
        inventory = [
            _wire_session("s-passive-1", "V000405SYN94677058"),
            _wire_session("s-passive-2", "V000405SYN94677059"),
        ]
        registry = _install_domain_registry(flow, inventory)

        with _stub_identity_wire(
            inventory,
            answers=[_wire_session("s-new", answered_pn)],
            read_pn=answered_pn,
        ):
            result = await flow.async_step_manual(self._manual_callback_input())

        self.assertEqual(result["type"], "menu")
        self.assertEqual(result["step_id"], "manual_recovery_confirm")
        self.assertEqual(flow._callback_continuation._certified_pn, answered_pn)
        # The strangers stayed unclaimed and unadopted.
        self.assertEqual(registry.owner_for_pn("V000405SYN94677058"), "")
        self.assertEqual(registry.owner_for_pn("V000405SYN94677059"), "")

    async def test_manual_callback_timeout_keeps_flow_open_without_entry(self) -> None:
        flow = self._make_flow()
        _install_domain_registry(flow, [])

        with _stub_identity_wire([], answers=()):
            result = await flow.async_step_manual(self._manual_callback_input())

        self.assertEqual(result["type"], "menu")
        self.assertEqual(result["step_id"], "manual_confirm")
        self.assertEqual(
            result["menu_options"],
            ["manual_probe_again", "manual_edit_settings"],
        )
        self.assertEqual(flow._manual_result.last_error, "callback_timeout")
        self.assertEqual(flow._manual_result.next_action, "retry_verification")
        self.assertFalse(hasattr(flow, "async_step_manual_create_pending"))

    async def test_unverified_manual_confirm_exposes_only_retry_and_edit(self) -> None:
        flow = self._make_flow()
        flow._manual_config = {
            "server_ip": "192.168.1.50",
            "collector_ip": "192.168.1.55",
            "tcp_port": 8899,
        }
        flow._manual_result = OnboardingResult(connection_mode="manual")

        result = await flow.async_step_manual_confirm()

        self.assertEqual(result["type"], "menu")
        self.assertEqual(result["step_id"], "manual_confirm")
        self.assertEqual(
            result["menu_options"],
            ["manual_probe_again", "manual_edit_settings"],
        )

    async def test_inbound_wait_can_enable_background_discovery_without_entry(self) -> None:
        flow = self._make_flow()
        flow._manual_config = {
            "server_ip": "192.168.1.50",
            "collector_ip": "",
            "tcp_port": 8899,
        }
        flow._manual_chosen_strategy = CONNECTION_STRATEGY_INBOUND
        flow._manual_result = OnboardingResult(
            connection_mode="manual",
            next_action="await_inbound_session",
            last_error="inbound_awaiting_session",
        )
        discovery = types.SimpleNamespace(
            async_show_discovered_devices_again=AsyncMock()
        )
        with patch(
            "custom_components.eybond_local.passive_discovery."
            "get_passive_callback_discovery",
            return_value=discovery,
        ):
            menu = await flow.async_step_manual_confirm()
            result = await flow.async_step_manual_enable_background_discovery()

        self.assertIn("manual_enable_background_discovery", menu["menu_options"])
        self.assertNotIn("manual_save", menu["menu_options"])
        discovery.async_show_discovered_devices_again.assert_awaited_once_with()
        self.assertEqual(result["type"], "create_entry")
        self.assertEqual(result["data"], {"entry_role": "listener"})
        self.assertEqual(flow._test_unique_id, "eybond_local:listener")

    async def test_manual_confirm_skips_smartess_cloud_assist_for_collector_only_result(self) -> None:
        flow = self._make_flow()
        flow._manual_config = {
            "server_ip": "192.168.1.50",
            "collector_ip": "192.168.1.55",
            "tcp_port": 8899,
        }
        flow._manual_result = OnboardingResult(
            connection_mode="manual",
            collector=CollectorCandidate(
                target_ip="192.168.1.55",
                source="manual",
                ip="192.168.1.55",
                connected=True,
                collector=CollectorInfo(collector_pn="E5000020000000"),
            ),
        )

        result = await flow.async_step_manual_confirm()

        self.assertNotIn("manual_smartess_cloud_assist", result["menu_options"])

    async def test_manual_confirm_skips_smartess_cloud_assist_for_low_confidence_inverter_match(self) -> None:
        flow = self._make_flow()
        flow._manual_config = {
            "server_ip": "192.168.1.50",
            "collector_ip": "192.168.1.55",
            "tcp_port": 8899,
        }
        flow._manual_result = OnboardingResult(
            connection_mode="manual",
            collector=CollectorCandidate(
                target_ip="192.168.1.55",
                source="manual",
                ip="192.168.1.55",
                connected=True,
                collector=CollectorInfo(collector_pn="E5000020000000"),
            ),
            match=DriverMatch(
                driver_key="pi30",
                protocol_family="pi30",
                model_name="PowMr 4.2kW",
                serial_number="553555355535552",
                probe_target=ProbeTarget(devcode=0x0994, collector_addr=0x01, device_addr=0),
                confidence="medium",
            ),
        )

        result = await flow.async_step_manual_confirm()

        self.assertNotIn("manual_smartess_cloud_assist", result["menu_options"])

    async def test_manual_confirm_surfaces_smartess_hint_when_local_driver_is_unconfirmed(self) -> None:
        flow = self._make_flow()
        flow._manual_config = {
            "server_ip": "192.168.1.50",
            "collector_ip": "192.168.1.55",
            "tcp_port": 8899,
        }
        flow._manual_result = OnboardingResult(
            connection_mode="manual",
            collector=CollectorCandidate(
                target_ip="192.168.1.55",
                source="manual",
                ip="192.168.1.55",
                connected=True,
                collector=CollectorInfo(
                    collector_pn="PN123",
                    smartess_collector_version="8.50.12.3",
                    smartess_protocol_asset_id="0000",
                ),
            ),
        )

        result = await flow.async_step_manual_confirm()
        placeholders = result["description_placeholders"]

        self.assertIn("SmartESS metadata", placeholders["probe_summary"])
        self.assertIn("identity is confirmed", placeholders["control_summary"])

    async def test_manual_edit_settings_returns_to_manual_form_with_previous_values(self) -> None:
        flow = self._make_flow()
        flow._manual_config = {
            "server_ip": "192.168.1.50",
            "collector_ip": "192.168.1.55",
            "driver_hint": "auto",
            "tcp_port": 8899,
            "udp_port": 58899,
            "discovery_target": "192.168.1.255",
            "discovery_interval": 3,
            "heartbeat_interval": 60,
        }
        flow._manual_result = OnboardingResult(connection_mode="manual")

        result = await flow.async_step_manual_edit_settings()

        self.assertEqual(result["type"], "form")
        self.assertEqual(result["step_id"], "manual")
        self.assertEqual(flow._manual_defaults["collector_ip"], "192.168.1.55")
        self.assertIsNone(flow._manual_result)

    async def test_manual_step_localizes_driver_selector_labels(self) -> None:
        flow = self._make_flow()
        flow.hass.config.language = "uk"

        result = await flow.async_step_manual()

        selector = result["data_schema"].schema["driver_hint"]
        labels = [option["label"] for option in selector.config.kwargs["options"]]
        self.assertEqual(
            labels,
            [
                "Авто",
                "SMG / Modbus",
                "SRNE / Modbus",
                "MUST PV/PH18",
                "Каталог пристроїв / Modbus (Aohai FSA…)",
                "PI30",
                "EyeBond G-ASCII",
                "SmartESS 0925 / Modbus",
                "PI18",
                "EyeBond Short-ASCII",
            ],
        )

    async def test_manual_step_recovers_when_auto_config_is_missing(self) -> None:
        flow = self._make_flow()
        flow._auto_config = None

        result = await flow.async_step_manual()

        self.assertEqual(result["type"], "form")
        self.assertEqual(result["step_id"], "manual")
        self.assertEqual(flow._auto_config["server_ip"], "192.168.1.50")

    async def test_manual_step_heals_stale_submitted_server_ip_before_attempt(self) -> None:
        flow = self._make_flow()
        flow._auto_config = {"connection_type": "eybond", "server_ip": "192.168.1.50"}

        with _capture_identity_requests() as captured:
            result = await flow.async_step_manual(
                # A stale prefill: 192.168.1.104 is no longer a local address.
                # Only callback_on_demand runs an active attempt at all.
                self._manual_callback_input(
                    collector_ip="192.168.1.14", server_ip="192.168.1.104"
                )
            )

        self.assertEqual(result["type"], "menu")
        self.assertEqual(result["step_id"], "manual_confirm")
        (request,) = captured
        self.assertEqual(request.server_ip, "192.168.1.50")
        self.assertEqual(flow._manual_config["server_ip"], "192.168.1.50")

    async def test_manual_probe_again_retries_with_stored_settings(self) -> None:
        flow = self._make_flow()
        flow._manual_config = {
            "server_ip": "192.168.1.50",
            "collector_ip": "192.168.1.55",
            "driver_hint": "auto",
            "tcp_port": 8899,
            "udp_port": 58899,
            "discovery_target": "192.168.1.255",
            "discovery_interval": 3,
            "heartbeat_interval": 60,
        }

        with _capture_identity_requests() as captured:
            result = await flow.async_step_manual_probe_again()

        # The retry is a whole NEW identity transaction built from the stored
        # settings -- never a re-probe carrying the previous attempt's state.
        (request,) = captured
        self.assertEqual(request.server_ip, "192.168.1.50")
        self.assertEqual(request.target_ip, "192.168.1.55")
        self.assertEqual(request.tcp_port, 8899)
        self.assertEqual(request.udp_port, 58899)
        self.assertEqual(result["type"], "menu")
        self.assertEqual(result["step_id"], "manual_confirm")

    async def test_manual_save_refuses_unidentified_entry(self) -> None:
        flow = self._make_flow()
        flow._manual_config = {
            "server_ip": "192.168.1.50",
            "collector_ip": "192.168.1.55",
            "driver_hint": "auto",
            "tcp_port": 8899,
            "udp_port": 58899,
            "discovery_target": "192.168.1.255",
            "discovery_interval": 3,
            "heartbeat_interval": 60,
        }
        flow._manual_result = OnboardingResult(connection_mode="manual")

        result = await flow.async_step_manual_save()

        self.assertEqual(result["type"], "menu")
        self.assertEqual(result["step_id"], "manual_confirm")
        self.assertEqual(
            result["menu_options"],
            ["manual_probe_again", "manual_edit_settings"],
        )
        self.assertFalse(hasattr(flow, "_test_unique_id"))

    async def test_manual_callback_identity_alone_requires_recovery_proof(self) -> None:
        # Batch 6 (the pcap regression gate): a certified callback identity
        # WITHOUT a proven recovery route must never mint a normal
        # callback_on_demand entry -- such an entry deadlocks on its next
        # silent socket. The normal entry is created only via the recovery
        # verification path; identity alone remains inside this flow.

        flow = self._make_flow()
        flow._manual_config = {
            "server_ip": "192.168.1.50",
            "collector_ip": "192.168.1.55",
            "driver_hint": "auto",
            "tcp_port": 18899,
            "udp_port": 58899,
            "discovery_target": "",
            "discovery_interval": 3,
            "heartbeat_interval": 60,
        }
        # A callback-only collector: the manual probe to the IP returns no
        # collector object, so collector_pn would otherwise be dropped.
        flow._manual_result = OnboardingResult(
            connection_mode="known_ip", next_action="verify_recovery"
        )
        # Post-attempt flow state: the user CHOSE callback_on_demand, the
        # transaction certified the PN, and no evidence was produced.
        flow._manual_chosen_strategy = CONNECTION_STRATEGY_CALLBACK_ON_DEMAND
        flow._callback_continuation._certified_pn = "V001020SYN62344022"
        flow._verified_connection_strategy = CONNECTION_STRATEGY_CALLBACK_ON_DEMAND
        flow._verified_strategy_evidence = ""

        self.assertFalse(flow._callback_continuation._callback_terminal_input.has_proof)
        result = await flow.async_step_manual_save()

        self.assertEqual(result["type"], "menu")
        self.assertEqual(result["step_id"], "manual_confirm")
        self.assertNotIn("manual_save", result["menu_options"])
        self.assertNotEqual(
            getattr(flow, "_test_unique_id", ""), "collector:V001020SYN62344022"
        )

    async def test_user_confirmed_session_creates_no_recovery_contract(self) -> None:
        # A user explicitly binding an OBSERVED session is honest inbound
        # provenance (legacy user_confirmed_session evidence) -- but nothing was
        # rebooted and nothing was proven about reconnection after loss, so NO
        # RecoveryContract may appear.
        from custom_components.eybond_local.const import (
            CONF_CONNECTION_STRATEGY_EVIDENCE,
            CONNECTION_STRATEGY_EVIDENCE_USER_CONFIRMED_SESSION,
        )

        flow = self._make_flow()
        flow._manual_config = {
            "server_ip": "192.168.1.50",
            "collector_ip": "",
            "driver_hint": "auto",
            "tcp_port": 18899,
            "udp_port": 58899,
            "discovery_target": "",
            "discovery_interval": 3,
            "heartbeat_interval": 60,
        }
        flow._manual_result = OnboardingResult(
            connection_mode="manual", next_action="create_entry"
        )
        flow._manual_chosen_strategy = CONNECTION_STRATEGY_INBOUND
        flow._callback_continuation._certified_pn = "V001020SYN62344022"
        flow._verified_connection_strategy = CONNECTION_STRATEGY_INBOUND
        flow._verified_strategy_evidence = (
            CONNECTION_STRATEGY_EVIDENCE_USER_CONFIRMED_SESSION
        )

        result = await flow.async_step_manual_save()

        self.assertEqual(result["type"], "create_entry")
        # The legacy user-binding evidence remains (its own honest provenance)...
        self.assertEqual(
            result["data"][CONF_CONNECTION_STRATEGY_EVIDENCE],
            CONNECTION_STRATEGY_EVIDENCE_USER_CONFIRMED_SESSION,
        )
        # ...but it is NOT recovery: no contract is minted.
        self.assertNotIn("recovery_contract", result["data"])

    async def test_callback_verification_unconfirmed_creates_no_normal_entry(self) -> None:
        # Item 5: a callback verification was in play (a passive-discovery
        # verification context exists) but produced no registry-certified strong
        # PN. Entry creation MUST fail closed -- no normal create_entry doomed to
        # collector_offline -- and instead re-prompt the manual verification form
        # with an error so the user can retry.
        flow = self._make_flow()
        flow._manual_config = {
            "server_ip": "192.168.1.50",
            "collector_ip": "192.168.1.55",
            "driver_hint": "auto",
            "tcp_port": 18899,
            "udp_port": 58899,
            "discovery_target": "",
            "discovery_interval": 3,
            "heartbeat_interval": 60,
        }
        flow._manual_result = OnboardingResult(
            connection_mode="known_ip", next_action="retry_verification"
        )
        # Verification context present, but no verified full PN was ever bound.
        flow._callback_continuation._expected_pn = "V001020SYN62344022"
        flow._callback_continuation._certified_pn = ""

        result = await flow.async_step_manual_save()

        self.assertEqual(result["type"], "menu")
        self.assertEqual(result["step_id"], "manual_confirm")
        self.assertNotIn("manual_save", result["menu_options"])
        # The unverified/expected PN never became a durable collector identity.
        self.assertNotEqual(
            getattr(flow, "_test_unique_id", None), "collector:V001020SYN62344022"
        )


    async def test_detected_inverter_without_collector_pn_is_not_created(self) -> None:
        # Item 1: a detected model + serial does NOT substitute for the collector
        # PN (registry ownership is by PN only). No normal entry is created; the
        # detection stays in the flow and the user is re-prompted to verify.
        flow = self._make_flow()
        flow._manual_config = {
            "server_ip": "192.168.1.50",
            "collector_ip": "192.168.1.55",
            "driver_hint": "auto",
            "tcp_port": 8899,
            "udp_port": 58899,
            "discovery_target": "192.168.1.255",
            "discovery_interval": 3,
            "heartbeat_interval": 60,
        }
        flow._manual_result = OnboardingResult(
            collector=CollectorCandidate(
                target_ip="192.168.1.55", source="manual", ip="192.168.1.55", connected=True
            ),  # detected inverter, but NO collector PN
            match=DriverMatch(
                driver_key="modbus_smg",
                protocol_family="modbus_smg",
                model_name="SMG 6200",
                serial_number="92632500000001",
                probe_target=ProbeTarget(devcode=0x0001, collector_addr=0x01, device_addr=1),
                confidence="high",
            ),
            connection_mode="manual",
        )

        result = await flow.async_step_manual_save()

        # A detected model/serial is NOT a session identity: no entry is made.
        self.assertEqual(result["type"], "menu")
        self.assertEqual(result["step_id"], "manual_confirm")
        self.assertNotIn("manual_save", result["menu_options"])
        self.assertFalse(hasattr(flow, "_test_unique_id"))

    async def test_full_pn_with_model_serial_is_created(self) -> None:
        # Item 1: a full PN alongside model/serial DOES create a normal entry.
        flow = self._make_flow()
        flow._manual_config = {
            "server_ip": "192.168.1.50",
            "collector_ip": "192.168.1.55",
            "driver_hint": "auto",
            "tcp_port": 8899,
            "udp_port": 58899,
            "discovery_target": "192.168.1.255",
            "discovery_interval": 3,
            "heartbeat_interval": 60,
        }
        flow._manual_result = OnboardingResult(
            collector=CollectorCandidate(
                target_ip="192.168.1.55",
                source="manual",
                ip="192.168.1.55",
                connected=True,
                collector=CollectorInfo(collector_pn="V001020SYN62344022"),
            ),
            match=DriverMatch(
                driver_key="modbus_smg",
                protocol_family="modbus_smg",
                model_name="SMG 6200",
                serial_number="92632500000001",
                probe_target=ProbeTarget(devcode=0x0001, collector_addr=0x01, device_addr=1),
                confidence="high",
            ),
            connection_mode="manual",
        )

        result = await flow.async_step_manual_save()

        self.assertEqual(result["type"], "create_entry")
        self.assertEqual(result["data"]["collector_pn"], "V001020SYN62344022")
        self.assertEqual(flow._test_unique_id, "collector:V001020SYN62344022")

    async def test_listener_entry_is_created_without_collector_pn(self) -> None:
        # Item 1 exception: the integration listener/bootstrap entry owns no
        # collector session, so it is created without a PN.
        flow = self._make_flow()
        result = await flow.async_step_listener()
        self.assertEqual(result["type"], "create_entry")
        self.assertEqual(result["data"].get("entry_role"), "listener")



    async def test_manual_entry_defers_inverter_identity_and_controls_to_runtime(self) -> None:
        flow = self._make_flow()
        flow._manual_config = {
            "server_ip": "192.168.1.50",
            "collector_ip": "192.168.1.55",
            "driver_hint": "auto",
            "tcp_port": 8899,
            "udp_port": 58899,
            "discovery_target": "192.168.1.255",
            "discovery_interval": 3,
            "heartbeat_interval": 60,
        }
        flow._manual_result = OnboardingResult(
            collector=CollectorCandidate(
                target_ip="192.168.1.55",
                source="manual",
                ip="192.168.1.55",
                connected=True,
                collector=CollectorInfo(collector_pn="V001020SYN62344022"),
            ),
            match=DriverMatch(
                driver_key="modbus_smg",
                protocol_family="modbus_smg",
                model_name="SMG 6200",
                serial_number="92632500000001",
                probe_target=ProbeTarget(devcode=0x0001, collector_addr=0x01, device_addr=1),
                confidence="high",
            ),
            connection_mode="manual",
        )

        result = await flow.async_step_manual_save()

        self.assertEqual(result["type"], "create_entry")
        self.assertEqual(result["data"]["control_mode"], "auto")
        self.assertEqual(result["data"]["detection_confidence"], "none")
        self.assertEqual(result["data"]["detected_model"], "")
        self.assertEqual(result["data"]["detected_serial"], "")
        self.assertEqual(result["data"][CONF_DRIVER_HINT], "auto")

    async def test_manual_success_routes_to_manual_confirm_without_detection(self) -> None:
        # The manual callback attempt proves a COLLECTOR and nothing else: no
        # driver sweep runs before the entry exists, so there is no detection
        # summary to route through. Success carries a collector-only result
        # (no match, no confidence) straight to manual_confirm.
        flow = self._make_flow()
        flow._manual_config = {
            "server_ip": "192.168.1.50",
            "collector_ip": "192.168.1.55",
            "driver_hint": "auto",
            "tcp_port": 8899,
            "udp_port": 58899,
            "discovery_target": "192.168.1.255",
            "discovery_interval": 3,
            "heartbeat_interval": 60,
        }
        answered_pn = "V001020SYN62344022"
        inventory: list[dict[str, object]] = []
        registry = _install_domain_registry(flow, inventory)

        with _stub_identity_wire(
            inventory,
            answers=[_wire_session("s-new", answered_pn)],
            read_pn=answered_pn,
        ), patch.object(
            config_scan_module,
            "create_onboarding_manager",
            side_effect=AssertionError("no detection may run before the entry exists"),
        ):
            result = await flow.async_step_manual_probe_again()

        self.assertEqual(result["type"], "menu")
        self.assertEqual(result["step_id"], "manual_confirm")
        self.assertEqual(flow._callback_continuation._certified_pn, answered_pn)
        # The result is honest: the certified collector, and nothing invented.
        self.assertIsNone(flow._manual_result.match)
        self.assertEqual(flow._manual_result.collector.source, "callback_identity")
        self.assertEqual(
            flow._manual_result.collector.collector.collector_pn, answered_pn
        )
        owner = registry.owner_for_pn(answered_pn)
        self.assertTrue(owner.startswith("callback_verification:"))

    async def test_auto_entry_does_not_persist_scan_time_inverter_metadata(self) -> None:
        flow = self._make_flow()
        flow._auto_config = {
            "server_ip": "192.168.1.104",
            "collector_ip": "",
            "driver_hint": "auto",
            "tcp_port": 8899,
            "udp_port": 58899,
            "discovery_target": "192.168.1.255",
            "discovery_interval": 3,
            "heartbeat_interval": 60,
        }
        flow._selected_result = OnboardingResult(
            collector=CollectorCandidate(
                target_ip="192.168.1.55",
                source="udp",
                ip="192.168.1.55",
                connected=True,
                collector=CollectorInfo(collector_pn="V001020SYN62344022"),
            ),
            match=DriverMatch(
                driver_key="modbus_smg",
                protocol_family="modbus_smg",
                model_name="SMG family 4200 variant",
                serial_number="15573400000004",
                probe_target=ProbeTarget(devcode=0x0001, collector_addr=0x01, device_addr=1),
                confidence="medium",
                details={
                    "device_catalog": {
                        "kind": "family",
                        "tier": "partial",
                    }
                },
            ),
            connection_mode="known_ip",
        )

        result = await flow._async_create_entry_from_result({"poll_interval": 30})

        self.assertEqual(result["type"], "create_entry")
        self.assertNotIn("device_catalog_kind", result["data"])
        self.assertNotIn("device_catalog_tier", result["data"])
        self.assertNotIn("device_catalog_entry_key", result["data"])
        self.assertEqual(result["data"]["detected_model"], "")
        self.assertEqual(result["data"]["detected_serial"], "")
        self.assertEqual(result["data"]["detection_confidence"], "none")
        self.assertEqual(result["data"][CONF_DRIVER_HINT], "auto")
        self.assertEqual(result["data"]["control_mode"], "auto")

    async def test_smartess_cloud_assist_preview_does_not_bind_runtime_driver(self) -> None:
        flow = self._make_flow()
        with tempfile.TemporaryDirectory() as tempdir:
            flow.hass.config.config_dir = tempdir
            flow._selected_result = OnboardingResult(
                collector=CollectorCandidate(
                    target_ip="192.168.1.55",
                    source="udp",
                    ip="192.168.1.55",
                    connected=True,
                    collector=CollectorInfo(
                        collector_pn="E5000020000000",
                        smartess_protocol_asset_id="0000",
                    ),
                ),
                connection_mode="known_ip",
            )

            evidence = build_cloud_evidence_payload(
                source="smartess_cloud_onboarding",
                payload={
                    "normalized": {
                        "device_list": {
                            "device_count": 1,
                            "devices": [
                                {
                                    "pn": "E50000200000000001",
                                    "sn": "E50000200000000001000001",
                                    "devcode": 2376,
                                    "devaddr": 5,
                                    "devName": "SD-HYM-4862HWP",
                                    "devalias": "Garage inverter",
                                    "status": "online",
                                    "brand": "SmartESS",
                                }
                            ],
                        },
                        "device_detail": {
                            "section_counts": {
                                "bc_": 1,
                                "bt_": 1,
                                "gd_": 1,
                                "pv_": 1,
                                "sy_": 1,
                            }
                        },
                        "device_settings": {
                            "field_count": 39,
                            "mapped_field_count": 28,
                            "fields_with_current_value": 2,
                            "fields": [
                                {
                                    "title": "Output priority",
                                    "bucket": "exact_0925",
                                    "has_current_value": True,
                                    "current_value": 2,
                                    "choices": [
                                        {"value": 0, "raw_value": "0", "label": "UTI"},
                                        {"value": 1, "raw_value": "1", "label": "SOL"},
                                        {"value": 2, "raw_value": "2", "label": "SBU"},
                                    ],
                                    "binding": {"register": 4537},
                                },
                                {
                                    "title": "Battery Type",
                                    "bucket": "exact_0925",
                                    "has_current_value": True,
                                    "current_value": 6,
                                    "choices": [
                                        {"value": 2, "raw_value": "2", "label": "USER"},
                                        {"value": 6, "raw_value": "6", "label": "Li4"},
                                    ],
                                    "binding": {"register": 4539},
                                },
                                {
                                    "title": "Boot method",
                                    "bucket": "cloud_only",
                                    "has_current_value": False,
                                },
                            ],
                        }
                    }
                },
                collector_pn="E5000020000000",
                pn="E50000200000000001",
                sn="E50000200000000001000001",
                devcode=2376,
                devaddr=5,
                summary={
                    "detail_sections": ["bc_", "bt_", "gd_", "pv_", "sy_"],
                    "settings_field_count": 39,
                    "settings_mapped_field_count": 28,
                    "settings_exact_0925_field_count": 28,
                    "settings_probable_0925_field_count": 5,
                    "settings_cloud_only_field_count": 6,
                    "settings_current_values_included": True,
                },
            )

            flow._smartess_cloud_assist_mode = "auto"
            with patch(
                "custom_components.eybond_local.support.cloud_evidence_providers.fetch_and_export_smartess_device_bundle_cloud_evidence",
                return_value=CloudEvidenceRecord(
                    path=Path("/config/eybond_local/cloud_evidence/onboarding.json"),
                    payload=evidence,
                ),
            ):
                assist_result = await flow.async_step_smartess_cloud_assist(
                    {"username": "test-user", "password": "secret"}
                )

            self.assertEqual(assist_result["type"], "menu")
            self.assertEqual(assist_result["step_id"], "smartess_cloud_assist_summary")
            self.assertEqual(assist_result["menu_options"], ["confirm"])

            placeholders = assist_result["description_placeholders"]
            self.assertIn("SmartESS 0925", placeholders["smartess_cloud_mapping_table"])
            self.assertIn("E50000200000000001", placeholders["smartess_cloud_identity_table"])
            self.assertIn("Garage inverter", placeholders["smartess_cloud_identity_table"])
            self.assertIn("bc_ (1)", placeholders["smartess_cloud_detail_summary"])
            self.assertIn("39", placeholders["smartess_cloud_settings_table"])
            self.assertIn("Output priority", placeholders["smartess_cloud_highlights_table"])
            self.assertIn("SBU", placeholders["smartess_cloud_highlights_table"])
            self.assertIn("reg 4537", placeholders["smartess_cloud_highlights_table"])

            created = await flow.async_step_confirm({"poll_mode": "auto"})

            self.assertEqual(created["type"], "create_entry")
            self.assertEqual(created["data"][CONF_SMARTESS_PROTOCOL_ASSET_ID], "0000")
            self.assertNotEqual(created["data"].get(CONF_SMARTESS_PROFILE_KEY), "smartess_0925")
            self.assertEqual(created["data"][CONF_DRIVER_HINT], "auto")

    async def test_scan_results_placeholders_use_localized_select_hint(self) -> None:
        flow = self._make_flow()
        flow.hass.config.language = "ru"
        flow._autodetect_results = {
            "0": OnboardingResult(
                collector=CollectorCandidate(target_ip="192.168.1.14", source="udp", ip="192.168.1.14", connected=True),
                match=DriverMatch(
                    driver_key="pi30",
                    protocol_family="pi30",
                    model_name="PowMr 4.2kW",
                    serial_number="553555355535552",
                    probe_target=ProbeTarget(devcode=0x0994, collector_addr=0x01, device_addr=0),
                ),
                connection_mode="known_ip",
            )
        }

        await flow._async_ensure_translation_bundle()

        placeholders = flow._scan_results_placeholders()

        self.assertIn("Выберите нужное устройство или адрес", placeholders["scan_next_hint"])
        self.assertNotIn("инвертор", placeholders["scan_summary"].lower())

    async def test_scan_results_placeholders_use_localized_retry_actions(self) -> None:
        flow = self._make_flow()
        flow.hass.config.language = "uk"
        flow._autodetect_results = {
            "0": OnboardingResult(
                collector=CollectorCandidate(
                    target_ip="192.168.1.14",
                    source="udp",
                    ip="192.168.1.14",
                    udp_reply="rsp>server=1;",
                ),
                connection_mode="known_ip",
            )
        }

        await flow._async_ensure_translation_bundle()

        placeholders = flow._scan_results_placeholders()

        self.assertIn("Повторити сканування", placeholders["scan_next_hint"])
        self.assertIn("Ввести адресу вручну", placeholders["scan_next_hint"])
        self.assertNotIn("Запустити глибоке сканування", placeholders["scan_next_hint"])
        self.assertNotIn("Refresh scan", placeholders["scan_next_hint"])
        self.assertNotIn("Enter address manually", placeholders["scan_next_hint"])

    async def test_scan_results_placeholders_do_not_offer_pending_from_scan(self) -> None:
        flow = self._make_flow()
        flow.hass.config.language = "ru"
        flow._autodetect_results = {
            "0": OnboardingResult(
                collector=CollectorCandidate(
                    target_ip="192.168.1.57",
                    source="udp",
                    ip="192.168.1.57",
                    connected=True,
                    collector=CollectorInfo(
                        collector_pn="PN789",
                        smartess_collector_version="8.50.12.3",
                        smartess_protocol_asset_id="0000",
                    ),
                ),
                connection_mode="known_ip",
            )
        }

        await flow._async_ensure_translation_bundle()

        placeholders = flow._scan_results_placeholders()
        result_label = flow._result_label(flow._autodetect_results["0"])

        self.assertIn("Доступны для настройки", placeholders["scan_summary"])
        self.assertNotIn("инвертор", placeholders["scan_summary"].lower())
        self.assertNotIn("ожидающее", placeholders["scan_next_hint"].lower())
        self.assertIn("ввести адрес вручную", placeholders["scan_next_hint"].lower())
        self.assertIn("Готово к настройке", result_label)
        self.assertNotIn("SmartESS", result_label)

    async def test_scan_result_labels_name_passive_callback_peer_address_explicitly(self) -> None:
        flow = self._make_flow()
        flow.hass.config.language = "uk"
        result = OnboardingResult(
            collector=CollectorCandidate(
                target_ip="192.168.1.50",
                source="callback_listener",
                ip="192.168.1.1",
                connected=True,
                collector=CollectorInfo(collector_pn="V001107SYN8229"),
            ),
            connection_mode="callback_listener",
            next_action="manual_driver_selection",
        )
        flow._autodetect_results = {"0": result}

        await flow._async_ensure_translation_bundle()

        result_label = flow._result_label(result)
        scan_line = flow._scan_result_line(1, result)

        self.assertIn("PN V001107SYN8229", result_label)
        self.assertIn("з’єднання від 192.168.1.1", result_label)
        self.assertIn("з’єднання від 192.168.1.1", scan_line)
        self.assertNotIn("колектор 192.168.1.1", scan_line)

    async def test_options_runtime_step_renders_branch_aware_connection_section(self) -> None:
        options = self._make_options_flow()

        result = await options.async_step_runtime()

        self.assertEqual(result["type"], "form")
        self.assertEqual(result["step_id"], "runtime")

    async def test_options_init_menu_exposes_collector_wifi(self) -> None:
        options = self._make_options_flow()

        result = await options.async_step_init()

        self.assertEqual(
            result["menu_options"],
            [
                "connection",
                "runtime",
                "collector_wifi",
                "diagnostics",
            ],
        )

    async def test_options_runtime_ambiguity_requires_post_entry_protocol_choice(self) -> None:
        options = self._make_options_flow()
        options._config_entry.runtime_data = types.SimpleNamespace(
            inverter_protocol_candidates=(
                RuntimeInverterCandidate(
                    driver_key="smartess_local",
                    protocol_family="0925",
                    model_name="Hybrid 5K",
                    serial_number="12345",
                ),
                RuntimeInverterCandidate(
                    driver_key="pi30",
                    protocol_family="pi30",
                    model_name="Hybrid 5K",
                    serial_number="12345",
                ),
            ),
            data=types.SimpleNamespace(collector=None, values={}),
        )

        menu = await options.async_step_init()
        self.assertEqual(menu["menu_options"][0], "inverter_protocol")

        form = await options.async_step_inverter_protocol()
        self.assertEqual(form["step_id"], "inverter_protocol")
        self.assertEqual(
            _schema_select_options(form["data_schema"], "driver_hint"),
            ["smartess_local", "pi30"],
        )

        result = await options.async_step_inverter_protocol(
            {"driver_hint": "pi30"}
        )
        self.assertEqual(result["type"], "create_entry")
        self.assertEqual(options._config_entry.options["driver_hint"], "pi30")
        self.assertEqual(options._config_entry.data["detected_driver"], "")
        self.assertEqual(options._config_entry.data["detected_model"], "")
        self.assertEqual(options._config_entry.data["detected_serial"], "")
        self.assertEqual(options._config_entry.data["detection_confidence"], "none")
        self.assertEqual(options._config_entry.data["control_mode"], "auto")
        self.assertEqual(len(options.hass.config_entries.updates), 1)
        self.assertEqual(options.hass.config_entries.reloaded, [])

    async def test_options_protocol_choice_rejects_unobserved_driver(self) -> None:
        options = self._make_options_flow()
        options._config_entry.runtime_data = types.SimpleNamespace(
            inverter_protocol_candidates=(
                RuntimeInverterCandidate(
                    driver_key="pi30",
                    protocol_family="pi30",
                    model_name="Hybrid 5K",
                    serial_number="12345",
                ),
                RuntimeInverterCandidate(
                    driver_key="smartess_local",
                    protocol_family="0925",
                    model_name="Hybrid 5K",
                    serial_number="12345",
                ),
            ),
            data=types.SimpleNamespace(collector=None, values={}),
        )

        result = await options.async_step_inverter_protocol(
            {"driver_hint": "modbus_smg"}
        )

        self.assertEqual(result["type"], "form")
        self.assertEqual(result["errors"]["driver_hint"], "invalid_selection")
        self.assertEqual(options.hass.config_entries.updates, [])

    async def test_options_init_hides_cloud_tools_for_persisted_custom_collector(
        self,
    ) -> None:
        options = self._make_options_flow()
        options._config_entry.data.update(
            {
                "collector_kind": COLLECTOR_KIND_ESP_EYBOND_BRIDGE,
                "collector_hardware_version": "esp-collector/0.1.10/ESP8266",
                "collector_virtual_bridge": True,
                CONF_CONNECTION_STRATEGY: CONNECTION_STRATEGY_INBOUND,
                "endpoint_control_policy": "external",
            }
        )
        options._config_entry.options.update(
            {
                "collector_kind": COLLECTOR_KIND_ESP_EYBOND_BRIDGE,
                "collector_hardware_version": "esp-collector/0.1.10/ESP8266",
                "collector_virtual_bridge": True,
            }
        )
        options._config_entry.runtime_data = types.SimpleNamespace(
            proxy_capture_overview=types.SimpleNamespace(
                can_start=False,
                can_stop=False,
                critical_phase=False,
                blocking_reason="operating_profile_requires_cloud_and_ha",
            ),
            latest_proxy_trace_path="",
            latest_proxy_trace_manifest_path="",
            data=types.SimpleNamespace(
                collector=None,
                values={},
            ),
        )

        result = await options.async_step_init()
        cloud_deep_link = await options.async_step_cloud_tools()
        proxy_deep_link = await options.async_step_proxy_capture()
        shadow_deep_link = await options.async_step_shadow_learning()

        self.assertEqual(
            result["menu_options"],
            [
                "collector_endpoint",
                "runtime",
                "collector_wifi",
                "collector_uart",
                "diagnostics",
            ],
        )
        self.assertNotIn("cloud_tools", result["menu_options"])
        self.assertIn("collector_uart", result["menu_options"])
        self.assertTrue(
            result["description_placeholders"]["bridge_note"].strip()
        )
        for deep_link in (cloud_deep_link, proxy_deep_link, shadow_deep_link):
            self.assertEqual(deep_link["step_id"], "init")
            self.assertNotIn("cloud_tools", deep_link["menu_options"])

    async def test_virtual_bridge_endpoint_menu_uses_verified_inbound_form(self) -> None:
        options = self._make_options_flow()
        options._config_entry.data.update(
            {
                "collector_kind": COLLECTOR_KIND_ESP_EYBOND_BRIDGE,
                "collector_hardware_version": "esp-collector/0.1.10/ESP8266",
                "collector_virtual_bridge": True,
                CONF_CONNECTION_STRATEGY: CONNECTION_STRATEGY_INBOUND,
                "endpoint_control_policy": "integration_managed",
            }
        )
        options._config_entry.runtime_data = types.SimpleNamespace(
            data=types.SimpleNamespace(
                collector=types.SimpleNamespace(collector_virtual_bridge=True),
                values={
                    "collector_virtual_bridge": True,
                    "collector_server_endpoint": "195.191.72.37,18899,TCP",
                },
            ),
        )

        prefill = options._transition_prefill()
        form = await options.async_step_collector_endpoint()

        self.assertEqual(form["type"], "form")
        self.assertEqual(form["step_id"], "strategy_transition")
        self.assertEqual(
            options._transition_target_strategy, CONNECTION_STRATEGY_INBOUND
        )
        self.assertIn("advertised_server_ip", form["data_schema"].schema)
        self.assertIn("advertised_tcp_port", form["data_schema"].schema)
        self.assertEqual(
            (prefill["host"], prefill["port"], prefill["provenance"]),
            ("195.191.72.37", 18899, "observed_current_endpoint"),
        )
        self.assertNotIn("collector_ip", form["data_schema"].schema)
        self.assertEqual(
            form["description_placeholders"]["connection_strategy_rollback"], ""
        )
        risk = form["description_placeholders"]["connection_strategy_risk"]
        self.assertIn("save this address", risk)
        self.assertNotIn("cloud", risk.lower())

    async def test_options_init_uses_one_cloud_tools_menu_for_factory_collector(self) -> None:
        options = self._make_options_flow()
        options._config_entry.data.update(
            {
                "collector_pn": "E50000200000000001",
                CONF_CONNECTION_STRATEGY: CONNECTION_STRATEGY_CALLBACK_ON_DEMAND,
                "endpoint_control_policy": "external",
            }
        )
        options._config_entry.runtime_data = types.SimpleNamespace(
            cloud_evidence_provider="smartess",
            smartess_collector_pn="E50000200000000001",
            proxy_capture_overview=types.SimpleNamespace(
                can_start=True,
                can_stop=False,
                critical_phase=False,
            ),
            data=types.SimpleNamespace(
                collector=types.SimpleNamespace(collector_virtual_bridge=False),
                values={},
            ),
        )

        result = await options.async_step_init()

        self.assertIn("cloud_tools", result["menu_options"])
        self.assertNotIn("shadow_learning", result["menu_options"])
        self.assertNotIn("proxy_capture", result["menu_options"])
        tools = await options.async_step_cloud_tools()
        self.assertEqual(
            tools["menu_options"],
            ["shadow_learning", "proxy_capture", "create_support_package"],
        )
        self.assertNotIn("collector_uart", result["menu_options"])
        self.assertEqual(result["description_placeholders"]["bridge_note"], "")

    async def test_callback_profile_exposes_shared_cloud_tools_path(self) -> None:
        options = self._make_options_flow()
        options._config_entry.data = {
            **dict(options._config_entry.data),
            "collector_kind": COLLECTOR_KIND_UNKNOWN,
            "collector_pn": "E50000200000000001",
            CONF_CONNECTION_STRATEGY: CONNECTION_STRATEGY_CALLBACK_ON_DEMAND,
            "endpoint_control_policy": "external",
        }
        options._config_entry.options = {
            "collector_kind": COLLECTOR_KIND_UNKNOWN,
        }
        options._config_entry.runtime_data = types.SimpleNamespace(
            cloud_evidence_provider="smartess",
            smartess_collector_pn="E50000200000000001",
            data=types.SimpleNamespace(
                collector=types.SimpleNamespace(collector_virtual_bridge=False),
                values={
                    "model_name": "SMG 6200",
                    "serial_number": "SMGSYN240001",
                },
            ),
        )

        menu = await options.async_step_init()
        with tempfile.TemporaryDirectory() as tempdir:
            options.hass.config.config_dir = tempdir
            diagnostics = options._diagnostics_menu_options(
                "create_support_package"
            )

        self.assertIn("cloud_tools", menu["menu_options"])
        self.assertNotIn("shadow_learning", menu["menu_options"])
        self.assertNotIn("proxy_capture", menu["menu_options"])
        self.assertNotIn("proxy_capture", diagnostics)
        self.assertFalse(options._collector_capabilities().ha_only_required)

    async def test_ha_only_profile_hides_new_cloud_tool_starts(self) -> None:
        options = self._make_options_flow()
        options._config_entry.data.update(
            {
                CONF_CONNECTION_STRATEGY: CONNECTION_STRATEGY_INBOUND,
                "endpoint_control_policy": "integration_managed",
            }
        )
        options._config_entry.runtime_data = types.SimpleNamespace(
            data=types.SimpleNamespace(
                collector=types.SimpleNamespace(collector_virtual_bridge=False),
                values={},
            ),
        )

        menu = await options.async_step_init()
        deep_link = await options.async_step_cloud_tools()

        self.assertNotIn("cloud_tools", menu["menu_options"])
        self.assertEqual(deep_link["step_id"], "connection")

    async def test_active_proxy_cleanup_remains_on_main_menu_after_capability_drift(
        self,
    ) -> None:
        options = self._make_options_flow()
        options._config_entry.runtime_data = types.SimpleNamespace(
            proxy_capture_overview=types.SimpleNamespace(
                can_start=False,
                can_stop=True,
                critical_phase=False,
            ),
            data=types.SimpleNamespace(
                collector=types.SimpleNamespace(collector_virtual_bridge=True),
                values={"collector_virtual_bridge": True},
            ),
        )

        menu = await options.async_step_init()

        self.assertIn("cloud_tools", menu["menu_options"])
        self.assertNotIn("shadow_learning", menu["menu_options"])
        tools = await options.async_step_cloud_tools()
        self.assertEqual(
            tools["menu_options"],
            ["proxy_capture", "create_support_package"],
        )

    async def test_shadow_restore_remains_reachable_after_profile_drift(self) -> None:
        options = self._make_options_flow()
        options._config_entry.data.update(
            {
                CONF_CONNECTION_STRATEGY: CONNECTION_STRATEGY_INBOUND,
                "endpoint_control_policy": "integration_managed",
            }
        )
        options._config_entry.runtime_data = types.SimpleNamespace(
            data=types.SimpleNamespace(
                collector=types.SimpleNamespace(collector_virtual_bridge=False),
                values={"shadow_learning_session_status": "restore_failed"},
            ),
        )

        menu = await options.async_step_init()
        tools = await options.async_step_cloud_tools()

        self.assertIn("cloud_tools", menu["menu_options"])
        self.assertIn("shadow_learning", tools["menu_options"])

    async def test_unbound_inverter_keeps_read_only_and_proxy_support_paths(self) -> None:
        options = self._make_options_flow()
        options._config_entry.data.update(
            {
                "collector_pn": "E50000200000000001",
                "detected_model": "",
                "detected_serial": "",
                CONF_CONNECTION_STRATEGY: CONNECTION_STRATEGY_CALLBACK_ON_DEMAND,
                "endpoint_control_policy": "external",
            }
        )
        options._config_entry.runtime_data = types.SimpleNamespace(
            cloud_evidence_provider="smartess",
            smartess_collector_pn="E50000200000000001",
            proxy_capture_overview=types.SimpleNamespace(
                can_start=False,
                can_stop=False,
                critical_phase=False,
                blocking_reason="current_endpoint_unavailable",
            ),
            data=types.SimpleNamespace(
                collector=types.SimpleNamespace(collector_virtual_bridge=False),
                values={"driver_key": "auto"},
            ),
        )

        menu = await options.async_step_init()
        tools = await options.async_step_cloud_tools()
        learning = await options.async_step_shadow_learning()

        self.assertEqual(options._collector_capabilities().collector_kind, "unknown")
        self.assertIn("cloud_tools", menu["menu_options"])
        self.assertEqual(
            tools["menu_options"],
            ["shadow_learning", "proxy_capture", "create_support_package"],
        )
        self.assertEqual(learning["step_id"], "shadow_learning")
        self.assertEqual(
            tuple(_schema_select_options(learning["data_schema"], "learning_method")),
            (
                LEARNING_METHOD_READ_ONLY_EVIDENCE,
                LEARNING_METHOD_ACTIVE_CORRELATION,
            ),
        )

    async def test_unbound_inverter_without_provider_still_gets_read_only_sources(self) -> None:
        options = self._make_options_flow()
        options._config_entry.data.update(
            {
                "collector_pn": "E50000200000000001",
                "detected_model": "",
                "detected_serial": "",
                CONF_CONNECTION_STRATEGY: CONNECTION_STRATEGY_CALLBACK_ON_DEMAND,
                "endpoint_control_policy": "external",
            }
        )
        options._config_entry.runtime_data = types.SimpleNamespace(
            cloud_evidence_provider="",
            smartess_collector_pn="E50000200000000001",
            data=types.SimpleNamespace(
                collector=types.SimpleNamespace(collector_virtual_bridge=False),
                values={"driver_key": "auto"},
            ),
        )

        menu = await options.async_step_init()
        tools = await options.async_step_cloud_tools()
        source = await options.async_step_shadow_learning()

        self.assertIn("cloud_tools", menu["menu_options"])
        self.assertEqual(
            tools["menu_options"],
            ["shadow_learning", "create_support_package"],
        )
        self.assertEqual(source["step_id"], "shadow_learning_source")
        self.assertEqual(
            tuple(_schema_select_options(source["data_schema"], "learning_source")),
            ("dessmonitor", "smartess", "smartclient"),
        )
        self.assertEqual(
            options._shadow_learning_state["wizard_method"],
            LEARNING_METHOD_READ_ONLY_EVIDENCE,
        )

    async def test_ha_only_unbound_inverter_keeps_metadata_read_but_not_active_learning(
        self,
    ) -> None:
        options = self._make_options_flow()
        options._config_entry.data.update(
            {
                "collector_pn": "E50000200000000001",
                "detected_model": "",
                "detected_serial": "",
                CONF_CONNECTION_STRATEGY: CONNECTION_STRATEGY_INBOUND,
                "endpoint_control_policy": "integration_managed",
            }
        )
        options._config_entry.runtime_data = types.SimpleNamespace(
            cloud_evidence_provider="smartess",
            smartess_collector_pn="E50000200000000001",
            data=types.SimpleNamespace(
                collector=types.SimpleNamespace(collector_virtual_bridge=False),
                values={"driver_key": "auto"},
            ),
        )

        menu = await options.async_step_init()
        tools = await options.async_step_cloud_tools()
        source = await options.async_step_shadow_learning()

        self.assertIn("cloud_tools", menu["menu_options"])
        # Proxy remains visible so its page can explain that Cloud + HA is
        # required; active writes are absent from the learning method set.
        self.assertEqual(
            tools["menu_options"],
            ["shadow_learning", "proxy_capture", "create_support_package"],
        )
        self.assertEqual(source["step_id"], "shadow_learning_source")
        self.assertEqual(
            options._shadow_learning_state["wizard_method"],
            LEARNING_METHOD_READ_ONLY_EVIDENCE,
        )

    async def test_options_init_offers_repair_for_degraded_virtual_bridge(self) -> None:
        # Recovery beats capability filtering: a DEGRADED virtual bridge (recovery
        # marker present) still offers the repair FIRST -- the bridge branch must
        # never drop it.
        options = self._make_options_flow()
        options._config_entry.data["connection_strategy_transition_state"] = {
            "kind": "callback_transition_unproven"
        }
        options._config_entry.runtime_data = types.SimpleNamespace(
            data=types.SimpleNamespace(
                collector=types.SimpleNamespace(collector_virtual_bridge=True),
                values={"collector_virtual_bridge": True},
            ),
        )

        result = await options.async_step_init()

        self.assertEqual(result["menu_options"][0], "strategy_transition_repair")
        # The bridge base menu remains (uart shown, shadow learning hidden).
        self.assertIn("collector_uart", result["menu_options"])
        self.assertNotIn("shadow_learning", result["menu_options"])

    async def test_options_init_proven_unloaded_shows_activation_only_menu(self) -> None:
        # A PROVEN-but-unloaded callback config gets a DEDICATED activation-only
        # menu that wins over ALL capability filtering -- even a virtual bridge
        # runtime cannot inject runtime/Wi-Fi/diagnostics or drop the retry.
        options = self._make_options_flow()
        options._config_entry.runtime_data = types.SimpleNamespace(
            data=types.SimpleNamespace(
                collector=types.SimpleNamespace(collector_virtual_bridge=True),
                values={"collector_virtual_bridge": True},
            ),
        )
        options._callback_proven_but_not_loaded = lambda: True

        result = await options.async_step_init()

        self.assertEqual(
            result["menu_options"],
            ["strategy_transition_activation_retry", "strategy_transition_cancel"],
        )
        for absent in (
            "runtime",
            "collector_wifi",
            "diagnostics",
            "collector_uart",
            "shadow_learning",
            "strategy_transition_repair",
        ):
            self.assertNotIn(absent, result["menu_options"])

    async def test_options_collector_wifi_step_renders_current_status(self) -> None:
        options = self._make_options_flow()

        async def refresh_status() -> None:
            options._collector_wifi_current_ssid = "HomeNet"
            options._collector_wifi_network_diagnostics = "1,0,0"
            options._collector_wifi_networks = (
                SmartEssBleWifiNetwork(ssid="HomeNet", signal=98),
                SmartEssBleWifiNetwork(ssid="Other", signal=42),
            )

        options._async_refresh_collector_wifi_status = refresh_status

        result = await options.async_step_collector_wifi()

        self.assertEqual(result["type"], "form")
        self.assertEqual(result["step_id"], "collector_wifi")
        self.assertEqual(result["description_placeholders"]["current_ssid"], "HomeNet")
        self.assertEqual(result["description_placeholders"]["status_updates"], "")
        self.assertNotIn("network_diagnostics", result["description_placeholders"])
        self.assertIn(CONF_WIFI_SSID, result["data_schema"].schema)
        self.assertIn(CONF_WIFI_PASSWORD, result["data_schema"].schema)
        self.assertIn(CONF_COLLECTOR_WIFI_ACTION, result["data_schema"].schema)
        self.assertIn(CONF_CONFIRM_COLLECTOR_WIFI_APPLY, result["data_schema"].schema)

    async def test_options_collector_wifi_step_shows_only_non_empty_status_updates(self) -> None:
        options = self._make_options_flow()
        options._collector_wifi_current_ssid = "HomeNet"
        options._collector_wifi_last_result = "Saved."
        options._collector_wifi_last_error = "collector_timeout"

        result = await options.async_step_collector_wifi(
            {
                CONF_COLLECTOR_WIFI_ACTION: COLLECTOR_WIFI_ACTION_APPLY,
                CONF_WIFI_SSID: "NewWiFi",
                CONF_WIFI_PASSWORD: "Secret123",
            }
        )

        self.assertEqual(result["type"], "form")
        self.assertEqual(
            result["errors"],
            {CONF_CONFIRM_COLLECTOR_WIFI_APPLY: "collector_wifi_apply_not_confirmed"},
        )
        self.assertIn("**Last action:** Saved.", result["description_placeholders"]["status_updates"])
        self.assertIn(
            "**Last error:** collector_timeout",
            result["description_placeholders"]["status_updates"],
        )

    async def test_options_collector_wifi_refresh_keeps_flow_open(self) -> None:
        options = self._make_options_flow()
        apply_mock = AsyncMock()

        async def refresh_status() -> None:
            options._collector_wifi_current_ssid = "HomeNet"

        options._async_refresh_collector_wifi_status = refresh_status
        options._async_apply_collector_wifi_settings = apply_mock

        result = await options.async_step_collector_wifi(
            {
                CONF_COLLECTOR_WIFI_ACTION: COLLECTOR_WIFI_ACTION_REFRESH,
                CONF_WIFI_SSID: "Ignored",
                CONF_WIFI_PASSWORD: "Ignored",
            }
        )

        self.assertEqual(result["type"], "form")
        self.assertEqual(result["errors"], {})
        apply_mock.assert_not_called()

    async def test_options_collector_wifi_apply_preserves_existing_options(self) -> None:
        options = self._make_options_flow()
        options._config_entry.options = {"poll_interval": 15}
        options._async_apply_collector_wifi_settings = AsyncMock()

        result = await options.async_step_collector_wifi(
            {
                CONF_COLLECTOR_WIFI_ACTION: COLLECTOR_WIFI_ACTION_APPLY,
                CONF_WIFI_SSID: "NewWiFi",
                CONF_WIFI_PASSWORD: "Secret123",
                CONF_CONFIRM_COLLECTOR_WIFI_APPLY: True,
            }
        )

        self.assertEqual(result["type"], "create_entry")
        self.assertEqual(result["data"], {"poll_interval": 15})
        options._async_apply_collector_wifi_settings.assert_awaited_once_with(
            ssid="NewWiFi",
            password="Secret123",
        )

    async def test_options_collector_wifi_apply_writes_without_password_readback(self) -> None:
        options = self._make_options_flow()
        writer = AsyncMock(return_value="NewWiFi")
        options._config_entry.runtime_data = types.SimpleNamespace(
            async_set_collector_wifi_credentials=writer
        )

        await options._async_apply_collector_wifi_settings(ssid="NewWiFi", password="Secret123")

        writer.assert_awaited_once_with(
            ssid="NewWiFi",
            password="Secret123",
            ssid_parameter=SET_TARGET_SSID,
            password_parameter=SET_TARGET_PASSWORD,
        )
        self.assertEqual(options._collector_wifi_current_ssid, "NewWiFi")

    async def test_options_collector_uart_step_renders_current_status_for_bridge(self) -> None:
        options = self._make_options_flow()
        options._config_entry.runtime_data = types.SimpleNamespace(
            data=types.SimpleNamespace(
                collector=types.SimpleNamespace(collector_virtual_bridge=True),
                values={"collector_virtual_bridge": True},
            ),
        )

        async def refresh_status() -> None:
            options._collector_uart_current_settings = "2400"
            options._collector_uart_current_baudrate = "2400"

        options._async_refresh_collector_uart_status = refresh_status

        result = await options.async_step_collector_uart()

        self.assertEqual(result["type"], "form")
        self.assertEqual(result["step_id"], "collector_uart")
        self.assertEqual(result["description_placeholders"]["current_uart"], "2400")
        self.assertIn(CONF_COLLECTOR_UART_BAUDRATE, result["data_schema"].schema)
        self.assertIn(CONF_COLLECTOR_UART_ACTION, result["data_schema"].schema)
        self.assertIn(CONF_CONFIRM_COLLECTOR_UART_APPLY, result["data_schema"].schema)

    async def test_options_collector_uart_refresh_reads_parameter_34(self) -> None:
        options = self._make_options_flow()
        options._config_entry.data[CONF_COLLECTOR_IP] = ""
        query = AsyncMock(
            return_value={
                QUERY_HARDWARE_VERSION: "ESP32",
                QUERY_SERIAL_BAUDRATE: "9600,8,1,NONE",
            }
        )
        options._config_entry.runtime_data = types.SimpleNamespace(
            async_query_collector_parameters=query
        )

        await options._async_refresh_collector_uart_status()

        query.assert_awaited_once_with(
            (QUERY_HARDWARE_VERSION, QUERY_SERIAL_BAUDRATE)
        )
        self.assertEqual(options._collector_uart_hardware_version, "ESP32")
        self.assertEqual(options._collector_uart_current_baudrate, "9600")
        self.assertEqual(options._collector_uart_current_settings, "9600,8,1,NONE")

    async def test_options_collector_uart_step_blocks_runtime_change_for_bk72xx(self) -> None:
        options = self._make_options_flow()
        options._config_entry.runtime_data = types.SimpleNamespace(
            data=types.SimpleNamespace(
                collector=types.SimpleNamespace(collector_virtual_bridge=True),
                values={"collector_virtual_bridge": True},
            ),
        )

        async def refresh_status() -> None:
            options._collector_uart_hardware_version = "BK72xx/RTL87xx"
            options._collector_uart_current_settings = "2400"
            options._collector_uart_current_baudrate = "2400"

        options._async_refresh_collector_uart_status = refresh_status

        result = await options.async_step_collector_uart()

        self.assertEqual(result["type"], "form")
        self.assertEqual(result["step_id"], "collector_uart")
        self.assertEqual(result["description_placeholders"]["hardware_version"], "BK72xx/RTL87xx")
        self.assertIn("BK72xx", result["description_placeholders"]["runtime_unavailable_note"])
        self.assertIn(CONF_COLLECTOR_UART_ACTION, result["data_schema"].schema)
        self.assertNotIn(CONF_COLLECTOR_UART_BAUDRATE, result["data_schema"].schema)
        self.assertNotIn(CONF_CONFIRM_COLLECTOR_UART_APPLY, result["data_schema"].schema)

    async def test_options_collector_uart_apply_writes_parameter_34_only(self) -> None:
        options = self._make_options_flow()
        snapshot = types.SimpleNamespace(
            values={
                "collector_virtual_bridge": True,
                "collector_serial_baudrate": "2400,8,1,NONE",
            }
        )
        coordinator = types.SimpleNamespace(
            data=snapshot,
            invalidate_collector_runtime_values=Mock(),
            async_request_refresh=AsyncMock(),
            async_set_collector_uart_baudrate=AsyncMock(
                return_value="9600,8,1,NONE"
            ),
        )
        options._config_entry.runtime_data = coordinator
        options._config_entry.data[CONF_COLLECTOR_IP] = ""

        await options._async_apply_collector_uart_baudrate("9600")

        coordinator.async_set_collector_uart_baudrate.assert_awaited_once_with("9600")
        self.assertEqual(snapshot.values["collector_serial_baudrate"], "2400,8,1,NONE")
        coordinator.invalidate_collector_runtime_values.assert_called_once_with()
        coordinator.async_request_refresh.assert_awaited_once_with()

    async def test_options_collector_uart_apply_refuses_bk72xx_runtime_change(self) -> None:
        options = self._make_options_flow()
        options._collector_uart_hardware_version = "BK72xx/RTL87xx"
        writer = AsyncMock()
        options._config_entry.runtime_data = types.SimpleNamespace(
            async_set_collector_uart_baudrate=writer
        )

        with self.assertRaisesRegex(RuntimeError, "collector_uart_runtime_unavailable"):
            await options._async_apply_collector_uart_baudrate("9600")

        writer.assert_not_called()

    async def test_options_collector_uart_apply_requires_confirmation(self) -> None:
        options = self._make_options_flow()
        options._config_entry.runtime_data = types.SimpleNamespace(
            data=types.SimpleNamespace(
                collector=types.SimpleNamespace(collector_virtual_bridge=True),
                values={"collector_virtual_bridge": True},
            ),
        )
        options._async_apply_collector_uart_baudrate = AsyncMock()

        result = await options.async_step_collector_uart(
            {
                CONF_COLLECTOR_UART_ACTION: COLLECTOR_UART_ACTION_APPLY,
                CONF_COLLECTOR_UART_BAUDRATE: "9600",
            }
        )

        self.assertEqual(result["type"], "form")
        self.assertEqual(
            result["errors"],
            {CONF_CONFIRM_COLLECTOR_UART_APPLY: "collector_uart_apply_not_confirmed"},
        )
        options._async_apply_collector_uart_baudrate.assert_not_called()

    async def test_options_collector_uart_apply_preserves_existing_options(self) -> None:
        options = self._make_options_flow()
        options._config_entry.options = {"poll_interval": 15}
        options._config_entry.runtime_data = types.SimpleNamespace(
            data=types.SimpleNamespace(
                collector=types.SimpleNamespace(collector_virtual_bridge=True),
                values={"collector_virtual_bridge": True},
            ),
        )
        options._async_apply_collector_uart_baudrate = AsyncMock()

        result = await options.async_step_collector_uart(
            {
                CONF_COLLECTOR_UART_ACTION: COLLECTOR_UART_ACTION_APPLY,
                CONF_COLLECTOR_UART_BAUDRATE: "9600",
                CONF_CONFIRM_COLLECTOR_UART_APPLY: True,
            }
        )

        self.assertEqual(result["type"], "create_entry")
        self.assertEqual(result["data"], {"poll_interval": 15})
        options._async_apply_collector_uart_baudrate.assert_awaited_once_with("9600")

    async def test_options_collector_uart_step_returns_init_for_factory_collector(self) -> None:
        options = self._make_options_flow()

        result = await options.async_step_collector_uart()

        self.assertEqual(result["type"], "menu")
        self.assertEqual(result["step_id"], "init")
        self.assertNotIn("collector_uart", result["menu_options"])

    async def test_options_runtime_step_preloads_translation_bundle_via_executor(self) -> None:
        options = self._make_options_flow()

        await options.async_step_runtime()

        self.assertIn(
            "load_translation_bundle",
            [getattr(func, "__name__", "") for func, _args in options.hass.executor_job_calls],
        )

    async def test_options_runtime_step_localizes_control_mode_labels(self) -> None:
        options = self._make_options_flow()
        options.hass.config.language = "ru"

        result = await options.async_step_runtime()

        selector = result["data_schema"].schema["control_mode"]
        labels = [option["label"] for option in selector.config.kwargs["options"]]
        self.assertEqual(labels, ["Авто", "Только чтение", "Полный контроль"])

    async def test_options_runtime_step_serializes_branch_aware_option_payload(self) -> None:
        options = self._make_options_flow()

        form = await options.async_step_runtime()

        self.assertIn(CONF_DRIVER_HINT, form["data_schema"].schema)
        self.assertIn(
            CONF_DRIVER_DETECTION_STRATEGY,
            form["data_schema"].schema,
        )
        self.assertIn("poll_mode", form["data_schema"].schema)
        self.assertIn("poll_interval", form["data_schema"].schema)
        self.assertNotIn(
            CONF_DRIVER_HINT,
            form["data_schema"].schema["connection"].schema,
        )

        result = await options.async_step_runtime(
            {
                CONF_DRIVER_HINT: "modbus_smg",
                CONF_DRIVER_DETECTION_STRATEGY: DRIVER_DETECTION_FULL_SCAN,
                "poll_mode": "manual",
                "poll_interval": 15,
                "control_mode": "full",
                "connection": {
                    "server_ip": "192.168.1.60",
                    "collector_ip": "192.168.1.56",
                    "tcp_port": 8899,
                    "advertised_server_ip": "203.0.113.10",
                    "advertised_tcp_port": "9443",
                    "udp_port": 58899,
                    "discovery_target": "192.168.1.255",
                    "discovery_interval": 4,
                    "heartbeat_interval": 30,
                },
            }
        )

        self.assertEqual(result["type"], "create_entry")
        self.assertEqual(result["data"]["poll_mode"], "manual")
        self.assertEqual(result["data"]["poll_interval"], 15)
        # Changing driver is user intent, not detected identity.  The new
        # Runtime binding provides the temporary interlock without replacing
        # the explicit Full Control choice made in this submission.
        self.assertEqual(result["data"]["control_mode"], "full")
        self.assertEqual(result["data"]["advertised_server_ip"], "203.0.113.10")
        self.assertEqual(result["data"]["advertised_tcp_port"], 9443)
        self.assertEqual(result["data"]["driver_hint"], "modbus_smg")
        self.assertEqual(
            result["data"][CONF_DRIVER_DETECTION_STRATEGY],
            DRIVER_DETECTION_FULL_SCAN,
        )
        self.assertNotIn("connection", result["data"])
        self.assertEqual(options._config_entry.data["detected_driver"], "")
        self.assertEqual(options._config_entry.data["detected_model"], "")
        self.assertEqual(options._config_entry.data["detected_serial"], "")

    async def test_options_runtime_omits_absent_advertised_route_pair(self) -> None:
        options = self._make_options_flow()

        result = await options.async_step_runtime(
            {
                CONF_DRIVER_HINT: "auto",
                CONF_DRIVER_DETECTION_STRATEGY: "first_match",
                "poll_mode": "auto",
                "control_mode": "auto",
                "connection": {
                    "server_ip": "192.168.1.50",
                    "collector_ip": "192.168.1.14",
                    "tcp_port": 8899,
                    "advertised_server_ip": "",
                    "advertised_tcp_port": "",
                    "udp_port": 58899,
                    "discovery_target": "192.168.1.255",
                    "discovery_interval": 4,
                    "heartbeat_interval": 30,
                },
            }
        )

        self.assertEqual(result["type"], "create_entry")
        self.assertNotIn("advertised_server_ip", result["data"])
        self.assertNotIn("advertised_tcp_port", result["data"])

    async def test_runtime_detection_strategy_change_forces_real_reidentification(
        self,
    ) -> None:
        options = self._make_options_flow()
        options._config_entry.data.update(
            {
                "detected_driver": "pi30",
                "detected_model": "PI30 inverter",
                "detected_serial": "SERIAL-1",
                "detection_confidence": "high",
                "control_mode": "full",
            }
        )
        options._config_entry.options.update(
            {
                CONF_DRIVER_HINT: "auto",
                CONF_DRIVER_DETECTION_STRATEGY: "first_match",
                "poll_mode": "auto",
                "poll_interval": 15,
                "control_mode": "full",
            }
        )

        result = await options.async_step_runtime(
            {
                CONF_DRIVER_HINT: "auto",
                CONF_DRIVER_DETECTION_STRATEGY: DRIVER_DETECTION_FULL_SCAN,
                "poll_mode": "auto",
                "control_mode": "full",
                "connection": {
                    "server_ip": "192.168.1.50",
                    "collector_ip": "192.168.1.55",
                    "tcp_port": 8899,
                    "advertised_server_ip": "203.0.113.10",
                    "advertised_tcp_port": 9443,
                    "udp_port": 58899,
                    "discovery_target": "192.168.1.255",
                    "discovery_interval": 4,
                    "heartbeat_interval": 30,
                },
            }
        )

        self.assertEqual(result["type"], "create_entry")
        self.assertEqual(
            result["data"][CONF_DRIVER_DETECTION_STRATEGY],
            DRIVER_DETECTION_FULL_SCAN,
        )
        self.assertEqual(result["data"]["control_mode"], "full")
        self.assertEqual(options._config_entry.data["detected_driver"], "")
        self.assertEqual(options._config_entry.data["detected_model"], "")
        self.assertEqual(options._config_entry.data["detected_serial"], "")
        self.assertEqual(
            options._config_entry.data["detection_confidence"],
            "none",
        )

    async def test_options_runtime_auto_mode_hides_poll_interval_and_preserves_fallback(self) -> None:
        options = self._make_options_flow()
        options._config_entry.options = {"poll_interval": 15, "poll_mode": "auto"}

        form = await options.async_step_runtime()

        self.assertIn("poll_mode", form["data_schema"].schema)
        self.assertNotIn("poll_interval", form["data_schema"].schema)

        result = await options.async_step_runtime(
            {
                "poll_mode": "auto",
                "control_mode": "full",
                "connection": {
                    "server_ip": "192.168.1.60",
                    "collector_ip": "192.168.1.56",
                    "tcp_port": 8899,
                    "advertised_server_ip": "203.0.113.10",
                    "advertised_tcp_port": "9443",
                    "udp_port": 58899,
                    "discovery_target": "192.168.1.255",
                    "discovery_interval": 4,
                    "heartbeat_interval": 30,
                    "driver_hint": "modbus_smg",
                },
            }
        )

        self.assertEqual(result["type"], "create_entry")
        self.assertEqual(result["data"]["poll_mode"], "auto")
        self.assertEqual(result["data"]["poll_interval"], 15)

    async def test_options_runtime_switching_auto_to_manual_requests_interval(self) -> None:
        options = self._make_options_flow()
        options._config_entry.options = {"poll_interval": 15, "poll_mode": "auto"}

        result = await options.async_step_runtime(
            {
                "poll_mode": "manual",
                "control_mode": "full",
                "connection": {
                    "server_ip": "192.168.1.60",
                    "collector_ip": "192.168.1.56",
                    "tcp_port": 8899,
                    "advertised_server_ip": "203.0.113.10",
                    "advertised_tcp_port": "9443",
                    "udp_port": 58899,
                    "discovery_target": "192.168.1.255",
                    "discovery_interval": 4,
                    "heartbeat_interval": 30,
                    "driver_hint": "modbus_smg",
                },
            }
        )

        self.assertEqual(result["type"], "form")
        self.assertEqual(result["step_id"], "runtime_poll_interval")
        self.assertIn("poll_interval", result["data_schema"].schema)

        created = await options.async_step_runtime_poll_interval({"poll_interval": 20})

        self.assertEqual(created["type"], "create_entry")
        self.assertEqual(created["data"]["poll_mode"], "manual")
        self.assertEqual(created["data"]["poll_interval"], 20)

    async def test_diagnostics_menu_exposes_reload_and_capture_actions(self) -> None:
        options = self._make_options_flow()
        workflow = {
            f"support_workflow_{key}": value
            for key, value in build_support_workflow_state(
                has_inverter=True,
                effective_owner_key="modbus_smg",
                effective_owner_name="SMG-family runtime",
                detection_confidence="high",
                profile_source_scope="external",
                schema_source_scope="builtin",
            ).items()
        }

        with tempfile.TemporaryDirectory() as tempdir:
            options.hass.config.config_dir = tempdir
            options._config_entry.runtime_data = types.SimpleNamespace(
                current_driver=None,
                effective_owner_name="SMG-family runtime",
                effective_owner_key="modbus_smg",
                smartess_family_name="SmartESS 0925",
                effective_profile_name="smg_modbus.json",
                effective_register_schema_name="modbus_smg/models/smg_6200.json",
                effective_profile_metadata=None,
                effective_register_schema_metadata=None,
                cloud_evidence_export_available=True,
                smartess_known_family_draft_plan=None,
                smartess_smg_bridge_plan=None,
                data=types.SimpleNamespace(values=workflow),
            )

            result = await options.async_step_diagnostics()

        self.assertEqual(result["type"], "menu")
        self.assertEqual(
            result["menu_options"],
            [
                "create_support_package",
                "diagnostic_commands",
                "reload_local_metadata",
            ],
        )
        self.assertEqual(
            result["description_placeholders"]["support_archive_action_label"],
            "Create support archive",
        )
        self.assertEqual(
            options._tr("options.step.diagnostics.menu_options.reload_local_metadata", ""),
            "Reload local metadata",
        )
        self.assertNotIn("advanced_metadata", result["menu_options"])

    async def test_diagnostics_menu_does_not_depend_on_advanced_mode(self) -> None:
        options = self._make_options_flow()
        options.context = {"show_advanced_options": False}
        workflow = {
            f"support_workflow_{key}": value
            for key, value in build_support_workflow_state(
                has_inverter=True,
                effective_owner_key="modbus_smg",
                effective_owner_name="SMG-family runtime",
                detection_confidence="high",
                profile_source_scope="external",
                schema_source_scope="builtin",
            ).items()
        }
        with tempfile.TemporaryDirectory() as tempdir:
            options.hass.config.config_dir = tempdir
            options._config_entry.runtime_data = types.SimpleNamespace(
                current_driver=None,
                effective_owner_name="SMG-family runtime",
                effective_owner_key="modbus_smg",
                smartess_family_name="SmartESS 0925",
                effective_profile_name="smg_modbus.json",
                effective_register_schema_name="modbus_smg/models/smg_6200.json",
                effective_profile_metadata=None,
                effective_register_schema_metadata=None,
                cloud_evidence_export_available=True,
                smartess_known_family_draft_plan=None,
                smartess_smg_bridge_plan=None,
                data=types.SimpleNamespace(values=workflow),
            )
            result = await options.async_step_diagnostics()
        self.assertEqual(result["type"], "menu")
        self.assertIn("diagnostic_commands", result["menu_options"])
        source = (REPO_ROOT / Path(
            "custom_components/eybond_local/flows/options/diagnostics.py"
        )).read_text(encoding="utf-8")
        self.assertNotIn('getattr(self, "show_advanced_options"', source)

    async def test_diagnostic_commands_step_runs_and_displays_result(self) -> None:
        options = self._make_options_flow()
        calls: list[dict[str, object]] = []

        async def _run_diagnostic_commands(**kwargs):
            calls.append(dict(kwargs))
            return {
                "success": True,
                "output": "[1] read 171\nstatus: ok\ndecimal: 8960\n",
                "results": [],
                "context": {},
                "started_at": "2026-06-19T00:00:00+00:00",
                "finished_at": "2026-06-19T00:00:01+00:00",
                "result_path": "/config/eybond_local/diagnostic_runs/result.json",
                "download_url": (
                    "https://ha.example/api/eybond_local/diagnostic_run/entry-1/"
                    "diagnostic_entry-1_result.share.json?authSig=signed"
                ),
            }

        options._config_entry.runtime_data = types.SimpleNamespace(
            async_run_diagnostic_commands=_run_diagnostic_commands,
        )

        initial = await options.async_step_diagnostic_commands()
        self.assertEqual(initial["type"], "form")
        self.assertEqual(initial["step_id"], "diagnostic_commands")
        commands_selector = initial["data_schema"].schema["diagnostic_commands"]
        self.assertTrue(commands_selector.config.kwargs.get("multiline"))
        self.assertNotIn("diagnostic_result", initial["data_schema"].schema)

        result = await options.async_step_diagnostic_commands(
            {
                "diagnostic_commands": "driver modbus_smg\nread 171\n",
                "diagnostic_stop_on_error": False,
                "diagnostic_publish_download_copy": True,
            }
        )

        self.assertEqual(
            calls,
            [
                {
                    "commands": "driver modbus_smg\nread 171\n",
                    "stop_on_error": False,
                    "confirm_write": False,
                    "publish_download_copy": True,
                }
            ],
        )
        self.assertEqual(result["type"], "form")
        self.assertIn("diagnostic_result", result["data_schema"].schema)
        result_selector = result["data_schema"].schema["diagnostic_result"]
        self.assertTrue(result_selector.config.kwargs.get("multiline"))
        self.assertTrue(result_selector.config.kwargs.get("read_only"))
        self.assertIn(
            "/api/eybond_local/diagnostic_run/entry-1/",
            result["description_placeholders"]["diagnostic_download_markdown"],
        )

    async def test_diagnostic_commands_step_requires_commands(self) -> None:
        options = self._make_options_flow()
        result = await options.async_step_diagnostic_commands(
            {
                "diagnostic_commands": " \n",
                "diagnostic_stop_on_error": True,
            }
        )

        self.assertEqual(
            result["errors"],
            {"diagnostic_commands": "diagnostic_commands_required"},
        )

    async def test_diagnostics_menu_omits_proxy_capture_for_detected_bridge(self) -> None:
        # Item 3: a detected bridge has no upstream provider side, so proxy
        # capture (which has nothing to capture) is omitted from diagnostics.
        options = self._make_options_flow()
        options._config_entry.runtime_data = types.SimpleNamespace(
            data=types.SimpleNamespace(
                collector=types.SimpleNamespace(collector_virtual_bridge=True),
                values={"collector_virtual_bridge": True},
            ),
        )

        with tempfile.TemporaryDirectory() as tempdir:
            options.hass.config.config_dir = tempdir
            menu_options = options._diagnostics_menu_options("create_support_package")

        self.assertNotIn("proxy_capture", menu_options)
        self.assertIn("create_support_package", menu_options)

    async def test_cloud_tools_are_exposed_from_main_menu_not_diagnostics(self) -> None:
        options = self._make_options_flow()
        options._config_entry.data.update(
            {
                CONF_CONNECTION_STRATEGY: CONNECTION_STRATEGY_CALLBACK_ON_DEMAND,
                "endpoint_control_policy": "external",
            }
        )
        options._config_entry.runtime_data = types.SimpleNamespace(
            proxy_capture_overview=types.SimpleNamespace(
                can_start=True,
                can_stop=False,
                critical_phase=False,
            ),
            data=types.SimpleNamespace(
                collector=types.SimpleNamespace(collector_virtual_bridge=False),
                values={},
            ),
        )

        with tempfile.TemporaryDirectory() as tempdir:
            options.hass.config.config_dir = tempdir
            menu_options = options._diagnostics_menu_options("create_support_package")
        main_menu = await options.async_step_init()

        self.assertNotIn("proxy_capture", menu_options)
        self.assertIn("cloud_tools", main_menu["menu_options"])
        self.assertNotIn("proxy_capture", main_menu["menu_options"])

    async def test_diagnostics_menu_hides_proxy_capture_in_callback_profile(self) -> None:
        options = self._make_options_flow()
        options._config_entry.data.update(
            {
                CONF_CONNECTION_STRATEGY: CONNECTION_STRATEGY_CALLBACK_ON_DEMAND,
                "endpoint_control_policy": "external",
            }
        )
        options._config_entry.runtime_data = types.SimpleNamespace(
            data=types.SimpleNamespace(
                collector=types.SimpleNamespace(collector_virtual_bridge=False),
                values={},
            ),
        )

        with tempfile.TemporaryDirectory() as tempdir:
            options.hass.config.config_dir = tempdir
            menu_options = options._diagnostics_menu_options(
                "create_support_package"
            )

        self.assertNotIn("proxy_capture", menu_options)

    async def test_active_proxy_remains_visible_after_profile_drift(self) -> None:
        options = self._make_options_flow()
        options._config_entry.data.update(
            {
                CONF_CONNECTION_STRATEGY: CONNECTION_STRATEGY_CALLBACK_ON_DEMAND,
                "endpoint_control_policy": "external",
            }
        )
        options._config_entry.runtime_data = types.SimpleNamespace(
            proxy_capture_overview=types.SimpleNamespace(
                can_stop=True,
                critical_phase=False,
            ),
            data=types.SimpleNamespace(
                collector=types.SimpleNamespace(collector_virtual_bridge=False),
                values={},
            ),
        )

        menu = await options.async_step_init()

        self.assertIn("cloud_tools", menu["menu_options"])

    async def test_options_runtime_step_hides_operation_mode_selector_for_bridge(self) -> None:
        # The polling form contains no connection profile control for any
        # collector, including a bridge.
        options = self._make_options_flow()
        options._config_entry.runtime_data = types.SimpleNamespace(
            data=types.SimpleNamespace(
                collector=types.SimpleNamespace(collector_virtual_bridge=True),
                values={"collector_virtual_bridge": True},
            ),
        )

        result = await options.async_step_runtime()

        self.assertEqual(result["type"], "form")
        self.assertNotIn(CONF_COLLECTOR_OPERATION_MODE, result["data_schema"].schema)
        self.assertNotIn(CONF_CONNECTION_STRATEGY, result["data_schema"].schema)
        self.assertEqual(
            result["description_placeholders"]["collector_connection_note"], ""
        )

    async def test_options_runtime_step_hides_operation_mode_selector_for_bridge_entry_data(self) -> None:
        options = self._make_options_flow()
        options._config_entry.data = {
            **dict(options._config_entry.data),
            "collector_virtual_bridge": True,
        }
        options._config_entry.runtime_data = None

        result = await options.async_step_runtime()

        self.assertEqual(result["type"], "form")
        self.assertNotIn(CONF_COLLECTOR_OPERATION_MODE, result["data_schema"].schema)
        self.assertNotIn(CONF_CONNECTION_STRATEGY, result["data_schema"].schema)
        self.assertEqual(
            result["description_placeholders"]["collector_connection_note"], ""
        )

    async def test_connection_profile_has_its_own_options_step(self) -> None:
        options = self._make_options_flow()
        options._config_entry.runtime_data = types.SimpleNamespace(
            data=types.SimpleNamespace(
                collector=types.SimpleNamespace(collector_virtual_bridge=False),
                values={},
            ),
        )

        runtime = await options.async_step_runtime()
        connection = await options.async_step_connection()

        self.assertEqual(runtime["type"], "form")
        self.assertNotIn(CONF_CONNECTION_STRATEGY, runtime["data_schema"].schema)
        self.assertNotIn(CONF_COLLECTOR_OPERATION_MODE, runtime["data_schema"].schema)
        self.assertEqual(connection["type"], "form")
        self.assertEqual(connection["step_id"], "connection")
        self.assertIn(CONF_CONNECTION_STRATEGY, connection["data_schema"].schema)
        self.assertIn(
            connection["description_placeholders"]["current_profile"],
            {"Cloud + Home Assistant", "Home Assistant only", "Custom configuration"},
        )

    async def test_options_runtime_step_forces_inbound_for_bridge_on_submit(self) -> None:
        # Phase 4: a bridge dials Home Assistant on its own -> inbound. The
        # strategy selector is hidden for it and inbound is persisted.
        options = self._make_options_flow()
        options._config_entry.options = {CONF_PROXY_ENABLED: True}
        options._config_entry.runtime_data = types.SimpleNamespace(
            data=types.SimpleNamespace(
                collector=types.SimpleNamespace(collector_virtual_bridge=True),
                values={"collector_virtual_bridge": True},
            ),
        )

        result = await options.async_step_runtime(
            {
                "poll_interval": 15,
                "control_mode": "auto",
                "connection": {
                    "server_ip": "192.168.1.50",
                    "collector_ip": "192.168.1.55",
                    "tcp_port": 8899,
                    "udp_port": 58899,
                    "discovery_target": "192.168.1.255",
                    "discovery_interval": 3,
                    "heartbeat_interval": 60,
                    "driver_hint": "auto",
                },
            }
        )

        self.assertEqual(result["type"], "create_entry")
        # Canonical (v4): the strategy is committed to entry.DATA, never options.
        self.assertEqual(
            options._config_entry.data[CONF_CONNECTION_STRATEGY],
            CONNECTION_STRATEGY_INBOUND,
        )
        self.assertNotIn(CONF_CONNECTION_STRATEGY, result["data"])
        # Capability-gated proxy must fail closed instead of carrying a stale
        # True from older options/capability snapshots.
        self.assertFalse(result["data"][CONF_PROXY_ENABLED])

    async def test_options_runtime_step_hides_retired_proxy_toggle(self) -> None:
        # The steady cloud-proxy flag never had a runtime consumer. Do not expose
        # it for either factory collectors or community bridges.
        proxy_capable = self._make_options_flow()
        proxy_capable._config_entry.runtime_data = types.SimpleNamespace(
            data=types.SimpleNamespace(collector=None, values={}),
        )
        proxy_result = await proxy_capable.async_step_runtime()
        self.assertEqual(proxy_result["type"], "form")
        self.assertNotIn(CONF_PROXY_ENABLED, proxy_result["data_schema"].schema)

        bridge = self._make_options_flow()
        bridge._config_entry.runtime_data = types.SimpleNamespace(
            data=types.SimpleNamespace(
                collector=types.SimpleNamespace(collector_virtual_bridge=True),
                values={"collector_virtual_bridge": True},
            ),
        )
        bridge_result = await bridge.async_step_runtime()
        self.assertEqual(bridge_result["type"], "form")
        self.assertNotIn(CONF_PROXY_ENABLED, bridge_result["data_schema"].schema)

    async def test_connection_step_routes_changed_profile_to_transition(self) -> None:
        # A changed product profile is still executed by the existing verified
        # strategy-transition authority. The new UX step is not a second writer.
        options = self._make_options_flow()
        options._config_entry.options = {CONF_PROXY_ENABLED: True}
        options._config_entry.runtime_data = types.SimpleNamespace(
            data=types.SimpleNamespace(
                collector=types.SimpleNamespace(collector_virtual_bridge=False),
                values={},
            ),
        )

        result = await options.async_step_connection(
            {CONF_CONNECTION_STRATEGY: CONNECTION_STRATEGY_CALLBACK_ON_DEMAND}
        )

        # Routed to the explicit confirmation form; NOTHING was persisted.
        self.assertEqual(result["type"], "form")
        self.assertEqual(result["step_id"], "strategy_transition")
        self.assertNotIn(CONF_CONNECTION_STRATEGY, options._config_entry.options)
        self.assertNotEqual(
            options._config_entry.data.get(CONF_CONNECTION_STRATEGY),
            CONNECTION_STRATEGY_CALLBACK_ON_DEMAND,
        )
        self.assertEqual(options.hass.config_entries.updates, [])
        self.assertEqual(
            options._transition_target_strategy,
            CONNECTION_STRATEGY_CALLBACK_ON_DEMAND,
        )
        self.assertEqual(options._transition_options_payload, {})

    async def test_custom_profile_same_strategy_does_not_silently_close(self) -> None:
        options = self._make_options_flow()
        options._config_entry.data = {
            **dict(options._config_entry.data),
            CONF_CONNECTION_STRATEGY: CONNECTION_STRATEGY_INBOUND,
            "endpoint_control_policy": "external",
        }
        options._config_entry.runtime_data = types.SimpleNamespace(
            data=types.SimpleNamespace(
                collector=types.SimpleNamespace(collector_virtual_bridge=False),
                values={},
            ),
        )

        result = await options.async_step_connection(
            {CONF_CONNECTION_STRATEGY: CONNECTION_STRATEGY_INBOUND}
        )

        self.assertEqual(result["type"], "form")
        self.assertEqual(result["step_id"], "connection")
        self.assertEqual(result["errors"], {"base": "operating_profile_inconsistent"})
        self.assertEqual(options.hass.config_entries.updates, [])
        self.assertEqual(options._transition_target_strategy, "")

    async def test_runtime_step_ignores_stale_posted_strategy(self) -> None:
        # A cached old runtime form cannot bypass the dedicated profile step.
        unchanged = self._make_options_flow()
        unchanged._config_entry.options = {CONF_PROXY_ENABLED: True}
        unchanged._config_entry.runtime_data = types.SimpleNamespace(
            data=types.SimpleNamespace(
                collector=types.SimpleNamespace(collector_virtual_bridge=False),
                values={},
            ),
        )
        plain = await unchanged.async_step_runtime(
            {
                "poll_interval": 15,
                "control_mode": "auto",
                "connection_strategy": CONNECTION_STRATEGY_CALLBACK_ON_DEMAND,
                "connection": {
                    "server_ip": "192.168.1.50",
                    "collector_ip": "192.168.1.55",
                    "tcp_port": 8899,
                    "udp_port": 58899,
                    "discovery_target": "192.168.1.255",
                    "discovery_interval": 3,
                    "heartbeat_interval": 60,
                    "driver_hint": "auto",
                },
            }
        )
        self.assertEqual(plain["type"], "create_entry")
        self.assertNotIn(CONF_CONNECTION_STRATEGY, plain["data"])
        self.assertNotIn(CONF_CONNECTION_STRATEGY, unchanged._config_entry.options)
        self.assertFalse(plain["data"][CONF_PROXY_ENABLED])
        # CP2A: the runtime options commit no longer writes a collector operation
        # mode shadow into the options. The mode is a read-only projection of the
        # canonical connection strategy.
        self.assertNotIn(CONF_COLLECTOR_OPERATION_MODE, plain["data"])
        updates = unchanged.hass.config_entries.updates
        self.assertEqual(len(updates), 1)
        self.assertIn("data", updates[0])
        self.assertIn("options", updates[0])
        self.assertEqual(unchanged._transition_target_strategy, "")

    async def test_proxy_capture_step_shows_planner_status(self) -> None:
        options = self._make_options_flow()

        with tempfile.TemporaryDirectory() as tempdir:
            options.hass.config.config_dir = tempdir
            options._config_entry.runtime_data = types.SimpleNamespace(
                proxy_capture_overview=_proxy_overview(can_start=True, can_stop=False),
                effective_owner_name="SMG-family runtime",
                effective_owner_key="modbus_smg",
                smartess_family_name="SmartESS 0925",
                effective_profile_name="smg_modbus.json",
                effective_register_schema_name="modbus_smg/models/smg_6200.json",
                effective_profile_metadata=None,
                effective_register_schema_metadata=None,
                latest_proxy_trace_path="/config/eybond_local/proxy_traces/session.jsonl",
                latest_proxy_trace_manifest_path="/config/eybond_local/proxy_traces/session.json",
                data=types.SimpleNamespace(
                    values={
                        "proxy_capture_status_label": "Ready",
                        "proxy_capture_summary": "Collector proxy capture is ready.",
                        "proxy_capture_blocking_reason": "",
                        "proxy_capture_current_endpoint": "collector-cloud.smartess.example,18899,TCP",
                        "proxy_capture_target_endpoint": "192.168.1.50,18899,TCP",
                        "proxy_capture_masked_endpoint": "collector-cloud.smartess.example,18899,TCP",
                        "proxy_capture_redirect_required": True,
                        "proxy_capture_can_stop": False,
                        "proxy_capture_status": "ready",
                        "proxy_trace_path": "/config/eybond_local/proxy_traces/session.jsonl",
                        "proxy_trace_manifest_path": "/config/eybond_local/proxy_traces/session.json",
                        "proxy_trace_line_count": 7,
                        "proxy_trace_kind_summary": "chunk=4, frame=2, masked_endpoint_response=1",
                        "proxy_trace_recent_kinds": "chunk -> frame -> masked_endpoint_response",
                        "proxy_trace_recent_events": "2026-04-28T12:00:03Z cloud_to_collector: masked AT+CLDSRVHOST1 response as collector-cloud.smartess.example,18899,TCP",
                        "proxy_trace_last_timestamp": "2026-04-28T12:00:03Z",
                    }
                ),
            )

            result = await options.async_step_proxy_capture()

        self.assertEqual(result["step_id"], "proxy_capture")
        self.assertEqual(result["type"], "form")
        self.assertEqual(
            list(result["data_schema"].schema.keys())[:2],
            ["proxy_capture_live_log_view", "proxy_capture_action"],
        )
        self.assertEqual(
            list(result["data_schema"].schema.keys()),
            [
                "proxy_capture_live_log_view",
                "proxy_capture_action",
                CONF_PROXY_CAPTURE_DURATION_MINUTES,
            ],
        )
        self.assertIn("proxy_capture_action", result["data_schema"].schema)
        self.assertIn("proxy_capture_live_log_view", result["data_schema"].schema)
        self.assertTrue(
            result["data_schema"].schema["proxy_capture_live_log_view"].config.kwargs.get("read_only")
        )
        self.assertIn("Collector proxy capture is ready.", result["description_placeholders"]["proxy_capture_summary"])
        self.assertEqual(result["description_placeholders"]["proxy_trace_line_count"], "7")
        self.assertEqual(
            result["description_placeholders"]["proxy_trace_recent_kinds"],
            "chunk -> frame -> masked_endpoint_response",
        )
        self.assertIn("The live log is empty.", result["description_placeholders"]["proxy_capture_live_log"])
        self.assertIn(
            "accept collector traffic on the proxy endpoint",
            result["description_placeholders"]["proxy_capture_user_plan"],
        )
        self.assertEqual(result["description_placeholders"]["proxy_capture_saved_result_section"], "")

    async def test_proxy_capture_deep_link_keeps_blocked_status_and_saved_result_reachable(
        self,
    ) -> None:
        options = self._make_options_flow()
        options._config_entry.runtime_data = types.SimpleNamespace(
            proxy_capture_overview=types.SimpleNamespace(
                can_start=False,
                can_stop=False,
                critical_phase=False,
                blocking_reason="collector_not_connected",
            ),
            latest_proxy_trace_path="/config/eybond_local/proxy_traces/session.jsonl",
            latest_proxy_trace_manifest_path="/config/eybond_local/proxy_traces/session.json",
            data=types.SimpleNamespace(
                collector=None,
                values={
                    "proxy_capture_status": "blocked",
                    "proxy_capture_blocking_reason": "collector_not_connected",
                },
            ),
        )

        with patch.object(
            options,
            "_diagnostics_placeholders",
            return_value={
                "proxy_capture_live_log": "",
                "proxy_capture_status": "blocked",
                "proxy_capture_blocking_reason": "collector_not_connected",
                "proxy_trace_manifest_download_url": (
                    "/api/eybond_local/proxy_capture/entry/session.zip?authSig=signed"
                ),
            },
        ):
            result = await options.async_step_proxy_capture()

        self.assertEqual(result["type"], "form")
        self.assertEqual(result["step_id"], "proxy_capture")
        self.assertEqual(
            [
                option["value"]
                for option in result["data_schema"].schema[
                    "proxy_capture_action"
                ].config.kwargs["options"]
            ],
            ["refresh"],
        )
        self.assertIn(
            "/api/eybond_local/proxy_capture/",
            result["description_placeholders"][
                "proxy_trace_manifest_download_url"
            ],
        )

    async def test_proxy_capture_disconnected_offers_explicit_live_preflight(self) -> None:
        options = self._make_options_flow()
        overview = types.SimpleNamespace(
            can_start=False, can_stop=False, critical_phase=False,
            can_reconnect_for_start=True, redirect_required=True,
            blocking_reason="collector_not_connected",
        )
        calls = []

        async def _start(**kwargs):
            calls.append(kwargs)

        coordinator = types.SimpleNamespace(
            proxy_capture_overview=overview,
            async_start_proxy_capture=_start,
            data=types.SimpleNamespace(values={}),
        )
        options._config_entry.runtime_data = coordinator
        choices = options._proxy_capture_action_options(coordinator)
        self.assertEqual([item["value"] for item in choices], ["start", "refresh"])
        self.assertEqual(choices[0]["label"], "Reconnect and start capture")
        # Disconnected state must not default to an endpoint-changing operation.
        self.assertEqual(options._default_proxy_capture_action(coordinator, choices), "refresh")

        with patch.object(options, "_support_acquisition_readiness",
                          return_value=types.SimpleNamespace(
                              proxy_capture=types.SimpleNamespace(visible=True))), \
             patch.object(options, "_diagnostics_placeholders", return_value={}):
            await options.async_step_proxy_capture()
            self.assertEqual(calls, [])
            await options.async_step_proxy_capture({"proxy_capture_action": "start"})

        self.assertEqual(calls, [{
            "anonymized": True,
            "confirm_redirect": True,
            "duration_minutes": DEFAULT_PROXY_CAPTURE_DURATION_MINUTES,
        }])
        plan = options._proxy_capture_user_plan({
            "proxy_capture_can_reconnect_for_start": True,
            "proxy_capture_blocking_reason": "collector_not_connected",
        })
        self.assertIn("read its current server address", plan)
        self.assertIn("temporarily redirect", plan)
        self.assertIn("address will not be changed", plan)

    async def test_show_proxy_capture_status_step_renders_current_status(self) -> None:
        options = self._make_options_flow()

        with tempfile.TemporaryDirectory() as tempdir:
            options.hass.config.config_dir = tempdir
            options._config_entry.runtime_data = types.SimpleNamespace(
                proxy_capture_overview=_proxy_overview(can_start=True, can_stop=False),
                effective_owner_name="SMG-family runtime",
                effective_owner_key="modbus_smg",
                smartess_family_name="SmartESS 0925",
                effective_profile_name="smg_modbus.json",
                effective_register_schema_name="modbus_smg/models/smg_6200.json",
                effective_profile_metadata=None,
                effective_register_schema_metadata=None,
                latest_proxy_trace_path="/config/eybond_local/proxy_traces/session.jsonl",
                latest_proxy_trace_manifest_path="/config/eybond_local/proxy_traces/session.json",
                data=types.SimpleNamespace(
                    values={
                        "proxy_capture_status_label": "Ready",
                        "proxy_capture_summary": "Collector proxy capture is ready.",
                        "proxy_capture_blocking_reason": "",
                        "proxy_capture_current_endpoint": "collector-cloud.smartess.example,18899,TCP",
                        "proxy_capture_target_endpoint": "192.168.1.50,18899,TCP",
                        "proxy_capture_masked_endpoint": "collector-cloud.smartess.example,18899,TCP",
                        "proxy_capture_redirect_required": True,
                        "proxy_capture_can_stop": False,
                        "proxy_capture_status": "ready",
                        "proxy_trace_path": "/config/eybond_local/proxy_traces/session.jsonl",
                        "proxy_trace_manifest_path": "/config/eybond_local/proxy_traces/session.json",
                        "proxy_trace_line_count": 7,
                        "proxy_trace_kind_summary": "chunk=4, frame=2, masked_endpoint_response=1",
                        "proxy_trace_recent_kinds": "chunk -> frame -> masked_endpoint_response",
                        "proxy_trace_recent_events": "2026-04-28T12:00:03Z cloud_to_collector: masked AT+CLDSRVHOST1 response as collector-cloud.smartess.example,18899,TCP",
                        "proxy_trace_last_timestamp": "2026-04-28T12:00:03Z",
                    }
                ),
            )

            result = await options.async_step_proxy_capture()

        self.assertEqual(result["step_id"], "proxy_capture")
        self.assertEqual(result["type"], "form")
        self.assertEqual(
            result["description_placeholders"]["proxy_capture_current_endpoint"],
            "collector-cloud.smartess.example,18899,TCP",
        )
        self.assertEqual(result["description_placeholders"]["proxy_trace_line_count"], "7")
        self.assertEqual(
            result["description_placeholders"]["proxy_trace_recent_kinds"],
            "chunk -> frame -> masked_endpoint_response",
        )
        self.assertIn("The live log is empty.", result["description_placeholders"]["proxy_capture_live_log"])
        self.assertIn(
            "accept collector traffic on the proxy endpoint",
            result["description_placeholders"]["proxy_capture_user_plan"],
        )

    async def test_proxy_capture_prefers_full_live_log_and_relative_download_url(self) -> None:
        options = self._make_options_flow()

        with tempfile.TemporaryDirectory() as tempdir:
            options.hass.config.config_dir = tempdir
            options._config_entry.runtime_data = types.SimpleNamespace(
                proxy_capture_overview=_proxy_overview(
                    status="running", status_label="Running", can_start=False, can_stop=True,
                ),
                effective_owner_name="SMG-family runtime",
                effective_owner_key="modbus_smg",
                smartess_family_name="SmartESS 0925",
                effective_profile_name="smg_modbus.json",
                effective_register_schema_name="modbus_smg/models/smg_6200.json",
                effective_profile_metadata=None,
                effective_register_schema_metadata=None,
                latest_proxy_trace_path="/config/eybond_local/proxy_traces/session.jsonl",
                latest_proxy_trace_manifest_path="/config/eybond_local/proxy_traces/session.json",
                data=types.SimpleNamespace(
                    values={
                        "proxy_capture_status_label": "Ready",
                        "proxy_capture_summary": "Collector proxy capture is ready.",
                        "proxy_capture_blocking_reason": "",
                        "proxy_capture_current_endpoint": "collector-cloud.smartess.example,18899,TCP",
                        "proxy_capture_target_endpoint": "192.168.1.50,18899,TCP",
                        "proxy_capture_masked_endpoint": "collector-cloud.smartess.example,18899,TCP",
                        "proxy_capture_redirect_required": True,
                        "proxy_capture_can_stop": True,
                        "proxy_capture_status": "running",
                        "proxy_trace_path": "/config/eybond_local/proxy_traces/session.jsonl",
                        "proxy_trace_manifest_path": "/config/eybond_local/proxy_traces/session.json",
                        "proxy_trace_saved_result_path": "/config/eybond_local/proxy_traces/session.zip",
                        "proxy_trace_saved_result_download_url": "/local/eybond_local/proxy_traces/session.zip",
                        "proxy_trace_line_count": 7,
                        "proxy_trace_kind_summary": "chunk=4, frame=2, masked_endpoint_response=1",
                        "proxy_trace_recent_kinds": "chunk -> frame -> masked_endpoint_response",
                        "proxy_trace_recent_events": "recent only",
                        "proxy_trace_live_log": "line one\nline two",
                        "proxy_trace_last_timestamp": "2026-04-28T12:00:03Z",
                    }
                ),
            )

            result = await options.async_step_proxy_capture()

        self.assertEqual(result["description_placeholders"]["proxy_capture_live_log"], "line one\nline two")
        self.assertEqual(result["description_placeholders"]["proxy_capture_saved_result_section"], "")

    async def test_proxy_capture_running_plan_surfaces_safety_lease_deadline(self) -> None:
        options = self._make_options_flow()
        options.hass.config.time_zone = "Europe/Kyiv"

        with tempfile.TemporaryDirectory() as tempdir:
            options.hass.config.config_dir = tempdir
            options._config_entry.runtime_data = types.SimpleNamespace(
                proxy_capture_overview=_proxy_overview(
                    status="running", status_label="Running", can_start=False, can_stop=True,
                ),
                effective_owner_name="SMG-family runtime",
                effective_owner_key="modbus_smg",
                smartess_family_name="SmartESS 0925",
                effective_profile_name="smg_modbus.json",
                effective_register_schema_name="modbus_smg/models/smg_6200.json",
                effective_profile_metadata=None,
                effective_register_schema_metadata=None,
                latest_proxy_trace_path="/config/eybond_local/proxy_traces/session.jsonl",
                latest_proxy_trace_manifest_path="/config/eybond_local/proxy_traces/session.json",
                data=types.SimpleNamespace(
                    values={
                        "proxy_capture_status_label": "Running",
                        "proxy_capture_summary": "Collector proxy capture is active.",
                        "proxy_capture_blocking_reason": "",
                        "proxy_capture_current_endpoint": "192.168.1.50,18899,TCP",
                        "proxy_capture_target_endpoint": "192.168.1.50,18899,TCP",
                        "proxy_capture_masked_endpoint": "collector-cloud.smartess.example,18899,TCP",
                        "proxy_capture_redirect_required": True,
                        "proxy_capture_can_stop": True,
                        "proxy_capture_status": "running",
                        "proxy_capture_session_expires_at": "2026-04-29T12:10:00+00:00",
                    }
                ),
            )

            result = await options.async_step_proxy_capture()

        self.assertIn(
            "29.04.2026 15:10 EEST",
            result["description_placeholders"]["proxy_capture_user_plan"],
        )
        self.assertNotIn(
            "2026-04-29T12:10:00+00:00",
            result["description_placeholders"]["proxy_capture_user_plan"],
        )
        self.assertNotIn(
            "29.04.2026 12:10 UTC",
            result["description_placeholders"]["proxy_capture_user_plan"],
        )
        self.assertNotIn(
            "lease",
            result["description_placeholders"]["proxy_capture_user_plan"].lower(),
        )

    async def test_proxy_capture_shows_saved_zip_when_session_is_finished(self) -> None:
        options = self._make_options_flow()

        with tempfile.TemporaryDirectory() as tempdir:
            options.hass.config.config_dir = tempdir
            options._config_entry.runtime_data = types.SimpleNamespace(
                proxy_capture_overview=_proxy_overview(can_start=True, can_stop=False),
                effective_owner_name="SMG-family runtime",
                effective_owner_key="modbus_smg",
                smartess_family_name="SmartESS 0925",
                effective_profile_name="smg_modbus.json",
                effective_register_schema_name="modbus_smg/models/smg_6200.json",
                effective_profile_metadata=None,
                effective_register_schema_metadata=None,
                latest_proxy_trace_path="/config/eybond_local/proxy_traces/session.jsonl",
                latest_proxy_trace_manifest_path="/config/eybond_local/proxy_traces/session.json",
                data=types.SimpleNamespace(
                    values={
                        "proxy_capture_status_label": "Ready",
                        "proxy_capture_summary": "Collector proxy capture is ready.",
                        "proxy_capture_status": "ready",
                        "proxy_trace_saved_result_path": "/config/eybond_local/proxy_traces/session.zip",
                        "proxy_trace_saved_result_download_url": "http://203.0.113.7:8123/local/eybond_local/proxy_traces/session.zip",
                    }
                ),
            )

            with patch.object(
                options_proxy_module,
                "sign_proxy_capture_download_url",
                return_value=(
                    "http://203.0.113.7:8123/api/eybond_local/proxy_capture/"
                    "entry-options/session.zip?authSig=fresh"
                ),
            ) as sign_mock:
                result = await options.async_step_proxy_capture()

        self.assertIn(
            "](http://203.0.113.7:8123/api/eybond_local/proxy_capture/"
            "entry-options/session.zip?authSig=fresh)",
            result["description_placeholders"]["proxy_capture_saved_result_section"],
        )
        sign_mock.assert_called_once_with(
            options.hass,
            "entry-options",
            "session.zip",
        )
        self.assertIn(
            "previous capture is complete",
            result["description_placeholders"]["proxy_capture_user_plan"].lower(),
        )
        self.assertNotIn(
            "/config/eybond_local/proxy_traces/session.zip",
            result["description_placeholders"]["proxy_capture_saved_result_section"],
        )

    def test_proxy_capture_form_mints_a_fresh_signed_url_on_each_render(self) -> None:
        options = self._make_options_flow()
        values = {
            "proxy_trace_saved_result_path": (
                "/config/eybond_local/proxy_traces/session.zip"
            ),
            "proxy_trace_saved_result_download_url": (
                "/api/eybond_local/proxy_capture/entry-options/session.zip"
                "?authSig=expired"
            ),
        }
        fresh_urls = (
            "/api/eybond_local/proxy_capture/entry-options/session.zip?authSig=fresh-1",
            "/api/eybond_local/proxy_capture/entry-options/session.zip?authSig=fresh-2",
        )
        with patch.object(
            options_proxy_module,
            "sign_proxy_capture_download_url",
            side_effect=fresh_urls,
        ) as sign_mock:
            first = options._fresh_proxy_capture_download_url(values)
            second = options._fresh_proxy_capture_download_url(values)

        self.assertEqual((first, second), fresh_urls)
        self.assertNotIn("expired", first + second)
        self.assertEqual(sign_mock.call_count, 2)

    async def test_start_proxy_capture_step_invokes_coordinator(self) -> None:
        options = self._make_options_flow()

        async def _start_proxy_capture(**kwargs):
            self.assertEqual(
                kwargs,
                {
                    "anonymized": True,
                    "confirm_redirect": False,
                    "duration_minutes": DEFAULT_PROXY_CAPTURE_DURATION_MINUTES,
                },
            )
            return {
                "status": "running",
                "trace_path": "/config/eybond_local/proxy_traces/session.jsonl",
            }

        with tempfile.TemporaryDirectory() as tempdir:
            options.hass.config.config_dir = tempdir
            options._config_entry.runtime_data = types.SimpleNamespace(
                proxy_capture_overview=_proxy_overview(can_start=True, can_stop=False),
                async_start_proxy_capture=_start_proxy_capture,
                effective_owner_name="SMG-family runtime",
                effective_owner_key="modbus_smg",
                smartess_family_name="SmartESS 0925",
                effective_profile_name="smg_modbus.json",
                effective_register_schema_name="modbus_smg/models/smg_6200.json",
                effective_profile_metadata=None,
                effective_register_schema_metadata=None,
                latest_proxy_trace_path="/config/eybond_local/proxy_traces/session.jsonl",
                latest_proxy_trace_manifest_path="",
                data=types.SimpleNamespace(values={}),
            )

            result = await options.async_step_proxy_capture({"proxy_capture_action": "start"})

        self.assertEqual(result["step_id"], "proxy_capture")
        self.assertEqual(result["type"], "form")
        self.assertEqual(result["description_placeholders"]["proxy_capture_action_result"], "Capture started.")

    async def test_start_proxy_capture_step_auto_confirms_redirect_when_required(self) -> None:
        options = self._make_options_flow()

        async def _start_proxy_capture(**kwargs):
            self.assertEqual(
                kwargs,
                {
                    "anonymized": True,
                    "confirm_redirect": True,
                    "duration_minutes": DEFAULT_PROXY_CAPTURE_DURATION_MINUTES,
                },
            )
            return {
                "status": "running",
                "trace_path": "/config/eybond_local/proxy_traces/session.jsonl",
            }

        with tempfile.TemporaryDirectory() as tempdir:
            options.hass.config.config_dir = tempdir
            options._config_entry.runtime_data = types.SimpleNamespace(
                proxy_capture_overview=_proxy_overview(can_start=True, can_stop=False, redirect_required=True),
                async_start_proxy_capture=_start_proxy_capture,
                effective_owner_name="SMG-family runtime",
                effective_owner_key="modbus_smg",
                smartess_family_name="SmartESS 0925",
                effective_profile_name="smg_modbus.json",
                effective_register_schema_name="modbus_smg/models/smg_6200.json",
                effective_profile_metadata=None,
                effective_register_schema_metadata=None,
                latest_proxy_trace_path="/config/eybond_local/proxy_traces/session.jsonl",
                latest_proxy_trace_manifest_path="",
                data=types.SimpleNamespace(values={}),
            )

            result = await options.async_step_proxy_capture({"proxy_capture_action": "start"})

        self.assertEqual(result["step_id"], "proxy_capture")
        self.assertEqual(result["description_placeholders"]["proxy_capture_action_result"], "Capture started.")

    async def test_stop_proxy_capture_step_invokes_coordinator(self) -> None:
        options = self._make_options_flow()

        async def _stop_proxy_capture():
            return {
                "status": "stopped",
                "trace_path": "/config/eybond_local/proxy_traces/session.jsonl",
                "manifest_path": "/config/eybond_local/proxy_traces/session.json",
                "saved_result_path": "/config/eybond_local/proxy_traces/session.zip",
            }

        with tempfile.TemporaryDirectory() as tempdir:
            options.hass.config.config_dir = tempdir
            options._config_entry.runtime_data = types.SimpleNamespace(
                proxy_capture_overview=_proxy_overview(can_start=False, can_stop=True, status="running"),
                async_stop_proxy_capture=_stop_proxy_capture,
                effective_owner_name="SMG-family runtime",
                effective_owner_key="modbus_smg",
                smartess_family_name="SmartESS 0925",
                effective_profile_name="smg_modbus.json",
                effective_register_schema_name="modbus_smg/models/smg_6200.json",
                effective_profile_metadata=None,
                effective_register_schema_metadata=None,
                latest_proxy_trace_path="/config/eybond_local/proxy_traces/session.jsonl",
                latest_proxy_trace_manifest_path="/config/eybond_local/proxy_traces/session.json",
                data=types.SimpleNamespace(values={}),
            )

            result = await options.async_step_proxy_capture({"proxy_capture_action": "stop"})

        self.assertEqual(result["step_id"], "proxy_capture")
        self.assertEqual(result["description_placeholders"]["proxy_capture_action_result"], "Capture stopped.")

    async def test_create_support_package_uses_current_origin_download_link_in_result(self) -> None:
        options = self._make_options_flow()

        async def _export_support_package_with_cloud_refresh(
            *,
            smartess_username: str,
            smartess_password: str,
            wants_refresh: bool | None = None,
        ) -> str:
            return "/config/support/support_archive.zip"

        options._config_entry.runtime_data = types.SimpleNamespace(
            async_export_support_package_with_cloud_refresh=_export_support_package_with_cloud_refresh,
            cloud_evidence_export_available=True,
            smartess_collector_pn="E5000020000000",
            data=types.SimpleNamespace(
                values={
                    "support_package_download_url": "http://192.168.1.50:8123/local/eybond_local/support/support_archive.zip",
                    "support_package_download_relative_url": "/local/eybond_local/support/support_archive.zip",
                }
            ),
        )

        result = await options.async_step_create_support_package(
            {
                CONF_SUPPORT_ARCHIVE_SMARTESS_CLOUD_MODE: SUPPORT_ARCHIVE_SMARTESS_CLOUD_MODE_REFRESH,
                "username": " test-user ",
                "password": " pw-test-0000 ",
            }
        )

        self.assertEqual(result["step_id"], "diagnostics_result")
        self.assertIn(
            'href="/local/eybond_local/support/support_archive.zip"',
            result["description_placeholders"]["download_markdown"],
        )
        self.assertNotIn(
            "http://192.168.1.50:8123",
            result["description_placeholders"]["download_markdown"],
        )
        self.assertIn(
            'target="_blank"',
            result["description_placeholders"]["download_markdown"],
        )
        self.assertIn(
            "download",
            result["description_placeholders"]["download_markdown"],
        )
        self.assertNotIn(
            "\n\n`",
            result["description_placeholders"]["download_markdown"],
        )

    async def test_proxy_capture_defaults_to_start_when_session_is_not_running(self) -> None:
        options = self._make_options_flow()
        coordinator = types.SimpleNamespace(
            proxy_capture_overview=types.SimpleNamespace(can_start=True, can_stop=False)
        )

        action = options._default_proxy_capture_action(
            coordinator,
            [
                {"value": "start", "label": "Start"},
                {"value": "refresh", "label": "Refresh"},
            ],
        )

        self.assertEqual(action, "start")

    async def test_proxy_capture_defaults_to_refresh_when_session_is_running(self) -> None:
        options = self._make_options_flow()
        coordinator = types.SimpleNamespace(
            proxy_capture_overview=types.SimpleNamespace(can_start=False, can_stop=True)
        )

        action = options._default_proxy_capture_action(
            coordinator,
            [
                {"value": "stop", "label": "Stop"},
                {"value": "refresh", "label": "Refresh"},
            ],
        )

        self.assertEqual(action, "refresh")

    async def test_diagnostics_menu_exposes_rollback_for_active_local_override(self) -> None:
        options = self._make_options_flow()
        options._config_entry.data.update(
            {
                CONF_CONNECTION_STRATEGY: CONNECTION_STRATEGY_INBOUND,
                "endpoint_control_policy": "integration_managed",
            }
        )
        workflow = {
            f"support_workflow_{key}": value
            for key, value in build_support_workflow_state(
                has_inverter=True,
                effective_owner_key="modbus_smg",
                effective_owner_name="SMG-family runtime",
                detection_confidence="high",
                profile_source_scope="external",
                schema_source_scope="external",
            ).items()
        }

        with tempfile.TemporaryDirectory() as tempdir:
            options.hass.config.config_dir = tempdir
            profile_path = local_profile_path(Path(tempdir), "smg_modbus.json")
            schema_path = local_register_schema_path(
                Path(tempdir),
                "modbus_smg/models/smg_6200.json",
            )
            profile_path.parent.mkdir(parents=True, exist_ok=True)
            schema_path.parent.mkdir(parents=True, exist_ok=True)
            profile_path.write_text("{}\n", encoding="utf-8")
            schema_path.write_text("{}\n", encoding="utf-8")
            options._config_entry.runtime_data = types.SimpleNamespace(
                current_driver=None,
                effective_owner_name="SMG-family runtime",
                effective_owner_key="modbus_smg",
                smartess_family_name="SmartESS 0925",
                effective_profile_name="smg_modbus.json",
                effective_register_schema_name="modbus_smg/models/smg_6200.json",
                effective_profile_metadata=types.SimpleNamespace(
                    source_scope="external",
                    source_path=str(profile_path),
                ),
                effective_register_schema_metadata=types.SimpleNamespace(
                    source_scope="external",
                    source_path=str(schema_path),
                ),
                cloud_evidence_export_available=True,
                smartess_known_family_draft_plan=None,
                smartess_smg_bridge_plan=None,
                data=types.SimpleNamespace(values=workflow),
            )

            result = await options.async_step_diagnostics()

        self.assertEqual(result["type"], "menu")
        self.assertEqual(result["menu_options"][0], "create_support_package")
        self.assertIn("reload_local_metadata", result["menu_options"])
        self.assertIn("rollback_local_metadata", result["menu_options"])
        self.assertNotIn("proxy_capture", result["menu_options"])
        self.assertNotIn("advanced_metadata", result["menu_options"])

    async def test_rollback_local_metadata_runs_coordinator_action(self) -> None:
        options = self._make_options_flow()
        captured: dict[str, object] = {}

        async def _rollback_local_metadata() -> tuple[str, str]:
            captured["called"] = True
            return (
                "/config/eybond_local/profiles/smg_modbus.json",
                "/config/eybond_local/register_schemas/modbus_smg/models/smg_6200.json",
            )

        with tempfile.TemporaryDirectory() as tempdir:
            options.hass.config.config_dir = tempdir
            profile_path = local_profile_path(Path(tempdir), "smg_modbus.json")
            schema_path = local_register_schema_path(
                Path(tempdir),
                "modbus_smg/models/smg_6200.json",
            )
            profile_path.parent.mkdir(parents=True, exist_ok=True)
            schema_path.parent.mkdir(parents=True, exist_ok=True)
            profile_path.write_text("{}\n", encoding="utf-8")
            schema_path.write_text("{}\n", encoding="utf-8")
            options._config_entry.runtime_data = types.SimpleNamespace(
                effective_profile_name="smg_modbus.json",
                effective_register_schema_name="modbus_smg/models/smg_6200.json",
                effective_profile_metadata=types.SimpleNamespace(
                    source_scope="external",
                    source_path=str(profile_path),
                ),
                effective_register_schema_metadata=types.SimpleNamespace(
                    source_scope="external",
                    source_path=str(schema_path),
                ),
                async_rollback_local_metadata=_rollback_local_metadata,
                data=types.SimpleNamespace(values={}),
            )

            result = await options.async_step_rollback_local_metadata({})

        self.assertTrue(captured["called"])
        self.assertEqual(result["step_id"], "diagnostics_result")
        self.assertIn(
            "removed",
            result["description_placeholders"]["status"].lower(),
        )
        self.assertIn(
            "/config/eybond_local/profiles/smg_modbus.json",
            result["description_placeholders"]["path"],
        )

    async def test_create_support_package_shows_guided_form_with_saved_cloud_evidence(self) -> None:
        options = self._make_options_flow()
        options._config_entry.runtime_data = types.SimpleNamespace(
            cloud_evidence_export_available=True,
            smartess_cloud_evidence_path="/config/eybond_local/cloud_evidence/entry123.json",
            smartess_collector_pn="E5000020000000",
            data=types.SimpleNamespace(values={}),
        )

        result = await options.async_step_create_support_package()

        self.assertEqual(result["type"], "form")
        self.assertEqual(result["step_id"], "create_support_package")
        self.assertIn(CONF_SUPPORT_ARCHIVE_SMARTESS_CLOUD_MODE, result["data_schema"].schema)
        self.assertEqual(
            result["description_placeholders"]["cloud_evidence_path"],
            "/config/eybond_local/cloud_evidence/entry123.json",
        )
        self.assertIn(
            "included automatically",
            result["description_placeholders"]["smartess_archive_plan_summary"],
        )
        selector = result["data_schema"].schema[CONF_SUPPORT_ARCHIVE_SMARTESS_CLOUD_MODE]
        option_values = [
            option["value"]
            for option in selector.config.kwargs["options"]
        ]
        self.assertEqual(
            option_values,
            [
                SUPPORT_ARCHIVE_SMARTESS_CLOUD_MODE_USE_SAVED,
                SUPPORT_ARCHIVE_SMARTESS_CLOUD_MODE_REFRESH,
            ],
        )

    async def test_create_support_package_shows_refresh_for_valuecloud_evidence(self) -> None:
        options = self._make_options_flow()
        options._config_entry.runtime_data = types.SimpleNamespace(
            cloud_evidence_export_available=True,
            smartess_cloud_evidence_path="",
            smartess_collector_pn="A0000000000001",
            data=types.SimpleNamespace(values={"collector_cloud_family": "valuecloud_at"}),
        )

        result = await options.async_step_create_support_package()

        self.assertEqual(result["type"], "form")
        self.assertEqual(result["step_id"], "create_support_package")
        selector = result["data_schema"].schema[CONF_SUPPORT_ARCHIVE_SMARTESS_CLOUD_MODE]
        option_values = [
            option["value"]
            for option in selector.config.kwargs["options"]
        ]
        self.assertEqual(
            option_values,
            [
                SUPPORT_ARCHIVE_SMARTESS_CLOUD_MODE_ARCHIVE_ONLY,
                SUPPORT_ARCHIVE_SMARTESS_CLOUD_MODE_REFRESH,
            ],
        )

    async def test_create_support_package_refresh_requires_credentials(self) -> None:
        options = self._make_options_flow()
        options._config_entry.runtime_data = types.SimpleNamespace(
            cloud_evidence_export_available=True,
            smartess_collector_pn="E5000020000000",
            data=types.SimpleNamespace(values={}),
        )

        result = await options.async_step_create_support_package(
            {
                CONF_SUPPORT_ARCHIVE_SMARTESS_CLOUD_MODE: SUPPORT_ARCHIVE_SMARTESS_CLOUD_MODE_REFRESH,
                "username": "",
                "password": "",
            }
        )

        self.assertEqual(result["type"], "form")
        self.assertEqual(result["step_id"], "create_support_package")
        self.assertEqual(
            result["errors"],
            {"username": "required", "password": "required"},
        )

    async def test_create_support_package_refresh_exports_archive_inline(self) -> None:
        options = self._make_options_flow()
        captured: dict[str, object] = {}

        async def _export_support_package_with_cloud_refresh(
            *,
            smartess_username: str,
            smartess_password: str,
            wants_refresh: bool | None = None,
        ) -> str:
            captured["username"] = smartess_username
            captured["password"] = smartess_password
            captured["wants_refresh"] = wants_refresh
            return "/config/support/support_archive.zip"

        options._config_entry.runtime_data = types.SimpleNamespace(
            async_export_support_package_with_cloud_refresh=_export_support_package_with_cloud_refresh,
            cloud_evidence_export_available=True,
            smartess_collector_pn="E5000020000000",
            data=types.SimpleNamespace(
                values={
                    "support_package_download_url": "https://ha.example/api/diagnostics/support_archive.zip",
                    "support_package_download_relative_url": "/api/diagnostics/support_archive.zip?authSig=current-origin",
                }
            ),
        )

        result = await options.async_step_create_support_package(
            {
                CONF_SUPPORT_ARCHIVE_SMARTESS_CLOUD_MODE: SUPPORT_ARCHIVE_SMARTESS_CLOUD_MODE_REFRESH,
                "username": " test-user ",
                "password": " pw-test-0000 ",
            }
        )

        self.assertEqual(captured["username"], "test-user")
        self.assertEqual(captured["password"], "pw-test-0000")
        self.assertEqual(result["step_id"], "diagnostics_result")
        self.assertEqual(
            result["description_placeholders"]["path"],
            "/config/support/support_archive.zip",
        )
        self.assertIn(
            "Fresh cloud evidence was fetched",
            result["description_placeholders"]["status"],
        )
        self.assertIn(
            "/api/diagnostics/support_archive.zip?authSig=current-origin",
            result["description_placeholders"]["download_markdown"],
        )
        self.assertNotIn(
            "https://ha.example",
            result["description_placeholders"]["download_markdown"],
        )

    async def test_create_support_package_for_bridge_does_not_refresh_cloud_evidence(self) -> None:
        options = self._make_options_flow()
        captured: dict[str, object] = {}

        async def _export_support_package_with_cloud_refresh(
            *,
            smartess_username: str,
            smartess_password: str,
            wants_refresh: bool | None = None,
        ) -> str:
            captured["username"] = smartess_username
            captured["password"] = smartess_password
            captured["wants_refresh"] = wants_refresh
            return "/config/support/support_archive.zip"

        options._config_entry.data = {
            **dict(options._config_entry.data),
            "collector_virtual_bridge": True,
        }
        options._config_entry.runtime_data = types.SimpleNamespace(
            async_export_support_package_with_cloud_refresh=_export_support_package_with_cloud_refresh,
            cloud_evidence_export_available=True,
            smartess_cloud_evidence_path="",
            smartess_collector_pn="ESP32COLLECTOR",
            data=types.SimpleNamespace(
                values={
                    "collector_virtual_bridge": True,
                    "support_package_download_url": "/api/diagnostics/support_archive.zip",
                }
            ),
        )

        result = await options.async_step_create_support_package(
            {
                CONF_SUPPORT_ARCHIVE_SMARTESS_CLOUD_MODE: SUPPORT_ARCHIVE_SMARTESS_CLOUD_MODE_REFRESH,
                "username": "should-not-be-used",
                "password": "should-not-be-used",
            }
        )

        self.assertEqual(result["step_id"], "diagnostics_result")
        self.assertEqual(captured["username"], "")
        self.assertEqual(captured["password"], "")
        self.assertIs(captured["wants_refresh"], False)
        self.assertIn(
            "No cloud evidence was included",
            result["description_placeholders"]["status"],
        )

    async def test_diagnostics_placeholders_use_effective_smartess_metadata_without_driver(self) -> None:
        options = self._make_options_flow()
        profile_metadata = load_driver_profile("pi30_ascii/models/smartess_0925_compat.json")
        schema_metadata = load_register_schema("pi30_ascii/models/smartess_0925_compat.json")

        with tempfile.TemporaryDirectory() as tempdir:
            options.hass.config.config_dir = tempdir
            options._config_entry.runtime_data = types.SimpleNamespace(
                current_driver=None,
                effective_owner_name="PI30-family runtime",
                effective_owner_key="pi30",
                smartess_family_name="SmartESS 0925",
                effective_profile_name="pi30_ascii/models/smartess_0925_compat.json",
                effective_register_schema_name="pi30_ascii/models/smartess_0925_compat.json",
                effective_profile_metadata=profile_metadata,
                effective_register_schema_metadata=schema_metadata,
                data=types.SimpleNamespace(values={}),
            )

            placeholders = options._diagnostics_placeholders()

        self.assertEqual(placeholders["effective_owner_name"], "PI30-family runtime")
        self.assertEqual(placeholders["effective_owner_key"], "pi30")
        self.assertEqual(placeholders["smartess_family_name"], "SmartESS 0925")
        self.assertEqual(placeholders["smartess_family_line"], "\n**SmartESS family:** SmartESS 0925")
        self.assertEqual(placeholders["profile_name"], "pi30_ascii/models/smartess_0925_compat.json")
        self.assertEqual(
            placeholders["register_schema_name"],
            "pi30_ascii/models/smartess_0925_compat.json",
        )
        self.assertIn(
            "profiles/pi30_ascii/models/smartess_0925_compat.json",
            placeholders["effective_profile_source"],
        )
        self.assertIn(
            "register_schemas/pi30_ascii/models/smartess_0925_compat.json",
            placeholders["effective_schema_source"],
        )

    def test_validate_connection_inputs_uses_field_validation_metadata(self) -> None:
        flow = self._make_flow()
        errors = flow._validate_connection_inputs(
            {
                "server_ip": "not-an-ip",
                "advertised_server_ip": "still-not-an-ip",
                "advertised_tcp_port": "70000",
                "collector_ip": "",
                "discovery_target": "also-not-an-ip",
            },
            fields=flow._connection_branch().form_layout.manual_fields
            + flow._connection_branch().form_layout.manual_advanced_fields,
        )

        self.assertEqual(errors["server_ip"], "invalid_ip")
        self.assertEqual(errors["advertised_server_ip"], "invalid_ip")
        self.assertEqual(errors["advertised_tcp_port"], "invalid_port")
        self.assertEqual(errors["discovery_target"], "invalid_ip")
        self.assertNotIn("collector_ip", errors)


    def test_flatten_sections_coerces_numeric_selector_values_to_ints(self) -> None:
        flattened = _flatten_sections(
            {
                "server_ip": "192.168.1.50",
                "advanced_connection": {
                    "tcp_port": 8899.0,
                    "udp_port": 58899.0,
                    "discovery_interval": 10.0,
                    "heartbeat_interval": 60.0,
                    "advertised_tcp_port": "9443",
                },
            }
        )

        self.assertEqual(flattened["advertised_tcp_port"], 9443)
        self.assertEqual(flattened["tcp_port"], 8899)
        self.assertEqual(flattened["udp_port"], 58899)
        self.assertEqual(flattened["discovery_interval"], 10)
        self.assertEqual(flattened["heartbeat_interval"], 60)

    def test_shadow_learning_route_rejects_control_when_collector_off_proxy(self) -> None:
        # SAFETY-CRITICAL: control is allowed ONLY while the collector's main link is on our
        # proxy right now (collector_connected). A sticky "reached us once" signal
        # (collector_protocol_ingress) plus residual route activity must NOT grant control --
        # after a mid-scan revert the collector is back on the real server and a ctrlDevice
        # would reach the inverter (it turned off the user's output).
        options = object.__new__(options_flow_module.EybondLocalOptionsFlow)

        def _coordinator(collector_connected: bool) -> object:
            return types.SimpleNamespace(
                shadow_learning_runtime=_shadow_runtime_facade(
                    ShadowLearningRouteStatus.from_mapping({
                        "running": True,
                        "collector_connected": collector_connected,
                        # Stale/sticky signals that must never override the live-socket check.
                        "collector_protocol_ingress": True,
                        "route_protocol_activity": True,
                        "upstream_connected": False,
                        "ready": False,
                        "upstream_error": "",
                    }),
                )
            )

        # Reverted to the real server (no live collector socket) -> blocked despite stale flags.
        self.assertFalse(
            options._shadow_learning_route_accepts_control(_coordinator(False))
        )
        # Collector on our proxy but upstream down -> blocked for writes.
        self.assertFalse(
            options._shadow_learning_route_accepts_control(_coordinator(True))
        )

        self.assertTrue(
            options._shadow_learning_route_accepts_control(
                types.SimpleNamespace(
                    shadow_learning_runtime=_shadow_runtime_facade(
                        ShadowLearningRouteStatus.from_mapping({
                            "running": True,
                            "collector_connected": True,
                            "collector_protocol_ingress": True,
                            "route_protocol_activity": True,
                            "upstream_connected": True,
                            "ready": True,
                            "upstream_error": "",
                        }),
                    )
                )
            )
        )

    def test_shadow_learning_placeholders_prefer_runtime_session_state(self) -> None:
        options = self._make_options_flow()
        options._shadow_learning_state = {
            "session": {"status": "learning"},
        }
        options._config_entry.runtime_data = types.SimpleNamespace(
            shadow_learning_runtime=_shadow_runtime_facade(
                ShadowLearningRouteStatus.from_mapping({
                    "running": False,
                    "collector_connected": False,
                    "upstream_connected": False,
                    "ready": False,
                    "upstream_error": "",
                }),
            ),
            data=types.SimpleNamespace(values={}),
        )

        placeholders = options._shadow_learning_placeholders(options._coordinator())

        self.assertEqual(placeholders["shadow_learning_session_state"], "stopped")

    def test_shadow_learning_placeholders_surface_restore_failed_state(self) -> None:
        options = self._make_options_flow()
        options._config_entry.runtime_data = types.SimpleNamespace(
            shadow_learning_runtime=_shadow_runtime_facade(
                ShadowLearningRouteStatus.from_mapping({
                    "running": False,
                    "collector_connected": False,
                    "collector_protocol_ingress": False,
                    "upstream_connected": False,
                    "ready": False,
                    "upstream_error": "",
                }),
            ),
            data=types.SimpleNamespace(values={"shadow_learning_session_status": "restore_failed"}),
        )

        placeholders = options._shadow_learning_placeholders(options._coordinator())

        self.assertEqual(placeholders["shadow_learning_session_state"], "restore_failed")

    def _wizard_options_flow(self) -> EybondLocalOptionsFlow:
        options = self._make_options_flow()
        options._config_entry.data.update(
            {
                CONF_CONNECTION_STRATEGY: CONNECTION_STRATEGY_CALLBACK_ON_DEMAND,
                "endpoint_control_policy": "external",
            }
        )
        coordinator = types.SimpleNamespace(
            data=types.SimpleNamespace(values={}),
            cloud_evidence_provider="smartess",
            smartess_collector_pn="E50000200000000001",
            local_register_collection_status=LocalRegisterCollectionStatus.idle(),
            local_register_collection_availability=LocalRegisterCollectionAvailability("ready"),
        )

        def _start_local_collection(plan):
            coordinator.local_register_collection_status = (
                LocalRegisterCollectionStatus(
                    state=LOCAL_REGISTER_COLLECTION_STATE_RUNNING,
                    plan=plan,
                    started_at="2026-08-22T10:00:00+00:00",
                    completed_at="",
                    completed_sample_count=0,
                    failure_reason="",
                )
            )
            return coordinator.local_register_collection_status

        coordinator.start_local_register_collection = Mock(
            side_effect=_start_local_collection
        )
        options._config_entry.runtime_data = coordinator
        return options

    async def test_control_discovery_ha_only_profile_routes_to_profile_choice(
        self,
    ) -> None:
        options = self._make_options_flow()
        options._config_entry.data.update(
            {
                CONF_CONNECTION_STRATEGY: CONNECTION_STRATEGY_INBOUND,
                "endpoint_control_policy": "integration_managed",
            }
        )
        options._config_entry.runtime_data = types.SimpleNamespace(
            data=types.SimpleNamespace(values={}),
        )

        result = await options.async_step_shadow_learning()

        self.assertEqual(result["type"], "form")
        self.assertEqual(result["step_id"], "connection")
        self.assertIn(CONF_CONNECTION_STRATEGY, result["data_schema"].schema)

    async def test_control_discovery_entry_shows_method_first_picker(self) -> None:
        options = self._wizard_options_flow()

        result = await options.async_step_shadow_learning()

        self.assertEqual(result["type"], "form")
        self.assertEqual(result["step_id"], "shadow_learning")
        self.assertEqual(set(result["data_schema"].schema), {"learning_method"})
        self.assertEqual(
            tuple(_schema_select_options(result["data_schema"], "learning_method")),
            (
                LEARNING_METHOD_READ_ONLY_EVIDENCE,
                LEARNING_METHOD_ACTIVE_CORRELATION,
            ),
        )
        method_field = next(iter(result["data_schema"].schema))
        self.assertEqual(method_field.default(), LEARNING_METHOD_READ_ONLY_EVIDENCE)
        # The long technical action/mode dropdown must be gone from the normal path.
        self.assertNotIn("shadow_learning_action", result["data_schema"].schema)
        self.assertNotIn("shadow_learning_mode", result["data_schema"].schema)
        self.assertNotIn("shadow_learning_field_ids", result["data_schema"].schema)

    async def test_control_discovery_intro_requires_consent(self) -> None:
        options = self._wizard_options_flow()
        selected = await options.async_step_shadow_learning(
            {"learning_method": LEARNING_METHOD_ACTIVE_CORRELATION}
        )
        self.assertEqual(selected["step_id"], "shadow_learning_source")
        self.assertEqual(
            tuple(_schema_select_options(selected["data_schema"], "learning_source")),
            ("dessmonitor", "smartess"),
        )
        selected = await options.async_step_shadow_learning_source(
            {"learning_source": "smartess"}
        )
        self.assertEqual(selected["step_id"], "shadow_learning_consent")

        result = await options.async_step_shadow_learning_consent(
            {"shadow_learning_confirm_cloud_write": False}
        )

        self.assertEqual(result["type"], "form")
        self.assertEqual(result["step_id"], "shadow_learning_consent")
        self.assertEqual(
            result["errors"], {"shadow_learning_confirm_cloud_write": "required"}
        )
        self.assertNotIn("wizard_consent", options._shadow_learning_state)

    async def test_control_discovery_consent_advances_to_credentials(self) -> None:
        options = self._wizard_options_flow()
        selected = await options.async_step_shadow_learning(
            {"learning_method": LEARNING_METHOD_ACTIVE_CORRELATION}
        )
        self.assertEqual(selected["step_id"], "shadow_learning_source")
        selected = await options.async_step_shadow_learning_source(
            {"learning_source": "smartess"}
        )
        self.assertEqual(selected["step_id"], "shadow_learning_consent")

        result = await options.async_step_shadow_learning_consent(
            {"shadow_learning_confirm_cloud_write": True}
        )

        self.assertEqual(result["type"], "form")
        self.assertEqual(result["step_id"], "shadow_learning_credentials")
        self.assertTrue(options._shadow_learning_state["wizard_consent"])
        # Credentials step asks only for cloud username/password.
        self.assertEqual(set(result["data_schema"].schema), {"username", "password"})

    async def test_control_discovery_dessmonitor_skips_control_consent(self) -> None:
        options = self._wizard_options_flow()
        entry_data = dict(options._config_entry.data)
        entry_options = dict(options._config_entry.options)

        source_step = await options.async_step_shadow_learning(
            {"learning_method": LEARNING_METHOD_READ_ONLY_EVIDENCE}
        )
        self.assertEqual(source_step["step_id"], "shadow_learning_source")
        self.assertEqual(
            tuple(_schema_select_options(source_step["data_schema"], "learning_source")),
            ("dessmonitor", "smartess", "smartclient"),
        )
        result = await options.async_step_shadow_learning_source(
            {"learning_source": "dessmonitor"}
        )

        self.assertEqual(result["type"], "form")
        self.assertEqual(result["step_id"], "shadow_learning_credentials")
        self.assertEqual(options._shadow_learning_state["wizard_source"], "dessmonitor")
        self.assertNotIn("wizard_consent", options._shadow_learning_state)
        self.assertEqual(options._config_entry.data, entry_data)
        self.assertEqual(options._config_entry.options, entry_options)

    async def test_smartclient_source_names_the_right_app_without_active_consent(self) -> None:
        options = self._wizard_options_flow()
        await options.async_step_shadow_learning(
            {"learning_method": LEARNING_METHOD_READ_ONLY_EVIDENCE}
        )
        result = await options.async_step_shadow_learning_source(
            {"learning_source": "smartclient"}
        )
        self.assertEqual(result["step_id"], "shadow_learning_credentials")
        self.assertEqual(options._control_discovery_cloud_app_label(options._coordinator()), "SmartClient")
        self.assertEqual(options._control_discovery_cloud_provider_label(options._coordinator()), "SmartClient / ShineMonitor")
        self.assertNotIn("wizard_consent", options._shadow_learning_state)
        self.assertFalse(options._control_discovery_requires_shadow_route(options._coordinator()))

    async def test_control_discovery_dessmonitor_active_requires_consent(self) -> None:
        options = self._wizard_options_flow()
        source_step = await options.async_step_shadow_learning(
            {"learning_method": LEARNING_METHOD_ACTIVE_CORRELATION}
        )

        self.assertEqual(source_step["step_id"], "shadow_learning_source")
        self.assertEqual(
            tuple(_schema_select_options(source_step["data_schema"], "learning_source")),
            ("dessmonitor", "smartess"),
        )
        consent = await options.async_step_shadow_learning_source(
            {"learning_source": "dessmonitor"}
        )

        self.assertEqual(consent["step_id"], "shadow_learning_consent")
        self.assertEqual(
            options._shadow_learning_state["wizard_method"],
            LEARNING_METHOD_ACTIVE_CORRELATION,
        )
        self.assertEqual(
            options._shadow_learning_state["wizard_source"],
            "dessmonitor",
        )

    async def test_learning_credentials_preserve_password_whitespace(self) -> None:
        options = self._wizard_options_flow()
        options._shadow_learning_state.update(
            {"wizard_method": LEARNING_METHOD_READ_ONLY_EVIDENCE, "wizard_source": "smartclient"}
        )
        with patch.object(options, "async_step_shadow_learning_progress", new=AsyncMock(return_value={})):
            await options.async_step_shadow_learning_credentials(
                {"username": " owner ", "password": " secret "}
            )
        self.assertEqual(options._shadow_learning_state["wizard_credentials"],
                         {"username": "owner", "password": " secret "})
        self.assertNotIn("password", options._config_entry.data)
        self.assertNotIn("password", options._config_entry.options)

    async def test_control_discovery_method_selection_fails_closed(self) -> None:
        options = self._wizard_options_flow()
        options._shadow_learning_state["sentinel"] = "preserved"

        for malformed in ("unknown", " read_only_evidence", b"x", object(), None):
            with self.subTest(malformed=malformed):
                result = await options.async_step_shadow_learning(
                    {"learning_method": malformed}
                )
                self.assertEqual(result["step_id"], "shadow_learning")
                self.assertEqual(
                    result["errors"], {"learning_method": "invalid_selection"}
                )
                self.assertNotIn("wizard_method", options._shadow_learning_state)
                self.assertNotIn("wizard_source", options._shadow_learning_state)
                self.assertEqual(
                    options._shadow_learning_state["sentinel"], "preserved"
                )

    async def test_control_discovery_source_selection_fails_closed(self) -> None:
        options = self._wizard_options_flow()
        await options.async_step_shadow_learning(
            {"learning_method": LEARNING_METHOD_READ_ONLY_EVIDENCE}
        )

        for malformed in ("unknown", " smartess", b"smartess", object(), None):
            with self.subTest(malformed=malformed):
                result = await options.async_step_shadow_learning_source(
                    {"learning_source": malformed}
                )
                self.assertEqual(result["step_id"], "shadow_learning_source")
                self.assertEqual(
                    result["errors"], {"learning_source": "invalid_selection"}
                )
                self.assertNotIn("wizard_source", options._shadow_learning_state)

    async def test_control_discovery_credentials_require_username_and_password(self) -> None:
        options = self._wizard_options_flow()
        options._shadow_learning_state["wizard_method"] = LEARNING_METHOD_ACTIVE_CORRELATION
        options._shadow_learning_state["wizard_source"] = "smartess"
        options._shadow_learning_state["wizard_consent"] = True

        result = await options.async_step_shadow_learning_credentials(
            {"username": "", "password": ""}
        )

        self.assertEqual(result["type"], "form")
        self.assertEqual(result["step_id"], "shadow_learning_credentials")
        self.assertEqual(
            result["errors"], {"username": "required", "password": "required"}
        )
        self.assertNotIn("wizard_credentials", options._shadow_learning_state)

    async def test_control_discovery_credentials_unreachable_without_consent(self) -> None:
        options = self._wizard_options_flow()

        result = await options.async_step_shadow_learning_credentials(
            {"username": "demo", "password": "secret"}
        )

        # Falls back to the intro/consent step; credentials are not accepted.
        self.assertEqual(result["type"], "form")
        self.assertEqual(result["step_id"], "shadow_learning")
        self.assertNotIn("wizard_credentials", options._shadow_learning_state)

    async def test_control_discovery_credentials_advance_through_progress(self) -> None:
        options = self._wizard_options_flow()
        options._shadow_learning_state["wizard_method"] = LEARNING_METHOD_ACTIVE_CORRELATION
        options._shadow_learning_state["wizard_source"] = "smartess"
        options._shadow_learning_state["wizard_consent"] = True
        options._shadow_learning_state["wizard_progress_task"] = _DoneTask()

        result = await options.async_step_shadow_learning_credentials(
            {"username": " demo ", "password": " secret "}
        )

        self.assertEqual(result["type"], "progress_done")
        self.assertEqual(result["next_step_id"], "shadow_learning_review")
        self.assertEqual(
            options._shadow_learning_state["wizard_credentials"],
            {"username": "demo", "password": " secret "},
        )

    async def test_control_discovery_progress_creates_task_and_shows_progress(self) -> None:
        options = self._wizard_options_flow()
        options._shadow_learning_state["wizard_consent"] = True
        options._shadow_learning_state["wizard_credentials"] = {
            "username": "demo",
            "password": "secret",
        }

        result = await options.async_step_shadow_learning_progress()

        self.assertEqual(result["type"], "progress")
        self.assertEqual(result["step_id"], "shadow_learning_progress")
        self.assertEqual(result["progress_action"], "shadow_learning")
        task = options._shadow_learning_state["wizard_progress_task"]
        self.assertIsNotNone(task)
        # The placeholder runner performs no live operation; let it finish cleanly.
        await task

    async def test_control_discovery_progress_completes_to_review(self) -> None:
        options = self._wizard_options_flow()
        options._shadow_learning_state["wizard_consent"] = True
        options._shadow_learning_state["wizard_credentials"] = {
            "username": "demo",
            "password": "secret",
        }
        options._shadow_learning_state["wizard_progress_task"] = _DoneTask()

        result = await options.async_step_shadow_learning_progress()

        self.assertEqual(result["type"], "progress_done")
        self.assertEqual(result["next_step_id"], "shadow_learning_review")
        self.assertIsNone(options._shadow_learning_state["wizard_progress_task"])

    async def test_control_discovery_progress_unreachable_without_credentials(self) -> None:
        options = self._wizard_options_flow()
        options._shadow_learning_state["wizard_consent"] = True

        result = await options.async_step_shadow_learning_progress()

        self.assertEqual(result["type"], "form")
        self.assertEqual(result["step_id"], "shadow_learning")

    def test_set_control_discovery_progress_records_stage_and_clamps(self) -> None:
        options = self._wizard_options_flow()

        options._set_control_discovery_progress(0.45, "testing", done=10, total=23)
        progress = options._shadow_learning_state["progress"]
        self.assertEqual(progress["stage"], "testing")
        self.assertAlmostEqual(progress["fraction"], 0.45)
        self.assertEqual(progress["done"], 10)
        self.assertEqual(progress["total"], 23)

        # Fractions are clamped into [0, 1] for the determinate progress bar.
        options._set_control_discovery_progress(1.5, "finalizing")
        self.assertEqual(options._shadow_learning_state["progress"]["fraction"], 1.0)
        options._set_control_discovery_progress(-0.5, "preflight")
        self.assertEqual(options._shadow_learning_state["progress"]["fraction"], 1.0)
        self.assertEqual(options._shadow_learning_state["progress"]["stage"], "preflight")

        # Only the explicit start of a fresh run may reset the bar.
        options._set_control_discovery_progress(0.0, "starting")
        self.assertEqual(options._shadow_learning_state["progress"]["fraction"], 0.0)

    def test_control_discovery_progress_never_moves_back_at_route_boundary(self) -> None:
        options = self._wizard_options_flow()
        observed: list[float] = []
        options.async_update_progress = observed.append

        options._set_control_discovery_progress(0.15, "fetching")
        options._set_control_discovery_progress(0.10, "connecting")

        self.assertEqual(observed, [0.15, 0.15])
        self.assertEqual(
            options._shadow_learning_state["progress"],
            {
                "fraction": 0.15,
                "stage": "connecting",
                "done": 0,
                "total": 0,
            },
        )

    async def test_control_discovery_review_forwards_to_result(self) -> None:
        options = self._wizard_options_flow()

        # An empty review (nothing found / failed run) skips the redundant
        # intermediate "nothing found" page and forwards straight to the result.
        shown = await options.async_step_shadow_learning_review()
        self.assertEqual(shown["type"], "form")
        self.assertEqual(shown["step_id"], "shadow_learning_result")

    @staticmethod
    def _review_capabilities() -> list[dict[str, Any]]:
        """A normal-risk control plus a high-risk (reset/destructive) control."""

        return [
            {
                "key": "learned_backlight_700",
                "title": "Backlight Control",
                "register": 700,
                "value_kind": "bool",
                "learned_provenance": {
                    "cloud_field_id": "sys_backlight_700",
                    "confidence": "high",
                    "safety_class": "setting",
                    "evidence_hash": "aaaa",
                },
            },
            {
                "key": "learned_reset_690",
                "title": "Reset user parameters",
                "register": 690,
                "value_kind": "action",
                "learned_provenance": {
                    "cloud_field_id": "sys_reset_690",
                    "confidence": "high",
                    "safety_class": "destructive_action",
                    "evidence_hash": "bbbb",
                },
            },
        ]

    def _seed_control_discovery_review(
        self,
        options,
        capabilities=None,
        *,
        phase="edit",
        skipped=None,
        learned_reads=None,
        skipped_reads=None,
        read_evidence=None,
    ) -> dict[str, Any]:
        """Embed a real review model in flow state the way the runner would.

        Defaults to the ``edit`` review page (where rename/enable fields live);
        pass ``phase="overview"`` to exercise the read-only overview page, and
        ``skipped`` to seed the already-supported control list.
        """

        review_model = attach_learned_read_review_model(
            build_learned_control_review_model(
                capabilities if capabilities is not None else self._review_capabilities()
            ),
            learned_read_sensors=list(learned_reads or []),
            skipped_read_sensors=list(skipped_reads or []),
            read_review_evidence=list(read_evidence or []),
        )
        manifest: dict[str, Any] = {"review_model": review_model}
        if skipped is not None:
            manifest["skipped_duplicates"] = list(skipped)
        options._shadow_learning_state["overlay"] = {"manifest": manifest}
        if phase is not None:
            options._shadow_learning_state["review_phase"] = phase
        return review_model

    async def test_control_discovery_review_edit_lists_controls_as_checkboxes(self) -> None:
        options = self._wizard_options_flow()
        self._seed_control_discovery_review(options)  # phase="edit" by default

        result = await options.async_step_shadow_learning_review()

        self.assertEqual(result["type"], "form")
        self.assertEqual(result["step_id"], "shadow_learning_review")
        # A single multi-select field — no per-control rename/enable fields.
        schema = result["data_schema"].schema
        self.assertEqual({str(key) for key in schema}, {"enabled_controls"})
        selector = next(
            value for key, value in schema.items() if str(key) == "enabled_controls"
        )
        labels = [option["label"] for option in selector.config.kwargs["options"]]
        # Each option is labelled with the control's friendly name (no field IDs).
        self.assertIn("Backlight Control", labels)
        self.assertIn("Reset user parameters", labels)
        self.assertNotIn("sys_reset_690", labels)
        placeholders = result["description_placeholders"]
        self.assertEqual(placeholders["control_discovery_count"], "2")
        on_count = int(placeholders["control_discovery_on_count"])
        off_count = int(placeholders["control_discovery_off_count"])
        self.assertEqual(on_count + off_count, 2)
        self.assertGreaterEqual(off_count, 1)
        # Descriptions/types live on the overview page, not here.
        self.assertNotIn("control_discovery_table", placeholders)

    async def test_control_discovery_review_overview_lists_new_and_existing(self) -> None:
        options = self._wizard_options_flow()
        self._seed_control_discovery_review(
            options,
            phase="overview",
            skipped=[
                {"field_id": "bse_eybond_ctrl_48", "field_name": "Output Mode", "register": 300},
                {"field_id": "bse_eybond_ctrl_49", "field_name": "Output priority", "register": 301},
            ],
        )

        result = await options.async_step_shadow_learning_review()

        self.assertEqual(result["type"], "form")
        self.assertEqual(result["step_id"], "shadow_learning_review")
        # Overview is read-only: no rename/enable fields on this page.
        self.assertEqual(dict(result["data_schema"].schema), {})
        placeholders = result["description_placeholders"]
        self.assertEqual(placeholders["control_discovery_new_count"], "2")
        self.assertEqual(placeholders["control_discovery_existing_count"], "2")
        overview = placeholders["control_discovery_overview"]
        # New controls and already-supported controls both appear, marked, with
        # friendly types and a suggested-state note (no field IDs / risk codes).
        self.assertIn("Backlight Control", overview)
        self.assertIn("Output Mode", overview)
        self.assertIn("Output priority", overview)
        self.assertIn("Switch", overview)
        self.assertIn("Button", overview)
        self.assertIn("Risky", overview)
        self.assertNotIn("destructive_action", overview)
        self.assertNotIn("sys_reset_690", overview)

    async def test_control_discovery_review_localizes_existing_read_section(self) -> None:
        options = self._wizard_options_flow()
        self._seed_control_discovery_review(
            options,
            capabilities=[],
            phase="overview",
            skipped_reads=[
                {
                    "register": 344,
                    "title": "PV Voltage",
                    "kind": "numeric",
                    "reason": "register_already_decoded",
                },
                {
                    "register": 239,
                    "title": "Battery Voltage",
                    "kind": "numeric",
                    "reason": "title_already_mapped",
                },
            ],
        )

        result = await options.async_step_shadow_learning_review()

        overview = result["description_placeholders"]["control_discovery_overview"]
        self.assertIn("Sensors already in Home Assistant (2)", overview)
        self.assertIn("PV Voltage", overview)
        self.assertIn("Battery Voltage", overview)
        self.assertNotIn("register_already_decoded", overview)
        self.assertNotIn("title_already_mapped", overview)

    async def test_control_discovery_review_lists_all_inconclusive_cloud_fields(self) -> None:
        options = self._wizard_options_flow()
        self._seed_control_discovery_review(
            options,
            capabilities=[],
            phase="overview",
            read_evidence=[
                {
                    "cloud_id": "grid_voltage",
                    "field_name": "Grid Voltage",
                    "default_label": "Grid Voltage",
                    "cloud_value": "0.0",
                    "unit": "V",
                    "kind": "numeric",
                    "binding_status": "skipped_zero",
                    "disposition": "inconclusive",
                    "reason": "value_zero",
                    "register": 0,
                    "candidate_registers": [],
                },
                {
                    "cloud_id": "dc_temperature",
                    "field_name": "DC Module Termperature",
                    "default_label": "DC Module Temperature",
                    "cloud_value": "27",
                    "unit": "°C",
                    "kind": "numeric",
                    "binding_status": "ambiguous",
                    "disposition": "inconclusive",
                    "reason": "multiple_registers",
                    "register": 0,
                    "candidate_registers": [206, 226],
                },
                {
                    "cloud_id": "operating_mode",
                    "field_name": "Operating mode",
                    "default_label": "Operating mode",
                    "cloud_value": "Off-Grid Mode",
                    "unit": "",
                    "kind": "enum",
                    "binding_status": "enum_ambiguous",
                    "disposition": "inconclusive",
                    "reason": "enum_ambiguous",
                    "register": 0,
                    "candidate_registers": [201, 331],
                },
            ],
        )

        result = await options.async_step_shadow_learning_review()

        placeholders = result["description_placeholders"]
        self.assertEqual(
            placeholders["control_discovery_inconclusive_read_count"], "3"
        )
        overview = placeholders["control_discovery_overview"]
        self.assertIn("Cloud fields not linked in this run (3)", overview)
        self.assertIn("Grid Voltage", overview)
        self.assertIn("DC Module Temperature", overview)
        self.assertNotIn("DC Module Termperature", overview)
        self.assertIn("Operating mode", overview)
        self.assertIn("no active value during this check", overview)
        self.assertIn("several registers had the same value", overview)
        self.assertIn("the state could not be matched safely", overview)
        self.assertNotIn("skipped_zero", overview)
        self.assertNotIn("enum_ambiguous", overview)

    async def test_control_discovery_review_overview_continues_to_edit(self) -> None:
        options = self._wizard_options_flow()
        self._seed_control_discovery_review(options, phase="overview")

        result = await options.async_step_shadow_learning_review({})

        # Continuing from the overview lands on the edit page with the selection.
        self.assertEqual(result["type"], "form")
        self.assertEqual(result["step_id"], "shadow_learning_review")
        self.assertIn("enabled_controls", {str(key) for key in result["data_schema"].schema})

    async def test_control_discovery_review_defaults_disable_risky_controls(self) -> None:
        options = self._wizard_options_flow()
        self._seed_control_discovery_review(options)
        controls = options._control_discovery_review_controls()

        default_enabled = options._control_discovery_default_enabled_keys(controls, {})

        # Normal control is pre-selected; risky control is not.
        self.assertIn("learned_backlight_700", default_enabled)
        self.assertNotIn("learned_reset_690", default_enabled)

    async def test_control_discovery_review_stores_user_choices(self) -> None:
        options = self._wizard_options_flow()
        self._seed_control_discovery_review(options)

        # User flips the defaults: enable the risky control, leave the normal off.
        forwarded = await options.async_step_shadow_learning_review(
            {"enabled_controls": ["learned_reset_690"]}
        )

        # On submit the wizard advances to the result step.
        self.assertEqual(forwarded["type"], "form")
        self.assertEqual(forwarded["step_id"], "shadow_learning_result")

        selections = options._shadow_learning_state["review_selections"]
        controls = selections["controls"]
        # The friendly discovered name is used as-is (there is no rename field).
        self.assertEqual(controls["learned_backlight_700"]["label"], "Backlight Control")
        self.assertFalse(controls["learned_backlight_700"]["enabled"])
        self.assertTrue(controls["learned_reset_690"]["enabled"])
        self.assertEqual(selections["enabled_by_user"], ["learned_reset_690"])
        self.assertEqual(selections["excluded_by_user"], ["learned_backlight_700"])

    async def test_control_discovery_review_lists_read_sensors_as_checkboxes(self) -> None:
        options = self._wizard_options_flow()
        self._seed_control_discovery_review(
            options,
            capabilities=[],
            learned_reads=[
                {
                    "key": "learned_read_344",
                    "register": 344,
                    "title": "Output 2 Cut-Off SOC Status",
                    "kind": "numeric",
                    "spec_set": "config",
                },
                {
                    "key": "learned_read_239",
                    "register": 239,
                    "title": "Output 2 Apparent Power",
                    "kind": "numeric",
                    "spec_set": "live",
                },
            ],
        )

        result = await options.async_step_shadow_learning_review()

        self.assertEqual(result["type"], "form")
        self.assertEqual(result["step_id"], "shadow_learning_review")
        schema = result["data_schema"].schema
        self.assertEqual({str(key) for key in schema}, {"enabled_read_sensors"})
        selector = next(
            value for key, value in schema.items() if str(key) == "enabled_read_sensors"
        )
        labels = [option["label"] for option in selector.config.kwargs["options"]]
        self.assertIn("Output 2 Cut-Off SOC Status", labels)
        self.assertIn("Output 2 Apparent Power", labels)

    async def test_control_discovery_review_stores_read_sensor_choices(self) -> None:
        options = self._wizard_options_flow()
        self._seed_control_discovery_review(
            options,
            capabilities=[],
            learned_reads=[
                {
                    "key": "learned_read_344",
                    "register": 344,
                    "title": "Output 2 Cut-Off SOC Status",
                    "kind": "numeric",
                    "spec_set": "config",
                },
                {
                    "key": "learned_read_239",
                    "register": 239,
                    "title": "Output 2 Apparent Power",
                    "kind": "numeric",
                    "spec_set": "live",
                },
            ],
        )

        await options.async_step_shadow_learning_review(
            {"enabled_read_sensors": ["learned_read_344"]}
        )

        selections = options._shadow_learning_state["review_selections"]
        self.assertEqual(selections["read_enabled_by_user"], ["learned_read_344"])
        self.assertEqual(selections["read_excluded_by_user"], ["learned_read_239"])
        self.assertTrue(selections["read_sensors"]["learned_read_344"]["enabled"])
        self.assertFalse(selections["read_sensors"]["learned_read_239"]["enabled"])

    async def test_control_discovery_review_keeps_disabled_controls_in_evidence(self) -> None:
        options = self._wizard_options_flow()
        review_model = self._seed_control_discovery_review(options)

        # Add nothing: both controls left off.
        await options.async_step_shadow_learning_review({"enabled_controls": []})

        # The discovered evidence is untouched: every control (including the ones
        # the user left disabled) is still present in learned_all...
        learned_keys = {
            entry["key"]
            for entry in options._shadow_learning_state["overlay"]["manifest"][
                "review_model"
            ]["learned_all"]
        }
        self.assertEqual(learned_keys, {"learned_backlight_700", "learned_reset_690"})
        # ...and the developer field name / default label is captured as evidence.
        reset_entry = next(
            entry
            for entry in review_model["learned_all"]
            if entry["key"] == "learned_reset_690"
        )
        self.assertEqual(reset_entry["field_name"], "Reset user parameters")
        self.assertEqual(reset_entry["default_label"], "Reset user parameters")
        # Both controls were recorded as excluded by the user.
        self.assertEqual(
            set(options._shadow_learning_state["review_selections"]["excluded_by_user"]),
            {"learned_backlight_700", "learned_reset_690"},
        )

    async def test_control_discovery_review_preserves_prior_selection_on_revisit(self) -> None:
        options = self._wizard_options_flow()
        self._seed_control_discovery_review(options)

        # First pass: flip both controls (enable risky, disable normal).
        await options.async_step_shadow_learning_review(
            {"enabled_controls": ["learned_reset_690"]}
        )

        # Revisiting reflects the user's prior choice, not the defaults.
        controls = options._control_discovery_review_controls()
        default_enabled = options._control_discovery_default_enabled_keys(
            controls, options._control_discovery_prior_selections()
        )
        self.assertNotIn("learned_backlight_700", default_enabled)
        self.assertIn("learned_reset_690", default_enabled)

    async def test_control_discovery_review_empty_uses_empty_copy(self) -> None:
        options = self._wizard_options_flow()

        # Empty review forwards to the result screen, which carries the detailed
        # "nothing found" copy directly (no intermediate empty page).
        shown = await options.async_step_shadow_learning_review()

        self.assertEqual(shown["type"], "form")
        self.assertEqual(shown["step_id"], "shadow_learning_result")
        self.assertIn(
            "No controls were found",
            shown["description_placeholders"]["control_discovery_hint"],
        )

    async def test_control_discovery_result_drops_credentials_and_returns_to_menu(self) -> None:
        options = self._wizard_options_flow()
        options._shadow_learning_state["wizard_credentials"] = {
            "username": "demo",
            "password": "secret",
        }

        shown = await options.async_step_shadow_learning_result()
        self.assertEqual(shown["type"], "form")
        self.assertEqual(shown["step_id"], "shadow_learning_result")
        # Credentials are dropped as soon as the result step is reached.
        self.assertNotIn("wizard_credentials", options._shadow_learning_state)

        done = await options.async_step_shadow_learning_result({})
        self.assertEqual(done["type"], "menu")
        self.assertEqual(done["step_id"], "init")

    async def test_control_discovery_result_failed_run_shows_failure_copy(self) -> None:
        options = self._wizard_options_flow()
        # Discovery ran but failed (e.g. the device never reconnected in time):
        # the copy must say so, not claim that nothing was found.
        options._shadow_learning_state["discovery"] = {
            "status": "error",
            "reason": "shadow_learning_session_not_ready",
        }

        shown = await options.async_step_shadow_learning_result()

        self.assertEqual(shown["type"], "form")
        self.assertEqual(shown["step_id"], "shadow_learning_result")
        hint = shown["description_placeholders"]["control_discovery_hint"]
        self.assertIn("couldn't finish", hint)
        self.assertNotIn("No controls were found", hint)

    async def test_control_discovery_empty_result_can_create_support_package(self) -> None:
        options = self._wizard_options_flow()
        options._shadow_learning_state["session"] = {
            "session_id": "empty-run",
            "trace_path": "/config/eybond_local/shadow_learning_traces/empty.jsonl",
        }
        options._shadow_learning_state["orchestration"] = {
            "planned_write_count": 1,
            "executed_result_count": 1,
            "sent_count": 1,
            "degraded_count": 1,
            "results": [{"field_id": "sys_eybond_ctrl_53", "reason": "session_not_ready"}],
            "correlation": {
                "matched_count": 0,
                "unmatched_attempt_count": 0,
                "degraded_attempt_count": 1,
            },
        }
        exported: dict[str, Any] = {}
        published: list[dict[str, Any]] = []

        async def _fake_export(**kwargs):
            exported.update(kwargs)
            return "/config/eybond_local/support/empty.zip"

        def _fake_publish(**kwargs):
            published.append(kwargs)
            values = build_shadow_learning_runtime_values(**kwargs)
            options._config_entry.runtime_data.data.values.update(values)
            return dict(values["shadow_learning_artifacts"])

        options._config_entry.runtime_data.publish_shadow_learning_artifacts = (
            _fake_publish
        )
        options._config_entry.runtime_data.async_export_support_package_with_cloud_refresh = (
            _fake_export
        )

        shown = await options.async_step_shadow_learning_result()
        self.assertEqual(shown["type"], "form")
        self.assertEqual(shown["step_id"], "shadow_learning_result")
        self.assertIn("result_action", shown["data_schema"].schema)

        result = await options.async_step_shadow_learning_result(
            {"result_action": "create_support_package"}
        )

        self.assertEqual(result["type"], "form")
        self.assertEqual(result["step_id"], "shadow_learning_result")
        self.assertEqual(exported.get("wants_refresh"), False)
        self.assertEqual(
            options._shadow_learning_state["support_package_path"],
            "/config/eybond_local/support/empty.zip",
        )
        self.assertTrue(published)
        self.assertEqual(
            options._config_entry.runtime_data.data.values[
                "shadow_learning_orchestration"
            ]["degraded_count"],
            1,
        )

    async def test_control_discovery_full_path_never_persists_credentials(self) -> None:
        options = self._wizard_options_flow()

        await options.async_step_shadow_learning(
            {"learning_method": LEARNING_METHOD_ACTIVE_CORRELATION}
        )
        await options.async_step_shadow_learning_source(
            {"learning_source": "smartess"}
        )
        await options.async_step_shadow_learning_consent(
            {"shadow_learning_confirm_cloud_write": True}
        )
        progress = await options.async_step_shadow_learning_credentials(
            {"username": "demo", "password": "secret"}
        )
        self.assertEqual(progress["type"], "progress")
        # Let the placeholder runner finish, then complete the progress step.
        await options._shadow_learning_state["wizard_progress_task"]
        done = await options.async_step_shadow_learning_progress()
        self.assertEqual(done["next_step_id"], "shadow_learning_review")

        await options.async_step_shadow_learning_review({})
        await options.async_step_shadow_learning_result({})

        self.assertNotIn("username", options._config_entry.options)
        self.assertNotIn("password", options._config_entry.options)
        self.assertNotIn("username", options._config_entry.data)
        self.assertNotIn("password", options._config_entry.data)
        self.assertNotIn("wizard_credentials", options._shadow_learning_state)

    async def test_control_discovery_result_offers_apply_for_learned_reads_only(self) -> None:
        # Read-learning closes the loop: when the session learned read sensors
        # but no controls were selected, the result screen must still offer
        # Apply (the schema overlay carrying the reads activates regardless).
        options = self._wizard_options_flow()
        options._shadow_learning_state["overlay"] = {
            "manifest": {"review_model": build_learned_control_review_model([])},
            "profile_name": "learned/p.json",
            "schema_name": "learned/s.json",
            "generated_read_count": 4,
        }

        recorded: dict[str, Any] = {}

        async def _fake_activate(*, profile_name, register_schema_name, selection=None):
            recorded["called"] = True
            recorded["selection"] = selection
            return {"scope": "device", "profile_name": profile_name}

        options._config_entry.runtime_data.async_activate_device_scoped_overlay = (
            _fake_activate
        )

        shown = await options.async_step_shadow_learning_result()
        self.assertEqual(shown["type"], "form")
        # The reads-only body reports the learned read count.
        self.assertIn("4", shown["description_placeholders"]["control_discovery_hint"])

        done = await options.async_step_shadow_learning_result(
            {"result_action": "activate_selected"}
        )
        # Activate is reachable with zero controls: the overlay schema (reads)
        # was activated, and the confirmation mentions the read sensors.
        self.assertTrue(recorded.get("called"))
        self.assertIn("4", done["description_placeholders"]["control_discovery_hint"])

    async def test_control_discovery_result_activates_selected_controls(self) -> None:
        # EYB-REF-047 (closes F1): the guided result step must actually activate
        # exactly the controls the user selected on the review screen — not just
        # store them in flow state and discard them at the end of the wizard.
        options = self._wizard_options_flow()
        self._seed_control_discovery_review(options)
        # The automatic runner records the generated overlay's profile/schema
        # names; the seed helper only embeds the review model, so add them.
        options._shadow_learning_state["overlay"].update(
            {"profile_name": "learned/p.json", "schema_name": "learned/s.json"}
        )
        # User keeps the normal control and leaves the risky one off.
        await options.async_step_shadow_learning_review(
            {"enabled_controls": ["learned_backlight_700"]}
        )

        recorded: dict[str, Any] = {}

        async def _fake_activate(*, profile_name, register_schema_name, selection=None):
            recorded["profile_name"] = profile_name
            recorded["register_schema_name"] = register_schema_name
            recorded["selection"] = selection
            return {
                "scope": "device",
                "profile_name": profile_name,
                **(selection or {}),
            }

        options._config_entry.runtime_data.async_activate_device_scoped_overlay = (
            _fake_activate
        )

        # The result screen offers the activate / support / close actions.
        shown = await options.async_step_shadow_learning_result()
        self.assertEqual(shown["type"], "form")
        self.assertEqual(shown["step_id"], "shadow_learning_result")
        self.assertIn("result_action", shown["data_schema"].schema)

        done = await options.async_step_shadow_learning_result(
            {"result_action": "activate_selected"}
        )

        # The guided flow activated the device-scoped overlay with exactly the
        # user's selection: only the enabled control, carrying its user label.
        self.assertEqual(recorded["profile_name"], "learned/p.json")
        self.assertEqual(recorded["register_schema_name"], "learned/s.json")
        self.assertEqual(
            recorded["selection"]["selected_control_keys"], ["learned_backlight_700"]
        )
        selected = {c["key"]: c for c in recorded["selection"]["selected_controls"]}
        self.assertEqual(selected["learned_backlight_700"]["label"], "Backlight Control")
        excluded_keys = {c["key"] for c in recorded["selection"]["excluded_controls"]}
        self.assertIn("learned_reset_690", excluded_keys)
        # The activation is recorded, and applying confirms on the same screen
        # instead of bouncing back to the menu (the user leaves deliberately).
        self.assertEqual(
            options._shadow_learning_state["activation"]["scope"], "device"
        )
        self.assertEqual(done["type"], "form")
        self.assertEqual(done["step_id"], "shadow_learning_result")
        self.assertIn(
            "added to Home Assistant",
            done["description_placeholders"]["control_discovery_hint"],
        )

    async def test_control_discovery_result_activates_selected_read_sensors(self) -> None:
        options = self._wizard_options_flow()
        self._seed_control_discovery_review(
            options,
            capabilities=[],
            learned_reads=[
                {
                    "key": "learned_read_344",
                    "register": 344,
                    "title": "Output 2 Cut-Off SOC Status",
                    "kind": "numeric",
                    "spec_set": "config",
                },
                {
                    "key": "learned_read_239",
                    "register": 239,
                    "title": "Output 2 Apparent Power",
                    "kind": "numeric",
                    "spec_set": "live",
                },
            ],
        )
        options._shadow_learning_state["overlay"].update(
            {"profile_name": "learned/p.json", "schema_name": "learned/s.json"}
        )
        await options.async_step_shadow_learning_review(
            {"enabled_read_sensors": ["learned_read_344"]}
        )

        recorded: dict[str, Any] = {}

        async def _fake_activate(*, profile_name, register_schema_name, selection=None):
            recorded["selection"] = selection
            return {"scope": "device", "profile_name": profile_name, **(selection or {})}

        options._config_entry.runtime_data.async_activate_device_scoped_overlay = (
            _fake_activate
        )

        await options.async_step_shadow_learning_result(
            {"result_action": "activate_selected"}
        )

        self.assertEqual(
            recorded["selection"]["selected_read_sensor_keys"], ["learned_read_344"]
        )
        self.assertEqual(recorded["selection"]["selected_control_keys"], [])
        excluded = {
            item["key"] for item in recorded["selection"]["excluded_read_sensors"]
        }
        self.assertEqual(excluded, {"learned_read_239"})

    async def test_control_discovery_result_creates_support_package(self) -> None:
        # The secondary result action exports a support package without a live
        # SmartESS refresh, preserves the reviewed selection for support evidence,
        # and keeps the user on the result screen without activating runtime controls.
        options = self._wizard_options_flow()
        self._seed_control_discovery_review(options)
        options._shadow_learning_state["overlay"].update(
            {"profile_name": "learned/p.json", "schema_name": "learned/s.json"}
        )
        await options.async_step_shadow_learning_review(
            {"enabled_controls": ["learned_backlight_700"]}
        )

        exported: dict[str, Any] = {}

        async def _fake_export(**kwargs):
            exported.update(kwargs)
            return "/config/eybond_local/support/eybond_support.zip"

        published: list[dict[str, Any]] = []

        def _fake_publish(**kwargs):
            published.append(kwargs)
            values = build_shadow_learning_runtime_values(**kwargs)
            options._config_entry.runtime_data.data.values.update(values)
            return dict(values["shadow_learning_artifacts"])

        async def _unexpected_activate(**_kwargs):
            raise AssertionError("support export must not activate learned controls")

        options._config_entry.runtime_data.publish_shadow_learning_artifacts = (
            _fake_publish
        )
        options._config_entry.runtime_data.async_activate_device_scoped_overlay = (
            _unexpected_activate
        )
        options._config_entry.runtime_data.async_export_support_package_with_cloud_refresh = (
            _fake_export
        )

        result = await options.async_step_shadow_learning_result(
            {"result_action": "create_support_package"}
        )

        self.assertEqual(
            options._shadow_learning_state["support_package_path"],
            "/config/eybond_local/support/eybond_support.zip",
        )
        # No live SmartESS operation: the export is requested without a refresh.
        self.assertEqual(exported.get("wants_refresh"), False)
        self.assertEqual(exported.get("smartess_username"), "")
        self.assertTrue(published)
        activation = options._config_entry.runtime_data.data.values[
            "shadow_learning_activation"
        ]
        self.assertEqual(activation["status"], "review_selected")
        self.assertFalse(activation["active"])
        self.assertEqual(
            activation["selected_control_keys"], ["learned_backlight_700"]
        )
        selected = {item["key"]: item for item in activation["selected_controls"]}
        excluded = {item["key"]: item for item in activation["excluded_controls"]}
        self.assertEqual(selected["learned_backlight_700"]["label"], "Backlight Control")
        self.assertIn("learned_reset_690", excluded)
        # The result screen is re-rendered so the user can still enable controls.
        self.assertEqual(result["type"], "form")
        self.assertEqual(result["step_id"], "shadow_learning_result")

    async def test_control_discovery_result_activation_failure_surfaces_error(self) -> None:
        # When activation cannot proceed (here: the overlay has no generated
        # profile/schema), the failure is surfaced as a plain form error and the
        # wizard stays on the result screen instead of raising or silently
        # returning to the menu.
        options = self._wizard_options_flow()
        self._seed_control_discovery_review(options)
        await options.async_step_shadow_learning_review(
            {"enabled_controls": ["learned_backlight_700"]}
        )

        result = await options.async_step_shadow_learning_result(
            {"result_action": "activate_selected"}
        )

        self.assertEqual(result["type"], "form")
        self.assertEqual(result["step_id"], "shadow_learning_result")
        self.assertEqual(result["errors"], {"base": "shadow_learning_failed"})

    async def test_control_discovery_intro_carries_friendly_hint_placeholder(self) -> None:
        # The intro screen is rendered from the plain-language hint placeholder,
        # not the legacy technical status table. Guards the translations wiring
        # (translations/*.json shadow_learning.description == {control_discovery_hint}).
        options = self._wizard_options_flow()

        result = await options.async_step_shadow_learning()

        self.assertEqual(result["type"], "form")
        hint = result["description_placeholders"].get("control_discovery_hint")
        self.assertTrue(hint)
        self.assertNotIn("{", hint)

    # ---- Automatic control-discovery runner (EYB-REF-041) ----

    async def test_shadow_learning_callbacks_use_public_coordinator_port(self) -> None:
        options = self._make_options_flow()
        observation = ShadowWriteObservation(
            register=7,
            values=(1,),
            function_code=16,
            devcode=None,
            devaddr=None,
            raw_payload_hex="",
        )
        calls: list[tuple[str, object]] = []

        class _Coordinator:
            @property
            def shadow_learning_runtime(self) -> ShadowLearningRuntimeFacade:
                return ShadowLearningRuntimeFacade(
                    runtime=self,
                    cloud_evidence_provider=lambda: None,
                )

            @staticmethod
            def shadow_learning_route_status() -> dict[str, object]:
                return ShadowLearningRouteStatus(
                    running=True,
                    collector_connected=True,
                    collector_protocol_ingress=True,
                    route_protocol_activity=True,
                    upstream_connected=True,
                    ready=True,
                ).to_mapping()

            @staticmethod
            def shadow_learning_write_observations() -> tuple:
                return ()

            @staticmethod
            def shadow_learning_observation_cursor() -> int:
                calls.append(("cursor", None))
                return 3

            @staticmethod
            def shadow_learning_observations_since(cursor: int):
                calls.append(("since", cursor))
                return (observation,)

            @staticmethod
            async def async_wait_for_shadow_learning_observations_since(
                cursor: int,
                *,
                timeout_seconds: float,
            ):
                calls.append(("wait", (cursor, timeout_seconds)))
                return (observation,)

            @staticmethod
            def shadow_learning_read_map_snapshot() -> dict[str, object]:
                calls.append(("read_map", None))
                return {"registers": {"7": [1]}}

        callbacks = options._shadow_learning_orchestrator_callbacks(_Coordinator())

        self.assertEqual(callbacks["observation_cursor"](), 3)
        self.assertEqual(callbacks["current_observations_since"](2), (observation,))
        self.assertEqual(
            await callbacks["wait_for_observations_since"](2, 0.25),
            (observation,),
        )
        self.assertEqual(
            callbacks["read_map_snapshot"](),
            {"registers": {"7": [1]}},
        )
        self.assertTrue(callbacks["is_session_ready"]())
        self.assertEqual(
            calls,
            [
                ("cursor", None),
                ("since", 2),
                ("wait", (2, 0.25)),
                ("read_map", None),
            ],
        )

    class _RunnerCoordinator:
        smartess_collector_pn = "E5000020000000"
        cloud_evidence_provider = "smartess"
        collector_cloud_family = "dtu_ess"
        effective_profile_name = "smg_modbus.json"
        effective_register_schema_name = "modbus_smg/models/smg_6200.json"

        def __init__(self, *, ready: bool = True) -> None:
            self.data = types.SimpleNamespace(values={})
            self.route_status = ShadowLearningRouteStatus(
                running=True,
                collector_connected=True,
                collector_protocol_ingress=True,
                upstream_connected=True,
                ready=ready,
            )
            self.started: list[dict] = []
            self.stopped: list[dict] = []
            self.published: list[dict] = []
            self.local_register_snapshot: LocalRegisterSnapshot | None = None
            self.latest_local_register_series: LocalRegisterSnapshotSeries | None = None
            self.local_register_overlay_context: LocalRegisterOverlayContext | None = None
            self.local_register_capture_calls = 0

        @property
        def shadow_learning_runtime(self) -> ShadowLearningRuntimeFacade:
            return ShadowLearningRuntimeFacade(
                runtime=self,
                cloud_evidence_provider=lambda: None,
            )

        def shadow_learning_route_status(self) -> dict[str, object]:
            return self.route_status.to_mapping()

        @staticmethod
        def shadow_learning_write_observations() -> tuple:
            return ()

        async def async_start_shadow_learning(self, **kwargs):
            self.started.append(kwargs)
            return {
                "status": "ready",
                "session_id": "auto-session",
                "trace_path": "/config/eybond_local/shadow_learning_traces/auto.jsonl",
            }

        async def async_stop_shadow_learning(self, **kwargs):
            self.stopped.append(kwargs)
            return {"status": "stopped", "restore_confirmed": True}

        async def async_capture_local_register_snapshot(self):
            self.local_register_capture_calls += 1
            return self.local_register_snapshot

        def publish_shadow_learning_artifacts(self, **kwargs):
            self.published.append(kwargs)
            return {}

    def _runner_options_flow(self, coordinator):
        """Build an options flow wired to run the automatic discovery pipeline.

        The expensive preflight/identity/observation helpers are stubbed the
        same way the advanced-path tests stub them, so each test focuses on the
        runner's orchestration, plan shape, and fail-closed cleanup.
        """

        options = self._make_options_flow()
        options._config_entry.runtime_data = coordinator

        async def _fake_preflight(_coordinator):
            return {
                "can_start": True,
                "blockers": [],
                "collector_pn": coordinator.smartess_collector_pn,
            }

        options._build_shadow_learning_preflight_snapshot = _fake_preflight
        options._shadow_learning_cloud_identity = lambda _coordinator: {
            "pn": "E50000200000000001",
            "sn": "E50000200000000001000001",
            "devcode": 2376,
            "devaddr": 1,
        }
        options._shadow_learning_state["wizard_credentials"] = {
            "username": "demo@example.com",
            "password": "cloud-secret",
        }
        options._shadow_learning_state["wizard_method"] = (
            LEARNING_METHOD_ACTIVE_CORRELATION
        )
        options._shadow_learning_state["wizard_source"] = (
            coordinator.cloud_evidence_provider
        )
        return options

    def _runner_cloud_patches(
        self,
        *,
        captured: dict,
        fetch_side_effect=None,
        orchestrate_side_effect=None,
        orchestration_override: dict | None = None,
    ):
        bundle = {
            "request": {
                "params": {
                    "pn": "E50000200000000001",
                    "sn": "E50000200000000001000001",
                    "devcode": 2376,
                    "devaddr": 1,
                }
            },
            "responses": {
                "device_settings": {
                    "dat": {
                        "field": [
                            {"id": "sys_eybond_ctrl_53", "item": [{"key": "0"}]}
                        ]
                    }
                }
            },
        }
        orchestration = orchestration_override or {
            "planned_write_count": 1,
            "executed_result_count": 1,
            "sent_count": 1,
            "error_count": 0,
            "degraded_count": 0,
            "leaked_count": 0,
            "unknown_field_count": 0,
            "results": [],
            "correlation": {"matched_count": 1, "unmatched_attempt_count": 0},
        }
        fetch_kwargs = {}
        if fetch_side_effect is not None:
            fetch_kwargs["side_effect"] = fetch_side_effect
        else:
            fetch_kwargs["return_value"] = bundle
        orchestrate_kwargs = (
            {"side_effect": orchestrate_side_effect}
            if orchestrate_side_effect is not None
            else {
                "side_effect": lambda **kwargs: captured.update(kwargs)
                or dict(orchestration)
            }
        )
        return (
            patch.object(
                cloud_control_discovery_module,
                "login_for_control_discovery",
                return_value=(
                    object(),
                    types.SimpleNamespace(
                        token="token",
                        secret="secret",
                        uid="uid",
                        usr="usr",
                        role=1,
                        expire=1,
                    ),
                ),
            ),
            patch.object(
                cloud_control_discovery_module,
                "fetch_control_discovery_bundle_for_collector",
                **fetch_kwargs,
            ),
            patch.object(
                cloud_control_discovery_module,
                "async_orchestrate_shadow_learning_settings",
                **orchestrate_kwargs,
            ),
            patch.object(
                options_shadow_run_module,
                "generate_shadow_learning_overlay_drafts",
                return_value=types.SimpleNamespace(
                    profile_path=Path("/config/eybond_local/profiles/learned/p.json"),
                    schema_path=Path("/config/eybond_local/register_schemas/learned/s.json"),
                    generated_capability_count=2,
                    skipped_duplicate_count=0,
                    generated_read_count=3,
                    manifest={
                        "output": {
                            "profile_name": "learned/p.json",
                            "schema_name": "learned/s.json",
                        }
                    },
                ),
            ),
        )

    async def test_control_discovery_runner_passes_bounded_live_route_waiter(self) -> None:
        # Read-only cloud metadata may be fetched while the short-lived collector
        # route is between connections. Actual control remains fail-closed in the
        # orchestrator, which receives both the strict live predicate and a
        # bounded waiter for the next safe route window.
        coordinator = self._RunnerCoordinator(ready=False)
        coordinator.route_status = ShadowLearningRouteStatus(
            running=True,
            collector_connected=True,
            collector_protocol_ingress=True,
            upstream_connected=False,
            ready=False,
        )
        options = self._runner_options_flow(coordinator)
        captured: dict = {}
        login_p, fetch_p, orchestrate_p, overlay_p = self._runner_cloud_patches(captured=captured)

        with (
            login_p as login_mock,
            fetch_p as fetch_mock,
            orchestrate_p as orchestrate_mock,
            overlay_p,
            patch.object(
                options_shadow_runtime_module,
                "_SHADOW_CONTROL_ROUTE_WINDOW_WAIT",
                0.01,
            ),
        ):
            await options._async_run_control_discovery()
            self.assertFalse(captured["is_session_ready"]())
            self.assertFalse(await captured["wait_until_session_ready"]())

        # The bundle helper owns its metadata login; this explicit login is the
        # fresh control-dispatch session created after the bundle completes.
        self.assertEqual(login_mock.call_count, 1)
        fetch_mock.assert_called_once()
        orchestrate_mock.assert_called_once()
        self.assertEqual(len(coordinator.stopped), 1)

    async def test_control_discovery_runner_uses_valuecloud_provider_runner(self) -> None:
        coordinator = self._RunnerCoordinator(ready=True)
        coordinator.cloud_evidence_provider = "valuecloud"
        coordinator.collector_cloud_family = "valuecloud_at"
        coordinator.effective_profile_name = "eybond_g_ascii/base.json"
        coordinator.effective_register_schema_name = "eybond_g_ascii/base.json"
        options = self._runner_options_flow(coordinator)
        captured: dict = {}
        login_p, fetch_p, orchestrate_p, overlay_p = self._runner_cloud_patches(captured=captured)
        valuecloud_session = types.SimpleNamespace(token="vc-token", secret="vc-secret", auth="")
        valuecloud_bundle = {
            "request": {
                "params": {
                    "pn": "A0000000000001",
                    "sn": "DEV19E27F1B2345DA3",
                    "devcode": 2506,
                    "devaddr": 1,
                }
            },
            "normalized": {
                "batch_control": {
                    "groups": [
                        {
                            "controlItemId": 10,
                            "parameters": [
                                {
                                    "id": "cltd_lcd_backlight",
                                    "detailsId": 20,
                                    "order": 3,
                                    "name": "LCD Backlight",
                                    "readwrite": "RW",
                                    "item": {"1": "On"},
                                }
                            ],
                        }
                    ]
                }
            },
        }

        with (
            login_p as smartess_login_mock,
            fetch_p as smartess_fetch_mock,
            orchestrate_p as smartess_orchestrate_mock,
            overlay_p as overlay_mock,
            patch.object(
                cloud_control_discovery_module.valuecloud_cloud_module,
                "login_with_password",
                return_value=(object(), valuecloud_session),
            ) as valuecloud_login_mock,
            patch.object(
                cloud_control_discovery_module.valuecloud_cloud_module,
                "fetch_device_bundle_for_collector_with_session",
                return_value=valuecloud_bundle,
            ) as valuecloud_fetch_mock,
            patch.object(
                cloud_control_discovery_module,
                "async_orchestrate_valuecloud_shadow_learning",
                side_effect=lambda **kwargs: captured.update(kwargs)
                or {
                    "planned_write_count": 1,
                    "executed_result_count": 1,
                    "sent_count": 1,
                    "captured_not_applied_count": 1,
                    "error_count": 0,
                    "degraded_count": 0,
                    "leaked_count": 0,
                    "unknown_field_count": 0,
                    "results": [],
                    "correlation": {
                        "matched_count": 1,
                        "matched": [
                            {
                                "field_id": "cltd_lcd_backlight",
                                "field_name": "LCD Backlight",
                                "requested_value": "1",
                                "value_label": "On",
                                "value_source": "choice",
                                "observation": {
                                    "register": -1,
                                    "values": [],
                                    "protocol": "eybond_g_ascii",
                                    "command": "PBL",
                                    "value": "1",
                                },
                            }
                        ],
                        "unmatched_attempt_count": 0,
                        "unmatched_write_count": 0,
                    },
                    "read_map": {},
                },
            ) as valuecloud_orchestrate_mock,
        ):
            await options._async_run_control_discovery()

        self.assertEqual(len(coordinator.started), 1)
        smartess_login_mock.assert_not_called()
        smartess_fetch_mock.assert_not_called()
        smartess_orchestrate_mock.assert_not_called()
        valuecloud_login_mock.assert_called_once()
        valuecloud_fetch_mock.assert_called_once()
        valuecloud_orchestrate_mock.assert_called_once()
        overlay_mock.assert_called_once()
        self.assertEqual(captured["session"], valuecloud_session)
        self.assertEqual(captured["batch_control"], valuecloud_bundle["normalized"]["batch_control"])
        self.assertEqual(captured["pn"], "A0000000000001")
        self.assertEqual(captured["devcode"], 2506)
        self.assertEqual(options._shadow_learning_state["discovery"]["status"], "ok")

    async def test_control_discovery_runner_runs_full_pipeline_without_preview_plan(self) -> None:
        coordinator = self._RunnerCoordinator(ready=True)
        options = self._runner_options_flow(coordinator)
        captured: dict = {}
        login_p, fetch_p, orchestrate_p, overlay_p = self._runner_cloud_patches(captured=captured)

        with login_p, fetch_p, orchestrate_p as orchestrate_mock, overlay_p as overlay_mock:
            await options._async_run_control_discovery()

        # One automatic pass: session started fail-closed, learning run, overlay
        # drafted, session stopped — with no preview-plan/action step in between.
        self.assertEqual(len(coordinator.started), 1)
        self.assertEqual(coordinator.started[0].get("allow_ack_writes"), False)
        self.assertEqual(coordinator.local_register_capture_calls, 0)
        orchestrate_mock.assert_called_once()
        overlay_mock.assert_called_once()
        self.assertEqual(len(coordinator.stopped), 1)

        # The plan is built internally and is bounded: all fields, every choice value swept (so
        # the overlay learns each control's value set) AND numeric fields included (one
        # observe-only write each to learn their register + display divisor), capped field count.
        self.assertEqual(list(captured["field_ids"]), [])
        self.assertTrue(captured["include_numeric"])
        self.assertTrue(captured["all_choice_values"])
        self.assertEqual(
            captured["max_fields"],
            options_shadow_run_module.CONTROL_DISCOVERY_AUTOMATIC_MAX_FIELDS,
        )
        self.assertGreater(options_shadow_run_module.CONTROL_DISCOVERY_AUTOMATIC_MAX_FIELDS, 0)

        self.assertEqual(options._shadow_learning_state["discovery"]["status"], "ok")
        self.assertEqual(
            options._shadow_learning_state["overlay"]["generated_capability_count"], 2
        )

    async def test_dessmonitor_runner_never_touches_shadow_route(self) -> None:
        coordinator = self._RunnerCoordinator(ready=False)
        options = self._runner_options_flow(coordinator)
        options._shadow_learning_state["wizard_method"] = LEARNING_METHOD_READ_ONLY_EVIDENCE
        options._shadow_learning_state["wizard_source"] = "dessmonitor"
        evidence = {
            "source": "dessmonitor",
            "metadata_field_count": 2,
            "telemetry_fields": [
                {
                    "field_id": "pv_voltage",
                    "title": "PV Voltage",
                    "value": "230.1",
                    "unit": "V",
                }
            ],
        }
        outcome = CloudLearningOutcome(
            identity={"pn": coordinator.smartess_collector_pn},
            result={
                "source": "dessmonitor",
                "metadata_only": True,
                "metadata_field_count": 2,
                "planned_write_count": 0,
                "executed_result_count": 0,
                "sent_count": 0,
                "leaked_count": 0,
                "degraded_count": 0,
            },
            read_bindings=None,
            metadata_evidence=evidence,
        )

        with (
            patch.object(asyncio, "sleep", new=AsyncMock()),
            patch.object(
                cloud_read_only_workflow_module.ReadOnlyEvidenceWorkflowRunner,
                "async_run",
                new=AsyncMock(return_value=outcome),
            ) as run_mock,
            patch.object(
                options,
                "_build_shadow_learning_preflight_snapshot",
                new=AsyncMock(side_effect=AssertionError("active preflight used")),
            ),
            patch.object(
                options,
                "_shadow_learning_runtime",
                side_effect=AssertionError("shadow runtime used"),
            ),
            patch.object(
                options,
                "_shadow_learning_cloud_identity",
                side_effect=AssertionError("active identity fallback used"),
            ),
        ):
            await options._async_run_control_discovery()

        run_mock.assert_awaited_once()
        kwargs = run_mock.await_args.kwargs
        self.assertEqual(kwargs["fallback_identity"], {})
        self.assertEqual(kwargs["orchestrator_callbacks"], {})
        self.assertEqual(coordinator.started, [])
        self.assertEqual(coordinator.stopped, [])
        self.assertEqual(options._shadow_learning_state["cloud_metadata"], evidence)
        self.assertEqual(
            options._shadow_learning_state["discovery"],
            {"status": "ok", "found_controls": 0, "found_metadata": 2},
        )

    async def test_smartclient_pipeline_keeps_exact_source_and_publishes_passive_evidence(self) -> None:
        from custom_components.eybond_local.smartclient_cloud import SmartClientEvidence, SmartClientIdentity
        from custom_components.eybond_local.support import smartclient_learning

        coordinator = self._RunnerCoordinator(ready=False)
        # Real collector-only RuntimeSnapshot has a typed empty frame, not a
        # missing telemetry attribute. Recognized cloud fields must not require
        # a local driver (issue #23).
        coordinator.effective_profile_name = ""
        coordinator.effective_register_schema_name = ""
        coordinator.data.telemetry = TypedTelemetryFrame(driver_key="", points=())
        options = self._runner_options_flow(coordinator)
        options._shadow_learning_state.update(
            {"wizard_method": LEARNING_METHOD_READ_ONLY_EVIDENCE, "wizard_source": "smartclient"}
        )
        bundle = SmartClientEvidence(
            identity=SmartClientIdentity(coordinator.smartess_collector_pn, "PV0001", 767, 1),
            telemetry=({"field_id": "2", "title": "PV Voltage", "unit": "V", "value": "220.5"},),
            controls=(), device_info={}, history={}, raw_packet={},
            unavailable_actions=(), action_errors=(), fetched_at="2026-09-08T09:00:00+00:00",
        )
        with patch.object(smartclient_learning, "fetch_read_only_evidence", return_value=bundle):
            await options._async_run_control_discovery()
        self.assertEqual(coordinator.started, [])
        self.assertEqual(coordinator.stopped, [])
        self.assertTrue(coordinator.published)
        self.assertEqual(options._shadow_learning_state["discovery"]["status"], "ok")
        self.assertEqual(options._shadow_learning_state["cloud_metadata"]["source"], "smartclient")
        self.assertNotIn("local_coverage", options._shadow_learning_state["cloud_metadata"])
        self.assertGreater(
            options._shadow_learning_state["cloud_metadata"]["semantic_report"]["read_candidate_count"], 0
        )
        self.assertNotIn("demo@example.com", str(coordinator.published))
        self.assertNotIn("wizard_credentials", str(coordinator.published))
        self.assertEqual(options._shadow_learning_state.get("overlay", {}), {})

    def test_cloud_coverage_drops_stale_driver_report_without_local_driver(self) -> None:
        from custom_components.eybond_local.flows.options.shadow_run import _metadata_with_local_coverage

        evidence = {"source": "smartclient", "local_coverage": {"driver_key": "smg"}}
        for telemetry in (None, TypedTelemetryFrame(driver_key="", points=())):
            with self.subTest(telemetry=telemetry):
                enriched = _metadata_with_local_coverage(evidence, telemetry)
                self.assertNotIn("local_coverage", enriched)
                self.assertEqual(enriched["source"], "smartclient")
                self.assertIn("local_coverage", evidence)

    async def test_cloud_learning_failure_exports_phase_without_exception_secrets(self) -> None:
        for partial_result in (False, True):
            with self.subTest(partial_result=partial_result):
                coordinator = self._RunnerCoordinator(ready=False)
                options = self._runner_options_flow(coordinator)
                options._shadow_learning_state.update({
                    "wizard_method": LEARNING_METHOD_READ_ONLY_EVIDENCE,
                    "wizard_source": "smartclient",
                    "progress": {"stage": "building", "fraction": 0.82},
                })
                if partial_result:
                    options._shadow_learning_state["orchestration"] = {
                        "source": "smartclient", "metadata_only": True,
                        "metadata_evidence": {"telemetry_fields": [{"title": "PV Voltage"}]},
                    }
                with (
                    patch.object(
                        options, "_async_execute_control_discovery",
                        new=AsyncMock(side_effect=ValueError("https://private.invalid/?password=cloud-secret")),
                    ),
                    self.assertLogs("custom_components.eybond_local.flows.options.shadow_run", level="ERROR") as logs,
                ):
                    await options._async_run_control_discovery()
                artifact = coordinator.published[-1]["orchestration"]
                self.assertEqual(artifact["failure"], {
                    "reason": "control_discovery_failure_generic",
                    "learning_source": "smartclient", "stage": "building",
                    "exception_category": "ValueError",
                })
                if partial_result:
                    self.assertIn("metadata_evidence", artifact)
                self.assertNotIn("private.invalid", str(coordinator.published) + str(logs.output))
                self.assertNotIn("cloud-secret", str(coordinator.published) + str(logs.output))
                self.assertEqual(coordinator.started, [])
                self.assertEqual(coordinator.stopped, [])

    async def test_dessmonitor_runner_records_typed_local_semantic_coverage(self) -> None:
        coordinator = self._RunnerCoordinator(ready=False)
        coordinator.data.telemetry = TypedTelemetryFrame(
            driver_key="smg",
            points=(
                TelemetryPoint(
                    key="pv_voltage",
                    value=230.1,
                    freshness=TelemetryFreshness.FRESH,
                ),
            ),
        )
        options = self._runner_options_flow(coordinator)
        options._shadow_learning_state["wizard_method"] = LEARNING_METHOD_READ_ONLY_EVIDENCE
        options._shadow_learning_state["wizard_source"] = "dessmonitor"
        semantic_report = {
            "schema_version": 1,
            "authority": "semantic_hint_only",
            "local_mapping_proven": False,
            "provider_id": "smartess",
            "source_id": "dessmonitor",
            "recognized_count": 1,
            "read_candidate_count": 1,
            "unit_conflict_count": 0,
            "unknown_count": 0,
            "control_metadata_count": 0,
            "observations": [
                {
                    "field_kind": "reading",
                    "field_id": "pv_voltage",
                    "title": "PV Voltage",
                    "value": "230.1",
                    "observed_unit": "V",
                    "source_action": "querySPDeviceLastData",
                    "status": "recognized",
                    "semantic_key": "pv_voltage",
                    "canonical_title": "PV Voltage",
                    "semantic_kind": "read",
                    "expected_unit": "V",
                    "device_class": "voltage",
                    "state_class": "measurement",
                    "local_mapping": "unproven",
                }
            ],
        }
        evidence = {
            "source": "dessmonitor",
            "metadata_field_count": 1,
            "semantic_report": semantic_report,
        }
        outcome = CloudLearningOutcome(
            identity={"pn": coordinator.smartess_collector_pn},
            result={
                "source": "dessmonitor",
                "metadata_only": True,
                "metadata_field_count": 1,
                "planned_write_count": 0,
                "executed_result_count": 0,
                "sent_count": 0,
                "leaked_count": 0,
                "degraded_count": 0,
            },
            metadata_evidence=evidence,
        )

        with patch.object(
            cloud_read_only_workflow_module.ReadOnlyEvidenceWorkflowRunner,
            "async_run",
            new=AsyncMock(return_value=outcome),
        ):
            await options._async_run_control_discovery()

        stored = options._shadow_learning_state["cloud_metadata"]
        coverage = stored["local_coverage"]
        self.assertEqual(coverage["authority"], "runtime_semantic_presence_only")
        self.assertIs(coverage["local_mapping_proven"], False)
        self.assertEqual(coverage["driver_key"], "smg")
        self.assertEqual(coverage["available_count"], 1)
        self.assertEqual(coverage["items"][0]["status"], "available_fresh")
        self.assertNotIn("230.1", str(coverage))
        self.assertNotIn("register", str(coverage).casefold())
        self.assertEqual(coordinator.started, [])
        self.assertEqual(coordinator.stopped, [])

    async def test_dessmonitor_records_exact_pn_local_register_snapshot(self) -> None:
        coordinator = self._RunnerCoordinator(ready=False)
        coordinator.local_register_snapshot = LocalRegisterSnapshot(
            collector_pn=coordinator.smartess_collector_pn,
            driver_key="smg",
            started_at="2026-08-22T10:00:00+00:00",
            completed_at="2026-08-22T10:00:02+00:00",
            planned_block_count=1,
            failed_block_count=0,
            blocks=(
                LocalRegisterBlockObservation(
                    plan=LocalRegisterReadPlan(
                        devcode=2376,
                        collector_addr=1,
                        device_addr=1,
                        function=3,
                        start=300,
                        count=2,
                    ),
                    observed_at="2026-08-22T10:00:01+00:00",
                    values=(2305, 500),
                ),
            ),
        )
        options = self._runner_options_flow(coordinator)
        options._shadow_learning_state["wizard_method"] = LEARNING_METHOD_READ_ONLY_EVIDENCE
        options._shadow_learning_state["wizard_source"] = "dessmonitor"
        evidence = {"source": "dessmonitor", "metadata_field_count": 1}
        outcome = CloudLearningOutcome(
            identity={"pn": coordinator.smartess_collector_pn},
            result={
                "source": "dessmonitor",
                "metadata_only": True,
                "metadata_field_count": 1,
                "planned_write_count": 0,
                "executed_result_count": 0,
                "sent_count": 0,
                "leaked_count": 0,
                "degraded_count": 0,
            },
            read_bindings=None,
            metadata_evidence=evidence,
        )

        with patch.object(
            cloud_read_only_workflow_module.ReadOnlyEvidenceWorkflowRunner,
            "async_run",
            new=AsyncMock(return_value=outcome),
        ):
            await options._async_run_control_discovery()

        self.assertEqual(coordinator.local_register_capture_calls, 1)
        stored = options._shadow_learning_state["cloud_metadata"]
        snapshot = stored["local_register_snapshot"]
        self.assertEqual(snapshot["authority"], "live_local_wire_observation")
        self.assertIs(snapshot["cloud_mapping_proven"], False)
        self.assertEqual(snapshot["blocks"][0]["plan"]["function"], 3)
        self.assertEqual(snapshot["blocks"][0]["values"], [2305, 500])
        self.assertNotIn("read_bindings", stored)
        published = coordinator.published[-1]["orchestration"]
        self.assertEqual(
            published["metadata_evidence"]["local_register_snapshot"],
            snapshot,
        )
        self.assertEqual(coordinator.started, [])
        self.assertEqual(coordinator.stopped, [])

    async def test_dessmonitor_composes_completed_local_series_for_review_only(
        self,
    ) -> None:
        coordinator = self._RunnerCoordinator(ready=False)
        identity = CloudHistoryIdentity(
            pn=coordinator.smartess_collector_pn,
            sn="90000000000001",
            devcode=2376,
            devaddr=1,
        )
        history = CloudHistorySeries(
            provider_id="smartess",
            source_id="dessmonitor",
            field_kind=CLOUD_FIELD_KIND_CHART,
            identity=identity,
            source_action=DESSMONITOR_HISTORY_SOURCE_SOLE_CHART,
            series_key="pv_voltage",
            title="PV Voltage",
            unit="V",
            requested_date="2026-08-22",
            precision_minutes=5,
            timezone_offset_seconds=0,
            points=tuple(
                CloudHistoryPoint(
                    device_local_timestamp=(
                        f"2026-08-22 10:{index * 5:02d}:00"
                    ),
                    utc_timestamp=(
                        f"2026-08-22T10:{index * 5:02d}:00+00:00"
                    ),
                    value=f"{230 + index}.0",
                )
                for index in range(5)
            ),
        )
        collection = CloudHistoryCollection(
            provider_id="smartess",
            source_id="dessmonitor",
            identity=identity,
            requested_date="2026-08-22",
            timezone_offset_seconds=0,
            attempted_series_count=1,
            failed_series_count=0,
            budget_exhausted=False,
            series=(history,),
        )
        plan = LocalRegisterReadPlan(
            devcode=2376,
            collector_addr=1,
            device_addr=1,
            function=3,
            start=300,
            count=1,
        )
        snapshots = tuple(
            LocalRegisterSnapshot(
                collector_pn=coordinator.smartess_collector_pn,
                driver_key="smg",
                started_at=f"2026-08-22T10:{index * 5:02d}:05+00:00",
                completed_at=f"2026-08-22T10:{index * 5:02d}:15+00:00",
                planned_block_count=1,
                failed_block_count=0,
                blocks=(
                    LocalRegisterBlockObservation(
                        plan=plan,
                        observed_at=(
                            f"2026-08-22T10:{index * 5:02d}:10+00:00"
                        ),
                        values=((230 + index) * 10,),
                    ),
                ),
            )
            for index in range(5)
        )
        coordinator.latest_local_register_series = LocalRegisterSnapshotSeries(
            collector_pn=coordinator.smartess_collector_pn,
            driver_key="smg",
            sample_interval_seconds=300,
            snapshots=snapshots,
        )
        coordinator.local_register_overlay_context = LocalRegisterOverlayContext(
            collector_pn=coordinator.smartess_collector_pn,
            driver_key="smg",
            register_schema_name="modbus_smg/models/smg_6200.json",
            devcode=2376,
            collector_addr=1,
            device_addr=1,
            claimed_locations=(),
            existing_semantic_keys=(),
        )
        options = self._runner_options_flow(coordinator)
        options._shadow_learning_state["wizard_method"] = LEARNING_METHOD_READ_ONLY_EVIDENCE
        options._shadow_learning_state["wizard_source"] = "dessmonitor"
        evidence = {
            "source": "dessmonitor",
            "metadata_field_count": 1,
            "telemetry_fields": [
                {
                    "field_id": "pv_voltage",
                    "title": "PV Voltage",
                    "value": "234.0",
                    "unit": "V",
                }
            ],
            "history_collection": collection.to_record(),
        }
        outcome = CloudLearningOutcome(
            identity={"pn": coordinator.smartess_collector_pn},
            result={
                "source": "dessmonitor",
                "metadata_only": True,
                "metadata_field_count": 1,
                "planned_write_count": 0,
                "executed_result_count": 0,
                "sent_count": 0,
                "leaked_count": 0,
                "degraded_count": 0,
            },
            metadata_evidence=evidence,
        )

        with patch.object(
            cloud_read_only_workflow_module.ReadOnlyEvidenceWorkflowRunner,
            "async_run",
            new=AsyncMock(return_value=outcome),
        ):
            await options._async_run_control_discovery()

        stored = options._shadow_learning_state["cloud_metadata"]
        review = stored["local_history_review"]
        self.assertEqual(review["authority"], "review_composition_only")
        self.assertIs(review["read_only"], True)
        self.assertIs(review["local_mapping_proven"], False)
        self.assertIs(review["activation_allowed"], False)
        self.assertEqual(review["status"], "review_candidates_available")
        self.assertEqual(review["unique_candidate_count"], 1)
        self.assertEqual(
            review["verdicts"][0]["alignment_tolerance_seconds"],
            150,
        )
        representability = stored["local_history_representability"]
        self.assertEqual(
            representability["authority"],
            "current_context_review_only",
        )
        self.assertEqual(representability["representable_count"], 1)
        self.assertIs(representability["draft_generation_allowed"], False)
        self.assertIs(representability["activation_allowed"], False)
        draft_plan = stored["local_history_draft_plan"]
        self.assertEqual(
            draft_plan["authority"],
            "inactive_review_draft_plan_only",
        )
        self.assertEqual(draft_plan["item_count"], 1)
        self.assertIs(draft_plan["local_mapping_proven"], False)
        self.assertIs(draft_plan["draft_generation_allowed"], True)
        self.assertIs(draft_plan["activation_allowed"], False)
        self.assertEqual(
            draft_plan["items"][0]["candidate"]["location"],
            {
                "devcode": 2376,
                "collector_addr": 1,
                "device_addr": 1,
                "function": 3,
                "register": 300,
            },
        )
        self.assertNotIn("read_bindings", stored)
        self.assertNotIn("overlay", options._shadow_learning_state)
        self.assertIn(
            "review hints only",
            options._control_discovery_local_history_review_summary(),
        )
        review_markdown = options._control_discovery_metadata_markdown(
            options._control_discovery_metadata_fields()
        )
        self.assertIn("Local comparison candidates", review_markdown)
        self.assertIn("FC3", review_markdown)
        self.assertIn("register 300", review_markdown)
        self.assertIn("scale ÷10", review_markdown)
        self.assertIn("Current local-context compatibility", review_markdown)
        self.assertIn("exact current route", review_markdown)
        self.assertEqual(
            coordinator.published[-1]["orchestration"]["metadata_evidence"]
            ["local_history_review"],
            review,
        )
        self.assertEqual(
            coordinator.published[-1]["orchestration"]["metadata_evidence"]
            ["local_history_draft_plan"],
            draft_plan,
        )

        result = await options.async_step_shadow_learning_result()
        self.assertEqual(
            _schema_select_options(result["data_schema"], "result_action"),
            [
                "create_inactive_read_draft",
                "create_support_package",
                "done",
            ],
        )
        self.assertIn(
            "does not add entities",
            result["description_placeholders"]["control_discovery_hint"],
        )
        with patch.object(
            options_shadow_inactive_draft_module,
            "generate_inactive_cloud_local_read_schema_draft",
        ) as invalid_generate:
            invalid = await options.async_step_shadow_learning_result(
                {"result_action": object()}
            )
        invalid_generate.assert_not_called()
        self.assertEqual(invalid["type"], "form")
        self.assertEqual(invalid["errors"], {"result_action": "invalid_selection"})

        artifact = CloudLocalReadDraftArtifact(
            schema_name="learned/dessmonitor_review/device/review.json",
            schema_path=Path(
                "/config/eybond_local/register_schemas/learned/"
                "dessmonitor_review/device/review.json"
            ),
            generated_read_count=1,
            evidence_sha256="a" * 64,
            manifest={},
        )
        with patch.object(
            options_shadow_inactive_draft_module,
            "generate_inactive_cloud_local_read_schema_draft",
            return_value=artifact,
        ) as generate:
            generated = await options.async_step_shadow_learning_result(
                {"result_action": "create_inactive_read_draft"}
            )

        generate.assert_called_once()
        self.assertEqual(
            options._shadow_learning_state["inactive_read_draft"],
            {
                "schema_name": artifact.schema_name,
                "schema_path": str(artifact.schema_path),
                "generated_read_count": 1,
                "evidence_sha256": "a" * 64,
                "status": "inactive_review_required",
                "activation_allowed": False,
            },
        )
        self.assertIn(
            "Nothing was added",
            generated["description_placeholders"]["control_discovery_hint"],
        )

    async def test_dessmonitor_drops_untrusted_stale_local_history_review(
        self,
    ) -> None:
        coordinator = self._RunnerCoordinator(ready=False)
        coordinator.latest_local_register_series = object()
        options = self._runner_options_flow(coordinator)
        options._shadow_learning_state["wizard_method"] = LEARNING_METHOD_READ_ONLY_EVIDENCE
        options._shadow_learning_state["wizard_source"] = "dessmonitor"
        outcome = CloudLearningOutcome(
            identity={"pn": coordinator.smartess_collector_pn},
            result={
                "source": "dessmonitor",
                "metadata_only": True,
                "metadata_field_count": 1,
                "planned_write_count": 0,
                "executed_result_count": 0,
                "sent_count": 0,
                "leaked_count": 0,
                "degraded_count": 0,
            },
            metadata_evidence={
                "source": "dessmonitor",
                "metadata_field_count": 1,
                "local_history_review": {
                    "authority": "forged_mapping_authority",
                },
                "local_history_representability": {
                    "authority": "forged_activation_authority",
                },
                "local_history_draft_plan": {
                    "authority": "forged_draft_authority",
                },
            },
        )

        with patch.object(
            cloud_read_only_workflow_module.ReadOnlyEvidenceWorkflowRunner,
            "async_run",
            new=AsyncMock(return_value=outcome),
        ):
            await options._async_run_control_discovery()

        self.assertNotIn(
            "local_history_review",
            options._shadow_learning_state["cloud_metadata"],
        )
        self.assertNotIn(
            "local_history_representability",
            options._shadow_learning_state["cloud_metadata"],
        )
        self.assertNotIn(
            "local_history_draft_plan",
            options._shadow_learning_state["cloud_metadata"],
        )
        self.assertNotIn("overlay", options._shadow_learning_state)

    async def test_dessmonitor_rejects_foreign_local_register_snapshot(self) -> None:
        coordinator = self._RunnerCoordinator(ready=False)
        coordinator.local_register_snapshot = LocalRegisterSnapshot(
            collector_pn="V0000000000001",
            driver_key="smg",
            started_at="2026-08-22T10:00:00+00:00",
            completed_at="2026-08-22T10:00:02+00:00",
            planned_block_count=1,
            failed_block_count=0,
            blocks=(
                LocalRegisterBlockObservation(
                    plan=LocalRegisterReadPlan(
                        devcode=2376,
                        collector_addr=1,
                        device_addr=1,
                        function=3,
                        start=300,
                        count=1,
                    ),
                    observed_at="2026-08-22T10:00:01+00:00",
                    values=(2305,),
                ),
            ),
        )
        options = self._runner_options_flow(coordinator)
        options._shadow_learning_state["wizard_method"] = LEARNING_METHOD_READ_ONLY_EVIDENCE
        options._shadow_learning_state["wizard_source"] = "dessmonitor"
        evidence = {"source": "dessmonitor", "metadata_field_count": 1}
        outcome = CloudLearningOutcome(
            identity={"pn": coordinator.smartess_collector_pn},
            result={
                "source": "dessmonitor",
                "metadata_only": True,
                "metadata_field_count": 1,
                "planned_write_count": 0,
                "executed_result_count": 0,
                "sent_count": 0,
                "leaked_count": 0,
                "degraded_count": 0,
            },
            metadata_evidence=evidence,
        )

        with patch.object(
            cloud_read_only_workflow_module.ReadOnlyEvidenceWorkflowRunner,
            "async_run",
            new=AsyncMock(return_value=outcome),
        ):
            await options._async_run_control_discovery()

        self.assertEqual(coordinator.local_register_capture_calls, 1)
        self.assertNotIn(
            "local_register_snapshot",
            options._shadow_learning_state["cloud_metadata"],
        )
        self.assertNotIn(
            "local_register_snapshot",
            coordinator.published[-1]["orchestration"]["metadata_evidence"],
        )

    async def test_dessmonitor_local_snapshot_failure_is_supplemental(self) -> None:
        coordinator = self._RunnerCoordinator(ready=False)
        coordinator.async_capture_local_register_snapshot = AsyncMock(
            side_effect=ConnectionError("private local wire detail")
        )
        options = self._runner_options_flow(coordinator)
        options._shadow_learning_state["wizard_method"] = LEARNING_METHOD_READ_ONLY_EVIDENCE
        options._shadow_learning_state["wizard_source"] = "dessmonitor"
        evidence = {"source": "dessmonitor", "metadata_field_count": 1}
        outcome = CloudLearningOutcome(
            identity={"pn": coordinator.smartess_collector_pn},
            result={
                "source": "dessmonitor",
                "metadata_only": True,
                "metadata_field_count": 1,
                "planned_write_count": 0,
                "executed_result_count": 0,
                "sent_count": 0,
                "leaked_count": 0,
                "degraded_count": 0,
            },
            metadata_evidence=evidence,
        )

        with patch.object(
            cloud_read_only_workflow_module.ReadOnlyEvidenceWorkflowRunner,
            "async_run",
            new=AsyncMock(return_value=outcome),
        ) as run_mock:
            await options._async_run_control_discovery()

        coordinator.async_capture_local_register_snapshot.assert_awaited_once()
        run_mock.assert_awaited_once()
        self.assertEqual(
            options._shadow_learning_state["cloud_metadata"],
            evidence,
        )
        self.assertNotIn(
            "private local wire detail",
            str(options._shadow_learning_state),
        )
        self.assertEqual(coordinator.started, [])
        self.assertEqual(coordinator.stopped, [])

    async def test_dessmonitor_local_snapshot_cancellation_propagates(self) -> None:
        coordinator = self._RunnerCoordinator(ready=False)
        entered = asyncio.Event()
        never = asyncio.Event()

        async def _capture():
            entered.set()
            await never.wait()

        coordinator.async_capture_local_register_snapshot = _capture
        options = self._runner_options_flow(coordinator)
        options._shadow_learning_state["wizard_method"] = LEARNING_METHOD_READ_ONLY_EVIDENCE
        options._shadow_learning_state["wizard_source"] = "dessmonitor"

        with (
            patch.object(asyncio, "sleep", new=AsyncMock()),
            patch.object(
                cloud_read_only_workflow_module.ReadOnlyEvidenceWorkflowRunner,
                "async_run",
                new=AsyncMock(),
            ) as run_mock,
        ):
            task = asyncio.create_task(options._async_run_control_discovery())
            await entered.wait()
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task

        run_mock.assert_not_awaited()
        self.assertEqual(
            options._shadow_learning_state["discovery"],
            {
                "status": "cancelled",
                "reason": "control_discovery_cancelled",
            },
        )
        self.assertEqual(coordinator.started, [])
        self.assertEqual(coordinator.stopped, [])

    async def test_dessmonitor_identity_change_after_snapshot_fails_before_cloud(self) -> None:
        coordinator = self._RunnerCoordinator(ready=False)
        original_pn = coordinator.smartess_collector_pn

        async def _capture():
            coordinator.smartess_collector_pn = "V0000000000001"
            return LocalRegisterSnapshot(
                collector_pn=original_pn,
                driver_key="smg",
                started_at="2026-08-22T10:00:00+00:00",
                completed_at="2026-08-22T10:00:00+00:00",
                planned_block_count=1,
                failed_block_count=1,
                blocks=(),
            )

        coordinator.async_capture_local_register_snapshot = _capture
        options = self._runner_options_flow(coordinator)
        options._shadow_learning_state["wizard_method"] = LEARNING_METHOD_READ_ONLY_EVIDENCE
        options._shadow_learning_state["wizard_source"] = "dessmonitor"

        with (
            patch.object(asyncio, "sleep", new=AsyncMock()),
            patch.object(
                cloud_read_only_workflow_module.ReadOnlyEvidenceWorkflowRunner,
                "async_run",
                new=AsyncMock(),
            ) as run_mock,
        ):
            await options._async_run_control_discovery()

        run_mock.assert_not_awaited()
        self.assertEqual(
            options._shadow_learning_state["discovery"]["status"],
            "error",
        )
        self.assertNotIn("local_register_snapshot", str(options._shadow_learning_state))
        self.assertEqual(coordinator.started, [])
        self.assertEqual(coordinator.stopped, [])

    async def test_dessmonitor_cancellation_never_runs_shadow_cleanup(self) -> None:
        coordinator = self._RunnerCoordinator(ready=False)
        options = self._runner_options_flow(coordinator)
        options._shadow_learning_state["wizard_method"] = LEARNING_METHOD_READ_ONLY_EVIDENCE
        options._shadow_learning_state["wizard_source"] = "dessmonitor"
        entered = asyncio.Event()
        never = asyncio.Event()

        async def _blocked_run(*_args, **_kwargs):
            entered.set()
            await never.wait()

        with (
            patch.object(asyncio, "sleep", new=AsyncMock()),
            patch.object(
                cloud_read_only_workflow_module.ReadOnlyEvidenceWorkflowRunner,
                "async_run",
                side_effect=_blocked_run,
            ),
        ):
            task = asyncio.create_task(options._async_run_control_discovery())
            await entered.wait()
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task

        self.assertEqual(coordinator.started, [])
        self.assertEqual(coordinator.stopped, [])
        self.assertEqual(
            options._shadow_learning_state["discovery"]["status"], "cancelled"
        )

    async def test_dessmonitor_failure_never_runs_shadow_cleanup(self) -> None:
        coordinator = self._RunnerCoordinator(ready=False)
        options = self._runner_options_flow(coordinator)
        options._shadow_learning_state["wizard_method"] = LEARNING_METHOD_READ_ONLY_EVIDENCE
        options._shadow_learning_state["wizard_source"] = "dessmonitor"

        with (
            patch.object(asyncio, "sleep", new=AsyncMock()),
            patch.object(
                cloud_read_only_workflow_module.ReadOnlyEvidenceWorkflowRunner,
                "async_run",
                new=AsyncMock(side_effect=RuntimeError("private dess detail")),
            ),
        ):
            await options._async_run_control_discovery()

        self.assertEqual(coordinator.started, [])
        self.assertEqual(coordinator.stopped, [])
        discovery = options._shadow_learning_state["discovery"]
        self.assertEqual(discovery["status"], "error")
        self.assertNotIn("private dess detail", str(discovery))

    async def test_dessmonitor_metadata_has_read_only_review_and_result(self) -> None:
        options = self._wizard_options_flow()
        options._shadow_learning_state.update(
            {
                "wizard_method": LEARNING_METHOD_READ_ONLY_EVIDENCE,
                "wizard_source": "dessmonitor",
                "discovery": {
                    "status": "ok",
                    "found_controls": 0,
                    "found_metadata": 2,
                },
                "cloud_metadata": {
                    "metadata_field_count": 2,
                    "history_collection": {
                        "schema_version": 1,
                        "authority": CLOUD_HISTORY_AUTHORITY,
                        "provider_id": "smartess",
                        "source_id": "dessmonitor",
                        "read_only": True,
                        "local_mapping_proven": False,
                        "activation_allowed": False,
                        "identity": {
                            "pn": "E50000200000000001",
                            "sn": "90000000000001",
                            "devcode": 2376,
                            "devaddr": 1,
                        },
                        "requested_date": "",
                        "timezone_offset_seconds": None,
                        "attempted_series_count": 0,
                        "failed_series_count": 0,
                        "budget_exhausted": False,
                        "series": [],
                        "status": "time_basis_unavailable",
                        "collected_series_count": 0,
                        "point_count": 0,
                    },
                    "semantic_report": {
                        "schema_version": 1,
                        "authority": "semantic_hint_only",
                        "local_mapping_proven": False,
                        "provider_id": "smartess",
                        "source_id": "dessmonitor",
                        "recognized_count": 2,
                        "read_candidate_count": 1,
                        "unit_conflict_count": 0,
                        "unknown_count": 0,
                        "control_metadata_count": 1,
                        "observations": [
                            {
                                "field_kind": "reading",
                                "field_id": "pv_voltage",
                                "title": "PV Voltage",
                                "value": "230.1",
                                "observed_unit": "V",
                                "source_action": "querySPDeviceLastData",
                                "status": "recognized",
                                "semantic_key": "pv_voltage",
                                "canonical_title": "PV Voltage",
                                "semantic_kind": "read",
                                "expected_unit": "V",
                                "device_class": "voltage",
                                "state_class": "measurement",
                                "local_mapping": "unproven",
                            },
                            {
                                "field_kind": "setting",
                                "field_id": "charger_priority",
                                "title": "Charger Source Priority",
                                "value": "Solar first",
                                "observed_unit": "",
                                "source_action": "queryDeviceCtrlField",
                                "status": "recognized",
                                "semantic_key": "charger_source_priority",
                                "canonical_title": "Charger Source Priority",
                                "semantic_kind": "both",
                                "expected_unit": "",
                                "device_class": "",
                                "state_class": "",
                                "local_mapping": "unproven",
                            },
                        ],
                    },
                    "local_coverage": {
                        "schema_version": 1,
                        "authority": "runtime_semantic_presence_only",
                        "local_mapping_proven": False,
                        "driver_key": "smg",
                        "items": [
                            {
                                "semantic_key": "pv_voltage",
                                "cloud_field_count": 1,
                                "status": "available_fresh",
                                "local_freshness": "fresh",
                                "local_origin": "driver",
                                "local_value_kind": "number",
                            }
                        ],
                        "available_count": 1,
                        "unknown_value_count": 0,
                        "not_observed_count": 0,
                    },
                    "telemetry_fields": [
                        {
                            "field_id": "pv_voltage",
                            "title": "PV Voltage",
                            "value": "230.1",
                            "unit": "V",
                        }
                    ],
                    "control_fields": [
                        {
                            "field_id": "charger_priority",
                            "title": "Charger Source Priority",
                            "current_value": "Solar first",
                            "unit": "",
                        }
                    ],
                },
            }
        )

        review = await options.async_step_shadow_learning_review()
        self.assertEqual(review["step_id"], "shadow_learning_review")
        hint = review["description_placeholders"]["control_discovery_hint"]
        self.assertIn("Already available locally", hint)
        self.assertIn("Cloud setting descriptions", hint)
        self.assertIn("PV Voltage", hint)
        self.assertIn("Charger Source Priority", hint)
        self.assertIn("1 are already available locally", hint)
        self.assertIn("device time zone could not be confirmed", hint)
        self.assertIn("about 20 minutes", hint)
        self.assertNotIn("local register", hint)
        self.assertNotIn("Apply", hint)
        self.assertIn(
            "start_local_register_observation",
            review["data_schema"].schema,
        )

        result = await options.async_step_shadow_learning_review(
            {"start_local_register_observation": True}
        )
        self.assertEqual(result["step_id"], "shadow_learning_result")
        start = options._coordinator().start_local_register_collection
        start.assert_called_once()
        plan = start.call_args.args[0]
        self.assertIs(type(plan), LocalRegisterSeriesPlan)
        self.assertEqual((plan.sample_count, plan.sample_interval_seconds), (5, 300))
        result_hint = result["description_placeholders"]["control_discovery_hint"]
        self.assertIn("2 metadata field", result_hint)
        self.assertIn("1 recognized semantic candidate", result_hint)
        self.assertIn("device time zone could not be confirmed", result_hint)
        self.assertIn("running (0/5 snapshots)", result_hint)
        self.assertNotIn("No controls were found", result_hint)
        self.assertEqual(
            _schema_select_options(result["data_schema"], "result_action"),
            ["create_support_package", "done"],
        )

    async def test_metadata_review_without_local_plan_never_starts_observation(self):
        options = self._wizard_options_flow()
        coordinator = options._coordinator()
        coordinator.local_register_collection_availability = LocalRegisterCollectionAvailability("inverter_unidentified")
        options._shadow_learning_state.update({
            "wizard_method": "read_only_evidence",
            "wizard_source": "smartclient",
            "discovery": {"status": "ok", "found_controls": 0, "found_metadata": 1},
            "cloud_metadata": {
                "provider_id": "smartess", "source_id": "smartclient",
                "telemetry_fields": [{"field_id": "2", "title": "PV Voltage", "value": "230", "unit": "V"}],
            },
        })
        review = await options.async_step_shadow_learning_review()
        self.assertEqual(review["step_id"], "shadow_learning_review")
        self.assertNotIn("start_local_register_observation", review["data_schema"].schema)
        self.assertIn("no local register read plan", review["description_placeholders"]["control_discovery_hint"])
        rejected = await options.async_step_shadow_learning_review({"start_local_register_observation": True})
        self.assertEqual(rejected["errors"]["base"], "local_register_collection_unavailable")
        coordinator.start_local_register_collection.assert_not_called()
        result = await options.async_step_shadow_learning_review({})
        self.assertEqual(result["step_id"], "shadow_learning_result")

    async def test_smartess_read_only_offers_background_history_correlation(
        self,
    ) -> None:
        options = self._wizard_options_flow()
        identity = CloudHistoryIdentity(
            pn="E50000200000000001",
            sn="90000000000001",
            devcode=2376,
            devaddr=1,
        )
        history = CloudHistorySeries(
            provider_id="smartess",
            source_id="smartess",
            source_action="queryDeviceKeyParameterOneDay",
            field_kind="key_parameter",
            identity=identity,
            series_key="PV_OUTPUT_POWER",
            title="PV Power",
            unit="kW",
            requested_date="2026-08-23",
            precision_minutes=0,
            timezone_offset_seconds=7200,
            points=(
                CloudHistoryPoint(
                    device_local_timestamp="2026-08-23 12:00:00",
                    utc_timestamp="2026-08-23T10:00:00+00:00",
                    value="1.25",
                ),
            ),
        )
        collection = CloudHistoryCollection(
            provider_id="smartess",
            source_id="smartess",
            identity=identity,
            requested_date="2026-08-23",
            timezone_offset_seconds=7200,
            attempted_series_count=1,
            failed_series_count=0,
            budget_exhausted=False,
            series=(history,),
        )
        options._shadow_learning_state.update(
            {
                "wizard_method": LEARNING_METHOD_READ_ONLY_EVIDENCE,
                "wizard_source": "smartess",
                "discovery": {
                    "status": "ok",
                    "found_controls": 0,
                    "found_metadata": 1,
                },
                "cloud_metadata": {
                    "source": "smartess",
                    "metadata_field_count": 1,
                    "history_collection": collection.to_record(),
                    "telemetry_fields": [
                        {
                            "field_id": "pv_voltage",
                            "title": "PV Voltage",
                            "value": "230.1",
                            "unit": "V",
                        }
                    ],
                },
            }
        )

        review = await options.async_step_shadow_learning_review()

        self.assertEqual(review["step_id"], "shadow_learning_review")
        self.assertIn(
            "start_local_register_observation",
            review["data_schema"].schema,
        )
        review_hint = review["description_placeholders"]["control_discovery_hint"]
        self.assertIn("Historical evidence includes 1 series", review_hint)
        self.assertIn("Optionally observe local readings", review_hint)

        result = await options.async_step_shadow_learning_review(
            {"start_local_register_observation": True}
        )
        self.assertEqual(result["step_id"], "shadow_learning_result")
        result_hint = result["description_placeholders"]["control_discovery_hint"]
        self.assertIn("Historical evidence includes 1 series", result_hint)
        options._coordinator().start_local_register_collection.assert_called_once()

    async def test_local_observation_can_be_cancelled_after_review_flow_closes(self) -> None:
        options = self._wizard_options_flow()
        coordinator = options._coordinator()
        plan = LocalRegisterSeriesPlan(5, 300)
        coordinator.local_register_collection_status = LocalRegisterCollectionStatus(
            state=LOCAL_REGISTER_COLLECTION_STATE_RUNNING,
            plan=plan,
            started_at="2026-08-22T10:00:00+00:00",
            completed_at="",
            completed_sample_count=2,
            failure_reason="",
        )

        async def _cancel():
            coordinator.local_register_collection_status = (
                LocalRegisterCollectionStatus(
                    state="cancelled",
                    plan=plan,
                    started_at="2026-08-22T10:00:00+00:00",
                    completed_at="2026-08-22T10:05:00+00:00",
                    completed_sample_count=2,
                    failure_reason="",
                )
            )
            return coordinator.local_register_collection_status

        coordinator.async_cancel_local_register_collection = AsyncMock(
            side_effect=_cancel
        )

        shown = await options.async_step_local_register_observation()
        self.assertEqual(shown["step_id"], "local_register_observation")
        self.assertIn(
            "running (2/5 snapshots)",
            shown["description_placeholders"][
                "local_register_observation_summary"
            ],
        )
        self.assertEqual(
            _schema_select_options(
                shown["data_schema"],
                "local_register_observation_action",
            ),
            ["cancel", "done"],
        )

        cancelled = await options.async_step_local_register_observation(
            {"local_register_observation_action": "cancel"}
        )
        coordinator.async_cancel_local_register_collection.assert_awaited_once()
        self.assertIn(
            "was cancelled",
            cancelled["description_placeholders"][
                "local_register_observation_summary"
            ],
        )
        self.assertEqual(
            _schema_select_options(
                cancelled["data_schema"],
                "local_register_observation_action",
            ),
            ["restart", "done"],
        )

    async def test_control_discovery_runner_uses_live_bundle_identity_without_saved_evidence(self) -> None:
        coordinator = self._RunnerCoordinator(ready=True)
        options = self._runner_options_flow(coordinator)
        options._shadow_learning_cloud_identity = lambda _coordinator: None
        captured: dict = {}
        login_p, fetch_p, orchestrate_p, overlay_p = self._runner_cloud_patches(captured=captured)

        with login_p, fetch_p as bundle_mock, orchestrate_p as orchestrate_mock, overlay_p:
            await options._async_run_control_discovery()

        bundle_mock.assert_called_once()
        self.assertEqual(
            set(bundle_mock.call_args.kwargs),
            {"username", "password", "collector_pn", "timeout"},
        )
        self.assertEqual(bundle_mock.call_args.kwargs["timeout"], 30.0)
        self.assertEqual(
            bundle_mock.call_args.kwargs["collector_pn"],
            "E5000020000000",
        )
        self.assertEqual(
            bundle_mock.call_args.kwargs["username"],
            "demo@example.com",
        )
        orchestrate_mock.assert_called_once()
        self.assertEqual(captured["pn"], "E50000200000000001")
        self.assertEqual(captured["sn"], "E50000200000000001000001")
        self.assertEqual(captured["devcode"], 2376)
        self.assertEqual(captured["devaddr"], 1)
        self.assertEqual(
            options._shadow_learning_state["identity"]["sn"],
            "E50000200000000001000001",
        )

    async def test_control_discovery_runner_surfaces_trace_path(self) -> None:
        coordinator = self._RunnerCoordinator(ready=True)
        options = self._runner_options_flow(coordinator)
        captured: dict = {}
        login_p, fetch_p, orchestrate_p, overlay_p = self._runner_cloud_patches(captured=captured)

        with login_p, fetch_p, orchestrate_p, overlay_p:
            await options._async_run_control_discovery()

        # Acceptance: the trace path created for the session is visible afterwards.
        placeholders = options._shadow_learning_placeholders(coordinator)
        self.assertEqual(
            placeholders["shadow_learning_trace_path"],
            "/config/eybond_local/shadow_learning_traces/auto.jsonl",
        )

    async def test_control_discovery_runner_is_fail_closed_on_failure(self) -> None:
        coordinator = self._RunnerCoordinator(ready=True)
        options = self._runner_options_flow(coordinator)
        captured: dict = {}
        login_p, fetch_p, orchestrate_p, overlay_p = self._runner_cloud_patches(
            captured=captured,
            fetch_side_effect=RuntimeError("settings_fetch_boom"),
        )

        with login_p, fetch_p, orchestrate_p as orchestrate_mock, overlay_p as overlay_mock:
            await options._async_run_control_discovery()

        # Authentication succeeded and the route opened, but device-bound
        # metadata failed through that route. Cleanup must stop and restore it.
        self.assertEqual(len(coordinator.started), 1)
        orchestrate_mock.assert_not_called()
        overlay_mock.assert_not_called()
        # Fail-closed: a stop+restore was attempted, tolerant of an already-stopped
        # session (raise_when_not_running=False).
        self.assertEqual(len(coordinator.stopped), 1)
        self.assertFalse(coordinator.stopped[0].get("raise_when_not_running", True))
        self.assertEqual(options._shadow_learning_state["discovery"]["status"], "error")
        self.assertEqual(
            options._shadow_learning_state["discovery"]["reason"],
            options_shadow_review_module.CONTROL_DISCOVERY_FAILURE_GENERIC,
        )

    async def test_control_discovery_runner_classifies_cloud_timeout_without_leaking(self) -> None:
        coordinator = self._RunnerCoordinator(ready=True)
        options = self._runner_options_flow(coordinator)
        captured: dict = {}
        login_p, fetch_p, orchestrate_p, overlay_p = self._runner_cloud_patches(
            captured=captured,
            fetch_side_effect=TimeoutError("secret cloud detail"),
        )

        with login_p, fetch_p, orchestrate_p, overlay_p:
            await options._async_run_control_discovery()

        discovery = options._shadow_learning_state["discovery"]
        self.assertEqual(discovery["status"], "error")
        self.assertEqual(discovery["reason"], "control_discovery_cloud_timeout")
        self.assertNotIn("secret", str(discovery))
        self.assertEqual(len(coordinator.stopped), 1)

    async def test_control_discovery_action_timeout_stops_and_restores(self) -> None:
        coordinator = self._RunnerCoordinator(ready=True)
        options = self._runner_options_flow(coordinator)
        captured: dict = {}
        login_p, fetch_p, orchestrate_p, overlay_p = self._runner_cloud_patches(
            captured=captured,
            orchestrate_side_effect=TimeoutError("private action detail"),
        )

        with login_p, fetch_p, orchestrate_p, overlay_p:
            await options._async_run_control_discovery()

        discovery = options._shadow_learning_state["discovery"]
        self.assertEqual(discovery["status"], "error")
        self.assertEqual(discovery["reason"], "control_discovery_cloud_timeout")
        self.assertNotIn("private action detail", str(discovery))
        self.assertEqual(len(coordinator.started), 1)
        self.assertEqual(len(coordinator.stopped), 1)
        self.assertFalse(coordinator.stopped[0].get("raise_when_not_running", True))

    def test_control_discovery_cloud_reason_boundary_is_closed(self) -> None:
        options = self._wizard_options_flow()

        self.assertEqual(
            options._control_discovery_failure_reason(
                RuntimeError("private detail"), cloud_error_code="network"
            ),
            "control_discovery_cloud_network",
        )
        for malformed in ("unknown", " timeout ", object(), None):
            with self.subTest(malformed=malformed):
                self.assertEqual(
                    options._control_discovery_failure_reason(
                        RuntimeError("private detail"),
                        cloud_error_code=malformed,
                    ),
                    options_shadow_review_module.CONTROL_DISCOVERY_FAILURE_GENERIC,
                )

    async def test_control_discovery_runner_treats_leaked_write_as_failure(self) -> None:
        coordinator = self._RunnerCoordinator(ready=True)
        options = self._runner_options_flow(coordinator)
        captured: dict = {}
        leaked_orchestration = {
            "planned_write_count": 62,
            "executed_result_count": 30,
            "sent_count": 0,
            "error_count": 29,
            "degraded_count": 0,
            "leaked_count": 1,
            "unknown_field_count": 0,
            "results": [{"status": "leaked", "reason": "control_leaked_unproxied"}],
            "correlation": {"matched_count": 29, "unmatched_attempt_count": 1},
        }
        login_p, fetch_p, orchestrate_p, overlay_p = self._runner_cloud_patches(
            captured=captured,
            orchestration_override=leaked_orchestration,
        )

        with login_p, fetch_p, orchestrate_p as orchestrate_mock, overlay_p as overlay_mock:
            await options._async_run_control_discovery()

        orchestrate_mock.assert_called_once()
        overlay_mock.assert_not_called()
        self.assertEqual(len(coordinator.stopped), 1)
        self.assertFalse(coordinator.stopped[0].get("raise_when_not_running", True))
        self.assertEqual(options._shadow_learning_state["discovery"]["status"], "error")
        self.assertEqual(
            options._shadow_learning_state["discovery"]["reason"],
            options_shared_module.CONTROL_DISCOVERY_FAILURE_SAFETY_STOP,
        )
        self.assertNotIn("overlay", options._shadow_learning_state)

    async def test_control_discovery_runner_requires_credentials(self) -> None:
        # No live SmartESS operation may start without the transient credentials
        # gathered earlier in the wizard.
        coordinator = self._RunnerCoordinator(ready=True)
        options = self._runner_options_flow(coordinator)
        options._shadow_learning_state.pop("wizard_credentials", None)

        await options._async_run_control_discovery()

        self.assertEqual(len(coordinator.started), 0)
        self.assertEqual(len(coordinator.stopped), 0)
        self.assertEqual(
            options._shadow_learning_state["discovery"]["reason"], "credentials_required"
        )

    async def test_control_discovery_runner_blocks_when_preflight_not_ready(self) -> None:
        coordinator = self._RunnerCoordinator(ready=True)
        options = self._runner_options_flow(coordinator)

        async def _blocked_preflight(_coordinator):
            return {"can_start": False, "blockers": ["collector_not_connected"]}

        options._build_shadow_learning_preflight_snapshot = _blocked_preflight
        captured: dict = {}
        login_p, fetch_p, orchestrate_p, overlay_p = self._runner_cloud_patches(captured=captured)

        with login_p as login_mock, fetch_p, orchestrate_p, overlay_p:
            await options._async_run_control_discovery()

        # Preflight gate prevents the session from starting and any cloud login.
        self.assertEqual(len(coordinator.started), 0)
        login_mock.assert_not_called()
        self.assertEqual(options._shadow_learning_state["discovery"]["status"], "error")
        self.assertEqual(
            options._shadow_learning_state["discovery"]["reason"],
            options_shadow_review_module.CONTROL_DISCOVERY_FAILURE_GENERIC,
        )



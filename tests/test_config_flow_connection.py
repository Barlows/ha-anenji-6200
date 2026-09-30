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


class ConnectionStrategyVerificationFlowTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        super().setUp()
        _install_fast_identity_policy(self)

    """Behavioral connection-strategy verification wired into passive discovery."""

    FULL_PN = "V001020SYN62344022"
    OTHER_FULL_PN = "V000405SYN94677058"
    OLD_SESSION = "listener-18899-1"
    NEW_SESSION = "listener-18899-2"
    PEER_IP = "203.0.113.10"

    def _make_flow(self) -> EybondLocalConfigFlow:
        flow = EybondLocalConfigFlow()
        flow.hass = _FakeHass()
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

    def _assert_callback_failure_menu(
        self,
        flow: EybondLocalConfigFlow,
        result: dict[str, object],
        reason: str,
    ) -> None:
        """A failed manual callback remains actionable, never form-blocking."""

        self.assertEqual(result["type"], "menu")
        self.assertEqual(result["step_id"], "manual_confirm")
        self.assertIn("manual_probe_again", result["menu_options"])
        self.assertIn("manual_edit_settings", result["menu_options"])
        self.assertNotIn("manual_save", result["menu_options"])
        self.assertIsNotNone(flow._manual_result)
        self.assertEqual(flow._manual_result.last_error, reason)

    def _discovery_info(self, **overrides) -> dict[str, object]:
        info = {
            "tcp_port": 18899,
            "collector_pn": self.FULL_PN,
            "peer_ip": self.PEER_IP,
            "session_id": self.OLD_SESSION,
        }
        info.update(overrides)
        return info

    # --- driving the real identity transaction from a flow test ---------------
    #
    # The flow tests keep exercising the REAL transaction (real causality lease,
    # real claim/promote/prepare_handoff) and stub only the two wire edges it
    # cannot have in a unit test: the UDP trigger sequence and the authoritative
    # on-session PN read. That keeps these tests about the FLOW's use of the
    # proof, while the proof's own mechanics are pinned in
    # tests/test_callback_identity.py.

    @contextmanager
    def _identity_wire(
        self,
        inventory,
        *,
        answers=(),
        read_pn=None,
        read_error=None,
        own_sends=1,
        foreign_sends=0,
    ):
        """Stub the collector: its trigger answer and its authoritative PN read.

        ``answers`` appear only AFTER the trigger, like a real collector dialing
        in; ``foreign_sends`` are recorded with no attempt context, exactly like
        an uncoordinated runtime sender.
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
            calls: list = []

            async def async_read_full_pn(self, *, session_id, session_protocol, listener_port, expected_pn=""):
                type(self).calls.append(session_id)
                if read_error is not None:
                    raise read_error
                if read_pn is None:
                    return ("", "")
                return (read_pn, "fc2_parameter_2")

        with patch.object(ci, "_ProductionTriggerSender", return_value=_Sender()), patch.object(
            ci, "_SessionPinnedIdentityReader", return_value=_Reader()
        ), patch.object(
            ci, "DEFAULT_ONBOARDING_TIMEOUT_POLICY", _fast_identity_policy()
        ):
            yield _Reader

    def _install_registry(self, flow, inventory: list[dict[str, object]]):
        from custom_components.eybond_local.connection.session_registry import (
            CallbackSessionRegistry,
        )

        registry = CallbackSessionRegistry(sessions_source=lambda: tuple(inventory))
        flow.hass.data["eybond_local"] = {"callback_session_registry": registry}
        return registry

    @staticmethod
    def _inventory_session(
        session_id: str,
        pn: str,
        state: str = "identified",
        *,
        identity_source: str = "at_dtupn",
        protocol_shape: str = "eybond_framed",
    ) -> dict[str, object]:
        # protocol_shape is what the socket's first bytes looked like. A real
        # listener always records it, and the identity transaction needs it: the
        # wire is negotiated from the observation alone, and a session with no
        # wire evidence is (correctly) refused rather than guessed at.
        return {
            "session_id": session_id,
            "peer_ip": "203.0.113.10",
            "listener_port": 18899,
            "collector_pn": pn,
            "state": state,
            "protocol_shape": protocol_shape,
            "collector_identity_source": identity_source,
        }

    @staticmethod
    def _schema_default(schema, field: str):
        for key in schema.schema:
            if str(getattr(key, "schema", key)) == field:
                default = getattr(key, "default", None)
                return default() if callable(default) else default
        return None

    def _manual_input(
        self, collector_ip: str, *, connection_strategy: str = "callback_on_demand"
    ) -> dict[str, object]:
        # The manual form now REQUIRES an explicit strategy: it decides whether
        # Home Assistant may reach out at all. These verification tests exercise
        # the callback path, so they state callback_on_demand.
        return {
            "server_ip": "192.168.1.50",
            "tcp_port": 18899,
            "udp_port": 58899,
            "collector_ip": collector_ip,
            "discovery_target": "192.168.1.255",
            "discovery_interval": 3,
            "heartbeat_interval": 60,
            "driver_hint": "auto",
            "connection_strategy": connection_strategy,
        }

    def _manual_result_with_pn(self, pn: str) -> OnboardingResult:
        return OnboardingResult(
            connection_mode="manual",
            collector=CollectorCandidate(
                target_ip="192.168.1.50",
                source="manual",
                ip="192.168.1.60",
                connected=True,
                collector=CollectorInfo(collector_pn=pn),
            ),
        )

    async def _drive_verification(self, flow) -> dict[str, object]:
        """Consent -> progress -> completed task -> result step routing."""

        consent = await flow.async_step_verify_connection()
        self.assertEqual(consent["type"], "form")
        self.assertEqual(consent["step_id"], "verify_connection")

        progress = await flow.async_step_verify_connection_progress()
        self.assertEqual(progress["type"], "progress")
        await flow._admission_task
        done = await flow.async_step_verify_connection_progress()
        self.assertEqual(done["type"], "progress_done")
        self.assertEqual(done["next_step_id"], "verify_connection_result")
        return await flow.async_step_verify_connection_result()

    # Discovery with an observed session id must ask for verification consent
    # in the SAME flow (no second flow is initialized anywhere).
    async def test_discovery_with_session_id_shows_verification_consent(self) -> None:
        flow = self._make_flow()
        result = await flow.async_step_integration_discovery(self._discovery_info())

        self.assertEqual(result["type"], "form")
        self.assertEqual(result["step_id"], "verify_connection")
        # The typed admission request now carries the observed session; discovery
        # is just one source adapter building a CollectorAdmissionRequest.
        request = flow._admission_transaction.request
        self.assertIsInstance(request, CollectorAdmissionRequest)
        self.assertEqual(request.origin, "integration_discovery")
        self.assertEqual(
            request.observed_session,
            ObservedCollectorSession(
                collector_pn=self.FULL_PN,
                identity_source="",
                session_id=self.OLD_SESSION,
                listener_port=18899,
                protocol_shape="",
                peer_hint=self.PEER_IP,
            ),
        )
        # Payloads without a session id can never become inbound: reboot
        # verification is impossible, so the SAME flow continues on the manual
        # callback step (peer IP prefilled as an editable hint) and the entry is
        # created only after the callback proof.
        legacy_flow = self._make_flow()
        legacy = await legacy_flow.async_step_integration_discovery(
            self._discovery_info(session_id="", collector_pn=self.OTHER_FULL_PN)
        )
        self.assertEqual(legacy["type"], "form")
        self.assertEqual(legacy["step_id"], "manual")
        self.assertIsNone(legacy_flow._admission_transaction)
        self.assertEqual(legacy_flow._callback_continuation._expected_pn, self.OTHER_FULL_PN)
        self.assertEqual(legacy_flow._manual_defaults.get("collector_ip"), self.PEER_IP)
        self.assertEqual(legacy_flow._verified_connection_strategy, "")

    async def test_discovery_admits_inbound_but_scan_requires_explicit_route(self) -> None:
        """Discovery verifies an inbound session; scan never guesses its route."""

        # Source A: integration discovery.
        disc_flow = self._make_flow()
        disc = await disc_flow.async_step_integration_discovery(self._discovery_info())
        disc_request = disc_flow._admission_transaction.request

        # Source B: a passive scan inventory result carrying the typed session.
        observed = ObservedCollectorSession(
            collector_pn=self.FULL_PN,
            identity_source="at_dtupn",
            session_id=self.OLD_SESSION,
            listener_port=8899,
            protocol_shape="eybond_framed",
            peer_hint=self.PEER_IP,
        )
        scan_flow = self._make_flow()
        scan_flow._autodetect_results = {
            "0": OnboardingResult(
                collector=CollectorCandidate(
                    target_ip="192.168.1.255",
                    source="callback_listener",
                    ip=self.PEER_IP,
                    connected=True,
                    collector=CollectorInfo(collector_pn=self.FULL_PN),
                ),
                connection_mode="callback_listener",
                observed_session=observed,
                detection=TargetDetectionEvidence(
                    status="collector_only",
                    reason="callback_session_inventory",
                ),
            )
        }
        scan = await scan_flow.async_step_scan_results({CONF_RESULT_KEY: "0"})
        # An integration-discovery session is an inbound observation and enters
        # admission.  A scan inventory session may have arrived through NAT, so
        # it first asks for an independently observed/editable route and starts
        # no admission transaction merely from its TCP peer.
        self.assertEqual(disc["step_id"], "verify_connection")
        self.assertEqual(scan["step_id"], "scan_collector_route")
        self.assertIs(type(disc_request), CollectorAdmissionRequest)
        self.assertEqual(disc_request.origin, "integration_discovery")
        self.assertEqual(disc_request.observed_session.collector_pn, self.FULL_PN)
        self.assertIsNone(scan_flow._admission_transaction)
        self.assertIs(scan_flow._selected_result.observed_session, observed)

    def test_typed_observed_session_identity_makes_silent_result_addable(self) -> None:
        """Exact-session FC=2 identity must survive an empty legacy projection."""

        flow = self._make_flow()
        observed = ObservedCollectorSession(
            collector_pn=self.FULL_PN,
            identity_source="fc2_parameter_2",
            session_id=self.OLD_SESSION,
            listener_port=8899,
            protocol_shape="eybond_framed",
            peer_hint=self.PEER_IP,
        )
        result = OnboardingResult(
            collector=CollectorCandidate(
                target_ip="192.168.1.255",
                source="silent_callback_scan",
                ip=self.PEER_IP,
                connected=False,
                collector=CollectorInfo(),
            ),
            observed_session=observed,
        )

        self.assertEqual(flow._collector_pn_for_result(result), self.FULL_PN)
        self.assertTrue(flow._is_addable_scan_result(result))

    def test_scan_identity_projection_reconciles_or_fails_closed(self) -> None:
        flow = self._make_flow()
        short_pn = self.FULL_PN[:14]
        observed = ObservedCollectorSession(
            collector_pn=self.FULL_PN,
            identity_source="fc2_parameter_2",
            session_id=self.OLD_SESSION,
            listener_port=8899,
        )
        same_identity = OnboardingResult(
            collector=CollectorCandidate(
                target_ip="192.168.1.255",
                source="silent_callback_scan",
                collector=CollectorInfo(collector_pn=short_pn),
            ),
            observed_session=observed,
        )
        foreign_identity = OnboardingResult(
            collector=CollectorCandidate(
                target_ip="192.168.1.255",
                source="silent_callback_scan",
                connected=True,
                collector=CollectorInfo(collector_pn=self.OTHER_FULL_PN),
            ),
            observed_session=observed,
        )

        self.assertEqual(
            flow._collector_pn_for_result(same_identity),
            self.FULL_PN,
        )
        self.assertTrue(flow._is_addable_scan_result(same_identity))
        self.assertEqual(flow._collector_pn_for_result(foreign_identity), "")
        self.assertFalse(flow._is_addable_scan_result(foreign_identity))

    async def test_passive_adapter_fails_closed_on_duck_or_subclass_observation(
        self,
    ) -> None:
        """A duck / subclass / non-typed ``observed_session`` must fail CLOSED in
        the passive adapter: it starts NO admission and mints NO request, rather
        than reaching the strict CollectorAdmissionRequest constructor and raising
        an unhandled TypeError (a 500) into the flow."""

        class _SneakyObservation(ObservedCollectorSession):
            pass

        duck = types.SimpleNamespace(
            collector_pn=self.FULL_PN,
            identity_source="at_dtupn",
            session_id=self.OLD_SESSION,
            listener_port=8899,
        )
        subclass = _SneakyObservation(
            collector_pn=self.FULL_PN,
            identity_source="at_dtupn",
            session_id=self.OLD_SESSION,
            listener_port=8899,
        )

        for bogus in (duck, subclass, "not-an-observation", None):
            flow = self._make_flow()
            flow._selected_result = OnboardingResult(
                collector=CollectorCandidate(
                    target_ip="192.168.1.255",
                    source="callback_listener",
                    ip=self.PEER_IP,
                    connected=True,
                    collector=CollectorInfo(collector_pn=self.FULL_PN),
                ),
                connection_mode="callback_listener",
                observed_session=bogus,  # type: ignore[arg-type]
            )
            result = await flow._async_admit_selected_scan_result()
            self.assertIsNone(result, msg=f"admission started for {bogus!r}")
            self.assertIsNone(flow._admission_transaction)

    async def test_single_active_scan_result_reuses_its_exact_typed_route(self) -> None:
        """An active result must not ask the user to reselect its proven route."""

        flow = self._make_flow()
        observed = ObservedCollectorSession(
            collector_pn=self.FULL_PN,
            identity_source="fc2_parameter_2",
            session_id=self.OLD_SESSION,
            listener_port=8899,
            protocol_shape="eybond_framed",
            peer_hint=self.PEER_IP,
        )
        route = CallbackRecoveryRoute(
            bind_ip="192.168.1.50",
            trigger_target_ip="192.168.1.55",
            trigger_udp_port=58899,
            advertised_ha_host="192.168.1.50",
            advertised_ha_port=8899,
            listener_port=8899,
        )
        result = OnboardingResult(
            collector=CollectorCandidate(
                target_ip="192.168.1.55",
                source="subnet_unicast",
                ip="192.168.1.55",
                connected=True,
                collector=CollectorInfo(collector_pn=self.FULL_PN),
            ),
            observed_session=observed,
            callback_route=route,
        )
        flow._autodetect_results = {"0": result}

        selected = await flow.async_step_choose()

        self.assertEqual(selected["step_id"], "verify_connection")
        request = flow._admission_transaction.request
        self.assertEqual(request.origin, "scan_selected_route")
        self.assertIs(request.observed_session, observed)
        self.assertIs(request.callback_route, route)
        self.assertEqual(request.callback_route.trigger_target_ip, "192.168.1.55")
        self.assertNotIn("manual_create_pending", selected.get("menu_options", ()))

    async def test_selected_route_retry_reuses_address_with_a_new_identity_attempt(self) -> None:
        from custom_components.eybond_local.connection.callback_identity import (
            CallbackIdentityOutcome,
        )

        flow = self._make_flow()
        observed = ObservedCollectorSession(
            collector_pn=self.FULL_PN,
            identity_source="fc2_parameter_2",
            session_id=self.OLD_SESSION,
            listener_port=8899,
            protocol_shape="eybond_framed",
            peer_hint="192.168.1.1",
        )
        flow._selected_result = OnboardingResult(
            collector=CollectorCandidate(
                target_ip="192.168.1.55",
                source="subnet_unicast",
                ip="192.168.1.1",
                connected=True,
                collector=CollectorInfo(collector_pn=self.FULL_PN),
            ),
            observed_session=observed,
            callback_route=CallbackRecoveryRoute(
                bind_ip="192.168.1.50",
                trigger_target_ip="192.168.1.55",
                trigger_udp_port=58899,
                advertised_ha_host="192.168.1.50",
                advertised_ha_port=8899,
                listener_port=8899,
            ),
        )
        await flow.async_step_scan_collector_route(
            {"collector_ip": "192.168.1.55"}
        )
        transaction = flow._admission_transaction
        transaction.begin_observed_callback_continuation()
        # Model the post-failure state produced after recovery releases its
        # unadopted owner. Retry must keep this transaction and selected route.
        transaction._state = "callback_ready"

        retry = await flow.async_step_verify_connection_retry()
        self.assertEqual(retry["step_id"], "verify_connection")
        self.assertIs(flow._admission_transaction, transaction)
        self.assertEqual(
            transaction.request.callback_route.trigger_target_ip,
            "192.168.1.55",
        )

        captured = []

        async def _identity(_hass, request):
            captured.append(request)
            return CallbackIdentityOutcome(result="callback_timeout")

        with patch.object(
            admission_transaction_module,
            "async_run_callback_identity_transaction",
            side_effect=_identity,
        ):
            await flow._async_run_observed_callback_admission(transaction)

        self.assertEqual(len(captured), 1)
        self.assertIsNone(captured[0].bootstrap_probe)
        self.assertEqual(captured[0].target_ip, "192.168.1.55")
        self.assertEqual(flow._admission_callback_error, "callback_timeout")

    async def test_selected_route_weak_session_runs_exact_identity_read_before_recovery(
        self,
    ) -> None:
        """Regression: heartbeat-only V0010 must not fail before the authority."""

        from custom_components.eybond_local.connection.callback_identity import (
            CallbackIdentityOutcome,
            IDENTITY_UNVERIFIED,
            ObservedSessionWireProbeIntent,
        )

        flow = self._make_flow()
        observed = ObservedCollectorSession(
            collector_pn=self.SHORT_PN,
            identity_source="framed_heartbeat",
            session_id=self.OLD_SESSION,
            listener_port=18899,
            protocol_shape="eybond_framed",
            peer_hint="195.138.86.175",
        )
        flow._selected_result = OnboardingResult(
            collector=CollectorCandidate(
                target_ip="195.138.86.175",
                source="callback_listener",
                ip="195.138.86.175",
                connected=True,
                collector=CollectorInfo(collector_pn=self.SHORT_PN),
            ),
            observed_session=observed,
        )
        await flow.async_step_scan_collector_route(
            {"collector_ip": "195.138.86.175"}
        )
        transaction = flow._admission_transaction
        captured = []

        async def _identity(_hass, request):
            captured.append(request)
            return CallbackIdentityOutcome(result=IDENTITY_UNVERIFIED)

        recovery = AsyncMock()
        with (
            patch.object(
                admission_transaction_module,
                "async_run_callback_identity_transaction",
                side_effect=_identity,
            ),
            patch.object(transaction, "async_run_recovery", recovery),
        ):
            await flow._async_run_observed_callback_admission(transaction)

        self.assertEqual(len(captured), 1)
        intent = captured[0].bootstrap_probe
        self.assertIs(type(intent), ObservedSessionWireProbeIntent)
        self.assertEqual(intent.session_id, self.OLD_SESSION)
        self.assertEqual(intent.collector_pn, self.SHORT_PN)
        self.assertEqual(intent.identity_source, "framed_heartbeat")
        self.assertEqual(captured[0].expected_pn, self.SHORT_PN)
        self.assertEqual(captured[0].target_ip, "195.138.86.175")
        self.assertEqual(flow._admission_callback_error, IDENTITY_UNVERIFIED)
        recovery.assert_not_awaited()

    async def test_stale_scan_socket_immediately_tests_the_selected_route(self) -> None:
        """A vanished zero-send bootstrap must not become an instant UI failure."""

        from custom_components.eybond_local.connection.callback_identity import (
            CallbackIdentityOutcome,
            IDENTITY_SILENT_SESSION_STALE,
        )

        flow = self._make_flow()
        observed = ObservedCollectorSession(
            collector_pn=self.FULL_PN,
            identity_source="fc2_parameter_2",
            session_id=self.OLD_SESSION,
            listener_port=8899,
            protocol_shape="eybond_framed",
            peer_hint="192.168.1.1",
        )
        flow._selected_result = OnboardingResult(
            collector=CollectorCandidate(
                target_ip="192.168.1.55",
                source="subnet_unicast",
                ip="192.168.1.1",
                connected=True,
                collector=CollectorInfo(collector_pn=self.FULL_PN),
            ),
            observed_session=observed,
            callback_route=CallbackRecoveryRoute(
                bind_ip="192.168.1.50",
                trigger_target_ip="192.168.1.55",
                trigger_udp_port=58899,
                advertised_ha_host="192.168.1.50",
                advertised_ha_port=8899,
                listener_port=8899,
            ),
        )
        await flow.async_step_scan_collector_route(
            {"collector_ip": "192.168.1.55"}
        )
        transaction = flow._admission_transaction
        captured = []

        async def _identity(_hass, request):
            captured.append(request)
            if len(captured) == 1:
                return CallbackIdentityOutcome(
                    result=IDENTITY_SILENT_SESSION_STALE
                )
            return CallbackIdentityOutcome(result="callback_timeout")

        with patch.object(
            admission_transaction_module,
            "async_run_callback_identity_transaction",
            side_effect=_identity,
        ):
            await flow._async_run_observed_callback_admission(transaction)

        self.assertEqual(len(captured), 2)
        self.assertIsNotNone(captured[0].bootstrap_probe)
        self.assertIsNone(captured[1].bootstrap_probe)
        self.assertEqual(
            [request.target_ip for request in captured],
            ["192.168.1.55", "192.168.1.55"],
        )
        self.assertEqual(flow._admission_callback_error, "callback_timeout")
        failed = await flow.async_step_verify_connection_failed()
        explanation = failed["description_placeholders"]["failure_explanation"]
        self.assertIn("did not call back", explanation)
        self.assertNotIn("could not verify the collector connection", explanation)

    async def test_silent_addressed_callback_reuses_observed_wire_without_second_trigger(
        self,
    ) -> None:
        """E500: a typed silent offer inherits only the selected session's wire."""

        from custom_components.eybond_local.connection.callback_identity import (
            CallbackIdentityOutcome,
            IDENTITY_SESSION_SILENT,
            IDENTITY_SILENT_SESSION_STALE,
            IDENTITY_WIRE_PROBE_FAILED,
            ObservedSessionWireProbeIntent,
            SilentSessionBootstrapOffer,
        )

        flow = self._make_flow()
        observed = ObservedCollectorSession(
            collector_pn=self.FULL_PN,
            identity_source="fc2_parameter_2",
            session_id=self.OLD_SESSION,
            listener_port=8899,
            protocol_shape="eybond_framed",
            peer_hint="192.168.1.55",
        )
        flow._selected_result = OnboardingResult(
            collector=CollectorCandidate(
                target_ip="192.168.1.55",
                source="subnet_unicast",
                ip="192.168.1.55",
                connected=True,
                collector=CollectorInfo(collector_pn=self.FULL_PN),
            ),
            observed_session=observed,
            callback_route=CallbackRecoveryRoute(
                bind_ip="192.168.1.50",
                trigger_target_ip="192.168.1.55",
                trigger_udp_port=58899,
                advertised_ha_host="192.168.1.50",
                advertised_ha_port=8899,
                listener_port=8899,
            ),
        )
        await flow.async_step_scan_collector_route(
            {"collector_ip": "192.168.1.55"}
        )
        transaction = flow._admission_transaction
        captured = []

        async def _identity(_hass, request):
            captured.append(request)
            if len(captured) == 1:
                return CallbackIdentityOutcome(
                    result=IDENTITY_SILENT_SESSION_STALE
                )
            if len(captured) == 2:
                return CallbackIdentityOutcome(
                    result=IDENTITY_SESSION_SILENT,
                    silent_bootstrap_offer=SilentSessionBootstrapOffer(
                        "s-silent-callback"
                    ),
                )
            return CallbackIdentityOutcome(result=IDENTITY_WIRE_PROBE_FAILED)

        with patch.object(
            admission_transaction_module,
            "async_run_callback_identity_transaction",
            side_effect=_identity,
        ):
            await flow._async_run_observed_callback_admission(transaction)

        self.assertEqual(len(captured), 3)
        self.assertIsNone(captured[1].bootstrap_probe)
        continuation = captured[2].bootstrap_probe
        self.assertIs(type(continuation), ObservedSessionWireProbeIntent)
        self.assertEqual(continuation.session_id, "s-silent-callback")
        self.assertEqual(continuation.wire_source_session_id, self.OLD_SESSION)
        self.assertEqual(continuation.protocol, "eybond_framed")
        self.assertEqual(flow._admission_callback_error, IDENTITY_WIRE_PROBE_FAILED)

    def test_identified_scan_session_keeps_route_addresses_independent(self) -> None:
        flow = self._make_flow()
        observed = ObservedCollectorSession(
            collector_pn=self.FULL_PN,
            identity_source="fc2_parameter_2",
            session_id=self.OLD_SESSION,
            listener_port=8899,
            protocol_shape="eybond_framed",
            peer_hint="192.168.1.1",
        )
        identified = OnboardingResult(
            collector=CollectorCandidate(
                target_ip="192.168.1.55",
                source="subnet_unicast",
                ip="192.168.1.1",
                connected=True,
                collector=CollectorInfo(collector_pn=self.FULL_PN),
            ),
            observed_session=observed,
            callback_route=CallbackRecoveryRoute(
                bind_ip="192.168.1.50",
                trigger_target_ip="192.168.1.55",
                trigger_udp_port=58899,
                advertised_ha_host="192.168.1.50",
                advertised_ha_port=8899,
                listener_port=8899,
            ),
        )
        route_only = OnboardingResult(
            collector=CollectorCandidate(
                target_ip="192.168.1.51",
                source="subnet_unicast",
                ip="192.168.1.51",
                udp_reply="rsp>server=1;",
            ),
        )
        flow._autodetect_results = {"identified": identified, "route": route_only}

        options = flow._scan_collector_route_options(identified)

        self.assertEqual(
            set(options), {"192.168.1.55", "192.168.1.51", "192.168.1.1"}
        )
        self.assertIn("responded", options["192.168.1.55"])
        self.assertIn("responded", options["192.168.1.51"])
        self.assertIn("may be a router", options["192.168.1.1"])

    async def test_route_only_scan_never_offers_or_creates_unidentified_entry(self) -> None:
        flow = self._make_flow()
        route_only = OnboardingResult(
            collector=CollectorCandidate(
                target_ip="192.168.1.51",
                source="subnet_unicast",
                ip="192.168.1.51",
                udp_reply="rsp>server=1;",
            ),
        )
        flow._autodetect_results = {"route": route_only}

        manual = await flow.async_step_scan_results({CONF_RESULT_KEY: "route"})
        self.assertEqual(manual["step_id"], "manual")
        self.assertEqual(flow._manual_defaults["collector_ip"], "192.168.1.51")
        stage_note = manual["description_placeholders"]["verification_note"]
        self.assertIn("Step 1 of 2", stage_note)
        self.assertIn("192.168.1.51", stage_note)

        flow._manual_config = self._manual_input("192.168.1.51")
        flow._manual_result = OnboardingResult(
            connection_mode="manual",
            next_action="retry_verification",
            last_error="callback_timeout",
        )
        menu = await flow.async_step_manual_confirm()
        self.assertNotIn("manual_save", menu["menu_options"])
        blocked = await flow.async_step_manual_save()
        self.assertEqual(blocked["step_id"], "manual_confirm")
        self.assertNotIn("manual_save", blocked["menu_options"])

    async def test_identified_collector_only_selector_label_includes_pn_and_route(self) -> None:
        flow = self._make_flow()
        flow.hass.config.language = "uk"
        result = OnboardingResult(
            collector=CollectorCandidate(
                target_ip="192.168.1.55",
                source="subnet_unicast",
                ip="192.168.1.1",
                connected=True,
                collector=CollectorInfo(collector_pn="E50000200000000001"),
            ),
            connection_mode="subnet_unicast",
            next_action="manual_driver_selection",
        )

        await flow._async_ensure_translation_bundle()
        label = flow._result_label(result)

        self.assertIn("PN E50000200000000001", label)
        self.assertIn("192.168.1.1", label)
        self.assertNotIn("виберіть", label.lower())

    def _flow_with_verified_selected_callback_route(self):
        """Model the exact post-recovery state of a NAT/hairpin scan result."""

        from custom_components.eybond_local.connection.admission import (
            CollectorAdmissionRequest,
        )
        from custom_components.eybond_local.connection.admission_transaction import (
            CollectorAdmissionTransaction,
        )
        from custom_components.eybond_local.connection.recovery.terminal import (
            RecoveryTerminalInput,
        )
        from custom_components.eybond_local.connection.recovery_contract import (
            CALLBACK_RECOVERY_RESET_UNICAST_RECONNECT,
            CallbackRecoveryProof,
        )

        flow = self._make_flow()
        route = CallbackRecoveryRoute(
            bind_ip="192.168.1.50",
            trigger_target_ip="192.168.1.55",
            trigger_udp_port=58899,
            advertised_ha_host="192.168.1.50",
            advertised_ha_port=8899,
            listener_port=8899,
        )
        selected = self._callback_listener_selected_result(
            with_observed_session=True
        )
        flow._selected_result = selected
        request = CollectorAdmissionRequest(
            observed_session=selected.observed_session,
            origin="scan_selected_route",
            callback_route=route,
        )
        transaction = CollectorAdmissionTransaction(
            request,
            registry_provider=flow._callback_session_registry,
            listener_host="0.0.0.0",
            policy_provider=lambda: config_common_module._ONBOARDING_TIMEOUT_POLICY,
        )
        proof = CallbackRecoveryProof(
            method=CALLBACK_RECOVERY_RESET_UNICAST_RECONNECT,
            collector_pn=self.FULL_PN,
            identity_source="fc2_parameter_2",
            verified_at="2026-07-22T10:00:00+00:00",
            trigger_target=route.trigger_target,
            advertised_ha_endpoint=route.advertised_ha_endpoint,
            listener_port=route.listener_port,
        )
        transaction._callback_terminal_input = RecoveryTerminalInput(
            collector_pn=self.FULL_PN,
            callback_proof=proof,
            prepared_handoff_owner="callback_recovery:test",
        )
        flow._admission_transaction = transaction
        flow._callback_continuation = transaction
        flow._verified_connection_strategy = CONNECTION_STRATEGY_CALLBACK_ON_DEMAND
        return flow, route

    async def test_verified_callback_route_and_tcp_peer_are_presented_separately(
        self,
    ) -> None:
        flow, route = self._flow_with_verified_selected_callback_route()
        flow.hass.config.language = "uk"
        await flow._async_ensure_translation_bundle()

        summary = flow._detection_summary_placeholders()
        placeholders = flow._result_placeholders(flow._selected_result)
        table = placeholders["collector_confirm_table"]

        self.assertEqual(summary["tier_headline"], "Колектор перевірено")
        self.assertIn(route.trigger_target_ip, summary["tier_details"])
        self.assertIn(self.PEER_IP, summary["tier_details"])
        self.assertIn("Адреса для callback", table)
        self.assertIn(route.trigger_target_ip, table)
        self.assertIn("Джерело вхідного з’єднання", table)
        self.assertIn(self.PEER_IP, table)
        self.assertEqual(placeholders["collector_ip"], route.trigger_target_ip)

    async def test_matching_callback_route_and_tcp_peer_are_presented_once(
        self,
    ) -> None:
        flow, route = self._flow_with_verified_selected_callback_route()
        flow._selected_result.collector.ip = route.trigger_target_ip
        flow.hass.config.language = "uk"
        await flow._async_ensure_translation_bundle()

        table = flow._result_placeholders(flow._selected_result)[
            "collector_confirm_table"
        ]

        self.assertIn("IP колектора", table)
        self.assertEqual(table.count(route.trigger_target_ip), 1)
        self.assertNotIn("Адреса для callback", table)
        self.assertNotIn("Джерело вхідного з’єднання", table)

    async def test_verified_callback_route_not_tcp_peer_is_persisted_for_runtime(
        self,
    ) -> None:
        from custom_components.eybond_local.connection.recovery_contract import (
            RecoveryContract,
        )

        flow, route = self._flow_with_verified_selected_callback_route()
        flow._selected_result = replace(
            flow._selected_result,
            observed_session=ObservedCollectorSession(
                collector_pn=self.FULL_PN,
                identity_source="fc2_parameter_2",
                session_id=self.OLD_SESSION,
                listener_port=8899,
                protocol_shape="eybond_framed",
                peer_hint=self.PEER_IP,
            ),
        )
        flow._selected_result.collector.session_protocol = ""

        def _run_terminal(_pn, terminal, *, recovery):
            self.assertIs(recovery.callback_proof, transaction.terminal_input.callback_proof)
            return terminal()

        transaction = flow._admission_transaction
        with patch.object(
            flow,
            "_create_entry_with_handoff",
            side_effect=_run_terminal,
        ):
            created = await flow._async_create_entry_from_result()

        self.assertEqual(created["type"], "create_entry")
        data = created["data"]
        self.assertEqual(
            data[const_module.CONF_COLLECTOR_IP], route.trigger_target_ip
        )
        self.assertNotEqual(data[const_module.CONF_COLLECTOR_IP], self.PEER_IP)
        self.assertEqual(data[const_module.CONF_CONNECTION_MODE], "known_ip")
        self.assertEqual(
            data[const_module.CONF_CONNECTION_STRATEGY],
            CONNECTION_STRATEGY_CALLBACK_ON_DEMAND,
        )
        self.assertNotIn("collector_session_protocol", data)
        self.assertEqual(
            data["collector_confirmed_session_protocol"], "eybond_framed"
        )
        self.assertEqual(
            data["collector_confirmed_session_protocol_source"], "live_session"
        )
        self.assertEqual(
            data["collector_confirmed_session_protocol_pn"], self.FULL_PN
        )
        self.assertTrue(data["collector_confirmed_session_protocol_observed_at"])
        contract = RecoveryContract.from_entry_data(data)
        self.assertIsNotNone(contract)
        self.assertEqual(contract.callback_proof.trigger_target, route.trigger_target)

    async def test_stale_passive_scan_session_requires_restart_verification(self) -> None:
        """Deleting an entry must not turn its old callback into inbound proof."""

        flow = self._make_flow()
        inventory = [self._inventory_session(self.OLD_SESSION, self.FULL_PN)]
        registry = self._install_registry(flow, inventory)
        observed = ObservedCollectorSession(
            collector_pn=self.FULL_PN,
            identity_source="at_dtupn",
            session_id=self.OLD_SESSION,
            listener_port=8899,
            protocol_shape="eybond_framed",
            peer_hint=self.PEER_IP,
        )
        flow._autodetect_results = {
            "0": OnboardingResult(
                collector=CollectorCandidate(
                    target_ip="192.168.1.255",
                    source="callback_listener",
                    ip=self.PEER_IP,
                    session_protocol="eybond_framed",
                    connected=True,
                    collector=CollectorInfo(collector_pn=self.FULL_PN),
                ),
                connection_mode="callback_listener",
                next_action="manual_driver_selection",
                observed_session=observed,
                detection=TargetDetectionEvidence(
                    status="collector_only",
                    reason="callback_session_inventory",
                    details={
                        "session_id": self.OLD_SESSION,
                        "collector_identity_source": "at_dtupn",
                    },
                ),
            )
        }

        selected = await flow.async_step_scan_results({CONF_RESULT_KEY: "0"})
        self.assertEqual(selected["type"], "form")
        self.assertEqual(selected["step_id"], "scan_collector_route")
        self.assertIsNone(flow._admission_transaction)

        consent = await flow.async_step_scan_collector_route(
            {"collector_ip": self.PEER_IP}
        )
        self.assertEqual(consent["step_id"], "verify_connection")
        request = flow._admission_transaction.request
        self.assertEqual(request.origin, "scan_selected_route")
        self.assertEqual(request.observed_session, observed)
        self.assertEqual(request.callback_route.trigger_target_ip, self.PEER_IP)
        self.assertEqual(flow._verified_connection_strategy, "")
        self.assertEqual(registry.owner_for_pn(self.FULL_PN), "")

    async def test_single_udp_route_equal_to_exact_peer_skips_redundant_ip_form(
        self,
    ) -> None:
        """One independently responding peer may enter the same proof transaction."""

        flow = self._make_flow()
        observed = ObservedCollectorSession(
            collector_pn=self.FULL_PN,
            identity_source="at_dtupn",
            session_id=self.OLD_SESSION,
            listener_port=8899,
            protocol_shape="eybond_framed",
            peer_hint=self.PEER_IP,
        )
        flow._autodetect_results = {
            "0": OnboardingResult(
                collector=CollectorCandidate(
                    target_ip="192.168.1.255",
                    source="callback_listener",
                    ip=self.PEER_IP,
                    connected=True,
                    collector=CollectorInfo(collector_pn=self.FULL_PN),
                ),
                connection_mode="callback_listener",
                observed_session=observed,
                detection=TargetDetectionEvidence(
                    status="collector_only",
                    reason="callback_session_inventory",
                ),
            )
        }
        flow._scan_responded_addresses = {self.PEER_IP}

        result = await flow.async_step_scan_results({CONF_RESULT_KEY: "0"})

        self.assertEqual(result["step_id"], "verify_connection")
        request = flow._admission_transaction.request
        self.assertEqual(request.origin, "scan_selected_route")
        self.assertEqual(
            request.callback_route.trigger_target_ip,
            self.PEER_IP,
        )

    async def test_multiple_udp_routes_never_guess_one_from_the_tcp_peer(self) -> None:
        flow = self._make_flow()
        observed = ObservedCollectorSession(
            collector_pn=self.FULL_PN,
            identity_source="at_dtupn",
            session_id=self.OLD_SESSION,
            listener_port=8899,
            protocol_shape="eybond_framed",
            peer_hint=self.PEER_IP,
        )
        flow._autodetect_results = {
            "0": OnboardingResult(
                collector=CollectorCandidate(
                    target_ip="192.168.1.255",
                    source="callback_listener",
                    ip=self.PEER_IP,
                    connected=True,
                    collector=CollectorInfo(collector_pn=self.FULL_PN),
                ),
                connection_mode="callback_listener",
                observed_session=observed,
            )
        }
        flow._scan_responded_addresses = {
            self.PEER_IP,
            "192.168.1.99",
        }

        result = await flow.async_step_scan_results({CONF_RESULT_KEY: "0"})

        self.assertEqual(result["step_id"], "scan_collector_route")
        self.assertIsNone(flow._admission_transaction)

    def _admission_request(self, origin: str) -> "CollectorAdmissionRequest":
        return CollectorAdmissionRequest(
            observed_session=ObservedCollectorSession(
                collector_pn=self.FULL_PN,
                identity_source="at_dtupn",
                session_id=self.OLD_SESSION,
                listener_port=8899,
                peer_hint=self.PEER_IP,
            ),
            origin=origin,
        )

    def _admission_transaction(self, origin: str, flow):
        from custom_components.eybond_local.connection.admission_transaction import (
            CollectorAdmissionTransaction,
        )

        return CollectorAdmissionTransaction(
            self._admission_request(origin),
            registry_provider=flow._callback_session_registry,
            listener_host="0.0.0.0",
            policy_provider=lambda: config_common_module._ONBOARDING_TIMEOUT_POLICY,
        )

    def _verified_inbound_terminal(self):
        from custom_components.eybond_local.connection.recovery_contract import (
            InboundRecoveryProof,
        )
        from custom_components.eybond_local.connection.recovery.terminal import (
            RecoveryTerminalInput,
        )
        from custom_components.eybond_local.connection.recovery.verification import (
            STATE_INBOUND_VERIFIED,
            InboundRecoveryOutcome,
        )

        proof = InboundRecoveryProof(
            method="reboot_reconnect_no_trigger",
            collector_pn=self.FULL_PN,
            identity_source="at_dtupn",
            verified_at="2026-07-20T00:00:00+00:00",
            session_protocol="eybond_framed",
        )
        outcome = InboundRecoveryOutcome(
            status=STATE_INBOUND_VERIFIED,
            collector_pn=self.FULL_PN,
            new_session_id=self.NEW_SESSION,
            proof=proof,
        )
        return RecoveryTerminalInput.from_inbound_outcome(outcome)

    def _callback_listener_selected_result(self, *, with_observed_session: bool):
        observed = (
            ObservedCollectorSession(
                collector_pn=self.FULL_PN,
                identity_source="at_dtupn",
                session_id=self.OLD_SESSION,
                listener_port=8899,
                peer_hint=self.PEER_IP,
            )
            if with_observed_session
            else None
        )
        return OnboardingResult(
            collector=CollectorCandidate(
                target_ip="192.168.1.255",
                source="callback_listener",
                ip=self.PEER_IP,
                connected=True,
                collector=CollectorInfo(collector_pn=self.FULL_PN),
            ),
            connection_mode="callback_listener",
            next_action="manual_driver_selection",
            observed_session=observed,
            detection=TargetDetectionEvidence(
                status="collector_only",
                reason="callback_session_inventory",
            ),
        )

    # Terminal matrix -- the fail-closed guard is SOURCE-NEUTRAL: it keys on the
    # typed in-flight CollectorAdmissionRequest, so it protects BOTH integration
    # discovery (whose selected result carries no observed_session) and passive
    # scan identically, and never inspects origin.

    async def test_A_terminal_refuses_discovery_admission_without_proof(self) -> None:
        """Integration discovery: admission request set, selected result has NO
        observed_session, inbound/external, no proof -> recovery_ownership_unavailable.
        This is the source-neutral hole the corrective closes."""

        flow = self._make_flow()
        flow._admission_transaction = self._admission_transaction("integration_discovery", flow)
        flow._callback_continuation = flow._admission_transaction
        # Integration discovery's selected result carries no observed_session.
        flow._selected_result = self._callback_listener_selected_result(
            with_observed_session=False
        )

        with patch.object(
            flow,
            "_create_entry_with_handoff",
            side_effect=AssertionError("unverified inbound reached create terminal"),
        ):
            result = await flow._async_create_entry_from_result()

        self.assertEqual(result["type"], "abort")
        self.assertEqual(result["reason"], "recovery_ownership_unavailable")

    async def test_B_terminal_allows_discovery_admission_with_verified_proof(self) -> None:
        """Same integration-discovery path WITH a valid InboundRecoveryProof ->
        the entry is created (the guard steps aside for a real proof)."""

        flow = self._make_flow()
        flow._admission_transaction = self._admission_transaction("integration_discovery", flow)
        flow._callback_continuation = flow._admission_transaction
        flow._selected_result = self._callback_listener_selected_result(
            with_observed_session=False
        )
        flow._verified_connection_strategy = CONNECTION_STRATEGY_INBOUND
        terminal = self._verified_inbound_terminal()
        from custom_components.eybond_local.connection.recovery.verification import (
            InboundRecoveryOutcome,
            STATE_INBOUND_VERIFIED,
        )

        flow._admission_transaction._outcome = InboundRecoveryOutcome(
            status=STATE_INBOUND_VERIFIED,
            collector_pn=self.FULL_PN,
            new_session_id=self.NEW_SESSION,
            proof=terminal.inbound_proof,
        )
        flow._admission_transaction._state = "verified"

        sentinel = {"type": "create_entry", "created": True}
        with patch.object(
            flow, "_create_entry_with_handoff", return_value=sentinel
        ):
            result = await flow._async_create_entry_from_result()

        # Reached creation -- the guard did NOT abort with recovery_ownership_unavailable.
        self.assertIs(result, sentinel)

    async def test_C_terminal_refuses_passive_admission_without_proof(self) -> None:
        """Passive scan preserves the same fail-closed result (unchanged)."""

        flow = self._make_flow()
        flow._admission_transaction = self._admission_transaction("passive_scan", flow)
        flow._callback_continuation = flow._admission_transaction
        flow._selected_result = self._callback_listener_selected_result(
            with_observed_session=True
        )

        with patch.object(
            flow,
            "_create_entry_with_handoff",
            side_effect=AssertionError("unverified inbound reached create terminal"),
        ):
            result = await flow._async_create_entry_from_result()

        self.assertEqual(result["type"], "abort")
        self.assertEqual(result["reason"], "recovery_ownership_unavailable")

    async def test_D_manual_callback_bridge_keeps_transaction_as_continuation(
        self,
    ) -> None:
        """2D.2: the explicit manual-callback bridge KEEPS the same admission
        transaction as the flow's continuation -- no hand-across, no close -- and
        transitions it from the failed inbound attempt into its callback-ready
        lifecycle. The terminal guard stays inert for the resulting callback entry
        because its strategy is callback_on_demand, not inbound."""

        from custom_components.eybond_local.connection.recovery.verification import (
            InboundRecoveryOutcome,
        )

        flow = self._make_flow()
        await flow.async_step_integration_discovery(self._discovery_info())
        txn = flow._admission_transaction
        self.assertIsInstance(txn, admission_transaction_module.CollectorAdmissionTransaction)
        # Source boundary: the transaction IS the flow's continuation.
        self.assertIs(flow._callback_continuation, txn)
        # Reach a FAILED inbound attempt (real async_run's post-condition).
        txn._outcome = InboundRecoveryOutcome(
            failure_reason="inbound_reconnect_timeout", collector_pn=self.FULL_PN
        )
        txn._state = "failed"

        result = await flow.async_step_verify_connection_manual_callback()
        self.assertEqual(result["step_id"], "manual")
        self.assertEqual(flow._manual_preselected_strategy, "callback_on_demand")
        # KEPT (not cleared) and transitioned into its callback lifecycle.
        self.assertIs(flow._admission_transaction, txn)
        self.assertIs(flow._callback_continuation, txn)
        self.assertEqual(txn.state, "callback_ready")
        # No hand-across: the same transaction retains its typed context.
        self.assertEqual(txn.identity_context.expected_pn, self.FULL_PN)
        self.assertEqual(txn.identity_context.old_session_id, self.OLD_SESSION)
        # The terminal guard is inert for a callback-strategy entry.
        self.assertFalse(
            flow._fresh_observed_session_entry_is_unverified(
                {const_module.CONF_CONNECTION_STRATEGY: "callback_on_demand"},
                {},
            )
        )

    async def test_selected_route_failure_can_enter_manual_without_unknown_error(
        self,
    ) -> None:
        """Regression: route failure -> manual submit never reuses READY state."""

        from custom_components.eybond_local.connection.callback_identity import (
            CallbackIdentityOutcome,
        )
        from custom_components.eybond_local.connection.recovery.verification import (
            CallbackRecoveryRoute,
        )

        flow = self._make_flow()
        observed = ObservedCollectorSession(
            collector_pn=self.FULL_PN,
            identity_source="fc2_parameter_2",
            session_id=self.OLD_SESSION,
            listener_port=18899,
            protocol_shape="eybond_framed",
            peer_hint=self.PEER_IP,
        )
        request = CollectorAdmissionRequest(
            observed_session=observed,
            origin="scan_selected_route",
            callback_route=CallbackRecoveryRoute(
                bind_ip="192.168.1.50",
                trigger_target_ip=self.PEER_IP,
                trigger_udp_port=58899,
                advertised_ha_host="192.168.1.50",
                advertised_ha_port=18899,
                listener_port=18899,
            ),
        )
        transaction = admission_transaction_module.CollectorAdmissionTransaction(
            request,
            registry_provider=lambda: None,
            listener_host="0.0.0.0",
            hass_provider=lambda: flow.hass,
        )
        flow._admission_transaction = transaction
        flow._callback_continuation = transaction

        # Exact production hole: a selected route can reach its failure menu
        # before READY changed. Choosing manual used to leave READY untouched;
        # async_run_identity then raised into aiohttp as an unknown error.
        manual = await flow.async_step_verify_connection_manual_callback()
        self.assertEqual(manual["step_id"], "manual")
        self.assertEqual(transaction.state, "callback_ready")

        async def _identity(_hass, _request):
            return CallbackIdentityOutcome(result="callback_timeout")

        with patch.object(
            admission_transaction_module,
            "async_run_callback_identity_transaction",
            side_effect=_identity,
        ):
            result = await flow.async_step_manual(
                self._manual_input(
                    self.PEER_IP,
                    connection_strategy="callback_on_demand",
                )
            )

        self.assertEqual(result["type"], "menu")
        self.assertEqual(result["step_id"], "manual_confirm")
        self.assertEqual(transaction.state, "callback_ready")

    # ---- blocker 1: weak->strong enrichment must retarget a retry onto the
    # ---- replacement full-PN session, not the stale observation.

    SHORT_PN = "V001020SYN6234"  # 14-char heartbeat prefix of FULL_PN

    def _fast_restart_policy(self):
        from dataclasses import replace

        return replace(
            config_common_module._ONBOARDING_TIMEOUT_POLICY,
            inbound_restart_disconnect_timeout=0.05,
            inbound_reconnect_timeout=0.05,
            inbound_strong_identity_timeout=0.05,
            callback_causality_lease_wait=0.5,
        )

    @staticmethod
    def _capturing_restart_channel(captured: dict):
        class _FakeChannel:
            def __init__(self, **kwargs) -> None:
                captured.update(kwargs)

            async def async_send_restart(self) -> None:
                captured["restarted"] = True

            def is_connected(self) -> bool:
                return False

            async def async_probe_identity(self) -> str:
                return ""

            async def async_close(self) -> None:
                return None

        return _FakeChannel

    async def test_weak_retry_retargets_replacement_full_pn_session(self) -> None:
        """weak S1 -> typed full-PN enrichment -> failure screen -> replacement
        full-PN S2 -> retry claims/restarts S2. The stale S1 and a foreign
        full-PN session are never used. Load-bearing for blocker 1: without the
        enriched-PN fix the retry would re-resolve by the SHORT PN onto S1."""

        from custom_components.eybond_local.connection.recovery.verification import (
            InboundRecoveryOutcome,
        )

        flow = self._make_flow()
        # Discovery observes only a WEAK short heartbeat PN on session S1.
        await flow.async_step_integration_discovery(
            self._discovery_info(
                collector_pn=self.SHORT_PN,
                collector_identity_source="framed_heartbeat",
            )
        )
        self.assertEqual(flow._admission_transaction.expected_pn, self.SHORT_PN)

        # First verification FAILS but the typed outcome carries the strong FULL
        # PN (the promote hook read it). Enrichment adopts it.
        async def _first_run() -> None:
            flow._admission_transaction._outcome = InboundRecoveryOutcome(
                failure_reason="inbound_reconnect_timeout",
                collector_pn=self.FULL_PN,
            )
            flow._admission_transaction._adopt_enriched_pn_from_outcome()

        with patch.object(
            flow._admission_transaction, "async_run", side_effect=_first_run
        ):
            failed = await self._drive_verification(flow)
        self.assertEqual(failed["step_id"], "verify_connection_failed")
        # Enrichment moved the CURRENT expected identity to the full PN; the
        # immutable observation still records the original short PN.
        self.assertEqual(flow._admission_transaction.expected_pn, self.FULL_PN)
        self.assertEqual(
            flow._admission_transaction.request.observed_session.collector_pn, self.SHORT_PN
        )

        # The collector rebooted: S1 is gone, a replacement full-PN S2 dialed in,
        # plus an unrelated FOREIGN full-PN session shares the listener.
        inventory = [
            self._inventory_session(
                self.NEW_SESSION, self.FULL_PN, state="routed_framed"
            ),
            self._inventory_session(
                "listener-18899-9", self.OTHER_FULL_PN, state="routed_framed"
            ),
        ]
        registry = self._install_registry(flow, inventory)

        captured: dict = {}
        with patch.object(
            admission_transaction_module,
            "ObservedSessionRestartChannel",
            self._capturing_restart_channel(captured),
        ), patch.object(
            config_admission_module, "_ONBOARDING_TIMEOUT_POLICY", self._fast_restart_policy()
        ):
            await flow.async_step_verify_connection_retry()
            await self._drive_verification(flow)

        # The retry resolved, claimed and restarted the REPLACEMENT full-PN S2 --
        # via the enriched full PN, never the stale short PN / S1 / the foreign one.
        self.assertTrue(captured.get("restarted"))
        self.assertEqual(captured.get("collector_pn"), self.FULL_PN)
        self.assertEqual(captured.get("session_id"), self.NEW_SESSION)
        self.assertNotEqual(captured.get("session_id"), self.OLD_SESSION)

    async def test_weak_verification_ignores_poisoned_discovery_identity_source(
        self,
    ) -> None:
        """blocker 2: the observation is weak; the eybond_discovery context is
        deliberately poisoned with a STRONG source. Verification must still use the
        WEAK exact-PN rule (from the typed observation only) and NOT reconcile onto
        a prefix-matched full-PN session."""

        flow = self._make_flow()
        # The observation carries an EMPTY (unknown-weak) identity source -- exactly
        # the case the removed fallback used to fill from the discovery context.
        await flow.async_step_integration_discovery(
            self._discovery_info(
                collector_pn=self.SHORT_PN,
                collector_identity_source="",
            )
        )
        self.assertEqual(flow._admission_transaction.request.observed_session.identity_source, "")
        # Poison the discovery context with a strong source. If the run read it,
        # require_exact would flip to False and reconcile onto the full-PN session.
        flow.context["eybond_discovery"]["collector_identity_source"] = "at_dtupn"

        inventory = [
            # S1: the exact weak short-PN session (the only correct target).
            self._inventory_session(
                self.OLD_SESSION,
                self.SHORT_PN,
                state="routed_framed",
                identity_source="framed_heartbeat",
            ),
            # A longer full-PN session the SHORT PN is a prefix of -- must NOT be
            # chosen under weak rules.
            self._inventory_session(
                self.NEW_SESSION, self.FULL_PN, state="routed_framed"
            ),
        ]
        self._install_registry(flow, inventory)

        captured: dict = {}
        with patch.object(
            admission_transaction_module,
            "ObservedSessionRestartChannel",
            self._capturing_restart_channel(captured),
        ), patch.object(
            config_admission_module, "_ONBOARDING_TIMEOUT_POLICY", self._fast_restart_policy()
        ):
            await self._drive_verification(flow)

        # Weak exact-PN rule held: the exact short-PN S1 was targeted, NOT the
        # prefix-matched full session.
        self.assertEqual(captured.get("collector_pn"), self.SHORT_PN)
        self.assertEqual(captured.get("session_id"), self.OLD_SESSION)
        self.assertNotEqual(captured.get("session_id"), self.NEW_SESSION)

    # Verification failure stays retryable in THIS discovery flow. Manual setup
    # remains an explicit choice and keeps the peer IP as an editable hint.
    async def test_verification_failure_falls_through_to_manual_with_peer_prefill(self) -> None:
        from custom_components.eybond_local.connection.recovery.verification import (
            InboundRecoveryOutcome,
        )

        flow = self._make_flow()
        await flow.async_step_integration_discovery(self._discovery_info())

        async def _fake_run() -> None:
            flow._admission_transaction._outcome = InboundRecoveryOutcome(
                failure_reason="restart_not_supported",
                collector_pn=self.FULL_PN,
            )
            flow._admission_transaction._adopt_enriched_pn_from_outcome()
            flow._admission_transaction._state = "failed"  # real async_run's post-cond

        with patch.object(flow._admission_transaction, "async_run", side_effect=_fake_run):
            result = await self._drive_verification(flow)

        self.assertEqual(result["type"], "menu")
        self.assertEqual(result["step_id"], "verify_connection_failed")
        # Three EXPLICIT actions -- no abstract "Manual".
        self.assertEqual(
            result["menu_options"],
            [
                "verify_connection_retry",
                "verify_connection_manual_callback",
                "verify_connection_cancel",
            ],
        )
        # A typed, human explanation of the exact reason (not a raw code).
        explanation = result["description_placeholders"]["failure_explanation"]
        self.assertNotIn("`", explanation)
        self.assertNotIn("restart_not_supported", explanation)
        self.assertGreater(len(explanation), 20)

        retry = await flow.async_step_verify_connection_retry()
        self.assertEqual(retry["type"], "form")
        self.assertEqual(retry["step_id"], "verify_connection")

        # In real use the retry re-runs inbound and fails again before the menu;
        # reflect that FAILED post-condition so the bridge is reached honestly.
        flow._admission_transaction._outcome = InboundRecoveryOutcome(
            failure_reason="restart_not_supported", collector_pn=self.FULL_PN
        )
        flow._admission_transaction._state = "failed"

        # The EXPLICIT callback action opens the existing manual step with
        # callback_on_demand pre-selected and the peer IP as an editable hint.
        result = await flow.async_step_verify_connection_manual_callback()
        self.assertEqual(result["type"], "form")
        self.assertEqual(result["step_id"], "manual")
        self.assertEqual(
            flow._manual_preselected_strategy, "callback_on_demand"
        )
        # Peer IP is prefilled purely as an editable hint...
        self.assertEqual(flow._manual_defaults.get("collector_ip"), self.PEER_IP)
        # ...with honest labeling about router/VPN/port-forward setups.
        note = result["description_placeholders"]["verification_note"]
        self.assertIn("router", note.lower())
        # No strategy was guessed and no entry was created.
        self.assertEqual(flow._verified_connection_strategy, "")
        # 2D.2: the SAME transaction is KEPT as the continuation (no hand-across,
        # no close) and is now callback-ready with its typed identity context.
        self.assertIsNotNone(flow._admission_transaction)
        self.assertEqual(flow._admission_transaction.state, "callback_ready")
        self.assertEqual(
            flow._callback_continuation.identity_context.expected_pn, self.FULL_PN
        )

    # Batch 7 -- the failure screen explains the exact reason in the user's
    # language (ru/uk), never the raw code, for every inbound failure code.
    async def test_verification_failed_explanation_is_localized(self) -> None:
        from custom_components.eybond_local.connection.recovery.verification import (
            InboundRecoveryOutcome,
        )

        for code in (
            "restart_not_supported",
            "inbound_reconnect_timeout",
            "recovery_silent_probe_failed",
            "reconnected_session_untrusted",
        ):
            english = {}
            for language in ("en", "ru", "uk"):
                flow = self._make_flow()
                flow.context = {"language": language}
                await flow.async_step_integration_discovery(self._discovery_info())
                flow._admission_transaction._outcome = InboundRecoveryOutcome(
                    failure_reason=code, collector_pn=self.FULL_PN
                )
                flow._admission_transaction._adopt_enriched_pn_from_outcome()
                await flow._async_ensure_translation_bundle()
                result = await flow.async_step_verify_connection_failed()
                explanation = result["description_placeholders"]["failure_explanation"]
                self.assertNotIn(code, explanation)
                self.assertNotIn("`", explanation)
                english[language] = explanation
            with self.subTest(code=code):
                self.assertNotEqual(english["ru"], english["en"])
                self.assertNotEqual(english["uk"], english["en"])
                self.assertTrue(any("Ѐ" <= ch <= "ӿ" for ch in english["ru"]))

    # B. A collector observed via a temporary callback session fails inbound
    # verification; the user EXPLICITLY chooses manual callback, and the
    # existing callback path (not a new matcher) proves it.
    async def test_failed_inbound_handoff_to_explicit_manual_callback(self) -> None:
        from custom_components.eybond_local.connection.recovery.verification import (
            InboundRecoveryOutcome,
        )

        flow = self._make_flow()
        inventory = [self._inventory_session(self.OLD_SESSION, self.FULL_PN)]
        registry = self._install_registry(flow, inventory)
        await flow.async_step_integration_discovery(self._discovery_info())

        async def _fake_run() -> None:
            # Inbound autonomous reconnect was NOT proven; the failure path
            # already released any strategy-verification claim.
            flow._admission_transaction._outcome = InboundRecoveryOutcome(
                failure_reason="inbound_reconnect_timeout",
                collector_pn=self.FULL_PN,
            )
            flow._admission_transaction._adopt_enriched_pn_from_outcome()
            flow._admission_transaction._state = "failed"  # real async_run's post-cond

        with patch.object(flow._admission_transaction, "async_run", side_effect=_fake_run):
            failed = await self._drive_verification(flow)
        self.assertEqual(failed["step_id"], "verify_connection_failed")
        # No inbound owner survives into the callback attempt.
        self.assertEqual(registry.owner_for_pn(self.FULL_PN), "")

        # The EXPLICIT callback action opens the manual step.
        manual = await flow.async_step_verify_connection_manual_callback()
        self.assertEqual(manual["step_id"], "manual")
        self.assertEqual(flow._manual_preselected_strategy, "callback_on_demand")
        self.assertEqual(flow._manual_defaults.get("collector_ip"), self.PEER_IP)
        # 2D.2: NO hand-across -- the transaction (the continuation) carries the
        # expected strong PN in its identity context; nothing is copied to flow.
        self.assertEqual(
            flow._callback_continuation.identity_context.expected_pn, self.FULL_PN
        )
        self.assertEqual(flow._admission_transaction.state, "callback_ready")

        # Submitting the manual form runs the EXISTING callback identity path;
        # the collector answers OUR trigger with a new strong session, and the
        # flow reaches the callback recovery consent -- no second verifier.
        with self._identity_wire(
            inventory,
            answers=[self._inventory_session(self.NEW_SESSION, self.FULL_PN)],
            read_pn=self.FULL_PN,
        ):
            routed = await flow.async_step_manual(
                self._manual_input(self.PEER_IP, connection_strategy="callback_on_demand")
            )
        self.assertEqual(routed["step_id"], "manual_recovery_confirm")
        # The transaction (the continuation) holds the certified PN; nothing is
        # copied into flow-owned callback lifecycle state.
        self.assertEqual(flow._callback_continuation.certified_pn, self.FULL_PN)
        self.assertNotIn("_manual_verified_full_pn", vars(flow))
        # A callback owner now holds the certified session (a NEW owner id).
        owner = registry.owner_for_pn(self.FULL_PN)
        self.assertTrue(owner.startswith("callback_verification:"))

    async def test_failed_inbound_then_manual_inbound_cannot_reuse_stale_session(
        self,
    ) -> None:
        """Changing intent back to inbound cannot bypass the failed restart proof."""

        from custom_components.eybond_local.connection.recovery.verification import (
            InboundRecoveryOutcome,
        )

        flow = self._make_flow()
        inventory = [self._inventory_session(self.OLD_SESSION, self.FULL_PN)]
        registry = self._install_registry(flow, inventory)
        await flow.async_step_integration_discovery(self._discovery_info())

        async def _fake_run() -> None:
            flow._admission_transaction._outcome = InboundRecoveryOutcome(
                failure_reason="inbound_reconnect_timeout",
                collector_pn=self.FULL_PN,
            )
            flow._admission_transaction._adopt_enriched_pn_from_outcome()
            flow._admission_transaction._state = "failed"

        with patch.object(flow._admission_transaction, "async_run", side_effect=_fake_run):
            failed = await self._drive_verification(flow)
        self.assertEqual(failed["step_id"], "verify_connection_failed")
        await flow.async_step_verify_connection_manual_callback()

        created = await flow.async_step_manual(
            self._manual_input(self.PEER_IP, connection_strategy="inbound")
        )

        self.assertEqual(created["type"], "menu")
        self.assertEqual(created["step_id"], "manual_confirm")
        self.assertIn("manual_enable_background_discovery", created["menu_options"])
        self.assertNotIn("manual_save", created["menu_options"])
        self.assertEqual(registry.owner_for_pn(self.FULL_PN), "")
        self.assertEqual(
            flow._callback_continuation.identity_context.expected_pn, self.FULL_PN
        )
        self.assertEqual(flow._callback_continuation.certified_pn, "")

    async def test_async_remove_during_admission_identity_releases_delayed_owner(
        self,
    ) -> None:
        """A removed admission flow cannot resurrect after identity returns."""

        from custom_components.eybond_local.connection.callback_identity import (
            CallbackIdentityOutcome,
        )
        from custom_components.eybond_local.connection.recovery.verification import (
            InboundRecoveryOutcome,
        )
        import custom_components.eybond_local.connection.admission_transaction as at

        flow = self._make_flow()
        inventory = [self._inventory_session(self.OLD_SESSION, self.FULL_PN)]
        registry = self._install_registry(flow, inventory)
        await flow.async_step_integration_discovery(self._discovery_info())
        transaction = flow._admission_transaction
        transaction._outcome = InboundRecoveryOutcome(
            failure_reason="inbound_reconnect_timeout", collector_pn=self.FULL_PN
        )
        transaction._state = "failed"
        await flow.async_step_verify_connection_manual_callback()

        entered = asyncio.Event()
        resume = asyncio.Event()
        owner = "callback_verification:flow-remove"
        new_session = self.NEW_SESSION

        async def _authority(_hass, _request, **_kwargs):
            inventory.append(self._inventory_session(new_session, self.FULL_PN))
            registry.claim_session(owner, session_id=new_session)
            registry.promote_claim_to_full_pn(owner, self.FULL_PN)
            self.assertTrue(registry.prepare_handoff(owner, self.FULL_PN))
            entered.set()
            await resume.wait()
            return CallbackIdentityOutcome(
                result="",
                collector_pn=self.FULL_PN,
                session_id=new_session,
                handoff_owner=owner,
            )

        with patch.object(at, "async_run_callback_identity_transaction", new=_authority):
            task = asyncio.create_task(
                flow.async_step_manual(
                    self._manual_input(
                        self.PEER_IP, connection_strategy="callback_on_demand"
                    )
                )
            )
            await asyncio.wait_for(entered.wait(), timeout=5.0)
            flow.async_remove()
            resume.set()
            with self.assertRaises(asyncio.CancelledError):
                await asyncio.wait_for(task, timeout=5.0)

        self.assertEqual(transaction.state, "closed")
        self.assertEqual(registry.owner_for_pn(self.FULL_PN), "")

    async def test_async_remove_during_admission_recovery_releases_delayed_owner(
        self,
    ) -> None:
        """A removed admission flow cannot publish a late recovery capability."""

        from custom_components.eybond_local.connection.callback_identity import (
            CallbackIdentityOutcome,
        )
        from custom_components.eybond_local.connection.recovery.verification import (
            RecoveryVerificationOutcome,
            STATE_CALLBACK_VERIFIED,
            InboundRecoveryOutcome,
        )
        from custom_components.eybond_local.connection.recovery_contract import (
            CALLBACK_RECOVERY_RESET_UNICAST_RECONNECT,
            CallbackRecoveryProof,
        )
        import custom_components.eybond_local.connection.admission_transaction as at

        flow = self._make_flow()
        inventory = [self._inventory_session(self.OLD_SESSION, self.FULL_PN)]
        registry = self._install_registry(flow, inventory)
        await flow.async_step_integration_discovery(self._discovery_info())
        transaction = flow._admission_transaction
        transaction._outcome = InboundRecoveryOutcome(
            failure_reason="inbound_reconnect_timeout", collector_pn=self.FULL_PN
        )
        transaction._state = "failed"
        await flow.async_step_verify_connection_manual_callback()

        identity_owner = "callback_verification:flow-recovery-remove"

        async def _identity_authority(_hass, _request, **_kwargs):
            inventory.append(self._inventory_session(self.NEW_SESSION, self.FULL_PN))
            registry.claim_session(identity_owner, session_id=self.NEW_SESSION)
            registry.promote_claim_to_full_pn(identity_owner, self.FULL_PN)
            self.assertTrue(registry.prepare_handoff(identity_owner, self.FULL_PN))
            return CallbackIdentityOutcome(
                result="",
                collector_pn=self.FULL_PN,
                session_id=self.NEW_SESSION,
                handoff_owner=identity_owner,
            )

        with patch.object(
            at, "async_run_callback_identity_transaction", new=_identity_authority
        ):
            routed = await flow.async_step_manual(
                self._manual_input(
                    self.PEER_IP, connection_strategy="callback_on_demand"
                )
            )
        self.assertEqual(routed["step_id"], "manual_recovery_confirm")

        entered = asyncio.Event()
        resume = asyncio.Event()
        recovery_owner = "callback_recovery:flow-remove"

        async def _recovery_authority(**kwargs):
            registry.claim_session(recovery_owner, session_id=self.NEW_SESSION)
            registry.promote_claim_to_full_pn(recovery_owner, self.FULL_PN)
            self.assertTrue(registry.prepare_handoff(recovery_owner, self.FULL_PN))
            entered.set()
            try:
                await resume.wait()
            except asyncio.CancelledError:
                # Model an authority which completes its mandatory cleanup boundary
                # before returning the capability it produced concurrently with the
                # flow cancellation.
                await resume.wait()
            route = kwargs["route"]
            return RecoveryVerificationOutcome(
                status=STATE_CALLBACK_VERIFIED,
                collector_pn=self.FULL_PN,
                new_session_id=self.NEW_SESSION,
                callback_proof=CallbackRecoveryProof(
                    method=CALLBACK_RECOVERY_RESET_UNICAST_RECONNECT,
                    collector_pn=self.FULL_PN,
                    identity_source="fc2_parameter_2",
                    verified_at="2026-07-20T10:00:00+00:00",
                    trigger_target=route.trigger_target,
                    advertised_ha_endpoint=route.advertised_ha_endpoint,
                    listener_port=route.listener_port,
                ),
                handoff_owner=recovery_owner,
            )

        with patch.object(
            at, "async_run_callback_recovery_transaction", new=_recovery_authority
        ):
            progress = await flow.async_step_manual_recovery_verify()
            self.assertEqual(progress["type"], "progress")
            task = flow._manual_recovery_task
            await asyncio.wait_for(entered.wait(), timeout=5.0)
            flow.async_remove()
            resume.set()
            with self.assertRaises(asyncio.CancelledError):
                await asyncio.wait_for(task, timeout=5.0)

        self.assertEqual(transaction.state, "closed")
        self.assertEqual(registry.owner_for_pn(self.FULL_PN), "")
        self.assertIsNone(flow._callback_continuation._recovery_outcome)

    # C. Cancelling from the failure screen aborts cleanly: no claim, no task,
    # no prepared handoff -- and no entry.
    async def test_cancel_from_failure_screen_is_clean(self) -> None:
        from custom_components.eybond_local.connection.recovery.verification import (
            InboundRecoveryOutcome,
        )

        flow = self._make_flow()
        inventory = [self._inventory_session(self.OLD_SESSION, self.FULL_PN)]
        registry = self._install_registry(flow, inventory)
        await flow.async_step_integration_discovery(self._discovery_info())

        async def _fake_run() -> None:
            flow._admission_transaction._outcome = InboundRecoveryOutcome(
                failure_reason="restart_not_confirmed",
                collector_pn=self.FULL_PN,
            )
            flow._admission_transaction._adopt_enriched_pn_from_outcome()

        with patch.object(flow._admission_transaction, "async_run", side_effect=_fake_run):
            failed = await self._drive_verification(flow)
        self.assertEqual(failed["step_id"], "verify_connection_failed")

        cancelled = await flow.async_step_verify_connection_cancel()
        self.assertEqual(cancelled["type"], "abort")
        self.assertEqual(cancelled["reason"], "discovery_cancelled")
        # Nothing is owned, held or prepared for the PN.
        self.assertEqual(registry.owner_for_pn(self.FULL_PN), "")
        self.assertEqual(flow._callback_continuation._owner, "")
        self.assertIsNone(flow._admission_transaction)

    async def test_cancel_during_progress_cleans_up_via_async_remove(self) -> None:
        import asyncio

        flow = self._make_flow()
        inventory = [self._inventory_session(self.OLD_SESSION, self.FULL_PN)]
        registry = self._install_registry(flow, inventory)
        await flow.async_step_integration_discovery(self._discovery_info())

        started = asyncio.Event()

        async def _hang() -> None:
            # The verifier claims the session, then never resolves until cancel.
            registry.claim_session("strategy_verification:hang", session_id=self.OLD_SESSION)
            flow._callback_continuation._registry = registry
            flow._callback_continuation._owner = "strategy_verification:hang"
            started.set()
            await asyncio.sleep(60)

        with patch.object(flow._admission_transaction, "async_run", side_effect=_hang):
            await flow.async_step_verify_connection({})
            progress = await flow.async_step_verify_connection_progress()
            self.assertEqual(progress["type"], "progress")
            await asyncio.wait_for(started.wait(), timeout=5.0)
            task = flow._admission_task

            flow.async_remove()  # frontend closed the flow mid-progress

            with self.assertRaises(asyncio.CancelledError):
                await asyncio.wait_for(task, timeout=5.0)

        # The claim is released by the task's finally; nothing survives.
        self.assertEqual(registry.owner_for_pn(self.FULL_PN), "")

    # 1./13. Verified inbound: entry data gets inbound + external + evidence,
    # and no unverified peer address is persisted as collector_ip.
    async def test_verification_success_stamps_inbound_external(self) -> None:
        from custom_components.eybond_local.connection import connection_policy as cp
        from custom_components.eybond_local.connection.recovery import verification as sv

        flow = self._make_flow()
        inventory = [self._inventory_session(self.OLD_SESSION, self.FULL_PN)]
        registry = self._install_registry(flow, inventory)
        await flow.async_step_integration_discovery(self._discovery_info())

        claim_owner_during_restart: list[str] = []
        test = self
        new_session = self._inventory_session(self.NEW_SESSION, self.FULL_PN)

        class _FakeChannel:
            def __init__(self, **_kwargs) -> None:
                self.closed = 0

            async def async_send_restart(self) -> None:
                # The temporary registry claim must already be held here.
                claim_owner_during_restart.append(registry.owner_for_pn(test.FULL_PN))
                # Collector reboots: old session drops, then a NEW one dials in.
                inventory.clear()
                inventory.append(new_session)

            def is_connected(self) -> bool:
                return False

            async def async_close(self) -> None:
                self.closed += 1

        with patch.object(admission_transaction_module, "ObservedSessionRestartChannel", _FakeChannel):
            result = await self._drive_verification(flow)

        # Success continues the normal passive-candidate routing.
        self.assertIn(result["type"], {"form", "menu"})
        self.assertEqual(result["step_id"], "confirm")
        # Strategy is the flow's INTENT; the verifier produced a typed PROOF
        # and no legacy evidence.
        self.assertEqual(flow._verified_connection_strategy, "inbound")
        self.assertEqual(flow._verified_strategy_evidence, "")
        # 2D.2: the proof travels ONLY inside the transaction's typed terminal
        # input (read through the continuation); no admission-origin
        # ``_recovery_terminal`` legacy write, and no loose proof field.
        self.assertFalse(flow._callback_continuation._callback_terminal_input.has_proof)
        terminal_input = flow._callback_continuation.terminal_input
        proof = terminal_input.inbound_proof
        self.assertIsNotNone(proof)
        self.assertEqual(proof.collector_pn, self.FULL_PN)
        self.assertEqual(proof.method, "reboot_reconnect_no_trigger")
        self.assertEqual(terminal_input.prepared_handoff_owner, "")
        # Item 2: the claim existed during the restart AND is HELD after a
        # successful inbound proof -- retargeted onto the NEW socket, handed
        # off at entry creation, so the runtime owns the session it will use.
        self.assertTrue(claim_owner_during_restart[0].startswith("strategy_verification:"))
        owner = registry.owner_for_pn(self.FULL_PN)
        self.assertTrue(owner.startswith("strategy_verification:"))
        self.assertEqual(registry.claimed_session_id(owner), self.NEW_SESSION)

        # Entry-data stamping: explicit inbound, NO evidence key; the typed
        # proof becomes the entry's RecoveryContract instead.
        from custom_components.eybond_local.connection.recovery_contract import (
            RecoveryContract,
        )

        data = {
            "connection_mode": "callback_listener",
            "collector_ip": self.PEER_IP,
            "collector_operation_mode": "smartess_cloud_home_assistant",
        }
        flow._apply_verified_connection_strategy(data)
        RecoveryContract.empty_for_pn(
            proof.collector_pn, identity_source=proof.identity_source
        ).with_inbound_proof(proof, updated_at=proof.verified_at).write_to(data)
        data.update(cp.migrate_entry_axes(data, {}))
        self.assertEqual(data["connection_strategy"], "inbound")
        self.assertNotIn("connection_strategy_evidence", data)
        self.assertEqual(data["endpoint_control_policy"], "external")
        self.assertEqual(data["collector_ip"], "")
        # The recovery-proven inbound entry is exempt from the legacy
        # cloud-primary migration correction (contract-based exemption).
        self.assertIsNone(cp.correct_migrated_connection_strategy(data, {}))

    async def test_verification_rebinds_stale_flow_to_current_session(self) -> None:
        """An OTA/reboot between discovery and consent must not stale the flow."""

        flow = self._make_flow()
        inventory = [self._inventory_session(self.OLD_SESSION, self.FULL_PN)]
        registry = self._install_registry(flow, inventory)
        await flow.async_step_integration_discovery(
            self._discovery_info(collector_identity_source="at_dtupn")
        )

        # The discovery-time socket disappears while the consent form is open;
        # the same durable collector dials back on a new socket.
        inventory[:] = [self._inventory_session(self.NEW_SESSION, self.FULL_PN)]
        claimed_session_ids: list[str] = []
        post_restart = self._inventory_session(
            "listener-18899-3", self.FULL_PN
        )

        class _FakeChannel:
            def __init__(self, **kwargs) -> None:
                claimed_session_ids.append(kwargs["session_id"])

            async def async_send_restart(self) -> None:
                inventory[:] = [post_restart]

            def is_connected(self) -> bool:
                return False

            async def async_close(self) -> None:
                return None

        with patch.object(admission_transaction_module, "ObservedSessionRestartChannel", _FakeChannel):
            await self._drive_verification(flow)

        self.assertEqual(claimed_session_ids, [self.NEW_SESSION])
        self.assertEqual(flow._admission_transaction.old_session_id, self.NEW_SESSION)
        # Item 2: a successful inbound proof HOLDS the claim for handoff.
        self.assertTrue(
            registry.owner_for_pn(self.FULL_PN).startswith("strategy_verification:")
        )
        self.assertTrue(flow._admission_transaction.outcome.inbound_verified)

    # 2. Zero UDP callback triggers are sent while inbound verification runs.
    async def test_inbound_verification_sends_zero_udp_triggers(self) -> None:
        from custom_components.eybond_local.connection.recovery import verification as sv

        flow = self._make_flow()
        inventory = [self._inventory_session(self.OLD_SESSION, self.FULL_PN)]
        self._install_registry(flow, inventory)
        await flow.async_step_integration_discovery(self._discovery_info())
        new_session = self._inventory_session(self.NEW_SESSION, self.FULL_PN)

        class _FakeChannel:
            def __init__(self, **_kwargs) -> None:
                return None

            async def async_send_restart(self) -> None:
                inventory.clear()
                inventory.append(new_session)

            def is_connected(self) -> bool:
                return False

            async def async_close(self) -> None:
                return None

        from custom_components.eybond_local.connection.callback_ledger import (
            get_callback_trigger_ledger,
        )

        generation_before = get_callback_trigger_ledger().snapshot_generation()
        with patch.object(
            admission_transaction_module,
            "ObservedSessionRestartChannel",
            _FakeChannel,
        ):
            await flow.async_step_verify_connection({})
            await flow._admission_task

        self.assertEqual(
            get_callback_trigger_ledger().snapshot_generation(),
            generation_before,
        )
        result = flow._admission_transaction.outcome
        assert result is not None
        self.assertTrue(result.inbound_verified)
        self.assertIsNotNone(result.proof)
        self.assertEqual(result.proof.method, "reboot_reconnect_no_trigger")

    async def test_inbound_verification_blocks_concurrent_callback_trigger(self) -> None:
        """A pending/runtime callback cannot contaminate the reboot proof."""

        from custom_components.eybond_local.collector.discovery import (
            async_send_callback_trigger,
        )
        from custom_components.eybond_local.connection.callback_ledger import (
            CallbackTriggerInhibitedError,
            get_callback_trigger_ledger,
        )

        flow = self._make_flow()
        inventory = [self._inventory_session(self.OLD_SESSION, self.FULL_PN)]
        self._install_registry(flow, inventory)
        await flow.async_step_integration_discovery(self._discovery_info())
        new_session = self._inventory_session(self.NEW_SESSION, self.FULL_PN)
        blocked: list[str] = []
        generation_before = get_callback_trigger_ledger().snapshot_generation()

        class _FakeChannel:
            def __init__(self, **_kwargs) -> None:
                return None

            async def async_send_restart(self) -> None:
                try:
                    await async_send_callback_trigger(
                        bind_ip="127.0.0.1",
                        advertised_server_ip="127.0.0.1",
                        advertised_server_port=8899,
                        target_ip="192.0.2.55",
                        udp_port=58899,
                        timeout=0.01,
                        source="concurrent_pending_entry",
                    )
                except CallbackTriggerInhibitedError as exc:
                    blocked.append(str(exc))
                inventory[:] = [new_session]

            def is_connected(self) -> bool:
                return False

            async def async_close(self) -> None:
                return None

        with patch.object(admission_transaction_module, "ObservedSessionRestartChannel", _FakeChannel):
            await flow.async_step_verify_connection({})
            await flow._admission_task

        self.assertEqual(
            blocked,
            ["callback_trigger_inhibited_by_inbound_verification"],
        )
        self.assertEqual(
            get_callback_trigger_ledger().snapshot_generation(),
            generation_before,
        )
        result = flow._admission_transaction.outcome
        assert result is not None
        self.assertTrue(result.inbound_verified)

    # A session/identity already claimed by another owner is a typed failure --
    # never hijacked -- and the flow continues on the manual callback step.
    async def test_already_claimed_session_is_not_hijacked(self) -> None:
        from custom_components.eybond_local.connection.recovery import verification as sv

        flow = self._make_flow()
        inventory = [self._inventory_session(self.OLD_SESSION, self.FULL_PN)]
        registry = self._install_registry(flow, inventory)
        registry.claim("entry-other", collector_pn=self.FULL_PN, session_id=self.OLD_SESSION)
        await flow.async_step_integration_discovery(self._discovery_info())

        class _FailChannel:
            def __init__(self, **_kwargs) -> None:
                return None

            async def async_send_restart(self) -> None:
                raise AssertionError("restart must not be sent for a claimed session")

            def is_connected(self) -> bool:
                return False

            async def async_close(self) -> None:
                return None

        with patch.object(admission_transaction_module, "ObservedSessionRestartChannel", _FailChannel):
            result = await self._drive_verification(flow)

        verification = flow._admission_transaction.outcome
        assert verification is not None
        self.assertEqual(verification.failure_reason, sv.FAILURE_SESSION_CLAIMED)
        # No inbound classification; the same flow offers retry or manual setup.
        self.assertEqual(flow._verified_connection_strategy, "")
        self.assertEqual(result["step_id"], "verify_connection_failed")
        # The foreign claim is untouched.
        self.assertEqual(registry.owner_for_pn(self.FULL_PN), "entry-other")

    # Cancel (flow removal) releases the temporary claim in every state.
    async def test_cancel_during_verification_releases_claim(self) -> None:
        flow = self._make_flow()
        inventory = [self._inventory_session(self.OLD_SESSION, self.FULL_PN)]
        registry = self._install_registry(flow, inventory)
        await flow.async_step_integration_discovery(self._discovery_info())

        restart_started = asyncio.Event()

        class _HangingChannel:
            def __init__(self, **_kwargs) -> None:
                return None

            async def async_send_restart(self) -> None:
                restart_started.set()
                await asyncio.sleep(30)

            def is_connected(self) -> bool:
                return True

            async def async_close(self) -> None:
                order.append("close")

        from custom_components.eybond_local.connection.session_registry import (
            CallbackSessionRegistry,
        )

        order: list[str] = []
        real_release = CallbackSessionRegistry.release

        def _tracking_release(registry_self, owner):
            order.append("release")
            return real_release(registry_self, owner)

        with patch.object(
            admission_transaction_module, "ObservedSessionRestartChannel", _HangingChannel
        ), patch.object(CallbackSessionRegistry, "release", _tracking_release):
            progress = await flow.async_step_verify_connection_progress()
            self.assertEqual(progress["type"], "progress")
            task = flow._admission_task
            await asyncio.wait_for(restart_started.wait(), timeout=5)
            # The claim is held while the verification is in flight (promotion
            # to the full PN already happened before the restart).
            self.assertTrue(
                registry.owner_for_pn(self.FULL_PN).startswith("strategy_verification:")
            )

            flow.async_remove()
            # async_remove must NOT release the claim early while the task is
            # alive; the task's finally releases it after the channel closes.
            with suppress(asyncio.CancelledError):
                await task

        self.assertTrue(task.cancelled())
        # Ordering: restart channel fully closed BEFORE the claim was released
        # (idempotent close may run more than once; release exactly once, last).
        self.assertEqual(order[0], "close")
        self.assertEqual(order[-1], "release")
        self.assertEqual(order.count("release"), 1)
        self.assertEqual(registry.owner_for_pn(self.FULL_PN), "")
        self.assertEqual(flow._callback_continuation._owner, "")

    # 8 (behavioral test A, flow level). Manual callback identity success keeps
    # the USER-CHOSEN callback_on_demand strategy and records NO recovery
    # evidence: one answered one-shot trigger certifies THIS session's identity,
    # not a future recovery route. The persisted address is the one the trigger
    # was actually sent to.
    async def test_manual_callback_success_marks_callback_on_demand(self) -> None:
        flow = self._make_flow()
        flow._callback_continuation._expected_pn = self.FULL_PN
        flow._callback_continuation._old_session_id = self.OLD_SESSION
        # Pre-trigger: only the originally observed session exists (baseline).
        inventory = [self._inventory_session(self.OLD_SESSION, self.FULL_PN)]
        self._install_registry(flow, inventory)

        with self._identity_wire(
            inventory,
            # The collector answers OUR trigger with a NEW strong session.
            answers=[self._inventory_session(self.NEW_SESSION, self.FULL_PN)],
            read_pn=self.FULL_PN,
        ):
            result = await flow.async_step_manual(self._manual_input("192.168.1.60"))

        self.assertEqual(result["type"], "menu")
        self.assertEqual(result["step_id"], "manual_recovery_confirm")
        # The strategy is the user's form choice, re-affirmed -- never inferred.
        self.assertEqual(flow._verified_connection_strategy, "callback_on_demand")
        self.assertEqual(flow._manual_chosen_strategy, "callback_on_demand")
        # Identity success produced NO recovery evidence.
        self.assertEqual(flow._verified_strategy_evidence, "")

        data = {"collector_ip": "192.168.1.60"}
        flow._apply_verified_connection_strategy(data)
        self.assertEqual(data["connection_strategy"], "callback_on_demand")
        self.assertNotIn("connection_strategy_evidence", data)
        # The callback target address is kept (it answered), not cleared.
        self.assertEqual(data["collector_ip"], "192.168.1.60")

    # 9. Identity mismatch / timeout show the flow error and create nothing;
    # the address stays editable for a retry.
    async def test_manual_callback_identity_mismatch_shows_error(self) -> None:
        flow = self._make_flow()
        flow._callback_continuation._expected_pn = self.FULL_PN
        flow._callback_continuation._old_session_id = self.OLD_SESSION
        inventory = [self._inventory_session(self.OLD_SESSION, self.FULL_PN)]
        self._install_registry(flow, inventory)

        with self._identity_wire(
            inventory,
            # A DIFFERENT collector answered at this address: the new session
            # authoritatively reads as the other PN.
            answers=[self._inventory_session(self.NEW_SESSION, self.OTHER_FULL_PN)],
            read_pn=self.OTHER_FULL_PN,
        ):
            result = await flow.async_step_manual(self._manual_input("192.168.1.60"))

        self._assert_callback_failure_menu(
            flow, result, "callback_identity_mismatch"
        )
        self.assertIsNone(flow._manual_result.collector)
        self.assertIsNone(flow._manual_result.match)
        self.assertEqual(flow._verified_connection_strategy, "")
        # The entered address stays in flow state and the explicit Edit action
        # returns it to the editable form.
        self.assertEqual(flow._manual_config.get("collector_ip"), "192.168.1.60")
        self.assertIn("manual_edit_settings", result["menu_options"])

    async def test_manual_callback_timeout_creates_no_entry(self) -> None:
        flow = self._make_flow()
        flow._callback_continuation._expected_pn = self.FULL_PN
        flow._callback_continuation._old_session_id = self.OLD_SESSION
        registry = self._install_registry(flow, [])

        with self._identity_wire([], answers=()):
            # The trigger goes out; nothing ever dials in.
            result = await flow.async_step_manual(self._manual_input("192.168.1.60"))

        self._assert_callback_failure_menu(flow, result, "callback_timeout")
        self.assertEqual(flow._verified_connection_strategy, "")

        created = await flow.async_step_manual_save()

        self.assertEqual(created["type"], "menu")
        self.assertEqual(created["step_id"], "manual_confirm")
        self.assertNotIn("manual_save", created["menu_options"])
        self.assertFalse(hasattr(flow, "_test_unique_id"))
        self.assertEqual(registry.owner_for_pn(self.FULL_PN), "")

    # 10. Two collectors behind one peer IP cannot confirm each other: the
    # other collector's session already exists (baseline) and nothing NEW
    # answers our trigger, so the attempt times out instead of adopting it.
    async def test_same_peer_ip_other_collector_does_not_confirm_callback(self) -> None:
        flow = self._make_flow()
        flow._callback_continuation._expected_pn = self.FULL_PN
        flow._callback_continuation._old_session_id = self.OLD_SESSION
        inventory = [self._inventory_session(self.NEW_SESSION, self.OTHER_FULL_PN)]
        registry = self._install_registry(flow, inventory)

        with self._identity_wire(inventory, answers=()):
            result = await flow.async_step_manual(self._manual_input(self.PEER_IP))

        self._assert_callback_failure_menu(flow, result, "callback_timeout")
        self.assertEqual(flow._verified_connection_strategy, "")
        # The same-IP stranger was never claimed.
        self.assertEqual(registry.owner_for_pn(self.OTHER_FULL_PN), "")

    # A session whose registry identity never became strong cannot be bound --
    # even when a read CLAIMS a PN, the certified proof requires the inventory
    # to carry the strong on-wire identity (the production read stamps it; a
    # session that never got stamped stays unprovable).
    async def test_manual_weak_new_session_does_not_confirm(self) -> None:
        flow = self._make_flow()
        flow._callback_continuation._expected_pn = self.FULL_PN
        flow._callback_continuation._old_session_id = self.OLD_SESSION
        inventory = [self._inventory_session(self.OLD_SESSION, self.FULL_PN)]
        registry = self._install_registry(flow, inventory)

        with self._identity_wire(
            inventory,
            answers=[
                self._inventory_session(
                    self.NEW_SESSION,
                    self.FULL_PN,
                    identity_source="framed_heartbeat",  # weak, never stamped
                )
            ],
            read_pn=self.FULL_PN,
        ):
            result = await flow.async_step_manual(self._manual_input("192.168.1.60"))

        self._assert_callback_failure_menu(flow, result, "callback_timeout")
        self.assertEqual(flow._verified_connection_strategy, "")
        self.assertEqual(registry.owner_for_pn(self.FULL_PN), "")

    # No-session-id discovery: a session that ALREADY existed before the trigger
    # is baseline and never counts as the callback answer.
    async def test_manual_no_session_id_preexisting_session_is_not_answer(self) -> None:
        flow = self._make_flow()
        inventory = [self._inventory_session(self.OLD_SESSION, self.FULL_PN)]
        self._install_registry(flow, inventory)
        # Discovery payload without session_id routes straight to manual.
        result = await flow.async_step_integration_discovery(
            self._discovery_info(session_id="")
        )
        self.assertEqual(result["step_id"], "manual")

        with self._identity_wire(inventory, answers=()):
            result = await flow.async_step_manual(self._manual_input(self.PEER_IP))

        # The pre-existing session is in the baseline: no proof, no entry.
        self._assert_callback_failure_menu(flow, result, "callback_timeout")
        self.assertEqual(flow._verified_connection_strategy, "")

    # Entry created after short->full enrichment carries ONE consistent full PN
    # in unique_id, CONF_COLLECTOR_PN, and the title.
    async def test_entry_after_short_to_full_enrichment_is_consistent(self) -> None:
        short_pn = "V001020SYN6234"
        flow = self._make_flow()
        # The observed session already reports the strong FULL PN; the discovery
        # payload still carried the short prefix.
        inventory = [self._inventory_session(self.OLD_SESSION, self.FULL_PN)]
        self._install_registry(flow, inventory)
        await flow.async_step_integration_discovery(
            self._discovery_info(collector_pn=short_pn)
        )
        self.assertEqual(flow._test_unique_id, f"collector:{short_pn}")
        new_session = self._inventory_session(self.NEW_SESSION, self.FULL_PN)

        class _FakeChannel:
            def __init__(self, **_kwargs) -> None:
                return None

            async def async_send_restart(self) -> None:
                inventory.clear()
                inventory.append(new_session)

            def is_connected(self) -> bool:
                return False

            async def async_close(self) -> None:
                return None

        with patch.object(admission_transaction_module, "ObservedSessionRestartChannel", _FakeChannel):
            await self._drive_verification(flow)

        # Every flow model adopted the enriched FULL PN.
        self.assertEqual(flow._verified_connection_strategy, "inbound")
        self.assertEqual(flow._test_unique_id, f"collector:{self.FULL_PN}")
        self.assertEqual(
            flow._selected_result.collector.collector.collector_pn, self.FULL_PN
        )
        self.assertEqual(
            flow.context["title_placeholders"],
            {"name": f"Collector PN {self.FULL_PN}"},
        )

        # Create the REAL entry through the confirm submit path and check its
        # data -- not just the strategy stamping helper.
        created = await flow.async_step_confirm({"poll_mode": "auto"})

        self.assertEqual(created["type"], "create_entry")
        data = created["data"]
        self.assertEqual(data["collector_pn"], self.FULL_PN)
        self.assertEqual(data["connection_strategy"], "inbound")
        # NO legacy reboot evidence is written anymore...
        self.assertNotIn("connection_strategy_evidence", data)
        self.assertEqual(data["endpoint_control_policy"], "external")
        self.assertEqual(data["collector_ip"], "")
        self.assertIn(self.FULL_PN, created["title"])
        # ...the typed proof landed as the entry's RecoveryContract instead, in
        # the SAME terminal create path, under the one canonical key.
        from custom_components.eybond_local.connection.recovery_contract import (
            INBOUND_RECOVERY_REBOOT_RECONNECT_NO_TRIGGER,
            RecoveryContract,
        )

        contract = RecoveryContract.from_entry_data(data)
        self.assertIsNotNone(contract)
        self.assertTrue(contract.inbound_verified)
        self.assertFalse(contract.callback_verified)
        self.assertEqual(contract.collector_pn, self.FULL_PN)
        self.assertEqual(
            contract.inbound_proof.method,
            INBOUND_RECOVERY_REBOOT_RECONNECT_NO_TRIGGER,
        )
        self.assertEqual(contract.inbound_proof.identity_source, "at_dtupn")
        # verified_at came from the injected aware clock and round-trips.
        from datetime import datetime

        parsed_ts = datetime.fromisoformat(contract.inbound_proof.verified_at)
        self.assertIsNotNone(parsed_ts.tzinfo)

    # 12. Cancel/error cleanup: removing the flow cancels the verification task.
    async def test_flow_removal_cancels_verification_task(self) -> None:
        flow = self._make_flow()
        await flow.async_step_integration_discovery(self._discovery_info())

        started = asyncio.Event()

        async def _hang() -> None:
            started.set()
            await asyncio.sleep(30)

        with patch.object(flow._admission_transaction, "async_run", side_effect=_hang):
            progress = await flow.async_step_verify_connection_progress()
            self.assertEqual(progress["type"], "progress")
            task = flow._admission_task
            await started.wait()

        flow.async_remove()
        with suppress(asyncio.CancelledError):
            await task
        self.assertTrue(task.cancelled())
        self.assertIsNone(flow._admission_task)
        self.assertIsNone(flow._admission_transaction)

    # ---- ownership handoff: config flow -> entry (items 1, 2, 3, 7, 9) ----

    async def test_manual_callback_claims_session_and_setup_completes_handoff(self) -> None:
        # Item 1 (the real end-to-end lifecycle): a known-IP one-shot callback
        # reaches a NEW strong full-PN session; the PRODUCTION manual step claims
        # THAT exact session under a UNIQUE per-attempt owner; the user confirms;
        # the entry is created (prepare_handoff commits the claim); and PRODUCTION
        # setup completes the handoff to the durable entry_id -- no gap, no double
        # owner, no leaked claim, never keyed on peer IP.
        from custom_components.eybond_local import (
            _register_entry_callback_session_claim,
        )
        from custom_components.eybond_local.const import CONF_COLLECTOR_PN

        flow = self._make_flow()
        flow._callback_continuation._expected_pn = self.FULL_PN
        flow._callback_continuation._old_session_id = self.OLD_SESSION
        inventory = [self._inventory_session(self.OLD_SESSION, self.FULL_PN)]
        registry = self._install_registry(flow, inventory)

        with self._identity_wire(
            inventory,
            answers=[self._inventory_session(self.NEW_SESSION, self.FULL_PN)],
            read_pn=self.FULL_PN,
        ):
            result = await flow.async_step_manual(self._manual_input("192.168.1.60"))
            self.assertEqual(result["step_id"], "manual_recovery_confirm")

            # The identity owner is a UNIQUE per-attempt id (never PN-derived).
            identity_owner = registry.owner_for_pn(self.FULL_PN)
            self.assertTrue(identity_owner.startswith("callback_verification:"))
            self.assertEqual(
                registry.claimed_session_id(identity_owner), self.NEW_SESSION
            )
            self.assertEqual(registry.claimed_identity(identity_owner), self.FULL_PN)

        # The user consents; the recovery transaction proves the route and its
        # own owner replaces the identity owner (released by the producer).
        created, _calls = await self._drive_recovery_verified(flow, registry)

        self.assertEqual(created["type"], "create_entry")
        self.assertEqual(created["data"][CONF_COLLECTOR_PN], self.FULL_PN)
        # The entry carries the proven recovery route (callback branch).
        self.assertIn("callback", created["data"]["recovery_contract"])
        self.assertTrue(flow._callback_continuation._handed_off)
        owner = registry.owner_for_pn(self.FULL_PN)
        self.assertTrue(owner.startswith("callback_recovery:"))
        self.assertEqual(registry.claimed_identity(identity_owner), "")

        # Flow cleanup must NOT release a committed handoff.
        flow.async_remove()
        self.assertEqual(registry.owner_for_pn(self.FULL_PN), owner)

        # PRODUCTION setup completes the handoff to the durable entry_id.
        entry = _FakeSetupEntry("entry-xyz", created["data"])
        _register_entry_callback_session_claim(flow.hass, entry)
        self.assertEqual(registry.owner_for_pn(self.FULL_PN), "entry-xyz")
        self.assertEqual(registry.claimed_session_id("entry-xyz"), self.NEW_SESSION)
        # No leaked/duplicate owner: the per-attempt owner is gone.
        self.assertEqual(registry.claimed_identity(owner), "")
        # Completing again is a no-op (the handoff transfers exactly once).
        self.assertFalse(registry.complete_handoff(self.FULL_PN, "entry-other"))

    def test_handoff_api_has_production_callers(self) -> None:
        # Item 9 guard: the handoff API must be invoked by production code, not
        # left as dead API. Setup completes the handoff (complete_handoff) with a
        # claim-by-PN fallback; the config flow prepares it (prepare_handoff).
        import ast
        import inspect
        import textwrap

        from custom_components.eybond_local import (
            _register_entry_callback_session_claim,
        )
        from custom_components.eybond_local.config_flow import (
            EybondLocalConfigFlow,
        )

        setup_src = textwrap.dedent(
            inspect.getsource(_register_entry_callback_session_claim)
        )
        setup_calls = {
            node.func.attr
            for node in ast.walk(ast.parse(setup_src))
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }
        self.assertIn("complete_handoff", setup_calls)
        self.assertIn("claim", setup_calls)  # restart / no-handoff fallback

        # Both manual identity and observed inbound handoff preparation live in
        # the one neutral transaction module; no flow-owned helper remains.
        del EybondLocalConfigFlow
        prepare_src = textwrap.dedent(
            inspect.getsource(
                admission_transaction_module.CollectorAdmissionTransaction
                ._prepare_callback_identity_handoff
            )
        )
        prepare_calls = {
            node.func.attr
            for node in ast.walk(ast.parse(prepare_src))
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }
        self.assertIn("prepare_handoff", prepare_calls)

    def test_setup_without_pending_handoff_claims_by_durable_pn(self) -> None:
        # Item 3 fallback: after an HA restart the in-memory handoff claim is
        # gone; setup must still claim the durable identity by PN (never by IP) so
        # the next same-PN session binds to the entry.
        from custom_components.eybond_local import (
            _register_entry_callback_session_claim,
        )

        flow = self._make_flow()
        inventory = [self._inventory_session(self.NEW_SESSION, self.FULL_PN)]
        registry = self._install_registry(flow, inventory)
        entry = _FakeSetupEntry("entry-restart", {"collector_pn": self.FULL_PN})
        _register_entry_callback_session_claim(flow.hass, entry)
        self.assertEqual(registry.owner_for_pn(self.FULL_PN), "entry-restart")
        self.assertEqual(registry.claimed_session_id("entry-restart"), self.NEW_SESSION)

    def test_setup_blocked_by_uncommitted_verification_claim_is_retryable(self) -> None:
        # Item 3: an in-flight verification (uncommitted) for the PN blocks setup
        # with a RETRYABLE error -- the runtime must not start without ownership,
        # and the verification claim is never stolen.
        from custom_components.eybond_local import (
            ConfigEntryNotReady,
            _register_entry_callback_session_claim,
        )

        flow = self._make_flow()
        inventory = [self._inventory_session(self.NEW_SESSION, self.FULL_PN)]
        registry = self._install_registry(flow, inventory)
        registry.claim_session("callback_verification:live", session_id=self.NEW_SESSION)
        registry.promote_claim_to_full_pn("callback_verification:live", self.FULL_PN)

        entry = _FakeSetupEntry("entry-racing", {"collector_pn": self.FULL_PN})
        with self.assertRaises(ConfigEntryNotReady):
            _register_entry_callback_session_claim(flow.hass, entry)

        # The uncommitted verification claim is untouched; the entry did not steal it.
        self.assertEqual(registry.owner_for_pn(self.FULL_PN), "callback_verification:live")
        self.assertEqual(registry.claimed_identity("entry-racing"), "")

        # After the competing verification releases, a setup retry succeeds and the
        # entry owns the durable identity.
        registry.release("callback_verification:live")
        _register_entry_callback_session_claim(flow.hass, entry)
        self.assertEqual(registry.owner_for_pn(self.FULL_PN), "entry-racing")

    async def test_two_concurrent_flows_same_pn_do_not_share_owner(self) -> None:
        # Item 1: two live flows verifying the SAME collector are distinct owners;
        # the second gets a typed conflict and cannot disturb the first.
        registry_inventory = [self._inventory_session(self.OLD_SESSION, self.FULL_PN)]

        flow_a = self._make_flow()
        flow_a._callback_continuation._expected_pn = self.FULL_PN
        flow_a._callback_continuation._old_session_id = self.OLD_SESSION
        registry = self._install_registry(flow_a, registry_inventory)

        flow_b = self._make_flow()
        flow_b._callback_continuation._expected_pn = self.FULL_PN
        flow_b._callback_continuation._old_session_id = self.OLD_SESSION
        # Same shared domain registry (one per HA process).
        flow_b.hass.data["eybond_local"] = flow_a.hass.data["eybond_local"]

        with self._identity_wire(
            registry_inventory,
            answers=[self._inventory_session(self.NEW_SESSION, self.FULL_PN)],
            read_pn=self.FULL_PN,
        ):
            result_a = await flow_a.async_step_manual(self._manual_input("192.168.1.60"))
        self.assertEqual(result_a["step_id"], "manual_recovery_confirm")
        owner_a = registry.owner_for_pn(self.FULL_PN)
        self.assertTrue(owner_a.startswith("callback_verification:"))

        # Flow B now verifies the same collector: it answers AGAIN on yet
        # another new session, but the identity already belongs to flow A --
        # a typed conflict, and flow B never takes ownership.
        with self._identity_wire(
            registry_inventory,
            answers=[self._inventory_session("listener-18899-3", self.FULL_PN)],
            read_pn=self.FULL_PN,
        ):
            result_b = await flow_b.async_step_manual(self._manual_input("192.168.1.60"))
        self.assertEqual(result_b["type"], "menu")
        self.assertEqual(result_b["step_id"], "manual_confirm")
        self.assertEqual(
            flow_b._manual_result.last_error, "callback_identity_conflict"
        )
        self.assertNotIn("manual_save", result_b["menu_options"])
        # Flow A still owns it; flow B never became an owner.
        self.assertEqual(registry.owner_for_pn(self.FULL_PN), owner_a)
        self.assertEqual(registry.claimed_session_id(owner_a), self.NEW_SESSION)
        self.assertEqual(flow_b._callback_continuation._owner, "")

    async def test_manual_callback_strategy_is_canonical_in_data_without_expected_pn(
        self,
    ) -> None:
        # Item 2 regression: a generic manual callback_on_demand flow (NO
        # passive-discovery expected PN) whose attempt resolves a full PN must
        # persist the CHOSEN strategy in entry.data -- not fall back to legacy
        # connection_mode derivation -- and never write it to options.
        #
        # The attempt is driven through the REAL lifecycle (own trigger recorded,
        # collector answers on a new strong session) rather than by stubbing the
        # probe out. A callback entry now takes its identity from the VERIFIED
        # PN only, so a stubbed probe -- which declares no trigger and leaves no
        # session behind -- is a state production cannot reach and would (fail
        # closed) yield a pending entry instead of the normal entry under test.
        from custom_components.eybond_local.const import (
            CONF_CONNECTION_STRATEGY,
            CONNECTION_STRATEGY_CALLBACK_ON_DEMAND,
        )

        flow = self._make_flow()
        inventory: list[dict[str, object]] = []
        self._install_registry(flow, inventory)
        assert not flow._callback_continuation._expected_pn

        def _answers():
            inventory.append(self._inventory_session(self.NEW_SESSION, self.FULL_PN))

        detector = self._recording_detector(
            results=(self._manual_result_with_pn(self.FULL_PN),), on_detect=_answers
        )

        routed = await self._drive_generic_callback(flow, detector)
        self.assertEqual(routed["step_id"], "manual_recovery_confirm")
        registry = flow._callback_session_registry()
        created, _calls = await self._drive_recovery_verified(flow, registry)

        # A NORMAL entry (the PN was found immediately), carrying the chosen
        # strategy canonically in data -- as USER INTENT, with the PROVEN
        # recovery route in the contract (never legacy strategy evidence).
        self.assertEqual(created["type"], "create_entry")
        self.assertEqual(created["data"]["collector_pn"], self.FULL_PN)
        self.assertEqual(created["data"].get("entry_role", ""), "")
        self.assertEqual(
            created["data"][CONF_CONNECTION_STRATEGY],
            CONNECTION_STRATEGY_CALLBACK_ON_DEMAND,
        )
        self.assertNotIn(CONF_CONNECTION_STRATEGY, created.get("options") or {})
        self.assertNotIn("connection_strategy_evidence", created["data"])
        self.assertIn("callback", created["data"]["recovery_contract"])
        # The exact callback identity transaction also persists the PN-bound
        # wire evidence runtime needs to identify a fully-silent reconnect.
        self.assertEqual(
            created["data"]["collector_confirmed_session_protocol"],
            "eybond_framed",
        )
        self.assertEqual(
            created["data"]["collector_confirmed_session_protocol_pn"],
            self.FULL_PN,
        )

    async def test_generic_manual_inbound_never_adopts_a_foreign_candidate(self) -> None:
        # Item 3 regression: ONE unclaimed strong collector exists globally, but
        # this generic manual inbound flow has no link to it (no expected PN). It
        # may belong to another pending flow, so it must NOT become this entry.
        from custom_components.eybond_local.const import CONF_CONNECTION_STRATEGY

        flow = self._make_flow()
        registry = self._install_registry(
            flow, [self._inventory_session(self.NEW_SESSION, self.FULL_PN)]
        )
        assert not flow._callback_continuation._expected_pn

        with patch.object(
            admission_transaction_module,
            "async_run_callback_identity_transaction",
            side_effect=AssertionError("inbound must not run an active attempt"),
        ):
            created = await flow.async_step_manual(
                self._manual_input("", connection_strategy="inbound")
            )

        # The flow remains open; it never creates an entry wearing the
        # stranger's PN.
        self.assertEqual(created["type"], "menu")
        self.assertEqual(created["step_id"], "manual_confirm")
        self.assertIn("manual_enable_background_discovery", created["menu_options"])
        self.assertNotIn("manual_save", created["menu_options"])
        self.assertNotEqual(
            getattr(flow, "_test_unique_id", ""), f"collector:{self.FULL_PN}"
        )
        # The stranger's session was never claimed by this flow.
        self.assertEqual(registry.owner_for_pn(self.FULL_PN), "")
        # And no user_confirmed_session evidence was invented.
        self.assertEqual(flow._manual_result.last_error, "inbound_awaiting_session")

    # ---- generic manual callback_on_demand: active attempt + shared matcher ----

    def _recording_detector(self, *, results=(), own_triggers=1, extra_triggers=0, on_detect=None):
        """A detector that records its trigger(s) in the shared ledger, like the real one.

        It now DECLARES its behaviour (results / trigger counts / the collector's
        answer) so one seam can drive both halves of the flow: the identity
        transaction's wire first, then this detector for the detection that runs
        afterwards. Passive inventory must never be consulted on a callback
        attempt.
        """

        from custom_components.eybond_local.connection.callback_ledger import (
            get_callback_trigger_ledger,
        )

        class _Detector:
            async def async_passive_detect(self, **_kwargs):
                raise AssertionError(
                    "a callback attempt must never short-circuit on passive inventory"
                )

            async def async_scan(self, **_kwargs):
                # Detection now runs AFTER identity is certified and outside the
                # causality lease, so its own probes cannot decide identity.
                ledger = get_callback_trigger_ledger()
                for _ in range(own_triggers):
                    ledger.record(target="ours", source="test_detection")
                return results

        detector = _Detector()
        # Declared behaviour for _identity_wire_for(): what the collector does in
        # response to THIS attempt's single trigger sequence.
        detector.declared_results = results
        detector.declared_own_triggers = own_triggers
        detector.declared_extra_triggers = extra_triggers
        detector.declared_on_detect = on_detect
        return detector

    @staticmethod
    def _detector_pn(detector):
        for result in getattr(detector, "declared_results", ()) or ():
            collector = getattr(result, "collector", None)
            pn = str(
                getattr(getattr(collector, "collector", None), "collector_pn", "") or ""
            ).strip()
            if pn:
                return pn
        return ""

    @contextmanager
    def _identity_wire_for(self, detector):
        """Drive the REAL identity transaction from a detector's declared behaviour."""

        import custom_components.eybond_local.connection.callback_identity as ci
        from custom_components.eybond_local.connection.callback_ledger import (
            get_callback_trigger_ledger,
        )

        pn = self._detector_pn(detector)
        on_detect = getattr(detector, "declared_on_detect", None)
        own = getattr(detector, "declared_own_triggers", 1)
        extra = getattr(detector, "declared_extra_triggers", 0)

        class _Sender:
            async def async_send(self, request):
                ledger = get_callback_trigger_ledger()
                for _ in range(own):
                    ledger.record(target=request.target_ip, source="test_attempt")
                for _ in range(extra):
                    # No attempt context: an uncoordinated sender (the runtime).
                    ledger.record(target="other", source="runtime", attempt_id="")
                if on_detect is not None:
                    on_detect()  # the collector dials in

        class _Reader:
            async def async_read_full_pn(self, **_kwargs):
                if not pn:
                    return ("", "")
                return (pn, "fc2_parameter_2")

        with patch.object(ci, "_ProductionTriggerSender", return_value=_Sender()), patch.object(
            ci, "_SessionPinnedIdentityReader", return_value=_Reader()
        ), patch.object(
            ci, "DEFAULT_ONBOARDING_TIMEOUT_POLICY", _fast_identity_policy()
        ):
            yield

    async def _drive_generic_callback(self, flow, detector, collector_ip="192.168.1.60"):
        with self._identity_wire_for(detector), patch(
            "custom_components.eybond_local.flows.config.scan.create_onboarding_manager",
            return_value=detector,
        ):
            return await flow.async_step_manual(
                self._manual_input(collector_ip, connection_strategy="callback_on_demand")
            )

    async def test_manual_callback_attempt_owns_one_passive_discovery_scope(self) -> None:
        # The transaction owns exactly ONE passive-discovery attribution scope
        # per attempt, opened under its unique per-attempt owner id, and the
        # answering session is retained in it (so discovery does not also
        # publish a card for the socket this flow caused).
        flow = self._make_flow()
        inventory: list[dict] = []
        self._install_registry(flow, inventory)
        events: list[tuple[str, str]] = []
        retained: set[str] = set()

        @contextmanager
        def _scope(_hass, scope_id):
            events.append(("begin", scope_id))
            try:
                yield retained
            finally:
                events.append(("end", scope_id))

        detector = self._recording_detector(
            results=(self._manual_result_with_pn(self.FULL_PN),),
            on_detect=lambda: inventory.append(
                self._inventory_session(self.NEW_SESSION, self.FULL_PN)
            ),
        )
        with patch(
            "custom_components.eybond_local.passive_discovery."
            "active_callback_probe_scope",
            new=_scope,
        ):
            routed = await self._drive_generic_callback(flow, detector)

        self.assertEqual(routed["step_id"], "manual_recovery_confirm")
        self.assertEqual([event for event, _scope_id in events], ["begin", "end"])
        self.assertEqual(events[0][1], events[1][1])
        self.assertTrue(events[0][1].startswith("callback_verification:"))
        self.assertEqual(retained, {self.NEW_SESSION})

    async def test_manual_attempt_runs_no_detection_and_keeps_proven_identity(self) -> None:
        """No driver work may run before the entry exists -- or touch the proof.

        The predecessor test pinned "a slow driver detection may not erase the
        proven identity". Detection is now gone from the flow entirely, which is
        the stronger form of the same invariant: the certified session/PN is the
        whole result, and any attempt to build a detector before entry creation
        explodes here.
        """

        flow = self._make_flow()
        inventory: list[dict] = []
        registry = self._install_registry(flow, inventory)

        with self._identity_wire(
            inventory,
            answers=[self._inventory_session(self.NEW_SESSION, self.FULL_PN)],
            read_pn=self.FULL_PN,
        ), patch(
            "custom_components.eybond_local.flows.config.scan.create_onboarding_manager",
            side_effect=AssertionError("no detection may run before the entry exists"),
        ):
            routed = await flow.async_step_manual(
                self._manual_input("192.168.1.60", connection_strategy="callback_on_demand")
            )

        self.assertEqual(routed["step_id"], "manual_recovery_confirm")
        self.assertEqual(flow._callback_continuation._certified_pn, self.FULL_PN)
        owner = registry.owner_for_pn(self.FULL_PN)
        self.assertTrue(owner.startswith("callback_verification:"))
        self.assertEqual(registry.claimed_session_id(owner), self.NEW_SESSION)

    async def test_generic_callback_rejects_pre_existing_foreign_session(self) -> None:
        # BLOCKER 1: a foreign strong session already exists; the user types a
        # DIFFERENT collector address and chooses callback_on_demand. The active
        # attempt reaches the target and a NEW matching session appears. The old
        # foreign session must never be adopted and must stay unclaimed.
        flow = self._make_flow()
        inventory = [self._inventory_session("foreign-1", self.OTHER_FULL_PN)]
        registry = self._install_registry(flow, inventory)

        def _target_answers():
            inventory.append(self._inventory_session(self.NEW_SESSION, self.FULL_PN))

        detector = self._recording_detector(
            results=(self._manual_result_with_pn(self.FULL_PN),),
            on_detect=_target_answers,
        )

        routed = await self._drive_generic_callback(flow, detector)
        self.assertEqual(routed["step_id"], "manual_recovery_confirm")
        # Only the target identity was claimed ...
        self.assertEqual(flow._callback_continuation._certified_pn, self.FULL_PN)
        owner = registry.owner_for_pn(self.FULL_PN)
        self.assertTrue(owner.startswith("callback_verification:"))
        self.assertEqual(registry.claimed_session_id(owner), self.NEW_SESSION)
        # ... and the pre-existing stranger is untouched.
        self.assertEqual(registry.owner_for_pn(self.OTHER_FULL_PN), "")

        created, _calls = await self._drive_recovery_verified(flow, registry)
        self.assertEqual(created["type"], "create_entry")
        self.assertEqual(created["data"]["collector_pn"], self.FULL_PN)
        # The stranger is STILL untouched after recovery + creation.
        self.assertEqual(registry.owner_for_pn(self.OTHER_FULL_PN), "")

    async def test_generic_callback_without_detector_pn_creates_no_normal_entry(self) -> None:
        # BLOCKER 1: one pre-existing foreign session; the active attempt does NOT
        # confirm a PN. No normal entry, and the foreign PN is never assigned.
        flow = self._make_flow()
        registry = self._install_registry(
            flow, [self._inventory_session("foreign-1", self.OTHER_FULL_PN)]
        )
        detector = self._recording_detector(results=())

        routed = await self._drive_generic_callback(flow, detector)

        self._assert_callback_failure_menu(flow, routed, "callback_timeout")
        self.assertEqual(flow._callback_continuation._certified_pn, "")
        self.assertEqual(registry.owner_for_pn(self.OTHER_FULL_PN), "")
        self.assertNotEqual(
            getattr(flow, "_test_unique_id", ""), f"collector:{self.OTHER_FULL_PN}"
        )

    async def test_concurrent_trigger_during_active_attempt_is_interference(self) -> None:
        # BLOCKER 2 (A): our trigger fires AND a concurrent one does. Even though
        # the detector returns the right PN and a matching session appeared, the
        # answer is not attributable to us -> interference, and nothing is claimed.
        flow = self._make_flow()
        inventory: list[dict] = []
        registry = self._install_registry(flow, inventory)

        def _answers():
            inventory.append(self._inventory_session(self.NEW_SESSION, self.FULL_PN))

        detector = self._recording_detector(
            results=(self._manual_result_with_pn(self.FULL_PN),),
            own_triggers=1,
            extra_triggers=1,  # someone else triggered concurrently
            on_detect=_answers,
        )

        routed = await self._drive_generic_callback(flow, detector)

        self._assert_callback_failure_menu(
            flow, routed, "callback_trigger_interference"
        )
        self.assertEqual(flow._callback_continuation._certified_pn, "")
        self.assertEqual(registry.owner_for_pn(self.FULL_PN), "")
        self.assertEqual(flow._callback_continuation._owner, "")

    async def test_timeout_after_our_trigger_is_timeout_not_interference(self) -> None:
        # BLOCKER 2 (B): our one trigger DID go out, then nothing answered. The
        # provenance is correct, so this is a plain timeout -- not interference.
        flow = self._make_flow()
        registry = self._install_registry(flow, [])
        detector = self._recording_detector(results=(), own_triggers=1)

        routed = await self._drive_generic_callback(flow, detector)

        self._assert_callback_failure_menu(flow, routed, "callback_timeout")
        self.assertNotEqual(
            flow._manual_result.last_error, "callback_trigger_interference"
        )
        self.assertEqual(registry.owner_for_pn(self.FULL_PN), "")

    async def test_generic_callback_success_claims_and_stamps_canonical_strategy(self) -> None:
        # BLOCKER 2 (C): exactly one trigger; detector PN == the new strong
        # session; claim + handoff exist; the entry carries callback_on_demand.
        from custom_components.eybond_local.const import (
            CONF_CONNECTION_STRATEGY,
            CONNECTION_STRATEGY_CALLBACK_ON_DEMAND,
        )

        flow = self._make_flow()
        inventory: list[dict] = []
        registry = self._install_registry(flow, inventory)

        def _answers():
            inventory.append(self._inventory_session(self.NEW_SESSION, self.FULL_PN))

        detector = self._recording_detector(
            results=(self._manual_result_with_pn(self.FULL_PN),),
            own_triggers=1,
            on_detect=_answers,
        )

        routed = await self._drive_generic_callback(flow, detector)
        self.assertEqual(routed["step_id"], "manual_recovery_confirm")

        identity_owner = registry.owner_for_pn(self.FULL_PN)
        self.assertTrue(identity_owner.startswith("callback_verification:"))

        created, _calls = await self._drive_recovery_verified(flow, registry)

        self.assertEqual(created["type"], "create_entry")
        self.assertEqual(
            created["data"][CONF_CONNECTION_STRATEGY],
            CONNECTION_STRATEGY_CALLBACK_ON_DEMAND,
        )
        self.assertNotIn(CONF_CONNECTION_STRATEGY, created.get("options") or {})
        # Strategy is the user's choice; the identity/recovery successes add
        # NO legacy evidence -- the proof lives in the RecoveryContract.
        self.assertNotIn("connection_strategy_evidence", created["data"])
        self.assertIn("callback", created["data"]["recovery_contract"])
        # The handoff was prepared for the RECOVERY transaction's owner (the
        # identity owner was released at the recovery handover).
        self.assertTrue(flow._callback_continuation._handed_off)
        owner = registry.owner_for_pn(self.FULL_PN)
        self.assertTrue(owner.startswith("callback_recovery:"))
        self.assertEqual(
            registry.prepared_handoff_identity(owner, self.FULL_PN), self.FULL_PN
        )
        self.assertEqual(registry.claimed_identity(identity_owner), "")

    async def test_pre_existing_session_never_substitutes_for_the_answer(self) -> None:
        # BLOCKER 2 (D): the ONLY strong session existed BEFORE our trigger and
        # matches the detector's PN. Baseline still rules it out: it cannot be an
        # answer to a trigger sent after it.
        flow = self._make_flow()
        registry = self._install_registry(
            flow, [self._inventory_session("pre-existing", self.FULL_PN)]
        )
        detector = self._recording_detector(
            results=(self._manual_result_with_pn(self.FULL_PN),), own_triggers=1
        )

        routed = await self._drive_generic_callback(flow, detector)

        self._assert_callback_failure_menu(flow, routed, "callback_timeout")
        self.assertEqual(registry.owner_for_pn(self.FULL_PN), "")

    async def test_manual_callback_timeout_leaves_no_registry_claim(self) -> None:
        # Item 2/5 cleanup: a timeout (no confirming strong session) must leave
        # nothing owned.
        flow = self._make_flow()
        flow._callback_continuation._expected_pn = self.FULL_PN
        flow._callback_continuation._old_session_id = self.OLD_SESSION
        registry = self._install_registry(flow, [])
        with self._identity_wire([], answers=()):
            result = await flow.async_step_manual(self._manual_input("192.168.1.60"))
        self._assert_callback_failure_menu(flow, result, "callback_timeout")
        self.assertEqual(registry.owner_for_pn(self.FULL_PN), "")
        self.assertEqual(flow._callback_continuation._owner, "")

    async def test_expected_short_pn_is_not_saved_as_durable_identity(self) -> None:
        # Item 4: a discovery-time expected/short PN is NOT durable evidence. With
        # no registry-certified strong session, no PN is persisted, no normal
        # entry is created, and the expected PN never leaks into a collector id.
        flow = self._make_flow()
        flow._manual_config = self._manual_input("192.168.1.60")
        flow._manual_result = OnboardingResult(
            connection_mode="known_ip", next_action="retry_verification"
        )
        flow._callback_continuation._expected_pn = self.FULL_PN
        flow._callback_continuation._certified_pn = ""

        result = await flow.async_step_manual_save()

        self.assertEqual(result["type"], "menu")
        self.assertEqual(result["step_id"], "manual_confirm")
        self.assertNotIn("manual_save", result["menu_options"])
        self.assertNotEqual(
            getattr(flow, "_test_unique_id", None), f"collector:{self.FULL_PN}"
        )

    def _pn_less_entry(self, entry_id: str = "entry-broken"):
        from custom_components.eybond_local.const import CONF_COLLECTOR_PN

        return _FakeSetupEntry(
            entry_id,
            {
                "connection_type": "eybond",
                "connection_mode": "known_ip",
                "collector_operation_mode": "home_assistant_only",
                CONF_COLLECTOR_PN: "",
            },
        )

    async def test_reconfigure_binds_pn_and_updates_existing_pn_less_entry(self) -> None:
        # Item 8 (behavioral test B): reconfigure runs the SAME identity
        # transaction against an existing PN-less entry, binds the strong full
        # PN, and updates the entry in place (no delete/re-add). A pre-canonical
        # entry gets the strategy stamped from the user's explicit callback
        # repair action -- and NO recovery evidence is added: identity repair
        # proves which collector this is, not how it can be reached again.
        from custom_components.eybond_local.const import (
            CONF_COLLECTOR_PN,
            CONF_CONNECTION_STRATEGY,
            CONF_CONNECTION_STRATEGY_EVIDENCE,
        )

        flow = self._make_flow()
        entry = self._pn_less_entry()
        flow.hass.config_entries._entries.append(entry)
        flow.context = {"entry_id": "entry-broken", "source": "reconfigure"}

        inventory: list[dict[str, object]] = []
        registry = self._install_registry(flow, inventory)

        with self._identity_wire(
            inventory,
            answers=[self._inventory_session(self.NEW_SESSION, self.FULL_PN)],
            read_pn=self.FULL_PN,
        ):
            result = await flow.async_step_reconfigure(self._manual_input("192.168.1.60"))

        self.assertEqual(result["type"], "abort")
        self.assertEqual(result["reason"], "reconfigure_successful")
        self.assertEqual(entry.data[CONF_COLLECTOR_PN], self.FULL_PN)
        self.assertEqual(entry.data[CONF_CONNECTION_STRATEGY], "callback_on_demand")
        # Identity repair records NO callback recovery evidence.
        self.assertNotIn(CONF_CONNECTION_STRATEGY_EVIDENCE, entry.data)
        self.assertEqual(entry.unique_id, f"collector:{self.FULL_PN}")
        self.assertTrue(flow._callback_continuation._handed_off)
        owner = registry.owner_for_pn(self.FULL_PN)
        self.assertTrue(owner.startswith("callback_verification:"))

    async def test_reconfigure_preserves_canonical_strategy_and_adds_no_evidence(self) -> None:
        # Behavioral test B (canonical entry): the entry already carries the
        # user's chosen strategy. Identity repair re-binds the PN and leaves the
        # strategy byte-for-byte -- it never re-decides how the collector
        # connects, and it never stamps callback recovery evidence.
        from custom_components.eybond_local.const import (
            CONF_COLLECTOR_PN,
            CONF_CONNECTION_STRATEGY,
            CONF_CONNECTION_STRATEGY_EVIDENCE,
        )

        flow = self._make_flow()
        entry = _FakeSetupEntry(
            "entry-broken",
            {
                "connection_type": "eybond",
                "connection_mode": "known_ip",
                CONF_COLLECTOR_PN: "",
                # The canonical axis is already present: the user's choice.
                CONF_CONNECTION_STRATEGY: "callback_on_demand",
            },
        )
        flow.hass.config_entries._entries.append(entry)
        flow.context = {"entry_id": "entry-broken", "source": "reconfigure"}
        inventory: list[dict[str, object]] = []
        self._install_registry(flow, inventory)

        with self._identity_wire(
            inventory,
            answers=[self._inventory_session(self.NEW_SESSION, self.FULL_PN)],
            read_pn=self.FULL_PN,
        ):
            result = await flow.async_step_reconfigure(self._manual_input("192.168.1.60"))

        self.assertEqual(result["type"], "abort")
        self.assertEqual(result["reason"], "reconfigure_successful")
        self.assertEqual(entry.data[CONF_COLLECTOR_PN], self.FULL_PN)
        self.assertEqual(entry.data[CONF_CONNECTION_STRATEGY], "callback_on_demand")
        self.assertNotIn(CONF_CONNECTION_STRATEGY_EVIDENCE, entry.data)

    async def test_reconfigure_without_strong_pn_does_not_masquerade_as_normal(self) -> None:
        # Item 8: until repair actually binds a strong PN, reconfigure must NOT
        # silently "fix" the entry -- it re-prompts, leaving the entry PN-less.
        from custom_components.eybond_local.const import CONF_COLLECTOR_PN

        flow = self._make_flow()
        entry = self._pn_less_entry()
        flow.hass.config_entries._entries.append(entry)
        flow.context = {"entry_id": "entry-broken", "source": "reconfigure"}
        inventory: list[dict[str, object]] = []
        registry = self._install_registry(flow, inventory)

        with self._identity_wire(
            inventory,
            # A session opens, but its identity cannot be read authoritatively.
            answers=[
                self._inventory_session(
                    self.NEW_SESSION, "", identity_source="framed_heartbeat"
                )
            ],
            read_pn=None,
        ):
            result = await flow.async_step_reconfigure(self._manual_input("192.168.1.60"))

        self.assertEqual(result["type"], "menu")
        self.assertEqual(result["step_id"], "reconfigure_confirm")
        self.assertIn(
            flow._manual_result.last_error,
            ("callback_timeout", "callback_identity_unverified"),
        )
        self.assertEqual(entry.data.get(CONF_COLLECTOR_PN, ""), "")
        self.assertEqual(registry.owner_for_pn(self.FULL_PN), "")

    async def test_reconfigure_ambiguous_when_two_new_collectors_answer(self) -> None:
        # Item 6: bind-any repair must NEVER pick the first inventory element. Two
        # distinct new strong PNs -> ambiguity, and nothing is bound.
        from custom_components.eybond_local.const import CONF_COLLECTOR_PN

        flow = self._make_flow()
        entry = self._pn_less_entry()
        flow.hass.config_entries._entries.append(entry)
        flow.context = {"entry_id": "entry-broken", "source": "reconfigure"}
        inventory: list[dict[str, object]] = []
        registry = self._install_registry(flow, inventory)

        with self._identity_wire(
            inventory,
            # TWO distinct collectors answer in the window: unattributable.
            answers=[
                self._inventory_session(self.NEW_SESSION, self.FULL_PN),
                self._inventory_session("listener-18899-3", self.OTHER_FULL_PN),
            ],
            read_pn=self.FULL_PN,
        ):
            result = await flow.async_step_reconfigure(self._manual_input("192.168.1.60"))

        self.assertEqual(result["type"], "menu")
        self.assertEqual(result["step_id"], "reconfigure_confirm")
        self.assertEqual(flow._manual_result.last_error, "callback_identity_ambiguous")
        self.assertEqual(entry.data.get(CONF_COLLECTOR_PN, ""), "")
        # Neither identity was claimed by this flow.
        self.assertEqual(registry.owner_for_pn(self.FULL_PN), "")
        self.assertEqual(registry.owner_for_pn(self.OTHER_FULL_PN), "")

    async def test_reconfigure_not_required_for_healthy_entry(self) -> None:
        # Item 5: a healthy PN-bound entry must not run identity repair; the flow
        # aborts without changing strategy or triggering a callback.
        from custom_components.eybond_local.const import (
            CONF_COLLECTOR_PN,
            CONF_CONNECTION_STRATEGY,
        )

        flow = self._make_flow()
        entry = _FakeSetupEntry(
            "entry-healthy",
            {
                "connection_type": "eybond",
                CONF_COLLECTOR_PN: self.FULL_PN,
                CONF_CONNECTION_STRATEGY: "inbound",
                "connection_strategy_evidence": "reboot_reconnect",
            },
        )
        flow.hass.config_entries._entries.append(entry)
        flow.context = {"entry_id": "entry-healthy", "source": "reconfigure"}

        with patch.object(
            admission_transaction_module,
            "async_run_callback_identity_transaction",
            side_effect=AssertionError("healthy entry must not be probed/triggered"),
        ):
            result = await flow.async_step_reconfigure(self._manual_input("192.168.1.60"))

        self.assertEqual(result["type"], "abort")
        self.assertEqual(result["reason"], "reconfigure_not_required")
        # Strategy untouched: a healthy inbound entry is NOT flipped to callback.
        self.assertEqual(entry.data[CONF_CONNECTION_STRATEGY], "inbound")

    async def test_reconfigure_collision_with_unloaded_same_pn_entry(self) -> None:
        # Item 7: a DIFFERENT config entry already owns collector:{pn} (unloaded,
        # so it holds NO registry claim, but the unique id is taken). Repair must
        # abort already_configured, leave the broken entry PN-less, and release
        # the attempt's claim.
        from custom_components.eybond_local.const import CONF_COLLECTOR_PN

        flow = self._make_flow()
        broken = self._pn_less_entry("entry-broken")
        healthy = _FakeSetupEntry("entry-healthy", {CONF_COLLECTOR_PN: self.FULL_PN})
        healthy.unique_id = f"collector:{self.FULL_PN}"
        flow.hass.config_entries._entries.extend([broken, healthy])
        flow.context = {"entry_id": "entry-broken", "source": "reconfigure"}
        inventory: list[dict[str, object]] = []
        registry = self._install_registry(flow, inventory)

        with self._identity_wire(
            inventory,
            answers=[self._inventory_session(self.NEW_SESSION, self.FULL_PN)],
            read_pn=self.FULL_PN,
        ):
            result = await flow.async_step_reconfigure(self._manual_input("192.168.1.60"))

        self.assertEqual(result["type"], "abort")
        self.assertEqual(result["reason"], "already_configured")
        self.assertEqual(broken.data.get(CONF_COLLECTOR_PN, ""), "")  # unchanged
        # The attempt's claim was released -> the other entry's identity is free.
        self.assertEqual(registry.owner_for_pn(self.FULL_PN), "")

    # ---- Path B symmetry: passive inbound restart/reconnect handoff (item 2) ----

    async def test_passive_inbound_verification_hands_off_to_entry_at_setup(self) -> None:
        # Item 2 -- the full production Path B: passive discovery -> restart/
        # reconnect verification -> confirm/create (prepare_handoff) -> setup
        # (complete_handoff) -> the runtime owns the session. Symmetric with the
        # manual callback e2e.
        from custom_components.eybond_local import (
            _register_entry_callback_session_claim,
        )

        flow = self._make_flow()
        inventory = [self._inventory_session(self.OLD_SESSION, self.FULL_PN)]
        registry = self._install_registry(flow, inventory)
        await flow.async_step_integration_discovery(self._discovery_info())
        new_session = self._inventory_session(self.NEW_SESSION, self.FULL_PN)

        class _FakeChannel:
            def __init__(self, **_kwargs) -> None:
                return None

            async def async_send_restart(self) -> None:
                inventory.clear()
                inventory.append(new_session)

            def is_connected(self) -> bool:
                return False

            async def async_close(self) -> None:
                return None

        with patch.object(admission_transaction_module, "ObservedSessionRestartChannel", _FakeChannel):
            await self._drive_verification(flow)

        # Success HELD the claim (item 2), under a unique per-attempt owner.
        owner = registry.owner_for_pn(self.FULL_PN)
        self.assertTrue(owner.startswith("strategy_verification:"))

        created = await flow.async_step_confirm({"poll_mode": "auto"})

        self.assertEqual(created["type"], "create_entry")
        self.assertEqual(created["data"]["collector_pn"], self.FULL_PN)
        # Confirm committed the handoff; flow cleanup must not release it.
        self.assertTrue(flow._admission_transaction.handed_off)
        flow.async_remove()
        self.assertEqual(registry.owner_for_pn(self.FULL_PN), owner)

        # PRODUCTION setup completes the handoff to the durable entry_id. (The
        # inbound claim keeps its pre-restart session id; the runtime rebinds the
        # next same-PN session by durable PN, which is what ownership guarantees.)
        entry = _FakeSetupEntry("entry-inbound", created["data"])
        _register_entry_callback_session_claim(flow.hass, entry)
        self.assertEqual(registry.owner_for_pn(self.FULL_PN), "entry-inbound")

    # ---- item 4: rollback after a terminal helper throws AFTER prepare_handoff ----

    async def test_create_terminal_exception_rolls_back_committed_handoff(self) -> None:
        flow = self._make_flow()
        flow._callback_continuation._expected_pn = self.FULL_PN
        flow._callback_continuation._old_session_id = self.OLD_SESSION
        inventory = [self._inventory_session(self.OLD_SESSION, self.FULL_PN)]
        registry = self._install_registry(flow, inventory)

        boom = RuntimeError("HA create failed")

        def _raise(*_a, **_k):
            raise boom

        with self._identity_wire(
            inventory,
            answers=[self._inventory_session(self.NEW_SESSION, self.FULL_PN)],
            read_pn=self.FULL_PN,
        ):
            routed = await flow.async_step_manual(self._manual_input("192.168.1.60"))
            self.assertEqual(routed["step_id"], "manual_recovery_confirm")

        # Recovery verifies; HA's create then throws AFTER the capability was
        # verified -- the adopted recovery owner must be fully rolled back.
        tx, _calls = self._recovery_transaction_stub(registry)
        with patch(
            "custom_components.eybond_local.connection.admission_transaction."
            "async_run_callback_recovery_transaction",
            side_effect=tx,
        ):
            progress = await flow.async_step_manual_recovery_verify()
            self.assertEqual(progress["type"], "progress")
            await flow._manual_recovery_task
            await flow.async_step_manual_recovery_verify()
            with patch.object(flow, "async_create_entry", side_effect=_raise):
                with self.assertRaises(RuntimeError):
                    await flow.async_step_manual_recovery_result()

        # The committed handoff was rolled back: flag reset, owner released, so a
        # retry (or another flow) is not permanently blocked.
        self.assertFalse(flow._callback_continuation._handed_off)
        self.assertEqual(registry.owner_for_pn(self.FULL_PN), "")
        self.assertEqual(flow._callback_continuation._owner, "")

    async def test_reconfigure_terminal_exception_rolls_back_committed_handoff(self) -> None:
        flow = self._make_flow()
        entry = self._pn_less_entry()
        flow.hass.config_entries._entries.append(entry)
        flow.context = {"entry_id": "entry-broken", "source": "reconfigure"}
        inventory: list[dict[str, object]] = []
        registry = self._install_registry(flow, inventory)

        boom = RuntimeError("HA update failed")

        def _raise(*_a, **_k):
            raise boom

        with self._identity_wire(
            inventory,
            answers=[self._inventory_session(self.NEW_SESSION, self.FULL_PN)],
            read_pn=self.FULL_PN,
        ):
            with patch.object(flow, "async_update_reload_and_abort", side_effect=_raise):
                with self.assertRaises(RuntimeError):
                    await flow.async_step_reconfigure(self._manual_input("192.168.1.60"))

        self.assertFalse(flow._callback_continuation._handed_off)
        self.assertEqual(registry.owner_for_pn(self.FULL_PN), "")
        self.assertEqual(entry.data.get("collector_pn", ""), "")  # entry untouched


    # --- retry must be a WHOLE new attempt, never a bare re-probe -------------
    #
    # async_step_manual_probe_again used to call the probe directly and route on,
    # keeping the previous attempt's baseline, ledger generation, verified PN and
    # registry claim. That let a second probe reaching collector B be combined
    # with the first attempt's proof/claim for collector A. Every active manual
    # callback path now runs the one shared lifecycle helper.

    async def _first_attempt_claiming(self, flow, inventory, pn, session_id):
        """Drive a successful first manual attempt; return its claim owner."""

        def _answers():
            inventory.append(self._inventory_session(session_id, pn))

        detector = self._recording_detector(
            results=(self._manual_result_with_pn(pn),), on_detect=_answers
        )
        routed = await self._drive_generic_callback(flow, detector)
        # Batch 6: a certified identity routes to the RECOVERY consent -- the
        # normal callback entry needs the proven recovery route first.
        self.assertEqual(routed["step_id"], "manual_recovery_confirm")
        self.assertEqual(flow._callback_continuation._certified_pn, pn)
        return flow._callback_continuation._owner

    def _recovery_transaction_stub(
        self, registry, *, owner="callback_recovery:flowtest"
    ):
        """Scripted transaction: the exact end state the real wrapper leaves.

        Claims the saved session under the transaction's own owner (the
        identity owner was released by the producer just before), promotes,
        prepares, and returns a REAL callback_verified outcome carrying that
        exact owner. Also records every call's kwargs for route assertions.
        """

        from custom_components.eybond_local.connection.recovery_contract import (
            CALLBACK_RECOVERY_RESET_UNICAST_RECONNECT,
            CallbackRecoveryProof,
        )
        from custom_components.eybond_local.connection.recovery.verification import (
            RecoveryVerificationOutcome,
            STATE_CALLBACK_VERIFIED,
        )

        calls: list[dict] = []

        async def _tx(**kwargs):
            calls.append(kwargs)
            pn = kwargs["collector_pn"]
            registry.claim_session(owner, session_id=kwargs["session_id"])
            registry.promote_claim_to_full_pn(owner, pn)
            registry.prepare_handoff(owner, pn)
            route = kwargs["route"]
            return RecoveryVerificationOutcome(
                status=STATE_CALLBACK_VERIFIED,
                collector_pn=pn,
                new_session_id=kwargs["session_id"],
                callback_proof=CallbackRecoveryProof(
                    method=CALLBACK_RECOVERY_RESET_UNICAST_RECONNECT,
                    collector_pn=pn,
                    identity_source="fc2_parameter_2",
                    verified_at="2026-07-17T10:00:00+00:00",
                    trigger_target=route.trigger_target,
                    advertised_ha_endpoint=route.advertised_ha_endpoint,
                    listener_port=route.listener_port,
                ),
                handoff_owner=owner,
            )

        return _tx, calls

    async def _drive_recovery_verified(
        self, flow, registry, *, owner="callback_recovery:flowtest"
    ):
        """Progress -> completed task -> result step (adoption + terminal)."""

        tx, calls = self._recovery_transaction_stub(registry, owner=owner)

        with patch(
            "custom_components.eybond_local.connection.admission_transaction."
            "async_run_callback_recovery_transaction",
            side_effect=tx,
        ):
            progress = await flow.async_step_manual_recovery_verify()
            self.assertEqual(progress["type"], "progress")
            await flow._manual_recovery_task
            done = await flow.async_step_manual_recovery_verify()
            self.assertEqual(done["type"], "progress_done")
            self.assertEqual(done["next_step_id"], "manual_recovery_result")
            result = await flow.async_step_manual_recovery_result()
        return result, calls

    async def _probe_again(self, flow, detector):
        # A retry is a FULL new attempt: a new identity transaction (new lease,
        # new trigger sequence, new authoritative read) plus the detection that
        # follows it. Same seam as the first submit.
        with self._identity_wire_for(detector), patch(
            "custom_components.eybond_local.flows.config.scan.create_onboarding_manager",
            return_value=detector,
        ):
            return await flow.async_step_manual_probe_again()

    async def test_probe_again_to_other_collector_rebinds_wholly(self) -> None:
        # A. First attempt claims A; "probe again" reaches B on a new strong
        # session. The old claim on A must be gone, the new claim must belong to
        # B, and the entry may only ever be created as B.
        flow = self._make_flow()
        inventory: list[dict[str, object]] = []
        registry = self._install_registry(flow, inventory)

        owner_a = await self._first_attempt_claiming(
            flow, inventory, self.FULL_PN, self.OLD_SESSION
        )
        self.assertEqual(registry.owner_for_pn(self.FULL_PN), owner_a)

        def _b_answers():
            inventory.append(self._inventory_session(self.NEW_SESSION, self.OTHER_FULL_PN))

        routed = await self._probe_again(
            flow,
            self._recording_detector(
                results=(self._manual_result_with_pn(self.OTHER_FULL_PN),),
                on_detect=_b_answers,
            ),
        )
        self.assertEqual(routed["step_id"], "manual_recovery_confirm")

        # The first attempt's claim on A is released, not merely overwritten.
        self.assertEqual(registry.owner_for_pn(self.FULL_PN), "")
        self.assertEqual(registry.claimed_identity(owner_a), "")
        # The new claim is a NEW owner, bound to B's new session.
        owner_b = registry.owner_for_pn(self.OTHER_FULL_PN)
        self.assertTrue(owner_b.startswith("callback_verification:"))
        self.assertNotEqual(owner_b, owner_a)
        self.assertEqual(registry.claimed_session_id(owner_b), self.NEW_SESSION)
        self.assertEqual(flow._callback_continuation._certified_pn, self.OTHER_FULL_PN)
        self.assertEqual(flow._callback_continuation._owner, owner_b)

        created, _calls = await self._drive_recovery_verified(flow, registry)

        # The entry is B, and ONLY B ...
        self.assertEqual(created["type"], "create_entry")
        self.assertEqual(created["data"]["collector_pn"], self.OTHER_FULL_PN)
        self.assertEqual(getattr(flow, "_test_unique_id", ""), f"collector:{self.OTHER_FULL_PN}")
        # ... the handoff certifies B under the RECOVERY owner ...
        recovery_owner = registry.owner_for_pn(self.OTHER_FULL_PN)
        self.assertTrue(recovery_owner.startswith("callback_recovery:"))
        self.assertEqual(
            registry.prepared_handoff_identity(recovery_owner, self.OTHER_FULL_PN),
            self.OTHER_FULL_PN,
        )
        # ... and no owner is left holding A anywhere in the registry.
        self.assertEqual(registry.owner_for_pn(self.FULL_PN), "")

    async def test_probe_again_timeout_drops_first_attempt_proof(self) -> None:
        # B. First attempt claims A; the retry times out. The claim on A must be
        # released, the verified PN cleared, and no normal entry for A may be
        # creatable from what the flow still holds.
        flow = self._make_flow()
        inventory: list[dict[str, object]] = []
        registry = self._install_registry(flow, inventory)

        owner_a = await self._first_attempt_claiming(
            flow, inventory, self.FULL_PN, self.OLD_SESSION
        )
        self.assertEqual(registry.owner_for_pn(self.FULL_PN), owner_a)

        # Our trigger fires; nothing new answers it.
        routed = await self._probe_again(flow, self._recording_detector(results=()))

        self._assert_callback_failure_menu(flow, routed, "callback_timeout")
        self.assertEqual(flow._callback_continuation._certified_pn, "")
        self.assertEqual(registry.owner_for_pn(self.FULL_PN), "")
        self.assertEqual(flow._callback_continuation._owner, "")
        self.assertFalse(flow._callback_continuation._handed_off)

        # The stale identity cannot be turned into a normal entry for A.
        created = await flow.async_step_manual_save()
        self.assertNotEqual(created.get("data", {}).get("collector_pn", ""), self.FULL_PN)
        self.assertEqual(registry.owner_for_pn(self.FULL_PN), "")

    async def test_probe_again_interference_drops_first_attempt_proof(self) -> None:
        # C. First attempt claims A; during the retry a CONCURRENT trigger fires,
        # so even a matching session is not attributable to us. Old claim gone,
        # no new claim, no stale entry.
        flow = self._make_flow()
        inventory: list[dict[str, object]] = []
        registry = self._install_registry(flow, inventory)

        owner_a = await self._first_attempt_claiming(
            flow, inventory, self.FULL_PN, self.OLD_SESSION
        )

        def _answers():
            inventory.append(self._inventory_session(self.NEW_SESSION, self.FULL_PN))

        routed = await self._probe_again(
            flow,
            self._recording_detector(
                results=(self._manual_result_with_pn(self.FULL_PN),),
                own_triggers=1,
                extra_triggers=1,
                on_detect=_answers,
            ),
        )

        self._assert_callback_failure_menu(
            flow, routed, "callback_trigger_interference"
        )
        self.assertEqual(flow._callback_continuation._certified_pn, "")
        # The old claim is released and NO new claim was taken.
        self.assertEqual(registry.owner_for_pn(self.FULL_PN), "")
        self.assertEqual(registry.claimed_identity(owner_a), "")
        self.assertEqual(flow._callback_continuation._owner, "")

        created = await flow.async_step_manual_save()
        self.assertNotEqual(created.get("data", {}).get("collector_pn", ""), self.FULL_PN)

    async def test_probe_again_is_a_whole_new_attempt_with_its_own_baseline(self) -> None:
        # F. The retry is a WHOLE new identity transaction with its OWN baseline
        # and its OWN attempt window -- never the first attempt's snapshots.
        # Both proofs are behavioral:
        #  * baseline: the first attempt's session is STILL LIVE during the
        #    retry; a stale (first) baseline would make it "fresh" alongside the
        #    retry's answer -- two distinct identities -> ambiguous. The retry
        #    succeeding on B alone proves it snapshotted its own baseline.
        #  * attempt window: the retry ran under a NEW unique owner (a new
        #    transaction), and the first attempt's claim is gone.
        flow = self._make_flow()
        inventory: list[dict[str, object]] = []
        registry = self._install_registry(flow, inventory)

        owner_a = await self._first_attempt_claiming(
            flow, inventory, self.FULL_PN, self.OLD_SESSION
        )
        self.assertEqual(registry.owner_for_pn(self.FULL_PN), owner_a)

        routed = await self._probe_again(
            flow,
            self._recording_detector(
                results=(self._manual_result_with_pn(self.OTHER_FULL_PN),),
                on_detect=lambda: inventory.append(
                    self._inventory_session(self.NEW_SESSION, self.OTHER_FULL_PN)
                ),
            ),
        )

        self.assertEqual(routed["step_id"], "manual_recovery_confirm")
        self.assertEqual(flow._callback_continuation._certified_pn, self.OTHER_FULL_PN)
        owner_b = registry.owner_for_pn(self.OTHER_FULL_PN)
        self.assertTrue(owner_b.startswith("callback_verification:"))
        # A NEW attempt identity: never the first attempt's owner, whose claim
        # (and baseline) did not survive into the retry.
        self.assertNotEqual(owner_b, owner_a)
        self.assertEqual(registry.owner_for_pn(self.FULL_PN), "")
        self.assertEqual(registry.claimed_identity(owner_a), "")

    async def test_flow_removal_releases_prepared_manual_handoff(self) -> None:
        # Terminal path: the user abandons the flow AFTER a successful attempt
        # (prepared handoff held) but BEFORE creating the entry. Removal must
        # release the prepared handoff so the identity is free again.
        flow = self._make_flow()
        inventory: list[dict[str, object]] = []
        registry = self._install_registry(flow, inventory)

        await self._first_attempt_claiming(
            flow, inventory, self.FULL_PN, self.NEW_SESSION
        )
        self.assertTrue(
            registry.owner_for_pn(self.FULL_PN).startswith("callback_verification:")
        )

        flow.async_remove()

        self.assertEqual(registry.owner_for_pn(self.FULL_PN), "")
        self.assertEqual(flow._callback_continuation._owner, "")


    async def test_handoff_flag_stays_false_when_nothing_was_prepared(self) -> None:
        # Item 5: the registry reports "no claim under this owner" (False). The
        # seam must NOT record a handoff it never made: _release_verification_claim
        # deliberately stops releasing once _callback_ownership_handed_off is set,
        # so a lying flag would suppress this flow's own cleanup and strand the
        # owner. No abort either -- entry setup re-claims and fails closed there.
        # The flow-owned claim decision now lives behind the seam's prepare_terminal.
        from custom_components.eybond_local.connection.recovery.terminal import (
            RecoveryTerminalInput,
        )

        flow = self._make_flow()
        registry = self._install_registry(flow, [])
        flow._callback_continuation._registry = registry
        flow._callback_continuation._owner = "callback_verification:vanished"
        flow._callback_continuation._certified_pn = self.FULL_PN
        flow._callback_continuation._state = "identity_certified"

        decision = flow._callback_continuation.prepare_terminal(
            self.FULL_PN, RecoveryTerminalInput.none()
        )

        self.assertFalse(decision.owns)
        self.assertEqual(decision.abort_reason, "recovery_ownership_unavailable")
        self.assertFalse(flow._callback_continuation._handed_off)
        self.assertEqual(flow._callback_continuation._owner, "")
        self.assertEqual(registry.owner_for_pn(self.FULL_PN), "")

    async def test_handoff_refusal_aborts_and_releases_own_claim(self) -> None:
        # Item 5 (other half): a REFUSED handoff (ValueError) must abort without
        # creating an entry and must release this flow's own claim -- now decided
        # by the seam's prepare_terminal (a typed abort_reason, not a result).
        from custom_components.eybond_local.connection.recovery.terminal import (
            RecoveryTerminalInput,
        )

        flow = self._make_flow()
        sessions = [self._inventory_session(self.OLD_SESSION, self.FULL_PN)]
        registry = self._install_registry(flow, sessions)
        registry.claim_session("callback_verification:mine", session_id=self.OLD_SESSION)
        registry.promote_claim_to_full_pn("callback_verification:mine", self.FULL_PN)
        flow._callback_continuation._registry = registry
        flow._callback_continuation._owner = "callback_verification:mine"
        flow._callback_continuation._certified_pn = self.FULL_PN
        flow._callback_continuation._state = "identity_certified"

        # The claim stands for A; handing off B is refused by the registry.
        decision = flow._callback_continuation.prepare_terminal(
            self.OTHER_FULL_PN, RecoveryTerminalInput.none()
        )

        self.assertEqual(decision.abort_reason, "recovery_ownership_unavailable")
        self.assertFalse(decision.owns)
        self.assertFalse(flow._callback_continuation._handed_off)
        flow._callback_continuation.release_terminal_owner()
        self.assertEqual(registry.owner_for_pn(self.FULL_PN), "")
        self.assertEqual(registry.owner_for_pn(self.OTHER_FULL_PN), "")

    # ---- the terminal coordinator with an ALREADY-PREPARED callback owner ----

    def _prepared_callback_recovery(self, flow, *, owner="callback_recovery:t1"):
        """Real registry + real transaction-shaped prepared owner + outcome."""

        from custom_components.eybond_local.connection.recovery_contract import (
            CALLBACK_RECOVERY_RESET_UNICAST_RECONNECT,
            CallbackRecoveryProof,
        )
        from custom_components.eybond_local.connection.recovery.verification import (
            RecoveryVerificationOutcome,
            STATE_CALLBACK_VERIFIED,
        )

        inventory = [self._inventory_session(self.NEW_SESSION, self.FULL_PN)]
        registry = self._install_registry(flow, inventory)
        registry.claim_session(owner, session_id=self.NEW_SESSION)
        registry.promote_claim_to_full_pn(owner, self.FULL_PN)
        self.assertTrue(registry.prepare_handoff(owner, self.FULL_PN))
        outcome = RecoveryVerificationOutcome(
            status=STATE_CALLBACK_VERIFIED,
            collector_pn=self.FULL_PN,
            new_session_id=self.NEW_SESSION,
            callback_proof=CallbackRecoveryProof(
                method=CALLBACK_RECOVERY_RESET_UNICAST_RECONNECT,
                collector_pn=self.FULL_PN,
                identity_source="fc2_parameter_2",
                verified_at="2026-07-16T10:00:00+00:00",
                trigger_target="192.168.1.60:58899",
                advertised_ha_endpoint="198.51.100.7:48899",
                listener_port=18899,
            ),
            handoff_owner=owner,
        )
        return registry, owner, outcome

    # ---- B. callback prepared-owner lifecycle (adoption-based) ----

    async def test_adoption_stores_the_exact_owner_in_flow_state(self) -> None:
        flow = self._make_flow()
        registry, owner, outcome = self._prepared_callback_recovery(flow)

        self.assertTrue(_adopt_recovery_for_test(flow, outcome))

        self.assertIs(flow._callback_continuation._registry, registry)
        self.assertEqual(flow._callback_continuation._owner, owner)
        self.assertEqual(flow._callback_continuation._callback_terminal_input.prepared_handoff_owner, owner)
        self.assertIsNotNone(flow._callback_continuation._callback_terminal_input.callback_proof)
        self.assertFalse(flow._callback_continuation._handed_off)

    async def test_abort_after_adoption_releases_the_adopted_owner(self) -> None:
        flow = self._make_flow()
        registry, owner, outcome = self._prepared_callback_recovery(flow)
        self.assertTrue(_adopt_recovery_for_test(flow, outcome))

        # Any pre-terminal cleanup path (abort/cancel) funnels here.
        flow._callback_continuation.release_terminal_owner()

        self.assertEqual(registry.owner_for_pn(self.FULL_PN), "")
        self.assertEqual(registry.prepared_handoff_identity(owner, self.FULL_PN), "")
        self.assertEqual(flow._callback_continuation._owner, "")

    async def test_async_remove_after_adoption_releases_the_adopted_owner(self) -> None:
        flow = self._make_flow()
        registry, owner, outcome = self._prepared_callback_recovery(flow)
        self.assertTrue(_adopt_recovery_for_test(flow, outcome))

        flow.async_remove()

        self.assertEqual(registry.owner_for_pn(self.FULL_PN), "")
        self.assertEqual(registry.prepared_handoff_identity(owner, self.FULL_PN), "")

    async def test_adopted_owner_terminal_success_keeps_handoff_for_setup(self) -> None:
        from custom_components.eybond_local.connection.session_registry import (
            CallbackSessionRegistry,
        )

        flow = self._make_flow()
        registry, owner, outcome = self._prepared_callback_recovery(flow)
        self.assertTrue(_adopt_recovery_for_test(flow, outcome))

        sentinel = {"type": "create_entry", "reason": ""}
        with patch.object(
            CallbackSessionRegistry,
            "prepare_handoff",
            autospec=True,
            side_effect=CallbackSessionRegistry.prepare_handoff,
        ) as prepare_mock:
            result = flow._create_entry_with_handoff(
                self.FULL_PN, lambda: sentinel, recovery=flow._callback_continuation._callback_terminal_input
            )

        self.assertIs(result, sentinel)
        # The transaction prepared the owner already; the coordinator only
        # verified the capability -- ZERO further prepare_handoff calls.
        self.assertEqual(prepare_mock.call_count, 0)
        # Success committed the flow: cleanup between CREATE_ENTRY and setup
        # must NOT release the prepared owner.
        self.assertTrue(flow._callback_continuation._handed_off)
        flow.async_remove()
        self.assertEqual(
            registry.prepared_handoff_identity(owner, self.FULL_PN), self.FULL_PN
        )
        # The committed handoff survived for entry setup to complete.
        self.assertTrue(registry.complete_handoff(self.FULL_PN, "entry-new"))
        self.assertEqual(registry.owner_for_pn(self.FULL_PN), "entry-new")

    async def test_terminal_without_adoption_refuses_and_never_releases(self) -> None:
        # A direct/forged RecoveryTerminalInput carrying a REAL prepared owner
        # the flow never adopted: refused, and the foreign owner is untouched.
        from custom_components.eybond_local.connection.recovery.terminal import (
            RecoveryTerminalInput,
        )

        flow = self._make_flow()
        registry, owner, outcome = self._prepared_callback_recovery(flow)
        forged = RecoveryTerminalInput.from_callback_transaction(outcome)
        ran: list[int] = []

        result = flow._create_entry_with_handoff(
            self.FULL_PN,
            lambda: ran.append(1) or {"type": "create_entry"},
            recovery=forged,
        )

        self.assertEqual(result["type"], "abort")
        self.assertEqual(result["reason"], "recovery_ownership_unavailable")
        self.assertEqual(ran, [])  # the terminal never ran
        # NOT ours to touch: the real transaction owner stays fully prepared.
        self.assertEqual(
            registry.prepared_handoff_identity(owner, self.FULL_PN), self.FULL_PN
        )
        self.assertEqual(registry.owner_for_pn(self.FULL_PN), owner)

    async def test_adopted_stale_owner_is_refused_before_terminal(self) -> None:
        flow = self._make_flow()
        registry, owner, outcome = self._prepared_callback_recovery(flow)
        self.assertTrue(_adopt_recovery_for_test(flow, outcome))
        # The capability went stale AFTER adoption (released elsewhere).
        registry.release(owner)
        ran: list[int] = []

        result = flow._create_entry_with_handoff(
            self.FULL_PN,
            lambda: ran.append(1) or {"type": "create_entry"},
            recovery=flow._callback_continuation._callback_terminal_input,
        )

        self.assertEqual(result["reason"], "recovery_ownership_unavailable")
        self.assertEqual(ran, [])

    async def test_stale_outcome_is_not_adopted_and_leaves_no_state(self) -> None:
        flow = self._make_flow()
        registry, owner, outcome = self._prepared_callback_recovery(flow)
        # The capability died BEFORE adoption.
        registry.release(owner)

        self.assertFalse(_adopt_recovery_for_test(flow, outcome))

        self.assertIsNone(flow._callback_continuation._registry)
        self.assertEqual(flow._callback_continuation._owner, "")
        self.assertFalse(flow._callback_continuation._callback_terminal_input.has_proof)

    async def test_terminal_exception_releases_only_the_adopted_owner(self) -> None:
        flow = self._make_flow()
        registry, owner, outcome = self._prepared_callback_recovery(flow)
        self.assertTrue(_adopt_recovery_for_test(flow, outcome))
        # Another flow's unrelated claim must survive the rollback untouched.
        registry.claim(
            "callback_verification:other", collector_pn=self.OTHER_FULL_PN
        )

        def _boom():
            raise RuntimeError("terminal blew up after capability verification")

        with self.assertRaises(RuntimeError):
            flow._create_entry_with_handoff(
                self.FULL_PN, _boom, recovery=flow._callback_continuation._callback_terminal_input
            )

        # Exactly this flow's adopted owner is gone, refs cleared...
        self.assertEqual(registry.prepared_handoff_identity(owner, self.FULL_PN), "")
        self.assertEqual(registry.owner_for_pn(self.FULL_PN), "")
        self.assertFalse(registry.complete_handoff(self.FULL_PN, "entry-x"))
        self.assertEqual(flow._callback_continuation._owner, "")
        self.assertFalse(flow._callback_continuation._handed_off)
        # ...while the other owner's claim is untouched.
        self.assertEqual(
            registry.owner_for_pn(self.OTHER_FULL_PN), "callback_verification:other"
        )

    # ---- C. replacement safety ----

    async def test_adoption_releases_only_the_flows_previous_claim(self) -> None:
        flow = self._make_flow()
        registry, owner, outcome = self._prepared_callback_recovery(flow)
        # The flow still owns an OLD identity attempt, and an unrelated flow
        # owns a third identity.
        old_owner = "strategy_verification:old"
        registry.claim(old_owner, collector_pn=self.OTHER_FULL_PN)
        flow._callback_continuation._registry = registry
        flow._callback_continuation._owner = old_owner
        registry.claim("callback_verification:bystander", collector_pn="V000405SYN94677999")

        self.assertTrue(_adopt_recovery_for_test(flow, outcome))

        # Only the flow's own previous claim was released.
        self.assertEqual(registry.owner_for_pn(self.OTHER_FULL_PN), "")
        self.assertEqual(flow._callback_continuation._owner, owner)
        self.assertEqual(
            registry.owner_for_pn("V000405SYN94677999"),
            "callback_verification:bystander",
        )
        # The adopted capability itself is intact.
        self.assertEqual(
            registry.prepared_handoff_identity(owner, self.FULL_PN), self.FULL_PN
        )

    # ---- A. inbound flow-owned lifecycle ----

    async def test_inbound_flow_owner_prepares_exactly_once(self) -> None:
        flow = self._make_flow()
        sessions = [self._inventory_session(self.NEW_SESSION, self.FULL_PN)]
        registry = self._install_registry(flow, sessions)
        owner = "strategy_verification:once"
        registry.claim_session(owner, session_id=self.NEW_SESSION)
        registry.promote_claim_to_full_pn(owner, self.FULL_PN)
        txn = self._admission_transaction("passive_scan", flow)
        terminal_input = self._inbound_terminal_input()
        from custom_components.eybond_local.connection.recovery.verification import (
            InboundRecoveryOutcome,
            STATE_INBOUND_VERIFIED,
        )

        txn._registry = registry
        txn._owner = owner
        txn._outcome = InboundRecoveryOutcome(
            status=STATE_INBOUND_VERIFIED,
            collector_pn=self.FULL_PN,
            new_session_id=self.NEW_SESSION,
            proof=terminal_input.inbound_proof,
        )
        txn._state = "verified"
        flow._admission_transaction = txn
        flow._callback_continuation = txn

        from custom_components.eybond_local.connection.session_registry import (
            CallbackSessionRegistry,
        )

        sentinel = {"type": "create_entry"}
        with patch.object(
            CallbackSessionRegistry,
            "prepare_handoff",
            autospec=True,
            side_effect=CallbackSessionRegistry.prepare_handoff,
        ) as prepare_mock:
            result = flow._create_entry_with_handoff(
                self.FULL_PN, lambda: sentinel, recovery=terminal_input
            )

        self.assertIs(result, sentinel)
        self.assertEqual(prepare_mock.call_count, 1)  # exactly once
        self.assertEqual(prepare_mock.call_args[0][1], owner)
        # The acceptance boundary certified the identity before the terminal.
        self.assertEqual(
            registry.prepared_handoff_identity(owner, self.FULL_PN), self.FULL_PN
        )
        self.assertTrue(registry.complete_handoff(self.FULL_PN, "entry-inbound"))

    def _inbound_terminal_input(self):
        from custom_components.eybond_local.connection.recovery_contract import (
            INBOUND_RECOVERY_REBOOT_RECONNECT_NO_TRIGGER,
            InboundRecoveryProof,
        )
        from custom_components.eybond_local.connection.recovery.terminal import (
            RecoveryTerminalInput,
        )

        return RecoveryTerminalInput(
            collector_pn=self.FULL_PN,
            inbound_proof=InboundRecoveryProof(
                method=INBOUND_RECOVERY_REBOOT_RECONNECT_NO_TRIGGER,
                collector_pn=self.FULL_PN,
                identity_source="fc2_parameter_2",
                verified_at="2026-07-16T10:00:00+00:00",
                session_protocol="eybond_framed",
            ),
        )

    async def test_inbound_proof_without_claim_refuses_terminal(self) -> None:
        flow = self._make_flow()
        self._install_registry(flow, [])
        ran: list[int] = []
        cases = (
            ("no_registry_no_owner", None, ""),
            ("registry_without_owner", flow._callback_session_registry(), ""),
            ("owner_without_registry", None, "strategy_verification:ghost"),
        )
        for label, registry, owner in cases:
            with self.subTest(case=label):
                flow._callback_continuation._registry = registry
                flow._callback_continuation._owner = owner
                result = flow._create_entry_with_handoff(
                    self.FULL_PN,
                    lambda: ran.append(1) or {"type": "create_entry"},
                    recovery=self._inbound_terminal_input(),
                )
                self.assertEqual(result["type"], "abort")
                self.assertEqual(result["reason"], "recovery_ownership_unavailable")
        self.assertEqual(ran, [])  # the terminal never ran in any case

    async def test_inbound_proof_with_stale_claim_refuses_terminal(self) -> None:
        # Registry + owner refs exist, but the registry no longer holds a
        # claim under that owner (prepare returns False): a proof-bearing
        # terminal must refuse instead of creating an unowned entry.
        flow = self._make_flow()
        registry = self._install_registry(flow, [])
        flow._callback_continuation._registry = registry
        flow._callback_continuation._owner = "strategy_verification:vanished"
        ran: list[int] = []

        result = flow._create_entry_with_handoff(
            self.FULL_PN,
            lambda: ran.append(1) or {"type": "create_entry"},
            recovery=self._inbound_terminal_input(),
        )

        self.assertEqual(result["type"], "abort")
        self.assertEqual(result["reason"], "recovery_ownership_unavailable")
        self.assertEqual(ran, [])
        self.assertFalse(flow._callback_continuation._handed_off)

    async def test_uncertifiable_prepared_inbound_claim_refuses_terminal(self) -> None:
        # prepare_handoff succeeds (a PN-only claim exists) but the registry
        # cannot certify it (no concrete session): the terminal must not run.
        flow = self._make_flow()
        registry = self._install_registry(flow, [])
        owner = "strategy_verification:pn-only"
        registry.claim(owner, collector_pn=self.FULL_PN)
        flow._callback_continuation._registry = registry
        flow._callback_continuation._owner = owner
        ran: list[int] = []

        result = flow._create_entry_with_handoff(
            self.FULL_PN,
            lambda: ran.append(1) or {"type": "create_entry"},
            recovery=self._inbound_terminal_input(),
        )

        self.assertEqual(result["type"], "abort")
        self.assertEqual(ran, [])
        self.assertFalse(flow._callback_continuation._handed_off)

    async def test_no_proof_terminal_still_works_without_claim(self) -> None:
        # RecoveryTerminalInput.none(): an ordinary/manual entry without any
        # recovery proof keeps the old behavior -- no claim required.
        flow = self._make_flow()
        sentinel = {"type": "create_entry"}

        result = flow._create_entry_with_handoff(self.FULL_PN, lambda: sentinel)

        self.assertIs(result, sentinel)
        self.assertEqual(
            flow.context["eybond_entry_commit_in_progress"], self.FULL_PN
        )

    # ---- Batch 6: manual callback recovery wiring (targeted) ----

    async def _identity_success(self, flow, inventory):
        with self._identity_wire(
            inventory,
            answers=[self._inventory_session(self.NEW_SESSION, self.FULL_PN)],
            read_pn=self.FULL_PN,
        ):
            routed = await flow.async_step_manual(self._manual_input("192.168.1.60"))
        self.assertEqual(routed["step_id"], "manual_recovery_confirm")
        return routed

    async def test_edit_from_recovery_consent_sends_no_reboot_or_udp(self) -> None:
        # The consent menu ran; the user edits instead of verifying. The recovery
        # transaction (reboot + trigger) never runs and no entry is created.
        flow = self._make_flow()
        inventory = [self._inventory_session(self.OLD_SESSION, self.FULL_PN)]
        registry = self._install_registry(flow, inventory)
        await self._identity_success(flow, inventory)

        with patch(
            "custom_components.eybond_local.connection.admission_transaction."
            "async_run_callback_recovery_transaction",
            side_effect=AssertionError("declined recovery must not reboot/trigger"),
        ):
            consent = await flow.async_step_manual_recovery_confirm()
            self.assertEqual(consent["type"], "menu")
            self.assertIn("manual_recovery_verify", consent["menu_options"])
            edited = await flow.async_step_manual_edit_settings()

        self.assertEqual(edited["type"], "form")
        self.assertEqual(edited["step_id"], "manual")
        self.assertEqual(registry.owner_for_pn(self.FULL_PN), "")

    async def test_recovery_route_is_form_values_never_peer_ip(self) -> None:
        # The answering socket has a DIFFERENT peer IP (NAT); the route must
        # carry the explicitly entered collector IP and the configured
        # advertised endpoint verbatim -- never the observed peer address, and
        # the advertised host is never replaced by the local bind address.
        flow = self._make_flow()
        inventory = [self._inventory_session(self.OLD_SESSION, self.FULL_PN)]
        registry = self._install_registry(flow, inventory)
        await self._identity_success(flow, inventory)
        # NAT-shaped form values: explicit advertised endpoint.
        flow._manual_config["advertised_server_ip"] = "198.51.100.7"
        flow._manual_config["advertised_tcp_port"] = 48899

        _created, calls = await self._drive_recovery_verified(flow, registry)

        (kwargs,) = calls
        route = kwargs["route"]
        self.assertEqual(route.trigger_target_ip, "192.168.1.60")  # form value
        self.assertEqual(route.advertised_ha_host, "198.51.100.7")
        self.assertEqual(route.advertised_ha_port, 48899)
        self.assertEqual(route.bind_ip, flow._manual_config["server_ip"])
        self.assertNotEqual(route.advertised_ha_host, route.bind_ip)
        self.assertEqual(route.listener_port, int(flow._manual_config["tcp_port"]))
        # Immutable attempt input: the exact certified session id and full PN.
        self.assertEqual(kwargs["session_id"], self.NEW_SESSION)
        self.assertEqual(kwargs["collector_pn"], self.FULL_PN)

    async def test_recovery_route_defaults_to_configured_server_endpoint(self) -> None:
        flow = self._make_flow()
        inventory = [self._inventory_session(self.OLD_SESSION, self.FULL_PN)]
        registry = self._install_registry(flow, inventory)
        await self._identity_success(flow, inventory)

        _created, calls = await self._drive_recovery_verified(flow, registry)

        (kwargs,) = calls
        route = kwargs["route"]
        self.assertEqual(route.advertised_ha_host, flow._manual_config["server_ip"])
        self.assertEqual(route.advertised_ha_port, int(flow._manual_config["tcp_port"]))

    def _recovery_outcome_stub(self, registry, *, status, owner, proof_kind):
        from custom_components.eybond_local.connection.recovery_contract import (
            CALLBACK_RECOVERY_RESET_UNICAST_RECONNECT,
            CallbackRecoveryProof,
            INBOUND_RECOVERY_REBOOT_RECONNECT_NO_TRIGGER,
            InboundRecoveryProof,
        )
        from custom_components.eybond_local.connection.recovery.verification import (
            RecoveryVerificationOutcome,
        )

        async def _tx(**kwargs):
            pn = kwargs["collector_pn"]
            if owner:
                registry.claim_session(owner, session_id=kwargs["session_id"])
                registry.promote_claim_to_full_pn(owner, pn)
                registry.prepare_handoff(owner, pn)
            if proof_kind == "inbound":
                proof = {"inbound_proof": InboundRecoveryProof(
                    method=INBOUND_RECOVERY_REBOOT_RECONNECT_NO_TRIGGER,
                    collector_pn=pn,
                    identity_source="fc2_parameter_2",
                    verified_at="2026-07-17T10:00:00+00:00",
                    session_protocol="eybond_framed",
                )}
            elif proof_kind == "callback":
                route = kwargs["route"]
                proof = {"callback_proof": CallbackRecoveryProof(
                    method=CALLBACK_RECOVERY_RESET_UNICAST_RECONNECT,
                    collector_pn=pn,
                    identity_source="fc2_parameter_2",
                    verified_at="2026-07-17T10:00:00+00:00",
                    trigger_target=route.trigger_target,
                    advertised_ha_endpoint=route.advertised_ha_endpoint,
                    listener_port=route.listener_port,
                )}
            else:
                proof = {}
            return RecoveryVerificationOutcome(
                status=status,
                failure_reason="" if proof else status,
                collector_pn=pn if proof else pn,
                new_session_id=kwargs["session_id"] if proof else "",
                handoff_owner=owner if proof else "",
                **proof,
            )

        return _tx

    async def _drive_recovery_outcome(self, flow, tx):
        with patch(
            "custom_components.eybond_local.connection.admission_transaction."
            "async_run_callback_recovery_transaction",
            side_effect=tx,
        ):
            progress = await flow.async_step_manual_recovery_verify()
            self.assertEqual(progress["type"], "progress")
            await flow._manual_recovery_task
            done = await flow.async_step_manual_recovery_verify()
            self.assertEqual(done["type"], "progress_done")
            return await flow.async_step_manual_recovery_result()

    async def test_inbound_recovered_requires_explicit_confirmation(self) -> None:
        from custom_components.eybond_local.connection.recovery.verification import (
            STATE_INBOUND_RECOVERED,
        )

        flow = self._make_flow()
        inventory = [self._inventory_session(self.OLD_SESSION, self.FULL_PN)]
        registry = self._install_registry(flow, inventory)
        await self._identity_success(flow, inventory)
        owner = "callback_recovery:autonomous"
        tx = self._recovery_outcome_stub(
            registry, status=STATE_INBOUND_RECOVERED, owner=owner, proof_kind="inbound"
        )

        result = await self._drive_recovery_outcome(flow, tx)

        # NOT silently callback_on_demand: an explicit confirmation menu.
        self.assertEqual(result["type"], "menu")
        self.assertEqual(result["step_id"], "manual_recovery_inbound_confirm")

        created = await flow.async_step_manual_recovery_accept_inbound()

        self.assertEqual(created["type"], "create_entry")
        self.assertEqual(created["data"]["connection_strategy"], "inbound")
        self.assertIn("inbound", created["data"]["recovery_contract"])
        self.assertNotIn("callback", created["data"]["recovery_contract"])
        # Inbound entries persist no unverified address.
        self.assertEqual(created["data"]["collector_ip"], "")

    async def test_inbound_recovered_decline_releases_exact_owner(self) -> None:
        from custom_components.eybond_local.connection.recovery.verification import (
            STATE_INBOUND_RECOVERED,
        )

        flow = self._make_flow()
        inventory = [self._inventory_session(self.OLD_SESSION, self.FULL_PN)]
        registry = self._install_registry(flow, inventory)
        await self._identity_success(flow, inventory)
        owner = "callback_recovery:autonomous2"
        tx = self._recovery_outcome_stub(
            registry, status=STATE_INBOUND_RECOVERED, owner=owner, proof_kind="inbound"
        )

        result = await self._drive_recovery_outcome(flow, tx)
        self.assertEqual(result["step_id"], "manual_recovery_inbound_confirm")
        self.assertEqual(
            registry.prepared_handoff_identity(owner, self.FULL_PN), self.FULL_PN
        )

        declined = await flow.async_step_manual_recovery_decline_inbound()

        self.assertEqual(declined["step_id"], "manual_recovery_failed")
        # The exact prepared owner is gone; nothing else was touched.
        self.assertEqual(registry.prepared_handoff_identity(owner, self.FULL_PN), "")
        self.assertEqual(registry.owner_for_pn(self.FULL_PN), "")
        self.assertIsNone(flow._callback_continuation._recovery_outcome)

    async def test_recovery_timeout_keeps_only_retry_and_edit_available(self) -> None:
        flow = self._make_flow()
        inventory = [self._inventory_session(self.OLD_SESSION, self.FULL_PN)]
        registry = self._install_registry(flow, inventory)
        await self._identity_success(flow, inventory)
        tx = self._recovery_outcome_stub(
            registry, status="inbound_not_verified", owner="", proof_kind=""
        )

        result = await self._drive_recovery_outcome(flow, tx)

        self.assertEqual(result["type"], "menu")
        self.assertEqual(result["step_id"], "manual_recovery_failed")
        self.assertEqual(
            result["menu_options"],
            ["manual_probe_again", "manual_edit_settings"],
        )
        # The typed failure is surfaced, not flattened to callback_timeout.
        self.assertEqual(flow._manual_recovery_error, "inbound_not_verified")


    async def test_typed_restart_not_supported_reaches_the_user(self) -> None:
        # An AT-wire collector honestly cannot reboot: the typed failure
        # travels to the failure menu verbatim -- zero invented proof.
        flow = self._make_flow()
        inventory = [self._inventory_session(self.OLD_SESSION, self.FULL_PN)]
        registry = self._install_registry(flow, inventory)
        await self._identity_success(flow, inventory)
        tx = self._recovery_outcome_stub(
            registry, status="restart_not_supported", owner="", proof_kind=""
        )

        result = await self._drive_recovery_outcome(flow, tx)

        self.assertEqual(result["step_id"], "manual_recovery_failed")
        self.assertEqual(flow._manual_recovery_error, "restart_not_supported")
        self.assertFalse(flow._callback_continuation._callback_terminal_input.has_proof)

    async def test_adoption_failure_releases_exact_outcome_owner(self) -> None:
        flow = self._make_flow()
        inventory = [self._inventory_session(self.OLD_SESSION, self.FULL_PN)]
        registry = self._install_registry(flow, inventory)
        await self._identity_success(flow, inventory)
        owner = "callback_recovery:adoptfail"
        tx, _calls = self._recovery_transaction_stub(registry, owner=owner)

        with patch(
            "custom_components.eybond_local.connection.admission_transaction."
            "async_run_callback_recovery_transaction",
            side_effect=tx,
        ), patch.object(
            flow._callback_continuation,
            "adopt_recovery",
            side_effect=RuntimeError("boom"),
        ):
            progress = await flow.async_step_manual_recovery_verify()
            self.assertEqual(progress["type"], "progress")
            await flow._manual_recovery_task
            await flow.async_step_manual_recovery_verify()
            result = await flow.async_step_manual_recovery_result()

        self.assertEqual(result["step_id"], "manual_recovery_failed")
        self.assertEqual(flow._manual_recovery_error, "recovery_ownership_unavailable")
        # The producer released exactly the outcome's owner.
        self.assertEqual(registry.prepared_handoff_identity(owner, self.FULL_PN), "")
        self.assertEqual(registry.owner_for_pn(self.FULL_PN), "")

    async def test_flow_cancel_during_recovery_progress_cleans_up(self) -> None:
        flow = self._make_flow()
        inventory = [self._inventory_session(self.OLD_SESSION, self.FULL_PN)]
        registry = self._install_registry(flow, inventory)
        await self._identity_success(flow, inventory)
        started = asyncio.Event()

        async def _hanging_tx(**_kwargs):
            started.set()
            await asyncio.sleep(60)

        with patch(
            "custom_components.eybond_local.connection.admission_transaction."
            "async_run_callback_recovery_transaction",
            side_effect=_hanging_tx,
        ):
            progress = await flow.async_step_manual_recovery_verify()
            self.assertEqual(progress["type"], "progress")
            task = flow._manual_recovery_task
            await asyncio.wait_for(started.wait(), timeout=5.0)

            flow.async_remove()
            with self.assertRaises(asyncio.CancelledError):
                await asyncio.wait_for(task, timeout=5.0)

        self.assertIsNone(flow._callback_continuation._recovery_outcome)
        # The identity owner was released at the recovery handover; nothing
        # is left claimed for the PN.
        self.assertEqual(registry.owner_for_pn(self.FULL_PN), "")

    async def test_async_remove_releases_unadopted_recovery_outcome(self) -> None:
        from custom_components.eybond_local.connection.recovery.verification import (
            STATE_INBOUND_RECOVERED,
        )

        flow = self._make_flow()
        inventory = [self._inventory_session(self.OLD_SESSION, self.FULL_PN)]
        registry = self._install_registry(flow, inventory)
        await self._identity_success(flow, inventory)
        owner = "callback_recovery:abandoned"
        tx = self._recovery_outcome_stub(
            registry, status=STATE_INBOUND_RECOVERED, owner=owner, proof_kind="inbound"
        )
        result = await self._drive_recovery_outcome(flow, tx)
        # The outcome is held (inbound confirmation pending) -- user closes.
        self.assertEqual(result["step_id"], "manual_recovery_inbound_confirm")

        flow.async_remove()

        self.assertEqual(registry.prepared_handoff_identity(owner, self.FULL_PN), "")
        self.assertEqual(registry.owner_for_pn(self.FULL_PN), "")
        self.assertIsNone(flow._callback_continuation._recovery_outcome)

    async def test_retry_after_recovery_failure_is_a_fresh_transaction(self) -> None:
        flow = self._make_flow()
        inventory = [self._inventory_session(self.OLD_SESSION, self.FULL_PN)]
        registry = self._install_registry(flow, inventory)
        await self._identity_success(flow, inventory)
        tx = self._recovery_outcome_stub(
            registry, status="inbound_not_verified", owner="", proof_kind=""
        )
        result = await self._drive_recovery_outcome(flow, tx)
        self.assertEqual(result["step_id"], "manual_recovery_failed")

        # "Probe again" = a whole new identity attempt; the failed recovery
        # state is wiped and nothing of the old attempt is reused.
        def _answers():
            inventory.append(self._inventory_session("listener-18899-9", self.FULL_PN))

        routed = await self._probe_again(
            flow,
            self._recording_detector(
                results=(self._manual_result_with_pn(self.FULL_PN),),
                on_detect=_answers,
            ),
        )
        self.assertEqual(routed["step_id"], "manual_recovery_confirm")
        self.assertEqual(flow._manual_recovery_error, "")
        self.assertIsNone(flow._callback_continuation._recovery_outcome)
        self.assertFalse(flow._callback_continuation._callback_terminal_input.has_proof)
        self.assertEqual(flow._callback_continuation._certified_session_id, "listener-18899-9")



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


class OptionsStrategyTransitionStepsTests(unittest.IsolatedAsyncioTestCase):
    """Batch 8: the options-flow confirmation/progress/result transition steps."""

    def _make_flow(
        self,
        *,
        transition_result=None,
        transition_error=None,
        endpoint_shape=None,
    ):
        from custom_components.eybond_local.connection.strategy_transition import (
            StrategyTransitionResult,
        )

        entry = type("_Entry", (), {})()
        entry.data = {
            "connection_type": "eybond",
            "collector_kind": "factory_eybond",
            "server_ip": "192.168.1.50",
            "collector_ip": "192.168.1.55",
            "tcp_port": 8899,
            "udp_port": 58899,
            "connection_strategy": "inbound",
            "control_mode": "auto",
        }
        entry.options = {}
        entry.entry_id = "entry-1"

        calls: list[dict] = []

        class _Coordinator:
            collector_endpoint_write_shape = endpoint_shape

            def format_home_assistant_callback_endpoint(self, host, port):
                if getattr(endpoint_shape, "port_is_fixed", False):
                    return host
                return f"{host}:{port}"

            async def async_run_connection_strategy_transition(self, **kwargs):
                calls.append(kwargs)
                if transition_error is not None:
                    raise RuntimeError(transition_error)
                if transition_result is not None:
                    return transition_result
                return StrategyTransitionResult(
                    success=True, target_strategy=kwargs["target_strategy"]
                )

        entry.runtime_data = _Coordinator()
        flow = EybondLocalOptionsFlow(entry)
        flow.hass = _FakeHass()
        flow.context = {}
        flow._transition_target_strategy = "callback_on_demand"
        flow._transition_options_payload = {"poll_mode": "auto"}
        return flow, calls

    @staticmethod
    def _legacy_host_only_shape():
        from custom_components.eybond_local.collector_endpoint import (
            resolve_collector_endpoint_write_shape,
        )

        return resolve_collector_endpoint_write_shape(
            cloud_family="legacy_binary",
            template_endpoint="ess.eybond.com",
        )

    async def test_host_only_transition_shows_address_only_and_uses_fixed_port(self) -> None:
        flow, calls = self._make_flow(endpoint_shape=self._legacy_host_only_shape())
        flow._transition_target_strategy = "inbound"
        flow._config_entry.data["connection_strategy"] = "callback_on_demand"

        form = await flow.async_step_strategy_transition()
        self.assertIn("advertised_server_ip", form["data_schema"].schema)
        self.assertNotIn("advertised_tcp_port", form["data_schema"].schema)
        self.assertIn(
            "502", form["description_placeholders"]["connection_strategy_risk"]
        )

        submitted = await flow.async_step_strategy_transition(
            {
                "advertised_server_ip": "192.168.1.50",
                "confirm_connection_strategy_risk": True,
            }
        )
        self.assertEqual(submitted["type"], "progress")
        await flow._transition_task
        self.assertEqual(calls[0]["inbound_endpoint"], "192.168.1.50")
        self.assertEqual(calls[0]["advertised_port"], 502)

    async def test_host_only_shape_does_not_constrain_callback_port(self) -> None:
        """CLDSRVHOST1 shape belongs to the persistent endpoint, not set>server."""

        flow, calls = self._make_flow(endpoint_shape=self._legacy_host_only_shape())
        flow._transition_target_strategy = "callback_on_demand"
        flow._config_entry.data["connection_strategy"] = "inbound"

        form = await flow.async_step_strategy_transition()
        port_field = next(
            key
            for key in form["data_schema"].schema
            if getattr(key, "schema", key) == "advertised_tcp_port"
        )
        self.assertEqual(port_field.default(), 8899)
        self.assertNotIn(
            "502", form["description_placeholders"]["connection_strategy_risk"]
        )

        submitted = await flow.async_step_strategy_transition(
            {
                "advertised_server_ip": "203.0.113.10",
                # A public NAT forwarding port need not equal any local
                # passive-discovery listener.
                "advertised_tcp_port": 50099,
                "collector_ip": "192.168.1.55",
                "confirm_connection_strategy_risk": True,
            }
        )
        self.assertEqual(submitted["type"], "progress")
        await flow._transition_task
        self.assertEqual(calls[0]["advertised_port"], 50099)

    def test_runtime_port_roles_do_not_apply_endpoint_shape_to_callback(self) -> None:
        """Guard the authority split until it has a dedicated typed port plan."""

        import inspect

        from custom_components.eybond_local.runtime.coordinator.strategy import (
            CoordinatorStrategyTransitionMixin,
        )

        source = inspect.getsource(
            CoordinatorStrategyTransitionMixin.async_run_connection_strategy_transition
        )
        self.assertIn("target == CONNECTION_STRATEGY_INBOUND", source)
        self.assertNotIn("callback_listener_port = endpoint_shape.fixed_port", source)
        self.assertIn("listener_port=callback_listener_port", source)
        self.assertIn(
            "if target == CONNECTION_STRATEGY_INBOUND\n                else callback_listener_port",
            source,
        )

    async def test_host_only_same_inbound_bad_metadata_routes_to_verified_correction(self) -> None:
        flow, _calls = self._make_flow(endpoint_shape=self._legacy_host_only_shape())
        flow._config_entry.data.update(
            {
                "connection_strategy": "inbound",
                "advertised_server_ip": "192.168.1.50",
                "advertised_tcp_port": 8899,
                "endpoint_control_policy": "integration_managed",
            }
        )

        result = await flow.async_step_connection(
            {"connection_strategy": "inbound"}
        )

        self.assertEqual(result["type"], "form")
        self.assertEqual(result["step_id"], "strategy_transition")
        self.assertEqual(flow._transition_prefill()["port"], 502)

    async def _drive(self, flow):
        progress = await flow.async_step_strategy_transition_progress()
        self.assertEqual(progress["type"], "progress")
        await flow._transition_task
        done = await flow.async_step_strategy_transition_progress()
        self.assertEqual(done["type"], "progress_done")
        return await flow.async_step_strategy_transition_result()

    # -- CP2A Test C: mandatory risk consent truth table -------------------
    async def test_consent_true_proceeds_to_transition(self) -> None:
        # The exact bool True is consent -> the transition runs.
        flow, calls = self._make_flow()
        submitted = await flow.async_step_strategy_transition(
            {
                "advertised_server_ip": "198.51.100.20",
                "advertised_tcp_port": 19000,
                "collector_ip": "203.0.113.10",
                "confirm_connection_strategy_risk": True,
            }
        )
        self.assertEqual(submitted["type"], "progress")
        await flow._transition_task
        self.assertEqual(len(calls), 1)

    async def test_consent_non_true_values_block_with_zero_side_effects(self) -> None:
        # Only the exact bool True is consent. A missing value, False, a truthy
        # int (1), the string "true", or an arbitrary object is a FORM ERROR
        # with ZERO side effects: no transition call, no transition task, no
        # config-entry writes (and therefore no endpoint write / reboot / UDP).
        _MISSING = object()
        for consent, label in (
            (_MISSING, "missing"),
            (False, "False"),
            (1, "int-1"),
            ("true", "string-true"),
            (object(), "object"),
        ):
            flow, calls = self._make_flow()
            user_input = {
                "advertised_server_ip": "198.51.100.20",
                "advertised_tcp_port": 19000,
                "collector_ip": "203.0.113.10",
            }
            if consent is not _MISSING:
                user_input["confirm_connection_strategy_risk"] = consent
            result = await flow.async_step_strategy_transition(user_input)
            with self.subTest(consent=label):
                self.assertEqual(result["type"], "form")
                self.assertEqual(
                    result["errors"].get("confirm_connection_strategy_risk"),
                    "connection_strategy_risk_unconfirmed",
                )
                self.assertIsNone(flow._transition_task)
                self.assertEqual(calls, [])
                self.assertEqual(flow.hass.config_entries.updates, [])
                self.assertIsNone(
                    getattr(flow, "_transition_confirmed_input", None)
                )

    async def test_consent_checkbox_is_never_persisted_or_forwarded(self) -> None:
        # The checkbox is user intent only: it never lands in the committed
        # data/options and is never forwarded to the transition authority.
        flow, calls = self._make_flow()
        flow._config_entry.options = {"poll_mode": "auto", "control_mode": "manual"}
        submitted = await flow.async_step_strategy_transition(
            {
                "advertised_server_ip": "198.51.100.20",
                "advertised_tcp_port": 19000,
                "collector_ip": "203.0.113.10",
                "confirm_connection_strategy_risk": True,
            }
        )
        self.assertEqual(submitted["type"], "progress")
        await flow._transition_task
        result = await flow.async_step_strategy_transition_result()
        self.assertEqual(result["type"], "create_entry")
        self.assertNotIn("confirm_connection_strategy_risk", result["data"])
        self.assertEqual(len(calls), 1)
        self.assertNotIn(
            "confirm_connection_strategy_risk",
            calls[0].get("option_payload", {}) or {},
        )

    async def test_consent_form_shows_direction_specific_risk_text(self) -> None:
        # Inbound and callback show DIFFERENT risk text under one strict
        # contract, and each mentions its direction-specific danger.
        inbound_flow, _ = self._make_flow()
        inbound_flow._transition_target_strategy = "inbound"
        inbound_form = await inbound_flow.async_step_strategy_transition()
        inbound_note = inbound_form["description_placeholders"]["connection_strategy_risk"]

        callback_flow, _ = self._make_flow()
        callback_flow._transition_target_strategy = "callback_on_demand"
        callback_form = await callback_flow.async_step_strategy_transition()
        callback_note = callback_form["description_placeholders"]["connection_strategy_risk"]

        self.assertNotEqual(inbound_note, callback_note)
        # Inbound names the user-visible effect and reachability requirement
        # without exposing callback/recovery implementation terminology.
        self.assertIn("connect directly", inbound_note)
        self.assertIn("reachable", inbound_note)
        self.assertNotIn("SmartESS", inbound_note)
        self.assertIn("use the cloud again", callback_note)
        self.assertIn("only when it needs data", callback_note)

    # -- CP2B.1 Test F: read-only rollback summary -------------------------
    @staticmethod
    def _rollback_stub(endpoint: str, provenance: str):
        from custom_components.eybond_local.connection.strategy_transition_context import (
            CloudRollbackEndpoint,
        )

        async def _ctx():
            if provenance == "none":
                return CloudRollbackEndpoint.none()
            return CloudRollbackEndpoint(endpoint=endpoint, provenance=provenance)

        return _ctx

    async def _rollback_note(self, *, target: str, endpoint: str, provenance: str) -> str:
        flow, _calls = self._make_flow()
        flow._transition_target_strategy = target
        flow._config_entry.runtime_data.collector_cloud_rollback_context = (
            self._rollback_stub(endpoint, provenance)
        )
        form = await flow.async_step_strategy_transition()
        return form["description_placeholders"]["connection_strategy_rollback"]

    async def test_rollback_summary_known_vs_unknown_differs(self) -> None:
        callback_known = await self._rollback_note(
            target="callback_on_demand",
            endpoint="ess.eybond.com,18899,TCP",
            provenance="original_cloud_endpoint",
        )
        callback_unknown = await self._rollback_note(
            target="callback_on_demand", endpoint="", provenance="none"
        )
        self.assertNotEqual(callback_known, callback_unknown)
        # Known callback summary shows the entry's own endpoint without
        # implementation provenance jargon.
        self.assertIn("ess.eybond.com,18899,TCP", callback_known)
        self.assertNotIn("source:", callback_known)
        self.assertNotIn("will be used", callback_known.lower())
        # Unknown callback summary is honest that no endpoint is guessed.
        self.assertNotIn("ess.eybond.com", callback_unknown)

    async def test_rollback_summary_inbound_vs_callback_wording_differs(self) -> None:
        inbound_known = await self._rollback_note(
            target="inbound",
            endpoint="ess.eybond.com,18899,TCP",
            provenance="original_cloud_endpoint",
        )
        callback_known = await self._rollback_note(
            target="callback_on_demand",
            endpoint="ess.eybond.com,18899,TCP",
            provenance="original_cloud_endpoint",
        )
        self.assertNotEqual(inbound_known, callback_known)
        # Inbound known/unknown wording differs too.
        inbound_unknown = await self._rollback_note(
            target="inbound", endpoint="", provenance="none"
        )
        self.assertNotEqual(inbound_known, inbound_unknown)

    async def test_rollback_summary_is_read_only_never_a_field_or_persisted(self) -> None:
        # The rollback summary is a description placeholder only: it is not a form
        # field, it does not change the submitted payload/transition call, and it
        # is never persisted. A KNOWN context does not alter the confirmed flow.
        flow, calls = self._make_flow()
        flow._transition_target_strategy = "callback_on_demand"
        flow._config_entry.runtime_data.collector_cloud_rollback_context = (
            self._rollback_stub("ess.eybond.com,18899,TCP", "original_cloud_endpoint")
        )
        form = await flow.async_step_strategy_transition()
        # Not an editable field.
        self.assertNotIn("connection_strategy_rollback", form["data_schema"].schema)
        # Submitting is unchanged: consent + addresses proceed, payload untouched.
        submitted = await flow.async_step_strategy_transition(
            {
                "advertised_server_ip": "198.51.100.20",
                "advertised_tcp_port": 19000,
                "collector_ip": "203.0.113.10",
                "confirm_connection_strategy_risk": True,
            }
        )
        self.assertEqual(submitted["type"], "progress")
        await flow._transition_task
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0].get("option_payload"), {"poll_mode": "auto"})
        self.assertNotIn(
            "connection_strategy_rollback", calls[0].get("option_payload", {}) or {}
        )

    # -- CP2B.2 Test B: the cloud rollback chooser -------------------------
    def _make_chooser_flow(self, *, candidate_endpoint=None, provenance="original_cloud_endpoint"):
        from custom_components.eybond_local.connection.strategy_transition_context import (
            CloudRollbackEndpoint,
        )

        flow, calls = self._make_flow()
        flow._config_entry.data = dict(flow._config_entry.data)
        # An integration-managed callback restore requires the chooser.
        flow._config_entry.data["endpoint_control_policy"] = "integration_managed"

        async def _ctx():
            if candidate_endpoint is None:
                return CloudRollbackEndpoint.none()
            return CloudRollbackEndpoint(candidate_endpoint, provenance)

        flow._config_entry.runtime_data.collector_cloud_rollback_context = _ctx
        flow._transition_target_strategy = "callback_on_demand"
        return flow, calls

    def _catalog_option(self):
        from custom_components.eybond_local.collector.cloud_rollback_catalog import (
            writable_cloud_rollback_catalog_options,
        )

        return writable_cloud_rollback_catalog_options()[0]

    async def _reach_chooser(self, flow):
        return await flow.async_step_strategy_transition(
            {
                "advertised_server_ip": "198.51.100.20",
                "advertised_tcp_port": 19000,
                "collector_ip": "203.0.113.10",
                "confirm_connection_strategy_risk": True,
            }
        )

    async def test_external_policy_skips_chooser(self) -> None:
        # The default fake entry is external -> the chooser is skipped and the
        # transition proceeds directly with no rollback selection.
        flow, calls = self._make_flow()
        submitted = await self._reach_chooser(flow)
        self.assertEqual(submitted["type"], "progress")
        self.assertIsNone(flow._transition_rollback_selection)
        await flow._transition_task
        self.assertIsNone(calls[0].get("cloud_rollback_selection"))

    async def test_integration_managed_routes_to_chooser(self) -> None:
        flow, _calls = self._make_chooser_flow(candidate_endpoint="ess.eybond.com,18899,TCP")
        form = await self._reach_chooser(flow)
        self.assertEqual(form["type"], "form")
        self.assertEqual(form["step_id"], "strategy_transition_rollback")
        self.assertIsNone(flow._transition_task)  # no transition started yet

    async def test_chooser_shows_known_candidate(self) -> None:
        # A known candidate is surfaced (endpoint shown) AND selectable; the
        # confirmed option builds a confirmed-candidate selection.
        flow, _calls = self._make_chooser_flow(candidate_endpoint="ess.eybond.com,18899,TCP")
        flow._transition_confirmed_input = {"host": "198.51.100.20", "port": 19000, "collector_ip": "203.0.113.10"}
        form = await flow.async_step_strategy_transition_rollback()
        self.assertEqual(form["step_id"], "strategy_transition_rollback")
        self.assertEqual(
            form["description_placeholders"]["candidate_endpoint"],
            "ess.eybond.com,18899,TCP",
        )
        self.assertIn("rollback_endpoint", form["data_schema"].schema)
        self.assertNotIn("rollback_manual_endpoint", form["data_schema"].schema)

    async def test_chooser_no_candidate_offers_catalog_and_manual(self) -> None:
        # With no candidate, the confirmed option is not accepted, but catalog and
        # manual choices are, and no endpoint is guessed.
        flow, _calls = self._make_chooser_flow(candidate_endpoint=None)
        flow._transition_confirmed_input = {"host": "1.2.3.4", "port": 19000, "collector_ip": "203.0.113.10"}
        form = await flow.async_step_strategy_transition_rollback()
        self.assertEqual(form["step_id"], "strategy_transition_rollback")
        self.assertEqual(form["description_placeholders"]["candidate_endpoint"], "")
        self.assertIn("rollback_endpoint", form["data_schema"].schema)

    async def _submit_chooser(self, flow, endpoint):
        flow._transition_confirmed_input = {"host": "198.51.100.20", "port": 19000, "collector_ip": "203.0.113.10"}
        return await flow.async_step_strategy_transition_rollback(
            {"rollback_endpoint": endpoint}
        )

    async def test_chooser_confirmed_builds_selection_and_is_single_authority(self) -> None:
        flow, calls = self._make_chooser_flow(candidate_endpoint="ess.eybond.com,18899,TCP")
        result = await self._submit_chooser(flow, "ess.eybond.com,18899,TCP")
        self.assertEqual(result["type"], "progress")
        selection = flow._transition_rollback_selection
        self.assertEqual(selection.selection_kind, "confirmed_candidate")
        self.assertEqual(selection.endpoint_value, "ess.eybond.com,18899,TCP")
        await flow._transition_task
        # NAT separation + single authority: the advertised HA route and the cloud
        # rollback endpoint travel as SEPARATE args, never substituted.
        self.assertEqual(calls[0]["advertised_host"], "198.51.100.20")
        self.assertEqual(calls[0]["advertised_port"], 19000)
        self.assertEqual(calls[0]["callback_target_ip"], "203.0.113.10")
        self.assertIs(calls[0]["cloud_rollback_selection"], selection)
        self.assertNotEqual(
            calls[0]["cloud_rollback_selection"].endpoint_value, calls[0]["advertised_host"]
        )

    async def test_chooser_catalog_builds_selection(self) -> None:
        flow, calls = self._make_chooser_flow(candidate_endpoint=None)
        option = self._catalog_option()
        result = await self._submit_chooser(flow, option.endpoint)
        self.assertEqual(result["type"], "progress")
        self.assertEqual(flow._transition_rollback_selection.selection_kind, "catalog")
        self.assertEqual(
            flow._transition_rollback_selection.catalog_profile_key,
            option.key,
        )

    async def test_chooser_manual_valid_builds_selection(self) -> None:
        flow, _calls = self._make_chooser_flow(candidate_endpoint=None)
        result = await self._submit_chooser(flow, "my.cloud,18899,TCP")
        self.assertEqual(result["type"], "progress")
        self.assertEqual(flow._transition_rollback_selection.selection_kind, "manual")
        self.assertEqual(flow._transition_rollback_selection.endpoint_value, "my.cloud,18899,TCP")

    async def test_chooser_manual_malformed_is_form_error(self) -> None:
        flow, calls = self._make_chooser_flow(candidate_endpoint=None)
        result = await self._submit_chooser(flow, "bad###ep")
        self.assertEqual(result["type"], "form")
        self.assertEqual(
            result["errors"].get("rollback_endpoint"),
            "rollback_endpoint_invalid",
        )
        self.assertIsNone(flow._transition_rollback_selection)
        self.assertIsNone(flow._transition_task)
        self.assertEqual(calls, [])

    async def test_chooser_stale_catalog_key_is_form_error(self) -> None:
        flow, calls = self._make_chooser_flow(candidate_endpoint=None)
        result = await self._submit_chooser(flow, "___removed_key___")
        self.assertEqual(result["type"], "form")
        self.assertEqual(
            result["errors"].get("rollback_endpoint"),
            "rollback_endpoint_invalid",
        )
        self.assertIsNone(flow._transition_rollback_selection)
        self.assertEqual(calls, [])

    async def test_chooser_typed_value_without_candidate_is_manual(self) -> None:
        flow, _calls = self._make_chooser_flow(candidate_endpoint=None)
        result = await self._submit_chooser(flow, "ess.eybond.com,18899,TCP")
        # Without a trusted saved candidate, the same syntactically valid value
        # is treated as an explicit manual endpoint, never as confirmed evidence.
        self.assertEqual(result["type"], "progress")
        self.assertEqual(
            flow._transition_rollback_selection.selection_kind,
            "manual",
        )

    async def test_chooser_submit_uses_the_candidate_that_was_shown(self) -> None:
        from custom_components.eybond_local.connection.strategy_transition_context import (
            CLOUD_PROVENANCE_ORIGINAL,
            CloudRollbackEndpoint,
        )

        flow, _calls = self._make_chooser_flow(candidate_endpoint=None)
        shown = CloudRollbackEndpoint(
            "shown.example,18899,TCP", CLOUD_PROVENANCE_ORIGINAL
        )
        changed = CloudRollbackEndpoint(
            "changed.example,18899,TCP", CLOUD_PROVENANCE_ORIGINAL
        )
        reads = 0

        async def _changing_context():
            nonlocal reads
            reads += 1
            return shown if reads == 1 else changed

        flow._config_entry.runtime_data.collector_cloud_rollback_context = (
            _changing_context
        )
        form = await flow.async_step_strategy_transition_rollback()
        self.assertEqual(form["description_placeholders"]["candidate_endpoint"], shown.endpoint)
        result = await self._submit_chooser(flow, shown.endpoint)
        self.assertEqual(result["type"], "progress")
        self.assertEqual(
            flow._transition_rollback_selection.endpoint_value, shown.endpoint
        )
        self.assertEqual(reads, 1)

    async def test_confirm_form_requires_explicit_addresses(self) -> None:
        flow, _calls = self._make_flow()
        form = await flow.async_step_strategy_transition()
        self.assertEqual(form["type"], "form")
        self.assertEqual(form["step_id"], "strategy_transition")
        # The callback direction demands the collector target too.
        missing = await flow.async_step_strategy_transition(
            {
                "advertised_server_ip": "",
                "advertised_tcp_port": 8899,
                "collector_ip": "",
            }
        )
        self.assertEqual(missing["type"], "form")
        self.assertIn("advertised_server_ip", missing["errors"])
        self.assertIn("collector_ip", missing["errors"])

    async def test_form_rejects_malformed_host_and_port_without_exception(self) -> None:
        # No coercion: a non-string / wildcard / padded host and a non-numeric
        # port are FORM ERRORS -- never a 500, never a started transition.
        flow, _calls = self._make_flow()
        for bad_host in (object(), "0.0.0.0", " 203.0.113.9 ", 12345):
            result = await flow.async_step_strategy_transition(
                {
                    "advertised_server_ip": bad_host,
                    "advertised_tcp_port": 8899,
                    "collector_ip": "203.0.113.10",
                }
            )
            self.assertEqual(result["type"], "form")
            self.assertEqual(
                result["errors"].get("advertised_server_ip"),
                "invalid_selection",
                msg=f"host {bad_host!r}",
            )
            self.assertIsNone(flow._transition_task)
        # A non-numeric port is a form error too (the free text field is safe).
        result = await flow.async_step_strategy_transition(
            {
                "advertised_server_ip": "203.0.113.9",
                "advertised_tcp_port": "abc",
                "collector_ip": "203.0.113.10",
            }
        )
        self.assertEqual(result["type"], "form")
        self.assertEqual(result["errors"].get("advertised_tcp_port"), "invalid_selection")
        # An empty host is 'required', not 'invalid_selection'.
        result = await flow.async_step_strategy_transition(
            {"advertised_server_ip": "", "advertised_tcp_port": 8899, "collector_ip": "x"}
        )
        self.assertEqual(result["errors"].get("advertised_server_ip"), "required")

    async def test_success_returns_full_committed_options_and_verbatim_addresses(
        self,
    ) -> None:
        flow, calls = self._make_flow()
        # The COMPLETE options the authority already committed (unrelated keys
        # included), which HA now holds post-commit.
        flow._config_entry.options = {
            "poll_mode": "auto",
            "control_mode": "manual",
            "collector_original_server_endpoint": "dtu_ess.eybond.com,18899,TCP",
        }
        submitted = await flow.async_step_strategy_transition(
            {
                # A PUBLIC NAT address: travels verbatim, never localized.
                "advertised_server_ip": "198.51.100.20",
                "advertised_tcp_port": 19000,
                "collector_ip": "203.0.113.10",
                "confirm_connection_strategy_risk": True,
            }
        )
        self.assertEqual(submitted["type"], "progress")
        await flow._transition_task
        done = await flow.async_step_strategy_transition_progress()
        self.assertEqual(done["type"], "progress_done")
        result = await flow.async_step_strategy_transition_result()
        self.assertEqual(result["type"], "create_entry")
        # §5/§H: the terminal writes the COMPLETE stored options (not the staged
        # poll/control subset) -- unrelated options are preserved and there is no
        # second semantic reload.
        self.assertEqual(
            result["data"],
            {
                "poll_mode": "auto",
                "control_mode": "manual",
                "collector_original_server_endpoint": "dtu_ess.eybond.com,18899,TCP",
            },
        )
        self.assertEqual(len(calls), 1)
        call = calls[0]
        self.assertEqual(call["target_strategy"], "callback_on_demand")
        self.assertEqual(call["callback_target_ip"], "203.0.113.10")
        self.assertEqual(call["advertised_host"], "198.51.100.20")
        self.assertEqual(call["advertised_port"], 19000)
        # The authority still receives ONLY the staged orthogonal options payload.
        self.assertEqual(call["option_payload"], {"poll_mode": "auto"})
        # The options flow itself persisted NOTHING (the authority commits).
        self.assertEqual(flow.hass.config_entries.updates, [])

    async def test_inbound_direction_formats_confirmed_endpoint(self) -> None:
        flow, calls = self._make_flow()
        flow._transition_target_strategy = "inbound"
        submitted = await flow.async_step_strategy_transition(
            {
                "advertised_server_ip": "198.51.100.20",
                "advertised_tcp_port": 19000,
                "confirm_connection_strategy_risk": True,
            }
        )
        self.assertEqual(submitted["type"], "progress")
        await flow._transition_task
        await flow.async_step_strategy_transition_progress()
        result = await flow.async_step_strategy_transition_result()
        self.assertEqual(result["type"], "create_entry")
        self.assertEqual(calls[0]["target_strategy"], "inbound")
        self.assertEqual(calls[0]["inbound_endpoint"], "198.51.100.20:19000")

    async def test_bridge_endpoint_submit_reuses_inbound_transition_authority(self) -> None:
        flow, calls = self._make_flow()
        flow._config_entry.data.update(
            {
                "collector_kind": COLLECTOR_KIND_ESP_EYBOND_BRIDGE,
                "collector_virtual_bridge": True,
                "collector_hardware_version": "esp-collector/0.1.10/ESP8266",
                CONF_CONNECTION_STRATEGY: CONNECTION_STRATEGY_INBOUND,
            }
        )

        form = await flow.async_step_collector_endpoint()
        self.assertEqual(form["step_id"], "strategy_transition")
        submitted = await flow.async_step_strategy_transition(
            {
                "advertised_server_ip": "198.51.100.25",
                "advertised_tcp_port": 19001,
                "confirm_connection_strategy_risk": True,
            }
        )
        self.assertEqual(submitted["type"], "progress")
        await flow._transition_task

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["target_strategy"], CONNECTION_STRATEGY_INBOUND)
        self.assertEqual(calls[0]["inbound_endpoint"], "198.51.100.25:19001")
        self.assertNotIn("callback_target_ip", calls[0])
        self.assertNotIn("cloud_rollback_selection", calls[0])

    async def test_failure_shows_localized_menu_and_keeps_strategy(self) -> None:
        from custom_components.eybond_local.connection.strategy_transition import (
            StrategyTransitionResult,
        )

        flow, _calls = self._make_flow(
            transition_result=StrategyTransitionResult(
                success=False,
                target_strategy="callback_on_demand",
                failure_reason="transition_rollback_endpoint_unavailable",
            )
        )
        await flow.async_step_strategy_transition(
            {
                "advertised_server_ip": "198.51.100.20",
                "advertised_tcp_port": 19000,
                "collector_ip": "203.0.113.10",
                "confirm_connection_strategy_risk": True,
            }
        )
        await flow._transition_task
        await flow.async_step_strategy_transition_progress()
        result = await flow.async_step_strategy_transition_result()
        self.assertEqual(result["type"], "menu")
        self.assertEqual(result["step_id"], "strategy_transition_failed")
        self.assertEqual(
            result["menu_options"],
            [
                "strategy_transition",
                "strategy_transition_keep_settings",
                "strategy_transition_cancel",
            ],
        )
        explanation = result["description_placeholders"]["failure_explanation"]
        self.assertNotIn("transition_rollback_endpoint_unavailable", explanation)
        self.assertNotIn("`", explanation)
        self.assertGreater(len(explanation), 20)
        # Nothing was persisted by the flow on failure.
        self.assertEqual(flow.hass.config_entries.updates, [])

    async def test_keep_settings_saves_options_without_strategy(self) -> None:
        flow, _calls = self._make_flow()
        flow._transition_error = "transition_session_unavailable"
        result = await flow.async_step_strategy_transition_keep_settings()
        self.assertEqual(result["type"], "create_entry")
        self.assertEqual(result["data"], {"poll_mode": "auto"})
        updates = flow.hass.config_entries.updates
        self.assertEqual(len(updates), 1)
        self.assertNotIn("data", updates[0])
        self.assertEqual(updates[0]["options"], {"poll_mode": "auto"})
        self.assertEqual(flow._config_entry.data["connection_strategy"], "inbound")

    async def test_cancel_leaves_everything_untouched(self) -> None:
        flow, _calls = self._make_flow()
        flow._transition_error = "transition_session_unavailable"
        result = await flow.async_step_strategy_transition_cancel()
        self.assertEqual(result["type"], "create_entry")
        self.assertEqual(flow.hass.config_entries.updates, [])
        self.assertEqual(flow._config_entry.data["connection_strategy"], "inbound")

    async def test_runtime_unavailable_is_typed(self) -> None:
        flow, _calls = self._make_flow()
        flow._config_entry.runtime_data = None
        flow._transition_confirmed_input = {
            "host": "198.51.100.20",
            "port": 19000,
            "collector_ip": "203.0.113.10",
        }
        await flow._async_run_strategy_transition_task()
        self.assertEqual(flow._transition_error, "transition_runtime_unavailable")



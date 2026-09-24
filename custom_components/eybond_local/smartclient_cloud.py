"""Bounded, passive SmartClient/ShineMonitor API acquisition.

The PV auth/source profile is independent of SmartESS and DESSMonitor. No
control, collector command, protocol download or cross-cloud login is allowed.
Wire shapes follow SmartClient 3.48.8.0 and the vendor's generic device API.
"""

from __future__ import annotations

import base64
import hashlib
import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .cloud_signing import password_signature, session_signature
from .collector_identity import pn_is_same_identity

DEFAULT_BASE_URL = "https://android.shinemonitor.com/public/"
OVERSEAS_BASE_URL = "https://android1.shinemonitor.com/public/"
DEFAULT_APP_ID = "com.eybond.smartclient"
DEFAULT_APP_VERSION = "3.48.8.0"
DEFAULT_COMPANY_KEY = "bnrl_frRFjEz8Mkn"
DEFAULT_LANGUAGE = "en_US"
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_RAW_BYTES = 64 * 1024
MAX_FIELDS = 512
MAX_HISTORY_ROWS = 4096
PASSIVE_ACTIONS = frozenset(
    {
        "queryCollectorDevices",
        "webQueryCollectorInfo",
        "queryDeviceInfo",
        "queryDeviceLastData",
        "queryDeviceDataOneDay",
        "queryDeviceCtrlField",
        "queryDeviceLastRawData",
    }
)
_DEVICE_PARAMETERS = frozenset({"pn", "sn", "devcode", "devaddr"})


class SmartClientCloudError(RuntimeError):
    """Sanitized error: no URL, provider text, password or session material."""

    def __init__(self, reason: str, *, stage: str = "", code: int | None = None):
        self.reason_code = reason
        self.stage = stage
        self.code = code
        super().__init__(reason)


@dataclass(frozen=True, slots=True)
class SmartClientSession:
    token: str = field(repr=False)
    secret: str = field(repr=False)
    base_url: str = DEFAULT_BASE_URL

    def __post_init__(self) -> None:
        _required(self.token)
        _required(self.secret)
        _base_url(self.base_url)


@dataclass(frozen=True, slots=True)
class SmartClientIdentity:
    pn: str
    sn: str
    devcode: int
    devaddr: int

    def __post_init__(self) -> None:
        _required(self.pn)
        _required(self.sn)
        if type(self.devcode) is not int or not 0 <= self.devcode <= 65535:
            raise SmartClientCloudError("identity_invalid")
        if type(self.devaddr) is not int or not 0 <= self.devaddr <= 255:
            raise SmartClientCloudError("identity_invalid")

    def to_record(self) -> dict[str, Any]:
        return {
            "pn": self.pn,
            "sn": self.sn,
            "devcode": self.devcode,
            "devaddr": self.devaddr,
        }


@dataclass(frozen=True, slots=True)
class SmartClientEvidence:
    identity: SmartClientIdentity
    telemetry: tuple[dict[str, str], ...]
    controls: tuple[dict[str, Any], ...]
    device_info: dict[str, Any]
    history: dict[str, Any]
    raw_packet: dict[str, Any]
    unavailable_actions: tuple[str, ...]
    action_errors: tuple[tuple[str, str], ...]
    fetched_at: str

    def to_record(self) -> dict[str, Any]:
        return {
            "source": "smartclient",
            "provider": "smartess",
            "identity": self.identity.to_record(),
            "telemetry_fields": list(self.telemetry),
            "control_fields": list(self.controls),
            "device_info": dict(self.device_info),
            "daily_data": dict(self.history),
            "raw_packet": dict(self.raw_packet),
            "unavailable_actions": list(self.unavailable_actions),
            "action_errors": dict(self.action_errors),
            "fetched_at": self.fetched_at,
            "metadata_field_count": len(self.telemetry) + len(self.controls),
        }


def _required(value: object) -> str:
    if (
        type(value) is not str
        or not value
        or value != value.strip()
        or len(value) > 512
    ):
        raise SmartClientCloudError("parameter_invalid")
    return value


def _text(value: object) -> str:
    if type(value) not in {str, int, float}:
        return ""
    return str(value).strip()[:512]


def _base_url(value: str) -> str:
    if value not in {DEFAULT_BASE_URL, OVERSEAS_BASE_URL}:
        raise SmartClientCloudError("server_invalid")
    return value


def _action(name: str, params: tuple[tuple[str, object], ...] = ()) -> str:
    return (
        "&action="
        + name
        + "".join(f"&{key}={quote(str(value), safe='')}" for key, value in params)
    )


def build_login_url(
    *, username: str, password: str, base_url: str = DEFAULT_BASE_URL
) -> str:
    _required(username)
    if type(password) is not str or not password or len(password) > 512:
        raise SmartClientCloudError("parameter_invalid")
    # Native APK login signs auth only; source=0 belongs to business requests.
    action = _action("auth", (("usr", username), ("company-key", DEFAULT_COMPANY_KEY)))
    salt = str(int(time.time() * 1000))
    sign = password_signature(salt, password, action)
    return f"{_base_url(base_url)}?sign={sign}&salt={salt}{action}"


def build_signed_action_url(
    *,
    name: str,
    session: SmartClientSession,
    parameters: tuple[tuple[str, object], ...] = (),
) -> str:
    if name not in PASSIVE_ACTIONS:
        raise SmartClientCloudError("action_forbidden")
    if type(session) is not SmartClientSession:
        raise SmartClientCloudError("session_invalid")
    allowed = (
        _DEVICE_PARAMETERS | {"date"}
        if name == "queryDeviceDataOneDay"
        else {"pn"}
        if name in {"queryCollectorDevices", "webQueryCollectorInfo"}
        else {"device"}
        if name == "queryDeviceInfo"
        else _DEVICE_PARAMETERS
    )
    if len({key for key, _ in parameters}) != len(parameters) or any(
        key not in allowed or type(value) not in {str, int} for key, value in parameters
    ):
        raise SmartClientCloudError("parameter_invalid")
    action = _action(name, parameters) + (
        f"&i18n={DEFAULT_LANGUAGE}&lang={DEFAULT_LANGUAGE}&source=0"
        f"&_app_client_=android&_app_id_={DEFAULT_APP_ID}&_app_version_={DEFAULT_APP_VERSION}"
    )
    salt = str(int(time.time() * 1000))
    sign = session_signature(salt, session.secret, session.token, action)
    return f"{session.base_url}?sign={sign}&salt={salt}&token={quote(session.token, safe='')}{action}"


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Signed query strings must not be forwarded to a redirected authority.
        return None


def _http_get_json(url: str, *, timeout: float) -> dict[str, Any]:
    try:
        request = Request(
            url, headers={"Accept": "application/json", "Accept-Encoding": "identity"}
        )
        with build_opener(_NoRedirect()).open(request, timeout=timeout) as response:
            body = response.read(MAX_RESPONSE_BYTES + 1)
        if len(body) > MAX_RESPONSE_BYTES:
            raise SmartClientCloudError("response_too_large")
        result = json.loads(body)
    except HTTPError as exc:
        reason = (
            "auth_failed"
            if exc.code in {401, 403}
            else ("rate_limited" if exc.code == 429 else "http_error")
        )
        raise SmartClientCloudError(reason, code=exc.code) from None
    except (TimeoutError, URLError) as exc:
        reason = (
            "timeout"
            if isinstance(exc, TimeoutError)
            or isinstance(getattr(exc, "reason", None), TimeoutError)
            else "network"
        )
        raise SmartClientCloudError(reason) from None
    except (ValueError, UnicodeError):
        raise SmartClientCloudError("invalid_response") from None
    if type(result) is not dict or type(result.get("err")) is not int:
        raise SmartClientCloudError("invalid_response")
    if result["err"] != 0:
        raise SmartClientCloudError("api_rejected", code=result["err"])
    return result


def _identity(data: object, expected_pn: str) -> SmartClientIdentity:
    if type(data) is not dict or not pn_is_same_identity(
        expected_pn, _text(data.get("pn"))
    ):
        raise SmartClientCloudError("identity_mismatch")
    devices = data.get("dev")
    if type(devices) is not list or not devices:
        raise SmartClientCloudError("device_unavailable")
    identities: set[SmartClientIdentity] = set()
    for item in devices:
        if type(item) is not dict:
            raise SmartClientCloudError("identity_invalid")
        identities.add(
            SmartClientIdentity(
                pn=_required(data["pn"]),
                sn=_required(item.get("sn")),
                devcode=item.get("devcode"),
                devaddr=item.get("devaddr"),
            )
        )
    if len(identities) != 1:
        raise SmartClientCloudError("identity_ambiguous")
    return identities.pop()


def _telemetry(data: object) -> tuple[dict[str, str], ...]:
    if type(data) is not list:
        raise SmartClientCloudError("invalid_telemetry")
    fields = []
    for index, item in enumerate(data[:MAX_FIELDS]):
        if type(item) is not dict:
            raise SmartClientCloudError("invalid_telemetry")
        title = _text(item.get("title"))
        if title:
            fields.append(
                {
                    "field_id": str(index),
                    "title": title,
                    "value": _text(item.get("val")),
                    "unit": _text(item.get("unit")),
                }
            )
    return tuple(fields)


def _controls(data: object) -> tuple[dict[str, Any], ...]:
    if type(data) is not dict or type(data.get("field")) is not list:
        raise SmartClientCloudError("invalid_controls")
    fields = []
    for item in data["field"][:MAX_FIELDS]:
        if (
            type(item) is not dict
            or not _text(item.get("id"))
            or not _text(item.get("name"))
        ):
            raise SmartClientCloudError("invalid_controls")
        choices = item.get("item", [])
        if type(choices) is not list:
            raise SmartClientCloudError("invalid_controls")
        fields.append(
            {
                "field_id": _text(item["id"]),
                "title": _text(item["name"]),
                "unit": _text(item.get("unit")),
                "hint": _text(item.get("hint")),
                "choices": [
                    {
                        "value": _text(choice.get("key")),
                        "label": _text(choice.get("val")),
                    }
                    for choice in choices[:256]
                    if type(choice) is dict
                ],
            }
        )
    return tuple(fields)


def _device_info(data: object, identity: SmartClientIdentity) -> dict[str, Any]:
    # The native SmartClient APK reads dat as an array. Keep the older object
    # envelope too, but never copy the APK's unverified first-row selection.
    rows = data.get("device") if type(data) is dict else data
    if type(rows) is not list:
        raise SmartClientCloudError("invalid_device_info")
    matches = []
    for item in rows:
        if type(item) is not dict:
            continue
        if (
            pn_is_same_identity(identity.pn, _text(item.get("pn")))
            and item.get("sn") == identity.sn
            and type(item.get("devcode")) is int
            and item["devcode"] == identity.devcode
            and type(item.get("devaddr")) is int
            and item["devaddr"] == identity.devaddr
        ):
            matches.append(item)
    if len(matches) != 1:
        raise SmartClientCloudError("identity_mismatch")
    item = matches[0]
    result = {
        key: _text(item[key])
        for key in ("alias", "status", "model", "firmware")
        if key in item
    }
    offset = item.get("timezone")
    if type(offset) is int and -43200 <= offset <= 50400:
        result["timezone"] = offset
    return result


def _collector_time_basis(data: object, identity: SmartClientIdentity) -> dict[str, Any]:
    """Read only the timezone of this collector, not its other settings."""

    if type(data) is not dict:
        raise SmartClientCloudError("invalid_collector_info")
    if not pn_is_same_identity(identity.pn, _text(data.get("pn"))):
        raise SmartClientCloudError("identity_mismatch")
    offset = data.get("timezone")
    if type(offset) is not int or not -43200 <= offset <= 50400:
        raise SmartClientCloudError("time_basis_unavailable")
    return {"timezone": offset, "timezone_source": "webQueryCollectorInfo"}


def _history(data: object, requested_date: str) -> dict[str, Any]:
    if (
        type(data) is not dict
        or type(data.get("title")) is not list
        or type(data.get("row")) is not list
    ):
        raise SmartClientCloudError("invalid_history")
    headers = data["title"]
    if not 2 <= len(headers) <= MAX_FIELDS or any(
        type(item) is not dict for item in headers
    ):
        raise SmartClientCloudError("invalid_history")
    titles = [
        {"title": _text(item.get("title")), "unit": _text(item.get("unit"))}
        for item in headers
    ]
    rows = []
    for row in data["row"][:MAX_HISTORY_ROWS]:
        if (
            type(row) is not dict
            or type(row.get("field")) is not list
            or len(row["field"]) != len(titles)
        ):
            raise SmartClientCloudError("invalid_history")
        rows.append(
            {
                "field": [_text(value) for value in row["field"]],
                "realtime": row.get("realtime") is True,
            }
        )
    return {
        "requested_date": requested_date,
        "title": titles,
        "row": rows,
        "truncated": len(data["row"]) > MAX_HISTORY_ROWS,
    }


def _raw_packet(data: object) -> dict[str, Any]:
    if type(data) is not dict or type(data.get("dat")) is not str:
        raise SmartClientCloudError("invalid_raw_packet")
    encoded = data["dat"]
    if len(encoded) > (MAX_RAW_BYTES + 2) // 3 * 4:
        raise SmartClientCloudError("raw_packet_too_large")
    try:
        raw = base64.b64decode(encoded, validate=True)
    except ValueError:
        raise SmartClientCloudError("invalid_raw_packet") from None
    if len(raw) > MAX_RAW_BYTES:
        raise SmartClientCloudError("raw_packet_too_large")
    return {
        # Unknown binary layouts can embed identities which archive redaction
        # cannot locate. Retain a fingerprint, not an unmasked Base64 payload.
        "payload_omitted": True,
        "length": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "timestamp": _text(data.get("gts")),
        "id": _text(data.get("id")),
        # The vendor's flag is an integer, not a Python truth value.
        "valid": data.get("valid") if type(data.get("valid")) is int else None,
    }


def fetch_read_only_evidence(
    *,
    username: str,
    password: str,
    collector_pn: str,
    base_url: str = DEFAULT_BASE_URL,
    timeout: float = 15.0,
    total_timeout: float = 75.0,
    progress: Callable[[str], None] | None = None,
) -> SmartClientEvidence:
    """Read one exact collector's cloud evidence; never operate the collector."""

    _required(collector_pn)
    if (
        type(timeout) not in {int, float}
        or type(total_timeout) not in {int, float}
        or not 0 < timeout <= 30
        or not 0 < total_timeout <= 120
    ):
        raise SmartClientCloudError("timeout_invalid")
    deadline = time.monotonic() + total_timeout

    def get(url: str, stage: str) -> Any:
        if progress:
            progress(stage)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise SmartClientCloudError("timeout", stage=stage)
        try:
            return _http_get_json(url, timeout=min(timeout, remaining)).get("dat")
        except SmartClientCloudError as exc:
            raise SmartClientCloudError(
                exc.reason_code, stage=stage, code=exc.code
            ) from None

    login = get(
        build_login_url(username=username, password=password, base_url=base_url), "auth"
    )
    if type(login) is not dict:
        raise SmartClientCloudError("session_invalid", stage="auth")
    session = SmartClientSession(
        token=login.get("token"), secret=login.get("secret"), base_url=base_url
    )

    def query(name: str, parameters: tuple[tuple[str, object], ...]) -> Any:
        return get(
            build_signed_action_url(name=name, session=session, parameters=parameters),
            name,
        )

    identity = _identity(
        query("queryCollectorDevices", (("pn", collector_pn),)), collector_pn
    )
    params = tuple(identity.to_record().items())
    unavailable: list[str] = []
    errors: list[tuple[str, str]] = []

    def optional(name: str, parameters, parse, empty):
        try:
            return parse(query(name, parameters))
        except SmartClientCloudError as exc:
            # A revoked session or changed ownership must not become partial success.
            if exc.code in {10, 11, 257, 258} or exc.reason_code in {
                "auth_failed",
                "identity_mismatch",
            }:
                raise
            unavailable.append(name)
            errors.append((name, exc.reason_code))
            return empty

    info = optional(
        "queryDeviceInfo",
        (
            (
                "device",
                f"{identity.pn},{identity.devcode},{identity.devaddr},{identity.sn}",
            ),
        ),
        lambda data: _device_info(data, identity),
        {},
    )
    if "timezone" not in info:
        info.update(
            optional(
                "webQueryCollectorInfo",
                (("pn", identity.pn),),
                lambda data: _collector_time_basis(data, identity),
                {},
            )
        )
    telemetry = optional("queryDeviceLastData", params, _telemetry, ())
    controls = optional("queryDeviceCtrlField", params, _controls, ())
    raw = optional("queryDeviceLastRawData", params, _raw_packet, {})
    # Ask for the device's current date, never substitute the HA host timezone.
    offset = info.get("timezone")
    requested_date = (
        datetime.now(timezone(timedelta(seconds=offset))).date().isoformat()
        if type(offset) is int
        else ""
    )
    history_params = params + ((("date", requested_date),) if requested_date else ())
    history = optional(
        "queryDeviceDataOneDay",
        history_params,
        lambda data: _history(data, requested_date),
        {},
    )
    readings = any(item["field_id"] not in {"0", "1"} for item in telemetry)
    if (
        not readings
        and not controls
        and not raw.get("length")
        and not history.get("row")
    ):
        for reason in ("timeout", "network", "rate_limited"):
            failed_stage = next(
                (stage for stage, error in errors if error == reason), ""
            )
            if failed_stage:
                raise SmartClientCloudError(reason, stage=failed_stage)
        raise SmartClientCloudError("device_data_unavailable")
    return SmartClientEvidence(
        identity,
        telemetry,
        controls,
        info,
        history,
        raw,
        tuple(unavailable),
        tuple(errors),
        datetime.now(timezone.utc).isoformat(),
    )

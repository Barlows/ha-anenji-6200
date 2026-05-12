"""Shared collector signal normalization helpers."""

from __future__ import annotations

import re

from .cloud_family import COLLECTOR_CLOUD_FAMILY_LEGACY_BINARY


COLLECTOR_SIGNAL_ENTITY_KEYS = frozenset(
    {
        "collector_signal_quality",
        "collector_signal_strength",
    }
)


def is_legacy_disabled_signal_entity_key(key: str, cloud_family: object) -> bool:
    """Return whether one collector signal entity should be hidden for legacy collectors."""

    if key not in COLLECTOR_SIGNAL_ENTITY_KEYS:
        return False
    family = str(cloud_family or "").strip().lower()
    return family == COLLECTOR_CLOUD_FAMILY_LEGACY_BINARY


def extract_signal_strength(value: str) -> int | None:
    """Extract one integer signal value from arbitrary collector text."""

    match = re.search(r"(-?\d+)", str(value or ""))
    if match is None:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


def normalize_signal_strength(value: str, *, source: str) -> tuple[int | None, str]:
    """Normalize one collector signal value into dBm when possible."""

    text = str(value or "").strip()
    normalized = text.upper()

    if source == "wifi_rssi":
        looks_like_rssi = (
            normalized.startswith("STA:")
            or normalized.startswith("RSSI:")
            or normalized.startswith("AT+WFSS:")
            or re.fullmatch(r"-\d{1,3}", text) is not None
        )
        if not looks_like_rssi:
            return (None, source)

    raw_strength = extract_signal_strength(value)
    if raw_strength is None:
        return (None, source)
    if source == "gprs_csq":
        if raw_strength == 99:
            return (None, source)
        if 0 <= raw_strength <= 31:
            return (-113 + (2 * raw_strength), source)
    return (raw_strength, source)


def signal_source_priority(source: object) -> int:
    """Return a stable source priority for signal value merges."""

    normalized = str(source or "").strip().lower()
    if normalized == "wifi_rssi":
        return 2
    if normalized == "gprs_csq":
        return 1
    return 0


def merge_collector_signal_values(
    current_values: dict[str, object],
    decoded_values: dict[str, object],
) -> None:
    """Merge decoded collector values while preferring better signal sources."""

    signal_strength = decoded_values.pop("collector_signal_strength", None)
    signal_source = decoded_values.pop("collector_signal_strength_source", None)
    current_values.update(decoded_values)

    if signal_strength is None:
        return

    if "collector_signal_strength" not in current_values:
        current_values["collector_signal_strength"] = signal_strength
        if signal_source:
            current_values["collector_signal_strength_source"] = signal_source
        return

    if signal_source_priority(signal_source) >= signal_source_priority(
        current_values.get("collector_signal_strength_source")
    ):
        current_values["collector_signal_strength"] = signal_strength
        if signal_source:
            current_values["collector_signal_strength_source"] = signal_source

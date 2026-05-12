"""Helpers for entity-platform setup before the first runtime snapshot is ready."""

from __future__ import annotations

from typing import Any

from .const import (
    CONF_DETECTED_MODEL,
    CONF_DETECTED_SERIAL,
    CONF_DRIVER_HINT,
    DRIVER_HINT_AUTO,
)
from .drivers.registry import get_driver


def persisted_inverter_identity(entry: Any) -> bool:
    """Return whether persisted config-entry data already knows the inverter."""

    data = getattr(entry, "data", {}) or {}
    return bool(
        str(data.get(CONF_DETECTED_MODEL) or "").strip()
        or str(data.get(CONF_DETECTED_SERIAL) or "").strip()
    )


def persisted_driver(entry: Any):
    """Return the persisted driver hint when runtime detection is still warming up."""

    data = getattr(entry, "data", {}) or {}
    options = getattr(entry, "options", {}) or {}
    driver_hint = str(
        options.get(CONF_DRIVER_HINT, data.get(CONF_DRIVER_HINT, DRIVER_HINT_AUTO))
        or DRIVER_HINT_AUTO
    ).strip()
    if not driver_hint or driver_hint == DRIVER_HINT_AUTO:
        return None
    try:
        return get_driver(driver_hint)
    except KeyError:
        return None


def entity_setup_context(entry: Any, coordinator: Any):
    """Resolve driver, inverter, and identity for entity-platform construction."""

    inverter = getattr(coordinator, "identified_inverter", None)
    driver = getattr(coordinator, "current_driver", None)
    if driver is None:
        driver = persisted_driver(entry)

    has_inverter_identity = bool(
        getattr(coordinator, "has_inverter_identity", False)
        or inverter is not None
        or persisted_inverter_identity(entry)
    )
    return driver, inverter, has_inverter_identity

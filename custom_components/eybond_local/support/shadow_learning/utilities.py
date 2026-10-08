"""Shared utility functions for shadow-learning orchestrators."""

from __future__ import annotations

from datetime import datetime
import time
from typing import Any, Awaitable, Callable

from . import ShadowWriteObservation


def _safe_read_map(read_map_snapshot: Callable[[], dict[str, Any]] | None) -> dict[str, Any]:
    """Snapshot the session read map without letting it fail the run."""

    if read_map_snapshot is None:
        return {}
    try:
        read_map = read_map_snapshot()
    except Exception:
        return {}
    return read_map if isinstance(read_map, dict) else {}


def _elapsed_ms(started_at: float) -> int:
    """Return one non-negative monotonic duration for safe diagnostics."""

    return max(0, int(round((time.monotonic() - started_at) * 1000.0)))


def _resolve_live_observation_cursor(
    *,
    observation_cursor: Callable[[], int] | None,
    current_observations_since: Callable[[int], tuple[ShadowWriteObservation, ...]] | None,
) -> int:
    if observation_cursor is not None:
        return int(observation_cursor())
    if current_observations_since is not None:
        return len(tuple(current_observations_since(0) or ()))
    return 0


def _collect_run_observations(
    *,
    run_cursor_start: int | None,
    current_observations_since: Callable[[int], tuple[ShadowWriteObservation, ...]] | None,
    attempt_observations: tuple[ShadowWriteObservation, ...],
) -> tuple[ShadowWriteObservation, ...]:
    if run_cursor_start is not None and current_observations_since is not None:
        return tuple(current_observations_since(run_cursor_start) or ())
    return tuple(attempt_observations)


async def _async_session_ready_for_attempt(
    *,
    is_session_ready: Callable[[], bool] | None,
    wait_until_session_ready: Callable[[], Awaitable[bool]] | None,
) -> bool:
    """Wait for a safe proxy window without weakening the live-route gate."""

    if is_session_ready is None or bool(is_session_ready()):
        return True
    if wait_until_session_ready is None:
        return False
    return bool(await wait_until_session_ready())


def _parse_iso_datetime(value: str) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _timestamp_delta_seconds(*, requested_at: datetime | None, observed_at: datetime | None) -> float | None:
    if requested_at is None or observed_at is None:
        return None
    return (observed_at - requested_at).total_seconds()


def _attach_attempt_observation(
    *,
    attempt: dict[str, Any],
    observations: tuple[ShadowWriteObservation, ...],
) -> None:
    if observations:
        observation = observations[0]
        attempt["observation_count"] = len(observations)
        attempt["observation"] = observation.to_json_dict()
        attempt["match_mode"] = "post_attempt_cursor"
        attempt["timestamp_delta_seconds"] = _timestamp_delta_seconds(
            requested_at=_parse_iso_datetime(str(attempt.get("requested_at") or "")),
            observed_at=_parse_iso_datetime(observation.timestamp),
        )
        return
    attempt["reason"] = "timeout_no_observed_write"

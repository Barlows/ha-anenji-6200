"""Bounded optional FC4 reads, with per-runtime freshness and negative caching."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Callable

from ..payload.short_ascii import ShortAsciiError, ShortAsciiSession, parse_f, parse_rb
from .command_support import (
    command_skipped_as_unsupported, commit_cycle_failures, record_command_failure,
    record_command_success, unsupported_commands,
)

STATE_KEY = "short_ascii_optional_reads"
_PREFIX = "short_ascii:"


@dataclass
class OptionalSample:
    command: str
    interval: float
    ttl: float
    parser: Callable[[bytes], dict[str, object]]
    next_due: float = 0
    sampled_at: float | None = None
    values: dict[str, object] = field(default_factory=dict)
    outcome: str = "not_checked"

    def clear(self) -> None:
        self.values.clear()
        self.sampled_at = None

    def fresh_values(self, now: float) -> dict[str, object]:
        if self.sampled_at is not None and not 0 <= now - self.sampled_at < self.ttl:
            self.clear()
            self.outcome = "expired"
        return dict(self.values)


@dataclass
class OptionalReads:
    # These references are runtime scope, not a second source of device identity.
    # The hub clears runtime_state on recovery/rebinding. Never persist samples.
    transport: object
    inverter: object
    last_clock: float
    samples: tuple[OptionalSample, ...] = field(default_factory=lambda: (
        OptionalSample("RB", interval=30, ttl=60, parser=parse_rb),
        OptionalSample("F", interval=900, ttl=900, parser=parse_f),
    ))

    def clear(self) -> None:
        for sample in self.samples:
            sample.clear()
            sample.next_due = 0
            sample.outcome = "not_checked"

    async def refresh_one(
        self, session: ShortAsciiSession, runtime_state: dict,
        clock: Callable[[], float],
    ) -> tuple[dict[str, object], dict[str, object]]:
        """At most one extra query per successful Q1 cycle; no discovery budget."""
        now = clock()
        for sample in self.samples:
            if command_skipped_as_unsupported(runtime_state, _PREFIX + sample.command):
                sample.clear()
                sample.outcome = "unsupported"
            elif sample.outcome == "unsupported":
                # The existing explicit re-check action cleared negative facts.
                sample.next_due = now
                sample.outcome = "not_checked"
        due = [sample for sample in self.samples
               if sample.outcome != "unsupported" and now >= sample.next_due]
        # Oldest scheduled group first; an unsupported RB cannot starve F.
        sample = min(due, key=lambda item: item.next_due) if due else None
        if sample is not None:
            key = _PREFIX + sample.command
            try:
                parsed = sample.parser(await session.request(sample.command))
            except (ShortAsciiError, asyncio.TimeoutError) as exc:
                sample.clear()
                sample.outcome = "timeout" if isinstance(exc, asyncio.TimeoutError) else "invalid_response"
                sample.next_due = clock() + 30
                if not session.transport.connected:
                    raise ConnectionError("short_ascii_optional_connection_lost") from None
                record_command_failure(runtime_state, key)
            else:
                sample.values = dict(parsed)
                sample.sampled_at = clock()
                sample.next_due = sample.sampled_at + sample.interval
                sample.outcome = "no_data" if parsed.get("short_ascii_bms_data_available") is False else "ok"
                record_command_success(runtime_state, key)
        # No staged strike survives a failed/cancelled cycle. Q1 was confirmed
        # by our caller, and from here to commit there are no suspension points.
        record_command_success(runtime_state, _PREFIX + "Q1")
        commit_cycle_failures(runtime_state)
        now = clock()
        self.last_clock = now
        values, diagnostics = {}, {}
        for sample in self.samples:
            values.update(sample.fresh_values(now))
            if sample.sampled_at is not None:
                diagnostics[f"short_ascii_{sample.command.lower()}_age_seconds"] = round(now - sample.sampled_at, 3)
        diagnostics["short_ascii_optional_status"] = "; ".join(
            f"{sample.command}={sample.outcome}" for sample in self.samples
        )
        diagnostics["driver_unsupported_commands"] = ", ".join(
            key for key in unsupported_commands(runtime_state) if key.startswith(_PREFIX)
        )
        return values, diagnostics


def optional_reads_for(runtime_state: dict, transport: object, inverter: object, now: float) -> OptionalReads:
    reads = runtime_state.get(STATE_KEY)
    if (
        type(reads) is not OptionalReads
        or reads.transport is not transport
        or reads.inverter is not inverter
        or now < reads.last_clock
    ):
        reads = OptionalReads(transport, inverter, now)
        runtime_state[STATE_KEY] = reads
    return reads

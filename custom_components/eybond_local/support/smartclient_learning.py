"""SmartClient passive evidence adaptation to the existing learning workflow."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

from ..smartclient_cloud import SmartClientEvidence, fetch_read_only_evidence
from .cloud_history_evidence import (
    CloudHistoryCollection,
    CloudHistoryIdentity,
    CloudHistoryPoint,
    CloudHistorySeries,
)
from .cloud_learning_runner import CloudLearningOutcome
from .cloud_read_only_workflow import CloudReadOnlyEvidenceOperation
from .cloud_semantic_evidence import (
    CLOUD_FIELD_KIND_CHART,
    CLOUD_FIELD_KIND_READING,
    CLOUD_FIELD_KIND_SETTING,
    CLOUD_SEMANTIC_STATUS_RECOGNIZED,
    CloudSemanticEvidenceReport,
    classify_cloud_semantic_observation,
)

_PROGRESS = {
    "auth": 0.16,
    "queryCollectorDevices": 0.24,
    "queryDeviceInfo": 0.32,
    "queryDeviceLastData": 0.40,
    "queryDeviceCtrlField": 0.48,
    "queryDeviceLastRawData": 0.56,
    "queryDeviceDataOneDay": 0.64,
}


def _history(bundle: SmartClientEvidence) -> CloudHistoryCollection:
    identity = CloudHistoryIdentity(**bundle.identity.to_record())
    offset = bundle.device_info.get("timezone")
    day = bundle.history.get("requested_date", "")
    if type(offset) is not int or not day:
        return CloudHistoryCollection(
            "smartess", "smartclient", identity, "", None, 0, 0, False, ()
        )
    titles = bundle.history.get("title", [])
    rows = bundle.history.get("row", [])
    series = []
    attempted = 0
    failed = 0
    for index, title in enumerate(titles):
        if index < 2 or attempted >= 8 or not title["title"]:
            continue
        hint = classify_cloud_semantic_observation(
            field_kind=CLOUD_FIELD_KIND_CHART,
            field_id=str(index),
            title=title["title"],
            value="",
            observed_unit=title["unit"],
            source_action="queryDeviceDataOneDay",
        )
        if (
            hint.status != CLOUD_SEMANTIC_STATUS_RECOGNIZED
            or hint.semantic_kind not in {"read", "both"}
        ):
            continue
        attempted += 1
        points = {}
        conflicts = set()
        for row in rows:
            values = row["field"]
            timestamp = values[1]
            value = values[index]
            try:
                local = datetime.strptime(timestamp, "%Y-%m-%d %H:%M:%S").replace(
                    tzinfo=timezone(timedelta(seconds=offset))
                )
                if (
                    local.date().isoformat() != day
                    or local.strftime("%Y-%m-%d %H:%M:%S") != timestamp
                    or not Decimal(value).is_finite()
                ):
                    continue
            except (ValueError, InvalidOperation):
                continue
            utc = local.astimezone(timezone.utc)
            point = CloudHistoryPoint(timestamp, utc.isoformat(), value)
            if timestamp in points and points[timestamp].value != value:
                conflicts.add(timestamp)
            points[timestamp] = point
        ordered = tuple(points[key] for key in sorted(points) if key not in conflicts)
        if not ordered:
            failed += 1
            continue
        series.append(
            CloudHistorySeries(
                provider_id="smartess",
                source_id="smartclient",
                source_action="queryDeviceDataOneDay",
                field_kind=CLOUD_FIELD_KIND_CHART,
                identity=identity,
                series_key=str(index),
                title=title["title"],
                unit=title["unit"],
                requested_date=day,
                precision_minutes=0,
                timezone_offset_seconds=offset,
                points=ordered,
            )
        )
    return CloudHistoryCollection(
        "smartess",
        "smartclient",
        identity,
        day,
        offset,
        attempted,
        failed,
        bundle.history.get("truncated") is True,
        tuple(series),
    )


def build_smartclient_outcome(bundle: SmartClientEvidence) -> CloudLearningOutcome:
    """Publish source-labelled hints/history, never a local mapping or control."""

    if type(bundle) is not SmartClientEvidence:
        raise TypeError("smartclient_evidence_invalid")
    observations = [
        classify_cloud_semantic_observation(
            field_kind=CLOUD_FIELD_KIND_READING,
            field_id=item["field_id"],
            title=item["title"],
            value=item["value"],
            observed_unit=item["unit"],
            source_action="queryDeviceLastData",
        )
        # Generic API reserves the first two fields for record ID and time.
        for item in bundle.telemetry
        if item["field_id"] not in {"0", "1"}
    ]
    observations.extend(
        classify_cloud_semantic_observation(
            field_kind=CLOUD_FIELD_KIND_SETTING,
            field_id=item["field_id"],
            title=item["title"],
            value="",
            observed_unit=item["unit"],
            source_action="queryDeviceCtrlField",
        )
        for item in bundle.controls
    )
    report = CloudSemanticEvidenceReport(
        "smartess", "smartclient", tuple(observations[:512])
    )
    history = _history(bundle)
    evidence = bundle.to_record()
    evidence["semantic_report"] = report.to_record()
    evidence["history_collection"] = history.to_record()
    result = {
        "source": "smartclient",
        "metadata_only": True,
        "metadata_field_count": evidence["metadata_field_count"],
        "semantic_candidate_count": report.read_candidate_count,
        "semantic_unit_conflict_count": report.unit_conflict_count,
        "semantic_unknown_count": report.unknown_count,
        "control_metadata_count": report.control_metadata_count,
        "history_status": history.status,
        "history_series_count": history.collected_series_count,
        "history_point_count": history.point_count,
        "history_failed_series_count": history.failed_series_count,
        "plan": [],
        "planned_write_count": 0,
        "executed_result_count": 0,
        "sent_count": 0,
        "leaked_count": 0,
        "degraded_count": 0,
        "metadata_evidence": evidence,
    }
    return CloudLearningOutcome(
        identity=bundle.identity.to_record(),
        result=result,
        metadata_evidence=evidence,
        read_bindings=None,
    )


class SmartClientReadOnlyEvidenceOperation(CloudReadOnlyEvidenceOperation):
    provider_id = "smartess"
    source_id = "smartclient"

    async def async_collect(
        self, *, executor, collector_pn, username, password, max_fields, progress
    ):
        del (
            max_fields
        )  # No active probe budget; the client has passive response bounds.
        loop = asyncio.get_running_loop()

        def report(stage: str) -> None:
            if stage in _PROGRESS:
                loop.call_soon_threadsafe(progress, _PROGRESS[stage], "fetching")

        return await executor(
            lambda: build_smartclient_outcome(
                fetch_read_only_evidence(
                    username=username,
                    password=password,
                    collector_pn=collector_pn,
                    progress=report,
                )
            )
        )

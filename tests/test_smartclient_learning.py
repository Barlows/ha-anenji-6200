from __future__ import annotations

import sys
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from test_smartclient_cloud import DAY, IDENTITY, PN, fetch_fixture

from custom_components.eybond_local.support.cloud_learning_engines import (
    resolve_cloud_learning_selection,
)
from custom_components.eybond_local.support.cloud_learning_models import (
    CloudLearningSelection,
)
from custom_components.eybond_local.support.cloud_read_only_workflow import (
    ReadOnlyEvidenceWorkflowRunner,
)
from custom_components.eybond_local.support.smartclient_learning import (
    SmartClientReadOnlyEvidenceOperation,
    build_smartclient_outcome,
)


def fixture():
    bundle, _ = fetch_fixture()
    return replace(bundle, history=dict(bundle.history, requested_date=DAY))


class SmartClientLearningTests(unittest.TestCase):
    def test_normalized_history_has_exact_identity_and_utc(self):
        outcome = build_smartclient_outcome(fixture())
        history = outcome.metadata_evidence["history_collection"]
        self.assertEqual(history["source_id"], "smartclient")
        self.assertEqual(history["identity"], IDENTITY)
        self.assertEqual(
            history["series"][0]["points"][0]["utc_timestamp"], DAY + "T09:00:00+00:00"
        )
        self.assertFalse(history["local_mapping_proven"])
        self.assertIsNone(outcome.read_bindings)
        self.assertEqual(outcome.result["planned_write_count"], 0)

    def test_absent_cloud_timezone_retains_data_without_claiming_utc(self):
        bundle = replace(fixture(), device_info={})
        outcome = build_smartclient_outcome(bundle)
        self.assertEqual(outcome.result["history_status"], "time_basis_unavailable")
        self.assertEqual(outcome.result["history_point_count"], 0)
        self.assertTrue(outcome.metadata_evidence["daily_data"]["row"])

    def test_conflicting_timestamp_and_non_numeric_points_are_not_matched(self):
        bundle = fixture()
        history = dict(
            bundle.history,
            row=[
                {"field": ["1", DAY + " 12:00:00", "220.5"]},
                {"field": ["2", DAY + " 12:00:00", "221.5"]},
                {"field": ["3", DAY + " 12:05:00", "NaN"]},
                {"field": ["4", DAY + " 12:10:00", "222.5"]},
            ],
        )
        outcome = build_smartclient_outcome(replace(bundle, history=history))
        self.assertEqual(outcome.result["history_point_count"], 1)

    def test_source_is_read_only_and_does_not_change_existing_defaults(self):
        engine = resolve_cloud_learning_selection(
            CloudLearningSelection("read_only_evidence", "smartclient")
        )
        self.assertTrue(engine.available)
        self.assertTrue(engine.evidence_capabilities.local_register_series)
        self.assertFalse(engine.source.capabilities.control_actions)
        active = resolve_cloud_learning_selection(
            CloudLearningSelection("active_correlation", "smartclient")
        )
        self.assertFalse(active.available)

    def test_adapter_uses_existing_localized_error_vocabulary(self):
        from custom_components.eybond_local.smartclient_cloud import (
            SmartClientCloudError,
        )
        from custom_components.eybond_local.support.cloud_api_adapters import (
            SmartClientCloudApiAdapter,
        )

        adapter = SmartClientCloudApiAdapter()
        for reason, code, expected in (
            ("timeout", None, "timeout"),
            ("network", None, "network"),
            ("identity_mismatch", None, "unavailable"),
            ("device_data_unavailable", None, "unavailable"),
            ("api_rejected", 10, "auth_failed"),
            ("api_rejected", 11, "unavailable"),
            ("api_rejected", 258, "unavailable"),
            ("api_rejected", 16, "unexpected"),
        ):
            with self.subTest(reason=reason, code=code):
                self.assertEqual(
                    adapter.classify_error(SmartClientCloudError(reason, code=code)),
                    expected,
                )


class SmartClientRunnerTests(unittest.IsolatedAsyncioTestCase):
    async def test_runner_uses_no_route_or_writer_and_keeps_password_ephemeral(self):
        runner = ReadOnlyEvidenceWorkflowRunner(SmartClientReadOnlyEvidenceOperation())
        start_route = AsyncMock()
        writer = Mock()
        identities = []

        async def executor(fn):
            return fn()

        with patch(
            "custom_components.eybond_local.support.smartclient_learning.fetch_read_only_evidence",
            return_value=fixture(),
        ):
            outcome = await runner.async_run(
                executor=executor,
                collector_pn=PN,
                username="owner",
                password="PRIVATE",
                fallback_identity={"pn": "FOREIGN"},
                max_fields=1,
                progress=Mock(),
                orchestrator_callbacks=Mock(),
                on_identity=identities.append,
                start_shadow_route=start_route,
                on_learning=writer,
            )
        start_route.assert_not_called()
        writer.assert_not_called()
        self.assertEqual(identities, [IDENTITY])
        self.assertNotIn("PRIVATE", str(outcome))
        self.assertFalse(hasattr(runner._operation, "password"))


if __name__ == "__main__":
    unittest.main()

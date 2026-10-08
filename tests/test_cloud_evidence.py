from __future__ import annotations

import contextlib
from datetime import datetime, timezone
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


from custom_components.eybond_local.support import cloud_evidence_providers as providers
from custom_components.eybond_local.support.cloud_evidence import (
    build_cloud_evidence_payload,
    cloud_evidence_root as _cloud_evidence_root,
    export_cloud_evidence,
    fetch_and_export_smartess_device_bundle_cloud_evidence,
    fetch_and_export_valuecloud_device_bundle_cloud_evidence,
    infer_evidence_provider,
    load_latest_cloud_evidence,
)
from custom_components.eybond_local.support.cloud_evidence_providers import (
    CloudEvidenceContext,
    resolve_cloud_evidence_provider,
)


@contextlib.contextmanager
def _frozen_export_clock():
    """Pin cloud_evidence's clock so every export derives the same timestamp.

    That is the real-world condition these tests are about: the platform clock
    is coarser (~1.4 ms) than the microsecond timestamp the filename claims, so
    two exports inside one tick collide by construction. Pinned, the collision is
    deterministic instead of dependent on how the file I/O happens to interleave
    with the clock tick -- which is the difference between a test that catches
    the bug and one that passes by luck.
    """

    frozen = datetime(2026, 1, 2, 3, 4, 5, 678901, tzinfo=timezone.utc)
    with patch(
        "custom_components.eybond_local.support.cloud_evidence.datetime"
    ) as mocked:
        mocked.now.return_value = frozen
        yield


class CloudEvidenceTests(unittest.TestCase):
    def test_exports_and_loads_latest_matching_cloud_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_dir = Path(temp_dir)
            older = build_cloud_evidence_payload(
                source="smartess_cloud_probe",
                payload={"request": {"command": "device-bundle", "older": True}},
                entry_id="entry123",
                collector_pn="E5000020000000",
                pn="E50000200000000001",
                sn="E50000200000000001000001",
                devcode=2376,
                devaddr=1,
            )
            newer = build_cloud_evidence_payload(
                source="smartess_cloud_probe",
                payload={"request": {"command": "device-bundle", "older": False}},
                entry_id="entry123",
                collector_pn="E5000020000000",
                pn="E50000200000000001",
                sn="E50000200000000001000001",
                devcode=2376,
                devaddr=1,
            )

            export_cloud_evidence(config_dir=config_dir, evidence=older)
            latest_path = export_cloud_evidence(config_dir=config_dir, evidence=newer)

            record = load_latest_cloud_evidence(
                config_dir,
                entry_id="entry123",
                collector_pn="E5000020000000",
            )

            self.assertIsNotNone(record)
            assert record is not None
            self.assertEqual(record.path, latest_path)
            self.assertFalse(record.payload["payload"]["request"]["older"])

    def test_returns_none_when_no_matching_cloud_evidence_exists(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_dir = Path(temp_dir)
            evidence = build_cloud_evidence_payload(
                source="smartess_cloud_probe",
                payload={"request": {"command": "device-bundle"}},
                entry_id="other-entry",
                collector_pn="Q0000000000001",
                pn="Q0000000000001",
                sn="Q00000000000010001",
                devcode=258,
                devaddr=1,
            )
            export_cloud_evidence(config_dir=config_dir, evidence=evidence)

            record = load_latest_cloud_evidence(
                config_dir,
                entry_id="entry123",
                collector_pn="E5000020000000",
            )

            self.assertIsNone(record)

    def test_loads_legacy_short_pn_cloud_evidence_for_full_current_pn(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_dir = Path(temp_dir)
            evidence = build_cloud_evidence_payload(
                source="smartess_cloud_probe",
                payload={"request": {"command": "device-bundle"}},
                entry_id="legacy-entry",
                collector_pn="E5000020000000",
                pn="E50000200000000001",
                sn="E50000200000000001000001",
                devcode=2376,
                devaddr=1,
            )
            exported_path = export_cloud_evidence(config_dir=config_dir, evidence=evidence)

            record = load_latest_cloud_evidence(
                config_dir,
                entry_id="current-entry",
                collector_pn="E50000200000000001",
            )

            self.assertIsNotNone(record)
            assert record is not None
            self.assertEqual(record.path, exported_path)

    def test_skips_non_utf8_cloud_evidence_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_dir = Path(temp_dir)
            root = config_dir / "eybond_local" / "cloud_evidence"
            root.mkdir(parents=True, exist_ok=True)
            (root / "bad_latest.json").write_bytes(b"\xff\xfe\x00\x00")

            evidence = build_cloud_evidence_payload(
                source="smartess_cloud_probe",
                payload={"request": {"command": "device-bundle"}},
                entry_id="entry123",
                collector_pn="E5000020000000",
                pn="E50000200000000001",
                sn="E50000200000000001000001",
                devcode=2376,
                devaddr=1,
            )
            valid_path = export_cloud_evidence(config_dir=config_dir, evidence=evidence)

            record = load_latest_cloud_evidence(
                config_dir,
                entry_id="entry123",
                collector_pn="E5000020000000",
            )

            self.assertIsNotNone(record)
            assert record is not None
            self.assertEqual(record.path, valid_path)

    def test_fetch_and_export_smartess_device_bundle_cloud_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_dir = Path(temp_dir)
            bundle_payload = {
                "request": {
                    "command": "device-bundle",
                    "params": {
                        "pn": "E50000200000000001",
                        "sn": "E50000200000000001000001",
                        "devcode": 2376,
                        "devaddr": 1,
                    },
                },
                "responses": {
                    "device_list": {},
                    "device_detail": {},
                    "device_settings": {},
                    "energy_flow": {},
                },
                "normalized": {
                    "device_list": {"device_count": 1},
                    "device_detail": {"section_counts": {"bc_": 1, "pv_": 1}},
                    "device_settings": {
                        "field_count": 5,
                        "mapped_field_count": 3,
                        "exact_0925_field_count": 3,
                        "probable_0925_field_count": 1,
                        "cloud_only_field_count": 1,
                        "current_values_included": False,
                        "write_action": "ctrlDevice",
                    },
                },
            }

            with patch(
                "custom_components.eybond_local.support.cloud_evidence.fetch_smartess_device_bundle_for_collector",
                return_value=bundle_payload,
            ):
                record = fetch_and_export_smartess_device_bundle_cloud_evidence(
                    config_dir=config_dir,
                    username="test-user",
                    password="secret",
                    collector_pn="E5000020000000",
                    source="smartess_cloud_onboarding",
                )

            self.assertTrue(record.path.exists())
            self.assertEqual(record.payload["match"]["collector_pn"], "E5000020000000")
            self.assertEqual(record.payload["summary"]["settings_write_action"], "ctrlDevice")

    def test_fetch_and_export_valuecloud_device_bundle_cloud_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_dir = Path(temp_dir)
            bundle_payload = {
                "request": {
                    "command": "valuecloud-device-bundle",
                    "provider": "valuecloud",
                    "params": {
                        "collector_pn": "A0000000000001",
                        "pn": "A0000000000001",
                        "sn": "TY-SIC-3.6KBE-W1",
                        "devcode": 2452,
                        "devaddr": 255,
                    },
                },
                "responses": {
                    "device_list": {},
                    "device_detail": {},
                    "device_pars": {},
                    "control_strategy": {},
                    "device_ctrl": {"status": "error", "error": "timeout"},
                },
                "normalized": {
                    "device_list": {"device_count": 1},
                    "device_detail": {"section_counts": {"gd_": 3, "pv_": 4}},
                    "device_pars": {"field_count": 7, "current_values_included": True},
                    "control_strategy": {"field_count": 2, "current_values_included": False},
                },
            }

            with patch(
                "custom_components.eybond_local.support.cloud_evidence.fetch_valuecloud_device_bundle_for_collector",
                return_value=bundle_payload,
            ):
                record = fetch_and_export_valuecloud_device_bundle_cloud_evidence(
                    config_dir=config_dir,
                    username="test-user",
                    password="secret",
                    collector_pn="A0000000000001",
                    source="valuecloud_cloud_diagnostics",
                )

            self.assertTrue(record.path.exists())
            self.assertEqual(record.payload["source"], "valuecloud_cloud_diagnostics")
            self.assertEqual(record.payload["summary"]["provider"], "valuecloud")
            self.assertEqual(record.payload["summary"]["parameter_field_count"], 7)
            self.assertEqual(record.payload["summary"]["optional_action_error_count"], 1)

    def test_registry_is_single_provider_selection_authority(self) -> None:
        # The provider-string dispatcher is gone; the registry selects the
        # provider and only ValueCloud's fetch runs for a ValueCloud context.
        context = CloudEvidenceContext(
            config_dir=Path("/tmp"), entry_id="e", collector_pn="A0000000000001"
        )
        with patch.object(
            providers, "fetch_and_export_valuecloud_device_bundle_cloud_evidence",
            return_value="sentinel",
        ) as vc_fetch, patch.object(
            providers, "fetch_and_export_smartess_device_bundle_cloud_evidence",
        ) as smartess_fetch:
            out = resolve_cloud_evidence_provider("valuecloud").export(
                context, username="test-user", password="secret"
            )
        self.assertEqual(out, "sentinel")
        vc_fetch.assert_called_once()
        smartess_fetch.assert_not_called()


class EvidenceProvenanceTests(unittest.TestCase):
    def test_new_records_carry_explicit_provider(self) -> None:
        payload = build_cloud_evidence_payload(
            source="x", payload={}, provider="smartess"
        )
        self.assertEqual(payload["provider"], "smartess")
        self.assertEqual(infer_evidence_provider(payload), "smartess")

    def test_legacy_source_prefix_inference(self) -> None:
        # An old record with no explicit provider is still readable via source.
        self.assertEqual(
            infer_evidence_provider({"source": "smartess_cloud_diagnostics"}), "smartess"
        )
        self.assertEqual(
            infer_evidence_provider({"source": "valuecloud_cloud_diagnostics"}), "valuecloud"
        )
        self.assertEqual(
            infer_evidence_provider({"summary": {"provider": "valuecloud"}}), "valuecloud"
        )

    def test_unknown_provenance_is_empty(self) -> None:
        self.assertEqual(infer_evidence_provider({"source": "mystery"}), "")
        self.assertEqual(infer_evidence_provider({}), "")

    def test_explicit_provider_is_strictly_authoritative(self) -> None:
        # A tampered/contradictory record: explicit provider "unknown" must NOT
        # fall back to the smartess source prefix.
        self.assertEqual(
            infer_evidence_provider(
                {"provider": "unknown", "source": "smartess_cloud_diagnostics"}
            ),
            "",
        )
        # Present-but-empty explicit provider also fails closed, no fallback.
        self.assertEqual(
            infer_evidence_provider(
                {"provider": "", "source": "smartess_cloud_diagnostics"}
            ),
            "",
        )
        # A known explicit provider wins over a contradictory source.
        self.assertEqual(
            infer_evidence_provider(
                {"provider": "valuecloud", "source": "smartess_cloud_diagnostics"}
            ),
            "valuecloud",
        )

    def test_summary_provider_only_when_top_level_absent(self) -> None:
        # Legacy record: no top-level provider key -> summary marker is used.
        self.assertEqual(
            infer_evidence_provider({"summary": {"provider": "smartess"}}), "smartess"
        )
        # Summary marker present-but-unknown fails closed (no source fallback).
        self.assertEqual(
            infer_evidence_provider(
                {"summary": {"provider": "unknown"}, "source": "smartess_cloud_diagnostics"}
            ),
            "",
        )

    def test_provider_scoped_load_refuses_foreign_provider(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_dir = Path(temp_dir)
            # Both providers export evidence for the SAME entry/PN.
            smartess = build_cloud_evidence_payload(
                source="smartess_cloud_diagnostics", payload={}, provider="smartess",
                entry_id="entry-1", collector_pn="A0000000000001",
            )
            valuecloud = build_cloud_evidence_payload(
                source="valuecloud_cloud_diagnostics", payload={}, provider="valuecloud",
                entry_id="entry-1", collector_pn="A0000000000001",
            )
            export_cloud_evidence(config_dir=config_dir, evidence=smartess)
            export_cloud_evidence(config_dir=config_dir, evidence=valuecloud)

            smartess_record = load_latest_cloud_evidence(
                config_dir, entry_id="entry-1", collector_pn="A0000000000001",
                provider="smartess",
            )
            valuecloud_record = load_latest_cloud_evidence(
                config_dir, entry_id="entry-1", collector_pn="A0000000000001",
                provider="valuecloud",
            )
            # Each provider gets ONLY its own record -- no cross-provider leak.
            self.assertIsNotNone(smartess_record)
            self.assertEqual(infer_evidence_provider(smartess_record.payload), "smartess")
            self.assertIsNotNone(valuecloud_record)
            self.assertEqual(infer_evidence_provider(valuecloud_record.payload), "valuecloud")

    def test_unknown_provenance_load_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_dir = Path(temp_dir)
            mystery = build_cloud_evidence_payload(
                source="mystery_source", payload={},
                entry_id="entry-1", collector_pn="A0000000000001",
            )
            export_cloud_evidence(config_dir=config_dir, evidence=mystery)
            self.assertIsNone(
                load_latest_cloud_evidence(
                    config_dir, entry_id="entry-1", collector_pn="A0000000000001",
                    provider="smartess",
                )
            )

    def test_unknown_provenance_export_does_not_prune_known_provider(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_dir = Path(temp_dir)
            known = build_cloud_evidence_payload(
                source="smartess_cloud_diagnostics",
                payload={},
                provider="smartess",
                entry_id="entry-1",
                collector_pn="A0000000000001",
            )
            known_path = export_cloud_evidence(config_dir=config_dir, evidence=known)
            mystery = build_cloud_evidence_payload(
                source="mystery_source",
                payload={},
                entry_id="entry-1",
                collector_pn="A0000000000001",
            )
            export_cloud_evidence(config_dir=config_dir, evidence=mystery)
            self.assertTrue(known_path.exists())
            self.assertIsNotNone(
                load_latest_cloud_evidence(
                    config_dir,
                    entry_id="entry-1",
                    collector_pn="A0000000000001",
                    provider="smartess",
                )
            )

    def test_back_to_back_exports_of_one_identity_do_not_collide(self) -> None:
        # The name carries a microsecond timestamp but the platform clock ticks
        # at ~1.4 ms, so two exports inside one tick derive the SAME name by
        # construction. The exclusive claim must resolve that by suffixing, not
        # by raising -- otherwise a retry loses its own record.
        #
        # The clock is pinned deliberately. Left to run freely, each export does
        # real file I/O and takes longer (~2 ms) than the tick it is naming, so
        # consecutive exports land in different ticks and never collide at all --
        # the test would pass against the unfixed code for the wrong reason.
        with tempfile.TemporaryDirectory() as temp_dir:
            config_dir = Path(temp_dir)
            evidence = build_cloud_evidence_payload(
                source="smartess_cloud_probe",
                payload={"request": {"command": "device-bundle"}},
                entry_id="entry123",
                collector_pn="E5000020000000",
                pn="E50000200000000001",
                sn="E50000200000000001000001",
                devcode=2376,
                devaddr=1,
            )

            with _frozen_export_clock():
                paths = [
                    export_cloud_evidence(config_dir=config_dir, evidence=evidence)
                    for _ in range(25)
                ]

            self.assertEqual(
                len(set(paths)), len(paths), "every export must get its own name"
            )
            for path in paths:
                self.assertTrue(path.exists(), path)

    def test_collision_suffix_still_reads_back_as_the_latest_record(self) -> None:
        # load_latest_cloud_evidence() picks the greatest FILENAME. '_' (0x5F)
        # sorts above '.' (0x2E), so a suffixed name has to sort after the plain
        # one or a retried export would be shadowed by the record it replaced.
        with tempfile.TemporaryDirectory() as temp_dir:
            config_dir = Path(temp_dir)
            evidence = build_cloud_evidence_payload(
                source="smartess_cloud_probe",
                payload={"request": {"command": "device-bundle", "attempt": 2}},
                entry_id="entry123",
                collector_pn="E5000020000000",
                pn="E50000200000000001",
                sn="E50000200000000001000001",
                devcode=2376,
                devaddr=1,
            )
            with _frozen_export_clock():
                first = export_cloud_evidence(config_dir=config_dir, evidence=evidence)
                second = export_cloud_evidence(config_dir=config_dir, evidence=evidence)

            self.assertGreater(second.name, first.name)

            record = load_latest_cloud_evidence(
                config_dir, entry_id="entry123", collector_pn="E5000020000000"
            )
            self.assertIsNotNone(record)
            assert record is not None
            self.assertEqual(record.path, second)

    def test_collision_suffix_stays_inside_its_own_prune_set(self) -> None:
        # _prune_older_files_for_stem() globs "{stem}_*.json". A suffixed name
        # must still match, or colliding exports would accumulate forever
        # instead of collapsing to one file per identity.
        #
        # The payload names a provider on purpose: pruning returns early for an
        # UNKNOWN provider (it must not delete another provider's evidence), so
        # a provider-less payload would keep every file and prove nothing.
        with tempfile.TemporaryDirectory() as temp_dir:
            config_dir = Path(temp_dir)
            evidence = build_cloud_evidence_payload(
                source="smartess_cloud_diagnostics",
                payload={"request": {"command": "device-bundle"}},
                provider="smartess",
                entry_id="entry123",
                collector_pn="E5000020000000",
                pn="E50000200000000001",
                sn="E50000200000000001000001",
                devcode=2376,
                devaddr=1,
            )
            with _frozen_export_clock():
                for _ in range(10):
                    export_cloud_evidence(config_dir=config_dir, evidence=evidence)

            stored = list(_cloud_evidence_root(config_dir).glob("*.json"))
            self.assertEqual(len(stored), 1, [p.name for p in stored])

    def test_overwrite_still_reclaims_the_exact_same_path(self) -> None:
        # overwrite=True is a deliberate replace: it must not walk the suffix.
        with tempfile.TemporaryDirectory() as temp_dir:
            config_dir = Path(temp_dir)
            evidence = build_cloud_evidence_payload(
                source="smartess_cloud_probe",
                payload={"request": {"command": "device-bundle"}},
                entry_id="entry123",
                collector_pn="E5000020000000",
                pn="E50000200000000001",
                sn="E50000200000000001000001",
                devcode=2376,
                devaddr=1,
            )
            with _frozen_export_clock():
                first = export_cloud_evidence(config_dir=config_dir, evidence=evidence)
                again = export_cloud_evidence(
                    config_dir=config_dir, evidence=evidence, overwrite=True
                )
            self.assertEqual(first.name, again.name)
            self.assertTrue(again.exists())

    def test_provider_load_latest_is_scoped(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_dir = Path(temp_dir)
            export_cloud_evidence(
                config_dir=config_dir,
                evidence=build_cloud_evidence_payload(
                    source="valuecloud_cloud_diagnostics", payload={}, provider="valuecloud",
                    entry_id="entry-1", collector_pn="A0000000000001",
                ),
            )
            context = CloudEvidenceContext(
                config_dir=config_dir, entry_id="entry-1", collector_pn="A0000000000001"
            )
            # SmartESS provider refuses the ValueCloud record; ValueCloud accepts it.
            self.assertIsNone(resolve_cloud_evidence_provider("smartess").load_latest(context))
            self.assertIsNotNone(resolve_cloud_evidence_provider("valuecloud").load_latest(context))


if __name__ == "__main__":
    unittest.main()

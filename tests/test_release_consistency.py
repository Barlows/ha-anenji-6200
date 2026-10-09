"""Keep the manifest version, the changelog and the release notes in step.

A release is a manifest version, a ``## [x.y.z] - date`` changelog section and a
``vx.y.z`` tag that all agree. HACS offers installs by tag and Home Assistant shows
the manifest version, so a mismatch means a rollback target that is mislabelled.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import re
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = REPO_ROOT / "custom_components" / "eybond_local" / "manifest.json"
CHANGELOG_PATH = REPO_ROOT / "CHANGELOG.md"

_SPEC = importlib.util.spec_from_file_location(
    "render_release_notes", REPO_ROOT / "tools" / "render_release_notes.py"
)
if _SPEC is None or _SPEC.loader is None:
    raise RuntimeError("Could not load render_release_notes tool")
_RENDER = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_RENDER)

# MAJOR.MINOR.PATCH with an optional pre-release suffix such as -rc.1.
_SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.]+)?$")
_RELEASE_HEADER_RE = re.compile(
    r"^## \[(?P<version>\d+\.\d+\.\d+[^\]]*)\] - (?P<date>\d{4}-\d{2}-\d{2})$",
    re.MULTILINE,
)


class ReleaseConsistencyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.manifest_version = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))["version"]
        cls.changelog = CHANGELOG_PATH.read_text(encoding="utf-8")
        cls.releases = _RELEASE_HEADER_RE.findall(cls.changelog)

    def test_manifest_version_is_semver(self) -> None:
        self.assertRegex(self.manifest_version, _SEMVER_RE)

    def test_changelog_has_an_unreleased_section(self) -> None:
        self.assertIn("## [Unreleased]", self.changelog)

    def test_manifest_version_is_the_newest_changelog_release(self) -> None:
        self.assertTrue(self.releases, "CHANGELOG.md has no '## [x.y.z] - date' section")
        newest_version, _date = self.releases[0]
        self.assertEqual(
            self.manifest_version,
            newest_version,
            "manifest.json version must equal the newest released section in "
            "CHANGELOG.md; bump both together when cutting a release",
        )

    def test_release_versions_are_unique_semver(self) -> None:
        versions = [version for version, _date in self.releases]
        self.assertEqual(len(versions), len(set(versions)))
        for version in versions:
            self.assertRegex(version, _SEMVER_RE)

    def test_every_release_section_renders_notes(self) -> None:
        for version, _date in self.releases:
            notes = _RENDER.extract_release_notes(self.changelog, f"v{version}")
            self.assertTrue(notes.strip(), f"release notes for {version} are empty")


if __name__ == "__main__":
    unittest.main()

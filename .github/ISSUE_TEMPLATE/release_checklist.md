---
name: Release Checklist
about: Checklist for publishing a numbered release of this fork so HACS can install (and roll back to) it.
title: "release: vX.Y.Z"
labels: maintenance
assignees: Barlows
---

Steps are explained in [docs/maintainer/RELEASING.md](../../docs/maintainer/RELEASING.md).

## Version

- [ ] Version number chosen (patch / minor / major / pre-release).
- [ ] `CHANGELOG.md`: `## [Unreleased]` content moved into `## [X.Y.Z] - YYYY-MM-DD`, a fresh `## [Unreleased]` left above it, link references at the bottom updated.
- [ ] `custom_components/eybond_local/manifest.json` `version` set to `X.Y.Z`.
- [ ] README install/troubleshooting text still correct for this version.

## Validation

- [ ] Unit suite passes (`python3 -m unittest discover -s tests -p "test_*.py"`).
- [ ] `python3 tools/check_public_docs.py` passes.
- [ ] `python3 tools/render_release_notes.py vX.Y.Z` prints the notes.
- [ ] **Validate** workflow green on the pull request (HACS validation, Hassfest, quality gate, HA lanes).
- [ ] Unreleased build ran cleanly on the real device for long enough to trust (logs, `Collector Stray Modbus Replies Skipped`, retained disconnect reason).

## Publish

- [ ] Pull request merged to `main`.
- [ ] **Release** workflow ran on the merge and created tag `vX.Y.Z` and the GitHub release (pre-release if the version contains `-`); otherwise published by hand per RELEASING.md.
- [ ] Release title and tag match the manifest version.

## Post-release

- [ ] HACS offers `X.Y.Z` (Update information) and lists it in the Redownload version list.
- [ ] Installed on the real device and the logs checked.
- [ ] Previous known-good version noted in case a rollback is needed.

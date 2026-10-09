# Releasing

This fork ships **numbered releases** so that a version that works can always be
reinstalled from HACS if a later one causes trouble.

[CHANGELOG.md](../../CHANGELOG.md) is the source of truth for release notes. The
GitHub release body is rendered from it, never written in the release form.

A release is four things that must agree:

| Where | What |
|---|---|
| [manifest.json](../../custom_components/eybond_local/manifest.json) | `"version": "X.Y.Z"` |
| [CHANGELOG.md](../../CHANGELOG.md) | a `## [X.Y.Z] - YYYY-MM-DD` section |
| git | the tag `vX.Y.Z` on the commit that carries both of the above |
| GitHub | a release named `vX.Y.Z`, with the section as its notes |

`tests/test_release_consistency.py` fails if the manifest version is not the newest
released changelog section, so the first two cannot drift apart unnoticed.

## Version numbers

Semantic Versioning, `MAJOR.MINOR.PATCH`:

- **Patch** (`1.0.1`): a fix, a diagnostic, a docs-only change that is worth
  shipping. Nothing the user has to react to.
- **Minor** (`1.1.0`): something new (a sensor, a supported setting, new inverter
  support) that does not break existing setups.
- **Major** (`2.0.0`): entity ids or options change, re-configuration is needed, or
  an upstream merge changes behaviour in a way that needs a note.
- **Pre-release** (`1.1.0-rc.1`): a build you want installed on purpose for testing.
  Publish it as a GitHub *pre-release*: HACS hides those unless **Show beta
  versions** is on for the repository, so nobody gets one by accident.

Versions are never reused or moved. If a release is bad, fix forward with the next
patch version. Do not delete or re-point the tag, because people may have it
installed and HACS and Home Assistant key off the number.

## Day to day: before a release

Every change goes in as a pull request against `main`, with its entry under
`## [Unreleased]` in the changelog, grouped under `Added`, `Changed`, `Fixed`,
`Diagnostics` and so on, naming the PR. Merging to `main` does **not** release
anything: HACS installs the newest *release*, not the newest commit.

To try merged-but-unreleased work on the real device, redownload in HACS and pick
the `main` branch from the version list (or copy the branch archive over
`custom_components/eybond_local/`), restart, and check the logs. Cut a release only
once it has run cleanly for long enough to trust.

## Cutting a release

1. **Choose the version** from the rules above.
2. **Prepare the release commit** (on a branch, through a pull request):
   - In `CHANGELOG.md`, rename `## [Unreleased]` content into a new
     `## [X.Y.Z] - YYYY-MM-DD` section (today's date) and leave a fresh
     `## [Unreleased]` / `Nothing yet.` above it. Add a **Known issues** list if
     something notable remains.
   - Update the link references at the bottom of the changelog
     (`[Unreleased]: …/compare/vX.Y.Z...HEAD` and `[X.Y.Z]: …/releases/tag/vX.Y.Z`).
   - Set `"version": "X.Y.Z"` in `custom_components/eybond_local/manifest.json`.
   - If the Install or Troubleshooting text in the README names a version, update it.
3. **Validate.** Install the test requirements (`pip install -r requirements-test.txt`)
   and run:

   ```bash
   python3 -m unittest discover -s tests -p "test_*.py"
   python3 tools/check_public_docs.py
   python3 tools/render_release_notes.py vX.Y.Z   # must print the notes, not fail
   ```

   Then confirm the **Validate** workflow is green on the pull request (HACS
   validation, Hassfest, the quality gate and the Home Assistant lanes).
4. **Merge the pull request.** Note the merge commit on `main`.
5. **Tag and publish** that commit. With the GitHub CLI:

   ```bash
   python3 tools/render_release_notes.py vX.Y.Z --output .local/release-notes/vX.Y.Z.md
   gh release create vX.Y.Z \
     --target main \
     --title "vX.Y.Z" \
     --notes-file .local/release-notes/vX.Y.Z.md
   ```

   Add `--prerelease` for a release candidate. `gh release create` creates the tag
   on the target commit as part of publishing. The same thing can be done through
   the REST API (`POST /repos/Barlows/ha-anenji-6200/releases` with `tag_name`,
   `target_commitish`, `name`, `body`, `prerelease`) where the CLI is not available.
6. **Check HACS.** In HACS, use **Update information** on the repository, then open
   it: the new version should be offered, and the *Redownload* version list should
   show it next to the previous ones.
7. **Install it and watch the logs** on the real device; record the result in the
   pull request or an issue if anything is off.

The release checklist issue template
([.github/ISSUE_TEMPLATE/release_checklist.md](../../.github/ISSUE_TEMPLATE/release_checklist.md))
lists the same steps for ticking off.

## Rolling back

Users (and you) go back with HACS: **EyeBond Local SC → ⋮ → Redownload → choose the
older version → restart Home Assistant.** HACS lists only the most recent releases,
so keep that in mind before letting many releases pile up between two versions you
may want to move between. A rollback is a reinstall of old files; nothing about the
config entry changes, so it is safe unless a release's notes say a migration ran.

## Upstream merges

Pulling changes from `groove-max/ha-eybond-local` is a deliberate act, done on its
own branch, never automatically. Copy the relevant upstream changelog entries into
[UPSTREAM_CHANGELOG.md](../../UPSTREAM_CHANGELOG.md), describe the merge in this
fork's changelog, and expect `manifest.json` to conflict: keep this fork's
`version`. Release the result like any other change.

## Writing good release notes

- Keep them user-facing: what changed on the real device, and how to tell.
- Group under `Added`, `Changed`, `Fixed`, `Diagnostics` and `Known issues`.
- Say plainly when something is **confirmed on the real unit** and when it is
  **untested**.
- Call out anything that needs re-configuration, a restart, or that changes an entity.
- Keep purely internal refactors out unless they affect users or release safety.

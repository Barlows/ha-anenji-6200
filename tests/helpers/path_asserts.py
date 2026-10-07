"""Platform-independent path comparisons for tests.

The suite asserts on repo-relative paths using forward slashes
(``profiles/pi30_ascii/models/default.json``). That is right -- it is the
form the repo, the docs and the error messages all use -- but comparing a
forward-slash literal against a *real* path makes the assertion
platform-dependent, because ``str(Path(...))`` renders ``os.sep``.

On Windows that turns every such assertion into ``False is not true``, which is
indistinguishable from a genuine regression. The fix is to normalize the real
side, never the expected literal: ``Path.as_posix()`` emits forward slashes on
every platform, so the assertion means the same thing everywhere.

Use ``posix()`` when comparing a path-ish value against a repo-relative literal,
and ``repo_relative()`` when building the expected value from a path.
"""

from __future__ import annotations

from pathlib import Path


def posix(value: object) -> str:
    """Render a path-ish value with forward slashes on every platform.

    Accepts a ``Path`` or anything already stringified to a path (``str(Path)``
    is what the production loaders store in ``source_path`` and friends).
    """

    return Path(str(value)).as_posix()


def repo_relative(value: object, root: Path) -> str:
    """Return ``value`` relative to ``root``, rendered with forward slashes.

    Falls back to the posix form of the input when it is not under ``root``,
    rather than raising -- a guard that inspects paths outside the repo (temp
    dirs, HA's config dir) should keep working.
    """

    text = str(value)
    try:
        return Path(text).resolve().relative_to(Path(root).resolve()).as_posix()
    except ValueError:
        return Path(text).as_posix()


def path_ends_with(value: object, suffix: str) -> bool:
    """True when ``value`` ends with the forward-slash path ``suffix``."""

    return posix(value).endswith(suffix)


def path_starts_with(value: object, prefix: str) -> bool:
    """True when ``value`` starts with the forward-slash path ``prefix``."""

    return posix(value).startswith(prefix)


def normalize_separators(text: str) -> str:
    """Turn backslashes into forward slashes in a plain (non-Path) string.

    For messages the production code formats by hand, where there is no Path
    object to normalize -- e.g. a status string embedding a directory built with
    ``os.path.join`` or ``str(path)``.
    """

    return text.replace("\\", "/")

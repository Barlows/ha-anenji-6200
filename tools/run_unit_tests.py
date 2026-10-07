"""Run the unit suite on an event loop that implements ``add_reader``.

Why this exists
---------------
``CollectorTcpAcceptor`` watches its listening sockets with ``loop.add_reader``
(see ``collector/transport/tcp_acceptor.py``; that module also documents that it
deliberately does no event-loop monkeypatching). On Windows the default asyncio
policy installs ``ProactorEventLoop``, which has no ``add_reader`` -- the base
class raises ``NotImplementedError``. Every test that starts the acceptor
therefore errored out with ``NotImplementedError``, 92 of them, for a reason that
has nothing to do with the code under test.

Installing ``WindowsSelectorEventLoopPolicy`` on Windows makes those tests drive
the same code path they drive everywhere else, rather than skipping or mocking
the acceptor away.

Scope
-----
The policy is switched **only on Windows**, and only for this process. Every other
platform takes an ordinary ``unittest`` discovery run, so CI behaviour is
unchanged. Nothing in the test suite asks for a Proactor loop or drives
``loop.subprocess_exec``, both of which the selector loop does not provide on
Windows, so nothing loses an ability it was using.

Usage
-----
    python tools/run_unit_tests.py [-q] [pattern ...]

Positional arguments are passed through to ``unittest`` as test-name patterns.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
TESTS_DIR = REPO_ROOT / "tests"


def _install_selector_policy() -> bool:
    """Use the selector loop on Windows; return whether anything was changed."""

    if sys.platform != "win32":
        return False
    policy_type = getattr(asyncio, "WindowsSelectorEventLoopPolicy", None)
    if policy_type is None:  # pragma: no cover - only on a stripped Windows build
        raise SystemExit(
            "asyncio.WindowsSelectorEventLoopPolicy is unavailable, so the "
            "add_reader-dependent tests cannot run on this interpreter."
        )
    asyncio.set_event_loop_policy(policy_type())
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "-q", "--quiet", action="store_true", help="one dot per test instead of a line each"
    )
    parser.add_argument(
        "patterns", nargs="*", help="optional substrings selecting which tests to run"
    )
    args = parser.parse_args(argv)

    switched = _install_selector_policy()
    if switched:
        print(
            "[run_unit_tests] Windows: using the selector event loop so "
            "loop.add_reader() is available.",
            file=sys.stderr,
        )

    # top_level_dir must be the tests directory so `import helpers...` resolves
    # exactly as it does under a bare `unittest discover -s tests`.
    suite = unittest.TestLoader().discover(
        start_dir=str(TESTS_DIR), top_level_dir=str(TESTS_DIR)
    )

    if args.patterns:
        filtered = unittest.TestSuite()
        for test in _flatten(suite):
            if any(pattern in test.id() for pattern in args.patterns):
                filtered.addTest(test)
        suite = filtered

    runner = unittest.TextTestRunner(verbosity=1 if args.quiet else 2)
    result = runner.run(suite)
    return 0 if result.wasSuccessful() else 1


def _flatten(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from _flatten(item)
        else:
            yield item


if __name__ == "__main__":
    raise SystemExit(main())

"""Escalating log level for persistent passive-discovery bootstrap failures.

The Home Assistant package root is held to a small size budget, and the
repeated-bootstrap-failure policy is not lifecycle composition, so it lives
here rather than in ``__init__.py``.
"""

from __future__ import annotations

import logging


logger = logging.getLogger(__name__)

# One failure is worth a full traceback. The same bootstrap failing over and
# over is a persistent condition rather than a surprise, so it is reported at
# warning level instead of burying the log in identical tracebacks.
_BOOTSTRAP_FAILURE_WARNING_THRESHOLD = 3


class BootstrapFailureLog:
    """Report listener-bootstrap failures at a severity matching persistence."""

    def __init__(self) -> None:
        self._consecutive_failures = 0

    def record_failure(self, message: str) -> None:
        """Record one bootstrap failure and log it at the appropriate level.

        Call this from inside the ``except`` block it reports on, so the active
        exception is still available to ``logger.exception``.
        """

        self._consecutive_failures += 1
        if self._consecutive_failures >= _BOOTSTRAP_FAILURE_WARNING_THRESHOLD:
            logger.warning(
                "%s (%d consecutive failures)",
                message,
                self._consecutive_failures,
                exc_info=True,
            )
            return
        logger.exception(message)

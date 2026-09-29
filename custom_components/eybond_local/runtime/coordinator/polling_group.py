"""Composite mixin grouping polling and snapshot concerns.

Groups: Polling, SnapshotProjection, RuntimeProfile, CollectorProfile.
"""

from __future__ import annotations

from .collector_profile import CoordinatorCollectorProfileMixin
from .polling import CoordinatorPollingMixin
from .runtime_profile import CoordinatorRuntimeProfileMixin
from .snapshot_projection import CoordinatorSnapshotProjectionMixin

__all__ = ["CoordinatorPollingMixin"]


class CoordinatorPollingMixin(
    CoordinatorPollingMixin,
    CoordinatorSnapshotProjectionMixin,
    CoordinatorRuntimeProfileMixin,
    CoordinatorCollectorProfileMixin,
):
    """Polling & snapshot: refresh loop, projections, runtime and collector profiles."""

"""Composite mixin grouping polling and snapshot concerns.

Groups: Polling, SnapshotProjection, RuntimeProfile, CollectorProfile.
"""

from __future__ import annotations

from .collector_profile import CoordinatorCollectorProfileMixin
from .polling import CoordinatorPollingMixin
from .runtime_profile import CoordinatorRuntimeProfileMixin
from .snapshot_projection import CoordinatorSnapshotProjectionMixin

__all__ = ["CoordinatorPollingGroupMixin"]


class CoordinatorPollingGroupMixin(
    CoordinatorPollingMixin,
    CoordinatorSnapshotProjectionMixin,
    CoordinatorRuntimeProfileMixin,
    CoordinatorCollectorProfileMixin,
):
    """Polling & snapshot: refresh loop, projections, runtime and collector profiles.

    Named ``...GroupMixin`` rather than reusing ``CoordinatorPollingMixin`` from
    ``.polling``: a composite that reuses its own leaf's name shadows it, so the
    package holds two distinct classes under one importable name and
    ``from .polling_group import CoordinatorPollingMixin`` silently returns the
    composite. Every other composite in this package follows the module-name
    convention (``core``/``CoordinatorCoreMixin``, ``integration``/
    ``CoordinatorIntegrationMixin``); this one now matches too.
    """

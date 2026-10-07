"""Composite mixin grouping management and control concerns.

Groups: Management, ManagementProjection, ControlProjection, OperatingProfile, StrategyTransition.
"""

from __future__ import annotations

from .control_projection import CoordinatorControlProjectionMixin
from .management import CoordinatorManagementMixin
from .management_projection import CoordinatorManagementProjectionMixin
from .operating_profile import CoordinatorOperatingProfileMixin
from .strategy import CoordinatorStrategyTransitionMixin

__all__ = ["CoordinatorManagementGroupMixin"]


class CoordinatorManagementGroupMixin(
    CoordinatorManagementMixin,
    CoordinatorManagementProjectionMixin,
    CoordinatorControlProjectionMixin,
    CoordinatorOperatingProfileMixin,
    CoordinatorStrategyTransitionMixin,
):
    """Management & control: writes, projections, operating profile, strategy transitions.

    Named ``...GroupMixin`` for the same reason as ``polling_group``: reusing the
    leaf's own name would shadow ``.management.CoordinatorManagementMixin``.
    """

"""Composite mixin grouping core lifecycle concerns.

Groups: Lifecycle, Startup, Persistence, Diagnostics.
"""

from __future__ import annotations

from .diagnostics import CoordinatorDiagnosticsMixin
from .lifecycle import CoordinatorLifecycleMixin
from .persistence import CoordinatorPersistenceMixin
from .startup import CoordinatorStartupIdentityMixin

__all__ = ["CoordinatorCoreMixin"]


class CoordinatorCoreMixin(
    CoordinatorLifecycleMixin,
    CoordinatorStartupIdentityMixin,
    CoordinatorPersistenceMixin,
    CoordinatorDiagnosticsMixin,
):
    """Core lifecycle: setup/teardown, startup identity, persistence, diagnostics."""

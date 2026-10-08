"""Composite mixin grouping integration concerns.

Groups: CloudTools, Support, NetworkReconcile, EntityReload, DeviceRegistry, InverterProfile.
"""

from __future__ import annotations

from .cloud_tools import CoordinatorCloudToolsMixin
from .device_registry import CoordinatorDeviceRegistryMixin
from .entity_reload import CoordinatorEntityReloadMixin
from .inverter_profile import CoordinatorInverterProfileMixin
from .network import CoordinatorNetworkReconcileMixin
from .support import CoordinatorSupportMixin

__all__ = ["CoordinatorIntegrationMixin"]


class CoordinatorIntegrationMixin(
    CoordinatorCloudToolsMixin,
    CoordinatorSupportMixin,
    CoordinatorNetworkReconcileMixin,
    CoordinatorEntityReloadMixin,
    CoordinatorDeviceRegistryMixin,
    CoordinatorInverterProfileMixin,
):
    """Integration: cloud tools, support, network, entity reload, device registry, inverter profile."""

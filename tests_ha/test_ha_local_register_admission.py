"""Background evidence admission against real HA imports, without device I/O."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from custom_components.eybond_local.drivers.local_register_evidence import (
    LocalRegisterCollectionAvailability,
)
from custom_components.eybond_local.drivers.local_register_series import LocalRegisterSeriesPlan
from custom_components.eybond_local.runtime.coordinator.support import CoordinatorSupportMixin


async def test_collection_start_rechecks_runtime_availability():
    coordinator = CoordinatorSupportMixin()
    coordinator._runtime = SimpleNamespace(
        local_register_collection_availability=LocalRegisterCollectionAvailability("inverter_unidentified")
    )
    coordinator._local_register_collection = Mock()
    plan = LocalRegisterSeriesPlan(3, 1)
    with pytest.raises(RuntimeError, match="local_register_collection_unavailable"):
        coordinator.start_local_register_collection(plan)
    coordinator._local_register_collection.start.assert_not_called()
    coordinator._runtime.local_register_collection_availability = LocalRegisterCollectionAvailability("ready")
    coordinator.start_local_register_collection(plan)
    coordinator._local_register_collection.start.assert_called_once_with(plan)
    coordinator._runtime.local_register_collection_availability = LocalRegisterCollectionAvailability("read_plan_unavailable")
    with pytest.raises(RuntimeError, match="local_register_collection_unavailable"):
        coordinator.start_local_register_collection(plan)
    assert coordinator._local_register_collection.start.call_count == 1

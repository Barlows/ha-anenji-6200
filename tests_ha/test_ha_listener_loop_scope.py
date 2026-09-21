"""Each isolated HA test owns its event-loop-bound listener lock."""
import asyncio

import pytest

from custom_components.eybond_local.collector.transport import listener


@pytest.mark.parametrize("separate_ha_loop", [1, 2])
async def test_listener_lock_contention_is_local_to_each_ha_loop(hass, separate_ha_loop):
    # Both parametrized cases must actually contend. An uncontended Lock can
    # appear to work on a different loop, hiding cross-test state until CI.
    lock = listener._LISTENERS_LOCK
    queued = asyncio.Event()
    acquired = asyncio.Event()

    async def contender():
        queued.set()
        async with lock:
            acquired.set()

    async with lock:
        task = asyncio.create_task(contender())
        await queued.wait()
        assert not acquired.is_set()
    await task
    assert acquired.is_set()
    assert not lock.locked()

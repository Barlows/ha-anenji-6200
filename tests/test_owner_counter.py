"""Regression tests for listener owner reference counting."""

from __future__ import annotations

from pathlib import Path
import sys
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from custom_components.eybond_local.collector.transport.listener import (
    _SharedEybondListener,
)
from custom_components.eybond_local.collector.transport.owner_counter import (
    OwnerCounter,
)


class OwnerCounterTests(unittest.TestCase):
    def test_empty_ip_owner_is_released_like_any_other(self) -> None:
        # An owner registered with no fixed collector IP owns every incoming
        # collector (see _has_owner_for_remote_ip). If unregistering it leaks,
        # the listener keeps claiming all callbacks until HA restarts.
        counter = OwnerCounter()
        counter.register_payload_owner("")
        counter.register_at_owner("")
        counter.unregister_payload_owner("")
        counter.unregister_at_owner("")
        self.assertEqual(counter._payload_owner_counts, {})
        self.assertEqual(counter._at_owner_counts, {})

    def test_listener_stops_claiming_every_collector_after_empty_owner_leaves(
        self,
    ) -> None:
        listener = _SharedEybondListener(host="127.0.0.1", port=0)
        self.assertFalse(
            listener._has_owner_for_remote_ip(
                listener._payload_owner_counts, "203.0.113.50"
            )
        )
        listener.register_payload_owner("")
        self.assertTrue(
            listener._has_owner_for_remote_ip(
                listener._payload_owner_counts, "203.0.113.50"
            )
        )
        listener.unregister_payload_owner("")
        self.assertFalse(
            listener._has_owner_for_remote_ip(
                listener._payload_owner_counts, "203.0.113.50"
            )
        )

    def test_counts_nest_and_release_in_order(self) -> None:
        counter = OwnerCounter()
        for _ in range(2):
            counter.register_payload_owner("203.0.113.10")
        counter.unregister_payload_owner("203.0.113.10")
        self.assertEqual(counter.get_payload_owner_count("203.0.113.10"), 1)
        counter.unregister_payload_owner("203.0.113.10")
        self.assertEqual(counter._payload_owner_counts, {})


if __name__ == "__main__":
    unittest.main()

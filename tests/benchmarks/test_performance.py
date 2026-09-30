"""Performance benchmarks for critical code paths.

These benchmarks use time.perf_counter() for timing and follow the existing
unittest.TestCase pattern. They are designed to be fast (< 1 second each)
while still providing meaningful performance data.
"""

from __future__ import annotations

import time
import unittest

from custom_components.eybond_local.collector_identity import normalize_pn
from custom_components.eybond_local.connection.connection_policy import (
    _derive_connection_strategy,
)
from custom_components.eybond_local.payload.modbus import crc16_modbus
from custom_components.eybond_local.runtime.poll_scheduler import (
    clamp_interval,
    clamp_poll_interval_seconds,
)


class ModbusCrc16Benchmark(unittest.TestCase):
    """Benchmark CRC16 computation with various payload sizes."""

    def test_crc16_small_payload(self) -> None:
        """Benchmark CRC16 with a small payload (8 bytes)."""
        payload = bytes(range(8))
        iterations = 10000
        start = time.perf_counter()
        for _ in range(iterations):
            crc16_modbus(payload)
        elapsed = time.perf_counter() - start
        avg_ms = (elapsed / iterations) * 1000
        self.assertLess(avg_ms, 0.01, f"CRC16 small payload too slow: {avg_ms:.4f}ms")

    def test_crc16_medium_payload(self) -> None:
        """Benchmark CRC16 with a medium payload (64 bytes)."""
        payload = bytes(range(64))
        iterations = 5000
        start = time.perf_counter()
        for _ in range(iterations):
            crc16_modbus(payload)
        elapsed = time.perf_counter() - start
        avg_ms = (elapsed / iterations) * 1000
        self.assertLess(avg_ms, 0.05, f"CRC16 medium payload too slow: {avg_ms:.4f}ms")

    def test_crc16_large_payload(self) -> None:
        """Benchmark CRC16 with a large payload (256 bytes)."""
        payload = bytes(range(256))
        iterations = 2000
        start = time.perf_counter()
        for _ in range(iterations):
            crc16_modbus(payload)
        elapsed = time.perf_counter() - start
        avg_ms = (elapsed / iterations) * 1000
        self.assertLess(avg_ms, 0.2, f"CRC16 large payload too slow: {avg_ms:.4f}ms")


class PnNormalizationBenchmark(unittest.TestCase):
    """Benchmark PN normalization with various formats."""

    def test_pn_normalization_short(self) -> None:
        """Benchmark PN normalization with short PN."""
        iterations = 10000
        start = time.perf_counter()
        for _ in range(iterations):
            normalize_pn("E5000020000000")
        elapsed = time.perf_counter() - start
        avg_ms = (elapsed / iterations) * 1000
        self.assertLess(avg_ms, 0.01, f"PN normalization short too slow: {avg_ms:.4f}ms")

    def test_pn_normalization_full(self) -> None:
        """Benchmark PN normalization with full PN."""
        iterations = 10000
        start = time.perf_counter()
        for _ in range(iterations):
            normalize_pn("E50000200000000001")
        elapsed = time.perf_counter() - start
        avg_ms = (elapsed / iterations) * 1000
        self.assertLess(avg_ms, 0.01, f"PN normalization full too slow: {avg_ms:.4f}ms")

    def test_pn_normalization_invalid(self) -> None:
        """Benchmark PN normalization with invalid input."""
        iterations = 10000
        start = time.perf_counter()
        for _ in range(iterations):
            normalize_pn("")
        elapsed = time.perf_counter() - start
        avg_ms = (elapsed / iterations) * 1000
        self.assertLess(avg_ms, 0.01, f"PN normalization invalid too slow: {avg_ms:.4f}ms")


class ConnectionStrategyBenchmark(unittest.TestCase):
    """Benchmark connection strategy derivation."""

    def test_strategy_derivation_inbound(self) -> None:
        """Benchmark strategy derivation for inbound connection."""
        iterations = 5000
        start = time.perf_counter()
        for _ in range(iterations):
            _derive_connection_strategy(
                connection_mode="inbound",
                collector_cloud_family="smartess",
                entry_role="collector",
            )
        elapsed = time.perf_counter() - start
        avg_ms = (elapsed / iterations) * 1000
        self.assertLess(avg_ms, 0.05, f"Strategy derivation inbound too slow: {avg_ms:.4f}ms")

    def test_strategy_derivation_callback(self) -> None:
        """Benchmark strategy derivation for callback connection."""
        iterations = 5000
        start = time.perf_counter()
        for _ in range(iterations):
            _derive_connection_strategy(
                connection_mode="callback_on_demand",
                collector_cloud_family="smartess",
                entry_role="collector",
            )
        elapsed = time.perf_counter() - start
        avg_ms = (elapsed / iterations) * 1000
        self.assertLess(avg_ms, 0.05, f"Strategy derivation callback too slow: {avg_ms:.4f}ms")


class PollIntervalBenchmark(unittest.TestCase):
    """Benchmark poll interval clamping."""

    def test_clamp_poll_interval_default(self) -> None:
        """Benchmark poll interval clamping with default value."""
        iterations = 10000
        start = time.perf_counter()
        for _ in range(iterations):
            clamp_poll_interval_seconds(10.0)
        elapsed = time.perf_counter() - start
        avg_ms = (elapsed / iterations) * 1000
        self.assertLess(avg_ms, 0.01, f"Clamp poll interval default too slow: {avg_ms:.4f}ms")

    def test_clamp_poll_interval_boundary(self) -> None:
        """Benchmark poll interval clamping with boundary values."""
        iterations = 10000
        start = time.perf_counter()
        for i in range(iterations):
            clamp_poll_interval_seconds(float(i % 3600))
        elapsed = time.perf_counter() - start
        avg_ms = (elapsed / iterations) * 1000
        self.assertLess(avg_ms, 0.01, f"Clamp poll interval boundary too slow: {avg_ms:.4f}ms")

    def test_clamp_interval(self) -> None:
        """Benchmark generic interval clamping."""
        iterations = 10000
        start = time.perf_counter()
        for i in range(iterations):
            clamp_interval(float(i % 3600), 2.0, 3600.0)
        elapsed = time.perf_counter() - start
        avg_ms = (elapsed / iterations) * 1000
        self.assertLess(avg_ms, 0.01, f"Clamp interval too slow: {avg_ms:.4f}ms")


if __name__ == "__main__":
    unittest.main()

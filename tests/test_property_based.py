"""Property-based tests for EyeBond Local using Hypothesis.

These tests complement the example-based suite by checking universal
properties over generated inputs rather than hand-picked examples:

* Modbus CRC16 consistency and injectivity
* Register decode/encode round-trips
* Session PN normalization idempotence
* Connection strategy derivation validity
* Poll interval clamping bounds

The modules under test are pure (no Home Assistant runtime), so no stubs
are required -- the same import path as the example-based tests.
"""

from __future__ import annotations

from pathlib import Path
import sys
import unittest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from hypothesis import assume, given, settings, strategies as st  # noqa: E402

from custom_components.eybond_local.collector_identity import normalize_pn  # noqa: E402
from custom_components.eybond_local.connection.connection_policy import (  # noqa: E402
    _derive_connection_strategy,
    resolve_connection_strategy,
)
from custom_components.eybond_local.const import (  # noqa: E402
    COLLECTOR_OPERATION_CLOUD_AND_HA,
    COLLECTOR_OPERATION_HA_ONLY,
    CONF_COLLECTOR_OPERATION_MODE,
    CONF_CONNECTION_MODE,
    CONF_CONNECTION_STRATEGY,
    CONF_CONNECTION_STRATEGY_EVIDENCE,
    CONNECTION_STRATEGIES,
    CONNECTION_STRATEGY_CALLBACK_ON_DEMAND,
    CONNECTION_STRATEGY_INBOUND,
)
from custom_components.eybond_local.drivers.capability_codec import (  # noqa: E402
    decode_capability_value,
    encode_capability_words,
)
from custom_components.eybond_local.models import WriteCapability  # noqa: E402
from custom_components.eybond_local.payload.modbus import crc16_modbus  # noqa: E402
from custom_components.eybond_local.runtime.coordinator.poll_projection import (  # noqa: E402
    POLL_INTERVAL_MAX_SECONDS,
    POLL_INTERVAL_MIN_SECONDS,
    clamp_poll_interval_seconds,
)
from custom_components.eybond_local.runtime.poll_scheduler import clamp_interval  # noqa: E402


# ---------------------------------------------------------------------------
# Modbus CRC16
# ---------------------------------------------------------------------------


class ModbusCrc16Tests(unittest.TestCase):
    """Property-based tests for crc16_modbus."""

    @given(data=st.binary(max_size=32))
    @settings(max_examples=50)
    def test_crc16_is_deterministic(self, data: bytes) -> None:
        """Same input always produces the same CRC16 value."""

        self.assertEqual(crc16_modbus(data), crc16_modbus(bytes(data)))

    @given(data=st.binary(max_size=32))
    @settings(max_examples=50)
    def test_crc16_output_is_16_bit(self, data: bytes) -> None:
        """CRC16 output is always in the range [0, 0xFFFF]."""

        crc = crc16_modbus(data)
        self.assertGreaterEqual(crc, 0)
        self.assertLessEqual(crc, 0xFFFF)

    @given(a=st.integers(min_value=0, max_value=255), b=st.integers(min_value=0, max_value=255))
    @settings(max_examples=50)
    def test_different_single_byte_inputs_produce_different_crcs(self, a: int, b: int) -> None:
        """Different single-byte inputs produce different CRC16 values.

        CRC-16/MODBUS is injective over single-byte messages (all 256
        single-byte CRCs are distinct), so this property holds exactly.
        """

        assume(a != b)
        self.assertNotEqual(crc16_modbus(bytes([a])), crc16_modbus(bytes([b])))

    @given(
        a=st.integers(min_value=0, max_value=255),
        b=st.integers(min_value=0, max_value=255),
        c=st.integers(min_value=0, max_value=255),
        d=st.integers(min_value=0, max_value=255),
    )
    @settings(max_examples=50)
    def test_different_two_byte_inputs_produce_different_crcs(
        self, a: int, b: int, c: int, d: int
    ) -> None:
        """Different two-byte inputs produce different CRC16 values.

        CRC-16/MODBUS is injective over the full two-byte message space
        (no collisions among all 65536 two-byte CRCs).
        """

        assume((a, b) != (c, d))
        self.assertNotEqual(
            crc16_modbus(bytes([a, b])),
            crc16_modbus(bytes([c, d])),
        )


# ---------------------------------------------------------------------------
# Register decode/encode round-trip
# ---------------------------------------------------------------------------


class RegisterDecodeRoundTripTests(unittest.TestCase):
    """Property-based round-trip tests for the capability codec.

    Each test starts from raw register words, decodes them to a logical
    value, encodes back to words, and asserts the words are unchanged.
    """

    @given(raw=st.integers(min_value=0, max_value=0xFFFF))
    @settings(max_examples=50)
    def test_u16_round_trip(self, raw: int) -> None:
        """u16: decode then encode reproduces the original register word."""

        cap = WriteCapability(key="k", register=1, value_kind="u16", note="n")
        words = [raw]
        value = decode_capability_value(cap, words)
        self.assertEqual(encode_capability_words(cap, value), words)

    @given(raw=st.integers(min_value=0, max_value=0xFFFF))
    @settings(max_examples=50)
    def test_scaled_u16_round_trip(self, raw: int) -> None:
        """scaled_u16 (divisor=10): decode then encode reproduces the word.

        The decoded value is round(raw/10, 1); encoding multiplies by 10
        and rounds back to the original integer word.
        """

        cap = WriteCapability(
            key="k", register=1, value_kind="scaled_u16", note="n", divisor=10
        )
        words = [raw]
        value = decode_capability_value(cap, words)
        self.assertEqual(encode_capability_words(cap, value), words)

    @given(hour=st.integers(min_value=0, max_value=23), minute=st.integers(min_value=0, max_value=59))
    @settings(max_examples=50)
    def test_time_hhmm_round_trip(self, hour: int, minute: int) -> None:
        """time_hhmm: decode then encode reproduces the original register word."""

        cap = WriteCapability(key="k", register=1, value_kind="time_hhmm", note="n")
        words = [hour * 100 + minute]
        value = decode_capability_value(cap, words)
        self.assertEqual(encode_capability_words(cap, value), words)

    @given(raw=st.integers(min_value=0, max_value=0xFFFFFFFF))
    @settings(max_examples=50)
    def test_u32_round_trip(self, raw: int) -> None:
        """u32: decode then encode reproduces the original register words."""

        cap = WriteCapability(
            key="k",
            register=1,
            value_kind="u32",
            note="n",
            word_count=2,
            combine="u32_high_first",
        )
        words = [(raw >> 16) & 0xFFFF, raw & 0xFFFF]
        value = decode_capability_value(cap, words)
        self.assertEqual(encode_capability_words(cap, value), words)

    @given(bit=st.integers(min_value=0, max_value=1))
    @settings(max_examples=25)
    def test_bool_round_trip(self, bit: int) -> None:
        """bool: decode then encode reproduces the original register word."""

        cap = WriteCapability(key="k", register=1, value_kind="bool", note="n")
        words = [bit]
        value = decode_capability_value(cap, words)
        self.assertEqual(encode_capability_words(cap, value), words)


# ---------------------------------------------------------------------------
# Session PN normalization
# ---------------------------------------------------------------------------


class SessionPnNormalizationTests(unittest.TestCase):
    """Property-based tests for normalize_pn idempotence."""

    @given(
        value=st.one_of(
            st.text(),
            st.none(),
            st.integers(),
            st.floats(allow_nan=False, allow_infinity=False),
            st.booleans(),
        )
    )
    @settings(max_examples=50)
    def test_normalize_pn_is_idempotent(self, value: object) -> None:
        """normalize_pn(normalize_pn(x)) == normalize_pn(x) for any input.

        The function coerces to str and strips whitespace; both operations
        are idempotent, so applying it twice yields the same result.
        """

        once = normalize_pn(value)
        twice = normalize_pn(once)
        self.assertEqual(once, twice)

    @given(value=st.text())
    @settings(max_examples=50)
    def test_normalize_pn_strips_whitespace(self, value: str) -> None:
        """normalize_pn output never has leading or trailing whitespace."""

        normalized = normalize_pn(value)
        self.assertEqual(normalized, normalized.strip())


# ---------------------------------------------------------------------------
# Connection strategy derivation
# ---------------------------------------------------------------------------


_STRATEGY_DATA_KEYS = [
    CONF_CONNECTION_STRATEGY,
    CONF_COLLECTOR_OPERATION_MODE,
    CONF_CONNECTION_MODE,
    CONF_CONNECTION_STRATEGY_EVIDENCE,
]

_STRATEGY_DATA_VALUES = [
    CONNECTION_STRATEGY_INBOUND,
    CONNECTION_STRATEGY_CALLBACK_ON_DEMAND,
    COLLECTOR_OPERATION_HA_ONLY,
    COLLECTOR_OPERATION_CLOUD_AND_HA,
    "callback_listener",
    "manual",
    "known_ip",
    "reboot_reconnect",
    "callback_trigger",
    "user_confirmed_session",
    "",
    "unknown",
]


class ConnectionStrategyDerivationTests(unittest.TestCase):
    """Property-based tests for connection strategy derivation."""

    @given(
        data=st.dictionaries(
            st.sampled_from(_STRATEGY_DATA_KEYS),
            st.sampled_from(_STRATEGY_DATA_VALUES),
            max_size=4,
        )
    )
    @settings(max_examples=50)
    def test_derive_connection_strategy_always_valid(self, data: dict) -> None:
        """_derive_connection_strategy always returns a valid strategy."""

        strategy = _derive_connection_strategy(data, {})
        self.assertIn(strategy, CONNECTION_STRATEGIES)

    @given(
        data=st.dictionaries(
            st.sampled_from(_STRATEGY_DATA_KEYS),
            st.sampled_from(_STRATEGY_DATA_VALUES),
            max_size=4,
        ),
        options=st.dictionaries(
            st.sampled_from(_STRATEGY_DATA_KEYS),
            st.sampled_from(_STRATEGY_DATA_VALUES),
            max_size=4,
        ),
    )
    @settings(max_examples=50)
    def test_resolve_connection_strategy_always_valid(self, data: dict, options: dict) -> None:
        """resolve_connection_strategy always returns a valid strategy."""

        strategy = resolve_connection_strategy(data, options)
        self.assertIn(strategy, CONNECTION_STRATEGIES)


# ---------------------------------------------------------------------------
# Poll interval clamping
# ---------------------------------------------------------------------------


_POLL_INTERVAL_VALUES = st.one_of(
    st.integers(min_value=-10**12, max_value=10**12),
    st.floats(allow_nan=False, allow_infinity=False),
    st.text(),
    st.none(),
    st.booleans(),
)


class PollIntervalClampingTests(unittest.TestCase):
    """Property-based tests for poll interval clamping."""

    @given(value=_POLL_INTERVAL_VALUES)
    @settings(max_examples=50)
    def test_clamp_poll_interval_seconds_within_bounds(self, value: object) -> None:
        """clamp_poll_interval_seconds always returns an int in [MIN, MAX]."""

        result = clamp_poll_interval_seconds(value)
        self.assertIsInstance(result, int)
        self.assertGreaterEqual(result, POLL_INTERVAL_MIN_SECONDS)
        self.assertLessEqual(result, POLL_INTERVAL_MAX_SECONDS)

    @given(
        value=_POLL_INTERVAL_VALUES,
        minimum=st.floats(min_value=0.1, max_value=100.0, allow_nan=False, allow_infinity=False),
        maximum=st.floats(min_value=100.1, max_value=10000.0, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=50)
    def test_clamp_interval_within_bounds(self, value: object, minimum: float, maximum: float) -> None:
        """clamp_interval always returns a float in [minimum, maximum]."""

        result = clamp_interval(value, minimum=minimum, maximum=maximum)
        self.assertIsInstance(result, float)
        self.assertGreaterEqual(result, minimum)
        self.assertLessEqual(result, maximum)


if __name__ == "__main__":
    unittest.main()

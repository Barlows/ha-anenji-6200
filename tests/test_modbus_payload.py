from __future__ import annotations

from pathlib import Path
import asyncio
import sys
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


from custom_components.eybond_local.payload.modbus import (
    ModbusError,
    ModbusSession,
    crc16_modbus,
    is_read_reply_prefix,
    reassemble_split_read_reply,
    recover_read_reply_tail,
    merge_register_bit,
    merge_register_field,
)
from custom_components.eybond_local.link_models import RawSerialLinkRoute


class _TimeoutTransport:
    def __init__(self) -> None:
        self.calls = 0

    async def async_send_payload(self, payload: bytes, *, route) -> bytes:
        self.calls += 1
        raise asyncio.TimeoutError()


class _RawSerialSelectingTransport:
    def __init__(self) -> None:
        self.routes = []

    def select_payload_route(self, route, *, payload_family: str = ""):
        return RawSerialLinkRoute(protocol=payload_family)

    async def async_send_payload(self, payload: bytes, *, route) -> bytes:
        self.routes.append(route)
        frame = bytearray((1, 3, 2, 0x73, 0x00))
        frame.extend(crc16_modbus(frame).to_bytes(2, "little"))
        return bytes(frame)


def _read_reply(slave: int, function: int, value: int = 0x7300) -> bytes:
    frame = bytearray((slave, function, 2, value >> 8, value & 0xFF))
    frame.extend(crc16_modbus(frame).to_bytes(2, "little"))
    return bytes(frame)


def _full_read_reply(slave: int, function: int, values: list[int]) -> bytes:
    frame = bytearray((slave, function, len(values) * 2))
    for value in values:
        frame.extend(value.to_bytes(2, "big"))
    frame.extend(crc16_modbus(frame).to_bytes(2, "little"))
    return bytes(frame)


class _ScriptedTransport:
    def __init__(self, *replies: bytes) -> None:
        self._replies = list(replies)
        self.calls = 0

    async def async_send_payload(self, payload: bytes, *, route) -> bytes:
        self.calls += 1
        return self._replies.pop(0)


class ModbusPayloadTests(unittest.IsolatedAsyncioTestCase):
    async def test_read_holding_timeout_reports_request_timeout(self) -> None:
        transport = _TimeoutTransport()
        session = ModbusSession(
            transport,
            devcode=1,
            collector_addr=255,
            slave_id=1,
        )

        with self.assertRaises(ModbusError) as ctx:
            await session.read_holding(100, 2)

        self.assertEqual(str(ctx.exception), "request_timeout")
        self.assertEqual(transport.calls, 2)

    async def test_read_retries_once_after_a_stray_reply_in_the_poll_slot(self) -> None:
        # Field-observed ``unexpected_slave_id:0`` / ``unexpected_function:0``.
        for bad in (_read_reply(0, 3), _read_reply(1, 0)):
            transport = _ScriptedTransport(bad, _read_reply(1, 3))
            session = ModbusSession(transport, devcode=1, collector_addr=255, slave_id=1)

            self.assertEqual(await session.read_holding(171, 1), [0x7300])
            self.assertEqual(transport.calls, 2)

    async def test_rejected_read_answer_is_logged_with_its_raw_bytes(self) -> None:
        bad = _read_reply(0, 3)
        transport = _ScriptedTransport(bad, _read_reply(1, 3))
        session = ModbusSession(transport, devcode=1, collector_addr=255, slave_id=1)

        with self.assertLogs(
            "custom_components.eybond_local.payload.modbus", level="WARNING"
        ) as captured:
            await session.read_holding(171, 1)

        joined = "\n".join(captured.output)
        self.assertIn("unexpected_slave_id:0", joined)
        self.assertIn(f"bytes={bad.hex()}", joined)
        self.assertIn("attempt=1", joined)
        self.assertIn("address=171 count=1", joined)

    async def test_long_rejected_answer_is_truncated_in_the_log(self) -> None:
        bad = bytes(200)
        transport = _ScriptedTransport(bad, _read_reply(1, 3))
        session = ModbusSession(transport, devcode=1, collector_addr=255, slave_id=1)

        with self.assertLogs(
            "custom_components.eybond_local.payload.modbus", level="WARNING"
        ) as captured:
            await session.read_holding(171, 1)

        line = captured.output[0]
        self.assertIn("len=200", line)
        self.assertIn(bytes(64).hex() + "...", line)
        self.assertNotIn(bytes(65).hex(), line)

    async def test_read_gives_up_after_one_retry_on_a_persistent_wrong_slave(self) -> None:
        transport = _ScriptedTransport(_read_reply(9, 3), _read_reply(9, 3))
        session = ModbusSession(transport, devcode=1, collector_addr=255, slave_id=1)

        with self.assertRaisesRegex(ModbusError, "unexpected_slave_id:9"):
            await session.read_holding(171, 1)
        self.assertEqual(transport.calls, 2)

    async def test_exception_replies_are_not_retried(self) -> None:
        exception_reply = bytearray((1, 0x83, 2))
        exception_reply.extend(crc16_modbus(exception_reply).to_bytes(2, "little"))
        transport = _ScriptedTransport(bytes(exception_reply))
        session = ModbusSession(transport, devcode=1, collector_addr=255, slave_id=1)

        with self.assertRaisesRegex(ModbusError, "exception_code"):
            await session.read_holding(171, 1)
        self.assertEqual(transport.calls, 1)

    async def test_modbus_session_selects_typed_raw_serial_route(self) -> None:
        transport = _RawSerialSelectingTransport()
        session = ModbusSession(
            transport,
            devcode=1,
            collector_addr=255,
            slave_id=1,
        )

        values = await session.read_holding(171, 1)

        self.assertEqual(values, [29440])
        self.assertEqual(
            transport.routes,
            [RawSerialLinkRoute(protocol="modbus_rtu")],
        )


    async def test_truncated_reply_then_leftover_plus_full_reply_is_recovered(self) -> None:
        # Field-observed (SMG 6200, 54-register read = 113-byte reply): the
        # collector returned only the first 20/40/80 bytes, and the retry came back
        # as the leftover bytes followed by the complete next reply
        # (33+113=146, 73+113=186, 93+113=206). Without recovery every such read
        # failed the whole refresh with ``unexpected_slave_id:0`` / ``unexpected_function:0``.
        first = _full_read_reply(1, 3, list(range(54)))
        second_values = [(i * 7) & 0xFFFF for i in range(54)]
        second = _full_read_reply(1, 3, second_values)
        self.assertEqual(len(first), 113)
        for cut in (20, 40, 80):
            transport = _ScriptedTransport(first[:cut], first[cut:] + second)
            session = ModbusSession(transport, devcode=1, collector_addr=255, slave_id=1)

            with self.assertLogs(
                "custom_components.eybond_local.payload.modbus", level="INFO"
            ) as captured:
                values = await session.read_holding(300, 54)

            self.assertEqual(values, second_values, f"cut={cut}")
            self.assertEqual(transport.calls, 2)
            self.assertEqual(session.recovered_read_count, 1)
            self.assertIn(
                f"Recovered Modbus read reply behind {113 - cut} leftover",
                "\n".join(captured.output),
            )

    async def test_recovery_works_on_the_first_attempt_too(self) -> None:
        previous = _full_read_reply(1, 3, [1, 2, 3, 4, 5, 6, 7, 8, 9, 10])
        current_values = [100 + i for i in range(10)]
        current = _full_read_reply(1, 3, current_values)
        transport = _ScriptedTransport(previous[20:] + current)
        session = ModbusSession(transport, devcode=1, collector_addr=255, slave_id=1)

        self.assertEqual(await session.read_holding(100, 10), current_values)
        self.assertEqual(transport.calls, 1)

    async def test_tail_with_bad_crc_is_not_recovered(self) -> None:
        previous = _full_read_reply(1, 3, [1, 2, 3, 4, 5, 6, 7, 8, 9, 10])
        current = bytearray(_full_read_reply(1, 3, [0] * 10))
        current[5] ^= 0xFF  # corrupt a data byte: CRC no longer verifies
        transport = _ScriptedTransport(
            previous[20:] + bytes(current), previous[20:] + bytes(current)
        )
        session = ModbusSession(transport, devcode=1, collector_addr=255, slave_id=1)

        with self.assertRaises(ModbusError):
            await session.read_holding(100, 10)
        self.assertEqual(session.recovered_read_count, 0)

    async def test_tail_for_a_different_slave_is_not_recovered(self) -> None:
        other = _full_read_reply(7, 3, [0] * 10)
        transport = _ScriptedTransport(b"\x00\x01\x02" + other, b"\x00\x01\x02" + other)
        session = ModbusSession(transport, devcode=1, collector_addr=255, slave_id=1)

        with self.assertRaises(ModbusError):
            await session.read_holding(100, 10)
        self.assertEqual(session.recovered_read_count, 0)


    async def test_cut_short_reply_completed_by_the_leftover_only_retry(self) -> None:
        # Byte-for-byte from the real unit (2026-10-20 14:54): a 25-byte read of
        # ten zero registers came back as its first 20 bytes, and the retry as the
        # missing last five (``000000a367``). Together they are the full reply.
        first = bytes.fromhex("0103140000000000000000000000000000000000")
        rest = bytes.fromhex("000000a367")
        transport = _ScriptedTransport(first, rest)
        session = ModbusSession(transport, devcode=1, collector_addr=255, slave_id=1)

        with self.assertLogs(
            "custom_components.eybond_local.payload.modbus", level="INFO"
        ) as captured:
            values = await session.read_holding(100, 10)

        self.assertEqual(values, [0] * 10)
        self.assertEqual(transport.calls, 2)
        self.assertEqual(session.recovered_read_count, 1)
        self.assertIn(
            "Reassembled split Modbus read reply from 20 + 5 byte(s)",
            "\n".join(captured.output),
        )

    async def test_twelve_register_read_split_20_and_9(self) -> None:
        full = _full_read_reply(1, 3, [0] * 12)
        self.assertEqual(len(full), 29)
        transport = _ScriptedTransport(full[:20], full[20:])
        session = ModbusSession(transport, devcode=1, collector_addr=255, slave_id=1)

        self.assertEqual(await session.read_holding(172, 12), [0] * 12)
        self.assertEqual(transport.calls, 2)

    async def test_split_reply_with_non_matching_continuation_still_fails(self) -> None:
        full = _full_read_reply(1, 3, [5] * 10)
        bad_rest = bytearray(full[20:])
        bad_rest[0] ^= 0xFF  # corrupted data: CRC over the joined reply fails
        transport = _ScriptedTransport(full[:20], bytes(bad_rest))
        session = ModbusSession(transport, devcode=1, collector_addr=255, slave_id=1)

        with self.assertRaises(ModbusError):
            await session.read_holding(100, 10)
        self.assertEqual(session.recovered_read_count, 0)

    async def test_continuation_of_the_wrong_length_is_not_joined(self) -> None:
        full = _full_read_reply(1, 3, [5] * 10)
        transport = _ScriptedTransport(full[:20], full[20:] + b"\x00")
        session = ModbusSession(transport, devcode=1, collector_addr=255, slave_id=1)

        with self.assertRaises(ModbusError):
            await session.read_holding(100, 10)
        self.assertEqual(session.recovered_read_count, 0)

    async def test_prefix_is_not_held_across_separate_reads(self) -> None:
        # A cut-short answer from one read must never complete a different read.
        full = _full_read_reply(1, 3, [5] * 10)
        transport = _ScriptedTransport(
            full[:20], b"\x00" * 7,  # first read: prefix, then junk -> fails
            full[20:], full[20:],  # second read: lone tail twice -> must fail
        )
        session = ModbusSession(transport, devcode=1, collector_addr=255, slave_id=1)

        with self.assertRaises(ModbusError):
            await session.read_holding(100, 10)
        with self.assertRaises(ModbusError):
            await session.read_holding(100, 10)
        self.assertEqual(session.recovered_read_count, 0)


class SplitReadReplyHelperTests(unittest.TestCase):
    def test_prefix_detection(self) -> None:
        full = _full_read_reply(1, 3, [1, 2, 3, 4, 5, 6, 7, 8, 9, 10])
        self.assertTrue(is_read_reply_prefix(full[:20], slave_id=1, count=10))
        self.assertTrue(is_read_reply_prefix(full[:3], slave_id=1, count=10))
        self.assertFalse(is_read_reply_prefix(full[:2], slave_id=1, count=10))
        self.assertFalse(is_read_reply_prefix(full, slave_id=1, count=10))
        self.assertFalse(is_read_reply_prefix(full[:20], slave_id=2, count=10))
        self.assertFalse(is_read_reply_prefix(full[:20], slave_id=1, count=9))
        self.assertFalse(
            is_read_reply_prefix(full[:20], slave_id=1, count=10, function=0x04)
        )

    def test_reassembly_requires_exact_length_and_crc(self) -> None:
        full = _full_read_reply(1, 3, [1, 2, 3, 4, 5, 6, 7, 8, 9, 10])
        self.assertEqual(
            reassemble_split_read_reply(full[:20], full[20:], slave_id=1, count=10), full
        )
        self.assertIsNone(
            reassemble_split_read_reply(full[:20], full[20:-1], slave_id=1, count=10)
        )
        self.assertIsNone(
            reassemble_split_read_reply(full[:19], full[20:], slave_id=1, count=10)
        )
        self.assertIsNone(
            reassemble_split_read_reply(b"\x09" + full[1:20], full[20:], slave_id=1, count=10)
        )


class RecoverReadReplyTailTests(unittest.TestCase):
    def test_returns_none_when_not_longer_than_a_reply(self) -> None:
        reply = _full_read_reply(1, 3, [1, 2])
        self.assertIsNone(recover_read_reply_tail(reply, slave_id=1, count=2))
        self.assertIsNone(recover_read_reply_tail(reply[:-1], slave_id=1, count=2))

    def test_returns_the_trailing_reply(self) -> None:
        reply = _full_read_reply(1, 3, [1, 2])
        self.assertEqual(
            recover_read_reply_tail(b"\xde\xad" + reply, slave_id=1, count=2), reply
        )

    def test_requires_slave_function_and_byte_count_to_match(self) -> None:
        reply = _full_read_reply(1, 3, [1, 2])
        junk = b"\x00\x00\x00"
        self.assertIsNone(recover_read_reply_tail(junk + reply, slave_id=2, count=2))
        self.assertIsNone(
            recover_read_reply_tail(junk + reply, slave_id=1, count=2, function=0x04)
        )
        self.assertIsNone(recover_read_reply_tail(junk + reply, slave_id=1, count=3))

    def test_input_register_replies_are_recovered_too(self) -> None:
        reply = _full_read_reply(1, 4, [9])
        self.assertEqual(
            recover_read_reply_tail(b"\x01" + reply, slave_id=1, count=1, function=0x04),
            reply,
        )

    def test_unsupported_function_or_count_returns_none(self) -> None:
        reply = _full_read_reply(1, 3, [1])
        self.assertIsNone(recover_read_reply_tail(b"\x00" + reply, slave_id=1, count=0))
        self.assertIsNone(
            recover_read_reply_tail(b"\x00" + reply, slave_id=1, count=1, function=0x06)
        )


class MergeRegisterBitTests(unittest.TestCase):
    def test_set_each_boundary_bit_preserves_other_bits(self) -> None:
        for bit_index in (0, 15):
            mask = 1 << bit_index
            merged = merge_register_bit(0x0000, bit_index, 1)
            self.assertEqual(merged, mask)
            # All other 15 bits stay zero.
            self.assertEqual(merged & ~mask, 0)

    def test_clear_each_boundary_bit_preserves_other_bits(self) -> None:
        for bit_index in (0, 15):
            mask = 1 << bit_index
            merged = merge_register_bit(0xFFFF, bit_index, 0)
            self.assertEqual(merged, 0xFFFF & ~mask)
            # All other 15 bits stay set.
            self.assertEqual(merged | mask, 0xFFFF)

    def test_set_bit_keeps_surrounding_bits(self) -> None:
        # 0xABCE has bit 0 == 0; setting it yields 0xABCF and touches nothing else.
        self.assertEqual(merge_register_bit(0xABCE, 0, 1), 0xABCF)
        # Setting an already-set bit is a no-op.
        self.assertEqual(merge_register_bit(0xABCF, 0, 1), 0xABCF)

    def test_clear_bit_keeps_surrounding_bits(self) -> None:
        self.assertEqual(merge_register_bit(0xABCF, 0, 1), 0xABCF)
        self.assertEqual(merge_register_bit(0xABCF, 0, 0), 0xABCE)

    def test_result_is_clamped_to_16_bits(self) -> None:
        self.assertLessEqual(merge_register_bit(0xFFFF, 15, 1), 0xFFFF)


class MergeRegisterFieldTests(unittest.TestCase):
    def test_replaces_only_masked_field(self) -> None:
        # Mask bits 4..7; write 0xA0 into them, keep the rest of 0x1234.
        merged = merge_register_field(0x1234, 0x00F0, 0x00A0)
        self.assertEqual(merged, 0x12A4)

    def test_field_bits_outside_mask_are_ignored(self) -> None:
        # field carries stray high bits; only masked bits land.
        merged = merge_register_field(0x0000, 0x000F, 0xFFF5)
        self.assertEqual(merged, 0x0005)

    def test_single_bit_field_matches_merge_register_bit(self) -> None:
        for bit_index in range(16):
            mask = 1 << bit_index
            self.assertEqual(
                merge_register_field(0x5555, mask, mask),
                merge_register_bit(0x5555, bit_index, 1),
            )
            self.assertEqual(
                merge_register_field(0x5555, mask, 0),
                merge_register_bit(0x5555, bit_index, 0),
            )


if __name__ == "__main__":
    unittest.main()

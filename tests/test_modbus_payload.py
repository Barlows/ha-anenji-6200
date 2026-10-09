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

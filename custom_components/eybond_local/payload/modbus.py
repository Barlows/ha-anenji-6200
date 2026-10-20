"""Minimal Modbus RTU helpers routed over a generic payload link."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import logging

from ..link_models import EybondLinkRoute, LinkRoute
from ..link_transport import (
    PayloadLinkTransport,
    async_send_payload,
    select_payload_route,
)

_logger = logging.getLogger(__name__)

# Enough to see a whole short answer and the start of a long one in a log line.
_BAD_ANSWER_LOG_BYTES = 64


class ModbusError(Exception):
    """Raised when a Modbus RTU response cannot be decoded."""


@dataclass(frozen=True, slots=True)
class ModbusReadRequestFrame:
    """Decoded Modbus RTU read request frame (function 0x03 or 0x04)."""

    slave_id: int
    function_code: int
    address: int
    count: int


@dataclass(frozen=True, slots=True)
class ModbusWriteRequestFrame:
    """Decoded Modbus RTU write request frame (function 0x06 or 0x10)."""

    slave_id: int
    function_code: int
    address: int
    values: tuple[int, ...]

    @property
    def count(self) -> int:
        """Return number of written registers."""

        return len(self.values)


def crc16_modbus(data: bytes) -> int:
    """Compute Modbus CRC16."""

    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 0x0001:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return crc & 0xFFFF


def to_signed_16(value: int) -> int:
    """Convert an unsigned 16-bit register into a signed integer."""

    return value - 0x10000 if value >= 0x8000 else value


def merge_register_field(current: int, mask: int, field: int) -> int:
    """Return one 16-bit register with only the masked bits replaced by ``field``.

    Read-modify-write primitive shared by SMG bitmask capabilities and the raw
    diagnostic ``write_bit`` command, so there is one merge implementation. Bits
    of ``field`` outside ``mask`` are ignored; the result is clamped to 16 bits.
    """

    masked = mask & 0xFFFF
    kept = int(current) & 0xFFFF & ~masked
    return (kept | (int(field) & masked)) & 0xFFFF


def merge_register_bit(current: int, bit_index: int, bit_value: int) -> int:
    """Return one 16-bit register with a single bit set or cleared.

    Single-bit case of :func:`merge_register_field`. ``bit_index`` is ``0..15``
    and ``bit_value`` is ``0`` or ``1``; the other 15 bits are preserved.
    """

    mask = 1 << bit_index
    field = (bit_value & 1) << bit_index
    return merge_register_field(current, mask, field)


def decode_read_request(frame: bytes) -> ModbusReadRequestFrame | None:
    """Decode one Modbus RTU read request frame when valid."""

    if len(frame) != 8:
        return None
    function_code = frame[1]
    if function_code not in {0x03, 0x04}:
        return None
    crc_received = int.from_bytes(frame[-2:], "little")
    crc_expected = crc16_modbus(frame[:-2])
    if crc_received != crc_expected:
        return None
    return ModbusReadRequestFrame(
        slave_id=frame[0],
        function_code=function_code,
        address=int.from_bytes(frame[2:4], "big"),
        count=int.from_bytes(frame[4:6], "big"),
    )


def decode_write_request(frame: bytes) -> ModbusWriteRequestFrame | None:
    """Decode one Modbus RTU write request frame when valid."""

    if len(frame) < 8:
        return None
    function_code = frame[1]
    crc_received = int.from_bytes(frame[-2:], "little")
    crc_expected = crc16_modbus(frame[:-2])
    if crc_received != crc_expected:
        return None

    if function_code == 0x06 and len(frame) == 8:
        return ModbusWriteRequestFrame(
            slave_id=frame[0],
            function_code=function_code,
            address=int.from_bytes(frame[2:4], "big"),
            values=(int.from_bytes(frame[4:6], "big"),),
        )

    if function_code != 0x10 or len(frame) < 9:
        return None

    address = int.from_bytes(frame[2:4], "big")
    register_count = int.from_bytes(frame[4:6], "big")
    byte_count = frame[6]
    if byte_count != register_count * 2:
        return None
    if len(frame) != 9 + byte_count:
        return None

    values: list[int] = []
    register_bytes = frame[7:-2]
    for offset in range(0, len(register_bytes), 2):
        values.append(int.from_bytes(register_bytes[offset : offset + 2], "big"))
    return ModbusWriteRequestFrame(
        slave_id=frame[0],
        function_code=function_code,
        address=address,
        values=tuple(values),
    )


def build_read_request(
    slave_id: int,
    address: int,
    count: int,
    *,
    function: int = 0x03,
) -> bytes:
    """Build a Modbus RTU read registers request (function 0x03 or 0x04)."""

    if function not in (0x03, 0x04):
        raise ValueError(f"unsupported_read_function:{function}")
    payload = bytearray(
        [
            slave_id,
            function,
            (address >> 8) & 0xFF,
            address & 0xFF,
            (count >> 8) & 0xFF,
            count & 0xFF,
        ]
    )
    crc = crc16_modbus(payload)
    payload.extend(crc.to_bytes(2, "little"))
    return bytes(payload)


def build_read_holding_request(slave_id: int, address: int, count: int) -> bytes:
    """Build a Modbus RTU read holding registers request."""

    return build_read_request(slave_id, address, count, function=0x03)


def build_write_multiple_request(slave_id: int, address: int, values: list[int]) -> bytes:
    """Build a Modbus RTU write multiple registers request."""

    register_count = len(values)
    byte_count = register_count * 2
    payload = bytearray(
        [
            slave_id,
            0x10,
            (address >> 8) & 0xFF,
            address & 0xFF,
            (register_count >> 8) & 0xFF,
            register_count & 0xFF,
            byte_count,
        ]
    )
    for value in values:
        payload.extend(value.to_bytes(2, "big", signed=False))
    crc = crc16_modbus(payload)
    payload.extend(crc.to_bytes(2, "little"))
    return bytes(payload)


def build_write_single_request(slave_id: int, address: int, value: int) -> bytes:
    """Build a Modbus RTU write single holding register request."""

    payload = bytearray(
        [
            slave_id,
            0x06,
            (address >> 8) & 0xFF,
            address & 0xFF,
            (int(value) >> 8) & 0xFF,
            int(value) & 0xFF,
        ]
    )
    crc = crc16_modbus(payload)
    payload.extend(crc.to_bytes(2, "little"))
    return bytes(payload)


def parse_read_registers_response(
    frame: bytes,
    *,
    slave_id: int,
    count: int,
    function: int = 0x03,
) -> list[int]:
    """Decode a Modbus RTU read registers response (function 0x03 or 0x04)."""

    if function not in (0x03, 0x04):
        raise ValueError(f"unsupported_read_function:{function}")
    if len(frame) < 5:
        raise ModbusError("response_too_short")

    if frame[0] != slave_id:
        raise ModbusError(f"unexpected_slave_id:{frame[0]}")

    function_code = frame[1]
    if function_code == (function | 0x80) and len(frame) >= 5:
        raise ModbusError(f"exception_code:{frame[2]}")
    if function_code != function:
        raise ModbusError(f"unexpected_function:{function_code}")

    expected_byte_count = count * 2
    byte_count = frame[2]
    if byte_count != expected_byte_count:
        raise ModbusError(f"unexpected_byte_count:{byte_count}")

    expected_length = 3 + byte_count + 2
    if len(frame) != expected_length:
        raise ModbusError(f"unexpected_length:{len(frame)}")

    crc_received = int.from_bytes(frame[-2:], "little")
    crc_expected = crc16_modbus(frame[:-2])
    if crc_received != crc_expected:
        raise ModbusError("crc_mismatch")

    registers: list[int] = []
    payload = frame[3:-2]
    for offset in range(0, len(payload), 2):
            registers.append(int.from_bytes(payload[offset : offset + 2], "big"))
    return registers


def parse_read_holding_response(frame: bytes, *, slave_id: int, count: int) -> list[int]:
    """Decode a Modbus RTU read holding registers response."""

    return parse_read_registers_response(
        frame, slave_id=slave_id, count=count, function=0x03
    )


def recover_read_reply_tail(
    frame: bytes,
    *,
    slave_id: int,
    count: int,
    function: int = 0x03,
) -> bytes | None:
    """Return the complete reply at the END of an over-long answer, if there is one.

    Field-observed on EyeBond collectors: the collector sometimes hands back only
    the first 20/40/80 bytes of an inverter reply. The rest of those bytes then
    arrive at the front of the NEXT request's answer, ahead of that request's own
    complete reply (for example a 113-byte read answered by ``33 leftover bytes +
    the full 113-byte reply = 146``). Judged by its first bytes such an answer
    looks like a wrong slave id or function, although the reply the caller asked
    for is intact at the end.

    The tail is only accepted when it has the exact length for this read, the
    right slave, function and byte count, AND a verifying Modbus CRC, so leftover
    bytes can never be mistaken for data.
    """

    if function not in (0x03, 0x04) or count <= 0:
        return None
    expected_length = 3 + count * 2 + 2
    if len(frame) <= expected_length:
        return None
    tail = frame[-expected_length:]
    if tail[0] != slave_id or tail[1] != function or tail[2] != count * 2:
        return None
    if int.from_bytes(tail[-2:], "little") != crc16_modbus(tail[:-2]):
        return None
    return tail


def is_read_reply_prefix(
    frame: bytes,
    *,
    slave_id: int,
    count: int,
    function: int = 0x03,
) -> bool:
    """Return whether ``frame`` is the START of a read reply that is cut short.

    True only for a non-empty strict prefix of the reply layout this read expects:
    the bytes present agree with the right slave, function and byte count, and
    there are fewer of them than a complete reply needs.
    """

    if function not in (0x03, 0x04) or count <= 0:
        return False
    expected_length = 3 + count * 2 + 2
    if not 3 <= len(frame) < expected_length:
        return False
    return frame[0] == slave_id and frame[1] == function and frame[2] == count * 2


def reassemble_split_read_reply(
    prefix: bytes,
    continuation: bytes,
    *,
    slave_id: int,
    count: int,
    function: int = 0x03,
) -> bytes | None:
    """Join a cut-short read reply with the bytes that completed it, if they fit.

    Field-observed: the collector returned the first 20 bytes of a 25- or 29-byte
    reply, and answered the retry with only the missing trailing 5 or 9 bytes
    (``000000a367``). Joined, the two are exactly the complete reply. The result is
    accepted only when ``prefix`` is a genuine prefix for this read, the joined
    length is exactly the expected one, and the Modbus CRC verifies.
    """

    if not is_read_reply_prefix(prefix, slave_id=slave_id, count=count, function=function):
        return None
    joined = prefix + continuation
    if len(joined) != 3 + count * 2 + 2:
        return None
    if int.from_bytes(joined[-2:], "little") != crc16_modbus(joined[:-2]):
        return None
    return joined


def parse_write_single_response(
    frame: bytes,
    *,
    slave_id: int,
    address: int,
) -> int:
    """Validate a Modbus RTU write-single response and return the echoed/status value.

    Standard Modbus FC06 responses echo the requested value. Some legacy
    SmartESS/EyeBond collectors have been observed returning a different
    value while still acknowledging the written register with a valid CRC.
    Callers that need strict value confirmation should read the register back
    after this acknowledgement.
    """

    if len(frame) < 5:
        raise ModbusError("response_too_short")
    if frame[0] != slave_id:
        raise ModbusError(f"unexpected_slave_id:{frame[0]}")
    if frame[1] == 0x86:
        crc_received = int.from_bytes(frame[-2:], "little")
        crc_expected = crc16_modbus(frame[:-2])
        if crc_received != crc_expected:
            raise ModbusError("crc_mismatch")
        raise ModbusError(f"exception_code:{frame[2]}")
    if len(frame) != 8:
        raise ModbusError(f"unexpected_length:{len(frame)}")
    if frame[1] != 0x06:
        raise ModbusError(f"unexpected_function:{frame[1]}")

    crc_received = int.from_bytes(frame[-2:], "little")
    crc_expected = crc16_modbus(frame[:-2])
    if crc_received != crc_expected:
        raise ModbusError("crc_mismatch")

    address_received = int.from_bytes(frame[2:4], "big")
    if address_received != address:
        raise ModbusError(f"unexpected_address:{address_received}")
    return int.from_bytes(frame[4:6], "big")


def parse_write_multiple_response(
    frame: bytes,
    *,
    slave_id: int,
    address: int,
    register_count: int,
) -> None:
    """Validate a Modbus RTU write multiple registers response."""

    if len(frame) < 5:
        raise ModbusError("response_too_short")
    if frame[0] != slave_id:
        raise ModbusError(f"unexpected_slave_id:{frame[0]}")
    if frame[1] == 0x90:
        crc_received = int.from_bytes(frame[-2:], "little")
        crc_expected = crc16_modbus(frame[:-2])
        if crc_received != crc_expected:
            raise ModbusError("crc_mismatch")
        raise ModbusError(f"exception_code:{frame[2]}")
    if len(frame) != 8:
        raise ModbusError(f"unexpected_length:{len(frame)}")
    if frame[1] != 0x10:
        raise ModbusError(f"unexpected_function:{frame[1]}")

    crc_received = int.from_bytes(frame[-2:], "little")
    crc_expected = crc16_modbus(frame[:-2])
    if crc_received != crc_expected:
        raise ModbusError("crc_mismatch")

    address_received = int.from_bytes(frame[2:4], "big")
    count_received = int.from_bytes(frame[4:6], "big")
    if address_received != address:
        raise ModbusError(f"unexpected_address:{address_received}")
    if count_received != register_count:
        raise ModbusError(f"unexpected_register_count:{count_received}")


class ModbusSession:
    """Modbus RTU session routed through one generic payload link."""

    def __init__(
        self,
        transport: PayloadLinkTransport,
        *,
        route: LinkRoute | None = None,
        devcode: int | None = None,
        collector_addr: int | None = None,
        slave_id: int,
    ) -> None:
        self._transport = transport
        if route is None:
            if devcode is None or collector_addr is None:
                raise TypeError("modbus_route_required")
            route = EybondLinkRoute(
                devcode=devcode,
                collector_addr=collector_addr,
            )
        self._route = route
        self._slave_id = slave_id
        self.recovered_read_count = 0

    def _selected_route(self) -> LinkRoute:
        """Resolve the logical Modbus target through the active link adapter.

        EyeBond framed sessions keep the catalog's tunnel route.  AT callback
        sessions explicitly translate it to a raw-serial Modbus route.  The
        transport -- not the driver or cloud metadata -- owns that wire choice.
        """

        return select_payload_route(
            self._transport,
            self._route,
            payload_family="modbus_rtu",
        )

    def _note_recovered_read(
        self,
        message: str,
        message_args: tuple[int, ...],
        *,
        function: int,
        address: int,
        count: int,
        attempt: int,
        detail: str,
    ) -> None:
        """Count a recovered read and log it (INFO for the first and every 25th)."""

        self.recovered_read_count += 1
        log = (
            _logger.info
            if self.recovered_read_count == 1 or self.recovered_read_count % 25 == 0
            else _logger.debug
        )
        log(
            message + ": function=%d slave=%d address=%d count=%d attempt=%d "
            "bytes=%s recovered_total=%d",
            *message_args,
            function,
            self._slave_id,
            address,
            count,
            attempt,
            detail,
            self.recovered_read_count,
        )

    async def read_registers(
        self,
        address: int,
        count: int,
        *,
        function: int = 0x03,
    ) -> list[int]:
        """Read holding (0x03) or input (0x04) registers from the inverter."""

        request = build_read_request(self._slave_id, address, count, function=function)
        last_error: ModbusError | None = None
        held_prefix: bytes | None = None
        for attempt in range(2):
            try:
                response = await async_send_payload(
                    self._transport,
                    request,
                    route=self._selected_route(),
                )
            except asyncio.TimeoutError as exc:
                last_error = ModbusError("request_timeout")
                if attempt == 0:
                    await asyncio.sleep(0.15)
                    continue
                raise last_error from exc
            try:
                return parse_read_registers_response(
                    response,
                    slave_id=self._slave_id,
                    count=count,
                    function=function,
                )
            except ModbusError as exc:
                tail = recover_read_reply_tail(
                    response,
                    slave_id=self._slave_id,
                    count=count,
                    function=function,
                )
                if tail is not None:
                    # Leftover bytes of an earlier truncated reply preceded this
                    # request's own, CRC-verified reply: use it, no retry needed.
                    self._note_recovered_read(
                        "Recovered Modbus read reply behind %d leftover byte(s)",
                        (len(response) - len(tail),),
                        function=function,
                        address=address,
                        count=count,
                        attempt=attempt + 1,
                        detail=response[: len(response) - len(tail)][:16].hex(),
                    )
                    return parse_read_registers_response(
                        tail,
                        slave_id=self._slave_id,
                        count=count,
                        function=function,
                    )
                if held_prefix is not None:
                    joined = reassemble_split_read_reply(
                        held_prefix,
                        response,
                        slave_id=self._slave_id,
                        count=count,
                        function=function,
                    )
                    if joined is not None:
                        # The first answer was cut short and this one carries
                        # exactly the missing tail: together a verified reply.
                        self._note_recovered_read(
                            "Reassembled split Modbus read reply from %d + %d byte(s)",
                            (len(held_prefix), len(response)),
                            function=function,
                            address=address,
                            count=count,
                            attempt=attempt + 1,
                            detail=held_prefix[:8].hex() + "+" + response[:8].hex(),
                        )
                        return parse_read_registers_response(
                            joined,
                            slave_id=self._slave_id,
                            count=count,
                            function=function,
                        )
                if is_read_reply_prefix(
                    response, slave_id=self._slave_id, count=count, function=function
                ):
                    held_prefix = response
                last_error = exc
                # Field diagnostics: the error text alone (``unexpected_slave_id:0``)
                # cannot show what actually arrived in the poll's slot.
                _logger.warning(
                    "Modbus read answer rejected: %s function=%d slave=%d "
                    "address=%d count=%d attempt=%d len=%d bytes=%s%s",
                    exc,
                    function,
                    self._slave_id,
                    address,
                    count,
                    attempt + 1,
                    len(response),
                    response[:_BAD_ANSWER_LOG_BYTES].hex(),
                    "..." if len(response) > _BAD_ANSWER_LOG_BYTES else "",
                )
                if attempt == 0 and _is_retryable_read_error(exc):
                    await asyncio.sleep(0.15)
                    continue
                raise
        raise last_error or ModbusError("read_failed")

    async def read_holding(self, address: int, count: int) -> list[int]:
        """Read holding registers from the inverter."""

        return await self.read_registers(address, count, function=0x03)

    async def read_input(self, address: int, count: int) -> list[int]:
        """Read input registers from the inverter."""

        return await self.read_registers(address, count, function=0x04)

    async def write_holding(self, address: int, values: list[int]) -> None:
        """Write one or more holding registers to the inverter."""

        request = build_write_multiple_request(self._slave_id, address, values)
        try:
            response = await async_send_payload(
                self._transport,
                request,
                route=self._selected_route(),
            )
        except asyncio.TimeoutError as exc:
            raise ModbusError("request_timeout") from exc
        parse_write_multiple_response(
            response,
            slave_id=self._slave_id,
            address=address,
            register_count=len(values),
        )

    async def write_single_holding(self, address: int, value: int) -> int:
        """Write one holding register using Modbus function code 0x06."""

        request = build_write_single_request(self._slave_id, address, value)
        try:
            response = await async_send_payload(
                self._transport,
                request,
                route=self._selected_route(),
            )
        except asyncio.TimeoutError as exc:
            raise ModbusError("request_timeout") from exc
        return parse_write_single_response(
            response,
            slave_id=self._slave_id,
            address=address,
        )


def _is_retryable_read_error(error: ModbusError) -> bool:
    """Return whether one Modbus read error looks transient enough to retry once."""

    text = str(error)
    # A wrong slave id or function byte on an otherwise well-formed answer is
    # what a stray collector reply looks like when it lands in the slot of a
    # real poll (field-observed ``unexpected_slave_id:0`` / ``unexpected_function:0``,
    # a few per hour, each of which cost a whole refresh). A repeat of the read
    # recovers them; a genuinely wrong slave id fails the same way twice.
    return text in {
        "response_too_short",
        "crc_mismatch",
    } or text.startswith(
        ("unexpected_length:", "unexpected_slave_id:", "unexpected_function:")
    )

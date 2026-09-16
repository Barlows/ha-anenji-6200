"""Read-only FC4 short commands for the captured URTU1920 checksum dialect.

Commands are ASCII plus a binary address and CR, not PI30 or a raw UART route.
MP/Q1/MD shapes are corroborated by two saved device exchanges. Q1 field widths
come from the vendor's 19B4 segment 1; decoding never shifts columns by magnitude.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import re

from ..link_models import EybondLinkRoute
from ..link_transport import PayloadLinkTransport, async_send_payload


READ_COMMANDS = ("MP", "Q1", "MD")
PROTOCOL_ID = "EYBOND_SHORT_ASCII"
WIRE_DIALECT = "urtu1920_checksum"


class ShortAsciiError(ValueError):
    """A response does not establish the supported wire/field contract."""


def build_short_ascii_request(command: str, device_addr: int) -> bytes:
    if type(command) is not str or command not in READ_COMMANDS:
        raise ShortAsciiError("short_ascii_read_command_unsupported")
    if type(device_addr) is not int or not 0 <= device_addr <= 255:
        raise ShortAsciiError("short_ascii_address_invalid")
    return command.encode("ascii") + bytes([device_addr]) + b"\r"


def _envelope(frame: bytes, *, length: int, status: bool) -> None:
    if type(frame) is not bytes or len(frame) != length:
        raise ShortAsciiError("short_ascii_response_length")
    if frame[-1:] != b"\r" or (status and frame[0] != 1):
        raise ShortAsciiError("short_ascii_response_envelope")


def parse_md(frame: bytes) -> dict[str, object]:
    _envelope(frame, length=24, status=False)
    # The vendor exposes a 20-byte SOFTWARE VERSION and no inverter serial.
    # Do not convert the firmware prefix into a retail model or collector PN.
    if frame[20:] != b"  \x00\r" or not re.fullmatch(
        rb"S[0-9]-[0-9]{4}-[0-9]{6}-V[0-9]\.[A-Z0-9]{2}", frame[:20],
    ):
        raise ShortAsciiError("short_ascii_firmware_shape")
    return {
        "short_ascii_firmware": frame[:20].decode("ascii"),
        "protocol_id": PROTOCOL_ID,
        "short_ascii_wire_dialect": WIRE_DIALECT,
        "short_ascii_md_length": len(frame),
    }


def parse_mp(frame: bytes) -> dict[str, object]:
    _envelope(frame, length=38, status=True)
    # This binary settings block participates in shape qualification only.
    # Its body may contain CR and arbitrary high bytes; never strip/truncate it.
    return {"short_ascii_mp_length": len(frame)}


def _decimal(field: bytes, pattern: bytes) -> float:
    if re.fullmatch(pattern, field) is None:
        raise ShortAsciiError("short_ascii_q1_field_format")
    return float(field.decode("ascii"))


def parse_q1(frame: bytes) -> dict[str, object]:
    _envelope(frame, length=51, status=True)
    # Sum of unsigned body bytes, excluding status, checksum and final CR.
    # Check FIRST: binary checksum bytes may themselves equal CR/ASCII/NUL.
    if sum(frame[1:-3]) & 0xFFFF != int.from_bytes(frame[-3:-1], "big"):
        raise ShortAsciiError("short_ascii_q1_checksum")
    body = frame[1:-3]
    if any(body[index] != 32 for index in (5, 11, 17, 21, 26, 31, 36)):
        raise ShortAsciiError("short_ascii_q1_separator")
    # The fault-voltage column also carries "04 03"/"04 04" on both captures.
    # Its meaning is not established: preserve it in evidence, not as a sensor.
    if any(byte < 32 or byte > 126 for byte in body[6:11]):
        raise ShortAsciiError("short_ascii_q1_fault_field")
    flags = body[37:44]
    if re.fullmatch(rb"[01]{7}", flags) is None:
        raise ShortAsciiError("short_ascii_q1_flags")
    return {
        "short_ascii_q1_length": len(frame),
        "grid_voltage": _decimal(body[0:5], rb"[0-9]{3}\.[0-9]"),
        "output_voltage": _decimal(body[12:17], rb"[0-9]{3}\.[0-9]"),
        "load_percent": _decimal(body[18:21], rb"[0-9]{3}"),
        "output_frequency": _decimal(body[22:26], rb"[0-9]{2}\.[0-9]"),
        "battery_reference_voltage": _decimal(body[27:31], rb"[0-9]{2}\.[0-9]"),
        "temperature": _decimal(body[32:36], rb"(?:[0-9]{2}|-[0-9])\.[0-9]"),
        "short_ascii_status_flags": flags.decode("ascii"),
        "short_ascii_fault_code": body[44],
        "inverter_fault": flags[1] == 49,
        "grid_available": flags[2] == 48,
        "short_ascii_mains_input_connected": flags[3] == 48,
        "battery_low": flags[4] == 49,
        "pv_controller_present": flags[5] == 49,
    }


@dataclass(frozen=True, slots=True)
class ShortAsciiSession:
    transport: PayloadLinkTransport
    route: EybondLinkRoute
    device_addr: int
    timeout: float = 4.0

    async def request(self, command: str) -> bytes:
        if type(self.route) is not EybondLinkRoute:
            raise ShortAsciiError("short_ascii_requires_fc4")
        payload = build_short_ascii_request(command, self.device_addr)
        # The qualified dialect uses FC4 even on AT-primary collectors. Never
        # choose AtMixed/raw UART or bootstrap a different mode as a fallback.
        return await asyncio.wait_for(async_send_payload(
            self.transport, payload, route=self.route, request_timeout=self.timeout,
        ), timeout=self.timeout)

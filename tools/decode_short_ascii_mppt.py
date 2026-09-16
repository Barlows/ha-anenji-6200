#!/usr/bin/env python3
"""Decode one explicitly assumed AABB runtime frame offline; never scan a stream."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from custom_components.eybond_local.collector.protocol import decode_header
from custom_components.eybond_local.collector.transport.binary_framing import (
    BinaryFrame, BinaryGrammar, runtime_eybond_header_error,
)
from custom_components.eybond_local.payload.short_ascii_mppt import parse_mppt_runtime


def decode_assumed_runtime(frame_hex: str) -> dict[str, object]:
    """Report a format assumption separately from decoded numeric fields."""

    if not isinstance(frame_hex, str) or len(frame_hex) > 128:
        raise ValueError("mppt_hex_invalid")
    try:
        wire = bytes.fromhex(frame_hex)
    except ValueError:
        raise ValueError("mppt_hex_invalid") from None
    sample = parse_mppt_runtime(BinaryFrame(BinaryGrammar.AABB, wire))
    header = decode_header(wire[:8])
    overlaps = not runtime_eybond_header_error(header)
    return {
        "wire_format_assumption": "aabb_runtime_0200",
        "semantic_schema": "19b4_segment4",
        "live_session_admitted": False,
        "eybond_header_overlap": overlaps,
        "eybond_claimed_total_length": header.total_len if overlaps else None,
        "sample": asdict(sample),
        "work_mode_name": sample.work_mode.name.lower() if sample.work_mode is not None else None,
        "fault_name": sample.fault.name.lower() if sample.fault is not None else None,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wire-format", required=True, choices=("aabb-runtime",))
    parser.add_argument("--frame-hex", required=True, help="One complete 21-byte frame, not a TCP chunk")
    args = parser.parse_args(argv)
    try:
        report = decode_assumed_runtime(args.frame_hex)
    except ValueError as exc:
        # Errors from our validators are fixed reason codes, not input contents.
        print(json.dumps({"error": str(exc)}))
        return 1
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

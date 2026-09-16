"""Binary evidence remains replayable without weakening identifier masking."""

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from custom_components.eybond_local.support.masking import mask_numeric_identifiers


class SupportMaskingTests(unittest.TestCase):
    def test_declared_binary_response_map_preserves_numeric_hex_runs(self):
        for raw in (bytes(range(36)), bytes(40), b"230.0 04 03 115.0\x00\r"):
            payload = {"responses_hex": {"MP": raw.hex()}}
            self.assertEqual(mask_numeric_identifiers(payload), payload)

    def test_declared_wire_fields_preserve_numeric_hex_runs(self):
        for key in ("response_hex", "raw_response_hex", "payload_hex", "raw_payload_hex",
                    "frame_hex", "chunk_hex", "remaining_hex", "buffer_hex", "raw_hex",
                    "command_hex"):
            with self.subTest(key=key):
                payload = {key: bytes(range(36)).hex()}
                self.assertEqual(mask_numeric_identifiers(payload), payload)

    def test_embedded_identifiers_still_masked_inside_declared_hex(self):
        identifier = "92632500000001"
        wire = ("AT+DTUPN:" + identifier).encode().hex()
        masked_wire = ("AT+DTUPN:9263******0001").encode().hex()
        payload = {"responses_hex": {"MP": wire}, "payload_hex": wire, "note": identifier}
        self.assertEqual(mask_numeric_identifiers(payload), {
            "responses_hex": {"MP": masked_wire}, "payload_hex": masked_wire,
            "note": "9263******0001",
        })
        self.assertEqual(mask_numeric_identifiers(mask_numeric_identifiers(payload)),
                         mask_numeric_identifiers(payload))

    def test_untyped_decimal_identifiers_and_mapping_keys_remain_masked(self):
        identifier = "92632500000001"
        payload = {identifier: identifier, "serial": identifier, "arbitrary_hex": identifier,
                   "responses_hex": {identifier: bytes(10).hex()}}
        masked = mask_numeric_identifiers(payload)
        self.assertNotIn(identifier, repr(masked))
        self.assertEqual(masked["responses_hex"], {"9263******0001": bytes(10).hex()})
        self.assertEqual(mask_numeric_identifiers(identifier), "9263******0001")

    def test_malformed_hex_does_not_bypass_text_masking(self):
        for value in ("92632500000001!", "12345678901", "PN=92632500000001"):
            self.assertIn("*", mask_numeric_identifiers({"payload_hex": value})["payload_hex"])

    def test_hex_map_context_does_not_spread_to_nested_metadata(self):
        payload = {"responses_hex": {"unexpected": {"serial": "92632500000001"}}}
        self.assertEqual(mask_numeric_identifiers(payload), {
            "responses_hex": {"unexpected": {"serial": "9263******0001"}},
        })

    def test_wire_whitespace_and_case_preserved_without_identifiers(self):
        payload = {"payload_hex": "00 01 02 03 04 05 06 07 08 09 AA BB"}
        self.assertEqual(mask_numeric_identifiers(payload), payload)


if __name__ == "__main__":
    unittest.main()

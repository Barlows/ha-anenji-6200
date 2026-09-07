"""Protocol-level fallbacks must not borrow another model's write evidence."""

from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from custom_components.eybond_local.drivers.smg import SmgModbusDriver, _decode_block
from custom_components.eybond_local.fixtures.transport import FixtureTransport
from custom_components.eybond_local.metadata.profile_loader import load_driver_profile
from custom_components.eybond_local.metadata.register_schema_loader import load_register_schema
from custom_components.eybond_local.models import ProbeTarget
from custom_components.eybond_local.schema import capability_write_exposure_allowed


def _name(protocol: int) -> str:
    return f"modbus_smg/protocols/communication_protocol_{protocol}.json"


def _issue_41_registers() -> dict[int, int]:
    raw = json.loads((REPO_ROOT / "tests/fixtures/smg_protocol_11_7904.json").read_text())
    return {
        item["start"] + offset: value
        for item in raw["ranges"]
        for offset, value in enumerate(item["values"])
    }


def _document_protocol_2_registers() -> dict[int, int]:
    """Synthetic GM6200 values at addresses defined by the July 2024 document."""
    registers = _issue_41_registers()
    registers.update({171: 0x9999, 184: 2, 300: 0, 301: 3, 331: 4})
    registers.update({235: 0xFFFF, 236: 0xFF9C})  # Signed CT power: -100 W.
    registers.update({344: 2500, 345: 655, 346: 1805, 347: 730, 348: 2300})
    registers.update({434: 2026, 435: 9, 436: 7, 437: 8, 438: 9, 439: 10})
    registers.update({443: 1234, 444: 1, 445: 100})
    return registers


class RecordingTransport(FixtureTransport):
    def __init__(self, registers: dict[int, int]) -> None:
        super().__init__(
            registers=registers, command_responses=None,
            probe_target=ProbeTarget(devcode=1, collector_addr=255, device_addr=1),
        )
        self.requests: list[bytes] = []

    async def async_send_forward(self, payload, *, devcode, collector_addr):
        self.requests.append(payload)
        return await super().async_send_forward(
            payload, devcode=devcode, collector_addr=collector_addr,
        )


class CompatibleProtocolProfileTests(unittest.TestCase):
    def test_generic_profiles_require_full_control_and_never_inherit_tested(self) -> None:
        for protocol, count in ((1, 30), (2, 54), (11, 30)):
            profile = load_driver_profile(_name(protocol))
            self.assertEqual(len(profile.capabilities), count)
            for capability in profile.capabilities:
                with self.subTest(protocol=protocol, capability=capability.key):
                    self.assertFalse(capability.tested)
                    self.assertEqual(capability.provenance, "doc_backed")
                    policy = dict(
                        detection_confidence="high",
                        variant_key=f"protocol_{protocol}_family_fallback",
                        profile_source_scope="builtin", schema_source_scope="builtin",
                        profile_name=_name(protocol),
                    )
                    for mode in ("auto", "read_only"):
                        self.assertFalse(capability_write_exposure_allowed(
                            capability, control_mode=mode, **policy,
                        ))
                    self.assertEqual(
                        capability_write_exposure_allowed(capability, control_mode="full", **policy),
                        capability.resolved_support_tier != "blocked",
                    )

    def test_protocol_2_matrix_excludes_reserved_and_other_protocol_extensions(self) -> None:
        profile = load_driver_profile(_name(2))
        self.assertEqual({cap.register for cap in profile.capabilities}, {
            300, 301, 302, 303, 305, 306, 307, 308, 309, 310, 311, 312, 313,
            314, 318, 319, 320, 321, 322, 323, 324, 325, 326, 327, 329,
            330, 331, 332, 333, 334, 335, 336, 337, 338, 341, 342, 343,
            344, 345, 346, 347, 348, 351, 352, 406, 420, 425, 426,
            434, 437, 459, 460, 461,
        })
        for protocol in (1, 11):
            other = load_driver_profile(_name(protocol))
            self.assertTrue(all(c.register < 434 for c in other.capabilities))
            self.assertNotIn(344, {c.register for c in other.capabilities})
            self.assertNotIn(354, {c.register for c in other.capabilities})
            self.assertNotIn(322, {c.register for c in other.capabilities})
        for protocol in (1, 2):
            schema = load_register_schema(_name(protocol))
            self.assertNotIn("dry_contact_mode", {s.key for s in schema.spec_set("config")})

    def test_protocol_2_enums_replace_rather_than_extend_classic_modes(self) -> None:
        profile = load_driver_profile(_name(2))
        schema = load_register_schema(_name(2))
        specs = {spec.key: spec for spec in schema.spec_set("config")}
        for key, expected in (
            ("output_source_priority", {1, 2, 3, 4}),
            ("charge_source_priority", {1, 2, 3, 4}),
            ("output_mode", {0, 1, 2, 3, 4}),
        ):
            cap = profile.get_capability(key)
            self.assertEqual({c.value for c in cap.choices}, expected)
            self.assertEqual(set(specs[key].enum_map), expected)
            for choice in cap.choices:
                values = _decode_block(cap.register, [choice.value], (specs[key],))
                self.assertEqual(values[key], choice.label)
        self.assertNotEqual(
            profile.get_capability("output_source_priority").choices,
            load_driver_profile(_name(1)).get_capability("output_source_priority").choices,
        )
        # 344 on a specific OP2 model is SOC, not the GM6200 grid-feed limit.
        op2 = load_driver_profile("modbus_smg/models/anenji_op2_6200.json")
        op2_keys = {c.key for c in op2.capabilities if c.register == 344}
        gm_keys = {c.key for c in profile.capabilities if c.register == 344}
        self.assertTrue(op2_keys)
        self.assertTrue(op2_keys.isdisjoint(gm_keys))


class CompatibleProtocolReplayTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.force_patch = patch(
            "custom_components.eybond_local.metadata.device_catalog_loader.FORCE_UNSUPPORTED_MODELS",
            False,
        )
        self.force_patch.start()
        self.addCleanup(self.force_patch.stop)
        self.driver = SmgModbusDriver()
        self.target = ProbeTarget(devcode=1, collector_addr=255, device_addr=1)

    async def test_issue_41_detects_generic_11_without_guessing_brand_or_op2(self) -> None:
        transport = RecordingTransport(_issue_41_registers())
        inverter = await self.driver.async_probe(transport, self.target)
        self.assertIsNotNone(inverter)
        self.assertEqual(inverter.variant_key, "protocol_11_family_fallback")
        self.assertEqual(inverter.model_name, "SMG Protocol 11 (Unverified Variant)")
        self.assertEqual(inverter.profile_name, _name(11))
        self.assertEqual(inverter.details["protocol_number"], 11)
        self.assertEqual(inverter.details["device_type"], 0x7904)
        self.assertEqual(inverter.details["rated_power"], 6200)
        self.assertEqual(len(inverter.capabilities), 30)
        values = (await self.driver.async_read_values(transport, inverter)).values
        self.assertEqual(values["battery_voltage"], 49.5)
        self.assertEqual(values["output_power"], 2979)
        self.assertEqual(values["output_frequency"], 50)
        self.assertEqual(values["charge_source_priority"], "PV and Utility")
        self.assertTrue(all(request[1] == 3 for request in transport.requests))
        starts = {int.from_bytes(request[2:4], "big") for request in transport.requests}
        self.assertNotIn(600, starts)
        self.assertNotIn(696, starts)
        self.assertNotIn(354, starts)

    async def test_protocol_2_clock_schedule_and_measurements_use_their_own_addresses(self) -> None:
        transport = RecordingTransport(_document_protocol_2_registers())
        inverter = await self.driver.async_probe(transport, self.target)
        self.assertIsNotNone(inverter)
        self.assertEqual(inverter.variant_key, "protocol_2_family_fallback")
        values = (await self.driver.async_read_values(transport, inverter)).values
        self.assertEqual(values["external_ct_power"], -100)
        self.assertEqual(values["pv_generation_day"], 12.34)
        self.assertEqual(values["pv_generation_sum"], 656.36)
        self.assertEqual(values["inverter_date"], "2026-09-07")
        self.assertEqual(values["inverter_time"], "08:09:10")
        self.assertEqual(values["output_source_priority"], "PV-Utility-Battery (Grid-Tied PV)")
        self.assertEqual(values["charge_source_priority"], "PV Priority With Load Reserve")
        self.assertTrue(all(request[1] == 3 for request in transport.requests))
        for cap in inverter.capabilities:
            if cap.value_kind != "time_hhmm":
                continue
            await self.driver.async_write_capability(transport, inverter, cap.key, "06:55")
            self.assertEqual(transport._registers[cap.register], 655)
            values = (await self.driver.async_read_values(transport, inverter)).values
            self.assertEqual(values[cap.value_key], "06:55")
        await self.driver.async_write_capability(
            transport, inverter, "inverter_date_write", "2026-09-08",
        )
        await self.driver.async_write_capability(
            transport, inverter, "inverter_time_write", "12:34:56",
        )
        values = (await self.driver.async_read_values(transport, inverter)).values
        self.assertEqual(values["inverter_date"], "2026-09-08")
        self.assertEqual(values["inverter_time"], "12:34:56")
        write_starts = {
            int.from_bytes(request[2:4], "big") for request in transport.requests
            if request[1] in (6, 16)
        }
        self.assertEqual(write_starts, {345, 346, 347, 348, 434, 437})

    async def test_undocumented_numbers_do_not_reuse_a_lower_protocol_map(self) -> None:
        for protocol in (0, 7, 8, 9, 10, 12, 255, 65535):
            with self.subTest(protocol=protocol):
                registers = _issue_41_registers()
                registers.update({171: 0x9999, 184: protocol})
                transport = RecordingTransport(registers)
                self.assertIsNone(await self.driver.async_probe(transport, self.target))
                self.assertTrue(all(request[1] == 3 for request in transport.requests))

    async def test_known_model_descriptors_keep_precedence_and_tested_evidence(self) -> None:
        for protocol, model, power, expected in (
            (1, 0x1E00, 6200, "default"),
            (11, 0x7801, 4200, "smg_variant_4200"),
            (11, 0x7901, 5000, "anenji_anj_5kw_48v_wifi"),
            (11, 0x7903, 6200, "anenji_op2_6200"),
            (11, 0x7803, 4200, "aninerel_anl_4200t_24l_w_pro"),
        ):
            with self.subTest(expected=expected):
                registers = _issue_41_registers()
                registers.update({171: model, 184: protocol, 643: power, 644: 8 if power == 4200 else 16})
                # Complete the exact OP2 model's larger live block in this synthetic test.
                registers.update({address: 0 for address in range(235, 245)})
                registers.update({address: 0 for address in range(354, 357)})
                transport = RecordingTransport(registers)
                inverter = await self.driver.async_probe(transport, self.target)
                self.assertIsNotNone(inverter)
                self.assertEqual(
                    inverter.variant_key, "default" if expected == "anenji_op2_6200" else expected,
                )
                if expected == "anenji_op2_6200":
                    self.assertEqual(inverter.profile_name, "modbus_smg/models/anenji_op2_6200.json")
                self.assertTrue(any(c.tested for c in inverter.capabilities))

    async def test_invalid_telemetry_cannot_activate_a_number_only_profile(self) -> None:
        for protocol in (1, 2, 11):
            with self.subTest(protocol=protocol):
                registers = _document_protocol_2_registers()
                registers.update({184: protocol, 320: 0, 321: 0})
                self.assertIsNone(await self.driver.async_probe(RecordingTransport(registers), self.target))


if __name__ == "__main__":
    unittest.main()

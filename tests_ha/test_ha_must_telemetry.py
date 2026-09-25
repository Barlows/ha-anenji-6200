"""MUST map corrections retire invalid energy identities through real HA."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from homeassistant.config_entries import ConfigEntryDisabler
from homeassistant.core import State
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry, mock_restore_cache

from custom_components.eybond_local.canonical_telemetry import project_canonical_telemetry
from custom_components.eybond_local.const import DOMAIN
from custom_components.eybond_local.drivers.must import MustPvPh18Driver, _support_capture_ranges
from custom_components.eybond_local.fixtures.transport import FixtureTransport
from custom_components.eybond_local.models import CollectorInfo, ProbeTarget, RuntimeSnapshot
from custom_components.eybond_local.telemetry import TypedTelemetryFrame, fold_driver_telemetry
from synthetic import SYNTHETIC_COLLECTOR_IP, SYNTHETIC_COLLECTOR_PN, SYNTHETIC_SERVER_IP


@pytest.mark.parametrize("upgrade", [False, True])
async def test_must_power_and_energy_setup_upgrade_reload(hass, fake_runtime, monkeypatch, upgrade):
    from conftest import FakeRuntimeManager
    from custom_components.eybond_local import sensor as sensor_platform

    # Keep the sensor's local-day clock deterministic without changing HA's own
    # clock/scheduler. This tests retained pre-fix energy, not a Recorder rewrite.
    now = datetime(2026, 9, 24, 12, tzinfo=timezone.utc)
    monkeypatch.setattr(sensor_platform, "dt_util", SimpleNamespace(now=lambda: now))

    # Synthetic bank, no customer identifiers or cloud/device I/O.
    registers = {
        register: 0
        for start, count in _support_capture_ranges("must_pv_ph18/base.json")
        for register in range(start, start + count)
    } | {20000: int.from_bytes(b"PV", "big"), 20001: 3300,
         25213: 65049, 25215: 0, 15217: 0, 15218: 1, 15219: 39}

    class ReadOnlyTransport(FixtureTransport):
        async def async_send_payload(self, payload, *, route):
            assert payload[1] == 3, "Telemetry setup must never write"
            return await super().async_send_payload(payload, route=route)

    driver = MustPvPh18Driver()
    transport = ReadOnlyTransport(registers=registers, command_responses=None, probe_target=ProbeTarget(1, 255, 4))
    inverter = await driver.async_probe(transport, ProbeTarget(1, 255, 4))
    assert inverter is not None

    async def refresh(self, *, poll_interval=None):
        read = await driver.async_read_values(transport, inverter)
        frame = project_canonical_telemetry(fold_driver_telemetry(
            TypedTelemetryFrame.empty(), driver_key=driver.key, values=read.values, replace=True,
        ))
        return RuntimeSnapshot(
            connected=True, inverter=inverter, telemetry=frame,
            collector=CollectorInfo(remote_ip=SYNTHETIC_COLLECTOR_IP, collector_pn=SYNTHETIC_COLLECTOR_PN),
        )

    monkeypatch.setattr(FakeRuntimeManager, "async_refresh", refresh)
    entry = MockConfigEntry(
        domain=DOMAIN, title=inverter.model_name, version=5,
        unique_id=f"collector:{SYNTHETIC_COLLECTOR_PN}",
        data={
            "connection_type": "eybond", "connection_mode": "known_ip",
            "server_ip": SYNTHETIC_SERVER_IP, "collector_ip": SYNTHETIC_COLLECTOR_IP,
            "collector_pn": SYNTHETIC_COLLECTOR_PN, "tcp_port": 8899, "udp_port": 58899,
            "driver_hint": "auto", "control_mode": "read_only",
            "connection_strategy": "callback_on_demand", "endpoint_control_policy": "external",
            "proxy_enabled": False, "detected_driver": driver.key, "detected_model": inverter.model_name,
            "detected_serial": "", "detection_confidence": "high",
        },
        options={"poll_interval": 30, "poll_mode": "auto"},
    )
    entry.add_to_hass(hass)
    registry = er.async_get(hass)
    legacy_ids = []
    old_load_id = None
    if upgrade:
        daily = registry.async_get_or_create(
            "sensor", DOMAIN, f"{entry.entry_id}_estimated_load_energy_daily",
            config_entry=entry, suggested_object_id="my_daily_load_energy",
        )
        mock_restore_cache(hass, [State(
            daily.entity_id, "102.2785",
            {"period_key": now.date().isoformat(), "unit_of_measurement": "kWh"},
        )])
        for key in ("pv_generation_sum", "pv_generation_day"):
            old = registry.async_get_or_create(
                "sensor", DOMAIN, f"{entry.entry_id}_{key}",
                config_entry=entry, suggested_object_id=f"must_{key}",
            )
            legacy_ids.append(old.entity_id)
        load = registry.async_get_or_create(
            "sensor", DOMAIN, f"{entry.entry_id}_output_power",
            config_entry=entry, suggested_object_id="my_existing_load",
        )
        old_load_id = load.entity_id
        registry.async_update_entity(old_load_id, name="My load")
    other = MockConfigEntry(
        domain=DOMAIN, title="Unrelated inverter", disabled_by=ConfigEntryDisabler.USER,
    )
    other.add_to_hass(hass)
    other_energy = registry.async_get_or_create(
        "sensor", DOMAIN, f"{other.entry_id}_pv_generation_sum",
        config_entry=other, suggested_object_id="other_pv_energy",
    )

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()

    def sensor_id(key):
        return registry.async_get_entity_id("sensor", DOMAIN, f"{entry.entry_id}_{key}")

    expected = {"output_power": 0, "ac_output_power": 0, "inverter_power": -487, "pv_energy_total": 0.1}
    identities = {key: sensor_id(key) for key in expected}
    for key, value in expected.items():
        assert identities[key] is not None, key
        state = hass.states.get(identities[key])
        assert state is not None and float(state.state) == value, key
    energy = hass.states.get(identities["pv_energy_total"])
    assert energy.attributes["unit_of_measurement"] == "kWh"
    assert energy.attributes["state_class"] == "total_increasing"
    daily_id = sensor_id("estimated_load_energy_daily")
    daily = hass.states.get(daily_id)
    assert daily.attributes["source_key"] == "estimated_load_energy"
    assert daily.attributes["period_key"] == now.date().isoformat()
    assert float(daily.state) == (102.2785 if upgrade else 0)
    assert identities["pv_energy_total"] not in legacy_ids
    for key in ("pv_generation_sum", "pv_generation_day"):
        assert sensor_id(key) is None
    assert all(registry.async_get(entity_id) is None for entity_id in legacy_ids)
    assert registry.async_get(other_energy.entity_id) is not None
    if upgrade:
        assert identities["output_power"] == old_load_id
        assert registry.async_get(old_load_id).name == "My load"
    days_id = sensor_id("pv_operating_days")
    assert registry.async_get(days_id).entity_category.value == "diagnostic"
    assert registry.async_get(days_id).disabled_by is er.RegistryEntryDisabler.INTEGRATION
    registry.async_update_entity(days_id, disabled_by=None)

    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert {key: sensor_id(key) for key in expected} == identities
    days = hass.states.get(days_id)
    assert float(days.state) == 39
    assert days.attributes["unit_of_measurement"] == "d"
    assert days.attributes.get("device_class") != "energy"
    assert days.attributes.get("state_class") == "measurement"
    assert registry.async_get(other_energy.entity_id) is not None
    # A same-day restart and correct zero load do not erase already accumulated
    # energy. A new local day resets on the next valid measurement, then the
    # corrected MUST load measurement integrates at 1000 W -> 1 kWh per hour.
    assert float(hass.states.get(daily_id).state) == (102.2785 if upgrade else 0)
    now += timedelta(days=1)
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert float(hass.states.get(daily_id).state) == 0
    transport._registers[25215] = 1000
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert float(hass.states.get(sensor_id("output_power")).state) == 1000
    now += timedelta(hours=1)
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert float(hass.states.get(daily_id).state) == 1
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()

"""Tests for sensor.py's own-bridge diagnostic entities (PROTOCOL.md §9,
issue #12). Federated (remote-bridge) entity creation is covered in
test_remote_entity_manager.py -- this file is just the local
BridgeMetadataEntities holder and its platform wiring.
"""

import asyncio

import pytest

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant

from custom_components import grapevine
from custom_components.grapevine import scheduler as scheduler_module
from custom_components.grapevine.const import (
    CONF_BRIDGE_NAME,
    CONF_ENTITIES,
    CONF_SENSOR_VALUE_PREFIX,
    CONF_SHARED_DISCOVERY_PREFIX,
    CONF_TIME_PATTERN_MINUTES,
)
from custom_components.grapevine.sensor import BridgeMetadataEntities


@pytest.fixture(autouse=True)
def _no_jitter(monkeypatch):
    monkeypatch.setattr(scheduler_module.random, "uniform", lambda a, b: 0)


def _run(coro):
    return asyncio.run(coro)


# --- BridgeMetadataEntities in isolation ---


def test_metadata_entities_share_one_device():
    entities = BridgeMetadataEntities(
        bridge_name="Bridge Jakob",
        slug_bridge_name="bridge_jakob",
        integration_version="0.1.3",
        protocol_version=1,
    )

    for entity in entities.entities:
        assert entity._attr_device_info["identifiers"] == {("grapevine", "bridge_jakob")}
        assert entity._attr_device_info["name"] == "Bridge Jakob"


def test_metadata_entities_are_diagnostic_category():
    entities = BridgeMetadataEntities(
        bridge_name="Bridge Jakob",
        slug_bridge_name="bridge_jakob",
        integration_version="0.1.3",
        protocol_version=1,
    )
    assert all(e._attr_entity_category == EntityCategory.DIAGNOSTIC for e in entities.entities)


def test_metadata_entities_update_sets_native_values():
    hass = HomeAssistant()
    entities = BridgeMetadataEntities(
        bridge_name="Bridge Jakob",
        slug_bridge_name="bridge_jakob",
        integration_version="0.1.3",
        protocol_version=1,
    )
    for entity, suffix in zip(entities.entities, ["count", "heartbeat", "haversion"]):
        entity.hass = hass
        entity.entity_id = f"sensor.{suffix}"

    entities.update(
        {"entity_count": 3, "last_heartbeat": "2026-08-06T08:14:00+00:00", "ha_version": "2026.8.0"}
    )

    assert entities.entity_count.native_value == "3"
    assert entities.last_heartbeat.native_value == "2026-08-06T08:14:00+00:00"
    assert entities.ha_version.native_value == "2026.8.0"


# --- end-to-end through async_setup_entry ---


def _make_entry(entities: list[str]) -> ConfigEntry:
    return ConfigEntry(
        entry_id="entry1",
        data={
            CONF_ENTITIES: entities,
            CONF_SHARED_DISCOVERY_PREFIX: "share/homeassistant/",
            CONF_SENSOR_VALUE_PREFIX: "share/jakob/",
            CONF_BRIDGE_NAME: "Bridge Jakob",
        },
        options={CONF_TIME_PATTERN_MINUTES: 1},
    )


async def _drain_hass_tasks(hass: HomeAssistant) -> None:
    while hass._tasks:
        await asyncio.gather(*list(hass._tasks), return_exceptions=True)


def test_setup_entry_creates_diagnostic_entities_with_values():
    hass = HomeAssistant()
    entry = _make_entry(["sensor.a"])
    hass.states.async_set("sensor.a", "1")

    async def scenario():
        await grapevine.async_setup_entry(hass, entry)
        await _drain_hass_tasks(hass)

    _run(scenario())

    # unique_id "bridge_jakob::entity_count" -> the fake entity-id slugifier
    # turns "::" into a double underscore.
    entity_count_state = hass.states.get("sensor.bridge_jakob__entity_count")
    assert entity_count_state is not None
    assert entity_count_state.state == "1"

    heartbeat_state = hass.states.get("sensor.bridge_jakob__last_heartbeat")
    assert heartbeat_state is not None
    assert heartbeat_state.state != ""

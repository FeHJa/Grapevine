"""RemoteEntityManager unit tests — create-on-first-sight, update-in-place
on redelivery, per-entity state-topic subscription, unload cleanup. Wired
manually here (not through __init__.py's full setup) to isolate the
manager's own behavior; see test_federated_entities_integration.py for the
end-to-end path through async_setup_entry.
"""

import asyncio

from homeassistant.components import mqtt
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from custom_components.ha_mqtt_bridge.const import DOMAIN
from custom_components.ha_mqtt_bridge.remote_entity_manager import RemoteEntityManager

EXAMPLE_PAYLOAD = {
    "name": "Garage Humidity",
    "state_topic": "share/other_bridge/sensor/garage_humidity",
    "unique_id": "other_bridge::sensor.garage_humidity",
    "device_class": "humidity",
    "unit_of_measurement": "%",
    "bridge_id": "other_bridge",
    "protocol_version": 1,
    "device": {
        "identifiers": ["other_bridge"],
        "name": "Bridge Other",
        "sw_version": "1.0.3",
    },
}


def _make_manager(hass: HomeAssistant) -> tuple[RemoteEntityManager, list]:
    manager = RemoteEntityManager(hass, ConfigEntry())
    added: list = []

    def _add_entities(entities) -> None:
        # Mimics what the real (and fake, in ConfigEntriesRegistry) entity
        # platform does when async_add_entities runs -- assigns hass and
        # an entity_id before the entity is otherwise usable.
        for entity in entities:
            entity.hass = hass
            entity.entity_id = f"sensor.{entity.unique_id.replace('.', '_').replace(':', '_')}"
            added.append(entity)

    manager.set_add_entities_callback(_add_entities)
    return manager, added


def _run(coro):
    return asyncio.run(coro)


def test_creates_entity_on_first_discovery():
    hass = HomeAssistant()
    manager, added = _make_manager(hass)

    _run(manager.async_handle_discovery(dict(EXAMPLE_PAYLOAD)))

    assert len(added) == 1
    entity = added[0]
    assert entity.unique_id == "other_bridge::sensor.garage_humidity"
    assert entity._attr_name == "Garage Humidity"
    assert entity._attr_device_class == "humidity"
    assert entity._attr_native_unit_of_measurement == "%"
    assert entity._attr_device_info == {
        "identifiers": {(DOMAIN, "other_bridge")},
        "name": "Bridge Other",
        "sw_version": "1.0.3",
    }


def test_subscribes_to_state_topic_on_first_discovery():
    hass = HomeAssistant()
    manager, _added = _make_manager(hass)

    _run(manager.async_handle_discovery(dict(EXAMPLE_PAYLOAD)))

    assert "share/other_bridge/sensor/garage_humidity" in mqtt._state(hass).subscriptions


def test_state_message_updates_entity_native_value_and_ha_state():
    hass = HomeAssistant()
    manager, added = _make_manager(hass)

    async def scenario():
        await manager.async_handle_discovery(dict(EXAMPLE_PAYLOAD))
        await mqtt.async_fire_mqtt_message(
            hass, "share/other_bridge/sensor/garage_humidity", "55"
        )

    _run(scenario())

    entity = added[0]
    assert entity.native_value == "55"
    assert hass.states.get(entity.entity_id).state == "55"


def test_redelivery_of_same_unique_id_updates_in_place_not_duplicated():
    hass = HomeAssistant()
    manager, added = _make_manager(hass)

    async def scenario():
        await manager.async_handle_discovery(dict(EXAMPLE_PAYLOAD))
        updated = dict(EXAMPLE_PAYLOAD)
        updated["name"] = "Garage Humidity (renamed)"
        updated["device_class"] = None
        await manager.async_handle_discovery(updated)

    _run(scenario())

    assert len(added) == 1  # only the first discovery triggered add_entities
    entity = added[0]
    assert entity._attr_name == "Garage Humidity (renamed)"
    assert entity._attr_device_class is None


def test_redelivery_does_not_resubscribe_state_topic():
    hass = HomeAssistant()
    manager, _added = _make_manager(hass)

    async def scenario():
        await manager.async_handle_discovery(dict(EXAMPLE_PAYLOAD))
        await manager.async_handle_discovery(dict(EXAMPLE_PAYLOAD))

    _run(scenario())

    subs = mqtt._state(hass).subscriptions["share/other_bridge/sensor/garage_humidity"]
    assert len(subs) == 1


def test_ignores_payload_missing_unique_id():
    hass = HomeAssistant()
    manager, added = _make_manager(hass)
    payload = dict(EXAMPLE_PAYLOAD)
    del payload["unique_id"]

    _run(manager.async_handle_discovery(payload))

    assert added == []


def test_ignores_payload_missing_state_topic():
    hass = HomeAssistant()
    manager, added = _make_manager(hass)
    payload = dict(EXAMPLE_PAYLOAD)
    del payload["state_topic"]

    _run(manager.async_handle_discovery(payload))

    assert added == []


def test_drops_discovery_when_platform_not_ready_yet():
    hass = HomeAssistant()
    manager = RemoteEntityManager(hass, ConfigEntry())
    # No set_add_entities_callback() call -- platform hasn't set up yet.

    _run(manager.async_handle_discovery(dict(EXAMPLE_PAYLOAD)))

    assert manager._entities == {}
    assert mqtt._state(hass).subscriptions == {}


def test_unload_unsubscribes_and_clears_tracked_entities():
    hass = HomeAssistant()
    manager, added = _make_manager(hass)

    async def scenario():
        await manager.async_handle_discovery(dict(EXAMPLE_PAYLOAD))
        second = dict(EXAMPLE_PAYLOAD)
        second["unique_id"] = "other_bridge::sensor.garage_temperature"
        second["state_topic"] = "share/other_bridge/sensor/garage_temperature"
        await manager.async_handle_discovery(second)

        await manager.async_unload()

    _run(scenario())

    assert len(added) == 2
    assert manager._entities == {}
    assert manager._state_unsubs == {}
    assert mqtt._state(hass).subscriptions.get("share/other_bridge/sensor/garage_humidity") == []
    assert mqtt._state(hass).subscriptions.get("share/other_bridge/sensor/garage_temperature") == []

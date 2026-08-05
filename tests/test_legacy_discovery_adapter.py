"""LegacyDiscoveryAdapter tests against the fake homeassistant.components.mqtt
in tests/ha_stubs — exercises publish/forward/loop-guard through the real
mqtt_io.py wrapper, not just discovery.py's pure functions directly.
"""

import asyncio
import json

from homeassistant.components import mqtt
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, State

from custom_components.ha_mqtt_bridge import mqtt_io
from custom_components.ha_mqtt_bridge.adapters.legacy_discovery import LegacyDiscoveryAdapter
from custom_components.ha_mqtt_bridge.const import (
    CONF_BRIDGE_NAME,
    CONF_LOCAL_DISCOVERY_PREFIX,
    CONF_SENSOR_VALUE_PREFIX,
    CONF_SHARED_DISCOVERY_PREFIX,
)


def _make_adapter(hass: HomeAssistant) -> LegacyDiscoveryAdapter:
    entry = ConfigEntry(
        data={
            CONF_SHARED_DISCOVERY_PREFIX: "share/homeassistant/",
            CONF_LOCAL_DISCOVERY_PREFIX: "homeassistant",
            CONF_SENSOR_VALUE_PREFIX: "share/jakob/",
            CONF_BRIDGE_NAME: "Bridge Jakob",
        }
    )
    return LegacyDiscoveryAdapter(hass, entry)


def _run(coro):
    return asyncio.run(coro)


def _published(hass: HomeAssistant) -> list[tuple[str, str, bool]]:
    return mqtt._state(hass).published


# --- publish_own_entity ---


def test_publish_own_entity_publishes_discovery_and_state_retained():
    hass = HomeAssistant()
    adapter = _make_adapter(hass)
    state = State("sensor.garage_temperature", "21.5", {"friendly_name": "Garage Temperature"})

    _run(adapter.publish_own_entity("sensor.garage_temperature", state))

    published = _published(hass)
    assert len(published) == 2

    discovery_topic, discovery_payload, discovery_retain = published[0]
    assert discovery_topic == "share/homeassistant/sensor/garage_temperature/config"
    assert discovery_retain is True
    payload = json.loads(discovery_payload)
    assert payload["name"] == "Garage Temperature"
    assert payload["state_topic"] == "share/jakob/sensor/garage_temperature"
    assert payload["unique_id"] == "bridge_jakob::sensor.garage_temperature"
    assert payload["device_class"] == "temperature"
    assert payload["unit_of_measurement"] == "°C"
    assert payload["bridge_id"] == "bridge_jakob"
    assert payload["protocol_version"] == 1
    assert payload["device"] == {
        "identifiers": ["bridge_jakob"],
        "name": "Bridge Jakob",
        "sw_version": "1.0.3",
    }

    state_topic, state_payload, state_retain = published[1]
    assert state_topic == "share/jakob/sensor/garage_temperature"
    assert state_payload == "21.5"  # raw string, no JSON wrapping (§4)
    assert state_retain is True


def test_publish_own_entity_uses_shared_discovery_prefix_for_topic_not_local():
    hass = HomeAssistant()
    adapter = _make_adapter(hass)
    state = State("sensor.x", "1", {})

    _run(adapter.publish_own_entity("sensor.x", state))

    discovery_topic, _, _ = _published(hass)[0]
    assert discovery_topic.startswith("share/homeassistant/")


# --- topics_to_subscribe ---


def test_topics_to_subscribe_uses_configured_shared_prefix():
    hass = HomeAssistant()
    adapter = _make_adapter(hass)
    assert adapter.topics_to_subscribe() == ["share/homeassistant/+/+/config"]


# --- handle_incoming_message: forwarding + loop guard (§5) ---


def test_forwards_foreign_bridge_discovery_verbatim():
    hass = HomeAssistant()
    adapter = _make_adapter(hass)
    raw_payload = '{"bridge_id": "other_bridge", "unique_id": "other_bridge::sensor.y", "extra": 1}'

    _run(
        adapter.handle_incoming_message(
            "share/homeassistant/sensor/garage_humidity/config", raw_payload
        )
    )

    published = _published(hass)
    assert published == [
        ("homeassistant/sensor/garage_humidity/config", raw_payload, True)
    ]


def test_does_not_forward_own_message_by_bridge_id():
    hass = HomeAssistant()
    adapter = _make_adapter(hass)
    own_payload = json.dumps({"bridge_id": "bridge_jakob", "unique_id": "bridge_jakob::sensor.x"})

    _run(adapter.handle_incoming_message("share/homeassistant/sensor/x/config", own_payload))

    assert _published(hass) == []


def test_does_not_forward_own_message_by_unique_id_prefix():
    hass = HomeAssistant()
    adapter = _make_adapter(hass)
    own_payload = json.dumps({"unique_id": "bridge_jakob.sensor.x"})

    _run(adapter.handle_incoming_message("share/homeassistant/sensor/x/config", own_payload))

    assert _published(hass) == []


def test_ignores_non_json_payload_without_raising():
    hass = HomeAssistant()
    adapter = _make_adapter(hass)

    _run(adapter.handle_incoming_message("share/homeassistant/sensor/x/config", "not json"))

    assert _published(hass) == []


def test_ignores_message_on_unmatched_topic_shape():
    hass = HomeAssistant()
    adapter = _make_adapter(hass)

    _run(adapter.handle_incoming_message("some/other/topic", '{"bridge_id": "x"}'))

    assert _published(hass) == []


# --- end-to-end through mqtt_io subscribe + fake broker delivery ---


def test_subscribed_topic_delivers_to_handler_and_forwards():
    hass = HomeAssistant()
    adapter = _make_adapter(hass)

    async def scenario():
        for topic in adapter.topics_to_subscribe():
            await mqtt_io.async_subscribe(hass, topic, adapter.async_handle_mqtt_message)

        payload = json.dumps({"bridge_id": "other_bridge", "unique_id": "other_bridge::sensor.y"})
        await mqtt.async_fire_mqtt_message(
            hass, "share/homeassistant/sensor/garage_humidity/config", payload
        )
        return payload

    payload = _run(scenario())

    assert _published(hass) == [
        ("homeassistant/sensor/garage_humidity/config", payload, True)
    ]

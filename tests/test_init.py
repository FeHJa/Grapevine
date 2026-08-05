"""__init__.py tests: entry setup/unload wiring and the domain-wide
republish service (registered once, dispatched per config entry).
"""

import asyncio

import pytest

from homeassistant.components import mqtt
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady, ServiceValidationError

from custom_components import ha_mqtt_bridge
from custom_components.ha_mqtt_bridge import scheduler as scheduler_module
from custom_components.ha_mqtt_bridge.const import (
    ATTR_CONFIG_ENTRY_ID,
    CONF_BRIDGE_NAME,
    CONF_ENTITIES,
    CONF_SENSOR_VALUE_PREFIX,
    CONF_SHARED_DISCOVERY_PREFIX,
    CONF_TIME_PATTERN_MINUTES,
    DOMAIN,
    SERVICE_REPUBLISH,
)
from custom_components.ha_mqtt_bridge.remote_entity_manager import RemoteEntityManager
from custom_components.ha_mqtt_bridge.scheduler import BridgeScheduler


@pytest.fixture(autouse=True)
def _no_jitter(monkeypatch):
    # Every setup schedules a real jittered (0-9s) initial republish; these
    # tests are about service dispatch/wiring, not jitter, so keep them fast.
    monkeypatch.setattr(scheduler_module.random, "uniform", lambda a, b: 0)


def _make_entry(entry_id: str, bridge_name: str, entities: list[str]) -> ConfigEntry:
    return ConfigEntry(
        entry_id=entry_id,
        data={
            CONF_ENTITIES: entities,
            CONF_SHARED_DISCOVERY_PREFIX: "share/homeassistant/",
            CONF_SENSOR_VALUE_PREFIX: "share/jakob/",
            CONF_BRIDGE_NAME: bridge_name,
        },
        options={CONF_TIME_PATTERN_MINUTES: 1},
    )


def _run(coro):
    return asyncio.run(coro)


def test_setup_entry_raises_config_entry_not_ready_when_mqtt_not_ready():
    hass = HomeAssistant()
    mqtt._state(hass).client_ready = False
    entry = _make_entry("entry1", "Bridge Jakob", ["sensor.a"])

    with pytest.raises(ConfigEntryNotReady):
        _run(ha_mqtt_bridge.async_setup_entry(hass, entry))


def test_setup_entry_wires_scheduler_onto_runtime_data():
    hass = HomeAssistant()
    entry = _make_entry("entry1", "Bridge Jakob", ["sensor.a"])

    result = _run(ha_mqtt_bridge.async_setup_entry(hass, entry))

    assert result is True
    assert isinstance(entry.runtime_data.scheduler, BridgeScheduler)
    assert isinstance(entry.runtime_data.remote_entity_manager, RemoteEntityManager)


def test_setup_entry_registers_service_once():
    hass = HomeAssistant()
    entry = _make_entry("entry1", "Bridge Jakob", ["sensor.a"])

    _run(ha_mqtt_bridge.async_setup_entry(hass, entry))

    assert hass.services.has_service(DOMAIN, SERVICE_REPUBLISH)


def test_republish_service_dispatches_to_correct_entry(monkeypatch):
    hass = HomeAssistant()
    entry_a = _make_entry("entry_a", "Bridge A", ["sensor.a"])
    entry_b = _make_entry("entry_b", "Bridge B", ["sensor.b"])
    hass.states.async_set("sensor.a", "1")
    hass.states.async_set("sensor.b", "2")

    async def scenario():
        await ha_mqtt_bridge.async_setup_entry(hass, entry_a)
        await ha_mqtt_bridge.async_setup_entry(hass, entry_b)

        # Both entries schedule an initial resync republish on setup; drain
        # those before exercising the service call so they don't muddy the
        # published-messages assertion below.
        for entry in (entry_a, entry_b):
            pending = list(entry.runtime_data.scheduler._tasks)
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)

        mqtt._state(hass).published.clear()

        await hass.services.async_call(
            DOMAIN, SERVICE_REPUBLISH, {ATTR_CONFIG_ENTRY_ID: "entry_a"}
        )
        pending = list(entry_a.runtime_data.scheduler._tasks)
        await asyncio.gather(*pending, return_exceptions=True)

    _run(scenario())

    published_topics = {topic for topic, _, _ in mqtt._state(hass).published}
    # entry_a's sensor ("sensor.a" -> object_id "a") was republished...
    assert "share/homeassistant/sensor/a/config" in published_topics
    assert "share/jakob/sensor/a" in published_topics
    # ...entry_b's was not, since the service call only targeted entry_a.
    assert "share/homeassistant/sensor/b/config" not in published_topics
    assert "share/jakob/sensor/b" not in published_topics


def test_republish_service_raises_for_unknown_entry_id():
    hass = HomeAssistant()
    entry = _make_entry("entry1", "Bridge Jakob", ["sensor.a"])
    _run(ha_mqtt_bridge.async_setup_entry(hass, entry))

    async def scenario():
        with pytest.raises(ServiceValidationError):
            await hass.services.async_call(
                DOMAIN, SERVICE_REPUBLISH, {ATTR_CONFIG_ENTRY_ID: "does_not_exist"}
            )

    _run(scenario())


def test_unload_entry_removes_its_republish_handler():
    hass = HomeAssistant()
    entry = _make_entry("entry1", "Bridge Jakob", ["sensor.a"])

    async def scenario():
        await ha_mqtt_bridge.async_setup_entry(hass, entry)
        assert "entry1" in hass.data[DOMAIN]["republish_handlers"]

        await ha_mqtt_bridge.async_unload_entry(hass, entry)
        await entry.async_unload()

        assert "entry1" not in hass.data[DOMAIN]["republish_handlers"]
        with pytest.raises(ServiceValidationError):
            await hass.services.async_call(
                DOMAIN, SERVICE_REPUBLISH, {ATTR_CONFIG_ENTRY_ID: "entry1"}
            )

    _run(scenario())

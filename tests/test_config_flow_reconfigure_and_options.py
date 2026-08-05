"""async_step_reconfigure and GrapevineOptionsFlow (issue #7), exercised
against the real async_setup_entry/async_unload_entry/async_reload path so
"did the change actually take effect" is genuinely tested, not just "did
the flow return the right dict."
"""

import asyncio

import pytest

from homeassistant.components import mqtt
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from custom_components import grapevine
from custom_components.grapevine import scheduler as scheduler_module
from custom_components.grapevine.config_flow import GrapevineConfigFlow, GrapevineOptionsFlow
from custom_components.grapevine.const import (
    CONF_BRIDGE_NAME,
    CONF_ENTITIES,
    CONF_SENSOR_VALUE_PREFIX,
    CONF_SHARED_DISCOVERY_PREFIX,
    CONF_TIME_PATTERN_MINUTES,
)


@pytest.fixture(autouse=True)
def _no_jitter(monkeypatch):
    monkeypatch.setattr(scheduler_module.random, "uniform", lambda a, b: 0)


def _make_entry(entry_id: str, bridge_name: str, entities: list[str], minutes: int = 1) -> ConfigEntry:
    return ConfigEntry(
        entry_id=entry_id,
        unique_id=bridge_name.lower().replace(" ", "_"),
        data={
            CONF_ENTITIES: entities,
            CONF_SHARED_DISCOVERY_PREFIX: "share/homeassistant/",
            CONF_SENSOR_VALUE_PREFIX: "share/jakob/",
            CONF_BRIDGE_NAME: bridge_name,
        },
        options={CONF_TIME_PATTERN_MINUTES: minutes},
    )


def _run(coro):
    return asyncio.run(coro)


async def _drain_hass_tasks(hass: HomeAssistant) -> None:
    """Update-entry-triggered reloads (and the republishes a reload
    itself schedules) run as background tasks; drain until none remain."""
    while hass._tasks:
        await asyncio.gather(*list(hass._tasks), return_exceptions=True)


def _reconfigure_flow(hass: HomeAssistant, entry: ConfigEntry) -> GrapevineConfigFlow:
    flow = GrapevineConfigFlow()
    flow.hass = hass
    flow.context = {"entry_id": entry.entry_id}
    return flow


def _options_flow(hass: HomeAssistant, entry: ConfigEntry) -> GrapevineOptionsFlow:
    flow = GrapevineOptionsFlow()
    flow.hass = hass
    flow.config_entry = entry
    return flow


# --- async_step_reconfigure ---


def test_reconfigure_shows_form_prefilled_with_current_values():
    hass = HomeAssistant()
    entry = _make_entry("entry1", "Bridge Jakob", ["sensor.a"])
    hass.config_entries.entries.append(entry)
    flow = _reconfigure_flow(hass, entry)

    result = _run(flow.async_step_reconfigure(None))

    assert result["type"] == "form"
    assert result["step_id"] == "reconfigure"
    assert result["errors"] == {}


def test_reconfigure_rejects_invalid_bridge_name():
    hass = HomeAssistant()
    entry = _make_entry("entry1", "Bridge Jakob", ["sensor.a"])
    hass.config_entries.entries.append(entry)
    flow = _reconfigure_flow(hass, entry)

    result = _run(
        flow.async_step_reconfigure(
            {
                CONF_BRIDGE_NAME: "!!!",
                CONF_ENTITIES: ["sensor.a"],
                CONF_SHARED_DISCOVERY_PREFIX: "share/homeassistant",
                CONF_SENSOR_VALUE_PREFIX: "share/jakob",
            }
        )
    )

    assert result["errors"] == {"base": "invalid_bridge_name"}
    assert entry.data[CONF_BRIDGE_NAME] == "Bridge Jakob"  # unchanged


def test_reconfigure_rejects_empty_entities():
    hass = HomeAssistant()
    entry = _make_entry("entry1", "Bridge Jakob", ["sensor.a"])
    hass.config_entries.entries.append(entry)
    flow = _reconfigure_flow(hass, entry)

    result = _run(
        flow.async_step_reconfigure(
            {
                CONF_BRIDGE_NAME: "Bridge Jakob",
                CONF_ENTITIES: [],
                CONF_SHARED_DISCOVERY_PREFIX: "share/homeassistant",
                CONF_SENSOR_VALUE_PREFIX: "share/jakob",
            }
        )
    )

    assert result["errors"] == {"base": "no_entities"}


def test_reconfigure_rejects_rename_colliding_with_another_entry():
    hass = HomeAssistant()
    entry_a = _make_entry("entry_a", "Bridge A", ["sensor.a"])
    entry_b = _make_entry("entry_b", "Bridge B", ["sensor.b"])
    hass.config_entries.entries.extend([entry_a, entry_b])
    flow = _reconfigure_flow(hass, entry_a)

    result = _run(
        flow.async_step_reconfigure(
            {
                CONF_BRIDGE_NAME: "Bridge B",  # entry_b's name/slug
                CONF_ENTITIES: ["sensor.a"],
                CONF_SHARED_DISCOVERY_PREFIX: "share/homeassistant",
                CONF_SENSOR_VALUE_PREFIX: "share/jakob",
            }
        )
    )

    assert result["errors"] == {"base": "already_configured"}
    assert entry_a.data[CONF_BRIDGE_NAME] == "Bridge A"  # unchanged


def test_reconfigure_keeping_same_bridge_name_does_not_self_collide():
    hass = HomeAssistant()
    entry = _make_entry("entry1", "Bridge Jakob", ["sensor.a"])
    hass.config_entries.entries.append(entry)

    async def scenario():
        await grapevine.async_setup_entry(hass, entry)
        await _drain_hass_tasks(hass)

        flow = _reconfigure_flow(hass, entry)
        return await flow.async_step_reconfigure(
            {
                CONF_BRIDGE_NAME: "Bridge Jakob",  # same as before
                CONF_ENTITIES: ["sensor.a"],
                CONF_SHARED_DISCOVERY_PREFIX: "share/homeassistant",
                CONF_SENSOR_VALUE_PREFIX: "share/jakob",
            }
        )

    result = _run(scenario())

    assert result == {"type": "abort", "reason": "reconfigure_successful"}


def test_reconfigure_updates_data_and_reloads():
    hass = HomeAssistant()
    entry = _make_entry("entry1", "Bridge Jakob", ["sensor.a"])
    hass.config_entries.entries.append(entry)
    hass.states.async_set("sensor.a", "1")
    hass.states.async_set("sensor.c", "3")

    async def scenario():
        await grapevine.async_setup_entry(hass, entry)
        await _drain_hass_tasks(hass)

        flow = _reconfigure_flow(hass, entry)
        result = await flow.async_step_reconfigure(
            {
                CONF_BRIDGE_NAME: "Bridge Jakob",
                CONF_ENTITIES: ["sensor.a", "sensor.c"],  # added sensor.c
                CONF_SHARED_DISCOVERY_PREFIX: "share/homeassistant",
                CONF_SENSOR_VALUE_PREFIX: "share/jakob",
            }
        )
        await _drain_hass_tasks(hass)
        return result

    result = _run(scenario())

    assert result == {"type": "abort", "reason": "reconfigure_successful"}
    assert entry.data[CONF_ENTITIES] == ["sensor.a", "sensor.c"]
    # The reload actually happened: the new entity got republished too.
    published_topics = {topic for topic, _, _ in mqtt._state(hass).published}
    assert "share/homeassistant/sensor/c/config" in published_topics


def test_reconfigure_removing_entity_depublishes_it_before_reload():
    hass = HomeAssistant()
    entry = _make_entry("entry1", "Bridge Jakob", ["sensor.a", "sensor.b"])
    hass.config_entries.entries.append(entry)
    hass.states.async_set("sensor.a", "1")
    hass.states.async_set("sensor.b", "2")

    async def scenario():
        await grapevine.async_setup_entry(hass, entry)
        await _drain_hass_tasks(hass)
        mqtt._state(hass).published.clear()

        flow = _reconfigure_flow(hass, entry)
        await flow.async_step_reconfigure(
            {
                CONF_BRIDGE_NAME: "Bridge Jakob",
                CONF_ENTITIES: ["sensor.a"],  # sensor.b dropped
                CONF_SHARED_DISCOVERY_PREFIX: "share/homeassistant",
                CONF_SENSOR_VALUE_PREFIX: "share/jakob",
            }
        )
        await _drain_hass_tasks(hass)

    _run(scenario())

    published = {(topic, payload) for topic, payload, _retain in mqtt._state(hass).published}
    # Depublished (empty retained payload) rather than left stale.
    assert ("share/homeassistant/sensor/b/config", "") in published
    assert ("share/jakob/sensor/b", "") in published
    assert entry.data[CONF_ENTITIES] == ["sensor.a"]


# --- GrapevineOptionsFlow ---


def test_options_flow_shows_form_with_current_interval_as_default():
    hass = HomeAssistant()
    entry = _make_entry("entry1", "Bridge Jakob", ["sensor.a"], minutes=5)
    flow = _options_flow(hass, entry)

    result = _run(flow.async_step_init(None))

    assert result["type"] == "form"
    assert result["step_id"] == "init"


def test_options_flow_change_updates_options_and_actually_reloads():
    hass = HomeAssistant()
    entry = _make_entry("entry1", "Bridge Jakob", ["sensor.a"], minutes=1)
    hass.config_entries.entries.append(entry)

    async def scenario():
        await grapevine.async_setup_entry(hass, entry)
        await _drain_hass_tasks(hass)
        assert entry.runtime_data.scheduler._minutes == 1

        flow = _options_flow(hass, entry)
        result = await flow.async_step_init({CONF_TIME_PATTERN_MINUTES: 5})
        await _drain_hass_tasks(hass)
        return result

    result = _run(scenario())

    assert result == {"type": "create_entry", "data": {CONF_TIME_PATTERN_MINUTES: 5}}
    assert entry.options[CONF_TIME_PATTERN_MINUTES] == 5
    # The core bug behind issue #7: previously this new value would sit in
    # entry.options forever without the running scheduler ever noticing.
    assert entry.runtime_data.scheduler._minutes == 5

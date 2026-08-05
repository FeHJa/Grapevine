"""Native sensor entity platform for federated (remote-bridge) entities —
see PROTOCOL.md §5a. Platform setup just hands its async_add_entities
callback to the config entry's RemoteEntityManager; entity creation itself
happens there, driven by incoming federation messages, not a static list.
"""

from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    entry.runtime_data.remote_entity_manager.set_add_entities_callback(async_add_entities)


class BridgedSensorEntity(SensorEntity):
    _attr_should_poll = False

    def __init__(
        self,
        *,
        unique_id: str,
        name: str | None,
        device_class: str | None,
        unit_of_measurement: str | None,
        device_identifiers: set[tuple[str, str]],
        device_name: str | None,
        device_sw_version: str | None,
    ) -> None:
        self._attr_unique_id = unique_id
        self._attr_name = name
        self._attr_device_class = device_class
        self._attr_native_unit_of_measurement = unit_of_measurement
        self._attr_device_info = {
            "identifiers": device_identifiers,
            "name": device_name,
            "sw_version": device_sw_version,
        }

    def set_native_value(self, value: str) -> None:
        self._attr_native_value = value
        self.async_write_ha_state()

    def update_from_discovery(
        self,
        *,
        name: str | None,
        device_class: str | None,
        unit_of_measurement: str | None,
        device_identifiers: set[tuple[str, str]],
        device_name: str | None,
        device_sw_version: str | None,
    ) -> None:
        self._attr_name = name
        self._attr_device_class = device_class
        self._attr_native_unit_of_measurement = unit_of_measurement
        self._attr_device_info = {
            "identifiers": device_identifiers,
            "name": device_name,
            "sw_version": device_sw_version,
        }
        self.async_write_ha_state()

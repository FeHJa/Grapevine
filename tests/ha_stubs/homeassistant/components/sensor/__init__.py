"""Minimal fake of homeassistant.components.sensor.SensorEntity — just the
attributes/methods custom_components/ha_mqtt_bridge/sensor.py uses.
"""

from __future__ import annotations

from typing import Any


class SensorEntity:
    _attr_should_poll: bool = True
    _attr_unique_id: str | None = None
    _attr_name: str | None = None
    _attr_device_class: str | None = None
    _attr_native_unit_of_measurement: str | None = None
    _attr_native_value: str | None = None
    _attr_device_info: dict | None = None

    hass: Any = None
    entity_id: str | None = None

    @property
    def unique_id(self) -> str | None:
        return self._attr_unique_id

    @property
    def native_value(self) -> str | None:
        return self._attr_native_value

    async def async_added_to_hass(self) -> None:
        pass

    async def async_will_remove_from_hass(self) -> None:
        pass

    def async_write_ha_state(self) -> None:
        if self.hass is None or self.entity_id is None:
            return
        self.hass.states.async_set(
            self.entity_id,
            "" if self._attr_native_value is None else str(self._attr_native_value),
            {
                "friendly_name": self._attr_name,
                "device_class": self._attr_device_class,
                "unit_of_measurement": self._attr_native_unit_of_measurement,
            },
        )

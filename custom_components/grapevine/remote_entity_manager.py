"""Materializes federated (remote-bridge) discovery messages as native
Home Assistant entities — see PROTOCOL.md §5a.

Owns the per-entity MQTT state-topic subscription directly, rather than
via entity lifecycle hooks (`async_added_to_hass`/`async_will_remove_from_hass`),
so entity creation and its state feed are wired up atomically and don't
depend on entity-platform timing.
"""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import mqtt_io
from .const import DOMAIN
from .sensor import BridgedSensorEntity

_LOGGER = logging.getLogger(__name__)


class RemoteEntityManager:
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self._hass = hass
        self._entry = entry
        self._entities: dict[str, BridgedSensorEntity] = {}
        self._state_unsubs: dict[str, callable] = {}
        self._add_entities_callback: AddEntitiesCallback | None = None

    def set_add_entities_callback(self, callback: AddEntitiesCallback) -> None:
        self._add_entities_callback = callback

    async def async_handle_discovery(self, payload_data: dict) -> None:
        unique_id = payload_data.get("unique_id")
        state_topic = payload_data.get("state_topic")
        if not unique_id or not state_topic:
            _LOGGER.debug(
                "Ignoring federated discovery payload missing unique_id/state_topic"
            )
            return

        name = payload_data.get("name")
        device_class = payload_data.get("device_class")
        unit_of_measurement = payload_data.get("unit_of_measurement")
        device = payload_data.get("device") or {}
        device_identifiers = {(DOMAIN, ident) for ident in device.get("identifiers", [])}
        device_name = device.get("name")
        device_sw_version = device.get("sw_version")

        existing = self._entities.get(unique_id)
        if existing is not None:
            existing.update_from_discovery(
                name=name,
                device_class=device_class,
                unit_of_measurement=unit_of_measurement,
                device_identifiers=device_identifiers,
                device_name=device_name,
                device_sw_version=device_sw_version,
            )
            return

        entity = BridgedSensorEntity(
            unique_id=unique_id,
            name=name,
            device_class=device_class,
            unit_of_measurement=unit_of_measurement,
            device_identifiers=device_identifiers,
            device_name=device_name,
            device_sw_version=device_sw_version,
        )

        if self._add_entities_callback is None:
            _LOGGER.warning(
                "Discovered federated entity %s before the sensor platform was "
                "ready; dropping",
                unique_id,
            )
            return

        self._entities[unique_id] = entity
        self._state_unsubs[unique_id] = await mqtt_io.async_subscribe(
            self._hass, state_topic, self._make_state_handler(unique_id)
        )
        self._add_entities_callback([entity])
        # Discovery alone doesn't carry a state value (§3/§4 are separate
        # messages) -- write once now so the entity is visible immediately
        # rather than absent from hass.states until its first state_topic
        # message arrives.
        entity.async_write_ha_state()

    def _make_state_handler(self, unique_id: str):
        async def _handle_state_message(msg) -> None:
            entity = self._entities.get(unique_id)
            if entity is not None:
                entity.set_native_value(msg.payload)

        return _handle_state_message

    async def async_unload(self) -> None:
        for unsub in self._state_unsubs.values():
            unsub()
        self._state_unsubs.clear()
        self._entities.clear()

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
from homeassistant.helpers import entity_registry as er
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
        self._topic_to_unique_id: dict[str, str] = {}
        self._add_entities_callback: AddEntitiesCallback | None = None

    def set_add_entities_callback(self, callback: AddEntitiesCallback) -> None:
        self._add_entities_callback = callback

    async def async_handle_discovery(self, topic: str, payload_data: dict) -> None:
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
            self._topic_to_unique_id[topic] = unique_id
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
        self._topic_to_unique_id[topic] = unique_id
        self._state_unsubs[unique_id] = await mqtt_io.async_subscribe(
            self._hass, state_topic, self._make_state_handler(unique_id)
        )
        self._add_entities_callback([entity])
        # Discovery alone doesn't carry a state value (§3/§4 are separate
        # messages) -- write once now so the entity is visible immediately
        # rather than absent from hass.states until its first state_topic
        # message arrives.
        entity.async_write_ha_state()

    async def async_handle_removal(self, topic: str) -> None:
        """An empty retained payload arrived on `topic` (issue #7 / §5's
        removal convention). Remove whatever entity we last associated
        with this exact topic, if any -- an empty payload carries no
        unique_id of its own, so topic is the only correlation we have."""
        unique_id = self._topic_to_unique_id.pop(topic, None)
        if unique_id is None:
            _LOGGER.debug("Ignoring removal on topic we never discovered anything from: %s", topic)
            return

        unsub = self._state_unsubs.pop(unique_id, None)
        if unsub is not None:
            unsub()

        entity = self._entities.pop(unique_id, None)
        if entity is None:
            return

        entity_id = entity.entity_id
        await entity.async_remove()
        if entity_id is not None:
            registry = er.async_get(self._hass)
            if registry.async_get(entity_id) is not None:
                registry.async_remove(entity_id)

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
        self._topic_to_unique_id.clear()

"""Native sensor entity platform.

Two unrelated groups of entities live here:
- Federated (remote-bridge) entities (PROTOCOL.md §5a) -- platform setup
  just hands its async_add_entities callback to the config entry's
  RemoteEntityManager; entity creation itself happens there, driven by
  incoming federation messages, not a static list.
- This bridge's own diagnostic entities (PROTOCOL.md §9, issue #12) --
  a small, fixed set created once at setup, updated by BridgeScheduler
  each time it publishes a metadata message.
"""

from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_BRIDGE_NAME, PROTOCOL_VERSION, DOMAIN
from .discovery import slugify_bridge_name


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    entry.runtime_data.remote_entity_manager.set_add_entities_callback(async_add_entities)

    metadata_entities = BridgeMetadataEntities(
        bridge_name=entry.data[CONF_BRIDGE_NAME],
        slug_bridge_name=slugify_bridge_name(entry.data[CONF_BRIDGE_NAME]),
        integration_version=entry.runtime_data.integration_version,
    )
    async_add_entities(metadata_entities.entities)
    entry.runtime_data.scheduler.set_metadata_entities(metadata_entities)


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


class _BridgeDiagnosticSensor(SensorEntity):
    """One field of this bridge's own metadata (PROTOCOL.md §9), shown as
    a plain-text diagnostic entity. Deliberately no device_class -- values
    like last_heartbeat are ISO8601 strings straight off the wire, not
    Python datetimes, and forcing e.g. device_class=timestamp without a
    real datetime object risks HA rejecting the state."""

    _attr_should_poll = False
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, *, unique_id: str, name: str, device_info: dict) -> None:
        self._attr_unique_id = unique_id
        self._attr_name = name
        self._attr_device_info = device_info

    def set_native_value(self, value: str) -> None:
        self._attr_native_value = value
        self.async_write_ha_state()


class BridgeMetadataEntities:
    """The fixed set of diagnostic entities for this bridge's own device
    (issue #12) -- created once at platform setup, pushed to on every
    metadata publish via BridgeScheduler.set_metadata_entities."""

    def __init__(self, *, bridge_name: str, slug_bridge_name: str, integration_version: str) -> None:
        device_info = {
            "identifiers": {(DOMAIN, slug_bridge_name)},
            "name": bridge_name,
            "sw_version": f"{integration_version} (protocol v{PROTOCOL_VERSION})",
        }
        self.entity_count = _BridgeDiagnosticSensor(
            unique_id=f"{slug_bridge_name}::entity_count",
            name="Bridged entity count",
            device_info=device_info,
        )
        self.last_heartbeat = _BridgeDiagnosticSensor(
            unique_id=f"{slug_bridge_name}::last_heartbeat",
            name="Last heartbeat",
            device_info=device_info,
        )
        self.ha_version = _BridgeDiagnosticSensor(
            unique_id=f"{slug_bridge_name}::ha_version",
            name="Home Assistant version",
            device_info=device_info,
        )
        self.entities = [self.entity_count, self.last_heartbeat, self.ha_version]

    def update(self, metadata: dict) -> None:
        self.entity_count.set_native_value(str(metadata["entity_count"]))
        self.last_heartbeat.set_native_value(metadata["last_heartbeat"])
        self.ha_version.set_native_value(metadata["ha_version"])

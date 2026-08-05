"""LegacyDiscoveryAdapter — Phase 1's (and today, the only) ProtocolAdapter.

Implements the MQTT-Discovery-emulation protocol reverse-engineered in
PROTOCOL.md §2-§5: own-entity discovery/state publish, federation
subscribe + verbatim forwarding, and the loop-prevention guard.
"""

from __future__ import annotations

import json
import logging

from homeassistant.components import mqtt
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, State

from .. import mqtt_io
from ..const import (
    CONF_BRIDGE_NAME,
    CONF_LOCAL_DISCOVERY_PREFIX,
    CONF_SENSOR_VALUE_PREFIX,
    CONF_SHARED_DISCOVERY_PREFIX,
)
from ..discovery import (
    build_discovery_payload,
    is_own_message,
    object_id_from_entity_id,
    parse_federation_topic,
    slugify_bridge_name,
)
from ..protocol import ProtocolAdapter

_LOGGER = logging.getLogger(__name__)


class LegacyDiscoveryAdapter(ProtocolAdapter):
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self._hass = hass
        self._shared_discovery_prefix = entry.data[CONF_SHARED_DISCOVERY_PREFIX]
        self._local_discovery_prefix = entry.data[CONF_LOCAL_DISCOVERY_PREFIX]
        self._sensor_value_prefix = entry.data[CONF_SENSOR_VALUE_PREFIX]
        self._bridge_name = entry.data[CONF_BRIDGE_NAME]
        self._slug_bridge_name = slugify_bridge_name(self._bridge_name)

    def topics_to_subscribe(self) -> list[str]:
        # PROTOCOL.md §5: subscribe using the *configured* shared prefix,
        # not the blueprint's hardcoded literal.
        return [f"{self._shared_discovery_prefix}+/+/config"]

    async def publish_own_entity(self, entity_id: str, state: State) -> None:
        object_id = object_id_from_entity_id(entity_id)
        payload = build_discovery_payload(
            entity_id=entity_id,
            friendly_name=state.attributes.get("friendly_name"),
            device_class=state.attributes.get("device_class"),
            unit_of_measurement=state.attributes.get("unit_of_measurement"),
            bridge_name=self._bridge_name,
            slug_bridge_name=self._slug_bridge_name,
            sensor_value_prefix=self._sensor_value_prefix,
        )
        discovery_topic = f"{self._shared_discovery_prefix}sensor/{object_id}/config"
        state_topic = f"{self._sensor_value_prefix}sensor/{object_id}"

        await mqtt_io.async_publish(self._hass, discovery_topic, json.dumps(payload), retain=True)
        # PROTOCOL.md §4: raw state string, no JSON wrapping.
        await mqtt_io.async_publish(self._hass, state_topic, state.state, retain=True)

    async def handle_incoming_message(self, topic: str, payload: str) -> None:
        parsed = parse_federation_topic(topic, self._shared_discovery_prefix)
        if parsed is None:
            _LOGGER.debug("Ignoring message on unexpected topic shape: %s", topic)
            return
        component, object_id = parsed

        try:
            payload_data = json.loads(payload)
        except (json.JSONDecodeError, TypeError):
            _LOGGER.debug("Ignoring non-JSON discovery payload on %s", topic)
            return

        if is_own_message(payload_data, self._slug_bridge_name):
            return

        forward_topic = f"{self._local_discovery_prefix}/{component}/{object_id}/config"
        # Verbatim byte passthrough (PROTOCOL.md §5) — forward exactly what
        # was received, never a re-serialization of payload_data.
        await mqtt_io.async_publish(self._hass, forward_topic, payload, retain=True)

    async def async_handle_mqtt_message(self, msg: mqtt.ReceiveMessage) -> None:
        await self.handle_incoming_message(msg.topic, msg.payload)

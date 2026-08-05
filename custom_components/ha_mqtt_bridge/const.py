"""Constants for the HA MQTT Bridge integration.

Values here are the wire-protocol contract reverse-engineered in
PROTOCOL.md — keep this module in sync with that document, not the other
way around.
"""

from __future__ import annotations

import re

DOMAIN = "ha_mqtt_bridge"

# Config entry keys (PROTOCOL.md §1)
CONF_ENTITIES = "entities"
CONF_SHARED_DISCOVERY_PREFIX = "shared_discovery_prefix"
CONF_LOCAL_DISCOVERY_PREFIX = "local_discovery_prefix"
CONF_SENSOR_VALUE_PREFIX = "sensor_value_prefix"
CONF_BRIDGE_NAME = "bridge_name"
CONF_TIME_PATTERN_MINUTES = "time_pattern_minutes"

DEFAULT_SHARED_DISCOVERY_PREFIX = "share/homeassistant/"
DEFAULT_LOCAL_DISCOVERY_PREFIX = "homeassistant"
DEFAULT_SENSOR_VALUE_PREFIX = "share/jakob/"
DEFAULT_BRIDGE_NAME = "Bridge Jakob"
DEFAULT_TIME_PATTERN_MINUTES = 1

# Discovery payload (PROTOCOL.md §3)
SW_VERSION = "1.0.3"
PROTOCOL_VERSION = 1

# Jitter (PROTOCOL.md §6)
JITTER_MAX_SECONDS = 9

SERVICE_REPUBLISH = "republish"
ATTR_CONFIG_ENTRY_ID = "config_entry_id"


def _pattern(word: str) -> re.Pattern[str]:
    return re.compile(rf"(^|_){word}(_|$)", re.IGNORECASE)


# device_class / unit_of_measurement fallback table (PROTOCOL.md §3).
# Pattern shape "(^|_)<word>(_|$)" and match order are load-bearing for
# interop with the other bridge instances — do not rewrite or reorder.
DEVICE_CLASS_UNIT_PATTERNS: list[tuple[re.Pattern[str], str, str]] = [
    (_pattern("temperature"), "temperature", "°C"),
    (_pattern("humidity"), "humidity", "%"),
    (_pattern("pressure"), "pressure", "hPa"),
    (_pattern("power"), "power", "W"),
    (_pattern("energy"), "energy", "kWh"),
    (_pattern("current"), "current", "A"),
    (_pattern("voltage"), "voltage", "V"),
    (_pattern("light"), "illuminance", "lx"),
]

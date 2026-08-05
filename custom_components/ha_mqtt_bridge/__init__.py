"""HA MQTT Bridge — native integration port of the MQTT bridge blueprint.

See PROTOCOL.md for the wire-protocol contract this must reproduce, and
MIGRATION_PLAN.md for the phased rollout this is Phase 1 of.
"""

from __future__ import annotations

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ConfigEntryNotReady, ServiceValidationError
from homeassistant.helpers import config_validation as cv

from . import mqtt_io
from .adapters.legacy_discovery import LegacyDiscoveryAdapter
from .const import ATTR_CONFIG_ENTRY_ID, DOMAIN, SERVICE_REPUBLISH
from .scheduler import BridgeScheduler

SERVICE_REPUBLISH_SCHEMA = vol.Schema({vol.Required(ATTR_CONFIG_ENTRY_ID): cv.string})


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    if not await mqtt_io.async_wait_for_mqtt_client(hass):
        raise ConfigEntryNotReady("MQTT integration is not ready")

    adapter = LegacyDiscoveryAdapter(hass, entry)
    scheduler = BridgeScheduler(hass, entry, adapter)
    entry.runtime_data = scheduler

    # Services are domain-global, not per-entry, so on-demand republish
    # dispatches through a small entry-keyed registry rather than a
    # singleton — this keeps the signature stable when Phase 2 multi-entry
    # support lands (MIGRATION_PLAN.md Decision 3).
    handlers = hass.data.setdefault(DOMAIN, {}).setdefault("republish_handlers", {})
    handlers[entry.entry_id] = scheduler.async_republish_all
    entry.async_on_unload(lambda: handlers.pop(entry.entry_id, None))

    if not hass.services.has_service(DOMAIN, SERVICE_REPUBLISH):
        hass.services.async_register(
            DOMAIN,
            SERVICE_REPUBLISH,
            _make_republish_service_handler(hass),
            schema=SERVICE_REPUBLISH_SCHEMA,
        )

    await scheduler.async_setup()
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    # Subscriptions, the time_pattern trigger, in-flight jittered tasks and
    # the republish-handler registration were all registered via
    # entry.async_on_unload during setup, so the framework tears them down
    # after this returns — nothing else to do here.
    return True


def _make_republish_service_handler(hass: HomeAssistant):
    async def _async_handle_republish(call: ServiceCall) -> None:
        entry_id = call.data[ATTR_CONFIG_ENTRY_ID]
        handlers = hass.data.get(DOMAIN, {}).get("republish_handlers", {})
        handler = handlers.get(entry_id)
        if handler is None:
            raise ServiceValidationError(f"No HA MQTT Bridge instance for config entry {entry_id}")
        handler()

    return _async_handle_republish

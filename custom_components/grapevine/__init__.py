"""Grapevine — peer-to-peer entity federation for Home Assistant.

A native integration port of the MQTT bridge blueprint. See PROTOCOL.md
for the wire-protocol contract this must reproduce, and MIGRATION_PLAN.md
for the phased rollout this is Phase 1(b) of.
"""

from __future__ import annotations

from dataclasses import dataclass

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ConfigEntryNotReady, ServiceValidationError
from homeassistant.helpers import config_validation as cv

from . import mqtt_io
from .adapters.legacy_discovery import LegacyDiscoveryAdapter
from .const import ATTR_CONFIG_ENTRY_ID, DOMAIN, SERVICE_REPUBLISH
from .remote_entity_manager import RemoteEntityManager
from .scheduler import BridgeScheduler

PLATFORMS: list[str] = ["sensor"]

SERVICE_REPUBLISH_SCHEMA = vol.Schema({vol.Required(ATTR_CONFIG_ENTRY_ID): cv.string})


@dataclass
class GrapevineRuntimeData:
    scheduler: BridgeScheduler
    remote_entity_manager: RemoteEntityManager


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    if not await mqtt_io.async_wait_for_mqtt_client(hass):
        raise ConfigEntryNotReady("MQTT integration is not ready")

    remote_entity_manager = RemoteEntityManager(hass, entry)
    adapter = LegacyDiscoveryAdapter(hass, entry, remote_entity_manager)
    scheduler = BridgeScheduler(hass, entry, adapter)
    entry.runtime_data = GrapevineRuntimeData(
        scheduler=scheduler, remote_entity_manager=remote_entity_manager
    )
    entry.async_on_unload(remote_entity_manager.async_unload)

    # Must happen before scheduler.async_setup() starts the federation MQTT
    # subscription below -- the sensor platform registers the
    # async_add_entities callback RemoteEntityManager needs before it can
    # materialize anything (§5a); this ordering, not a queue, is what
    # prevents an early incoming message from being dropped.
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

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
    # Unloading the sensor platform removes the native entities this entry
    # created (§5a) -- this is what makes "remove the bridge" actually
    # clean up after itself for federated entities, unlike the old
    # forward-to-local-discovery approach where HA's own mqtt integration
    # owned that lifecycle.
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


def _make_republish_service_handler(hass: HomeAssistant):
    async def _async_handle_republish(call: ServiceCall) -> None:
        entry_id = call.data[ATTR_CONFIG_ENTRY_ID]
        handlers = hass.data.get(DOMAIN, {}).get("republish_handlers", {})
        handler = handlers.get(entry_id)
        if handler is None:
            raise ServiceValidationError(f"No Grapevine instance for config entry {entry_id}")
        handler()

    return _async_handle_republish

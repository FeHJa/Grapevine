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
from .const import ATTR_CONFIG_ENTRY_ID, CONF_ENTITIES, DOMAIN, SERVICE_REPUBLISH
from .remote_entity_manager import RemoteEntityManager
from .scheduler import BridgeScheduler
from .version import integration_version

PLATFORMS: list[str] = ["sensor"]

SERVICE_REPUBLISH_SCHEMA = vol.Schema({vol.Required(ATTR_CONFIG_ENTRY_ID): cv.string})


@dataclass
class GrapevineRuntimeData:
    scheduler: BridgeScheduler
    remote_entity_manager: RemoteEntityManager
    protocol_adapter: LegacyDiscoveryAdapter
    integration_version: str


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    if not await mqtt_io.async_wait_for_mqtt_client(hass):
        raise ConfigEntryNotReady("MQTT integration is not ready")

    # integration_version() reads manifest.json off disk -- must not run
    # directly on the event loop (issue #13: this crashed/hung the entry
    # on every setup, including reload, when called synchronously from
    # LegacyDiscoveryAdapter's constructor).
    version = await hass.async_add_executor_job(integration_version)

    remote_entity_manager = RemoteEntityManager(hass, entry)
    adapter = LegacyDiscoveryAdapter(hass, entry, remote_entity_manager, version)
    scheduler = BridgeScheduler(hass, entry, adapter)
    entry.runtime_data = GrapevineRuntimeData(
        scheduler=scheduler,
        remote_entity_manager=remote_entity_manager,
        protocol_adapter=adapter,
        integration_version=version,
    )
    entry.async_on_unload(remote_entity_manager.async_unload)
    # GrapevineOptionsFlow's single "Configure" step (data and options
    # fields alike) goes through hass.config_entries.async_update_entry,
    # which is what fires this (issue #7; previously nothing reloaded the
    # entry after a change).
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))

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

    def _unregister_republish_handler() -> None:
        # Not `lambda: handlers.pop(...)` -- dict.pop() returns the
        # removed value (the scheduler method itself), and HA's real
        # on_unload processing treats a truthy callback return as a job
        # to schedule as a task, then crashes trying to wrap a plain
        # bound method as a coroutine. This wrapper discards the result
        # so the callback returns None, as every other on_unload
        # callback here does.
        handlers.pop(entry.entry_id, None)

    entry.async_on_unload(_unregister_republish_handler)

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


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    # The receiving-side half of cleanup (native entities) is handled by
    # async_unload_entry above via the platform unload, which HA calls
    # before this. This is the sending-side half (issue #7): depublish
    # every entity this bridge was publishing, so other instances --
    # Grapevine or blueprint -- don't keep it around as a stale entity
    # forever. Uses the same async_depublish_entity as the options flow's
    # per-entity removal.
    runtime_data: GrapevineRuntimeData | None = entry.runtime_data
    if runtime_data is None:
        return
    for entity_id in entry.data.get(CONF_ENTITIES, []):
        await runtime_data.protocol_adapter.async_depublish_entity(entity_id)


async def _async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


def _make_republish_service_handler(hass: HomeAssistant):
    async def _async_handle_republish(call: ServiceCall) -> None:
        entry_id = call.data[ATTR_CONFIG_ENTRY_ID]
        handlers = hass.data.get(DOMAIN, {}).get("republish_handlers", {})
        handler = handlers.get(entry_id)
        if handler is None:
            raise ServiceValidationError(f"No Grapevine instance for config entry {entry_id}")
        handler()

    return _async_handle_republish

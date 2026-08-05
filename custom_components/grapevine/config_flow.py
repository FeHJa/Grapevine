"""Config flow — maps the blueprint's inputs (PROTOCOL.md §1) onto a config
entry. Three flows: initial setup (async_step_user), editing the identity
fields on an existing entry (async_step_reconfigure, issue #7), and editing
the republish interval (GrapevineOptionsFlow, issue #7)."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    CONF_BRIDGE_NAME,
    CONF_ENTITIES,
    CONF_SENSOR_VALUE_PREFIX,
    CONF_SHARED_DISCOVERY_PREFIX,
    CONF_TIME_PATTERN_MINUTES,
    DEFAULT_BRIDGE_NAME,
    DEFAULT_SENSOR_VALUE_PREFIX,
    DEFAULT_SHARED_DISCOVERY_PREFIX,
    DEFAULT_TIME_PATTERN_MINUTES,
    DOMAIN,
)
from .discovery import normalize_prefix, slugify_bridge_name

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_BRIDGE_NAME, default=DEFAULT_BRIDGE_NAME): str,
        vol.Required(CONF_ENTITIES): selector.EntitySelector(
            selector.EntitySelectorConfig(multiple=True)
        ),
        vol.Required(
            CONF_SHARED_DISCOVERY_PREFIX, default=DEFAULT_SHARED_DISCOVERY_PREFIX
        ): str,
        vol.Required(CONF_SENSOR_VALUE_PREFIX, default=DEFAULT_SENSOR_VALUE_PREFIX): str,
        vol.Required(
            CONF_TIME_PATTERN_MINUTES, default=DEFAULT_TIME_PATTERN_MINUTES
        ): vol.All(vol.Coerce(int), vol.Range(min=1, max=60)),
    }
)

TIME_PATTERN_SELECTOR = vol.All(vol.Coerce(int), vol.Range(min=1, max=60))


def _reconfigure_schema(current: dict[str, Any]) -> vol.Schema:
    # Deliberately excludes time_pattern_minutes -- that's the options
    # flow's field, not this one's (data vs. options split, see
    # MIGRATION_PLAN.md's Config entry mapping section).
    return vol.Schema(
        {
            vol.Required(CONF_BRIDGE_NAME, default=current[CONF_BRIDGE_NAME]): str,
            vol.Required(
                CONF_ENTITIES, default=current[CONF_ENTITIES]
            ): selector.EntitySelector(selector.EntitySelectorConfig(multiple=True)),
            vol.Required(
                CONF_SHARED_DISCOVERY_PREFIX, default=current[CONF_SHARED_DISCOVERY_PREFIX]
            ): str,
            vol.Required(
                CONF_SENSOR_VALUE_PREFIX, default=current[CONF_SENSOR_VALUE_PREFIX]
            ): str,
        }
    )


class GrapevineConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> config_entries.ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            slug_bridge_name = slugify_bridge_name(user_input[CONF_BRIDGE_NAME])
            entities = user_input[CONF_ENTITIES]

            if not slug_bridge_name:
                errors["base"] = "invalid_bridge_name"
            elif not entities:
                errors["base"] = "no_entities"
            else:
                await self.async_set_unique_id(slug_bridge_name)
                self._abort_if_unique_id_configured()

                data = {
                    CONF_ENTITIES: entities,
                    CONF_SHARED_DISCOVERY_PREFIX: normalize_prefix(
                        user_input[CONF_SHARED_DISCOVERY_PREFIX]
                    ),
                    CONF_SENSOR_VALUE_PREFIX: normalize_prefix(
                        user_input[CONF_SENSOR_VALUE_PREFIX]
                    ),
                    CONF_BRIDGE_NAME: user_input[CONF_BRIDGE_NAME],
                }
                options = {CONF_TIME_PATTERN_MINUTES: user_input[CONF_TIME_PATTERN_MINUTES]}

                return self.async_create_entry(
                    title=user_input[CONF_BRIDGE_NAME], data=data, options=options
                )

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        reconfigure_entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}

        if user_input is not None:
            slug_bridge_name = slugify_bridge_name(user_input[CONF_BRIDGE_NAME])
            entities = user_input[CONF_ENTITIES]

            if not slug_bridge_name:
                errors["base"] = "invalid_bridge_name"
            elif not entities:
                errors["base"] = "no_entities"
            elif any(
                entry.entry_id != reconfigure_entry.entry_id
                and entry.unique_id == slug_bridge_name
                for entry in self._async_current_entries()
            ):
                # Renaming the bridge is allowed (it's the same case as
                # any other identity field changing) -- this only rejects
                # renaming *onto* a slug some other entry already owns.
                errors["base"] = "already_configured"
            else:
                # Depublish entities dropped from the list *before*
                # updating entry.data, while we can still reach the live
                # adapter -- see PROTOCOL.md §5/async_depublish_entity and
                # issue #7. Renaming the bridge itself (slug change) is
                # not handled here: that would orphan every entity under
                # the old slug too, which is a separate, not-yet-decided
                # piece of scope.
                removed_entities = set(reconfigure_entry.data[CONF_ENTITIES]) - set(entities)
                runtime_data = reconfigure_entry.runtime_data
                if runtime_data is not None:
                    for entity_id in removed_entities:
                        await runtime_data.protocol_adapter.async_depublish_entity(entity_id)

                await self.async_set_unique_id(slug_bridge_name)

                new_data = {
                    CONF_ENTITIES: entities,
                    CONF_SHARED_DISCOVERY_PREFIX: normalize_prefix(
                        user_input[CONF_SHARED_DISCOVERY_PREFIX]
                    ),
                    CONF_SENSOR_VALUE_PREFIX: normalize_prefix(
                        user_input[CONF_SENSOR_VALUE_PREFIX]
                    ),
                    CONF_BRIDGE_NAME: user_input[CONF_BRIDGE_NAME],
                }
                # Triggers the update listener registered in __init__.py,
                # which reloads the entry -- no manual reload call here.
                self.hass.config_entries.async_update_entry(
                    reconfigure_entry, title=user_input[CONF_BRIDGE_NAME], data=new_data
                )
                return self.async_abort(reason="reconfigure_successful")

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=_reconfigure_schema(reconfigure_entry.data),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> GrapevineOptionsFlow:
        return GrapevineOptionsFlow()


class GrapevineOptionsFlow(config_entries.OptionsFlow):
    """Just time_pattern_minutes -- the only field that was ever designed
    to be safely reconfigurable without touching entry.data (see
    MIGRATION_PLAN.md's Config entry mapping section). Does not set
    self.config_entry in __init__: that's deprecated as of HA 2025.12 in
    favor of the base class providing it automatically."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        if user_input is not None:
            # async_create_entry here sets entry.options directly (not a
            # new entry) and triggers the same update listener as
            # reconfigure does, reloading the entry.
            return self.async_create_entry(data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_TIME_PATTERN_MINUTES,
                        default=self.config_entry.options.get(
                            CONF_TIME_PATTERN_MINUTES, DEFAULT_TIME_PATTERN_MINUTES
                        ),
                    ): TIME_PATTERN_SELECTOR,
                }
            ),
        )

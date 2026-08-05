"""Config flow — maps the blueprint's inputs (PROTOCOL.md §1) onto a config
entry. Single step, no reconfigure/options flow yet (Phase 2)."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant import config_entries
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

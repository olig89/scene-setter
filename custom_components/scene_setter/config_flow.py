"""Setup. There is nothing to fill in: rooms come from Home Assistant's areas.

The options hold the room settings (set on the page) and two house-wide
settings set here: apostrophes in entity IDs, and the default white for
scenes made from a brightness level.
"""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import CONF_DEFAULT_WHITE, CONF_NO_APOSTROPHES, DEFAULT_WHITE_K, DOMAIN, NAME


class SceneSetterConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(title=NAME, data={}, options={})
        return self.async_show_form(step_id="user")

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return SceneSetterOptionsFlow()


class SceneSetterOptionsFlow(OptionsFlow):
    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            # Keep the room settings the page saved.
            if CONF_DEFAULT_WHITE in user_input:
                user_input[CONF_DEFAULT_WHITE] = int(user_input[CONF_DEFAULT_WHITE])
            return self.async_create_entry(data={**self.config_entry.options, **user_input})
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_NO_APOSTROPHES,
                        default=bool(self.config_entry.options.get(CONF_NO_APOSTROPHES, False)),
                    ): bool,
                    vol.Required(
                        CONF_DEFAULT_WHITE,
                        default=int(self.config_entry.options.get(CONF_DEFAULT_WHITE, DEFAULT_WHITE_K)),
                    ): selector.ColorTempSelector(
                        selector.ColorTempSelectorConfig(unit="kelvin", min=2000, max=6500)
                    ),
                }
            ),
        )

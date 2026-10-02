"""Setup. There is nothing to fill in: rooms come from Home Assistant's areas."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult

from .const import DOMAIN, NAME


class SceneSetterConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(title=NAME, data={}, options={})
        return self.async_show_form(step_id="user")

"""Scene Setter: save a room's lights and blinds, as they are now, as a scene.

``setter.py`` does the work; ``core/`` holds the parts with no Home Assistant
imports. The page (a sidebar page and a dashboard card, one file) is in ``www/``.
"""

from __future__ import annotations

from pathlib import Path

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_STATE_CHANGED, Platform
from homeassistant.core import Event, HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import (
    area_registry as ar,
    config_validation as cv,
    device_registry as dr,
    entity_registry as er,
)
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.typing import ConfigType

from .const import (
    ANY_SIGNAL,
    DOMAIN,
    FRONTEND_FILE,
    NAME,
    PANEL_COMPONENT,
    PANEL_URL,
    SERVICE_CREATE,
    SERVICE_DELETE,
    SERVICE_RENAME,
    SERVICE_SAVE,
    STATIC_URL,
)
from .setter import SceneSetter, SceneSetterError
from .websocket import async_register_websocket

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

type SceneSetterConfigEntry = ConfigEntry[SceneSetter]

PLATFORMS = [Platform.BINARY_SENSOR]  # an "on now" sensor for each scene

SAVE_SCHEMA = vol.All(
    vol.Schema(
        {
            vol.Optional("area_id"): cv.string,
            vol.Optional("name"): cv.string,
            vol.Optional("scene"): cv.entity_domain("scene"),
        }
    ),
    cv.has_at_least_one_key("area_id", "scene"),
)
RENAME_SCHEMA = vol.Schema({vol.Required("scene"): cv.entity_domain("scene"), vol.Required("name"): cv.string})
DELETE_SCHEMA = vol.Schema({vol.Required("scene"): cv.entity_domain("scene")})
PERCENT = vol.All(vol.Coerce(float), vol.Range(min=0, max=100))
KELVIN = vol.All(vol.Coerce(int), vol.Range(min=1000, max=10000))
CREATE_SCHEMA = vol.Schema(
    {
        vol.Required("name"): cv.string,
        vol.Required("brightness"): PERCENT,
        vol.Optional("area_id"): vol.All(cv.ensure_list, [cv.string]),
        vol.Optional("levels"): vol.Schema({cv.entity_domain("light"): PERCENT}),
        vol.Optional("replace", default=False): cv.boolean,
        vol.Optional("color_temp_kelvin"): KELVIN,
        vol.Optional("whites"): vol.Schema({cv.entity_domain("light"): KELVIN}),
    }
)


def setter_of(hass: HomeAssistant) -> SceneSetter | None:
    for entry in hass.config_entries.async_entries(DOMAIN):
        setter = getattr(entry, "runtime_data", None)
        if isinstance(setter, SceneSetter):
            return setter
    return None


async def _async_register_frontend(hass: HomeAssistant) -> None:
    """The sidebar page and the dashboard card. Skipped quietly where the frontend isn't loaded (tests)."""
    if hass.data.get(f"{DOMAIN}_frontend") or "frontend" not in hass.config.components:
        return
    from homeassistant.components import frontend, panel_custom
    from homeassistant.components.http import StaticPathConfig

    www = Path(__file__).parent / "www"
    await hass.http.async_register_static_paths([StaticPathConfig(STATIC_URL, str(www), False)])
    version = (await hass.async_add_executor_job((www / FRONTEND_FILE).stat)).st_mtime_ns
    url = f"{STATIC_URL}/{FRONTEND_FILE}?v={version}"
    await panel_custom.async_register_panel(
        hass,
        frontend_url_path=PANEL_URL,
        webcomponent_name=PANEL_COMPONENT,
        sidebar_title=NAME,
        sidebar_icon="mdi:palette-swatch-variant",
        module_url=url,
        # Everyone in the household can save scenes; the page keeps the room
        # settings for administrators, and the server refuses them to anyone else.
        require_admin=False,
    )
    # Loads the same file on every page, so the card works on any dashboard
    # without adding a resource by hand.
    frontend.add_extra_js_url(hass, url)
    hass.data[f"{DOMAIN}_frontend"] = url


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    async_register_websocket(hass)

    def _setter() -> SceneSetter:
        setter = setter_of(hass)
        if setter is None:
            raise ServiceValidationError("Scene Setter isn't set up. Add it under Settings, Devices & services.")
        return setter

    async def save(call: ServiceCall) -> ServiceResponse:
        try:
            return await _setter().async_save(call.data.get("area_id"), call.data.get("name"), call.data.get("scene"))
        except SceneSetterError as err:
            raise ServiceValidationError(str(err)) from err

    async def rename(call: ServiceCall) -> ServiceResponse:
        try:
            return await _setter().async_rename(call.data["scene"], call.data["name"])
        except SceneSetterError as err:
            raise ServiceValidationError(str(err)) from err

    async def delete(call: ServiceCall) -> ServiceResponse:
        try:
            return await _setter().async_delete(call.data["scene"])
        except SceneSetterError as err:
            raise ServiceValidationError(str(err)) from err

    async def create(call: ServiceCall) -> ServiceResponse:
        try:
            return await _setter().async_create(
                call.data["name"],
                call.data["brightness"],
                call.data.get("area_id"),
                call.data.get("levels"),
                call.data["replace"],
                call.data.get("color_temp_kelvin"),
                call.data.get("whites"),
            )
        except SceneSetterError as err:
            raise ServiceValidationError(str(err)) from err

    optional = SupportsResponse.OPTIONAL
    hass.services.async_register(DOMAIN, SERVICE_SAVE, save, schema=SAVE_SCHEMA, supports_response=optional)
    hass.services.async_register(DOMAIN, SERVICE_RENAME, rename, schema=RENAME_SCHEMA, supports_response=optional)
    hass.services.async_register(DOMAIN, SERVICE_DELETE, delete, schema=DELETE_SCHEMA, supports_response=optional)
    hass.services.async_register(DOMAIN, SERVICE_CREATE, create, schema=CREATE_SCHEMA, supports_response=optional)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: SceneSetterConfigEntry) -> bool:
    entry.runtime_data = SceneSetter(hass, entry)

    @callback
    def _changed(_event: Event | None = None) -> None:
        async_dispatcher_send(hass, ANY_SIGNAL)

    @callback
    def _is_scene(data) -> bool:
        return data["entity_id"].startswith("scene.")

    @callback
    def _scene_changed(event: Event) -> None:
        # A scene appearing or going (the scene editor, a reload) changes the lists.
        if event.data.get("old_state") is None or event.data.get("new_state") is None:
            _changed()

    for event_type in (
        er.EVENT_ENTITY_REGISTRY_UPDATED,
        dr.EVENT_DEVICE_REGISTRY_UPDATED,
        ar.EVENT_AREA_REGISTRY_UPDATED,
    ):
        entry.async_on_unload(hass.bus.async_listen(event_type, _changed))
    entry.async_on_unload(hass.bus.async_listen(EVENT_STATE_CHANGED, _scene_changed, event_filter=_is_scene))
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    await _async_register_frontend(hass)
    _changed()
    return True


async def _async_options_updated(hass: HomeAssistant, entry: SceneSetterConfigEntry) -> None:
    async_dispatcher_send(hass, ANY_SIGNAL)


async def async_unload_entry(hass: HomeAssistant, entry: SceneSetterConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    async_dispatcher_send(hass, ANY_SIGNAL)
    return unloaded


async def async_remove_entry(hass: HomeAssistant, entry: SceneSetterConfigEntry) -> None:
    if url := hass.data.pop(f"{DOMAIN}_frontend", None):
        from homeassistant.components import frontend

        frontend.async_remove_panel(hass, PANEL_URL)
        frontend.remove_extra_js_url(hass, url)

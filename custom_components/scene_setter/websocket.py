"""The page's API (websocket commands).

Seeing the rooms and saving, renaming or deleting a scene are open to anyone
who can open the page, so the whole household can use it. Choosing which
lights and blinds a room saves is for administrators only: the page hides it
from other users and ``save_room`` refuses them.
"""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.event import async_call_later

from .const import ANY_SIGNAL, DOMAIN, VERSION
from .setter import SceneSetter, SceneSetterError


def async_register_websocket(hass: HomeAssistant) -> None:
    for command in (ws_subscribe, ws_save, ws_rename, ws_delete, ws_save_room):
        websocket_api.async_register_command(hass, command)


def _setter(hass: HomeAssistant) -> SceneSetter | None:
    for entry in hass.config_entries.async_entries(DOMAIN):
        setter = getattr(entry, "runtime_data", None)
        if isinstance(setter, SceneSetter):
            return setter
    return None


def snapshot(hass: HomeAssistant) -> dict[str, Any]:
    setter = _setter(hass)
    if setter is None:
        return {"version": VERSION, "set_up": False}
    return {"version": VERSION, "set_up": True, "rooms": setter.snapshot()}


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/subscribe"})
@callback
def ws_subscribe(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    """The rooms as the page shows them, sent now and again after every change (at most every 0.3 s)."""
    pending: dict[str, Any] = {"cancel": None}

    @callback
    def _send(_now=None) -> None:
        pending["cancel"] = None
        connection.send_message(websocket_api.event_message(msg["id"], snapshot(hass)))

    @callback
    def _changed() -> None:
        if pending["cancel"] is None:
            pending["cancel"] = async_call_later(hass, 0.3, _send)

    unsub = async_dispatcher_connect(hass, ANY_SIGNAL, _changed)

    @callback
    def _unsubscribe() -> None:
        unsub()
        if pending["cancel"]:
            pending["cancel"]()

    connection.subscriptions[msg["id"]] = _unsubscribe
    connection.send_result(msg["id"])
    _send()


async def _run(hass, connection, msg, action) -> None:
    setter = _setter(hass)
    if setter is None:
        connection.send_error(msg["id"], "not_set_up", "Scene Setter isn't set up")
        return
    try:
        result = await action(setter)
    except SceneSetterError as err:
        connection.send_error(msg["id"], err.key, str(err))
        return
    connection.send_result(msg["id"], result)


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/save",
        vol.Optional("area_id"): str,
        vol.Optional("name"): str,
        # Save over this scene (its entity id), whatever its name.
        vol.Optional("scene"): str,
    }
)
@websocket_api.async_response
async def ws_save(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    await _run(hass, connection, msg, lambda s: s.async_save(msg.get("area_id"), msg.get("name"), msg.get("scene")))


@websocket_api.websocket_command(
    {vol.Required("type"): f"{DOMAIN}/rename", vol.Required("scene"): str, vol.Required("name"): str}
)
@websocket_api.async_response
async def ws_rename(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    await _run(hass, connection, msg, lambda s: s.async_rename(msg["scene"], msg["name"]))


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/delete", vol.Required("scene"): str})
@websocket_api.async_response
async def ws_delete(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    await _run(hass, connection, msg, lambda s: s.async_delete(msg["scene"]))


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/save_room",
        vol.Required("area_id"): str,
        vol.Optional("exclude", default=list): [str],
        vol.Optional("include", default=list): [str],
    }
)
@websocket_api.async_response
async def ws_save_room(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    if not connection.user.is_admin:
        connection.send_error(msg["id"], "unauthorized", "Only an administrator can change this")
        return

    async def action(setter: SceneSetter) -> None:
        setter.set_room(msg["area_id"], msg["exclude"], msg["include"])

    await _run(hass, connection, msg, action)

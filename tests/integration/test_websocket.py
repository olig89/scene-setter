"""The page's API."""

from homeassistant.core import HomeAssistant
from homeassistant.util.yaml import load_yaml


async def test_subscribe_sends_rooms_and_updates(hass: HomeAssistant, house, hass_ws_client):
    client = await hass_ws_client(hass)
    await client.send_json({"id": 1, "type": "scene_setter/subscribe"})
    assert (await client.receive_json())["success"]
    first = (await client.receive_json())["event"]
    assert first["set_up"] is True
    assert first["rooms"][0]["scenes"] == []

    await client.send_json({"id": 2, "type": "scene_setter/save", "area_id": "kitchen", "name": "Evening"})
    seen = None
    saved = None
    while seen is None or saved is None:
        message = await client.receive_json()
        if message["id"] == 2:
            saved = message
        elif message["event"]["rooms"][0]["scenes"]:
            seen = message["event"]
    assert saved["success"] and saved["result"]["scene"] == "scene.kitchen_evening"
    assert seen["rooms"][0]["scenes"][0]["name"] == "Evening"


async def test_errors_carry_a_key(hass: HomeAssistant, house, hass_ws_client):
    client = await hass_ws_client(hass)
    await client.send_json({"id": 1, "type": "scene_setter/save", "area_id": "kitchen", "name": " "})
    reply = await client.receive_json()
    assert not reply["success"]
    assert reply["error"]["code"] == "invalid_name"


async def test_rename_and_delete(hass: HomeAssistant, house, hass_ws_client):
    client = await hass_ws_client(hass)
    await client.send_json({"id": 1, "type": "scene_setter/save", "area_id": "kitchen", "name": "Evening"})
    assert (await client.receive_json())["success"]
    await client.send_json({"id": 2, "type": "scene_setter/rename", "scene": "scene.kitchen_evening", "name": "Late"})
    assert (await client.receive_json())["result"]["name"] == "Late"
    assert load_yaml(str(house.scenes_file))[0]["name"] == "Kitchen Late"
    await client.send_json({"id": 3, "type": "scene_setter/delete", "scene": "scene.kitchen_evening"})
    assert (await client.receive_json())["success"]
    assert load_yaml(str(house.scenes_file)) == []


async def test_room_settings_are_for_admins(hass: HomeAssistant, house, hass_ws_client, hass_admin_user):
    hass_admin_user.groups = []
    client = await hass_ws_client(hass)
    await client.send_json({"id": 1, "type": "scene_setter/save_room", "area_id": "kitchen", "exclude": ["cover.blind"]})
    reply = await client.receive_json()
    assert reply["error"]["code"] == "unauthorized"
    assert house.entry.options == {}


async def test_admin_can_change_room_settings(hass: HomeAssistant, house, hass_ws_client):
    client = await hass_ws_client(hass)
    await client.send_json({"id": 1, "type": "scene_setter/save_room", "area_id": "kitchen", "exclude": ["cover.blind"]})
    assert (await client.receive_json())["success"]
    assert house.entry.options["rooms"]["kitchen"]["exclude"] == ["cover.blind"]

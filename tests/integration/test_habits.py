"""The log behind suggested scenes, and the page's suggestion buttons."""

from datetime import timedelta

from pytest_homeassistant_custom_component.common import async_fire_time_changed

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from homeassistant.util.yaml import load_yaml

from custom_components.scene_setter.core.habits import Setting
from custom_components.scene_setter.habits import SETTLE_S

CEILING = {"color_mode": "brightness", "supported_color_modes": ["brightness"]}


async def settle(hass: HomeAssistant, freezer) -> None:
    freezer.tick(timedelta(seconds=SETTLE_S + 1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


async def test_a_change_is_logged_once_the_lights_settle(hass: HomeAssistant, house, freezer):
    log = house.setter.habits
    hass.states.async_set("light.ceiling", "on", {"brightness": 90, **CEILING})
    await hass.async_block_till_done()
    freezer.tick(timedelta(seconds=60))
    async_fire_time_changed(hass)
    hass.states.async_set("light.ceiling", "on", {"brightness": 80, **CEILING})  # still being set
    await hass.async_block_till_done()
    assert log.settings == []

    await settle(hass, freezer)
    (setting,) = log.settings
    assert setting.area_id == "kitchen"
    assert setting.lights["light.ceiling"] == {"state": "on", "brightness": 80}
    assert set(setting.lights) == {"light.ceiling", "light.island", "light.counter"}  # lights only, no blind

    # A nudge too small to be a different setting isn't logged again.
    hass.states.async_set("light.ceiling", "on", {"brightness": 85, **CEILING})
    await settle(hass, freezer)
    assert len(log.settings) == 1


async def test_off_and_back_on_counts_again(hass: HomeAssistant, house, freezer):
    log = house.setter.habits
    hass.states.async_set("light.ceiling", "on", {"brightness": 80, **CEILING})
    await settle(hass, freezer)
    for light in ("light.ceiling", "light.island"):
        hass.states.async_set(light, "off", {})
    await settle(hass, freezer)
    assert len(log.settings) == 1  # all off: not a setting
    hass.states.async_set("light.ceiling", "on", {"brightness": 80, **CEILING})
    await settle(hass, freezer)
    assert len(log.settings) == 2


async def test_lights_coming_back_is_not_a_setting(hass: HomeAssistant, house, freezer):
    hass.states.async_set("light.ceiling", "unavailable", {})
    await hass.async_block_till_done()
    hass.states.async_set("light.ceiling", "on", {"brightness": 30, **CEILING})
    await settle(hass, freezer)
    assert house.setter.habits.settings == []


def seed(house, brightness: int = 120, days=(1, 2, 3, 4)) -> None:
    now = dt_util.now()
    for day in days:
        house.setter.habits.settings.append(
            Setting(
                now - timedelta(days=day),
                "kitchen",
                {"light.ceiling": {"state": "on", "brightness": brightness}, "light.counter": {"state": "off"}},
            )
        )


async def test_suggestions_reach_the_page_and_can_be_saved(hass: HomeAssistant, house, hass_ws_client):
    seed(house)
    client = await hass_ws_client(hass)
    await client.send_json({"id": 1, "type": "scene_setter/subscribe"})
    assert (await client.receive_json())["success"]
    room = (await client.receive_json())["event"]["rooms"][0]
    (suggestion,) = room["suggestions"]
    assert suggestion["count"] == 4 and suggestion["days"] == 4

    await client.send_json({"id": 2, "type": "scene_setter/try_suggestion", "area_id": "kitchen", "suggestion": suggestion["id"]})
    while (reply := await client.receive_json())["id"] != 2:
        pass
    assert reply["success"]
    assert ("light", "turn_on", {"entity_id": "light.ceiling", "brightness": 120}) in [
        (d, s, {k: v for k, v in data.items() if k in ("entity_id", "brightness")}) for d, s, data in house.calls
    ]

    await client.send_json(
        {"id": 3, "type": "scene_setter/save_suggestion", "area_id": "kitchen", "suggestion": suggestion["id"], "name": "Supper"}
    )
    while (reply := await client.receive_json())["id"] != 3:
        pass
    assert reply["success"], reply
    (scene,) = load_yaml(str(house.scenes_file))
    assert scene["name"] == "Kitchen Supper"
    assert scene["entities"] == {"light.ceiling": {"state": "on", "brightness": 120}, "light.counter": {"state": "off"}}
    # Now a scene gives it, so it isn't suggested any more.
    assert house.setter.snapshot()[0]["suggestions"] == []


async def test_save_never_overwrites_a_scene(hass: HomeAssistant, house):
    seed(house)
    await hass.services.async_call("scene_setter", "save", {"area_id": "kitchen", "name": "Evening"}, blocking=True)
    (suggestion,) = house.setter.snapshot()[0]["suggestions"]
    try:
        await house.setter.async_save_suggestion("kitchen", suggestion["id"], "evening")
    except Exception as err:  # noqa: BLE001
        assert getattr(err, "key", None) == "name_taken"
    else:
        raise AssertionError("saved over a scene")


async def test_not_useful_hides_it_for_good(hass: HomeAssistant, house, hass_ws_client):
    seed(house)
    (suggestion,) = house.setter.snapshot()[0]["suggestions"]
    client = await hass_ws_client(hass)
    await client.send_json({"id": 1, "type": "scene_setter/dismiss_suggestion", "area_id": "kitchen", "suggestion": suggestion["id"]})
    assert (await client.receive_json())["success"]
    assert house.setter.snapshot()[0]["suggestions"] == []
    seed(house, 125, days=(5, 6))  # more of much the same
    assert house.setter.snapshot()[0]["suggestions"] == []


async def test_log_survives_a_reload(hass: HomeAssistant, house):
    seed(house)
    assert await hass.config_entries.async_reload(house.entry.entry_id)
    await hass.async_block_till_done()
    assert len(house.setter.habits.settings) == 4


async def test_suggestions_can_be_switched_off(hass: HomeAssistant, house):
    seed(house)
    hass.config_entries.async_update_entry(house.entry, options={"suggest_scenes": False})
    await hass.async_block_till_done()
    assert house.setter.habits is None
    assert house.setter.snapshot()[0]["suggestions"] == []

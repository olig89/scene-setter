"""The "on now" sensor each scene gets."""

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

SENSOR = "binary_sensor.kitchen_evening_active"


async def save(hass: HomeAssistant, **data) -> dict:
    return await hass.services.async_call("scene_setter", "save", data, blocking=True, return_response=True)


async def test_saving_a_scene_adds_a_sensor_that_is_on(hass, house):
    await save(hass, area_id="kitchen", name="Evening")
    await hass.async_block_till_done()

    state = hass.states.get(SENSOR)
    assert state.state == "on"
    assert state.attributes["friendly_name"] == "Kitchen Evening active"
    assert state.attributes["scene"] == "scene.kitchen_evening"
    assert state.attributes["not_matching"] == []
    assert er.async_get(hass).async_get(SENSOR).area_id == "kitchen"


async def test_sensor_goes_off_when_the_room_changes_and_back_on(hass, house):
    await save(hass, area_id="kitchen", name="Evening")
    await hass.async_block_till_done()

    hass.states.async_set("light.ceiling", "on", {"brightness": 40, "color_mode": "brightness"})
    await hass.async_block_till_done()
    state = hass.states.get(SENSOR)
    assert state.state == "off"
    assert state.attributes["not_matching"] == ["light.ceiling"]

    hass.states.async_set("light.ceiling", "on", {"brightness": 202, "color_mode": "brightness"})
    await hass.async_block_till_done()
    assert hass.states.get(SENSOR).state == "on"


async def test_saving_over_follows_the_new_contents(hass, house):
    await save(hass, area_id="kitchen", name="Evening")
    hass.states.async_set("light.ceiling", "on", {"brightness": 40, "color_mode": "brightness"})
    await hass.async_block_till_done()
    assert hass.states.get(SENSOR).state == "off"

    await save(hass, area_id="kitchen", name="Evening")
    await hass.async_block_till_done()
    assert hass.states.get(SENSOR).state == "on"


async def test_one_sensor_per_scene_and_only_the_matching_one_is_on(hass, house):
    await save(hass, area_id="kitchen", name="Evening")
    hass.states.async_set("light.ceiling", "off", {})
    await save(hass, area_id="kitchen", name="Night")
    await hass.async_block_till_done()

    assert hass.states.get(SENSOR).state == "off"
    assert hass.states.get("binary_sensor.kitchen_night_active").state == "on"


async def test_rename_keeps_the_sensor_and_changes_its_name(hass, house):
    await save(hass, area_id="kitchen", name="Evening")
    await hass.async_block_till_done()
    first = er.async_get(hass).async_get(SENSOR).id

    await hass.services.async_call("scene_setter", "rename", {"scene": "scene.kitchen_evening", "name": "Supper"}, blocking=True)
    await hass.async_block_till_done()

    assert er.async_get(hass).async_get(SENSOR).id == first
    assert hass.states.get(SENSOR).attributes["friendly_name"] == "Kitchen Supper active"


async def test_sensor_survives_the_scene_reload_another_save_causes(hass, house):
    await save(hass, area_id="kitchen", name="Evening")
    await hass.async_block_till_done()
    first = er.async_get(hass).async_get(SENSOR).id

    await save(hass, area_id="kitchen", name="Night")
    await hass.async_block_till_done()

    assert er.async_get(hass).async_get(SENSOR).id == first


async def test_deleting_the_scene_removes_its_sensor(hass, house):
    await save(hass, area_id="kitchen", name="Evening")
    await hass.async_block_till_done()

    await hass.services.async_call("scene_setter", "delete", {"scene": "scene.kitchen_evening"}, blocking=True)
    await hass.async_block_till_done()

    assert hass.states.get(SENSOR) is None
    assert er.async_get(hass).async_get(SENSOR) is None


async def test_page_gets_the_sensor_of_each_scene(hass, house):
    await save(hass, area_id="kitchen", name="Evening")
    await hass.async_block_till_done()

    (room,) = [r for r in house.setter.snapshot() if r["area_id"] == "kitchen"]
    assert room["scenes"][0]["active_sensor"] == SENSOR


async def test_sensor_follows_the_scene_entity_id_without_apostrophes(hass, house):
    hass.config_entries.async_update_entry(house.entry, options={"no_apostrophes_in_ids": True})
    office = house.area("Oli's Office")
    house.add("light.desk", "on", {"brightness": 90, "color_mode": "brightness"}, office)

    await save(hass, area_id=office, name="Dim")
    await hass.async_block_till_done()

    assert hass.states.get("binary_sensor.olis_office_dim_active").state == "on"


async def test_page_gets_each_scene_s_level(hass, house):
    await save(hass, area_id="kitchen", name="Evening")
    hass.states.async_set("light.ceiling", "on", {"brightness": 10, "color_mode": "brightness"})
    await save(hass, area_id="kitchen", name="Night")
    await hass.async_block_till_done()

    (room,) = [r for r in house.setter.snapshot() if r["area_id"] == "kitchen"]
    levels = {s["name"]: s["level"] for s in room["scenes"]}
    assert levels == {"Evening": 200 + 120, "Night": 10 + 120}

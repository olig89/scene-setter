"""Saving, renaming and deleting scenes against a real scenes.yaml."""

import pytest

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import entity_registry as er
from homeassistant.util.yaml import load_yaml

from custom_components.scene_setter.const import IGNORE_LABEL
from custom_components.scene_setter.setter import SceneSetterError


def stored(house) -> list[dict]:
    return load_yaml(str(house.scenes_file)) or []


async def save(hass: HomeAssistant, **data) -> dict:
    return await hass.services.async_call("scene_setter", "save", data, blocking=True, return_response=True)


async def test_save_writes_the_room_as_it_is(hass, house):
    result = await save(hass, area_id="kitchen", name="Evening")

    assert result["scene"] == "scene.kitchen_evening"
    assert result["created"] is True
    assert result["skipped"] == []
    (scene,) = stored(house)
    assert scene["name"] == "Kitchen Evening"
    assert scene["entities"] == {
        "light.ceiling": {"state": "on", "brightness": 200},
        "light.counter": {"state": "off"},
        "light.island": {"state": "on", "brightness": 120, "color_mode": "color_temp", "color_temp_kelvin": 2700},
        "cover.blind": {"state": "open", "current_position": 40},
    }
    assert "switch.kettle" not in scene["entities"]


async def test_saved_scene_is_a_real_scene_in_the_room(hass, house):
    await save(hass, area_id="kitchen", name="Evening")

    state = hass.states.get("scene.kitchen_evening")
    assert state is not None
    assert state.attributes["friendly_name"] == "Kitchen Evening"
    assert er.async_get(hass).async_get("scene.kitchen_evening").area_id == "kitchen"
    (listed,) = house.setter.scenes("kitchen")
    assert listed.name == "Evening"
    assert listed.editable
    assert listed.entities["cover.blind"]["current_position"] == 40


async def test_turning_the_scene_on_puts_the_room_back(hass, house):
    await save(hass, area_id="kitchen", name="Evening")
    hass.states.async_set("light.ceiling", "off")
    hass.states.async_set("cover.blind", "closed", {"current_position": 0, "supported_features": 15})

    await hass.services.async_call("scene", "turn_on", {"entity_id": "scene.kitchen_evening"}, blocking=True)

    assert ("cover", "set_cover_position", {"entity_id": "cover.blind", "position": 40}) in house.calls
    on = [data for domain, service, data in house.calls if (domain, service) == ("light", "turn_on")]
    assert {"entity_id": "light.ceiling", "brightness": 200} in on


async def test_same_name_saves_over_and_keeps_the_entity(hass, house):
    first = await save(hass, area_id="kitchen", name="Evening")
    hass.states.async_set("light.ceiling", "on", {"brightness": 50, "color_mode": "brightness"})

    second = await save(hass, area_id="kitchen", name="evening")

    assert second["scene"] == first["scene"]
    assert second["created"] is False
    (scene,) = stored(house)
    assert scene["entities"]["light.ceiling"] == {"state": "on", "brightness": 50}


async def test_same_name_in_another_room_is_its_own_scene(hass, house):
    lounge = house.area("Lounge")
    house.add("light.lamp", "on", {"brightness": 10, "color_mode": "brightness"}, lounge)

    a = await save(hass, area_id="kitchen", name="Evening")
    b = await save(hass, area_id=lounge, name="Evening")

    assert {a["scene"], b["scene"]} == {"scene.kitchen_evening", "scene.lounge_evening"}
    assert [s.name for s in house.setter.scenes(lounge)] == ["Evening"]
    assert list(stored(house)[1]["entities"]) == ["light.lamp"]


async def test_save_over_a_given_scene_keeps_its_name(hass, house):
    first = await save(hass, area_id="kitchen", name="Evening")
    hass.states.async_set("cover.blind", "closed", {"current_position": 0, "supported_features": 15})

    again = await save(hass, scene=first["scene"])

    assert again["name"] == "Evening"
    (scene,) = stored(house)
    assert scene["name"] == "Kitchen Evening"
    assert scene["entities"]["cover.blind"] == {"state": "closed", "current_position": 0}


async def test_unreachable_light_is_left_out_not_saved_as_off(hass, house):
    hass.states.async_set("light.counter", "unavailable")

    result = await save(hass, area_id="kitchen", name="Evening")

    assert result["skipped"] == ["light.counter"]
    assert "light.counter" not in stored(house)[0]["entities"]


async def test_nothing_to_save(hass, house):
    empty = house.area("Loft")
    with pytest.raises(ServiceValidationError, match="no lights or blinds"):
        await save(hass, area_id=empty, name="Evening")
    assert stored(house) == []


async def test_name_is_required_and_room_must_exist(hass, house):
    with pytest.raises(ServiceValidationError, match="Give the scene a name"):
        await save(hass, area_id="kitchen", name="  ")
    with pytest.raises(ServiceValidationError, match="room doesn't exist"):
        await save(hass, area_id="nowhere", name="Evening")


async def test_group_is_replaced_by_its_members(hass, house):
    # The members are in no area; the group is.
    house.add("light.lamp_top", "on", {"brightness": 30, "color_mode": "brightness"})
    house.add("light.lamp_bottom", "off", {})
    house.add("light.lamp", "on", {"brightness": 30, "entity_id": ["light.lamp_top", "light.lamp_bottom"]}, "kitchen")

    await save(hass, area_id="kitchen", name="Evening")

    entities = stored(house)[0]["entities"]
    assert "light.lamp" not in entities
    assert entities["light.lamp_top"] == {"state": "on", "brightness": 30}
    assert entities["light.lamp_bottom"] == {"state": "off"}
    rows = {r.entity_id: r for r in house.setter.rows("kitchen")}
    assert rows["light.lamp"].status == "group"
    assert rows["light.lamp_top"].via == "light.lamp"


async def test_member_in_the_room_and_in_a_group_is_saved_once(hass, house):
    house.add("light.all", "on", {"entity_id": ["light.ceiling", "light.island"]}, "kitchen")

    await save(hass, area_id="kitchen", name="Evening")

    entities = stored(house)[0]["entities"]
    assert "light.all" not in entities
    assert sorted(entities) == ["cover.blind", "light.ceiling", "light.counter", "light.island"]


async def test_ignore_label_and_hidden_entities_are_left_out(hass, house):
    registry = er.async_get(hass)
    registry.async_update_entity("light.counter", labels={IGNORE_LABEL})
    registry.async_update_entity("light.island", hidden_by=er.RegistryEntryHider.USER)

    await save(hass, area_id="kitchen", name="Evening")

    assert sorted(stored(house)[0]["entities"]) == ["cover.blind", "light.ceiling"]


async def test_room_settings_leave_out_and_add(hass, house):
    house.add("light.porch", "on", {"brightness": 5, "color_mode": "brightness"})
    house.setter.set_room("kitchen", exclude=["cover.blind"], include=["light.porch", "switch.kettle"])
    await hass.async_block_till_done()

    await save(hass, area_id="kitchen", name="Evening")

    assert sorted(stored(house)[0]["entities"]) == ["light.ceiling", "light.counter", "light.island", "light.porch"]
    rows = {r.entity_id: r for r in house.setter.rows("kitchen")}
    assert rows["cover.blind"].status == "left_out"
    assert rows["light.porch"].added
    assert "switch.kettle" not in rows


async def test_rename_keeps_the_entity_id(hass, house):
    await save(hass, area_id="kitchen", name="Evening")

    await hass.services.async_call(
        "scene_setter", "rename", {"scene": "scene.kitchen_evening", "name": "Supper"}, blocking=True
    )

    assert stored(house)[0]["name"] == "Kitchen Supper"
    assert hass.states.get("scene.kitchen_evening").attributes["friendly_name"] == "Kitchen Supper"
    assert [s.name for s in house.setter.scenes("kitchen")] == ["Supper"]
    assert er.async_get(hass).async_get("scene.kitchen_evening").area_id == "kitchen"


async def test_rename_refuses_a_name_the_room_already_has(hass, house):
    await save(hass, area_id="kitchen", name="Evening")
    await save(hass, area_id="kitchen", name="Morning")

    with pytest.raises(ServiceValidationError, match="already has a scene called Morning"):
        await hass.services.async_call(
            "scene_setter", "rename", {"scene": "scene.kitchen_evening", "name": "morning"}, blocking=True
        )


async def test_delete_removes_the_scene(hass, house):
    await save(hass, area_id="kitchen", name="Evening")
    await save(hass, area_id="kitchen", name="Morning")

    await hass.services.async_call("scene_setter", "delete", {"scene": "scene.kitchen_evening"}, blocking=True)
    await hass.async_block_till_done()

    assert [s["name"] for s in stored(house)] == ["Kitchen Morning"]
    assert hass.states.get("scene.kitchen_evening") is None
    assert er.async_get(hass).async_get("scene.kitchen_evening") is None
    assert [s.name for s in house.setter.scenes("kitchen")] == ["Morning"]


async def test_scenes_from_elsewhere_are_kept_and_others_untouched(hass, house):
    house.scenes_file.write_text(
        "- id: 'abc'\n  name: Hall Bright\n  icon: mdi:star\n  entities:\n    light.ceiling:\n      state: 'on'\n"
    )
    await hass.services.async_call("scene", "reload", blocking=True)

    await save(hass, area_id="kitchen", name="Evening")

    names = [s["name"] for s in stored(house)]
    assert names == ["Hall Bright", "Kitchen Evening"]
    assert stored(house)[0]["icon"] == "mdi:star"


async def test_scene_made_in_the_editor_can_be_managed_once_in_the_room(hass, house):
    house.scenes_file.write_text(
        "- id: 'abc'\n  name: Bright\n  icon: mdi:star\n  entities:\n    light.ceiling:\n      state: 'on'\n"
    )
    await hass.services.async_call("scene", "reload", blocking=True)
    er.async_get(hass).async_update_entity("scene.bright", area_id="kitchen")

    (listed,) = house.setter.scenes("kitchen")
    assert (listed.name, listed.editable) == ("Bright", True)
    await save(hass, area_id="kitchen", name="Bright")

    (scene,) = stored(house)
    assert scene["id"] == "abc"
    assert scene["icon"] == "mdi:star"
    assert len(scene["entities"]) == 4


async def test_scene_from_another_app_cannot_be_changed(hass, house):
    er.async_get(hass).async_get_or_create("scene", "hue", "h1", suggested_object_id="kitchen_relax")
    er.async_get(hass).async_update_entity("scene.kitchen_relax", area_id="kitchen")
    hass.states.async_set("scene.kitchen_relax", "unknown", {"friendly_name": "Kitchen Relax"})

    (listed,) = house.setter.scenes("kitchen")
    assert (listed.name, listed.editable, listed.entities) == ("Relax", False, None)
    with pytest.raises(SceneSetterError) as err:
        await house.setter.async_delete("scene.kitchen_relax")
    assert err.value.key == "not_editable"
    with pytest.raises(ServiceValidationError, match="from another app"):
        await save(hass, area_id="kitchen", name="relax")


async def test_snapshot_lists_rooms_with_something_in_them(hass, house):
    house.area("Loft")
    await save(hass, area_id="kitchen", name="Evening")

    (room,) = house.setter.snapshot()

    assert room["area_id"] == "kitchen"
    assert [e["entity_id"] for e in room["entities"]] == ["light.ceiling", "light.counter", "light.island", "cover.blind"]
    assert [s["name"] for s in room["scenes"]] == ["Evening"]


async def test_real_light_attributes_can_be_written(hass, house):
    """A real light reports its colour mode as an enum and colours as tuples."""
    from homeassistant.components.light import ColorMode

    hass.states.async_set(
        "light.island",
        "on",
        {"brightness": 77, "color_mode": ColorMode.XY, "xy_color": (0.4, 0.39), "rgb_color": (255, 200, 120)},
    )

    await save(hass, area_id="kitchen", name="Evening")

    assert stored(house)[0]["entities"]["light.island"] == {
        "state": "on",
        "brightness": 77,
        "color_mode": "xy",
        "xy_color": [0.4, 0.39],
    }
    assert "ColorMode" not in house.scenes_file.read_text()

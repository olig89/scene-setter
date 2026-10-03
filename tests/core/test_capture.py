"""What gets written into a scene for a light or a blind."""

from enum import StrEnum

from custom_components.scene_setter.core.capture import cover_entry, entry_for, light_entry


def test_light_off_is_saved_as_off():
    assert light_entry("off", {"brightness": None}) == {"state": "off"}


def test_unreachable_light_is_not_saved():
    assert light_entry("unavailable", {}) is None
    assert light_entry("unknown", {}) is None


def test_dimmable_light_keeps_brightness_only():
    assert light_entry("on", {"brightness": 128, "color_mode": "brightness"}) == {"state": "on", "brightness": 128}


def test_colour_light_keeps_only_the_colour_of_its_mode():
    attrs = {
        "brightness": 255,
        "color_mode": "xy",
        "xy_color": (0.4578, 0.4121),
        "hs_color": (38.8, 53.3),
        "rgb_color": (255, 207, 119),
        "color_temp_kelvin": None,
    }
    assert light_entry("on", attrs) == {
        "state": "on",
        "brightness": 255,
        "color_mode": "xy",
        "xy_color": [0.4578, 0.4121],
    }


def test_white_light_keeps_its_temperature():
    attrs = {"brightness": 90, "color_mode": "color_temp", "color_temp_kelvin": 2700, "hs_color": (28, 65)}
    assert light_entry("on", attrs) == {
        "state": "on",
        "brightness": 90,
        "color_mode": "color_temp",
        "color_temp_kelvin": 2700,
    }


def test_effect_is_kept_only_if_the_light_offers_it():
    assert light_entry("on", {"effect": "candle", "effect_list": ["off", "candle"]})["effect"] == "candle"
    assert "effect" not in light_entry("on", {"effect": "None", "effect_list": ["candle"]})
    assert "effect" not in light_entry("on", {"effect": None})


def test_blind_keeps_position_and_tilt():
    assert cover_entry("open", {"current_position": 40, "current_tilt_position": 75}) == {
        "state": "open",
        "current_position": 40,
        "current_tilt_position": 75,
    }


def test_blind_at_zero_is_closed():
    assert cover_entry("open", {"current_position": 0}) == {"state": "closed", "current_position": 0}


def test_moving_blind_is_saved_where_it_is():
    assert cover_entry("closing", {"current_position": 62}) == {"state": "open", "current_position": 62}
    assert cover_entry("opening", {}) == {"state": "open"}
    assert cover_entry("closing", {}) == {"state": "closed"}


def test_unreachable_blind_is_not_saved():
    assert cover_entry("unavailable", {}) is None


def test_other_kinds_of_entity_are_not_saved():
    assert entry_for("switch.kettle", "on", {}) is None
    assert entry_for("light.lamp", "off", {}) == {"state": "off"}
    assert entry_for("cover.blind", "closed", {}) == {"state": "closed"}


def test_colour_mode_enum_is_saved_as_plain_text():
    # Home Assistant hands the colour mode over as an enum, which YAML can't write.
    class Mode(StrEnum):
        COLOR_TEMP = "color_temp"

    entry = light_entry("on", {"brightness": 10, "color_mode": Mode.COLOR_TEMP, "color_temp_kelvin": 3000})
    assert entry["color_mode"] == "color_temp"
    assert type(entry["color_mode"]) is str
    assert entry["color_temp_kelvin"] == 3000


def test_level_entry():
    from custom_components.scene_setter.core.capture import level_entry

    assert level_entry(100, True) == {"state": "on", "brightness": 255}
    assert level_entry(50, True) == {"state": "on", "brightness": 128}
    assert level_entry(0.2, True) == {"state": "on", "brightness": 1}
    assert level_entry(0, True) == {"state": "off"}
    assert level_entry(60, False) == {"state": "on"}
    assert level_entry(20, False) == {"state": "off"}


def test_can_dim():
    from custom_components.scene_setter.core.capture import can_dim

    assert can_dim(["brightness"]) and can_dim(["color_temp", "xy"]) and can_dim(None)
    assert not can_dim(["onoff"])


def test_white_for():
    from custom_components.scene_setter.core.capture import white_for

    assert white_for(["color_temp", "xy"], 2700) == ("color_temp", 2700)
    assert white_for(["color_temp"], 2200, 2702, 5988) == ("color_temp", 2702)  # kept within the light's range
    assert white_for(["color_temp"], 9000, 2000, 6535) == ("color_temp", 6535)
    assert white_for(["rgb"], 2700) == ("hs", 2700)
    assert white_for(["brightness"], 2700) is None
    assert white_for(None, 2700) is None

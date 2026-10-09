"""Suggesting scenes from how a room's lights are used."""

from datetime import datetime, timedelta, timezone

from custom_components.scene_setter.core.habits import (
    Setting,
    name_for,
    same_setting,
    setting_from,
    setting_to,
    suggest,
    typical,
    usual_time,
)

TZ = timezone(timedelta(hours=3))
NOW = datetime(2026, 10, 9, 12, 0, tzinfo=TZ)


def warm(brightness, kelvin=2700):
    return {"state": "on", "brightness": brightness, "color_mode": "color_temp", "color_temp_kelvin": kelvin}


def evening(day, brightness=100, hour=21, minute=0, lamp=None):
    lights = {"light.ceiling": warm(brightness), "light.lamp": lamp or {"state": "off"}}
    return Setting(NOW - timedelta(days=day) + timedelta(hours=hour - 12, minutes=minute), "lounge", lights)


def test_same_setting_allows_small_differences():
    a = {"light.ceiling": warm(100)}
    assert same_setting(a, {"light.ceiling": warm(120, 2900)})
    assert not same_setting(a, {"light.ceiling": warm(140)})
    assert not same_setting(a, {"light.ceiling": warm(100, 3200)})
    assert not same_setting(a, {"light.ceiling": {"state": "off"}})


def test_white_and_colour_differ():
    white = {"light.lamp": warm(100)}
    red = {"light.lamp": {"state": "on", "brightness": 100, "color_mode": "xy", "xy_color": [0.7, 0.3]}}
    assert not same_setting(white, red)


def test_a_light_only_one_side_knows_is_not_held_against_it():
    a = {"light.ceiling": warm(100), "light.lamp": {"state": "off"}}
    b = {"light.ceiling": warm(105)}  # the lamp couldn't be reached
    assert same_setting(a, b)
    assert not same_setting({"light.a": warm(1)}, {"light.b": warm(1)})  # nothing to compare


def test_a_repeated_setting_is_suggested():
    settings = [evening(d, 95 + d) for d in (1, 2, 3, 5)]
    (found,) = suggest(settings, "lounge", {}, [], NOW)
    assert found.count == 4 and found.days == 4
    assert found.usual_time == "21:00"
    assert found.name == "Evening"
    assert found.lights["light.ceiling"]["brightness"] == 98  # the middle
    assert found.lights["light.lamp"] == {"state": "off"}


def test_needs_enough_times_and_days():
    same_day = [evening(1, minute=m) for m in (0, 10, 20, 30)]
    assert suggest(same_day, "lounge", {}, [], NOW) == []
    three = [evening(d) for d in (1, 2, 3)]
    assert suggest(three, "lounge", {}, [], NOW) == []


def test_old_settings_and_other_rooms_dont_count():
    old = [evening(d) for d in (30, 31, 32, 33)]
    assert suggest(old, "lounge", {}, [], NOW) == []
    assert suggest([evening(d) for d in (1, 2, 3, 4)], "kitchen", {}, [], NOW) == []


def test_nothing_suggested_when_a_scene_gives_it():
    settings = [evening(d) for d in (1, 2, 3, 4)]
    scenes = {"Cosy": {"light.ceiling": warm(102), "light.lamp": {"state": "off"}, "cover.blind": {"state": "open"}}}
    assert suggest(settings, "lounge", scenes, [], NOW) == []


def test_a_dimmed_scene_is_suggested_as_its_own():
    """Someone keeps turning a scene on and then dimming it at the switch."""
    scenes = {"Bright": {"light.ceiling": warm(255), "light.lamp": {"state": "off"}}}
    settings = [evening(d, 190) for d in (1, 2, 3, 4)] + [evening(d, 255, hour=18) for d in (1, 2, 3, 4)]
    (found,) = suggest(settings, "lounge", scenes, [], NOW)
    assert found.lights["light.ceiling"]["brightness"] == 190


def test_dismissed_settings_stay_away():
    settings = [evening(d) for d in (1, 2, 3, 4)]
    (found,) = suggest(settings, "lounge", {}, [], NOW)
    assert suggest(settings, "lounge", {}, [found.lights], NOW) == []
    # Even after the setting drifts a little.
    drifted = settings + [evening(d, 110) for d in (6, 7)]
    assert suggest(drifted, "lounge", {}, [found.lights], NOW) == []


def test_two_settings_two_suggestions_and_names_dont_clash():
    morning = [evening(d, 250, hour=7) for d in (1, 2, 3, 4)]
    night = [evening(d, 20, hour=23, lamp=warm(10, 2200)) for d in (1, 2, 3, 4, 5)]
    found = suggest(morning + night, "lounge", {"Night": {"light.ceiling": warm(60)}}, [], NOW)
    assert [f.name for f in found] == ["Night 2", "Morning"]
    assert found[0].count == 5


def test_usual_time_across_midnight():
    t = lambda h, m: datetime(2026, 10, 1, h, m, tzinfo=TZ)
    assert usual_time([t(23, 50), t(0, 10), t(0, 5)]) == (0, 0)
    assert usual_time([t(21, 0), t(21, 20), t(20, 50)]) == (21, 0)


def test_names_by_time_of_day():
    assert name_for(7, []) == "Morning"
    assert name_for(13, []) == "Day"
    assert name_for(20, ["evening"]) == "Evening 2"
    assert name_for(2, []) == "Night"


def test_typical_takes_the_usual_colour_mode():
    group = [
        Setting(NOW, "x", {"light.l": warm(100, 2700)}),
        Setting(NOW, "x", {"light.l": warm(100, 2750)}),
        Setting(NOW, "x", {"light.l": {"state": "on", "brightness": 100, "color_mode": "xy", "xy_color": [0.5, 0.4]}}),
    ]
    assert typical(group)["light.l"] == {"state": "on", "brightness": 100, "color_mode": "color_temp", "color_temp_kelvin": 2720}


def test_storage_round_trip():
    s = evening(1)
    assert setting_from(setting_to(s)) == s

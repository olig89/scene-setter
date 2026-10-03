from custom_components.scene_setter.core.match import scene_level, scene_matches

DIM = {"state": "on", "brightness": 128, "color_mode": "color_temp", "color_temp_kelvin": 2710}


def test_room_as_the_scene_left_it():
    assert scene_matches({"light.a": DIM}, {"light.a": ("on", {"brightness": 128, "color_temp_kelvin": 2710})}) == (True, [])


def test_small_rounding_is_allowed():
    now = {"light.a": ("on", {"brightness": 125, "color_temp_kelvin": 2780})}
    assert scene_matches({"light.a": DIM}, now)[0]


def test_brightness_changed_is_not_the_scene():
    now = {"light.a": ("on", {"brightness": 200, "color_temp_kelvin": 2710})}
    assert scene_matches({"light.a": DIM}, now) == (False, ["light.a"])


def test_colour_temperature_changed_is_not_the_scene():
    now = {"light.a": ("on", {"brightness": 128, "color_temp_kelvin": 4000})}
    assert not scene_matches({"light.a": DIM}, now)[0]


def test_xy_and_hs_colour_are_compared():
    want = {"state": "on", "brightness": 255, "color_mode": "xy", "xy_color": [0.4578, 0.4121]}
    assert scene_matches({"light.a": want}, {"light.a": ("on", {"brightness": 255, "xy_color": (0.458, 0.412)})})[0]
    assert not scene_matches({"light.a": want}, {"light.a": ("on", {"brightness": 255, "xy_color": (0.3, 0.3)})})[0]
    want = {"state": "on", "color_mode": "hs", "hs_color": [30, 60]}
    assert scene_matches({"light.a": want}, {"light.a": ("on", {"hs_color": (32, 58)})})[0]
    assert not scene_matches({"light.a": want}, {"light.a": ("on", {"hs_color": (200, 60)})})[0]


def test_on_and_off_must_agree():
    assert not scene_matches({"light.a": DIM}, {"light.a": ("off", {})})[0]
    assert not scene_matches({"light.a": {"state": "off"}}, {"light.a": ("on", {"brightness": 10})})[0]
    assert scene_matches({"light.a": {"state": "off"}}, {"light.a": ("off", {})})[0]


def test_unreachable_entities_are_skipped_not_held_against_it():
    wanted = {"light.a": DIM, "light.b": DIM}
    now = {"light.a": ("on", {"brightness": 128}), "light.b": ("unavailable", {})}
    assert scene_matches(wanted, now) == (True, [])


def test_nothing_reachable_is_not_on():
    assert scene_matches({"light.a": DIM}, {"light.a": None}) == (False, [])


def test_covers_by_position_and_tilt():
    want = {"state": "open", "current_position": 40, "current_tilt_position": 50}
    assert scene_matches({"cover.b": want}, {"cover.b": ("open", {"current_position": 42, "current_tilt_position": 50})})[0]
    assert not scene_matches({"cover.b": want}, {"cover.b": ("open", {"current_position": 80})})[0]
    assert not scene_matches({"cover.b": want}, {"cover.b": ("open", {"current_position": 40, "current_tilt_position": 0})})[0]
    assert scene_matches({"cover.b": {"state": "closed"}}, {"cover.b": ("closed", {})})[0]


def test_lists_every_entity_that_differs():
    wanted = {"light.a": DIM, "light.b": DIM, "light.c": DIM}
    now = {"light.a": ("off", {}), "light.b": ("on", {"brightness": 128}), "light.c": ("on", {"brightness": 10})}
    assert scene_matches(wanted, now) == (False, ["light.a", "light.c"])


def test_level_adds_up_the_lights():
    bright = {"light.a": {"state": "on", "brightness": 255}, "light.b": {"state": "on", "brightness": 76}}
    dim = {"light.a": {"state": "on", "brightness": 128}, "light.b": {"state": "on", "brightness": 38}}
    dark = {"light.a": {"state": "on", "brightness": 51}, "light.b": {"state": "on", "brightness": 15}}
    assert scene_level(bright) == 331
    assert scene_level(bright) > scene_level(dim) > scene_level(dark)


def test_level_off_counts_nothing_and_on_without_brightness_counts_full():
    assert scene_level({"light.a": {"state": "off"}, "light.b": {"state": "on"}}) == 255


def test_level_ignores_blinds_and_is_none_without_lights():
    assert scene_level({"light.a": {"state": "on", "brightness": 10}, "cover.b": {"state": "open", "current_position": 100}}) == 10
    assert scene_level({"cover.b": {"state": "open"}}) is None


def test_rgb_colours_and_effects_are_compared():
    want = {"state": "on", "brightness": 200, "color_mode": "rgb", "rgb_color": [255, 0, 0]}
    assert scene_matches({"light.s": want}, {"light.s": ("on", {"brightness": 200, "rgb_color": (250, 4, 0)})})[0]
    assert not scene_matches({"light.s": want}, {"light.s": ("on", {"brightness": 200, "rgb_color": (0, 0, 255)})})[0]
    want = {"state": "on", "brightness": 200, "effect": "off"}
    assert scene_matches({"light.e": want}, {"light.e": ("on", {"brightness": 200, "effect": "off"})})[0]
    assert not scene_matches({"light.e": want}, {"light.e": ("on", {"brightness": 200, "effect": "candle"})})[0]

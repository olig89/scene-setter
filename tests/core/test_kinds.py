"""The table of device kinds, and that a new kind plugs in without touching anything else."""

from custom_components.scene_setter.core import kinds
from custom_components.scene_setter.core.kinds import DOMAINS, KINDS, Kind, entry_for, kind_of, takes_levels
from custom_components.scene_setter.core.match import scene_level, scene_matches


def test_every_kind_has_the_rules_it_must_have():
    assert DOMAINS == ("light", "cover")  # the order rooms list them in
    for domain, kind in KINDS.items():
        assert kind.domain == domain
        assert callable(kind.capture) and callable(kind.matches)


def test_lights_take_levels_and_count_towards_brightness_blinds_do_not():
    assert takes_levels("light.a") and kind_of("light.a").brightness is not None
    assert not takes_levels("cover.b") and kind_of("cover.b").brightness is None
    assert not takes_levels("switch.c") and kind_of("switch.c") is None


def test_a_device_no_kind_covers_is_not_saved():
    assert entry_for("switch.kettle", "on", {}) is None


def test_a_new_kind_plugs_in(monkeypatch):
    fan = Kind(
        "fan",
        capture=lambda state, attrs: {"state": state, "percentage": attrs.get("percentage")},
        matches=lambda want, state, attrs: state == want["state"] and attrs.get("percentage") == want.get("percentage"),
        brightness=lambda want: 0,
        level=lambda percent, facts, white_k, hs_of: {"state": "on", "percentage": round(percent)},
    )
    monkeypatch.setattr(kinds, "KINDS", {**KINDS, "fan": fan})

    assert entry_for("fan.ceiling", "on", {"percentage": 40}) == {"state": "on", "percentage": 40}
    assert takes_levels("fan.ceiling")
    wanted = {"fan.ceiling": {"state": "on", "percentage": 40}, "light.a": {"state": "on", "brightness": 100}}
    assert scene_matches(wanted, {"fan.ceiling": ("on", {"percentage": 40}), "light.a": ("on", {"brightness": 100})})[0]
    assert not scene_matches(wanted, {"fan.ceiling": ("on", {"percentage": 90}), "light.a": ("on", {"brightness": 100})})[0]
    assert scene_level(wanted) == 100

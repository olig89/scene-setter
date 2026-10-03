"""Lights: what a scene saves for one, whether it matches, and setting one to a level.

No Home Assistant imports.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .common import NOT_THERE, Attributes, near, pair_near, plain

EFFECT_OFF = "off"  # Home Assistant's name for "no effect"
FULL = 255

# The attribute that holds the colour, for each colour mode a light can be in.
COLOUR_ATTR = {
    "color_temp": "color_temp_kelvin",
    "hs": "hs_color",
    "xy": "xy_color",
    "rgb": "rgb_color",
    "rgbw": "rgbw_color",
    "rgbww": "rgbww_color",
}
COLOUR_MODES = ("hs", "xy", "rgb", "rgbw", "rgbww")  # colour without colour temperature

# How close counts as the same, when checking a light against a scene.
BRIGHTNESS_SLACK = 5  # out of 255
KELVIN_SLACK = 100
XY_SLACK = 0.01
HS_SLACK = 4  # degrees of hue, percent of saturation
RGB_SLACK = 8  # out of 255, per channel
CHECKS = (
    ("brightness", near, BRIGHTNESS_SLACK),
    ("color_temp_kelvin", near, KELVIN_SLACK),
    ("xy_color", pair_near, XY_SLACK),
    ("hs_color", pair_near, HS_SLACK),
    ("rgb_color", pair_near, RGB_SLACK),
    ("rgbw_color", pair_near, RGB_SLACK),
    ("rgbww_color", pair_near, RGB_SLACK),
    ("effect", lambda a, b, _: a == b, 0),
)


def _modes(color_modes: object) -> set[str]:
    return {str(getattr(m, "value", m)) for m in (color_modes or ())}  # type: ignore[union-attr]


def capture(state: str, attributes: Attributes) -> dict[str, Any] | None:
    """A light as a scene stores it, or None if the light has nothing to save.

    Only the colour of the mode the light is in is kept. Saving every colour
    attribute (as a state has them) would make Home Assistant choose between
    them when the scene is turned on.
    """
    if state in NOT_THERE:
        return None
    if state != "on":
        return {"state": "off"}
    entry: dict[str, Any] = {"state": "on"}
    if (brightness := attributes.get("brightness")) is not None:
        entry["brightness"] = plain(brightness)
    mode = plain(attributes.get("color_mode"))
    colour_attr = COLOUR_ATTR.get(mode) if isinstance(mode, str) else None
    if colour_attr and (colour := attributes.get(colour_attr)) is not None:
        entry["color_mode"] = mode
        entry[colour_attr] = plain(colour)
    effect = attributes.get("effect")
    effects = attributes.get("effect_list") or ()
    if effect is not None and effect in effects:
        entry["effect"] = plain(effect)
    elif EFFECT_OFF in effects:
        # No effect running now: save that, so turning the scene on stops one
        # that is running by then.
        entry["effect"] = EFFECT_OFF
    return entry


def matches(want: Attributes, state: str, attributes: Attributes) -> bool:
    if (state == "on") != (want.get("state") == "on"):
        return False
    if state != "on":
        return True
    # A light showing a colour when the scene wants a white reports no colour
    # temperature at all, so the check below would skip it: count it as different.
    if want.get("color_temp_kelvin") is not None and attributes.get("color_temp_kelvin") is None:
        if plain(attributes.get("color_mode")) in COLOUR_MODES:
            return False
    for attr, close, slack in CHECKS:
        wanted, now = want.get(attr), attributes.get(attr)
        # A value only one side has (a light in another colour mode reports no
        # colour temperature, say) is not held against the scene.
        if wanted is not None and now is not None and not close(wanted, now, slack):
            return False
    return True


def brightness(want: Attributes) -> int:
    """This light's share of a scene's rough brightness: off 0, on without a
    brightness (it can't dim) full."""
    if want.get("state") != "on":
        return 0
    try:
        return int(want.get("brightness", FULL))
    except (TypeError, ValueError):
        return FULL


def can_dim(color_modes: object) -> bool:
    """Whether a light with these supported colour modes can dim. Unknown counts as yes."""
    if not color_modes:
        return True
    return bool(_modes(color_modes) - {"onoff", "unknown"})


def level_entry(percent: float, dimmable: bool) -> dict[str, Any]:
    """A light set to a brightness level, as a scene stores it.

    0 % (or less) is off. A light that can't dim is on from 50 % up, else off,
    so a dim scene never puts it on at full.
    """
    if percent <= 0:
        return {"state": "off"}
    if not dimmable:
        return {"state": "on"} if percent >= 50 else {"state": "off"}
    return {"state": "on", "brightness": max(1, min(255, round(percent * 255 / 100)))}


def white_for(
    color_modes: object, kelvin: float, lowest: float | None = None, highest: float | None = None
) -> tuple[str, float] | None:
    """How a light takes a white of ``kelvin``: ("color_temp", kelvin kept within
    the light's range), ("hs", kelvin) for a colour-only light (shown as the
    nearest colour), or None for a light with no colour at all.
    """
    modes = _modes(color_modes)
    if "color_temp" in modes:
        if lowest:
            kelvin = max(kelvin, lowest)
        if highest:
            kelvin = min(kelvin, highest)
        return "color_temp", round(kelvin)
    if modes & set(COLOUR_MODES):
        return "hs", kelvin
    return None


def level(
    percent: float, facts: Attributes, white_k: float, hs_of: Callable[[float], tuple[float, float]]
) -> dict[str, Any]:
    """A light fully set for a level scene: brightness, a white if it has colour,
    and no effect if it has effects, so nothing it was doing before is left over.

    ``facts`` is what the light can do (its attributes, or its registry entry's
    capabilities while unreachable); ``hs_of`` turns a white into a colour for a
    light that only does colours.
    """
    modes = facts.get("supported_color_modes")
    entry = level_entry(percent, can_dim(modes))
    if entry["state"] != "on":
        return entry
    white = white_for(modes, white_k, facts.get("min_color_temp_kelvin"), facts.get("max_color_temp_kelvin"))
    if white is not None:
        kind, value = white
        if kind == "color_temp":
            entry |= {"color_mode": "color_temp", "color_temp_kelvin": value}
        else:
            hue, sat = hs_of(value)
            entry |= {"color_mode": "hs", "hs_color": [round(hue, 1), round(sat, 1)]}
    if EFFECT_OFF in (facts.get("effect_list") or ()):
        entry["effect"] = EFFECT_OFF
    return entry

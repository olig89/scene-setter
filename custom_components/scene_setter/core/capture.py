"""Turning a light's or a blind's state into what a Home Assistant scene stores.

No Home Assistant imports: everything here works on plain strings and dicts.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import Enum
from typing import Any

LIGHT = "light"
COVER = "cover"
DOMAINS = (LIGHT, COVER)

NOT_THERE = ("unavailable", "unknown")

# The attribute that holds the colour, for each colour mode a light can be in.
COLOUR_ATTR = {
    "color_temp": "color_temp_kelvin",
    "hs": "hs_color",
    "xy": "xy_color",
    "rgb": "rgb_color",
    "rgbw": "rgbw_color",
    "rgbww": "rgbww_color",
}


def domain_of(entity_id: str) -> str:
    return entity_id.split(".", 1)[0]


def _plain(value: Any) -> Any:
    """The value as ordinary YAML can hold it: lists for tuples, and the plain
    value of an enum (Home Assistant's colour mode is one)."""
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (tuple, list)):
        return [_plain(item) for item in value]
    return value


def light_entry(state: str, attributes: Mapping[str, Any]) -> dict[str, Any] | None:
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
        entry["brightness"] = _plain(brightness)
    mode = _plain(attributes.get("color_mode"))
    colour_attr = COLOUR_ATTR.get(mode) if isinstance(mode, str) else None
    if colour_attr and (colour := attributes.get(colour_attr)) is not None:
        entry["color_mode"] = mode
        entry[colour_attr] = _plain(colour)
    effect = attributes.get("effect")
    if effect is not None and effect in (attributes.get("effect_list") or ()):
        entry["effect"] = _plain(effect)
    return entry


def cover_entry(state: str, attributes: Mapping[str, Any]) -> dict[str, Any] | None:
    """A blind (or window, or any cover) as a scene stores it, or None if unknown.

    A cover caught while moving is saved where it is at that moment.
    """
    if state in NOT_THERE:
        return None
    position = attributes.get("current_position")
    tilt = attributes.get("current_tilt_position")
    if position is not None:
        resting = "closed" if position == 0 else "open"
    elif state in ("open", "opening"):
        resting = "open"
    elif state in ("closed", "closing"):
        resting = "closed"
    else:
        return None
    entry: dict[str, Any] = {"state": resting}
    if position is not None:
        entry["current_position"] = _plain(position)
    if tilt is not None:
        entry["current_tilt_position"] = _plain(tilt)
    return entry


def entry_for(entity_id: str, state: str, attributes: Mapping[str, Any]) -> dict[str, Any] | None:
    domain = domain_of(entity_id)
    if domain == LIGHT:
        return light_entry(state, attributes)
    if domain == COVER:
        return cover_entry(state, attributes)
    return None


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


def can_dim(color_modes: object) -> bool:
    """Whether a light with these supported colour modes can dim. Unknown counts as yes."""
    if not color_modes:
        return True
    modes = {str(getattr(m, "value", m)) for m in color_modes}  # type: ignore[union-attr]
    return bool(modes - {"onoff", "unknown"})


COLOUR_MODES = ("hs", "xy", "rgb", "rgbw", "rgbww")


def white_for(color_modes: object, kelvin: float, lowest: float | None = None, highest: float | None = None) -> tuple[str, float] | None:
    """How a light takes a white of ``kelvin``: ("color_temp", kelvin kept within
    the light's range), ("hs", kelvin) for a colour-only light (shown as the
    nearest colour), or None for a light with no colour at all.
    """
    modes = {str(getattr(m, "value", m)) for m in (color_modes or ())}  # type: ignore[union-attr]
    if "color_temp" in modes:
        if lowest:
            kelvin = max(kelvin, lowest)
        if highest:
            kelvin = min(kelvin, highest)
        return "color_temp", round(kelvin)
    if modes & set(COLOUR_MODES):
        return "hs", kelvin
    return None

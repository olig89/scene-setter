"""Is a room as a scene left it?

A scene in Home Assistant has no on or off: its state is the time it was last
turned on. This answers the question people actually ask ("is the Evening scene
on right now?") by comparing what the scene sets with what the lights and blinds
are doing now, with a little slack for rounding.

No Home Assistant imports.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .capture import COVER, LIGHT, NOT_THERE, domain_of

BRIGHTNESS_SLACK = 5  # out of 255
KELVIN_SLACK = 100
XY_SLACK = 0.01
HS_SLACK = 4  # degrees of hue, percent of saturation
POSITION_SLACK = 3  # percent

# (entity's state, its attributes), or None when the entity doesn't exist.
Current = tuple[str, Mapping[str, Any]] | None


def _near(a: Any, b: Any, slack: float) -> bool:
    try:
        return abs(float(a) - float(b)) <= slack
    except (TypeError, ValueError):
        return a == b


def _pair_near(a: Any, b: Any, slack: float) -> bool:
    try:
        return len(a) == len(b) and all(_near(x, y, slack) for x, y in zip(a, b))
    except TypeError:
        return a == b


def light_matches(want: Mapping[str, Any], state: str, attributes: Mapping[str, Any]) -> bool:
    if (state == "on") != (want.get("state") == "on"):
        return False
    if state != "on":
        return True
    checks = (
        ("brightness", _near, BRIGHTNESS_SLACK),
        ("color_temp_kelvin", _near, KELVIN_SLACK),
        ("xy_color", _pair_near, XY_SLACK),
        ("hs_color", _pair_near, HS_SLACK),
    )
    for attr, close, slack in checks:
        wanted, now = want.get(attr), attributes.get(attr)
        # A value only one side has (a light in another colour mode reports no
        # colour temperature, say) is not held against the scene.
        if wanted is not None and now is not None and not close(wanted, now, slack):
            return False
    return True


def cover_matches(want: Mapping[str, Any], state: str, attributes: Mapping[str, Any]) -> bool:
    position, wanted = attributes.get("current_position"), want.get("current_position")
    if wanted is not None and position is not None:
        if not _near(wanted, position, POSITION_SLACK):
            return False
    elif (state == "closed") != (want.get("state") == "closed"):
        return False
    tilt, wanted_tilt = attributes.get("current_tilt_position"), want.get("current_tilt_position")
    return wanted_tilt is None or tilt is None or _near(wanted_tilt, tilt, POSITION_SLACK)


def scene_matches(wanted: Mapping[str, Mapping[str, Any]], current: Mapping[str, Current]) -> tuple[bool, list[str]]:
    """Whether the room is as the scene left it, and which entities differ.

    Entities that can't be reached right now are skipped rather than counted
    against the scene. If none of the scene's entities can be reached, the scene
    is not on.
    """
    compared = 0
    differ: list[str] = []
    for entity_id, want in wanted.items():
        now = current.get(entity_id)
        if now is None or now[0] in NOT_THERE:
            continue
        state, attributes = now
        domain = domain_of(entity_id)
        if domain == LIGHT:
            ok = light_matches(want, state, attributes)
        elif domain == COVER:
            ok = cover_matches(want, state, attributes)
        else:
            ok = state == want.get("state")
        compared += 1
        if not ok:
            differ.append(entity_id)
    return compared > 0 and not differ, differ


FULL = 255


def scene_level(wanted: Mapping[str, Mapping[str, Any]]) -> int | None:
    """A rough "how bright is this scene" figure, for putting scenes in order.

    The brightness of every light the scene sets, added up: a light that is off
    counts 0, one that is on with no brightness (it can't dim) counts as full.
    Blinds don't count. None when the scene sets no lights.

    Within one room it ranks scenes well, since they share the same lights.
    It knows nothing of how much light each lamp actually gives.
    """
    lights = [want for entity_id, want in wanted.items() if domain_of(entity_id) == LIGHT]
    if not lights:
        return None
    total = 0
    for want in lights:
        if want.get("state") != "on":
            continue
        try:
            total += int(want.get("brightness", FULL))
        except (TypeError, ValueError):
            total += FULL
    return total

"""Is a room as a scene left it, and how bright is a scene?

A scene in Home Assistant has no on or off: its state is the time it was last
turned on. This answers the question people actually ask ("is the Evening scene
on right now?") by comparing what the scene sets with what each device is doing
now, using that kind of device's own rule (see ``kinds.py``).

No Home Assistant imports.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .common import NOT_THERE
from .cover import matches as cover_matches
from .kinds import kind_of, matches
from .light import matches as light_matches

__all__ = ["Current", "cover_matches", "light_matches", "scene_level", "scene_matches"]

# (entity's state, its attributes), or None when the entity doesn't exist.
Current = tuple[str, Mapping[str, Any]] | None


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
        compared += 1
        if not matches(entity_id, want, state, attributes):
            differ.append(entity_id)
    return compared > 0 and not differ, differ


def scene_level(wanted: Mapping[str, Mapping[str, Any]]) -> int | None:
    """A rough "how bright is this scene" figure, for putting scenes in order.

    Every device that counts (lights, so far) adds its share: a light's
    brightness, 0 if off, full if it's on but can't dim. Blinds don't count.
    None when nothing in the scene counts.

    Within one room it ranks scenes well, since they share the same lights.
    It knows nothing of how much light each lamp actually gives.
    """
    shares = [
        kind.brightness(want)
        for entity_id, want in wanted.items()
        if (kind := kind_of(entity_id)) is not None and kind.brightness is not None
    ]
    return sum(shares) if shares else None

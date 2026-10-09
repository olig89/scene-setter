"""Suggesting scenes from how a room's lights are really used.

Home Assistant's history keeps only whether a light was on or off, never its
brightness or colour, so Scene Setter keeps its own short log: each time a
room's lights settle (nothing changes for a couple of minutes) with at least
one light on, the room's lights are written down as a scene would store them.

When much the same setting keeps coming back (``MIN_COUNT`` times on
``MIN_DAYS`` different days within ``WINDOW``) and no saved scene in the room
already gives it, ``suggest`` offers it as a scene. Settings that match a saved
scene don't count, and a setting someone said was not useful is never offered
again.

No Home Assistant imports.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from statistics import median
from typing import Any

from .common import domain_of, near, pair_near
from .match import scene_matches
from .names import same_name

WINDOW = timedelta(days=28)
KEEP = timedelta(days=60)
MIN_COUNT = 4
MIN_DAYS = 3

# How close counts as the same setting. Looser than a scene's "on now" check,
# since nobody sets a light to exactly the same place twice by hand.
BRIGHTNESS_SLACK = 26  # out of 255, about 10 %
KELVIN_SLACK = 300
XY_SLACK = 0.03
HS_SLACK = 12  # degrees of hue, percent of saturation
RGB_SLACK = 25  # out of 255, per channel
CHECKS = (
    ("brightness", near, BRIGHTNESS_SLACK),
    ("color_temp_kelvin", near, KELVIN_SLACK),
    ("xy_color", pair_near, XY_SLACK),
    ("hs_color", pair_near, HS_SLACK),
    ("rgb_color", pair_near, RGB_SLACK),
    ("rgbw_color", pair_near, RGB_SLACK),
    ("rgbww_color", pair_near, RGB_SLACK),
)
COLOUR_KEYS = ("color_temp_kelvin", "xy_color", "hs_color", "rgb_color", "rgbw_color", "rgbww_color")

# Names offered for a suggestion, by the time it usually happens: (from hour, name).
TIMES_OF_DAY = ((5, "Morning"), (11, "Day"), (17, "Evening"), (22, "Night"))

Lights = Mapping[str, Mapping[str, Any]]  # entity id -> the light as a scene stores it


@dataclass(frozen=True)
class Setting:
    """A room's lights as they settled. ``at`` is when the setting began (local time)."""

    at: datetime
    area_id: str
    lights: Lights


@dataclass(frozen=True)
class Suggestion:
    id: str  # stable while the setting stays the same; used by the page's buttons
    area_id: str
    lights: dict[str, dict[str, Any]]  # what the scene would set
    count: int
    days: int
    usual_time: str  # "21:00"
    name: str  # offered name, free in the room


def lights_only(entities: Lights) -> dict[str, dict[str, Any]]:
    return {e: dict(v) for e, v in entities.items() if domain_of(e) == "light"}


def is_lit(lights: Lights) -> bool:
    return any(v.get("state") == "on" for v in lights.values())


def _shade(light: Mapping[str, Any]) -> str | None:
    """Whether the light is set to a white or a colour (None: neither saved)."""
    if light.get("color_temp_kelvin") is not None:
        return "white"
    if any(light.get(k) is not None for k in COLOUR_KEYS):
        return "colour"
    return None


def _same_light(a: Mapping[str, Any], b: Mapping[str, Any]) -> bool:
    if (a.get("state") == "on") != (b.get("state") == "on"):
        return False
    if a.get("state") != "on":
        return True
    # A white and a colour are different settings, however the numbers fall.
    shades = {_shade(a), _shade(b)}
    if None not in shades and len(shades) > 1:
        return False
    for attr, close, slack in CHECKS:
        x, y = a.get(attr), b.get(attr)
        if x is not None and y is not None and not close(x, y, slack):
            return False
    if a.get("effect") not in (None, "off") or b.get("effect") not in (None, "off"):
        return a.get("effect") == b.get("effect")
    return True


def same_setting(a: Lights, b: Lights) -> bool:
    """Whether two settings of a room are much the same. A light only one of them
    knows (it was unreachable at the time) is not held against them."""
    shared = set(a) & set(b)
    return bool(shared) and all(_same_light(a[e], b[e]) for e in shared)


def matches_scene(lights: Lights, scene: Lights) -> bool:
    """Whether a setting is what a saved scene gives (by the scene's own "on now" rule)."""
    current = {e: (str(v.get("state")), v) for e, v in lights.items()}
    wanted = {e: v for e, v in scene.items() if e in lights}
    return scene_matches(wanted, current)[0]


def _clusters(settings: Iterable[Setting]) -> list[list[Setting]]:
    """Group settings that are much the same, newest first. Each group is led by
    its newest setting, which the others are compared with."""
    groups: list[list[Setting]] = []
    for s in sorted(settings, key=lambda s: s.at, reverse=True):
        for group in groups:
            if same_setting(group[0].lights, s.lights):
                group.append(s)
                break
        else:
            groups.append([s])
    return groups


def _middle(values: list[Any]) -> Any:
    """The middle of some numbers, or of each part of some pairs."""
    if isinstance(values[0], (list, tuple)):
        size = len(values[0])
        parts = [_middle([v[i] for v in values if len(v) == size]) for i in range(size)]
        return parts
    return median(float(v) for v in values)


def typical(group: list[Setting]) -> dict[str, dict[str, Any]]:
    """The setting a group stands for: each light's most usual state, colour mode
    and effect, and the middle of its brightness and colour."""
    out: dict[str, dict[str, Any]] = {}
    lights = sorted({e for s in group for e in s.lights})
    for entity_id in lights:
        seen = [s.lights[entity_id] for s in group if entity_id in s.lights]
        state = Counter(v.get("state") for v in seen).most_common(1)[0][0]
        if state != "on":
            out[entity_id] = {"state": state}
            continue
        on = [v for v in seen if v.get("state") == "on"]
        entry: dict[str, Any] = {"state": "on"}
        if bright := [v["brightness"] for v in on if v.get("brightness") is not None]:
            entry["brightness"] = max(1, min(255, round(_middle(bright))))
        modes = [v.get("color_mode") for v in on if v.get("color_mode")]
        if modes:
            mode = Counter(modes).most_common(1)[0][0]
            same_mode = [v for v in on if v.get("color_mode") == mode]
            for key in COLOUR_KEYS:
                if found := [v[key] for v in same_mode if v.get(key) is not None]:
                    entry["color_mode"] = mode
                    value = _middle(found)
                    if key == "color_temp_kelvin":
                        entry[key] = round(value / 10) * 10
                    elif key == "xy_color":
                        entry[key] = [round(x, 4) for x in value]
                    elif key == "hs_color":
                        entry[key] = [round(x, 1) for x in value]
                    else:
                        entry[key] = [round(x) for x in value]
                    break
        if effects := [v["effect"] for v in on if v.get("effect") is not None]:
            entry["effect"] = Counter(effects).most_common(1)[0][0]
        out[entity_id] = entry
    return out


def usual_time(times: list[datetime]) -> tuple[int, int]:
    """The usual time of day, as (hour, minute) rounded to 15 minutes. Times either
    side of midnight count as close together."""
    minutes = sorted(t.hour * 60 + t.minute for t in times)
    # Cut the day at the widest gap, so 23:50 and 00:10 sit side by side.
    gaps = [(minutes[(i + 1) % len(minutes)] - m) % 1440 for i, m in enumerate(minutes)]
    cut = gaps.index(max(gaps)) + 1 if len(minutes) > 1 else 0
    ordered = minutes[cut:] + [m + 1440 for m in minutes[:cut]]
    middle = round(median(ordered) / 15) * 15 % 1440
    return middle // 60, middle % 60


def name_for(hour: int, taken: Iterable[str]) -> str:
    """A name for a scene by when it is used, not yet used in the room."""
    base = TIMES_OF_DAY[-1][1]
    for start, label in TIMES_OF_DAY:
        if hour >= start:
            base = label
    taken = list(taken)
    name, n = base, 1
    while any(same_name(name, t) for t in taken):
        n += 1
        name = f"{base} {n}"
    return name


def setting_id(area_id: str, lights: Lights) -> str:
    text = json.dumps([area_id, lights], sort_keys=True, default=str)
    return hashlib.sha1(text.encode()).hexdigest()[:12]


def suggest(
    settings: Iterable[Setting],
    area_id: str,
    scenes: Mapping[str, Lights],
    dismissed: Iterable[Lights],
    now: datetime,
    window: timedelta = WINDOW,
    min_count: int = MIN_COUNT,
    min_days: int = MIN_DAYS,
) -> list[Suggestion]:
    """Scenes to suggest for one room, most used first.

    ``scenes`` is the room's saved scenes by name (what each sets); ``dismissed``
    the settings someone said were not useful.
    """
    saved = [lights_only(s) for s in scenes.values()]
    dismissed = list(dismissed)
    recent = [
        s for s in settings
        if s.area_id == area_id and timedelta(0) <= now - s.at <= window
        and not any(matches_scene(s.lights, scene) for scene in saved)
    ]
    out: list[Suggestion] = []
    taken = list(scenes)
    for group in _clusters(recent):
        days = len({s.at.date() for s in group})
        if len(group) < min_count or days < min_days:
            continue
        look = typical(group)
        if not is_lit(look) or any(matches_scene(look, scene) for scene in saved):
            continue
        if any(same_setting(look, d) for d in dismissed):
            continue
        hour, minute = usual_time([s.at for s in group])
        name = name_for(hour, taken)
        taken.append(name)
        out.append(Suggestion(setting_id(area_id, look), area_id, look, len(group), days, f"{hour:02d}:{minute:02d}", name))
    out.sort(key=lambda s: (-s.count, s.usual_time))
    return out


# ---- storage -------------------------------------------------------------------


def setting_to(s: Setting) -> dict[str, Any]:
    return {"at": s.at.isoformat(), "area_id": s.area_id, "lights": {e: dict(v) for e, v in s.lights.items()}}


def setting_from(data: Mapping[str, Any]) -> Setting:
    return Setting(datetime.fromisoformat(data["at"]), str(data["area_id"]), dict(data.get("lights") or {}))

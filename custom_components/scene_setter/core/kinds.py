"""The kinds of device a room's scenes take in, and each kind's rules.

Everything that differs between lights, blinds and any future kind lives in one
entry here; the rest of Scene Setter asks this table and never names a kind.

To add a kind (fans, say): write a module like ``light.py`` or ``cover.py``
with at least ``capture`` and ``matches``, then add one ``Kind`` below. Give it
``brightness`` if it should count towards a scene's "brightest" order, and
``level`` if level scenes (the Create action) should set it.

No Home Assistant imports.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from . import cover, light
from .common import Attributes, domain_of


@dataclass(frozen=True)
class Kind:
    """One kind of device and how scenes deal with it."""

    domain: str
    # The device as a scene stores it, from its state and attributes; None = nothing to save.
    capture: Callable[[str, Attributes], dict[str, Any] | None]
    # Whether it is as the scene wants: (what the scene sets, state, attributes).
    matches: Callable[[Attributes, str, Attributes], bool]
    # Its share of a scene's rough brightness, or None if it doesn't count.
    brightness: Callable[[Attributes], int] | None = None
    # How a level scene sets it: (percent, what it can do, white in kelvin,
    # white to hue/saturation). None if level scenes leave it out.
    level: Callable[[float, Attributes, float, Callable[[float], tuple[float, float]]], dict[str, Any]] | None = None


LIGHT = Kind("light", light.capture, light.matches, brightness=light.brightness, level=light.level)
COVER = Kind("cover", cover.capture, cover.matches)

# In the order rooms list them.
KINDS: dict[str, Kind] = {kind.domain: kind for kind in (LIGHT, COVER)}
DOMAINS: tuple[str, ...] = tuple(KINDS)


def kind_of(entity_id: str) -> Kind | None:
    return KINDS.get(domain_of(entity_id))


def entry_for(entity_id: str, state: str, attributes: Attributes) -> dict[str, Any] | None:
    """The device as a scene stores it, or None (not a kind scenes take, or nothing to save)."""
    kind = kind_of(entity_id)
    return kind.capture(state, attributes) if kind else None


def matches(entity_id: str, want: Mapping[str, Any], state: str, attributes: Attributes) -> bool:
    kind = kind_of(entity_id)
    return kind.matches(want, state, attributes) if kind else state == want.get("state")


def takes_levels(entity_id: str) -> bool:
    kind = kind_of(entity_id)
    return bool(kind and kind.level)

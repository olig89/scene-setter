"""Turning a device's state into what a Home Assistant scene stores.

The rules for each kind of device live in its own module (``light.py``,
``cover.py``) and are listed in ``kinds.py``; this module gives the common entry
points.

No Home Assistant imports.
"""

from __future__ import annotations

from .common import NOT_THERE, domain_of, plain
from .cover import capture as cover_entry
from .kinds import DOMAINS, entry_for
from .light import EFFECT_OFF, can_dim, level_entry, white_for
from .light import capture as light_entry

__all__ = [
    "DOMAINS",
    "EFFECT_OFF",
    "NOT_THERE",
    "can_dim",
    "cover_entry",
    "domain_of",
    "entry_for",
    "level_entry",
    "light_entry",
    "plain",
    "white_for",
]

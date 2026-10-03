"""Small helpers every kind of device shares.

No Home Assistant imports.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import Enum
from typing import Any

NOT_THERE = ("unavailable", "unknown")

# A plain {attribute: value} view of a state's attributes (or a registry entry's capabilities).
Attributes = Mapping[str, Any]


def domain_of(entity_id: str) -> str:
    return entity_id.split(".", 1)[0]


def plain(value: Any) -> Any:
    """The value as ordinary YAML can hold it: lists for tuples, and the plain
    value of an enum (Home Assistant's colour mode is one)."""
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (tuple, list)):
        return [plain(item) for item in value]
    return value


def near(a: Any, b: Any, slack: float) -> bool:
    try:
        return abs(float(a) - float(b)) <= slack
    except (TypeError, ValueError):
        return a == b


def pair_near(a: Any, b: Any, slack: float) -> bool:
    try:
        return len(a) == len(b) and all(near(x, y, slack) for x, y in zip(a, b))
    except TypeError:
        return a == b

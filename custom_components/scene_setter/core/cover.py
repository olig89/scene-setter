"""Blinds (and windows, and any cover): what a scene saves for one, and whether it matches.

Covers take no part in level scenes or a scene's brightness.

No Home Assistant imports.
"""

from __future__ import annotations

from typing import Any

from .common import NOT_THERE, Attributes, near, plain

POSITION_SLACK = 3  # percent


def capture(state: str, attributes: Attributes) -> dict[str, Any] | None:
    """A cover as a scene stores it, or None if unknown.

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
        entry["current_position"] = plain(position)
    if tilt is not None:
        entry["current_tilt_position"] = plain(tilt)
    return entry


def matches(want: Attributes, state: str, attributes: Attributes) -> bool:
    position, wanted = attributes.get("current_position"), want.get("current_position")
    if wanted is not None and position is not None:
        if not near(wanted, position, POSITION_SLACK):
            return False
    elif (state == "closed") != (want.get("state") == "closed"):
        return False
    tilt, wanted_tilt = attributes.get("current_tilt_position"), want.get("current_tilt_position")
    return wanted_tilt is None or tilt is None or near(wanted_tilt, tilt, POSITION_SLACK)

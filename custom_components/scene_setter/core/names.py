"""Scene names.

A scene is called "Evening" in its room, and "Kitchen Evening" in Home
Assistant, so the same name can be used in every room and Home Assistant's own
lists still say which room a scene belongs to.

No Home Assistant imports.
"""

from __future__ import annotations

MAX_NAME = 60


class SceneNameError(ValueError):
    """The name can't be used."""


def clean_name(name: object) -> str:
    """The name with tidy spacing. Raises SceneNameError if nothing is left or it is too long."""
    text = " ".join(str(name or "").split())
    if not text:
        raise SceneNameError("Give the scene a name.")
    if len(text) > MAX_NAME:
        raise SceneNameError(f"That name is too long (at most {MAX_NAME} characters).")
    return text


def full_name(room: str, name: str) -> str:
    """The name Home Assistant shows: the room's name, then the scene's."""
    room = " ".join(room.split())
    if not room or name.casefold().startswith(room.casefold() + " ") or name.casefold() == room.casefold():
        return name
    return f"{room} {name}"


def short_name(room: str, full: str) -> str:
    """The name the room's own list shows: ``full`` without the room in front."""
    room = " ".join(room.split())
    prefix = room.casefold() + " "
    if room and full.casefold().startswith(prefix) and full[len(prefix):].strip():
        return full[len(prefix):].strip()
    return full


def same_name(a: str, b: str) -> bool:
    return " ".join(a.split()).casefold() == " ".join(b.split()).casefold()

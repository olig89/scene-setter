"""The log behind scene suggestions.

Home Assistant's history keeps only on and off for lights (it leaves brightness
and colour out on purpose), so Scene Setter writes down each room's lights
itself: whenever they settle, with at least one on, after a change. The rules
for what counts and what is suggested are in ``core/habits.py``.

The log is kept in Home Assistant's own storage (``.storage/scene_setter.habits``),
only on this machine, for ``KEEP`` days.
"""

from __future__ import annotations

from collections.abc import Callable
from functools import partial
from datetime import datetime
from typing import Any

from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import CALLBACK_TYPE, Event, EventStateChangedData, HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect, async_dispatcher_send
from homeassistant.helpers.event import async_call_later, async_track_state_change_event
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import ANY_SIGNAL, DOMAIN
from .core.kinds import entry_for
from .core.habits import (
    KEEP,
    Setting,
    Suggestion,
    is_lit,
    lights_only,
    same_setting,
    setting_from,
    setting_to,
    suggest,
)

STORAGE_KEY = f"{DOMAIN}.habits"
STORAGE_VERSION = 1
SETTLE_S = 120  # the lights must stay as they are this long to count
SAVE_DELAY_S = 30
MAX_SETTINGS = 5000  # however busy the house, the log stays small


class HabitLog:
    def __init__(self, hass: HomeAssistant, rooms: Callable[[], dict[str, list[str]]]) -> None:
        """``rooms`` gives each room's lights: {area id: [light entity ids]}."""
        self.hass = hass
        self._rooms = rooms
        self._store: Store[dict[str, Any]] = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self.settings: list[Setting] = []
        self.dismissed: list[dict[str, Any]] = []  # {"area_id", "lights"}
        self._room_of: dict[str, str] = {}
        self._watching: frozenset[str] = frozenset()
        self._unsub_state: CALLBACK_TYPE | None = None
        self._unsub_signal: CALLBACK_TYPE | None = None
        self._timers: dict[str, CALLBACK_TYPE] = {}
        self._began: dict[str, datetime] = {}  # when the room's latest change was made
        self._last: dict[str, dict[str, Any]] = {}  # each room's lights as they last settled

    # ---- start and stop ------------------------------------------------------

    async def async_start(self) -> None:
        data = await self._store.async_load() or {}
        cutoff = dt_util.now() - KEEP
        for raw in data.get("settings") or ():
            try:
                setting = setting_from(raw)
            except (KeyError, TypeError, ValueError):
                continue
            if setting.at >= cutoff:
                self.settings.append(setting)
        self.dismissed = [d for d in data.get("dismissed") or () if isinstance(d, dict) and d.get("lights")]
        self._unsub_signal = async_dispatcher_connect(self.hass, ANY_SIGNAL, self._rewatch)
        self._rewatch()

    async def async_stop(self) -> None:
        if self._unsub_signal:
            self._unsub_signal()
            self._unsub_signal = None
        if self._unsub_state:
            self._unsub_state()
            self._unsub_state = None
        for cancel in self._timers.values():
            cancel()
        self._timers.clear()
        await self._store.async_save(self._data())

    def _data(self) -> dict[str, Any]:
        return {"settings": [setting_to(s) for s in self.settings], "dismissed": self.dismissed}

    def _save(self) -> None:
        self._store.async_delay_save(self._data, SAVE_DELAY_S)

    # ---- watching the lights -------------------------------------------------

    @callback
    def _rewatch(self) -> None:
        """Rooms or their lights may have changed: watch the lights rooms hold now."""
        room_of = {light: area_id for area_id, lights in self._rooms().items() for light in lights}
        self._room_of = room_of
        ids = frozenset(room_of)
        if ids == self._watching and self._unsub_state:
            return
        if self._unsub_state:
            self._unsub_state()
        self._watching = ids
        self._unsub_state = async_track_state_change_event(self.hass, list(ids), self._changed) if ids else None
        for area_id in set(room_of.values()) - set(self._last):
            self._last[area_id] = self._lights(area_id)

    def _lights(self, area_id: str) -> dict[str, Any]:
        found: dict[str, Any] = {}
        for light, room in self._room_of.items():
            if room != area_id:
                continue
            state = self.hass.states.get(light)
            if state is None or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
                continue  # unreachable lights say nothing about how the room is used
            found[light] = state
        return lights_only({e: v for e, s in found.items() if (v := entry_for(e, s.state, s.attributes))})

    @callback
    def _changed(self, event: Event[EventStateChangedData]) -> None:
        area_id = self._room_of.get(event.data["entity_id"])
        if area_id is None:
            return
        old, new = event.data.get("old_state"), event.data.get("new_state")
        gone = (STATE_UNAVAILABLE, STATE_UNKNOWN)
        if old is None or new is None or old.state in gone or new.state in gone:
            # A light dropping out or coming back (a restart, a power cut) is not
            # someone setting the room. Unless a change is already waiting, the
            # room as it is now becomes the starting point.
            if area_id not in self._timers:
                self._last[area_id] = self._lights(area_id)
            return
        # The setting began with the last change before the lights settled.
        self._began[area_id] = dt_util.now()
        if cancel := self._timers.pop(area_id, None):
            cancel()
        self._timers[area_id] = async_call_later(self.hass, SETTLE_S, partial(self._settled, area_id))

    @callback
    def _settled(self, area_id: str, _now: datetime | None = None) -> None:
        self._timers.pop(area_id, None)
        began = self._began.pop(area_id, dt_util.now())
        lights = self._lights(area_id)
        before = self._last.get(area_id)
        self._last[area_id] = lights
        if not is_lit(lights):
            return
        if before is not None and is_lit(before) and same_setting(before, lights):
            return  # a small nudge, or something changed and went back
        self.add(Setting(dt_util.as_local(began), area_id, lights))

    @callback
    def add(self, setting: Setting) -> None:
        cutoff = dt_util.now() - KEEP
        self.settings = [s for s in self.settings if s.at >= cutoff][-(MAX_SETTINGS - 1):]
        self.settings.append(setting)
        self._save()
        async_dispatcher_send(self.hass, ANY_SIGNAL)

    # ---- suggestions ---------------------------------------------------------

    def suggestions(self, area_id: str, scenes: dict[str, dict[str, Any]]) -> list[Suggestion]:
        dismissed = [d["lights"] for d in self.dismissed if d.get("area_id") == area_id]
        return suggest(self.settings, area_id, scenes, dismissed, dt_util.now())

    @callback
    def dismiss(self, suggestion: Suggestion) -> None:
        self.dismissed.append({"area_id": suggestion.area_id, "lights": suggestion.lights, "at": dt_util.now().isoformat()})
        self._save()
        async_dispatcher_send(self.hass, ANY_SIGNAL)

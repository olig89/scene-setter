"""An "on now" sensor for each scene.

A scene in Home Assistant has no on or off: its state is the time it was last
turned on. Each scene in a room gets a sensor that is on while the room is as
the scene left it, so a wall button's light, a dashboard or an automation can
show or use which scene is on. The page's "On now" mark reads the same sensor.

The sensors follow the scenes: one appears when a scene is saved, its name
follows a rename, its area follows the scene, and it goes when the scene is
deleted.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.event import async_track_state_change_event

from .const import ANY_SIGNAL
from .core.match import scene_matches
from .setter import SceneInfo, SceneSetter


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    setter: SceneSetter = entry.runtime_data
    sensors: dict[str, SceneActiveSensor] = {}

    @callback
    def _gone(sensor: SceneActiveSensor) -> bool:
        """The scene was deleted or left its room (not just reloading)."""
        scene = er.async_get(hass).async_get(sensor.scene.registry_id)
        return scene is None or not scene.area_id or bool(scene.disabled_by)

    @callback
    def _reconcile() -> None:
        scenes = {s.active_sensor_key: s for s in setter.all_scenes()}
        new: list[SceneActiveSensor] = []
        for key, scene in scenes.items():
            if key in sensors:
                sensors[key].async_set_scene(scene)
            else:
                sensors[key] = SceneActiveSensor(scene)
                new.append(sensors[key])
        for key in [k for k in sensors if k not in scenes]:
            # A scene briefly missing while scenes reload keeps its sensor.
            if _gone(sensors[key]):
                sensor = sensors.pop(key)
                registry = er.async_get(hass)
                if sensor.entity_id and registry.async_get(sensor.entity_id):
                    registry.async_remove(sensor.entity_id)
        if new:
            async_add_entities(new)

    entry.async_on_unload(async_dispatcher_connect(hass, ANY_SIGNAL, _reconcile))
    _reconcile()


class SceneActiveSensor(BinarySensorEntity):
    """On while the room is as the scene left it."""

    _attr_should_poll = False
    _attr_icon = "mdi:palette-swatch-variant"

    def __init__(self, scene: SceneInfo) -> None:
        self.scene = scene
        self._attr_unique_id = scene.active_sensor_key
        # Follows the scene's entity id: scene.kitchen_evening gets
        # binary_sensor.kitchen_evening_active. Only used the first time; after
        # that the entity registry keeps it, so a scene rename changes nothing.
        self.entity_id = f"binary_sensor.{scene.entity_id.split('.', 1)[1]}_active"
        self._unsub = None
        self._watching: frozenset[str] = frozenset()
        self._differ: list[str] = []

    @property
    def name(self) -> str:
        return f"{self.scene.full_name} active"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"scene": self.scene.entity_id, "not_matching": self._differ}

    async def async_added_to_hass(self) -> None:
        self._watch()
        self._evaluate()
        self._place()

    async def async_will_remove_from_hass(self) -> None:
        if self._unsub:
            self._unsub()
            self._unsub = None

    @callback
    def async_set_scene(self, scene: SceneInfo) -> None:
        """The scene changed: saved over, renamed or moved."""
        self.scene = scene
        if self.hass is None:
            return
        self._watch()
        self._evaluate()
        self._place()
        self.async_write_ha_state()

    @callback
    def _watch(self) -> None:
        ids = frozenset(self.scene.entities or ())
        if ids == self._watching and self._unsub:
            return
        if self._unsub:
            self._unsub()
        self._watching = ids
        self._unsub = async_track_state_change_event(self.hass, list(ids), self._changed) if ids else None

    @callback
    def _changed(self, _event: Event[EventStateChangedData]) -> None:
        self._evaluate()
        self.async_write_ha_state()

    @callback
    def _evaluate(self) -> None:
        wanted = self.scene.entities or {}
        current = {}
        for entity_id in wanted:
            state = self.hass.states.get(entity_id)
            current[entity_id] = (state.state, state.attributes) if state is not None else None
        self._attr_is_on, self._differ = scene_matches(wanted, current)

    @callback
    def _place(self) -> None:
        """Keep the sensor in the scene's room."""
        registry = er.async_get(self.hass)
        entry = registry.async_get(self.entity_id) if self.entity_id else None
        if entry is not None and self.scene.area_id and entry.area_id != self.scene.area_id:
            registry.async_update_entity(self.entity_id, area_id=self.scene.area_id)

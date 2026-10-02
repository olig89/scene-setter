"""Saving, renaming and deleting scenes, and working out what a room holds.

Scenes are written to Home Assistant's own ``scenes.yaml`` (the file the scene
editor uses), so they are ordinary Home Assistant scenes: they survive a
restart, open in the scene editor, and can be turned on from anything.

A scene belongs to a room through its area in Home Assistant. Every scene made
in Home Assistant with that area is listed for the room, whichever tool made it.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from homeassistant.config import SCENE_CONFIG_PATH
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_ENTITY_ID, CONF_ENTITIES, CONF_ICON, CONF_ID, CONF_NAME, SERVICE_RELOAD
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import (
    area_registry as ar,
    device_registry as dr,
    entity_registry as er,
    floor_registry as fr,
)
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.util.file import write_utf8_file_atomic
from homeassistant.util.yaml import dump, load_yaml

from .const import ANY_SIGNAL, CONF_EXCLUDE, CONF_INCLUDE, CONF_NO_APOSTROPHES, CONF_ROOMS, DOMAIN, IGNORE_LABEL
from .core.capture import DOMAINS, domain_of, entry_for
from .core.names import SceneNameError, clean_name, full_name, id_text, same_name, short_name

SCENE = "scene"
HA_SCENES = "homeassistant"  # the platform of scenes made in Home Assistant
SCENE_PLATFORM = "homeassistant_scene"
SCENE_WAIT_S = 10.0

SAVED = "saved"
LEFT_OUT = "left_out"  # switched off for this room in the settings
IGNORED = "ignored"  # carries the ignore label
GROUP = "group"  # a group: its members are saved instead


class SceneSetterError(HomeAssistantError):
    """Something the person can put right. ``key`` names it for the page."""

    def __init__(self, key: str, message: str) -> None:
        super().__init__(message)
        self.key = key


@dataclass
class Row:
    """One light or blind a room knows about."""

    entity_id: str
    name: str
    status: str
    via: str | None = None  # the group that brought it in
    added: bool = False  # added by hand in the settings (not in the area)
    members: list[str] = field(default_factory=list)

    @property
    def domain(self) -> str:
        return domain_of(self.entity_id)


@dataclass
class SceneInfo:
    entity_id: str
    name: str  # as the room shows it
    full_name: str  # as Home Assistant shows it
    config_id: str | None  # set for scenes made in Home Assistant
    entities: dict[str, dict[str, Any]] | None  # what it sets, when it can be read
    key: str = ""  # stable across renames: the scene's platform and unique id
    area_id: str | None = None
    registry_id: str = ""  # the scene's entity registry entry

    @property
    def editable(self) -> bool:
        return self.config_id is not None

    @property
    def active_sensor_key(self) -> str:
        return f"active_{self.key}"


def _read(path: str) -> list[dict[str, Any]] | None:
    if not os.path.isfile(path):
        return None
    data = load_yaml(path)
    return data if isinstance(data, list) else []


def _write(path: str, data: list[dict[str, Any]]) -> None:
    write_utf8_file_atomic(path, dump(data))


class SceneSetter:
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self._lock = asyncio.Lock()

    # ---- what a room holds ---------------------------------------------------

    def _room_options(self, area_id: str) -> Mapping[str, Any]:
        return (self.entry.options.get(CONF_ROOMS) or {}).get(area_id) or {}

    def _area_of(self, entity: er.RegistryEntry, devices: dr.DeviceRegistry) -> str | None:
        if entity.area_id:
            return entity.area_id
        device = devices.async_get(entity.device_id) if entity.device_id else None
        return device.area_id if device else None

    def _ignored(self, entity_id: str) -> bool:
        entity = er.async_get(self.hass).async_get(entity_id)
        if entity is None:
            return False
        if IGNORE_LABEL in entity.labels:
            return True
        device = dr.async_get(self.hass).async_get(entity.device_id) if entity.device_id else None
        return device is not None and IGNORE_LABEL in device.labels

    def _name(self, entity_id: str) -> str:
        state = self.hass.states.get(entity_id)
        if state is not None and state.attributes.get("friendly_name"):
            return str(state.attributes["friendly_name"])
        entity = er.async_get(self.hass).async_get(entity_id)
        return (entity and (entity.name or entity.original_name)) or entity_id

    def _members(self, entity_id: str) -> list[str] | None:
        """A group's members of its own kind, or None if it isn't a group."""
        state = self.hass.states.get(entity_id)
        members = state.attributes.get(ATTR_ENTITY_ID) if state is not None else None
        if not isinstance(members, (list, tuple)):
            return None
        domain = domain_of(entity_id)
        return [m for m in members if isinstance(m, str) and domain_of(m) == domain and m != entity_id]

    def area_entities(self, area_id: str) -> list[str]:
        """The lights and blinds Home Assistant puts in the area."""
        entities = er.async_get(self.hass)
        devices = dr.async_get(self.hass)
        found = [
            e.entity_id
            for e in entities.entities.values()
            if e.domain in DOMAINS
            and not e.disabled_by
            and not e.hidden_by
            and e.entity_category is None
            and self._area_of(e, devices) == area_id
        ]
        return sorted(found, key=lambda e: (DOMAINS.index(domain_of(e)), self._name(e).casefold()))

    def rows(self, area_id: str) -> list[Row]:
        """Every light and blind the room knows about, and whether it is saved.

        A group is replaced by its members, so a scene sets each light itself
        and never both a group and what is in it.
        """
        options = self._room_options(area_id)
        excluded = set(options.get(CONF_EXCLUDE) or ())
        added = [e for e in options.get(CONF_INCLUDE) or () if domain_of(e) in DOMAINS]
        rows: dict[str, Row] = {}

        def add(entity_id: str, via: str | None, by_hand: bool) -> None:
            if entity_id in rows:
                return
            name = self._name(entity_id)
            if entity_id in excluded:
                rows[entity_id] = Row(entity_id, name, LEFT_OUT, via, by_hand)
                return
            if self._ignored(entity_id):
                rows[entity_id] = Row(entity_id, name, IGNORED, via, by_hand)
                return
            members = self._members(entity_id)
            if members is None:
                rows[entity_id] = Row(entity_id, name, SAVED, via, by_hand)
                return
            rows[entity_id] = Row(entity_id, name, GROUP, via, by_hand, members)
            for member in members:
                add(member, entity_id, False)

        for entity_id in self.area_entities(area_id):
            add(entity_id, None, False)
        for entity_id in added:
            add(entity_id, None, True)
        return list(rows.values())

    # ---- the scenes of a room ------------------------------------------------

    def _scene_states(self, entity_id: str) -> dict[str, dict[str, Any]] | None:
        platform = self.hass.data.get(SCENE_PLATFORM)
        entity = getattr(platform, "entities", {}).get(entity_id) if platform is not None else None
        states = getattr(getattr(entity, "scene_config", None), "states", None)
        if not isinstance(states, Mapping):
            return None
        return {eid: {"state": s.state, **dict(s.attributes)} for eid, s in states.items()}

    def _info(self, entity: er.RegistryEntry, room: str) -> SceneInfo:
        state = self.hass.states.get(entity.entity_id)
        full = entity.name or (state and state.attributes.get("friendly_name")) or entity.original_name or entity.entity_id
        config_id = entity.unique_id if entity.platform == HA_SCENES else None
        return SceneInfo(
            entity.entity_id,
            short_name(room, str(full)),
            str(full),
            config_id,
            self._scene_states(entity.entity_id),
            key=f"{entity.platform}_{entity.unique_id or entity.id}",
            area_id=entity.area_id,
            registry_id=entity.id,
        )

    def scenes(self, area_id: str) -> list[SceneInfo]:
        area = ar.async_get(self.hass).async_get_area(area_id)
        room = area.name if area else ""
        found = [
            self._info(e, room)
            for e in er.async_get(self.hass).entities.values()
            if e.domain == SCENE and e.area_id == area_id and not e.disabled_by
            and self.hass.states.get(e.entity_id) is not None
        ]
        return sorted(found, key=lambda s: s.name.casefold())

    def all_scenes(self) -> list[SceneInfo]:
        """Every scene that belongs to a room and whose contents can be read."""
        found: list[SceneInfo] = []
        for area in ar.async_get(self.hass).async_list_areas():
            found.extend(s for s in self.scenes(area.id) if s.entities)
        return found

    def active_sensor(self, scene: SceneInfo) -> str | None:
        """The entity id of the scene's "on now" sensor, if it has one."""
        return er.async_get(self.hass).async_get_entity_id("binary_sensor", DOMAIN, scene.active_sensor_key)

    def _find(self, scene: str) -> tuple[er.RegistryEntry, str]:
        """The scene's registry entry and config id, from its entity id or config id."""
        registry = er.async_get(self.hass)
        entity_id = scene if scene.startswith(f"{SCENE}.") else registry.async_get_entity_id(SCENE, HA_SCENES, scene)
        entity = registry.async_get(entity_id) if entity_id else None
        if entity is None:
            raise SceneSetterError("unknown_scene", "That scene doesn't exist.")
        if entity.platform != HA_SCENES or not entity.unique_id:
            raise SceneSetterError(
                "not_editable",
                "That scene comes from another app (such as the Hue app), so it can only be changed there.",
            )
        return entity, entity.unique_id

    # ---- the scene file ------------------------------------------------------

    @property
    def _path(self) -> str:
        return self.hass.config.path(SCENE_CONFIG_PATH)

    async def _load(self) -> list[dict[str, Any]]:
        try:
            data = await self.hass.async_add_executor_job(_read, self._path)
        except HomeAssistantError as err:
            raise SceneSetterError("file_unreadable", f"scenes.yaml can't be read: {err}") from err
        return list(data or [])

    async def _store(self, data: list[dict[str, Any]]) -> None:
        await self.hass.async_add_executor_job(_write, self._path, data)
        await self.hass.services.async_call(SCENE, SERVICE_RELOAD, blocking=True)

    async def _entity_of(self, config_id: str) -> str | None:
        registry = er.async_get(self.hass)
        for _ in range(int(SCENE_WAIT_S / 0.1)):
            entity_id = registry.async_get_entity_id(SCENE, HA_SCENES, config_id)
            if entity_id and self.hass.states.get(entity_id) is not None:
                return entity_id
            await asyncio.sleep(0.1)
        return None

    def _changed(self) -> None:
        async_dispatcher_send(self.hass, ANY_SIGNAL)

    # ---- changes -------------------------------------------------------------

    def capture(self, area_id: str) -> tuple[dict[str, dict[str, Any]], list[str]]:
        """The room as it is now: what to save, and what had to be left out."""
        entities: dict[str, dict[str, Any]] = {}
        skipped: list[str] = []
        for row in self.rows(area_id):
            if row.status != SAVED:
                continue
            state = self.hass.states.get(row.entity_id)
            entry = entry_for(row.entity_id, state.state, state.attributes) if state is not None else None
            if entry is None:
                # Not there right now. Saving it as off would switch it off
                # every time the scene is used once it comes back.
                skipped.append(row.entity_id)
            else:
                entities[row.entity_id] = entry
        return entities, skipped

    async def async_save(self, area_id: str | None, name: str | None = None, scene: str | None = None) -> dict[str, Any]:
        """Save the room as it is now, as a new scene or over an existing one.

        With ``scene`` that scene is saved over (and renamed if ``name`` is
        given). Otherwise a scene of that name in the room is saved over, or a
        new one is made.
        """
        registry = er.async_get(self.hass)
        config_id: str | None = None
        if scene:
            entity, config_id = self._find(scene)
            area_id = area_id or entity.area_id
        area = ar.async_get(self.hass).async_get_area(area_id) if area_id else None
        if area is None:
            raise SceneSetterError("unknown_room", "That room doesn't exist.")
        current = self.scenes(area.id)
        try:
            if config_id is not None:
                was = next((s for s in current if s.config_id == config_id), None)
                wanted = clean_name(name) if name else (was.name if was else None)
                if wanted is None:
                    raise SceneNameError("Give the scene a name.")
            else:
                wanted = clean_name(name)
        except SceneNameError as err:
            raise SceneSetterError("invalid_name", str(err)) from err
        for other in current:
            if not same_name(other.name, wanted) or (config_id is not None and other.config_id == config_id):
                continue
            if config_id is not None:
                raise SceneSetterError("name_taken", f"This room already has a scene called {other.name}.")
            if not other.editable:
                raise SceneSetterError(
                    "name_taken",
                    f"This room already has a scene called {other.name} from another app. Choose another name.",
                )
            config_id = other.config_id
            wanted = other.name  # saving over keeps the scene's name as it was written

        entities, skipped = self.capture(area.id)
        if not entities:
            raise SceneSetterError(
                "nothing_to_save",
                "This room has no lights or blinds to save."
                if not skipped
                else "None of this room's lights or blinds can be reached right now, so there is nothing to save.",
            )

        async with self._lock:
            data = await self._load()
            new = config_id is None
            config_id = config_id or uuid.uuid4().hex
            old = next((item for item in data if item.get(CONF_ID) == config_id), None)
            if old is None and not new:
                raise SceneSetterError(
                    "not_in_file", "That scene isn't in scenes.yaml, so it can only be changed where it was made."
                )
            config: dict[str, Any] = {CONF_ID: config_id, CONF_NAME: full_name(area.name, wanted)}
            if old is not None and old.get(CONF_ICON):
                config[CONF_ICON] = old[CONF_ICON]
            config[CONF_ENTITIES] = entities
            # Tells the scene editor these were added as single entities, not whole devices.
            config["metadata"] = {entity_id: {"entity_only": True} for entity_id in entities}
            before = list(data)
            if old is None:
                data.append(config)
            else:
                data[data.index(old)] = config
            if new and self.entry.options.get(CONF_NO_APOSTROPHES):
                # Claim the entity id before Home Assistant makes one from the name,
                # so an apostrophe doesn't become an underscore (olis_, not oli_s_).
                registry.async_get_or_create(
                    SCENE, HA_SCENES, config_id, suggested_object_id=id_text(config[CONF_NAME])
                )
            await self._store(data)
            entity_id = await self._entity_of(config_id)
            if entity_id is None:
                await self._store(before)
                if new and (claimed := registry.async_get_entity_id(SCENE, HA_SCENES, config_id)):
                    registry.async_remove(claimed)
                raise SceneSetterError(
                    "not_loaded",
                    "Home Assistant didn't load the scene. Check that configuration.yaml has the line "
                    "'scene: !include scenes.yaml' (it does unless it was removed).",
                )
            if registry.async_get(entity_id).area_id != area.id:
                registry.async_update_entity(entity_id, area_id=area.id)
        self._changed()
        return {
            "scene": entity_id,
            "name": wanted,
            "created": new,
            "saved": list(entities),
            "skipped": skipped,
        }

    async def async_rename(self, scene: str, name: str) -> dict[str, Any]:
        entity, config_id = self._find(scene)
        try:
            wanted = clean_name(name)
        except SceneNameError as err:
            raise SceneSetterError("invalid_name", str(err)) from err
        area = ar.async_get(self.hass).async_get_area(entity.area_id) if entity.area_id else None
        if area is not None:
            for other in self.scenes(area.id):
                if other.entity_id != entity.entity_id and same_name(other.name, wanted):
                    raise SceneSetterError("name_taken", f"This room already has a scene called {other.name}.")
        async with self._lock:
            data = await self._load()
            item = next((i for i in data if i.get(CONF_ID) == config_id), None)
            if item is None:
                raise SceneSetterError(
                    "not_in_file", "That scene isn't in scenes.yaml, so it can only be changed where it was made."
                )
            item[CONF_NAME] = full_name(area.name, wanted) if area else wanted
            await self._store(data)
            if entity.name:
                # A name typed over the scene's own in Home Assistant would hide the new one.
                er.async_get(self.hass).async_update_entity(entity.entity_id, name=None)
        self._changed()
        # The entity id stays as it is, so buttons and routines that use the scene keep working.
        return {"scene": entity.entity_id, "name": wanted}

    async def async_delete(self, scene: str) -> dict[str, Any]:
        entity, config_id = self._find(scene)
        async with self._lock:
            data = await self._load()
            kept = [i for i in data if i.get(CONF_ID) != config_id]
            if len(kept) == len(data):
                raise SceneSetterError(
                    "not_in_file", "That scene isn't in scenes.yaml, so it can only be deleted where it was made."
                )
            await self._store(kept)
            registry = er.async_get(self.hass)
            if registry.async_get(entity.entity_id) is not None:
                registry.async_remove(entity.entity_id)
        self._changed()
        return {"scene": entity.entity_id}

    def set_room(self, area_id: str, exclude: list[str], include: list[str]) -> None:
        """Which lights and blinds the room saves (settings)."""
        if ar.async_get(self.hass).async_get_area(area_id) is None:
            raise SceneSetterError("unknown_room", "That room doesn't exist.")
        rooms = {k: dict(v) for k, v in (self.entry.options.get(CONF_ROOMS) or {}).items()}
        include = sorted({e for e in include if domain_of(e) in DOMAINS})
        exclude = sorted({e for e in exclude if domain_of(e) in DOMAINS})
        if include or exclude:
            rooms[area_id] = {CONF_EXCLUDE: exclude, CONF_INCLUDE: include}
        else:
            rooms.pop(area_id, None)
        self.hass.config_entries.async_update_entry(self.entry, options={**self.entry.options, CONF_ROOMS: rooms})
        self._changed()

    # ---- what the page shows -------------------------------------------------

    def snapshot(self) -> list[dict[str, Any]]:
        areas = ar.async_get(self.hass)
        floors = fr.async_get(self.hass)
        rooms: list[tuple[tuple, dict[str, Any]]] = []
        for area in areas.async_list_areas():
            rows = self.rows(area.id)
            scenes = self.scenes(area.id)
            if not rows and not scenes:
                continue
            floor = floors.async_get_floor(area.floor_id) if area.floor_id else None
            rooms.append(
                (
                    (floor.level if floor and floor.level is not None else 999, floor.name if floor else "", area.name.casefold()),
                    {
                        "area_id": area.id,
                        "name": area.name,
                        "icon": area.icon,
                        "floor": floor.name if floor else None,
                        "entities": [
                            {
                                "entity_id": r.entity_id,
                                "name": r.name,
                                "domain": r.domain,
                                "status": r.status,
                                "via": r.via,
                                "added": r.added,
                                "members": r.members,
                            }
                            for r in rows
                        ],
                        "scenes": [
                            {
                                "entity_id": s.entity_id,
                                "name": s.name,
                                "full_name": s.full_name,
                                "config_id": s.config_id,
                                "editable": s.editable,
                                "entities": s.entities,
                                "active_sensor": self.active_sensor(s),
                            }
                            for s in scenes
                        ],
                    },
                )
            )
        return [room for _, room in sorted(rooms, key=lambda item: item[0])]

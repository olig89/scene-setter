"""A small house: a kitchen with lights and a blind, in a config folder of its own
so the tests can read and write a real scenes.yaml."""

from pathlib import Path

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.core import HomeAssistant
from homeassistant.helpers import area_registry as ar, entity_registry as er
from homeassistant.setup import async_setup_component

from custom_components.scene_setter.const import DOMAIN


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


class House:
    def __init__(self, hass: HomeAssistant, folder: Path) -> None:
        self.hass = hass
        self.folder = folder
        self.entry: MockConfigEntry | None = None
        self.calls: list[tuple[str, str, dict]] = []

    @property
    def scenes_file(self) -> Path:
        return self.folder / "scenes.yaml"

    def area(self, name: str) -> str:
        return ar.async_get(self.hass).async_get_or_create(name).id

    def add(self, entity_id: str, state: str, attrs: dict | None = None, area: str | None = None, **registry) -> None:
        """An entity in the registry (so it can have an area) with a state."""
        domain, object_id = entity_id.split(".")
        entry = er.async_get(self.hass).async_get_or_create(
            domain, "test", object_id, suggested_object_id=object_id, **registry
        )
        if area:
            er.async_get(self.hass).async_update_entity(entry.entity_id, area_id=area)
        self.hass.states.async_set(entity_id, state, {"friendly_name": object_id.replace("_", " ").title(), **(attrs or {})})

    async def handle(self, call) -> None:
        self.calls.append((call.domain, call.service, dict(call.data)))

    @property
    def setter(self):
        return self.entry.runtime_data


@pytest.fixture
async def house(hass: HomeAssistant, tmp_path: Path) -> House:
    hass.config.config_dir = str(tmp_path)
    (tmp_path / "configuration.yaml").write_text("scene: !include scenes.yaml\n")
    (tmp_path / "scenes.yaml").write_text("[]\n")
    assert await async_setup_component(hass, "scene", {"scene": []})
    built = House(hass, tmp_path)
    for domain, services in {
        "light": ("turn_on", "turn_off"),
        "cover": ("set_cover_position", "set_cover_tilt_position", "open_cover", "close_cover"),
    }.items():
        for service in services:
            hass.services.async_register(domain, service, built.handle)
    kitchen = built.area("Kitchen")
    built.add("light.ceiling", "on", {"brightness": 200, "color_mode": "brightness", "supported_color_modes": ["brightness"]}, kitchen)
    built.add(
        "light.island",
        "on",
        {"brightness": 120, "color_mode": "color_temp", "color_temp_kelvin": 2700, "hs_color": (28.0, 65.0)},
        kitchen,
    )
    built.add("light.counter", "off", {}, kitchen)
    built.add("cover.blind", "open", {"current_position": 40, "supported_features": 15}, kitchen)
    built.add("switch.kettle", "on", {}, kitchen)
    built.entry = MockConfigEntry(domain=DOMAIN, title="Scene Setter", data={}, options={})
    built.entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(built.entry.entry_id)
    await hass.async_block_till_done()
    return built

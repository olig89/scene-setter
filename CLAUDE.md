# Scene Setter: notes for Claude Code

Home Assistant custom integration. Saves a room's lights and covers, as they are now, as a named scene. Sibling of `olig89/watt-window` and `olig89/room-routines`; keep the same conventions.

## Layout

- `custom_components/scene_setter/`
  - `__init__.py`: setup, the three actions (`save`, `rename`, `delete`), panel and card registration.
  - `setter.py`: `SceneSetter`, all the work. Room contents (`rows`), scene listing (`scenes`), `capture`, `async_save` / `async_rename` / `async_delete`, `set_room`, `snapshot`.
  - `websocket.py`: `scene_setter/subscribe`, `save`, `rename`, `delete`, `save_room` (admin only).
  - `core/capture.py`, `core/names.py`: pure functions, **no Home Assistant imports** (CI greps for this).
  - `config_flow.py`: one empty step, single instance.
  - `www/scene-setter.js`: the sidebar page (`scene-setter-panel`) and the dashboard card (`scene-setter-card`) in one file. Plain web components, no build step.
  - `strings.json` and `translations/en.json` must be identical (a test checks).
- `tests/core` (no HA needed), `tests/integration` (real `scenes.yaml` in a temp config folder).

## Rules that must hold

- Scenes live only in Home Assistant's `scenes.yaml`. There is no store of our own. A scene belongs to a room through the scene entity's area.
- Scene name in HA is `<Area name> <name>`; the room shows it without the area. Rename changes the name only, never the entity ID.
- A new scene's entity ID is claimed in the entity registry before the reload, from the name without apostrophes (`core/names.py::id_text`): `scene.olis_office_dim`, not `oli_s_`. Display names keep apostrophes. A failed save removes the claim.
- Unreachable entities (`unavailable` / `unknown`) are left out of a scene, never saved as off.
- A group (state has an `entity_id` list) is replaced by its members.
- Only the colour attribute of the light's current `color_mode` is saved.
- Values written to YAML must be plain: HA hands over `ColorMode` enums and tuples (`core/capture.py::_plain`).
- Every write: load `scenes.yaml`, change, atomic write, `scene.reload`, then wait for the entity. If the entity never appears the write is rolled back.
- The page is open to non-admins; only `save_room` is admin-only, enforced in `websocket.py`.
- Wording on the page and in the README is plain English, no jargon.

## Version and release

The version is in three places and a test checks they agree: `manifest.json`, `const.py` (`VERSION`), `www/scene-setter.js` (`PAGE_VERSION`).

To release: bump all three, update the README status line, commit to `main`, wait for both workflows (Tests, Validate) to pass, then `gh release create vX.Y.Z --target main --title "Scene Setter X.Y.Z" --notes "..."`. HACS installs from GitHub releases, so a tag alone is not enough.

## Testing

    pip install -r requirements_test.txt
    python -m pytest -q

Use Python 3.14 to get the current Home Assistant (3.13 resolves to an older one; both pass). `tests/core` alone: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/core`.

There are no automated tests for the JavaScript. To check the page for real: run `hass -c <dir>` with `home-assistant-frontend` installed, `custom_components/scene_setter` linked into the config folder, `scene: !include scenes.yaml`, and a few lights and a cover in an area; then drive `/scene-setter` with Playwright. This found the `ColorMode` bug that the unit tests missed.

## Not done yet

- GitHub topics are not set on the repo, so `validate.yml` ignores the `topics` check. Set topics and remove `topics` from `ignore`.
- No brand icon.
- No JavaScript tests.

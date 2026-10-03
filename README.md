# Scene Setter

Save a room's lights and blinds, as they are right now, as a named scene, for Home Assistant.

Set the room how you like it (by hand, from a wall switch, from any app), press **Save current scene**, and give it a name. The result is an ordinary Home Assistant scene, so anything can turn it on: a wall button, an automation, [Room Routines](https://github.com/olig89/room-routines), a voice assistant.

**Status: early development (0.3.4).** Install through HACS as a custom repository.

## What you get

- **A sidebar page**, open to everyone in the household:
  - **Rooms**: every Home Assistant area that has lights or covers, grouped by floor, with its saved scenes.
  - **A room**: its lights and blinds as they are now (tap one to open its controls), a large **Save current scene** button, and its saved scenes. Tap a scene to turn it on. Each scene has **Update** (save the room as it is now over it), **Rename** and **Delete**. A scene the room currently matches is marked *On now*. Scenes are listed brightest first, or A–Z (every light's brightness in the scene added up), chosen with the switch above the list and remembered in that browser. Brightest first is the default.
  - **What this room saves** (administrators only): untick a light or blind the room's scenes should leave alone, or add one from another area.
- **A dashboard card** with the same room view, for a room's own dashboard:

  ```yaml
  type: custom:scene-setter-card
  area: kitchen
  ```

  It appears in the card picker as *Scene Setter* and needs no resource added by hand. Options: `title`, and `show_now: false` to hide the row of lights and blinds.
- **An "active" sensor for each scene.** A Home Assistant scene has no on or off: its state is just when it was last turned on. Each scene in a room gets `binary_sensor.<scene>_active` (for example `binary_sensor.kitchen_evening_active`), on while the room is as the scene left it, so a wall button's light, a dashboard or an automation can show or use which scene is on. Its `not_matching` attribute lists the lights and blinds that differ. The page's *On now* mark uses the same sensor.
- **Four actions**, for automations and scripts: `scene_setter.save` (a room and a name, or a scene to save over), `scene_setter.rename`, `scene_setter.delete`, and `scene_setter.create`, which makes a scene from a brightness level without turning anything on: every light in the room at that percent (0 = off), some lights at their own level if you like, one white for every light with colour (2700 K unless you choose another) and any running effect stopped, so nothing left from before stays, blinds left out, for one room or every room at once. A room that already has a scene of that name keeps it unless you choose to replace it.

## How it works

- **Rooms are areas.** A room saves every light and cover that Home Assistant puts in the area, directly or through its device. Hidden and disabled entities are left out.
- **Scenes are Home Assistant's own.** They are written to `scenes.yaml`, the file the scene editor uses, so they survive a restart, open in the scene editor, and can be deleted there too. Nothing is kept anywhere else.
- **A scene belongs to its room through its area.** "Evening" in the Kitchen is called *Kitchen Evening* in Home Assistant, with the entity `scene.kitchen_evening`, so every room can have its own "Evening". Any scene made in Home Assistant and given the room's area shows up in the room and can be updated, renamed and deleted there, whichever tool made it. Scenes from other integrations (the Hue app's) are listed and can be turned on, but not changed.
- **Renaming keeps the entity ID.** A wall button or routine pointing at `scene.kitchen_evening` keeps working after the scene is renamed or updated.
- **Apostrophes in entity IDs, your choice.** Home Assistant makes "Oli's Office Dim" into `scene.oli_s_office_dim`. Turn on *Leave apostrophes out of new scene entity IDs* (Settings → Devices & services → Scene Setter → Configure) to get `scene.olis_office_dim` instead. The name you see keeps its apostrophe either way.
- **Saving under a name the room already has replaces that scene**, after asking.
- **Lights** are saved with their brightness and the colour of the mode they are in (colour temperature, or colour), and their effect: the one running, or "no effect" so that turning the scene on stops one. A light that is off is saved as off, so the scene switches it off.
- **Blinds and other covers** are saved with their position, and their slat tilt if they have one.
- **Anything that can't be reached is left out**, not saved as off. Saving it as off would switch it off every time the scene is used once it comes back. The page says what was left out.
- **Groups are saved as their members.** A light group in the room is replaced by the lights in it, so a scene never sets both a group and its members. This also brings in group members that have no area of their own.
- **"Active" allows for rounding.** A light counts as matching within 5 of 255 brightness, 100 K of colour temperature, and a small step of colour; a blind within 3 % of its position and tilt. Anything unreachable is skipped. A colour a light can't report in its current mode isn't held against the scene. The sensor follows its scene: renamed with it, kept in its room, and removed when the scene is deleted.
- **To keep something out of every scene**, give the entity or its device the label `scene_setter_ignore`. To keep it out of one room's scenes, untick it under *What this room saves*.

## Install

1. In HACS, open the menu, choose **Custom repositories**, and add `https://github.com/olig89/scene-setter` as an **Integration**.
2. Download **Scene Setter** and restart Home Assistant.
3. Under **Settings → Devices & services**, add **Scene Setter**. There is nothing to fill in.

Scene Setter needs `configuration.yaml` to load `scenes.yaml`, which it does unless the line `scene: !include scenes.yaml` was removed.

## Development

`core/` has no Home Assistant imports, so its tests run anywhere:

    PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/core

The full suite needs `pytest-homeassistant-custom-component`, which runs on Linux (or WSL) only.

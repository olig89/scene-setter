# Scene Setter

Save a room's lights and blinds, as they are right now, as a named scene, for Home Assistant.

Set the room how you like it (by hand, from a wall switch, from any app), press **Save current scene**, and give it a name. The result is an ordinary Home Assistant scene, so anything can turn it on: a wall button, an automation, [Room Routines](https://github.com/olig89/room-routines), a voice assistant.

**Status: early development (0.1.1).** Install through HACS as a custom repository.

## What you get

- **A sidebar page**, open to everyone in the household:
  - **Rooms**: every Home Assistant area that has lights or covers, grouped by floor, with its saved scenes.
  - **A room**: its lights and blinds as they are now (tap one to open its controls), a large **Save current scene** button, and its saved scenes. Tap a scene to turn it on. Each scene has **Update** (save the room as it is now over it), **Rename** and **Delete**. A scene the room currently matches is marked *On now*.
  - **What this room saves** (administrators only): untick a light or blind the room's scenes should leave alone, or add one from another area.
- **A dashboard card** with the same room view, for a room's own dashboard:

  ```yaml
  type: custom:scene-setter-card
  area: kitchen
  ```

  It appears in the card picker as *Scene Setter* and needs no resource added by hand. Options: `title`, and `show_now: false` to hide the row of lights and blinds.
- **Three actions**, for automations and scripts: `scene_setter.save` (a room and a name, or a scene to save over), `scene_setter.rename` and `scene_setter.delete`.

## How it works

- **Rooms are areas.** A room saves every light and cover that Home Assistant puts in the area, directly or through its device. Hidden and disabled entities are left out.
- **Scenes are Home Assistant's own.** They are written to `scenes.yaml`, the file the scene editor uses, so they survive a restart, open in the scene editor, and can be deleted there too. Nothing is kept anywhere else.
- **A scene belongs to its room through its area.** "Evening" in the Kitchen is called *Kitchen Evening* in Home Assistant, with the entity `scene.kitchen_evening`, so every room can have its own "Evening". Any scene made in Home Assistant and given the room's area shows up in the room and can be updated, renamed and deleted there, whichever tool made it. Scenes from other integrations (the Hue app's) are listed and can be turned on, but not changed.
- **Renaming keeps the entity ID.** A wall button or routine pointing at `scene.kitchen_evening` keeps working after the scene is renamed or updated.
- **No apostrophes in entity IDs.** "Oli's Office Dim" becomes `scene.olis_office_dim`, not `scene.oli_s_office_dim`. The name you see keeps its apostrophe.
- **Saving under a name the room already has replaces that scene**, after asking.
- **Lights** are saved with their brightness and the colour of the mode they are in (colour temperature, or colour), plus an effect if one is running. A light that is off is saved as off, so the scene switches it off.
- **Blinds and other covers** are saved with their position, and their slat tilt if they have one.
- **Anything that can't be reached is left out**, not saved as off. Saving it as off would switch it off every time the scene is used once it comes back. The page says what was left out.
- **Groups are saved as their members.** A light group in the room is replaced by the lights in it, so a scene never sets both a group and its members. This also brings in group members that have no area of their own.
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

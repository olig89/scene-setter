"""Names shared across the integration."""

from __future__ import annotations

DOMAIN = "scene_setter"
NAME = "Scene Setter"
VERSION = "0.1.0"  # must match manifest.json and the page (a test checks)

CONF_ROOMS = "rooms"
CONF_EXCLUDE = "exclude"
CONF_INCLUDE = "include"

# An entity (or its device) with this label is never saved in a scene.
IGNORE_LABEL = "scene_setter_ignore"

SERVICE_SAVE = "save"
SERVICE_RENAME = "rename"
SERVICE_DELETE = "delete"

# Sent on any change the page shows.
ANY_SIGNAL = f"{DOMAIN}_any"

PANEL_URL = "scene-setter"
PANEL_COMPONENT = "scene-setter-panel"
STATIC_URL = "/scene_setter_static"
FRONTEND_FILE = "scene-setter.js"

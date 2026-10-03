"""Names shared across the integration."""

from __future__ import annotations

DOMAIN = "scene_setter"
NAME = "Scene Setter"
VERSION = "0.4.1"  # must match manifest.json and the page (a test checks)

CONF_ROOMS = "rooms"
CONF_EXCLUDE = "exclude"
CONF_INCLUDE = "include"
# Leave apostrophes out of new scene entity ids (olis_office_dim, not oli_s_office_dim).
CONF_NO_APOSTROPHES = "no_apostrophes_in_ids"

# An entity (or its device) with this label is never saved in a scene.
IGNORE_LABEL = "scene_setter_ignore"

SERVICE_SAVE = "save"
SERVICE_RENAME = "rename"
SERVICE_DELETE = "delete"
SERVICE_CREATE = "create"
# The white scene_setter.create gives every light with colour unless told otherwise:
# the house's own setting (options flow), else this.
CONF_DEFAULT_WHITE = "default_white_k"
DEFAULT_WHITE_K = 2700

# Sent on any change the page shows.
ANY_SIGNAL = f"{DOMAIN}_any"

PANEL_URL = "scene-setter"
PANEL_COMPONENT = "scene-setter-panel"
STATIC_URL = "/scene_setter_static"
FRONTEND_FILE = "scene-setter.js"

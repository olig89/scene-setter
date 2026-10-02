"""The version is written in three places; they must agree."""

import json
import re
from pathlib import Path

from custom_components.scene_setter.const import VERSION

ROOT = Path(__file__).parents[2] / "custom_components" / "scene_setter"


def test_versions_agree():
    manifest = json.loads((ROOT / "manifest.json").read_text())["version"]
    js = (ROOT / "www" / "scene-setter.js").read_text(encoding="utf-8")
    page = re.search(r'const PAGE_VERSION = "([^"]+)"', js).group(1)
    assert manifest == VERSION == page


def test_strings_and_translation_agree():
    assert json.loads((ROOT / "strings.json").read_text()) == json.loads((ROOT / "translations" / "en.json").read_text())

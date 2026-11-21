"""Small local adapter for reading preferences and installed Pi color roles."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TOKENS = json.loads((ROOT / "design.tokens.json").read_text())
CLASSIC = {"theme": "classic", "large": False, "still": False}
OPTIONS = {
    "font": ("default", "system"),
    "spacing": ("default", "wide"),
    "background": ("default", "mint"),
}


def appearance(value):
    if (
        not isinstance(value, dict)
        or value.get("theme") not in ("classic", TOKENS["name"])
        or any(type(value.get(key)) is not bool for key in ("large", "still"))
    ):
        raise ValueError("Invalid display preferences")
    prefs = {key: value[key] for key in CLASSIC}
    for key, choices in OPTIONS.items():
        choice = value.get(key, "default")
        if choice not in choices:
            raise ValueError("Invalid reading setting")
        prefs[key] = choice
    return prefs


def read_appearance(path):
    try:
        return appearance(json.loads(path.read_text()))
    except (OSError, ValueError, UnicodeError):
        return CLASSIC.copy()


def pi_theme(builtin):
    # Derive from the installed schema's complete light theme, preserving syntax/diff roles.
    theme = json.loads(builtin.read_text())
    color = TOKENS["color"]
    theme["name"] = TOKENS["name"]
    theme["vars"].update(
        {
            key: color[role]
            for key, role in {
                "text": "ink",
                "blue": "primary",
                "teal": "primary",
                "mediumGray": "muted",
                "dimGray": "muted",
                "lightGray": "muted",
                "green": "success",
                "red": "danger",
                "yellow": "warning",
                "selectedBg": "yellow",
                "userMsgBg": "screen",
                "customMsgBg": "screen",
            }.items()
        }
    )
    theme["colors"].update(toolOutput="text", toolTitle="text", border="text")
    theme["export"].update(pageBg=color["paper"], cardBg=color["screen"])
    return theme

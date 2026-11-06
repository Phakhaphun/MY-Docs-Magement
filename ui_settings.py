"""Local persistence for recent folders and conversion preferences."""

import json
import os
from pathlib import Path
import tempfile

from pdf_to_jpg import BASE_DIR, IMAGE_FORMATS

SETTINGS_PATH = BASE_DIR / "ui_settings.json"


def load_settings(settings_path=SETTINGS_PATH):
    try:
        data = json.loads(Path(settings_path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    valid = {}
    for key in ("input_dir", "output_dir"):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            try:
                folder = Path(value).expanduser()
                if folder.is_absolute() and folder.is_dir():
                    valid[key] = str(folder.resolve())
            except (OSError, ValueError):
                pass
    for key, minimum, maximum in (("dpi", 36, 600), ("quality", 1, 100)):
        value = data.get(key)
        if type(value) is int and minimum <= value <= maximum:
            valid[key] = value
    if data.get("image_format") in IMAGE_FORMATS:
        valid["image_format"] = data["image_format"]
    if type(data.get("sidebar_expanded")) is bool:
        valid["sidebar_expanded"] = data["sidebar_expanded"]
    return valid


def save_settings(paths, settings_path=SETTINGS_PATH):
    """Atomically replace settings so an interrupted write preserves the old file."""
    settings_path = Path(settings_path)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=settings_path.parent,
            prefix=".ui_settings_", suffix=".tmp", delete=False,
        ) as stream:
            temporary = Path(stream.name)
            json.dump(paths, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        os.replace(temporary, settings_path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def load_recent_paths(settings_path=SETTINGS_PATH):
    return {key: value for key, value in load_settings(settings_path).items()
            if key in ("input_dir", "output_dir")}


def save_recent_paths(paths, settings_path=SETTINGS_PATH):
    # Keep conversion preferences when the legacy Tkinter UI saves its folders.
    settings = load_settings(settings_path)
    settings.update(paths)
    save_settings(settings, settings_path)

"""Shared JSON configuration for CLI, desktop API, and future host applications."""

import json
import math
from pathlib import Path

from .interpolation import validate_temperatures
from .geometry import validate_geometry

BASE_DIR = Path(__file__).resolve().parents[1]
CONFIG_PATH = BASE_DIR / "config.json"


def validate_settings(settings: dict) -> dict:
    """Validate a complete configuration before allocating a raster or figure."""
    if not isinstance(settings, dict):
        raise ValueError("Settings must be a JSON object.")
    result = validate_geometry(settings)
    result["temperatures"] = validate_temperatures(result.get("temperatures")).tolist()
    for key, low, high in (("grid_rows", 2, 2000), ("grid_cols", 2, 2000), ("dpi", 72, 600)):
        value = result.get(key)
        if type(value) is not int or not low <= value <= high:
            raise ValueError(f"{key} must be a whole number from {low} to {high}.")
    for key in ("color_min", "color_max", "figure_width", "figure_height"):
        value = result.get(key)
        if type(value) not in (int, float) or not math.isfinite(value):
            raise ValueError(f"{key} must be a finite number.")
    if result["color_max"] <= result["color_min"]:
        raise ValueError("Color maximum must be greater than color minimum.")
    for key in ("figure_width", "figure_height"):
        if not 3 <= result[key] <= 16:
            raise ValueError(f"{key} must be between 3 and 16 inches.")
    if result["figure_width"] * result["figure_height"] * result["dpi"] ** 2 > 25_000_000:
        raise ValueError("Image is too large. Reduce figure size or DPI (maximum 25 million pixels).")
    for key in ("show_sensor_labels", "show_sensor_markers"):
        if type(result.get(key)) is not bool:
            raise ValueError(f"{key} must be true or false.")
    if not isinstance(result.get("title"), str) or len(result["title"]) > 160:
        raise ValueError("Title must be text up to 160 characters.")
    for key, default in (("x_axis_title", "X"), ("y_axis_title", "Y")):
        value = result.setdefault(key, default)
        if not isinstance(value, str) or len(value) > 160:
            raise ValueError(f"{key} must be text up to 160 characters (or empty to hide).")
    path = result.get("output_path")
    if not isinstance(path, str) or not path.strip() or Path(path).suffix.lower() != ".png":
        raise ValueError("Output path must end in .png.")
    return result


def load_settings(path: Path = CONFIG_PATH) -> dict:
    """Read editable defaults or a saved workspace."""
    try:
        settings = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"Cannot read configuration: {exc}") from exc
    return validate_settings(settings)


def output_path(settings: dict) -> Path:
    """Resolve relative paths against the project, independent of working directory."""
    path = Path(settings["output_path"]).expanduser()
    return path if path.is_absolute() else BASE_DIR / path

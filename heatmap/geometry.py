"""Area and measurement geometry, including migration from normalized layouts."""

import math
import numpy as np


def validate_geometry(settings: dict) -> dict:
    """Add legacy defaults and validate physical coordinates and point identities."""
    result = dict(settings)
    for key in ("area_width", "area_height"):
        value = result.setdefault(key, 1.0)
        if type(value) not in (int, float) or not math.isfinite(value) or not 1e-6 <= value <= 1e9:
            raise ValueError(f"{key} must be between 0.000001 and 1,000,000,000.")
    if result.setdefault("area_unit", "relative") not in ("relative", "mm", "cm", "m"):
        raise ValueError("Area unit must be relative, mm, cm, or m.")
    width, height = result["area_width"], result["area_height"]
    names = result.setdefault("sensor_names", [f"T{i}" for i in range(1, 7)])
    if not isinstance(names, list) or len(names) != 6:
        raise ValueError("Provide six point names.")
    if any(not isinstance(name, str) or not name.strip() or len(name) > 32 for name in names):
        raise ValueError("Point names must contain 1–32 characters.")
    names = [name.strip() for name in names]
    if len(set(names)) != 6:
        raise ValueError("Point names must be unique.")
    result["sensor_names"] = names
    positions = result.setdefault("sensor_positions", [[x * width, y * height]
                                                       for y in (0, 1) for x in (0, .5, 1)])
    try:
        raw = np.asarray(positions)
        if raw.dtype.kind not in "iuf" or raw.shape != (6, 2):
            raise ValueError()
        points = raw.astype(float)
        if not np.isfinite(points).all():
            raise ValueError()
    except (TypeError, ValueError) as exc:
        raise ValueError("Provide six finite numeric X/Y positions.") from exc
    if np.any(points < 0) or np.any(points[:, 0] > width) or np.any(points[:, 1] > height):
        raise ValueError("Every point must be inside the area: 0 ≤ X ≤ width, 0 ≤ Y ≤ height.")
    normalized = points / [width, height]
    distances = np.linalg.norm(normalized[:, None] - normalized[None, :], axis=2)
    np.fill_diagonal(distances, np.inf)
    if distances.min() < 1e-9:
        raise ValueError("Measurement positions must be distinct; two points overlap.")
    if np.linalg.matrix_rank(normalized - normalized.mean(axis=0), tol=1e-9) < 2:
        raise ValueError("Points cannot all lie on one straight line. Spread them across the area.")
    result["sensor_positions"] = points.tolist()
    return result

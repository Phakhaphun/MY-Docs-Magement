"""Piecewise bilinear interpolation within the normalized sensor rectangle."""

import numpy as np


def validate_temperatures(values) -> np.ndarray:
    """Return a finite numeric 2 × 3 matrix, rejecting malformed measurements."""
    try:
        raw = np.asarray(values)
        if raw.dtype.kind not in "iuf":
            raise ValueError("Temperatures must contain only numbers.")
        data = raw.astype(float)
    except (TypeError, ValueError) as exc:
        raise ValueError("Temperatures must be a numeric 2 x 3 matrix.") from exc
    if data.shape != (2, 3):
        raise ValueError("Temperatures must have 2 rows and 3 columns.")
    if not np.isfinite(data).all():
        raise ValueError("Temperatures must be finite (no NaN or infinity).")
    return data


def interpolate(temperatures, x, y) -> np.ndarray:
    """Evaluate at broadcastable coordinates; x is rightward, y is downward."""
    data = validate_temperatures(temperatures)
    x, y = np.broadcast_arrays(np.asarray(x, dtype=float), np.asarray(y, dtype=float))
    if not (np.isfinite(x).all() and np.isfinite(y).all()):
        raise ValueError("Coordinates must be finite.")
    if np.any((x < 0) | (x > 1) | (y < 0) | (y > 1)):
        raise ValueError("Coordinates must be within [0, 1]; extrapolation is unsupported.")
    left = x <= 0.5
    column = np.where(left, 0, 1)
    u = np.where(left, 2 * x, 2 * x - 1)
    top = (1 - u) * data[0, column] + u * data[0, column + 1]
    bottom = (1 - u) * data[1, column] + u * data[1, column + 1]
    return (1 - y) * top + y * bottom


def make_grid(temperatures, rows: int = 200, cols: int = 300) -> np.ndarray:
    """Sample the full rectangle, preserving endpoints and measured bounds."""
    for name, size in (("rows", rows), ("columns", cols)):
        if type(size) is not int or not 2 <= size <= 2000:
            raise ValueError(f"Grid {name} must be a whole number from 2 to 2000.")
    return interpolate(temperatures, np.linspace(0, 1, cols)[None, :],
                       np.linspace(0, 1, rows)[:, None])

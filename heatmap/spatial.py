"""Interpolation for editable point coordinates, with no extrapolation."""

import numpy as np
from matplotlib.tri import LinearTriInterpolator, Triangulation


def rectangular_layout(points):
    """Find a complete 2 × 3 Cartesian layout regardless of input order."""
    points = np.asarray(points, dtype=float)
    xs, ys = np.unique(points[:, 0]), np.unique(points[:, 1])
    if len(xs) == 3 and len(ys) == 2:
        indices = np.array([[np.flatnonzero((points[:, 0] == x) & (points[:, 1] == y))[0]
                             for x in xs] for y in ys])
        return xs, ys, indices
    return None


def method_name(settings: dict) -> str:
    return "Bilinear" if rectangular_layout(settings["sensor_positions"]) else "Triangular linear"


def evaluate_spatial(settings: dict, x, y) -> np.ma.MaskedArray:
    """Evaluate within measured coverage; mask all unsupported locations."""
    points = np.asarray(settings["sensor_positions"], dtype=float)
    values = np.asarray(settings["temperatures"], dtype=float).ravel()
    x, y = np.broadcast_arrays(np.asarray(x, dtype=float), np.asarray(y, dtype=float))
    layout = rectangular_layout(points)
    if layout:
        xs, ys, indices = layout
        column = np.where(x <= xs[1], 0, 1)
        u = (x - xs[column]) / (xs[column + 1] - xs[column])
        v = (y - ys[0]) / (ys[1] - ys[0])
        temperatures = values[indices]
        top = (1 - u) * temperatures[0, column] + u * temperatures[0, column + 1]
        bottom = (1 - u) * temperatures[1, column] + u * temperatures[1, column + 1]
        outside = (x < xs[0]) | (x > xs[-1]) | (y < ys[0]) | (y > ys[-1])
        return np.ma.array((1 - v) * top + v * bottom, mask=outside)
    # A common scale preserves Euclidean geometry in the selected physical units.
    scale = max(settings["area_width"], settings["area_height"])
    try:
        triangulation = Triangulation(points[:, 0] / scale, points[:, 1] / scale)
        return LinearTriInterpolator(triangulation, values)(x / scale, y / scale)
    except (RuntimeError, ValueError) as exc:
        raise ValueError("Point geometry cannot be interpolated. Spread points farther apart.") from exc


def spatial_grid(settings: dict) -> np.ma.MaskedArray:
    """Sample the specified area with uncovered locations left blank."""
    return evaluate_spatial(settings,
                            np.linspace(0, settings["area_width"], settings["grid_cols"])[None, :],
                            np.linspace(0, settings["area_height"], settings["grid_rows"])[:, None])

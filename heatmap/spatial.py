"""Full-area inverse-distance estimation and legacy measured-region interpolation."""

import numpy as np
from matplotlib.tri import CubicTriInterpolator, LinearTriInterpolator, Triangulation


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
    if settings.get("estimation_method", "idw") == "idw":
        return f"IDW · power {settings.get('idw_power', 2):g}"
    if settings["estimation_method"] == "smooth":
        return "Smooth cubic"
    return "Bilinear" if rectangular_layout(settings["sensor_positions"]) else "Triangular linear"


def evaluate_idw(settings, x, y):
    """T(q) = sum(T_i / d_i**p) / sum(1 / d_i**p), exact at sensors.

    A shared length scale preserves physical Euclidean distances. Scaling weights
    by the nearest distance avoids singular/overflowing inverse powers. Chunking
    bounds temporary arrays even at the maximum 2000 by 2000 output grid.
    """
    scale = max(settings["area_width"], settings["area_height"])
    points = np.asarray(settings["sensor_positions"], dtype=float) / scale
    values = np.asarray(settings["temperatures"], dtype=float).ravel()
    x, y = np.broadcast_arrays(np.asarray(x, dtype=float), np.asarray(y, dtype=float))
    if not (np.isfinite(x).all() and np.isfinite(y).all()):
        raise ValueError("Coordinates must be finite.")
    shape = x.shape
    flat_x, flat_y = x.ravel() / scale, y.ravel() / scale
    result = np.empty(flat_x.size, dtype=float)
    for start in range(0, flat_x.size, 32768):
        end = min(start + 32768, flat_x.size)
        distances = np.hypot(flat_x[start:end, None] - points[None, :, 0],
                             flat_y[start:end, None] - points[None, :, 1])
        nearest = distances.min(axis=1)
        weights = np.divide(nearest[:, None], distances, out=np.zeros_like(distances), where=distances > 0)
        weights **= settings.get("idw_power", 2.0)
        exact = nearest == 0
        sums = weights.sum(axis=1)
        estimates = np.divide((weights * values).sum(axis=1), sums,
                              out=np.zeros(end - start, dtype=float), where=sums > 0)
        estimates[exact] = values[distances[exact].argmin(axis=1)]
        result[start:end] = np.clip(estimates, values.min(), values.max())
    outside = (x < 0) | (x > settings["area_width"]) | (y < 0) | (y > settings["area_height"])
    return np.ma.array(result.reshape(shape), mask=outside)


def evaluate_spatial(settings: dict, x, y) -> np.ma.MaskedArray:
    """Estimate the full rectangle, or mask outside sample coverage in linear mode."""
    if settings.get("estimation_method", "idw") == "idw":
        return evaluate_idw(settings, x, y)
    points = np.asarray(settings["sensor_positions"], dtype=float)
    values = np.asarray(settings["temperatures"], dtype=float).ravel()
    x, y = np.broadcast_arrays(np.asarray(x, dtype=float), np.asarray(y, dtype=float))
    if settings["estimation_method"] == "smooth":
        scale = max(settings["area_width"], settings["area_height"])
        if not (np.isfinite(x).all() and np.isfinite(y).all()):
            raise ValueError("Coordinates must be finite.")
        try:
            triangulation = Triangulation(points[:,0]/scale, points[:,1]/scale)
            interpolator = CubicTriInterpolator(triangulation, values, kind="geom")
            flat_x, flat_y = x.ravel()/scale, y.ravel()/scale
            result = np.ma.masked_all(flat_x.size)
            for start in range(0, flat_x.size, 32768):
                end = min(start+32768,flat_x.size)
                result[start:end] = interpolator(flat_x[start:end],flat_y[start:end])
            if not np.isfinite(result.compressed()).all():
                raise ValueError("Smooth interpolation is unstable for these positions. Spread points farther apart or use IDW.")
            return result.reshape(x.shape)
        except (RuntimeError, np.linalg.LinAlgError) as exc:
            raise ValueError("Point geometry cannot be smoothly interpolated. Spread points farther apart or use IDW.") from exc
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
    """Sample the selected model over the specified rectangle."""
    return evaluate_spatial(settings,
                            np.linspace(0, settings["area_width"], settings["grid_cols"])[None, :],
                            np.linspace(0, settings["area_height"], settings["grid_rows"])[:, None])

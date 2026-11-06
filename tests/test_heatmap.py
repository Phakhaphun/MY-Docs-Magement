"""Numerical guarantees, configuration failures, and real PNG/API checks."""

from copy import deepcopy
from io import BytesIO
from pathlib import Path
import unittest

import numpy as np
from matplotlib.colors import to_hex
from PIL import Image

from heatmap.interpolation import interpolate, make_grid, validate_temperatures
from heatmap.plotting import COLORS, render_png, thermal_palette
from heatmap.settings import load_settings, validate_settings
from heatmap_app import HeatmapAPI
from heatmap.spatial import evaluate_spatial, spatial_grid, method_name
from tools.test_workspace import test_workspace


class InterpolationTests(unittest.TestCase):
    def setUp(self):
        self.settings = load_settings()
        self.values = self.settings["temperatures"]

    def test_recovers_six_measurements_at_actual_positions(self):
        actual = interpolate(self.values, [[0, .5, 1]], [[0], [1]])
        np.testing.assert_allclose(actual, self.values, atol=1e-9, rtol=0)

    def test_interior_values_use_both_rectangles(self):
        self.assertAlmostEqual(float(interpolate(self.values, .25, .5)), (89.15 + 88 + 66 + 81.48) / 4)
        self.assertAlmostEqual(float(interpolate(self.values, .75, .5)), (88 + 88 + 81.48 + 83) / 4)
        a = interpolate(self.values, .5 - 1e-10, .4)
        b = interpolate(self.values, .5 + 1e-10, .4)
        self.assertAlmostEqual(float(a), float(b), places=7)

    def test_grid_sizes_bounds_and_orientation(self):
        for rows, cols in [(20, 30), (200, 300), (400, 600)]:
            grid = make_grid(self.values, rows, cols)
            self.assertEqual(grid.shape, (rows, cols))
            self.assertTrue(np.isfinite(grid).all())
            self.assertGreaterEqual(grid.min(), 66)
            self.assertLessEqual(grid.max(), 89.15)
            self.assertEqual(grid[0, 0], 89.15)
            self.assertEqual(grid[-1, 0], 66)
        self.assertFalse(np.any(np.linspace(0, 1, 300) == .5))

    def test_rejects_invalid_measurements(self):
        for values in ([[1, 2, 3]], [[1, 2], [3]], [[1, 2, 3], [4, 5, "x"]],
                       [[1, 2, 3], [4, 5, float("nan")]], [[1, 2, 3], [4, 5, float("inf")]],
                       [[True, False, True], [False, True, False]]):
            with self.subTest(values=values), self.assertRaises(ValueError):
                validate_temperatures(values)

    def test_rejects_invalid_grid_and_extrapolation(self):
        for size in (0, 1, -2, 2.5, True, 2001):
            with self.assertRaises(ValueError):
                make_grid(self.values, size, 30)
        with self.assertRaises(ValueError):
            interpolate(self.values, 1.1, 0)

    def test_palette_anchors_and_display_clipping(self):
        palette = thermal_palette()
        self.assertEqual([to_hex(palette(float(x))).upper() for x in np.linspace(0, 1, 6)], COLORS)
        self.assertNotEqual(to_hex(palette(.1)), COLORS[0])
        values = [[100, 110, 120], [-10, 20, 30]]
        np.testing.assert_allclose(interpolate(values, [[0, .5, 1]], [[0], [1]]), values)

    def test_settings_validation(self):
        cases = {"color_max": 60, "dpi": 0, "figure_width": 0, "grid_rows": 1,
                 "color_min": float("nan"), "show_sensor_labels": "true", "output_path": "bad.jpg"}
        for key, value in cases.items():
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate_settings({**self.settings, key: value})

    def test_png_deterministic_and_changes_with_input(self):
        settings = {**self.settings, "dpi": 72}
        image = render_png(settings)
        self.assertEqual(image, render_png(settings))
        with Image.open(BytesIO(image)) as png:
            self.assertEqual(png.format, "PNG")
            self.assertGreater(png.width, 400)
            self.assertGreater(png.height, 300)
            png.verify()
        changed = deepcopy(settings)
        changed["temperatures"][0][0] = 75
        self.assertNotEqual(image, render_png(changed))

    def test_desktop_export_preserves_files_and_restores_settings(self):
        with test_workspace() as temporary:
            folder = Path(temporary)
            api = HeatmapAPI(folder / "settings.json")
            settings = {**self.settings, "dpi": 72, "output_path": str(folder / "ไทย.png")}
            one = api.generate(settings, True)
            two = api.generate(settings, True)
            self.assertNotIn("error", one)
            self.assertNotIn("error", two)
            self.assertNotEqual(one["saved_path"], two["saved_path"])
            self.assertTrue(Path(one["saved_path"]).is_file())
            self.assertEqual(HeatmapAPI(folder / "settings.json").get_settings()["settings"], settings)
            self.assertIn("error", api.generate({**settings, "color_max": 0}))

    def test_old_settings_migrate_without_changing_temperatures(self):
        legacy = {key: value for key, value in self.settings.items()
                  if key not in ("area_width", "area_height", "area_unit", "sensor_names", "sensor_positions")}
        migrated = validate_settings(legacy)
        self.assertEqual(migrated["sensor_names"], [f"T{i}" for i in range(1, 7)])
        self.assertEqual(migrated["area_unit"], "relative")
        self.assertEqual(migrated["temperatures"], legacy["temperatures"])
        np.testing.assert_allclose(spatial_grid(migrated), make_grid(self.values))

    def test_physical_bilinear_unequal_spacing_and_permuted_points(self):
        settings = {**self.settings, "area_width": 300, "area_height": 200, "area_unit": "mm",
                    "sensor_positions": [[20, 10], [110, 10], [280, 10], [20, 190], [110, 190], [280, 190]]}
        settings = validate_settings(settings)
        points = np.array(settings["sensor_positions"])
        np.testing.assert_allclose(evaluate_spatial(settings, points[:, 0], points[:, 1]), np.ravel(self.values), atol=1e-9)
        self.assertAlmostEqual(float(evaluate_spatial(settings, 65, 100)), (89.15+88+66+81.48)/4)
        self.assertTrue(np.ma.getmaskarray(evaluate_spatial(settings, 0, 0)))
        order = [5, 2, 0, 4, 1, 3]
        reordered = {**settings, "sensor_positions": points[order].tolist(),
                     "temperatures": np.asarray(self.values).ravel()[order].reshape(2, 3).tolist()}
        np.testing.assert_allclose(spatial_grid(settings).compressed(), spatial_grid(reordered).compressed())

    def test_arbitrary_points_recover_measurements_and_mask_outside_hull(self):
        points = np.array([[20, 20], [130, 35], [270, 30], [30, 180], [160, 150], [280, 175]])
        values = 50 + points[:, 0] * .1 + points[:, 1] * .2
        settings = validate_settings({**self.settings, "area_width": 300, "area_height": 200, "area_unit": "mm",
                                      "sensor_positions": points.tolist(), "temperatures": values.reshape(2, 3).tolist(),
                                      "sensor_names": ["ซ้ายบน", "Center", "Right", "A", "B", "C"]})
        self.assertEqual(method_name(settings), "Triangular linear")
        recovered = evaluate_spatial(settings, points[:, 0], points[:, 1])
        self.assertFalse(np.ma.getmaskarray(recovered).any())
        np.testing.assert_allclose(recovered, values, atol=1e-9)
        self.assertAlmostEqual(float(evaluate_spatial(settings, 140, 100)), 84)
        grid = spatial_grid(settings)
        self.assertTrue(grid.mask[0, 0])
        self.assertGreaterEqual(grid.compressed().min(), values.min() - 1e-9)
        self.assertLessEqual(grid.compressed().max(), values.max() + 1e-9)
        self.assertTrue(render_png({**settings, "dpi": 72}).startswith(b"\x89PNG"))

    def test_geometry_validation(self):
        cases = [{"area_width": 0}, {"area_height": float("inf")}, {"area_unit": "inch"},
                 {"sensor_names": ["A"] * 6}, {"sensor_names": ["", "B", "C", "D", "E", "F"]},
                 {"sensor_positions": [[0, 0]] * 6},
                 {"sensor_positions": [[i / 5, i / 5] for i in range(6)]},
                 {"sensor_positions": [[-1, 0]] + self.settings["sensor_positions"][1:]},
                 {"sensor_positions": [[2, 0]] + self.settings["sensor_positions"][1:]},
                 {"sensor_positions": [[float("nan"), 0]] + self.settings["sensor_positions"][1:]}]
        for case in cases:
            with self.subTest(case=case), self.assertRaises(ValueError):
                validate_settings({**self.settings, **case})

    def test_geometry_and_names_are_persisted(self):
        with test_workspace() as folder:
            settings = {**self.settings, "area_width": 300, "area_height": 200, "area_unit": "mm",
                        "sensor_positions": [[0,0], [120,30], [300,0], [0,200], [150,200], [300,200]],
                        "sensor_names": ["Top left", "Center", "Right", "Bottom left", "B", "C"]}
            api = HeatmapAPI(folder / "settings.json")
            self.assertNotIn("error", api.generate(settings))
            self.assertEqual(HeatmapAPI(folder / "settings.json").get_settings()["settings"], settings)


if __name__ == "__main__":
    unittest.main()

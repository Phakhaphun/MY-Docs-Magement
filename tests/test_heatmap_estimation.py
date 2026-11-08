"""Full-area temperature estimates must honor measured samples and geometry."""

from copy import deepcopy
from pathlib import Path
import unittest

import numpy as np

from heatmap.settings import load_settings, validate_settings
from heatmap.spatial import evaluate_spatial, spatial_grid
from heatmap_app import HeatmapAPI
from tools.test_workspace import test_workspace


class FullAreaEstimationTests(unittest.TestCase):
    def setUp(self):
        self.settings = {**load_settings(), "estimation_method": "idw", "idw_power": 2.0,
                         "area_width": 10.0, "area_height": 10.0, "area_unit": "cm",
                         "sensor_positions": [[3, 3], [5, 3], [7, 3], [3, 7], [5, 7], [7, 7]],
                         "temperatures": [[10, 20, 30], [40, 50, 60]]}

    def test_fills_entire_area_but_keeps_sensor_values_exact(self):
        settings = validate_settings(self.settings)
        points = np.asarray(settings["sensor_positions"])
        np.testing.assert_allclose(evaluate_spatial(settings, points[:, 0], points[:, 1]), np.arange(10, 61, 10), rtol=0, atol=0)
        grid = spatial_grid(settings)
        self.assertFalse(np.ma.getmaskarray(grid).any())
        self.assertTrue(np.isfinite(grid).all())
        self.assertGreaterEqual(grid.min(), 10)
        self.assertLessEqual(grid.max(), 60)
        # At the center, paired points are equidistant with complementary values.
        self.assertAlmostEqual(float(evaluate_spatial(settings, 5, 5)), 35.0)
        self.assertTrue(np.ma.is_masked(evaluate_spatial(settings, -1, 0)))
        with self.assertRaises(ValueError):
            evaluate_spatial(settings, float("nan"), 0)

    def test_independent_corner_value_from_inverse_squared_distances(self):
        settings = validate_settings(self.settings)
        # Distances squared from (0,0): 18,34,58,58,74,98.
        expected = sum(t / d for t, d in zip([10, 20, 30, 40, 50, 60], [18, 34, 58, 58, 74, 98])) / sum(1 / d for d in [18, 34, 58, 58, 74, 98])
        corner = evaluate_spatial(settings, 0, 0)
        self.assertFalse(np.ma.is_masked(corner))
        self.assertAlmostEqual(float(corner), expected, places=10)
        # Changing the enclosing area must not distort physical X/Y distances.
        wider = {**settings, "area_width": 100}
        self.assertAlmostEqual(float(evaluate_spatial(wider, 0, 0)), expected, places=10)

    def test_physical_units_permutation_and_constant_field(self):
        base = validate_settings(self.settings)
        scaled = deepcopy(base)
        scaled.update(area_width=100, area_height=100, area_unit="mm",
                      sensor_positions=(np.asarray(base["sensor_positions"]) * 10).tolist())
        self.assertAlmostEqual(float(evaluate_spatial(base, 1, 8)), float(evaluate_spatial(scaled, 10, 80)))
        order = [5, 2, 0, 4, 1, 3]
        permuted = {**base, "sensor_positions": np.asarray(base["sensor_positions"])[order].tolist(),
                    "temperatures": np.asarray(base["temperatures"]).ravel()[order].reshape(2, 3).tolist()}
        np.testing.assert_allclose(spatial_grid(base), spatial_grid(permuted))
        constant = {**base, "temperatures": [[42, 42, 42], [42, 42, 42]]}
        np.testing.assert_allclose(spatial_grid(constant), 42)

    def test_power_validation_linear_option_and_persistence(self):
        for update in [{"idw_power": 0}, {"idw_power": True}, {"idw_power": float("nan")},
                       {"idw_power": 6}, {"estimation_method": "random"}]:
            with self.subTest(update=update), self.assertRaises(ValueError):
                validate_settings({**self.settings, **update})
        legacy = validate_settings({**self.settings, "estimation_method": "linear"})
        self.assertTrue(np.ma.is_masked(evaluate_spatial(legacy, 0, 0)))
        with test_workspace() as folder:
            path = Path(folder) / "heatmap.json"
            api = HeatmapAPI(path)
            settings = validate_settings(self.settings)
            result = api.generate(settings)
            self.assertNotIn("error", result)
            restored = HeatmapAPI(path).get_settings()["settings"]
            self.assertEqual(restored["sensor_positions"], settings["sensor_positions"])
            self.assertEqual(restored["estimation_method"], "idw")
            self.assertEqual(restored["idw_power"], 2)

    def test_idw_allows_line_layout_and_migrates_missing_options(self):
        line = {**self.settings, "sensor_positions": [[i + 1, 5] for i in range(6)]}
        self.assertFalse(np.ma.getmaskarray(spatial_grid(validate_settings(line))).any())
        legacy = dict(self.settings)
        legacy.pop("estimation_method"); legacy.pop("idw_power")
        migrated = validate_settings(legacy)
        self.assertEqual(migrated["estimation_method"], "idw")
        self.assertEqual(migrated["temperatures"], legacy["temperatures"])
        self.assertEqual(migrated["sensor_positions"], legacy["sensor_positions"])

    def test_placement_grid_defaults_validation_and_persistence(self):
        settings = validate_settings({key:value for key,value in self.settings.items() if not key.startswith("layout_")})
        self.assertTrue(settings["layout_grid_visible"])
        self.assertFalse(settings["layout_snap"])
        self.assertEqual(settings["layout_grid_spacing"], 1.0)
        for update in [{"layout_snap": "yes"}, {"layout_grid_visible": 1}, {"layout_grid_spacing": 0},
                       {"layout_grid_spacing": float("inf")}, {"layout_grid_spacing": True}]:
            with self.subTest(update=update), self.assertRaises(ValueError):
                validate_settings({**settings, **update})
        configured = {**settings, "layout_grid_visible": False, "layout_snap": True, "layout_grid_spacing": 0.25}
        with test_workspace() as folder:
            path = Path(folder) / "layout.json"
            api = HeatmapAPI(path)
            self.assertNotIn("error", api.generate(configured))
            self.assertEqual(HeatmapAPI(path).get_settings()["settings"], configured)
        np.testing.assert_allclose(spatial_grid(settings), spatial_grid(configured))

    def test_smooth_measured_region_recovers_readings_and_preserves_coverage(self):
        settings = validate_settings({**self.settings, "estimation_method": "smooth"})
        points = np.asarray(settings["sensor_positions"])
        np.testing.assert_allclose(evaluate_spatial(settings, points[:,0], points[:,1]), np.arange(10,61,10), atol=1e-8)
        self.assertTrue(np.ma.is_masked(evaluate_spatial(settings, 0, 0)))
        plane = {**settings, "temperatures": (50 + points[:,0]*.1 + points[:,1]*.2).reshape(2,3).tolist()}
        self.assertAlmostEqual(float(evaluate_spatial(plane,5,5)), 51.5, places=7)
        self.assertTrue(np.isfinite(spatial_grid(settings).compressed()).all())
        with test_workspace() as folder:
            path=Path(folder)/"smooth.json"
            self.assertNotIn("error",HeatmapAPI(path).generate(settings))
            self.assertEqual(HeatmapAPI(path).get_settings()["settings"]["estimation_method"],"smooth")
        with self.assertRaises(ValueError):
            validate_settings({**settings,"sensor_positions":[[i+1,5] for i in range(6)]})

    def test_smooth_transition_has_no_gradient_jump_between_regions(self):
        settings = validate_settings({**load_settings(), "estimation_method": "smooth",
                                     "temperatures": [[10,80,20],[40,20,70]]})
        epsilon = 1e-5
        center = float(evaluate_spatial(settings,.5,.4))
        left = (center-float(evaluate_spatial(settings,.5-epsilon,.4)))/epsilon
        right = (float(evaluate_spatial(settings,.5+epsilon,.4))-center)/epsilon
        self.assertLess(abs(left-right), .02)

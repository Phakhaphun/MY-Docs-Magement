"""Window persistence survives restart, maximization and monitor changes."""

import json
from pathlib import Path
from types import SimpleNamespace as NS
import unittest

from tools.test_workspace import test_workspace
from window_settings import WindowSettings


class WindowSettingsTests(unittest.TestCase):
    def test_invalid_settings_and_offscreen_window(self):
        with test_workspace() as folder:
            path = Path(folder) / "window.json"
            layout = WindowSettings(path)
            self.assertEqual(layout.options()["width"], 1280)
            path.write_text('{"width": true, "height": -1, "maximized": "yes"}')
            self.assertEqual(layout.options(), {"width": 1280, "height": 820, "maximized": False})
            path.write_text('{"width": 1600, "height": 1000, "x": 9000, "y": -5000}')
            options = layout.options([NS(x=0, y=0, width=1366, height=900)])
            self.assertEqual(options, {"width": 1366, "height": 900, "x": 0, "y": 0, "maximized": False})
            path.write_text('[]')
            self.assertEqual(layout.options()["height"], 820)

    def test_normal_and_maximized_bounds_round_trip_at_high_dpi(self):
        with test_workspace() as folder:
            path = Path(folder) / "window.json"
            layout = WindowSettings(path)
            normal = NS(Width=1400, Height=900, X=100, Y=50)
            form = NS(WindowState="Normal", Bounds=normal, RestoreBounds=normal, _scale=1.25, InvokeRequired=False)
            layout.window = NS(native=form)
            layout.save()
            expected = {"width": 1120, "height": 720, "x": 80, "y": 40, "maximized": False}
            self.assertEqual(WindowSettings(path).options(), expected)
            form.WindowState = "Maximized"
            form.Bounds = NS(Width=2400, Height=1350, X=0, Y=0)
            layout.save()
            expected["maximized"] = True
            self.assertEqual(WindowSettings(path).options(), expected)
            layout._maximize()
            form.WindowState = "Minimized"
            layout.save()
            self.assertTrue(json.loads(path.read_text())["maximized"])

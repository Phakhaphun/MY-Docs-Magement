"""Verify bridge routing and independent settings for the combined desktop."""

from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import Mock

from main_app import ManagementAPI, build_html
from tools.test_workspace import test_workspace


class ManagementTests(unittest.TestCase):
    def test_document_startup_does_not_load_heatmap_libraries(self):
        result = subprocess.run([sys.executable, "-c", "import sys; from main_app import ManagementAPI, build_html; api = ManagementAPI(); build_html(); api._attach(None); assert api._can_close(); assert 'numpy' not in sys.modules; assert 'matplotlib' not in sys.modules"],
                                cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_routing_does_not_mix_output_dialogs_or_settings(self):
        with test_workspace() as folder:
            api = ManagementAPI(folder)
            api._documents.choose_output = Mock(return_value={"output": "documents"})
            api._heatmap.choose_output = Mock(return_value={"output_path": "heatmap.png"})
            self.assertEqual(api.invoke("documents", "choose_output", []), {"output": "documents"})
            self.assertEqual(api.invoke("heatmap", "choose_output", []), {"output_path": "heatmap.png"})
            self.assertNotEqual(api._documents._settings_path, api._heatmap._settings_path)
            self.assertEqual(api._documents._settings_path.parent, Path(folder))
            self.assertIn("error", api.invoke("heatmap", "_busy", []))
            self.assertIn("error", api.invoke("other", "get_state", []))

    def test_close_waits_for_either_worker_and_attaches_same_window(self):
        with test_workspace() as folder:
            api = ManagementAPI(folder)
            window = Mock()
            api._attach(window)
            self.assertIs(api._documents._window, window)
            self.assertIs(api._heatmap._window, window)
            self.assertTrue(api._can_close())
            api._heatmap._busy.set()
            self.assertFalse(api._can_close())
            api._heatmap._busy.clear()
            api._documents._state["running"] = True
            self.assertFalse(api._can_close())

    def test_bundled_workspaces_are_offline_and_ready_callback_runs_once(self):
        content = build_html()
        self.assertNotIn("<!-- DOCUMENTS_HTML -->", content)
        self.assertNotIn("<!-- HEATMAP_HTML -->", content)
        self.assertNotIn("/* APP_SCRIPT */", content)
        self.assertNotIn("/* APP_STYLES */", content)
        self.assertIn('id="documents"', content)
        self.assertIn('id="heatmap"', content)
        with test_workspace() as folder:
            callback = Mock()
            api = ManagementAPI(folder, on_ready=callback)
            api.ready()
            api.ready()
            callback.assert_called_once()

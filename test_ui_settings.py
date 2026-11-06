from pathlib import Path
import tempfile
import unittest

from pdf_to_jpg import BASE_DIR
from ui_settings import load_recent_paths, save_recent_paths, load_settings, save_settings


class RecentPathTests(unittest.TestCase):
    def test_preferences_validation_and_legacy_folder_saves(self):
        with tempfile.TemporaryDirectory(dir=BASE_DIR, prefix="test_settings_") as temporary:
            folder = Path(temporary)
            config = folder / "settings.json"
            save_settings({"dpi": 300, "quality": 88, "image_format": "png"}, config)
            save_recent_paths({"input_dir": str(folder)}, config)
            self.assertEqual(load_settings(config), {"input_dir": str(folder), "dpi": 300, "quality": 88, "image_format": "png"})
            save_settings({"dpi": True, "quality": 101, "image_format": "invalid"}, config)
            self.assertEqual(load_settings(config), {})
            save_settings({"dpi": 600, "quality": 1}, config)
            self.assertEqual(load_settings(config), {"dpi": 600, "quality": 1})

    def test_round_trip_and_missing_folders(self):
        with tempfile.TemporaryDirectory(dir=BASE_DIR, prefix="test_settings_") as temporary:
            folder = Path(temporary)
            config = folder / "settings.json"
            paths = {"input_dir": str(folder), "output_dir": str(folder)}
            save_recent_paths(paths, config)
            self.assertEqual(load_recent_paths(config), paths)
            save_recent_paths({"input_dir": str(folder / "deleted"), "output_dir": str(folder)}, config)
            self.assertEqual(load_recent_paths(config), {"output_dir": str(folder)})

    def test_missing_corrupt_or_invalid_settings(self):
        with tempfile.TemporaryDirectory(dir=BASE_DIR, prefix="test_settings_") as temporary:
            config = Path(temporary) / "settings.json"
            self.assertEqual(load_recent_paths(config), {})
            for content in ('{broken', 'null', '[]', '{"input_dir": 123}', '{"output_dir": "relative"}'):
                config.write_text(content, encoding="utf-8")
                self.assertEqual(load_recent_paths(config), {})

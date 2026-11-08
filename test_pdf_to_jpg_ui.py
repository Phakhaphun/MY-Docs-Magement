"""Integration test for multi-file selection and background GUI conversion."""

from pathlib import Path
import gc
import tempfile
import time
import tkinter as tk
import unittest
from unittest.mock import patch

import pymupdf

from pdf_to_jpg import BASE_DIR
from pdf_to_jpg_ui import PDFConverterApp
from ui_settings import load_recent_paths


class UIConversionTests(unittest.TestCase):
    def tearDown(self):
        # Tk objects can form cycles after destroy(). Release them on the UI
        # thread before later background-worker tests trigger garbage collection.
        gc.collect()

    def test_multiple_files_to_selected_output(self):
        with tempfile.TemporaryDirectory(dir=BASE_DIR, prefix="test_ui_") as temporary:
            folder = Path(temporary)
            files = [folder / "first.pdf", folder / "เอกสาร.pdf"]
            for file in files:
                with pymupdf.open() as document:
                    document.new_page(width=72, height=72)
                    document.save(file)
            root = tk.Tk()
            root.withdraw()
            try:
                settings_path = folder / "settings.json"
                app = PDFConverterApp(root, settings_path=settings_path)
                with patch("pdf_to_jpg_ui.filedialog.askopenfilenames", return_value=[str(p) for p in files]) as choose:
                    app.choose_files()
                    app.choose_files()  # Selecting the same files again must not duplicate them.
                    self.assertEqual(choose.call_args.kwargs["initialdir"], str(folder))
                self.assertEqual(app.files, files)
                output = folder / "selected_output"
                output.mkdir()
                with patch("pdf_to_jpg_ui.filedialog.askdirectory", return_value=str(output)):
                    app.choose_output()
                self.assertEqual(load_recent_paths(settings_path), {
                    "input_dir": str(folder), "output_dir": str(output),
                })
                saved = settings_path.read_bytes()
                with patch("pdf_to_jpg_ui.filedialog.askopenfilenames", return_value=()):
                    app.choose_files()
                with patch("pdf_to_jpg_ui.filedialog.askdirectory", return_value=""):
                    app.choose_output()
                self.assertEqual(settings_path.read_bytes(), saved)
                app.dpi.set("72")
                with patch("pdf_to_jpg_ui.messagebox.showinfo") as complete:
                    app.start()
                    deadline = time.monotonic() + 20
                    while app.running and time.monotonic() < deadline:
                        root.update()
                        time.sleep(0.01)
                    self.assertFalse(app.running, "Background conversion did not complete")
                    complete.assert_called_once()
                for file in files:
                    image = output / f"{file.stem}_images" / "page_001.jpg"
                    self.assertTrue(image.is_file())
                    self.assertEqual(image.read_bytes()[:2], b"\xff\xd8")
                self.assertEqual(float(app.progress["value"]), 2)
                self.assertTrue(all("Done" in app.tree.set(item, "status") for item in app.tree.get_children()))
            finally:
                root.destroy()


if __name__ == "__main__":
    unittest.main()

"""Selected-page export, cancellation, and native dropped-file intake."""

from pathlib import Path
from threading import Event
import unittest
from unittest.mock import patch

import pymupdf

from doc_app import DocumentAPI
from pdf_to_jpg import ConversionCancelled, convert_pdf_to_images, parse_page_selection
from tools.test_workspace import test_workspace


class PDFWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.context = test_workspace()
        self.folder = Path(self.context.__enter__())
        self.addCleanup(lambda: self.context.__exit__(None, None, None))
        self.pdf = self.folder / "six pages.pdf"
        with pymupdf.open() as document:
            for index in range(6):
                page = document.new_page(width=72, height=72)
                page.insert_text((10, 30), str(index + 1))
            document.save(self.pdf)
        self.api = DocumentAPI(self.folder / "settings.json")
        self.api._state["output"] = str(self.folder / "output")

    def test_parser_normalizes_and_rejects_invalid_ranges(self):
        self.assertEqual(parse_page_selection(" 3, 1–2, 2, 6 ", 6), [1, 2, 3, 6])
        self.assertEqual(parse_page_selection("", 6), [1, 2, 3, 4, 5, 6])
        for value in ["0", "7", "3-1", "1,", "one", "1-2-3", None, True]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_page_selection(value, 6)

    def test_selected_pages_keep_original_numbers_and_progress(self):
        progress = []
        images = convert_pdf_to_images(self.pdf, self.folder / "images", dpi=72,
                                       page_selection="2, 4-5, 2", on_progress=lambda *args: progress.append(args))
        self.assertEqual([p.name for p in images], ["page_002.jpg", "page_004.jpg", "page_005.jpg"])
        self.assertEqual(progress, [(1, 3), (2, 3), (3, 3)])
        with self.assertRaises(ValueError):
            convert_pdf_to_images(self.pdf, self.folder / "invalid", page_selection="7")
        self.assertFalse((self.folder / "invalid").exists())

    def test_cancel_keeps_saved_images_and_can_stop_before_start(self):
        cancel = Event()
        with self.assertRaises(ConversionCancelled) as caught:
            convert_pdf_to_images(self.pdf, self.folder / "images", dpi=72,
                                  should_cancel=cancel.is_set, on_progress=lambda *_: cancel.set())
        self.assertEqual(len(caught.exception.images), 1)
        self.assertTrue(caught.exception.images[0].exists())
        with self.assertRaises(ConversionCancelled) as caught:
            convert_pdf_to_images(self.pdf, self.folder / "unstarted", should_cancel=cancel.is_set)
        self.assertEqual(caught.exception.images, [])
        self.assertFalse((self.folder / "unstarted").exists())

    def test_drop_paths_duplicate_and_busy_handling(self):
        self.api._on_drop({"dataTransfer": {"files": [{"pywebviewFullPath": str(self.pdf)},
                                                    {"pywebviewFullPath": str(self.pdf)}, {"name": "fake.pdf"}]}})
        self.assertEqual(len(self.api.get_state()["files"]), 1)

        self.api._state["running"] = True
        self.api._on_drop({"dataTransfer": {"files": [{"pywebviewFullPath": str(self.folder / "new.pdf")}]}})
        self.assertEqual(len(self.api.get_state()["files"]), 1)

    def test_print_style_page_modes_and_current_preview(self):
        file_id = self.api._add_files([self.pdf])["files"][0]["id"]
        for mode, expected in [("all", [1, 2, 3, 4, 5, 6]), ("even", [2, 4, 6]),
                               ("odd", [1, 3, 5]), ("current", [4]), ("custom", [2, 6])]:
            with self.subTest(mode=mode):
                state = self.api.set_page_selection(file_id, "2,6", mode, 4)
                self.assertNotIn("error", state)
                item = state["files"][0]
                self.assertEqual(item["page_mode"], mode)
                self.assertEqual(parse_page_selection(item["page_selection"], 6), expected)
        self.api.set_page_selection(file_id, "", "current", 4)
        self.api.preview(file_id, 2)
        self.assertEqual(self.api.get_state()["files"][0]["page_selection"], "3")
        self.api.start_conversion(72, 90)
        self.api._thread.join(10)
        self.assertEqual([p.name for p in (self.folder / "output").rglob("*.jpg")], ["page_003.jpg"])
        for mode, selection, current in [("invalid", "", 1), ("custom", "", 1), ("current", "", 7), ("current", "", True)]:
            self.assertIn("error", self.api.set_page_selection(file_id, selection, mode, current))
        single = self.folder / "single.pdf"
        with pymupdf.open() as document:
            document.new_page()
            document.save(single)
        one_id = self.api._add_files([single])["files"][-1]["id"]
        self.assertIn("error", self.api.set_page_selection(one_id, "", "even"))

    def test_per_file_selection_and_cancelled_batch_can_restart(self):
        other = self.folder / "other.pdf"
        other.write_bytes(self.pdf.read_bytes())
        state = self.api._add_files([self.pdf, other])
        first, second = [f["id"] for f in state["files"]]
        self.api.set_page_selection(first, "2, 5")
        self.api.set_page_selection(second, "6")
        self.assertIn("error", self.api.set_page_selection(first, "7"))
        entered, release = Event(), Event()
        from pdf_worker import convert_in_process as original

        def paused(*args, **kwargs):
            progress = kwargs["on_progress"]
            def on_progress(*values):
                progress(*values)
                entered.set()
                if not release.wait(10):
                    raise RuntimeError("Test timed out waiting for cancellation")
            kwargs["on_progress"] = on_progress
            return original(*args, **kwargs)

        with patch("doc_app.convert_pdf_to_images", side_effect=paused):
            self.api.start_conversion(72, 90)
            try:
                self.assertTrue(entered.wait(10))
                self.assertIn("error", self.api.set_page_selection(first, "1"))
                self.assertFalse(self.api._can_close())
                self.assertTrue(self.api.cancel_conversion()["cancelling"])
            finally:
                release.set()
                self.api._thread.join(10)
        state = self.api.get_state()
        self.assertFalse(state["running"])
        self.assertEqual(state["result"]["cancelled"], 2)
        self.assertEqual(state["result"]["images"], 1)
        self.assertEqual(state["result"]["failed"], 0)
        self.assertEqual([f["status"] for f in state["files"]], ["cancelled", "cancelled"])
        self.assertTrue(self.api._can_close())
        self.api.start_conversion(72, 90)
        self.api._thread.join(10)
        state = self.api.get_state()
        self.assertEqual(state["result"]["completed"], 2)
        self.assertEqual(state["result"]["images"], 3)
        self.assertEqual(state["result"]["cancelled"], 0)
        self.assertTrue((self.folder / "output" / "six pages_2" / "page_005.jpg").exists())


if __name__ == "__main__":
    unittest.main()

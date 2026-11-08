from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

import pymupdf

from doc_app import DocumentAPI
from pdf_to_jpg import BASE_DIR


class DocumentWorkspaceTests(unittest.TestCase):
    def test_sidebar_preference_survives_restart(self):
        self.api.set_sidebar_expanded(True)
        restarted = DocumentAPI(self.folder / "settings.json")
        self.assertTrue(restarted.get_state()["sidebar_expanded"])
        self.assertIn("error", self.api.set_sidebar_expanded("true"))
        self.api.set_sidebar_expanded(False)
        restarted = DocumentAPI(self.folder / "settings.json")
        self.assertFalse(restarted.get_state()["sidebar_expanded"])

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(dir=BASE_DIR, prefix="test_workspace_")
        self.addCleanup(self.temporary.cleanup)
        self.folder = Path(self.temporary.name)
        self.pdf = self.folder / "sample.pdf"
        with pymupdf.open() as document:
            for color in [(1, 0, 0), (0, 0, 1)]:
                page = document.new_page(width=144, height=72)
                page.draw_rect(page.rect, color=color, fill=color)
            document.save(self.pdf)
        self.api = DocumentAPI(self.folder / "settings.json")
        self.api._window = Mock()

    def test_dialog_recents_restart_cancel_and_duplicates(self):
        self.api._window.create_file_dialog.return_value = (str(self.pdf),)
        self.api.choose_files()
        self.api.choose_files()
        self.assertEqual(len(self.api.get_state()["files"]), 1)
        self.assertEqual(self.api._window.create_file_dialog.call_args.kwargs["directory"], str(self.folder))
        output = self.folder / "output"
        output.mkdir()
        self.api._window.create_file_dialog.return_value = (str(output),)
        self.api.choose_output()
        restarted = DocumentAPI(self.folder / "settings.json")
        self.assertEqual(restarted.get_state()["input"], str(self.folder))
        self.assertEqual(restarted.get_state()["output"], str(output))
        self.api._window.create_file_dialog.return_value = None
        self.api.choose_output()
        self.api.choose_files()
        self.assertEqual(self.api.get_state()["output"], str(output))
        self.assertEqual(len(self.api.get_state()["files"]), 1)

    def test_bounded_page_preview_and_invalid_requests(self):
        state = self.api._add_files([self.pdf])
        file_id = state["files"][0]["id"]
        for page in [0, 1]:
            preview = self.api.preview(file_id, page)
            self.assertEqual(preview["page"], page)
            self.assertEqual(preview["pages"], 2)
            self.assertTrue(preview["image"].startswith("data:image/jpeg;base64,"))
            self.assertLessEqual(max(preview["width"], preview["height"]), 1401)
        self.assertIn("error", self.api.preview(file_id, 2))
        self.assertIn("error", self.api.preview(file_id, -1))
        self.assertIn("error", self.api.preview(file_id, "0"))
        self.assertIn("error", self.api.preview("unregistered-id"))

    def test_batch_continues_after_corrupt_pdf_and_records_outputs(self):
        bad = self.folder / "broken.pdf"
        bad.write_bytes(b"not a PDF")
        self.api._add_files([bad, self.pdf])
        output = self.folder / "converted"
        self.api._state["output"] = str(output)
        self.api.start_conversion(72, 95)
        self.api._thread.join(timeout=15)
        state = self.api.get_state()
        self.assertFalse(state["running"])
        self.assertEqual((state["completed"], state["failed"], state["progress"]), (1, 1, 100))
        self.assertEqual([f["status"] for f in state["files"]], ["error", "done"])
        self.assertTrue((output / "sample_images" / "page_002.jpg").is_file())
        self.assertEqual(state["result"]["completed"], 1)
        self.assertEqual(state["result"]["failed"], 1)
        self.assertEqual(state["result"]["images"], 2)
        self.assertEqual(state["result"]["output"], str(output))

    def test_preferences_persist_before_conversion_and_invalid_values_are_rejected(self):
        self.api.update_settings(300, 88, "webp")
        restarted = DocumentAPI(self.folder / "settings.json")
        self.assertEqual((restarted.get_state()["dpi"], restarted.get_state()["quality"]), (300, 88))
        self.assertEqual(restarted.get_state()["image_format"], "webp")
        self.assertIn("error", self.api.update_settings(300, 88, "invalid"))
        self.assertIn("error", self.api.update_settings(0, 88))
        self.assertIn("error", self.api.update_settings(300, True))
        restarted = DocumentAPI(self.folder / "settings.json")
        self.assertEqual((restarted.get_state()["dpi"], restarted.get_state()["quality"]), (300, 88))

    def test_failed_batch_produces_completion_result(self):
        bad = self.folder / "broken.pdf"
        bad.write_bytes(b"not a PDF")
        self.api._add_files([bad])
        self.api.start_conversion(72, 90)
        self.api._thread.join(timeout=15)
        result = self.api.get_state()["result"]
        self.assertEqual((result["completed"], result["failed"], result["images"]), (0, 1, 0))
        self.assertTrue(result["id"])

    def test_empty_invalid_settings_and_remove(self):
        self.assertIn("error", self.api.start_conversion())
        state = self.api._add_files([self.pdf])
        self.assertIn("error", self.api.start_conversion(0, 95))
        self.api.remove_file(state["files"][0]["id"])
        self.assertEqual(self.api.get_state()["files"], [])
        self.api._add_files([self.pdf])
        self.api.clear_files()
        self.assertEqual(self.api.get_state()["files"], [])


if __name__ == "__main__":
    unittest.main()

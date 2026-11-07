"""Verify page contents, ordering, isolated settings, and safe PDF output."""

import hashlib
from pathlib import Path
from threading import Event
import unittest

import pymupdf

from main_app import ManagementAPI, build_html
from organize_pdf import organize_pdfs
from organizer_app import OrganizerAPI
from pdf_to_jpg import ConversionCancelled
from pdf_worker import organize_in_process
from tools.test_workspace import test_workspace


class OrganizerTests(unittest.TestCase):
    def setUp(self):
        context = test_workspace()
        self.folder = Path(context.__enter__())
        self.addCleanup(lambda: context.__exit__(None, None, None))
        self.sources = []
        for name, count in (("A", 3), ("B", 2)):
            path = self.folder / f"{name}.pdf"
            with pymupdf.open() as document:
                for number in range(1, count + 1):
                    document.new_page(width=144, height=144).insert_text((20, 40), f"{name}{number}")
                document.save(path)
            self.sources.append(path)
        self.jobs = [{"path": str(self.sources[1]), "page_selection": "2"},
                     {"path": str(self.sources[0]), "page_selection": "1, 3"}]

    def texts(self, path):
        with pymupdf.open(path) as document:
            return [page.get_text().strip() for page in document]

    def test_merge_preserves_text_selection_and_order_without_overwriting(self):
        before = [hashlib.sha256(path.read_bytes()).hexdigest() for path in self.sources]
        images = organize_pdfs(self.jobs, self.folder / "output")
        self.assertEqual(self.texts(images[0]), ["B2", "A1", "A3"])
        again = organize_pdfs(self.jobs, self.folder / "output")
        self.assertNotEqual(images[0].parent, again[0].parent)
        self.assertEqual(before, [hashlib.sha256(path.read_bytes()).hexdigest() for path in self.sources])

    def test_extract_and_split_keep_correct_pages(self):
        extracted = organize_pdfs(self.jobs, self.folder / "output", mode="extract")
        self.assertEqual([self.texts(path) for path in extracted], [["B2"], ["A1", "A3"]])
        split = organize_pdfs(self.jobs, self.folder / "output", mode="split")
        self.assertEqual([self.texts(path) for path in split], [["B2"], ["A1"], ["A3"]])
        self.assertTrue(split[-1].name.endswith("page_003.pdf"))

    def test_links_between_selected_pages_are_retained(self):
        with pymupdf.open(self.sources[0]) as document:
            document[0].insert_link({"kind": pymupdf.LINK_GOTO, "from": pymupdf.Rect(10, 10, 60, 30),
                                     "page": 2, "to": pymupdf.Point(0, 0)})
            linked = self.folder / "linked.pdf"
            document.save(linked)
        files = organize_pdfs([{"path": str(linked), "page_selection": "1,3"}], self.folder / "links")
        with pymupdf.open(files[0]) as document:
            self.assertEqual(document[0].get_links()[0]["page"], 1)

    def test_validation_before_output_and_worker_cancellation(self):
        self.jobs[0]["page_selection"] = "3"
        with self.assertRaises(ValueError):
            organize_pdfs(self.jobs, self.folder / "invalid")
        self.assertFalse((self.folder / "invalid").exists())
        self.jobs[0]["page_selection"] = "2"
        stop = Event()
        with self.assertRaises(ConversionCancelled) as caught:
            organize_in_process(self.jobs, self.folder / "cancelled", mode="split",
                                should_cancel=stop.is_set, on_progress=lambda *_: stop.set())
        self.assertEqual(len(caught.exception.images), 1)
        self.assertEqual(self.texts(caught.exception.images[0]), ["B2"])

    def test_api_reorders_validates_and_exports_in_background(self):
        api = OrganizerAPI(self.folder / "organizer.json")
        state = api._add_files(self.sources)
        ids = [file["id"] for file in state["files"]]
        self.assertIn("error", api.reorder([ids[0], ids[0]]))
        self.assertIn("error", api.reorder(None))
        self.assertIn("error", api.start("bad"))
        api.reorder(ids[::-1])
        api._state["output"] = str(self.folder / "output")
        self.assertIn("error", api.start("merge", {ids[0]: ""}))
        self.assertIn("error", api.start("merge", {ids[0]: "4", ids[1]: ""}))
        api.start("merge", {ids[0]: "1,3", ids[1]: "2"})
        api._thread.join(15)
        result = api.get_state()["result"]
        self.assertEqual(result["error"], "")
        self.assertEqual(self.texts(result["paths"][0]), ["B2", "A1", "A3"])

    def test_host_routes_are_independent_and_close_waits_for_organizer(self):
        host = ManagementAPI(self.folder)
        host._organizer._add_files(self.sources)
        self.assertEqual(len(host.invoke("organizer", "get_state", [])["files"]), 2)
        self.assertEqual(host.invoke("documents", "get_state", [])["files"], [])
        self.assertNotEqual(host._organizer._settings_path, host._documents._settings_path)
        self.assertIn("error", host.invoke("organizer", "_run", []))
        host._organizer._state["running"] = True
        self.assertFalse(host._can_close())
        host._organizer._state["running"] = False
        self.assertTrue(host._can_close())
        self.assertNotIn("<!-- ORGANIZER_HTML -->", build_html())

    def test_visual_plan_interleaves_pages_and_applies_rotation(self):
        api = OrganizerAPI(self.folder / "organizer.json")
        files = api._add_files(self.sources)["files"]
        a, b = [file["id"] for file in files]
        plan = [{"file_id": b, "page": 2, "rotation": 90}, {"file_id": a, "page": 3, "rotation": 180},
                {"file_id": b, "page": 1, "rotation": 0}]
        api._state["output"] = str(self.folder / "plan")
        api.start_plan("merge", plan)
        api._thread.join(15)
        result = api.get_state()["result"]
        self.assertEqual(result["error"], "")
        self.assertEqual(self.texts(result["paths"][0]), ["B2", "A3", "B1"])
        with pymupdf.open(result["paths"][0]) as document:
            self.assertEqual([page.rotation for page in document], [90, 180, 0])
        api.start_plan("extract", plan)
        api._thread.join(15)
        self.assertEqual([self.texts(path) for path in api.get_state()["result"]["paths"]], [["B2", "B1"], ["A3"]])

    def test_visual_plan_validation_and_bounded_thumbnail(self):
        api = OrganizerAPI(self.folder / "organizer.json")
        file_id = api._add_files(self.sources)["files"][0]["id"]
        for plan in [[], None, [{"file_id": "unknown", "page": 1}], [{"file_id": file_id, "page": True}],
                     [{"file_id": file_id, "page": 4}], [{"file_id": file_id, "page": 1, "rotation": 45}],
                     [{"file_id": file_id, "page": 1}] * 2]:
            self.assertIn("error", api.start_plan("merge", plan))
        self.assertIn("error", api.thumbnail(file_id, -1))
        self.assertIn("error", api.thumbnail(file_id, True))
        result = api.thumbnail(file_id, 0)
        self.assertTrue(result["image"].startswith("data:image/jpeg;base64,"))

    def test_reflections_match_preview_and_preserve_pdf_text(self):
        from PIL import Image, ImageChops, ImageStat
        source = self.folder / "asymmetric.pdf"
        with pymupdf.open() as document:
            page = document.new_page(width=200, height=120)
            page.draw_rect(pymupdf.Rect(10, 10, 60, 40), fill=(1, 0, 0))
            page.draw_rect(pymupdf.Rect(100, 60, 180, 100), fill=(0, 0, 1))
            page.insert_text((20, 80), "TEST")
            document.save(source)
            pixmap = page.get_pixmap()
            original = Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)
        for rotation, flip_x, flip_y in [(0, True, False), (0, False, True), (90, True, False), (270, False, True), (180, True, True)]:
            with self.subTest(rotation=rotation, flip_x=flip_x, flip_y=flip_y):
                files = organize_pdfs([{"path": str(source), "page_order": [1], "rotations": [rotation],
                                        "flips": [[flip_x, flip_y]]}], self.folder / "reflections")
                expected = original.rotate(-rotation, expand=True)
                if flip_x: expected = expected.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
                if flip_y: expected = expected.transpose(Image.Transpose.FLIP_TOP_BOTTOM)
                with pymupdf.open(files[0]) as document:
                    pixmap = document[0].get_pixmap()
                    actual = Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)
                    self.assertEqual(actual.size, expected.size)
                    self.assertLess(max(ImageStat.Stat(ImageChops.difference(actual, expected)).mean), 1.0)
                    self.assertIn("TEST", document[0].get_text())

    def test_flip_handles_existing_rotation_and_crop(self):
        from PIL import Image, ImageChops, ImageStat
        source = self.folder / "cropped.pdf"
        with pymupdf.open() as document:
            page = document.new_page(width=240, height=160)
            page.draw_rect(pymupdf.Rect(30, 30, 90, 65), fill=(1, 0, 0))
            page.draw_rect(pymupdf.Rect(120, 80, 200, 120), fill=(0, 1, 0))
            page.set_cropbox(pymupdf.Rect(20, 20, 220, 140))
            page.set_rotation(90)
            document.save(source)
            pixmap = page.get_pixmap()
            expected = Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples).transpose(Image.Transpose.FLIP_LEFT_RIGHT)
        files = organize_pdfs([{"path": str(source), "page_order": [1], "flips": [[True, False]]}], self.folder / "crop-flip")
        with pymupdf.open(files[0]) as document:
            pixmap = document[0].get_pixmap()
            actual = Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)
            self.assertEqual(actual.size, expected.size)
            self.assertLess(max(ImageStat.Stat(ImageChops.difference(actual, expected)).mean), 1.0)

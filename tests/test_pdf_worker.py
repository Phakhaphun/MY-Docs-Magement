"""Exercise the real spawned renderer, including the Windows GUI interpreter."""

import multiprocessing
from pathlib import Path
import subprocess
import sys
from threading import Event
import unittest

import pymupdf

from pdf_to_jpg import ConversionCancelled
from pdf_worker import convert_in_process
from tools.test_workspace import test_workspace


class PDFWorkerTests(unittest.TestCase):
    def setUp(self):
        context = test_workspace()
        self.folder = Path(context.__enter__())
        self.addCleanup(lambda: context.__exit__(None, None, None))
        self.pdf = self.folder / "worker.pdf"
        with pymupdf.open() as document:
            for _ in range(3):
                document.new_page(width=72, height=72)
            document.save(self.pdf)

    def test_spawned_export_formats_and_page_selection(self):
        for image_format in ("jpg", "png", "webp"):
            with self.subTest(image_format=image_format):
                images = convert_in_process(self.pdf, self.folder / image_format, dpi=72,
                                            image_format=image_format, page_selection="2-3")
                self.assertEqual([p.name for p in images], [f"page_002.{image_format}", f"page_003.{image_format}"])
                self.assertTrue(all(p.stat().st_size > 0 for p in images))
        self.assertFalse(any(p.name == "Docspace PDF renderer" for p in multiprocessing.active_children()))

    def test_spawned_cancellation_retains_first_page_and_exits(self):
        stop = Event()
        with self.assertRaises(ConversionCancelled) as caught:
            convert_in_process(self.pdf, self.folder / "images", dpi=72,
                               should_cancel=stop.is_set, on_progress=lambda *_: stop.set())
        self.assertEqual(len(caught.exception.images), 1)
        self.assertTrue(caught.exception.images[0].is_file())
        with self.assertRaises(ConversionCancelled):
            convert_in_process(self.pdf, self.folder / "unstarted", should_cancel=stop.is_set)
        self.assertFalse((self.folder / "unstarted").exists())
        self.assertFalse(any(p.name == "Docspace PDF renderer" for p in multiprocessing.active_children()))

    @unittest.skipUnless(sys.platform == "win32", "Windows GUI launcher")
    def test_pythonw_launcher_can_spawn_renderer(self):
        marker = self.folder / "result.txt"
        script = ("from pathlib import Path; from pdf_worker import convert_in_process; "
                  f"images=convert_in_process({str(self.pdf)!r}, {str(self.folder / 'gui')!r}, dpi=72); "
                  f"Path({str(marker)!r}).write_text(str(len(images)))")
        result = subprocess.run([str(Path(sys.executable).with_name("pythonw.exe")), "-c", script],
                                cwd=Path(__file__).resolve().parents[1], timeout=20)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(marker.read_text(), "3")

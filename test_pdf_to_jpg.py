"""Run with: python -m unittest -v"""

from contextlib import redirect_stderr, redirect_stdout
import io
from pathlib import Path
import tempfile
import unittest

import pymupdf

from pdf_to_jpg import BASE_DIR, convert_pdf_to_jpg, convert_pdf_to_images, main, project_path
from PIL import Image


class ConversionTests(unittest.TestCase):
    def test_image_formats_are_encoded_correctly(self):
        for extension, expected_format in (("jpg", "JPEG"), ("png", "PNG"), ("webp", "WEBP")):
            with self.subTest(format=extension):
                images = convert_pdf_to_images(self.source, self.root / "formats", dpi=72, image_format=extension)
                self.assertEqual(len(images), 2)
                for path, expected in zip(images, ((255, 0, 0), (0, 0, 255))):
                    self.assertEqual(path.suffix, "." + extension)
                    with Image.open(path) as image:
                        self.assertEqual(image.format, expected_format)
                        self.assertEqual(image.size, (144, 72))
                        pixel = image.convert("RGB").getpixel((72, 36))
                        self.assertTrue(all(abs(a - b) <= 6 for a, b in zip(pixel, expected)))
        with self.assertRaises(ValueError):
            convert_pdf_to_images(self.source, image_format="invalid")

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(dir=BASE_DIR, prefix="test_pdf_")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / "report.pdf"
        with pymupdf.open() as document:
            for color in [(1, 0, 0), (0, 0, 1)]:
                page = document.new_page(width=144, height=72)
                page.draw_rect(page.rect, fill=color, color=color)
            document.save(self.source)

    def test_multiple_pages_pixels_and_no_overwrite(self):
        images = convert_pdf_to_jpg(self.source, self.root / "out", dpi=72)
        self.assertEqual([p.name for p in images], ["page_001.jpg", "page_002.jpg"])
        for path, expected in zip(images, [(255, 0, 0), (0, 0, 255)]):
            self.assertEqual(path.read_bytes()[:2], b"\xff\xd8")
            pixmap = pymupdf.Pixmap(str(path))
            self.assertEqual((pixmap.width, pixmap.height), (144, 72))
            self.assertTrue(all(abs(a - b) <= 5 for a, b in zip(pixmap.pixel(72, 36), expected)))
        original = images[0].read_bytes()
        second = convert_pdf_to_jpg(self.source, self.root / "out", dpi=144)
        self.assertNotEqual(images[0].parent, second[0].parent)
        self.assertEqual(images[0].read_bytes(), original)

    def test_batch_continues_after_invalid_pdf(self):
        (self.root / "broken.pdf").write_bytes(b"not a PDF")
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            result = main([str(self.root), "-o", str(self.root / "out"), "--dpi", "72"])
        self.assertEqual(result, 1)
        self.assertTrue((self.root / "out" / "report_images" / "page_002.jpg").exists())

    def test_validation_and_relative_paths(self):
        self.assertEqual(project_path("input"), BASE_DIR / "input")
        with self.assertRaises(FileNotFoundError):
            convert_pdf_to_jpg(self.root / "missing.pdf")
        with self.assertRaises(ValueError):
            convert_pdf_to_jpg(self.source, dpi=0)
        with self.assertRaises(ValueError):
            convert_pdf_to_jpg(self.source, quality=101)

    def test_password_protected_pdf(self):
        locked = self.root / "locked.pdf"
        with pymupdf.open(self.source) as document:
            document.save(
                locked, encryption=pymupdf.PDF_ENCRYPT_AES_256,
                owner_pw="owner", user_pw="secret",
            )
        with self.assertRaisesRegex(ValueError, "password"):
            convert_pdf_to_jpg(locked, self.root / "out")


if __name__ == "__main__":
    unittest.main()

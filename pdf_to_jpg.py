"""Convert PDF pages to JPG, PNG, or WebP entirely in Python."""

import argparse
from pathlib import Path
import sys

BASE_DIR = Path(__file__).resolve().parent
IMAGE_FORMATS = ("jpg", "png", "webp")


def project_path(value):
    path = Path(value).expanduser()
    return (path if path.is_absolute() else BASE_DIR / path).resolve()


def convert_pdf_to_images(pdf_path, output_dir=None, *, dpi=200, quality=95, image_format="jpg", on_progress=None):
    """Return image paths, using a new folder for each conversion."""
    source = project_path(pdf_path)
    destination = project_path(output_dir if output_dir is not None else "output")
    if not source.is_file():
        raise FileNotFoundError(f"PDF file not found: {source}")
    if source.suffix.lower() != ".pdf":
        raise ValueError(f"Expected a .pdf file: {source.name}")
    if not 36 <= dpi <= 600:
        raise ValueError("DPI must be between 36 and 600")
    if not 1 <= quality <= 100:
        raise ValueError("Image quality must be between 1 and 100")
    if image_format not in IMAGE_FORMATS:
        raise ValueError("Supported image formats: jpg, png, webp")

    try:
        import pymupdf
    except ImportError as exc:
        raise RuntimeError(
            "Missing PyMuPDF. Install it with: python -m pip install -r requirements.txt"
        ) from exc

    images = []
    with pymupdf.open(source) as document:
        if document.needs_pass:
            raise ValueError("This PDF requires a password; use an unlocked copy")
        if document.page_count == 0:
            raise ValueError("The PDF contains no pages")
        destination.mkdir(parents=True, exist_ok=True)
        # mkdir prevents overwriting files, including simultaneous conversions.
        folder = destination / source.stem
        suffix = 2
        while True:
            try:
                folder.mkdir()
                break
            except FileExistsError:
                folder = destination / f"{source.stem}_{suffix}"
                suffix += 1

        try:
            for number, page in enumerate(document, start=1):
                # Bound memory use before attempting to render a very large page.
                width = int(page.rect.width * dpi / 72) + 1
                height = int(page.rect.height * dpi / 72) + 1
                if width * height > 50_000_000:
                    raise ValueError(
                        f"Page {number} exceeds 50 million pixels; lower --dpi"
                    )
                pixmap = page.get_pixmap(
                    dpi=dpi, colorspace=pymupdf.csRGB, alpha=False,
                )
                image_path = folder / f"page_{number:03d}.{image_format}"
                if image_format == "webp":
                    from PIL import Image
                    with Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples) as image:
                        image.save(image_path, format="WEBP", quality=quality, method=4)
                elif image_format == "png":
                    pixmap.save(str(image_path))
                else:
                    pixmap.save(str(image_path), jpg_quality=quality)
                images.append(image_path)
                del pixmap
                if on_progress is not None:
                    on_progress(number, document.page_count)
        except Exception as exc:
            raise RuntimeError(
                f"Conversion stopped after {len(images)} page(s). "
                f"Output folder: {folder}. {exc}"
            ) from exc
    return images


def convert_pdf_to_jpg(pdf_path, output_dir=None, *, dpi=200, quality=95, on_progress=None):
    """Backward-compatible JPG export for existing callers."""
    return convert_pdf_to_images(pdf_path, output_dir, dpi=dpi, quality=quality,
                                 image_format="jpg", on_progress=on_progress)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Convert PDF to images. Relative paths start at this script's folder.",
    )
    parser.add_argument(
        "input", nargs="?", default="input", help="PDF file or folder (default: input)",
    )
    parser.add_argument("-o", "--output", default="output", help="Output folder (default: output)")
    parser.add_argument("--dpi", type=int, default=200, help="Resolution: 36-600 (default: 200)")
    parser.add_argument("--quality", type=int, default=95, help="JPG/WebP quality: 1-100 (default: 95); PNG is lossless")
    parser.add_argument("--format", choices=IMAGE_FORMATS, default="jpg", help="Output format (default: jpg); PNG is lossless")
    args = parser.parse_args(argv)
    if not 36 <= args.dpi <= 600:
        parser.error("--dpi must be between 36 and 600")
    if not 1 <= args.quality <= 100:
        parser.error("--quality must be between 1 and 100")
    source = project_path(args.input)
    if source.is_dir():
        files = sorted(
            (path for path in source.iterdir() if path.is_file() and path.suffix.lower() == ".pdf"),
            key=lambda path: path.name.lower(),
        )
    else:
        files = [source]
    if not files:
        print(f"No PDF files found. Place PDF files in: {source}", file=sys.stderr)
        return 1
    failures = 0
    for pdf in files:
        try:
            images = convert_pdf_to_images(pdf, args.output, dpi=args.dpi, quality=args.quality, image_format=args.format)
        except Exception as exc:
            print(f"ERROR [{pdf.name}]: {exc}", file=sys.stderr)
            failures += 1
            continue
        print(f"OK [{pdf.name}]: {len(images)} {args.format.upper()} file(s) -> {images[0].parent}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())

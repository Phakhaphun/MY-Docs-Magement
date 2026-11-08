"""Optimize PDF objects and optionally recompress images, retaining document text."""
from pathlib import Path
import shutil

from pdf_to_jpg import ConversionCancelled
from export_folders import create_export_folder

PRESETS = {'lossless': None, 'balanced': (180, 150, 80), 'smallest': (120, 96, 60)}


def compress_pdf(source, output, *, preset='balanced', on_progress=None, should_cancel=None):
    import pymupdf
    if not isinstance(preset, str) or preset not in PRESETS:
        raise ValueError('Choose Lossless, Balanced, or Smallest.')
    source = Path(source).resolve()
    if source.suffix.lower() != '.pdf' or not source.is_file():
        raise ValueError('Choose a readable PDF file.')

    def check_cancel():
        if should_cancel and should_cancel():
            raise ConversionCancelled([])

    check_cancel()
    with pymupdf.open(source) as document:
        if not document.is_pdf or document.needs_pass or not document.page_count:
            raise ValueError('Use an unlocked PDF with at least one page.')
        if document.get_sigflags() > 0:
            raise ValueError('This PDF contains signature fields. Use an unsigned copy for compression.')
        if PRESETS[preset] and not hasattr(document, 'rewrite_images'):
            raise ValueError('Update PyMuPDF to 1.28.2 or newer for image compression, or choose Lossless.')
        if on_progress:
            on_progress(0, 1)
        check_cancel()
        if PRESETS[preset]:
            threshold, target, quality = PRESETS[preset]
            document.rewrite_images(dpi_threshold=threshold, dpi_target=target, quality=quality)
        check_cancel()
        folder = create_export_folder(output,source,'compressed')
        destination = folder / f'{source.stem}_compressed.pdf'
        temporary = destination.with_suffix('.partial')
        published = False
        try:
            document.save(temporary, garbage=4, deflate=True, deflate_images=True,
                          deflate_fonts=True, use_objstms=1)
            check_cancel()
            # A PDF may already be optimized. Keep a byte-for-byte copy in that case.
            if temporary.stat().st_size >= source.stat().st_size:
                shutil.copyfile(source, temporary)
            with pymupdf.open(temporary) as verified:
                if verified.page_count != document.page_count or verified.needs_pass:
                    raise RuntimeError('The compressed PDF could not be verified.')
            check_cancel()
            temporary.replace(destination)
            published = True
        finally:
            temporary.unlink(missing_ok=True)
            if not published:
                folder.rmdir()
    if on_progress:
        on_progress(1, 1)
    return [destination]

"""Add an invisible CPU OCR text layer while preserving the original PDF artwork."""
import math
import os
from pathlib import Path

from ocr_languages import DATA_DIR, require_languages
from pdf_to_jpg import ConversionCancelled
from export_folders import create_export_folder

PROFILES={'light':150,'balanced':200,'detailed':300}
MAX_PIXELS=12_000_000
MAX_EDGE=10_000


def render_scale(width,height,dpi):
    """Bound image allocation by total pixels and by the longest page edge."""
    if not all(math.isfinite(value) and value>0 for value in (width,height,dpi)):
        raise ValueError('The page has invalid dimensions.')
    return min(dpi/72,math.sqrt(MAX_PIXELS/(width*height)),MAX_EDGE/max(width,height))


def ocr_pdf(source, output, *, languages, profile='balanced', on_progress=None, should_cancel=None):
    # This is set before loading the OCR library in the isolated worker as well.
    os.environ['OMP_THREAD_LIMIT']='1'
    import pymupdf
    languages=require_languages(languages)
    if not isinstance(profile,str) or profile not in PROFILES:
        raise ValueError('Choose Light, Balanced, or Detailed processing.')
    source=Path(source).resolve()
    if source.suffix.lower()!='.pdf' or not source.is_file():
        raise ValueError('Choose a readable PDF file.')

    def check_cancel():
        if should_cancel and should_cancel():raise ConversionCancelled([])

    check_cancel()
    with pymupdf.open(source) as document:
        if not document.is_pdf or document.needs_pass or not document.page_count:
            raise ValueError('Use an unlocked PDF with at least one page.')
        if document.get_sigflags()>0:
            raise ValueError('This PDF contains signature fields. Use an unsigned copy for OCR.')
        if on_progress:on_progress(0,document.page_count)
        for index in range(document.page_count):
            check_cancel()
            page=document[index]
            # Avoid duplicate text and preserve existing searchable/vector pages.
            if not page.get_text().strip():
                rect=page.rect
                if rect.is_empty or rect.is_infinite or not all(math.isfinite(v) for v in rect):
                    raise ValueError(f'Page {index+1} has invalid dimensions.')
                scale=render_scale(rect.width,rect.height,PROFILES[profile])
                pixmap=page.get_pixmap(matrix=pymupdf.Matrix(scale,scale),colorspace=pymupdf.csRGB,alpha=False,annots=False)
                pixmap.set_dpi(max(1,round(scale*72)),max(1,round(scale*72)))
                data=pixmap.pdfocr_tobytes(language='+'.join(languages),tessdata=str(DATA_DIR))
                del pixmap
                check_cancel()
                with pymupdf.open('pdf',data) as text_document:
                    # Only copy the invisible recognized text. Keep original images,
                    # vectors, links, annotations, crop boxes and page rotations.
                    if text_document[0].get_text().strip():
                        for image in text_document[0].get_images():
                            text_document[0].delete_image(image[0])
                        page.show_pdf_page(page.rect*page.derotation_matrix,text_document,0,rotate=page.rotation)
                del data
            # The worker processes pages sequentially. Retaining decoded source
            # images only grows memory; they are not needed by later OCR pages.
            pymupdf.TOOLS.store_shrink(100)
            if on_progress:on_progress(index+1,document.page_count)
        check_cancel()
        folder=create_export_folder(output,source,'searchable')
        destination=folder/f'{source.stem}_searchable.pdf'
        temporary=destination.with_suffix('.partial')
        published=False
        try:
            document.save(temporary,garbage=3,deflate=True,use_objstms=1)
            check_cancel()
            with pymupdf.open(temporary) as verified:
                if verified.page_count!=document.page_count or verified.needs_pass:
                    raise RuntimeError('The searchable PDF could not be verified.')
            temporary.replace(destination);published=True
        finally:
            temporary.unlink(missing_ok=True)
            if not published:folder.rmdir()
    return [destination]

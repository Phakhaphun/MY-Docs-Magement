"""Combine or extract original PDF pages without rasterizing their contents."""

from pathlib import Path

from pdf_to_jpg import ConversionCancelled, parse_page_selection
from export_folders import create_export_folder


def transform_page(page, rotation, flips):
    """Rotate first, then reflect along the visible page's horizontal/vertical axes."""
    import pymupdf
    page.set_rotation((page.rotation + rotation) % 360)
    flip_x, flip_y = flips
    if not (flip_x or flip_y):
        return
    screen = pymupdf.Matrix(-1 if flip_x else 1, 0, 0, -1 if flip_y else 1,
                            page.rect.width if flip_x else 0, page.rect.height if flip_y else 0)
    # Read the PDF-to-page transform without /Rotate: for cropped rotated
    # pages MuPDF's rotated transform omits the crop's coordinate offset.
    angle = page.rotation
    page.set_rotation(0)
    pdf_to_page = page.transformation_matrix
    page.set_rotation(angle)
    to_screen = pdf_to_page * page.rotation_matrix
    matrix = to_screen * screen * ~to_screen
    unrotated = page.rotation_matrix * screen * page.derotation_matrix
    page.wrap_contents()
    content = page.read_contents()
    prefix = "q\n" + " ".join(f"{value:.8g}" for value in matrix) + " cm\n"
    xref = page.parent.get_new_xref()
    page.parent.update_object(xref, "<<>>")
    page.parent.update_stream(xref, prefix.encode("ascii") + content + b"\nQ\n")
    page.set_contents(xref)
    for link in page.get_links():
        link["from"] = link["from"] * unrotated
        page.update_link(link)
    for annotation in page.annots() or ():
        annotation.set_rect(annotation.rect * unrotated)
        annotation.update()
    for widget in page.widgets() or ():
        widget.rect = widget.rect * unrotated
        widget.update()


def organize_pdfs(jobs, output, *, mode="merge", on_progress=None, should_cancel=None):
    import pymupdf
    if mode not in ("merge", "extract", "split"):
        raise ValueError("Choose merge, extract, or split.")
    if not jobs:
        raise ValueError("Add at least one PDF.")
    validated = []
    for job in jobs:
        source = Path(job["path"])
        if source.suffix.lower() != ".pdf" or not source.is_file():
            raise ValueError(f"Not a PDF file: {source.name}")
        with pymupdf.open(source) as document:
            if document.needs_pass or document.page_count == 0:
                raise ValueError(f"{source.name}: use an unlocked PDF with at least one page.")
            pages = job.get("page_order")
            if pages is None:
                pages = parse_page_selection(job.get("page_selection", ""), document.page_count)
            if not isinstance(pages, list) or not pages or any(type(p) is not int or not 1 <= p <= document.page_count for p in pages) or len(pages) != len(set(pages)):
                raise ValueError("Invalid page order.")
            rotations = job.get("rotations", [0] * len(pages))
            if not isinstance(rotations, list) or len(rotations) != len(pages) or any(type(r) is not int or r not in (0, 90, 180, 270) for r in rotations):
                raise ValueError("Invalid page rotations.")
            flips = job.get("flips", [[False, False] for _ in pages])
            if not isinstance(flips, list) or len(flips) != len(pages) or any(not isinstance(f, list) or len(f) != 2 or any(type(value) is not bool for value in f) for f in flips):
                raise ValueError("Invalid page reflections.")
        validated.append((source, pages, rotations, flips))
    saved = []
    def check_cancel():
        if should_cancel and should_cancel():
            raise ConversionCancelled(saved)
    check_cancel()
    root = Path(output)
    sources = list(dict.fromkeys(source.resolve() for source, _, _, _ in validated))
    folder = root
    source_folders = {}
    if mode == "merge":
        folder = create_export_folder(root,sources[0],"merged",additional_sources=len(sources)-1)
    total = sum(len(pages) for _, pages, _, _ in validated)
    done = 0

    def save(document, filename):
        check_cancel()
        destination = folder / filename
        temporary = destination.with_suffix(".partial")
        try:
            document.save(temporary, garbage=3, deflate=True)
            temporary.replace(destination)
            saved.append(destination)
        finally:
            temporary.unlink(missing_ok=True)

    merged = pymupdf.open() if mode == "merge" else None
    try:
        for file_index, (source, pages, rotations, flips) in enumerate(validated, 1):
            check_cancel()
            if mode != "merge":
                key = source.resolve()
                if key not in source_folders:
                    source_folders[key] = create_export_folder(root,source,"split" if mode == "split" else "extracted")
                folder = source_folders[key]
            with pymupdf.open(source) as document, pymupdf.open() as extracted:
                if mode == "split":
                    for number, rotation, reflection in zip(pages, rotations, flips):
                        check_cancel()
                        with pymupdf.open() as single:
                            single.insert_pdf(document, from_page=number - 1, to_page=number - 1)
                            transform_page(single[0], rotation, reflection)
                            save(single, f"{file_index:03d}_{source.stem}_page_{number:03d}.pdf")
                        done += 1
                        if on_progress:
                            on_progress(done, total)
                else:
                    # Copy the chosen document in one operation. This preserves
                    # links between selected pages and reuses shared resources.
                    document.select([number - 1 for number in pages])
                    for page, rotation, reflection in zip(document, rotations, flips):
                        transform_page(page, rotation, reflection)
                    target = merged if mode == "merge" else extracted
                    target.insert_pdf(document)
                    done += len(pages)
                    if on_progress:
                        on_progress(done, total)
                if mode == "extract":
                    save(extracted, f"{file_index:03d}_{source.stem}.pdf")
        if merged is not None:
            save(merged, "merged.pdf")
    except ConversionCancelled:
        raise
    except Exception as exc:
        raise RuntimeError(f"Saved {len(saved)} PDF(s) in {folder}. {exc}") from exc
    finally:
        if merged is not None:
            merged.close()
    return saved

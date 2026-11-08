"""Run CPU-heavy PDF rendering outside the desktop bridge's Python process."""

import multiprocessing
import os
from pathlib import Path

from pdf_to_jpg import ConversionCancelled


def _render(connection, cancelled, operation, source, output, options):
    try:
        if operation == "ocr":
            os.environ["OMP_THREAD_LIMIT"] = "1"
        # Keep interactive desktop applications ahead of a background conversion.
        if os.name == "nt":
            import ctypes
            kernel = ctypes.windll.kernel32
            kernel.GetCurrentProcess.restype = ctypes.c_void_p
            kernel.SetPriorityClass.argtypes = [ctypes.c_void_p, ctypes.c_uint]
            kernel.SetPriorityClass(kernel.GetCurrentProcess(), 0x00004000)  # BELOW_NORMAL_PRIORITY_CLASS
        from pdf_to_jpg import convert_pdf_to_images

        def progress(done, total):
            connection.send(("progress", done, total))
            # Acknowledge progress before continuing so Cancel can stop at the
            # page boundary, even if a very small PDF finishes faster than polling.
            if connection.recv() != "continue":
                cancelled.set()

        if operation == "image-pdf":
            from images_to_pdf import images_to_pdf
            images = images_to_pdf(source, output, **options, on_progress=progress, should_cancel=cancelled.is_set)
        elif operation == "ocr":
            from ocr_pdf import ocr_pdf
            images = ocr_pdf(source, output, **options, on_progress=progress, should_cancel=cancelled.is_set)
        elif operation == "compress":
            from compress_pdf import compress_pdf
            images = compress_pdf(source, output, **options, on_progress=progress, should_cancel=cancelled.is_set)
        elif operation == "organize":
            from organize_pdf import organize_pdfs
            images = organize_pdfs(source, output, **options, on_progress=progress, should_cancel=cancelled.is_set)
        else:
            images = convert_pdf_to_images(source, output, **options,
                                           on_progress=progress, should_cancel=cancelled.is_set)
        connection.send(("done", [str(path) for path in images]))
    except ConversionCancelled as exc:
        connection.send(("cancelled", [str(path) for path in exc.images]))
    except Exception as exc:
        if operation == "image-pdf":
            connection.send(("error", str(exc), [str(path) for path in getattr(exc,"images",[])]))
        else:
            connection.send(("error", str(exc)))
    finally:
        connection.close()


def convert_in_process(source, output, *, on_progress=None, should_cancel=None, **options):
    """Keep the converter's API while isolating rendering, encoding and the GIL."""
    return _run_in_process("convert", str(source), output, options, on_progress, should_cancel)


def organize_in_process(jobs, output, *, mode, on_progress=None, should_cancel=None):
    return _run_in_process("organize", jobs, output, {"mode": mode}, on_progress, should_cancel)


def compress_in_process(source, output, *, preset, on_progress=None, should_cancel=None):
    return _run_in_process("compress", str(source), output, {"preset": preset}, on_progress, should_cancel)


def ocr_in_process(source, output, *, languages, profile, on_progress=None, should_cancel=None):
    return _run_in_process("ocr", str(source), output, {"languages": languages, "profile": profile}, on_progress, should_cancel)


def images_in_process(jobs, output, *, on_progress=None, should_cancel=None, **options):
    return _run_in_process("image-pdf", jobs, output, options, on_progress, should_cancel)


def _run_in_process(operation, source, output, options, on_progress, should_cancel):
    context = multiprocessing.get_context("spawn")
    parent, child = context.Pipe()
    cancelled = context.Event()
    process = context.Process(target=_render, args=(child, cancelled, operation, source, str(output), options),
                              name="Docspace PDF renderer", daemon=True)
    started = False
    try:
        process.start()
        started = True
        child.close()
        while True:
            if should_cancel and should_cancel():
                cancelled.set()
            if not parent.poll(.025):
                if not process.is_alive():
                    raise RuntimeError(f"PDF renderer stopped unexpectedly (exit code {process.exitcode}).")
                continue
            try:
                message = parent.recv()
            except EOFError as exc:
                raise RuntimeError("PDF renderer disconnected before reporting its result.") from exc
            if message[0] == "progress":
                if on_progress:
                    on_progress(message[1], message[2])
                if should_cancel and should_cancel():
                    cancelled.set()
                parent.send("cancel" if cancelled.is_set() else "continue")
            elif message[0] == "done":
                return [Path(path) for path in message[1]]
            elif message[0] == "cancelled":
                raise ConversionCancelled([Path(path) for path in message[1]])
            elif message[0] == "error":
                error = RuntimeError(message[1])
                if len(message)>2:
                    error.images = [Path(path) for path in message[2]]
                raise error
    finally:
        parent.close()
        child.close()
        if started:
            process.join(2)
            if process.is_alive():
                process.terminate()
                process.join(2)
            process.close()

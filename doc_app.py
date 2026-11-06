"""Document workspace: HTML/CSS desktop interface and Python application API."""

import base64
from copy import deepcopy
import os
from pathlib import Path
from threading import RLock, Thread
from uuid import uuid4

from pdf_to_jpg import BASE_DIR, IMAGE_FORMATS, convert_pdf_to_images
from ui_settings import SETTINGS_PATH, load_settings, save_settings


class DocumentAPI:
    def __init__(self, settings_path=SETTINGS_PATH, on_ready=None):
        self._window = None
        self._on_ready = on_ready
        self._ready = False
        self._settings_path = Path(settings_path)
        self._recent = load_settings(self._settings_path)
        self._lock = RLock()
        self._files = []
        self._state = {
            "output": self._recent.get("output_dir", str(BASE_DIR / "output")),
            "input": self._recent.get("input_dir", str(BASE_DIR / "input")),
            "running": False, "progress": 0, "message": "Add PDFs to start your workspace.",
            "warning": "", "completed": 0, "failed": 0,
            "dpi": self._recent.get("dpi", 200), "quality": self._recent.get("quality", 95),
            "image_format": self._recent.get("image_format", "jpg"),
            "sidebar_expanded": self._recent.get("sidebar_expanded", False),
            "result": None,
        }

    def _remember(self):
        try:
            save_settings(self._recent, self._settings_path)
        except OSError as exc:
            self._state["warning"] = f"Could not save settings: {exc}"

    def update_settings(self, dpi, quality, image_format=None):
        with self._lock:
            if self._state["running"]:
                return {"error": "Wait for conversion to finish before changing settings."}
            if type(dpi) is not int or not 36 <= dpi <= 600 or type(quality) is not int or not 1 <= quality <= 100:
                return {"error": "Use DPI 36–600 and quality 1–100 (whole numbers)."}
            image_format = self._state["image_format"] if image_format is None else image_format
            if image_format not in IMAGE_FORMATS:
                return {"error": "Choose JPG, PNG, or WebP."}
            self._state.update(dpi=dpi, quality=quality, image_format=image_format)
            self._recent.update(dpi=dpi, quality=quality, image_format=image_format)
            self._remember()
            return self.get_state()

    def get_state(self):
        with self._lock:
            return {**deepcopy(self._state), "files": deepcopy(self._files)}

    def ready(self):
        """Called once the UI has rendered its initial settings and connected."""
        with self._lock:
            if self._ready:
                return {"ok": True}
            self._ready = True
        try:
            if self._on_ready:
                self._on_ready()
        except Exception:
            with self._lock:
                self._ready = False
            raise
        # Warm the PDF engine after the UI is usable, rather than blocking startup.
        def warm_pdf_engine():
            try:
                import pymupdf
            except Exception:
                pass  # A file operation reports the error if the engine is unavailable.
        Thread(target=warm_pdf_engine, daemon=True).start()
        return {"ok": True}

    def set_sidebar_expanded(self, expanded):
        with self._lock:
            if type(expanded) is not bool:
                return {"error": "Menu state must be true or false."}
            self._state["sidebar_expanded"] = expanded
            self._recent["sidebar_expanded"] = expanded
            self._remember()
            return {"sidebar_expanded": expanded}

    def _add_files(self, paths):
        import pymupdf
        with self._lock:
            if self._state["running"]:
                return self.get_state()
            for name in paths:
                path = Path(name).resolve()
                if any(item["path"] == str(path) for item in self._files):
                    continue
                item = {"id": uuid4().hex, "name": path.name, "path": str(path),
                        "pages": 0, "size": 0, "status": "ready", "detail": "Ready", "output": ""}
                try:
                    if path.suffix.lower() != ".pdf":
                        raise ValueError("Please select a PDF file.")
                    item["size"] = path.stat().st_size
                    with pymupdf.open(path) as document:
                        if document.needs_pass:
                            raise ValueError("Password-protected PDF. Please use an unlocked copy.")
                        if document.page_count == 0:
                            raise ValueError("This PDF has no pages.")
                        item["pages"] = document.page_count
                except Exception as exc:
                    item.update(status="error", detail=str(exc))
                self._files.append(item)
            if paths:
                self._state["input"] = str(Path(paths[-1]).resolve().parent)
                self._recent["input_dir"] = self._state["input"]
                self._remember()
            self._state["message"] = f"{len(self._files)} PDF(s) in your workspace."
            self._state["progress"] = 0
            return self.get_state()

    def choose_files(self):
        import webview
        with self._lock:
            if self._state["running"]:
                return self.get_state()
            folder = self._state["input"]
        if not Path(folder).is_dir():
            folder = str(BASE_DIR)
        paths = self._window.create_file_dialog(
            webview.FileDialog.OPEN, directory=folder, allow_multiple=True,
            file_types=("PDF files (*.pdf)",),
        )
        return self._add_files(paths) if paths else self.get_state()

    def choose_output(self):
        import webview
        with self._lock:
            if self._state["running"]:
                return self.get_state()
            folder = self._state["output"]
        paths = self._window.create_file_dialog(
            webview.FileDialog.FOLDER,
            directory=folder if Path(folder).is_dir() else str(BASE_DIR),
        )
        if paths:
            with self._lock:
                self._state["output"] = str(Path(paths[0]).resolve())
                self._recent["output_dir"] = self._state["output"]
                self._remember()
        return self.get_state()

    def remove_file(self, file_id):
        with self._lock:
            if not self._state["running"]:
                self._files = [item for item in self._files if item["id"] != file_id]
                self._state.update(progress=0, message=f"{len(self._files)} PDF(s) in your workspace.")
            return self.get_state()

    def clear_files(self):
        with self._lock:
            if not self._state["running"]:
                self._files.clear()
                self._state.update(progress=0, message="Add PDFs to start your workspace.")
            return self.get_state()

    def preview(self, file_id, page=0):
        try:
            import pymupdf
            with self._lock:
                item = next((deepcopy(f) for f in self._files if f["id"] == file_id), None)
            if item is None:
                raise ValueError("Select a PDF from your workspace.")
            if isinstance(page, bool) or not isinstance(page, int):
                raise ValueError("Invalid page number.")
            with pymupdf.open(item["path"]) as document:
                if document.needs_pass:
                    raise ValueError("This PDF requires a password.")
                if not 0 <= page < document.page_count:
                    raise ValueError("Page number is outside this document.")
                pdf_page = document[page]
                longest = max(pdf_page.rect.width, pdf_page.rect.height)
                if longest <= 0:
                    raise ValueError("Invalid page dimensions.")
                scale = min(2, 1400 / longest)
                pixmap = pdf_page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), colorspace=pymupdf.csRGB, alpha=False)
                data = base64.b64encode(pixmap.tobytes("jpg", jpg_quality=85)).decode("ascii")
                return {"image": f"data:image/jpeg;base64,{data}", "page": page,
                        "pages": document.page_count, "width": pixmap.width, "height": pixmap.height}
        except Exception as exc:
            return {"error": str(exc)}

    def start_conversion(self, dpi=None, quality=None, image_format=None):
        with self._lock:
            if self._state["running"]:
                return {"error": "A conversion is already running."}
            if not self._files:
                return {"error": "Add at least one PDF first."}
            dpi = self._state["dpi"] if dpi is None else dpi
            quality = self._state["quality"] if quality is None else quality
            if type(dpi) is not int or not 36 <= dpi <= 600 or type(quality) is not int or not 1 <= quality <= 100:
                return {"error": "Use DPI 36–600 and quality 1–100 (whole numbers)."}
            settings_result = self.update_settings(dpi, quality, image_format)
            if "error" in settings_result:
                return settings_result
            image_format = self._state["image_format"]
            for item in self._files:
                item.update(status="waiting", detail="Waiting", output="")
            self._state.update(running=True, progress=0, completed=0, failed=0, result=None, message="Starting conversion…")
            jobs = deepcopy(self._files)
            output = self._state["output"]
            self._thread = Thread(target=self._convert, args=(jobs, output, dpi, quality, image_format), daemon=True)
            self._thread.start()
            return self.get_state()

    def _convert(self, jobs, output, dpi, quality, image_format):
        image_count = 0
        try:
            for index, job in enumerate(jobs):
                def update_progress(done, total):
                    with self._lock:
                        self._state["progress"] = (index + done / total) / len(jobs) * 100
                        self._state["message"] = f"{job['name']} · page {done} of {total}"

                with self._lock:
                    item = next(f for f in self._files if f["id"] == job["id"])
                    item.update(status="working", detail="Converting…")
                    self._state["message"] = f"Converting {job['name']}…"
                try:
                    images = convert_pdf_to_images(job["path"], output, dpi=dpi, quality=quality,
                                                   image_format=image_format, on_progress=update_progress)
                except Exception as exc:
                    with self._lock:
                        item.update(status="error", detail=str(exc))
                        self._state["failed"] += 1
                else:
                    with self._lock:
                        item.update(status="done", detail=f"{len(images)} images saved", output=str(images[0].parent))
                        self._state["completed"] += 1
                        image_count += len(images)
                with self._lock:
                    self._state["progress"] = (index + 1) / len(jobs) * 100
        finally:
            with self._lock:
                self._state["running"] = False
                self._state["message"] = f"Finished · {self._state['completed']} succeeded, {self._state['failed']} failed"
                self._state["result"] = {
                    "id": uuid4().hex, "completed": self._state["completed"],
                    "failed": self._state["failed"], "images": image_count, "output": output,
                    "image_format": image_format,
                }

    def open_output(self):
        try:
            folder = Path(self._state["output"])
            if not folder.is_dir():
                return {"error": "The output folder will be created when you convert."}
            os.startfile(str(folder))
            return {"ok": True}
        except OSError as exc:
            return {"error": str(exc)}

    def _can_close(self):
        with self._lock:
            if self._state["running"]:
                self._state["warning"] = "Please wait for conversion to finish before closing."
                return False
        return True


def build_html():
    assets = BASE_DIR / "ui"
    logo = (assets / "assets" / "docspace.svg").read_text(encoding="utf-8")
    return (assets / "index.html").read_text(encoding="utf-8").replace(
        "/* APP_STYLES */", (assets / "styles.css").read_text(encoding="utf-8"),
    ).replace("/* APP_SCRIPT */", (assets / "app.js").read_text(encoding="utf-8")).replace(
        "<!-- APP_LOGO -->", logo,
    ).replace("APP_FAVICON", base64.b64encode(logo.encode("utf-8")).decode("ascii"))


def main():
    import argparse
    import json
    import time
    parser = argparse.ArgumentParser(description="Docspace desktop workspace")
    parser.add_argument("--startup-channel", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    started = time.perf_counter()

    def report(status, message):
        if args.startup_channel is not None:
            data = {"status": status, "message": message, "seconds": round(time.perf_counter() - started, 3)}
            temporary = args.startup_channel.with_suffix(".tmp")
            temporary.write_text(json.dumps(data), encoding="utf-8")
            for attempt in range(4):
                try:
                    temporary.replace(args.startup_channel)
                    break
                except PermissionError:
                    if attempt == 3:
                        raise
                    time.sleep(.02 * (attempt + 1))

    try:
        report("loading", "Preparing the application window…")
        run_desktop(report)
    except Exception:
        try:
            report("error", "Docspace could not start. Check the startup log for details.")
        except OSError:
            pass
        raise


def run_desktop(report=lambda status, message: None):
    import webview
    def on_ready():
        window.show()
        report("ready", "Your workspace is ready.")

    api = DocumentAPI(on_ready=on_ready)
    report("loading", "Restoring your settings…")
    window = webview.create_window(
        "Docspace · PDF to Image", html=build_html(), js_api=api,
        width=900, height=620, min_size=(780, 540), background_color="#f3f8fd",
        hidden=True,
    )
    api._window = window
    window.events.closing += api._can_close
    report("loading", "Loading your document workspace…")
    webview.start(gui="edgechromium", storage_path=str(BASE_DIR / ".webview"),
                  icon=str(BASE_DIR / "ui" / "assets" / "docspace.ico"))


if __name__ == "__main__":
    main()

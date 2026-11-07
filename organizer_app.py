"""Independent workspace for assembling and extracting PDF pages."""

from copy import deepcopy
from pathlib import Path
from threading import RLock, Thread
import base64
from uuid import uuid4

from doc_app import DocumentAPI
from pdf_to_jpg import BASE_DIR, ConversionCancelled, parse_page_selection
from pdf_worker import organize_in_process


class OrganizerAPI(DocumentAPI):
    def __init__(self, settings_path=None):
        super().__init__(settings_path or BASE_DIR / "organizer_settings.json")
        self._state["message"] = "Add PDFs to arrange their pages."
        self._pdf_lock = RLock()

    def _add_files(self, paths):
        with self._pdf_lock:
            return super()._add_files(paths)

    def preview(self, file_id, page=0):
        with self._pdf_lock:
            return super().preview(file_id, page)

    def thumbnail(self, file_id, page):
        import pymupdf
        with self._lock:
            item = next((dict(f) for f in self._files if f["id"] == file_id), None)
        if item is None or type(page) is not int or not 0 <= page < item["pages"]:
            return {"error": "Page not found."}
        try:
            with self._pdf_lock, pymupdf.open(item["path"]) as document:
                pdf_page = document[page]
                scale = min(1, 280 / max(pdf_page.rect.width, pdf_page.rect.height))
                pixmap = pdf_page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False, colorspace=pymupdf.csRGB)
                data = base64.b64encode(pixmap.tobytes("jpg", jpg_quality=85)).decode("ascii")
                return {"image": "data:image/jpeg;base64," + data}
        except Exception as exc:
            return {"error": str(exc)}

    def start_plan(self, mode, pages):
        """Validate a visual page plan before passing paths to the worker."""
        with self._lock:
            if self._state["running"]:
                return {"error": "An operation is already running."}
            if mode not in ("merge", "extract", "split") or not isinstance(pages, list) or not pages:
                return {"error": "Choose at least one page before saving."}
            lookup = {f["id"]: f for f in self._files}
            seen, entries = set(), []
            for entry in pages:
                if not isinstance(entry, dict):
                    return {"error": "Invalid page data."}
                file_id, number, rotation = entry.get("file_id"), entry.get("page"), entry.get("rotation", 0)
                flip_x, flip_y = entry.get("flip_x", False), entry.get("flip_y", False)
                item = lookup.get(file_id) if isinstance(file_id, str) else None
                if not item or type(number) is not int or not 1 <= number <= item["pages"] or type(rotation) is not int or rotation not in (0, 90, 180, 270) or type(flip_x) is not bool or type(flip_y) is not bool:
                    return {"error": "Invalid page or transform."}
                if (file_id, number) in seen:
                    return {"error": "Duplicate pages are not allowed."}
                seen.add((file_id, number))
                entries.append((item, number, rotation, flip_x, flip_y))
            if mode == "extract":
                order = list(dict.fromkeys(entry[0]["id"] for entry in entries))
                entries = [entry for file_id in order for entry in entries if entry[0]["id"] == file_id]
            jobs = []
            for item, number, rotation, flip_x, flip_y in entries:
                if not jobs or jobs[-1]["id"] != item["id"]:
                    jobs.append({"id": item["id"], "path": item["path"], "page_order": [], "rotations": [], "flips": []})
                jobs[-1]["page_order"].append(number)
                jobs[-1]["rotations"].append(rotation)
                jobs[-1]["flips"].append([flip_x, flip_y])
            return self._launch(jobs, mode)

    def _launch(self, jobs, mode):
        for item in self._files:
            item.update(status="waiting", detail="Waiting", output="")
        self._cancel.clear()
        self._state.update(running=True, cancelling=False, progress=0, result=None, message="Organizing PDF pages…")
        self._thread = Thread(target=self._run, args=(jobs, self._state["output"], mode), daemon=True)
        self._thread.start()
        return self.get_state()

    def cancel_conversion(self):
        with self._lock:
            super().cancel_conversion()
            if self._state["running"]:
                self._state["message"] = "Cancelling… waiting for the current operation."
            return self.get_state()

    def _can_close(self):
        with self._lock:
            if self._state["running"]:
                self._state["message"] = "Cancel or wait for the operation to finish before closing."
                return False
            return True

    def reorder(self, file_ids):
        with self._lock:
            if self._state["running"]:
                return {"error": "Wait for the operation to finish before reordering."}
            if not isinstance(file_ids, list) or not all(isinstance(value, str) for value in file_ids):
                return {"error": "Invalid file order."}
            if len(file_ids) != len(self._files) or set(file_ids) != {f["id"] for f in self._files}:
                return {"error": "File order does not match the current queue."}
            lookup = {f["id"]: f for f in self._files}
            self._files = [lookup[file_id] for file_id in file_ids]
            self._state["result"] = None
            return self.get_state()

    def start(self, mode="merge", selections=None):
        with self._lock:
            if self._state["running"]:
                return {"error": "An operation is already running."}
            if mode not in ("merge", "extract", "split") or not self._files:
                return {"error": "Add PDFs and choose an output mode first."}
            if selections is None:
                selections = {f["id"]: f["page_selection"] for f in self._files}
            if not isinstance(selections, dict) or set(selections) != {f["id"] for f in self._files}:
                return {"error": "Page selections do not match the current files."}
            for item in self._files:
                try:
                    if not item["pages"]:
                        raise ValueError("This file cannot be read. Remove it from the queue.")
                    parse_page_selection(selections[item["id"]], item["pages"])
                except ValueError as exc:
                    return {"error": f"{item['name']}: {exc}"}
            for item in self._files:
                item.update(page_selection=selections[item["id"]].strip(), status="waiting", detail="Waiting", output="")
            jobs = deepcopy(self._files)
            return self._launch(jobs, mode)

    def _run(self, jobs, output, mode):
        saved, error, cancelled = [], "", False
        def progress(done, total):
            with self._lock:
                self._state["progress"] = done / total * 100
                if not self._cancel.is_set():
                    self._state["message"] = f"Processed {done} of {total} pages"
        try:
            saved = organize_in_process(jobs, output, mode=mode, on_progress=progress, should_cancel=self._cancel.is_set)
        except ConversionCancelled as exc:
            saved, cancelled = exc.images, True
        except Exception as exc:
            error = str(exc)
        finally:
            with self._lock:
                status = "error" if error else "cancelled" if cancelled else "done"
                message = error or ("Cancelled" if cancelled else f"Saved {len(saved)} PDF(s)")
                for item in self._files:
                    item.update(status=status, detail=message)
                self._state.update(running=False, cancelling=False, message=message,
                                   result={"id": uuid4().hex, "paths": [str(p) for p in saved],
                                           "cancelled": cancelled, "error": error, "mode": mode})


def build_html():
    directory = BASE_DIR / "organizer_ui"
    return (directory / "index.html").read_text(encoding="utf-8").replace(
        "/* APP_STYLES */", (directory / "styles.css").read_text(encoding="utf-8")
    ).replace("/* APP_SCRIPT */", (directory / "app.js").read_text(encoding="utf-8"))

"""Desktop adapter. A future Docspace host can mount HeatmapAPI and the UI separately."""

import base64
import json
import os
from pathlib import Path
from threading import Event, RLock

BASE_DIR = Path(__file__).resolve().parent


class HeatmapAPI:
    """Small PyWebView bridge; interpolation and rendering live in heatmap/."""

    def __init__(self, settings_path=None):
        from heatmap.settings import load_settings
        self._window = None
        self._settings_path = Path(settings_path) if settings_path else BASE_DIR / "heatmap_settings.json"
        self._settings = load_settings()
        self._warning = ""
        self._lock = RLock()
        self._last_output = None
        self._busy = Event()
        if self._settings_path.exists():
            try:
                self._settings = load_settings(self._settings_path)
            except ValueError:
                self._warning = "Saved settings could not be loaded. Using config.json defaults."

    def get_settings(self):
        with self._lock:
            return {"settings": dict(self._settings), "warning": self._warning}

    def defaults(self):
        from heatmap.settings import load_settings
        return {"settings": load_settings()}

    def generate(self, settings, export=False):
        """Preview or save a validated snapshot, serializing rendering operations."""
        self._busy.set()
        try:
            from heatmap.settings import output_path, validate_settings
            from heatmap.plotting import render_png
            from heatmap.spatial import method_name
            settings = validate_settings(settings)
            if type(export) is not bool:
                raise ValueError("Export must be true or false.")
            with self._lock:
                preview = render_png(settings, preview=True)
                result = {"image": "data:image/png;base64," + base64.b64encode(preview).decode("ascii")}
                values = sum(settings["temperatures"], [])
                result.update(minimum=min(values), maximum=max(values), mean=sum(values) / 6,
                              spread=max(values) - min(values), method=method_name(settings))
                result["estimated"] = settings["estimation_method"] == "idw"
                if export:
                    image = render_png(settings)
                    path = output_path(settings)
                    path.parent.mkdir(parents=True, exist_ok=True)
                    # Preserve previous experiments; CLI retains the configured fixed filename.
                    destination = path
                    index = 2
                    while True:
                        try:
                            with destination.open("xb") as stream:
                                stream.write(image)
                            break
                        except FileExistsError:
                            destination = path.with_name(f"{path.stem}_{index}.png")
                            index += 1
                    self._last_output = destination
                    result["saved_path"] = str(destination)
                self._settings = settings
                try:
                    temporary = self._settings_path.with_suffix(".tmp")
                    temporary.write_text(json.dumps(settings, indent=2, ensure_ascii=False), encoding="utf-8")
                    temporary.replace(self._settings_path)
                except OSError as exc:
                    result["warning"] = f"Image generated, but settings could not be saved: {exc}"
                return result
        except Exception as exc:
            return {"error": str(exc)}
        finally:
            self._busy.clear()

    def choose_output(self):
        import webview
        from heatmap.settings import output_path
        folder = output_path(self._settings).parent
        paths = self._window.create_file_dialog(webview.FileDialog.FOLDER,
                                               directory=str(folder if folder.is_dir() else BASE_DIR))
        return {"output_path": str(Path(paths[0]) / "temperature_heatmap.png")} if paths else {"cancelled": True}

    def open_output(self):
        try:
            if self._last_output is None or not self._last_output.parent.is_dir():
                raise ValueError("Export a PNG first.")
            os.startfile(str(self._last_output.parent))
            return {"ok": True}
        except (OSError, ValueError) as exc:
            return {"error": str(exc)}


def build_html() -> str:
    """Bundle local assets for offline desktop use with no HTTP server."""
    from ui_components import bundle_output_picker
    directory = BASE_DIR / "heatmap_ui"
    html = (directory / "index.html").read_text(encoding="utf-8").replace(
        "/* APP_STYLES */", (directory / "styles.css").read_text(encoding="utf-8")
        + "\n" + (directory / "completion.css").read_text(encoding="utf-8")
        + "\n" + (directory / "geometry.css").read_text(encoding="utf-8")
    ).replace("/* APP_SCRIPT */", (directory / "app.js").read_text(encoding="utf-8"))
    return bundle_output_picker(html, path_id="output_path", button_id="browse", label="Save PNG to", editable=True)


def main():
    import webview
    api = HeatmapAPI()
    window = webview.create_window("Heatmap · Temperature workspace", html=build_html(), js_api=api,
                                   width=1160, height=780, min_size=(900, 650), background_color="#f3f8fd")
    api._window = window
    window.events.closing += lambda: not api._busy.is_set()
    webview.start(gui="edgechromium", storage_path=str(BASE_DIR / ".webview"))


if __name__ == "__main__":
    main()

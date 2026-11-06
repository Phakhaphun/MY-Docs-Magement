"""Single desktop host for the document and temperature workspaces."""

import argparse
import json
from html import escape
from pathlib import Path
from threading import RLock

from doc_app import DocumentAPI, build_html as document_html
from heatmap_app import HeatmapAPI, build_html as heatmap_html

BASE_DIR = Path(__file__).resolve().parent
METHODS = {
    "documents": ("get_state", "ready", "choose_files", "choose_output", "remove_file",
                  "clear_files", "preview", "start_conversion", "update_settings",
                  "open_output", "set_sidebar_expanded"),
    "heatmap": ("get_settings", "defaults", "generate", "choose_output", "open_output"),
}


class ManagementAPI:
    def __init__(self, settings_dir=BASE_DIR, on_ready=None):
        self._on_ready = on_ready
        self._settings_dir = Path(settings_dir)
        self._window = None
        self._heatmap_instance = None
        self._heatmap_lock = RLock()
        self._documents = DocumentAPI(self._settings_dir / "ui_settings.json", on_ready=self.ready)

    @property
    def _heatmap(self):
        # NumPy, settings validation, and rendering are needed only after the
        # user opens Heatmap. Serialize first access from bridge worker threads.
        with self._heatmap_lock:
            if self._heatmap_instance is None:
                api = HeatmapAPI(self._settings_dir / "heatmap_settings.json")
                api._window = self._window
                self._heatmap_instance = api
            return self._heatmap_instance

    def invoke(self, workspace, method, args):
        if not isinstance(workspace, str) or not isinstance(method, str):
            return {"error": "Invalid workspace or action."}
        if method not in METHODS.get(workspace, ()) or not isinstance(args, list):
            return {"error": "Unknown workspace action."}
        try:
            target = self._documents if workspace == "documents" else self._heatmap
            return getattr(target, method)(*args)
        except Exception as exc:
            return {"error": str(exc)}

    def ready(self):
        if self._on_ready:
            callback, self._on_ready = self._on_ready, None
            callback()
        return {"ok": True}

    def _attach(self, window):
        self._window = window
        self._documents._window = window
        if self._heatmap_instance is not None:
            self._heatmap_instance._window = window

    def _can_close(self):
        return self._documents._can_close() and (
            self._heatmap_instance is None or not self._heatmap_instance._busy.is_set())


def build_html():
    # Separate documents isolate existing CSS, IDs, and scripts while sharing one
    # native window and bridge. Both frames stay mounted to preserve current work.
    embedded_style = "<style>body>.rail{display:none!important}body{min-width:0!important}</style>"
    template = (BASE_DIR / "ui" / "management.html").read_text(encoding="utf-8")
    for name, content in (("DOCUMENTS", document_html()), ("HEATMAP", heatmap_html())):
        template = template.replace(f"<!-- {name}_HTML -->", escape(content.replace("</head>", embedded_style + "</head>"), quote=True))
    return template.replace("/* BRIDGE_METHODS */", json.dumps(METHODS))


def run_desktop(report=lambda status, message: None):
    import webview

    def on_ready():
        window.show()
        report("ready", "Your document and heatmap workspace is ready.")

    report("loading", "Preparing PDF and Heatmap workspaces…")
    api = ManagementAPI(on_ready=on_ready)
    window = webview.create_window(
        "Docspace · Main Management", html=build_html(), js_api=api,
        width=1280, height=820, min_size=(1080, 700), background_color="#f3f8fd", hidden=True,
    )
    api._attach(window)
    window.events.closing += api._can_close
    webview.start(gui="edgechromium", storage_path=str(BASE_DIR / ".webview"),
                  icon=str(BASE_DIR / "ui" / "assets" / "docspace.ico"))


def main():
    parser = argparse.ArgumentParser(description="Documents and Temperature Heatmap")
    parser.add_argument("--startup-channel", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()

    def report(status, message):
        if args.startup_channel:
            temporary = args.startup_channel.with_suffix(".tmp")
            temporary.write_text(json.dumps({"status": status, "message": message}), encoding="utf-8")
            temporary.replace(args.startup_channel)

    try:
        run_desktop(report)
    except Exception:
        report("error", "Could not start. See .webview/startup.log for details.")
        raise


if __name__ == "__main__":
    main()

"""Exercise both workspaces through the actual shared WebView bridge."""

import json
from pathlib import Path
import sys
import time
import traceback

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pymupdf
import webview

from main_app import ManagementAPI, BASE_DIR, build_html
from tools.test_workspace import test_workspace


def main():
    failures = []
    with test_workspace() as folder:
        folder = Path(folder)
        pdf = folder / "sample.pdf"
        with pymupdf.open() as document:
            page = document.new_page(width=144, height=72)
            page.insert_text((12, 30), "Combined workspace")
            document.save(pdf)
        api = ManagementAPI(folder)
        api._documents._state["output"] = str(folder / "pdf_output")
        api._documents._add_files([str(pdf)])
        settings = json.loads((BASE_DIR / "config.json").read_text(encoding="utf-8"))
        settings["output_path"] = str(folder / "heatmap.png")
        (folder / "heatmap_settings.json").write_text(json.dumps(settings), encoding="utf-8")
        window = webview.create_window("Docspace · Integration check", html=build_html(), js_api=api,
                                       width=1280, height=820, min_size=(1080, 700))
        api._attach(window)

        def wait_for(expression, timeout=60):
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                if window.evaluate_js(expression):
                    return
                time.sleep(.15)
            raise AssertionError(f"Timed out: {expression}")

        def run():
            try:
                assert window.events.loaded.wait(30)
                wait_for("document.getElementById('connection').hidden")
                assert api._heatmap_instance is None, "Heatmap must not delay startup"
                assert window.evaluate_js("document.getElementById('documents').contentDocument.getElementById('openOutputBtn') === null")
                wait_for("document.getElementById('documents').contentDocument.getElementById('fileCount').textContent === '1'")
                window.evaluate_js("document.getElementById('documents').contentDocument.querySelector('#fileList .file-row').click()")
                wait_for("document.getElementById('documents').contentDocument.getElementById('previewImage').naturalWidth > 0")
                window.evaluate_js("document.getElementById('documents').contentDocument.getElementById('convertBtn').click()")
                wait_for("document.getElementById('documents').contentDocument.getElementById('completionDialog').open")
                assert len(list((folder / "pdf_output").rglob("*.jpg"))) == 1
                assert api._heatmap_instance is None
                window.evaluate_js("document.getElementById('documents').contentDocument.getElementById('completionDone').click(); document.getElementById('heatmapTab').click()")
                wait_for("!document.getElementById('heatmap').contentWindow.heatmapBusy && document.getElementById('heatmap').contentDocument.getElementById('previewImage').naturalWidth > 0")
                assert window.evaluate_js("document.getElementById('documents').hidden && !document.getElementById('heatmap').hidden")
                assert window.evaluate_js("document.getElementById('heatmap').contentDocument.getElementById('openOutput') === null")
                window.evaluate_js("document.getElementById('heatmap').contentDocument.getElementById('t1').value = '75'; document.getElementById('documentsTab').click(); document.getElementById('heatmapTab').click()")
                assert window.evaluate_js("document.getElementById('heatmap').contentDocument.getElementById('t1').value") == "75"
                window.evaluate_js("document.getElementById('heatmap').contentDocument.getElementById('export').click()")
                wait_for("document.getElementById('heatmap').contentDocument.getElementById('exportDialog').open")
                assert (folder / "heatmap.png").read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
                assert api._heatmap._settings["temperatures"][0][0] == 75
                assert (folder / "ui_settings.json").exists()
                assert (folder / "heatmap_settings.json").exists()
                assert json.loads((folder / "heatmap_settings.json").read_text())["temperatures"][0][0] == 75
                assert window.evaluate_js("document.documentElement.scrollWidth <= innerWidth")
                screenshot = window.evaluate_js("document.getElementById('heatmap').contentDocument.getElementById('previewImage').src")
                assert screenshot.startswith("data:image/png;base64,")
                print("PASS: shared bridge, PDF preview/conversion, Heatmap preview/export, navigation, retained state, independent settings")
            except Exception:
                failures.append(traceback.format_exc())
            finally:
                window.destroy()

        webview.start(run, gui="edgechromium", storage_path=str(folder / "webview"))
    if failures:
        raise AssertionError("\n".join(failures))


if __name__ == "__main__":
    main()

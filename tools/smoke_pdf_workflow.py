"""Exercise PDF workflows in WebView2, including native file drag events."""

import base64
import json
from pathlib import Path
import sys
from threading import Event
import time
import traceback
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pymupdf
import webview

from main_app import ManagementAPI, build_html
from pdf_worker import convert_in_process as convert_pdf_to_images
from tools.test_workspace import test_workspace


def main():
    failures = []
    with test_workspace() as folder:
        folder = Path(folder)
        pdf = folder / "PDF drag ทดสอบ.pdf"
        with pymupdf.open() as document:
            for index in range(6):
                document.new_page(width=144, height=72).insert_text((12, 30), f"Page {index + 1}")
            document.save(pdf)
        api = ManagementAPI(folder)
        api._documents._state["output"] = str(folder / "images")
        window = webview.create_window("Docspace · PDF workflow check", html=build_html(), js_api=api,
                                       width=1280, height=820, min_size=(1080, 700))
        api._attach(window)
        window.events.loaded += api._bind_drop
        release = Event()

        def js(code):
            return window.evaluate_js("(() => {const w = document.getElementById('documents').contentWindow; const d = w.document; " + code + "})()")

        def wait_for(check, timeout=20):
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                if check():
                    return
                time.sleep(.05)
            raise AssertionError("Timed out waiting for PDF workflow")

        def devtools(method, parameters):
            # Test-only access to WebView2's native DevTools endpoint. Dispatching
            # file paths here exercises pywebview's AdditionalObjects path bridge.
            from System import Action
            tasks = []
            control = window.native.webview
            control.Invoke(Action(lambda: tasks.append(control.CoreWebView2.CallDevToolsProtocolMethodAsync(
                method, json.dumps(parameters)))))
            if not tasks[0].Wait(10000):
                raise AssertionError("DevTools command timed out")
            return tasks[0].Result

        def drop(x, y):
            data = {"items": [], "files": [str(pdf)], "dragOperationsMask": 1}
            for event_type in ("dragEnter", "dragOver", "drop"):
                devtools("Input.dispatchDragEvent", {"type": event_type, "x": x, "y": y, "data": data})

        def run():
            try:
                wait_for(lambda: window.evaluate_js("document.getElementById('connection').hidden"))
                wait_for(lambda: hasattr(api._documents, "_drop_target"))
                # Drop into the child workspace and the undecorated host sidebar.
                drop(500, 200)
                wait_for(lambda: js("return d.getElementById('fileCount').textContent === '1';"))
                assert api._documents.get_state()["files"][0]["path"] == str(pdf)
                drop(60, 400)  # Host sidebar: duplicate remains one file.
                wait_for(lambda: js("return d.getElementById('previewImage').naturalWidth > 0;"))
                assert len(api._documents.get_state()["files"]) == 1
                assert js("return d.getElementById('pageMode').value === 'all' && d.getElementById('pageSelection').hidden;")
                assert not window.evaluate_js("document.body.textContent.includes('Drop PDFs here')")
                js("const mode=d.getElementById('pageMode'); mode.value='custom'; mode.dispatchEvent(new Event('change'));")
                js("const input = d.getElementById('pageSelection'); input.value='0'; input.dispatchEvent(new Event('input')); d.getElementById('convertBtn').click();")
                wait_for(lambda: js("return !d.getElementById('toast').hidden;"))
                assert not (folder / "images").exists()
                js("const input = d.getElementById('pageSelection'); input.value='2, 4-5'; input.dispatchEvent(new Event('input')); d.getElementById('convertBtn').click();")
                wait_for(lambda: js("return d.getElementById('completionDialog').open;"))
                assert sorted(p.name for p in (folder / "images").rglob("*.jpg")) == ["page_002.jpg", "page_004.jpg", "page_005.jpg"]
                js("d.getElementById('completionDone').click();")
                entered = Event()

                def paused(*args, **kwargs):
                    progress = kwargs["on_progress"]
                    def on_progress(*values):
                        progress(*values)
                        entered.set()
                        if not release.wait(15):
                            raise RuntimeError("Test cancellation timed out")
                    kwargs["on_progress"] = on_progress
                    return convert_pdf_to_images(*args, **kwargs)

                with patch("doc_app.convert_pdf_to_images", side_effect=paused):
                    js("d.getElementById('convertBtn').click();")
                    assert entered.wait(15)
                    wait_for(lambda: js("return !d.getElementById('cancelBtn').hidden;"))
                    assert js("return w.getComputedStyle(d.getElementById('cancelBtn')).backgroundColor === 'rgb(199, 45, 61)';")
                    evidence = Path(__file__).resolve().parents[1] / ".runtime-tmp"
                    evidence.mkdir(exist_ok=True)
                    screenshot = json.loads(devtools("Page.captureScreenshot", {"format": "png"}))
                    (evidence / "pdf-cancel-button.png").write_bytes(base64.b64decode(screenshot["data"]))
                    assert js("return d.getElementById('pageSelection').disabled;")
                    js("d.getElementById('cancelBtn').click();")
                    wait_for(lambda: api._documents.get_state()["cancelling"])
                    release.set()
                    wait_for(lambda: js("return d.getElementById('completionDialog').open;"))
                    assert js("return d.getElementById('completionTitle').textContent;") == "Conversion cancelled"
                    assert api._documents.get_state()["result"]["images"] == 1
                    assert len(list((folder / "images" / f"{pdf.stem}_2").glob("*.jpg"))) == 1
                js("d.getElementById('completionDone').click();")
                for mode, pages in [("all", [1, 2, 3, 4, 5, 6]), ("even", [2, 4, 6]), ("odd", [1, 3, 5]), ("current", [2])]:
                    before = set((folder / "images").iterdir())
                    if mode == "current":
                        js("d.getElementById('nextPage').click();")
                        wait_for(lambda: js("return d.getElementById('pageLabel').textContent === '2 / 6';"))
                    js(f"const mode=d.getElementById('pageMode'); mode.value='{mode}'; mode.dispatchEvent(new Event('change')); d.getElementById('convertBtn').click();")
                    wait_for(lambda: js("return d.getElementById('completionDialog').open;"))
                    new = set((folder / "images").iterdir()) - before
                    assert len(new) == 1
                    assert sorted(p.name for p in new.pop().glob("*.jpg")) == [f"page_{p:03d}.jpg" for p in pages]
                    assert js("return d.getElementById('pageSelection').hidden;")
                    js("d.getElementById('completionDone').click();")
                js("const mode=d.getElementById('pageMode'); mode.value='custom'; mode.dispatchEvent(new Event('change'));")
                for width, height in [(1280, 820), (1080, 700)]:
                    window.resize(width, height)
                    time.sleep(.2)
                    assert js("return d.documentElement.scrollWidth <= w.innerWidth && d.documentElement.scrollHeight <= w.innerHeight;")
                    assert js("const r=d.getElementById('pageSelection').getBoundingClientRect(); return r.width>100 && r.bottom<w.innerHeight;")
                    assert js("const r=d.getElementById('previewStage').getBoundingClientRect(); return r.height>100;")
                    evidence = Path(__file__).resolve().parents[1] / ".runtime-tmp"
                    evidence.mkdir(exist_ok=True)
                    screenshot = json.loads(devtools("Page.captureScreenshot", {"format": "png"}))
                    (evidence / f"pdf-workflow-{width}x{height}.png").write_bytes(base64.b64decode(screenshot["data"]))
                print("PASS: native PDF drop into iframe/host, duplicate paths, invalid pages, selected export, cancellation UI, kept images, 1280x820 and 1080x700 layouts")
            except Exception:
                failures.append(traceback.format_exc())
            finally:
                release.set()
                window.destroy()

        webview.start(run, gui="edgechromium", storage_path=str(folder / "webview"))
    if failures:
        raise AssertionError("\n".join(failures))


if __name__ == "__main__":
    main()

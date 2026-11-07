"""Exercise the new PDF organizer through its actual WebView2 UI and bridge."""

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

from main_app import ManagementAPI, BASE_DIR, build_html
from pdf_worker import organize_in_process
from tools.test_workspace import test_workspace


def main():
    failures = []
    release = Event()
    with test_workspace() as folder:
        folder = Path(folder)
        sources = []
        for name, count in (("A", 3), ("B", 2)):
            source = folder / f"{name} เอกสาร.pdf"
            with pymupdf.open() as document:
                for number in range(1, count + 1):
                    document.new_page(width=300, height=400).insert_text((30, 60), f"{name}{number}", fontsize=30)
                document.save(source)
            sources.append(source)
        api = ManagementAPI(folder)
        api._organizer._state["output"] = str(folder / "organized")
        window = webview.create_window("Docspace · Organizer check", html=build_html(), js_api=api,
                                       width=1280, height=820, min_size=(1080, 700))
        api._attach(window)
        window.events.loaded += api._bind_drop

        def js(code):
            return window.evaluate_js("(() => {const w=document.getElementById('organizer').contentWindow; const d=w.document; " + code + "})()")

        def wait_for(check):
            deadline = time.monotonic() + 25
            while time.monotonic() < deadline:
                if check():
                    return
                time.sleep(.05)
            raise AssertionError("Organizer UI check timed out")

        def cdp(method, params):
            from System import Action
            control, tasks = window.native.webview, []
            control.Invoke(Action(lambda: tasks.append(control.CoreWebView2.CallDevToolsProtocolMethodAsync(method, json.dumps(params)))))
            assert tasks[0].Wait(10000)
            return json.loads(tasks[0].Result)

        def zoom_settings():
            from System import Action
            values = []
            control = window.native.webview
            control.Invoke(Action(lambda: values.extend([control.ZoomFactor, control.CoreWebView2.Settings.IsZoomControlEnabled])))
            return values

        def result():
            wait_for(lambda: js("return d.getElementById('resultDialog').open;"))
            output = api._organizer.get_state()["result"]
            assert not output["error"], output
            return output

        def texts(path):
            with pymupdf.open(path) as document:
                return [page.get_text().strip() for page in document]

        def run():
            try:
                wait_for(lambda: window.evaluate_js("document.getElementById('connection').hidden"))
                window.evaluate_js("document.getElementById('organizerTab').click()")
                wait_for(lambda: js("return d.getElementById('status').textContent !== 'Connecting…';"))
                wait_for(lambda: hasattr(api._documents, "_drop_target"))
                for kind in ("dragEnter", "dragOver", "drop"):
                    cdp("Input.dispatchDragEvent", {"type": kind, "x": 550, "y": 260,
                        "data": {"items": [], "files": [str(path) for path in sources], "dragOperationsMask": 1}})
                wait_for(lambda: js("return d.querySelectorAll('.page-card').length === 5;"))
                assert api._documents.get_state()["files"] == [], "Drop must go only to organizer"
                wait_for(lambda: js("return d.querySelector('.thumb img').naturalWidth > 0;"))
                js("d.querySelectorAll('.page-card')[1].querySelector('[data-action=trash]').click(); d.getElementById('undo').click();")
                assert js("return d.querySelectorAll('.page-card').length;") == 5
                js("d.querySelector('.thumb').click(); d.querySelectorAll('.thumb')[4].dispatchEvent(new MouseEvent('click',{shiftKey:true,bubbles:true}));")
                assert js("return d.querySelectorAll('.page-card.selected').length;") == 5
                js("d.getElementById('rotateSelected').click(); d.querySelector('[data-transform=right]').click(); d.getElementById('undo').click();")
                js("const cards=d.querySelectorAll('.page-card'), transfer=new DataTransfer(); cards[4].dispatchEvent(new DragEvent('dragstart',{dataTransfer:transfer,bubbles:true})); cards[0].dispatchEvent(new DragEvent('drop',{dataTransfer:transfer,bubbles:true,cancelable:true}));")
                assert js("return d.querySelector('.page-meta span').textContent.startsWith('B');")
                js("d.querySelectorAll('.page-card')[4].querySelector('[data-action=trash]').click(); d.querySelectorAll('.page-card')[2].querySelector('[data-action=trash]').click();")
                assert js("return d.querySelectorAll('.page-card').length;") == 3
                js("d.querySelector('[data-action=rotate]').click(); d.querySelector('[data-transform=right]').click(); d.querySelector('[data-action=zoom]').click();")
                wait_for(lambda: js("return d.getElementById('previewImage').naturalWidth > 0;"))
                wait_for(lambda: js("return !d.getElementById('previewImage').hidden;"))
                original = js("return d.getElementById('previewCanvas').getBoundingClientRect().width;")
                js("d.getElementById('previewZoomIn').click();")
                assert js("return d.getElementById('previewCanvas').getBoundingClientRect().width;") > original
                assert zoom_settings() == [1.0, False]
                js("d.getElementById('previewFit').click();")
                assert js("const image=d.getElementById('previewCanvas').getBoundingClientRect(), stage=d.getElementById('previewStage').getBoundingClientRect(); return image.width<=stage.width && image.height<=stage.height;")
                js("d.getElementById('previewFitWidth').click();")
                assert js("return d.getElementById('previewCanvas').getBoundingClientRect().width;") >= original
                js("d.getElementById('previewStage').dispatchEvent(new WheelEvent('wheel',{ctrlKey:true,deltaY:-80,bubbles:true,cancelable:true}));")
                assert zoom_settings() == [1.0, False]
                position = js("const r=d.getElementById('previewStage').getBoundingClientRect(), frame=w.frameElement.getBoundingClientRect(); return {x:frame.left+r.left+r.width/2,y:frame.top+r.top+r.height/2};")
                cdp("Input.dispatchMouseEvent", {"type":"mouseWheel", **position, "deltaX":0, "deltaY":-100, "modifiers":2})
                assert zoom_settings() == [1.0, False]
                js("d.getElementById('previewFit').click();")
                evidence = BASE_DIR / ".runtime-tmp"
                evidence.mkdir(exist_ok=True)
                (evidence / "organizer-preview-fit.png").write_bytes(base64.b64decode(cdp("Page.captureScreenshot", {"format": "png"})["data"]))
                js("d.getElementById('previewTransform').click(); d.querySelector('[data-transform=horizontal]').click();")
                assert js("return d.getElementById('previewImage').style.transform.includes('scale(-1');")
                js("d.getElementById('previewTransform').click(); d.querySelector('[data-transform=horizontal]').click();")
                js("d.getElementById('closePreview').click();")
                window.evaluate_js("document.getElementById('documentsTab').click(); document.getElementById('organizerTab').click();")
                assert js("return d.querySelectorAll('.page-card').length;") == 3
                for mode, expected in [("merge", [["B2", "A1", "A3"]]), ("extract", [["B2"], ["A1", "A3"]]),
                                       ("split", [["B2"], ["A1"], ["A3"]])]:
                    js(f"d.getElementById('mode').value='{mode}'; d.getElementById('export').click();")
                    output = result()
                    assert [texts(path) for path in output["paths"]] == expected
                    with pymupdf.open(output["paths"][0]) as document:
                        assert document[0].rotation == 90
                    js("d.getElementById('done').click();")
                js("d.querySelectorAll('.thumb')[1].click(); d.getElementById('scope').value='selected'; d.getElementById('scope').dispatchEvent(new Event('change')); d.getElementById('mode').value='merge'; d.getElementById('export').click();")
                assert [texts(path) for path in result()["paths"]] == [["A1"]]
                js("d.getElementById('done').click(); d.getElementById('scope').value='all'; d.getElementById('scope').dispatchEvent(new Event('change')); d.getElementById('mode').value='split';")
                entered = Event()
                def paused(*args, **kwargs):
                    callback = kwargs["on_progress"]
                    def progress(*values):
                        callback(*values); entered.set()
                        if not release.wait(15):
                            raise RuntimeError("Timed out waiting for Cancel")
                    kwargs["on_progress"] = progress
                    return organize_in_process(*args, **kwargs)
                with patch("organizer_app.organize_in_process", side_effect=paused):
                    js("d.getElementById('export').click();")
                    assert entered.wait(15)
                    wait_for(lambda: js("return !d.getElementById('cancel').hidden;"))
                    assert not api._can_close()
                    js("d.getElementById('cancel').click();")
                    wait_for(lambda: api._organizer.get_state()["cancelling"])
                    release.set()
                    output = result()
                    assert output["cancelled"] and len(output["paths"]) == 1
                    js("d.getElementById('done').click();")
                for width, height in [(1280, 820), (1080, 700)]:
                    window.resize(width, height); time.sleep(.2)
                    assert js("return d.documentElement.scrollWidth <= w.innerWidth && d.documentElement.scrollHeight <= w.innerHeight;")
                    assert js("return d.getElementById('pageScroll').getBoundingClientRect().height > 150;")
                    assert js("const r=d.getElementById('export').getBoundingClientRect(); return r.bottom<=w.innerHeight && r.right<=w.innerWidth;")
                    evidence = BASE_DIR / ".runtime-tmp"
                    evidence.mkdir(exist_ok=True)
                    (evidence / f"organizer-{width}x{height}.png").write_bytes(base64.b64decode(cdp("Page.captureScreenshot", {"format": "png"})["data"]))
                    js("d.getElementById('listView').click();")
                    assert js("return d.getElementById('pages').classList.contains('list-view');")
                    (evidence / f"organizer-list-{width}x{height}.png").write_bytes(base64.b64decode(cdp("Page.captureScreenshot", {"format": "png"})["data"]))
                    js("d.getElementById('gridView').click();")
                many = folder / "many.pdf"
                with pymupdf.open() as document:
                    for number in range(40):
                        document.new_page().insert_text((30, 60), f"Page {number + 1}")
                    document.save(many)
                with patch.object(api._organizer, "thumbnail", wraps=api._organizer.thumbnail) as thumbnail:
                    api._organizer._add_files([many])
                    wait_for(lambda: js("return d.querySelectorAll('.page-card').length === 43;"))
                    time.sleep(.5)
                    assert thumbnail.call_count < 40, "Offscreen pages should not all render immediately"
                    js("d.getElementById('pageScroll').scrollTop=d.getElementById('pageScroll').scrollHeight;")
                    wait_for(lambda: js("return d.querySelector('.page-card:last-child .thumb img').naturalWidth > 0;"))
                print("PASS: organizer page grid/list, native drop, thumbnails, shift selection, drag order, delete/undo, rotation/preview, selected export, 3 PDF modes, cancellation and 2 window sizes")
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

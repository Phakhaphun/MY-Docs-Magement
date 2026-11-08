"""Verify point placement and full-area estimates through the real desktop UI."""

import base64
import json
from pathlib import Path
import sys
import time
import traceback

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
import webview

from heatmap.settings import load_settings
from heatmap.spatial import evaluate_spatial, spatial_grid
from main_app import BASE_DIR, ManagementAPI, build_html
from tools.test_workspace import test_workspace


def main():
    failures = []
    with test_workspace() as folder:
        folder = Path(folder)
        settings = {**load_settings(), "area_width": 10, "area_height": 10, "area_unit": "cm",
                    "sensor_positions": [[3,3],[5,3],[7,3],[3,7],[5,7],[7,7]],
                    "temperatures": [[10,20,30],[40,50,60]], "color_min":10,"color_max":60,
                    "output_path":str(folder / "estimated.png"), "dpi":72}
        (folder / "heatmap_settings.json").write_text(json.dumps(settings), encoding="utf-8")
        api = ManagementAPI(folder)
        window = webview.create_window("Docspace · Spatial heatmap check", html=build_html(), js_api=api,
                                       width=1280, height=820, min_size=(1080,700))
        api._attach(window)
        window.events.loaded += api._bind_drop

        def js(code):
            return window.evaluate_js("(() => {const w=document.getElementById('heatmap').contentWindow, d=w.document; " + code + "})()")

        def wait_for(check):
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                if check(): return
                time.sleep(.1)
            raise AssertionError("Heatmap UI check timed out")

        def ready():
            return js("return !w.heatmapBusy && d.getElementById('previewState').textContent === 'Preview up to date';")

        def screenshot(path):
            from System import Action
            tasks = []
            control = window.native.webview
            control.Invoke(Action(lambda: tasks.append(control.CoreWebView2.CallDevToolsProtocolMethodAsync("Page.captureScreenshot", '{"format":"png"}'))))
            assert tasks[0].Wait(10000)
            path.write_bytes(base64.b64decode(json.loads(tasks[0].Result)["data"]))

        def run():
            try:
                wait_for(lambda: window.evaluate_js("document.getElementById('connection').hidden"))
                window.evaluate_js("document.getElementById('heatmapTab').click()")
                wait_for(ready)
                assert js("return d.getElementById('x1').value;") == "3", "Initial coordinates must not reset to 2x3 corners"
                assert js("return [...d.querySelectorAll('.coordinate-fields')].every(panel=>panel.hidden);")
                js("d.querySelector('.coordinate-toggle').click();")
                assert js("return !d.getElementById('coordinates1').hidden;")
                assert not np.ma.getmaskarray(spatial_grid(api._heatmap._settings)).any()
                # Type coordinates and verify they reach the real API unchanged.
                js("d.getElementById('x1').value='2'; d.getElementById('x1').dispatchEvent(new Event('input',{bubbles:true})); d.getElementById('generate').click();")
                wait_for(ready)
                assert api._heatmap._settings["sensor_positions"][0] == [2,3]
                js("d.getElementById('areaSection').open=true;")
                js("d.getElementById('openLayout').click();")
                assert js("const r=d.getElementById('pointLayout').getBoundingClientRect(); return d.getElementById('layoutDialog').open && r.width>400 && r.height>300;")
                # Keyboard operation on the diagram changes coordinates.
                js("d.querySelector('[data-point=\"0\"]').dispatchEvent(new KeyboardEvent('keydown',{key:'ArrowRight',bubbles:true}));")
                assert js("return Number(d.getElementById('x1').value);") == 2.1
                # Drag the first point using real browser input coordinates.
                from System import Action
                def mouse(kind, x, y, **extra):
                    tasks=[]; control=window.native.webview
                    params=json.dumps({"type":kind,"x":x,"y":y,**extra})
                    control.Invoke(Action(lambda: tasks.append(control.CoreWebView2.CallDevToolsProtocolMethodAsync("Input.dispatchMouseEvent",params))))
                    assert tasks[0].Wait(10000)
                    tasks[0].Result
                position = js("const point=d.querySelector('[data-point=\"0\"]').getBoundingClientRect(), frame=w.frameElement.getBoundingClientRect(); return {x:frame.left+point.left+point.width/2,y:frame.top+point.top+point.height/2};")
                mouse("mousePressed",**position,button="left",clickCount=1)
                mouse("mouseMoved",position["x"]+18,position["y"]+8,button="left",buttons=1)
                mouse("mouseReleased",position["x"]+18,position["y"]+8,button="left",clickCount=1)
                assert js("return Number(d.getElementById('x1').value);") > 2.1
                # Placement grid changes do not silently move existing readings.
                previous = js("return [Number(d.getElementById('x1').value),Number(d.getElementById('y1').value)];")
                js("d.getElementById('layout_grid_spacing').value='0.5'; d.getElementById('layout_grid_spacing').dispatchEvent(new Event('input',{bubbles:true})); d.getElementById('layout_snap').checked=true; d.getElementById('layout_snap').dispatchEvent(new Event('input',{bubbles:true}));")
                assert js("return [Number(d.getElementById('x1').value),Number(d.getElementById('y1').value)];") == previous
                assert js("return d.querySelectorAll('#placementGrid line').length;") == 40
                position = js("const point=d.querySelector('[data-point=\"0\"]').getBoundingClientRect(), frame=w.frameElement.getBoundingClientRect(); return {x:frame.left+point.left+point.width/2,y:frame.top+point.top+point.height/2};")
                mouse("mousePressed",**position,button="left",clickCount=1)
                mouse("mouseMoved",position["x"]+13,position["y"]+7,button="left",buttons=1)
                mouse("mouseReleased",position["x"]+13,position["y"]+7,button="left",clickCount=1)
                snapped = js("return [Number(d.getElementById('x1').value),Number(d.getElementById('y1').value)];")
                assert all(value*2 == round(value*2) for value in snapped), snapped
                # Exact typed values remain possible while snapping is on.
                js("d.getElementById('x1').value='4.37'; d.getElementById('x1').dispatchEvent(new Event('input',{bubbles:true}));")
                assert js("return Number(d.getElementById('x1').value);") == 4.37
                js("d.querySelector('[data-point=\"0\"]').dispatchEvent(new KeyboardEvent('keydown',{key:'ArrowRight',bubbles:true}));")
                assert js("return Number(d.getElementById('x1').value);") == 4.5
                js("d.getElementById('y1').value='3'; d.getElementById('y1').dispatchEvent(new Event('input',{bubbles:true})); d.querySelector('[data-point=\"0\"]').dispatchEvent(new KeyboardEvent('keydown',{key:'ArrowRight',bubbles:true}));")
                assert js("return Number(d.getElementById('x1').value);") == 4.5
                assert js("return d.getElementById('gridStatus').textContent.includes('occupied');")
                js("d.querySelector('[data-point=\"0\"]').dispatchEvent(new KeyboardEvent('keydown',{key:'ArrowDown',shiftKey:true,bubbles:true}));")
                assert js("return Number(d.getElementById('y1').value);") == 5.5
                # Hiding lines leaves snapping enabled; a tiny grid cannot flood the DOM.
                js("d.getElementById('layout_grid_visible').checked=false; d.getElementById('layout_grid_visible').dispatchEvent(new Event('input',{bubbles:true}));")
                assert js("return d.querySelectorAll('#placementGrid line').length;") == 0
                js("d.getElementById('layout_grid_spacing').value='0.000001'; d.getElementById('layout_grid_visible').checked=true; d.getElementById('layout_grid_spacing').dispatchEvent(new Event('input',{bubbles:true}));")
                assert js("return d.querySelectorAll('#placementGrid line').length;") == 0
                assert js("return d.getElementById('gridStatus').textContent.includes('too dense');")
                js("d.getElementById('layout_grid_spacing').value='3'; d.getElementById('x1').value='10'; d.getElementById('y1').value='0'; d.getElementById('layout_grid_spacing').dispatchEvent(new Event('input',{bubbles:true})); d.querySelector('[data-point=\"0\"]').dispatchEvent(new KeyboardEvent('keydown',{key:'ArrowLeft',bubbles:true}));")
                assert js("return Number(d.getElementById('x1').value);") == 9
                js("d.getElementById('layout_grid_spacing').value='0'; d.getElementById('layout_grid_spacing').dispatchEvent(new Event('input',{bubbles:true}));")
                assert js("return !d.getElementById('layout_grid_spacing').checkValidity();")
                js("d.getElementById('closeLayout').click(); d.getElementById('generate').click();")
                assert js("return d.getElementById('layoutDialog').open && !w.heatmapBusy;")
                js("d.getElementById('layout_grid_spacing').value='0.5'; d.getElementById('layout_grid_spacing').dispatchEvent(new Event('input',{bubbles:true}));")
                evidence=BASE_DIR / '.runtime-tmp'; evidence.mkdir(exist_ok=True)
                screenshot(evidence / 'heatmap-layout-popup.png')
                js("d.getElementById('closeLayout').click();")
                js("d.getElementById('generate').click();")
                wait_for(ready)
                points=api._heatmap._settings["sensor_positions"]
                assert points[0][0] > 2.1
                saved_points=[list(point) for point in points]
                # Invalid locations fail visibly before rendering.
                js("if (!d.getElementById('coordinates1').hidden) d.querySelector('.coordinate-toggle').click();")
                js("d.getElementById('x1').value='11'; d.getElementById('x1').dispatchEvent(new Event('input',{bubbles:true}));")
                assert js("return !d.getElementById('x1').checkValidity();")
                assert js("return !d.getElementById('coordinates1').hidden;")
                js(f"d.getElementById('x1').value='{points[0][0]}'; d.getElementById('x1').dispatchEvent(new Event('input',{{bubbles:true}}));")
                js("d.getElementById('estimation_method').value='linear'; d.getElementById('estimation_method').dispatchEvent(new Event('input',{bubbles:true})); d.getElementById('generate').click();")
                wait_for(ready)
                assert np.ma.is_masked(evaluate_spatial(api._heatmap._settings,0,0))
                js("d.getElementById('estimation_method').value='smooth'; d.getElementById('estimation_method').dispatchEvent(new Event('input',{bubbles:true})); d.getElementById('generate').click();")
                wait_for(ready)
                assert api._heatmap._settings['estimation_method']=='smooth'
                assert np.ma.is_masked(evaluate_spatial(api._heatmap._settings,0,0))
                screenshot(evidence / 'heatmap-smooth-region.png')
                js("d.getElementById('estimation_method').value='idw'; d.getElementById('estimation_method').dispatchEvent(new Event('input',{bubbles:true})); d.getElementById('idw_power').value='3'; d.getElementById('export').click();")
                wait_for(lambda: js("return d.getElementById('exportDialog').open;"))
                assert (folder / "estimated.png").read_bytes().startswith(b"\x89PNG")
                restored = json.loads((folder / "heatmap_settings.json").read_text())
                assert restored["sensor_positions"] == saved_points
                assert restored["estimation_method"] == "idw" and restored["idw_power"] == 3
                assert restored["layout_snap"] and restored["layout_grid_visible"] and restored["layout_grid_spacing"] == 0.5
                assert not np.ma.getmaskarray(spatial_grid(restored)).any()
                js("d.getElementById('completionDone').click();")
                evidence = BASE_DIR / ".runtime-tmp"; evidence.mkdir(exist_ok=True)
                js("d.getElementById('areaSection').open=true; d.getElementById('settingsForm').scrollTop=0;")
                screenshot(evidence / "heatmap-placement-grid.png")
                js("d.querySelectorAll('.coordinate-toggle[aria-expanded=true]').forEach(button=>button.click()); d.getElementById('areaSection').open=false; d.getElementById('measurementsSection').open=true; d.getElementById('settingsForm').scrollTop=0;")
                evidence = BASE_DIR / ".runtime-tmp"; evidence.mkdir(exist_ok=True)
                for width,height in [(1280,820),(1080,700)]:
                    window.resize(width,height); time.sleep(.25)
                    assert js("return d.documentElement.scrollWidth<=w.innerWidth && d.documentElement.scrollHeight<=w.innerHeight;")
                    assert js("return d.getElementById('previewSurface').getBoundingClientRect().height>150;")
                    screenshot(evidence / f"heatmap-estimation-{width}x{height}.png")
                    js("d.getElementById('areaSection').open=true; d.getElementById('openLayout').click();")
                    assert js("const r=d.getElementById('layoutDialog').getBoundingClientRect(); return r.width<w.innerWidth && r.height<w.innerHeight && r.left>=0 && r.top>=0;")
                    assert js("const r=d.getElementById('pointLayout').getBoundingClientRect(); return r.width>350 && r.height>250;")
                    js("d.getElementById('closeLayout').click(); d.getElementById('areaSection').open=false;")
                print("PASS: large layout popup, expandable X/Y and validation, free/snap drag, adjustable grid, IDW/linear/smooth, saved positions/model, PNG export, 2 layouts")
            except Exception:
                failures.append(traceback.format_exc())
            finally:
                window.destroy()
        webview.start(run, gui="edgechromium", storage_path=str(folder / "webview"))
    if failures: raise AssertionError("\n".join(failures))


if __name__ == "__main__":
    main()

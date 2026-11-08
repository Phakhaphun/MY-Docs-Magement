"""Check fixed-size measurement markers, local canvas zoom, pan and snapped drag."""

import base64
import json
from pathlib import Path
import sys
import time
import traceback

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import webview

from heatmap.settings import load_settings
from main_app import BASE_DIR, ManagementAPI, build_html
from tools.test_workspace import test_workspace


def main():
    failures=[]
    with test_workspace() as folder:
        folder=Path(folder)
        settings={**load_settings(), "area_width":59,"area_height":47,"area_unit":"cm",
                  "sensor_positions":[[7,7],[30,10],[50,10],[10,34],[30,34],[50,34]],
                  "layout_snap":True,"layout_grid_spacing":1}
        (folder/'heatmap_settings.json').write_text(json.dumps(settings),encoding='utf-8')
        api=ManagementAPI(folder)
        window=webview.create_window('Docspace · Layout zoom check',html=build_html(),js_api=api,
                                     width=1280,height=820,min_size=(1080,700))
        api._attach(window);window.events.loaded+=api._bind_drop

        def js(code):
            return window.evaluate_js("(() => {const w=document.getElementById('heatmap').contentWindow,d=w.document; "+code+"})()")
        def wait_for(check):
            deadline=time.monotonic()+25
            while time.monotonic()<deadline:
                if check():return
                time.sleep(.05)
            raise AssertionError('Layout zoom check timed out')
        def cdp(method,params):
            from System import Action
            tasks=[];control=window.native.webview
            control.Invoke(Action(lambda:tasks.append(control.CoreWebView2.CallDevToolsProtocolMethodAsync(method,json.dumps(params)))))
            assert tasks[0].Wait(10000)
            return json.loads(tasks[0].Result)
        def marker_size():
            return js("return d.querySelector('#pointLayout .layout-point circle').getBoundingClientRect().width;")
        def positions():
            return js("return Array.from({length:6},(_,i)=>[Number(d.getElementById('x'+(i+1)).value),Number(d.getElementById('y'+(i+1)).value)]);")
        def run():
            try:
                wait_for(lambda:window.evaluate_js("document.getElementById('connection').hidden"))
                window.evaluate_js("document.getElementById('heatmapTab').click()")
                wait_for(lambda:js("return !w.heatmapBusy && d.getElementById('previewImage').naturalWidth>0;"))
                js("d.getElementById('areaSection').open=true;d.getElementById('openLayout').click();")
                assert marker_size()<=24, 'Marker should stay small enough for precise placement'
                assert js("return !!d.getElementById('layoutZoomIn') && !!d.getElementById('layoutZoomOut') && !!d.getElementById('layoutFit');"), 'Canvas zoom controls are missing'
                original=positions()
                js("d.getElementById('layoutZoomIn').click();d.getElementById('layoutZoomIn').click();")
                assert js("return parseInt(d.getElementById('layoutZoomLabel').textContent);")>100
                assert abs(marker_size()-18)<1
                assert positions()==original
                # Ctrl+wheel must also stay inside the layout, with no page scaling.
                stage=js("const r=d.getElementById('layoutViewport').getBoundingClientRect(),frame=w.frameElement.getBoundingClientRect();return {x:r.left+frame.left+r.width/2,y:r.top+frame.top+r.height/2};")
                page_width=window.evaluate_js("window.innerWidth")
                cdp('Input.dispatchMouseEvent',{'type':'mouseWheel',**stage,'deltaX':0,'deltaY':-30,'modifiers':2})
                assert window.evaluate_js("window.innerWidth")==page_width
                assert positions()==original
                stage=js("const r=d.getElementById('layoutViewport').getBoundingClientRect(),frame=w.frameElement.getBoundingClientRect();return {x:r.left+frame.left+r.width/2,y:r.top+frame.top+r.height/2};")
                before=js("return d.getElementById('pointLayout').getBoundingClientRect().width;")
                cdp('Input.dispatchMouseEvent',{'type':'mouseWheel',**stage,'deltaX':0,'deltaY':-100})
                assert js("return d.getElementById('pointLayout').getBoundingClientRect().width;")>before
                assert abs(marker_size()-18)<1
                assert positions()==original
                # Drag empty canvas to pan: it must never change measured positions.
                pan=js("const r=d.getElementById('layoutViewport').getBoundingClientRect(),f=w.frameElement.getBoundingClientRect();return {x:f.left+r.left+40,y:f.top+r.top+40};")
                scroll_before=js("return [d.getElementById('layoutViewport').scrollLeft,d.getElementById('layoutViewport').scrollTop];")
                cdp('Input.dispatchMouseEvent',{'type':'mousePressed',**pan,'button':'left','clickCount':1})
                cdp('Input.dispatchMouseEvent',{'type':'mouseMoved','x':pan['x']-25,'y':pan['y']-20,'buttons':1})
                cdp('Input.dispatchMouseEvent',{'type':'mouseReleased','x':pan['x']-25,'y':pan['y']-20,'button':'left','clickCount':1})
                assert js("return [d.getElementById('layoutViewport').scrollLeft,d.getElementById('layoutViewport').scrollTop];")!=scroll_before
                assert positions()==original
                # Select a point from the list so it is visible even after panning.
                js("d.querySelector('.layout-point-item').click();")
                point=js("const r=d.querySelector('#pointLayout [data-point=\"0\"]').getBoundingClientRect(),f=w.frameElement.getBoundingClientRect();return {x:f.left+r.left+r.width/2,y:f.top+r.top+r.height/2};")
                cdp('Input.dispatchMouseEvent',{'type':'mousePressed',**point,'button':'left','clickCount':1})
                cdp('Input.dispatchMouseEvent',{'type':'mouseMoved','x':point['x']+35,'y':point['y']+22,'buttons':1})
                cdp('Input.dispatchMouseEvent',{'type':'mouseReleased','x':point['x']+35,'y':point['y']+22,'button':'left','clickCount':1})
                moved=positions()
                assert moved[0]!=original[0] and moved[1:]==original[1:]
                assert all(value==round(value) for value in moved[0])
                js("d.getElementById('layoutFit').click();")
                assert js("return d.getElementById('layoutZoomLabel').textContent;")=='100%'
                assert positions()==moved
                js("for(let i=0;i<30;i++)d.getElementById('layoutZoomIn').click();")
                assert js("return d.getElementById('layoutZoomLabel').textContent;")=='800%'
                assert abs(marker_size()-18)<1
                js("for(let i=0;i<30;i++)d.getElementById('layoutZoomOut').click();")
                assert js("return d.getElementById('layoutZoomLabel').textContent;")=='50%'
                assert positions()==moved
                js("d.getElementById('layoutFit').click();")
                assert js("return d.querySelectorAll('#layoutMini .point-hit').length;")==0
                evidence=BASE_DIR/'.runtime-tmp';evidence.mkdir(exist_ok=True)
                (evidence/'heatmap-layout-zoom.png').write_bytes(base64.b64decode(cdp('Page.captureScreenshot',{'format':'png'})['data']))
                for width,height in [(1080,700),(1280,820)]:
                    window.resize(width,height);time.sleep(.2)
                    assert abs(marker_size()-18)<1
                    assert js("const r=d.getElementById('layoutDialog').getBoundingClientRect();return r.width<w.innerWidth && r.height<w.innerHeight;")
                print('PASS: small fixed markers, canvas buttons/wheel zoom, pan without changing coordinates, snapped drag while zoomed, Fit and 2 layouts')
            except Exception:
                failures.append(traceback.format_exc())
            finally:window.destroy()
        webview.start(run,gui='edgechromium',storage_path=str(folder/'webview'))
    if failures:raise AssertionError('\n'.join(failures))


if __name__=='__main__':main()

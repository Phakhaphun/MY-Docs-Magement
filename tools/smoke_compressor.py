"""Exercise compression through the actual native multi-workspace WebView bridge."""
import base64
import json
from pathlib import Path
import sys
import time
import traceback

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import pymupdf
from PIL import Image
import webview
from main_app import BASE_DIR, ManagementAPI, build_html
from tools.test_workspace import test_workspace


def main():
    failures=[]
    with test_workspace() as folder:
        folder=Path(folder)
        Image.effect_noise((1600,1600),55).convert('RGB').save(folder/'image.png')
        source=folder/'Measurement report.pdf'
        with pymupdf.open() as doc:
            page=doc.new_page(width=400,height=400)
            page.insert_image(pymupdf.Rect(10,10,390,350),filename=str(folder/'image.png'))
            page.insert_text((20,380),'Searchable document')
            doc.save(source)
        api=ManagementAPI(folder)
        api._compressor._state['output']=str(folder/'output')
        window=webview.create_window('Docspace · Compression check',html=build_html(),js_api=api,
                                    width=1280,height=820,min_size=(1080,700))
        api._attach(window)
        window.events.loaded+=api._bind_drop

        def js(code):
            return window.evaluate_js("(()=>{const w=document.getElementById('compressor').contentWindow,d=w.document;"+code+"})()")
        def wait(check):
            deadline=time.monotonic()+35
            while time.monotonic()<deadline:
                if check():return
                time.sleep(.1)
            raise AssertionError('Compression UI timed out')
        def screenshot(path):
            from System import Action
            tasks=[];control=window.native.webview
            control.Invoke(Action(lambda:tasks.append(control.CoreWebView2.CallDevToolsProtocolMethodAsync('Page.captureScreenshot',json.dumps({'format':'png'})))))
            assert tasks[0].Wait(10000)
            path.write_bytes(base64.b64decode(json.loads(tasks[0].Result)['data']))
        def run():
            try:
                wait(lambda:window.evaluate_js("document.getElementById('connection').hidden"))
                window.evaluate_js("document.getElementById('compressorTab').click()")
                wait(lambda:js("return !d.getElementById('emptyState').hidden;"))
                assert js("return d.getElementById('compress').disabled;")
                # Native drop handler must route to this independent queue.
                api._on_drop({'dataTransfer':{'files':[{'pywebviewFullPath':str(source)}]}})
                wait(lambda:js("return d.getElementById('fileCount').textContent==='1';"))
                assert not api._documents.get_state()['files']
                assert api._heatmap_instance is None
                js("d.getElementById('compress').click()")
                wait(lambda:js("return d.getElementById('status').textContent==='Compression complete';"))
                result=api._compressor.get_state()
                assert result['completed']==1 and not result['failed']
                item=result['files'][0]
                assert item['after_size']<item['before_size']*.5
                assert js("return d.querySelector('.file-sizes b').textContent.length>0 && !d.getElementById('openOutput').hidden;")
                with pymupdf.open(item['output']) as doc:
                    assert 'Searchable document' in doc[0].get_text()
                window.evaluate_js("document.getElementById('documentsTab').click();document.getElementById('compressorTab').click()")
                assert js("return d.getElementById('fileCount').textContent;")=='1'
                evidence=BASE_DIR/'.runtime-tmp';evidence.mkdir(exist_ok=True)
                for width,height in [(1280,820),(1080,700)]:
                    window.resize(width,height);time.sleep(.25)
                    assert js("return d.documentElement.scrollWidth<=w.innerWidth && d.documentElement.scrollHeight<=w.innerHeight;")
                    assert js("const r=d.getElementById('compress').getBoundingClientRect();return r.right<=w.innerWidth && r.bottom<=w.innerHeight;")
                    screenshot(evidence/f'compressor-{width}x{height}.png')
                # Cancel a real queued batch from the visible red button.
                for index in range(4):
                    path=folder/f'batch-{index}.pdf';path.write_bytes(source.read_bytes())
                    api._compressor._add_files([str(path)])
                wait(lambda:js("return d.getElementById('fileCount').textContent==='5';"))
                js("d.getElementById('compress').click()")
                wait(lambda:js("return !d.getElementById('cancel').hidden;"))
                js("d.getElementById('cancel').click()")
                wait(lambda:not api._compressor.get_state()['running'])
                assert api._compressor.get_state()['result']['cancelled']
                assert not list((folder/'output').rglob('*.partial'))
                wait(lambda:js("return !d.getElementById('compress').disabled;"))
                js("d.getElementById('clearFiles').click()")
                wait(lambda:js("return d.getElementById('fileCount').textContent==='0';"))
                print(f"PASS: Compress PDF bridge/drop, balanced output {item['before_size']} -> {item['after_size']} bytes, retained queue, cancel, clear, 2 window sizes")
            except Exception:
                failures.append(traceback.format_exc())
            finally:window.destroy()
        webview.start(run,gui='edgechromium',storage_path=str(folder/'webview'))
    if failures:raise AssertionError('\n'.join(failures))


if __name__=='__main__':main()

"""Run multilingual CPU OCR, optional model download and cancellation in WebView2."""
import base64
import json
from pathlib import Path
import sys
import time
import traceback
from unittest.mock import Mock

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import pymupdf
import webview
from main_app import BASE_DIR,ManagementAPI,build_html
from tests.test_ocr import make_scan
from tools.test_workspace import test_workspace


def main():
    failures=[]
    with test_workspace() as folder:
        folder=Path(folder)
        source=make_scan(folder/'Bilingual scan.pdf')
        api=ManagementAPI(folder)
        api._ocr._state['output']=str(folder/'output')
        window=webview.create_window('Docspace · CPU OCR check',html=build_html(),js_api=api,width=1280,height=820,min_size=(1080,700))
        api._attach(window);window.events.loaded+=api._bind_drop
        def js(code):
            return window.evaluate_js("(()=>{const w=document.getElementById('ocr').contentWindow,d=w.document;"+code+"})()")
        def wait(check):
            deadline=time.monotonic()+45
            while time.monotonic()<deadline:
                if check():return
                time.sleep(.1)
            raise AssertionError('OCR UI timed out')
        def screenshot(path):
            from System import Action
            tasks=[];control=window.native.webview
            control.Invoke(Action(lambda:tasks.append(control.CoreWebView2.CallDevToolsProtocolMethodAsync('Page.captureScreenshot','{"format":"png"}'))))
            assert tasks[0].Wait(10000)
            path.write_bytes(base64.b64decode(json.loads(tasks[0].Result)['data']))
        def run():
            try:
                wait(lambda:window.evaluate_js("document.getElementById('connection').hidden"))
                assert api._heatmap_instance is None
                window.evaluate_js("document.getElementById('ocrTab').click()")
                wait(lambda:js("return !d.getElementById('chooseLanguages').disabled;"))
                assert js("return d.getElementById('startOCR').disabled;")
                api._on_drop({'dataTransfer':{'files':[{'pywebviewFullPath':str(source)}]}})
                wait(lambda:js("return d.getElementById('fileCount').textContent==='1';"))
                assert not api._documents.get_state()['files']
                assert not api._compressor.get_state()['files']
                js("d.getElementById('chooseLanguages').click();d.getElementById('languageSearch').value='French';d.getElementById('languageSearch').dispatchEvent(new Event('input'));")
                assert js("return d.getElementById('languageList').textContent.includes('French');")
                js("d.querySelector('#languageList input[value=fra]').click();d.getElementById('closeLanguages').click();")
                needs_download=js("return !d.getElementById('downloadLanguages').hidden;")
                if needs_download:
                    assert js("return d.getElementById('startOCR').disabled;")
                    js("d.getElementById('downloadLanguages').click();")
                    wait(lambda:api._ocr.get_state().get('result',{}).get('operation')=='download' if api._ocr.get_state().get('result') else False)
                    assert not api._ocr.get_state()['result'].get('error'),api._ocr.get_state()
                    wait(lambda:js("return !d.getElementById('startOCR').disabled;"))
                    assert not js("return d.getElementById('completionDialog').open;"),'Language downloads must not open the PDF completion popup'
                js("d.getElementById('chooseLanguages').click();d.querySelector('#languageList input[value=fra]').click();d.getElementById('closeLanguages').click();")
                assert js("return d.querySelector('.destination-change').textContent;")=='Change folder'
                js("d.getElementById('startOCR').click();")
                wait(lambda:js("return d.getElementById('status').textContent.startsWith('OCR complete');"))
                wait(lambda:js("return !!d.getElementById('completionDialog')?.open;"))
                assert js("return d.getElementById('completionTitle').textContent;")=='Searchable PDFs created'
                assert js("return d.getElementById('completionSummary').textContent.includes('1 PDF');")
                assert js("return !d.getElementById('completionOpenOutput').hidden;")
                evidence=BASE_DIR/'.runtime-tmp';evidence.mkdir(exist_ok=True)
                screenshot(evidence/'ocr-complete.png')
                open_folder=api._ocr.open_output
                api._ocr.open_output=Mock(return_value={'ok':True})
                js("d.getElementById('completionOpenOutput').click();")
                wait(lambda:api._ocr.open_output.called)
                api._ocr.open_output=open_folder
                js("d.getElementById('completionDone').click();")
                time.sleep(.6)
                assert not js("return d.getElementById('completionDialog').open;"),'Polling must not reopen a dismissed completion'
                result=api._ocr.get_state();item=result['files'][0]
                assert result['completed']==1 and result['failed']==0
                assert item['text_pages']==1
                with pymupdf.open(item['output']) as output,pymupdf.open(source) as original:
                    text=output[0].get_text()
                    assert '12345' in text and 'ภาษาไทย' in ''.join(text.split())
                    assert output[0].get_pixmap().samples==original[0].get_pixmap().samples
                window.evaluate_js("document.getElementById('documentsTab').click();document.getElementById('ocrTab').click()")
                assert js("return d.getElementById('fileCount').textContent;")=='1'
                evidence=BASE_DIR/'.runtime-tmp';evidence.mkdir(exist_ok=True)
                for width,height in [(1280,820),(1080,700)]:
                    window.resize(width,height);time.sleep(.25)
                    assert js("return d.documentElement.scrollWidth<=w.innerWidth && d.documentElement.scrollHeight<=w.innerHeight;")
                    assert js("const r=d.getElementById('startOCR').getBoundingClientRect();return r.right<=w.innerWidth&&r.bottom<=w.innerHeight;")
                    screenshot(evidence/f'ocr-{width}x{height}.png')
                js("d.getElementById('chooseLanguages').click();")
                assert js("const r=d.getElementById('languageDialog').getBoundingClientRect();return r.width<w.innerWidth&&r.height<w.innerHeight;")
                screenshot(evidence/'ocr-languages.png')
                js("d.getElementById('closeLanguages').click();")
                for index in range(4):
                    copy=folder/f'cancel-{index}.pdf';copy.write_bytes(source.read_bytes());api._ocr._add_files([str(copy)])
                wait(lambda:js("return d.getElementById('fileCount').textContent==='5';"))
                js("d.getElementById('startOCR').click();")
                wait(lambda:js("return !d.getElementById('cancel').hidden;"))
                js("d.getElementById('cancel').click();")
                wait(lambda:not api._ocr.get_state()['running'])
                assert api._ocr.get_state()['result']['cancelled']
                wait(lambda:js("return d.getElementById('completionDialog').open;"))
                assert js("return d.getElementById('completionTitle').textContent;")=='OCR cancelled'
                assert js("const r=d.getElementById('completionDialog').getBoundingClientRect();return r.width<w.innerWidth&&r.height<w.innerHeight;")
                js("d.getElementById('completionDone').click();")
                assert not list((folder/'output').rglob('*.partial'))
                # A file removed after queuing must show failure, not a success tick.
                js("d.getElementById('clearFiles').click();")
                wait(lambda:js("return d.getElementById('fileCount').textContent==='0';"))
                missing=folder/'missing.pdf';missing.write_bytes(source.read_bytes())
                api._ocr._add_files([str(missing)]);missing.unlink()
                wait(lambda:js("return !d.getElementById('startOCR').disabled;"))
                js("d.getElementById('startOCR').click();")
                wait(lambda:js("return d.getElementById('completionDialog').open;"))
                assert js("return d.getElementById('completionTitle').textContent;")=='Could not create searchable PDFs'
                assert js("return d.getElementById('completionOpenOutput').hidden;")
                assert js("return d.getElementById('completionSummary').textContent.includes('1 failed');")
                js("d.getElementById('completionDone').click();")
                js("d.getElementById('clearFiles').click();")
                wait(lambda:js("return d.getElementById('fileCount').textContent==='0';"))
                missing.write_bytes(source.read_bytes())
                api._ocr._add_files([str(source),str(missing)]);missing.unlink()
                wait(lambda:js("return d.getElementById('fileCount').textContent==='2';"))
                js("d.getElementById('startOCR').click();")
                wait(lambda:js("return d.getElementById('completionDialog').open;"))
                assert js("return d.getElementById('completionTitle').textContent;")=='Completed with errors'
                assert js("return !d.getElementById('completionOpenOutput').hidden;")
                js("d.getElementById('completionDone').click();")
                print(f'PASS: real multilingual CPU OCR; language download ({needs_download}); popup success/cancel/failure/partial error, Done without reopen, Open folder bridge, independent queue and 2 layouts')
            except Exception:failures.append(traceback.format_exc())
            finally:window.destroy()
        webview.start(run,gui='edgechromium',storage_path=str(folder/'webview'))
    if failures:raise AssertionError('\n'.join(failures))


if __name__=='__main__':main()

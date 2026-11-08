"""Exercise the image grid, real PDF export and OCR/compression continuation."""
import base64
import json
from pathlib import Path
import sys
import time
import traceback

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PIL import Image,ImageDraw,ImageFont
import pymupdf
import webview
from main_app import BASE_DIR,ManagementAPI,build_html
from tools.test_workspace import test_workspace


def main():
    failures=[]
    with test_workspace() as folder:
        folder=Path(folder);sources=[]
        for index,(name,extension) in enumerate([('Receipt','.jpg'),('Inspection','.png'),('Photo','.webp'),('รายการตรวจ','.png')],1):
            path=folder/(name+extension)
            image=Image.new('RGB',(700,950),'white');draw=ImageDraw.Draw(image)
            draw.rectangle((0,0,700,115),fill=['#2563c6','#238670','#ab7643','#6e64b7'][index-1])
            font=ImageFont.truetype('C:/Windows/Fonts/tahoma.ttf',36)
            draw.text((40,35),'DOCUMENT '+str(index),font=font,fill='white')
            for row in range(7):draw.text((40,170+row*80),'Item '+str(row+1)+'   1,250.50',font=font,fill='#18324d')
            image.save(path);sources.append(path)
        api=ManagementAPI(folder);api._imagepdf._state['output']=str(folder/'output')
        window=webview.create_window('Docspace · Image to PDF check',html=build_html(),js_api=api,width=1280,height=820,min_size=(1080,700))
        api._attach(window);window.events.loaded+=api._bind_drop
        def js(code):return window.evaluate_js("(()=>{const w=document.getElementById('imagepdf').contentWindow,d=w.document;"+code+"})()")
        def wait(check):
            deadline=time.monotonic()+35
            while time.monotonic()<deadline:
                if check():return
                time.sleep(.08)
            raise AssertionError('Image to PDF UI timed out')
        def screenshot(path):
            from System import Action
            tasks=[];control=window.native.webview
            control.Invoke(Action(lambda:tasks.append(control.CoreWebView2.CallDevToolsProtocolMethodAsync('Page.captureScreenshot','{"format":"png"}'))))
            assert tasks[0].Wait(10000)
            path.write_bytes(base64.b64decode(json.loads(tasks[0].Result)['data']))
        def run():
            try:
                wait(lambda:window.evaluate_js("document.getElementById('connection').hidden"))
                evidence=BASE_DIR/'.runtime-tmp';evidence.mkdir(exist_ok=True)
                version=(BASE_DIR/'VERSION').read_text(encoding='utf-8').strip()
                assert window.evaluate_js("document.querySelector('.local').textContent.includes("+json.dumps(version)+")")
                window.evaluate_js("document.getElementById('imagepdfTab').click()")
                api._on_drop({'dataTransfer':{'files':[{'pywebviewFullPath':str(path)} for path in sources]}})
                wait(lambda:js("return d.querySelectorAll('.image-card').length===4;"))
                wait(lambda:js("return d.querySelectorAll('.thumb img:not([hidden])').length===4;"))
                assert js("return d.querySelectorAll('#pageSize option').length;")>=17
                assert not api._documents.get_state()['files']
                js("d.getElementById('sortImages').value='az';d.getElementById('sortImages').dispatchEvent(new Event('change'));")
                wait(lambda:api._imagepdf.get_state()['files'][0]['name']=='Inspection.png')
                wait(lambda:js("return !d.getElementById('sortImages').disabled;"))
                js("const cards=d.querySelectorAll('.image-card'),transfer=new DataTransfer();cards[3].dispatchEvent(new DragEvent('dragstart',{dataTransfer:transfer,bubbles:true}));cards[0].dispatchEvent(new DragEvent('drop',{dataTransfer:transfer,bubbles:true,cancelable:true}));")
                wait(lambda:api._imagepdf.get_state()['files'][0]['name']==sources[3].name)
                wait(lambda:js("return !d.querySelector('[data-action=rotateRight]').disabled;"))
                js("d.querySelector('[data-action=rotateRight]').click();")
                wait(lambda:api._imagepdf.get_state()['files'][0]['rotation']==90)
                wait(lambda:js("return !d.querySelector('[data-action=right]').disabled;"))
                js("d.querySelector('[data-action=right]').click();")
                wait(lambda:api._imagepdf.get_state()['files'][1]['name']==sources[3].name)
                wait(lambda:js("return !d.querySelector('[data-action=remove]').disabled;"))
                js("d.querySelectorAll('[data-action=remove]')[3].click();")
                wait(lambda:js("return d.querySelectorAll('.image-card').length===3;"))
                js("d.getElementById('pageSize').value='original';d.getElementById('pageSize').dispatchEvent(new Event('input'));")
                assert js("return d.getElementById('orientation').disabled;")
                js("d.getElementById('pageSize').value='legal';d.getElementById('pageSize').dispatchEvent(new Event('input'));d.querySelector('[data-orientation=portrait]').click();d.querySelector('[data-margin=\"20\"]').click();")
                assert js("return d.getElementById('paperDimensions').textContent.includes('355.6');")
                assert js("const r=d.querySelector('.paper-preview').getBoundingClientRect();return Math.abs(r.width/r.height-215.9/355.6)<.015;")
                assert js("return d.getElementById('margin').value;")=='20'
                screenshot(evidence/'image-pdf-page-setup.png')
                js("d.getElementById('pageSize').value='custom';d.getElementById('customWidth').value='320';d.getElementById('customHeight').value='180';d.getElementById('pageSize').dispatchEvent(new Event('input'));")
                assert js("return !d.getElementById('customSizeFields').hidden&&d.getElementById('orientation').disabled;")
                js("d.getElementById('swapDimensions').click();")
                assert js("return d.getElementById('customWidth').value;")=='180'
                js("d.getElementById('swapDimensions').click();d.getElementById('customWidth').value='20';d.getElementById('margin').value='10';d.getElementById('customWidth').dispatchEvent(new Event('input'));")
                assert js("return d.getElementById('createPDF').disabled&&!d.getElementById('layoutError').hidden;")
                js("d.getElementById('customWidth').value='320';d.getElementById('margin').value='8';d.getElementById('margin').dispatchEvent(new Event('input'));")
                assert js("return d.getElementById('layoutError').hidden;")
                assert js("const r=d.querySelector('.paper-preview').getBoundingClientRect();return Math.abs(r.width/r.height-320/180)<.015;")
                evidence=BASE_DIR/'.runtime-tmp';evidence.mkdir(exist_ok=True)
                for width,height in [(1280,820),(1080,700)]:
                    window.resize(width,height);time.sleep(.25)
                    assert js("return d.documentElement.scrollWidth<=w.innerWidth&&d.documentElement.scrollHeight<=w.innerHeight;")
                    assert js("return [...d.querySelectorAll('.thumb img:not([hidden])')].every(image=>{const r=image.getBoundingClientRect(),p=image.parentElement.getBoundingClientRect();return r.left>=p.left-.5&&r.right<=p.right+.5&&r.top>=p.top-.5&&r.bottom<=p.bottom+.5;});"),'Rotated previews must fit inside their cards'
                    assert js("return d.getElementById('chooseOutput').getBoundingClientRect().bottom<=d.querySelector('.settings').getBoundingClientRect().bottom;"),'Folder picker should remain visible'
                    assert window.evaluate_js("document.querySelector('.local').getBoundingClientRect().bottom<=innerHeight")
                    screenshot(evidence/f'image-pdf-{width}x{height}.png')
                js("d.getElementById('createPDF').click();")
                wait(lambda:js("return d.getElementById('completionDialog').open;"))
                result=api._imagepdf.get_state()['result'];assert not result['error'],result
                assert len(result['paths'])==1
                with pymupdf.open(result['paths'][0]) as doc:
                    assert doc.page_count==3
                    assert abs(doc[0].rect.width-320*72/25.4)<.02
                    assert abs(doc[0].rect.height-180*72/25.4)<.02
                screenshot(evidence/'image-pdf-complete.png')
                js("d.getElementById('continueOCR').click();")
                wait(lambda:window.evaluate_js("!document.getElementById('ocr').hidden"))
                wait(lambda:len(api._ocr.get_state()['files'])==1)
                assert api._ocr.get_state()['files'][0]['path']==result['paths'][0]
                window.evaluate_js("document.getElementById('imagepdfTab').click()")
                js("d.getElementById('viewResult').click();d.getElementById('continueCompress').click();")
                wait(lambda:window.evaluate_js("!document.getElementById('compressor').hidden"))
                assert api._compressor.get_state()['files'][0]['path']==result['paths'][0]
                window.evaluate_js("document.getElementById('imagepdfTab').click()")
                assert js("return d.getElementById('margin').value;")=='8'
                js("d.getElementById('mode').value='separate';d.getElementById('mode').dispatchEvent(new Event('input'));d.getElementById('createPDF').click();")
                wait(lambda:js("return d.getElementById('completionDialog').open;"))
                assert len(api._imagepdf.get_state()['result']['paths'])==3
                js("d.getElementById('completionDone').click();")
                time.sleep(.6);assert not js("return d.getElementById('completionDialog').open;")
                js("d.getElementById('mode').value='combine';d.getElementById('mode').dispatchEvent(new Event('input'));d.getElementById('createPDF').click();")
                wait(lambda:js("return !d.getElementById('cancel').hidden;"))
                js("d.getElementById('cancel').click();")
                wait(lambda:js("return d.getElementById('completionDialog').open;"))
                assert api._imagepdf.get_state()['result']['cancelled']
                assert js("return d.getElementById('nextSteps').hidden;")
                assert not list((folder/'output').rglob('*.partial'))
                print('PASS: native image grid/drop, thumbnails, drag/arrows/rotation/remove, paper controls, combined/separate PDFs, retained settings, OCR/compression handoff, cancellation, popup and 2 layouts')
            except Exception:failures.append(traceback.format_exc())
            finally:window.destroy()
        webview.start(run,gui='edgechromium',storage_path=str(folder/'webview'))
    if failures:raise AssertionError('\n'.join(failures))


if __name__=='__main__':main()

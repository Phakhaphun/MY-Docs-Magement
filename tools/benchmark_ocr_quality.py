"""Generate shaped-font scanned PDFs and measure real CPU OCR error, time and memory.

No network, GPU, mocked OCR, or changes to the source PDFs. Run from the project venv.
"""
import argparse
import csv
import ctypes
from contextlib import ExitStack
from html import escape
from io import BytesIO
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
import time
import unicodedata

os.environ['OMP_THREAD_LIMIT']='1'
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

SIZES=(6,8,9,10,12,14,16)
FONTS=(('Tahoma','tahoma.ttf','English'),('Arial','arial.ttf','English'),
       ('Times New Roman','times.ttf','English'),('Tahoma','tahoma.ttf','Thai'),
       ('Angsana New','angsana.ttc','Thai'),('Cordia New','cordia.ttc','Thai'))
TEXT={
    'English':('Invoice AB-12345 Total 1,250.50 THB','Quick brown fox jumps over the lazy dog.'),
    'Thai':('ภาษาไทย ทดสอบเอกสาร เลขที่ 12345','วันที่ 08/11/2026 จำนวนเงิน 1,250.50 บาท'),
}


def normalized(text):
    # Thai sara am can be encoded as U+0E33 or U+0E4D U+0E32. Compare
    # compatibility-equivalent text fairly; retain case and punctuation errors.
    return ''.join(unicodedata.normalize('NFKC',text).split())


def edit_distance(expected,actual):
    previous=list(range(len(actual)+1))
    for index,left in enumerate(expected,1):
        current=[index]
        for column,right in enumerate(actual,1):
            current.append(min(current[-1]+1,previous[column]+1,previous[column-1]+(left!=right)))
        previous=current
    return previous[-1]


def make_samples(folder):
    import pymupdf
    from PIL import Image,ImageFilter
    folder.mkdir(parents=True,exist_ok=True)
    font_root=Path(os.environ.get('WINDIR','C:/Windows'))/'Fonts'
    for _,filename,_ in FONTS:
        if not (font_root/filename).is_file():raise FileNotFoundError(font_root/filename)
    manifest=[]
    with pymupdf.open() as reference,pymupdf.open() as clean,pymupdf.open() as degraded:
        for number,(name,filename,language) in enumerate(FONTS):
            page=reference.new_page(width=595.276,height=841.89)
            page.insert_text((42,40),'Docspace OCR font and size test',fontsize=18,color=(.1,.2,.3))
            page.insert_text((42,62),f'{name} / {language} / source 300 DPI',fontsize=11)
            page.insert_text((42,79),'Synthetic samples. Sizes are physical points. No handwriting.',fontsize=9)
            css=f"@font-face{{font-family:Fixture;src:url('{filename}')}} body{{font-family:Fixture;margin:0;padding:0}} p{{margin:0;line-height:1.6}}"
            for row,point_size in enumerate(SIZES):
                top=112+row*92
                page.insert_text((23,top+12),f'{point_size}pt',fontsize=8,color=(.4,.5,.6))
                page.draw_line((55,top-5),(553,top-5),color=(.87,.9,.94),width=.4)
                bounds=pymupdf.Rect(58,top,553,top+73)
                body='<p style="font-size:'+str(point_size)+'pt">'+'<br>'.join(map(escape,TEXT[language]))+'</p>'
                spare,scale=page.insert_htmlbox(bounds,body,css=css,archive=pymupdf.Archive(str(font_root)),scale_low=1)
                if spare<0 or scale<.999:raise ValueError('Sample text does not fit at the declared size')
                manifest.append({'page':number,'font':name,'font_file':filename,'language':language,
                    'points':point_size,'rect':list(bounds),'expected':'\n'.join(TEXT[language])})
            page.insert_text((42,812),f'{number+1}/6 - Use samples-clean.pdf or samples-low-quality.pdf for OCR; this reference has selectable text.',fontsize=8)
            pix=page.get_pixmap(dpi=300,alpha=False)
            pixels=Image.frombytes('RGB',(pix.width,pix.height),pix.samples)
            for document,low_quality in ((clean,False),(degraded,True)):
                output_page=document.new_page(width=page.rect.width,height=page.rect.height)
                if low_quality:
                    # Deliberately reduce source detail; higher OCR DPI cannot restore it.
                    image=pixels.resize((round(pix.width/2),round(pix.height/2)),Image.Resampling.LANCZOS).filter(ImageFilter.GaussianBlur(.35))
                    stream=BytesIO();image.save(stream,format='JPEG',quality=45);data=stream.getvalue()
                else:data=pix.tobytes('png')
                output_page.insert_image(output_page.rect,stream=data)
        reference.save(folder/'reference-selectable.pdf',garbage=4,deflate=True)
        clean.save(folder/'samples-clean.pdf',garbage=4,deflate=True)
        degraded.save(folder/'samples-low-quality.pdf',garbage=4,deflate=True)
    (folder/'ground-truth.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    for name in ('samples-clean','samples-low-quality'):
        with pymupdf.open(folder/f'{name}.pdf') as document:
            assert all(not page.get_text().strip() for page in document),'OCR input must be genuinely image-only'
            document[3].get_pixmap(dpi=140).save(folder/f'{name}-preview.png')
    return manifest


def peak_memory_mb():
    if os.name!='nt':return None
    class Counters(ctypes.Structure):
        _fields_=[('cb',ctypes.c_ulong),('faults',ctypes.c_ulong)]+[(name,ctypes.c_size_t) for name in (
            'peak','working','peak_paged','paged','peak_nonpaged','nonpaged','pagefile','peak_pagefile')]
    info=Counters();info.cb=ctypes.sizeof(info)
    kernel=ctypes.windll.kernel32;kernel.GetCurrentProcess.restype=ctypes.c_void_p
    api=ctypes.windll.psapi.GetProcessMemoryInfo
    api.argtypes=[ctypes.c_void_p,ctypes.c_void_p,ctypes.c_ulong]
    if not api(kernel.GetCurrentProcess(),ctypes.byref(info),info.cb):raise ctypes.WinError()
    return info.peak/1048576


def worker(folder,profile,variant,condition,label):
    import pymupdf
    from unittest.mock import patch
    from ocr_pdf import ocr_pdf
    original=pymupdf.Page.get_pixmap
    def candidate(page,*args,**kwargs):
        if variant=='gray':kwargs['colorspace']=pymupdf.csGRAY
        return original(page,*args,**kwargs)
    def progress(done,total):
        if variant=='release-cache':pymupdf.TOOLS.store_shrink(100)
    source=folder/f'samples-{condition}.pdf'
    started=time.perf_counter()
    # Only the rendering color space changes in this experiment. OCR is real.
    with ExitStack() as experiment:
        experiment.enter_context(patch.object(pymupdf.Page,'get_pixmap',candidate))
        if variant=='retain-cache':
            experiment.enter_context(patch.object(pymupdf.TOOLS,'store_shrink',lambda _:None))
        result=ocr_pdf(source,folder/'results'/label/f'{condition}-{profile}',languages=['eng','tha'],profile=profile,on_progress=progress)[0]
    elapsed=time.perf_counter()-started
    peak=peak_memory_mb()
    rows=[]
    with pymupdf.open(result) as document,pymupdf.open(source) as before:
        identical=all(original(page,dpi=72).samples==original(before[index],dpi=72).samples for index,page in enumerate(document))
        for expected in json.loads((folder/'ground-truth.json').read_text(encoding='utf-8')):
            text=document[expected['page']].get_text('text',clip=pymupdf.Rect(expected['rect']),sort=True)
            actual=normalized(text);truth=normalized(expected['expected'])
            digits=lambda value:''.join(re.findall(r'\d',value))
            rows.append({**expected,'actual':text,'characters':len(truth),'errors':edit_distance(truth,actual),
                'digits_exact':digits(text)==digits(expected['expected']), 'profile':profile,'condition':condition})
    return {'profile':profile,'variant':variant,'condition':condition,'seconds':elapsed,
        'peak_mb':peak,'pdf':str(result.relative_to(folder)),'visual_identical':identical,'rows':rows}


def run_benchmark(folder,label,variant,profiles):
    all_results=[]
    for condition in ('clean','low-quality'):
        for profile in profiles:
            command=[sys.executable,str(Path(__file__).resolve()),'--worker','--output',str(folder),
                '--label',label,'--variant',variant,'--profiles',profile,'--condition',condition]
            result=subprocess.run(command,capture_output=True,text=True,encoding='utf-8',
                creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0,timeout=240)
            if result.returncode:raise RuntimeError(result.stdout+'\n'+result.stderr)
            data=json.loads(result.stdout);all_results.append(data)
            errors=sum(row['errors'] for row in data['rows']);count=sum(row['characters'] for row in data['rows'])
            print(f"{label} {condition} {profile}: CER {errors/count*100:.2f}% | {data['seconds']:.2f}s | peak {data['peak_mb']:.1f} MB",flush=True)
    report={'environment':{'platform':platform.platform(),'python':platform.python_version(),'cpu':platform.processor(),
        'languages':['eng','tha'],'threads':1,'variant':variant},'results':all_results}
    (folder/f'{label}.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    with (folder/f'{label}.csv').open('w',encoding='utf-8-sig',newline='') as stream:
        fields=['condition','profile','language','font','points','characters','errors','digits_exact','actual']
        writer=csv.DictWriter(stream,fields,extrasaction='ignore');writer.writeheader()
        for item in all_results:writer.writerows(item['rows'])


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=ROOT/'output'/'pdf'/'ocr-test-kit')
    parser.add_argument('--generate',action='store_true')
    parser.add_argument('--label',default='current')
    parser.add_argument('--variant',choices=['rgb','gray','release-cache','retain-cache'],default='rgb')
    parser.add_argument('--profiles',nargs='+',default=['light','balanced','detailed'])
    parser.add_argument('--condition',default='clean')
    parser.add_argument('--worker',action='store_true')
    options=parser.parse_args();folder=options.output.resolve()
    if options.worker:
        print(json.dumps(worker(folder,options.profiles[0],options.variant,options.condition,options.label),ensure_ascii=True));return
    if options.generate:make_samples(folder)
    run_benchmark(folder,options.label,options.variant,options.profiles)


if __name__=='__main__':main()

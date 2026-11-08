"""CPU-only searchable PDF workspace with explicit offline language management."""
import json
from pathlib import Path
from threading import Thread
from uuid import uuid4

from doc_app import DocumentAPI
from ocr_languages import download_languages, language_status, require_languages, validate_languages
from ocr_pdf import PROFILES
from pdf_to_jpg import BASE_DIR, ConversionCancelled
from pdf_worker import ocr_in_process
from ui_components import bundle_output_picker


class OCRAPI(DocumentAPI):
    def __init__(self, settings_path=None):
        super().__init__(settings_path or BASE_DIR/'ocr_settings.json')
        languages,profile=['eng','tha'],'balanced'
        try:
            data=json.loads(self._settings_path.read_text(encoding='utf-8'))
            languages=validate_languages(data.get('ocr_languages',languages))
            if data.get('ocr_profile') in PROFILES:profile=data['ocr_profile']
        except (OSError,ValueError,AttributeError,TypeError):
            pass
        self._state.update(languages=languages,profile=profile,operation='ocr',message='Add scanned PDFs to make their text searchable.')

    def get_languages(self):
        return {'languages':language_status(),'selected':self._state['languages'],'profile':self._state['profile']}

    def _remember_options(self,languages,profile):
        self._state.update(languages=languages,profile=profile)
        self._recent.update(ocr_languages=languages,ocr_profile=profile)
        self._remember()

    def install_languages(self,languages):
        with self._lock:
            if self._state['running']:return {'error':'Wait for the current operation to finish.'}
            try:languages=validate_languages(languages)
            except ValueError as exc:return {'error':str(exc)}
            self._remember_options(languages,self._state['profile'])
            self._cancel.clear()
            self._state.update(running=True,cancelling=False,operation='download',progress=0,result=None,message='Downloading language packs…')
            self._thread=Thread(target=self._install,args=(languages,),daemon=True)
            self._thread.start()
            return self.get_state()

    def _install(self,languages):
        error=''
        def progress(done,total):
            with self._lock:
                self._state['progress']=done/total*100
        try:
            download_languages(languages,on_progress=progress,should_cancel=self._cancel.is_set)
        except ConversionCancelled:
            pass
        except Exception as exc:
            error=f'Could not download languages. Check your internet connection and folder permissions. {exc}'
        finally:
            with self._lock:
                cancelled=self._cancel.is_set()
                self._state.update(running=False,cancelling=False,
                    message=error or ('Language download cancelled' if cancelled else 'Language packs ready · OCR works offline'),
                    result={'id':uuid4().hex,'paths':[],'operation':'download','cancelled':cancelled,'error':error})

    def start(self,languages,profile='balanced'):
        with self._lock:
            if self._state['running']:return {'error':'OCR is already running.'}
            try:
                languages=require_languages(languages)
                if not isinstance(profile,str) or profile not in PROFILES:raise ValueError('Choose a processing profile.')
                if not self._files or any(not item['pages'] for item in self._files):
                    raise ValueError('Add readable PDFs and remove any invalid files first.')
            except ValueError as exc:return {'error':str(exc)}
            self._remember_options(languages,profile)
            for item in self._files:item.update(status='waiting',detail='Waiting',output='',text_pages=None)
            jobs=[dict(item) for item in self._files]
            self._cancel.clear()
            self._state.update(running=True,cancelling=False,operation='ocr',completed=0,failed=0,progress=0,result=None,message='Preparing CPU OCR…')
            self._thread=Thread(target=self._run,args=(jobs,self._state['output'],languages,profile),daemon=True)
            self._thread.start()
            return self.get_state()

    def cancel_conversion(self):
        with self._lock:
            if self._state['running']:
                self._cancel.set()
                self._state.update(cancelling=True,message='Cancelling… finishing the current page or download request.')
            return self.get_state()

    def _can_close(self):
        with self._lock:return not self._state['running']

    def _run(self,jobs,output,languages,profile):
        paths=[]
        total=sum(job['pages'] for job in jobs)
        completed_pages=0
        try:
            for job in jobs:
                if self._cancel.is_set():break
                with self._lock:
                    item=next(item for item in self._files if item['id']==job['id'])
                    item.update(status='working',detail='Recognizing text…')
                def progress(done,count):
                    with self._lock:
                        self._state['progress']=(completed_pages+done)/total*100
                        if not self._cancel.is_set():
                            item['detail']=f'Processed {done} of {count} pages'
                            self._state['message']=f"{job['name']} · {done}/{count} pages"
                try:
                    saved=ocr_in_process(job['path'],output,languages=languages,profile=profile,on_progress=progress,should_cancel=self._cancel.is_set)
                    import pymupdf
                    with pymupdf.open(saved[0]) as document:
                        text_pages=sum(bool(page.get_text().strip()) for page in document)
                    paths.append(str(saved[0]))
                    with self._lock:
                        item.update(status='done',output=str(saved[0]),text_pages=text_pages,
                            detail=f'Text detected on {text_pages} of {job["pages"]} pages' if text_pages else 'Saved · No text recognized. Check the language and scan quality.')
                        self._state['completed']+=1
                except ConversionCancelled:
                    break
                except Exception as exc:
                    with self._lock:
                        item.update(status='error',detail=str(exc))
                        self._state['failed']+=1
                completed_pages+=job['pages']
                with self._lock:self._state['progress']=completed_pages/total*100
        finally:
            with self._lock:
                cancelled=self._cancel.is_set()
                for item in self._files:
                    if item['status'] in ('waiting','working'):item.update(status='cancelled',detail='Cancelled · No incomplete PDF saved')
                message='OCR cancelled' if cancelled else f"OCR complete · {self._state['completed']} saved"
                if self._state['failed']:message+=f" · {self._state['failed']} failed"
                self._state.update(running=False,cancelling=False,message=message,
                    result={'id':uuid4().hex,'paths':paths,'operation':'ocr','cancelled':cancelled})


def build_html():
    directory=BASE_DIR/'ocr_ui'
    html=(directory/'index.html').read_text(encoding='utf-8').replace(
        '/* APP_STYLES */',(BASE_DIR/'compressor_ui'/'styles.css').read_text(encoding='utf-8')+'\n'+(directory/'styles.css').read_text(encoding='utf-8')).replace(
        '/* APP_SCRIPT */',(directory/'app.js').read_text(encoding='utf-8'))
    return bundle_output_picker(html,path_id='outputPath',button_id='chooseOutput')

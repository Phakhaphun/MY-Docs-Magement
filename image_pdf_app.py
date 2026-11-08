"""Image to PDF workspace with native dialogs and an isolated export worker."""
import base64
from io import BytesIO
import json
from pathlib import Path
from threading import Thread
from uuid import uuid4

from doc_app import DocumentAPI
from images_to_pdf import image_info,validate_options,DEFAULTS,PAPER_SIZES
from pdf_to_jpg import BASE_DIR,ConversionCancelled
from pdf_worker import images_in_process
from ui_components import bundle_output_picker


class ImagePDFAPI(DocumentAPI):
    def __init__(self,settings_path=None,on_send=None):
        super().__init__(settings_path or BASE_DIR/'image_pdf_settings.json')
        self._on_send=on_send
        options=dict(DEFAULTS)
        try:
            data=json.loads(self._settings_path.read_text(encoding='utf-8'))
            options=validate_options(data.get('image_pdf',{}))
        except (OSError,ValueError,TypeError,AttributeError):pass
        self._recent['image_pdf']=options
        catalog=[dict(id=key,name=value[0],group=value[1],width=value[2],height=value[3]) for key,value in PAPER_SIZES.items()]
        self._state.update(options=options,paper_sizes=catalog,message='Add images to create a PDF.')

    def _add_files(self,paths):
        with self._lock:
            if self._state['running']:return self.get_state()
            for value in paths:
                path=Path(value).resolve()
                if any(item['path']==str(path) for item in self._files):continue
                item={'id':uuid4().hex,'path':str(path),'name':path.name,'rotation':0,'status':'ready','detail':'Ready','size':0,'width':0,'height':0}
                try:
                    info=image_info(path)
                    item.update(width=info['width'],height=info['height'],dpi=info['dpi'],size=path.stat().st_size)
                except Exception as exc:item.update(status='error',detail=str(exc))
                self._files.append(item)
            if paths:
                self._state['input']=str(Path(paths[-1]).resolve().parent)
                self._recent['input_dir']=self._state['input'];self._remember()
            self._state.update(message=f'{len(self._files)} image(s) in your workspace.',progress=0)
            return self.get_state()

    def choose_files(self):
        import webview
        with self._lock:
            if self._state['running']:return self.get_state()
            folder=Path(self._state['input'])
        paths=self._window.create_file_dialog(webview.FileDialog.OPEN,directory=str(folder if folder.is_dir() else BASE_DIR),allow_multiple=True,
            file_types=('Images (*.jpg;*.jpeg;*.png;*.webp)',))
        return self._add_files(paths) if paths else self.get_state()

    def remove_file(self,file_id):
        with self._lock:
            if not self._state['running']:
                self._files=[item for item in self._files if item['id']!=file_id]
                self._state.update(result=None,progress=0,message=f'{len(self._files)} image(s) in your workspace.')
            return self.get_state()

    def clear_files(self):
        with self._lock:
            if not self._state['running']:
                self._files.clear();self._state.update(result=None,progress=0,message='Add images to create a PDF.')
            return self.get_state()

    def set_layout(self,plan):
        with self._lock:
            if self._state['running']:return {'error':'Wait for PDF creation to finish.'}
            if not isinstance(plan,list) or any(not isinstance(item,dict) or not isinstance(item.get('id'),str) or type(item.get('rotation')) is not int or item['rotation'] not in (0,90,180,270) for item in plan):
                return {'error':'Invalid image layout.'}
            ids=[item['id'] for item in plan];lookup={item['id']:item for item in self._files}
            if len(ids)!=len(lookup) or set(ids)!=set(lookup):return {'error':'Image layout does not match the queue.'}
            self._files=[{**lookup[item['id']],'rotation':item['rotation']} for item in plan]
            return self.get_state()

    def thumbnail(self,file_id):
        from PIL import Image,ImageOps
        with self._lock:item=next((dict(item) for item in self._files if item['id']==file_id),None)
        if item is None or not item['width']:return {'error':'Image not found.'}
        try:
            image_info(item['path'])
            with Image.open(item['path']) as original:
                original.draft('RGB',(480,480));original.thumbnail((480,480))
                with ImageOps.exif_transpose(original) as upright:
                    rgba=upright.convert('RGBA');background=Image.new('RGB',rgba.size,'white')
                    background.paste(rgba,mask=rgba.getchannel('A'))
                    stream=BytesIO();background.save(stream,format='JPEG',quality=85)
            return {'image':'data:image/jpeg;base64,'+base64.b64encode(stream.getvalue()).decode('ascii')}
        except Exception as exc:return {'error':str(exc)}

    def start(self,options):
        with self._lock:
            if self._state['running']:return {'error':'PDF creation is already running.'}
            try:
                options=validate_options(options)
                if not self._files or any(not item['width'] for item in self._files):raise ValueError('Add readable images and remove invalid files first.')
            except ValueError as exc:return {'error':str(exc)}
            self._recent['image_pdf']=options;self._remember()
            self._cancel.clear()
            self._state.update(options=options,running=True,cancelling=False,progress=0,result=None,message='Creating PDF…')
            jobs=[{'path':item['path'],'rotation':item['rotation']} for item in self._files]
            self._thread=Thread(target=self._run,args=(jobs,self._state['output'],options),daemon=True)
            self._thread.start();return self.get_state()

    def _run(self,jobs,output,options):
        paths=[];error='';cancelled=False
        def progress(done,total):
            with self._lock:
                self._state['progress']=done/total*100
                if not self._cancel.is_set():self._state['message']=f'Processed {done} of {total} images'
        try:paths=images_in_process(jobs,output,**options,on_progress=progress,should_cancel=self._cancel.is_set)
        except ConversionCancelled as exc:paths=exc.images;cancelled=True
        except Exception as exc:paths=getattr(exc,'images',[]);error=str(exc)
        finally:
            with self._lock:
                self._state.update(running=False,cancelling=False,message=error or ('PDF creation cancelled' if cancelled else 'PDF creation complete'),
                    result={'id':uuid4().hex,'paths':[str(path) for path in paths],'error':error,'cancelled':cancelled})

    def cancel_conversion(self):
        with self._lock:
            if self._state['running']:
                self._cancel.set();self._state.update(cancelling=True,message='Cancelling… finishing the current image operation.')
            return self.get_state()

    def _can_close(self):
        with self._lock:return not self._state['running']

    def send_to(self,target,result_id):
        with self._lock:
            result=self._state.get('result')
            if self._state['running'] or not result or result['id']!=result_id:return {'error':'The result has changed. Create or select the current result first.'}
            if target not in ('ocr','compressor') or not self._on_send:return {'error':'Choose OCR or Compress PDF.'}
            paths=list(result['paths'])
            if not paths or not all(Path(path).is_file() for path in paths):return {'error':'The exported PDFs are no longer available.'}
        return self._on_send(target,paths)


def build_html():
    directory=BASE_DIR/'image_pdf_ui'
    html=(directory/'index.html').read_text(encoding='utf-8').replace('/* APP_STYLES */',(directory/'styles.css').read_text(encoding='utf-8')).replace('/* APP_SCRIPT */',(directory/'app.js').read_text(encoding='utf-8'))
    return bundle_output_picker(html,path_id='outputPath',button_id='chooseOutput')

"""Independent PDF compression queue, using the shared native document dialogs."""
from pathlib import Path
from threading import Thread
from uuid import uuid4

from doc_app import DocumentAPI
from compress_pdf import PRESETS
from pdf_to_jpg import BASE_DIR, ConversionCancelled
from pdf_worker import compress_in_process


class CompressorAPI(DocumentAPI):
    def __init__(self, settings_path=None):
        super().__init__(settings_path or BASE_DIR / 'compressor_settings.json')
        self._state['message'] = 'Add PDFs to reduce their file size.'

    def start(self, preset='balanced'):
        with self._lock:
            if self._state['running']:
                return {'error': 'Compression is already running.'}
            if not isinstance(preset, str) or preset not in PRESETS:
                return {'error': 'Choose Lossless, Balanced, or Smallest.'}
            if not self._files or any(not item['pages'] for item in self._files):
                return {'error': 'Add readable PDFs and remove any invalid files first.'}
            for item in self._files:
                item.update(status='waiting', detail='Waiting', output='', before_size=item['size'], after_size=None)
            jobs = [dict(item) for item in self._files]
            self._cancel.clear()
            self._state.update(running=True, cancelling=False, progress=0, completed=0, warning='',
                               failed=0, result=None, message='Preparing compression…', preset=preset)
            self._thread = Thread(target=self._run, args=(jobs,self._state['output'],preset), daemon=True)
            self._thread.start()
            return self.get_state()

    def cancel_conversion(self):
        with self._lock:
            if self._state['running']:
                self._cancel.set()
                self._state.update(cancelling=True, message='Cancelling… waiting for the current PDF operation.')
            return self.get_state()

    def _can_close(self):
        with self._lock:
            return not self._state['running']

    def _run(self, jobs, output, preset):
        paths = []
        try:
            for index, job in enumerate(jobs):
                if self._cancel.is_set():
                    break
                with self._lock:
                    item = next(item for item in self._files if item['id'] == job['id'])
                    item.update(status='working',detail='Compressing…')
                    self._state.update(progress=index/len(jobs)*100, message=f"Compressing {index+1} of {len(jobs)}: {job['name']}")
                try:
                    saved = compress_in_process(job['path'], output, preset=preset, should_cancel=self._cancel.is_set)
                    path = saved[0]
                    before, after = Path(job['path']).stat().st_size, path.stat().st_size
                    paths.append(str(path))
                    with self._lock:
                        item.update(status='done',detail='No further reduction' if after>=before else f'{(1-after/before)*100:.1f}% smaller',
                                    before_size=before,after_size=after,output=str(path))
                        self._state['completed'] += 1
                except ConversionCancelled:
                    break
                except Exception as exc:
                    with self._lock:
                        item.update(status='error', detail=str(exc))
                        self._state['failed'] += 1
                with self._lock:
                    self._state['progress'] = (index+1)/len(jobs)*100
        finally:
            with self._lock:
                cancelled = self._cancel.is_set()
                for item in self._files:
                    if item['status'] in ('waiting','working'):
                        item.update(status='cancelled',detail='Cancelled')
                message = 'Compression cancelled' if cancelled else 'Compression complete'
                if not cancelled and self._state['failed']:
                    message = f"Compression finished: {self._state['completed']} saved, {self._state['failed']} failed"
                self._state.update(running=False,cancelling=False,message=message,
                                   result={'id':uuid4().hex,'paths':paths,'cancelled':cancelled})


def build_html():
    from ui_components import bundle_output_picker
    directory = BASE_DIR / 'compressor_ui'
    html = (directory/'index.html').read_text(encoding='utf-8').replace(
        '/* APP_STYLES */',(directory/'styles.css').read_text(encoding='utf-8')).replace(
        '/* APP_SCRIPT */',(directory/'app.js').read_text(encoding='utf-8'))
    return bundle_output_picker(html, path_id='outputPath', button_id='chooseOutput')

"""Verify real compression, document fidelity, output safety and cancellation."""
from pathlib import Path
from threading import Event
import hashlib
import unittest

import pymupdf
from PIL import Image

from compress_pdf import compress_pdf
from pdf_worker import compress_in_process
from pdf_to_jpg import ConversionCancelled
from tools.test_workspace import test_workspace


class CompressionTests(unittest.TestCase):
    def setUp(self):
        context = test_workspace()
        self.root = Path(context.__enter__())
        self.addCleanup(lambda: context.__exit__(None, None, None))
        self.source = self.root / 'scan.pdf'
        image = Image.effect_noise((1200, 1200), 65).convert('RGB')
        image.save(self.root / 'scan.png')
        with pymupdf.open() as doc:
            page = doc.new_page(width=288, height=288)
            page.insert_image(pymupdf.Rect(0, 0, 288, 250), filename=str(self.root / 'scan.png'))
            page.insert_text((12, 275), 'Searchable measurement report')
            page.insert_link({'kind':pymupdf.LINK_URI, 'from':pymupdf.Rect(10,260,200,280), 'uri':'https://example.com'})
            page.set_rotation(90)
            widget=pymupdf.Widget()
            widget.field_name='reference'
            widget.field_type=pymupdf.PDF_WIDGET_TYPE_TEXT
            widget.field_value='DOC-002'
            widget.rect=pymupdf.Rect(10,10,120,30)
            page.add_widget(widget)
            page.add_text_annot((140,20),'Review note')
            doc.set_metadata({'title':'Compression fixture'})
            doc.save(self.source, deflate=False)

    def test_presets_reduce_size_preserve_text_pages_and_source(self):
        original = hashlib.sha256(self.source.read_bytes()).digest()
        for preset in ('lossless', 'balanced', 'smallest'):
            with self.subTest(preset=preset):
                output = compress_pdf(self.source, self.root / 'output', preset=preset)[0]
                self.assertLessEqual(output.stat().st_size, self.source.stat().st_size)
                with pymupdf.open(output) as result, pymupdf.open(self.source) as source:
                    self.assertEqual(result.page_count, 1)
                    self.assertIn('Searchable measurement report', result[0].get_text())
                    self.assertEqual(result[0].rect, source[0].rect)
                    self.assertEqual(result[0].rotation, 90)
                    self.assertEqual(result[0].get_links()[0]['uri'], 'https://example.com')
                    self.assertEqual(result.metadata['title'], 'Compression fixture')
                    self.assertEqual(next(result[0].widgets()).field_value,'DOC-002')
                    self.assertEqual(next(result[0].annots()).info['content'],'Review note')
                    if preset == 'lossless':
                        self.assertEqual(result[0].get_pixmap().samples, source[0].get_pixmap().samples)
                    else:
                        self.assertLess(output.stat().st_size, self.source.stat().st_size * .5)
        self.assertEqual(hashlib.sha256(self.source.read_bytes()).digest(), original)
        self.assertFalse(list(self.root.rglob('*.partial')))

    def test_unique_outputs_and_never_larger_than_source(self):
        with pymupdf.open() as doc:
            doc.new_page().insert_text((30,30),'Small PDF')
            doc.save(self.root/'tiny.pdf',garbage=4,deflate=True,use_objstms=1)
        first=compress_pdf(self.root/'tiny.pdf',self.root)[0]
        second=compress_pdf(self.root/'tiny.pdf',self.root)[0]
        self.assertNotEqual(first,second)
        self.assertLessEqual(first.stat().st_size,(self.root/'tiny.pdf').stat().st_size)

    def test_cancel_and_invalid_inputs_do_not_publish_outputs(self):
        with self.assertRaises(ConversionCancelled):
            compress_pdf(self.source,self.root/'cancel',should_cancel=lambda:True)
        self.assertFalse((self.root/'cancel').exists())
        with self.assertRaises(ValueError):
            compress_pdf(self.source,self.root/'invalid',preset='bad')
        with pymupdf.open() as doc:
            doc.new_page()
            doc.save(self.root/'locked.pdf',encryption=pymupdf.PDF_ENCRYPT_AES_256,user_pw='secret',owner_pw='owner')
        with self.assertRaises(ValueError):
            compress_pdf(self.root/'locked.pdf',self.root/'locked')
        stop=Event()
        with self.assertRaises(ConversionCancelled):
            compress_in_process(self.source,self.root/'spawn-cancel',preset='balanced',
                                on_progress=lambda *_:stop.set(),should_cancel=stop.is_set)
        self.assertFalse(list((self.root/'spawn-cancel').rglob('*.pdf')))

    def test_real_worker_and_bridge(self):
        from main_app import ManagementAPI, build_html
        output=compress_in_process(self.source,self.root/'worker',preset='balanced')[0]
        self.assertLess(output.stat().st_size,self.source.stat().st_size)
        api=ManagementAPI(self.root)
        api._compressor._state['output']=str(self.root/'bridge')
        api._compressor._add_files([str(self.source)])
        self.assertIn('error',api.invoke('compressor','start',['bad']))
        state=api.invoke('compressor','start',['balanced'])
        self.assertTrue(state['running'])
        self.assertFalse(api._can_close())
        api._compressor._thread.join(30)
        state=api.invoke('compressor','get_state',[])
        self.assertFalse(state['running'])
        self.assertEqual(state['completed'],1)
        self.assertLess(state['files'][0]['after_size'],state['files'][0]['before_size'])
        self.assertIn('id="compressorTab"',build_html())
        self.assertIn('error',api.invoke('compressor','_run',[]))

    def test_batch_continues_after_file_error(self):
        from compressor_app import CompressorAPI
        bad=self.root/'removed.pdf'
        bad.write_bytes(self.source.read_bytes())
        api=CompressorAPI(self.root/'settings.json')
        api._state['output']=str(self.root/'batch')
        api._add_files([str(bad),str(self.source)])
        bad.unlink()
        api.start('lossless')
        api._thread.join(30)
        state=api.get_state()
        self.assertFalse(state['running'])
        self.assertEqual((state['failed'],state['completed']),(1,1))
        self.assertEqual(state['files'][0]['status'],'error')
        self.assertEqual(state['files'][1]['status'],'done')

"""CPU OCR acceptance checks with real bilingual images and pinned language models."""
import hashlib
from io import BytesIO
from pathlib import Path
from threading import Event
import unittest
from unittest.mock import Mock, patch

from PIL import Image, ImageDraw, ImageFont
import pymupdf

from ocr_pdf import ocr_pdf,render_scale,MAX_PIXELS,MAX_EDGE
from ocr_languages import language_status, validate_languages, download_languages, pack_installed, DATA_DIR
from pdf_worker import ocr_in_process
from pdf_to_jpg import ConversionCancelled
from tools.test_workspace import test_workspace


def make_scan(path, *, rotation=0):
    image=Image.new('RGB',(1200,700),'white')
    font=ImageFont.truetype('C:/Windows/Fonts/tahoma.ttf',52)
    draw=ImageDraw.Draw(image)
    draw.text((70,100),'Document number 12345',font=font,fill='black')
    draw.text((70,280),'ภาษาไทย ทดสอบ',font=font,fill='black')
    png=path.with_suffix('.png');image.save(png)
    with pymupdf.open() as doc:
        page=doc.new_page(width=600 if rotation%180==0 else 350,height=350 if rotation%180==0 else 600)
        page.insert_image(page.rect,filename=str(png),rotate=rotation)
        page.set_rotation(rotation)
        page.insert_link({'kind':pymupdf.LINK_URI,'from':pymupdf.Rect(20,20,100,40),'uri':'https://example.com'})
        doc.set_metadata({'title':'OCR bilingual fixture'})
        doc.save(path)
    return path


class OCRTests(unittest.TestCase):
    def setUp(self):
        context=test_workspace()
        self.root=Path(context.__enter__())
        self.addCleanup(lambda:context.__exit__(None,None,None))
        self.source=make_scan(self.root/'scan.pdf')

    def test_real_bilingual_text_and_visual_fidelity_without_gpu(self):
        digest=hashlib.sha256(self.source.read_bytes()).digest()
        output=ocr_in_process(self.source,self.root/'out',languages=['eng','tha'],profile='balanced')[0]
        with pymupdf.open(output) as result,pymupdf.open(self.source) as source:
            self.assertEqual(result.page_count,source.page_count)
            text=result[0].get_text()
            self.assertIn('12345',text)
            self.assertIn('ภาษาไทย',''.join(text.split()))
            self.assertTrue(result[0].search_for('Document'))
            self.assertEqual(result[0].get_pixmap().samples,source[0].get_pixmap().samples)
            self.assertEqual(result[0].get_links()[0]['uri'],'https://example.com')
            self.assertEqual(result.metadata['title'],'OCR bilingual fixture')
        self.assertEqual(hashlib.sha256(self.source.read_bytes()).digest(),digest)

    def test_rotated_pages_keep_geometry_and_search_alignment(self):
        for angle,cropped in ((90,False),(180,False),(270,False),(90,True),(270,True)):
            with self.subTest(angle=angle,cropped=cropped):
                path=make_scan(self.root/f'rotated-{angle}-{cropped}.pdf',rotation=angle)
                if cropped:
                    with pymupdf.open(path) as doc:
                        bounds=doc[0].cropbox
                        doc[0].set_cropbox(pymupdf.Rect(10,10,bounds.width-10,bounds.height-10))
                        doc.saveIncr()
                output=ocr_pdf(path,self.root/'rotated',languages=['eng'],profile='light')[0]
                with pymupdf.open(path) as source,pymupdf.open(output) as result:
                    self.assertEqual(source[0].rect,result[0].rect)
                    self.assertEqual(source[0].rotation,result[0].rotation)
                    self.assertEqual(source[0].get_pixmap().samples,result[0].get_pixmap().samples)
                    hits=result[0].search_for('12345')
                    self.assertTrue(hits)
                    visible=hits[0]*result[0].rotation_matrix
                    self.assertLess(visible.y0,120)
                    self.assertGreater(visible.x0,150)

    def test_existing_text_is_not_duplicated_and_outputs_are_unique(self):
        with pymupdf.open(self.source) as doc:
            page=doc.new_page(width=400,height=200)
            page.insert_text((30,60),'Original selectable text')
            doc.save(self.root/'mixed.pdf')
        first=ocr_pdf(self.root/'mixed.pdf',self.root/'out',languages=['eng'],profile='light')[0]
        second=ocr_pdf(self.root/'mixed.pdf',self.root/'out',languages=['eng'],profile='light')[0]
        self.assertNotEqual(first,second)
        with pymupdf.open(first) as doc:
            self.assertEqual(doc.page_count,2)
            self.assertEqual(doc[1].get_text().count('Original selectable text'),1)

    def test_cancel_discards_incomplete_pdf_and_missing_language_is_clear(self):
        stop=Event()
        with self.assertRaises(ConversionCancelled):
            ocr_in_process(self.source,self.root/'cancel',languages=['eng'],profile='light',
                           on_progress=lambda done,total:stop.set() if done else None,should_cancel=stop.is_set)
        self.assertFalse(list((self.root/'cancel').rglob('*.pdf')))
        self.assertFalse(list(self.root.rglob('*.partial')))
        with self.assertRaises(ValueError):validate_languages(['../../bad'])
        with self.assertRaises(ValueError):validate_languages([])
        with self.assertRaises(ValueError):ocr_pdf(self.source,self.root/'bad',languages=['eng'],profile='bad')
        installed={item['code']:item for item in language_status()}
        self.assertTrue(installed['eng']['installed'])
        self.assertTrue(installed['tha']['installed'])
        self.assertGreater(len(installed),50)
        missing=next(code for code,item in installed.items() if not item['installed'])
        with self.assertRaisesRegex(ValueError,'Download'):
            ocr_pdf(self.source,self.root/'missing',languages=[missing],profile='light')

    def test_crop_box_and_blank_page_are_kept(self):
        with pymupdf.open(self.source) as doc:
            doc[0].set_cropbox(pymupdf.Rect(15,10,590,340))
            doc.new_page(width=200,height=100)
            doc.save(self.root/'cropped.pdf')
        output=ocr_pdf(self.root/'cropped.pdf',self.root/'out',languages=['eng'],profile='light')[0]
        with pymupdf.open(self.root/'cropped.pdf') as source,pymupdf.open(output) as result:
            self.assertEqual(result[0].cropbox,source[0].cropbox)
            self.assertEqual(result[0].get_pixmap().samples,source[0].get_pixmap().samples)
            self.assertIn('12345',result[0].get_text())
            self.assertEqual(result[1].get_text().strip(),'')

    def test_verified_download_and_corrupt_download_cleanup(self):
        folder=self.root/'packs'
        good=(DATA_DIR/'eng.traineddata').read_bytes()
        with patch('ocr_languages.urlopen',return_value=BytesIO(good)) as request:
            download_languages(['eng'],directory=folder)
        self.assertTrue(pack_installed('eng',folder))
        self.assertIn('87416418657359cb625c412a48b6e1d6d41c29bd',request.call_args.args[0])
        with patch('ocr_languages.urlopen',return_value=BytesIO(b'corrupt')):
            with self.assertRaisesRegex(ValueError,'verification failed'):
                download_languages(['tha'],directory=folder)
        self.assertFalse((folder/'tha.traineddata').exists())
        self.assertFalse(list(folder.glob('*.partial')))
        with self.assertRaises(ConversionCancelled):
            download_languages(['tha'],directory=folder,should_cancel=lambda:True)

    def test_render_budget_for_large_and_extremely_wide_pages(self):
        for width,height in [(595,842),(100000,100000),(1000000,10),(10,1000000)]:
            scale=render_scale(width,height,300)
            self.assertLessEqual(width*height*scale*scale,MAX_PIXELS*1.000001)
            self.assertLessEqual(max(width,height)*scale,MAX_EDGE*1.000001)
        with self.assertRaises(ValueError):render_scale(float('inf'),842,200)
        with self.assertRaises(ValueError):render_scale(0,842,200)

    def test_multiple_pages_keep_text_and_artwork_across_cache_boundaries(self):
        with pymupdf.open() as document,pymupdf.open(self.source) as scan:
            for _ in range(4):document.insert_pdf(scan)
            document.save(self.root/'four-pages.pdf')
        progress=[]
        output=ocr_pdf(self.root/'four-pages.pdf',self.root/'cache',languages=['eng'],profile='balanced',
            on_progress=lambda done,total:progress.append((done,total)))[0]
        self.assertEqual(progress,[(number,4) for number in range(5)])
        with pymupdf.open(output) as result,pymupdf.open(self.source) as scan:
            self.assertEqual(result.page_count,4)
            for page in result:
                self.assertIn('12345',page.get_text())
                self.assertEqual(page.get_pixmap().samples,scan[0].get_pixmap().samples)

    def test_bridge_options_persist_and_batch_continues_after_bad_file(self):
        from main_app import ManagementAPI,build_html
        api=ManagementAPI(self.root)
        (self.root/'bridge').mkdir()
        api._ocr._window=Mock()
        api._ocr._window.create_file_dialog.return_value=[str(self.root/'bridge')]
        api.invoke('ocr','choose_output',[])
        missing=self.root/'removed.pdf';missing.write_bytes(self.source.read_bytes())
        api._ocr._add_files([str(missing),str(self.source)])
        missing.unlink()
        self.assertIn('error',api.invoke('ocr','start',[[], 'balanced']))
        self.assertIn('error',api.invoke('ocr','install_languages',[['../../bad']]))
        started=api.invoke('ocr','start',[['eng','tha'],'light'])
        self.assertTrue(started['running'])
        self.assertFalse(api._can_close())
        api._ocr._thread.join(30)
        result=api.invoke('ocr','get_state',[])
        self.assertFalse(result['running'])
        self.assertEqual((result['completed'],result['failed']),(1,1))
        self.assertEqual(result['files'][1]['text_pages'],1)
        self.assertIn('id="ocrTab"',build_html())
        self.assertIn('error',api.invoke('ocr','_install',[['eng']]))
        restarted=ManagementAPI(self.root)
        options=restarted.invoke('ocr','get_languages',[])
        self.assertEqual(options['selected'],['eng','tha'])
        self.assertEqual(options['profile'],'light')
        self.assertEqual(restarted._ocr.get_state()['output'],str(self.root/'bridge'))

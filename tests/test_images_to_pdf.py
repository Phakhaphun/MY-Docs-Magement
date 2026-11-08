"""Verify real image layout, orientation, no-overwrite output and continuation."""
import hashlib
from pathlib import Path
from threading import Event
import unittest

from PIL import Image
import pymupdf

from images_to_pdf import images_to_pdf, validate_options, image_info
from pdf_worker import images_in_process
from pdf_to_jpg import ConversionCancelled
from tools.test_workspace import test_workspace


class ImagesToPDFTests(unittest.TestCase):
    def setUp(self):
        context=test_workspace();self.root=Path(context.__enter__())
        self.addCleanup(lambda:context.__exit__(None,None,None))
        self.paths=[]
        for name,color,kind in [('First photo','red','JPEG'),('ภาพที่สอง','blue','PNG'),('Third','green','WEBP')]:
            path=self.root/(name+{'JPEG':'.jpg','PNG':'.png','WEBP':'.webp'}[kind])
            Image.new('RGB',(200,100),color).save(path,format=kind)
            self.paths.append(path)
        self.jobs=[{'path':str(path),'rotation':0} for path in self.paths]

    def test_combined_page_order_dimensions_margins_and_sources_unchanged(self):
        digest=[hashlib.sha256(path.read_bytes()).digest() for path in self.paths]
        ordered=[self.jobs[1],self.jobs[0],self.jobs[2]]
        result=images_to_pdf(ordered,self.root/'out',page_size='a4',orientation='portrait',margin=10,mode='combine')[0]
        self.assertEqual(result.parent.name,self.paths[1].stem+'_and_2_more_pdf')
        with pymupdf.open(result) as doc:
            self.assertEqual(doc.page_count,3)
            colors=[(0,0,255),(254,0,0),(0,128,1)]
            for page,color in zip(doc,colors):
                self.assertAlmostEqual(page.rect.width,595.276,delta=.5)
                self.assertAlmostEqual(page.rect.height,841.89,delta=.5)
                pix=page.get_pixmap()
                self.assertTrue(all(abs(a-b)<8 for a,b in zip(pix.pixel(pix.width//2,pix.height//2),color)))
                self.assertEqual(pix.pixel(1,1),(255,255,255))
                rect=page.get_image_rects(page.get_images()[0][0])[0]
                self.assertGreaterEqual(rect.x0,10*72/25.4-.1)
            self.assertEqual(doc.extract_image(doc[1].get_images()[0][0])['image'],self.paths[0].read_bytes())
        self.assertEqual(digest,[hashlib.sha256(path.read_bytes()).digest() for path in self.paths])

    def test_separate_pdfs_original_size_and_collision(self):
        first=images_to_pdf(self.jobs,self.root/'out',page_size='original',orientation='auto',margin=0,mode='separate')
        again=images_to_pdf(self.jobs,self.root/'out',page_size='original',orientation='auto',margin=0,mode='separate')
        self.assertEqual([path.parent.name for path in first],[path.stem+'_pdf' for path in self.paths])
        self.assertTrue(all(left.parent!=right.parent for left,right in zip(first,again)))
        with pymupdf.open(first[1]) as doc:
            self.assertAlmostEqual(doc[0].rect.width,150,delta=.5)
            self.assertAlmostEqual(doc[0].rect.height,75,delta=.5)

    def test_exif_orientation_manual_clockwise_rotation_and_alpha(self):
        image=Image.new('RGB',(100,200),'red');image.paste('blue',(0,100,100,200))
        exif=Image.Exif();exif[274]=6
        path=self.root/'exif.jpg';image.save(path,exif=exif)
        self.assertEqual((image_info(path)['width'],image_info(path)['height']),(200,100))
        output=images_to_pdf([{'path':str(path),'rotation':90}],self.root/'out',page_size='original',margin=0)[0]
        with pymupdf.open(output) as doc:
            self.assertLess(doc[0].rect.width,doc[0].rect.height)
            pix=doc[0].get_pixmap()
            self.assertGreater(pix.pixel(pix.width//2,pix.height//4)[2],240)
        alpha=self.root/'transparent.png';Image.new('RGBA',(100,100),(0,0,0,0)).save(alpha)
        output=images_to_pdf([{'path':str(alpha),'rotation':0}],self.root/'out',page_size='letter',orientation='landscape',margin=0)[0]
        with pymupdf.open(output) as doc:
            self.assertEqual(tuple(doc[0].rect),(0,0,792,612))
            self.assertEqual(doc[0].get_pixmap().pixel(300,300),(255,255,255))

    def test_bad_inputs_rejected_before_output_and_cancel_retains_complete_files(self):
        with self.assertRaises(ValueError):validate_options({'page_size':'bad'})
        with self.assertRaises(ValueError):validate_options({'margin':float('nan')})
        with self.assertRaises(ValueError):validate_options({'margin':True})
        with self.assertRaises(ValueError):images_to_pdf([{'path':str(self.paths[0]),'rotation':13}],self.root/'invalid')
        self.assertFalse((self.root/'invalid').exists())
        bad=self.root/'bad.png';bad.write_bytes(b'not an image')
        with self.assertRaises(Exception):images_to_pdf([{'path':str(bad),'rotation':0}],self.root/'invalid')
        self.assertFalse((self.root/'invalid').exists())
        for mode,count in [('combine',0),('separate',1)]:
            stop=Event()
            with self.assertRaises(ConversionCancelled) as caught:
                images_in_process(self.jobs,self.root/mode,mode=mode,on_progress=lambda done,total:stop.set() if done else None,should_cancel=stop.is_set)
            self.assertEqual(len(caught.exception.images),count)
            self.assertEqual(len(list((self.root/mode).rglob('*.pdf'))),count)
            self.assertFalse(list((self.root/mode).rglob('*.partial')))

    def test_real_bridge_layout_and_handoff_preserve_destination_queues(self):
        from main_app import ManagementAPI
        api=ManagementAPI(self.root)
        api._imagepdf._state['output']=str(self.root/'bridge')
        files=api._imagepdf._add_files([str(path) for path in self.paths])['files']
        plan=[{'id':item['id'],'rotation':90} for item in reversed(files)]
        api.invoke('imagepdf','set_layout',[plan])
        self.assertEqual([item['id'] for item in api._imagepdf.get_state()['files']],[item['id'] for item in reversed(files)])
        self.assertIn('error',api.invoke('imagepdf','set_layout',[[{'id':'bad','rotation':0}]]))
        api.invoke('imagepdf','start',[{'mode':'separate'}]);api._imagepdf._thread.join(30)
        result=api._imagepdf.get_state()['result']
        self.assertEqual(len(result['paths']),3)
        self.assertFalse(result['error'])
        with pymupdf.open() as document:
            document.new_page().insert_text((30,40),'Existing document')
            document.save(self.root/'existing.pdf')
        api._ocr._add_files([str(self.root/'existing.pdf')])
        self.assertIn('error',api.invoke('imagepdf','send_to',['other',result['id']]))
        self.assertIn('error',api.invoke('imagepdf','send_to',['ocr','stale']))
        sent=api.invoke('imagepdf','send_to',['ocr',result['id']])
        self.assertEqual(sent['workspace'],'ocr')
        self.assertEqual(len(api._ocr.get_state()['files']),4)
        self.assertEqual(api._ocr.get_state()['files'][0]['name'],'existing.pdf')
        api.invoke('imagepdf','send_to',['ocr',result['id']])
        self.assertEqual(len(api._ocr.get_state()['files']),4)
        api._compressor._state['running']=True
        self.assertIn('error',api.invoke('imagepdf','send_to',['compressor',result['id']]))
        api._compressor._state['running']=False
        self.assertEqual(api.invoke('imagepdf','send_to',['compressor',result['id']])['workspace'],'compressor')
        from image_pdf_app import ImagePDFAPI
        self.assertEqual(ImagePDFAPI(self.root/'image_pdf_settings.json').get_state()['options']['mode'],'separate')

    def test_input_removed_mid_batch_still_reports_completed_pdfs(self):
        def progress(done,total):
            if done==1:self.paths[1].unlink()
        with self.assertRaises(RuntimeError) as caught:
            images_in_process(self.jobs,self.root/'partial',mode='separate',on_progress=progress)
        self.assertEqual(len(caught.exception.images),1)
        self.assertTrue(caught.exception.images[0].is_file())
        self.assertFalse(list((self.root/'partial').rglob('*.partial')))

    def test_additional_paper_sizes_have_correct_physical_dimensions(self):
        expected={'a0':(841,1189),'a1':(594,841),'a2':(420,594),'a3':(297,420),
            'a5':(148,210),'a6':(105,148),'b4':(250,353),'b5':(176,250),
            'legal':(215.9,355.6),'tabloid':(279.4,431.8),'executive':(184.15,266.7),
            'photo4x6':(101.6,152.4),'photo5x7':(127,177.8),'jis_b4':(257,364),'jis_b5':(182,257),'folio':(215.9,330.2)}
        for paper,(width,height) in expected.items():
            with self.subTest(paper=paper):
                output=images_to_pdf(self.jobs[:1],self.root/'paper-sizes',page_size=paper,orientation='portrait',margin=5)[0]
                with pymupdf.open(output) as doc:
                    self.assertAlmostEqual(doc[0].rect.width,width*72/25.4,delta=.02)
                    self.assertAlmostEqual(doc[0].rect.height,height*72/25.4,delta=.02)

    def test_custom_size_is_exact_and_bad_margins_do_not_create_outputs(self):
        output=images_to_pdf(self.jobs[:1],self.root/'custom',page_size='custom',
            custom_width=320,custom_height=180,orientation='portrait',margin=7)[0]
        with pymupdf.open(output) as doc:
            self.assertAlmostEqual(doc[0].rect.width,320*72/25.4,delta=.02)
            self.assertAlmostEqual(doc[0].rect.height,180*72/25.4,delta=.02)
        for values in ({'custom_width':0},{'custom_height':float('inf')},{'custom_width':True}):
            with self.assertRaises(ValueError):validate_options({'page_size':'custom',**values})
        with self.assertRaisesRegex(ValueError,'margin|Margin'):
            images_to_pdf(self.jobs[:1],self.root/'invalid-margin',page_size='custom',custom_width=20,custom_height=40,margin=10)
        self.assertFalse((self.root/'invalid-margin').exists())

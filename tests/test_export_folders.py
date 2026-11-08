"""Source-based export folders, atomic collisions and per-source organization."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import unittest

import pymupdf

from export_folders import create_export_folder
from pdf_to_jpg import convert_pdf_to_images
from compress_pdf import compress_pdf
from ocr_pdf import ocr_pdf
from organize_pdf import organize_pdfs
from tools.test_workspace import test_workspace


class ExportFolderTests(unittest.TestCase):
    def setUp(self):
        context=test_workspace()
        self.root=Path(context.__enter__())
        self.addCleanup(lambda:context.__exit__(None,None,None))
        self.sources=[]
        for name in ('รายงาน ฉบับที่ 1','Invoice B'):
            path=self.root/f'{name}.pdf'
            with pymupdf.open() as document:
                for number in (1,2):document.new_page().insert_text((30,40),f'Page {number}')
                document.save(path)
            self.sources.append(path)

    def test_every_pdf_tool_names_folder_from_source_and_operation(self):
        source=self.sources[0];output=self.root/'output'
        images=convert_pdf_to_images(source,output,dpi=36)
        compressed=compress_pdf(source,output,preset='lossless')
        searchable=ocr_pdf(source,output,languages=['eng'],profile='light')
        self.assertEqual(images[0].parent.name,source.stem+'_images')
        self.assertEqual(compressed[0].parent.name,source.stem+'_compressed')
        self.assertEqual(searchable[0].parent.name,source.stem+'_searchable')
        self.assertTrue(all(path.is_file() for path in images+compressed+searchable))

    def test_extract_and_split_have_a_separate_folder_for_each_source(self):
        jobs=[{'path':str(source),'page_selection':''} for source in self.sources]
        for mode,suffix in [('extract','extracted'),('split','split')]:
            outputs=organize_pdfs(jobs,self.root/'organized',mode=mode)
            self.assertEqual({path.parent.name for path in outputs},{source.stem+'_'+suffix for source in self.sources})
            self.assertEqual(len(outputs),2 if mode=='extract' else 4)

    def test_merge_identifies_first_source_and_distinct_file_count(self):
        jobs=[{'path':str(source),'page_selection':'1'} for source in self.sources]
        output=organize_pdfs(jobs,self.root/'merged')[0]
        self.assertEqual(output.parent.name,self.sources[0].stem+'_and_1_more_merged')
        # Repeated source blocks in a visual page plan are one source document.
        repeated=[{'path':str(self.sources[0]),'page_selection':str(number)} for number in (1,2)]
        output=organize_pdfs(repeated,self.root/'merged')[0]
        self.assertEqual(output.parent.name,self.sources[0].stem+'_merged')

    def test_collisions_do_not_overwrite_files_or_concurrent_exports(self):
        output=self.root/'collisions';output.mkdir()
        marker=output/'Invoice_images';marker.write_text('Keep this file',encoding='utf-8')
        first=create_export_folder(output,Path('Invoice.pdf'),'images')
        self.assertEqual(first.name,'Invoice_images_2')
        with ThreadPoolExecutor(max_workers=4) as pool:
            folders=list(pool.map(lambda _:create_export_folder(output,Path('Invoice.pdf'),'images'),range(8)))
        self.assertEqual(len(set(folders)),8)
        self.assertTrue(all(folder.is_dir() for folder in folders))
        self.assertEqual(marker.read_text(encoding='utf-8'),'Keep this file')

    def test_same_filenames_from_different_inputs_remain_separate(self):
        other=self.root/'other';other.mkdir()
        duplicate=other/self.sources[0].name;duplicate.write_bytes(self.sources[0].read_bytes())
        jobs=[{'path':str(path),'page_selection':'1'} for path in (self.sources[0],duplicate)]
        outputs=organize_pdfs(jobs,self.root/'same-name',mode='extract')
        self.assertEqual([path.parent.name for path in outputs],[self.sources[0].stem+'_extracted',self.sources[0].stem+'_extracted_2'])

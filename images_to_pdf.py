"""Create PDFs from still images, retaining page order and correcting EXIF rotation."""
from io import BytesIO
import math
from pathlib import Path

from export_folders import create_export_folder
from pdf_to_jpg import ConversionCancelled

EXTENSIONS={'.jpg','.jpeg','.png','.webp'}
DEFAULTS={'page_size':'a4','orientation':'auto','margin':10,'mode':'combine'}
MAX_IMAGE_PIXELS=50_000_000


class ImageExportError(RuntimeError):
    """Preserve complete separate PDFs if an input disappears during export."""
    def __init__(self,message,images):
        super().__init__(message)
        self.images=list(images)


def validate_options(options):
    if not isinstance(options,dict) or set(options)-set(DEFAULTS):
        raise ValueError('Invalid PDF settings.')
    values={**DEFAULTS,**options}
    if values['page_size'] not in ('a4','letter','original'):
        raise ValueError('Choose A4, Letter, or Original size.')
    if values['orientation'] not in ('auto','portrait','landscape'):
        raise ValueError('Choose Auto, Portrait, or Landscape.')
    if values['mode'] not in ('combine','separate'):
        raise ValueError('Choose one combined PDF or one PDF per image.')
    margin=values['margin']
    if type(margin) not in (int,float) or not math.isfinite(margin) or not 0<=margin<=50:
        raise ValueError('Use a margin between 0 and 50 mm.')
    return values


def image_info(path):
    from PIL import Image
    path=Path(path)
    if path.suffix.lower() not in EXTENSIONS or not path.is_file():
        raise ValueError('Choose JPG, PNG, or WebP images.')
    with Image.open(path) as image:
        if image.format not in ('JPEG','PNG','WEBP') or getattr(image,'is_animated',False):
            raise ValueError('Use a still JPG, PNG, or WebP image.')
        width,height=image.size
        if width<=0 or height<=0 or width*height>MAX_IMAGE_PIXELS:
            raise ValueError('Image exceeds 50 million pixels. Resize it before adding.')
        exif_orientation=image.getexif().get(274,1) if image.format=='JPEG' or 'exif' in image.info else 1
        dpi=image.info.get('dpi',(96,96))
        if not isinstance(dpi,(tuple,list)) or len(dpi)!=2 or any(type(value) not in (int,float) or not math.isfinite(value) or not 36<=value<=1200 for value in dpi):
            dpi=(96,96)
        if exif_orientation in (5,6,7,8):width,height=height,width;dpi=dpi[::-1]
        info={'width':width,'height':height,'dpi':list(dpi),'exif':exif_orientation,'format':image.format}
    with Image.open(path) as verified:verified.verify()
    return info


def page_geometry(info,rotation,options):
    margin=options['margin']*72/25.4
    width,height=info['width'],info['height']
    if rotation%180:width,height=height,width
    if options['page_size']=='original':
        dpi_x,dpi_y=info['dpi']
        if rotation%180:dpi_x,dpi_y=dpi_y,dpi_x
        paper=(width*72/dpi_x+2*margin,height*72/dpi_y+2*margin)
    else:
        paper=(595.2756,841.8898) if options['page_size']=='a4' else (612,792)
        landscape=options['orientation']=='landscape' or (options['orientation']=='auto' and width>height)
        if landscape:paper=paper[::-1]
    if max(paper)>14400:
        raise ValueError('Original page size is too large. Choose A4 or Letter.')
    return paper,(margin,margin,paper[0]-margin,paper[1]-margin)


def images_to_pdf(jobs,output,*,page_size='a4',orientation='auto',margin=10,mode='combine',on_progress=None,should_cancel=None):
    import pymupdf
    options=validate_options(dict(page_size=page_size,orientation=orientation,margin=margin,mode=mode))
    if not isinstance(jobs,list) or not jobs:raise ValueError('Add at least one image.')
    validated=[]
    for job in jobs:
        if not isinstance(job,dict) or not isinstance(job.get('path'),str):raise ValueError('Invalid image data.')
        rotation=job.get('rotation',0)
        if type(rotation) is not int or rotation not in (0,90,180,270):raise ValueError('Invalid image rotation.')
        source=Path(job['path']).resolve();info=image_info(source)
        paper,rect=page_geometry(info,rotation,options)
        validated.append((source,info,rotation,paper,rect))
    saved=[]
    def check_cancel():
        if should_cancel and should_cancel():raise ConversionCancelled(saved)
    check_cancel()
    if on_progress:on_progress(0,len(validated))
    check_cancel()

    def add_page(document,entry):
        source,info,rotation,paper,rect=entry
        page=document.new_page(width=paper[0],height=paper[1])
        if info['exif'] in (2,3,4,5,6,7,8) or info['format']=='WEBP':
            from PIL import Image,ImageOps
            with Image.open(source) as original:
                with ImageOps.exif_transpose(original) as upright:
                    stream=BytesIO();upright.save(stream,format='PNG')
                    page.insert_image(pymupdf.Rect(rect),stream=stream.getvalue(),rotate=(-rotation)%360)
        else:
            # Reuse original JPEG/PNG data rather than recompressing photographs.
            page.insert_image(pymupdf.Rect(rect),filename=str(source),rotate=(-rotation)%360)
        pymupdf.TOOLS.store_shrink(100)

    def save(document,source,additional=0):
        check_cancel()
        folder=create_export_folder(output,source,'pdf',additional_sources=additional)
        name=source.stem+(f'_and_{additional}_more' if additional else '')+'.pdf'
        path=folder/name;temporary=path.with_suffix('.partial');published=False
        try:
            document.save(temporary,garbage=3,deflate=True,use_objstms=1)
            check_cancel()
            with pymupdf.open(temporary) as verified:
                if verified.page_count!=document.page_count:raise RuntimeError('The PDF could not be verified.')
            temporary.replace(path);published=True;saved.append(path)
        finally:
            temporary.unlink(missing_ok=True)
            if not published:folder.rmdir()

    try:
        if mode=='combine':
            with pymupdf.open() as document:
                for index,entry in enumerate(validated,1):
                    check_cancel();add_page(document,entry)
                    if on_progress:on_progress(index,len(validated))
                save(document,validated[0][0],len(validated)-1)
        else:
            for index,entry in enumerate(validated,1):
                check_cancel()
                with pymupdf.open() as document:
                    add_page(document,entry);save(document,entry[0])
                if on_progress:on_progress(index,len(validated))
    except ConversionCancelled:
        raise
    except Exception as exc:
        raise ImageExportError(str(exc),saved) from exc
    return saved

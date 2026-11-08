"""Readable source-based output folders, reserved atomically without overwriting."""
from pathlib import Path
import re

OPERATIONS={'images','compressed','searchable','merged','extracted','split'}


def create_export_folder(output,source,operation,*,additional_sources=0):
    if operation not in OPERATIONS:
        raise ValueError('Unknown export operation.')
    stem=re.sub(r'[<>:"/\\|?*\x00-\x1f]','_',Path(source).stem).strip(' .') or 'document'
    # Keep source names readable without making the folder component too long
    # for Windows. Colliding shortened names still get separate reservations.
    stem=stem.encode('utf-16-le')[:160].decode('utf-16-le',errors='ignore')
    group=f'_and_{additional_sources}_more' if additional_sources else ''
    name=f'{stem}{group}_{operation}'
    root=Path(output);root.mkdir(parents=True,exist_ok=True)
    index=1
    while True:
        folder=root/(name if index==1 else f'{name}_{index}')
        try:
            folder.mkdir()
            return folder
        except FileExistsError:
            index+=1

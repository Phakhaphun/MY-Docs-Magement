"""Pinned, verified Tesseract Fast language packs; no system installation needed."""
from functools import lru_cache
import hashlib
import json
from pathlib import Path
from urllib.request import urlopen
from uuid import uuid4

from pdf_to_jpg import BASE_DIR, ConversionCancelled

DATA_DIR = BASE_DIR / 'ocr_data' / 'tessdata'
_MANIFEST = json.loads((BASE_DIR / 'ocr_data' / 'manifest.json').read_text(encoding='utf-8-sig'))
NAMES = {
    'afr':'Afrikaans', 'amh':'Amharic', 'ara':'Arabic', 'asm':'Assamese', 'aze':'Azerbaijani',
    'aze_cyrl':'Azerbaijani (Cyrillic)', 'bel':'Belarusian', 'ben':'Bengali', 'bod':'Tibetan',
    'bos':'Bosnian', 'bre':'Breton', 'bul':'Bulgarian', 'cat':'Catalan', 'ceb':'Cebuano',
    'ces':'Czech', 'chi_sim':'Chinese (Simplified)', 'chi_sim_vert':'Chinese (Simplified, vertical)',
    'chi_tra':'Chinese (Traditional)', 'chi_tra_vert':'Chinese (Traditional, vertical)',
    'chr':'Cherokee', 'cos':'Corsican', 'cym':'Welsh', 'dan':'Danish', 'deu':'German',
    'deu_latf':'German (Fraktur)', 'div':'Dhivehi', 'dzo':'Dzongkha', 'ell':'Greek', 'eng':'English', 'enm':'English (Middle)',
    'epo':'Esperanto', 'est':'Estonian', 'eus':'Basque', 'fao':'Faroese', 'fas':'Persian',
    'fil':'Filipino', 'fin':'Finnish', 'fra':'French', 'frk':'German (Fraktur)',
    'frm':'French (Middle)', 'fry':'Frisian', 'gla':'Scottish Gaelic', 'gle':'Irish',
    'glg':'Galician', 'grc':'Greek (Ancient)', 'guj':'Gujarati', 'hat':'Haitian Creole',
    'heb':'Hebrew', 'hin':'Hindi', 'hrv':'Croatian', 'hun':'Hungarian', 'hye':'Armenian',
    'iku':'Inuktitut', 'ind':'Indonesian', 'isl':'Icelandic', 'ita':'Italian',
    'ita_old':'Italian (Old)', 'jav':'Javanese', 'jpn':'Japanese', 'jpn_vert':'Japanese (vertical)',
    'kan':'Kannada', 'kat':'Georgian', 'kat_old':'Georgian (Old)', 'kaz':'Kazakh',
    'khm':'Khmer', 'kir':'Kyrgyz', 'kmr':'Kurdish (Kurmanji)', 'kor':'Korean',
    'kor_vert':'Korean (vertical)', 'lao':'Lao', 'lat':'Latin', 'lav':'Latvian',
    'lit':'Lithuanian', 'ltz':'Luxembourgish', 'mal':'Malayalam', 'mar':'Marathi',
    'mkd':'Macedonian', 'mlt':'Maltese', 'mon':'Mongolian', 'mri':'Maori', 'msa':'Malay',
    'mya':'Burmese', 'nep':'Nepali', 'nld':'Dutch', 'nor':'Norwegian', 'oci':'Occitan',
    'ori':'Odia', 'pan':'Punjabi', 'pol':'Polish', 'por':'Portuguese', 'pus':'Pashto',
    'que':'Quechua', 'ron':'Romanian', 'rus':'Russian', 'san':'Sanskrit', 'sin':'Sinhala',
    'slk':'Slovak', 'slv':'Slovenian', 'snd':'Sindhi', 'spa':'Spanish', 'spa_old':'Spanish (Old)',
    'sqi':'Albanian', 'srp':'Serbian', 'srp_latn':'Serbian (Latin)', 'sun':'Sundanese',
    'swa':'Swahili', 'swe':'Swedish', 'syr':'Syriac', 'tam':'Tamil', 'tat':'Tatar',
    'tel':'Telugu', 'tgk':'Tajik', 'tha':'Thai', 'tir':'Tigrinya', 'ton':'Tongan',
    'tur':'Turkish', 'uig':'Uyghur', 'ukr':'Ukrainian', 'urd':'Urdu', 'uzb':'Uzbek',
    'uzb_cyrl':'Uzbek (Cyrillic)', 'vie':'Vietnamese', 'yid':'Yiddish', 'yor':'Yoruba',
}


def validate_languages(languages):
    if not isinstance(languages, list) or not 1 <= len(languages) <= 5:
        raise ValueError('Choose 1–5 languages. Fewer languages use less memory and usually work better.')
    if any(not isinstance(code,str) or code not in _MANIFEST['packs'] for code in languages):
        raise ValueError('Choose languages from the available list.')
    return list(dict.fromkeys(languages))


@lru_cache(maxsize=256)
def _verified(path, size, modified):
    code = Path(path).stem
    expected = _MANIFEST['packs'].get(code)
    if not expected or expected['size'] != size:
        return False
    digest = hashlib.sha1(f'blob {size}\0'.encode('ascii'))
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda:stream.read(65536),b''):
            digest.update(chunk)
    return digest.hexdigest() == expected['sha']


def pack_installed(code, directory=DATA_DIR):
    try:
        path = Path(directory) / f'{code}.traineddata'
        info = path.stat()
        return _verified(str(path.resolve()),info.st_size,info.st_mtime_ns)
    except OSError:
        return False


def language_status():
    return sorted([{'code':code,'name':NAMES.get(code,code),'installed':pack_installed(code),
                    'size':pack['size']} for code,pack in _MANIFEST['packs'].items()],
                  key=lambda item:(item['code'] not in ('eng','tha'),item['name']))


def require_languages(languages, directory=DATA_DIR):
    languages=validate_languages(languages)
    missing=[NAMES.get(code,code) for code in languages if not pack_installed(code,directory)]
    if missing:
        raise ValueError('Download the selected language packs first: '+', '.join(missing))
    return languages


def download_languages(languages, *, directory=DATA_DIR, on_progress=None, should_cancel=None):
    languages=validate_languages(languages)
    directory=Path(directory)
    directory.mkdir(parents=True,exist_ok=True)
    def check_cancel():
        if should_cancel and should_cancel():
            raise ConversionCancelled([])
    for index,code in enumerate(languages):
        check_cancel()
        if not pack_installed(code,directory):
            expected=_MANIFEST['packs'][code]
            temporary=directory/f'.{code}-{uuid4().hex}.partial'
            url=f"https://raw.githubusercontent.com/tesseract-ocr/tessdata_fast/{_MANIFEST['revision']}/{code}.traineddata"
            try:
                with urlopen(url,timeout=20) as response,temporary.open('xb') as stream:
                    received=0
                    digest=hashlib.sha1(f"blob {expected['size']}\0".encode('ascii'))
                    while True:
                        check_cancel()
                        chunk=response.read(65536)
                        if not chunk:break
                        received+=len(chunk)
                        if received>expected['size']:
                            raise ValueError('The downloaded language pack has an unexpected size.')
                        stream.write(chunk);digest.update(chunk)
                        if on_progress:on_progress(index+received/expected['size'],len(languages))
                if received!=expected['size'] or digest.hexdigest()!=expected['sha']:
                    raise ValueError('Language pack verification failed. Please try the download again.')
                check_cancel()
                temporary.replace(directory/f'{code}.traineddata')
            finally:
                temporary.unlink(missing_ok=True)
        if on_progress:on_progress(index+1,len(languages))

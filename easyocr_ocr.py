"""
EasyOCR wrapper — 100% offline OCR untuk mode easyocr.
Reader di-cache sebagai module-level variable supaya model cuma di-load sekali
sepanjang session (berat ~1-2GB, tapi sekali load).
"""

import functools

import easyocr


@functools.lru_cache(maxsize=1)
def _get_reader_key(languages_tuple, gpu):
    languages = list(languages_tuple)
    return easyocr.Reader(languages, gpu=gpu)


_reader = None
_reader_languages = None
_reader_gpu = None


def get_reader(languages=None, gpu=True):
    global _reader, _reader_languages, _reader_gpu
    langs = languages or ["en"]
    if _reader is None or _reader_languages != langs or _reader_gpu != gpu:
        _reader = easyocr.Reader(langs, gpu=gpu)
        _reader_languages = langs
        _reader_gpu = gpu
    return _reader


def extract_text(image_path, languages=None, gpu=True) -> str:
    reader = get_reader(languages, gpu)
    results = reader.readtext(image_path, detail=0, paragraph=True)
    return " ".join(results).strip()

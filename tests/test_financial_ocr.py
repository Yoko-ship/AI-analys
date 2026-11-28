"""OCR selection must preserve readable evidence before classification succeeds."""
import io
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from reportlab.pdfgen import canvas

from financial_ingestion import extract


@pytest.mark.parametrize('unresolved,reverse', [(True, False), (False, False), (True, True)])
def test_otngk_keeps_clearer_rows_even_before_dates_resolve(monkeypatch, unresolved, reverse):
    source = json.loads(Path('tests/fixtures/financial_documents/otngk-2016-ocr.json').read_text(encoding='utf-8'))
    clear = source['refined']
    if unresolved:
        clear = clear.replace('31.12.2016', '??????????').replace('31.12.2015', '??????????')
    first, later = (clear, source['survey']) if reverse else (source['survey'], clear)
    output = io.BytesIO()
    pdf = canvas.Canvas(output)
    pdf.showPage()
    pdf.save()
    calls = []
    def recognize(command, **options):
        calls.append(command)
        return SimpleNamespace(stdout=first if len(calls) == 1 else later)
    monkeypatch.setattr(extract.shutil, 'which', lambda _: 'test-tesseract')
    monkeypatch.setattr(extract.subprocess, 'run', recognize)
    monkeypatch.setattr(extract.layout, 'tsv_text', lambda text: text)
    monkeypatch.setattr(extract.layout, 'tsv_words', lambda *args, **kwargs: [])
    monkeypatch.setattr(extract, 'deskew_image', lambda image: (image, 0))
    pages, evidence = extract.page_texts(output.getvalue(), ocr=True)
    assert len(calls) > 1
    assert pages[1] == clear
    assert evidence['ocr_errors'] == []

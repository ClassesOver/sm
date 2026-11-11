from __future__ import annotations

import hashlib
from io import BytesIO

from pptx import Presentation

from smart_reporting.reporting.delivery import pdf_native
from smart_reporting.reporting.tests.test_native_pdf_extract import source_pdf

def test_real_cli_conversion_returns_editable_pptx_and_source_identity():
    source=source_pdf();result=pdf_native.convert_pdf_office(source)
    assert result['sourceSha256']==hashlib.sha256(source).hexdigest();assert result['sha256']==hashlib.sha256(result['content']).hexdigest();assert result['size']==len(result['content'])
    deck=Presentation(BytesIO(result['content']));assert len(deck.slides)==3
    for slide,text in zip(deck.slides,['source page one','source page two','source page three']):assert text in '\n'.join(shape.text for shape in slide.shapes if shape.has_text_frame)
    assert result['validation']['ok'] is False

def test_bridge_retains_actual_written_file_when_receipt_fails(monkeypatch):
    deck=Presentation();deck.slides.add_slide(deck.slide_layouts[6]);stream=BytesIO();deck.save(stream);content=stream.getvalue()
    def fail_after_write(payload,root,**kwargs):
        from pathlib import Path
        Path(payload['output']).write_bytes(content);raise ValueError('receipt unavailable')
    monkeypatch.setattr(pdf_native,'_invoke',fail_after_write)
    result=pdf_native.convert_pdf_office(source_pdf());assert result['content']==content;assert result['sha256']==hashlib.sha256(content).hexdigest();assert result['validation']['ok'] is False;assert result['validation']['issues']

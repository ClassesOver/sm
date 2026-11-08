from __future__ import annotations

import hashlib
from io import BytesIO

import pytest
from pypdf import PdfReader
from reportlab.pdfgen.canvas import Canvas


def _pdf() -> bytes:
    stream = BytesIO()
    canvas = Canvas(stream, pagesize=(300, 400))
    for label in ('FIRST PAGE', 'SECOND PAGE', 'THIRD PAGE'):
        canvas.drawString(30, 350, label)
        canvas.showPage()
    canvas.save()
    return stream.getvalue()


def test_pdf_native_roundtrip_preserves_source_and_applies_page_annotations():
    from smart_reporting.reporting.delivery.pdf_native import inspect_pdf, patch_pdf

    source = _pdf()
    digest = hashlib.sha256(source).hexdigest()
    inspected = inspect_pdf(source)
    assert inspected['sourceSha256'] == digest
    assert inspected['pageCount'] == 3
    first, second, third = (page['pageId'] for page in inspected['pages'])
    assert inspect_pdf(source)['pages'][0]['pageId'] == first
    edited = patch_pdf(source, [
        {'kind': 'highlight', 'pageId': first, 'rect': [25, 345, 120, 365], 'color': [1, .8, 0]},
        {'kind': 'addTextAnnotation', 'pageId': first, 'rect': [150, 200, 174, 224], 'text': '审阅意见'},
        {'kind': 'rotatePage', 'pageId': first, 'delta': 90},
        {'kind': 'deletePage', 'pageId': second},
        {'kind': 'reorderPages', 'pageIds': [third, first]},
    ])
    result = PdfReader(BytesIO(edited))
    assert len(result.pages) == 2
    assert 'THIRD PAGE' in result.pages[0].extract_text()
    assert 'FIRST PAGE' in result.pages[1].extract_text()
    assert result.pages[1].get('/Rotate') == 90
    annotations = [item.get_object() for item in result.pages[1]['/Annots']]
    assert any(item['/Subtype'] == '/Highlight' and item.get('/QuadPoints') for item in annotations)
    assert any(item['/Subtype'] == '/Text' and item['/Contents'] == '审阅意见' for item in annotations)
    assert inspect_pdf(edited)['pages'][0]['pageId'] != third
    assert hashlib.sha256(source).hexdigest() == digest
    assert patch_pdf(source, []) is source
    with pytest.raises(ValueError):
        patch_pdf(edited, [{'kind': 'rotatePage', 'pageId': first, 'delta': 90}])


@pytest.mark.parametrize('invalid', [
    lambda p: [{'kind': 'deletePage', 'pageId': page['pageId']} for page in p],
    lambda p: [{'kind': 'reorderPages', 'pageIds': [p[0]['pageId']] * 3}],
    lambda p: [{'kind': 'rotatePage', 'pageId': p[0]['pageId'], 'delta': 45}],
    lambda p: [{'kind': 'rotatePage', 'pageId': p[0]['pageId'], 'delta': 90, 'sourceSha256': '0' * 64}],
    lambda p: [{'kind': 'highlight', 'pageId': p[0]['pageId'], 'rect': [0, 0, 500, 500]}],
    lambda p: [{'kind': 'highlight', 'pageId': p[0]['pageId'], 'rect': [0, 0, 10, 10], 'color': [2, 0, 0]}],
    lambda p: [{'kind': 'addTextAnnotation', 'pageId': p[0]['pageId'], 'rect': [0, 0, 10, 10], 'text': ''}],
    lambda p: [{'kind': 'rotatePage', 'pageId': p[0]['pageId'], 'delta': 90, 'injected': True}],
    lambda p: [{'kind': 'deletePage', 'pageId': 'unknown'}],
    lambda p: [{'kind': 'rotatePage', 'pageId': p[0]['pageId'], 'delta': 90}] * 501,
    lambda p: [{'kind': 'textEdits', 'pageId': p[0]['pageId']}],
    lambda p: [{'kind': 'deletePage', 'pageId': p[0]['pageId']}, {'kind': 'rotatePage', 'pageId': p[0]['pageId'], 'delta': 90}],
])
def test_pdf_native_rejects_invalid_operations_before_generating(invalid):
    from smart_reporting.reporting.delivery.pdf_native import inspect_pdf, patch_pdf

    source = _pdf()
    with pytest.raises(ValueError):
        patch_pdf(source, invalid(inspect_pdf(source)['pages']))

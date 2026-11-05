"""真实 PDFium 原位改字：身份、跳过与独立文本/渲染验收。"""
from __future__ import annotations

import hashlib
from io import BytesIO

import pytest
from pypdf import PdfReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas


def source_pdf(*, chinese=False, duplicate=False):
    stream = BytesIO()
    canvas = Canvas(stream, pagesize=(400, 300))
    if chinese:
        pdfmetrics.registerFont(TTFont('NativeTestCJK', '/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf'))
        canvas.setFont('NativeTestCJK', 14)
        text = '原始金额五百'
    else:
        canvas.setFont('Helvetica', 14)
        text = 'Amount due 500'
    canvas.setFillColorRGB(.88, .95, 1)
    canvas.rect(20, 195, 350, 65, stroke=0, fill=1)
    canvas.setFillColorRGB(0, 0, 0)
    canvas.drawString(30, 230, text)
    if duplicate:
        canvas.drawString(30, 200, text)
    canvas.setFont('Helvetica', 12)
    canvas.drawString(30, 160, 'UNCHANGED CONTROL')
    canvas.save()
    return stream.getvalue()


def text_operation(source, new_text, *, index=0):
    from smart_reporting.reporting.delivery.pdf_native import inspect_pdf
    page = inspect_pdf(source, include_text=True)['pages'][0]
    target = page['textObjects'][index]
    return {'kind': 'replaceText', 'pageId': page['pageId'], 'objectId': target['objectId'],
            'expectedTextSha256': target['expectedTextSha256'], 'newText': new_text}


def test_pdf_text_inspect_is_explicit_and_binds_source_objects():
    from smart_reporting.reporting.delivery.pdf_native import inspect_pdf
    source = source_pdf(duplicate=True)
    assert 'textObjects' not in inspect_pdf(source)['pages'][0]
    page = inspect_pdf(source, include_text=True)['pages'][0]
    objects = page['textObjects']
    assert len(objects) == 3
    assert objects[0]['text'] == objects[1]['text'] == 'Amount due 500'
    assert objects[0]['objectId'] != objects[1]['objectId']
    assert objects[0]['expectedTextSha256'] == hashlib.sha256(b'Amount due 500').hexdigest()
    assert inspect_pdf(source, include_text=True)['pages'][0]['textObjects'] == objects


@pytest.mark.parametrize(('chinese', 'new_text'), [(False, 'Amount due 750'), (False, '应付金额七百'), (True, '调整金额七百')])
def test_pdf_replace_text_real_engine_keeps_background_and_control(tmp_path, chinese, new_text):
    from smart_reporting.reporting.delivery.pdf_native import patch_pdf_with_receipt
    from PIL import Image, ImageChops
    import subprocess
    source = source_pdf(chinese=chinese)
    op = text_operation(source, new_text)
    receipt = patch_pdf_with_receipt(source, [op])
    assert receipt['skippedOperations'] == []
    assert receipt['appliedOperationIndices'] == [0]
    assert len(receipt['previewDigest']) == 64
    again = patch_pdf_with_receipt(source, [op])
    assert again['previewDigest'] == receipt['previewDigest']
    text = PdfReader(BytesIO(receipt['content'])).pages[0].extract_text()
    assert new_text in text and 'UNCHANGED CONTROL' in text
    assert ('原始金额五百' if chinese else 'Amount due 500') not in text
    assert not PdfReader(BytesIO(receipt['content'])).pages[0].get('/Annots')
    for name, content in [('source', source), ('edited', receipt['content'])]:
        (tmp_path / f'{name}.pdf').write_bytes(content)
        subprocess.run(['pdftoppm', '-r', '72', '-png', '-singlefile', str(tmp_path / f'{name}.pdf'), str(tmp_path / name)], check=True, capture_output=True)
    before, after = (Image.open(tmp_path / f'{name}.png').convert('RGB') for name in ['source', 'edited'])
    assert before.getpixel((25, 65)) == after.getpixel((25, 65))
    bounds = ImageChops.difference(before, after).getbbox()
    assert bounds and bounds[0] >= 25 and bounds[1] >= 50 and bounds[2] < 370 and bounds[3] < 95


def test_pdf_repeated_text_uses_object_identity_and_skips_invalid_without_loss(tmp_path):
    from smart_reporting.reporting.delivery.pdf_native import patch_pdf, patch_pdf_with_receipt
    source = source_pdf(duplicate=True)
    op = text_operation(source, 'Amount due 750', index=1)
    valid = patch_pdf_with_receipt(source, [op])
    text = PdfReader(BytesIO(valid['content'])).pages[0].extract_text()
    assert text.count('Amount due 500') == 1 and text.count('Amount due 750') == 1
    # The repeated text identity must change the second location, not just any match.
    import subprocess
    from PIL import Image, ImageChops
    for name, content in [('source', source), ('edited', valid['content'])]:
        (tmp_path / f'{name}.pdf').write_bytes(content)
        subprocess.run(['pdftoppm', '-r', '72', '-png', '-singlefile', str(tmp_path / f'{name}.pdf'), str(tmp_path / name)], check=True, capture_output=True)
    original, edited = (Image.open(tmp_path / f'{name}.png').convert('RGB') for name in ['source', 'edited'])
    bounds = ImageChops.difference(original, edited).getbbox()
    assert bounds and bounds[0] >= 25 and 85 <= bounds[1] < bounds[3] <= 105
    for change, reason in [({'objectId': 'unknown'}, 'identity'), ({'expectedTextSha256': '0' * 64}, 'identity'), ({'newText': 'X' * 1000}, 'overflow'), ({'newText': 'line one\nline two'}, 'overflow'), ({'newText': '\U0010ffff'}, 'font')]:
        operations = [{**op, **change}]
        result = patch_pdf_with_receipt(source, operations)
        assert result['content'] == source
        assert result['appliedOperationIndices'] == []
        assert len(result['skippedOperations']) == 1
        assert reason in result['skippedOperations'][0]['reason']
        with pytest.raises(ValueError, match='pdf_text_operations_skipped'):
            patch_pdf(source, operations)


def test_pdf_text_resources_use_actual_cjk_numeric_rebuild():
    from smart_reporting.reporting.delivery.pdf_native import check_text_resources
    result = check_text_resources()
    assert result['ok'] is True
    assert result['issues'] == []
    assert result['fonts'] and all(font['fontSha256'] for font in result['fonts'])


@pytest.mark.parametrize('neighbor', [False, True])
def test_pdf_text_growth_respects_page_edge_and_neighbor(neighbor):
    from smart_reporting.reporting.delivery.pdf_native import patch_pdf_with_receipt
    stream = BytesIO()
    canvas = Canvas(stream, pagesize=(400 if neighbor else 135, 300))
    canvas.setFont('Helvetica', 14)
    canvas.drawString(30, 230, 'Amount due 500')
    if neighbor:
        canvas.drawString(137, 230, 'NEXT')
    canvas.save()
    source = stream.getvalue()
    result = patch_pdf_with_receipt(source, [text_operation(source, 'Amount due 750')])
    assert result['content'] == source
    assert 'overflow' in result['skippedOperations'][0]['reason']


def test_pdf_mixed_text_success_retains_skipped_original_and_bounds_input():
    from smart_reporting.reporting.delivery.pdf_native import patch_pdf_with_receipt
    source = source_pdf(duplicate=True)
    valid, stale = text_operation(source, 'Amount due 750'), text_operation(source, 'Amount due 900', index=1)
    stale['expectedTextSha256'] = '0' * 64
    result = patch_pdf_with_receipt(source, [valid, stale])
    assert result['appliedOperationIndices'] == [0]
    assert result['skippedOperations'][0]['operationIndex'] == 1
    text = PdfReader(BytesIO(result['content'])).pages[0].extract_text()
    assert text.count('Amount due 500') == text.count('Amount due 750') == 1
    with pytest.raises(ValueError):
        patch_pdf_with_receipt(source, [{**valid, 'newText': 'x' * 4001}])


def test_pdf_preview_digest_binds_actual_wasm_bytes(tmp_path, monkeypatch):
    from smart_reporting.reporting.delivery.pdf_native import patch_pdf_with_receipt
    from smart_reporting.reporting.delivery.office_engine import engine_dir
    source = source_pdf()
    operations = [text_operation(source, '应付金额七百')]
    original = patch_pdf_with_receipt(source, operations)
    modules = engine_dir('pdf') / 'node_modules'
    (tmp_path / 'pdfium.wasm').write_bytes((modules / '@embedpdf/pdfium/dist/pdfium.wasm').read_bytes())
    # A valid empty custom section preserves WASM behavior but changes resource identity.
    (tmp_path / 'hb-subset.wasm').write_bytes((modules / 'harfbuzzjs/hb-subset.wasm').read_bytes() + b'\x00\x01\x00')
    monkeypatch.setenv('AGENT_REPORTING_PDF_WASM_DIR', str(tmp_path))
    changed = patch_pdf_with_receipt(source, operations)
    assert changed['skippedOperations'] == original['skippedOperations'] == []
    assert changed['previewDigest'] != original['previewDigest']


def test_pdf_ambiguous_overlaid_text_and_foreign_page_keep_original():
    from smart_reporting.reporting.delivery.pdf_native import patch_pdf_with_receipt
    stream = BytesIO()
    canvas = Canvas(stream, pagesize=(400, 300))
    for _ in range(2):
        canvas.drawString(30, 230, 'DUPLICATE')
    canvas.save()
    source = stream.getvalue()
    operation = text_operation(source, 'REPLACED')
    result = patch_pdf_with_receipt(source, [operation])
    assert result['content'] == source
    assert result['skippedOperations'][0]['reason'] == 'pdf_text_identity_ambiguous'
    result = patch_pdf_with_receipt(source, [{**operation, 'pageId': 'foreign'}])
    assert result['content'] == source
    assert 'identity' in result['skippedOperations'][0]['reason']

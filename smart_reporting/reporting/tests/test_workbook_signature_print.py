"""数据表紧凑布局不得裁掉独立落款。"""
from io import BytesIO

import pytest
from openpyxl import load_workbook
from pypdf import PdfReader

from smart_reporting.preferences.models import FormatPreferences, resolve_format_preferences
from smart_reporting.reporting.delivery.office_engine import libreoffice_to_pdf
from smart_reporting.reporting.delivery.xlsx import build_workbook


@pytest.mark.parametrize('size,chinese,orientation', [(12, False, 'portrait'), (72, False, 'portrait'), (72, True, 'landscape')])
def test_long_signature_print_ignores_business_dimensions_and_preserves_all_text(tmp_path, size, chinese, orientation):
    signer = ('编制复核' * 47 if chinese else 'SignatureIdentity ' * 10) + 'SIGNER_END'
    description = ('报告说明' * 145 if chinese else 'Detailed explanation ' * 20) + 'DESCRIPTION_END'
    prefs = resolve_format_preferences(FormatPreferences.model_validate({'common': {'signer': signer, 'dateFormat': 'iso'}, 'xlsx': {
        'rowHeight': 8, 'columnWidth': 2, 'wrapText': False,
        'signature': {'size': size, 'description': description},
        'print': {'headerFooter': {'enabled': False}, 'page': {'orientation': orientation}},
    }}), 'xlsx')
    path = tmp_path / 'long-signature.xlsx'
    built = build_workbook(output_path=path, title='Print', period='2026', sheets=({'name': 'Data', 'rows': [
        ['Item', 'Value'], ['Revenue', 1234.56]]},), preferences=prefs, generated_date='2026-11-12')
    book = load_workbook(path)
    notes = book['说明']
    assert notes['A2'].value == signer and notes['A4'].value == description
    assert notes['A2'].alignment.wrap_text
    assert notes['A2'].font.sz == notes['A3'].font.sz
    assert notes.column_dimensions['A'].width >= 60
    assert 8 < notes.row_dimensions[2].height <= 409
    assert book['Data'].row_dimensions[2].height == 8
    assert bool(built.issues) == (size == 72)
    if built.issues:
        assert built.issues[0]['code'] == 'workbook_signature_font_reduced'
    actual = PdfReader(BytesIO(libreoffice_to_pdf(path.read_bytes(), suffix='.xlsx', timeout=60)))
    text = '\n'.join(page.extract_text() for page in actual.pages)
    assert 'SIGNER_END' in text and 'DESCRIPTION_END' in text and '2026-11-12' in text
    compact = ''.join(text.split())
    assert ''.join(signer.split()) in compact
    assert ''.join(description.split()) in compact
    identity_page = next(page.extract_text() for page in actual.pages if 'SIGNER_END' in page.extract_text())
    assert '2026-11-12' in identity_page

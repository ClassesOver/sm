"""表格标题/说明保留物理内容，字符引用须符合标准 XML 回读。"""
from io import BytesIO
from zipfile import ZipFile

import pytest
from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

from smart_reporting.reporting.delivery.docx_native import inspect_docx, patch_docx
from smart_reporting.reporting.tests.test_docx_table_row_height import source


def anchor(content):
    return next(b for b in inspect_docx(content)['blocks'] if b['type'] == 'table')


def operation(content, title='表格标题', description='第一行\n第二行 & < > " 中文'):
    block = anchor(content)
    return {'kind': 'setTableAltText', 'blockId': block['blockId'],
            'expectedObjectSha256': block['expectedObjectSha256'],
            'title': title, 'description': description}


def test_alt_text_standard_xml_and_source_round_trip_with_other_parts_preserved():
    content = source()
    assert anchor(content).get('tableAltTextEditable') is True
    result = patch_docx(content, [operation(content)])
    table = Document(BytesIO(result)).tables[0]._tbl
    assert table.tblPr.find(qn('w:tblCaption')).get(qn('w:val')) == '表格标题'
    assert table.tblPr.find(qn('w:tblDescription')).get(qn('w:val')) == '第一行\n第二行 & < > " 中文'
    assert anchor(result)['tableAltTextSource']['description'] == '第一行\n第二行 & < > " 中文'
    before = Document(BytesIO(content)).tables[0]._tbl
    assert [row.xml for row in table.tr_lst] == [row.xml for row in before.tr_lst]
    with ZipFile(BytesIO(content)) as old, ZipFile(BytesIO(result)) as new:
        names = {i.filename for i in old.infolist() if not i.is_dir()}
        assert names == {i.filename for i in new.infolist() if not i.is_dir()}
        assert b'&#10;' in new.read('word/document.xml')
        for name in names - {'word/document.xml'}:
            assert old.read(name) == new.read(name), name
    cleared = patch_docx(result, [operation(result, '', '')])
    assert Document(BytesIO(cleared)).tables[0]._tbl.tblPr.find(qn('w:tblDescription')) is None
    assert anchor(cleared)['tableAltTextSource']['title'] == ''


def test_alt_text_literal_reference_and_hidden_continuation_are_preserved():
    doc = Document(BytesIO(source()))
    doc.tables[0].cell(0, 0).merge(doc.tables[0].cell(1, 0))
    continuation = doc.tables[0]._tbl.tr_lst[1].tc_lst[0]
    continuation.get_or_add_tcPr().append(OxmlElement('w:tcFitText'))
    run = OxmlElement('w:r')
    text = OxmlElement('w:t')
    text.text = '独立隐藏正文'
    run.append(text)
    continuation.p_lst[0].append(run)
    buffer = BytesIO()
    doc.save(buffer)
    content = buffer.getvalue()
    result = patch_docx(content, [operation(content, '&#10;', 'literal &#xA;\n实际换行')])
    table = Document(BytesIO(result)).tables[0]._tbl
    assert table.tblPr.find(qn('w:tblCaption')).get(qn('w:val')) == '&#10;'
    assert table.tblPr.find(qn('w:tblDescription')).get(qn('w:val')) == 'literal &#xA;\n实际换行'
    assert anchor(result)['tableAltTextSource']['title'] == '&#10;'
    assert table.tr_lst[1].tc_lst[0].xml == continuation.xml


@pytest.mark.parametrize('values', [
    {'title': 'bad\nline'}, {'title': 'a' * 256}, {'description': 'a' * 4097},
    {'description': '\x01'}, {'title': 1}, {'xml': '<w:tblCaption/>'},
])
def test_alt_text_rejects_invalid_values(values):
    content = source()
    with pytest.raises(ValueError):
        patch_docx(content, [{**operation(content), **values}])


def test_alt_text_identity_protection_and_same_table_batch():
    content = source()
    op = operation(content)
    with pytest.raises(ValueError):
        patch_docx(content, [{**op, 'expectedObjectSha256': '0' * 64}])
    with pytest.raises(ValueError):
        patch_docx(content, [op, op])
    doc = Document(BytesIO(content))
    protection = OxmlElement('w:documentProtection')
    protection.set(qn('w:edit'), 'readOnly')
    protection.set(qn('w:enforcement'), '1')
    doc.settings._element.append(protection)
    buffer = BytesIO()
    doc.save(buffer)
    protected = buffer.getvalue()
    assert anchor(protected)['tableAltTextEditable'] is False
    with pytest.raises(ValueError):
        patch_docx(protected, [operation(protected)])

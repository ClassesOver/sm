"""重复标题行可信源补丁：真实 DOCX、属性保留和重新解析。"""
from io import BytesIO
from zipfile import ZipFile

import pytest
from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from lxml import etree

from smart_reporting.reporting.delivery.docx_native import inspect_docx, patch_docx


def fixture():
    doc = Document()
    doc.add_paragraph('keep')
    table = doc.add_table(rows=3, cols=3)
    for r, row in enumerate(table.rows):
        props = row._tr.get_or_add_trPr()
        props.append(OxmlElement('w:cantSplit'))
        height = OxmlElement('w:trHeight')
        height.set(qn('w:val'), str(300 + r))
        props.append(height)
        for c, cell in enumerate(row.cells):
            cell.text = f'{r}:{c}'
    table.cell(1, 0).merge(table.cell(1, 1))
    output = BytesIO()
    doc.save(output)
    return output.getvalue()


def operation(source, headers):
    anchor = next(b for b in inspect_docx(source)['blocks'] if b['type'] == 'table')
    return dict(kind='setTableRepeatHeaders', blockId=anchor['blockId'],
                expectedObjectSha256=anchor['expectedObjectSha256'], expectedRowCount=3, prefixRowCount=2, headers=headers)


def test_repeat_headers_preserves_merged_cells_properties_and_package():
    source = fixture()
    enabled = patch_docx(source, [operation(source, [True, True, False])])
    after = Document(BytesIO(enabled))
    assert [r._tr.trPr.find(qn('w:tblHeader')) is not None for r in after.tables[0].rows] == [True, True, False]
    disabled = patch_docx(enabled, [operation(enabled, [False, False, False])])
    assert all(r._tr.trPr.find(qn('w:tblHeader')) is None for r in Document(BytesIO(disabled)).tables[0].rows)
    with ZipFile(BytesIO(source)) as before, ZipFile(BytesIO(disabled)) as result:
        names = {name for name in before.namelist() if not name.endswith('/')}
        assert names == {name for name in result.namelist() if not name.endswith('/')}
        for name in names:
            assert before.read(name) == result.read(name), name
    assert [c.text for c in after.tables[0].rows[1].cells] == ['1:0\n1:1', '1:0\n1:1', '1:2']
    original = Document(BytesIO(source)).tables[0]
    for left, right in zip(original.rows, after.tables[0].rows):
        props = etree.fromstring(etree.tostring(right._tr.trPr))
        for header in list(props.findall(qn('w:tblHeader'))):
            props.remove(header)
        assert etree.tostring(props, method='c14n') == etree.tostring(left._tr.trPr, method='c14n')


@pytest.mark.parametrize('field,value', [('expectedObjectSha256', 'foreign'), ('expectedRowCount', 2), ('headers', [True, None, False]), ('headers', [True]), ('xml', '<w:tbl/>')])
def test_repeat_headers_rejects_bad_identity_or_fields(field, value):
    source = fixture()
    op = operation(source, [True, False, False])
    op[field] = value
    with pytest.raises(ValueError):
        patch_docx(source, [op])

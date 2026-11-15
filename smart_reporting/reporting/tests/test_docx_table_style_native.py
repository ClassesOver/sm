from io import BytesIO
from zipfile import ZipFile
from docx import Document
from smart_reporting.reporting.delivery.docx_native import inspect_docx, patch_docx


def fixture():
    doc=Document();doc.add_paragraph('keep')
    for _ in range(2):
        table=doc.add_table(rows=2,cols=2)
        for row in table.rows:
            for cell in row.cells: cell.text='same'
    doc.sections[0].header.paragraphs[0].text='header keep'
    out=BytesIO();doc.save(out);return out.getvalue()


def test_table_style_targets_second_identical_table_and_preserves_other_parts():
    data=fixture();tables=[b for b in inspect_docx(data)['blocks']if b['type']=='table'];target=tables[1]
    assert target.get('tableStyleEditable') is True
    op={'kind':'setTableStyle','blockId':target['blockId'],'expectedObjectSha256':target['expectedObjectSha256'],'style':{'kind':'preset','id':'blue-header'}}
    result=patch_docx(data,[op]);doc=Document(BytesIO(result))
    assert 'D9EAF7' not in doc.tables[0]._tbl.xml
    assert 'D9EAF7' in doc.tables[1]._tbl.xml
    with ZipFile(BytesIO(data))as before,ZipFile(BytesIO(result))as after:
        assert set(before.namelist())==set(after.namelist())
        assert all(before.read(name)==after.read(name)for name in before.namelist()if name!='word/document.xml')

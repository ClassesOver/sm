from copy import deepcopy
from io import BytesIO
from zipfile import ZipFile

import pytest
from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from lxml import etree

from smart_reporting.reporting.delivery.docx_native import inspect_docx, patch_docx

NS={'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}


def fixture(only=False):
    doc=Document()
    if not only:doc.add_paragraph('Before keep')
    for _ in range(1 if only else 2):
        table=doc.add_table(rows=3,cols=2)
        for r,row in enumerate(table.rows):
            for c,cell in enumerate(row.cells):
                run=cell.paragraphs[0].add_run(f'Cell {r}/{c}');run.italic=True
        for tag,value in [('tblCaption','Caption keep'),('tblDescription','Description keep')]:
            node=OxmlElement('w:'+tag);node.set(qn('w:val'),value);table._tbl.tblPr.append(node)
        if not only:doc.add_paragraph('After keep')
    doc.sections[0].header.paragraphs[0].text='Header keep'
    stream=BytesIO();doc.save(stream);return stream.getvalue()


def operation(data,kind,index=-1,**extra):
    source=[b for b in inspect_docx(data)['blocks'] if b['type']=='table'][index]
    return {'kind':kind,'blockId':source['blockId'],'expectedObjectSha256':source['expectedObjectSha256'],**extra}


def unchanged_parts(source,saved):
    with ZipFile(BytesIO(source)) as a,ZipFile(BytesIO(saved)) as b:
        assert set(a.namelist())==set(b.namelist())
        for name in a.namelist():
            if name!='word/document.xml':assert a.read(name)==b.read(name),name
        return etree.fromstring(a.read('word/document.xml')),etree.fromstring(b.read('word/document.xml'))


def test_delete_exact_second_identical_table_keeps_neighbors_and_original_package():
    source=fixture();saved=patch_docx(source,[operation(source,'deleteTable')])
    before,after=unchanged_parts(source,saved)
    original=before.findall('./w:body/w:tbl',NS);remaining=after.findall('./w:body/w:tbl',NS)
    assert len(original)==2 and len(remaining)==1
    assert etree.tostring(original[0])==etree.tostring(remaining[0])
    assert [p.text for p in Document(BytesIO(saved)).paragraphs]==['Before keep','After keep','After keep']
    assert Document(BytesIO(saved)).sections[0].header.paragraphs[0].text=='Header keep'


def test_split_second_identical_table_preserves_exact_rows_and_resets_only_lower_alt_text():
    source=fixture();saved=patch_docx(source,[operation(source,'splitTable',row=1)])
    before,after=unchanged_parts(source,saved)
    original=before.findall('./w:body/w:tbl',NS);tables=after.findall('./w:body/w:tbl',NS)
    assert len(tables)==3
    assert etree.tostring(original[0])==etree.tostring(tables[0])
    rows=original[1].findall('w:tr',NS)
    assert [etree.tostring(r) for r in tables[1].findall('w:tr',NS)]==[etree.tostring(rows[0])]
    assert [etree.tostring(r) for r in tables[2].findall('w:tr',NS)]==[etree.tostring(r) for r in rows[1:]]
    assert tables[1].find('./w:tblPr/w:tblCaption',NS) is not None
    assert tables[2].find('./w:tblPr/w:tblCaption',NS) is None
    assert tables[2].find('./w:tblPr/w:tblDescription',NS) is None
    body=list(after.find('w:body',NS));at=body.index(tables[1])
    assert body[at+1].tag==qn('w:p') and not body[at+1].xpath('.//w:t',namespaces=NS)
    assert body[at+2] is tables[2]
    assert all(run.italic for table in Document(BytesIO(saved)).tables for row in table.rows for cell in row.cells for run in cell.paragraphs[0].runs)


def test_deleting_only_body_table_leaves_editable_empty_paragraph():
    source=fixture(only=True);saved=patch_docx(source,[operation(source,'deleteTable')])
    doc=Document(BytesIO(saved));assert not doc.tables
    assert len(doc.paragraphs)==1 and doc.paragraphs[0].text==''
    assert inspect_docx(saved)['blocks'][0]['editable'] is True


def test_lifecycle_refuses_stale_unknown_rows_mixed_and_protected_requests():
    source=fixture();valid=operation(source,'splitTable',row=1)
    for change in [{'row':0},{'row':3},{'expectedObjectSha256':'0'*64},{'rawXml':'<w:tbl/>'}]:
        with pytest.raises(ValueError):patch_docx(source,[{**valid,**change}])
    with pytest.raises(ValueError):patch_docx(source,[valid,deepcopy(valid)])
    document=Document(BytesIO(source));protection=OxmlElement('w:documentProtection');protection.set(qn('w:edit'),'readOnly');protection.set(qn('w:enforcement'),'1');document.settings.element.append(protection)
    stream=BytesIO();document.save(stream);protected=stream.getvalue()
    with pytest.raises(ValueError):patch_docx(protected,[operation(protected,'deleteTable')])

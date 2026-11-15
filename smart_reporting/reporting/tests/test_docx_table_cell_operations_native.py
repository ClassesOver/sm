from io import BytesIO
from zipfile import ZipFile
from copy import deepcopy
import pytest
from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from lxml import etree
from smart_reporting.reporting.delivery.docx_native import inspect_docx,patch_docx
NS={'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}


def fixture(only=False):
    doc=Document()
    if not only:doc.add_paragraph('Before KEEP')
    table=doc.add_table(rows=3,cols=3);table.autofit=False
    width=table._tbl.tblPr.find(qn('w:tblW'));width.set(qn('w:type'),'dxa');width.set(qn('w:w'),'7200')
    for node,w in zip(table._tbl.tblGrid, [1600,2400,3200]):node.set(qn('w:w'),str(w))
    for r,row in enumerate(table.rows):
        for c,cell in enumerate(row.cells):
            cell._tc.tcPr.find(qn('w:tcW')).set(qn('w:w'),str([1600,2400,3200][c]))
            p=cell.paragraphs[0];p.paragraph_format.space_after=0
            run=p.add_run(f'{r}/{c}');run.italic=True
            shd=OxmlElement('w:shd');shd.set(qn('w:fill'),['DDEEFF','FFEEDD','EEFFDD'][r]);cell._tc.tcPr.append(shd)
    if not only:doc.add_paragraph('After KEEP')
    doc.sections[0].header.paragraphs[0].text='Header KEEP'
    stream=BytesIO();doc.save(stream);return stream.getvalue()


def operation(data,change):
    target=next(b for b in inspect_docx(data)['blocks'] if b['type']=='table')
    return {'kind':'editTableCells','blockId':target['blockId'],'expectedObjectSha256':target['expectedObjectSha256'],'change':change}


def tree(data):
    with ZipFile(BytesIO(data)) as z:return etree.fromstring(z.read('word/document.xml'))


def texts(tbl):
    return [[''.join(c.xpath('.//w:t/text()',namespaces=NS)) for c in row.findall('w:tc',NS)] for row in tbl.findall('w:tr',NS)]


def preserved(source,saved):
    with ZipFile(BytesIO(source)) as a,ZipFile(BytesIO(saved)) as b:
        assert set(a.namelist())==set(b.namelist())
        for name in a.namelist():
            if name!='word/document.xml':assert a.read(name)==b.read(name),name
    assert [p.text for p in Document(BytesIO(saved)).paragraphs]==['Before KEEP','After KEEP']
    assert Document(BytesIO(saved)).sections[0].header.paragraphs[0].text=='Header KEEP'


@pytest.mark.parametrize('where',['above','below','left','right'])
def test_real_insert_cells_dialog_semantics_preserve_source_paragraphs(where):
    source=fixture();change={'type':'insert','where':where,'count':2 if where in ['above','below'] else 1,'rect':{'top':1,'left':1,'bottom':2,'right':2}}
    saved=patch_docx(source,[operation(source,change)]);preserved(source,saved)
    old=tree(source).find('./w:body/w:tbl',NS);new=tree(saved).find('./w:body/w:tbl',NS);rows=texts(new)
    if where=='above':expected=[['0/0','0/1','0/2'],['','',''],['','',''],['1/0','1/1','1/2'],['2/0','2/1','2/2']]
    elif where=='below':expected=[['0/0','0/1','0/2'],['1/0','1/1','1/2'],['','',''],['','',''],['2/0','2/1','2/2']]
    else:
        at=1 if where=='left' else 2;expected=[]
        for r in range(3):row=[f'{r}/{c}' for c in range(3)];row.insert(at,'');expected.append(row)
    assert rows==expected
    for old_cell in old.findall('w:tr/w:tc',NS):
        value=''.join(old_cell.xpath('.//w:t/text()',namespaces=NS));matches=[c for c in new.findall('w:tr/w:tc',NS) if ''.join(c.xpath('.//w:t/text()',namespaces=NS))==value]
        assert len(matches)==1
        assert [etree.tostring(p) for p in matches[0].findall('w:p',NS)]==[etree.tostring(p) for p in old_cell.findall('w:p',NS)]


@pytest.mark.parametrize('mode',['shiftLeft','shiftUp','row','column'])
def test_real_delete_cells_modes_relocate_exact_source_paragraphs(mode):
    source=fixture();change={'type':'delete','mode':mode,'rect':{'top':1,'left':1,'bottom':2,'right':2}}
    saved=patch_docx(source,[operation(source,change)]);preserved(source,saved)
    old=tree(source).find('./w:body/w:tbl',NS);new=tree(saved).find('./w:body/w:tbl',NS)
    expected={'shiftLeft':[['0/0','0/1','0/2'],['1/0','1/2'],['2/0','2/1','2/2']], 'shiftUp':[['0/0','0/1','0/2'],['1/0','2/1','1/2'],['2/0','','2/2']], 'row':[['0/0','0/1','0/2'],['2/0','2/1','2/2']], 'column':[['0/0','0/2'],['1/0','1/2'],['2/0','2/2']]}[mode]
    assert texts(new)==expected
    originals={''.join(c.xpath('.//w:t/text()',namespaces=NS)):[etree.tostring(p) for p in c.findall('w:p',NS)] for c in old.findall('w:tr/w:tc',NS)}
    for c in new.findall('w:tr/w:tc',NS):
        value=''.join(c.xpath('.//w:t/text()',namespaces=NS))
        if value:assert [etree.tostring(p) for p in c.findall('w:p',NS)]==originals[value]
    if mode=='shiftLeft':assert new.findall('w:tr',NS)[1].find('./w:trPr/w:gridAfter',NS).get(qn('w:val'))=='1'


@pytest.mark.parametrize('mode',['row','column','shiftLeft'])
def test_complete_table_cell_deletion_leaves_legal_editable_paragraph(mode):
    source=fixture(only=True);saved=patch_docx(source,[operation(source,{'type':'delete','mode':mode,'rect':{'top':0,'left':0,'bottom':3,'right':3}})])
    doc=Document(BytesIO(saved));assert not doc.tables
    assert len(doc.paragraphs)==1 and doc.paragraphs[0].text==''
    assert inspect_docx(saved)['blocks'][0]['editable'] is True


def test_cell_operation_rejects_bad_coordinates_unknown_fields_stale_and_mixed():
    source=fixture();valid=operation(source,{'type':'delete','mode':'shiftUp','rect':{'top':0,'left':0,'bottom':1,'right':1}})
    bad=[]
    for rect in [{'top':-1,'left':0,'bottom':1,'right':1},{'top':0,'left':0,'bottom':4,'right':1}]:x=deepcopy(valid);x['change']['rect']=rect;bad.append(x)
    bad.extend([{**valid,'expectedObjectSha256':'0'*64},{**valid,'rawXml':'<w:tbl/>'},{**valid,'change':{**valid['change'],'mode':'bad'}}])
    for op in bad:
        with pytest.raises(ValueError):patch_docx(source,[op])
    with pytest.raises(ValueError):patch_docx(source,[valid,valid])

from io import BytesIO
from docx import Document
from docx.oxml.ns import qn
from smart_reporting.reporting.delivery.docx_native import inspect_docx,patch_docx


def test_new_rich_paragraph_real_native_pipeline_preserves_format_and_neighbor():
    doc=Document();doc.add_paragraph('keep');doc.sections[0].header.paragraphs[0].text='header keep';out=BytesIO();doc.save(out);data=out.getvalue()
    a=inspect_docx(data)['blocks'][0]
    op={'kind':'insertRichParagraph','blockId':a['blockId'],'expectedObjectSha256':a['expectedObjectSha256'],'position':'after','paragraph':{'type':'paragraph','format':{'align':'center','spaceAfter':240},'runs':[{'text':'rich new','bold':True,'color':'112233','sizeHalfPoints':28}]}}
    result=patch_docx(data,[op]);changed=Document(BytesIO(result))
    assert [p.text for p in changed.paragraphs]==['keep','rich new']
    assert changed.paragraphs[1].runs[0].bold is True
    assert changed.paragraphs[1]._p.pPr.find(qn('w:jc')).get(qn('w:val'))=='center'
    assert changed.paragraphs[1].runs[0]._r.rPr.find(qn('w:color')).get(qn('w:val'))=='112233'
    assert changed.sections[0].header.paragraphs[0].text=='header keep'


def test_source_bound_run_format_uses_verified_original_and_never_accepts_raw_xml():
    from copy import deepcopy
    import pytest
    from lxml import etree
    from zipfile import ZipFile
    doc=Document();doc.add_paragraph().add_run('Italic original').italic=True
    doc.add_paragraph('Neighbor keep');out=BytesIO();doc.save(out);data=out.getvalue()
    a=inspect_docx(data)['blocks'][0]
    ref={key:a[key] for key in ('blockId','expectedObjectSha256')};ref['from']=0
    op={'kind':'insertRichParagraph','blockId':a['blockId'],'expectedObjectSha256':a['expectedObjectSha256'],'position':'after','paragraph':{'type':'paragraph','format':{'indentLeft':360,'spaceAfter':160},'runs':[{'text':'Inherited italic','italic':True,'sourceFormat':ref}]}}
    result=patch_docx(data,[op]);changed=Document(BytesIO(result))
    assert [p.text for p in changed.paragraphs]==['Italic original','Inherited italic','Neighbor keep']
    assert changed.paragraphs[1].runs[0].italic is True
    assert changed.paragraphs[1]._p.pPr.find(qn('w:ind')).get(qn('w:left'))=='360'
    with ZipFile(BytesIO(data)) as source,ZipFile(BytesIO(result)) as saved:
        ns={'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
        before=etree.fromstring(source.read('word/document.xml')).findall('./w:body/w:p',ns)
        after=etree.fromstring(saved.read('word/document.xml')).findall('./w:body/w:p',ns)
        assert etree.tostring(before[0])==etree.tostring(after[0])
        assert etree.tostring(before[1])==etree.tostring(after[2])
    for key,value in [('from',999),('expectedObjectSha256','0'*64)]:
        invalid=deepcopy(op);invalid['paragraph']['runs'][0]['sourceFormat'][key]=value
        with pytest.raises(ValueError):patch_docx(data,[invalid])
    invalid=deepcopy(op);invalid['paragraph']['runs'][0]['rawRPr']='<w:rPr><w:emboss/></w:rPr>'
    with pytest.raises(ValueError):patch_docx(data,[invalid])

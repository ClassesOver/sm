from io import BytesIO
from zipfile import ZipFile

import pytest
from docx import Document
from docx.oxml.ns import qn
from lxml import etree
from smart_reporting.reporting.tests.test_docx_cell_shading import source as rich_source
from smart_reporting.reporting.delivery.docx_native import inspect_docx, patch_docx

@pytest.mark.parametrize('shade_first',[True,False])
@pytest.mark.parametrize('fill',['00B050',None])
def test_source_border_and_shading_compose_in_same_trusted_table(shade_first,fill):
    content=rich_source.__wrapped__()
    table=next(block for block in inspect_docx(content)['blocks'] if block['type']=='table')
    cell=table['cells'][0][0]
    borders={'kind':'setTableCellBorders','blockId':table['blockId'],'expectedObjectSha256':table['expectedObjectSha256'],
             'steps':[{'range':None,'mode':'outer','pen':{'style':'double','szEighths':12,'color':'FF0000'}}]}
    shading={'kind':'setCellShading','blockId':table['blockId'],'cellId':cell['cellId'],'expectedObjectSha256':cell['expectedObjectSha256'],'fill':fill}
    edited=patch_docx(content,[shading,borders] if shade_first else [borders,shading])
    a,b=ZipFile(BytesIO(content)),ZipFile(BytesIO(edited))
    names={name for name in a.namelist() if not name.endswith('/')}
    assert names=={name for name in b.namelist() if not name.endswith('/')}
    for name in names-{'word/document.xml'}:assert a.read(name)==b.read(name),name
    before=Document(BytesIO(content)).tables[0];after=Document(BytesIO(edited)).tables[0]
    for r,row in enumerate(before.rows):
        for c,original in enumerate(row.cells):assert [etree.tostring(p._p) for p in original.paragraphs]==[etree.tostring(p._p) for p in after.cell(r,c).paragraphs]
    direct=after.cell(0,0)._tc.tcPr.find(qn('w:shd'))
    assert direct is None if fill is None else direct.get(qn('w:fill'))==fill
    line=after.cell(0,0)._tc.tcPr.find(qn('w:tcBorders')).find(qn('w:top'))
    assert (line.get(qn('w:val')),line.get(qn('w:color')))==('double','FF0000')

@pytest.mark.parametrize('shade_first',[True,False])
def test_none_and_null_compose_without_leaking_table_borders(shade_first):
    from docx.oxml import OxmlElement
    doc=Document(BytesIO(rich_source.__wrapped__()))
    table=doc.tables[0]
    table_borders=OxmlElement('w:tblBorders')
    for name in ['insideH','insideV']:
        edge=OxmlElement('w:'+name);edge.set(qn('w:val'),'single');table_borders.append(edge)
    table._tbl.tblPr.append(table_borders)
    output=BytesIO();doc.save(output);content=output.getvalue()
    anchor=next(block for block in inspect_docx(content)['blocks'] if block['type']=='table');cell=anchor['cells'][0][0]
    border={'kind':'setTableCellBorders','blockId':anchor['blockId'],'expectedObjectSha256':anchor['expectedObjectSha256'],'steps':[{'range':{'fromCellId':cell['cellId'],'toCellId':cell['cellId']},'mode':'none','pen':{'style':'single','szEighths':4,'color':'000000'}}]}
    shade={'kind':'setCellShading','blockId':anchor['blockId'],'cellId':cell['cellId'],'expectedObjectSha256':cell['expectedObjectSha256'],'fill':None}
    result=patch_docx(content,[shade,border] if shade_first else [border,shade])
    table=Document(BytesIO(result)).tables[0];properties=table.cell(0,0)._tc.tcPr
    assert properties.find(qn('w:shd')) is None
    for side in ['top','left','bottom','right','tl2br','tr2bl']:assert properties.find(qn('w:tcBorders')).find(qn('w:'+side)).get(qn('w:val'))=='none'
    assert all(table._tbl.tblPr.find(qn('w:tblBorders')).find(qn('w:'+name)) is None for name in ['insideH','insideV'])
    assert ZipFile(BytesIO(content)).read('word/styles.xml')==ZipFile(BytesIO(result)).read('word/styles.xml')

@pytest.mark.parametrize('fault',['duplicate-border','duplicate-shade','stale-shade','foreign-cell','mixed-text','mixed-structure','extra-field'])
def test_combination_keeps_original_identity_and_other_conflicts(fault):
    content=rich_source.__wrapped__();anchor=next(block for block in inspect_docx(content)['blocks'] if block['type']=='table');cell=anchor['cells'][1][1]
    border={'kind':'setTableCellBorders','blockId':anchor['blockId'],'expectedObjectSha256':anchor['expectedObjectSha256'],'steps':[{'range':None,'mode':'outer','pen':{'style':'single','szEighths':4,'color':'000000'}}]}
    shade={'kind':'setCellShading','blockId':anchor['blockId'],'cellId':cell['cellId'],'expectedObjectSha256':cell['expectedObjectSha256'],'fill':'00B050'}
    operations=[border,shade]
    if fault=='duplicate-border':operations.append(border)
    elif fault=='duplicate-shade':operations.append(shade)
    elif fault=='stale-shade':shade['expectedObjectSha256']='foreign'
    elif fault=='foreign-cell':shade['cellId']='foreign'
    elif fault=='mixed-text':operations.append({'kind':'replaceCellText','blockId':anchor['blockId'],'cellId':cell['cellId'],'expectedObjectSha256':cell['expectedObjectSha256'],'text':'no'})
    elif fault=='mixed-structure':operations.append({'kind':'insertTableRow','blockId':anchor['blockId'],'expectedObjectSha256':anchor['expectedObjectSha256'],'index':1})
    else:shade['xml']='<w:shd/>'
    with pytest.raises(ValueError):patch_docx(content,operations)

def test_none_null_orders_produce_identical_xml_and_preserve_unselected_theme_diagonal():
    from docx.oxml import OxmlElement
    doc=Document(BytesIO(rich_source.__wrapped__()));table=doc.tables[0]
    table_borders=OxmlElement('w:tblBorders')
    for name in ['insideH','insideV']:
        edge=OxmlElement('w:'+name);edge.set(qn('w:val'),'single');table_borders.append(edge)
    table._tbl.tblPr.append(table_borders)
    cell_borders=OxmlElement('w:tcBorders');diagonal=OxmlElement('w:tl2br');diagonal.set(qn('w:val'),'double');diagonal.set(qn('w:themeColor'),'accent2');diagonal.set(qn('w:themeTint'),'80');cell_borders.append(diagonal);table.cell(1,1)._tc.get_or_add_tcPr().append(cell_borders)
    expected_diagonal=etree.tostring(diagonal)
    output=BytesIO();doc.save(output);content=output.getvalue()
    anchor=next(block for block in inspect_docx(content)['blocks'] if block['type']=='table');cell=anchor['cells'][0][0]
    border={'kind':'setTableCellBorders','blockId':anchor['blockId'],'expectedObjectSha256':anchor['expectedObjectSha256'],'steps':[{'range':{'fromCellId':cell['cellId'],'toCellId':cell['cellId']},'mode':'none','pen':{'style':'single','szEighths':4,'color':'000000'}}]}
    shade={'kind':'setCellShading','blockId':anchor['blockId'],'cellId':cell['cellId'],'expectedObjectSha256':cell['expectedObjectSha256'],'fill':None}
    a=patch_docx(content,[border,shade]);b=patch_docx(content,[shade,border])
    za,zb,original=ZipFile(BytesIO(a)),ZipFile(BytesIO(b)),ZipFile(BytesIO(content))
    names={name for name in original.namelist() if not name.endswith('/')}
    for name in names:
        assert za.read(name)==zb.read(name),name
        if name!='word/document.xml':assert za.read(name)==original.read(name),name
    result=Document(BytesIO(a)).tables[0]
    assert result.cell(0,0)._tc.tcPr.find(qn('w:shd')) is None
    assert all(result._tbl.tblPr.find(qn('w:tblBorders')).find(qn('w:'+name)) is None for name in ['insideH','insideV'])
    assert etree.tostring(result.cell(1,1)._tc.tcPr.find(qn('w:tcBorders')).find(qn('w:tl2br')))==expected_diagonal

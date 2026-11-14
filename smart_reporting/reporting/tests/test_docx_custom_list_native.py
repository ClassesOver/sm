"""自定义多级列表经 Python 白名单进入真实 DOCX 桥并独立回读。"""
from io import BytesIO
from zipfile import ZipFile

from docx import Document
from docx.oxml.ns import qn
from lxml import etree

from smart_reporting.reporting.delivery.docx_native import inspect_docx, patch_docx


def test_custom_multilevel_list_passes_native_boundary_and_preserves_source():
    document = Document()
    document.add_paragraph('第一段').runs[0].bold = True
    document.add_paragraph('第二段')
    document.add_heading('保留标题', level=1)
    stream = BytesIO()
    document.save(stream)
    source = stream.getvalue()
    targets = inspect_docx(source)['blocks'][:2]
    levels = [
        {'numFmt': 'decimal', 'lvlText': '第%1章' if i == 0 else '.'.join(f'%{j + 1}' for j in range(i + 1)),
         'indentLeft': 720 * (i + 1), 'hanging': 360, 'start': 4 if i == 0 else 1}
        for i in range(9)
    ]
    result = patch_docx(source, [
        {'kind': 'setParagraphCustomList', 'blockId': target['blockId'],
         'expectedObjectSha256': target['expectedObjectSha256'],
         'definitionId': 'shared-custom-list', 'levels': levels, 'ilvl': i}
        for i, target in enumerate(targets)
    ])
    reopened = Document(BytesIO(result))
    refs = [p._p.xpath('./w:pPr/w:numPr/w:numId')[0].get(qn('w:val')) for p in reopened.paragraphs[:2]]
    assert refs[0] == refs[1]
    assert reopened.paragraphs[0].runs[0].bold is True
    assert [p.text for p in reopened.paragraphs] == ['第一段', '第二段', '保留标题']
    assert reopened.paragraphs[2]._p.xml == document.paragraphs[2]._p.xml
    with ZipFile(BytesIO(source)) as before, ZipFile(BytesIO(result)) as after:
        ns = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
        numbering = etree.fromstring(after.read('word/numbering.xml'))
        abstract = numbering.xpath(f'./w:num[@w:numId="{refs[0]}"]/w:abstractNumId/@w:val', namespaces=ns)[0]
        definition = numbering.xpath(f'./w:abstractNum[@w:abstractNumId="{abstract}"]', namespaces=ns)[0]
        assert len(definition.findall('w:lvl', ns)) == 9
        assert definition.xpath('./w:lvl[@w:ilvl="0"]/w:lvlText/@w:val', namespaces=ns) == ['第%1章']
        assert definition.xpath('./w:lvl[@w:ilvl="0"]/w:start/@w:val', namespaces=ns) == ['4']
        for name in before.namelist():
            if name not in {'word/document.xml', 'word/numbering.xml', 'docProps/core.xml'}:
                assert before.read(name) == after.read(name), name
    assert stream.getvalue() == source

from io import BytesIO
from zipfile import ZipFile
import pytest
from docx import Document
from lxml import etree
from smart_reporting.reporting.delivery.docx_native import inspect_docx, patch_docx


def source():
    doc = Document(); doc.add_paragraph('anchor'); doc.add_paragraph('tail')
    out = BytesIO(); doc.save(out); return out.getvalue()


def operation(data, object):
    a = inspect_docx(data)['blocks'][0]
    return dict(kind='insertDocxObject', blockId=a['blockId'], expectedObjectSha256=a['expectedObjectSha256'], position='after', object=object)


@pytest.mark.parametrize('obj,expected', [({'type':'textbox','text':'box <&中文'},'box <&中文'),({'type':'shape','preset':'ellipse','text':'shape'},'shape'),({'type':'shape','preset':'lineArrow'},''),({'type':'wordArt','preset':'green-italic','text':'艺术字'},'艺术字')])
def test_objects_save_editable_ooxml_and_preserve_parts(obj, expected):
    data = source(); result = patch_docx(data, [operation(data,obj)])
    with ZipFile(BytesIO(data)) as before, ZipFile(BytesIO(result)) as after:
        xml = etree.fromstring(after.read('word/document.xml'))
        ns = {'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main','wps':'http://schemas.microsoft.com/office/word/2010/wordprocessingShape','mc':'http://schemas.openxmlformats.org/markup-compatibility/2006'}
        assert xml.xpath('count(//wps:wsp)',namespaces=ns) == 1
        assert ''.join(xml.xpath('//mc:Choice//w:txbxContent//w:t/text()',namespaces=ns)) == expected
        for name in before.namelist():
            if name not in {'word/document.xml','docProps/core.xml'}: assert after.read(name) == before.read(name), name
    assert len(inspect_docx(result)['blocks']) == 3


@pytest.mark.parametrize('obj', [{'type':'shape','preset':'evil"/><x>'},{'type':'textbox','xml':'<w:p/>'},{'type':'wordArt','preset':'missing'},{'type':'textbox','widthEmu':0},{'type':'textbox','text':'\x01'}])
def test_objects_reject_untrusted_parameters(obj):
    data=source()
    with pytest.raises(Exception): patch_docx(data,[operation(data,obj)])

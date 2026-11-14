from io import BytesIO
from zipfile import ZipFile
from lxml import etree as E
from docx import Document
from smart_reporting.reporting.delivery.docx_native import inspect_docx,patch_docx


def source():
    doc=Document();doc.add_paragraph('keep');doc.sections[0].header.paragraphs[0].text='header keep'
    out=BytesIO();doc.save(out);return out.getvalue()


def test_mirrored_margins_and_section_margins_save_as_one_batch():
    data=source();model=inspect_docx(data);section=model['sections'][0]
    result=patch_docx(data,[{'kind':'setMirrorMargins','expectedSettingsSha256':model['documentProtection']['expectedSettingsSha256'],'enabled':True},{'kind':'setSectionLayout','sectionId':section['sectionId'],'expectedSectionSha256':section['expectedSectionSha256'],'values':{'marginLeft':1800,'marginRight':1440}}])
    model2=inspect_docx(result)
    with ZipFile(BytesIO(result))as z:
        ns={'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
        assert E.fromstring(z.read('word/settings.xml')).find('w:mirrorMargins',ns)is not None
    assert Document(BytesIO(result)).sections[0].header.paragraphs[0].text=='header keep'
    assert model2['sections'][0]['settings']['marginLeft']==1800

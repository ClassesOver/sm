"""Legal uploaded DOCX without settings and self-closing paragraphs remain editable."""
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

import pytest
from docx import Document
from lxml import etree

from smart_reporting.reporting.delivery.docx_native import inspect_docx, patch_docx

W='http://schemas.openxmlformats.org/wordprocessingml/2006/main'

@pytest.fixture
def source_runtime(tmp_path,monkeypatch):
    engine=Path(__file__).resolve().parents[1]/'doc_engine';runtime=tmp_path/'engine';runtime.mkdir()
    for name in ('bridge','packages','node_modules'):(runtime/name).symlink_to(engine/name,target_is_directory=True)
    monkeypatch.setenv('AGENT_REPORTING_DOC_ENGINE_DIR',str(runtime))


def uploaded_empty_paragraph(*,self_closing,settings):
    document=Document();document.add_paragraph('');stream=BytesIO();document.save(stream)
    result=BytesIO()
    with ZipFile(BytesIO(stream.getvalue())) as original,ZipFile(result,'w') as target:
        for entry in original.infolist():
            if not settings and entry.filename=='word/settings.xml':continue
            raw=original.read(entry)
            if entry.filename=='word/document.xml':
                root=etree.fromstring(raw);body=root.find('{'+W+'}body');paragraph=body.find('{'+W+'}p')
                paragraph.set('{'+W+'}rsidR','00ABCDEF');paragraph.set('custom-marker','keep/me > still')
                raw=etree.tostring(root,xml_declaration=True,encoding='UTF-8')
                if not self_closing:
                    raw=raw.replace(b'custom-marker="keep/me &gt; still"/>',b'custom-marker="keep/me &gt; still"></w:p>')
            elif not settings and entry.filename in ('word/_rels/document.xml.rels','[Content_Types].xml'):
                root=etree.fromstring(raw)
                for child in list(root):
                    if child.get('Target')=='settings.xml' or child.get('PartName')=='/word/settings.xml':root.remove(child)
                raw=etree.tostring(root,xml_declaration=True,encoding='UTF-8')
            target.writestr(entry,raw)
    return result.getvalue()


@pytest.mark.parametrize('self_closing',[False,True])
@pytest.mark.parametrize('settings',[False,True])
def test_real_inspect_replace_strict_xml_retains_empty_paragraph_attributes(source_runtime,self_closing,settings):
    raw=uploaded_empty_paragraph(self_closing=self_closing,settings=settings)
    # This fixture is a legal uploaded file, independently checked before the native reader.
    assert Document(BytesIO(raw)).paragraphs[0].text==''
    model=inspect_docx(raw);block=model['blocks'][0]
    assert model['documentProtection']['contentLocked'] is False
    output=patch_docx(raw,[{'kind':'replaceParagraph','blockId':block['blockId'],
        'expectedObjectSha256':block['expectedObjectSha256'],'text':'First <trusted> & editable text'}])
    with ZipFile(BytesIO(raw)) as original,ZipFile(BytesIO(output)) as saved:
        for name in saved.namelist():
            if name.endswith('.xml') or name.endswith('.rels'):etree.fromstring(saved.read(name))
        root=etree.fromstring(saved.read('word/document.xml'));paragraph=root.find('.//{'+W+'}body/{'+W+'}p')
        assert paragraph.get('{'+W+'}rsidR')=='00ABCDEF'
        assert paragraph.get('custom-marker')=='keep/me > still'
        assert ('word/settings.xml' in saved.namelist())==settings
        for name in original.namelist():
            if name not in {'word/document.xml','docProps/core.xml','docProps/app.xml'}:assert saved.read(name)==original.read(name)
    assert Document(BytesIO(output)).paragraphs[0].text=='First <trusted> & editable text'
    reopened=inspect_docx(output)
    assert reopened['blocks'][0]['text']=='First <trusted> & editable text'

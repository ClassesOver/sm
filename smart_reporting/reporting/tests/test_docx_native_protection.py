"""Protect Document: independently inspect OOXML, password boundary, part preservation."""
from io import BytesIO
from zipfile import ZipFile

from docx import Document
from lxml import etree
import pytest

from smart_reporting.reporting.delivery import docx_native
from smart_reporting.reporting.tests.test_docx_comment_text_host import NS, W, isolated_bundled_engine


def _source():
    document = Document()
    document.add_paragraph('文档保护原文')
    stream = BytesIO()
    document.save(stream)
    return stream.getvalue()


def _op(model, action, password='', mode='readOnly'):
    operation = dict(kind='setDocumentProtection', action=action, password=password,
                     expectedSettingsSha256=model['expectedSettingsSha256'],
                     expectedProtectionSha256=model['expectedProtectionSha256'])
    if action == 'enable':
        operation['mode'] = mode
    return operation


def _settings(content):
    with ZipFile(BytesIO(content)) as archive:
        return etree.fromstring(archive.read('word/settings.xml'))


def test_document_protection_save_readback_password_and_preservation(tmp_path, monkeypatch):
    isolated_bundled_engine(tmp_path, monkeypatch)
    source = _source()
    model = docx_native.inspect_docx(source)['documentProtection']
    saved = docx_native.patch_docx(source, [_op(model, 'enable', 'correct-password')])
    restriction = _settings(saved).find(f'{{{W}}}documentProtection')
    assert restriction is not None
    assert restriction.get(f'{{{W}}}edit') == 'readOnly'
    assert restriction.get(f'{{{W}}}enforcement') == '1'
    assert restriction.get(f'{{{W}}}cryptAlgorithmSid') == '14'
    assert restriction.get(f'{{{W}}}hash')
    assert b'correct-password' not in etree.tostring(restriction)
    with ZipFile(BytesIO(source)) as before, ZipFile(BytesIO(saved)) as after:
        changed = {name for name in before.namelist() if before.read(name) != after.read(name)}
        assert changed <= {'word/settings.xml', 'docProps/core.xml'}
        assert 'word/settings.xml' in changed
    reopened = docx_native.inspect_docx(saved)['documentProtection']
    assert reopened['contentLocked'] is True and reopened['hasPassword'] is True
    with pytest.raises(ValueError):
        docx_native.patch_docx(saved, [_op(reopened, 'disable', 'wrong-password')])
    with pytest.raises(ValueError):
        docx_native.patch_docx(saved, [_op(model, 'disable', 'correct-password')])
    unlocked = docx_native.patch_docx(saved, [_op(reopened, 'disable', 'correct-password')])
    assert _settings(unlocked).find(f'{{{W}}}documentProtection') is None
    assert docx_native.inspect_docx(unlocked)['documentProtection']['contentLocked'] is False
    assert Document(BytesIO(unlocked)).paragraphs[0].text == '文档保护原文'


@pytest.mark.parametrize('mode', ['trackedChanges', 'comments', 'forms'])
def test_document_protection_passwordless_modes(tmp_path, monkeypatch, mode):
    isolated_bundled_engine(tmp_path, monkeypatch)
    source = _source()
    saved = docx_native.patch_docx(source, [_op(docx_native.inspect_docx(source)['documentProtection'], 'enable', mode=mode)])
    model = docx_native.inspect_docx(saved)['documentProtection']
    assert model['protection']['edit'] == mode and model['contentLocked'] is True
    unlocked = docx_native.patch_docx(saved, [_op(model, 'disable')])
    assert _settings(unlocked).find(f'{{{W}}}documentProtection') is None

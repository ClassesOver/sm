"""真实 Python 薄桥到打包 doc engine 的批注纯文字编辑回归。"""
from io import BytesIO
import hashlib
import json
from pathlib import Path
import subprocess
from unittest.mock import AsyncMock
from zipfile import ZipFile, ZIP_DEFLATED

from docx import Document
from lxml import etree
import pytest

from smart_reporting.reporting.delivery import docx_native
from smart_reporting.reporting.delivery.office_engine import run_bridge

ENGINE = Path(__file__).resolve().parents[1] / 'doc_engine'
W = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
R = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
NS = {'w': W}
COMMENTS = '<w:comments xmlns:w="' + W + '"><w:comment w:id="1" w:author="Alice"><w:p><w:r><w:t>Original note</w:t></w:r></w:p></w:comment></w:comments>'
ANCHOR = ('<w:p><w:commentRangeStart w:id="1"/><w:r><w:t>Anchor text</w:t></w:r>'
          '<w:commentRangeEnd w:id="1"/><w:r><w:commentReference w:id="1"/></w:r></w:p>')


def source():
    document = Document()
    document.add_paragraph('Anchor text')
    stream = BytesIO()
    document.save(stream)
    output = BytesIO()
    with ZipFile(BytesIO(stream.getvalue())) as original, ZipFile(output, 'w', ZIP_DEFLATED) as edited:
        for name in original.namelist():
            data = original.read(name)
            if name == 'word/document.xml':
                data = data.replace(b'<w:p><w:r><w:t>Anchor text</w:t></w:r></w:p>', ANCHOR.encode())
            elif name == 'word/_rels/document.xml.rels':
                data = data.replace(b'</Relationships>', (f'<Relationship Id="rId20" Type="{R}/comments" Target="comments.xml"/></Relationships>').encode())
            elif name == '[Content_Types].xml':
                data = data.replace(b'</Types>', b'<Override PartName="/word/comments.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.comments+xml"/></Types>')
            edited.writestr(name, data)
        edited.writestr('word/comments.xml', COMMENTS.encode())
    return output.getvalue()


def isolated_bundled_engine(tmp_path, monkeypatch):
    runtime = tmp_path / 'doc-engine-runtime'
    runtime.mkdir()
    for name in ('bridge', 'packages', 'node_modules', 'package.json'):
        (runtime / name).symlink_to(ENGINE / name, target_is_directory=(ENGINE / name).is_dir())
    completed = subprocess.run(['npm', 'run', 'bundle:bridges'], cwd=runtime, capture_output=True, text=True, timeout=120)
    assert completed.returncode == 0, completed.stderr
    assert (runtime / 'dist/edit-docx.mjs').is_file()
    monkeypatch.setenv('AGENT_REPORTING_DOC_ENGINE_DIR', str(runtime))
    return runtime


def operation(target, text='Updated note'):
    return {'kind': 'editCommentText', **{key: target[key] for key in (
        'sourceId', 'targetId', 'expectedCommentsSha256', 'expectedObjectSha256',
    )}, 'text': text}


@pytest.fixture
def bundled_engine(tmp_path, monkeypatch):
    return isolated_bundled_engine(tmp_path, monkeypatch)


def test_python_thin_bridge_edits_only_comments_part_and_rejects_bad_batches(tmp_path, bundled_engine):
    content = source()
    original = content
    model = docx_native.inspect_docx(content)
    assert model['comments']['commentReadOnlyReason'] is None
    target = model['comments']['commentTargets'][0]
    edit = operation(target)

    result = docx_native.patch_docx(content, [edit])
    with ZipFile(BytesIO(content)) as before, ZipFile(BytesIO(result)) as after:
        assert after.testzip() is None
        assert before.namelist() == after.namelist()
        changed = [name for name in before.namelist() if before.read(name) != after.read(name)]
        assert changed == ['word/comments.xml']
        for name in after.namelist():
            if name.endswith(('.xml', '.rels')):
                etree.fromstring(after.read(name))
        saved = etree.fromstring(after.read('word/comments.xml'))
        assert ''.join(saved.xpath('.//w:t/text()', namespaces=NS)) == 'Updated note'

    with pytest.raises(ValueError, match='docx_engine_failed'):
        docx_native.patch_docx(content, [edit, {**edit, 'expectedObjectSha256': '0' * 64}])
    with pytest.raises(ValueError, match='docx_engine_failed'):
        docx_native.patch_docx(content, [edit, {'kind': 'replaceParagraph', 'blockId': 'foreign'}])
    with pytest.raises(ValueError, match='docx_engine_failed'):
        docx_native.patch_docx(content, [{**edit, 'sourceId': 'forged'}])
    assert content == original


def test_python_bridge_keeps_cli_source_overwrite_guard(tmp_path, bundled_engine):
    content = source()
    source_path = tmp_path / 'source.docx'
    source_path.write_bytes(content)
    model = docx_native.inspect_docx(content)
    payload = {
        'kind': 'patch', 'input': str(source_path), 'output': str(source_path),
        'operations': [operation(model['comments']['commentTargets'][0])],
    }
    request = tmp_path / 'overwrite.json'
    request.write_text(json.dumps(payload), encoding='utf-8')
    result = run_bridge('doc', 'edit-docx', request)
    assert result.returncode != 0
    assert 'docx_output_overwrites_source' in result.stderr
    assert source_path.read_bytes() == content


@pytest.fixture
def anyio_backend():
    return 'asyncio'


@pytest.mark.anyio
async def test_comment_publication_preserves_download_on_validation_failure(tmp_path, bundled_engine):
    from smart_reporting.report_editor.native import bind_native_workspace
    from smart_reporting.reporting.delivery.artifacts_v1 import ArtifactFile
    from smart_reporting.reporting.tests.test_native_publication_nonblocking import create_publication

    service, parent, downloads = await create_publication(tmp_path / 'publication')
    content = source()
    key = bind_native_workspace(service.workspace, parent.scope)
    comment_path = 'native/comment-source.docx'
    await service.workspace.awrite_bytes(key, comment_path, content)
    parent = parent.model_copy(update={'source_file': ArtifactFile(
        path=comment_path, size=len(content),
        sha256=hashlib.sha256(content).hexdigest(), mediaType=parent.source_file.media_type,
    )})
    target = docx_native.inspect_docx(content)['comments']['commentTargets'][0]
    operations = [operation(target, '已核实的中文批注')]
    service.validator = AsyncMock(side_effect=RuntimeError('comment layout validation unavailable'))
    result = await service.save_revision(
        parent, operations=operations, request_id='comment-save',
        expected_sha256=parent.source_file.sha256,
    )
    assert result['revisionRegistered'] is True
    assert result['validation']['ok'] is False
    assert 'native_validation_failed' in {issue['code'] for issue in result['validation']['issues']}
    artifact = result['artifacts']['word']
    _, chunks = await downloads.stream(artifact['downloadUrl'].split('/')[-2], artifact='word')
    saved = b''.join([chunk async for chunk in chunks])
    assert hashlib.sha256(saved).hexdigest() == artifact['sha256']
    with ZipFile(BytesIO(content)) as before, ZipFile(BytesIO(saved)) as after:
        assert after.testzip() is None
        assert before.namelist() == after.namelist()
        assert [name for name in before.namelist() if before.read(name) != after.read(name)] == ['word/comments.xml']
        assert ''.join(etree.fromstring(after.read('word/comments.xml')).xpath('.//w:t/text()', namespaces=NS)) == '已核实的中文批注'
    assert (await service.workspace.afile_bytes(key, parent.source_file.path))[0] == content
    retry = await service.save_revision(
        parent, operations=operations, request_id='comment-save',
        expected_sha256=parent.source_file.sha256,
    )
    assert retry['revision'] == result['revision']
    assert service.repository.completions == 1

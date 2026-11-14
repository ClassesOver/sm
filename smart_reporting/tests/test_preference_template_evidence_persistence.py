"""模板正式填充、双授权、SQL留存及消费前身份变化；不生成模板V。"""

import base64
import json
from copy import deepcopy
from hashlib import sha256
from io import BytesIO
from pathlib import Path

import pytest
from docx import Document
from pypdf import PdfReader, PdfWriter
from sqlalchemy import select

from smart_reporting.management.configuration_store import configuration_hash
from smart_reporting.management.models import ManagementError
from smart_reporting.management.repository import preference_verification_results
from smart_reporting.preferences.models import FormatPreferences
from smart_reporting.reporting.delivery.office_engine import run_office_engine
from smart_reporting.reporting.delivery.publishing import (
    ReportArtifactPersistenceService,
    SqlAlchemyReportArtifactRepository,
    report_artifact_chunks_v1,
    report_artifact_files_v1,
)
from smart_reporting.tests.test_management_persistence import auth_context as auth_context
from smart_reporting.tests.test_preference_template_preflight import identity, template_bytes
from smart_reporting.tests.test_preference_verification_handoff import ROOT, begin
from smart_reporting.tests.test_preference_verification_handoff import case as case

pytestmark = [pytest.mark.anyio, pytest.mark.integration]


@pytest.fixture
def anyio_backend():
    return 'asyncio'


async def test_template_actual_word_pdf_retained_in_sql_and_template_drift_rejects_reuse_without_losing_artifacts(case, monkeypatch):
    from smart_reporting.management import preference_report_preflight

    service, client, _, headers, _, admin, editor, repository, grants, _, _ = case
    context = await service.bound.editor.context_for_session(await grants.lookup_session(editor))
    workspace = service.bound.editor.workspace_registry.get(context.scope['threadId'])
    assert workspace is not None
    root = workspace.root
    markdown = (root / context.markdown_path).read_bytes()
    markdown_identity = identity(context.markdown_path, markdown)
    raw = template_bytes()
    template = identity('frozen-template.docx', raw)
    (root / template['path']).write_bytes(raw)
    template_input = {**template, 'filename': '来源模板.docx'}
    # 真实生成只写临时验收/留存目录；同工作区已有的历史输出不能被同名产物覆盖。
    old_word = Document()
    old_word.add_paragraph('历史文字报告保持')
    old_word.save(root / 'report.docx')
    old_pdf = PdfWriter()
    old_pdf.add_blank_page(width=595, height=842)
    old_pdf.add_metadata({'/Title': '历史PDF报告保持'})
    with (root / 'report.pdf').open('wb') as stream:
        old_pdf.write(stream)
    originals = {path: (root / path).read_bytes() for path in (
        context.markdown_path, 'chart.png', template['path'], 'report.docx', 'report.pdf')}
    state = service.bound.editor.state_repository.state
    state.payload['requestMaterials'] = {'fileInputs': [], 'templateInput': template_input}
    state.payload.setdefault('artifacts', []).extend(identity(path, originals[path])
        for path in ('report.docx', 'report.pdf'))
    draft = (await service.preferences.detail(admin))['draft']
    document = deepcopy(draft['document'])
    document['word']['common'].update(signer='模板文字署名', dateFormat='iso')
    document['pdf']['common'].update(signer='模板版式署名', dateFormat='slash')
    document['word']['signature']['description'] = 'Word独立说明\nWord第二行说明'
    document['pdf']['signature']['description'] = 'PDF独立说明'
    document = FormatPreferences.model_validate(document).model_dump(mode='json', by_alias=True)
    await service.preferences.save_draft(admin, document, draft['version'])
    draft = (await service.preferences.detail(admin))['draft']
    # case仅复用真实授权/路由；撤销其旧生成替身，调度、正式模板填充、reader和留存均用生产实现。
    monkeypatch.setattr(preference_report_preflight, 'run_office_engine', run_office_engine)
    async with repository.engine.begin() as connection:
        await connection.run_sync(lambda sync: report_artifact_files_v1.metadata.create_all(sync,
            tables=[report_artifact_files_v1, report_artifact_chunks_v1]))
    artifacts = SqlAlchemyReportArtifactRepository(repository.engine)
    service.bound.editor.artifact_persistence = ReportArtifactPersistenceService(artifacts, service.bound.editor.workspace)
    active = list(case)
    active[2] = {'expectedVersion': draft['version'], 'expectedHash': draft['contentHash']}
    token = await begin(active)
    response = await client.post(ROOT + '/run', json={**active[2], 'handoffToken': token}, headers=headers)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload['bindingValid'] is True and payload['canApply'] is False
    receipt = payload['verificationReceipt']
    async with repository.engine.connect() as connection:
        row = (await connection.execute(select(preference_verification_results).where(
            preference_verification_results.c.id == receipt['id']))).mappings().one()
    stored = row['document']
    assert receipt['contentHash'] == row['content_hash'] == configuration_hash(stored)
    assert stored['retained']['issues'] == []
    binding = stored['binding']
    assert binding['valid'] is binding['artifactAccessAuthorized'] is True
    assert binding['templateSource'] == {'identity': {**template_input, 'mediaType': None},
        'templateFormat': 'docx', 'sourceContent': markdown_identity}
    assert template in binding['identities'] and markdown_identity in binding['identities']
    snapshot_keys = ('reportId', 'workflowRunId', 'revision', 'contextSha256', 'workspaceFingerprint',
        'identities', 'nativeSources', 'availabilityIssues', 'templateSource')
    assert configuration_hash({key: binding[key] for key in snapshot_keys}) == binding['bindingHash'] == payload['bindingHash']
    assert not any(item.get('format') in {'word', 'pdf'}
        or item.get('requirementId') == 'template-binding-and-precedence' for item in stored['evidence'])
    output = Path('output/system-config-preferences/template-preflight-continuation/sql-evidence')
    output.mkdir(parents=True, exist_ok=True)
    (output / 'source-template.docx').write_bytes(raw)
    native, readbacks = {}, []
    independent = SqlAlchemyReportArtifactRepository(repository.engine)
    for format in ('word', 'pdf'):
        entry = payload['formats'][format]
        assert entry['availability'] == 'available' and entry['artifact'] is not None
        assert entry['pdf'] is not None and entry['previewPageCount'] > 0
        assert all('evidenceKind' not in check for check in entry['readback']['checks'])
        provenance = entry['provenance']
        assert provenance['layoutSource'] == 'uploaded_template'
        assert provenance['contentSource'] == 'frozen_report_markdown'
        assert provenance['signatureSource'] == 'current_draft'
        assert provenance['template'] == {key: template_input[key] for key in ('filename', 'size', 'sha256')}
        assert provenance['sourceContent'] == {key: markdown_identity[key] for key in ('size', 'sha256')}
        assert provenance['generatedDate'] == '2026-11-13'
        for role in ('artifact', 'pdf'):
            inline = entry[role]
            reference = stored['retained']['formats'][format][role]
            metadata = await independent.get(reference['artifactKey'])
            content = b''.join([chunk async for chunk in independent.stream(reference['artifactKey'])])
            assert content == base64.b64decode(inline['base64'], validate=True)
            assert len(content) == inline['size'] == reference['size'] == metadata.size
            assert sha256(content).hexdigest() == inline['sha256'] == reference['sha256'] == metadata.sha256
            assert stored['result']['formats'][format][role] == {key: inline[key]
                for key in ('filename', 'mediaType', 'size', 'sha256')}
            suffix = 'docx' if format == 'word' and role == 'artifact' else 'pdf'
            filename = format + '-' + role + '.' + suffix
            (output / filename).write_bytes(content)
            readbacks.append({'format': format, 'role': role, 'file': filename,
                'size': len(content), 'sha256': metadata.sha256, 'artifactKey': reference['artifactKey']})
            if role == 'artifact':
                native[format] = content
            else:
                assert len(PdfReader(BytesIO(content)).pages) > 0
    word = Document(BytesIO(native['word']))
    slots = word._element.body.xpath('.//w:sdt[w:sdtPr/w:tag[@w:val="report_signature"]]/w:sdtContent')
    assert len(slots) == 1
    assert [''.join(paragraph.xpath('.//w:t/text()')) for paragraph in slots[0]] == [
        '模板文字署名', '2026-11-13', 'Word独立说明', 'Word第二行说明']
    assert word.styles['Normal'].font.size.pt == 17
    assert word.paragraphs[0].text == '保留业务引用：既有作者；2000-01-01'
    assert word.paragraphs[-1].text == '末尾非声明业务说明保持'
    assert payload['formats']['word']['templateReadback']['signature']['status'] == 'passed'
    assert payload['formats']['word']['templateReadback']['outsideDeclaredTargets']['status'] == 'passed'
    pdf = PdfReader(BytesIO(native['pdf']))
    visible = ''.join(''.join((page.extract_text() or '').split()) for page in pdf.pages)
    assert '模板版式署名' in visible and 'PDF独立说明' in visible and '2026/11/13' in visible
    assert '模板文字署名' not in visible
    assert '冻结业务原值1234.56。' in visible
    prepared = await service.evidence.prepare(admin, expected_version=draft['version'],
        expected_hash=draft['contentHash'], evidence_ids=[receipt['id']])
    assert prepared['status'] == stored['assessment']['status'] == 'incomplete'
    assert prepared['canApply'] is stored['assessment']['canApply'] is False
    assert prepared['missingRequirements'] and any(gap['requirementId'] == 'template-binding-and-precedence'
        for gap in prepared['missingRequirements'])
    assert prepared['evidenceReferences'] == [{'id': receipt['id'], 'contentHash': receipt['contentHash']}]
    assert all((root / path).read_bytes() == original for path, original in originals.items())
    try:
        (root / template['path']).write_bytes(raw + b'\nchanged-after-issuance')
        with pytest.raises(ManagementError) as rejected:
            await service.evidence.prepare(admin, expected_version=draft['version'],
                expected_hash=draft['contentHash'], evidence_ids=[receipt['id']])
        assert rejected.value.status == 409 and rejected.value.code == 'management_preference_materials_changed'
        for item in readbacks:
            content = b''.join([chunk async for chunk in independent.stream(item['artifactKey'])])
            assert len(content) == item['size'] and sha256(content).hexdigest() == item['sha256']
        assert all(base64.b64decode(payload['formats'][format]['artifact']['base64'], validate=True) == native[format]
            for format in ('word', 'pdf'))
    finally:
        (root / template['path']).write_bytes(raw)
    assert all((root / path).read_bytes() == original for path, original in originals.items())
    async with repository.engine.connect() as connection:
        assert await connection.scalar(select(preference_verification_results.c.content_hash).where(
            preference_verification_results.c.id == receipt['id'])) == receipt['contentHash']
    (output / 'readback.json').write_text(json.dumps({'scope': 'fixture_workflow_real_auth_template_render_sql_not_full_V',
        'bindingHash': binding['bindingHash'], 'templateSource': binding['templateSource'],
        'draft': stored['draft'], 'formats': {format: {key: payload['formats'][format][key]
            for key in ('provenance', 'readback', 'templateReadback', 'issues')} for format in ('word', 'pdf')},
        'artifacts': [{key: value for key, value in item.items() if key != 'artifactKey'} for item in readbacks],
        'originalsUnchanged': True, 'templateDriftRejected': {'status': 409, 'code': rejected.value.code},
        'retainedAfterDrift': True, 'assessment': {'status': prepared['status'], 'canApply': prepared['canApply'],
            'gapCount': len(prepared['missingRequirements'])}}, ensure_ascii=False, indent=2))

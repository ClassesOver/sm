"""六角色真实生成、独立回读与SQL留证；原生证据不表示完整批准。"""

import base64
import json
from copy import deepcopy
from hashlib import sha256
from pathlib import Path

import pytest
from sqlalchemy import select

from smart_reporting.management.configuration_store import configuration_hash
from smart_reporting.management.format_preferences import FormatPreferenceService
from smart_reporting.management.preference_verification import PreferenceVerificationHandoffService
from smart_reporting.management.repository import preference_verification_results
from smart_reporting.preferences.models import FormatPreferences
from smart_reporting.report_editor.repository import SqlAlchemyReportEditorRepository
from smart_reporting.report_editor.service import ReportEditorGrantService
from smart_reporting.reporting.delivery.pptx_tables import project_fact_slide_tables
from smart_reporting.reporting.delivery.publishing import (
    ReportArtifactPersistenceService,
    SqlAlchemyReportArtifactRepository,
    report_artifact_chunks_v1,
    report_artifact_files_v1,
)
from smart_reporting.reporting.tests.test_trace_table_builder import _bundle
from smart_reporting.reporting.workflow.checkpoint import FileIdentity
from smart_reporting.tests.test_management_persistence import OLD_PASSWORD
from smart_reporting.tests.test_management_persistence import auth_context as auth_context
from smart_reporting.tests.test_preference_pptx_indent_capabilities import INDENTS
from smart_reporting.tests.test_preference_report_preflight import native_case

pytestmark = [pytest.mark.anyio, pytest.mark.integration]


@pytest.fixture
def anyio_backend():
    return 'asyncio'


async def test_six_indents_survive_actual_handoff_sql_retention_and_reopen_without_full_approval(auth_context, tmp_path, monkeypatch):
    from smart_reporting.management import preference_preflight, preference_report_preflight

    auth, repository, _ = auth_context
    await auth.bootstrap(OLD_PASSWORD)
    admin = (await auth.login('admin', OLD_PASSWORD, '127.0.0.1')).raw_token
    bound, _, states, context, root, spec, _, _ = await native_case(tmp_path, 'pptx')
    raw = _bundle().model_dump_json(by_alias=True).encode()
    source = FileIdentity(path='indent-table-facts.json', size=len(raw), sha256=sha256(raw).hexdigest())
    (root / source.path).write_bytes(raw)
    spec['slides'] = [{**spec['slides'][0], 'tables': project_fact_slide_tables('analysis_001', source, raw)}]

    def saved(path, value):
        content = json.dumps(value, ensure_ascii=False).encode()
        (root / path).write_bytes(content)
        return {'path': path, 'size': len(content), 'sha256': sha256(content).hexdigest()}

    job = deepcopy(context.job)
    pointer = job['pptxNativeInput']
    pointer['spec'] = saved('native-spec.json', spec)
    pointer['receipt'] = saved('report.pptx.receipt.json', {'schemaVersion': 'pptx-native-receipt/1',
        'binding': pointer['binding'], 'artifact': pointer['artifact'], 'spec': pointer['spec']})
    context = context.model_copy(update={'job': job})
    states.state.payload['reportEditorContexts']['1'] = context.model_dump(mode='json', by_alias=True)
    states.state.payload['workflowCheckpoint'] = {'deterministicFactFiles': {'analysis_001': source.model_dump()}}
    states.state.payload['artifacts'] = [pointer['artifact'], pointer['spec'], pointer['receipt'], source.model_dump()]
    preferences = FormatPreferenceService(auth, FormatPreferences(common={'signer': '缩进留证编制'}))
    editor_repository = SqlAlchemyReportEditorRepository(repository.engine)
    await editor_repository.create_schema()
    grants = ReportEditorGrantService(editor_repository, secret='indent-fields-fixture-' * 3)
    grant, _ = await grants.issue(context)
    session, _ = await grants.exchange(grant)
    bound.preferences, bound.grants = preferences, grants
    async with repository.engine.begin() as connection:
        await connection.run_sync(lambda sync: report_artifact_files_v1.metadata.create_all(sync,
            tables=[report_artifact_files_v1, report_artifact_chunks_v1]))
    artifacts = SqlAlchemyReportArtifactRepository(repository.engine)
    bound.editor.artifact_persistence = ReportArtifactPersistenceService(artifacts, bound.editor.workspace)
    service = PreferenceVerificationHandoffService(preferences=preferences, bound=bound)

    async def native_only(function, *args, **kwargs):
        return function(*args, **kwargs)

    def no_pdf_preview(*args, **kwargs):
        raise RuntimeError('SQL专项只证明原生属性，PDF视觉另有实际样本')

    monkeypatch.setattr(preference_preflight, 'libreoffice_to_pdf', no_pdf_preview)
    monkeypatch.setattr(preference_report_preflight, 'run_office_engine', native_only)
    draft = (await preferences.detail(admin))['draft']
    document = deepcopy(draft['document'])
    for index, local in enumerate(INDENTS, 1):
        target = document['pptx']
        *parts, key = local.split('.')
        for part in parts:
            target = target[part]
        target[key] = index * 3
    await preferences.save_draft(admin, document, draft['version'])
    draft = (await preferences.detail(admin))['draft']
    token = (await service.create(admin, expected_version=draft['version'], expected_hash=draft['contentHash']))['handoffToken']
    await service.confirm(token, session, report_id=context.report_id, revision=context.revision)
    payload = await service.run(admin, token, expected_version=draft['version'], expected_hash=draft['contentHash'])
    receipt = payload['verificationReceipt']
    async with repository.engine.connect() as connection:
        row = (await connection.execute(select(preference_verification_results).where(
            preference_verification_results.c.id == receipt['id']))).mappings().one()
    document = row['document']
    assert row['content_hash'] == receipt['contentHash'] == configuration_hash(document)
    assert document['binding']['valid'] is document['binding']['artifactAccessAuthorized'] is True
    assert document['retained']['issues'] == []
    rows = [item for item in document['evidence'] if item.get('readerGroup') == 'pptx_native_indent_fields_v1']
    assert {item['path'] for item in rows} == {'pptx.' + local for local in INDENTS}, document['result']['formats']['pptx']['readback']
    assert len(rows) == 6 and all(item['status'] == 'passed' and item['dimension'] == 'native' for item in rows)
    reference = document['retained']['formats']['pptx']['artifact']
    independent = SqlAlchemyReportArtifactRepository(repository.engine)
    metadata = await independent.get(reference['artifactKey'])
    content = b''.join([chunk async for chunk in independent.stream(reference['artifactKey'])])
    assert content == base64.b64decode(payload['formats']['pptx']['artifact']['base64'], validate=True)
    assert metadata.size == len(content) == reference['size']
    assert metadata.sha256 == sha256(content).hexdigest() == reference['sha256']
    assert all(item['artifact'] == {'sizeBytes': len(content), 'sha256': metadata.sha256} for item in rows)
    prepared = await service.evidence.prepare(admin, expected_version=draft['version'],
        expected_hash=draft['contentHash'], evidence_ids=[receipt['id']])
    assert prepared['canApply'] is False and prepared['missingRequirements']
    assert not any(gap.get('path') in {'pptx.' + local for local in INDENTS}
        and gap.get('scenario') == 'configured_field' for gap in prepared['missingRequirements'])
    reopened = await service.evidence.read(admin, receipt['id'])
    assert reopened['contentHash'] == receipt['contentHash']
    output = Path('output/system-config-preferences/pptx-indent/sql')
    output.mkdir(parents=True, exist_ok=True)
    assert not (output / 'actual.pptx').exists(), '证据原件禁止覆盖'
    (output / 'actual.pptx').write_bytes(content)
    (output / 'receipt.json').write_text(json.dumps({'verification': receipt, 'evidence': rows,
        'size': len(content), 'sha256': metadata.sha256, 'canApply': False,
        'scope': 'real_bound_native_generation_reader_sql_retention_not_visual_or_lifecycle_acceptance'},
        ensure_ascii=False, indent=2) + '\n')

"""真实管理授权、富正文生成与独立SQL留存回读；不构成应用批准。"""

import base64
import hashlib
import json
from pathlib import Path

import pytest
from sqlalchemy import select

from smart_reporting.management.repository import preference_verification_results
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


async def test_rich_template_body_is_independently_read_and_retained_in_sql(case, monkeypatch):
    from smart_reporting.management import preference_report_preflight

    service, client, _, headers, _, _, editor, repository, grants, _, _ = case
    context = await service.bound.editor.context_for_session(await grants.lookup_session(editor))
    workspace = service.bound.editor.workspace_registry.get(context.scope['threadId'])
    raw = template_bytes()
    path = 'rich-body-template.docx'
    (workspace.root / path).write_bytes(raw)
    service.bound.editor.state_repository.state.payload['requestMaterials'] = {
        'fileInputs': [], 'templateInput': {**identity(path, raw), 'filename': '原生正文模板.docx'}}
    monkeypatch.setattr(preference_report_preflight, 'run_office_engine', run_office_engine)
    async with repository.engine.begin() as connection:
        await connection.run_sync(lambda sync: report_artifact_files_v1.metadata.create_all(sync,
            tables=[report_artifact_files_v1, report_artifact_chunks_v1]))
    artifacts = SqlAlchemyReportArtifactRepository(repository.engine)
    service.bound.editor.artifact_persistence = ReportArtifactPersistenceService(artifacts, service.bound.editor.workspace)
    token = await begin(case)
    response = await client.post(ROOT + '/run', json={**case[2], 'handoffToken': token}, headers=headers)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload['bindingValid'] is True and payload['canApply'] is False
    async with repository.engine.connect() as connection:
        stored = (await connection.execute(select(preference_verification_results.c.document).where(
            preference_verification_results.c.id == payload['verificationReceipt']['id']))).scalar_one()
    assert stored['retained']['issues'] == []
    output = Path('output/system-config-preferences/template-rich-body/sql')
    output.mkdir(parents=True, exist_ok=True)
    evidence = {}
    independent = SqlAlchemyReportArtifactRepository(repository.engine)
    for format in ('word', 'pdf'):
        entry = payload['formats'][format]
        body = entry['templateReadback']['body']
        assert body['status'] == ('passed' if format == 'word' else 'sampled')
        assert body['coverage'] == ('complete' if format == 'word' else 'sample')
        assert entry['provenance']['richDocumentProjection'] == ('structure_verified' if format == 'word' else 'sample_only')
        assert not any(check.get('evidenceKind') for check in entry['readback']['checks'])
        reference = stored['retained']['formats'][format]['artifact']
        content = b''.join([chunk async for chunk in independent.stream(reference['artifactKey'])])
        assert content == base64.b64decode(entry['artifact']['base64'], validate=True)
        assert len(content) == reference['size']
        assert hashlib.sha256(content).hexdigest() == reference['sha256']
        (output / ('actual.' + ('docx' if format == 'word' else 'pdf'))).write_bytes(content)
        evidence[format] = {'body': body, 'provenance': entry['provenance'], 'artifact': reference}
    assert stored['assessment']['canApply'] is False
    (output / 'readback.json').write_text(json.dumps(evidence, ensure_ascii=False, indent=2))

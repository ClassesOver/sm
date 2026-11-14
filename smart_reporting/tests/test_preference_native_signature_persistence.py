"""真实MD生成/回读与SQL留存的窄字段证据；完整生产要求仍不满足。"""

import base64
from hashlib import sha256

import pytest
from sqlalchemy import select

from smart_reporting.management.configuration_store import configuration_hash
from smart_reporting.management.repository import preference_verification_results
from smart_reporting.preferences.markdown_adapter import START
from smart_reporting.reporting.delivery.publishing import (
    ReportArtifactPersistenceService,
    SqlAlchemyReportArtifactRepository,
    report_artifact_chunks_v1,
    report_artifact_files_v1,
)
from smart_reporting.tests.test_management_persistence import auth_context as auth_context
from smart_reporting.tests.test_preference_evidence_persistence import run
from smart_reporting.tests.test_preference_verification_handoff import case as case

pytestmark = [pytest.mark.anyio, pytest.mark.integration]


@pytest.fixture
def anyio_backend():
    return 'asyncio'


@pytest.mark.parametrize('fault', ['valid', 'missing_tail', 'runtime_identity'])
async def test_real_md_field_evidence_survives_sql_readback_without_global_approval(case, monkeypatch, fault):
    from smart_reporting.management import (
        preference_evidence,
        preference_preflight,
        preference_report_preflight,
        preference_verification,
    )

    async with case[7].engine.begin() as connection:
        await connection.run_sync(lambda sync: report_artifact_files_v1.metadata.create_all(sync,
            tables=[report_artifact_files_v1, report_artifact_chunks_v1]))
    repository = SqlAlchemyReportArtifactRepository(case[7].engine)
    case[0].bound.editor.artifact_persistence = ReportArtifactPersistenceService(repository, case[0].bound.editor.workspace)

    async def actual_md(function, *args, **kwargs):
        return function(*args, **{**kwargs, 'formats': ('md',)})

    # 只移除测试生成的尾块；reader、材料绑定、mapper及数据库留存均使用生产实现。
    original_generate = preference_preflight._generate
    if fault == 'missing_tail':
        def missing_tail(root, preferences, frozen):
            issues = original_generate(root, preferences, frozen)
            path = root / 'report.md'
            path.write_text(path.read_text().split(START)[0])
            return issues

        monkeypatch.setattr(preference_preflight, '_generate', missing_tail)
    if fault == 'runtime_identity':
        original_manifest = preference_verification.executor_manifest

        def unavailable_runtime():
            manifest = original_manifest()
            manifest['runtimeIdentityComplete'] = False
            manifest['runtimeIdentityIssues'].append({'code': 'test_runtime_identity_missing', 'resource': 'test-only-resource'})
            return manifest

        monkeypatch.setattr(preference_verification, 'executor_manifest', unavailable_runtime)
        monkeypatch.setattr(preference_evidence, 'executor_manifest', unavailable_runtime)
    else:
        assert preference_verification.executor_manifest()['runtimeIdentityComplete'] is True
    monkeypatch.setattr(preference_report_preflight, 'run_office_engine', actual_md)
    payload = await run(case)
    receipt = payload['verificationReceipt']
    async with case[7].engine.connect() as connection:
        row = (await connection.execute(select(preference_verification_results).where(
            preference_verification_results.c.id == receipt['id']))).mappings().one()
    document = row['document']
    assert row['content_hash'] == receipt['contentHash'] == configuration_hash(document)
    assert document['retained']['issues'] == []
    rows = document['evidence']
    assert len(rows) == (0 if fault == 'runtime_identity' else 3)
    assert all(item['status'] == ('failed' if fault == 'missing_tail' else 'passed') for item in rows)
    assert all(item['format'] == 'md' and item['dimension'] == 'native'
        and item['scenario'] == 'configured_field' for item in rows)
    if rows:
        assert {item['path'] for item in rows} == {'md.common.signer', 'md.common.dateFormat', 'md.signature.description'}
    reference = document['retained']['formats']['md']['artifact']
    independent = SqlAlchemyReportArtifactRepository(case[7].engine)
    stored = await independent.get(reference['artifactKey'])
    content = b''.join([chunk async for chunk in independent.stream(reference['artifactKey'])])
    assert content == base64.b64decode(payload['formats']['md']['artifact']['base64'], validate=True)
    assert stored.size == len(content) == reference['size']
    assert stored.sha256 == sha256(content).hexdigest() == reference['sha256']
    assert all(item['artifact'] == {'sizeBytes': len(content), 'sha256': stored.sha256} for item in rows)
    prepared = await case[0].evidence.prepare(case[5], expected_version=case[2]['expectedVersion'],
        expected_hash=case[2]['expectedHash'], evidence_ids=[receipt['id']])
    assert prepared['status'] == document['assessment']['status'] == 'incomplete'
    assert prepared['canApply'] is document['assessment']['canApply'] is False
    gaps = prepared['missingRequirements']
    assert gaps and any('visual' in gap['missingDimensions'] for gap in gaps)
    if fault == 'valid':
        assert not any(gap.get('path') in {item['path'] for item in rows}
            and gap.get('scenario') == 'configured_field' for gap in gaps)
    elif fault == 'missing_tail':
        assert {gap['path'] for gap in gaps if gap['reason'] == 'check_failed'} == {item['path'] for item in rows}
    else:
        assert any(gap['reason'] == 'executor_identity_unavailable' for gap in gaps)

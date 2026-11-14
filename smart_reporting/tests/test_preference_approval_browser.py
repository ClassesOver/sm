"""实际HTTP/renderer/SQL分块留存的批准汇总；仅fixture工作流，不接业务数据库。"""
import hashlib
import json
import socket
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi import FastAPI
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError

from smart_reporting.management.api import SESSION_COOKIE, create_management_router
from smart_reporting.management.configuration_store import configuration_hash
from smart_reporting.management.format_preferences import FormatPreferenceService
from smart_reporting.management.preference_approval import PreferenceApprovalService
from smart_reporting.management.preference_verification import PreferenceVerificationHandoffService
from smart_reporting.management.preference_verification_api import (
    create_preference_verification_router,
)
from smart_reporting.management.repository import (
    preference_approval_receipts,
    preference_verification_results,
)
from smart_reporting.management.settings import ManagementSettings
from smart_reporting.preferences.models import FormatPreferences
from smart_reporting.report_editor.api import EDITOR_SESSION_COOKIE, create_report_editor_router
from smart_reporting.report_editor.repository import SqlAlchemyReportEditorRepository
from smart_reporting.report_editor.service import ReportEditorGrantService
from smart_reporting.reporting.delivery.publishing import (
    ReportArtifactPersistenceService,
    SqlAlchemyReportArtifactRepository,
    report_artifact_chunks_v1,
    report_artifact_files_v1,
)
from smart_reporting.runtime.settings import AgentSettings
from smart_reporting.runtime.system_configuration import SystemConfigurationState
from smart_reporting.tests.report_issue_browser_flow import run_management_browser
from smart_reporting.tests.test_management_persistence import OLD_PASSWORD
from smart_reporting.tests.test_management_persistence import auth_context as auth_context
from smart_reporting.tests.test_preference_report_preflight import bound_case

pytestmark = [pytest.mark.anyio, pytest.mark.integration]


@pytest.fixture
def anyio_backend():
    return 'asyncio'


async def test_actual_report_approval_browser_retains_sql_artifacts_and_lists_real_gaps(auth_context, tmp_path):
    auth, repository, _ = auth_context
    auth.clock = lambda: datetime.now(UTC)
    await auth.bootstrap(OLD_PASSWORD)
    bound, _, _, _, context, workspace, _ = await bound_case(tmp_path)
    source_identities = {name: hashlib.sha256((workspace / name).read_bytes()).hexdigest()
        for name in ('report.md', 'chart.png')}
    editor_repository = SqlAlchemyReportEditorRepository(repository.engine)
    await editor_repository.create_schema()
    # 只在显式隔离验收DB中建现有两张产物表，不创建下载授权或替代工作区。
    async with repository.engine.begin() as connection:
        await connection.run_sync(lambda sync: report_artifact_files_v1.metadata.create_all(sync,
            tables=[report_artifact_files_v1, report_artifact_chunks_v1]))
    artifacts = SqlAlchemyReportArtifactRepository(repository.engine)
    bound.editor.artifact_persistence = ReportArtifactPersistenceService(artifacts, bound.editor.workspace)
    grants = ReportEditorGrantService(editor_repository, secret='approval-browser-fixture-' * 3)
    grant, _ = await grants.issue(context)
    startup = AgentSettings.from_environment({}, load_env_file=False)
    preferences = FormatPreferenceService(auth, FormatPreferences.from_delivery(startup.report_delivery_settings))
    bound.preferences, bound.grants = preferences, grants
    verification = PreferenceVerificationHandoffService(preferences=preferences, bound=bound)
    approval = PreferenceApprovalService(evidence=verification.evidence)

    listener = socket.socket()
    listener.bind(('127.0.0.1', 0))
    listener.listen()
    origin = f'http://127.0.0.1:{listener.getsockname()[1]}'
    settings = ManagementSettings(public_origin=origin,
        static_dir=ManagementSettings.from_environment().static_dir, allow_local_http=True)
    app, requests = FastAPI(), []
    app.state.preference_approval = approval

    @app.middleware('http')
    async def observe_cookie_names(request, call_next):
        response = await call_next(request)
        path = request.url.path
        if path.startswith(('/management/api/', f'/reports/v1/editor/{context.report_id}/')):
            # 不记录Cookie值、grant、密码或请求体。
            requests.append({'path': path, 'method': request.method,
                'cookieNames': sorted(request.cookies), 'status': response.status_code})
        return response

    app.include_router(create_management_router(auth, settings, startup_settings=startup,
        system_configuration_state=SystemConfigurationState()))
    app.include_router(create_preference_verification_router(verification, settings))
    app.include_router(create_report_editor_router(grants, editor=bound.editor,
        cookie_secure=False, allowed_origin=origin))
    output = Path('output/system-config-preferences/approval-browser').resolve()
    result = await run_management_browser(app, {'password': OLD_PASSWORD,
        'reportPath': f'/reports/v1/editor/{context.report_id}/{context.revision}',
        'fullOpenPath': f'/reports/v1/editor/open/{grant}'}, output,
        script='smoke/management-preference-approval-smoke.mjs', listener=listener)
    assert result == {'errors': [], 'actualRuns': 1, 'receiptCount': 1, 'productionIncomplete': True,
        'applyUnavailable': True, 'cookiePathsVerified': True, 'workflowMaterials': 'fixture', 'renderer': 'real'}

    async with repository.engine.connect() as connection:
        run_row = (await connection.execute(select(preference_verification_results))).mappings().one()
        approval_row = (await connection.execute(select(preference_approval_receipts))).mappings().one()
    browser = json.loads((output / 'approval-evidence.json').read_text())
    assert browser['verificationReceipt']['id'] == run_row['id']
    assert browser['summary']['id'] == approval_row['id']
    for row in (run_row, approval_row):
        assert configuration_hash(row['document']) == row['content_hash']
    summary = approval_row['document']
    assert summary['status'] == 'incomplete' and summary['canApply'] is False
    assert summary['missingRequirements']
    assert summary['evidenceReferences'] == [{'id': run_row['id'], 'contentHash': run_row['content_hash']}]
    assert run_row['document']['retained']['issues'] == []
    # 重构仓库对象后只从实际SQL分块读取，不依赖内存仓库或先前下载缓存。
    independent = SqlAlchemyReportArtifactRepository(repository.engine)
    readbacks = []
    for format, entries in run_row['document']['retained']['formats'].items():
        for role, reference in entries.items():
            metadata = await independent.get(reference['artifactKey'])
            assert metadata is not None
            content = b''.join([chunk async for chunk in independent.stream(reference['artifactKey'])])
            assert len(content) == metadata.size == reference['size']
            assert hashlib.sha256(content).hexdigest() == metadata.sha256 == reference['sha256']
            inline = run_row['document']['result']['formats'][format][role]
            assert inline['size'] == len(content) and inline['sha256'] == metadata.sha256
            async with repository.engine.connect() as connection:
                count = await connection.scalar(select(func.count()).select_from(report_artifact_chunks_v1).where(
                    report_artifact_chunks_v1.c.artifact_key == reference['artifactKey']))
            assert count > 0
            readbacks.append({'format': format, 'role': role, 'size': len(content), 'sha256': metadata.sha256,
                'sqlChunks': count, 'independentRepository': True})
    assert {item['format'] for item in readbacks} == {'md', 'pdf', 'word'}
    # 两类不可变记录均由数据库拒绝覆盖，失败事务不影响原存证。
    for table, row in ((preference_verification_results, run_row), (preference_approval_receipts, approval_row)):
        with pytest.raises(IntegrityError):
            async with repository.engine.begin() as connection:
                await connection.execute(update(table).where(table.c.id == row['id']).values(content_hash='f' * 64))
        async with repository.engine.connect() as connection:
            assert await connection.scalar(select(table.c.content_hash).where(table.c.id == row['id'])) == row['content_hash']
    assert source_identities == {name: hashlib.sha256((workspace / name).read_bytes()).hexdigest()
        for name in source_identities}
    management = [item for item in requests if item['path'].startswith('/management/api/')]
    editor = [item for item in requests if item['path'].endswith('/api/preference-verification')]
    assert management and editor
    assert all(EDITOR_SESSION_COOKIE not in item['cookieNames'] for item in management)
    assert all(SESSION_COOKIE not in item['cookieNames'] for item in editor)
    assert all(EDITOR_SESSION_COOKIE in item['cookieNames'] for item in editor)
    assert sum(item['path'].endswith('/report-verification/run') for item in management) == 1
    assert sum(item['path'].endswith('/report-verification/prepare') for item in management) == 1
    (output / 'independent-sql-readback.json').write_text(json.dumps({'resultsImmutable': True,
        'approvalsImmutable': True, 'resultHash': run_row['content_hash'], 'approvalHash': approval_row['content_hash'],
        'originalSourcesUnchanged': True, 'artifacts': readbacks}, ensure_ascii=False, indent=2))
    (output / 'http-cookie-evidence.json').write_text(json.dumps(requests, ensure_ascii=False, indent=2))

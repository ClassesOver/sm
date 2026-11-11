"""公开首次创建使用生产验签及 Agno 原生路由，不预建报告或伪造可信身份。"""

import asyncio
import json
import os
from types import SimpleNamespace

import pytest
from agno.os import AgentOS
from agno.run import RunStatus
from agno.run.workflow import WorkflowRunOutput
from cryptography.fernet import Fernet
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from smart_reporting.management.business_documents import BusinessDocumentService
from smart_reporting.management.models import ManagementScope
from smart_reporting.management.scopes import ScopeService
from smart_reporting.reporting.business_knowledge.originals import BusinessOriginalStore
from smart_reporting.reporting.workflow.scope import REPORT_WORKFLOW_SCOPE_DEPENDENCY
from smart_reporting.tests.test_initial_workbook_delivery import exercise_initial_workbook_delivery
from smart_reporting.tests.test_management_persistence import OLD_PASSWORD
from smart_reporting.tests.test_report_basis_persistence import auth_context as auth_context
from smart_reporting.tests.test_report_basis_persistence import basis_context as basis_context
from smart_reporting.tests.test_report_basis_persistence import index_context as index_context
from smart_reporting.tests.test_report_basis_persistence import receipt_snapshot as receipt_snapshot
from smart_reporting.tests.test_reporting_request_identity import SECRET, _capability

pytestmark = [pytest.mark.anyio, pytest.mark.integration]


@pytest.fixture
def anyio_backend():
    return 'asyncio'


@pytest.fixture
async def document_context(auth_context, tmp_path):
    # 真实 capability 只接受正整数组织标识，不放宽协议来迁就旧测试夹具。
    auth, _, _ = auth_context
    await auth.bootstrap(OLD_PASSWORD)
    login = await auth.login('admin', OLD_PASSWORD, '127.0.0.1')
    scopes = ScopeService(auth)
    first_scope, second_scope = ManagementScope('warehouse', '101'), ManagementScope('warehouse', '102')
    first = await scopes.register(login.raw_token, first_scope, '隔离组织一')
    second = await scopes.register(login.raw_token, second_scope, '隔离组织二')
    documents = BusinessDocumentService(scopes, BusinessOriginalStore(tmp_path / 'originals'))
    return documents, login.raw_token, first_scope, second_scope, first['id'], second['id']


@pytest.mark.parametrize(
    ('delivery_format', 'fact_read_failure', 'knowledge_registration_failure', 'narrative_parsing_failure'),
    [('xlsx', False, False, False), ('xlsx', True, False, False),
        ('pptx', False, False, False), ('pptx', False, True, False), ('pptx', False, False, True)],
    ids=['xlsx-normal', 'xlsx-fact-read-fault', 'pptx-normal', 'pptx-knowledge-fault', 'pptx-narrative-fault'],
)
async def test_http_first_report_overrides_client_identity_and_delivers_revision_one(
    basis_context, document_context, receipt_snapshot, monkeypatch, tmp_path, fact_read_failure, delivery_format,
    knowledge_registration_failure, narrative_parsing_failure,
):
    monkeypatch.setenv('AGENT_DB_URL', os.environ['REPORTING_MANAGEMENT_TEST_DB_URL'])
    monkeypatch.setenv('AGENT_WORKSPACE_HMAC_SECRET', SECRET)
    monkeypatch.setenv('AGENT_MANAGEMENT_CREDENTIAL_KEYS', 'isolated:' + Fernet.generate_key().decode())
    monkeypatch.setenv('REPORTING_HOST_WORKSPACE_ROOT', str(tmp_path / 'bootstrap-workspaces'))
    from smart_reporting.app import require_workspace_capability

    async def http_entry(runtime, run_id, thread_id, scope, queries):
        workflow = runtime.workflow()
        base = FastAPI()
        base.middleware('http')(require_workspace_capability)
        app = AgentOS(workflows=[workflow], base_app=base, telemetry=False).get_app()
        app.state.agentos_context = SimpleNamespace(settings=SimpleNamespace(workspace_hmac_secret=SECRET))
        path = f'/workflows/{workflow.id}/runs'
        form = {'message': f'生成2026年11月预算执行{delivery_format}报告，核对执行率及当期背景',
            'stream': 'false', 'run_id': run_id, 'session_id': 'forged-thread', 'user_id': '999',
            'dependencies': json.dumps({REPORT_WORKFLOW_SCOPE_DEPENDENCY: {
                'database': 'foreign', 'companyId': '102', 'userId': '999', 'threadId': 'forged-thread'}})}
        headers = {'X-Workspace-Thread': thread_id,
            'X-Workspace-Capability': _capability(thread_id, database=scope.database, company=int(scope.company_id))}
        attempts = []
        async with AsyncClient(transport=ASGITransport(app), base_url='https://reports.test') as client:
            for invalid in (
                {'X-Workspace-Thread': thread_id},
                {**headers, 'X-Workspace-Capability': headers['X-Workspace-Capability'] + 'x'},
                {**headers, 'X-Workspace-Thread': 'foreign-thread'},
            ):
                response = await client.post(path, data=form, headers=invalid)
                assert response.status_code == 401, response.text
                assert queries == []
                assert await runtime.state_repository.get(run_id) is None
                attempts.append({'status': response.status_code, 'body': response.json(), 'queryCount': len(queries)})
            response = await asyncio.wait_for(client.post(path, data=form, headers=headers), timeout=90)
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload['status'] == RunStatus.completed.value
        assert payload['run_id'] == run_id
        assert payload['user_id'] == '7' and payload['session_id'] == thread_id
        registered = await runtime.state_repository.get_run(run_id)
        # 工作流传输类型和配置仓储的可信入口类型是两份不同契约。
        assert registered['entrypoint'] == 'agentos'
        assert registered['database'] == scope.database and registered['company_id'] == scope.company_id
        assert registered['owner_user_id'] == '7' and registered['thread_id'] == thread_id
        async with basis_context['repository'].transaction() as connection:
            tenant = await basis_context['scopes'].require_registered(connection, scope)
            trusted = await basis_context['provider']._run(connection, tenant['id'], run_id)
        assert trusted['entrypoint'] == 'http-capability'
        assert trusted['user_id'] == '7' and trusted['thread_id'] == thread_id
        output = WorkflowRunOutput.from_dict(payload)
        # Agno 的字典恢复保留 wire 字符串；在测试适配层明确恢复枚举。
        output.status = RunStatus(output.status)
        return output, {'entrypoint': 'public-http-native-agentos-workflow',
            'path': path, 'rejectedAttempts': attempts, 'responseStatus': response.status_code,
            'verifiedCompanyId': scope.company_id, 'clientIdentityOverridden': True,
            'registeredRun': {key: registered[key] for key in (
                'entrypoint', 'database', 'company_id', 'owner_user_id', 'thread_id')},
            'trustedConfigurationIdentity': {key: trusted[key] for key in (
                'scope_id', 'entrypoint', 'user_id', 'thread_id')}}

    await exercise_initial_workbook_delivery(basis_context, document_context, receipt_snapshot,
        monkeypatch, entry_runner=http_entry, fact_read_failure=fact_read_failure, delivery_format=delivery_format,
        knowledge_registration_failure=knowledge_registration_failure, narrative_parsing_failure=narrative_parsing_failure)

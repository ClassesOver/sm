from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from agno.run.base import RunStatus
from agno.workflow.types import StepOutput, StepRequirement
import pytest

from smart_reporting.office.report_resume import resume_office_report
from smart_reporting.office.repository import Identity, OfficeError
from smart_reporting.reporting.workflow.identity import require_verified_reporting_identity


@pytest.mark.asyncio
async def test_clarification_route_requires_office_csrf_and_uses_session_actor(monkeypatch):
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient
    from smart_reporting.office import report_resume
    from smart_reporting.office.api import COOKIE, create_office_router, csrf_token

    actor = Identity('tenant', 'company', 'writer')
    office = SimpleNamespace(authenticate=AsyncMock(return_value=actor))
    runtime, workflow = object(), object()
    resume = AsyncMock(return_value={'run_id': 'run-1'})
    monkeypatch.setattr(report_resume, 'resume_office_report', resume)
    app = FastAPI()
    app.include_router(create_office_router(office, public_origin='http://test',
                                         report_runtime=runtime, report_workflow=workflow))
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test', cookies={COOKIE: 'session'}) as client:
        path = '/office/api/workspaces/team/reports/run-1/clarification'
        payload = {'feedback': ' 2026 年 1 月 ', 'retry_count': 0}
        assert (await client.post(path, json=payload, headers={'Origin': 'http://test'})).status_code == 403
        response = await client.post(path, json=payload, headers={
            'Origin': 'http://test', 'X-CSRF-Token': csrf_token('session'),
        })
    assert response.json() == {'run_id': 'run-1'}
    resume.assert_awaited_once_with(office, runtime, workflow, actor, 'team', 'run-1', '2026 年 1 月', 0)


@pytest.mark.asyncio
@pytest.mark.parametrize('case', ['resume', 'workspace', 'user', 'retry', 'outline', 'completed'])
async def test_office_report_resumes_only_the_current_owned_clarification(case):
    actor = Identity('tenant', 'company', 'writer', 2, 'reference')
    office = SimpleNamespace(space_access=AsyncMock())
    requirement = StepRequirement(
        step_id='generate-outline' if case == 'outline' else 'normalize-report-request',
        requires_output_review=True, is_post_execution=True, retry_count=1,
        step_output=StepOutput(content={'clarificationQuestion': '分析期间？'}),
    )
    run = SimpleNamespace(status=RunStatus.completed if case == 'completed' else RunStatus.paused,
                          step_requirements=[requirement])
    session = SimpleNamespace(session_data={'session_state': {'officeReportSpace': 'team'}},
                              get_run=Mock(return_value=run))

    @asynccontextmanager
    async def lock(run_id):
        assert run_id == 'run-1'
        yield

    repository = SimpleNamespace(get_run=AsyncMock(return_value={
        'database': 'tenant', 'company_id': 'company', 'owner_user_id': 'other' if case == 'user' else 'writer',
        'thread_id': 'office-report:thread', 'agno_session_id': 'session', 'external_run_id': 'run-1',
    }), workflow_execution_lock=lock)
    runtime = SimpleNamespace(state_repository=repository, prepare_run=Mock())

    async def continue_run(**kwargs):
        assert kwargs['run_response'] is run
        assert kwargs['step_requirements'][0].rejection_feedback == '2026 年 1 月'
        identity = require_verified_reporting_identity()
        assert (identity.thread_id, identity.office_space, identity.office_session_version) == ('office-report:thread', 'team', 2)
        return SimpleNamespace(to_dict=lambda: {'run_id': 'run-1'})

    workflow = SimpleNamespace(aget_session=AsyncMock(return_value=session), acontinue_run=AsyncMock(side_effect=continue_run))
    template = SimpleNamespace(deep_copy=Mock(return_value=workflow))
    args = (office, runtime, template, actor, 'other' if case == 'workspace' else 'team',
            'run-1', '2026 年 1 月', 0 if case == 'retry' else 1)
    if case == 'resume':
        assert await resume_office_report(*args) == {'run_id': 'run-1'}
        workflow.aget_session.assert_awaited_once_with(session_id='session', user_id='writer')
        runtime.prepare_run.assert_called_once()
    else:
        with pytest.raises(OfficeError) as error:
            await resume_office_report(*args)
        assert error.value.status == (404 if case in {'workspace', 'user'} else 409)
        workflow.acontinue_run.assert_not_awaited()


@pytest.mark.asyncio
async def test_office_clarification_retries_a_persisted_agno_step(tmp_path):
    from agno.db.sqlite import AsyncSqliteDb
    from agno.workflow import Step
    from agno.workflow.types import HumanReview, OnReject
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient
    from sqlalchemy.ext.asyncio import create_async_engine
    from smart_reporting.office.api import COOKIE, create_office_router, csrf_token
    from smart_reporting.office.repository import OfficeRepository
    from smart_reporting.reporting.workflow.identity import VerifiedReportingIdentity, bind_verified_reporting_identity
    from smart_reporting.reporting.workflow.managed import ManagedReportingWorkflow
    from smart_reporting.reporting.workflow.runtime.base import _ReportWorkflowRuntimeBase
    from smart_reporting.reporting.workflow.scope import REPORT_WORKFLOW_SCOPE_DEPENDENCY

    calls = []
    original = '{"prompt":"营收报告","deliveryFormat":"docx","sourceIds":["sales"]}'

    async def normalize(step_input, run_context):
        assert run_context.dependencies[REPORT_WORKFLOW_SCOPE_DEPENDENCY]['database'] == 'tenant'
        calls.append((step_input.input, (step_input.additional_data or {}).get('rejection_feedback')))
        if len(calls) == 1:
            return StepOutput(content={'clarificationQuestion': '分析期间？'})
        return StepOutput(content={'reportId': 'published'})

    @asynccontextmanager
    async def lock(_run_id):
        yield

    class Lifecycle:
        configuration_provider = object()
        prepare_run = _ReportWorkflowRuntimeBase.prepare_run
        _bind_workspace = Mock()
        start_run = AsyncMock()
        assert_resumable = AsyncMock()
        settle_run = AsyncMock()
        state_repository = SimpleNamespace(workflow_execution_lock=lock, get_run=AsyncMock(), paused_office_runs=AsyncMock())

    runtime = Lifecycle()
    workflow = ManagedReportingWorkflow(id='enterprise-reporting-workflow-v1', name='Reporting',
                                        lifecycle=runtime, db=AsyncSqliteDb(db_file=str(tmp_path / 'runs.db')), steps=[
        Step(step_id='normalize-report-request', name='Normalize', executor=normalize, human_review=HumanReview(
            requires_output_review=lambda output: 'clarificationQuestion' in output.content, on_reject=OnReject.retry,
        )),
    ])
    engine = create_async_engine('sqlite+aiosqlite://')
    try:
        office = OfficeRepository(engine)
        await office.create_schema()
        admin = Identity('tenant', 'company', 'admin')
        actor = Identity('tenant', 'company', 'writer')
        await office.bootstrap(admin, 'Admin')
        await office.provision(admin, actor.user, 'Writer')
        space = (await office.create_space(admin, 'Team', admin.user))['id']
        await office.set_member(admin, space, actor.user, 'editor')
        token = await office.create_session(actor)
        actor = await office.authenticate(token)
        thread = 'office-report:session'
        scope = {REPORT_WORKFLOW_SCOPE_DEPENDENCY: {'database': actor.database, 'companyId': actor.company}}
        with bind_verified_reporting_identity(VerifiedReportingIdentity(
            actor.database, actor.company, actor.user, thread, 'http-capability', space,
            actor.session_version, actor.session_reference,
        )):
            initial = await workflow.arun(original, user_id=actor.user, session_id=thread,
                                          dependencies=scope, stream=False)
        assert initial.status == RunStatus.paused
        requirement = initial.to_dict()['step_requirements'][0]
        runtime.state_repository.get_run.return_value = {
            'report_run_id': initial.run_id,
            'database': actor.database, 'company_id': actor.company, 'owner_user_id': actor.user,
            'thread_id': thread, 'agno_session_id': initial.session_id, 'external_run_id': initial.run_id,
        }
        async def find_paused(database, company, user, workspace, offset):
            assert (database, company, user, workspace) == (actor.database, actor.company, actor.user, space)
            return [] if offset else [runtime.state_repository.get_run.return_value]

        runtime.state_repository.paused_office_runs.side_effect = find_paused
        app = FastAPI()
        app.include_router(create_office_router(office, public_origin='http://test',
                                               report_runtime=runtime, report_workflow=workflow))
        headers = {'Origin': 'http://test', 'X-CSRF-Token': csrf_token(token)}
        path = f'/office/api/workspaces/{space}/reports/{initial.run_id}/clarification'
        latest_path = f'/office/api/workspaces/{space}/reports/pending'
        payload = {'feedback': '2026 年 1 月', 'retry_count': requirement['retry_count']}
        async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test', cookies={COOKIE: token}) as client:
            await office.set_member(admin, space, actor.user, 'viewer')
            assert (await client.get(path)).status_code == 403
            assert (await client.get(latest_path)).status_code == 403
            assert (await client.post(path, json=payload, headers=headers)).status_code == 403
            await office.set_member(admin, space, actor.user, 'editor')
            pending = await client.get(path)
            assert (await client.get(latest_path)).json() == pending.json()
            assert pending.json() == {'pending': {'runId': initial.run_id, 'retryCount': requirement['retry_count'],
                                                   'question': '分析期间？'}}
            response = await client.post(path, json=payload, headers=headers)
            assert response.status_code == 200, response.text
            assert (await client.post(path, json=payload, headers=headers)).status_code == 409
            assert (await client.get(path)).json() == {'pending': None}
            assert (await client.get(latest_path)).json() == {'pending': None}
        finished = response.json()
        assert finished['run_id'] == initial.run_id
        assert finished['status'] == RunStatus.completed.value
        assert calls == [(original, None), (original, '2026 年 1 月')]
        assert [item.args[1] for item in runtime.settle_run.await_args_list] == ['paused', 'completed']
    finally:
        await engine.dispose()

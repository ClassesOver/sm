"""Resume the persisted Agno run after an Office user answers a clarification."""

from agno.run.base import RunStatus

from ..reporting.workflow.identity import VerifiedReportingIdentity, bind_verified_reporting_identity
from ..reporting.workflow.scope import REPORT_WORKFLOW_SCOPE_DEPENDENCY
from ..reporting.workflow.state import ReportingStateError
from .repository import OfficeError


async def _report_run(office, runtime, actor, space, run_id):
    await office.space_access(actor, space, write=True)
    repository = runtime.state_repository
    row = await repository.get_run(run_id)
    if (not row or (row['database'], row['company_id'], row['owner_user_id']) !=
            (actor.database, actor.company, actor.user) or not row['thread_id'].startswith('office-report:')):
        raise OfficeError('office_report_not_found', '找不到此工作区的报告运行。', 404)
    return row


async def _report_output(workflow, actor, space, row, run_id):
    session = await workflow.aget_session(session_id=row['agno_session_id'], user_id=actor.user)
    if not session or (session.session_data or {}).get('session_state', {}).get('officeReportSpace') != space:
        raise OfficeError('office_report_not_found', '找不到此工作区的报告运行。', 404)
    return session.get_run(run_id)


def _clarification(output):
    if not output or output.status != RunStatus.paused:
        return None
    pending = [item for item in (output.step_requirements or []) if not item.is_resolved]
    if len(pending) != 1:
        return None
    requirement = pending[0]
    content = getattr(requirement.step_output, 'content', None)
    question = content.get('clarificationQuestion') if isinstance(content, dict) else None
    if requirement.step_id != 'normalize-report-request' or not isinstance(question, str) or not question.strip():
        return None
    return requirement, question.strip()


async def pending_office_clarification(office, runtime, workflow, actor, space, run_id):
    row = await _report_run(office, runtime, actor, space, run_id)
    output = await _report_output(workflow.deep_copy(), actor, space, row, run_id)
    return {'pending': _pending_payload(run_id, output)}


def _pending_payload(run_id, output):
    pending = _clarification(output)
    return {'runId': run_id, 'retryCount': pending[0].retry_count, 'question': pending[1]} if pending else None


async def latest_office_clarification(office, runtime, workflow, actor, space):
    await office.space_access(actor, space, write=True)
    workflow = workflow.deep_copy()
    offset = 0
    while True:
        rows = await runtime.state_repository.paused_office_runs(actor.database, actor.company, actor.user, space, offset)
        if not rows:
            return {'pending': None}
        for row in rows:
            run_id = row['report_run_id']
            try:
                output = await _report_output(workflow, actor, space, row, run_id)
            except OfficeError as error:
                if error.status != 404:
                    raise
                continue
            pending = _pending_payload(run_id, output)
            if pending:
                await office.space_access(actor, space, write=True)
                return {'pending': pending}
        offset += len(rows)


async def resume_office_report(office, runtime, workflow, actor, space, run_id, feedback, retry_count):
    row = await _report_run(office, runtime, actor, space, run_id)

    try:
        async with runtime.state_repository.workflow_execution_lock(row['external_run_id']):
            workflow = workflow.deep_copy()
            output = await _report_output(workflow, actor, space, row, run_id)
            pending = _clarification(output)
            if not pending or pending[0].retry_count != retry_count:
                raise OfficeError('office_report_review_conflict', '此澄清问题已变更，请核对当前报告状态。', 409)
            requirement = pending[0]

            dependencies = {REPORT_WORKFLOW_SCOPE_DEPENDENCY: {
                'externalRunId': row['external_run_id'], 'threadId': row['thread_id'],
                'database': actor.database, 'companyId': actor.company, 'userId': actor.user,
            }}
            with bind_verified_reporting_identity(VerifiedReportingIdentity(
                actor.database, actor.company, actor.user, row['thread_id'], 'http-capability',
                space, actor.session_version, actor.session_reference,
            )):
                runtime.prepare_run(run_id=run_id, session_id=row['agno_session_id'],
                                    user_id=actor.user, dependencies=dependencies)
                requirement.reject(feedback=feedback)
                result = await workflow.acontinue_run(run_response=output, step_requirements=output.step_requirements,
                                                      dependencies=dependencies, stream=False)
            return result.to_dict()
    except ReportingStateError as error:
        raise OfficeError(error.code, error.message, 409) from error

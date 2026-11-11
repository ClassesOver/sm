"""明确确认后的新口径续跑：复用原生Workflow与持久队列，不重置原票据。"""

from typing import Literal
from uuid import NAMESPACE_URL, uuid5

from loguru import logger
from pydantic import Field, ValidationError

from ..reporting.contract import SHA256_PATTERN, StrictModel
from ..reporting.models import ReportingError
from ..reporting.trace.contracts_v1 import canonical_sha256
from ..reporting.workflow.checkpoint import FileIdentity
from . import recalculation
from .trace_retention import source_lifecycle_lock

_COMPONENT = 'report-editor-policy-recovery'


class RecoveryRunInput(StrictModel):
    report_run_id: str = Field(alias='reportRunId', min_length=1)
    revision: int = Field(ge=1)
    task_id: str = Field(alias='taskId', pattern=r'^recalc-[0-9a-f]{32}$')
    input_hash: str = Field(alias='inputHash', pattern=SHA256_PATTERN)
    context_sha256: str = Field(alias='contextSha256', pattern=SHA256_PATTERN)
    kind: Literal['analysis', 'document']
    identity: FileIdentity


def recovery_run_input(context, task, request):
    return RecoveryRunInput(**recalculation.recalculation_run_input(context, task),
        kind=request.kind, identity=request.identity).model_dump(mode='json', by_alias=True)


def recovery_run_id(inputs):
    return str(uuid5(NAMESPACE_URL, _COMPONENT + ':' + canonical_sha256(inputs)))


def _require_registered(result, inputs):
    candidate = result.get(inputs['kind'], {})
    if candidate.get('status') != 'registered' or candidate.get('identity') != inputs['identity']:
        raise ReportingError('report_editor_conflict', '续跑准备文件尚未确认或身份变化，请重新核对。')


async def _context_and_task(editor, inputs):
    from .service import ReportEditorContext

    parsed = RecoveryRunInput.model_validate(inputs)
    state = await editor.state_repository.get(parsed.report_run_id)
    raw = state.payload.get('reportEditorContexts', {}).get(str(parsed.revision)) if state else None
    if raw is None:
        raise ReportingError('report_editor_scope_mismatch', '续跑缺少已登记报告上下文。')
    context = await editor._restore(ReportEditorContext.model_validate(raw))
    task = await recalculation.read_task_by_id(editor, context, parsed.task_id)
    request = recalculation.PreparationConfirmationRequest(kind=parsed.kind, identity=parsed.identity, expectedStateVersion=0)
    if (task is None or not isinstance(task.request, recalculation.PolicyAdoptionRequest)
            or recovery_run_input(context, task, request) != inputs):
        raise ReportingError('report_editor_scope_mismatch', '续跑输入与已确认原任务不一致。')
    return context, task


def create_policy_recovery_workflow(editor, *, runtime, database):
    from agno.workflow import Step, Workflow
    from agno.workflow.types import StepOutput

    async def execute(step_input, run_context):
        inputs = step_input.input
        context, task = await _context_and_task(editor, inputs)
        if (run_context.run_id != recovery_run_id(inputs)
                or run_context.user_id != context.scope['userId']
                or run_context.session_id != 'report-editor-recovery-' + recovery_run_id(inputs)):
            raise ReportingError('report_editor_scope_mismatch', '续跑用户或原生会话身份不一致。')
        async with source_lifecycle_lock(editor, context, exclusive=True):
            await recalculation.require_recalculation_ended(editor, context, task.task_id, database=database)
            inspected = await recalculation.read_policy_adoption_preparation(editor, context, task.task_id, runtime=runtime)
            _require_registered(inspected, inputs)
            completed, _ = await recalculation.run_policy_adoption_request(editor, context, task.task_id, runtime=runtime)
            return StepOutput(content=completed.model_dump(mode='json', by_alias=True))

    return Workflow(id=_COMPONENT, name='报告准备确认后续跑', db=database,
        steps=[Step(name='confirmed-policy-delivery', executor=execute, max_retries=0)])


def _verify_ticket(context, task, job):
    try:
        inputs = RecoveryRunInput.model_validate((job.get('payload') or {}).get('input')).model_dump(mode='json', by_alias=True)
    except ValidationError as error:
        raise ReportingError('report_editor_scope_mismatch', '续跑票据输入身份无效。') from error
    request = recalculation.PreparationConfirmationRequest(kind=inputs['kind'], identity=inputs['identity'], expectedStateVersion=0)
    run_id = recovery_run_id(inputs)
    if (recovery_run_input(context, task, request) != inputs or job.get('id') != run_id
            or job.get('job_type', 'run') != 'run' or job.get('component_type') != 'workflow'
            or job.get('component_id') != _COMPONENT
            or job.get('deployment_id') != recalculation.recalculation_queue_config().deployment_id
            or job.get('session_id') != 'report-editor-recovery-' + run_id
            or job.get('user_id') != context.scope['userId']):
        raise ReportingError('report_editor_scope_mismatch', '续跑票据与原报告任务或确认文件不一致。')


async def read_policy_recovery(editor, expected, task_id, recovery_id, *, database):
    """只读持久票据；后台执行结束不等于任务交付完成。"""
    from agno.os.job_queue import resolve_queue_store, ticket_status_to_api

    editor._require_lineage_feature('panel')
    context = await editor._restore(expected)
    task = await recalculation.read_task_by_id(editor, context, task_id)
    if task is None or not isinstance(task.request, recalculation.PolicyAdoptionRequest):
        raise ReportingError('source_missing', '续跑任务不存在。')
    worker = editor.recalculation_queue_worker
    store = worker.store if worker else resolve_queue_store(recalculation.recalculation_queue_config(), database)
    job = await store.get_job(recovery_id)
    if job is None:
        raise ReportingError('source_missing', '续跑票据不存在；读取不会创建执行。')
    _verify_ticket(context, task, job)
    status = ticket_status_to_api(job.get('status', ''))
    if status is None:
        raise ReportingError('report_editor_recalculation_unavailable', '续跑票据状态无法核验。')
    status = status.lower()
    issues = ['policy_recovery_completion_unconfirmed'] if status == 'completed' and task.status != 'completed' else []
    return {'taskId': task.task_id, 'recoveryId': recovery_id, 'status': status,
        'deliveryStatus': task.status, 'issueCodes': issues}


async def dispatch_policy_recovery(editor, expected, task_id, request, *, runtime, database):
    """明确确认后委托独立原生票据，同一文件只派发一次，未知响应先读回。"""
    from agno.db.schemas.jobs import QueuedJob
    from agno.os.job_queue import aprepare_accepted_or_abort

    editor._require_lineage_feature('panel')
    context = await editor._restore(expected)
    task = await recalculation.read_task_by_id(editor, context, task_id)
    if task is None or not isinstance(task.request, recalculation.PolicyAdoptionRequest):
        raise ReportingError('source_missing', '续跑任务不存在。')
    if not editor.recalculation_durable or editor.recalculation_queue_worker is None:
        raise ReportingError('report_editor_recalculation_unavailable', '续跑持久队列尚未就绪。')
    worker = editor.recalculation_queue_worker
    inputs = recovery_run_input(context, task, request)
    run_id = recovery_run_id(inputs)
    # 已接受结果优先只读，不因依赖后来不可用而重复执行同一确认。
    if await worker.store.get_job(run_id) is not None:
        return await read_policy_recovery(editor, context, task_id, run_id, database=database)
    async with source_lifecycle_lock(editor, context, exclusive=True):
        if await worker.store.get_job(run_id) is not None:
            return await read_policy_recovery(editor, context, task_id, run_id, database=database)
        task = await recalculation.read_task_by_id(editor, context, task_id)
        if task.status != 'pending':
            raise ReportingError('report_editor_conflict', '原任务已有交付终态，不创建新的续跑。')
        await recalculation.require_recalculation_ended(editor, context, task_id, database=database)
        ready = await recalculation.confirm_policy_adoption_preparation_request(editor, context, task_id, request,
            runtime=runtime, database=database)
        _require_registered(ready, inputs)
        # 仅两种固定准备文件；检查它们已存在的续跑，避免不同文件的票据同时执行同一任务。
        for kind in ('analysis', 'document'):
            candidate = ready.get(kind, {})
            if candidate.get('status') != 'registered':
                continue
            other_request = recalculation.PreparationConfirmationRequest(kind=kind,
                identity=candidate['identity'], expectedStateVersion=0)
            other_id = recovery_run_id(recovery_run_input(context, task, other_request))
            other = await worker.store.get_job(other_id)
            if other is not None:
                _verify_ticket(context, task, other)
                if other.get('status') not in {'completed', 'failed', 'cancelled'}:
                    raise ReportingError('report_editor_conflict', '已有续跑尚未确认结束，请先读取该票据。')
        workflow = create_policy_recovery_workflow(editor, runtime=runtime, database=database)
        try:
            accepted = await worker.store.enqueue_job(QueuedJob(id=run_id, component_type='workflow',
                component_id=_COMPONENT, session_id='report-editor-recovery-' + run_id,
                user_id=context.scope['userId'], payload={'input': inputs, 'stream': False}, max_attempts=1,
                deployment_id=worker.config.deployment_id, idempotency_key=run_id).to_dict(),
                max_depth=worker.config.max_queue_depth)
            if not accepted['accepted'] and accepted.get('reason') != 'duplicate':
                raise ReportingError('report_editor_recalculation_unavailable', '续跑队列未接受请求，请先读取原票据。')
            if accepted['accepted']:
                await aprepare_accepted_or_abort(worker, workflow, 'workflow', run_id,
                    'report-editor-recovery-' + run_id, context.scope['userId'], inputs)
        except ReportingError:
            raise
        except Exception as error:
            logger.warning('policy_recovery_dispatch_unknown recovery_id={} error_type={}', run_id, type(error).__name__)
            raise ReportingError('report_editor_recalculation_unavailable',
                '续跑派发结果未知，请先读取原票据，不要自动重新提交。',
                details={'recoveryId': run_id}) from error
    return await read_policy_recovery(editor, context, task_id, run_id, database=database)

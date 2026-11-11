"""复用报告状态仓储记录复核任务；原快照复核不生成新计算或业务批准。"""

import hashlib
from datetime import UTC, datetime
from typing import Literal

from loguru import logger
from pydantic import Field, model_validator

from ..reporting.contract import SHA256_PATTERN, StrictModel
from ..reporting.models import ReportingError
from ..reporting.semantics.models import PolicyVersionRef
from ..reporting.semantics.policy_adoption import PolicyAdoptionConfirmation
from ..reporting.trace.contracts_v1 import canonical_json_bytes
from ..reporting.workflow.checkpoint import FileIdentity
from ..reporting.workflow.policy_adoption import PolicyAdoptionExecution
from ..reporting.workflow.revision_execution import ReportRevisionExecution
from ..reporting.workflow.state import ReportingCommand
from .revisions import apply_editor_command
from .trace_retention import source_lifecycle_lock


class RecalculationRequest(StrictModel):
    request_id: str = Field(alias='requestId', min_length=1, max_length=128, pattern=r'^[A-Za-z0-9_-]+$')
    parent_revision: int = Field(alias='parentRevision', ge=1)
    expected_sha256: str = Field(alias='expectedSha256', pattern=SHA256_PATTERN)
    operation: Literal['verify_snapshot', 'refresh_data']


class PolicyAdoptionRequest(RecalculationRequest):
    operation: Literal['adopt_policy'] = 'adopt_policy'
    confirmation: PolicyAdoptionConfirmation

    @model_validator(mode='after')
    def explicit_confirmation(self):
        if self.confirmation.request_id != self.request_id:
            raise ValueError('确认与任务请求必须使用同一请求身份')
        questions = tuple(choice.question_id for choice in self.confirmation.question_choices)
        if len(questions) != len(set(questions)):
            raise ValueError('每个问题只能有一项明确选择')
        return self


class PreparationConfirmationRequest(StrictModel):
    kind: Literal['analysis', 'document']
    identity: FileIdentity
    expected_state_version: int = Field(alias='expectedStateVersion', ge=0)


class PolicyAdoptionPreviewRequest(StrictModel):
    parent_revision: int = Field(alias='parentRevision', ge=1)
    expected_sha256: str = Field(alias='expectedSha256', pattern=SHA256_PATTERN)
    policy_version: PolicyVersionRef = Field(alias='policyVersion')


async def policy_adoption_options(editor, expected, *, limit=50, after=None):
    from ..management.models import ManagementScope

    editor._require_lineage_feature('panel')
    async with source_lifecycle_lock(editor, expected, exclusive=False):
        context = await editor._restore(expected)
        source = await editor._source_context(context)
        index = await editor.trace.require_index(source)
        service = editor.trace.report_basis_service
        if service is None or not index.report_basis_id:
            raise ReportingError('report_editor_recalculation_unavailable', '报告缺少可信计算依据，无法读取新口径候选。')
        scope = source.scope
        result = await service.policy_adoption_options(source.workflow_run_id,
            ManagementScope(scope['database'], scope['companyId']), user_id=scope['userId'],
            thread_id=scope['callerThreadId'], limit=limit, after=after)
        if result['parentBasisId'] != index.report_basis_id:
            raise ReportingError('report_editor_scope_mismatch', '口径候选的父依据与报告来源不一致。')
        return {**result, 'parentRevision': context.revision}


async def preview_policy_adoption(editor, expected, request):
    from ..management.models import ManagementScope

    editor._require_lineage_feature('panel')
    async with source_lifecycle_lock(editor, expected, exclusive=False):
        context = await editor._restore(expected)
        if request.parent_revision != context.revision:
            raise ReportingError('report_editor_conflict', '预检与原报告修订不一致。')
        _, _, digest = await editor._read_revision_markdown(context)
        if digest != request.expected_sha256:
            raise ReportingError('report_editor_conflict', '正文已变化，请先保存并核对后重新预检。')
        source = await editor._source_context(context)
        index = await editor.trace.require_index(source)
        service = editor.trace.report_basis_service
        if service is None or not index.report_basis_id:
            raise ReportingError('report_editor_recalculation_unavailable', '报告缺少可信计算依据，无法预检新口径。')
        scope = source.scope
        result = await service.preview_policy_adoption(source.workflow_run_id,
            ManagementScope(scope['database'], scope['companyId']), user_id=scope['userId'],
            thread_id=scope['callerThreadId'], policy_version=request.policy_version.model_dump(mode='json', by_alias=True))
        if result.parent_basis_id != index.report_basis_id:
            raise ReportingError('report_editor_scope_mismatch', '新口径预检的父依据与报告来源不一致。')
        return {'preview': result.model_dump(mode='json', by_alias=True), 'previewHash': result.digest()}


class SnapshotVerification(StrictModel):
    calculation_status: Literal['not_recalculated'] = Field(default='not_recalculated', alias='calculationStatus')
    business_approval: Literal['not_performed'] = Field(default='not_performed', alias='businessApproval')
    draft_sha256: str = Field(alias='draftSha256', pattern=SHA256_PATTERN)
    source_issue_count: int = Field(alias='sourceIssueCount', ge=0)
    knowledge_status: Literal['available', 'unavailable'] = Field(alias='knowledgeStatus')
    invalid_subject_ids: tuple[str, ...] = Field(alias='invalidSubjectIds')
    issue_codes: tuple[str, ...] = Field(alias='issueCodes')
    all_key_facts_evaluated: Literal[False] = Field(default=False, alias='allKeyFactsEvaluated')


class RefreshExecutionBinding(StrictModel):
    parent_report_revision: str = Field(alias='parentReportRevision', min_length=1, max_length=128)
    report_revision: str = Field(alias='reportRevision', pattern=r'^editor-refresh-[0-9a-f]{32}$')

    @model_validator(mode='after')
    def distinct_revisions(self):
        if self.parent_report_revision == self.report_revision:
            raise ValueError('刷新必须生成新的计算修订')
        return self


class RefreshDeliveryResult(StrictModel):
    calculation_status: Literal['refreshed'] = Field(default='refreshed', alias='calculationStatus')
    business_approval: Literal['not_performed'] = Field(default='not_performed', alias='businessApproval')
    execution: ReportRevisionExecution
    artifacts: tuple[FileIdentity, ...] = Field(min_length=1, max_length=4)
    validation_passed: bool = Field(alias='validationPassed')
    issue_codes: tuple[str, ...] = Field(alias='issueCodes')

    @model_validator(mode='after')
    def delivery_identity(self):
        delivery = 'document-render' if set(self.execution.requested_outputs) <= {'pdf', 'docx'} else (
            'slides' if self.execution.requested_outputs == ('pptx',) else 'workbook')
        root = f'报表/智能分析/{self.execution.execution_run_id}/{delivery}/revision-{self.execution.output_revision}'
        allowed = {f'{root}/report.{output}' for output in self.execution.requested_outputs}
        if (len({file.path for file in self.artifacts}) != len(self.artifacts)
                or any(file.path not in allowed for file in self.artifacts)):
            raise ValueError('刷新交付必须属于本执行选择的格式与预留编号')
        return self


class PolicyAdoptionDeliveryResult(StrictModel):
    calculation_status: Literal['adopted_policy'] = Field(default='adopted_policy', alias='calculationStatus')
    business_approval: Literal['not_performed'] = Field(default='not_performed', alias='businessApproval')
    execution: PolicyAdoptionExecution
    artifacts: tuple[FileIdentity, ...] = Field(min_length=1, max_length=4)
    validation_passed: bool = Field(alias='validationPassed')
    issue_codes: tuple[str, ...] = Field(alias='issueCodes')

    @model_validator(mode='after')
    def delivery_identity(self):
        delivery = 'document-render' if set(self.execution.requested_outputs) <= {'pdf', 'docx'} else (
            'slides' if self.execution.requested_outputs == ('pptx',) else 'workbook')
        root = f'报表/智能分析/{self.execution.scope.run_id}/{delivery}/revision-{self.execution.output_revision}'
        allowed = {f'{root}/report.{output}' for output in self.execution.requested_outputs}
        if (len({file.path for file in self.artifacts}) != len(self.artifacts)
                or any(file.path not in allowed for file in self.artifacts)):
            raise ValueError('新口径交付必须属于本执行选择的格式与预留编号')
        return self


class RecalculationTask(StrictModel):
    task_id: str = Field(alias='taskId', pattern=r'^recalc-[0-9a-f]{32}$')
    report_id: str = Field(alias='reportId', min_length=1)
    context_sha256: str = Field(alias='contextSha256', pattern=SHA256_PATTERN)
    basis_id: str = Field(alias='basisId', min_length=1)
    input_hash: str = Field(alias='inputHash', pattern=SHA256_PATTERN)
    request: RecalculationRequest | PolicyAdoptionRequest
    status: Literal['pending', 'completed', 'failed'] = 'pending'
    created_at: datetime = Field(alias='createdAt')
    checked_at: datetime | None = Field(default=None, alias='checkedAt')
    refresh_binding: RefreshExecutionBinding | None = Field(default=None, alias='refreshBinding')
    result: SnapshotVerification | RefreshDeliveryResult | PolicyAdoptionDeliveryResult | None = None
    error_code: str | None = Field(default=None, alias='errorCode', max_length=128)

    @model_validator(mode='after')
    def terminal_result(self):
        if (self.request.operation == 'refresh_data') != (self.refresh_binding is not None):
            raise ValueError('刷新任务必须绑定独立计算修订；原快照复核不能附加刷新执行')
        if self.refresh_binding and self.refresh_binding.report_revision != (
                'editor-refresh-' + self.task_id.removeprefix('recalc-')):
            raise ValueError('目标计算修订必须由登记任务身份唯一派生')
        if self.request.operation == 'adopt_policy' and not isinstance(self.request, PolicyAdoptionRequest):
            raise ValueError('采用新口径必须登记完整显式确认')
        if self.result is not None:
            if self.request.operation == 'adopt_policy':
                if (not isinstance(self.result, PolicyAdoptionDeliveryResult)
                        or self.result.execution.parent_basis_id != self.basis_id
                        or self.result.execution.request_id != self.task_id):
                    raise ValueError('新口径完成必须绑定本任务与可信父依据的实际交付')
            elif self.request.operation == 'refresh_data':
                if (not isinstance(self.result, RefreshDeliveryResult)
                        or self.result.execution.basis_id != self.basis_id
                        or self.result.execution.report_revision != self.refresh_binding.report_revision
                        or self.result.execution.parent_report_revision != self.refresh_binding.parent_report_revision):
                    raise ValueError('刷新完成必须绑定本任务计算修订的实际交付')
            elif not isinstance(self.result, SnapshotVerification):
                raise ValueError('快照复核不能冒充已刷新计算')
        if self.created_at.utcoffset() is None or (self.checked_at and self.checked_at.utcoffset() is None):
            raise ValueError('复核任务时间必须包含时区')
        if self.status == 'pending' and (self.result or self.error_code or self.checked_at):
            raise ValueError('待复核任务不能附加结果')
        if self.status == 'completed' and (not self.result or self.error_code or not self.checked_at):
            raise ValueError('完成复核必须有结果及时间')
        if self.status == 'failed' and (self.result or not self.error_code or not self.checked_at):
            raise ValueError('复核失败必须给出原因及时间')
        if self.checked_at and self.checked_at < self.created_at:
            raise ValueError('复核完成时间不能早于登记时间')
        if isinstance(self.result, SnapshotVerification) and self.result.draft_sha256 != self.request.expected_sha256:
            raise ValueError('复核结果正文身份必须与请求一致')
        return self


def task_identity(context, request_id):
    return 'recalc-' + hashlib.sha256(canonical_json_bytes({
        'runId': context.workflow_run_id, 'reportId': context.report_id,
        'parentRevision': context.revision, 'requestId': request_id,
    })).hexdigest()[:32]


def request_hash(context, request):
    return hashlib.sha256(canonical_json_bytes({
        'contextSha256': context.digest(), 'request': request.model_dump(mode='json', by_alias=True),
    })).hexdigest()


async def read_task(editor, context, request_id):
    return await read_task_by_id(editor, context, task_identity(context, request_id))


async def read_task_by_id(editor, context, task_id):
    state = await editor.state_repository.get(context.workflow_run_id)
    raw = state.payload.get('reportEditorRecalculations', {}).get(task_id) if state else None
    if raw is None:
        return None
    task = RecalculationTask.model_validate(raw)
    if (task.context_sha256 != context.digest() or task.report_id != context.report_id
            or task.task_id != task_id or task.task_id != task_identity(context, task.request.request_id)
            or task.request.parent_revision != context.revision or task.input_hash != request_hash(context, task.request)):
        raise ReportingError('report_editor_scope_mismatch', '复核任务不属于当前报告修订。')
    return task


async def record_task(editor, context, task):
    payload = task.model_dump(mode='json', by_alias=True)
    await apply_editor_command(editor.state_repository, context.workflow_run_id, ReportingCommand(
        name='record_report_editor_recalculation', payload={'task': payload},
        commandId='editor-recalc:' + hashlib.sha256(canonical_json_bytes(payload)).hexdigest(),
    ))


async def start_recalculation(editor, expected, request):
    editor._require_lineage_feature('panel')
    if request.operation in {'refresh_data', 'adopt_policy'}:
        runtime, database = editor.recalculation_runtime, editor.recalculation_database
        if runtime is None or database is None:
            raise ReportingError('report_editor_recalculation_unavailable', '报告重算后台服务尚未启用。')
        if request.operation == 'adopt_policy':
            if not isinstance(request, PolicyAdoptionRequest) or getattr(runtime, 'report_basis_service', None) is None:
                raise ReportingError('report_editor_recalculation_unavailable', '采用新口径需要完整确认与计算依据服务。')
        elif getattr(runtime, 'configuration_provider', None) is None:
            raise ReportingError('report_editor_recalculation_unavailable', '数据刷新后台服务尚未启用。')
        context = await editor._restore(expected)
        if request.parent_revision != context.revision:
            raise ReportingError('report_editor_conflict', '重算请求与父修订不一致。')
        task = await read_task(editor, context, request.request_id)
        if task is not None:
            if task.input_hash != request_hash(context, request):
                raise ReportingError('report_editor_conflict', '同一请求已登记其他输入，请核对原任务。')
        elif request.operation == 'adopt_policy':
            task = await register_policy_adoption_request(editor, context, request)
        else:
            task = await register_refresh_request(editor, context, request,
                vault=runtime.configuration_provider.vault)
        if task.status == 'pending':
            await dispatch_recalculation_request(editor, context, task.task_id, runtime=runtime, database=database)
        return await task_response(editor, context, task)
    # 同机跨worker共用已有来源锁：重复提交先读耐久状态，不重复复核；不持有共享锁再升级。
    async with source_lifecycle_lock(editor, expected, exclusive=True):
        context = await editor._restore(expected)
        if request.parent_revision != context.revision:
            raise ReportingError('report_editor_conflict', '复核请求与父修订不一致。')
        previous = await read_task(editor, context, request.request_id)
        digest = request_hash(context, request)
        if previous is not None:
            if previous.input_hash != digest:
                raise ReportingError('report_editor_conflict', '同一请求已登记其他输入，请先核对原任务。')
            if previous.status != 'pending':
                return previous.model_dump(mode='json', by_alias=True)
        if request.operation != 'verify_snapshot':
            raise ReportingError('report_editor_recalculation_unavailable', '真实数据刷新和采用新口径的执行器尚未启用。')
        source = await editor._source_context(context)
        _, markdown, sha256 = await editor._read_revision_markdown(context)
        if sha256 != request.expected_sha256:
            raise ReportingError('report_editor_conflict', '正文已变化，请重新读取后复核。')
        index = await editor.trace.require_index(source)
        if not index.report_basis_id:
            raise ReportingError('report_editor_recalculation_unavailable', '本报告未登记计算依据，无法复核。')
        task = previous or RecalculationTask(taskId=task_identity(context, request.request_id), reportId=context.report_id,
            contextSha256=context.digest(), basisId=index.report_basis_id, inputHash=digest, request=request,
            createdAt=datetime.now(UTC))
        if task.basis_id != index.report_basis_id:
            raise ReportingError('report_editor_conflict', '待复核任务的计算依据已变化。')
        await record_task(editor, context, task)
        try:
            validation = await editor.trace.validate(source, markdown, sha256,
                analysis_context_file=await editor._registered_analysis_context_file(context))
            codes = {item['code'] for item in validation.get('quality', {}).get('issues', [])}
            codes.update(item['code'] for item in validation.get('sourceIssues', []))
            codes.update(validation.get('revisionImpactIssues', []))
            codes.update(validation.get('businessKnowledge', {}).get('issueCodes', []))
            if validation.get('quality', {}).get('status') != 'evaluated':
                codes.add('quality_evaluation_unavailable')
            result = SnapshotVerification(draftSha256=sha256,
                knowledgeStatus=validation.get('businessKnowledge', {}).get('status', 'unavailable'),
                sourceIssueCount=len(validation.get('sourceIssues', [])),
                invalidSubjectIds=tuple(item['subjectId'] for item in validation['subjects'] if item['status'] != 'valid'),
                issueCodes=tuple(sorted(codes)))
            task = task.model_copy(update={'status': 'completed', 'result': result, 'checked_at': datetime.now(UTC)})
        except Exception as error:
            logger.warning('editor_snapshot_verification_failed report_id={} reason={}', context.report_id, type(error).__name__)
            task = task.model_copy(update={'status': 'failed', 'error_code': 'snapshot_verification_unavailable',
                'checked_at': datetime.now(UTC)})
        # 提交失败不宣称任务成功；保留pending供读回，同输入可安全重做只读复核。
        await record_task(editor, context, task)
        return task.model_dump(mode='json', by_alias=True)


async def register_policy_adoption_request(editor, expected, request):
    """冻结Editor父修订、正文及明确选择；登记意图不执行取数或创建新依据。"""
    from ..management.models import ManagementScope

    editor._require_lineage_feature('panel')
    if not isinstance(request, PolicyAdoptionRequest):
        raise ReportingError('report_editor_recalculation_unavailable', '采用新口径必须提供完整确认内容。')
    async with source_lifecycle_lock(editor, expected, exclusive=True):
        context = await editor._restore(expected)
        if request.parent_revision != context.revision:
            raise ReportingError('report_editor_conflict', '确认请求与父交付修订不一致。')
        previous = await read_task(editor, context, request.request_id)
        if previous is not None:
            if previous.input_hash != request_hash(context, request):
                raise ReportingError('report_editor_conflict', '同一确认请求已登记其他输入，请读取原任务核对。')
            return previous
        _, _, sha256 = await editor._read_revision_markdown(context)
        if sha256 != request.expected_sha256:
            raise ReportingError('report_editor_conflict', '正文已变化，请保存并重新核对新口径确认。')
        source = await editor._source_context(context)
        index = await editor.trace.require_index(source)
        service = editor.trace.report_basis_service
        if service is None or not index.report_basis_id:
            raise ReportingError('report_editor_recalculation_unavailable', '报告缺少可信计算依据，无法确认新口径。')
        scope = source.scope
        preview = await service.preview_policy_adoption(source.workflow_run_id,
            ManagementScope(scope['database'], scope['companyId']), user_id=scope['userId'],
            thread_id=scope['callerThreadId'],
            policy_version=request.confirmation.target_policy_version.model_dump(mode='json', by_alias=True))
        if preview.parent_basis_id != index.report_basis_id:
            raise ReportingError('report_editor_scope_mismatch', '确认预检的父依据与当前报告来源不一致。')
        if preview.digest() != request.confirmation.preview_hash:
            raise ReportingError('report_editor_conflict', '新口径预检已变化，请重新核对后确认。')
        task = RecalculationTask(taskId=task_identity(context, request.request_id), reportId=context.report_id,
            contextSha256=context.digest(), basisId=index.report_basis_id,
            inputHash=request_hash(context, request), request=request, createdAt=datetime.now(UTC))
        await record_task(editor, context, task)
        return task


async def register_refresh_request(editor, expected, request, *, parent_report_revision=None, vault=None):
    """内部控制器登记刷新意图；父计算修订由可信运行解析，HTTP请求不能指定。"""
    editor._require_lineage_feature('panel')
    if request.operation != 'refresh_data':
        raise ReportingError('report_editor_recalculation_unavailable', '此登记入口只接受数据刷新。')
    async with source_lifecycle_lock(editor, expected, exclusive=True):
        context = await editor._restore(expected)
        if request.parent_revision != context.revision:
            raise ReportingError('report_editor_conflict', '刷新请求与父交付修订不一致。')
        task_id = task_identity(context, request.request_id)
        previous = await read_task(editor, context, request.request_id)
        if previous is not None:
            if (previous.input_hash != request_hash(context, request)
                    or parent_report_revision is not None and (
                        previous.refresh_binding is None
                        or previous.refresh_binding.parent_report_revision != parent_report_revision)):
                raise ReportingError('report_editor_conflict', '同一刷新请求已绑定其他输入或父计算修订。')
            return previous
        _, _, sha256 = await editor._read_revision_markdown(context)
        if sha256 != request.expected_sha256:
            raise ReportingError('report_editor_conflict', '正文已变化，请读取后重新发起刷新。')
        source = await editor._source_context(context)
        index = await editor.trace.require_index(source)
        if not index.report_basis_id:
            raise ReportingError('report_editor_recalculation_unavailable', '报告未登记计算依据，无法刷新。')
        if parent_report_revision is None:
            parent = await resolve_refresh_parent(editor, context, vault=vault)
            if parent.basis_id != index.report_basis_id:
                raise ReportingError('report_editor_scope_mismatch', '刷新父依据与当前来源不一致。')
            parent_report_revision = parent.report_revision
        binding = RefreshExecutionBinding(parentReportRevision=parent_report_revision,
            reportRevision='editor-refresh-' + task_id.removeprefix('recalc-'))
        task = RecalculationTask(taskId=task_id, reportId=context.report_id,
            contextSha256=context.digest(), basisId=index.report_basis_id,
            inputHash=request_hash(context, request), request=request, refreshBinding=binding,
            createdAt=datetime.now(UTC))
        await record_task(editor, context, task)
        return task


async def resolve_refresh_parent(editor, expected, *, vault):
    """从当前实际来源的正式事实及管理回执恢复父计算，不猜交付版本或最新版本。"""
    from ..management.models import ManagementScope
    from ..reporting.semantics.planning_contracts import MetricPlanningContext
    from ..reporting.trace.fact_service import read_fact_document

    source = await editor._source_context(expected)
    index = await editor.trace.require_index(source)
    files = {item.resource_id: item for item in index.files}
    parent = None
    for entry in index.fact_files:
        if entry.content_kind != 'deterministic_bundle':
            continue
        raw = await editor.trace._read_registered_file(source, files[entry.file_resource_id],
            max_bytes=16 * 1024 * 1024)
        document = read_fact_document(raw)
        if document.get('analysisId') != entry.analysis_id or document.get('metricContext') is None:
            raise ReportingError('report_editor_recalculation_unavailable', '来源事实缺少可绑定的正式计算上下文。')
        candidate = MetricPlanningContext.model_validate(document['metricContext'])
        if candidate.basis_id != index.report_basis_id or parent is not None and parent != candidate:
            raise ReportingError('report_editor_scope_mismatch', '来源事实引用了不同的计算依据或修订。')
        parent = candidate
    if parent is None or editor.trace.report_basis_service is None:
        raise ReportingError('report_editor_recalculation_unavailable', '缺少正式计算来源或管理回执服务，无法刷新。')
    scope = source.scope
    registered = await editor.trace.report_basis_service.load_registered_revision_planning_context(
        source.workflow_run_id, ManagementScope(scope['database'], scope['companyId']),
        user_id=scope['userId'], thread_id=scope['callerThreadId'],
        report_revision=parent.report_revision, vault=vault)
    if registered != parent:
        raise ReportingError('report_editor_scope_mismatch', '报告来源与管理服务登记的计算修订不一致。')
    return registered


async def run_policy_adoption_request(editor, expected, task_id, *, runtime):
    """从已冻结确认登记新依据并委托原生交付；任务完成记录不保存下载授权。"""
    from agno.run import RunContext
    from agno.workflow.types import StepOutput

    from ..management.models import ManagementScope
    from ..reporting.workflow.policy_adoption import prepare_policy_adoption_execution
    from ..reporting.workflow.policy_adoption_analysis import continue_policy_adoption_delivery
    from ..reporting.workflow.runtime.base import REPORT_WORKFLOW_SCOPE_STATE_KEY

    editor._require_lineage_feature('panel')
    async with source_lifecycle_lock(editor, expected, exclusive=True):
        context = await editor._restore(expected)
        task = await read_task_by_id(editor, context, task_id)
        if task is None or not isinstance(task.request, PolicyAdoptionRequest) or task.status == 'failed':
            raise ReportingError('report_editor_recalculation_unavailable', '没有可执行的已确认新口径任务。')
        run_context = RunContext(run_id=context.workflow_run_id, session_id=context.scope['sessionId'],
            user_id=context.scope['userId'], session_state={REPORT_WORKFLOW_SCOPE_STATE_KEY: context.scope})
        if task.status == 'completed':
            execution = task.result.execution
        else:
            # 管理确认身份从任务派生，避免相同客户端requestId在不同父修订间串用新依据。
            confirmation = task.request.confirmation.model_copy(update={'request_id': task.task_id})
            receipt = await runtime.report_basis_service.register_policy_adoption(context.workflow_run_id,
                ManagementScope(context.scope['database'], context.scope['companyId']),
                user_id=context.scope['userId'], thread_id=context.scope['callerThreadId'],
                confirmation=confirmation, build_identity=runtime.report_build_identity)
            if receipt.parent_basis_id != task.basis_id:
                raise ReportingError('report_editor_scope_mismatch', '新口径登记的父依据与确认任务不一致。')
            execution = await prepare_policy_adoption_execution(runtime, run_context, request_id=task.task_id)
            if (execution.scope.run_id, execution.basis_id) != (receipt.target_run_id, receipt.basis_id):
                raise ReportingError('report_editor_scope_mismatch', '新执行与已登记新依据不一致。')
        if (execution.source_scope.run_id != context.workflow_run_id or execution.source_scope.as_state() != context.scope
                or execution.parent_basis_id != task.basis_id or execution.request_id != task.task_id):
            raise ReportingError('report_editor_scope_mismatch', '新口径执行与原报告作用域或确认任务不一致。')
        published = (await runtime._publish_revision_report(run_context, execution) if task.status == 'completed'
            else await continue_policy_adoption_delivery(runtime, run_context, execution))
        content = dict(published.content)
        delivery = 'document-render' if set(execution.requested_outputs) <= {'pdf', 'docx'} else (
            'slides' if execution.requested_outputs == ('pptx',) else 'workbook')
        root = f'报表/智能分析/{execution.scope.run_id}/{delivery}/revision-{execution.output_revision}'
        artifacts, identity_issues = [], []
        for label in ('pdf', 'word', 'pptx', 'xlsx'):
            if not content.get(f'{label}Path'):
                continue
            try:
                file = FileIdentity(path=content[f'{label}Path'], size=content[f'{label}Size'], sha256=content[f'{label}Sha256'])
                output = 'docx' if label == 'word' else label
                if output not in execution.requested_outputs or file.path != f'{root}/report.{output}':
                    raise ValueError('policy adoption artifact does not belong to execution')
                await runtime._read_identity_bytes(execution.scope.workspace_key, file, max_bytes=file.size)
                artifacts.append(file)
            except Exception as error:
                logger.warning('policy_adoption_artifact_unavailable format={} error_type={}', label, type(error).__name__)
                for suffix in ('Path', 'Size', 'Sha256'):
                    content.pop(f'{label}{suffix}', None)
                identity_issues.append({'code': f'policy_adoption_{label}_artifact_unavailable',
                    'message': '该格式文件身份无法核验，其他已核验格式仍可下载。'})
        if identity_issues:
            issues = [*content.get('validation', {}).get('issues', ()), *identity_issues]
            content.update({'status': 'validation_failed', 'validation': {
                **content.get('validation', {}), 'ok': False, 'issues': issues}, 'validationIssues': issues})
        published = StepOutput(content=content)
        if not artifacts:
            raise ReportingError('report_artifact_unavailable', '新口径尚无可核验交付，任务不能标为完成。')
        if task.status == 'completed':
            return task, published
        result = PolicyAdoptionDeliveryResult(execution=execution, artifacts=artifacts,
            validationPassed=content.get('validation', {}).get('ok') is True,
            issueCodes=tuple(sorted({item['code'] for group in (content.get('validation', {}),
                content.get('publicationGate', {})) for item in group.get('issues', ())})))
        completed = task.model_copy(update={'status': 'completed', 'result': result, 'checked_at': datetime.now(UTC)})
        try:
            await record_task(editor, context, completed)
        except Exception as error:
            logger.warning('policy_adoption_completion_record_unavailable report_id={} error_type={}',
                context.report_id, type(error).__name__)
            issue = {'code': 'policy_adoption_completion_record_unavailable',
                'message': '新口径文件已生成，完成登记结果未知；文件仍可下载，请先读取原任务状态。'}
            issues = [*content.get('validation', {}).get('issues', ()), issue]
            content.update({'status': 'validation_failed', 'validation': {
                **content.get('validation', {}), 'ok': False, 'issues': issues}, 'validationIssues': issues})
            return task, StepOutput(content=content)
        return completed, published


async def run_refresh_request(editor, expected, task_id, *, runtime):
    """执行已登记意图；调度可重复委托，完成结果不保存会过期的下载授权。"""
    from agno.run import RunContext

    from ..reporting.workflow.revision_execution import (
        continue_revision_delivery,
        prepare_refresh_delivery,
    )
    from ..reporting.workflow.runtime.base import REPORT_WORKFLOW_SCOPE_STATE_KEY

    editor._require_lineage_feature('panel')
    async with source_lifecycle_lock(editor, expected, exclusive=True):
        context = await editor._restore(expected)
        task = await read_task_by_id(editor, context, task_id)
        if task is None or task.request.operation != 'refresh_data' or task.refresh_binding is None:
            raise ReportingError('report_editor_recalculation_unavailable', '没有可执行的已登记刷新请求。')
        run_context = RunContext(run_id=context.workflow_run_id, session_id=context.scope['sessionId'],
            user_id=context.scope['userId'], session_state={REPORT_WORKFLOW_SCOPE_STATE_KEY: context.scope})
        if task.status == 'failed':
            raise ReportingError('report_editor_recalculation_unavailable', '刷新任务已失败，请核对原因后使用新请求。')
        if task.status == 'completed':
            execution = task.result.execution
        else:
            execution = await prepare_refresh_delivery(runtime, run_context,
                parent_report_revision=task.refresh_binding.parent_report_revision,
                report_revision=task.refresh_binding.report_revision)
        if (execution.basis_id != task.basis_id or execution.source_scope.run_id != context.workflow_run_id
                or execution.source_scope.as_state() != context.scope
                or execution.report_revision != task.refresh_binding.report_revision
                or execution.parent_report_revision != task.refresh_binding.parent_report_revision):
            raise ReportingError('report_editor_scope_mismatch', '刷新执行与已登记任务或原报告作用域不一致。')
        published = await continue_revision_delivery(runtime, run_context, execution)
        from agno.workflow.types import StepOutput

        content = dict(published.content)
        artifacts, identity_issues = [], []
        delivery = 'document-render' if set(execution.requested_outputs) <= {'pdf', 'docx'} else (
            'slides' if execution.requested_outputs == ('pptx',) else 'workbook')
        root = f'报表/智能分析/{execution.execution_run_id}/{delivery}/revision-{execution.output_revision}'
        for label in ('pdf', 'word', 'pptx', 'xlsx'):
            if not content.get(f'{label}Path'):
                continue
            try:
                identity = FileIdentity(path=content[f'{label}Path'], size=content[f'{label}Size'],
                    sha256=content[f'{label}Sha256'])
                output_format = 'docx' if label == 'word' else label
                if output_format not in execution.requested_outputs or identity.path != f'{root}/report.{output_format}':
                    raise ValueError('refresh artifact does not belong to execution')
                await runtime._read_identity_bytes(execution.source_scope.workspace_key, identity)
                artifacts.append(identity)
            except Exception as error:
                logger.warning('refresh_artifact_unavailable format={} error_type={}', label, type(error).__name__)
                for suffix in ('Path', 'Size', 'Sha256'):
                    content.pop(f'{label}{suffix}', None)
                identity_issues.append({'code': f'refresh_{label}_artifact_unavailable',
                    'message': '该格式文件身份无法核验，其他已核验格式仍可下载。'})
        if identity_issues:
            issues = [*content.get('validation', {}).get('issues', ()), *identity_issues]
            content.update({'validation': {**content.get('validation', {}), 'ok': False, 'issues': issues},
                'validationIssues': issues, 'status': 'validation_failed'})
            published = StepOutput(content=content)
        if not artifacts:
            raise ReportingError('report_editor_recalculation_unavailable', '新修订尚无可核验交付，任务无法完成。')
        if task.status == 'completed':
            return task, published
        result = RefreshDeliveryResult(execution=execution, artifacts=artifacts,
            validationPassed=content.get('validation', {}).get('ok') is True,
            issueCodes=tuple(sorted({item['code'] for group in (content.get('validation', {}),
                content.get('publicationGate', {})) for item in group.get('issues', ())})))
        completed = task.model_copy(update={'status': 'completed', 'result': result, 'checked_at': datetime.now(UTC)})
        try:
            await record_task(editor, context, completed)
        except Exception as error:
            from agno.workflow.types import StepOutput

            logger.warning('refresh_completion_record_unavailable report_id={} error_type={}',
                context.report_id, type(error).__name__)
            issue = {'code': 'refresh_completion_record_unavailable',
                'message': '新修订文件已生成，刷新完成登记结果未知；文件仍可下载，请先读取原任务状态。'}
            content = dict(published.content)
            issues = [*content.get('validation', {}).get('issues', ()), issue]
            content.update({'validation': {**content.get('validation', {}), 'ok': False, 'issues': issues},
                'validationIssues': issues, 'status': 'validation_failed'})
            return task, StepOutput(content=content)
        return completed, published


async def read_refresh_delivery(editor, expected, task_id, *, runtime):
    """只恢复已登记执行的交付；完成登记失败也不能撤销已生成文件。"""
    from agno.run import RunContext

    from ..reporting.workflow.runtime.base import REPORT_WORKFLOW_SCOPE_STATE_KEY

    editor._require_lineage_feature('panel')
    context = await editor._restore(expected)
    task = await read_task_by_id(editor, context, task_id)
    if task is None or task.request.operation != 'refresh_data':
        raise ReportingError('report_editor_recalculation_unavailable', '没有可读取的已登记刷新请求。')
    if task.status == 'completed':
        execution = task.result.execution
    else:
        source = await editor.state_repository.get(context.workflow_run_id)
        executions = []
        for child_id in source.payload.get('reportEditorRevisionReservations', {}):
            child = await editor.state_repository.get(child_id)
            raw = child.payload.get('reportRevisionExecution') if child else None
            if raw is not None and raw.get('reportRevision') == task.refresh_binding.report_revision:
                executions.append(ReportRevisionExecution.model_validate(raw))
        if len(executions) != 1:
            raise ReportingError('report_editor_recalculation_unavailable', '刷新尚无唯一已登记执行；读取不会启动计算。')
        execution = executions[0]
    if (execution.source_scope.as_state() != context.scope
            or execution.source_scope.run_id != context.workflow_run_id
            or execution.basis_id != task.basis_id
            or execution.report_revision != task.refresh_binding.report_revision
            or execution.parent_report_revision != task.refresh_binding.parent_report_revision):
        raise ReportingError('report_editor_scope_mismatch', '刷新交付与已登记请求作用域不一致。')
    run_context = RunContext(run_id=context.workflow_run_id, session_id=context.scope['sessionId'],
        user_id=context.scope['userId'], session_state={REPORT_WORKFLOW_SCOPE_STATE_KEY: context.scope})
    published = await runtime._publish_revision_report(run_context, execution)
    if task.status != 'completed':
        from agno.workflow.types import StepOutput

        content = dict(published.content)
        issue = {'code': 'refresh_completion_record_unavailable',
            'message': '刷新完成状态未确认；已核验文件仍可下载，请先读取任务状态。'}
        issues = [*content.get('validation', {}).get('issues', ()), issue]
        content.update({'validation': {**content.get('validation', {}), 'ok': False, 'issues': issues},
            'validationIssues': issues, 'status': 'validation_failed'})
        published = StepOutput(content=content)
    return task, published


async def _read_policy_adoption_execution(editor, context, task):
    """从可信任务和父修订登记中查找执行，不创建目标运行。"""
    if task.status == 'completed':
        execution = task.result.execution
    else:
        source = await editor.state_repository.get(context.workflow_run_id)
        executions = []
        for child_id in source.payload.get('reportEditorRevisionReservations', {}):
            child = await editor.state_repository.get(child_id)
            raw = child.payload.get('reportPolicyAdoptionExecution') if child else None
            if raw is not None and raw.get('requestId') == task.task_id:
                executions.append(PolicyAdoptionExecution.model_validate(raw))
        if len(executions) != 1:
            raise ReportingError('report_editor_recalculation_unavailable', '新口径尚无唯一已登记执行；读取不会启动计算。')
        execution = executions[0]
    if (execution.source_scope.as_state() != context.scope
            or execution.source_scope.run_id != context.workflow_run_id
            or execution.parent_basis_id != task.basis_id or execution.request_id != task.task_id):
        raise ReportingError('report_editor_scope_mismatch', '新口径交付与已确认任务作用域不一致。')
    return execution


async def read_policy_adoption_delivery(editor, expected, task_id, *, runtime):
    """仅读回已登记新执行及产物；读取动作不确认口径、不准备执行或取数。"""
    from agno.run import RunContext
    from agno.workflow.types import StepOutput

    from ..reporting.workflow.runtime.base import REPORT_WORKFLOW_SCOPE_STATE_KEY

    editor._require_lineage_feature('panel')
    context = await editor._restore(expected)
    task = await read_task_by_id(editor, context, task_id)
    if task is None or not isinstance(task.request, PolicyAdoptionRequest):
        raise ReportingError('report_editor_recalculation_unavailable', '没有可读取的已确认新口径任务。')
    execution = await _read_policy_adoption_execution(editor, context, task)
    run_context = RunContext(run_id=context.workflow_run_id, session_id=context.scope['sessionId'],
        user_id=context.scope['userId'], session_state={REPORT_WORKFLOW_SCOPE_STATE_KEY: context.scope})
    published = await runtime._publish_revision_report(run_context, execution)
    if task.status != 'completed':
        content = dict(published.content)
        issue = {'code': 'policy_adoption_completion_record_unavailable',
            'message': '新口径完成状态未确认；已核验文件仍可下载，请先读取任务状态。'}
        issues = [*content.get('validation', {}).get('issues', ()), issue]
        content.update({'validation': {**content.get('validation', {}), 'ok': False, 'issues': issues},
            'validationIssues': issues, 'status': 'validation_failed'})
        published = StepOutput(content=content)
    return task, published, execution


async def read_policy_adoption_preparation(editor, expected, task_id, *, runtime):
    """报告修订授权下只读检查，既不派发也不补登记。"""
    from agno.run import RunContext

    from ..reporting.workflow.policy_adoption_recovery import inspect_policy_adoption_preparation

    editor._require_lineage_feature('panel')
    async with source_lifecycle_lock(editor, expected, exclusive=False):
        context = await editor._restore(expected)
        task = await read_task_by_id(editor, context, task_id)
        if task is None or not isinstance(task.request, PolicyAdoptionRequest):
            raise ReportingError('report_editor_recalculation_unavailable', '没有可核对的已确认新口径任务。')
        execution = await _read_policy_adoption_execution(editor, context, task)
        source = RunContext(run_id=context.workflow_run_id, session_id=context.scope['sessionId'],
            user_id=context.scope['userId'], session_state={'report_workflow_scope': context.scope})
        result = await inspect_policy_adoption_preparation(runtime, source, execution)
        # 请求前即可缓存票据身份，网络响应完全丢失时仍能按原身份只读查询。
        from .policy_recovery import recovery_run_id, recovery_run_input

        for kind in ('analysis', 'document'):
            candidate = result[kind]
            if candidate.get('identity') is not None:
                request = PreparationConfirmationRequest(kind=kind, identity=candidate['identity'],
                    expectedStateVersion=result['stateVersion'])
                candidate['recoveryId'] = recovery_run_id(recovery_run_input(context, task, request))
        return {'taskId': task.task_id, 'runId': execution.scope.run_id,
            'outputRevision': execution.output_revision, **result}


async def require_recalculation_ended(editor, context, task_id, *, database):
    """持久会话终态和队列票据终态分别核验，旧会话不能掩盖运行中票据。"""
    for queue_only in ((False, True) if editor.recalculation_durable else (False,)):
        try:
            run = await read_recalculation_run(editor, context, task_id, database=database, queue_only=queue_only)
        except ReportingError:
            raise
        except Exception as error:
            logger.warning('policy_adoption_preparation_run_status_unavailable error_type={}', type(error).__name__)
            raise ReportingError('report_editor_recalculation_unavailable', '原执行状态无法核验，本次未确认准备文件。') from error
        if run is None or str(getattr(run.status, 'value', run.status)).lower() not in {'completed', 'error', 'cancelled'}:
            raise ReportingError('report_editor_conflict', '原执行尚未确认结束，请先读取原任务状态。')


async def confirm_policy_adoption_preparation_request(editor, expected, task_id, request, *, runtime, database):
    """原执行已结束后显式补登记；不会改变队列状态或重新取数。"""
    from agno.run import RunContext

    from ..reporting.workflow.policy_adoption_recovery import confirm_policy_adoption_preparation

    editor._require_lineage_feature('panel')
    context = await editor._restore(expected)
    await require_recalculation_ended(editor, context, task_id, database=database)
    async with source_lifecycle_lock(editor, context, exclusive=True):
        context = await editor._restore(expected)
        task = await read_task_by_id(editor, context, task_id)
        if task is None or not isinstance(task.request, PolicyAdoptionRequest) or task.status == 'failed':
            raise ReportingError('report_editor_recalculation_unavailable', '没有可确认的已登记新口径任务。')
        # 进入写锁后再次核对原生状态；不能把观测失败当作执行已停止。
        await require_recalculation_ended(editor, context, task_id, database=database)
        execution = await _read_policy_adoption_execution(editor, context, task)
        source = RunContext(run_id=context.workflow_run_id, session_id=context.scope['sessionId'],
            user_id=context.scope['userId'], session_state={'report_workflow_scope': context.scope})
        try:
            result = await confirm_policy_adoption_preparation(runtime, source, execution,
                kind=request.kind, identity=request.identity, expected_state_version=request.expected_state_version)
        except ReportingError:
            raise
        except Exception as error:
            logger.warning('policy_adoption_preparation_confirmation_unknown error_type={}', type(error).__name__)
            raise ReportingError('report_editor_recalculation_unavailable',
                '确认结果未知，请先读取原准备状态；不要自动再次提交。') from error
        return {'taskId': task.task_id, 'runId': execution.scope.run_id,
            'outputRevision': execution.output_revision, **result}


async def read_recalculation_run(editor, expected, task_id, *, database, queue_only=False):
    """仅读取已登记原生运行；状态查询不能创建或重启计算。"""
    from agno.workflow import Workflow

    editor._require_lineage_feature('panel')
    context = await editor._restore(expected)
    task = await read_task_by_id(editor, context, task_id)
    if task is None or task.request.operation not in {'refresh_data', 'adopt_policy'}:
        raise ReportingError('report_editor_recalculation_unavailable', '后台重算必须先登记可信请求。')
    workflow_id = ('report-editor-policy-adoption' if task.request.operation == 'adopt_policy'
        else 'report-editor-refresh')
    workflow = Workflow(id=workflow_id, db=database)
    session = await workflow.aget_session(session_id='report-editor-' + task_id,
        user_id=context.scope['userId'])
    if not queue_only and session and session.runs:
        inputs = recalculation_run_input(context, task)
        if (len(session.runs) != 1 or session.runs[0].input != inputs
                or session.workflow_id != workflow_id
                or session.runs[0].workflow_id != workflow_id
                or session.runs[0].session_id != session.session_id
                or session.runs[0].user_id != context.scope['userId']):
            raise ReportingError('report_editor_scope_mismatch', '后台重算运行与已登记请求不一致。')
        return session.runs[0]
    if editor.recalculation_durable:
        from agno.os.job_queue import resolve_queue_store, ticket_status_to_api
        from agno.run.base import RunStatus
        from agno.run.workflow import WorkflowRunOutput

        worker = editor.recalculation_queue_worker
        store = worker.store if worker else resolve_queue_store(recalculation_queue_config(), database)
        job = await store.get_job(recalculation_queue_run_id(task))
        if job is not None:
            if (job.get('id') != recalculation_queue_run_id(task) or job.get('job_type', 'run') != 'run'
                    or job.get('deployment_id') != recalculation_queue_config().deployment_id
                    or job.get('component_type') != 'workflow' or job.get('component_id') != workflow.id
                    or job.get('session_id') != 'report-editor-' + task_id
                    or job.get('user_id') != context.scope['userId']
                    or (job.get('payload') or {}).get('input') != recalculation_run_input(context, task)):
                raise ReportingError('report_editor_scope_mismatch', '后台重算票据与已登记请求不一致。')
            status = ticket_status_to_api(job.get('status', ''))
            if status is None:
                raise ReportingError('report_editor_recalculation_unavailable', '后台重算票据状态无法读取。')
            return WorkflowRunOutput(run_id=job['id'], session_id=job['session_id'],
                user_id=job['user_id'], workflow_id=workflow.id, input=recalculation_run_input(context, task),
                status=RunStatus(status))
    return None


async def task_response(editor, context, task):
    """原生执行状态与交付完成记录分开表达；查询失败不改写耐久任务。"""
    result = task.model_dump(mode='json', by_alias=True)
    if task.request.operation not in {'refresh_data', 'adopt_policy'}:
        return result
    prefix = 'policy_adoption' if task.request.operation == 'adopt_policy' else 'refresh'
    database = editor.recalculation_database
    status, run_id, issues = 'unavailable', None, []
    if database is None:
        issues.append(prefix + '_status_backend_unavailable')
    else:
        try:
            run = await read_recalculation_run(editor, context, task.task_id, database=database)
            if run is None:
                status = 'not_dispatched'
            else:
                run_id = run.run_id
                status = str(getattr(run.status, 'value', run.status)).lower()
                if status not in {'pending', 'running', 'completed', 'error', 'cancelled', 'paused'}:
                    status = 'unknown'
                if status == 'completed' and task.status != 'completed':
                    issues.append(prefix + '_completion_record_unavailable')
                elif status in {'error', 'cancelled', 'paused', 'unknown'}:
                    issues.append(prefix + '_execution_' + status)
        except ReportingError:
            raise
        except Exception as error:
            logger.warning('recalculation_status_unavailable operation={} error_type={}',
                task.request.operation, type(error).__name__)
            issues.append(prefix + '_status_unavailable')
    result['execution'] = {'runId': run_id, 'status': status, 'issueCodes': issues}
    return result


def recalculation_run_input(context, task):
    return {'reportRunId': context.workflow_run_id, 'revision': context.revision,
        'taskId': task.task_id, 'inputHash': task.input_hash, 'contextSha256': context.digest()}


def recalculation_queue_run_id(task):
    from uuid import NAMESPACE_URL, uuid5

    component_id = ('report-editor-policy-adoption' if task.request.operation == 'adopt_policy'
        else 'report-editor-refresh')
    return str(uuid5(NAMESPACE_URL, component_id + ':' + task.task_id))


def recalculation_queue_config():
    from agno.job_queue import QueueConfig

    # 两种重算复用现有部署队列，component_id区分执行器；单次尝试禁止自动重查。
    return QueueConfig(durable=True, max_attempts=1, deployment_id='report-editor-refresh')


def create_refresh_workflow(editor, *, runtime, database):
    """创建可重建的原生工作流；请求身份仅从耐久记录恢复，不闭包绑定单个请求。"""
    from agno.workflow import Step, Workflow
    from agno.workflow.types import StepOutput

    from .service import ReportEditorContext

    async def execute(step_input, run_context):
        inputs = step_input.input
        if (not isinstance(inputs, dict) or set(inputs) != {
                'reportRunId', 'revision', 'taskId', 'inputHash', 'contextSha256'}
                or not isinstance(inputs['reportRunId'], str)
                or type(inputs['revision']) is not int):
            raise ReportingError('report_editor_scope_mismatch', '后台刷新输入身份无效。')
        state = await editor.state_repository.get(inputs['reportRunId'])
        raw = state.payload.get('reportEditorContexts', {}).get(str(inputs['revision'])) if state else None
        if raw is None:
            raise ReportingError('report_editor_scope_mismatch', '后台刷新缺少已登记报告上下文。')
        context = await editor._restore(ReportEditorContext.model_validate(raw))
        task = await read_task_by_id(editor, context, inputs['taskId'])
        if (context.workflow_run_id != inputs['reportRunId'] or task is None
                or task.request.operation != 'refresh_data' or recalculation_run_input(context, task) != inputs
                or run_context.user_id != context.scope['userId']
                or run_context.session_id != 'report-editor-' + task.task_id):
            raise ReportingError('report_editor_scope_mismatch', '后台刷新输入与已登记请求不一致。')
        completed, _ = await run_refresh_request(editor, context, task.task_id, runtime=runtime)
        return StepOutput(content=completed.model_dump(mode='json', by_alias=True))

    # 队列单次执行不能关闭Step默认重试；交付结果未知时必须先核对原运行。
    return Workflow(id='report-editor-refresh', name='报告数据刷新', db=database,
        steps=[Step(name='refresh-delivery', executor=execute, max_retries=0)])


def create_policy_adoption_workflow(editor, *, runtime, database):
    """重建采用新口径的原生工作流，仅执行已冻结的明确确认。"""
    from agno.workflow import Step, Workflow
    from agno.workflow.types import StepOutput

    from .service import ReportEditorContext

    async def execute(step_input, run_context):
        inputs = step_input.input
        if (not isinstance(inputs, dict) or set(inputs) != {
                'reportRunId', 'revision', 'taskId', 'inputHash', 'contextSha256'}
                or not isinstance(inputs['reportRunId'], str)
                or type(inputs['revision']) is not int):
            raise ReportingError('report_editor_scope_mismatch', '新口径后台输入身份无效。')
        state = await editor.state_repository.get(inputs['reportRunId'])
        raw = state.payload.get('reportEditorContexts', {}).get(str(inputs['revision'])) if state else None
        if raw is None:
            raise ReportingError('report_editor_scope_mismatch', '新口径后台缺少已登记报告上下文。')
        context = await editor._restore(ReportEditorContext.model_validate(raw))
        task = await read_task_by_id(editor, context, inputs['taskId'])
        if (context.workflow_run_id != inputs['reportRunId'] or task is None
                or not isinstance(task.request, PolicyAdoptionRequest) or recalculation_run_input(context, task) != inputs
                or run_context.user_id != context.scope['userId']
                or run_context.session_id != 'report-editor-' + task.task_id):
            raise ReportingError('report_editor_scope_mismatch', '新口径后台输入与已确认请求不一致。')
        completed, _ = await run_policy_adoption_request(editor, context, task.task_id, runtime=runtime)
        return StepOutput(content=completed.model_dump(mode='json', by_alias=True))

    return Workflow(id='report-editor-policy-adoption', name='报告采用新口径', db=database,
        steps=[Step(name='policy-adoption-delivery', executor=execute, max_retries=0)])


async def dispatch_recalculation_request(editor, expected, task_id, *, runtime, database):
    """委托Agno原生后台Workflow；同一持久请求只认已登记的原生运行，不自动重启。"""
    editor._require_lineage_feature('panel')
    context = await editor._restore(expected)
    task = await read_task_by_id(editor, context, task_id)
    if task is None or task.request.operation not in {'refresh_data', 'adopt_policy'}:
        raise ReportingError('report_editor_recalculation_unavailable', '后台重算必须先登记可信请求。')
    factory = create_policy_adoption_workflow if task.request.operation == 'adopt_policy' else create_refresh_workflow
    workflow = factory(editor, runtime=runtime, database=database)
    session_id = 'report-editor-' + task_id
    inputs = recalculation_run_input(context, task)
    # 状态读回不能等待执行器持有的来源锁；首次派发在锁内再次核对，避免重复启动。
    existing = await read_recalculation_run(editor, context, task_id, database=database)
    if existing is not None:
        return existing
    async with source_lifecycle_lock(editor, context, exclusive=True):
        existing = await read_recalculation_run(editor, context, task_id, database=database)
        if existing is not None:
            return existing
        task = await read_task_by_id(editor, context, task_id)
        if task.status != 'pending':
            raise ReportingError('report_editor_recalculation_unavailable', '任务已有终态，不自动创建新的后台执行。')
        if editor.recalculation_durable:
            from agno.db.schemas.jobs import QueuedJob
            from agno.os.job_queue import aprepare_accepted_or_abort

            worker = editor.recalculation_queue_worker
            if worker is None:
                raise ReportingError('report_editor_recalculation_unavailable', '后台重算队列尚未就绪。')
            run_id = recalculation_queue_run_id(task)
            accepted = await worker.store.enqueue_job(QueuedJob(id=run_id, component_type='workflow',
                component_id=workflow.id, session_id=session_id, user_id=context.scope['userId'],
                payload={'input': inputs, 'stream': False}, max_attempts=1,
                deployment_id=worker.config.deployment_id,
                idempotency_key=run_id).to_dict(), max_depth=worker.config.max_queue_depth)
            if not accepted['accepted'] and accepted.get('reason') != 'duplicate':
                raise ReportingError('report_editor_recalculation_unavailable', '后台重算队列未接受请求，请先读取原任务状态。')
            if accepted['accepted']:
                await aprepare_accepted_or_abort(worker, workflow, 'workflow', run_id, session_id,
                    context.scope['userId'], inputs)
            return await read_recalculation_run(editor, context, task_id, database=database)
        return await workflow.arun(input=inputs, session_id=session_id, user_id=context.scope['userId'],
            background=True, stream=False)

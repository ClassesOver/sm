"""正式 workbook/slides 保存稿到共享耐久刷新协议的薄桥。"""
from types import SimpleNamespace

from loguru import logger
from pydantic import Field

from ..reporting.contract import SHA256_PATTERN, StrictModel
from ..reporting.models import ReportingError
from ..reporting.saved_revision_reference import OfficeReportSource, OfficeRevisionSelection
from ..reporting.workflow.revision_execution import _source_state
from ..reporting.workflow.scope import resolve_reporting_workflow_scope
from ._file_identity import read_verified_file
from .recalculation import (
    BinaryRecalculationRequest,
    RefreshDeliveryRecovery,
    dispatch_recalculation_request,
    read_refresh_delivery,
    read_registered_recalculation_execution,
    read_task,
    read_task_by_id,
    register_refresh_request,
    request_hash,
    resolve_refresh_parent,
    task_identity,
    task_response,
)
from .service import ReportEditorContext


def require_backend(editor):
    runtime = editor.recalculation_runtime
    if (not editor.recalculation_durable or runtime is None or editor.recalculation_database is None
            or getattr(runtime, 'configuration_provider', None) is None
            or getattr(editor.recalculation_queue_worker, 'store', None) is None):
        raise ReportingError('report_editor_recalculation_unavailable', '正式刷新耐久后台尚未启用。')
    editor._require_lineage_feature('panel')
    return runtime


class OfficeRefreshRequest(StrictModel):
    request_id: str = Field(alias='requestId', min_length=1, max_length=128, pattern=r'^[A-Za-z0-9_-]+$')
    expected_binary_sha256: str = Field(alias='expectedBinarySha256', pattern=SHA256_PATTERN)


def source_pointer(context):
    return OfficeReportSource(workflowRunId=context.workflow_run_id, reportId=context.report_id,
        revision=context.revision, contextSha256=context.digest())


def office_selection(context, source):
    return OfficeRevisionSelection(editor='workbook' if context.delivery_format == 'xlsx' else 'slides',
        revision=context.revision, contextSha256=context.digest(), format=context.delivery_format,
        calculationSource=source_pointer(source))


def registered_office_source(state, context):
    """只读取精确耐久身份；旧无指针只能按继承的可信标识唯一恢复。"""
    if context.delivery_format not in {'xlsx', 'pptx'}:
        raise ReportingError('office_refresh_source_unavailable', '此文件没有正式 Office 来源。')
    raw_contexts = state.payload.get('reportEditorContexts', {}) if state else {}
    pointer = context.job.get('officeRefreshSource')
    if pointer is not None:
        try:
            pointer = OfficeReportSource.model_validate(pointer)
            source = ReportEditorContext.model_validate(raw_contexts.get(str(pointer.revision)))
        except (ValueError, TypeError) as error:
            raise ReportingError('office_refresh_source_unavailable', '正式计算来源指针无法核验。') from error
        candidates = [source] if source_pointer(source) == pointer else []
    elif context.source == 'published':
        candidates = [context]
    else:
        candidates = []
        # 旧保存稿没有新字段时，路径/序号本身不构成可信来源，须有既存完整身份标识。
        if context.artifact_manifest is not None or context.analysis_context_file is not None:
            for raw in raw_contexts.values():
                try:
                    candidate = ReportEditorContext.model_validate(raw)
                except (ValueError, TypeError):
                    continue
                if (candidate.source == 'published' and candidate.markdown_path == context.markdown_path
                        and candidate.job_id == context.job_id
                        and candidate.artifact_manifest == context.artifact_manifest
                        and candidate.analysis_context_file == context.analysis_context_file):
                    candidates.append(candidate)
    if len(candidates) != 1:
        raise ReportingError('office_refresh_source_unavailable', '无法唯一精确恢复正式来源；保存及可信下载仍可使用。')
    source = candidates[0]
    if (source.source != 'published' or source.workflow_run_id != context.workflow_run_id
            or source.report_id != context.report_id or source.scope != context.scope
            or source.delivery_format != context.delivery_format or source.job_id != context.job_id
            or source.markdown_path != context.markdown_path
            or source.analysis_context_file != context.analysis_context_file
            or (context.artifact_manifest is not None and source.artifact_manifest != context.artifact_manifest)):
        raise ReportingError('report_editor_scope_mismatch', 'Office 正式来源与当前保存稿或授权范围不一致。')
    return source


async def restore_office_source(editor, context):
    if editor is None:
        raise ReportingError('report_editor_recalculation_unavailable', '正式刷新后台尚未装配。')
    context = await editor._restore(context)
    state = await editor.state_repository.get(context.workflow_run_id)
    source = registered_office_source(state, context)
    source = await editor._restore(source)
    scope = resolve_reporting_workflow_scope(run_id=source.workflow_run_id,
        session_id=source.scope['sessionId'], user_id=source.scope['userId'], stored_scope=source.scope)
    _, registered = await _source_state(SimpleNamespace(state_repository=editor.state_repository), scope)
    require_office_run(scope, registered)
    return source


def require_office_run(scope, registered):
    expected = {'report_run_id': scope.run_id, 'external_run_id': scope.external_run_id,
        'agno_run_id': scope.run_id, 'agno_session_id': scope.session_id,
        'thread_id': scope.caller_thread_id, 'owner_user_id': scope.user_id}
    if any(registered.get(key) != value for key, value in expected.items()):
        raise ReportingError('report_editor_scope_mismatch', '正式来源耐久运行登记与完整授权身份不一致。')


async def saved_source_pointer(office, context, issues):
    """来源登记不可用仅关闭正式分析，不阻断手工保存或可信文件签发。"""
    if office.report_editor is None:
        return None
    try:
        source = await restore_office_source(office.report_editor, context)
        return source_pointer(source).model_dump(mode='json', by_alias=True)
    except Exception as error:
        logger.warning('office_refresh_save_source_unavailable error_type={}', type(error).__name__)
        issues.append({'code': 'office_refresh_source_unavailable',
            'message': '正式计算来源暂不可核验；本次保存文件仍可下载，不能据人工改值发起正式分析。'})
        return None


async def office_refresh_capability(office, context, *, verify_file=True):
    try:
        source = await restore_office_source(office.report_editor, context)
        runtime = require_backend(office.report_editor)
        await office.report_editor._ensure_sources_retained(context)
        await office.report_editor._ensure_sources_retained(source)
        if verify_file:
            await resolve_refresh_parent(office.report_editor, source,
                vault=runtime.configuration_provider.vault, exact_source=True)
            await read_binary(office, context)
        elif not await office.workspace.apath_exists(context.scope['threadId'], binary_identity(context)[0]):
            raise ReportingError('office_refresh_source_missing', 'Office 来源已删除，当前任务仅从冻结参考恢复。')
        return {'available': True, 'parentRevision': context.revision}
    except Exception as error:
        logger.warning('office_refresh_capability_unavailable error_type={}', type(error).__name__)
        return {'available': False, 'parentRevision': context.revision,
            'reason': error.code if isinstance(error, ReportingError) else 'office_refresh_source_unavailable',
            'message': error.message if isinstance(error, ReportingError) else '正式刷新来源暂不可核验，已有可信文件仍可下载。'}


def binary_identity(context):
    return tuple(getattr(context, context.delivery_format + '_' + key) for key in ('path', 'size', 'sha256'))


async def read_binary(office, context):
    path, size, sha256 = binary_identity(context)
    return await read_verified_file(office.workspace, context.scope, path, size=size, sha256=sha256,
        error_code='report_editor_conflict', format_name=context.delivery_format)


async def start_office_refresh(office, context, request):
    editor = office.report_editor
    source = await restore_office_source(editor, context)
    runtime = require_backend(editor)
    if request.expected_binary_sha256 != binary_identity(context)[2]:
        raise ReportingError('report_editor_conflict', 'Office 保存稿已变化，请核对当前修订。')
    internal = BinaryRecalculationRequest(requestId=request.request_id, parentRevision=context.revision,
        expectedBinarySha256=request.expected_binary_sha256, officeSource=office_selection(context, source))
    previous = await read_task(editor, context, request.request_id)
    if previous is not None:
        require_office_reference(context, source, previous.saved_revision_reference)
        if previous.input_hash != request_hash(context, internal, previous.saved_revision_reference):
            raise ReportingError('report_editor_conflict', '同一刷新请求已绑定其他 Office 保存稿。')
        if previous.status == 'pending':
            await dispatch_recalculation_request(editor, context, previous.task_id, runtime=runtime,
                database=editor.recalculation_database)
        return await task_response(editor, context, previous)
    await editor._ensure_sources_retained(context)
    await editor._ensure_sources_retained(source)
    task = await register_refresh_request(editor, context, internal,
        vault=runtime.configuration_provider.vault, binary_content=await read_binary(office, context))
    await dispatch_recalculation_request(editor, context, task.task_id, runtime=runtime,
        database=editor.recalculation_database)
    return await task_response(editor, context, task)


def require_office_reference(context, source, reference):
    if (reference is None or reference.office_source != office_selection(context, source)
            or reference.native_source is not None or reference.file.size != binary_identity(context)[1]
            or reference.file.sha256 != binary_identity(context)[2]):
        raise ReportingError('report_editor_scope_mismatch', '刷新任务不属于当前 Office 保存稿、来源或修订。')


async def selected_office_task(office, context, source, *, task_id=None, request_id=None):
    editor = office.report_editor
    task_id = task_id or task_identity(context, request_id)
    try:
        task = await read_task_by_id(editor, context, task_id)
    except (ValueError, ReportingError):
        task = None
    if task is not None:
        require_office_reference(context, source, task.saved_revision_reference)
        return task
    execution = await read_registered_recalculation_execution(editor, context, task_id)
    binding = execution.saved_revision_binding
    require_office_reference(context, source, binding.reference if binding is not None else None)
    if execution.requested_outputs != (context.delivery_format,):
        raise ReportingError('report_editor_scope_mismatch', '刷新交付目标与当前 Office 格式不一致。')
    return RefreshDeliveryRecovery(taskId=task_id, reportId=context.report_id)


async def office_refresh_status(office, context, *, task_id=None, request_id=None):
    source = await restore_office_source(office.report_editor, context)
    task = await selected_office_task(office, context, source, task_id=task_id, request_id=request_id)
    input_unavailable = isinstance(task, RefreshDeliveryRecovery)
    if not input_unavailable:
        try:
            ref = task.saved_revision_reference
            await read_verified_file(office.workspace, context.scope, ref.file.path, size=ref.file.size,
                sha256=ref.file.sha256, error_code='report_editor_conflict', format_name=ref.format)
        except Exception as error:
            logger.warning('office_refresh_frozen_input_unavailable error_type={}', type(error).__name__)
            input_unavailable = True
    if input_unavailable:
        if office.report_editor.recalculation_runtime is None:
            raise ReportingError('report_editor_recalculation_unavailable', '交付读取后台尚未启用。')
        await read_refresh_delivery(office.report_editor, context, task.task_id,
            runtime=office.report_editor.recalculation_runtime)
        result = RefreshDeliveryRecovery(taskId=task.task_id, reportId=context.report_id).model_dump(mode='json', by_alias=True)
    else:
        result = await task_response(office.report_editor, context, task)
    capability = await office_refresh_capability(office, context, verify_file=False)
    return {**result, 'sourceReusable': capability['available'],
        **({'sourceIssue': capability['reason']} if not capability['available'] else {})}


async def office_refresh_delivery(office, context, task_id):
    source = await restore_office_source(office.report_editor, context)
    await selected_office_task(office, context, source, task_id=task_id)
    result = await office.report_editor.recalculation_delivery(context, task_id)
    issues = result['delivery'].get('validation', {}).get('issues', ())
    if any(issue.get('code') in {'saved_revision_reference_unavailable', 'refresh_task_input_unverified'} for issue in issues):
        result['task'] = RefreshDeliveryRecovery(taskId=task_id, reportId=context.report_id).model_dump(mode='json', by_alias=True)
    return result

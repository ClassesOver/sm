"""正式报告 native 保存稿到既有耐久刷新控制器的薄桥。"""
from types import SimpleNamespace

from loguru import logger
from pydantic import Field

from ..reporting.contract import SHA256_PATTERN, StrictModel
from ..reporting.models import ReportingError
from ..reporting.saved_revision_reference import NativeRevisionSelection
from ..reporting.workflow.revision_execution import _source_state
from ..reporting.workflow.scope import resolve_reporting_workflow_scope
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
    task_response,
)
from .service import ReportEditorContext


class NativeRefreshRequest(StrictModel):
    request_id: str = Field(alias='requestId', min_length=1, max_length=128, pattern=r'^[A-Za-z0-9_-]+$')
    expected_binary_sha256: str = Field(alias='expectedBinarySha256', pattern=SHA256_PATTERN)


def selection(context):
    return NativeRevisionSelection(documentId=context.document_id, revision=context.revision,
        contextSha256=context.digest(), format=context.format)


async def restore_report_source(native, context):
    """状态/下载只核耐久来源登记，不读取可变 native 或历史 MD 字节。"""
    editor = native.report_editor
    if editor is None or context.format not in {'pdf', 'docx'} or context.origin != 'report':
        raise ReportingError('report_editor_recalculation_unavailable', '此文件没有可恢复的正式报告来源。')
    revision = await native.repository.get_revision(context.document_id, context.revision, scope=context.scope)
    document = await native.repository.get_document(context.document_id, scope=context.scope)
    if (revision is None or revision.status != 'saved' or revision.context != context
            or document is None or document.document_id != context.document_id or document.scope != context.scope
            or document.source.origin != 'report' or document.source.format != context.format):
        raise ReportingError('report_editor_scope_mismatch', '原生修订或报告来源身份不一致。')
    source = document.source
    if source.report_context_sha256 is None:
        raise ReportingError('native_refresh_source_binding_missing',
            '此旧原生分支缺少原报告上下文绑定，请从原报告重新打开可信原生分支后刷新；已有保存和下载不受影响。')
    state = await editor.state_repository.get(source.workflow_run_id)
    try:
        report = ReportEditorContext.model_validate(state.payload.get('reportEditorContexts', {}).get(str(source.revision)))
    except (AttributeError, ValueError, TypeError) as error:
        raise ReportingError('report_editor_scope_mismatch', '原报告上下文无法精确恢复。') from error
    if (report.workflow_run_id != source.workflow_run_id or report.report_id != source.report_id
            or report.revision != source.revision or source.report_context_sha256 != report.digest()
            or any(report.scope.get(key) != value for key, value in context.scope.model_dump(by_alias=True).items())
            or report.delivery_format not in {'document', context.format}):
        raise ReportingError('report_editor_scope_mismatch', '原报告上下文与原生来源或授权范围不一致。')
    report = await editor._restore(report)
    scope = resolve_reporting_workflow_scope(run_id=report.workflow_run_id,
        session_id=report.scope['sessionId'], user_id=report.scope['userId'], stored_scope=report.scope)
    _, registered = await _source_state(SimpleNamespace(state_repository=editor.state_repository), scope)
    expected = {'report_run_id': scope.run_id, 'external_run_id': scope.external_run_id,
        'agno_run_id': scope.run_id, 'agno_session_id': scope.session_id,
        'thread_id': scope.caller_thread_id, 'owner_user_id': scope.user_id}
    if any(registered.get(key) != value for key, value in expected.items()):
        raise ReportingError('report_editor_scope_mismatch', '原报告耐久运行登记与完整授权身份不一致。')
    return report


def require_backend(editor):
    runtime = editor.recalculation_runtime
    if (not editor.recalculation_durable or runtime is None or editor.recalculation_database is None
            or getattr(runtime, 'configuration_provider', None) is None
            or getattr(editor.recalculation_queue_worker, 'store', None) is None):
        raise ReportingError('report_editor_recalculation_unavailable', '正式刷新耐久后台尚未启用。')
    editor._require_lineage_feature('panel')
    return runtime


async def native_refresh_capability(native, context, *, verify_file=True):
    try:
        report = await restore_report_source(native, context)
        runtime = require_backend(native.report_editor)
        await native.report_editor._ensure_sources_retained(report)
        if verify_file:
            await resolve_refresh_parent(native.report_editor, report,
                vault=runtime.configuration_provider.vault, exact_source=True)
            await native.read_file(context)
        else:
            from .native import bind_native_workspace
            key = bind_native_workspace(native.workspace, context.scope)
            if not await native.workspace.apath_exists(key, context.source_file.path):
                raise ReportingError('native_source_missing', '原生来源已删除，当前任务仅从冻结参考恢复。')
        return {'available': True, 'parentRevision': context.revision}
    except Exception as error:
        logger.warning('native_refresh_capability_unavailable error_type={}', type(error).__name__)
        return {'available': False, 'parentRevision': context.revision,
            'reason': error.code if isinstance(error, ReportingError) else 'native_refresh_source_unavailable',
            'message': error.message if isinstance(error, ReportingError) else '正式刷新来源暂不可核验，已有文件仍可下载。'}


async def start_native_refresh(native, context, request):
    report = await restore_report_source(native, context)
    editor = native.report_editor
    runtime = require_backend(editor)
    if request.expected_binary_sha256 != context.source_file.sha256:
        raise ReportingError('report_editor_conflict', '原生保存稿已变化，请核对当前修订。')
    internal = BinaryRecalculationRequest(requestId=request.request_id, parentRevision=report.revision,
        expectedBinarySha256=request.expected_binary_sha256, nativeSource=selection(context))
    previous = await read_task(editor, report, request.request_id)
    if previous is not None:
        if previous.input_hash != request_hash(report, internal, previous.saved_revision_reference):
            raise ReportingError('report_editor_conflict', '同一刷新请求已绑定其他原生保存稿。')
        if previous.status == 'pending':
            await dispatch_recalculation_request(editor, report, previous.task_id, runtime=runtime,
                database=editor.recalculation_database)
        return await task_response(editor, report, previous)
    await editor._ensure_sources_retained(report)
    raw = await native.read_file(context)
    task = await register_refresh_request(editor, report, internal,
        vault=runtime.configuration_provider.vault, binary_content=raw)
    await dispatch_recalculation_request(editor, report, task.task_id, runtime=runtime,
        database=editor.recalculation_database)
    return await task_response(editor, report, task)


def require_native_reference(context, reference):
    if (reference is None or reference.native_source != selection(context)
            or reference.file.sha256 != context.source_file.sha256 or reference.file.size != context.source_file.size):
        raise ReportingError('report_editor_scope_mismatch', '刷新任务不属于当前原生文档、分支或保存修订。')


async def selected_task(native, context, report, *, task_id=None, request_id=None):
    editor = native.report_editor
    if task_id is None:
        from .recalculation import task_identity
        task_id = task_identity(report, request_id)
    try:
        task = await read_task_by_id(editor, report, task_id)
    except (ValueError, ReportingError):
        task = None
    if task is not None:
        require_native_reference(context, task.saved_revision_reference)
        return task
    execution = await read_registered_recalculation_execution(editor, report, task_id)
    binding = execution.saved_revision_binding
    require_native_reference(context, binding.reference if binding is not None else None)
    if execution.requested_outputs != (context.format,):
        raise ReportingError('report_editor_scope_mismatch', '刷新交付目标与当前原生格式不一致。')
    return RefreshDeliveryRecovery(taskId=task_id, reportId=report.report_id)


async def native_refresh_status(native, context, *, task_id=None, request_id=None):
    report = await restore_report_source(native, context)
    task = await selected_task(native, context, report, task_id=task_id, request_id=request_id)
    input_unavailable = isinstance(task, RefreshDeliveryRecovery)
    if not input_unavailable:
        from ._file_identity import read_verified_file
        try:
            reference = task.saved_revision_reference
            await read_verified_file(native.report_editor.workspace, report.scope, reference.file.path,
                size=reference.file.size, sha256=reference.file.sha256,
                error_code='report_editor_conflict', format_name=reference.format)
        except Exception as error:
            logger.warning('native_refresh_frozen_input_unavailable error_type={}', type(error).__name__)
            input_unavailable = True
    if input_unavailable:
        if native.report_editor.recalculation_runtime is None:
            raise ReportingError('report_editor_recalculation_unavailable', '交付读取后台尚未启用。')
        await read_refresh_delivery(native.report_editor, report, task.task_id,
            runtime=native.report_editor.recalculation_runtime)
        result = RefreshDeliveryRecovery(taskId=task.task_id, reportId=report.report_id).model_dump(mode='json', by_alias=True)
    else:
        result = await task_response(native.report_editor, report, task)
    capability = await native_refresh_capability(native, context, verify_file=False)
    return {**result, 'sourceReusable': capability['available'],
        **({'sourceIssue': capability['reason']} if not capability['available'] else {})}


async def native_refresh_delivery(native, context, task_id):
    report = await restore_report_source(native, context)
    await selected_task(native, context, report, task_id=task_id)
    result = await native.report_editor.recalculation_delivery(report, task_id)
    issues = result['delivery'].get('validation', {}).get('issues', ())
    if any(issue.get('code') in {'saved_revision_reference_unavailable', 'refresh_task_input_unverified'} for issue in issues):
        result['task'] = RefreshDeliveryRecovery(taskId=task_id, reportId=report.report_id).model_dump(mode='json', by_alias=True)
    return result

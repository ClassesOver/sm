"""已登记分析修订的独立原生状态；不创建另一套任务或检查点平台。"""

from typing import Literal

from pydantic import Field, model_serializer, model_validator

from ..contract import SHA256_PATTERN, StrictModel
from ..models import ReportingError
from ..saved_revision_reference import SavedRevisionExecutionBinding
from ..semantics.basis import BasisRefreshRevisionReceipt
from ..semantics.models import Identity, RunIdentity
from ..trace.contracts_v1 import canonical_sha256
from .scope import ReportingWorkflowScope, resolve_reporting_workflow_scope
from .state import ReportingCommand


def execution_run_id(scope, basis_id, report_revision, planning_hash):
    return 'revision-execution-' + canonical_sha256({'sourceRunId': scope.run_id,
        'basisId': basis_id, 'reportRevision': report_revision, 'planningHash': planning_hash})


class ReportRevisionExecution(StrictModel):
    saved_revision_binding: SavedRevisionExecutionBinding | None = Field(default=None, alias='savedRevisionBinding')
    source_scope: ReportingWorkflowScope = Field(alias='sourceScope')
    execution_run_id: RunIdentity = Field(alias='executionRunId')
    basis_id: Identity = Field(alias='basisId')
    report_revision: RunIdentity = Field(alias='reportRevision')
    parent_report_revision: RunIdentity = Field(alias='parentReportRevision')
    planning_hash: str = Field(alias='planningHash', pattern=SHA256_PATTERN)
    output_revision: int = Field(alias='outputRevision', ge=2)
    requested_outputs: tuple[Literal['md', 'pdf', 'docx', 'pptx', 'xlsx'], ...] = Field(
        alias='requestedOutputs', min_length=1, max_length=5)

    @model_serializer(mode='wrap')
    def legacy_serialization(self, handler):
        payload = handler(self)
        if self.saved_revision_binding is None:
            payload.pop('savedRevisionBinding', None)
            payload.pop('saved_revision_binding', None)
        return payload

    @model_validator(mode='after')
    def identity(self):
        if (len(set(self.requested_outputs)) != len(self.requested_outputs)
                or self.report_revision == self.parent_report_revision
                or self.execution_run_id != execution_run_id(self.source_scope, self.basis_id,
                    self.report_revision, self.planning_hash)):
            raise ValueError('新修订执行必须绑定独立状态及精确分析身份')
        if (self.saved_revision_binding is not None and self.saved_revision_binding.reference.source != 'markdown_editor'
                and self.requested_outputs != (self.saved_revision_binding.reference.format,)):
            raise ValueError('原生保存稿刷新必须绑定当前唯一二进制目标格式')
        return self


def _source_scope(runtime, run_context):
    scope = runtime._scope(run_context)
    return resolve_reporting_workflow_scope(run_id=str(run_context.run_id), session_id=scope['sessionId'],
        user_id=scope['userId'], stored_scope=scope)


async def _source_state(runtime, scope):
    state = await runtime.state_repository.get(scope.run_id)
    registered = await runtime.state_repository.get_run(scope.run_id)
    if (state is None or registered is None
            or (state.external_run_id, state.thread_id, state.owner_user_id) != (
                scope.external_run_id, scope.caller_thread_id, scope.user_id)
            or (registered['database'], registered['company_id']) != (scope.database, scope.company_id)):
        raise ReportingError('report_revision_execution_mismatch', '新修订来源与可信报告运行不一致。')
    return state, registered


async def load_revision_materials(runtime, scope, source):
    """只从原运行耐久登记恢复材料；兼容旧报告已登记的分析上下文。"""
    import json

    from ..contract import ReportFileInput
    from .checkpoint import FileIdentity

    materials = source.payload.get('requestMaterials')
    if materials is None:
        path = f'报表/分析计划/{scope.run_id}/detailed-analysis-context.json'
        candidate = next((item for item in source.payload.get('workflowCheckpoint', {}).get('files', ())
            if item.get('path') == path), None)
        materials = {'fileInputs': [], 'templateInput': None}
        if candidate is not None:
            try:
                file = FileIdentity.model_validate(candidate)
                context = json.loads(await runtime._read_identity_bytes(scope.workspace_key, file, max_bytes=file.size))
                materials['templateInput'] = (context.get('templateInput') or {}).get('identity')
            except Exception as error:
                raise ReportingError('report_revision_materials_unavailable', '原运行冻结材料身份无法核验。') from error
    try:
        return {'fileInputs': [ReportFileInput.model_validate(item).model_dump(mode='json', by_alias=True)
                for item in materials.get('fileInputs', ())],
            'templateInput': ReportFileInput.model_validate(materials['templateInput']).model_dump(mode='json', by_alias=True)
                if materials.get('templateInput') else None}
    except (TypeError, ValueError, AttributeError) as error:
        raise ReportingError('report_revision_materials_unavailable', '原运行冻结材料登记无效。') from error


async def copy_revision_materials(runtime, source_scope, target_scope, materials):
    """新口径工作区只复制授权的冻结材料，保留文件身份与相对位置。"""
    from ...workspace import WorkspaceError
    from .checkpoint import FileIdentity

    for item in (*materials['fileInputs'], *((materials['templateInput'],) if materials['templateInput'] else ())):
        file = FileIdentity.model_validate({key: item[key] for key in ('path', 'size', 'sha256')})
        try:
            await runtime._read_identity_bytes(target_scope.workspace_key, file, max_bytes=file.size)
            continue
        except (FileNotFoundError, KeyError):
            pass
        except WorkspaceError as error:
            if not isinstance(error.__cause__, FileNotFoundError):
                raise
        raw = await runtime._read_identity_bytes(source_scope.workspace_key, file, max_bytes=file.size)
        copied = await runtime._write_immutable_artifact(target_scope.workspace_key, file.path, raw)
        if copied != file:
            raise ReportingError('report_revision_materials_unavailable', '新工作区材料与授权来源身份不同。')
        await runtime._read_identity_bytes(target_scope.workspace_key, file, max_bytes=file.size)


async def prepare_revision_execution(runtime, run_context, *, report_revision, task=None):
    """实际CSV/清单验证后预留唯一交付编号，再登记独立Reporting状态，重复调用只恢复。"""
    from ...management.models import ManagementScope
    from ...report_editor.revisions import apply_editor_command

    scope = _source_scope(runtime, run_context)
    source, registered = await _source_state(runtime, scope)
    view = await runtime._metric_planning_context(run_context, report_revision=report_revision)
    receipts = await runtime.report_basis_service.load_basis_receipts(scope.run_id,
        ManagementScope(scope.database, scope.company_id), user_id=scope.user_id,
        thread_id=scope.caller_thread_id, report_revision=report_revision)
    manifests = tuple(item for item in receipts if isinstance(item, BasisRefreshRevisionReceipt))
    if len(manifests) != 1 or manifests[0].basis_id != view.basis_id:
        raise ReportingError('report_revision_execution_unavailable', '新执行需要完整登记的刷新分析清单。')
    manifest = manifests[0]
    materials = await load_revision_materials(runtime, scope, source)
    saved_binding = None
    if task is not None and task.saved_revision_reference is not None:
        from ..saved_revision_reference import read_saved_revision_reference
        saved_binding = SavedRevisionExecutionBinding(taskId=task.task_id, inputHash=task.input_hash,
            contextSha256=task.context_sha256, reference=task.saved_revision_reference)
        await _require_saved_revision_task(runtime, scope, source, saved_binding, report_revision)
        await read_saved_revision_reference(runtime, scope.workspace_key, saved_binding.reference)
    child_id = execution_run_id(scope, view.basis_id, report_revision, manifest.planning_hash)
    reservation = await apply_editor_command(runtime.state_repository, scope.run_id, ReportingCommand(
        name='reserve_report_editor_revision', commandId=child_id,
        payload={'minimumRevision': source.revision, 'reservationKey': child_id}))
    output_revision = reservation.state.payload['reportEditorRevisionReservations'][child_id]
    execution = ReportRevisionExecution(sourceScope=scope, executionRunId=child_id, basisId=view.basis_id,
        reportRevision=report_revision, parentReportRevision=manifest.parent_report_revision,
        planningHash=manifest.planning_hash, outputRevision=output_revision, requestedOutputs=((saved_binding.reference.format,) if saved_binding is not None
            and saved_binding.reference.source != 'markdown_editor' else view.request.requested_outputs),
        savedRevisionBinding=saved_binding)
    from ...preferences.runtime import inherit_execution_preferences

    await inherit_execution_preferences(runtime, scope, child_id, 'report_revision')
    await runtime.state_repository.register_run(report_run_id=child_id, external_run_id=child_id,
        entrypoint='report_revision', workflow_id=registered['workflow_id'], agno_session_id=child_id,
        agno_run_id=child_id, caller_session_id=scope.session_id, caller_run_id=scope.run_id,
        thread_id=scope.caller_thread_id, owner_user_id=scope.user_id, database=scope.database,
        company_id=scope.company_id, revision=output_revision, status='pending')
    await runtime.state_repository.get_or_create(report_run_id=child_id, external_run_id=child_id,
        thread_id=scope.caller_thread_id, owner_user_id=scope.user_id, revision=output_revision,
        payload={'reportRevisionExecution': execution.model_dump(mode='json', by_alias=True), 'requestMaterials': materials})
    await require_revision_execution(runtime, run_context, execution)
    return execution


async def _require_saved_revision_task(runtime, scope, source, binding, report_revision):
    """只核对耐久绑定；文件读取只在生成前做，不能成为完成文件下载门禁。"""
    from types import SimpleNamespace

    from ...report_editor.recalculation import read_task_by_id
    from ...report_editor.service import ReportEditorContext

    try:
        context = ReportEditorContext.model_validate(source.payload.get('reportEditorContexts', {}).get(
            str(binding.reference.revision)))
        task = await read_task_by_id(SimpleNamespace(state_repository=runtime.state_repository), context, binding.task_id)
        if (context.scope != scope.as_state() or context.workflow_run_id != scope.run_id or task is None
                or task.input_hash != binding.input_hash or task.context_sha256 != binding.context_sha256
                or task.saved_revision_reference != binding.reference or task.refresh_binding is None
                or task.refresh_binding.report_revision != report_revision):
            raise ValueError('父任务输入不一致')
        if binding.reference.office_source is not None:
            from ...report_editor.office_refresh import (
                office_selection,
                registered_office_source,
                require_office_run,
            )
            require_office_run(scope, await runtime.state_repository.get_run(scope.run_id))
            calculation_source = registered_office_source(source, context)
            if binding.reference.office_source != office_selection(context, calculation_source):
                raise ValueError('Office 正式计算来源与保存任务不一致')
            retired = source.payload.get('reportEditorRetiredSources', {})
            if (not isinstance(retired, dict) or str(context.revision) in retired
                    or str(calculation_source.revision) in retired):
                raise ReportingError('snapshot_expired', 'Office 正式计算来源已退休，不能用于新计算。')
    except (ValueError, TypeError, AttributeError, ReportingError) as error:
        raise ReportingError('report_revision_execution_mismatch', '保存参考与父任务、上下文或输入摘要不一致。') from error
    return task


def revision_delivery_paths(execution, child):
    """只认可本执行固定目录或既有模板哈希目录中的目标文件。"""
    import re

    execution_id = execution.execution_run_id if isinstance(execution, ReportRevisionExecution) else execution.scope.run_id
    root = f'报表/智能分析/{execution_id}'
    directories = {'md': 'document', 'pdf': 'document-render', 'docx': 'document-render',
        'pptx': 'slides', 'xlsx': 'workbook'}
    paths = {output: [f'{root}/{directories[output]}/revision-{execution.output_revision}/report.{output}']
        for output in execution.requested_outputs}
    if child.payload.get('requestMaterials', {}).get('templateInput'):
        for output in execution.requested_outputs:
            pattern = re.escape(f'{root}/template/revision-{execution.output_revision}/') + r'[0-9a-f]{20}/report\.' + output
            paths[output] = [item['path'] for item in child.payload.get('artifacts', ())
                if re.fullmatch(pattern, item.get('path', ''))]
    return paths


async def require_revision_execution(runtime, run_context, execution, *, report_revision=None, revision=None, restore_only=False):
    """会话自报身份不生效；每次写产物或检查点都核对已登记执行及原授权作用域。"""
    scope = _source_scope(runtime, run_context)
    source, _ = await _source_state(runtime, scope)
    child = await runtime.state_repository.get(execution.execution_run_id)
    registered = await runtime.state_repository.get_run(execution.execution_run_id)
    if (scope != execution.source_scope or child is None or registered is None
            or source.payload.get('reportEditorRevisionReservations', {}).get(execution.execution_run_id) != execution.output_revision
            or child.payload.get('reportRevisionExecution') != execution.model_dump(mode='json', by_alias=True)
            or (child.external_run_id, child.thread_id, child.owner_user_id, child.revision) != (
                execution.execution_run_id, scope.caller_thread_id, scope.user_id, execution.output_revision)
            or (registered['entrypoint'], registered['caller_run_id'], registered['caller_session_id'],
                registered['database'], registered['company_id']) != (
                    'report_revision', scope.run_id, scope.session_id, scope.database, scope.company_id)
            or report_revision is not None and execution.report_revision != report_revision
            or revision is not None and execution.output_revision != revision):
        raise ReportingError('report_revision_execution_mismatch', '产物或检查点与已登记新修订执行不一致。')
    if execution.saved_revision_binding is None and not restore_only:
        import re
        if re.fullmatch(r'editor-refresh-[0-9a-f]{32}', execution.report_revision):
            from types import SimpleNamespace

            from ...report_editor.recalculation import RecalculationTask, read_task_by_id
            from ...report_editor.service import ReportEditorContext
            task_id = 'recalc-' + execution.report_revision.removeprefix('editor-refresh-')
            try:
                registered_task = RecalculationTask.model_validate(source.payload.get('reportEditorRecalculations', {}).get(task_id))
                context = ReportEditorContext.model_validate(source.payload.get('reportEditorContexts', {}).get(
                    str(registered_task.request.parent_revision)))
                task = await read_task_by_id(SimpleNamespace(state_repository=runtime.state_repository), context, task_id)
                if (context.scope != scope.as_state() or context.workflow_run_id != scope.run_id
                        or task is None or task.saved_revision_reference is not None or task.refresh_binding is None
                        or task.refresh_binding.report_revision != execution.report_revision
                        or task.refresh_binding.parent_report_revision != execution.parent_report_revision
                        or task.basis_id != execution.basis_id):
                    raise ValueError('缺保存参考绑定的执行不是已登记旧任务')
            except (ValueError, TypeError, ReportingError) as error:
                raise ReportingError('report_revision_execution_mismatch', '刷新执行缺少可验证的父任务或保存参考绑定。') from error
    if execution.saved_revision_binding is not None:
        try:
            await _require_saved_revision_task(runtime, scope, source, execution.saved_revision_binding, execution.report_revision)
        except Exception:
            if not restore_only:
                raise
            # 生成前仍严格拒绝；已生成的服务端目标文件不依赖参考追溯继续存在。
            # 仅精确执行路径且实际身份可读的目标允许进入既有发布，后续返回具体追溯告警。
            expected = {path for paths in revision_delivery_paths(execution, child).values() for path in paths}
            verified = False
            from .checkpoint import FileIdentity
            for item in child.payload.get('artifacts', ()):
                if item.get('path') in expected:
                    try:
                        identity = FileIdentity.model_validate(item)
                        await runtime._read_identity_bytes(scope.workspace_key, identity, max_bytes=identity.size)
                        verified = True
                        break
                    except Exception:
                        pass
            if not verified:
                raise ReportingError('report_revision_execution_mismatch', '保存参考父任务身份无效且没有可恢复的可信目标。')
    return child


async def apply_revision_execution_command(runtime, run_context, execution, command):
    from ...report_editor.revisions import apply_editor_command

    child = await require_revision_execution(runtime, run_context, execution)
    return await apply_editor_command(runtime.state_repository, execution.execution_run_id, command, state=child)


async def prepare_revision_dataset_contexts(runtime, run_context, execution):
    """对新批次CSV运行原生数据画像；上下文和画像只登记到独立执行。"""
    import hashlib
    import json
    from functools import partial

    import anyio

    from ..hospital_operation.detailed_analysis import DatasetAnalysisContext, profile_csv_dataset
    from .checkpoint import FileIdentity
    from .runtime.datasets import _run_profile_job

    child = await require_revision_execution(runtime, run_context, execution)
    handles = await runtime._registered_metric_dataset_handles(run_context, report_revision=execution.report_revision)
    if not handles:
        raise ReportingError('report_analysis_context_unavailable', '新修订没有可供分析的已登记数据集。')
    root = f'报表/智能分析/{execution.source_scope.run_id}/revision-executions/{execution.execution_run_id}'
    context_path = f'{root}/dataset-contexts.json'
    registered = next((FileIdentity.model_validate(item) for item in child.payload.get('artifacts', ())
        if item.get('path') == context_path), None)
    thread_id = execution.source_scope.workspace_key
    if registered is not None:
        raw = await runtime.workspace_service.read_limited_regular_file(thread_id, registered.path, max_bytes=registered.size)
        if len(raw) != registered.size or hashlib.sha256(raw).hexdigest() != registered.sha256:
            raise ReportingError('report_analysis_context_invalid', '新修订数据上下文身份已变化。')
        payload = json.loads(raw)
        contexts = tuple(DatasetAnalysisContext.model_validate(item) for item in payload['datasetContexts'])
        expected = {(item.dataset_id, item.path, item.size, item.sha256, item.row_count) for item in handles}
        if (payload.get('execution') != execution.model_dump(mode='json', by_alias=True)
                or len(contexts) != len(handles) or expected != {
                    (item.dataset_id, item.path, item.size, item.sha256, item.row_count) for item in contexts}):
            raise ReportingError('report_revision_execution_mismatch', '数据上下文与当前新修订输入不一致。')
        for context in contexts:
            identity = context.profile_file
            if identity.model_dump(mode='json', by_alias=True) not in child.payload.get('artifacts', ()):
                raise ReportingError('report_revision_execution_mismatch', '画像没有登记到当前新修订。')
            raw = await runtime.workspace_service.read_limited_regular_file(thread_id, identity.path, max_bytes=identity.size)
            if len(raw) != identity.size or hashlib.sha256(raw).hexdigest() != identity.sha256:
                raise ReportingError('report_analysis_profile_changed', '新修订完整数据画像已变化。')
        return contexts
    contexts = []
    limiter = anyio.CapacityLimiter(1)
    for handle in handles:
        raw = await runtime.workspace_service.read_limited_regular_file(thread_id, handle.path, max_bytes=handle.size)
        if len(raw) != handle.size or hashlib.sha256(raw).hexdigest() != handle.sha256:
            raise ReportingError('stale_dataset', '新修订画像前CSV身份已变化。')
        item_path = f'{root}/profiles/{handle.dataset_id}.context.json'
        item_identity = next((FileIdentity.model_validate(item) for item in child.payload.get('artifacts', ())
            if item.get('path') == item_path), None)
        if item_identity is not None:
            item_raw = await runtime.workspace_service.read_limited_regular_file(thread_id, item_path, max_bytes=item_identity.size)
            if len(item_raw) != item_identity.size or hashlib.sha256(item_raw).hexdigest() != item_identity.sha256:
                raise ReportingError('report_analysis_context_invalid', '逐数据集画像上下文身份已变化。')
            item = json.loads(item_raw)
            context = DatasetAnalysisContext.model_validate(item['datasetContext'])
            if (item.get('execution') != execution.model_dump(mode='json', by_alias=True)
                    or (context.dataset_id, context.path, context.size, context.sha256, context.row_count) != (
                        handle.dataset_id, handle.path, handle.size, handle.sha256, handle.row_count)
                    or context.profile_file.model_dump(mode='json', by_alias=True) not in child.payload.get('artifacts', ())):
                raise ReportingError('report_revision_execution_mismatch', '逐数据集上下文不属于当前执行或CSV。')
            profile_raw = await runtime.workspace_service.read_limited_regular_file(thread_id,
                context.profile_file.path, max_bytes=context.profile_file.size)
            if len(profile_raw) != context.profile_file.size or hashlib.sha256(profile_raw).hexdigest() != context.profile_file.sha256:
                raise ReportingError('report_analysis_profile_changed', '已完成数据画像身份已变化。')
            contexts.append(context)
            continue
        profiled = await _run_profile_job(partial(profile_csv_dataset, raw,
            dataset_id=handle.dataset_id, path=handle.path, expected_sha256=handle.sha256,
            profile_path=f'{root}/profiles/{handle.dataset_id}.json',
            schema={'sourceId': handle.source_id, 'requirementId': handle.requirement_id,
                'sqlHash': handle.sql_hash, 'periodRoles': list(handle.period_roles),
                'contentRole': 'registered_calculation_output'},
            source_warnings=('这是已登记计算输出的画像，不代表业务明细、趋势或期间覆盖完整。',)), limiter)
        identity = await runtime._write_immutable_artifact(thread_id, profiled.context.profile_file.path,
            profiled.profile_content)
        await apply_revision_execution_command(runtime, run_context, execution, ReportingCommand(
            name='record_artifact', commandId=f'revision-profile:{identity.sha256}',
            payload={'artifact': identity.model_dump(mode='json', by_alias=True)}))
        item_content = json.dumps({'execution': execution.model_dump(mode='json', by_alias=True),
            'datasetContext': profiled.context.model_dump(mode='json', by_alias=True)},
            ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
        item_identity = await runtime._write_immutable_artifact(thread_id, item_path, item_content)
        await apply_revision_execution_command(runtime, run_context, execution, ReportingCommand(
            name='record_artifact', commandId=f'revision-profile-context:{item_identity.sha256}',
            payload={'artifact': item_identity.model_dump(mode='json', by_alias=True)}))
        contexts.append(profiled.context)
    content = json.dumps({'execution': execution.model_dump(mode='json', by_alias=True),
        'datasetContexts': [item.model_dump(mode='json', by_alias=True) for item in contexts]},
        ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
    identity = await runtime._write_immutable_artifact(thread_id, context_path, content)
    await apply_revision_execution_command(runtime, run_context, execution, ReportingCommand(
        name='record_artifact', commandId=f'revision-dataset-contexts:{identity.sha256}',
        payload={'artifact': identity.model_dump(mode='json', by_alias=True)}))
    return tuple(contexts)


async def restore_refresh_analysis_plan(runtime, run_context, execution):
    """只从可信原状态/父执行文件恢复完整计划，以新批次真实字段承接原意图。"""
    from ...management.models import ManagementScope
    from ..hospital_operation.detailed_analysis import DetailedAnalysisPlan
    from ..semantics.planning import rebind_refresh_analysis_plan
    from .checkpoint import FileIdentity

    await require_revision_execution(runtime, run_context, execution)
    scope = execution.source_scope
    parent_view = await runtime.report_basis_service.load_registered_revision_planning_context(scope.run_id,
        ManagementScope(scope.database, scope.company_id), user_id=scope.user_id,
        thread_id=scope.caller_thread_id, report_revision=execution.parent_report_revision,
        vault=runtime.configuration_provider.vault)
    child_view = await runtime._metric_planning_context(run_context, report_revision=execution.report_revision)
    if canonical_sha256(child_view.model_dump(mode='json', by_alias=True)) != execution.planning_hash:
        raise ReportingError('report_revision_execution_mismatch', '新分析输入与执行绑定摘要不同。')
    if execution.parent_report_revision == 'initial':
        source, _ = await _source_state(runtime, scope)
        raw = source.payload.get('detailedAnalysisPlan')
        if raw is None:
            raise ReportingError('report_refresh_analysis_plan_unavailable', '原报告未保存完整批准计划，无法自动承接分析。')
        plan = DetailedAnalysisPlan.model_validate(raw)
    else:
        parent_id = execution_run_id(scope, parent_view.basis_id, parent_view.report_revision,
            canonical_sha256(parent_view.model_dump(mode='json', by_alias=True)))
        parent_state = await runtime.state_repository.get(parent_id)
        if parent_state is None or 'reportRevisionExecution' not in parent_state.payload:
            raise ReportingError('report_refresh_analysis_plan_unavailable', '父修订尚未登记独立生成执行和完整计划。')
        parent_execution = ReportRevisionExecution.model_validate(parent_state.payload['reportRevisionExecution'])
        if parent_execution.execution_run_id != parent_id:
            raise ReportingError('report_revision_execution_mismatch', '父执行身份与登记分析不同。')
        await require_revision_execution(runtime, run_context, parent_execution)
        path = f'报表/智能分析/{scope.run_id}/revision-executions/{parent_id}/detailed-plan.json'
        identities = tuple(FileIdentity.model_validate(item) for item in parent_state.payload.get('artifacts', ())
            if item.get('path') == path)
        if len(identities) != 1:
            raise ReportingError('report_refresh_analysis_plan_unavailable', '父修订缺少唯一完整计划登记。')
        plan = await runtime._read_identity_model(scope.workspace_key, identities[0], DetailedAnalysisPlan)
    contexts = await prepare_revision_dataset_contexts(runtime, run_context, execution)
    return rebind_refresh_analysis_plan(plan, parent_view, child_view,
        dataset_fields={item.dataset_id: item.fields for item in contexts})


async def restore_refresh_outline(runtime, run_context, execution):
    """承接登记父大纲；只保留规划意图，后续章节仍以本次证据重新规划。"""
    from ...management.models import ManagementScope
    from ..hospital_operation.outline import ReportOutline
    from .checkpoint import FileIdentity

    await require_revision_execution(runtime, run_context, execution)
    scope = execution.source_scope
    if execution.parent_report_revision == 'initial':
        source, _ = await _source_state(runtime, scope)
        raw = source.payload.get('approvedOutline')
        if raw is None:
            raise ReportingError('report_refresh_outline_unavailable', '原报告未登记批准大纲，无法自动承接分析。')
        return ReportOutline.model_validate(raw)
    parent_view = await runtime.report_basis_service.load_registered_revision_planning_context(scope.run_id,
        ManagementScope(scope.database, scope.company_id), user_id=scope.user_id,
        thread_id=scope.caller_thread_id, report_revision=execution.parent_report_revision,
        vault=runtime.configuration_provider.vault)
    parent_id = execution_run_id(scope, parent_view.basis_id, parent_view.report_revision,
        canonical_sha256(parent_view.model_dump(mode='json', by_alias=True)))
    parent = await runtime.state_repository.get(parent_id)
    if parent is None or 'reportRevisionExecution' not in parent.payload:
        raise ReportingError('report_refresh_outline_unavailable', '父修订缺少独立执行，无法恢复批准大纲。')
    parent_execution = ReportRevisionExecution.model_validate(parent.payload['reportRevisionExecution'])
    if parent_execution.execution_run_id != parent_id:
        raise ReportingError('report_revision_execution_mismatch', '父执行与登记分析不同。')
    await require_revision_execution(runtime, run_context, parent_execution)
    path = f'报表/智能分析/{scope.run_id}/revision-executions/{parent_id}/approved-outline.json'
    identities = tuple(FileIdentity.model_validate(item) for item in parent.payload.get('artifacts', ())
        if item.get('path') == path)
    if len(identities) != 1:
        raise ReportingError('report_refresh_outline_unavailable', '父修订缺少唯一批准大纲登记。')
    return await runtime._read_identity_model(scope.workspace_key, identities[0], ReportOutline)


async def prepare_revision_analysis(runtime, run_context, execution, *, detailed_plan=None, outline=None):
    """将已批准分析计划、新CSV画像和精确事实装配为可恢复的原生分析检查点。"""
    import json

    from ..hospital_operation.detailed_analysis import DetailedAnalysisPlan
    from ..hospital_operation.findings import FindingGraph
    from ..hospital_operation.outline import ReportOutline
    from .checkpoint import ReportingCheckpoint, build_profile_coverage_manifest, payload_sha256
    from .questions import freeze_plan_questions, request_questions

    await require_revision_execution(runtime, run_context, execution)
    if outline is None:
        outline = await restore_refresh_outline(runtime, run_context, execution)
    detailed_plan = (await restore_refresh_analysis_plan(runtime, run_context, execution) if detailed_plan is None
        else DetailedAnalysisPlan.model_validate(detailed_plan))
    outline = ReportOutline.model_validate(outline)
    if {key for section in outline.sections for key in section.analysis_ids} != {item.analysis_id for item in detailed_plan.analyses}:
        raise ReportingError('report_revision_execution_mismatch', '新修订提纲必须覆盖批准的分析计划。')
    outline_payload = outline.model_dump(mode='json', by_alias=True)
    outline_hash = payload_sha256(outline_payload)
    contexts = await prepare_revision_dataset_contexts(runtime, run_context, execution)
    handles = await runtime._registered_metric_dataset_handles(run_context, report_revision=execution.report_revision)
    handle_ids = {item.dataset_id for item in handles}
    if (set(detailed_plan.dataset_ids) != handle_ids
            or {key for analysis in detailed_plan.analyses for key in analysis.dataset_ids} != handle_ids):
        raise ReportingError('report_revision_execution_mismatch', '新分析计划必须精确覆盖本次已登记新数据集。')
    formats = {'document' if item in {'pdf', 'docx'} else item for item in execution.requested_outputs}
    if len(formats) != 1:
        raise ReportingError('report_revision_execution_unavailable', '新修订尚不支持混合文档、演示和工作簿交付。')
    root = f'报表/智能分析/{execution.source_scope.run_id}/revision-executions/{execution.execution_run_id}'
    outline_identity = await runtime._write_immutable_artifact(execution.source_scope.workspace_key,
        f'{root}/approved-outline.json', json.dumps(outline_payload, ensure_ascii=False,
            sort_keys=True, separators=(',', ':'), allow_nan=False).encode())
    await apply_revision_execution_command(runtime, run_context, execution, ReportingCommand(
        name='record_artifact', commandId=f'revision-approved-outline:{outline_identity.sha256}',
        payload={'artifact': outline_identity.model_dump(mode='json', by_alias=True)}))
    plan_identity = await runtime._write_immutable_artifact(execution.source_scope.workspace_key,
        f'{root}/detailed-plan.json', json.dumps(detailed_plan.model_dump(mode='json', by_alias=True),
            ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode())
    await apply_revision_execution_command(runtime, run_context, execution, ReportingCommand(
        name='record_artifact', commandId=f'revision-detailed-plan:{plan_identity.sha256}',
        payload={'artifact': plan_identity.model_dump(mode='json', by_alias=True)}))
    view = await runtime._metric_planning_context(run_context, report_revision=execution.report_revision)
    if canonical_sha256(view.model_dump(mode='json', by_alias=True)) != execution.planning_hash:
        raise ReportingError('report_revision_execution_mismatch', '新分析计划与执行绑定摘要不同。')
    questions = freeze_plan_questions(request_questions(view.request.goal, questions=view.request.questions),
        [item.model_dump(mode='json', by_alias=True) for item in detailed_plan.analyses], goal=view.request.goal)
    await apply_revision_execution_command(runtime, run_context, execution, ReportingCommand(
        name='freeze_delivery_format', commandId='revision-delivery-format', payload={'deliveryFormat': next(iter(formats))}))
    await apply_revision_execution_command(runtime, run_context, execution, ReportingCommand(
        name='set_analysis_plan', commandId=f'revision-analysis-plan:{plan_identity.sha256}', payload={
            'analysisIds': [item.analysis_id for item in detailed_plan.analyses],
            'datasetIds': list(detailed_plan.dataset_ids),
            'detailedAnalysisPlan': detailed_plan.model_dump(mode='json', by_alias=True),
            'questionSpecs': questions.model_dump(mode='json', by_alias=True),
            'analysisPlans': {item.analysis_id: {'analysisId': item.analysis_id, 'analysisName': item.analysis_name,
                'domain': item.domain, 'step': item.management_question,
                'questionId': questions.analysis_to_question[item.analysis_id],
                'primaryMetricFamily': item.primary_metric_family, 'datasetIds': list(item.dataset_ids)}
                for item in detailed_plan.analyses}}))
    facts = await runtime._prepare_deterministic_analysis_facts(run_context=run_context,
        thread_id=execution.source_scope.workspace_key, report_run_id=execution.source_scope.run_id,
        revision=execution.output_revision, detailed_plan=detailed_plan, dataset_handles=handles,
        metric_report_revision=execution.report_revision, execution=execution, dataset_contexts=contexts)
    graph_identity, _ = await runtime._prepare_registered_revision_findings(run_context=run_context,
        thread_id=execution.source_scope.workspace_key, report_run_id=execution.source_scope.run_id,
        revision=execution.output_revision, report_revision=execution.report_revision, fact_files=facts, execution=execution)
    graph = await runtime._read_identity_model(execution.source_scope.workspace_key, graph_identity, FindingGraph)
    coverage = build_profile_coverage_manifest(dataset_handles=[item.public_dict() for item in handles],
        dataset_contexts=[item.model_dump(mode='json', by_alias=True) for item in contexts])
    checkpoint = ReportingCheckpoint(revision=execution.output_revision, phase='analysis', outlineHash=outline_hash,
        profileCoverage=coverage, deterministicFactFiles=facts, findingGraphFile=graph_identity,
        findingGraphHash=graph.snapshot_hash)
    return await runtime._persist_reporting_checkpoint(run_context, checkpoint, execution=execution)


async def load_revision_outline(runtime, run_context, execution):
    """只恢复本执行登记且与检查点摘要一致的大纲，不读取原会话自报值。"""
    from ..hospital_operation.outline import ReportOutline
    from .checkpoint import FileIdentity, ReportingCheckpoint, payload_sha256

    child = await require_revision_execution(runtime, run_context, execution)
    checkpoint = ReportingCheckpoint.model_validate(child.payload.get('workflowCheckpoint'))
    path = (f'报表/智能分析/{execution.source_scope.run_id}/revision-executions/'
        f'{execution.execution_run_id}/approved-outline.json')
    identities = tuple(FileIdentity.model_validate(item) for item in child.payload.get('artifacts', ())
        if item.get('path') == path)
    if len(identities) != 1 or checkpoint.revision != execution.output_revision:
        raise ReportingError('report_revision_execution_mismatch', '新修订缺少唯一登记大纲。')
    outline = await runtime._read_identity_model(execution.source_scope.workspace_key, identities[0], ReportOutline)
    if checkpoint.narrative_outline_file is not None:
        from ..hospital_operation.findings import FindingGraph
        from ..hospital_operation.narrative_outline import NarrativeOutline
        from ..hospital_operation.narrative_planner import build_compatible_report_outline

        files = (checkpoint.narrative_outline_file, checkpoint.finding_graph_file)
        if (checkpoint.narrative_outline_hash != checkpoint.narrative_outline_file.sha256
                or any(file is None or file.model_dump(mode='json', by_alias=True) not in child.payload.get('artifacts', ())
                    for file in files)):
            raise ReportingError('report_revision_execution_mismatch', '新章节提纲或发现图谱未登记。')
        narrative = await runtime._read_identity_model(execution.source_scope.workspace_key, files[0], NarrativeOutline)
        graph = await runtime._read_identity_model(execution.source_scope.workspace_key, files[1], FindingGraph)
        if narrative.snapshot_hash != graph.snapshot_hash or graph.snapshot_hash != checkpoint.finding_graph_hash:
            raise ReportingError('report_revision_execution_mismatch', '新章节提纲与发现图谱不同。')
        outline = build_compatible_report_outline(graph, report_type=outline.report_type,
            title=narrative.title, narrative_outline=narrative)
    if payload_sha256(outline.model_dump(mode='json', by_alias=True)) != checkpoint.outline_hash:
        raise ReportingError('report_revision_execution_mismatch', '新修订大纲与检查点摘要不同。')
    return outline


async def freeze_revision_analysis_artifact(runtime, run_context, execution, *, outline):
    """汇编真实完成回执与新事实；不代替逐问题核对，也不自动完成分析项。"""
    from ..delivery.artifacts_v1 import Citation
    from ..hospital_operation.detailed_analysis import DetailedAnalysisPlan
    from .checkpoint import ReportingCheckpoint

    child = await require_revision_execution(runtime, run_context, execution)
    plan = DetailedAnalysisPlan.model_validate(child.payload.get('detailedAnalysisPlan'))
    checkpoint = ReportingCheckpoint.model_validate(child.payload.get('workflowCheckpoint'))
    handles = await runtime._registered_metric_dataset_handles(run_context, report_revision=execution.report_revision)
    citations = tuple(Citation(citationId=f'citation_{index:03d}', datasetId=item.dataset_id,
        requirementId=item.requirement_id, snapshotHash=item.sha256)
        for index, item in enumerate(sorted(handles, key=lambda item: (item.requirement_id, item.dataset_id)), 1))
    artifact = await runtime._build_reporting_artifact(run_context,
        analysis_ids=tuple(item.analysis_id for item in plan.analyses), detailed_plan=plan,
        fact_files=checkpoint.deterministic_fact_files, citation_bindings=citations,
        execution=execution, outline=outline)
    path = (f'报表/智能分析/{execution.source_scope.run_id}/revision-executions/'
        f'{execution.execution_run_id}/analysis-artifact.json')
    identity = await runtime._write_immutable_artifact(execution.source_scope.workspace_key,
        path, artifact.model_dump_json(by_alias=True).encode('utf-8'))
    await apply_revision_execution_command(runtime, run_context, execution, ReportingCommand(
        name='record_artifact', commandId=f'revision-analysis-artifact:{identity.sha256}',
        payload={'artifact': identity.model_dump(mode='json', by_alias=True)}))
    return await runtime._persist_reporting_checkpoint(run_context, checkpoint.model_copy(update={
        'analysis_manifest_file': identity, 'evidence_manifest': artifact.evidence_manifest,
        'report_brief': artifact.report_brief, 'profile_read_receipts': artifact.profile_read_receipts}), execution=execution)


async def run_revision_analysis_items(runtime, run_context, execution):
    """逐项委托现有Task执行器；已完成项只恢复，任务回执不代替业务验收。"""
    import json

    from ..delivery.acceptance import build_report_artifact_validation_context
    from ..delivery.artifacts_v1 import authoritative_citations
    from ..hospital_operation.detailed_analysis import DetailedAnalysisPlan
    from .checkpoint import FileIdentity, ReportingCheckpoint
    from .query_pipeline import DatasetLineage

    await load_revision_outline(runtime, run_context, execution)
    child = await require_revision_execution(runtime, run_context, execution)
    from .runtime.run_configuration import execution_runtime

    runtime = await execution_runtime(runtime, run_context, execution=execution)
    plan = DetailedAnalysisPlan.model_validate(child.payload.get('detailedAnalysisPlan'))
    checkpoint = ReportingCheckpoint.model_validate(child.payload.get('workflowCheckpoint'))
    contexts = await prepare_revision_dataset_contexts(runtime, run_context, execution)
    handles = await runtime._registered_metric_dataset_handles(run_context, report_revision=execution.report_revision)
    root = f'报表/智能分析/{execution.source_scope.run_id}/revision-executions/{execution.execution_run_id}'
    context_path = f'{root}/dataset-contexts.json'
    identities = tuple(FileIdentity.model_validate(item) for item in child.payload.get('artifacts', ())
        if item.get('path') == context_path)
    if (len(identities) != 1 or {item.dataset_id for item in contexts} != set(plan.dataset_ids)
            or checkpoint.revision != execution.output_revision):
        raise ReportingError('report_revision_execution_mismatch', '新分析任务缺少当前批次的完整上下文。')
    lineage = tuple(DatasetLineage(datasetId=item.dataset_id, sourceId=item.source_id,
        requirementId=item.requirement_id, sqlHash=item.sql_hash, rowCount=item.row_count,
        size=item.size, sha256=item.sha256, periodRoles=item.period_roles, queryWindowId=item.query_window_id)
        for item in handles)
    citations = authoritative_citations(lineage)
    validation = build_report_artifact_validation_context(
        expected_citations=tuple((item.citation_id, item.dataset_id, item.requirement_id, item.snapshot_hash)
            for item in citations), analysis_context_file=identities[0].model_dump(mode='json', by_alias=True))
    validation_file = await runtime._write_immutable_artifact(execution.source_scope.workspace_key,
        f'{root}/analysis.validation-context.json', json.dumps(validation, ensure_ascii=False,
            sort_keys=True, separators=(',', ':'), allow_nan=False).encode())
    await apply_revision_execution_command(runtime, run_context, execution, ReportingCommand(
        name='record_artifact', commandId=f'revision-analysis-validation:{validation_file.sha256}',
        payload={'artifact': validation_file.model_dump(mode='json', by_alias=True)}))
    await apply_revision_execution_command(runtime, run_context, execution, ReportingCommand(
        name='start_analysis', commandId='revision-analysis-start'))
    for analysis in plan.analyses:
        current = await require_revision_execution(runtime, run_context, execution)
        checkpoint = ReportingCheckpoint.model_validate(current.payload['workflowCheckpoint'])
        checkpoint = await runtime._execute_analysis_item_task(run_context, checkpoint=checkpoint,
            revision=execution.output_revision, sandbox_id=execution.source_scope.workspace_key,
            validation_context_file=validation_file, detailed_plan=plan, dataset_handles=handles,
            lineage=lineage, citation_bindings=citations, analysis_context_file=identities[0],
            fact_files=checkpoint.deterministic_fact_files, analysis_id=analysis.analysis_id,
            section_goal={'sectionCode': 'evidence', 'title': analysis.analysis_name or analysis.management_question,
                'sectionNumber': '1', 'focus': (analysis.management_question,)},
            retry_reason=None, feedback=None, rework_request=None, execution=execution)
    return checkpoint


async def run_revision_section(runtime, run_context, execution, *, section_code):
    """从已登记发现/大纲构建原生章节任务；补证请求原样返回，不能冒充已完成正文。"""
    import json

    from ..delivery.acceptance import build_report_artifact_validation_context
    from ..delivery.artifacts_v1 import authoritative_citations
    from ..hospital_operation.detailed_analysis import DetailedAnalysisPlan
    from ..hospital_operation.findings import FindingGraph
    from ..hospital_operation.narrative_outline import NarrativeOutline
    from .checkpoint import FileIdentity, ReportingCheckpoint
    from .query_pipeline import DatasetLineage

    outline = await load_revision_outline(runtime, run_context, execution)
    child = await require_revision_execution(runtime, run_context, execution)
    from .runtime.run_configuration import execution_runtime

    runtime = await execution_runtime(runtime, run_context, execution=execution)
    checkpoint = ReportingCheckpoint.model_validate(child.payload.get('workflowCheckpoint'))
    section = next((item for item in outline.sections if item.code == section_code), None)
    if (not ((execution.requested_outputs == ('md',) and child.payload.get('deliveryFormat') == 'md')
            or (set(execution.requested_outputs) <= {'pdf', 'docx'} and child.payload.get('deliveryFormat') == 'document'))
            or section is None or checkpoint.narrative_outline_file is None or checkpoint.analysis_manifest_file is None):
        raise ReportingError('report_revision_execution_mismatch', '章节生成需要当前文档修订的完整已登记分析和提纲。')
    plan = DetailedAnalysisPlan.model_validate(child.payload.get('detailedAnalysisPlan'))
    handles = await runtime._registered_metric_dataset_handles(run_context, report_revision=execution.report_revision)
    lineage = tuple(DatasetLineage(datasetId=item.dataset_id, sourceId=item.source_id,
        requirementId=item.requirement_id, sqlHash=item.sql_hash, rowCount=item.row_count,
        size=item.size, sha256=item.sha256, periodRoles=item.period_roles, queryWindowId=item.query_window_id)
        for item in handles)
    citations = authoritative_citations(lineage)
    artifact = await runtime._build_reporting_artifact(run_context, analysis_ids=tuple(item.analysis_id for item in plan.analyses),
        detailed_plan=plan, fact_files=checkpoint.deterministic_fact_files, citation_bindings=citations,
        section_codes=(section_code,), execution=execution, outline=outline)
    narrative = await runtime._read_identity_model(execution.source_scope.workspace_key,
        checkpoint.narrative_outline_file, NarrativeOutline)
    graph = await runtime._read_identity_model(execution.source_scope.workspace_key, checkpoint.finding_graph_file, FindingGraph)
    selected = next(item for item in narrative.sections if item.code == section_code)
    work_item = runtime._build_narrative_section_work_item(selected, graph=graph, detailed_plan=plan,
        analysis_artifact=artifact, citation_bindings=citations)
    root = f'报表/智能分析/{execution.source_scope.run_id}/revision-executions/{execution.execution_run_id}'
    context_path = f'{root}/dataset-contexts.json'
    context = next((FileIdentity.model_validate(item) for item in child.payload.get('artifacts', ())
        if item.get('path') == context_path), None)
    if context is None:
        raise ReportingError('report_revision_execution_mismatch', '章节任务缺少当前新修订数据上下文。')
    validation = build_report_artifact_validation_context(
        expected_citations=tuple((item.citation_id, item.dataset_id, item.requirement_id, item.snapshot_hash) for item in citations),
        analysis_context_file=context.model_dump(mode='json', by_alias=True))
    validation_file = await runtime._write_immutable_artifact(execution.source_scope.workspace_key,
        f'{root}/section.validation-context.json', json.dumps(validation, ensure_ascii=False,
            sort_keys=True, separators=(',', ':'), allow_nan=False).encode())
    await apply_revision_execution_command(runtime, run_context, execution, ReportingCommand(name='record_artifact',
        commandId=f'revision-section-validation:{validation_file.sha256}',
        payload={'artifact': validation_file.model_dump(mode='json', by_alias=True)}))
    allowed = selected.narrative_role != 'appendix'
    return await runtime._run_section_phase(run_context, checkpoint=checkpoint, revision=execution.output_revision,
        sandbox_id=execution.source_scope.workspace_key, validation_context_file=validation_file,
        work_item=work_item, analysis_rework_constraints=runtime._analysis_rework_constraints(
            detailed_plan=plan, profile_coverage=checkpoint.profile_coverage, analysis_ids=work_item.analysis_ids) if allowed else {},
        analysis_rework_allowed=allowed, degraded_rework=None, execution=execution)


async def assemble_revision_workbook(runtime, run_context, execution):
    """冻结工作簿计算说明与来源清单；不会把数值计算成功标为问题已回答。"""
    import json
    from functools import partial

    from ..delivery.artifacts_v1 import (
        ArtifactFile,
        ReportArtifactManifest,
        authoritative_citations,
    )
    from ..delivery.draft_v1 import HeadingNumber
    from ..hospital_operation.detailed_analysis import DetailedAnalysisPlan
    from ..hospital_operation.deterministic_analysis import DeterministicAnalysisBundle
    from ..hospital_operation.outline import ReportOutline
    from ..semantics.tables import build_registered_result_tables
    from ..trace.contracts_v1 import derive_resource_id
    from ..trace.index_builder import trace_index_path_for
    from ..trace.semantic_bindings import anchor_bound_numbers
    from ..trace.subject_builder import build_claim_subject_bindings
    from .checkpoint import FileIdentity, ReportingCheckpoint
    from .policy_adoption import (
        PolicyAdoptionExecution,
        policy_adoption_run_context,
        require_policy_adoption_execution,
    )
    from .query_pipeline import DatasetLineage
    from .workbook_claims import freeze_workbook_summary_sections

    source_context = run_context
    adoption = isinstance(execution, PolicyAdoptionExecution)
    if adoption:
        child = await require_policy_adoption_execution(runtime, source_context, execution)
        run_context = policy_adoption_run_context(execution)
        target_run_id = execution.scope.run_id
        report_id = target_run_id
        thread_id = execution.scope.workspace_key
        report_revision = 'initial'
        execution_options = {}
        apply_command = partial(runtime._apply_durable_command, run_context)
    else:
        child = await require_revision_execution(runtime, run_context, execution)
        target_run_id = execution.execution_run_id
        report_id = execution.source_scope.run_id
        thread_id = execution.source_scope.workspace_key
        report_revision = execution.report_revision
        execution_options = {'execution': execution}
        apply_command = partial(apply_revision_execution_command, runtime, run_context, execution)
    if execution.requested_outputs != ('xlsx',) or child.payload.get('deliveryFormat') != 'xlsx':
        raise ReportingError('report_revision_execution_mismatch', '工作簿计算说明只能用于本修订冻结的XLSX交付。')
    root = f'报表/智能分析/{target_run_id}/workbook/revision-{execution.output_revision}'
    markdown_path, manifest_path = f'{root}/report.md', f'{root}/report.manifest.json'
    registered = {item['path']: FileIdentity.model_validate(item) for item in child.payload.get('artifacts', ())}
    saved = child.payload.get('result', {}).get('workbookAssembly')
    if saved is not None:
        if saved.get('execution') != execution.model_dump(mode='json', by_alias=True):
            raise ReportingError('report_revision_execution_mismatch', '工作簿完成回执不属于本修订。')
        markdown_file, manifest_file = (FileIdentity.model_validate(saved[key]) for key in ('markdown', 'manifest'))
        if (markdown_file.path, manifest_file.path) != (markdown_path, manifest_path):
            raise ReportingError('report_revision_execution_mismatch', '工作簿完成路径与本修订不一致。')
        files = (markdown_file, manifest_file, *(FileIdentity.model_validate(item) for item in saved.get('dependencies', ())))
        for file in files:
            if registered.get(file.path) != file:
                raise ReportingError('report_revision_execution_mismatch', '工作簿计算说明或来源未登记到本修订。')
            await runtime._read_identity_bytes(thread_id, file)
        manifest = await runtime._read_identity_model(thread_id, manifest_file, ReportArtifactManifest)
        if (manifest.report_id, manifest.revision, manifest.report_basis_id) != (
                report_id, execution.output_revision, execution.basis_id):
            raise ReportingError('report_revision_execution_mismatch', '工作簿清单与本修订计算依据不一致。')
        completed = ReportingCheckpoint.model_validate(saved['completedCheckpoint'])
        current = ReportingCheckpoint.model_validate(child.payload['workflowCheckpoint'])
        if current.phase != 'completed':
            current = await runtime._persist_reporting_checkpoint(run_context, completed, **execution_options)
        return current, manifest
    existing = await runtime.workspace_service.abatch_hash_files(thread_id,
        [markdown_path, manifest_path, trace_index_path_for(manifest_path)])
    if any(not item.get('missing') for item in existing):
        raise ReportingError('report_revision_workbook_outcome_unknown',
            '工作簿说明已有文件但未完成登记，需核对结果，禁止自动覆盖。')
    checkpoint = ReportingCheckpoint.model_validate(child.payload['workflowCheckpoint'])
    if adoption:
        from .policy_adoption_analysis import prepare_policy_adoption_narrative

        run_context = await prepare_policy_adoption_narrative(runtime, source_context, execution)
        apply_command = partial(runtime._apply_durable_command, run_context)
        outline = ReportOutline.model_validate(run_context.session_state['report_outline'])
        if checkpoint.analysis_manifest_file is None:
            plan = DetailedAnalysisPlan.model_validate(run_context.session_state['report_detailed_analysis_plan'])
            lineage = tuple(DatasetLineage.model_validate(item) for item in run_context.session_state['report_dataset_lineage'])
            artifact = await runtime._build_reporting_artifact(run_context,
                analysis_ids=tuple(item.analysis_id for item in plan.analyses), detailed_plan=plan,
                fact_files=checkpoint.deterministic_fact_files, citation_bindings=authoritative_citations(lineage))
            identity = await runtime._write_immutable_artifact(thread_id,
                f'报表/智能分析/{target_run_id}/policy-adoption/analysis-artifact.json',
                json.dumps(artifact.model_dump(mode='json', by_alias=True), ensure_ascii=False,
                    sort_keys=True, separators=(',', ':'), allow_nan=False).encode())
            checkpoint = runtime._update_reporting_checkpoint(checkpoint,
                report_brief=artifact.report_brief, evidence_manifest=artifact.evidence_manifest,
                analysis_manifest_file=identity, profile_read_receipts=artifact.profile_read_receipts,
                files=runtime._merge_checkpoint_files(checkpoint.files, identity))
            for file in checkpoint.files:
                await apply_command(ReportingCommand(name='record_artifact',
                    commandId=f'adoption-workbook-input:{canonical_sha256(file.model_dump(mode="json"))}',
                    payload={'artifact': file.model_dump(mode='json', by_alias=True)}))
                registered[file.path] = file
            checkpoint = await runtime._persist_reporting_checkpoint(run_context, checkpoint)
    else:
        outline = await load_revision_outline(runtime, run_context, execution)
    if checkpoint.analysis_manifest_file is None or checkpoint.evidence_manifest is None:
        raise ReportingError('report_revision_execution_mismatch', '工作簿计算说明缺少冻结分析回执。')
    for file in (checkpoint.analysis_manifest_file, *checkpoint.deterministic_fact_files.values()):
        if registered.get(file.path) != file:
            raise ReportingError('report_revision_execution_mismatch', '工作簿分析回执未登记到本修订。')
        await runtime._read_identity_bytes(thread_id, file)
    view = await runtime._metric_planning_context(run_context, report_revision=report_revision)
    checkpoint, summaries = await freeze_workbook_summary_sections(runtime, run_context,
        checkpoint=checkpoint, outline=outline, root=root, view=view, **execution_options)
    handles = await runtime._registered_metric_dataset_handles(run_context, report_revision=report_revision)
    lineage = tuple(DatasetLineage(datasetId=item.dataset_id, sourceId=item.source_id,
        requirementId=item.requirement_id, sqlHash=item.sql_hash, rowCount=item.row_count,
        size=item.size, sha256=item.sha256, periodRoles=item.period_roles, queryWindowId=item.query_window_id)
        for item in handles)
    lines = [f'# {outline.title}', '',
        '工作簿计算说明：仅列示本修订已登记的计算结果与限制；已计算不代表管理问题已回答或业务验收通过。']
    traces, included = [], set()
    for section in outline.sections:
        lines.extend(('', f'## {section.section_number} {section.title}'))
        for summary in summaries:
            if summary.section_code == section.code:
                for block in summary.blocks:
                    lines.extend(('', anchor_bound_numbers(block.markdown, block.narrative_references)))
        for analysis_id in section.analysis_ids:
            if analysis_id in included:
                continue
            included.add(analysis_id)
            bundle = await runtime._read_identity_model(thread_id,
                checkpoint.deterministic_fact_files[analysis_id], DeterministicAnalysisBundle)
            if bundle.metric_context != view:
                raise ReportingError('report_revision_execution_mismatch', '工作簿事实不属于当前登记计算版本。')
            for trace, markdown in build_registered_result_tables(bundle,
                    fact_file_resource_id=derive_resource_id(checkpoint.deterministic_fact_files[analysis_id].path)):
                traces.append(trace)
                lines.extend(('', markdown))
    lines.extend(('', '数据来源：' + ' '.join(f'[[citation:{item.citation_id}]]' for item in authoritative_citations(lineage)), ''))
    markdown_file = await runtime._write_immutable_artifact(thread_id, markdown_path, '\n'.join(lines).encode('utf-8'))
    manifest = await runtime._build_and_write_artifact_manifest(manifest_path,
        accepted_artifacts=[markdown_file.model_dump(mode='json', by_alias=True)], handles=handles,
        fact_files={key: ArtifactFile(**file.model_dump(), mediaType='application/json')
            for key, file in checkpoint.deterministic_fact_files.items()}, server_table_traces=tuple(traces),
        markdown_path=markdown_path, lineage=lineage, revision=execution.output_revision,
        subject_bindings=build_claim_subject_bindings(summaries, {}, {}),
        task_key=f'workbook-{target_run_id}',
        section_numbers=tuple(section.section_number for section in outline.sections),
        heading_numbers=tuple(HeadingNumber(level=2, number=section.section_number, title=section.title,
            sectionCode=section.code, anchor=f'report-section-{section.code}') for section in outline.sections),
        run_context=run_context, **execution_options)
    manifest_file = FileIdentity.model_validate(await runtime.workspace_service.ahash_file(thread_id, manifest_path))
    dependencies = (*checkpoint.workbook_summary_files,
        *((FileIdentity(path=manifest.trace_index.path, size=manifest.trace_index.size,
            sha256=manifest.trace_index.sha256),) if manifest.trace_index else ()))
    completed = runtime._update_reporting_checkpoint(checkpoint, phase='completed', pending_sections=(),
        files=runtime._merge_checkpoint_files(checkpoint.files, markdown_file, manifest_file, *dependencies))
    for file in (markdown_file, manifest_file, *dependencies):
        await apply_command(ReportingCommand(name='record_artifact',
            commandId=f'revision-workbook-assembly:{derive_resource_id(file.path)}:{file.sha256}',
            payload={'artifact': file.model_dump(mode='json', by_alias=True)}))
    assembly = {'execution': execution.model_dump(mode='json', by_alias=True),
        'markdown': markdown_file.model_dump(mode='json', by_alias=True),
        'manifest': manifest_file.model_dump(mode='json', by_alias=True),
        'dependencies': [file.model_dump(mode='json', by_alias=True) for file in dependencies],
        'completedCheckpoint': completed.model_dump(mode='json', by_alias=True)}
    await apply_command(ReportingCommand(name='finalize',
        commandId=f'revision-workbook-finalize:{execution.output_revision}:{manifest_file.sha256}'))
    await apply_command(ReportingCommand(name='complete',
        commandId=f'revision-workbook-complete:{execution.output_revision}:{manifest_file.sha256}',
        payload={'markdown': assembly['markdown'], 'manifest': assembly['manifest'], 'charts': [], 'workbookAssembly': assembly}))
    completed = await runtime._persist_reporting_checkpoint(run_context, completed, **execution_options)
    return completed, manifest


async def continue_revision_delivery(runtime, run_context, execution):
    """以子检查点续跑原生交付；已生成文件优先恢复，不重做取数或分析。"""
    from agno.workflow.types import StepInput, StepOutput

    from ..delivery.artifacts_v1 import authoritative_citations
    from .checkpoint import ReportingCheckpoint
    from .query_pipeline import DatasetLineage

    child = await require_revision_execution(runtime, run_context, execution, restore_only=True)
    delivery = child.payload.get('deliveryFormat')
    root = f'报表/智能分析/{execution.execution_run_id}'
    output_root = (f'{root}/document-render' if delivery == 'document'
        else f'{root}/{"document" if delivery == "md" else "slides" if delivery == "pptx" else "workbook"}')
    final_paths = {f'{output_root}/revision-{execution.output_revision}/report.{output}'
        for output in execution.requested_outputs}
    template = child.payload.get('requestMaterials', {}).get('templateInput') and delivery != 'md'
    if template:
        prefix = f'{root}/template/revision-{execution.output_revision}/'
        final_paths = {item['path'] for item in child.payload.get('artifacts', ()) if item['path'].startswith(prefix)}
        saved = child.payload.get('result', {}).get('renderedTemplate', {})
        final_paths.update(saved[f'{label}Path'] for label in ('pdf', 'word', 'pptx', 'xlsx') if saved.get(f'{label}Path'))
    step = StepInput(input='继续已登记的新修订交付')
    if any(item.get('path') in final_paths for item in child.payload.get('artifacts', ())):
        return await runtime.publish_report(step, run_context, execution=execution)
    child = await require_revision_execution(runtime, run_context, execution)
    checkpoint = ReportingCheckpoint.model_validate(child.payload.get('workflowCheckpoint'))
    if checkpoint.phase != 'completed':
        from .runtime.run_configuration import execution_runtime

        runtime = await execution_runtime(runtime, run_context, execution=execution)
        if checkpoint.analysis_manifest_file is None:
            await run_revision_analysis_items(runtime, run_context, execution)
            outline = await load_revision_outline(runtime, run_context, execution)
            checkpoint = await freeze_revision_analysis_artifact(runtime, run_context, execution, outline=outline)
        if checkpoint.narrative_outline_file is None:
            await runtime.generate_narrative_outline(step, run_context, execution=execution)
        outline = await load_revision_outline(runtime, run_context, execution)
        if delivery in {'document', 'md'}:
            for section in outline.sections:
                checkpoint, _, rework = await run_revision_section(runtime, run_context, execution,
                    section_code=section.code)
                if rework is not None:
                    return StepOutput(content={'status': 'supplemental_evidence_required',
                        'revision': execution.output_revision,
                        'reworkRequest': rework.model_dump(mode='json', by_alias=True)})
            handles = await runtime._registered_metric_dataset_handles(run_context, report_revision=execution.report_revision)
            lineage = tuple(DatasetLineage(datasetId=item.dataset_id, sourceId=item.source_id,
                requirementId=item.requirement_id, sqlHash=item.sql_hash, rowCount=item.row_count,
                size=item.size, sha256=item.sha256, periodRoles=item.period_roles, queryWindowId=item.query_window_id)
                for item in handles)
            document_root = f'{root}/document/revision-{execution.output_revision}'
            await runtime._finalize_reporting_sections(run_context, checkpoint=checkpoint,
                revision=execution.output_revision, markdown_path=f'{document_root}/report.md',
                manifest_path=f'{document_root}/report.manifest.json', lineage=lineage,
                citation_bindings=authoritative_citations(lineage), source_warnings=(), execution=execution)
        elif delivery == 'pptx':
            await runtime.assemble_slides(step, run_context, execution=execution)
        elif delivery == 'xlsx':
            await assemble_revision_workbook(runtime, run_context, execution)
        else:
            raise ReportingError('report_revision_execution_mismatch', '新修订没有可信交付格式。')
    if template:
        rendered = await runtime._render_revision_document(run_context, execution)
    elif delivery in {'document', 'md'}:
        rendered = await runtime._render_and_validate(run_context, execution=execution)
    elif delivery == 'pptx':
        rendered = (await runtime.validate_slides(step, run_context, execution=execution)).content
    elif delivery == 'xlsx':
        rendered = await runtime._render_xlsx(run_context, {'revision': execution.output_revision},
            await load_revision_outline(runtime, run_context, execution), execution=execution)
    else:
        raise ReportingError('report_revision_execution_mismatch', '新修订没有可信交付格式。')
    published = await runtime._publish_revision_report(run_context, execution, rendered=rendered)
    if rendered.get('validation', {}).get('ok') is False:
        # 同次执行发生的验收或登记故障不能被紧接的恢复读取抹去；下载身份仍取发布分支。
        content = dict(published.content)
        issues = [*content.get('validation', {}).get('issues', ())]
        for issue in rendered['validation'].get('issues', ()):
            if issue not in issues:
                issues.append(issue)
        content.update({'status': 'validation_failed',
            'validation': {**content.get('validation', {}), 'ok': False, 'issues': issues},
            'validationIssues': issues})
        return StepOutput(content=content)
    return published


async def prepare_refresh_delivery(runtime, run_context, *, parent_report_revision, report_revision, task=None):
    """按原授权范围刷新并准备子执行；重复调用不回退已有生成检查点。"""
    from ...management.models import ManagementScope

    scope = _source_scope(runtime, run_context)
    source, _ = await _source_state(runtime, scope)
    if task is not None and task.saved_revision_reference is not None:
        from ..saved_revision_reference import read_saved_revision_reference
        binding = SavedRevisionExecutionBinding(taskId=task.task_id, inputHash=task.input_hash,
            contextSha256=task.context_sha256, reference=task.saved_revision_reference)
        await _require_saved_revision_task(runtime, scope, source, binding, report_revision)
        await read_saved_revision_reference(runtime, scope.workspace_key, binding.reference)
    if task is not None and task.saved_revision_reference is not None and task.saved_revision_reference.source != 'markdown_editor':
        reference = task.saved_revision_reference
        retired = source.payload.get('reportEditorRetiredSources', {})
        if not isinstance(retired, dict) or str(reference.revision) in retired:
            raise ReportingError('snapshot_expired', '原报告来源不可再用于计算；已生成文件仍可只读下载。')
    await runtime.report_basis_service.refresh_revision(scope.run_id,
        ManagementScope(scope.database, scope.company_id), user_id=scope.user_id,
        thread_id=scope.caller_thread_id, parent_report_revision=parent_report_revision,
        report_revision=report_revision, vault=runtime.configuration_provider.vault,
        dataset_store=runtime.datasets, run_context=runtime._tool_context(run_context), workflow_scope=scope)
    execution = await prepare_revision_execution(runtime, run_context, report_revision=report_revision, task=task)
    if execution.parent_report_revision != parent_report_revision:
        raise ReportingError('report_revision_execution_mismatch', '刷新执行与请求父修订不一致。')
    child = await require_revision_execution(runtime, run_context, execution)
    if 'workflowCheckpoint' not in child.payload:
        await prepare_revision_analysis(runtime, run_context, execution)
    return execution

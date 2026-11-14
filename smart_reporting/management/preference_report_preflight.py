"""内部双会话授权的真实修订验收；不提供HTTP入口或偏好发布许可。

生成后撤权时仍保留内部产物，但 artifactAccessAuthorized=False；任何未来交付
必须独立重新鉴权，不能将内部结果直接转发客户端。临时目录仅为渲染材料快照。
"""
from __future__ import annotations

import hashlib
import json
import tempfile
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from types import SimpleNamespace

from loguru import logger

from ..preferences.models import FORMATS, FormatPreferences, resolve_format_preferences
from ..report_editor.capabilities import EditorCapabilities
from ..report_editor.office_refresh import require_office_run
from ..report_editor.trace_retention import source_lifecycle_lock
from ..reporting.contract import ReportFileInput
from ..reporting.delivery.office_engine import run_office_engine
from ..reporting.delivery.report_runtime.markdown import _document_context
from ..reporting.models import ReportingError
from ..reporting.workflow.checkpoint import FileIdentity
from ..reporting.workflow.policy_adoption import PolicyAdoptionExecution
from ..reporting.workflow.revision_execution import (
    ReportRevisionExecution,
    _source_state,
    require_revision_execution,
    revision_delivery_paths,
)
from ..reporting.workflow.scope import resolve_reporting_workflow_scope
from .configuration_store import configuration_hash
from .models import ManagementError
from .preference_preflight import PreferencePreflightMaterials, _leaves, run_preference_preflight


def _identity(raw):
    return FileIdentity.model_validate({key: raw[key] for key in ('path', 'size', 'sha256')})


@dataclass(frozen=True)
class _RegisteredEditorSession:
    """由服务端一次性交接记录构造，不能从HTTP请求反序列化。"""

    session_hash: str


def _native_execution(context, state, execution, format):
    """精确比对当前授权运行登记；不借父运行的当前checkpoint猜测子执行。"""
    registrations = [(key, state.payload[key]) for key in
        ('reportRevisionExecution', 'reportPolicyAdoptionExecution') if state.payload.get(key) is not None]
    if execution is None:
        if registrations:
            raise ValueError('derived execution registration missing from native input')
        return
    if len(registrations) != 1 or registrations[0][1] != execution:
        raise ValueError('native execution is not the authorized durable execution')
    key, _ = registrations[0]
    if key == 'reportRevisionExecution':
        parsed = ReportRevisionExecution.model_validate(execution)
        execution_run = parsed.execution_run_id
        source_scope = parsed.source_scope
    else:
        parsed = PolicyAdoptionExecution.model_validate(execution)
        execution_run = parsed.scope.run_id
        source_scope = parsed.scope
        if parsed.scope.as_state() != context.scope:
            raise ValueError('native policy adoption scope mismatch')
    expected_scope = (context.scope['database'], context.scope['companyId'],
        context.scope['userId'], context.scope['callerThreadId'])
    if (execution_run != context.workflow_run_id or parsed.output_revision != context.revision
        or parsed.requested_outputs != (format,)
        or (source_scope.database, source_scope.company_id, source_scope.user_id,
            source_scope.caller_thread_id) != expected_scope):
        raise ValueError('native execution scope mismatch')


def _unavailable_result(draft, issues):
    preferences = FormatPreferences.model_validate(draft['document'])
    formats = {}
    for format in FORMATS:
        issue = issues[format]
        formats[format] = {'availability': 'unavailable', 'artifact': None, 'pdf': None,
            'previewPageCount': 0, 'readback': {'status': 'unavailable', 'checks': []},
            'capabilities': [{'path': format + '.' + path, 'value': value, 'status': 'unavailable',
                'reason': issue['message']} for path, value in _leaves(resolve_format_preferences(preferences, format))],
            'issues': [issue], 'status': 'incomplete'}
    return {'schemaVersion': 1, 'draftVersion': draft['version'], 'contentHash': draft['contentHash'],
        'scope': 'server_bound_report_materials', 'status': 'incomplete', 'canApply': False, 'formats': formats}


class BoundPreferencePreflightService:
    def __init__(self, *, preferences, editor, grants):
        self.preferences, self.editor, self.grants = preferences, editor, grants

    async def _authorize(self, admin_session, editor_session, expected_context_hash):
        actor = await self.preferences.auth.authenticate(admin_session)
        session = (await self.grants.lookup_registered_session(editor_session.session_hash)
            if isinstance(editor_session, _RegisteredEditorSession)
            else await self.grants.lookup_session(editor_session))
        if not EditorCapabilities.of(session.capabilities).full:
            raise ReportingError('dataset_access_denied', '分享会话不能读取报告材料进行偏好验收。')
        context = await self.editor.context_for_session(session)
        if context.revision != session.revision or context.digest() != expected_context_hash:
            raise ReportingError('report_editor_scope_mismatch', '报告修订或上下文摘要已变化。')
        state = await self._state_for_context(context)
        return actor, context, state

    async def _state_for_context(self, context):
        scope = resolve_reporting_workflow_scope(run_id=context.workflow_run_id,
            session_id=context.scope['sessionId'], user_id=context.scope['userId'], stored_scope=context.scope)
        state, registered = await _source_state(self.editor, scope)
        require_office_run(scope, registered)
        if state.report_run_id != scope.run_id:
            raise ReportingError('report_editor_scope_mismatch', '报告状态与授权运行不一致。')
        return state

    async def _derived_native_state(self, context, state, format, execution=None):
        """父授权只恢复对应修订的完整已登记任务，不以原生指针自证权限。"""
        from ..report_editor.recalculation import (
            RecalculationTask,
            read_registered_recalculation_execution,
            read_task_by_id,
        )
        from ..report_editor.service import ReportEditorContext

        if execution is not None and execution.get('executionRunId') == context.workflow_run_id:
            return state, None
        reservations = state.payload.get('reportEditorRevisionReservations', {})
        if execution is None:
            candidates = []
            for child_id, revision in reservations.items():
                if revision != context.revision:
                    continue
                child = await self.editor.state_repository.get(child_id)
                raw = child.payload.get('reportRevisionExecution') if child else None
                if not isinstance(raw, dict) or raw.get('requestedOutputs') != [format]:
                    raise ValueError('reserved native child has no matching execution registration')
                candidates.append(raw)
            if not candidates:
                return state, None
            if len(candidates) != 1:
                raise ValueError('native revision has ambiguous child executions')
            execution = candidates[0]
        parsed = ReportRevisionExecution.model_validate(execution)
        if (parsed.source_scope.run_id != context.workflow_run_id
            or parsed.source_scope.as_state() != context.scope
            or parsed.output_revision != context.revision or parsed.requested_outputs != (format,)
            or reservations.get(parsed.execution_run_id) != context.revision):
            raise ValueError('native child is outside authorized revision scope')
        task_id = 'recalc-' + parsed.report_revision.removeprefix('editor-refresh-')
        registered_task = RecalculationTask.model_validate(
            state.payload.get('reportEditorRecalculations', {}).get(task_id))
        parent = ReportEditorContext.model_validate(state.payload.get('reportEditorContexts', {}).get(
            str(registered_task.request.parent_revision)))
        if (parent.scope != context.scope or parent.workflow_run_id != context.workflow_run_id
            or parent.report_id != context.report_id):
            raise ValueError('native task parent is outside authorized report')
        task = await read_task_by_id(self.editor, parent, task_id)
        recovered = await read_registered_recalculation_execution(self.editor, parent, task_id)
        if (task is None or recovered != parsed or task.refresh_binding is None
            or task.refresh_binding.report_revision != parsed.report_revision
            or task.refresh_binding.parent_report_revision != parsed.parent_report_revision
            or task.basis_id != parsed.basis_id
            or task.result is not None and getattr(task.result, 'execution', None) != parsed):
            raise ValueError('native execution differs from durable parent task')
        runtime = SimpleNamespace(state_repository=self.editor.state_repository,
            _scope=lambda _: context.scope)
        child = await require_revision_execution(runtime, SimpleNamespace(run_id=context.workflow_run_id),
            parsed, revision=context.revision)
        registered = await self.editor.state_repository.get_run(parsed.execution_run_id)
        expected = {'report_run_id': parsed.execution_run_id, 'external_run_id': parsed.execution_run_id,
            'agno_run_id': parsed.execution_run_id, 'agno_session_id': parsed.execution_run_id,
            'thread_id': parsed.source_scope.caller_thread_id, 'owner_user_id': parsed.source_scope.user_id,
            'revision': parsed.output_revision}
        if (child.report_run_id != parsed.execution_run_id
            or child.payload.get('reportPolicyAdoptionExecution') is not None
            or any(registered.get(key) != value for key, value in expected.items())):
            raise ValueError('native child run registration identity mismatch')
        path = getattr(context, format + '_path')
        if path not in revision_delivery_paths(parsed, child).get(format, ()):
            raise ValueError('native artifact is outside exact execution delivery')
        artifact = FileIdentity(path=path, size=getattr(context, format + '_size'),
            sha256=getattr(context, format + '_sha256'))
        if task.result is not None and artifact not in task.result.artifacts:
            raise ValueError('native artifact differs from completed parent task result')
        return child, {'execution': parsed.model_dump(mode='json', by_alias=True),
            'task': task.model_dump(mode='json', by_alias=True), 'parentContextSha256': parent.digest(),
            'run': {key: registered[key] for key in (*expected, 'entrypoint', 'caller_run_id',
                'caller_session_id', 'database', 'company_id')}, 'reservation': context.revision}

    async def _snapshot(self, context, state, destination):
        identities, copies = {}, {}
        thread = context.scope['threadId']

        async def read(raw, *, copy=False):
            identity = _identity(raw)
            previous = identities.get(identity.path)
            if previous is not None and previous != identity.model_dump():
                raise ReportingError('snapshot_integrity_failed', '同一路径存在冲突的来源身份。')
            if identity.path not in identities and sum(item['size'] for item in identities.values()) + identity.size > 200 * 1024 * 1024:
                raise ReportingError('resource_limit_exceeded', '偏好验收材料超过现有200MiB来源读取上限。')
            content = await self.editor.workspace.read_limited_regular_file(thread, identity.path, max_bytes=identity.size)
            if len(content) != identity.size or hashlib.sha256(content).hexdigest() != identity.sha256:
                raise ReportingError('snapshot_integrity_failed', '验收来源与耐久登记身份不一致。')
            identities[identity.path] = identity.model_dump()
            if copy:
                copies[identity.path] = content
            return content

        job = deepcopy(context.job)
        job.pop('_tableCaptionManifest', None)
        job.pop('_tableCaptionWorkflowRunId', None)
        table_caption_issue = None
        manifest = await self.editor.trace.load_manifest(context)
        if manifest is not None:
            if context.artifact_manifest is not None:
                await read(context.artifact_manifest.model_dump(mode='json', by_alias=True))
            markdown_identity = manifest.markdown.model_dump(mode='json', by_alias=True)
        else:
            markdown_identity = job.get('render', {}).get('markdown')
        if not isinstance(markdown_identity, dict) or markdown_identity.get('path') != context.markdown_path:
            raise ReportingError('snapshot_integrity_failed', '修订缺少完整的已登记Markdown身份。')
        await read(markdown_identity, copy=True)
        if manifest is not None and manifest.trace_index is not None:
            try:
                await self.editor.trace.index_for_manifest(context, manifest)
                await read(manifest.trace_index.model_dump(mode='json', by_alias=True), copy=True)
                job['_tableCaptionManifest'] = manifest.model_dump(mode='json', by_alias=True)
                job['_tableCaptionWorkflowRunId'] = context.workflow_run_id
            except Exception as error:
                table_caption_issue = {'code': 'report_table_caption_source_unavailable',
                    'message': '当前修订的表题索引未能核验，保留原文和已生成文件，表题编号未获验证。'}
                logger.warning('preference_table_caption_source_unavailable error_type={}', type(error).__name__)
        for source in job.get('sources', []):
            await read(source, copy=True)
        # 只能加入已由修订清单/冻结job核验的正文身份，不能将当前可读路径升级为来源。
        job['sources'] = [_identity(source).model_dump() for source in job.get('sources', [])
            if source['path'] != context.markdown_path] + [_identity(markdown_identity).model_dump()]
        issues = {}
        try:
            _document_context(job.get('_documentContext'))
            available = ['md', 'pdf', 'word']
        except Exception:
            available = []
            issues.update({key: {'code': 'management_preference_document_context_unavailable',
                'message': '当前修订缺少冻结文档展示契约，未用当前日期或界面标题补造。'} for key in ('md', 'pdf', 'word')})
        materials = state.payload.get('requestMaterials', {})
        template_bound = materials.get('templateInput') is not None
        template_source = None
        if template_bound:
            available = [key for key in available if key == 'md']
            issues.update({key: {'code': 'management_preference_template_input_unavailable',
                'message': '当前修订绑定模板，通用文档生成不能替代正式模板验收。'} for key in ('pdf', 'word')})
            try:
                template = ReportFileInput.model_validate(materials['templateInput'])
                if PurePosixPath(template.filename).suffix.lower() != '.docx' or 'md' not in available:
                    raise ValueError('template route or frozen document context unavailable')
                from .preference_template_preflight import verify_docx_template

                template_bytes = await read(template.model_dump(), copy=True)
                verify_docx_template(template_bytes)
                template_source = {'identity': template.model_dump(mode='json', by_alias=True),
                    'templateFormat': 'docx', 'sourceContent': _identity(markdown_identity).model_dump(), 'images': []}
                if job.get('_templateSemanticReview') is not None or '_templateSource' in job:
                    from ..report_editor.template_source import resolve_editor_template
                    from ..reporting.template_semantic_review import semantic_issue
                    from ..reporting.workflow.runtime.template_semantics import (
                        semantic_review_reference,
                    )

                    try:
                        origin = await resolve_editor_template(self.editor, context=context, source_context=context)
                        if (origin is None or origin.identity.model_dump(mode='json', by_alias=True)
                                != template_source['identity'] or origin.content != template_bytes):
                            raise ValueError('冻结语义来源与当前模板不一致')
                        template_source['semanticIssues'] = deepcopy(list(origin.semantic_issues))
                        if origin.semantic_review is not None:
                            template_source['semanticReview'] = deepcopy(origin.semantic_review)
                            template_source['semanticSource'] = {
                                'review': semantic_review_reference(origin.semantic_review),
                                'materialRunId': origin.material_run_id, 'binding': deepcopy(origin.binding)}
                    except Exception as error:
                        logger.warning('preference_template_semantic_source_unavailable error_type={}', type(error).__name__)
                        template_source['semanticIssues'] = [semantic_issue('unavailable')]
                for chart in getattr(manifest, 'charts', ()):
                    image = _identity(chart.model_dump()).model_dump()
                    await read(image, copy=True)
                    template_source['images'].append(image)
                if not any(item['path'] == template.path for item in job['sources']):
                    job['sources'].append(_identity(template.model_dump()).model_dump())
                available.extend(('pdf', 'word'))
                for format in ('pdf', 'word'):
                    issues.pop(format)
            except Exception as error:
                logger.warning('preference_template_material_unavailable error_type={}', type(error).__name__)
        sheets, slides, native_sources = (), (), {}
        for format in ('xlsx', 'pptx'):
            try:
                if template_bound:
                    raise ValueError('generic renderer cannot verify template delivery')
                if context.delivery_format != format:
                    raise ValueError('no revision-scoped native artifact')
                artifact = {'path': getattr(context, format + '_path'), 'size': getattr(context, format + '_size'),
                    'sha256': getattr(context, format + '_sha256')}
                await read(artifact)
                native_state, execution_binding = state, None
                if format == 'pptx':
                    pointer = job['pptxNativeInput']
                    if _identity(pointer['artifact']) != _identity(artifact):
                        raise ValueError('native artifact mismatch')
                    receipt = json.loads(await read(pointer['receipt']))
                    binding = pointer['binding']
                    if (set(binding) != {'workflowRunId', 'revision', 'execution'}
                        or type(binding['revision']) is not int
                        or receipt.get('schemaVersion') != 'pptx-native-receipt/1'
                        or receipt.get('binding') != binding
                        or binding['revision'] != context.revision or receipt['spec'] != pointer['spec']):
                        raise ValueError('native receipt binding mismatch')
                    if (binding['workflowRunId'] != context.workflow_run_id
                        or context.revision in state.payload.get('reportEditorRevisionReservations', {}).values()):
                        native_state, execution_binding = await self._derived_native_state(
                            context, state, format, binding['execution'])
                        if (execution_binding is None or binding['workflowRunId'] !=
                            execution_binding['execution']['executionRunId']):
                            raise ValueError('native receipt child binding mismatch')
                else:
                    path = str(PurePosixPath(artifact['path']).with_suffix('.xlsx.receipt.json'))
                    if not any(state.payload.get(key) is not None for key in (
                        'reportRevisionExecution', 'reportPolicyAdoptionExecution')):
                        native_state, execution_binding = await self._derived_native_state(context, state, format)
                    checkpoint = native_state.payload.get('workflowCheckpoint')
                    registered = [*(checkpoint.get('files', []) if isinstance(checkpoint, dict)
                        and execution_binding is None else []), *native_state.payload.get('artifacts', [])]
                    candidates = {_identity(item).sha256: item for item in registered if item.get('path') == path}
                    if len(candidates) != 1:
                        raise ValueError('native receipt unavailable or ambiguous')
                    receipt_identity = next(iter(candidates.values()))
                    receipt = json.loads(await read(receipt_identity))
                if _identity(receipt['artifact']) != _identity(artifact):
                    raise ValueError('receipt artifact mismatch')
                execution = binding.get('execution') if format == 'pptx' else receipt.get('execution')
                if execution_binding is not None:
                    if execution != execution_binding['execution']:
                        raise ValueError('native receipt differs from registered child execution')
                    required = (artifact, pointer['receipt'] if format == 'pptx' else receipt_identity, receipt['spec'])
                    for item in required:
                        matches = [_identity(raw) for raw in native_state.payload.get('artifacts', [])
                            if raw.get('path') == item['path']]
                        if not matches or any(identity != _identity(item) for identity in matches):
                            raise ValueError('native input identity absent from exact child artifacts')
                else:
                    _native_execution(context, state, execution, format)
                spec = json.loads(await read(receipt['spec']))
                document = job.get('_documentContext') or {}
                native_document = {'title': spec.get('title'), 'periodLabel': spec.get('period'),
                    'generatedDate': spec.get('generatedDate') or document.get('generatedDate')}
                if any(not isinstance(value, str) or not value for value in native_document.values()):
                    raise ValueError('native document context unavailable')
                if format == 'pptx':
                    if spec.get('schemaVersion') != 'pptx-native-input/1' or spec.get('binding') != binding:
                        raise ValueError('native spec binding mismatch')
                    slides = tuple(deepcopy(spec['slides']))
                    images = {_identity(item).path: item for item in spec['chartFiles']}
                    if (len(images) != len(spec['chartFiles'])
                        or {slide['chartPath'] for slide in slides if slide.get('chartPath')} != set(images)
                        or any(PurePosixPath(path).suffix.lower() not in {'.png', '.jpg', '.jpeg'} for path in images)):
                        raise ValueError('native static chart identity set mismatch')
                    # 表体必须复用当前精确执行登记的事实，不能只相信冻结spec中的自声明身份。
                    from ..reporting.delivery.pptx_tables import (
                        normalize_slide_table,
                        project_fact_slide_tables,
                    )

                    checkpoint = native_state.payload.get('workflowCheckpoint') or {}
                    fact_files = checkpoint.get('deterministicFactFiles', {})
                    registered_files = [*native_state.payload.get('artifacts', []), *checkpoint.get('files', [])]
                    projected, declared = {}, {}
                    for slide in slides:
                        for raw_table in slide.get('tables', []):
                            table = normalize_slide_table(raw_table)
                            analysis_id = table['sourceAnalysisId']
                            source = _identity(table['sourceFile'])
                            if (analysis_id not in fact_files or _identity(fact_files[analysis_id]) != source
                                or source not in [_identity(item) for item in registered_files
                                    if item.get('path') == source.path]
                                or any(_identity(item) != source for item in registered_files
                                    if item.get('path') == source.path)):
                                raise ValueError('native table fact absent from exact execution registration')
                            if analysis_id not in projected:
                                raw = await read(source.model_dump(), copy=True)
                                projected[analysis_id] = project_fact_slide_tables(analysis_id, source, raw)
                                if not any(item['path'] == source.path for item in job['sources']):
                                    job['sources'].append(source.model_dump())
                            declared.setdefault(analysis_id, []).append(table)
                    if declared != projected:
                        raise ValueError('native table differs from complete frozen fact projection')
                    for slide in slides:
                        if slide.get('chartPath'):
                            image = images[slide['chartPath']]
                            await read(image, copy=True)
                            if not any(item['path'] == image['path'] for item in job['sources']):
                                job['sources'].append(_identity(image).model_dump())
                    if not slides:
                        raise ValueError('empty native slides')
                else:
                    sheets = tuple(deepcopy(spec['sheets']))
                    if not sheets or not isinstance(spec.get('sourceMapping'), dict):
                        raise ValueError('native workbook sources unavailable')
                    job['_workbookSourceMapping'] = deepcopy(spec['sourceMapping'])
                if not available:
                    job['_documentContext'] = native_document
                job.setdefault('_nativeDocumentContexts', {})[format] = native_document
                native_sources[format] = {'artifact': _identity(artifact).model_dump(),
                    'receipt': _identity(pointer['receipt'] if format == 'pptx' else receipt_identity).model_dump(),
                    'spec': _identity(receipt['spec']).model_dump(),
                    **({'binding': deepcopy(binding)} if format == 'pptx' else {'execution': deepcopy(execution)}),
                    **({'executionBinding': execution_binding} if execution_binding is not None else {}),
                    'documentContext': native_document, 'sourceMapping': spec.get('sourceMapping')}
                available.append(format)
            except Exception as error:
                logger.warning('preference_native_material_unavailable format={} error_type={}', format, type(error).__name__)
                issues[format] = {'code': 'management_preference_template_input_unavailable' if template_bound else format + '_native_input_unavailable',
                    'message': '当前修订的' + ('工作簿' if format == 'xlsx' else '演示文稿') + '正式原生输入未能完整核验，未使用样例或逆推数据替代。'}
                if format == 'xlsx':
                    sheets = ()
                else:
                    slides = ()
        for path, content in copies.items():
            target = destination / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
        identity = self.editor.workspace_registry.get(thread)
        binding = {'reportId': context.report_id, 'workflowRunId': context.workflow_run_id,
            'revision': context.revision, 'contextSha256': context.digest(), 'workspaceFingerprint': identity.scope_fingerprint,
            'identities': sorted(identities.values(), key=lambda item: item['path']),
            'nativeSources': native_sources, 'availabilityIssues': issues}
        if table_caption_issue is not None:
            binding['tableCaptionSourceIssue'] = table_caption_issue
        if template_bound:
            binding['templateSource'] = template_source
        return PreferencePreflightMaterials(destination, context.markdown_path, job, sheets, slides,
            template_source=template_source), tuple(available), binding

    async def run(self, *, admin_session, editor_session, expected_draft_version,
        expected_draft_hash, expected_context_hash):
        actor, context, state = await self._authorize(admin_session, editor_session, expected_context_hash)
        draft = (await self.preferences.detail(admin_session))['draft']
        if type(expected_draft_version) is not int or draft['version'] != expected_draft_version or draft['contentHash'] != expected_draft_hash:
            raise ManagementError('management_version_conflict', '草稿身份已变化，请重新回读。', 409)
        with tempfile.TemporaryDirectory(prefix='report-preference-materials-') as directory:
            root = Path(directory)
            async with source_lifecycle_lock(self.editor, context):
                await self.editor._ensure_sources_retained(context)
                state = await self._state_for_context(context)
                materials, formats, binding = await self._snapshot(context, state, root / 'before')
            digest = configuration_hash(binding)
            if formats:
                result = await run_office_engine(run_preference_preflight, deepcopy(draft), materials,
                    expected_version=expected_draft_version, expected_content_hash=expected_draft_hash, formats=formats)
            else:
                result = _unavailable_result(draft, binding['availabilityIssues'])
            result['binding'] = {**binding, 'bindingHash': digest, 'actorId': actor.account_id,
                'actorAuthVersion': actor.auth_version, 'stateVersionBefore': state.state_version,
                'valid': False, 'artifactAccessAuthorized': False}
            try:
                _, after_context, after = await self._authorize(admin_session, editor_session, expected_context_hash)
                latest = (await self.preferences.detail(admin_session))['draft']
                if latest['version'] != expected_draft_version or latest['contentHash'] != expected_draft_hash:
                    raise ManagementError('management_version_conflict', '验收期间草稿已变化。', 409)
                async with source_lifecycle_lock(self.editor, after_context):
                    await self.editor._ensure_sources_retained(after_context)
                    after = await self._state_for_context(after_context)
                    _, _, final = await self._snapshot(after_context, after, root / 'after')
                result['binding']['stateVersionAfter'] = after.state_version
                if configuration_hash(final) != digest:
                    raise ManagementError('management_preference_materials_changed', '验收期间材料绑定发生变化。', 409)
                result['binding']['valid'] = True
                result['binding']['artifactAccessAuthorized'] = True
            except Exception as error:
                result['status'], result['canApply'] = 'failed', False
                result.setdefault('issues', []).append({'code': getattr(error, 'code', 'management_preference_binding_recheck_failed'),
                    'message': getattr(error, 'message', '验收后的授权或材料复核失败；内部实际产物保留，不可据此应用。')})
            return result

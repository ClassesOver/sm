"""只读恢复编辑器实际来源修订的模板、授权材料和冻结配置。"""

from copy import deepcopy
from dataclasses import dataclass, replace
from pathlib import PurePosixPath
from types import SimpleNamespace

from ..management.models import ManagementError, ManagementScope
from ..preferences.runtime import REPORT_CONFIGURATION_SNAPSHOT_KEY
from ..reporting.contract import ReportFileInput
from ..reporting.models import ReportingError
from ..reporting.workflow.checkpoint import FileIdentity
from ..reporting.workflow.revision_execution import (
    ReportRevisionExecution,
    _source_state,
    load_revision_materials,
    require_revision_execution,
)
from ..reporting.workflow.scope import resolve_reporting_workflow_scope
from ._file_identity import read_verified_file


@dataclass(frozen=True)
class EditorTemplateSource:
    identity: ReportFileInput
    content: bytes
    material_run_id: str
    binding: dict
    configuration: dict | None
    document_context: dict | None = None
    semantic_review: dict | None = None
    semantic_issues: tuple = ()


def _unavailable():
    return ReportingError('report_editor_template_source_unavailable',
        '本修订绑定的模板来源或冻结材料无法核验，未改用通用布局。')


def _same_scope(left, right):
    return (left.report_id, left.workflow_run_id, left.scope) == (
        right.report_id, right.workflow_run_id, right.scope)


def _template_output(context):
    render = context.job.get('render') or {}
    return isinstance(render, dict) and any(isinstance(render.get(format), dict)
        and '/template/' in str(render[format].get('path', '')) for format in ('word', 'pdf'))


def _registered_context(source, expected):
    from .service import ReportEditorContext

    actual = ReportEditorContext.model_validate(source.payload.get('reportEditorContexts', {}).get(str(expected.revision)))
    if actual != expected:
        raise _unavailable()


async def _material_source(runtime, scope, root, origin):
    """派生来源必须拥有精确父reservation和完整child执行，不按目录猜。"""
    reservations = root.payload.get('reportEditorRevisionReservations', {})
    candidates = [run_id for run_id, revision in reservations.items() if revision == origin.revision]
    if len(candidates) > 1:
        raise _unavailable()
    if candidates:
        run_id = candidates[0]
        child = await runtime.state_repository.get(run_id)
        execution = ReportRevisionExecution.model_validate(child.payload.get('reportRevisionExecution') if child else None)
        if execution.execution_run_id != run_id or execution.output_revision != origin.revision:
            raise _unavailable()
        child = await require_revision_execution(runtime, SimpleNamespace(run_id=scope.run_id), execution,
            revision=origin.revision)
        return run_id, child
    # 已知派生job不能在reservation缺失时借用根模板；job ID仅用于拒绝，不授予读取权限。
    if origin.job_id.startswith('revision-execution-') or origin.job_id in reservations:
        raise _unavailable()
    return scope.run_id, root


async def _configuration(editor, scope, material_run_id, origin):
    provider = getattr(getattr(editor, 'recalculation_runtime', None), 'configuration_provider', None)
    if provider is not None and hasattr(provider, 'load_run_preferences'):
        try:
            value = await provider.load_run_preferences(material_run_id, ManagementScope(scope.database, scope.company_id),
                user_id=scope.user_id, thread_id=scope.caller_thread_id)
            return deepcopy(value)
        except ManagementError as error:
            if error.code != 'management_run_identity_missing':
                raise
            return None
    return deepcopy(origin.job.get(REPORT_CONFIGURATION_SNAPSHOT_KEY))


def _document_context(origin, state, configuration):
    value = deepcopy(origin.job.get('_documentContext'))
    if not isinstance(value, dict):
        outline = state.payload.get('approvedOutline')
        value = {'title': outline.get('title')} if isinstance(outline, dict) else {}
    frozen_date = configuration.get('generatedDate') if isinstance(configuration, dict) else None
    if frozen_date is not None:
        if value.get('generatedDate') is not None and value['generatedDate'] != frozen_date:
            raise _unavailable()
        value['generatedDate'] = frozen_date
    if not isinstance(value.get('title'), str) or not value['title'].strip():
        return None
    return value


async def resolve_editor_template(editor, *, context, source_context) -> EditorTemplateSource | None:
    """None仅表示耐久材料确认无模板；声明失效、歧义或越权均明确失败。"""
    try:
        if not _same_scope(context, source_context):
            raise _unavailable()
        scope = resolve_reporting_workflow_scope(run_id=context.workflow_run_id,
            session_id=context.scope.get('sessionId', ''), user_id=context.scope.get('userId'), stored_scope=context.scope)

        async def read_identity(thread_id, identity, *, max_bytes):
            if thread_id != scope.workspace_key or identity.size > max_bytes:
                raise _unavailable()
            return await read_verified_file(editor.workspace, context.scope, identity.path,
                size=identity.size, sha256=identity.sha256,
                error_code='report_editor_template_source_unavailable', format_name='模板材料')

        # 复用既有只读核验，普通编辑无需启动重算服务或构造新工作区。
        runtime = SimpleNamespace(state_repository=editor.state_repository,
            _scope=lambda _: scope.as_state(), _read_identity_bytes=read_identity)
        root = await runtime.state_repository.get(scope.run_id)
        _registered_context(root, context)
        _registered_context(root, source_context)
        if (root.external_run_id, root.thread_id, root.owner_user_id) != (
            scope.external_run_id, scope.caller_thread_id, scope.user_id):
            raise _unavailable()
        reservations = root.payload.get('reportEditorRevisionReservations', {})
        if ('_templateSource' not in source_context.job and source_context.revision not in reservations.values()
            and not source_context.job_id.startswith('revision-execution-')
            and source_context.job_id not in reservations and not _template_output(source_context)):
            root_materials = root.payload.get('requestMaterials')
            if isinstance(root_materials, dict) and root_materials.get('templateInput') is not None and not root_materials.get('templateInput'):
                raise _unavailable()
            if (await load_revision_materials(runtime, scope, root))['templateInput'] is None:
                return None
        root, _ = await _source_state(runtime, scope)
        binding = source_context.job.get('_templateSource')
        origin = source_context
        if '_templateSource' in source_context.job:
            from .service import ReportEditorContext

            if (not isinstance(binding, dict) or set(binding) != {
                'schemaVersion', 'originRevision', 'originContextSha256', 'materialRunId', 'identity'}
                or type(binding['schemaVersion']) is not int or binding['schemaVersion'] != 1
                or type(binding['originRevision']) is not int or not 1 <= binding['originRevision'] < source_context.revision):
                raise _unavailable()
            origin = ReportEditorContext.model_validate(root.payload.get('reportEditorContexts', {}).get(str(binding['originRevision'])))
            if (not _same_scope(origin, source_context) or origin.digest() != binding['originContextSha256']
                or '_templateSource' in origin.job):
                raise _unavailable()
        material_run_id, state = await _material_source(runtime, scope, root, origin)
        raw_materials = state.payload.get('requestMaterials')
        if (isinstance(raw_materials, dict) and raw_materials.get('templateInput') is not None
            and not raw_materials.get('templateInput')):
            raise _unavailable()
        materials = await load_revision_materials(runtime, replace(scope, run_id=material_run_id), state)
        template = materials['templateInput']
        if template is None:
            if binding is not None or _template_output(origin):
                raise _unavailable()
            return None
        identity = ReportFileInput.model_validate(template)
        FileIdentity.model_validate({key: getattr(identity, key) for key in ('path', 'size', 'sha256')})
        if PurePosixPath(identity.filename).suffix.lower() != '.docx':
            raise _unavailable()
        expected = {'schemaVersion': 1, 'originRevision': origin.revision, 'originContextSha256': origin.digest(),
            'materialRunId': material_run_id, 'identity': identity.model_dump(mode='json', by_alias=True)}
        if binding is not None and binding != expected:
            raise _unavailable()
        content = await read_verified_file(editor.workspace, source_context.scope, identity.path,
            size=identity.size, sha256=identity.sha256,
            error_code='report_editor_template_source_unavailable', format_name='DOCX模板')
        configuration = await _configuration(editor, scope, material_run_id, origin)
        semantic_review, semantic_issues = None, []
        marker = source_context.job.get('_templateSemanticReview')
        if marker is not None:
            from ..reporting.template_semantic_review import semantic_issue
            from ..reporting.workflow.runtime.template_semantics import (
                load_frozen_template_review,
                semantic_review_reference,
            )

            try:
                semantic_review = await load_frozen_template_review(editor.workspace,
                    thread_id=scope.workspace_key, run_id=material_run_id, raw=content,
                    artifacts=state.payload.get('artifacts', ()))
                if (semantic_review is None or not isinstance(marker, dict)
                        or type(marker.get('version')) is not int
                        or marker != semantic_review_reference(semantic_review)):
                    raise ValueError('历史语义判断与原修订冻结身份不一致')
            except Exception:
                semantic_review = None
                semantic_issues.append(semantic_issue('unavailable'))
        return EditorTemplateSource(identity=identity, content=content, material_run_id=material_run_id,
            binding=deepcopy(expected), configuration=configuration,
            document_context=_document_context(origin, state, configuration),
            semantic_review=deepcopy(semantic_review), semantic_issues=tuple(semantic_issues))
    except ReportingError:
        raise
    except Exception as error:
        raise _unavailable() from error

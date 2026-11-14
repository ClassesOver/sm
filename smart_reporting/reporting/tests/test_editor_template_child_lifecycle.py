"""保存稿刷新子执行经真实发布入口后，人工导出仍使用子执行冻结模板。"""

import hashlib
import json
from io import BytesIO
from types import SimpleNamespace

import pytest
from agno.run import RunContext
from docx import Document

from smart_reporting.preferences.models import FormatPreferences, resolve_format_preferences
from smart_reporting.report_editor import ReportEditorContext, ReportEditorService
from smart_reporting.report_editor.recalculation import (
    RecalculationRequest,
    register_refresh_request,
)
from smart_reporting.reporting.contract import ReportFileInput
from smart_reporting.reporting.delivery.artifacts_v1 import ReportArtifactManifest
from smart_reporting.reporting.tests.test_office_revision_safety import ConcurrentRepository
from smart_reporting.reporting.tests.test_registered_claim_support import native_quality_inputs
from smart_reporting.reporting.tests.test_template_runtime import identity
from smart_reporting.reporting.workflow.revision_execution import (
    ReportRevisionExecution,
    execution_run_id,
)
from smart_reporting.reporting.workflow.runtime.template_delivery import render_template_delivery
from smart_reporting.reporting.workflow.state import ReportingRunState, ReportingStateReducer
from smart_reporting.tests.test_preference_template_preflight import template_bytes


@pytest.mark.anyio
@pytest.mark.parametrize('fault', ['missing', 'directory', 'unknown_read'])
async def test_template_existing_probe_only_accepts_confirmed_missing(tmp_path, monkeypatch, fault):
    from smart_reporting.reporting.host_workspace import (
        ReportingWorkspaceRegistry,
        ReportingWorkspaceRouter,
    )
    from smart_reporting.reporting.tests.test_report_editor import _scope
    from smart_reporting.reporting.workflow.runtime.template_delivery import (
        _existing_template_bytes,
    )
    from smart_reporting.reporting.workspace import WorkspaceError

    registry = ReportingWorkspaceRegistry(tmp_path, secret='s' * 32)
    scope = _scope()
    registry.resolve(scope)
    workspace = ReportingWorkspaceRouter(registry)
    thread = scope.workspace_key
    path = 'template/output.docx'
    if fault == 'missing':
        assert await _existing_template_bytes(workspace, thread, path) is None
        assert not await workspace.apath_exists(thread, path)
    elif fault == 'directory':
        await workspace.aensure_directory(thread, path)
        with pytest.raises(WorkspaceError):
            await _existing_template_bytes(workspace, thread, path)
        assert await workspace.apath_exists(thread, path)
    else:
        await workspace.awrite_bytes(thread, path, b'existing identity')
        async def unavailable(*args, **kwargs):
            raise WorkspaceError('未知读取故障')
        with monkeypatch.context() as patch:
            patch.setattr(workspace, 'afile_bytes', unavailable)
            with pytest.raises(WorkspaceError, match='未知读取故障'):
                await _existing_template_bytes(workspace, thread, path)
        assert (await workspace.afile_bytes(thread, path))[0] == b'existing identity'


@pytest.mark.anyio
async def test_saved_reference_refresh_child_publication_then_editor_export_keeps_child_template(tmp_path, monkeypatch):
    runtime, arguments, scope, durable, _, _, _, _ = await native_quality_inputs(tmp_path, publication_fixture=True)
    await runtime.issue_http_publication(**arguments)
    runtime.workspace_registry.resolve(scope)
    parent = ReportEditorContext.model_validate(durable.payload['reportEditorContexts']['2'])

    class Repository(ConcurrentRepository):
        child = None

        async def get(self, run_id):
            if self.child is not None and run_id == self.child.external_run_id:
                return self.child
            assert run_id == scope.run_id
            return await super().get(run_id)

        async def get_run(self, run_id):
            assert run_id in (scope.run_id, self.child.external_run_id)
            return {'database': scope.database, 'company_id': scope.company_id,
                'entrypoint': 'report_revision', 'caller_run_id': scope.run_id,
                'caller_session_id': scope.session_id}

        async def apply(self, run_id, command, *, expected_version):
            if self.child is not None and run_id == self.child.external_run_id:
                result = ReportingStateReducer.apply(self.child, command, expected_version)
                self.child = result.state
                return result
            return await super().apply(run_id, command, expected_version=expected_version)

    repository = Repository(parent)
    repository.state = ReportingRunState.initial(report_run_id=scope.run_id,
        external_run_id=scope.external_run_id, thread_id=scope.caller_thread_id,
        owner_user_id=scope.user_id, payload=durable.payload)
    runtime.state_repository = repository
    runtime._scope = lambda _: scope.as_state()
    runtime._state = lambda _: {}
    editor = ReportEditorService(state_repository=repository,
        workspace_registry=runtime.workspace_registry, workspace=runtime.workspace_service,
        artifact_persistence=runtime.artifact_persistence, download_grants=runtime.download_grants,
        editor_grants=runtime.editor_grants, public_base_url='http://reports.test',
        recalculation_runtime=runtime)
    async def forbidden_generic(*args, **kwargs):
        pytest.fail('模板子修订不能改用通用渲染')
    editor.report_tools = SimpleNamespace(_render_report_pair=forbidden_generic)
    document = await editor.read_document(parent)
    task = await register_refresh_request(editor, parent, RecalculationRequest(
        requestId='template-child-lifecycle', parentRevision=parent.revision,
        expectedSha256=document.sha256, operation='refresh_data'), parent_report_revision='initial')
    assert task.saved_revision_reference is not None
    child_id = execution_run_id(scope, task.basis_id, task.refresh_binding.report_revision, 'a' * 64)
    execution = ReportRevisionExecution(sourceScope=scope, executionRunId=child_id,
        basisId=task.basis_id, reportRevision=task.refresh_binding.report_revision,
        parentReportRevision='initial', planningHash='a' * 64, outputRevision=3,
        requestedOutputs=('docx',), savedRevisionBinding={'taskId': task.task_id,
            'inputHash': task.input_hash, 'contextSha256': task.context_sha256,
            'reference': task.saved_revision_reference})
    root = f'报表/智能分析/{child_id}/document/revision-3'
    markdown_path, manifest_path = root + '/report.md', root + '/manifest.json'
    markdown = '# 子修订冻结标题\n\n| 项目 | 金额 |\n| --- | ---: |\n| 收入 | 1234.5600 |\n'
    template = template_bytes()
    template_input = ReportFileInput(filename='冻结模板.docx', **identity('inputs/template.docx', template).model_dump())
    manifest = ReportArtifactManifest.model_validate_json((await editor.workspace.afile_bytes(
        scope.workspace_key, parent.artifact_manifest.path))[0])
    manifest = ReportArtifactManifest.model_validate(manifest.model_dump(mode='json', by_alias=True) | {
            'reportId': scope.run_id, 'revision': 3, 'reportBasisId': task.basis_id,
            'markdown': identity(markdown_path, markdown.encode()).model_dump() | {'mediaType': 'text/markdown'},
            'traceIndex': None, 'charts': ()})
    # 子执行的分析产物在此以耐久身份夹具登记；不调用业务库或外部模型。
    context_path = f'报表/智能分析/{scope.run_id}/revision-executions/{child_id}/dataset-contexts.json'
    files = {'inputs/template.docx': template, markdown_path: markdown.encode(),
        context_path: json.dumps({'execution': execution.model_dump(mode='json', by_alias=True),
            'datasetContexts': []}).encode(),
        manifest_path: manifest.model_dump_json(by_alias=True).encode()}
    for path, raw in files.items():
        await editor.workspace.awrite_bytes(scope.workspace_key, path, raw)
    repository.state.payload.setdefault('reportEditorRevisionReservations', {})[child_id] = 3
    repository.child = ReportingRunState.initial(report_run_id=child_id, external_run_id=child_id,
        thread_id=scope.caller_thread_id, owner_user_id=scope.user_id, payload={
            'reportRevisionExecution': execution.model_dump(mode='json', by_alias=True),
            'deliveryFormat': 'document', 'requestMaterials': {'fileInputs': [],
                'templateInput': template_input.model_dump(mode='json', by_alias=True)},
            'approvedOutline': {'title': '子修订冻结标题'},
            'artifacts': [identity(path, raw).model_dump() for path, raw in files.items()],
            'result': {'markdown': identity(markdown_path, files[markdown_path]).model_dump(),
                'manifest': identity(manifest_path, files[manifest_path]).model_dump()}}).model_copy(update={'revision': 3})
    loads = []

    async def preferences(run_id, management_scope, *, user_id, thread_id):
        assert management_scope.database == scope.database and user_id == scope.user_id
        assert thread_id == scope.caller_thread_id
        loads.append(run_id)
        signer = '子修订冻结编制' if run_id == child_id else '根报告错误编制'
        return {'generatedDate': '2026-11-10', 'contentHash': 'd' * 64,
            'resolvedFormats': {format: resolve_format_preferences(
                FormatPreferences(common={'signer': signer, 'dateFormat': 'iso'}), format)
                for format in ('word', 'pdf')}}

    runtime.configuration_provider = SimpleNamespace(load_run_preferences=preferences)
    run = RunContext(run_id=scope.run_id, session_id=scope.session_id, user_id=scope.user_id)
    rendered = await render_template_delivery(runtime, run,
        {'revision': 3, 'markdownPath': markdown_path, 'artifactManifest': identity(manifest_path, files[manifest_path]).model_dump()},
        SimpleNamespace(title='子修订冻结标题'), 'docx', execution=execution)
    assert rendered.get('wordPath'), rendered
    repository.child.payload['result']['renderedDocument'] = rendered
    old_word = (await editor.workspace.afile_bytes(scope.workspace_key, rendered['wordPath']))[0]
    # 真实Router恢复已登记模板文件不重新生成；幂等登记不推进已有状态版本。
    from smart_reporting.reporting.workflow.runtime import template_delivery
    def forbidden_generation(*args, **kwargs):
        pytest.fail('只读恢复不得重新生成模板文件')
    with monkeypatch.context() as patch:
        patch.setattr(template_delivery, 'fill_report_template', forbidden_generation)
        version = repository.child.state_version
        restored = await render_template_delivery(runtime, run,
            {'revision': 3, 'markdownPath': markdown_path,
                'artifactManifest': identity(manifest_path, files[manifest_path]).model_dump()},
            SimpleNamespace(title='子修订冻结标题'), 'docx', execution=execution, restore_only=True)
        assert restored['wordSha256'] == rendered['wordSha256']
        assert repository.child.state_version == version
    delivery = await editor.recalculation_delivery(parent, task.task_id)
    assert delivery['delivery']['word']['downloadUrl']
    state = await repository.get(scope.run_id)
    child_context = ReportEditorContext.model_validate(state.payload['reportEditorContexts']['3'])
    assert child_context.workflow_run_id == parent.workflow_run_id
    assert child_context.markdown_path.startswith(f'报表/智能分析/{child_id}/')
    document = await editor.read_document(child_context)
    result = await editor.export_revision(child_context, expected_sha256=document.sha256)
    assert result['revision'] == 4
    latest = ReportEditorContext.model_validate((await repository.get(scope.run_id)).payload['reportEditorContexts']['4'])
    binding = latest.job['_templateSource']
    assert binding['materialRunId'] == child_id and binding['originRevision'] == 3
    actual = latest.job['render']['word']
    raw = (await editor.workspace.afile_bytes(scope.workspace_key, actual['path']))[0]
    assert hashlib.sha256(raw).hexdigest() == actual['sha256']
    doc = Document(BytesIO(raw))
    text = ''.join(doc._element.body.xpath('.//w:t/text()'))
    assert all(value in text for value in ('子修订冻结标题', '子修订冻结编制', '2026-11-10', '1234.5600'))
    assert '根报告错误编制' not in text
    assert doc.styles['Normal'].font.size.pt == 17 and len(doc._element.body.xpath('.//w:tbl')) == 1
    assert set(loads) == {child_id}
    assert (await editor.workspace.afile_bytes(scope.workspace_key, rendered['wordPath']))[0] == old_word
    for path, expected in files.items():
        assert (await editor.workspace.afile_bytes(scope.workspace_key, path))[0] == expected

"""编辑器模板只从同作用域耐久原材料恢复，不信任job裸路径。"""

from copy import deepcopy
from hashlib import sha256
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.workflow.revision_execution import (
    ReportRevisionExecution,
    execution_run_id,
)
from smart_reporting.reporting.workflow.scope import resolve_reporting_workflow_scope

from .test_report_editor import _context


@pytest.fixture
def anyio_backend():
    return 'asyncio'


def fixture():
    context = _context()
    scope = resolve_reporting_workflow_scope(run_id=context.workflow_run_id,
        session_id=context.scope['sessionId'], user_id=context.scope['userId'], stored_scope=context.scope)
    content = b'current controlled template'
    identity = {'filename': 'template.docx', 'path': 'inputs/template.docx', 'size': len(content), 'sha256': sha256(content).hexdigest(), 'mediaType': None}
    root = SimpleNamespace(external_run_id=scope.external_run_id, thread_id=scope.caller_thread_id,
        owner_user_id=scope.user_id, payload={'requestMaterials': {'fileInputs': [], 'templateInput': identity},
            'reportEditorContexts': {'1': context.model_dump(mode='json', by_alias=True)}})
    states = {scope.run_id: root}
    rows = {scope.run_id: {'database': scope.database, 'company_id': scope.company_id}}
    repository = SimpleNamespace(get=AsyncMock(side_effect=lambda key: states.get(key)), get_run=AsyncMock(side_effect=lambda key: rows.get(key)))
    workspace = SimpleNamespace(afile_bytes=AsyncMock(return_value=(content, 'application/octet-stream')))
    provider = SimpleNamespace(load_run_preferences=AsyncMock(return_value={'generatedDate': '2026-11-13', 'resolvedFormats': {}}))
    editor = SimpleNamespace(state_repository=repository, workspace=workspace,
        recalculation_runtime=SimpleNamespace(configuration_provider=provider))
    return editor, context, scope, root, states, rows, identity, content


def child(f):
    editor, context, scope, root, states, rows, identity, content = f
    run_id = execution_run_id(scope, 'basis-child', 'refresh-child', 'a' * 64)
    execution = ReportRevisionExecution(sourceScope=scope, executionRunId=run_id, basisId='basis-child',
        reportRevision='refresh-child', parentReportRevision='initial', planningHash='a' * 64,
        outputRevision=2, requestedOutputs=['docx'])
    derived = context.model_copy(update={'revision': 2, 'job_id': run_id, 'job': {**context.job, 'jobId': run_id}})
    root.payload['reportEditorContexts']['2'] = derived.model_dump(mode='json', by_alias=True)
    root.payload['reportEditorRevisionReservations'] = {run_id: 2}
    states[run_id] = SimpleNamespace(external_run_id=run_id, thread_id=scope.caller_thread_id,
        owner_user_id=scope.user_id, revision=2, payload={'requestMaterials': deepcopy(root.payload['requestMaterials']),
            'reportRevisionExecution': execution.model_dump(mode='json', by_alias=True)})
    rows[run_id] = {'entrypoint': 'report_revision', 'caller_run_id': scope.run_id,
        'caller_session_id': scope.session_id, 'database': scope.database, 'company_id': scope.company_id}
    return derived, run_id


@pytest.mark.anyio
async def test_initial_source_uses_durable_template_and_frozen_configuration_without_recalculation():
    from smart_reporting.report_editor.template_source import resolve_editor_template

    editor, context, scope, root, _, _, identity, content = fixture()
    result = await resolve_editor_template(editor, context=context, source_context=context)
    assert result.identity.model_dump(mode='json', by_alias=True) == identity
    assert result.content == content and result.material_run_id == context.workflow_run_id
    assert result.binding == {'schemaVersion': 1, 'originRevision': 1, 'originContextSha256': context.digest(),
        'materialRunId': context.workflow_run_id, 'identity': identity}
    editor.recalculation_runtime.configuration_provider.load_run_preferences.assert_awaited_once_with(
        scope.run_id, __import__('smart_reporting.management.models', fromlist=['ManagementScope']).ManagementScope(scope.database, scope.company_id),
        user_id=scope.user_id, thread_id=scope.caller_thread_id)
    assert result.configuration['generatedDate'] == '2026-11-13'
    assert root.payload['reportEditorContexts']['1'] == context.model_dump(mode='json', by_alias=True)


@pytest.mark.anyio
async def test_confirmed_absent_template_does_not_read_files_or_preferences():
    from smart_reporting.report_editor.template_source import resolve_editor_template

    editor, context, _, root, *_ = fixture()
    root.payload['requestMaterials']['templateInput'] = None
    assert await resolve_editor_template(editor, context=context, source_context=context) is None
    editor.workspace.afile_bytes.assert_not_awaited()
    editor.recalculation_runtime.configuration_provider.load_run_preferences.assert_not_awaited()


@pytest.mark.anyio
@pytest.mark.parametrize('fault', ['bytes', 'registration', 'context-scope', 'invalid-material', 'bare-job'])
async def test_bound_source_fault_never_silently_falls_back(fault):
    from smart_reporting.report_editor.template_source import resolve_editor_template

    editor, context, scope, root, states, rows, identity, content = fixture()
    if fault == 'bytes':
        editor.workspace.afile_bytes.return_value = (b'changed', 'application/octet-stream')
    elif fault == 'registration':
        rows[scope.run_id]['company_id'] = 'foreign'
    elif fault == 'context-scope':
        context = context.model_copy(update={'report_id': 'foreign-report'})
    elif fault == 'invalid-material':
        root.payload['requestMaterials']['templateInput'] = {'path': identity['path']}
    else:
        root.payload['requestMaterials']['templateInput'] = None
        context = context.model_copy(update={'job': {**context.job, '_templateSource': {'identity': identity}}})
    with pytest.raises(ReportingError):
        await resolve_editor_template(editor, context=context, source_context=context)


@pytest.mark.anyio
async def test_derived_source_requires_registered_execution_and_uses_child_snapshot():
    from smart_reporting.report_editor.template_source import resolve_editor_template

    f = fixture()
    derived, run_id = child(f)
    editor, original, _, _, states, _, identity, _ = f
    states[run_id].payload['requestMaterials']['templateInput'] = {**identity, 'filename': 'child-template.docx'}
    result = await resolve_editor_template(editor, context=derived, source_context=derived)
    assert result.material_run_id == run_id and result.identity.filename == 'child-template.docx'
    assert editor.recalculation_runtime.configuration_provider.load_run_preferences.await_args.args[0] == run_id


@pytest.mark.anyio
@pytest.mark.parametrize('fault', ['child-row', 'child-owner', 'execution', 'reservation', 'two-children'])
async def test_derived_source_rejects_broken_or_ambiguous_child_identity(fault):
    from smart_reporting.report_editor.template_source import resolve_editor_template

    f = fixture()
    derived, run_id = child(f)
    editor, _, _, root, states, rows, *_ = f
    if fault == 'child-row':
        rows[run_id]['caller_run_id'] = 'foreign'
    elif fault == 'child-owner':
        states[run_id].owner_user_id = 'foreign'
    elif fault == 'execution':
        states[run_id].payload['reportRevisionExecution']['outputRevision'] = 3
    elif fault == 'reservation':
        root.payload['reportEditorRevisionReservations'][run_id] = 3
    else:
        root.payload['reportEditorRevisionReservations']['another-child'] = 2
    with pytest.raises(ReportingError):
        await resolve_editor_template(editor, context=derived, source_context=derived)


@pytest.mark.anyio
async def test_manual_revisions_keep_original_binding_and_history_source():
    from smart_reporting.report_editor.template_source import resolve_editor_template

    f = fixture()
    derived, run_id = child(f)
    editor, original, _, root, *_ = f
    bound = await resolve_editor_template(editor, context=derived, source_context=derived)
    manual = derived.model_copy(update={'revision': 3, 'job': {**derived.job, '_templateSource': bound.binding}})
    root.payload['reportEditorContexts']['3'] = manual.model_dump(mode='json', by_alias=True)
    result = await resolve_editor_template(editor, context=manual, source_context=manual)
    assert result.binding == bound.binding and result.material_run_id == run_id
    old = await resolve_editor_template(editor, context=manual, source_context=original)
    assert old.binding['originRevision'] == 1 and old.material_run_id == original.workflow_run_id


@pytest.mark.anyio
@pytest.mark.parametrize('fault', ['origin-hash', 'origin-report', 'material-run', 'identity', 'chain'])
async def test_manual_binding_cannot_self_authorize_foreign_materials(fault):
    from smart_reporting.report_editor.template_source import resolve_editor_template

    editor, original, _, root, *_ = fixture()
    bound = await resolve_editor_template(editor, context=original, source_context=original)
    binding = deepcopy(bound.binding)
    if fault == 'origin-hash':
        binding['originContextSha256'] = 'f' * 64
    elif fault == 'origin-report':
        raw = root.payload['reportEditorContexts']['1']
        raw['reportId'] = 'foreign'
        binding['originContextSha256'] = type(original).model_validate(raw).digest()
    elif fault == 'material-run':
        binding['materialRunId'] = 'foreign'
    elif fault == 'identity':
        binding['identity']['path'] = 'arbitrary.docx'
    else:
        root.payload['reportEditorContexts']['1']['job']['_templateSource'] = deepcopy(binding)
        binding['originContextSha256'] = type(original).model_validate(root.payload['reportEditorContexts']['1']).digest()
    manual = original.model_copy(update={'revision': 3, 'job': {**original.job, '_templateSource': binding}})
    root.payload['reportEditorContexts']['3'] = manual.model_dump(mode='json', by_alias=True)
    with pytest.raises(ReportingError):
        await resolve_editor_template(editor, context=manual, source_context=manual)


@pytest.mark.anyio
async def test_old_missing_preferences_return_none_without_loading_current_defaults():
    from smart_reporting.management.models import ManagementError
    from smart_reporting.report_editor.template_source import resolve_editor_template

    editor, context, *_ = fixture()
    editor.recalculation_runtime.configuration_provider.load_run_preferences.side_effect = ManagementError('management_run_identity_missing', 'legacy', 404)
    result = await resolve_editor_template(editor, context=context, source_context=context)
    assert result.configuration is None


@pytest.mark.anyio
@pytest.mark.parametrize('fault', ['null-binding', 'empty-material', 'absolute-path', 'template-output-with-missing-material'])
async def test_malformed_declaration_or_template_output_never_becomes_absent(fault):
    from smart_reporting.report_editor.template_source import resolve_editor_template

    editor, context, _, root, *_ = fixture()
    if fault == 'null-binding':
        context = context.model_copy(update={'job': {**context.job, '_templateSource': None}})
    elif fault == 'empty-material':
        root.payload['requestMaterials']['templateInput'] = {}
    elif fault == 'absolute-path':
        root.payload['requestMaterials']['templateInput']['path'] = '/outside/template.docx'
    else:
        context = context.model_copy(update={'job': {**context.job, 'render': {
            'word': {'path': 'reports/template/revision-1/' + 'a' * 20 + '/report.docx'}}}})
        root.payload['requestMaterials']['templateInput'] = None
    root.payload['reportEditorContexts']['1'] = context.model_dump(mode='json', by_alias=True)
    with pytest.raises(ReportingError):
        await resolve_editor_template(editor, context=context, source_context=context)


@pytest.mark.anyio
async def test_legacy_context_restores_only_registered_checkpoint_and_no_recalculation_runtime():
    import json

    from smart_reporting.report_editor.template_source import resolve_editor_template

    editor, context, scope, root, _, _, identity, content = fixture()
    root.payload.pop('requestMaterials')
    raw = json.dumps({'templateInput': {'identity': identity}}).encode()
    checkpoint = {'path': f'报表/分析计划/{scope.run_id}/detailed-analysis-context.json', 'size': len(raw), 'sha256': sha256(raw).hexdigest()}
    root.payload['workflowCheckpoint'] = {'files': [checkpoint]}
    editor.recalculation_runtime = None
    editor.workspace.afile_bytes.side_effect = lambda thread, path: (raw if path == checkpoint['path'] else content, 'application/octet-stream')
    result = await resolve_editor_template(editor, context=context, source_context=context)
    assert result.content == content and result.configuration is None


@pytest.mark.anyio
async def test_configuration_identity_errors_fail_closed():
    from smart_reporting.management.models import ManagementError
    from smart_reporting.report_editor.template_source import resolve_editor_template

    editor, context, *_ = fixture()
    editor.recalculation_runtime.configuration_provider.load_run_preferences.side_effect = ManagementError('management_run_identity_conflict', 'foreign', 403)
    with pytest.raises(ReportingError):
        await resolve_editor_template(editor, context=context, source_context=context)


@pytest.mark.anyio
async def test_child_legacy_materials_read_child_registered_checkpoint_in_same_workspace():
    import json

    from smart_reporting.report_editor.template_source import resolve_editor_template

    f = fixture()
    derived, run_id = child(f)
    editor, _, scope, _, states, _, identity, content = f
    states[run_id].payload.pop('requestMaterials')
    raw = json.dumps({'templateInput': {'identity': identity}}).encode()
    checkpoint = {'path': f'报表/分析计划/{run_id}/detailed-analysis-context.json', 'size': len(raw), 'sha256': sha256(raw).hexdigest()}
    states[run_id].payload['workflowCheckpoint'] = {'files': [checkpoint]}
    editor.workspace.afile_bytes.side_effect = lambda thread, path: (raw if path == checkpoint['path'] else content, 'application/octet-stream')
    result = await resolve_editor_template(editor, context=derived, source_context=derived)
    assert result.content == content and result.material_run_id == run_id
    assert editor.workspace.afile_bytes.await_args_list[0].args == (scope.workspace_key, checkpoint['path'])


@pytest.mark.anyio
async def test_legacy_registered_checkpoint_changed_bytes_cannot_fall_back():
    from smart_reporting.report_editor.template_source import resolve_editor_template

    editor, context, scope, root, *_ = fixture()
    root.payload.pop('requestMaterials')
    root.payload['workflowCheckpoint'] = {'files': [{'path': f'报表/分析计划/{scope.run_id}/detailed-analysis-context.json',
        'size': 999, 'sha256': 'a' * 64}]}
    with pytest.raises(ReportingError):
        await resolve_editor_template(editor, context=context, source_context=context)


@pytest.mark.anyio
async def test_derived_document_context_comes_from_exact_child_outline_and_frozen_date():
    from smart_reporting.report_editor.template_source import resolve_editor_template

    f = fixture()
    derived, run_id = child(f)
    editor, _, _, root, states, *_ = f
    root.payload['approvedOutline'] = {'title': '不得采用的根标题'}
    states[run_id].payload['approvedOutline'] = {'title': '本次派生冻结标题'}
    result = await resolve_editor_template(editor, context=derived, source_context=derived)
    assert result.document_context == {'title': '本次派生冻结标题', 'generatedDate': '2026-11-13'}
    editor.recalculation_runtime.configuration_provider.load_run_preferences.return_value = None
    assert (await resolve_editor_template(editor, context=derived, source_context=derived)).document_context == {'title': '本次派生冻结标题'}


@pytest.mark.anyio
async def test_registered_source_document_context_precedes_outline_and_is_detached():
    from smart_reporting.report_editor.template_source import resolve_editor_template

    editor, context, _, root, *_ = fixture()
    document_context = {'title': '原修订冻结标题', 'generatedDate': '2026-11-13', 'periodLabel': '2026年'}
    context = context.model_copy(update={'job': {**context.job, '_documentContext': document_context}})
    root.payload['reportEditorContexts']['1'] = context.model_dump(mode='json', by_alias=True)
    root.payload['approvedOutline'] = {'title': '不覆盖已冻结标题'}
    result = await resolve_editor_template(editor, context=context, source_context=context)
    assert result.document_context == document_context
    result.document_context['title'] = 'caller mutation'
    assert document_context['title'] == '原修订冻结标题'


@pytest.mark.anyio
@pytest.mark.parametrize('legacy', ['no-get-run', 'no-run-registration'])
async def test_confirmed_unbound_old_editor_needs_no_new_run_registration(legacy):
    from smart_reporting.report_editor.template_source import resolve_editor_template

    editor, context, _, root, _, rows, *_ = fixture()
    root.payload['requestMaterials']['templateInput'] = None
    if legacy == 'no-get-run':
        del editor.state_repository.get_run
    else:
        rows.clear()
    assert await resolve_editor_template(editor, context=context, source_context=context) is None
    root.payload['requestMaterials']['templateInput'] = fixture()[-2]
    with pytest.raises(ReportingError):
        await resolve_editor_template(editor, context=context, source_context=context)


@pytest.mark.anyio
async def test_known_frozen_title_survives_missing_provider_without_inventing_date():
    from smart_reporting.report_editor.template_source import resolve_editor_template

    editor, context, _, root, *_ = fixture()
    editor.recalculation_runtime = None
    root.payload['approvedOutline'] = {'title': '旧报告已登记标题'}
    result = await resolve_editor_template(editor, context=context, source_context=context)
    assert result.document_context == {'title': '旧报告已登记标题'} and result.configuration is None


@pytest.mark.anyio
@pytest.mark.parametrize('derived_source', [False, True])
async def test_conflicting_frozen_dates_are_rejected_for_root_and_child(derived_source):
    from smart_reporting.report_editor.template_source import resolve_editor_template

    f = fixture()
    editor, context, _, root, *_ = f
    if derived_source:
        context, _ = child(f)
    context = context.model_copy(update={'job': {**context.job, '_documentContext': {
        'title': '冻结标题', 'generatedDate': '2000-01-01'}}})
    root.payload['reportEditorContexts'][str(context.revision)] = context.model_dump(mode='json', by_alias=True)
    with pytest.raises(ReportingError):
        await resolve_editor_template(editor, context=context, source_context=context)

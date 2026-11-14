"""便携真实 policy 模块回归；POLICY_ADOPTION_SOURCE 指定被测完整源。"""
import importlib.util
import os
from types import SimpleNamespace

import pytest

from smart_reporting.reporting.saved_revision_reference import SavedRevisionExecutionBinding
from smart_reporting.reporting.workflow.scope import resolve_reporting_workflow_scope


@pytest.fixture
def policy_module():
    path = os.environ.get('POLICY_ADOPTION_SOURCE')
    if path is None:
        from smart_reporting.reporting.workflow import policy_adoption
        return policy_adoption
    spec = importlib.util.spec_from_file_location('smart_reporting.reporting.workflow._binding_regression', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def binding():
    task_id = 'recalc-' + 'a' * 32
    return SavedRevisionExecutionBinding.model_validate({'taskId': task_id,
        'inputHash': 'b' * 64, 'contextSha256': 'c' * 64, 'reference': {
            'taskId': task_id, 'contextSha256': 'c' * 64, 'workflowRunId': 'parent', 'reportId': 'parent',
            'revision': 2, 'file': {'path': f'report/editor-inputs/{task_id}/current.md',
                'filename': 'current.md', 'mediaType': 'text/markdown', 'size': 1, 'sha256': 'd' * 64}}})


def test_policy_binding_preserves_legacy_hash_and_roundtrips(policy_module):
    module = policy_module
    source = resolve_reporting_workflow_scope(run_id='parent', session_id='session', user_id='user')
    target = module._target_scope(source, 'child')
    legacy = dict(requestId='policy-1', sourceScope=source, scope=target, parentBasisId='basis-1',
        basisId='basis-2', registrationSha256='a' * 64, outputRevision=3, requestedOutputs=['pdf'])
    old = module.PolicyAdoptionExecution(**legacy)
    assert old.saved_revision_binding is None
    assert 'savedRevisionBinding' not in old.model_dump(mode='json', by_alias=True)
    saved = binding()
    bound = module.PolicyAdoptionExecution(**legacy, savedRevisionBinding=saved)
    persisted = bound.model_dump(mode='json', by_alias=True)
    assert persisted['savedRevisionBinding'] == saved.model_dump(mode='json', by_alias=True)
    assert module.PolicyAdoptionExecution.model_validate(persisted).saved_revision_binding == saved
    assert module._saved_binding(SimpleNamespace(saved_revision_reference=saved.reference,
        task_id=saved.task_id, input_hash=saved.input_hash, context_sha256=saved.context_sha256)) == saved


@pytest.mark.anyio
async def test_prepare_persists_binding_and_keeps_newbase_materials_and_preferences(policy_module, monkeypatch):
    module = policy_module
    from smart_reporting.report_editor import revisions
    from smart_reporting.preferences import runtime as preferences
    source = resolve_reporting_workflow_scope(run_id='parent', session_id='session', user_id='user')
    saved = binding()
    task = SimpleNamespace(saved_revision_reference=saved.reference, task_id=saved.task_id,
        input_hash=saved.input_hash, context_sha256=saved.context_sha256)
    state = SimpleNamespace(revision=2)
    adoption = SimpleNamespace(target_run_id='child', parent_basis_id='basis-1', model_dump=lambda **kwargs: {})
    basis = SimpleNamespace(id='basis-2', request_summary=SimpleNamespace(requested_outputs=('pdf',)))
    materials = {'fileInputs': [], 'templateInput': None}
    calls, persisted = [], {}
    async def source_state(*args):
        return state, {'workflow_id': 'workflow'}
    async def registration(*args):
        return adoption, basis
    async def read_task(*args):
        return task
    async def load_materials(*args):
        calls.append('materials_read')
        return materials
    async def copy_materials(*args):
        calls.append('materials_copy')
    async def copy_saved(*args):
        assert args[-1] == saved.reference
        calls.append('saved_copy')
    async def reserve(*args):
        return SimpleNamespace(state=SimpleNamespace(payload={'reportEditorRevisionReservations': {'child': 3}}))
    async def inherit(*args):
        assert args[-2:] == ('child', 'policy_adoption')
        calls.append('preferences_inherited')
    async def register_run(**kwargs):
        persisted['run'] = kwargs
    async def create(**kwargs):
        persisted['child'] = kwargs
    async def require(_runtime, _context, execution):
        assert execution.saved_revision_binding == saved
        calls.append('execution_rechecked')
    async def register_selections(*args, **kwargs):
        calls.append('selections_registered')
    monkeypatch.setattr(module, '_source_scope', lambda *args: source)
    monkeypatch.setattr(module, '_source_state', source_state)
    monkeypatch.setattr(module, '_registration', registration)
    monkeypatch.setattr(module, '_read_policy_adoption_task', read_task, raising=False)
    monkeypatch.setattr(module, 'load_revision_materials', load_materials)
    monkeypatch.setattr(module, 'copy_revision_materials', copy_materials)
    monkeypatch.setattr(module, '_copy_saved_revision', copy_saved, raising=False)
    monkeypatch.setattr(module, 'require_policy_adoption_execution', require)
    monkeypatch.setattr(revisions, 'apply_editor_command', reserve)
    monkeypatch.setattr(preferences, 'inherit_execution_preferences', inherit)
    runtime = SimpleNamespace(report_basis_service=SimpleNamespace(register_adoption_selections=register_selections),
        state_repository=SimpleNamespace(register_run=register_run, get_or_create=create),
        workspace_service=SimpleNamespace(registry=SimpleNamespace(resolve=lambda scope: None)))
    execution = await module.prepare_policy_adoption_execution(runtime, None, request_id=saved.task_id)
    payload = persisted['child']['payload']
    assert execution.saved_revision_binding == saved
    assert payload['reportPolicyAdoptionExecution']['savedRevisionBinding'] == saved.model_dump(mode='json', by_alias=True)
    assert payload['requestMaterials'] == materials
    assert persisted['run']['entrypoint'] == 'policy_adoption'
    assert {'materials_read', 'materials_copy', 'saved_copy', 'preferences_inherited', 'execution_rechecked'} <= set(calls)

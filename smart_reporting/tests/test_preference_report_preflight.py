"""真实会话和耐久材料绑定后才能验收草稿，不以可构造context代替授权。"""
import base64
import hashlib
import json
from copy import deepcopy
from types import SimpleNamespace

import pytest

from smart_reporting.management.models import ManagementError
from smart_reporting.report_editor import ReportEditorService
from smart_reporting.report_editor.service import (
    InMemoryReportEditorRepository,
    ReportEditorGrantService,
)
from smart_reporting.reporting.host_workspace import (
    ReportingWorkspaceRegistry,
    ReportingWorkspaceRouter,
)
from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.tests.test_office_revision_safety import ConcurrentRepository
from smart_reporting.reporting.tests.test_report_editor import _context, _scope
from smart_reporting.tests.test_preference_preflight import _inputs
from smart_reporting.workspace import WorkspaceError

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return 'asyncio'


async def bound_case(tmp_path):
    from smart_reporting.management.preference_report_preflight import (
        BoundPreferencePreflightService,
    )

    scope = _scope()
    registry = ReportingWorkspaceRegistry(tmp_path / 'host', secret='s' * 32)
    identity = registry.resolve(scope)
    draft, materials = _inputs(identity.root)
    job = deepcopy(materials.state)
    job['jobId'] = 'job-1'
    job['render'] = {'markdown': next(item for item in job['sources'] if item['path'] == 'report.md')}
    context = _context('report.md').model_copy(update={'job': job})
    repository = ConcurrentRepository(context)
    repository.state = repository.state.model_copy(update={'external_run_id': scope.external_run_id,
        'thread_id': scope.caller_thread_id})
    registered = {'report_run_id': scope.run_id, 'external_run_id': scope.external_run_id,
        'agno_run_id': scope.run_id, 'agno_session_id': scope.session_id,
        'thread_id': scope.caller_thread_id, 'owner_user_id': scope.user_id,
        'database': scope.database, 'company_id': scope.company_id}
    async def get_run(_):
        return registered.copy()
    repository.get_run = get_run
    editor = ReportEditorService(state_repository=repository, workspace_registry=registry,
        workspace=ReportingWorkspaceRouter(registry))
    grants = ReportEditorGrantService(InMemoryReportEditorRepository(), secret='g' * 32)
    grant, _ = await grants.issue(context)
    token, _ = await grants.exchange(grant)
    class Preferences:
        valid = True
        def __init__(self):
            self.auth = self
        async def authenticate(self, raw):
            if raw != 'admin-session' or not self.valid:
                raise ManagementError('management_session_invalid', '管理会话无效。', 401)
            return SimpleNamespace(account_id='admin-fixture', auth_version=1)
        async def detail(self, raw):
            await self.authenticate(raw)
            return {'draft': deepcopy(draft)}
    preferences = Preferences()
    service = BoundPreferencePreflightService(preferences=preferences, editor=editor, grants=grants)
    args = {'admin_session': 'admin-session', 'editor_session': token,
        'expected_draft_version': 7, 'expected_draft_hash': draft['contentHash'],
        'expected_context_hash': context.digest()}
    return service, args, preferences, repository, context, identity.root, registered


@pytest.mark.parametrize('fault', ['admin', 'editor', 'restricted', 'context', 'run', 'revision'])
async def test_bound_preflight_requires_both_real_sessions_and_exact_scope_before_generation(tmp_path, monkeypatch, fault):
    from smart_reporting.management import preference_report_preflight as module

    service, args, _, repository, context, _, registered = await bound_case(tmp_path)
    if fault == 'admin':
        args['admin_session'] = 'fake'
    elif fault == 'editor':
        args['editor_session'] = 'fake'
    elif fault in {'restricted', 'revision'}:
        grant_context = context if fault == 'restricted' else context.model_copy(update={'revision': 2})
        grant, _ = await service.grants.issue(grant_context, capabilities={} if fault == 'restricted' else None)
        args['editor_session'], _ = await service.grants.exchange(grant)
        if fault == 'revision':
            repository.state.payload['reportEditorContexts']['2'] = context.model_dump(mode='json', by_alias=True)
    elif fault == 'context':
        args['expected_context_hash'] = '0' * 64
    else:
        registered['agno_session_id'] = 'foreign'
    async def forbidden(*a, **kw):
        pytest.fail('授权/身份核验前不得生成')
    monkeypatch.setattr(module, 'run_office_engine', forbidden)
    with pytest.raises((ManagementError, ReportingError, WorkspaceError)):
        await service.run(**args)


@pytest.mark.parametrize('fault', ['identity_missing', 'changed', 'symlink', 'retired'])
async def test_bound_preflight_rejects_unregistered_or_changed_source_before_generation(tmp_path, monkeypatch, fault):
    from smart_reporting.management import preference_report_preflight as module

    service, args, _, repository, context, root, _ = await bound_case(tmp_path)
    if fault == 'identity_missing':
        changed = context.model_copy(update={'job': {**context.job, 'render': {}}})
        repository.state.payload['reportEditorContexts']['1'] = changed.model_dump(mode='json', by_alias=True)
        grant, _ = await service.grants.issue(changed)
        args['editor_session'], _ = await service.grants.exchange(grant)
        args['expected_context_hash'] = changed.digest()
    elif fault == 'changed':
        (root / 'report.md').write_text('changed')
    elif fault == 'symlink':
        source = root / 'report.md'
        data = source.read_bytes()
        source.unlink()
        foreign = tmp_path / 'outside.md'
        foreign.write_bytes(data)
        source.symlink_to(foreign)
    else:
        repository.state.payload['reportEditorRetiredSources'] = {'1': context.digest()}
    async def forbidden(*a, **kw): pytest.fail('来源无效前不得生成')
    monkeypatch.setattr(module, 'run_office_engine', forbidden)
    with pytest.raises((ManagementError, ReportingError, WorkspaceError)):
        await service.run(**args)


@pytest.mark.parametrize('change', ['draft', 'session', 'editor_session', 'context', 'detail_session', 'source', 'state_only'])
async def test_bound_preflight_postcheck_preserves_actual_output_and_distinguishes_unrelated_state(tmp_path, monkeypatch, change):
    from smart_reporting.management import preference_report_preflight as module

    service, args, preferences, repository, _, root, _ = await bound_case(tmp_path)
    async def generated(function, draft, materials, **kwargs):
        assert kwargs['formats'] == ('md', 'pdf', 'word')
        assert not service.editor._source_lifecycle_locks  # 仅复制快照期间持锁。
        assert materials.workspace != root and (materials.workspace / 'report.md').is_file()
        if change == 'draft':
            previous = preferences.detail
            async def newer(raw):
                result = await previous(raw)
                result['draft']['version'] = 8
                return result
            preferences.detail = newer
        elif change == 'session':
            preferences.valid = False
        elif change == 'editor_session':
            service.grants.repository.sessions.clear()
        elif change == 'context':
            repository.state.payload['reportEditorContexts']['1']['note'] = 'changed during generation'
        elif change == 'detail_session':
            previous = preferences.detail
            async def denied(raw):
                preferences.valid = False
                return await previous(raw)
            preferences.detail = denied
        elif change == 'source':
            (root / 'chart.png').write_bytes(b'changed')
        else:
            repository.state = repository.state.model_copy(update={'state_version': repository.state.state_version + 1})
        data = b'actual-rendered-artifact'
        return {'status': 'incomplete', 'canApply': False, 'formats': {'md': {'artifact': {
            'base64': base64.b64encode(data).decode(), 'size': len(data), 'sha256': hashlib.sha256(data).hexdigest()}}}}
    monkeypatch.setattr(module, 'run_office_engine', generated)
    result = await service.run(**args)
    assert result['formats']['md']['artifact']['size'] == len(b'actual-rendered-artifact')
    assert result['binding']['valid'] is (change == 'state_only')
    assert result['binding']['artifactAccessAuthorized'] is (change == 'state_only')
    assert result['canApply'] is False
    assert result['status'] == ('incomplete' if change == 'state_only' else 'failed')
    assert str(root) not in str(result) and 'admin-session' not in str(result)


async def native_case(tmp_path, format, *, frozen_document=False, checkpoint=None, execution=None,
    revision=1, spec_date='2026-11-13', spec_period='2026年10月'):
    service, args, preferences, repository, context, root, registered = await bound_case(tmp_path)
    _, original = _inputs(root)
    def write(path, content):
        (root / path).write_bytes(content)
        return {'path': path, 'size': len(content), 'sha256': hashlib.sha256(content).hexdigest()}
    def saved(path, value):
        return write(path, json.dumps(value, ensure_ascii=False).encode())
    artifact = write('report.' + format, b'published-native-artifact')
    job = {'jobId': context.job_id, 'sources': [], 'render': context.job['render']}
    if frozen_document:
        job['_documentContext'] = deepcopy(original.state['_documentContext'])
    binding = {'workflowRunId': context.workflow_run_id, 'revision': revision, 'execution': execution}
    spec = {'title': '月度业务核对', 'period': spec_period}
    if spec_date is not None:
        spec['generatedDate'] = spec_date
    if format == 'xlsx':
        spec.update(sheets=original.sheets, sourceMapping={'datasets': {}, 'cells': [], 'claims': []})
    else:
        spec.update(schemaVersion='pptx-native-input/1', binding=binding,
            slides=original.slides, chartFiles=[item for item in original.state['sources'] if item['path'] == 'chart.png'])
    spec_identity = saved('native-spec.json', spec)
    receipt = {'artifact': artifact, 'spec': spec_identity}
    if format == 'xlsx' and execution is not None:
        receipt['execution'] = execution
    elif format == 'pptx':
        receipt.update(schemaVersion='pptx-native-receipt/1', binding=binding)
    receipt_identity = saved('report.' + format + '.receipt.json', receipt)
    if format == 'pptx':
        job['pptxNativeInput'] = {'binding': binding, 'artifact': artifact, 'spec': spec_identity, 'receipt': receipt_identity}
    context = context.model_copy(update={'job': job, 'delivery_format': format, 'revision': revision,
        format + '_path': artifact['path'], format + '_size': artifact['size'], format + '_sha256': artifact['sha256']})
    repository.state.payload['reportEditorContexts'][str(revision)] = context.model_dump(mode='json', by_alias=True)
    repository.state.payload.update(artifacts=[artifact, spec_identity, receipt_identity], workflowCheckpoint=checkpoint)
    grant, _ = await service.grants.issue(context)
    args['editor_session'], _ = await service.grants.exchange(grant)
    args['expected_context_hash'] = context.digest()
    return service, args, repository, context, root, spec, spec_identity, receipt_identity


@pytest.mark.parametrize('format,checkpoint', [('xlsx', None), ('xlsx', {'revision': 99, 'files': []}), ('pptx', None)])
async def test_native_preflight_recovers_registered_spec_without_fabricating_document_context(tmp_path, monkeypatch, format, checkpoint):
    from smart_reporting.management import preference_report_preflight as module

    service, args, _, _, _, _, _, _ = await native_case(tmp_path, format, checkpoint=checkpoint)
    async def generated(function, draft, materials, **kwargs):
        assert kwargs['formats'] == (format,)
        assert materials.state['_documentContext'] == {'title': '月度业务核对', 'periodLabel': '2026年10月', 'generatedDate': '2026-11-13'}
        if format == 'xlsx':
            assert materials.sheets[0]['rows'][1] == ['收入', 1234.56]
            assert materials.state['_workbookSourceMapping'] == {'datasets': {}, 'cells': [], 'claims': []}
        else:
            assert materials.slides[0]['chartPath'] == 'chart.png'
            assert (materials.workspace / 'chart.png').is_file()
        return {'status': 'incomplete', 'canApply': False, 'formats': {format: {'artifact': {'size': 1}}}}
    monkeypatch.setattr(module, 'run_office_engine', generated)
    result = await service.run(**args)
    assert result['binding']['valid'] is True
    assert result['formats'][format]['artifact']['size'] == 1
    assert result['binding']['nativeSources'][format]['spec']['path'] == 'native-spec.json'


async def test_no_frozen_document_or_native_input_returns_unavailable_without_generation(tmp_path, monkeypatch):
    from smart_reporting.management import preference_report_preflight as module

    service, args, _, repository, context, _, _ = await bound_case(tmp_path)
    context = context.model_copy(update={'job': {key: value for key, value in context.job.items() if key != '_documentContext'}})
    repository.state.payload['reportEditorContexts']['1'] = context.model_dump(mode='json', by_alias=True)
    grant, _ = await service.grants.issue(context)
    args['editor_session'], _ = await service.grants.exchange(grant)
    args['expected_context_hash'] = context.digest()
    async def forbidden(*a, **kw): pytest.fail('没有完整正式格式时不得生成')
    monkeypatch.setattr(module, 'run_office_engine', forbidden)
    result = await service.run(**args)
    assert result['status'] == 'incomplete' and result['canApply'] is False
    assert result['binding']['valid'] is True
    assert all(item['availability'] == 'unavailable' and item['artifact'] is None for item in result['formats'].values())


async def test_snapshot_reads_state_again_under_existing_source_lock(tmp_path, monkeypatch):
    from smart_reporting.management import preference_report_preflight as module

    service, args, _, repository, _, _, _ = await bound_case(tmp_path)
    retained = service.editor._ensure_sources_retained
    async def change_before_snapshot(context):
        await retained(context)
        assert service.editor._source_lifecycle_locks
        repository.state.payload['requestMaterials'] = {'templateInput': {'path': 'registered-template.docx'}}
    monkeypatch.setattr(service.editor, '_ensure_sources_retained', change_before_snapshot)
    async def generated(function, draft, materials, **kwargs):
        assert kwargs['formats'] == ('md',)
        return {'status': 'incomplete', 'canApply': False, 'formats': {}}
    monkeypatch.setattr(module, 'run_office_engine', generated)
    result = await service.run(**args)
    assert result['binding']['valid'] is True
    assert result['binding']['availabilityIssues']['word']['code'] == 'management_preference_template_input_unavailable'


@pytest.mark.parametrize('fault', ['execution', 'duplicate_chart', 'extra_chart', 'unsafe_chart'])
async def test_pptx_native_input_rejects_unregistered_execution_or_chart_set(tmp_path, monkeypatch, fault):
    from smart_reporting.management import preference_report_preflight as module

    execution = {'executionRunId': 'foreign', 'outputRevision': 1} if fault == 'execution' else None
    service, args, repository, context, root, spec, _, _ = await native_case(tmp_path, 'pptx', execution=execution)
    if fault != 'execution':
        if fault == 'duplicate_chart':
            spec['chartFiles'].append(deepcopy(spec['chartFiles'][0]))
        elif fault == 'extra_chart':
            spec['slides'] = [{'title': 'No chart', 'bullets': ['正式事实']}]
        else:
            chart = spec['chartFiles'][0]
            (root / 'chart.svg').write_bytes((root / chart['path']).read_bytes())
            chart['path'] = 'chart.svg'
            spec['slides'][0]['chartPath'] = 'chart.svg'
        pointer = context.job['pptxNativeInput']
        content = json.dumps(spec, ensure_ascii=False).encode()
        (root / 'native-spec.json').write_bytes(content)
        pointer['spec'].update(size=len(content), sha256=hashlib.sha256(content).hexdigest())
        receipt = {'schemaVersion': 'pptx-native-receipt/1', 'binding': pointer['binding'], 'artifact': pointer['artifact'], 'spec': pointer['spec']}
        content = json.dumps(receipt, ensure_ascii=False).encode()
        (root / pointer['receipt']['path']).write_bytes(content)
        pointer['receipt'].update(size=len(content), sha256=hashlib.sha256(content).hexdigest())
        repository.state.payload['reportEditorContexts']['1'] = context.model_dump(mode='json', by_alias=True)
        grant, _ = await service.grants.issue(context)
        args['editor_session'], _ = await service.grants.exchange(grant)
        args['expected_context_hash'] = context.digest()
    async def forbidden(*a, **kw): pytest.fail('未核验的原生输入不得生成')
    monkeypatch.setattr(module, 'run_office_engine', forbidden)
    result = await service.run(**args)
    assert result['canApply'] is False
    assert result['formats']['pptx']['availability'] == 'unavailable'
    assert result['binding']['availabilityIssues']['pptx']['code'] == 'pptx_native_input_unavailable'


@pytest.mark.parametrize('fault', [None, 'missing', 'changed', 'initial', 'scope', 'wrong_output', 'schema'])
async def test_pptx_preflight_requires_exact_registered_policy_adoption_execution(tmp_path, monkeypatch, fault):
    from smart_reporting.management import preference_report_preflight as module
    from smart_reporting.reporting.workflow.policy_adoption import PolicyAdoptionExecution
    from smart_reporting.reporting.workflow.scope import resolve_reporting_workflow_scope

    target = _scope()
    source = resolve_reporting_workflow_scope(run_id='parent-report', session_id='parent-session', user_id=target.user_id,
        dependencies={'AgentOS 报表工作流': {'database': target.database, 'companyId': target.company_id,
            'threadId': target.caller_thread_id}})
    execution = PolicyAdoptionExecution(requestId='policy-change', sourceScope=source, scope=target,
        parentBasisId='old-basis', basisId='new-basis', registrationSha256='a' * 64,
        outputRevision=2, requestedOutputs=('pptx',)).model_dump(mode='json', by_alias=True)
    if fault == 'scope':
        execution['scope']['user_id'] = 'foreign-user'
    elif fault == 'wrong_output':
        execution['requestedOutputs'] = ['xlsx']
    elif fault == 'schema':
        del execution['registrationSha256']
    service, args, repository, _, _, _, _, _ = await native_case(tmp_path, 'pptx',
        execution=None if fault == 'initial' else execution, revision=2)
    if fault != 'missing':
        repository.state.payload['reportPolicyAdoptionExecution'] = deepcopy(execution)
    if fault == 'changed':
        repository.state.payload['reportPolicyAdoptionExecution']['basisId'] = 'changed-basis'
    async def generated(function, draft, materials, **kwargs):
        assert fault is None, '原生输入必须对应完整已登记的执行'
        assert kwargs['formats'] == ('pptx',)
        return {'status': 'incomplete', 'canApply': False, 'formats': {'pptx': {'artifact': {'size': 1}}}}
    monkeypatch.setattr(module, 'run_office_engine', generated)
    result = await service.run(**args)
    if fault is None:
        assert result['binding']['nativeSources']['pptx']['binding']['execution']['basisId'] == 'new-basis'
    else:
        assert result['formats']['pptx']['availability'] == 'unavailable'
    assert result['canApply'] is False


async def test_legacy_workbook_spec_uses_only_same_frozen_document_date(tmp_path, monkeypatch):
    from smart_reporting.management import preference_report_preflight as module

    service, args, _, _, _, _, _, _ = await native_case(tmp_path, 'xlsx', frozen_document=True, spec_date=None)
    async def generated(function, draft, materials, **kwargs):
        assert kwargs['formats'] == ('md', 'pdf', 'word', 'xlsx')
        assert materials.state['_documentContext']['generatedDate'] == '2026-11-13'
        return {'status': 'incomplete', 'canApply': False, 'formats': {}}
    monkeypatch.setattr(module, 'run_office_engine', generated)
    result = await service.run(**args)
    assert result['binding']['valid'] is True
    assert result['binding']['nativeSources']['xlsx']['sourceMapping'] == {'datasets': {}, 'cells': [], 'claims': []}


@pytest.mark.parametrize('format', ['xlsx', 'pptx'])
async def test_native_formats_keep_their_frozen_period_instead_of_document_display_label(tmp_path, monkeypatch, format):
    from smart_reporting.management import preference_report_preflight as module

    service, args, _, _, _, _, _, _ = await native_case(tmp_path, format,
        frozen_document=True, spec_period='2026-10-01 至 2026-10-31')
    async def generated(function, draft, materials, **kwargs):
        assert kwargs['formats'] == ('md', 'pdf', 'word', format)
        assert materials.state['_documentContext']['periodLabel'] == '2026年10月'
        assert materials.state['_nativeDocumentContexts'][format] == {'title': '月度业务核对',
            'periodLabel': '2026-10-01 至 2026-10-31', 'generatedDate': '2026-11-13'}
        return {'status': 'incomplete', 'canApply': False, 'formats': {format: {'artifact': {'size': 1}}}}
    monkeypatch.setattr(module, 'run_office_engine', generated)
    result = await service.run(**args)
    assert result['binding']['valid'] is True
    assert result['formats'][format]['artifact']['size'] == 1


@pytest.mark.parametrize('format', ['xlsx', 'pptx'])
async def test_template_revision_cannot_pass_generic_native_preflight(tmp_path, monkeypatch, format):
    from smart_reporting.management import preference_report_preflight as module

    service, args, repository, _, _, _, _, _ = await native_case(tmp_path, format)
    repository.state.payload['requestMaterials'] = {'templateInput': {'path': 'frozen-template.' + format}}
    async def forbidden(*a, **kw):
        pytest.fail('模板专属生成未接线，不得用通用原生生成冒充验收')
    monkeypatch.setattr(module, 'run_office_engine', forbidden)
    result = await service.run(**args)
    assert result['formats'][format]['availability'] == 'unavailable'
    assert result['canApply'] is False


async def test_unavailable_preflight_rejects_boolean_draft_version_before_generation(tmp_path, monkeypatch):
    from smart_reporting.management import preference_report_preflight as module

    service, args, preferences, repository, context, _, _ = await bound_case(tmp_path)
    context = context.model_copy(update={'job': {key: value for key, value in context.job.items() if key != '_documentContext'}})
    repository.state.payload['reportEditorContexts']['1'] = context.model_dump(mode='json', by_alias=True)
    grant, _ = await service.grants.issue(context)
    args['editor_session'], _ = await service.grants.exchange(grant)
    args['expected_context_hash'] = context.digest()
    args['expected_draft_version'] = True
    previous = preferences.detail
    async def first_version(raw):
        result = await previous(raw)
        result['draft']['version'] = 1
        return result
    monkeypatch.setattr(preferences, 'detail', first_version)
    async def forbidden(*a, **kw):
        pytest.fail('版本类型无效时不得生成')
    monkeypatch.setattr(module, 'run_office_engine', forbidden)
    with pytest.raises(ManagementError) as caught:
        await service.run(**args)
    assert caught.value.code == 'management_version_conflict'

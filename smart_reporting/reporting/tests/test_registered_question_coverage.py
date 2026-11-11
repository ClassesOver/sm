"""C31：原始问题、正式结果与当前正文支持之间的覆盖检查。"""

import pytest

from smart_reporting.reporting.semantics.request_types import ReportQuestion
from smart_reporting.reporting.tests.test_registered_claim_support import native_quality_inputs
from smart_reporting.reporting.trace.quality_bundle import evaluate_quality_bundle
from smart_reporting.reporting.workflow.questions import request_questions


def questions():
    return request_questions('核对预算并解释变化', questions=(
        ReportQuestion(id='q-budget', text='预算是多少？'),
        ReportQuestion(id='q-reason', text='为什么变化？'),
    ))


@pytest.mark.anyio
async def test_c31_native_quality_keeps_original_questions_and_does_not_equate_value_with_answer(tmp_path):
    index, markdown, sources = await native_quality_inputs(tmp_path)
    quality = evaluate_quality_bundle(index, markdown, sources, authorization_scope_hash='a' * 64,
        questions=questions())
    coverage = {item.question_id: item for item in quality.registered_question_coverage}
    assert set(coverage) == {'q-budget', 'q-reason'}
    assert coverage['q-budget'].status == 'partial'
    assert coverage['q-budget'].subject_ids == (quality.claim_support[0].subject_id,)
    assert 'question_completion_mapping_unavailable' in coverage['q-budget'].issue_codes
    assert coverage['q-reason'].status == 'unavailable'
    assert coverage['q-reason'].issue_codes


@pytest.mark.anyio
@pytest.mark.parametrize('fault', ['missing', 'tampered', 'wrong_basis', 'semantic_conflict'])
async def test_native_question_coverage_rejects_inapplicable_sources(tmp_path, fault):
    change = (lambda item: item.update(metricVersion={'metricId': 'foreign', 'revision': 1})) if fault == 'semantic_conflict' else None
    index, markdown, sources = await native_quality_inputs(tmp_path, change=change)
    if fault == 'missing':
        sources.clear()
    elif fault == 'tampered':
        sources = {key: raw + b' ' for key, raw in sources.items()}
    elif fault == 'wrong_basis':
        index = index.model_copy(update={'report_basis_id': 'foreign-basis'})
    quality = evaluate_quality_bundle(index, markdown, sources, authorization_scope_hash='a' * 64,
        questions=questions())
    coverage = {item.question_id: item for item in quality.registered_question_coverage}
    assert coverage['q-budget'].status != 'answered'
    assert coverage['q-budget'].issue_codes
    assert coverage['q-reason'].status == 'unavailable'


@pytest.mark.anyio
@pytest.mark.parametrize('case', ['complete', 'wrong_basis', 'wrong_question_hash', 'wrong_subject', 'wrong_fact', 'inference'])
async def test_only_current_server_approved_completion_mapping_can_mark_question_answered(tmp_path, case):
    from smart_reporting.reporting.semantics.question_coverage import RegisteredAnswerPlan
    from smart_reporting.reporting.workflow.answer_review import questions_sha256

    index, markdown, sources = await native_quality_inputs(tmp_path)
    required = request_questions('核对预算', questions=(ReportQuestion(id='q-budget', text='预算是多少？'),))
    subject, = index.subject_bindings
    plan = RegisteredAnswerPlan(reportBasisId=index.report_basis_id, questionSetSha256=questions_sha256(required),
        criteria=[{'questionId': 'q-budget', 'condition': '预算是多少？', 'kind': 'fact',
            'subjectIds': [subject.subject_id], 'factRefs': ['fact-budget']}])
    if case == 'wrong_basis':
        plan = plan.model_copy(update={'report_basis_id': 'foreign-basis'})
    elif case == 'wrong_question_hash':
        plan = plan.model_copy(update={'question_set_sha256': 'f' * 64})
    elif case in {'wrong_subject', 'wrong_fact', 'inference'}:
        patch = {'subject_ids': ('sub-' + 'f' * 16,)} if case == 'wrong_subject' else {
            'fact_refs': ('foreign-fact',)} if case == 'wrong_fact' else {'kind': 'inference'}
        plan = plan.model_copy(update={'criteria': (plan.criteria[0].model_copy(update=patch),)})
    quality = evaluate_quality_bundle(index, markdown, sources, authorization_scope_hash='a' * 64,
        questions=required, registered_answer_plan=plan)
    coverage, = quality.registered_question_coverage
    assert (coverage.status == 'answered') == (case == 'complete')
    assert bool(coverage.issue_codes) == (case != 'complete')


def test_native_answer_plan_freezes_once_with_registered_basis_and_questions():
    from smart_reporting.reporting.semantics.question_coverage import RegisteredAnswerPlan
    from smart_reporting.reporting.workflow.answer_review import questions_sha256
    from smart_reporting.reporting.workflow.state import ReportingRunState, apply

    state = ReportingRunState.initial(report_run_id='report-1', external_run_id='external-1',
        thread_id='thread-1', owner_user_id='user-1')
    required = questions()
    state = state.model_copy(update={'payload': {'questionSpecs': required.model_dump(mode='json', by_alias=True)}})
    plan = RegisteredAnswerPlan(reportBasisId='basis-1', questionSetSha256=questions_sha256(required), criteria=[])
    command = {'name': 'freeze_registered_answer_plan', 'commandId': 'native-plan',
        'payload': {'basisId': 'basis-1', 'plan': plan.model_dump(mode='json', by_alias=True)}}
    result = apply(state, command, state.state_version)
    assert result.state.payload['registeredAnswerPlan'] == plan.model_dump(mode='json', by_alias=True)
    altered = plan.model_copy(update={'criteria': (RegisteredAnswerPlan.model_validate({
        **plan.model_dump(by_alias=True), 'criteria': [{'questionId': 'q-budget', 'condition': '预算是多少？',
            'kind': 'fact', 'subjectIds': ['sub-1'], 'factRefs': ['fact-budget']}]}).criteria[0],)})
    with pytest.raises(ValueError):
        apply(result.state, {**command, 'commandId': 'altered', 'payload': {'basisId': 'basis-1',
            'plan': altered.model_dump(mode='json', by_alias=True)}}, result.state.state_version)
    foreign = plan.model_copy(update={'report_basis_id': 'foreign'})
    with pytest.raises(ValueError):
        apply(state, {**command, 'commandId': 'foreign', 'payload': {
            'basisId': 'basis-1', 'plan': foreign.model_dump(mode='json', by_alias=True)}}, state.state_version)


@pytest.mark.anyio
@pytest.mark.parametrize('fault', ['none', 'provider', 'freeze', 'receipt', 'foreign_basis'])
async def test_actual_publication_freezes_and_recovers_native_completion_plan(tmp_path, monkeypatch, fault):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from smart_reporting.reporting.semantics.question_coverage import RegisteredAnswerPlan
    from smart_reporting.reporting.tests.lineage_fixtures.manifest import register_trace_manifest
    from smart_reporting.reporting.tests.test_registered_claim_support import native_quality_inputs
    from smart_reporting.reporting.trace.contracts_v1 import RevisionTraceIndexV1
    from smart_reporting.reporting.trace.quality_bundle import QualityBundle
    from smart_reporting.reporting.workflow.answer_review import questions_sha256
    from smart_reporting.reporting.workflow.runtime import publication as publication_module
    from smart_reporting.reporting.workflow.state import ReportingRunState, apply

    runtime, arguments, scope, durable, _, _, files, index = await native_quality_inputs(tmp_path, publication_fixture=True)
    required = request_questions('核对预算', questions=(ReportQuestion(id='q-budget', text='预算是多少？'),))
    state = ReportingRunState.initial(report_run_id=index.report_id, external_run_id='external-1',
        thread_id='caller-thread', owner_user_id='user-1').model_copy(update={'payload': {
            'questionSpecs': required.model_dump(mode='json', by_alias=True)}})
    durable.payload = state.payload
    provider_calls, commands = [], []

    async def provider(context):
        provider_calls.append(context)
        if fault == 'provider':
            raise OSError('injected native provider failure')
        return RegisteredAnswerPlan(reportBasisId='foreign' if fault == 'foreign_basis' else context.report_basis_id,
            questionSetSha256=questions_sha256(context.questions), criteria=[{
                'questionId': 'q-budget', 'condition': '预算是多少？', 'kind': 'fact',
                'subjectIds': [context.supports[0].subject_id], 'factRefs': ['fact-budget']}])

    async def command(_context, value):
        nonlocal state
        commands.append(value.name)
        if fault == 'freeze' and value.name == 'freeze_registered_answer_plan':
            raise OSError('injected native freeze failure')
        result = apply(state, value, state.state_version)
        state = result.state
        durable.payload = state.payload
        if fault == 'receipt' and value.name == 'freeze_registered_answer_plan':
            return SimpleNamespace(state=state.model_copy(update={'report_run_id': 'foreign'}))
        return result

    original_get = runtime.state_repository.get

    async def get(run_id):
        return durable if run_id == index.report_id else await original_get(run_id)

    runtime.state_repository.get = get
    runtime.registered_answer_plan_provider = provider
    runtime._apply_durable_command = command
    runtime._state = lambda _: {}
    runtime._scope = lambda _: scope.as_state()
    runtime._build_drilldown_metrics = AsyncMock(return_value=())
    monkeypatch.setattr(publication_module, 'build_csv_trace_index', lambda **_: index)
    file = next(file for file in index.files if file.resource_id == index.markdown_file_resource_id)
    from smart_reporting.reporting.delivery.artifacts_v1 import ArtifactFile

    params = dict(report_basis_id=index.report_basis_id, handles=(), lineage=(), revision=1,
        markdown_artifact=ArtifactFile.model_validate(file.model_dump(exclude={'resource_id'})),
        run_context=SimpleNamespace(run_id=index.report_id), markdown=files[file.path].decode())
    identity = await runtime._write_trace_index('reports/report.manifest.json', **params)
    stored = RevisionTraceIndexV1.model_validate_json(await runtime.workspace_service.read_limited_regular_file(
        scope.workspace_key, identity.path, max_bytes=16 * 1024 * 1024))
    quality_file = next(file for file in stored.files if file.path.endswith('/quality-bundle-v1.json'))
    quality = QualityBundle.model_validate_json(await runtime.workspace_service.read_limited_regular_file(
        scope.workspace_key, quality_file.path, max_bytes=16 * 1024 * 1024))
    assert (quality.registered_question_coverage[0].status == 'answered') == (fault == 'none')
    if fault == 'none':
        await runtime._write_trace_index('reports/report.manifest.json', **params)
        assert len(provider_calls) == 1 and commands.count('freeze_registered_answer_plan') == 1
    else:
        assert any(issue.code == 'registered_answer_plan_unavailable' for issue in quality.issues)
    manifest = await register_trace_manifest(runtime.workspace_service, scope.workspace_key, stored, overwrite=True)
    arguments['output']['artifactManifest'] = manifest.model_dump(mode='json', by_alias=True)
    output = await runtime.issue_http_publication(**arguments)
    assert output['pdf']['downloadUrl'] and output['word']['downloadUrl']
    if fault == 'none':
        import hashlib

        from smart_reporting.report_editor import ReportEditorContext, ReportEditorService

        runtime.workspace_registry.resolve(scope)
        editor = ReportEditorService(state_repository=runtime.state_repository,
            workspace_registry=runtime.workspace_registry, workspace=runtime.workspace_service,
            trace_cursor_secret=b'trace-cursor-secret-32-bytes-ok!')
        context = ReportEditorContext.model_validate(durable.payload['reportEditorContexts']['2'])
        loaded = await editor.trace.require_index(context)
        md = next(file for file in loaded.files if file.resource_id == loaded.markdown_file_resource_id)
        markdown = (await editor.trace._read_registered_file(context, md, max_bytes=16 * 1024 * 1024)).decode()
        result = await editor.trace.validate(context, markdown, hashlib.sha256(markdown.encode()).hexdigest())
        assert result['quality']['registeredQuestionCoverage'][0]['status'] == 'answered'
        changed = markdown.replace('本期预算', '全年实际收入')
        reviewed = await editor.trace.validate(context, changed, hashlib.sha256(changed.encode()).hexdigest())
        assert reviewed['quality']['registeredQuestionCoverage'][0]['status'] != 'answered'


@pytest.mark.anyio
async def test_missing_comparison_period_cannot_pass_a_value_only_completion_mapping(tmp_path, monkeypatch):
    from smart_reporting.reporting.semantics.models import Period
    from smart_reporting.reporting.tests import test_registered_claim_support as fixtures

    original_inputs = fixtures.analysis_inputs

    def inputs():
        analysis, context, result = original_inputs()
        request = context.request.model_copy(update={'comparison_period': Period(start='2025-11-01', end='2025-12-01')})
        return analysis, context.model_copy(update={'request': request}), result

    monkeypatch.setattr(fixtures, 'analysis_inputs', inputs)
    index, markdown, sources = await fixtures.native_quality_inputs(tmp_path)
    quality = evaluate_quality_bundle(index, markdown, sources, authorization_scope_hash='a' * 64)
    coverage, = quality.registered_question_coverage
    assert coverage.status == 'partial'
    assert 'registered_question_period_unavailable' in coverage.issue_codes

"""正式正文支持关系不经过旧业务Profile断言。"""

from types import SimpleNamespace

import pytest

from smart_reporting.reporting.delivery.draft_v1 import ReportDraftBlock
from smart_reporting.reporting.tests.test_http_publication_lineage import _publication_fixture
from smart_reporting.reporting.tests.test_registered_analysis_facts import analysis_inputs
from smart_reporting.reporting.trace.claim_semantics import freeze_interpretation
from smart_reporting.reporting.trace.quality_bundle import evaluate_quality_bundle
from smart_reporting.reporting.trace.semantic_bindings import (
    NumberReferenceResolver,
    anchor_bound_numbers,
    render_bound_numbers,
)
from smart_reporting.reporting.trace.subject_builder import build_claim_subject_bindings


async def native_quality_inputs(tmp_path, *, change=None, issue_codes=(), publication_fixture=False, knowledge_candidates=None, basis_id=None):
    from smart_reporting.reporting.tests import test_registered_analysis_facts

    def inputs():
        analysis, context, result = analysis_inputs()
        result = result.model_copy(update={'issue_codes': issue_codes, **({'basis_id': basis_id} if basis_id else {})})
        calculation = context.calculations[0].model_copy(update={'results': (result,), **({'request': context.calculations[0].request.model_copy(update={'basis_id': basis_id})} if basis_id else {})})
        return analysis, context.model_copy(update={'calculations': (calculation,), **({'basis_id': basis_id} if basis_id else {})}), result

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(test_registered_analysis_facts, 'analysis_inputs', inputs)
        fixture = await _publication_fixture(tmp_path, registered_result=True)
    runtime, arguments, scope, durable, artifacts, grants, contents, index = fixture
    entry, = index.fact_files
    file = next(file for file in index.files if file.resource_id == entry.file_resource_id)
    content = contents[file.path].decode()
    result = analysis_inputs()[2]
    token = '{{value:' + result.fact_id + ':value:' + result.unit + '}}'
    text = '本期预算合计为' + token + '。'
    markdown, numbers, notices = render_bound_numbers(text, (content,), key='native-support')
    anchored = anchor_bound_numbers(markdown, numbers)
    reference = NumberReferenceResolver((content,)).resolve(token)
    interpretation = {'claimId': numbers[0].claim_id, 'period': reference['period'],
        'periodEvidence': ['本期'], 'claimKind': 'fact', 'kindEvidence': ['预算合计'],
        'metricVersion': result.metric_version.model_dump(by_alias=True), 'metricEvidence': ['预算'],
        'statistic': 'period_total', 'statisticEvidence': ['合计']}
    if change:
        change(interpretation)
    receipt = freeze_interpretation(anchored, numbers[0].claim_id, interpretation, reference=reference,
        knowledge_candidates=knowledge_candidates)
    numbers = (numbers[0].model_copy(update={'semantic_receipt': receipt}),)
    block = ReportDraftBlock(blockId='native-support', markdown=markdown, numberReferences=numbers, reviewNotices=notices)
    subjects = build_claim_subject_bindings((SimpleNamespace(section_code='section_001', blocks=(block,), claims=()),),
        {result.fact_id: (entry.analysis_id, '/metricContext/calculations/0/results/0')},
        {entry.analysis_id: file.resource_id})
    index = index.model_copy(update={'subject_bindings': subjects, 'tables': ()})
    if publication_fixture:
        import hashlib

        from smart_reporting.reporting.tests.lineage_fixtures.manifest import (
            register_trace_manifest,
        )
        from smart_reporting.reporting.trace.index_builder import encode_trace_index

        markdown_file = next(file for file in index.files if file.resource_id == index.markdown_file_resource_id)
        raw = anchored.encode()
        index = index.model_copy(update={'files': tuple(file.model_copy(update={
            'size': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()})
            if file.resource_id == markdown_file.resource_id else file for file in index.files)})
        contents[markdown_file.path] = raw
        await runtime.workspace_service.awrite_bytes(scope.workspace_key, markdown_file.path, raw, overwrite=True)
        await runtime.workspace_service.awrite_bytes(scope.workspace_key, 'reports/trace-index-v1.json',
            encode_trace_index(index), overwrite=True)
        identity = await register_trace_manifest(runtime.workspace_service, scope.workspace_key, index, overwrite=True)
        arguments['output']['artifactManifest'] = identity.model_dump(mode='json', by_alias=True)
        return runtime, arguments, scope, durable, artifacts, grants, contents, index
    return index, anchored, {file.resource_id: contents[file.path] for file in index.files}


@pytest.mark.anyio
@pytest.mark.parametrize('case', ['supported', 'conflicting', 'inference'])
async def test_native_support_reaches_actual_editor_validation(tmp_path, case):
    import hashlib
    import json

    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from smart_reporting.report_editor import (
        ReportEditorContext,
        ReportEditorService,
        create_report_editor_router,
    )

    def change(item):
        if case == 'conflicting':
            item['metricVersion'] = {'metricId': 'foreign-metric', 'revision': 1}
        elif case == 'inference':
            item['claimKind'] = 'inference'

    runtime, arguments, scope, durable, _, _, _, _ = await native_quality_inputs(
        tmp_path, change=change, publication_fixture=True)
    publication = await runtime.issue_http_publication(**arguments)
    runtime.workspace_registry.resolve(scope)
    editor = ReportEditorService(state_repository=runtime.state_repository,
        workspace_registry=runtime.workspace_registry, workspace=runtime.workspace_service,
        trace_cursor_secret=b'trace-cursor-secret-32-bytes-ok!')
    context = ReportEditorContext.model_validate(durable.payload['reportEditorContexts']['2'])
    index = await editor.trace.require_index(context)
    file = next(file for file in index.files if file.resource_id == index.markdown_file_resource_id)
    markdown = (await editor.trace._read_registered_file(context, file, max_bytes=16 * 1024 * 1024)).decode()
    result = await editor.trace.validate(context, markdown, hashlib.sha256(markdown.encode()).hexdigest())
    assert result['quality']['reportBasisId'] == index.report_basis_id
    assert result['quality']['claimSupport'][0]['supportStatus'] == {
        'supported': 'supported', 'conflicting': 'conflicted', 'inference': 'unverified',
    }[case]
    assert result['subjects'][0]['supportStatus'] == {
        'supported': 'supported', 'conflicting': 'conflicting', 'inference': 'unknown',
    }[case]
    # 精确小数在来源返回边界按字符串传输，不能因 JSON 序列化失败丢失整份支持判断。
    assert json.loads(json.dumps(result))['subjects'][0]['factValue'] == '300.123456789123456789'
    app = FastAPI()
    app.include_router(create_report_editor_router(runtime.editor_grants, editor=editor, cookie_secure=False))
    grant, _ = await runtime.editor_grants.issue(context)
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://reports.test') as client:
        opened = await client.get('/reports/v1/editor/open/' + grant, follow_redirects=False)
        assert opened.status_code == 303
        response = await client.post(f'/reports/v1/editor/{context.report_id}/{context.revision}/api/sources/validate',
            json={'markdown': markdown, 'draftSha256': result['draftSha256']},
            headers={'Origin': 'http://reports.test',
                'X-CSRF-Token': runtime.editor_grants.csrf_token(client.cookies['report_editor_session'])})
    assert response.status_code == 200
    assert response.json()['subjects'][0]['factValue'] == '300.123456789123456789'
    assert response.json()['quality']['claimSupport'] == result['quality']['claimSupport']
    assert publication['pdf']['downloadUrl'] and publication['word']['downloadUrl']


@pytest.mark.anyio
async def test_native_quality_records_basis_and_original_fact_without_constructing_old_compiler(tmp_path, monkeypatch):
    from smart_reporting.reporting.trace import quality_bundle

    index, markdown, sources = await native_quality_inputs(tmp_path)

    def retired_compiler(*args, **kwargs):
        raise AssertionError('正式结果不得创建旧Profile编译器')

    monkeypatch.setattr(quality_bundle, 'AssertionCompiler', retired_compiler)
    quality = evaluate_quality_bundle(index, markdown, sources, authorization_scope_hash='a' * 64)
    support, = quality.claim_support
    assert quality.report_basis_id == index.report_basis_id
    assert support.fact_refs == ('fact-budget',)
    assert support.kind == 'fact' and support.support_status == 'supported'
    assert quality.assertions == ()


@pytest.mark.anyio
@pytest.mark.parametrize('case', ['inference', 'recommendation', 'unknown', 'wrong_metric', 'wrong_statistic', 'ungrounded'])
async def test_native_fact_does_not_certify_unsupported_business_meaning(tmp_path, case):
    def change(item):
        if case in {'inference', 'recommendation', 'unknown'}:
            item['claimKind'] = case
        elif case == 'wrong_metric':
            item['metricVersion'] = {'metricId': 'different', 'revision': 1}
        elif case == 'wrong_statistic':
            item['statistic'] = 'period_average'
        else:
            item['metricEvidence'] = ['原文没有的指标']

    index, markdown, sources = await native_quality_inputs(tmp_path, change=change)
    quality = evaluate_quality_bundle(index, markdown, sources, authorization_scope_hash='a' * 64)
    support, = quality.claim_support
    assert support.support_status != 'supported'
    assert support.evidence_refs == ()
    assert any(issue.subject_id == support.subject_id for issue in quality.issues)


@pytest.mark.anyio
@pytest.mark.parametrize('fault', ['missing', 'changed', 'foreign_basis', 'wrong_pointer'])
async def test_native_claim_keeps_explicit_unverified_state_when_source_is_rejected(tmp_path, fault):
    index, markdown, sources = await native_quality_inputs(tmp_path)
    ref = index.subject_bindings[0].fact_refs[0]
    if fault == 'missing':
        sources.pop(ref.file_resource_id)
    elif fault == 'changed':
        sources[ref.file_resource_id] += b' '
    elif fault == 'foreign_basis':
        index = index.model_copy(update={'report_basis_id': 'foreign-basis'})
    else:
        subject = index.subject_bindings[0]
        index = index.model_copy(update={'subject_bindings': (subject.model_copy(update={
            'fact_refs': (ref.model_copy(update={'json_pointer': '/metricContext/calculations/0/results/8'}),)}),)})
    quality = evaluate_quality_bundle(index, markdown, sources, authorization_scope_hash='a' * 64)
    support, = quality.claim_support
    assert support.support_status == 'unverified'
    assert not quality.assertions


@pytest.mark.anyio
async def test_registered_quality_cannot_be_current_under_another_basis(tmp_path):
    from smart_reporting.reporting.trace.quality_bundle import quality_bundle_is_current

    index, markdown, sources = await native_quality_inputs(tmp_path)
    quality = evaluate_quality_bundle(index, markdown, sources, authorization_scope_hash='a' * 64)
    assert not quality_bundle_is_current(quality.model_copy(update={'report_basis_id': 'foreign-basis'}),
        index, markdown, input_sha256=quality.input_sha256)


@pytest.mark.anyio
async def test_incomplete_readiness_is_preserved_in_native_support(tmp_path):
    index, markdown, sources = await native_quality_inputs(tmp_path, issue_codes=('data_readiness_unknown',))
    quality = evaluate_quality_bundle(index, markdown, sources, authorization_scope_hash='a' * 64)
    assert quality.claim_support[0].support_status == 'unverified'
    assert 'data_readiness_unknown' in next(issue for issue in quality.issues
        if issue.subject_id == quality.claim_support[0].subject_id).reasons


@pytest.mark.anyio
async def test_warning_review_rejects_quality_from_another_basis(tmp_path):
    from smart_reporting.reporting.trace.warning_ledger import build_warning_ledger

    index, markdown, sources = await native_quality_inputs(tmp_path)
    quality = evaluate_quality_bundle(index, markdown, sources, authorization_scope_hash='a' * 64)
    with pytest.raises(ValueError, match='identities'):
        build_warning_ledger(quality.model_copy(update={'report_basis_id': 'foreign-basis'}), index)


@pytest.mark.parametrize('field,value', [('basisId', 'foreign-basis'), ('calculationId', 'foreign-calculation'),
    ('metricVersion', {'metricId': 'foreign-metric', 'revision': 1}), ('unit', 'USD'),
    ('period', {'start': '2025-01-01', 'end': '2026-01-01'})])
def test_native_fact_reader_rejects_internally_inconsistent_registered_result(field, value):
    import json

    from smart_reporting.reporting.models import ReportingError
    from smart_reporting.reporting.semantics.analysis_facts import build_registered_analysis_bundle
    from smart_reporting.reporting.trace.fact_service import read_fact_document

    analysis, context, _ = analysis_inputs()
    document = build_registered_analysis_bundle(analysis, context, ()).model_dump(mode='json', by_alias=True)
    document['metricContext']['calculations'][0]['results'][0][field] = value
    with pytest.raises(ReportingError, match='正式计算'):
        read_fact_document(json.dumps(document).encode())

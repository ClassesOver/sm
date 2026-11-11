"""正式结果的期间核对直接使用半开日期窗口。"""

import pytest

from smart_reporting.reporting.semantics.analysis_facts import build_registered_analysis_bundle
from smart_reporting.reporting.tests.test_registered_analysis_facts import analysis_inputs
from smart_reporting.reporting.trace.claim_semantics import freeze_interpretation
from smart_reporting.reporting.trace.semantic_bindings import NumberReferenceResolver
from smart_reporting.reporting.trace.subject_builder import claim_status


def native_claim():
    analysis, context, result = analysis_inputs()
    content = build_registered_analysis_bundle(analysis, context, ()).model_dump_json(by_alias=True)
    token = '{{value:' + result.fact_id + ':value:' + result.unit + '}}'
    reference = NumberReferenceResolver((content,)).resolve(token)
    markdown = '本期预算为300.12元[[claim:native-budget]]。'
    return markdown, reference


def check(markdown, reference, interpretation=None):
    receipt = freeze_interpretation(markdown, 'native-budget', interpretation, reference=reference) if interpretation else None
    return claim_status(markdown, 'native-budget', reference['value'], expected_unit=reference['unit'],
        expected_scope=reference['scope'], expected_reference=reference, semantic_receipt=receipt)


def test_native_period_without_interpretation_is_not_silently_verified():
    markdown, reference = native_claim()
    result = check(markdown, reference)
    assert result['status'] == 'valid'  # 数值正确不表示期间正确，仍允许导出。
    assert any('期间' in warning for warning in result['warnings'])


@pytest.mark.parametrize('case', ['exact', 'different', 'ungrounded', 'missing', 'legacy_buckets'])
def test_native_period_requires_exact_grounded_half_open_interval(case):
    markdown, reference = native_claim()
    period = dict(reference['period'])
    if case == 'different':
        period['end'] = '2030-01-01'
    interpretation = {'claimId': 'native-budget', 'period': period,
        'periodEvidence': ['本期' if case != 'ungrounded' else '原文没有的全年'], 'statistic': 'unknown'}
    if case in {'missing', 'legacy_buckets'}:
        interpretation.pop('period')
    if case == 'legacy_buckets':
        interpretation['periods'] = ['2025-01']
    result = check(markdown, reference, interpretation)
    period_warnings = [warning for warning in result['warnings'] if '期间' in warning]
    assert bool(period_warnings) == (case != 'exact')


def test_native_period_receipt_expires_after_text_edit():
    markdown, reference = native_claim()
    receipt = freeze_interpretation(markdown, 'native-budget', {'claimId': 'native-budget',
        'period': reference['period'], 'periodEvidence': ['本期']}, reference=reference)
    result = claim_status(markdown.replace('本期', '全年'), 'native-budget', reference['value'],
        expected_unit=reference['unit'], expected_reference=reference, semantic_receipt=receipt)
    assert any('失效' in warning for warning in result['warnings'])


def test_native_missing_scope_interpretation_does_not_borrow_literal_presence():
    markdown, reference = native_claim()
    reference = {**reference, 'scope': {'project_id': 'A'}}
    markdown = 'A为比较对象。' + markdown
    result = check(markdown, reference, {'claimId': 'native-budget',
        'period': reference['period'], 'periodEvidence': ['本期']})
    assert any('project_id' in warning for warning in result['warnings'])


@pytest.mark.parametrize('value,evidence,warning', [('A', '本期', False), ('B', '本期', True),
    ('A', '不存在的范围说明', True)])
def test_native_dimension_requires_unique_grounded_semantic_attribution(value, evidence, warning):
    markdown, reference = native_claim()
    reference = {**reference, 'scope': {'project_id': 'A'}}
    result = check(markdown, reference, {'claimId': 'native-budget',
        'period': reference['period'], 'periodEvidence': ['本期'], 'scope': [{
            'field': 'project_id', 'value': value, 'status': 'resolved', 'evidence': [evidence]}]})
    assert any('project_id' in item for item in result['warnings']) == warning


@pytest.mark.parametrize('field,value', [('basisId', 'other-basis'), ('calculationId', 'other-calculation'),
    ('metricVersion', {'metricId': 'other-metric', 'revision': 1})])
def test_semantic_receipt_cannot_be_reused_for_another_result(field, value):
    markdown, reference = native_claim()
    receipt = freeze_interpretation(markdown, 'native-budget', {'claimId': 'native-budget',
        'period': reference['period'], 'periodEvidence': ['本期']}, reference=reference)
    changed = {**reference, 'entry': {**reference['entry'], field: value}}
    result = claim_status(markdown, 'native-budget', reference['value'], expected_unit=reference['unit'],
        expected_reference=changed, semantic_receipt=receipt)
    assert any('结果身份' in warning for warning in result['warnings'])


@pytest.mark.anyio
async def test_actual_section_review_preserves_native_result_and_passes_interval_to_model(monkeypatch):
    from types import SimpleNamespace

    from smart_reporting.reporting.delivery.draft_v1 import ReportDraftBlock
    from smart_reporting.reporting.model_policy import ThinkingRequest
    from smart_reporting.reporting.trace.semantic_bindings import (
        anchor_bound_numbers,
        render_bound_numbers,
    )
    from smart_reporting.reporting.workflow.runtime import sections
    from smart_reporting.reporting.workflow.runtime.phase_models import SectionSemanticReview

    analysis, context, result = analysis_inputs()
    content = build_registered_analysis_bundle(analysis, context, ()).model_dump_json(by_alias=True)
    token = '{{value:' + result.fact_id + ':value:' + result.unit + '}}'
    markdown, refs, notices = render_bound_numbers('本期预算为' + token + '。', (content,), key='native-review')
    block = ReportDraftBlock(blockId='native', markdown=markdown, numberReferences=refs, reviewNotices=notices)
    calls = []

    async def review(agent, schema, stage, payload, **kwargs):
        calls.append(payload)
        reference, = payload['references']
        assert reference['periodBoundary'] == 'half_open'
        assert reference['period'] == result.period.model_dump(mode='json')
        assert reference['metricVersion'] == result.metric_version.model_dump(by_alias=True)
        assert reference['basisId'] == result.basis_id
        return SectionSemanticReview.model_validate({'interpretations': [{
            'claimId': refs[0].claim_id, 'period': reference['period'], 'periodEvidence': ['本期']}]})

    monkeypatch.setattr(sections, '_run_section_stage', review)
    reviewed, = await sections._disambiguate_section_claims(object(), (block,), (content,),
        section_code='section_001', scope=SimpleNamespace(), run_context=SimpleNamespace(),
        thinking_request=ThinkingRequest(operation='section_generation', complexity='standard'))
    assert len(calls) == 1
    assert reviewed.markdown == markdown and reviewed.number_references[0].token == token
    number, = reviewed.number_references
    assert number.semantic_receipt.result_binding_sha256
    reference = NumberReferenceResolver((content,)).resolve(token)
    checked = claim_status(anchor_bound_numbers(reviewed.markdown, reviewed.number_references),
        number.claim_id, result.value, expected_unit=result.unit,
        expected_reference=reference, semantic_receipt=number.semantic_receipt)
    assert checked['status'] == 'valid' and not checked['warnings']


@pytest.mark.parametrize('fact_id', ['fact-budget', 'org:fact:budget'])
def test_native_reference_keeps_full_registered_identity(fact_id):
    from smart_reporting.reporting.trace.semantic_bindings import reference_fact_ids

    analysis, context, result = analysis_inputs()
    result = result.model_copy(update={'fact_id': fact_id})
    context = context.model_copy(update={'calculations': (context.calculations[0].model_copy(update={'results': (result,)}),)})
    content = build_registered_analysis_bundle(analysis, context, ()).model_dump_json(by_alias=True)
    token = '{{value:' + fact_id + ':value:' + result.unit + '}}'
    resolver = NumberReferenceResolver((content,))
    assert reference_fact_ids(token) == (fact_id,)
    assert resolver.resolve(token)['entry']['factId'] == fact_id
    assert resolver.registered_token(fact_id, 'value') == token


@pytest.mark.anyio
@pytest.mark.parametrize('different_period', [False, True])
async def test_native_semantics_reaches_actual_publication_quality(tmp_path, different_period):
    from types import SimpleNamespace

    from smart_reporting.reporting.delivery.draft_v1 import ReportDraftBlock
    from smart_reporting.reporting.tests.test_http_publication_lineage import _publication_fixture
    from smart_reporting.reporting.trace.quality_bundle import evaluate_quality_bundle
    from smart_reporting.reporting.trace.semantic_bindings import (
        anchor_bound_numbers,
        render_bound_numbers,
    )
    from smart_reporting.reporting.trace.subject_builder import build_claim_subject_bindings

    _, _, _, _, _, _, contents, index = await _publication_fixture(tmp_path, registered_result=True)
    entry, = index.fact_files
    file = next(file for file in index.files if file.resource_id == entry.file_resource_id)
    content = contents[file.path].decode()
    result = analysis_inputs()[2]
    token = '{{value:' + result.fact_id + ':value:' + result.unit + '}}'
    markdown, numbers, notices = render_bound_numbers('本期预算为' + token + '。', (content,), key='native-quality')
    anchored = anchor_bound_numbers(markdown, numbers)
    period = result.period.model_dump(mode='json')
    if different_period:
        period['end'] = '2030-01-01'
    reference = NumberReferenceResolver((content,)).resolve(token)
    receipt = freeze_interpretation(anchored, numbers[0].claim_id, {'claimId': numbers[0].claim_id,
        'period': period, 'periodEvidence': ['本期']}, reference=reference)
    numbers = (numbers[0].model_copy(update={'semantic_receipt': receipt}),)
    block = ReportDraftBlock(blockId='native-quality', markdown=markdown, numberReferences=numbers, reviewNotices=notices)
    subjects = build_claim_subject_bindings((SimpleNamespace(section_code='section_001', blocks=(block,), claims=()),),
        {result.fact_id: (entry.analysis_id, '/metricContext/calculations/0/results/0')},
        {entry.analysis_id: file.resource_id})
    assert len(subjects) == 1
    index = index.model_copy(update={'subject_bindings': subjects, 'tables': ()})
    sources = {file.resource_id: contents[file.path] for file in index.files}
    quality = evaluate_quality_bundle(index, anchored, sources, authorization_scope_hash='a' * 64)
    issue, = [issue for issue in quality.issues if issue.subject_id == subjects[0].subject_id]
    # 期间正确也不凭空声明没有登记的组织范围，期间错误必须有具体软告警。
    assert ('statement_not_supported' in issue.reasons) == different_period
    if different_period:
        assert any('半开期间' in warning for warning in issue.statement_review.warnings)

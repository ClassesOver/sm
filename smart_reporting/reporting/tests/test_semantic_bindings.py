"""冻结数值引用贯通生成、绑定、编辑校验，不以同值替代事实身份。"""
import json
from types import SimpleNamespace

import pytest

from smart_reporting.reporting.trace.contracts_v1 import derive_resource_id
from smart_reporting.reporting.trace.semantic_bindings import (
    anchor_bound_numbers,
    render_bound_numbers,
    resolve_number_reference,
    statement_fingerprint,
)
from smart_reporting.reporting.trace.subject_builder import build_claim_subject_bindings


def contents():
    metrics = []
    for key, field, values in [('a', 'actual_equipment', (10, 20)), ('b', 'budget_equipment', (20, 100))]:
        metrics.append(dict(factId='fact-' + key * 16, datasetId='ds', datasetSha256='c' * 64,
                            periodRoles=['current'], field=field, fieldRef='source.db.table.' + field,
                            aggregation='sum', unit='元', formula=f'SUM({field})', scope={},
                            total=sum(values), missingCount=0, zeroCount=0, negativeCount=0,
                            periodGranularity='month', periodStart='2025-01', periodEnd='2025-02',
                            periodValues=[{'period': f'2025-0{i+1}', 'value': value} for i, value in enumerate(values)]))
    return [json.dumps({'analysisId': 'analysis_001', 'metrics': metrics})]


@pytest.mark.parametrize(('selector', 'value', 'unit', 'periods'), [
    ('periodValues.1:元', 20, '元', ('2025-02',)),
    ('periodTotals.0-0:元', 10, '元', ('2025-01',)),
    ('budgetComparison.fact-bbbbbbbbbbbbbbbb.2025-02.percentage:%', 20, '%', ('2025-02',)),
])
def test_resolves_exact_selector_instead_of_first_fact_total(selector, value, unit, periods):
    token = '{{value:fact-aaaaaaaaaaaaaaaa:' + selector + '}}'
    result = resolve_number_reference(token, contents())
    assert result['value'] == value
    assert result['unit'] == unit
    assert result['periods'] == periods


def test_number_anchors_keep_repeated_values_distinct_and_bind_both_operands():
    first = '{{value:fact-aaaaaaaaaaaaaaaa:periodValues.1:元}}'
    second = '{{value:fact-aaaaaaaaaaaaaaaa:budgetComparison.fact-bbbbbbbbbbbbbbbb.2025-02.percentage:%}}'
    markdown, references, notices = render_bound_numbers('租赁' + first + '，执行率' + second + '。', contents(), key='s:b')
    markdown = anchor_bound_numbers(markdown, references, notices)
    assert len(references) == 2 and references[0].claim_id != references[1].claim_id
    assert all(markdown.count('[[claim:' + ref.claim_id + ']]') == 1 for ref in references)
    block = SimpleNamespace(number_references=references)
    artifact = SimpleNamespace(section_code='s', blocks=[block], claims=[])
    bindings = build_claim_subject_bindings([artifact],
        {'fact-' + c * 16: ('analysis_001', '/metrics/' + str(i)) for i, c in enumerate('ab')},
        {'analysis_001': derive_resource_id('facts.json')})
    assert len(bindings) == 2
    assert len(bindings[1].fact_refs) == 2
    assert not notices
    assert statement_fingerprint(markdown.replace('租赁', '销售'), references[0].claim_id) != references[0].statement_sha256


def test_missing_operand_or_conflicting_identity_never_falls_back_to_total():
    token = '{{value:fact-aaaaaaaaaaaaaaaa:budgetComparison.fact-bbbbbbbbbbbbbbbb.2025-02.percentage:%}}'
    doc = json.loads(contents()[0])
    doc['metrics'] = doc['metrics'][:1]
    assert resolve_number_reference(token, [json.dumps(doc)]) is None
    conflicting = json.loads(contents()[0])
    conflicting['metrics'][0]['periodValues'][1]['value'] = 999
    assert resolve_number_reference('{{value:fact-aaaaaaaaaaaaaaaa:periodValues.1:元}}',
                                    [*contents(), json.dumps(conflicting)]) is None


def test_missing_numbers_are_typed_at_replacement_not_guessed_from_prose():
    markdown, refs, notices = render_bound_numbers(
        '供应商答复待核实。租赁999999元。无效引用{{value:fact-cccccccccccccccc:total:元}}。', contents(), key='s:b')
    markdown = anchor_bound_numbers(markdown, refs, notices)
    assert not refs
    assert [notice.kind for notice in notices].count('numeric_unverified') == 2
    assert [notice.kind for notice in notices].count('source_review') == 1
    assert all('[[claim:' + notice.claim_id + ']]' in markdown for notice in notices)


def test_assembly_preserves_bindings_through_punctuation_and_date_formatting():
    from smart_reporting.reporting.delivery.draft_v1 import (
        ReportDraftBlock,
        validate_report_draft_blocks,
    )

    from .test_reporting_heading_numbers import _assemble_charts
    markdown, refs, notices = render_bound_numbers(
        '2025-02收入: {{value:fact-aaaaaaaaaaaaaaaa:periodValues.1:元}}。答复待核实。',
        contents(), key='section_001:b',
    )
    block = ReportDraftBlock(blockId='b', markdown=markdown, numberReferences=refs,
                             reviewNotices=notices, chartPlacement='explicit')
    validate_report_draft_blocks((block,))
    rendered = _assemble_charts((block,), ()).markdown
    assert statement_fingerprint(rendered, refs[0].claim_id) == refs[0].statement_sha256
    assert '[[citation:sub-' in rendered
    assert all('[[claim:' + notice.claim_id + ']]' in rendered for notice in notices)


def test_bound_references_do_not_allow_model_protocol_injection():
    from smart_reporting.reporting.delivery.draft_v1 import (
        ReportDraftBlock,
        validate_report_draft_blocks,
    )
    from smart_reporting.reporting.models import ReportingError
    markdown, refs, notices = render_bound_numbers('{{value:fact-aaaaaaaaaaaaaaaa:total:元}}', contents(), key='s:b')
    block = ReportDraftBlock(blockId='b', markdown=markdown + '[[claim:forged]]', numberReferences=refs,
                             reviewNotices=notices)
    with pytest.raises(ReportingError, match='正文不得'):
        validate_report_draft_blocks((block,))


def test_merging_blocks_retains_annotation_offsets():
    from smart_reporting.reporting.delivery.draft_v1 import ReportDraftBlock
    from smart_reporting.reporting.tools.sections import RuntimeSectionsMixin
    first, refs1, notes1 = render_bound_numbers('甲{{value:fact-aaaaaaaaaaaaaaaa:total:元}}。', contents(), key='s:a')
    second, refs2, notes2 = render_bound_numbers('乙{{value:fact-bbbbbbbbbbbbbbbb:total:元}}。', contents(), key='s:b')
    blocks = [ReportDraftBlock(blockId='a', markdown=first, numberReferences=refs1, reviewNotices=notes1, claimIds=('c',)),
              ReportDraftBlock(blockId='b', markdown=second, numberReferences=refs2, reviewNotices=notes2)]
    merged, _ = RuntimeSectionsMixin._merge_claimless_blocks('s', blocks)
    assert len(merged) == 1
    anchored = anchor_bound_numbers(merged[0].markdown, merged[0].number_references, merged[0].review_notices)
    assert len(merged[0].number_references) == 2
    for ref in (*refs1, *refs2):
        assert statement_fingerprint(anchored, ref.claim_id) == ref.statement_sha256


def test_correlation_reference_preserves_scalar_fact_identity():
    doc = json.loads(contents()[0])
    doc['correlationDetails'] = [{
        'factId': 'fact-cccccccccccccccc', 'datasetId': 'ds', 'datasetSha256': 'c' * 64,
        'leftField': 'x', 'rightField': 'y',
        'method': 'pearson', 'sampleCount': 12, 'value': 0.82,
    }]
    token = '{{value:fact-cccccccccccccccc:value:}}'
    selected = resolve_number_reference(token, [json.dumps(doc)])
    assert selected is not None and selected['value'] == 0.82
    markdown, refs, notices = render_bound_numbers('关联系数' + token + '。', [json.dumps(doc)], key='s:b')
    artifact = SimpleNamespace(section_code='s', blocks=[SimpleNamespace(number_references=refs)], claims=[])
    bindings = build_claim_subject_bindings([artifact],
        {'fact-cccccccccccccccc': ('analysis_001', '/correlationDetails/0')},
        {'analysis_001': derive_resource_id('facts.json')})
    assert '0.82' in markdown and not notices
    assert bindings[0].fact_refs[0].fact_kind == 'correlation'


def test_heading_promotion_retains_exact_number_binding():
    from smart_reporting.reporting.delivery.draft_v1 import ReportDraftBlock
    from smart_reporting.reporting.models import ReportingError
    from smart_reporting.reporting.workflow.runtime.sections import _promoted_heading_block
    markdown, refs, notices = render_bound_numbers(
        '#### 租赁\n\n2月回款{{value:fact-aaaaaaaaaaaaaaaa:periodValues.1:元}}。', contents(), key='s:b')
    block = ReportDraftBlock(blockId='b', markdown=markdown, numberReferences=refs, reviewNotices=notices)
    promoted = _promoted_heading_block(ReportingError('report_draft_heading_parent_missing', 'x'),
                                      block, [], SimpleNamespace(title='经营', section_code='s'))
    assert promoted is not None and promoted.markdown.startswith('### ')
    assert len(promoted.number_references) == 1
    anchored = anchor_bound_numbers(promoted.markdown, promoted.number_references, promoted.review_notices)
    assert statement_fingerprint(anchored, refs[0].claim_id) == refs[0].statement_sha256

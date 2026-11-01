"""模型解释共同口径，程序绑定当前正文并保留无法确认的语义。"""

import pytest


@pytest.mark.parametrize('wording', [
    '本段统计医院开单收入，北院100元；南院200元',
    '以下金额均属开单收入。北院100元，南院200元',
    '开单收入是此处的统计口径：北院100元；南院200元',
])
def test_scope_disambiguation_accepts_evidence_without_fixed_wording(wording):
    from smart_reporting.reporting.trace.claim_semantics import (
        freeze_interpretation,
        semantic_warnings,
    )
    markdown = wording + '[[claim:second]]。'
    receipt = freeze_interpretation(markdown, 'second', {
        'claimId': 'second', 'scope': [
            {'field': 'income_nature', 'value': '开单收入', 'status': 'resolved',
             'evidence': ['开单收入']},
        ], 'periods': [], 'periodEvidence': [],
    })
    warnings = ['业务范围需复核：当前引用句未体现登记范围 income_nature=开单收入。']
    assert semantic_warnings(markdown, 'second', receipt,
                             {'income_nature': '开单收入'}, (), warnings) == []


def test_scope_judgment_is_generic_and_only_removes_its_own_missing_scope_warning():
    from smart_reporting.reporting.trace.claim_semantics import (
        freeze_interpretation,
        semantic_warnings,
    )
    markdown = '此段按急诊就诊人群列示。甲100人次；乙200人次[[claim:c]]。'
    receipt = freeze_interpretation(markdown, 'c', {
        'claimId': 'c', 'scope': [{'field': 'patient_type', 'value': '急诊',
                                  'status': 'resolved', 'evidence': ['急诊就诊人群']}],
        'periods': [], 'periodEvidence': [],
    })
    missing = '业务范围需复核：当前引用句未体现登记范围 patient_type=急诊。'
    other = ['期间文本与生成时不一致', '业务范围需复核：当前引用否定或排除了登记范围 patient_type=急诊。',
             '业务范围需复核：当前引用句未体现登记范围 campus=北院。']
    assert semantic_warnings(markdown, 'c', receipt, {'patient_type': '急诊', 'campus': '北院'},
                             (), [missing, *other]) == other


@pytest.mark.parametrize('change', ['口径替换', '新增排除', '复制锚点'])
def test_semantic_receipt_is_invalid_after_context_edit(change):
    from smart_reporting.reporting.trace.claim_semantics import (
        freeze_interpretation,
        semantic_warnings,
    )
    markdown = '本段统计开单收入。南院200元[[claim:c]]。'
    receipt = freeze_interpretation(markdown, 'c', {
        'claimId': 'c', 'scope': [{'field': 'income_nature', 'value': '开单收入',
                                  'status': 'resolved', 'evidence': ['开单收入']}],
        'periods': [], 'periodEvidence': [],
    })
    edited = {'口径替换': markdown.replace('开单收入', '实收收入'),
              '新增排除': markdown.replace('南院', '不含开单收入的南院'),
              '复制锚点': markdown + markdown}[change]
    warnings = ['业务范围需复核：当前引用句未体现登记范围 income_nature=开单收入。']
    result = semantic_warnings(edited, 'c', receipt, {'income_nature': '开单收入'}, (), warnings)
    assert warnings[0] in result
    assert any('失效' in item for item in result)


@pytest.mark.parametrize('status,value,evidence', [
    ('unknown', None, []), ('conflicting', '实收收入', ['实收收入']),
    ('resolved', '开单收入', ['不存在的文字']),
])
def test_ambiguous_conflicting_or_fabricated_evidence_does_not_clear_warning(status, value, evidence):
    from smart_reporting.reporting.trace.claim_semantics import (
        freeze_interpretation,
        semantic_warnings,
    )
    markdown = '这里可能是实收收入。南院200元[[claim:c]]。'
    receipt = freeze_interpretation(markdown, 'c', {
        'claimId': 'c', 'scope': [{'field': 'income_nature', 'value': value,
                                  'status': status, 'evidence': evidence}],
        'periods': [], 'periodEvidence': [],
    })
    warning = '业务范围需复核：当前引用句未体现登记范围 income_nature=开单收入。'
    assert warning in semantic_warnings(markdown, 'c', receipt, {'income_nature': '开单收入'}, (), [warning])


def test_model_detected_single_month_conflicts_with_frozen_window():
    from smart_reporting.reporting.trace.claim_semantics import (
        freeze_interpretation,
        semantic_warnings,
    )
    markdown = '八月份的收入为10.43亿元[[claim:c]]。'
    receipt = freeze_interpretation(markdown, 'c', {
        'claimId': 'c', 'scope': [], 'periods': ['2025-08'], 'periodEvidence': ['八月份'],
    })
    result = semantic_warnings(markdown, 'c', receipt, {}, ('2025-01', '2025-08'), [])
    assert any('期间' in item for item in result)


def test_comparison_period_membership_does_not_depend_on_model_array_order():
    from smart_reporting.reporting.trace.claim_semantics import freeze_interpretation, semantic_warnings

    markdown = '2025年11月较2024年11月减少5元[[claim:c]]。'
    receipt = freeze_interpretation(markdown, 'c', {'claimId': 'c',
        'periods': ['2024-11', '2025-11'], 'periodEvidence': ['2025年11月较2024年11月']})
    assert semantic_warnings(markdown, 'c', receipt, {}, ('2025-11', '2024-11'), []) == []
    receipt = freeze_interpretation(markdown, 'c', {'claimId': 'c',
        'periods': ['2024-10', '2025-11'], 'periodEvidence': ['2025年11月较2024年11月']})
    assert any('期间' in warning for warning in semantic_warnings(
        markdown, 'c', receipt, {}, ('2025-11', '2024-11'), []))


@pytest.mark.parametrize('evidence', ['9月收入为100元', '2025年收入为100元'])
def test_semantic_period_disambiguation_accepts_context_resolved_year_or_month(evidence):
    from smart_reporting.reporting.trace.claim_semantics import freeze_interpretation, semantic_warnings

    markdown = '本节分析2025年9月。' + evidence + '[[claim:c]]。'
    receipt = freeze_interpretation(markdown, 'c', {'claimId': 'c',
        'periods': ['2025-09'], 'periodEvidence': [evidence]})
    warning = '期间文本与生成时不一致（生成时 2025年9月）'
    assert semantic_warnings(markdown, 'c', receipt, {}, ('2025-09',), [warning]) == []


@pytest.mark.parametrize('selector,statistic', [
    ('total', 'period_average'), ('monthlyAverage', 'period_total'),
])
def test_semantic_aggregation_mismatch_warns_even_when_periods_match(selector, statistic):
    from smart_reporting.reporting.tests.test_semantic_bindings import contents
    from smart_reporting.reporting.trace.claim_semantics import (
        freeze_interpretation,
        semantic_warnings,
    )
    from smart_reporting.reporting.trace.semantic_bindings import resolve_number_reference

    wording = '一至二月月均' if statistic == 'period_average' else '一至二月合计'
    markdown = wording + '30元[[claim:c]]。'
    selected = resolve_number_reference('{{value:fact-aaaaaaaaaaaaaaaa:' + selector + ':元}}', contents())
    receipt = freeze_interpretation(markdown, 'c', {
        'claimId': 'c', 'periods': ['2025-01', '2025-02'], 'periodEvidence': ['一至二月'],
        'statistic': statistic, 'statisticEvidence': [wording],
    })
    warnings = semantic_warnings(markdown, 'c', receipt, {}, selected['periods'], [], reference=selected)
    assert any('统计方式' in warning for warning in warnings)


def test_evidence_cannot_be_borrowed_from_another_paragraph_or_claim():
    from smart_reporting.reporting.trace.claim_semantics import freeze_interpretation
    markdown = '开单收入。\n\n南院200元[[claim:c]]。'
    receipt = freeze_interpretation(markdown, 'c', {
        'claimId': 'other', 'scope': [{'field': 'income_nature', 'value': '开单收入',
                                      'status': 'resolved', 'evidence': ['开单收入']}],
        'periods': [], 'periodEvidence': [],
    })
    assert receipt is None


def test_previous_paragraph_evidence_is_bound_and_invalidated_when_edited():
    from smart_reporting.reporting.trace.claim_semantics import (
        freeze_interpretation,
        semantic_receipt_status,
        semantic_warnings,
    )

    markdown = '2025年开单收入按月列示，10月100元。\n\n11月较10月减少50元[[claim:c]]。'
    receipt = freeze_interpretation(markdown, 'c', {
        'claimId': 'c', 'scope': [{'field': 'income_nature', 'value': '开单收入',
                                  'status': 'resolved', 'evidence': ['开单收入按月列示']}],
    }, include_previous=True)
    warning = '业务范围需复核：当前引用句未体现登记范围 income_nature=开单收入。'
    assert semantic_warnings(markdown, 'c', receipt, {'income_nature': '开单收入'}, (), [warning]) == []
    assert semantic_receipt_status(markdown.replace('开单收入', '执行收入'), 'c', receipt) == 'invalidated'


@pytest.mark.parametrize('boundary', ['### 另一个主题', '[[section:section_002]]'])
def test_previous_paragraph_context_does_not_cross_heading_or_section(boundary):
    from smart_reporting.reporting.trace.claim_semantics import claim_context

    markdown = '开单收入100元。\n\n' + boundary + '\n\n本期50元[[claim:c]]。'
    context = claim_context(markdown, 'c', include_previous=True)
    assert '开单收入' not in context


def test_previous_paragraph_context_preserves_scope_switch_for_model_review():
    from smart_reporting.reporting.trace.claim_semantics import (
        claim_context,
        freeze_interpretation,
        semantic_warnings,
    )

    markdown = '开单收入100元。\n\n以下改按执行收入，本期50元[[claim:c]]。'
    assert '开单收入' in claim_context(markdown, 'c', include_previous=True)
    receipt = freeze_interpretation(markdown, 'c', {
        'claimId': 'c', 'scope': [{'field': 'income_nature', 'value': '执行收入',
                                  'status': 'conflicting', 'evidence': ['改按执行收入']}],
    }, include_previous=True)
    warning = '业务范围需复核：当前引用句未体现登记范围 income_nature=开单收入。'
    assert warning in semantic_warnings(markdown, 'c', receipt, {'income_nature': '开单收入'}, (), [warning])


def test_shared_claim_checker_consumes_receipt_and_invalidates_changed_common_scope():
    from smart_reporting.reporting.trace.claim_semantics import freeze_interpretation
    from smart_reporting.reporting.trace.subject_builder import claim_status

    markdown = '以下金额均属开单收入。北院100元；南院200元[[claim:c]]。'
    scope = {'income_nature': '开单收入'}
    receipt = freeze_interpretation(markdown, 'c', {
        'claimId': 'c', 'scope': [{'field': 'income_nature', 'value': '开单收入',
                                  'status': 'resolved', 'evidence': ['以下金额均属开单收入']}],
        'periods': [], 'periodEvidence': [],
    })
    assert claim_status(markdown, 'c', 200, expected_scope=scope)['warnings']
    result = claim_status(markdown, 'c', 200, expected_scope=scope, semantic_receipt=receipt)
    assert result == {'status': 'valid', 'warnings': []}
    edited = claim_status(markdown.replace('开单收入', '实收收入'), 'c', 200,
                          expected_scope=scope, semantic_receipt=receipt)
    assert any('失效' in warning for warning in edited['warnings'])


def test_resolved_model_scope_never_overrides_explicit_exclusion_or_period_error():
    from smart_reporting.reporting.trace.claim_semantics import freeze_interpretation
    from smart_reporting.reporting.trace.subject_builder import claim_status

    markdown = '2025年8月不含开单收入的金额200元[[claim:c]]。'
    receipt = freeze_interpretation(markdown, 'c', {
        'claimId': 'c', 'scope': [{'field': 'income_nature', 'value': '开单收入',
                                  'status': 'resolved', 'evidence': ['开单收入']}],
        'periods': ['2025-01'], 'periodEvidence': ['2025年8月'],
    })
    result = claim_status(markdown, 'c', 200, expected_scope={'income_nature': '开单收入'},
                          expected_periods=('2025-01',), semantic_receipt=receipt)
    assert any('排除' in warning for warning in result['warnings'])
    assert any('期间' in warning for warning in result['warnings'])


def test_semantic_receipt_is_invalid_when_claim_moves_within_same_paragraph():
    from smart_reporting.reporting.trace.claim_semantics import (
        freeze_interpretation,
        semantic_warnings,
    )

    markdown = '开单收入100元[[claim:c]]；实收收入200元。'
    receipt = freeze_interpretation(markdown, 'c', {
        'claimId': 'c', 'scope': [{'field': 'income_nature', 'value': '开单收入',
                                  'status': 'resolved', 'evidence': ['开单收入100元']}],
    })
    moved = '开单收入100元；实收收入200元[[claim:c]]。'
    assert any('失效' in warning for warning in semantic_warnings(
        moved, 'c', receipt, {'income_nature': '开单收入'}, (), [],
    ))


@pytest.mark.parametrize('statistic,periods,expected', [
    ('single_period', ['2025-02'], 'periodValues.1'),
    ('period_average', ['2025-01', '2025-02'], 'monthlyAverage'),
    ('unknown', ['2025-02'], None),
    ('single_period', ['2025-03'], None),
])
def test_semantic_reselection_requires_grounded_unique_frozen_month(statistic, periods, expected):
    from smart_reporting.reporting.tests.test_semantic_bindings import contents
    from smart_reporting.reporting.trace.claim_semantics import semantic_period_token
    from smart_reporting.reporting.trace.semantic_bindings import resolve_number_reference

    token = '{{value:fact-aaaaaaaaaaaaaaaa:total:元}}'
    selected = resolve_number_reference(token, contents())
    interpretation = {'claimId': 'c', 'periods': periods, 'periodEvidence': ['本月'],
                      'statistic': statistic, 'statisticEvidence': ['本月']}
    candidate = semantic_period_token('本月收入200元[[claim:c]]。', 'c', token, selected, interpretation, contents())
    if expected:
        assert candidate == '{{value:fact-aaaaaaaaaaaaaaaa:' + expected + ':元}}'
    else:
        assert candidate is None


def test_corrected_number_retains_original_semantic_excerpt_without_fabricating_quote():
    from smart_reporting.reporting.trace.claim_semantics import (
        freeze_interpretation,
        semantic_warnings,
    )

    original = '开单收入中，八月10.43亿元[[claim:c]]。'
    corrected = original.replace('10.43', '10.93')
    receipt = freeze_interpretation(corrected, 'c', {
        'claimId': 'c', 'scope': [{'field': 'income_nature', 'value': '开单收入',
        'status': 'resolved', 'evidence': ['开单收入中，八月10.43亿元']}],
    }, reviewed_markdown=original)
    assert semantic_warnings(corrected, 'c', receipt, {'income_nature': '开单收入'}, (), []) == []
    assert '10.43' in receipt.reviewed_context


@pytest.mark.parametrize('scope', [
    [],
    [{'field': 'income_nature', 'status': 'unknown'}],
    [{'field': 'income_nature', 'status': 'resolved', 'value': '开单收入',
      'evidence': ['不存在的范围声明']}],
    [{'field': 'income_nature', 'status': 'resolved', 'value': '开单收入',
      'evidence': ['开单收入']}] * 2,
])
def test_period_reselection_preserves_number_until_all_registered_scope_is_grounded(scope):
    import json

    from smart_reporting.reporting.tests.test_semantic_bindings import contents
    from smart_reporting.reporting.trace.claim_semantics import semantic_period_token
    from smart_reporting.reporting.trace.semantic_bindings import resolve_number_reference

    doc = json.loads(contents()[0])
    doc['metrics'][0]['scope'] = {'income_nature': '开单收入'}
    frozen = [json.dumps(doc)]
    token = '{{value:fact-aaaaaaaaaaaaaaaa:total:元}}'
    selected = resolve_number_reference(token, frozen)
    interpretation = {'claimId': 'c', 'scope': scope, 'periods': ['2025-02'],
                      'periodEvidence': ['二月'], 'statistic': 'single_period',
                      'statisticEvidence': ['二月']}
    assert semantic_period_token('开单收入中，二月30元[[claim:c]]。', 'c', token,
                                 selected, interpretation, frozen) is None


def test_extremum_occurrence_month_is_distinct_from_calculation_window():
    from smart_reporting.reporting.tests.test_semantic_bindings import contents
    from smart_reporting.reporting.trace.claim_semantics import (
        freeze_interpretation,
        semantic_warnings,
    )
    from smart_reporting.reporting.trace.semantic_bindings import resolve_number_reference

    markdown = '二月最高收入20元[[claim:c]]。'
    selected = resolve_number_reference('{{value:fact-aaaaaaaaaaaaaaaa:monthlyMaximum:元}}', contents())
    receipt = freeze_interpretation(markdown, 'c', {
        'claimId': 'c', 'periods': ['2025-02'], 'periodEvidence': ['二月'],
    })
    assert semantic_warnings(markdown, 'c', receipt, {}, selected['periods'], [], reference=selected) == []


@pytest.mark.anyio
@pytest.mark.parametrize('correct_month', [False, True])
async def test_section_semantic_review_uses_final_text_and_frozen_scope(monkeypatch, correct_month):
    import json
    from types import SimpleNamespace

    from smart_reporting.reporting.delivery.draft_v1 import ReportDraftBlock
    from smart_reporting.reporting.model_policy import ThinkingRequest
    from smart_reporting.reporting.tests.test_semantic_bindings import contents
    from smart_reporting.reporting.trace.semantic_bindings import render_bound_numbers
    from smart_reporting.reporting.workflow.runtime import sections
    from smart_reporting.reporting.workflow.runtime.phase_models import SectionSemanticReview

    doc = json.loads(contents()[0])
    doc['metrics'][0]['scope'] = {'income_nature': '开单收入'}
    frozen = [json.dumps(doc)]
    raw = ('二月份南院收入' if correct_month else '北院100元；南院')
    md, refs, notices = render_bound_numbers(
        '以下金额均属开单收入。' + raw + '{{value:fact-aaaaaaaaaaaaaaaa:total:元}}。',
        frozen, key='semantic-test',
    )
    blocks = (ReportDraftBlock(blockId='b1', markdown=md, numberReferences=refs, reviewNotices=notices),)
    calls = []

    async def fake_stage(agent, schema, stage, payload, **kwargs):
        assert stage == 'semantics' and schema is SectionSemanticReview
        calls.append(payload)
        assert payload['references'][0]['scope'] == {'income_nature': '开单收入'}
        return SectionSemanticReview.model_validate({'interpretations': [{
            'claimId': refs[0].claim_id, 'scope': [{'field': 'income_nature', 'value': '开单收入',
            'status': 'resolved', 'evidence': ['以下金额均属开单收入']}],
            'periods': ['2025-02'] if correct_month else [],
            'periodEvidence': ['二月份'] if correct_month else [],
            'statistic': 'single_period' if correct_month else 'unknown',
            'statisticEvidence': ['二月份'] if correct_month else [],
        }]})

    monkeypatch.setattr(sections, '_run_section_stage', fake_stage)
    result = await sections._disambiguate_section_claims(
        object(), blocks, frozen, section_code='section_001', scope=SimpleNamespace(),
        run_context=SimpleNamespace(), thinking_request=ThinkingRequest(operation='section_generation', complexity='standard'),
    )
    assert len(calls) == 1
    assert result[0].markdown == (md.replace('30元', '20元') if correct_month else md)
    if correct_month:
        assert result[0].number_references[0].token.endswith(':periodValues.1:元}}')
        assert result[0].number_references[0].display_text == '20元'
    assert result[0].number_references[0].semantic_receipt is not None


@pytest.mark.anyio
async def test_section_semantic_context_crosses_blocks_and_survives_report_assembly(monkeypatch):
    import json
    from types import SimpleNamespace

    from smart_reporting.reporting.delivery.draft_v1 import ReportDraftBlock
    from smart_reporting.reporting.model_policy import ThinkingRequest
    from smart_reporting.reporting.tests.test_semantic_bindings import contents
    from smart_reporting.reporting.trace.semantic_bindings import (
        anchor_bound_numbers,
        render_bound_numbers,
    )
    from smart_reporting.reporting.trace.subject_builder import claim_status
    from smart_reporting.reporting.workflow.runtime import sections
    from smart_reporting.reporting.workflow.runtime.phase_models import SectionSemanticReview

    doc = json.loads(contents()[0])
    doc['metrics'][0]['scope'] = {'income_nature': '开单收入'}
    frozen = [json.dumps(doc)]
    md, refs, _ = render_bound_numbers(
        '二月较一月增加{{value:fact-aaaaaaaaaaaaaaaa:periodChanges.1:元}}。', frozen, key='cross-block',
    )
    blocks = (ReportDraftBlock(blockId='prior', markdown='本段统计开单收入的月度变化。'),
              ReportDraftBlock(blockId='current', markdown=md, numberReferences=refs))

    async def review(agent, schema, stage, payload, **kwargs):
        assert '本段统计开单收入' in next(iter(payload['contexts'].values()))
        return SectionSemanticReview.model_validate({'interpretations': [{
            'claimId': refs[0].claim_id, 'scope': [{'field': 'income_nature', 'value': '开单收入',
                                                  'status': 'resolved', 'evidence': ['本段统计开单收入']}],
        }]})

    monkeypatch.setattr(sections, '_run_section_stage', review)
    result = await sections._disambiguate_section_claims(
        object(), blocks, frozen, section_code='section_001', scope=SimpleNamespace(),
        run_context=SimpleNamespace(), thinking_request=ThinkingRequest(operation='section_generation', complexity='standard'),
    )
    receipt = result[1].number_references[0].semantic_receipt
    assert receipt is not None and receipt.includes_section
    assembled = '## 科室收入\n\n' + '\n\n'.join(anchor_bound_numbers(b.markdown, b.number_references) for b in result)
    detail = claim_status(assembled, refs[0].claim_id, 10, expected_scope={'income_nature': '开单收入'},
                          semantic_receipt=receipt)
    assert detail['warnings'] == []


@pytest.mark.anyio
async def test_editor_revalidates_semantic_receipt_after_common_scope_edit(tmp_path):
    import hashlib

    from smart_reporting.reporting.tests.lineage_fixtures.manifest import register_trace_manifest
    from smart_reporting.reporting.tests.test_trace_subject_validate import (
        _make_editor_with_subject,
    )
    from smart_reporting.reporting.trace.claim_semantics import freeze_interpretation
    from smart_reporting.reporting.trace.index_builder import encode_trace_index

    editor, _, context = await _make_editor_with_subject(
        tmp_path, period_table=True, number_reference=True,
        metric_scope={'income_nature': '开单收入'},
        number_statement='以下金额均属开单收入。南院{{value:fact-aaaaaaaaaaaaaaaa:total:万元}}。',
    )
    index = await editor.trace.load_index(context)
    binding = index.subject_bindings[0]
    number = binding.number_reference
    report = next(tmp_path.rglob('report.md'))
    markdown = report.read_text()
    receipt = freeze_interpretation(markdown, binding.claim_id, {
        'claimId': binding.claim_id, 'scope': [{'field': 'income_nature', 'value': '开单收入',
        'status': 'resolved', 'evidence': ['以下金额均属开单收入']}],
    })
    updated = index.model_copy(update={'subject_bindings': (binding.model_copy(update={
        'number_reference': number.model_copy(update={'semantic_receipt': receipt}),
    }), *index.subject_bindings[1:])})
    path = next(tmp_path.rglob('trace-index-v1.json'))
    path.write_bytes(encode_trace_index(updated))
    manifest = await register_trace_manifest(editor.trace._workspace, context.scope['threadId'], updated, overwrite=True)
    context = context.model_copy(update={'artifact_manifest': manifest})
    result = await editor.trace.validate(context, markdown, hashlib.sha256(markdown.encode()).hexdigest())
    assert result['subjects'][0]['semanticCheck']['status'] == 'interpreted'
    assert not any('income_nature=开单收入' in warning for warning in result['subjects'][0]['warnings'])
    from smart_reporting.reporting.trace.quality_bundle import evaluate_quality_bundle

    sources = {file.resource_id: await editor.trace._read_registered_file(
        context, file, max_bytes=16 * 1024 * 1024,
    ) for file in updated.files if file.media_type == 'application/json'}
    quality = evaluate_quality_bundle(updated, markdown, sources, authorization_scope_hash='c' * 64)
    assert not any(issue.statement_review and any('income_nature=开单收入' in warning
                   for warning in issue.statement_review.warnings) for issue in quality.issues)
    edited = markdown.replace('开单收入', '实收收入')
    result = await editor.trace.validate(context, edited, hashlib.sha256(edited.encode()).hexdigest())
    assert result['subjects'][0]['semanticCheck']['status'] == 'invalidated'
    assert any('失效' in warning for warning in result['subjects'][0]['warnings'])


@pytest.mark.anyio
async def test_semantic_model_failure_keeps_report_blocks_and_adds_soft_notice(monkeypatch):
    from types import SimpleNamespace

    from smart_reporting.reporting.delivery.draft_v1 import ReportDraftBlock
    from smart_reporting.reporting.model_policy import ThinkingRequest
    from smart_reporting.reporting.tests.test_semantic_bindings import contents
    from smart_reporting.reporting.trace.semantic_bindings import render_bound_numbers
    from smart_reporting.reporting.workflow.runtime import sections

    md, refs, _ = render_bound_numbers('收入{{value:fact-aaaaaaaaaaaaaaaa:total:元}}。', contents(), key='fail')
    blocks = (ReportDraftBlock(blockId='b', markdown=md, numberReferences=refs),)

    async def fail(*args, **kwargs):
        raise RuntimeError('provider unavailable')

    monkeypatch.setattr(sections, '_run_section_stage', fail)
    notices = {}
    result = await sections._disambiguate_section_claims(
        object(), blocks, contents(), section_code='section_001', scope=SimpleNamespace(),
        run_context=SimpleNamespace(), thinking_request=ThinkingRequest(operation='section_generation', complexity='standard'),
        review_notices=notices,
    )
    assert result == blocks
    assert notices['b'][0]['code'] == 'report_claim_semantics_unavailable'


@pytest.mark.anyio
async def test_semantic_postprocessing_failure_keeps_original_report(monkeypatch):
    from types import SimpleNamespace

    from smart_reporting.reporting.delivery.draft_v1 import ReportDraftBlock
    from smart_reporting.reporting.model_policy import ThinkingRequest
    from smart_reporting.reporting.trace import claim_semantics
    from smart_reporting.reporting.workflow.runtime import sections

    def fail(*args, **kwargs):
        raise RuntimeError('semantic context parser failed')

    monkeypatch.setattr(claim_semantics, 'claim_context', fail)
    from smart_reporting.reporting.tests.test_semantic_bindings import contents
    from smart_reporting.reporting.trace.semantic_bindings import render_bound_numbers

    md, refs, _ = render_bound_numbers('收入{{value:fact-aaaaaaaaaaaaaaaa:total:元}}。', contents(), key='fail')
    blocks = (ReportDraftBlock(blockId='b', markdown=md, numberReferences=refs),)
    notices = {}
    result = await sections._disambiguate_section_claims(
        object(), blocks, contents(), section_code='section_001', scope=SimpleNamespace(),
        run_context=SimpleNamespace(), thinking_request=ThinkingRequest(operation='section_generation', complexity='standard'),
        review_notices=notices,
    )
    assert result == blocks
    assert notices['b'][0]['code'] == 'report_claim_semantics_unavailable'


def test_semantic_batch_keeps_valid_items_without_accepting_invalid_or_duplicate_claims():
    from smart_reporting.reporting.workflow.runtime.sections import (
        _validated_section_semantic_review,
    )

    result = _validated_section_semantic_review({'interpretations': [
        {'claimId': 'valid', 'scope': [{'field': 'nature', 'status': 'resolved',
                                        'value': '开单', 'evidence': ['开单']} ]},
        {'claimId': 'invalid', 'statistic': 'not_a_statistic'},
        {'claimId': 'duplicate'},
        {'claimId': 'duplicate', 'statistic': 'invalid'},
    ]})
    assert [item.claim_id for item in result.interpretations] == ['valid']
    assert result.interpretations[0].scope[0].evidence == ('开单',)


def test_semantic_json_mode_response_keeps_valid_items_at_provider_boundary():
    import json

    from agno.models.response import ModelResponse

    from smart_reporting.reporting.agent import ReportingPhaseOpenAIChat
    from smart_reporting.reporting.workflow.runtime.sections import (
        _validated_section_semantic_review,
    )

    model = ReportingPhaseOpenAIChat(id='test', api_key='test')
    model._report_response_validator = _validated_section_semantic_review
    response = ModelResponse(content=json.dumps({'interpretations': [
        {'claimId': 'valid', 'scope': [{'field': 'company', 'status': 'resolved',
                                       'value': '本院', 'evidence': ['本院']}]},
        {'claimId': 'invalid', 'statistic': 'invalid'},
    ]}, ensure_ascii=False))
    result = model._validated_reporting_response(model, response)
    assert [item.claim_id for item in result.content.interpretations] == ['valid']
    assert result.content.interpretations[0].scope[0].value == '本院'


@pytest.mark.anyio
async def test_semantic_batches_keep_full_context_and_isolate_failed_or_foreign_claims(monkeypatch):
    from types import SimpleNamespace

    from smart_reporting.reporting.delivery.draft_v1 import ReportDraftBlock
    from smart_reporting.reporting.model_policy import ThinkingRequest
    from smart_reporting.reporting.tests.test_semantic_bindings import contents
    from smart_reporting.reporting.trace.semantic_bindings import render_bound_numbers
    from smart_reporting.reporting.workflow.runtime import sections

    frozen = contents()
    blocks = [ReportDraftBlock(blockId='scope', markdown='本节共同口径为开单收入。')]
    for index in range(21):
        markdown, refs, _ = render_bound_numbers(
            f'独立项目{index}收入{{{{value:fact-aaaaaaaaaaaaaaaa:total:元}}}}。', frozen, key=f'batch-{index}')
        blocks.append(ReportDraftBlock(blockId=f'b{index}', markdown=markdown, numberReferences=refs))
    calls = []
    progress = []
    monkeypatch.setattr(sections, 'loguru_logger', SimpleNamespace(
        info=lambda message, *args: progress.append((message, args)), warning=lambda *_: None,
    ))

    async def review(agent, schema, stage, payload, **kwargs):
        calls.append(payload)
        assert len(payload['references']) <= 20
        assert {item['factId'] for item in payload['quantitySources']} == {'fact-aaaaaaaaaaaaaaaa'}
        context = next(iter(payload['contexts'].values()))
        assert '本节共同口径为开单收入' in context and '独立项目20收入' in context
        if len(calls) in {1, 3}:
            # 首个 20 条大批失败后拆半重试；拆出的 10 条批次再失败时不再拆分。
            raise RuntimeError('one batch unavailable')
        items = [{'claimId': item['claimId'], 'scope': [{'field': 'nature', 'value': '开单收入',
                 'status': 'resolved', 'evidence': ['本节共同口径为开单收入']}]} for item in payload['references']]
        if len(calls) == 2:
            # 上一批不能提前解释或替代另一批的引用。
            items.append({'claimId': blocks[11].number_references[0].claim_id})
        return schema.model_validate({'interpretations': items})

    monkeypatch.setattr(sections, '_run_section_stage', review)
    result = await sections._interpret_section_claims(object(), blocks, frozen, section_code='section_001',
        scope=SimpleNamespace(), run_context=SimpleNamespace(),
        thinking_request=ThinkingRequest(operation='section_generation', complexity='standard'))
    assert [len(item['references']) for item in calls] == [20, 10, 10, 1]
    reviewed = [number.semantic_receipt is not None for block in result for number in block.number_references]
    assert reviewed == [True] * 10 + [False] * 10 + [True]
    finished = [args for message, args in progress if 'report_claim_semantics_batch_completed' in message]
    assert [(args[1], args[2], args[3], args[4]) for args in finished] == [
        (1, 0, 21, 'split'), (2, 10, 21, 'completed'), (3, 20, 21, 'failed'), (4, 21, 21, 'completed'),
    ]


@pytest.mark.anyio
@pytest.mark.parametrize('budget_error', [False, True])
async def test_semantic_batches_fit_routed_budget_without_losing_claims_or_chapter(monkeypatch, budget_error):
    import json
    from types import SimpleNamespace

    from agno.run import RunContext

    from smart_reporting.reporting.delivery.draft_v1 import ReportDraftBlock
    from smart_reporting.reporting.model_policy import ThinkingRequest
    from smart_reporting.reporting.tests.test_semantic_bindings import contents
    from smart_reporting.reporting.trace.semantic_bindings import render_bound_numbers
    from smart_reporting.reporting.workflow.runtime import sections

    class Model:
        _task_execution_input_token_budget = 150

        def count_tokens(self, messages, **kwargs):
            payload = json.loads(messages[-1].content)
            return 20 + 30 * len(payload['references'])

    markdown, refs, _ = render_bound_numbers(
        '本章共同口径。' + '收入{{value:fact-aaaaaaaaaaaaaaaa:total:元}}。' * 11 + '末段口径。',
        contents(), key='bounded-semantics')
    calls = []

    async def review(agent, schema, stage, payload, **kwargs):
        assert len(payload['references']) <= (10 if budget_error else 4)
        assert all('本章共同口径' in text and '末段口径' in text for text in payload['contexts'].values())
        calls.extend(item['claimId'] for item in payload['references'])
        return schema.model_validate({'interpretations': [{'claimId': item['claimId']}
                                                          for item in payload['references']]})

    monkeypatch.setattr(sections, '_run_section_stage', review)
    if budget_error:
        def unavailable(*args, **kwargs):
            raise RuntimeError('预算解析暂时不可用')
        monkeypatch.setattr(sections, '_section_block_input_token_budget', unavailable)
    result = await sections._interpret_section_claims(
        SimpleNamespace(model=Model()), [ReportDraftBlock(blockId='b', markdown=markdown, numberReferences=refs)],
        contents(), section_code='s', scope=SimpleNamespace(), run_context=RunContext(run_id='r', session_id='s'),
        thinking_request=ThinkingRequest(operation='section_generation', complexity='standard'))
    assert calls == [number.claim_id for number in refs]
    assert all(number.semantic_receipt is not None for number in result[0].number_references)


@pytest.mark.parametrize('payload', [
    '{"interpretations": [',
    '{"interpretations": [], "unexpected": true}',
    '[{"claimId": "invalid_envelope"}]',
    {'interpretations': [], 'unexpected': True},
    {'interpretations': 'invalid'},
    {'interpretations': [{'claimId': str(index)} for index in range(501)]},
])
def test_semantic_batch_does_not_salvage_invalid_envelope(payload):
    from pydantic import ValidationError

    from smart_reporting.reporting.workflow.runtime.sections import (
        _validated_section_semantic_review,
    )

    with pytest.raises(ValidationError):
        _validated_section_semantic_review(payload)


@pytest.mark.anyio
async def test_semantic_invalid_item_only_leaves_that_reference_unreviewed(monkeypatch):
    from types import SimpleNamespace

    from smart_reporting.reporting.delivery.draft_v1 import ReportDraftBlock
    from smart_reporting.reporting.model_policy import ThinkingRequest
    from smart_reporting.reporting.tests.test_semantic_bindings import contents
    from smart_reporting.reporting.trace.semantic_bindings import render_bound_numbers
    from smart_reporting.reporting.workflow.runtime import sections

    frozen = contents()
    markdown, refs, notices = render_bound_numbers(
        '合计{{value:fact-aaaaaaaaaaaaaaaa:total:元}}，'
        '另列{{value:fact-aaaaaaaaaaaaaaaa:total:元}}。', frozen, key='partial-review',
    )
    blocks = (ReportDraftBlock(blockId='b', markdown=markdown, numberReferences=refs, reviewNotices=notices),)
    calls = []

    async def review(agent, schema, stage, payload, **kwargs):
        calls.append(payload)
        return kwargs['response_validator']({'interpretations': [
            {'claimId': refs[0].claim_id},
            {'claimId': refs[1].claim_id, 'statistic': 'invalid'},
            {'claimId': 'unknown-input-id'},
        ]})

    monkeypatch.setattr(sections, '_run_section_stage', review)
    review_notices = {}
    result = await sections._disambiguate_section_claims(
        object(), blocks, frozen, section_code='s', scope=SimpleNamespace(),
        run_context=SimpleNamespace(), thinking_request=ThinkingRequest(
            operation='section_generation', complexity='standard'), review_notices=review_notices,
    )
    assert len(calls) == 1
    assert result[0].markdown == markdown
    assert result[0].number_references[0].semantic_receipt is not None
    assert result[0].number_references[1].semantic_receipt is None
    assert review_notices['b'][0]['details']['count'] == 1


def test_section_context_crosses_subheadings_but_never_other_sections():
    from smart_reporting.reporting.trace.claim_semantics import claim_context

    markdown = ('## 前章\n\n甲院收入。\n\n## 本章\n\n[[section:current]]\n\n'
                '### 总体\n\n乙院开单收入。\n\n### 趋势\n\n本期100元[[claim:c]]。'
                '\n\n## 后章\n\n丙院收入。')
    context = claim_context(markdown, 'c', include_section=True)
    assert '乙院开单收入' in context
    assert '### 趋势' in context
    assert '甲院' not in context and '丙院' not in context


def test_section_receipt_invalidates_when_distant_scope_changes():
    from smart_reporting.reporting.trace.claim_semantics import (
        freeze_interpretation,
        semantic_receipt_status,
        semantic_warnings,
    )

    markdown = '### 总体\n\n乙院开单收入。\n\n### 趋势\n\n本期100元[[claim:c]]。'
    receipt = freeze_interpretation(markdown, 'c', {
        'claimId': 'c', 'scope': [{'field': 'company', 'value': '乙院',
                                  'status': 'resolved', 'evidence': ['乙院开单收入']}],
    }, include_section=True)
    assert semantic_receipt_status('## 本章\n\n[[section:s]]\n\n' + markdown, 'c', receipt) == 'interpreted'
    assert semantic_warnings(markdown, 'c', receipt, {'company': '乙院'}, (), [
        '业务范围需复核：当前引用句未体现登记范围 company=乙院。']) == []
    edited = markdown.replace('乙院', '丙院')
    assert semantic_receipt_status(edited, 'c', receipt) == 'invalidated'
    assert any('失效' in warning for warning in semantic_warnings(edited, 'c', receipt, {'company': '乙院'}, (), []))


def test_section_receipt_survives_rendered_visuals_tables_and_heading_numbers():
    from smart_reporting.reporting.trace.claim_semantics import (
        freeze_interpretation,
        semantic_receipt_status,
    )

    original = '### 总体\n\n乙院开单收入。\n\n### 趋势\n\n本期100元[[claim:c]]。'
    receipt = freeze_interpretation(original, 'c', {'claimId': 'c'}, include_section=True)
    rendered = ('## 1. 本章\n\n### 1.1 总体\n\n乙院开单收入。\n\n'
                '![收入图](chart.png)\n\n*图表：收入图*\n\n'
                '### 1.2 趋势\n\n本期100元[[claim:c]]。\n\n'
                '月度收入表\n\n[[table:t]]\n| 科室 | 金额 |\n| --- | --- |\n| 甲 | 100 |\n\n[[/table:t]]')
    assert semantic_receipt_status(rendered, 'c', receipt) == 'interpreted'
    assert semantic_receipt_status(rendered.replace('乙院', '丙院'), 'c', receipt) == 'invalidated'


def test_section_context_preserves_current_number_inside_markdown_table():
    from smart_reporting.reporting.trace.claim_semantics import claim_context

    markdown = ('本段为乙院开单收入。\n\n| 科室 | 收入 |\n| --- | --- |\n'
                '| 内科 | 100元[[claim:table-number]] |\n\n其他200元[[claim:body-number]]。')
    table = claim_context(markdown, 'table-number', include_section=True)
    body = claim_context(markdown, 'body-number', include_section=True)
    assert '【当前数值引用】' in table and '| 科室 | 收入 |' in table
    assert '本段为乙院开单收入' in table
    assert '【当前数值引用】' in body


def test_section_context_never_returns_context_without_current_marker():
    from smart_reporting.reporting.trace.claim_semantics import claim_context

    assert claim_context('![100元[[claim:c]]](figure.png)', 'c', include_section=True) is None


@pytest.mark.parametrize('inside_table', [False, True])
def test_section_context_excludes_unrelated_server_table_but_keeps_current_reference(inside_table):
    from smart_reporting.reporting.trace.claim_semantics import claim_context

    current = '100元[[claim:c]]' if inside_table else '100元'
    markdown = (
        '本节统计乙院开单收入。\n\n'
        '其他院区金额汇总\n\n[[table:other]]\n| 院区 | 金额 |\n| --- | --- |\n'
        '| 丙院 | 999元 |\n\n[[/table:other]]\n\n'
        '本院金额汇总\n\n[[table:current]]\n| 院区 | 金额 |\n| --- | --- |\n'
        f'| 乙院 | {current} |\n\n[[/table:current]]\n\n'
        + ('本期结果如表所示。' if inside_table else '本期收入100元[[claim:c]]。')
    )
    context = claim_context(markdown, 'c', include_section=True)
    assert context is not None
    assert '本节统计乙院开单收入' in context
    assert '100元【当前数值引用】' in context
    assert '其他院区金额汇总' not in context
    assert '丙院' not in context and '999元' not in context
    if inside_table:
        assert '本院金额汇总' in context
        assert '| 乙院 | 100元【当前数值引用】 |' in context
    else:
        assert '本院金额汇总' not in context


def test_quantity_fingerprint_keeps_denominator_role_but_not_revision_resource_location():
    from smart_reporting.reporting.trace.claim_semantics import quantity_binding_fingerprint
    reference = {'value':50,'unit':'%','formula':'10 / 20 * 100', 'denominatorFact':{
        'analysisId':'analysis_001','jsonPointer':'/metrics/0','factKey':'fact-'+'a'*16,
        'fileResourceId':'trf-'+'a'*20}}
    original = quantity_binding_fingerprint(reference)
    moved = {**reference,'denominatorFact':{**reference['denominatorFact'],'fileResourceId':'trf-'+'b'*20}}
    other = {**reference,'denominatorFact':{**reference['denominatorFact'],'factKey':'fact-'+'b'*16}}
    assert quantity_binding_fingerprint(moved) == original
    assert quantity_binding_fingerprint(other) != original

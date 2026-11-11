"""原生格式只给完整登记的同一段文字继承支持判断。"""

import hashlib
from types import SimpleNamespace

import pytest

from smart_reporting.reporting.semantics.models import ClaimSupport
from smart_reporting.reporting.trace.claim_semantics import freeze_interpretation
from smart_reporting.reporting.trace.native_claims import (
    native_claim_presentations,
    present_native_summary,
)
from smart_reporting.reporting.trace.semantic_bindings import statement_fingerprint


def inputs(text='建议核对付款时点。', *, kind='recommendation', status='supported', numeric=False):
    markdown = '# 报告\n\n' + text + '[[claim:claim-1]]\n'
    reference = SimpleNamespace(statement_sha256=statement_fingerprint(markdown, 'claim-1'),
        analysis_id='analysis_001',
        semantic_receipt=None if numeric else freeze_interpretation(markdown, 'claim-1', {
            'claimId': 'claim-1', 'claimKind': kind, 'kindEvidence': [text]},
            reference={'entry': {'basisId': 'test-basis'}}))
    subject = SimpleNamespace(subject_id='subject-1', claim_id='claim-1', locator=SimpleNamespace(section_id='budget'),
        fact_refs=(SimpleNamespace(analysis_id='analysis_001'),) if numeric else (),
        number_reference=reference if numeric else None, narrative_reference=None if numeric else reference)
    support = ClaimSupport(subjectId=subject.subject_id, kind=kind, supportStatus=status,
        evidenceRefs=['evidence-1'] if kind != 'fact' else [], factRefs=['fact-1'] if kind == 'fact' else [])
    return SimpleNamespace(subject_bindings=(subject,)), markdown, (support,)


@pytest.mark.parametrize('kind,status,label', [('recommendation', 'supported', '（建议）'),
    ('inference', 'unverified', '（推断，待核实）'), ('inference', 'conflicted', '（推断，存在反证）'),
    ('fact', 'supported', ''), ('fact', 'unverified', '（事实陈述，待核实）')])
def test_native_summary_preserves_current_support_only_for_whole_registered_text(kind, status, label):
    text = '预算合计为300元。' if kind == 'fact' else '建议核对付款时点。'
    index, markdown, supports = inputs(text, kind=kind, status=status, numeric=kind == 'fact')
    presentations = native_claim_presentations(index, markdown, supports)
    result = present_native_summary(text, presentations, section_ids=('budget',), analysis_ids=('analysis_001',))
    assert result['text'] == text + label
    assert result['support']['subjectId'] == 'subject-1'
    assert result['support']['supportStatus'] == status
    assert result['support']['sourceSha256'] == hashlib.sha256(markdown.encode()).hexdigest()
    edited = present_native_summary(text + '因此经营原因已证实。', presentations)
    assert edited['text'].endswith('（支持关系待核实）')
    assert edited['support']['supportStatus'] == 'unverified'
    assert 'subjectId' not in edited['support']


@pytest.mark.parametrize('fault', ['absent', 'edited', 'duplicated', 'mixed'])
def test_native_summary_never_borrows_support_from_same_number_or_adjacent_registered_sentence(fault):
    text = '预算合计为300元。'
    index, markdown, supports = inputs(text, kind='fact', numeric=True)
    if fault == 'absent':
        supports = ()
    elif fault == 'edited':
        markdown = markdown.replace('合计', '平均')
    elif fault == 'duplicated':
        markdown += '\n' + text + '[[claim:claim-1]]\n'
    else:
        markdown = markdown.replace('预算合计', '原因已经证实。预算合计')
        text = '原因已经证实。' + text
    result = present_native_summary(text, native_claim_presentations(index, markdown, supports))
    assert result['text'] == text + '（支持关系待核实）'
    assert result['support']['supportStatus'] == 'unverified'


def test_native_summary_does_not_classify_unregistered_text_by_fixed_business_phrases():
    for text in ['建议付款。', '付款安排影响预算执行。', '收入增加5%。']:
        result = present_native_summary(text, {})
        assert result['text'] == text + '（支持关系待核实）'
        assert result['support']['kind'] == 'unknown'


def test_specific_analysis_cannot_borrow_unscoped_document_support():
    text = '建议核对付款时点。'
    index, markdown, supports = inputs(text)
    index.subject_bindings[0].narrative_reference.analysis_id = None
    presentations = native_claim_presentations(index, markdown, supports)
    result = present_native_summary(text, presentations, section_ids=('budget',), analysis_ids=('analysis_001',))
    assert result['support']['supportStatus'] == 'unverified'
    assert 'subjectId' not in result['support']


def test_explicit_summary_uses_own_support_when_same_text_has_unscoped_document_support():
    text = '建议核对付款时点。'
    index, markdown, supports = inputs(text)
    presentations = native_claim_presentations(index, markdown, supports)
    value, = next(iter(presentations.values()))
    next(iter(presentations.values())).append({**value, 'analysisIds': [], 'subjectId': 'document-subject'})
    result = present_native_summary(text, presentations, section_ids=('budget',), analysis_ids=('analysis_001',))
    assert result['support']['subjectId'] == 'subject-1'


def test_native_narrative_cannot_reuse_a_receipt_after_preceding_sentence_changes():
    text = '建议核对付款时点。'
    index, markdown, supports = inputs(text)
    changed = '本次已经查明原因。' + text
    result = present_native_summary(changed, native_claim_presentations(index,
        markdown.replace(text, changed), supports), section_ids=('budget',))
    assert result['support']['supportStatus'] == 'unverified'
    assert 'subjectId' not in result['support']


@pytest.mark.parametrize('status', ['supported', 'unverified', 'conflicted'])
def test_workbook_summary_and_registered_claim_mapping_remain_bound_without_changing_numbers(status):
    from smart_reporting.reporting.workflow.runtime.workbook import build_workbook_sheets

    text = '建议核对付款时点。'
    index, markdown, supports = inputs(text, status=status)
    presentations = native_claim_presentations(index, markdown, supports)
    evidence = SimpleNamespace(analysis_id='analysis_001', summary=text, dataset_ids=('dataset-1',))
    manifest = SimpleNamespace(evidence=(evidence,), metric_definitions=())
    outline = SimpleNamespace(sections=(SimpleNamespace(code='budget', title='预算', analysis_ids=('analysis_001',)),))
    sheets, sources = build_workbook_sheets(manifest=manifest, outline=outline, period='2026-11',
        fact_documents={'analysis_001': {'metrics': [{'factId': 'fact-1', 'total': 0, 'unit': '元'}]}},
        datasets={}, claim_presentations=presentations)
    assert sheets[0]['rows'][1][3]['value'] == 0
    assert sheets[1]['rows'][1][2] == 0
    assert sheets[0]['rows'][1][6] == present_native_summary(text, presentations, section_ids=('budget',), analysis_ids=('analysis_001',))['text']
    assert sources['claims'][0]['cell'] == 'G2'
    assert sources['claims'][0]['support']['supportStatus'] == status


@pytest.mark.parametrize('fault', ['foreign_section', 'foreign_analysis', 'previous_context', 'section_context', 'ambiguous_subject'])
def test_same_native_text_cannot_borrow_support_from_foreign_or_omitted_context(fault):
    text = '预算合计为300元。'
    index, markdown, supports = inputs(text, kind='fact', numeric=True)
    subject = index.subject_bindings[0]
    if fault == 'ambiguous_subject':
        other = SimpleNamespace(**{**vars(subject), 'subject_id': 'subject-2'})
        index.subject_bindings += (other,)
        supports += (supports[0].model_copy(update={'subject_id': other.subject_id}),)
    if fault in {'previous_context', 'section_context'}:
        subject.number_reference.semantic_receipt = SimpleNamespace(
            includes_previous=fault == 'previous_context', includes_section=fault == 'section_context')
    presentations = native_claim_presentations(index, markdown, supports)
    result = present_native_summary(text, presentations,
        section_ids=('foreign' if fault == 'foreign_section' else 'budget',),
        analysis_ids=('foreign' if fault == 'foreign_analysis' else 'analysis_001',))
    assert result['text'] == text + '（支持关系待核实）'
    assert 'subjectId' not in result['support']

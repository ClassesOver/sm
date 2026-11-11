"""幻灯片数字必须来自明确的冻结结果，不能凭摘要金额相同猜绑定。"""

from hashlib import sha256
from types import SimpleNamespace

import pytest

from smart_reporting.reporting.tests.test_registered_claim_support import native_quality_inputs


@pytest.mark.anyio
async def test_registered_slide_preserves_visible_value_and_exact_fact_binding(tmp_path):
    from smart_reporting.reporting.hospital_operation.deterministic_analysis import (
        DeterministicAnalysisBundle,
    )
    from smart_reporting.reporting.semantics.analysis_facts import build_registered_finding_graph
    from smart_reporting.reporting.trace.issue_content import evaluate_calculation_content
    from smart_reporting.reporting.trace.semantic_bindings import (
        NumberReferenceResolver,
        anchor_bound_numbers,
        statement_fingerprint,
    )
    from smart_reporting.reporting.trace.subject_builder import (
        build_claim_subject_bindings,
        prepare_claim_status,
    )
    from smart_reporting.reporting.workflow.runtime.slides import build_slide_outline

    index, _, sources = await native_quality_inputs(tmp_path)
    entry, = index.fact_files
    file = next(item for item in index.files if item.resource_id == entry.file_resource_id)
    raw = sources[file.resource_id]
    bundle = DeterministicAnalysisBundle.model_validate_json(raw)
    context = bundle.metric_context
    graph = build_registered_finding_graph((bundle,), context=context, snapshot_hash='a' * 64,
        files={entry.analysis_id: {'path': file.path, 'sha256': sha256(raw).hexdigest()}},
        citations=(), dataset_snapshots={})
    # 摘要可能来自其他写作者；绑定必须按精确来源重新投影，不能认可摘要中的错误数字。
    graph = graph.model_copy(update={'findings': (graph.findings[0].model_copy(update={'summary': '预算为70元。'}),)})
    manifest = SimpleNamespace(evidence=(SimpleNamespace(analysis_id=entry.analysis_id,
        citation_ids=(), chart_ids=()),), charts=())
    outline = build_slide_outline(graph, manifest, title='预算核对', fact_contents={entry.analysis_id: raw})
    slide, = outline.slides
    block = slide.summary_block
    assert block is not None and len(block.number_references) == 1
    assert block.markdown == '- ' + slide.bullets[0]
    assert '70元' not in slide.bullets[0]
    assert '300.12CNY' in slide.bullets[0]
    assert block.number_references[0].token == '{{value:fact-budget:value:CNY}}'
    assert block.number_references[0].semantic_receipt.method == 'registered_result_projection_v1'
    markdown = anchor_bound_numbers(block.markdown, block.number_references, block.review_notices)
    number, = block.number_references
    assert statement_fingerprint(markdown, number.claim_id) == number.statement_sha256
    selected = NumberReferenceResolver((raw.decode(),)).resolve(number.token)
    detail = prepare_claim_status(markdown)(number.claim_id, selected['value'], expected_unit=selected['unit'],
        expected_scope=selected['scope'], expected_reference=selected, semantic_receipt=number.semantic_receipt)
    assert detail == {'status': 'valid', 'warnings': []}
    subjects = build_claim_subject_bindings((SimpleNamespace(section_code='section_001', blocks=(block,), claims=()),),
        {'fact-budget': (entry.analysis_id, '/metricContext/calculations/0/results/0')},
        {entry.analysis_id: file.resource_id})
    index = index.model_copy(update={'subject_bindings': subjects, 'tables': ()})
    result = evaluate_calculation_content(index, markdown, sources, context.calculations[0], report_revision='initial')
    assert result['factPresentationVerified'] is True
    assert result['coveredFactIds'] == ['fact-budget']
    assert result['businessApproval'] == 'not_performed'
    assert evaluate_calculation_content(index, markdown.replace('300.12', '70'),
        sources, context.calculations[0], report_revision='initial')['factPresentationVerified'] is False
    assert graph.findings[0].summary == '预算为70元。'


@pytest.mark.anyio
async def test_registered_slide_does_not_bind_wrong_source_or_pointer(tmp_path):
    from smart_reporting.reporting.hospital_operation.deterministic_analysis import (
        DeterministicAnalysisBundle,
    )
    from smart_reporting.reporting.models import ReportingError
    from smart_reporting.reporting.semantics.analysis_facts import build_registered_finding_graph
    from smart_reporting.reporting.workflow.runtime.slides import build_slide_outline

    index, _, sources = await native_quality_inputs(tmp_path)
    entry, = index.fact_files
    file = next(item for item in index.files if item.resource_id == entry.file_resource_id)
    raw = sources[file.resource_id]
    bundle = DeterministicAnalysisBundle.model_validate_json(raw)
    graph = build_registered_finding_graph((bundle,), context=bundle.metric_context, snapshot_hash='a' * 64,
        files={entry.analysis_id: {'path': file.path, 'sha256': sha256(raw).hexdigest()}},
        citations=(), dataset_snapshots={})
    manifest = SimpleNamespace(evidence=(SimpleNamespace(analysis_id=entry.analysis_id,
        citation_ids=(), chart_ids=()),), charts=())
    for content in ({}, {entry.analysis_id: raw + b' '}):
        with pytest.raises(ReportingError):
            build_slide_outline(graph, manifest, title='预算核对', fact_contents=content)
    card = graph.findings[0]
    wrong = card.model_copy(update={'source_refs': (card.source_refs[0].model_copy(
        update={'pointer': '/metricContext/calculations/0/results/99'}),)})
    with pytest.raises(ReportingError):
        build_slide_outline(graph.model_copy(update={'findings': (wrong,)}), manifest,
            title='预算核对', fact_contents={entry.analysis_id: raw})

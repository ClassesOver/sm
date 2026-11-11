"""纠错内容必须绑定精确计算及正文呈现，不能只匹配数值或依据。"""

import json

import pytest

from smart_reporting.reporting.tests.test_registered_claim_support import native_quality_inputs
from smart_reporting.reporting.trace.fact_service import read_fact_document


def calculation_from(index, sources):
    from smart_reporting.reporting.semantics.planning_contracts import MetricPlanningContext
    document = read_fact_document(sources[index.fact_files[0].file_resource_id])
    return MetricPlanningContext.model_validate(document['metricContext']).calculations[0]


@pytest.mark.anyio
async def test_content_requires_exact_calculation_and_current_visible_fact(tmp_path):
    from smart_reporting.reporting.trace.issue_content import evaluate_calculation_content
    index, markdown, sources = await native_quality_inputs(tmp_path)
    calculation = calculation_from(index, sources)
    result = evaluate_calculation_content(index, markdown, sources, calculation, report_revision='initial')
    assert result['factPresentationVerified'] is True
    assert result['coveredFactIds'] == ['fact-budget']
    assert result['businessApproval'] == 'not_performed'
    hidden = evaluate_calculation_content(index, '# 报告\n正文尚未采用修复结果。', sources, calculation, report_revision='initial')
    assert hidden['factPresentationVerified'] is False and hidden['missingFactIds'] == ['fact-budget']
    assert evaluate_calculation_content(index, markdown, sources, calculation, report_revision='other-revision')['factPresentationVerified'] is False
    different = calculation.model_copy(update={'receipt_id': 'another-calculation'})
    assert evaluate_calculation_content(index, markdown, sources, different, report_revision='initial')['factPresentationVerified'] is False
    value = calculation.results[0].model_copy(update={'value': calculation.results[0].value + 1})
    assert evaluate_calculation_content(index, markdown, sources,
        calculation.model_copy(update={'results': (value,)}), report_revision='initial')['factPresentationVerified'] is False


@pytest.mark.anyio
async def test_content_rejects_changed_source_and_incomplete_group_coverage(tmp_path):
    from smart_reporting.reporting.trace.issue_content import evaluate_calculation_content
    index, markdown, sources = await native_quality_inputs(tmp_path)
    calculation = calculation_from(index, sources)
    changed = {**sources, index.fact_files[0].file_resource_id: json.dumps({'metricContext': {}}).encode()}
    assert evaluate_calculation_content(index, markdown, changed, calculation, report_revision='initial')['factPresentationVerified'] is False
    extra = calculation.results[0].model_copy(update={'fact_id': 'fact-second-group'})
    result = evaluate_calculation_content(index, markdown, sources,
        calculation.model_copy(update={'results': (*calculation.results, extra)}), report_revision='initial')
    assert result['factPresentationVerified'] is False
    assert 'fact-second-group' in result['missingFactIds']


@pytest.mark.anyio
async def test_frozen_table_covers_exact_result_but_changed_cell_or_selector_does_not(tmp_path):
    from smart_reporting.reporting.hospital_operation.deterministic_analysis import (
        DeterministicAnalysisBundle,
    )
    from smart_reporting.reporting.trace.issue_content import evaluate_calculation_content
    from smart_reporting.reporting.trace.table_builder import build_analysis_tables

    index, _, sources = await native_quality_inputs(tmp_path)
    resource_id = index.fact_files[0].file_resource_id
    bundle = DeterministicAnalysisBundle.model_validate_json(sources[resource_id])
    table, markdown = build_analysis_tables(bundle, fact_file_resource_id=resource_id)[0]
    index = index.model_copy(update={'tables': (table,), 'subject_bindings': ()})
    calculation = calculation_from(index, sources)
    assert evaluate_calculation_content(index, markdown, sources, calculation, report_revision='initial')['factPresentationVerified'] is True
    assert evaluate_calculation_content(index, markdown.replace('300.123456789123456789', '70'),
        sources, calculation, report_revision='initial')['factPresentationVerified'] is False
    wrong = table.model_copy(update={'cells': tuple(cell.model_copy(update={'value_selector': 'total'}) for cell in table.cells)})
    assert evaluate_calculation_content(index.model_copy(update={'tables': (wrong,)}), markdown,
        sources, calculation, report_revision='initial')['factPresentationVerified'] is False

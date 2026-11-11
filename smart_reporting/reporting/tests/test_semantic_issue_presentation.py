"""各交付格式解释计算限制，同时保留原始事实及问题身份。"""

from copy import deepcopy
from decimal import Decimal
from types import SimpleNamespace

import pytest

from smart_reporting.reporting.semantics.analysis_facts import (
    build_registered_analysis_bundle,
    build_registered_finding_graph,
)
from smart_reporting.reporting.tests.test_registered_analysis_facts import analysis_inputs
from smart_reporting.reporting.tests.test_registered_workbook import workbook
from smart_reporting.reporting.trace.table_builder import build_analysis_tables
from smart_reporting.reporting.workflow.registered_overview import (
    RegisteredManagementOverview,
    RegisteredOverviewRow,
    registered_overview_projection,
)
from smart_reporting.reporting.workflow.runtime.slides import build_slide_outline


@pytest.mark.parametrize('code,value,status,message', [
    ('data_readiness_unknown', '300', 'computed', '数据完整性与更新状态尚未核实'),
    ('missing_data', None, 'unavailable', '未取得对应范围的数据'),
    ('zero_denominator', None, 'unavailable', '分母为零'),
    ('future_check_unknown', None, 'unavailable', '尚未识别的计算限制'),
])
def test_deliveries_explain_limitations_without_changing_facts(code, value, status, message):
    analysis, context, result = analysis_inputs()
    result = result.model_copy(update={'value': Decimal(value) if value is not None else None, 'status': status, 'issue_codes': (code,)})
    context = context.model_copy(update={'calculations': (
        context.calculations[0].model_copy(update={'results': (result,)}),)})
    # 完整往返验证契约，不能靠model_copy绕过业务值类型。
    context = type(context).model_validate(context.model_dump(mode='json', by_alias=True))
    bundle = build_registered_analysis_bundle(analysis, context, ())
    original = deepcopy(bundle.model_dump(mode='json', by_alias=True))
    graph = build_registered_finding_graph((bundle,), context=context, snapshot_hash='a' * 64,
        files={analysis.analysis_id: {'path': 'facts.json', 'sha256': 'b' * 64}},
        citations=(), dataset_snapshots={})
    original_graph = graph.model_dump(mode='json', by_alias=True)
    manifest = SimpleNamespace(evidence=(SimpleNamespace(analysis_id=analysis.analysis_id,
        citation_ids=(), chart_ids=()),), charts=())
    slides = build_slide_outline(graph, manifest, title='预算核对')
    sheets, sources = workbook(original)
    trace, table = build_analysis_tables(bundle, fact_file_resource_id='trf-' + 'a' * 20)[0]
    overview = RegisteredManagementOverview(report_basis_id=context.basis_id,
        input_sha256='b' * 64, markdown_sha256='c' * 64, status='evaluated',
        rows=(RegisteredOverviewRow(question_id='q-budget', question='预算是多少？',
            status='partial', issue_codes=(code,)),))
    visible = [table, ' '.join(slides.slides[0].bullets), sheets[1]['rows'][1][8],
        registered_overview_projection(overview, 'c' * 64)['markdown']]
    for text in visible:
        assert message in text
        assert code not in text
    assert bundle.model_dump(mode='json', by_alias=True) == original
    assert graph.model_dump(mode='json', by_alias=True) == original_graph
    assert code in graph.findings[0].limitations
    assert code in sources['cells'][0]['issueCodes']
    assert sources['cells'][0]['factId'] == result.fact_id
    assert trace.cells[0].fact_refs[0].fact_key == result.fact_id
    if status == 'unavailable':
        assert sheets[1]['rows'][1][2] is None
        assert '—' in table
        assert '无可用数值' in graph.findings[0].summary
        assert code not in graph.findings[0].summary
    else:
        assert sheets[1]['rows'][1][2] == 300


def test_free_text_finding_limitations_are_preserved():
    analysis, context, _ = analysis_inputs()
    graph = build_registered_finding_graph((build_registered_analysis_bundle(analysis, context, ()),),
        context=context, snapshot_hash='a' * 64,
        files={analysis.analysis_id: {'path': 'facts.json', 'sha256': 'b' * 64}},
        citations=(), dataset_snapshots={})
    card = graph.findings[0].model_copy(update={'limitations': ('尚缺项目B的结账记录，需财务核对。',)})
    graph = graph.model_copy(update={'findings': (card,)})
    manifest = SimpleNamespace(evidence=(SimpleNamespace(analysis_id=analysis.analysis_id,
        citation_ids=(), chart_ids=()),), charts=())
    assert build_slide_outline(graph, manifest, title='预算核对').slides[0].bullets[-1] == card.limitations[0]

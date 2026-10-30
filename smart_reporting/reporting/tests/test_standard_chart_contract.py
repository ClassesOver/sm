import json

import pytest
from pydantic import ValidationError

from smart_reporting.reporting.tests.test_reporting_phase_models import _chart
from smart_reporting.reporting.tests.test_standard_chart_presentation import render  # noqa: F401
from smart_reporting.reporting.workflow.runtime.chart_inputs import (
    ChartInputFile,
    ChartInputMaterialization,
)
from smart_reporting.reporting.workflow.runtime.phase_models import (
    ChartDraft,
    StandardChartSource,
    VisualizationPlanDraft,
)
from smart_reporting.reporting.workflow.runtime.standard_chart_alignment import align_chart_sources
from smart_reporting.reporting.workflow.runtime.standard_visualization import (
    standard_visualization_preflight,
)


def plan_and_inputs(documents, **options):
    payload = _chart('chart.png').model_dump(mode='json', by_alias=True)
    payload.update(visualForm='按业务需要突出重点月份', standardForm='bar',
                   standardValueFields=['value'], standardLabelField='period')
    payload.update(options)
    chart = ChartDraft.model_validate(payload)
    files = tuple(ChartInputFile(f'input-{i}.json', json.dumps(doc).encode())
                  for i, doc in enumerate(documents))
    inputs = ChartInputMaterialization(files=files, entries=tuple(
        dict(chartId=chart.chart_id, path=file.path, sha256=file.sha256) for file in files))
    return VisualizationPlanDraft(charts=(chart,)), inputs


def monthly():
    return {'columns': ['period', 'value'], 'rows': [['2025-01-01', 10], ['2025-02-01', 20]],
            'columnMeta': {'value': {'unit': '元'}}}


@pytest.mark.parametrize('description', [
    '单系列柱状图，横轴为2025年各月，逐月标注数值',
    '该图用来比较月份收入，机器类型不应从这段描述推断',
])
def test_machine_form_controls_rendering_independently_of_business_description(render, description):  # noqa: F811
    plan, inputs = plan_and_inputs([monthly()], visualForm=description)
    figure = render(plan, inputs)
    assert [bar.get_height() for bar in figure.axes[0].containers[0]] == [10, 20]
    assert not figure.axes[0].lines


def test_machine_form_rejects_noncanonical_values_without_fuzzy_matching():
    with pytest.raises(ValidationError):
        plan_and_inputs([monthly()], standardForm='普通柱状图')


def test_explicit_sum_summary_uses_frozen_rows_without_changing_input(render):  # noqa: F811
    document = monthly()
    plan, inputs = plan_and_inputs([document], standardPresentation={
        'summaries': [{'field': 'value', 'aggregation': 'sum', 'caption': '绑定月份合计'}]})
    figure = render(plan, inputs)
    assert '绑定月份合计 30.00元' in [text.get_text() for text in figure.texts]
    assert json.loads(inputs.files[0].content) == document


@pytest.mark.parametrize('unit', ['千元', '人次', '万人次', '床日'])
def test_sum_summary_accepts_registered_additive_unit_families(render, unit):  # noqa: F811
    document = monthly()
    document['columnMeta']['value']['unit'] = unit
    plan, inputs = plan_and_inputs([document], standardPresentation={
        'summaries': [{'field': 'value', 'aggregation': 'sum', 'caption': '冻结合计'}]})
    figure = render(plan, inputs)
    assert f'冻结合计 30.00{unit}' in [text.get_text() for text in figure.texts]


@pytest.mark.parametrize('fault', ['implicit_sum', 'percentage', 'missing', 'boolean', 'compound', 'unknown_unit'])
def test_summary_never_guesses_aggregation_or_sums_unsafe_values(fault):
    doc = monthly()
    summary = {'field': 'value', 'aggregation': 'sum'}
    if fault == 'implicit_sum':
        summary.pop('aggregation')
    elif fault == 'percentage':
        doc['columnMeta']['value'] = {'unit': '%', 'isPercent': True}
    elif fault == 'missing':
        doc['rows'][0][1] = None
    elif fault == 'compound':
        doc['columnMeta']['value']['unit'] = '元/人次'
    elif fault == 'unknown_unit':
        doc['columnMeta']['value']['unit'] = '未登记量纲'
    else:
        doc['rows'][0][1] = True
    plan, inputs = plan_and_inputs([doc], standardAxes={'allowNulls': True},
                                  standardPresentation={'summaries': [summary]})
    assert standard_visualization_preflight(plan, inputs).source is None


def test_yoy_bar_accepts_distinct_years_but_preserves_amounts_and_metadata(render):  # noqa: F811
    doc = {'columns': ['area', 'current', 'baseline'], 'rows': [['甲', 120, 100], ['乙', 240, 200]],
           'columnMeta': {'current': {'unit': '元', 'periods': ['2025-01-01', '2025-02-01']},
                          'baseline': {'unit': '元', 'periods': ['2024-01-01', '2024-02-01']}}}
    plan, inputs = plan_and_inputs([doc], standardLabelField='area',
        standardValueFields=['current', 'baseline'], comparisonType='yoy', comparisonPeriod='2024-01至2024-02',
        standardStyle={'series': [{'series': 'current', 'geometry': 'bar'},
                                  {'series': 'baseline', 'geometry': 'bar'}]})
    figure = render(plan, inputs)
    assert [bar.get_height() for bar in figure.axes[0].containers[0]] == [120, 240]
    assert [bar.get_height() for bar in figure.axes[0].containers[1]] == [100, 200]
    assert json.loads(inputs.files[0].content) == doc
    doc['columnMeta']['baseline']['periods'] = ['2024-01-01', '2024-03-01']
    bad_plan, bad_inputs = plan_and_inputs([doc], **{
        k: v for k, v in plan.charts[0].model_dump(mode='json', by_alias=True).items()
        if k not in {'dataBindings'}})
    result = standard_visualization_preflight(bad_plan, bad_inputs)
    assert result.source is None
    assert result.diagnostic['code'] == 'standard_period_alignment_invalid'


def test_explicit_month_of_year_alignment_renders_yoy_without_overwriting_dates(render):  # noqa: F811
    current = monthly()
    current['rows'].append(['2025-03-01', 30])
    previous = {'columns': ['period', 'value'], 'rows': [['2024-02-01', 18], ['2024-01-01', 9]],
                'columnMeta': {'value': {'unit': '元'}}}
    plan, inputs = plan_and_inputs([current, previous], comparisonType='yoy', comparisonPeriod='2024-01至2024-02',
        standardValueFields=['本期', '同期'], standardSourceLabels=['01', '02'],
        standardSources=[{'sourceIndex': 0, 'labelField': 'period', 'valueField': 'value',
                          'seriesName': '本期', 'labelMode': 'month_of_year', 'periodYear': 2025},
                         {'sourceIndex': 1, 'labelField': 'period', 'valueField': 'value',
                          'seriesName': '同期', 'labelMode': 'month_of_year', 'periodYear': 2024}],
        standardPresentation={'labelMode': 'month_of_year'})
    figure = render(plan, inputs)
    assert [tick.get_text() for tick in figure.axes[0].get_xticklabels()] == ['1月', '2月']
    assert [bar.get_height() for bar in figure.axes[0].containers[0]] == [10, 20]
    assert [bar.get_height() for bar in figure.axes[0].containers[1]] == [9, 18]
    assert json.loads(inputs.files[1].content) == previous


def test_month_of_year_yoy_accepts_multiple_registered_series_per_year(render):  # noqa: F811
    documents = []
    selections = []
    for index, year in enumerate((2025, 2025, 2024, 2024)):
        documents.append({'columns': ['period', 'value'],
            'rows': [[f'{year}-01-01', 10 + index], [f'{year}-02-01', 20 + index]],
            'columnMeta': {'value': {'unit': '床日'}}})
        selections.append({'sourceIndex': index, 'labelField': 'period', 'valueField': 'value',
                           'seriesName': f'系列{index}', 'labelMode': 'month_of_year', 'periodYear': year})
    plan, inputs = plan_and_inputs(documents, comparisonType='yoy', comparisonPeriod='2024-01至2024-02',
        standardForm='line', standardValueFields=[item['seriesName'] for item in selections],
        standardSourceLabels=['01', '02'], standardSources=selections,
        standardPresentation={'labelMode': 'month_of_year'})
    figure = render(plan, inputs)
    assert [list(line.get_ydata()) for line in figure.axes[0].lines] == [
        [10, 20], [11, 21], [12, 22], [13, 23]]
    assert [json.loads(file.content) for file in inputs.files] == documents


@pytest.mark.parametrize('fault', ['third_year', 'different_months', 'duplicate_month'])
def test_multiple_yoy_series_still_reject_incompatible_period_windows(fault):
    windows = [['2025-01', '2025-02'], ['2025-01', '2025-02'],
               ['2024-01', '2024-02'], ['2024-01', '2024-02']]
    windows[-1] = {'third_year': ['2023-01', '2023-02'],
                  'different_months': ['2024-01', '2024-03'],
                  'duplicate_month': ['2024-01-01', '2024-01-02']}[fault]
    columns = ['current_a', 'current_b', 'previous_a', 'previous_b']
    document = {'columns': ['area', *columns], 'rows': [['甲', 10, 20, 30, 40]],
                'columnMeta': {name: {'unit': '床日', 'periods': window}
                               for name, window in zip(columns, windows, strict=True)}}
    plan, inputs = plan_and_inputs([document], comparisonType='yoy', comparisonPeriod='2024-01至2024-02',
        standardLabelField='area', standardValueFields=columns,
        standardStyle={'series': [{'series': name, 'geometry': 'bar'} for name in columns]})
    result = standard_visualization_preflight(plan, inputs)
    assert result.source is None
    assert result.diagnostic['code'] == 'standard_period_alignment_invalid'


@pytest.mark.parametrize('fault', ['wrong_year', 'duplicate_month', 'missing_month', 'identity'])
def test_month_of_year_alignment_rejects_unsafe_sources(fault):
    left, right = monthly(), monthly()
    if fault == 'wrong_year':
        right['rows'][0][0] = '2024-01-01'
    elif fault == 'duplicate_month':
        right['rows'][1][0] = '2025-01-02'
    elif fault == 'missing_month':
        right['rows'].pop()
    files = tuple(ChartInputFile(f'{i}.json', json.dumps(doc).encode()) for i, doc in enumerate([left, right]))
    entries = [dict(path=file.path, sha256=file.sha256) for file in files]
    if fault == 'identity':
        entries[1]['sha256'] = '0' * 64
    selections = [StandardChartSource(sourceIndex=i, labelField='period', valueField='value',
        seriesName=f'系列{i}', labelMode='month_of_year', periodYear=2025) for i in range(2)]
    assert align_chart_sources(entries, files, selections) is None


def test_month_of_year_requires_explicit_year_scope():
    with pytest.raises(ValidationError):
        StandardChartSource(sourceIndex=0, labelField='period', valueField='value',
                            seriesName='本期', labelMode='month_of_year')


@pytest.mark.anyio
@pytest.mark.parametrize('anyio_backend', ['asyncio'])
@pytest.mark.parametrize('repair_succeeds', [True, False])
@pytest.mark.parametrize('preflight_error', [True, False])
async def test_workflow_replans_parameters_once_without_changing_facts_or_blocking(repair_succeeds, preflight_error):
    from smart_reporting.reporting.models import ReportingError
    from smart_reporting.reporting.tests.test_reporting_fixed_phase_workflows import (
        _context,
        _execution_receipt,
        _inspection,
        _visualization_payload,
        _visualization_plan,
    )
    from smart_reporting.reporting.workflow.checkpoint import FileIdentity
    from smart_reporting.reporting.workflow.runtime.code_generation import CodeGenerationResult
    from smart_reporting.reporting.workflow.runtime.visualization_section_workflow import (
        VisualizationSectionWorkflow,
    )

    original = _visualization_plan()
    from smart_reporting.reporting.workflow.runtime.phase_models import (
        StandardChartPresentation,
        StandardChartView,
    )
    original = original.model_copy(update={'charts': (original.charts[0].model_copy(update={
        'standard_labels': ('2025-02-01',),
        'standard_view': StandardChartView(kind='group', labelField='period', valueFields=['value']),
        'standard_presentation': StandardChartPresentation(subtitle='原业务说明', summaries=[
            {'field': 'value', 'aggregation': 'sum', 'caption': '绑定月份合计'}]),
    }),)})
    file = ChartInputFile('input.json', json.dumps(monthly()).encode())
    inputs = ChartInputMaterialization(files=(file,), entries=(
        dict(chartId='chart_001', path=file.path, sha256=file.sha256),))
    requests, executed = [], []

    async def generate(payload, _context):
        requests.append(payload)
        if len(requests) == 1:
            return original
        assert len(requests) == 2
        assert requests[0]['standardChartCapabilities']['forms'] == payload['standardChartCapabilities']['forms']
        assert 'bar' in payload['standardChartCapabilities']['forms']
        assert payload['standardChartCorrections'][0]['code'] == 'standard_form_unsupported'
        if not repair_succeeds:
            raise ReportingError('report_structured_output_invalid', '模拟规划纠错失败')
        return original.model_copy(update={'charts': (_visualization_plan().charts[0].model_copy(update={
            'standard_form': 'bar', 'title': '不应接受的业务改写', 'current_period': '2030-01',
            'standard_presentation': StandardChartPresentation(sourceNote='更新来源说明'),
            'source_path': 'charts/replaced.png'}),)})

    async def preflight(plan, _context):
        from smart_reporting.reporting.workflow.runtime.standard_visualization import (
            standard_plan_diagnostics,
        )
        if preflight_error:
            raise RuntimeError('模拟优化预检异常')
        return standard_plan_diagnostics(plan, inputs)

    async def run_code(plan, _context, **kwargs):
        executed.append(plan)
        return CodeGenerationResult(
            script_file=FileIdentity(path='charts/charts.py', size=1, sha256='b' * 64),
            execution_receipt=_execution_receipt('charts/charts.py', 1, 'b' * 64, ('charts/chart.png',)),
            visual_inspection_receipts=(_inspection(),))

    async def submit(plan, _inspections, _context):
        return {'status': 'accepted'}

    workflow = VisualizationSectionWorkflow(generate_plan=generate, run_code=run_code,
        submit=submit, preflight_plan=preflight)
    result = await workflow.run(_visualization_payload(), _context())
    assert result.status == 'accepted'
    assert len(requests) == (1 if preflight_error else 2)
    assert len(executed) == 1
    chart = result.plan.charts[0]
    assert chart.source_path == original.charts[0].source_path
    assert chart.title == original.charts[0].title
    assert chart.current_period == original.charts[0].current_period
    assert chart.data_bindings == original.charts[0].data_bindings
    assert chart.standard_labels == ('2025-02-01',)
    assert chart.standard_view == original.charts[0].standard_view
    assert chart.standard_presentation.subtitle == '原业务说明'
    assert chart.standard_presentation.summaries == original.charts[0].standard_presentation.summaries
    assert chart.standard_form == ('bar' if repair_succeeds and not preflight_error else None)
    if repair_succeeds and not preflight_error:
        assert chart.standard_presentation.source_note == '更新来源说明'
        assert standard_visualization_preflight(result.plan, inputs).source is not None


def test_explicit_custom_chart_is_not_replanned_as_standard():
    from smart_reporting.reporting.workflow.runtime.standard_visualization import (
        standard_plan_diagnostics,
    )
    plan, inputs = plan_and_inputs([monthly()], standardForm='custom')
    assert standard_plan_diagnostics(plan, inputs) == []
    assert standard_visualization_preflight(plan, inputs).diagnostic['code'] == 'standard_custom_requested'


def test_empty_registered_series_requests_source_correction_instead_of_filling_zero():
    from smart_reporting.reporting.workflow.runtime.standard_visualization import (
        standard_plan_diagnostics,
    )

    document = monthly()
    for row in document['rows']:
        row[1] = None
    plan, inputs = plan_and_inputs([document], standardAxes={'allowNulls': True})
    issues = standard_plan_diagnostics(plan, inputs)
    assert issues[0]['code'] == 'standard_series_empty'
    assert issues[0]['bindingCorrectionAllowed'] is True


@pytest.mark.anyio
@pytest.mark.parametrize('anyio_backend', ['asyncio'])
@pytest.mark.parametrize('source', ['registered', 'foreign', 'other_analysis', 'other_metric',
                                   'other_scope', 'other_unit', 'other_field', 'other_aggregation'])
async def test_source_correction_rebinds_only_registered_same_analysis_series(source):
    from smart_reporting.reporting.tests.test_reporting_fixed_phase_workflows import (
        _context,
        _execution_receipt,
        _inspection,
        _visualization_payload,
        _visualization_plan,
    )
    from smart_reporting.reporting.workflow.checkpoint import FileIdentity
    from smart_reporting.reporting.workflow.runtime.code_generation import CodeGenerationResult
    from smart_reporting.reporting.workflow.runtime.visualization_section_workflow import (
        VisualizationSectionWorkflow,
    )

    original = _visualization_plan()
    chart = original.charts[0]
    payload = _visualization_payload()
    candidate = chart.data_bindings[0].model_copy(update={'data_path': 'metrics[1].periodValues'})
    payload['visualizationFacts'][0]['dataDescriptors'].append({
        'dataPath': candidate.data_path, 'fields': list(candidate.fields)})
    primary = {'metricIndex': 0, 'datasetId': chart.source_dataset_id, 'metricCodes': list(chart.metric_codes),
               'field': 'income', 'fieldRef': 'hospital.income', 'aggregation': 'sum',
               'periodAggregation': 'sum', 'scope': {'company': '甲院'}, 'unit': '元'}
    secondary = {**primary, 'metricIndex': 1, 'datasetId': 'dataset_previous', 'periodRoles': ['yoy']}
    secondary.update({'other_metric': {'metricCodes': ['expense']},
                      'other_scope': {'scope': {'company': '乙院'}}, 'other_unit': {'unit': '人次'},
                      'other_field': {'field': 'expense', 'fieldRef': 'hospital.expense'},
                      'other_aggregation': {'aggregation': 'mean'}}.get(source, {}))
    payload['visualizationFacts'][0]['metrics'] = [primary, secondary]
    if source == 'foreign':
        candidate = candidate.model_copy(update={'fact_path': 'foreign.json', 'data_path': 'unknown'})
    elif source == 'other_analysis':
        candidate = candidate.model_copy(update={'analysis_id': 'analysis_002'})
        payload['visualizationFacts'].append({
            'analysisId': 'analysis_002', 'factFile': {'path': candidate.fact_path},
            'dataDescriptors': [{'dataPath': candidate.data_path, 'fields': list(candidate.fields)}]})
    calls = []

    async def generate(request, _context):
        calls.append(request)
        if len(calls) == 1:
            return original
        return original.model_copy(update={'charts': (chart.model_copy(update={
            'data_bindings': (candidate,), 'standard_form': 'line',
            'title': '不得覆盖原业务目标', 'source_path': 'changed.png', 'current_period': '2030'}),)})

    async def preflight(plan, _context):
        return [{'chartId': chart.chart_id, 'code': 'standard_series_empty', 'bindingCorrectionAllowed': True}]

    async def run_code(plan, _context, **kwargs):
        return CodeGenerationResult(script_file=FileIdentity(path='charts/charts.py', size=1, sha256='b' * 64),
            execution_receipt=_execution_receipt('charts/charts.py', 1, 'b' * 64, (chart.source_path,)),
            visual_inspection_receipts=(_inspection(),))

    async def submit(*args):
        return {'status': 'accepted'}

    result = await VisualizationSectionWorkflow(generate_plan=generate, preflight_plan=preflight,
        run_code=run_code, submit=submit).run(payload, _context())
    assert result.status == 'accepted' and len(calls) == 2
    actual = result.plan.charts[0]
    assert actual.data_bindings == ((candidate,) if source == 'registered' else chart.data_bindings)
    assert (actual.title, actual.source_path, actual.current_period) == (
        chart.title, chart.source_path, chart.current_period)


def test_parameter_repair_distinguishes_explicit_clear_from_omission():
    from smart_reporting.reporting.workflow.runtime.phase_models import (
        StandardChartPresentation,
        StandardChartView,
    )
    from smart_reporting.reporting.workflow.runtime.visualization_section_workflow import (
        _merge_standard_chart_parameters,
    )

    chart = _chart().model_copy(update={
        'standard_labels': ('2025-02-01',),
        'standard_view': StandardChartView(kind='group', labelField='period', valueFields=['value']),
        'standard_presentation': StandardChartPresentation(subtitle='保留原说明', summaries=[
            {'field': 'value', 'aggregation': 'sum'}]),
    })
    payload = _chart().model_dump(by_alias=True, exclude_unset=True)
    payload.update(standardView=None, standardPresentation={'summaries': []})
    repaired = _merge_standard_chart_parameters(chart, ChartDraft.model_validate(payload))
    assert repaired.standard_labels == ('2025-02-01',)
    assert repaired.standard_view is None
    assert repaired.standard_presentation.subtitle == '保留原说明'
    assert repaired.standard_presentation.summaries == ()

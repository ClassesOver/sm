import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from smart_reporting.reporting.tests.test_standard_chart_presentation import render  # noqa: F401
from smart_reporting.reporting.workflow.runtime.chart_inputs import (
    ChartInputMaterialization,
    materialize_chart_inputs,
)
from smart_reporting.reporting.workflow.runtime.phase_models import (
    ChartDraft,
    StandardChartPagination,
    VisualizationPlanDraft,
)
from smart_reporting.reporting.workflow.runtime.standard_chart_pagination import (
    expand_standard_pagination,
    prepare_standard_paginated_plan,
)
from smart_reporting.reporting.workflow.runtime.standard_visualization import (
    standard_visualization_preflight,
)


def pagination_plan(count=65, page_size=30, *, form="barh", rows=None, **updates):
    document = {"columns": ["label", "actual", "budget"],
        "rows": rows if rows is not None else [[f"类别{n:03d}", n*10000-90000, (n+1)*20000] for n in range(count)],
        "columnMeta": {"actual": {"unit": "元"}, "budget": {"unit": "元"}}}
    chart = ChartDraft(chartId="chart", sourcePath="chart.png", title="完整类别预算对照", altText="全部类别逐页显示",
        citationIds=["citation"], metricCodes=["metric"], currentPeriod="2026-10", sourceDatasetId="dataset",
        aggregationGrain="category", visualForm=form, standardValueFields=["actual", "budget"],
        standardPagination={"pageSize": page_size}, standardDisplayUnit="万元", standardStyle={"labelRotation": 0},
        dataBindings=[{"analysisId": "a", "factPath": "facts.json", "dataPath": "findings[0].rows", "fields": document["columns"], "role": "完整类别汇总"}])
    chart = chart.model_copy(update=updates)
    plan = VisualizationPlanDraft.model_validate_json(VisualizationPlanDraft(charts=(chart,)).model_dump_json(by_alias=True))
    blob = json.dumps({"findings": [document]}, ensure_ascii=False).encode()
    facts = [{"analysisId": "a", "factFile": {"path": "facts.json", "size": len(blob), "sha256": hashlib.sha256(blob).hexdigest()},
        "dataDescriptors": [{"dataPath": "findings[0].rows", "fields": document["columns"]}]}]
    documents = {"facts.json": {"findings": [document]}}
    inputs = materialize_chart_inputs(plan, facts, documents, output_root="inputs")
    return plan, inputs, facts, documents, blob


@pytest.mark.parametrize("invalid", [True, 1.5, 0, 61])
def test_pagination_schema_rejects_noninteger_and_out_of_capacity_page_size(invalid):
    with pytest.raises(ValidationError):
        StandardChartPagination(pageSize=invalid)


@pytest.mark.parametrize("invalid", [True, 1.5, 0, 21])
def test_pagination_schema_rejects_invalid_max_pages(invalid):
    with pytest.raises(ValidationError):
        StandardChartPagination(pageSize=20, maxPages=invalid)


def test_pagination_roundtrip_conserves_all_rows_binding_identity_and_shared_domains():
    plan, inputs, facts, documents, _ = pagination_plan()
    expanded = expand_standard_pagination(plan, inputs)
    assert len(expanded.charts) == 3
    original = plan.charts[0]
    assert [label for chart in expanded.charts for label in chart.standard_labels] == [row[0] for row in documents['facts.json']['findings'][0]['rows']]
    assert len({chart.standard_domains.model_dump_json() for chart in expanded.charts}) == 1
    assert [chart.source_path for chart in expanded.charts] == ["chart.png", "chart--page-2.png", "chart--page-3.png"]
    for n, chart in enumerate(expanded.charts, 1):
        assert chart.data_bindings == original.data_bindings and chart.standard_pagination is None
        assert f"第{n}/3页" in chart.title and f"第{n}/3页" in chart.alt_text
        assert "总计65类" in chart.standard_presentation.source_note
    final_inputs = materialize_chart_inputs(expanded, facts, documents, output_root="inputs")
    for file in final_inputs.files:
        payload = json.loads(file.content)
        assert payload['rows'] == documents['facts.json']['findings'][0]['rows']
        assert payload['source']['sha256'] == facts[0]['factFile']['sha256']
    roundtrip = VisualizationPlanDraft.model_validate_json(expanded.model_dump_json(by_alias=True))
    assert roundtrip == expanded


@pytest.mark.parametrize("form", ["bar", "barh"])
def test_all_pagination_pngs_preserve_frozen_geometry_uniform_units_colors_and_numeric_range(render, monkeypatch, form):  # noqa: F811
    import matplotlib.figure
    from matplotlib.colors import to_hex

    plan, inputs, facts, documents, _ = pagination_plan(25, 10, form=form)
    expanded = expand_standard_pagination(plan, inputs)
    final_inputs = materialize_chart_inputs(expanded, facts, documents, output_root=".")
    saved = []
    original_save = matplotlib.figure.Figure.savefig
    def capture(fig, *args, **kwargs):
        saved.append(fig)
        return original_save(fig, *args, **kwargs)
    monkeypatch.setattr(matplotlib.figure.Figure, "savefig", capture)
    render(expanded, final_inputs)
    domains = []
    for page, fig in zip(expanded.charts, saved):
        ax = fig.axes[0]
        assert len(ax.containers) == 2
        domains.append(ax.get_xlim() if form=="barh" else ax.get_ylim())
        selected = [row for row in documents['facts.json']['findings'][0]['rows'] if row[0] in page.standard_labels]
        for i, container in enumerate(ax.containers):
            assert [bar.get_width() if form=="barh" else bar.get_height() for bar in container] == [row[i+1]/1e4 for row in selected]
            assert all(to_hex(bar.get_facecolor()) == ['#3066a3','#dc884d'][i] for bar in container)
        assert "万元" in (ax.get_xlabel() if form=="barh" else ax.get_ylabel())
        assert Path(page.source_path).read_bytes().startswith(b'\x89PNG')
    assert domains[0] == domains[1] == domains[2]


@pytest.mark.parametrize("budget", [1, 2])
def test_pagination_budget_never_drops_partial_pages_or_pending_spec(budget):
    plan, inputs, *_ = pagination_plan()
    result = expand_standard_pagination(plan, inputs, max_charts=budget)
    assert result.charts == plan.charts and result.charts[0].standard_pagination
    assert "图数预算" in result.warnings[-1] and "不截断页面" in result.warnings[-1]


@pytest.mark.parametrize("field,value", [("chart_id", "chart__page_2"), ("source_path", "chart--page-2.png")])
def test_pagination_id_or_path_collision_is_atomic(field, value):
    plan, inputs, *_ = pagination_plan(4, 2)
    other = plan.charts[0].model_copy(update={"chart_id": "other", "source_path": "other.png", "standard_pagination": None, field: value})
    result = expand_standard_pagination(VisualizationPlanDraft(charts=(*plan.charts, other)), inputs)
    assert result.charts[0] == plan.charts[0] and len(result.charts)==2
    assert "冲突" in result.warnings[-1]


def test_pagination_validates_identity_before_selecting_any_rows():
    plan, inputs, *_ = pagination_plan()
    inputs.entries[0]['sha256'] = '0'*64
    result = expand_standard_pagination(plan, inputs)
    assert result.charts==plan.charts and "身份不符" in result.warnings[-1]


@pytest.mark.parametrize("unit,percent,values", [("元",None,[1e-320,2e-320]),("元",None,[1e308,-1e308])])
def test_pagination_rejects_underflow_and_unrepresentable_span(unit, percent, values):
    plan, _, facts, documents, _ = pagination_plan(2, 1)
    table = documents['facts.json']['findings'][0]
    table['rows'] = [['甲',values[0],values[0]],['乙',values[1],values[1]]]
    table['columnMeta'] = {field:{'unit':unit} for field in ['actual','budget']}
    if values[0]<1:
        plan=plan.model_copy(update={'charts':(plan.charts[0].model_copy(update={'standard_display_unit':'亿元'}),)})
    else:
        plan=plan.model_copy(update={'charts':(plan.charts[0].model_copy(update={'standard_display_unit':None}),)})
    inputs = materialize_chart_inputs(plan,facts,documents,output_root='inputs')
    result = expand_standard_pagination(plan, inputs)
    assert result.charts==plan.charts and result.warnings


@pytest.mark.parametrize("fault", ["max_pages", "duplicate", "mixed_units", "missing", "point", "topn", "summary", "too_many_rows"])
def test_unsupported_pagination_preserves_whole_chart_and_reason(fault):
    plan, _, facts, documents, _ = pagination_plan()
    chart = plan.charts[0]
    table = documents['facts.json']['findings'][0]
    if fault=='max_pages':
        chart=chart.model_copy(update={'standard_pagination':chart.standard_pagination.model_copy(update={'max_pages':2})})
    elif fault=='duplicate':
        table['rows'][1][0] = table['rows'][0][0]
    elif fault=='mixed_units':
        table['columnMeta']['budget']['unit']='万元'
    elif fault=='missing':
        table['rows'][0][1]=None
    elif fault=='point':
        from smart_reporting.reporting.workflow.runtime.phase_models import StandardChartAnnotation
        chart=chart.model_copy(update={'standard_annotations':(StandardChartAnnotation(kind='point',series='actual',label='类别000'),)})
    elif fault=='topn':
        chart=chart.model_copy(update={'standard_presentation':chart.standard_presentation.model_copy(update={'order':chart.standard_presentation.order.model_copy(update={'limit':10})})})
    elif fault=='summary':
        chart=chart.model_copy(update={'standard_total_field':'actual'})
    else:
        table['rows'] = [[f'类别{i}',i,i+1] for i in range(481)]
    plan=plan.model_copy(update={'charts':(chart,)})
    inputs = materialize_chart_inputs(plan,facts,documents,output_root='inputs')
    result = expand_standard_pagination(plan,inputs)
    assert result.charts==plan.charts and result.warnings


@pytest.mark.anyio
@pytest.mark.parametrize('anyio_backend',['asyncio'])
async def test_async_host_pagination_requires_fact_sha_and_registers_all_pages_in_workflow(tmp_path):
    from agno.run import RunContext

    from smart_reporting.reporting.code_agent.context import ExecutionReceipt
    from smart_reporting.reporting.workflow.checkpoint import (
        ChartVisualInspectionReceipt,
        FileIdentity,
    )
    from smart_reporting.reporting.workflow.runtime.code_generation import CodeGenerationResult
    from smart_reporting.reporting.workflow.runtime.visualization_section_workflow import (
        VisualizationSectionWorkflow,
    )

    plan, _, facts, _, blob = pagination_plan(25,10)
    writes = {}
    async def read(*args, **kwargs):
        return blob
    async def write(thread_id,path,content,**kwargs):
        writes[path]=content
    workspace=SimpleNamespace(read_limited_regular_file=read,awrite_bytes=write)
    expanded = await prepare_standard_paginated_plan(plan,facts,workspace,thread_id='task',output_root='inputs')
    assert len(expanded.charts)==3
    paths = tuple(chart.source_path for chart in expanded.charts)
    script = FileIdentity(path='charts.py',size=1,sha256='b'*64)
    receipt = ExecutionReceipt(runId='run',sourceFile=script,outputFiles=tuple(FileIdentity(path=path,size=1,sha256='a'*64) for path in paths))
    inspections=tuple(ChartVisualInspectionReceipt(sourcePath=path,sha256='a'*64,reviewed=True,requiresRevision=False,inspectionMode='vision',modelId='fixture-vision') for path in paths)
    code = CodeGenerationResult(script_file=script,execution_receipt=receipt,visual_inspection_receipts=inspections)
    submit=AsyncMock(return_value={'status':'accepted'})
    workflow=VisualizationSectionWorkflow(generate_plan=AsyncMock(return_value=expanded),run_code=AsyncMock(return_value=code),submit=submit)
    result=await workflow.run({'visualizationWorkspace':{'scriptPath':'charts.py'},'visualizationFacts':facts},RunContext(run_id='run',session_id='s'))
    assert result.status=='accepted' and len(result.inspections)==3
    submitted=submit.call_args.args[0]
    assert tuple(chart.source_path for chart in submitted.charts)==paths
    assert len(submit.call_args.args[1])==3
    facts[0]['factFile']['sha256']='0'*64
    unexpanded=await prepare_standard_paginated_plan(plan,facts,workspace,thread_id='task',output_root='inputs')
    assert unexpanded.charts==plan.charts and unexpanded.warnings


def test_pending_pagination_is_not_silently_ignored_by_compiler():
    plan, inputs, *_ = pagination_plan(4,2)
    preflight=standard_visualization_preflight(plan,inputs)
    assert preflight.source is None
    assert preflight.diagnostic['code']=='standard_pagination_not_expanded'


def test_chart_without_pagination_retains_original_plan_instance():
    plan,*_=pagination_plan()
    plan=plan.model_copy(update={'charts':(plan.charts[0].model_copy(update={'standard_pagination':None}),)})
    assert expand_standard_pagination(plan,ChartInputMaterialization()) is plan


def test_paginated_labels_are_explicit_and_do_not_reinterpret_auxiliary_text_as_series():
    plan,_,facts,documents,_=pagination_plan(4,2)
    table=documents['facts.json']['findings'][0]
    table['columns'].append('aux')
    for row in table['rows']:
        row.append('冻结辅助文本')
    binding=plan.charts[0].data_bindings[0].model_copy(update={'fields':tuple(table['columns'])})
    chart=plan.charts[0].model_copy(update={'data_bindings':(binding,)})
    plan=plan.model_copy(update={'charts':(chart,)})
    facts[0]['dataDescriptors'][0]['fields']=table['columns']
    inputs=materialize_chart_inputs(plan,facts,documents,output_root='inputs')
    expanded=expand_standard_pagination(plan,inputs)
    assert len(expanded.charts)==2
    assert all(chart.standard_label_field=='label' for chart in expanded.charts)
    final=materialize_chart_inputs(expanded,facts,documents,output_root='inputs')
    assert standard_visualization_preflight(expanded,final).source


def test_paginated_materialized_safe_name_collision_is_detected():
    from smart_reporting.reporting.workflow.runtime.chart_inputs import _safe_name

    plan,_,facts,documents,_=pagination_plan(4,2)
    base=plan.charts[0].model_copy(update={'chart_id':'中文'})
    collision=_safe_name('中文__page_2')
    other=base.model_copy(update={'chart_id':collision,'source_path':'other.png','standard_pagination':None})
    plan=VisualizationPlanDraft(charts=(base,other))
    inputs=materialize_chart_inputs(plan,facts,documents,output_root='inputs')
    result=expand_standard_pagination(plan,inputs)
    assert result.charts==plan.charts and '冲突' in result.warnings[-1]


def test_page_point_colors_are_filtered_without_changing_series_order():
    from smart_reporting.reporting.workflow.runtime.phase_models import StandardChartStyle

    plan,inputs,*_=pagination_plan(4,2)
    chart=plan.charts[0].model_copy(update={'standard_style':StandardChartStyle(points=[{'series':'budget','label':'类别003','color':'#ff0000'}])})
    plan=plan.model_copy(update={'charts':(chart,)})
    expanded=expand_standard_pagination(plan,inputs)
    assert expanded.charts[0].standard_style.points==()
    assert expanded.charts[1].standard_style.points==chart.standard_style.points
    assert all(page.standard_value_fields==('actual','budget') for page in expanded.charts)


def test_pagination_left_unit_is_normalized_into_actual_single_axis_display_conversion():
    from smart_reporting.reporting.workflow.runtime.phase_models import StandardChartAxes

    plan,inputs,*_=pagination_plan(4,2)
    chart=plan.charts[0].model_copy(update={'standard_display_unit':None,'standard_axes':StandardChartAxes(leftDisplayUnit='亿元')})
    plan=plan.model_copy(update={'charts':(chart,)})
    expanded=expand_standard_pagination(plan,inputs)
    assert len(expanded.charts)==2
    assert all(page.standard_display_unit=='亿元' for page in expanded.charts)
    assert expanded.charts[0].standard_domains.left.maximum<.01


def test_pagination_conflicting_unit_declarations_keep_pending_spec_and_warning():
    from smart_reporting.reporting.workflow.runtime.phase_models import StandardChartAxes

    plan,inputs,*_=pagination_plan(4,2)
    chart=plan.charts[0].model_copy(update={'standard_axes':StandardChartAxes(leftDisplayUnit='亿元')})
    plan=plan.model_copy(update={'charts':(chart,)})
    result=expand_standard_pagination(plan,inputs)
    assert result.charts==plan.charts and '单位声明冲突' in result.warnings[-1]


def test_pagination_all_zero_data_remains_real_zero_with_shared_nonempty_range():
    plan,inputs,*_=pagination_plan(2,1,rows=[['甲',0,0],['乙',0,0]])
    expanded=expand_standard_pagination(plan,inputs)
    assert len(expanded.charts)==2
    assert expanded.charts[0].standard_domains.left.minimum==-1
    assert expanded.charts[0].standard_domains.left.maximum==1


def test_paginated_batch_passes_formal_source_gate_with_every_output_authorized(tmp_path):
    from smart_reporting.reporting.code_agent.context import ReportingCodingTaskContext
    from smart_reporting.reporting.code_agent.toolkit import validate_script_source
    from smart_reporting.reporting.workflow.runtime.analysis import _visualization_output_paths

    plan,inputs,facts,documents,_=pagination_plan(25,10)
    expanded=expand_standard_pagination(plan,inputs)
    inputs=materialize_chart_inputs(expanded,facts,documents,output_root='inputs')
    source=standard_visualization_preflight(expanded,inputs).source
    assert source
    outputs=_visualization_output_paths(expanded)
    assert set(outputs)=={chart.source_path for chart in expanded.charts}
    context=ReportingCodingTaskContext(task_id='test',task_kind='visualization',code_mode_session_id='s',
        workspace_key='workspace',workspace_root=tmp_path,script_path='charts.py',authorized_read_paths=inputs.read_paths,
        authorized_write_paths=('charts.py',*outputs),declared_output_paths=outputs,max_source_bytes=128*1024)
    validate_script_source(context,source)

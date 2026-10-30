import hashlib
import json
import subprocess
import sys
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from smart_reporting.report_editor.chart_ai import ChartAIEditRequest, ChartEditPlan
from smart_reporting.report_editor.chart_edits import load_chart_edit_records
from smart_reporting.report_editor.standard_charts import (
    StandardChartEditParameters,
    inherit_standard,
    standard_edit_plan,
    standard_plot_summary,
)
from smart_reporting.reporting.tests.test_report_editor_chart_ai import (
    FakeRunner,
    _await_edit,
    _make_editor_with_chart,
    _service,
    _sha,
)
from smart_reporting.reporting.tests.test_standard_chart_presentation import render  # noqa: F401
from smart_reporting.reporting.workflow.runtime.phase_models import ChartDraft
from smart_reporting.reporting.workflow.runtime.standard_visualization import (
    standard_visualization_preflight,
)


def plot_file(document, path="input.json"):
    content=json.dumps(document,ensure_ascii=False).encode()
    return SimpleNamespace(path=path,content=content,size=len(content),sha256=hashlib.sha256(content).hexdigest())


def prepared(parameters, documents):
    options=StandardChartEditParameters.model_validate({key:value for key,value in parameters.items() if key.startswith('standard_')})
    return standard_edit_plan(chart_id="chart",output_path="chart.png",title="标准改图",alt_text="标准参数呈现",
        visual_form=parameters['visual_form'],standard=options,bindings=(),
        plot_files=[plot_file(doc,f'input-{n}.json') for n,doc in enumerate(documents)])


def test_standard_editor_parameter_schema_is_complete_and_never_accepts_identity():
    assert set(StandardChartEditParameters.model_fields)=={name for name in ChartDraft.model_fields if name.startswith('standard_')}
    for key in ('chartId','sourcePath','dataBindings','renderer','currentPeriod'):
        with pytest.raises(ValidationError):
            StandardChartEditParameters.model_validate({key:'injected'})


def test_standard_parameter_inheritance_preserves_axes_but_explicit_group_resets_mode():
    previous=StandardChartEditParameters.model_validate({'standardAxes':{'mode':'dual','rightFields':['ratio']},'standardBreak':None}).model_dump(mode='json',by_alias=True)
    colors=inherit_standard(previous,StandardChartEditParameters.model_validate({'standardStyle':{'palette':'viridis'}}))
    assert colors.standard_axes.mode=='dual' and colors.standard_axes.right_fields==('ratio',)
    reset=inherit_standard(colors.model_dump(mode='json',by_alias=True),StandardChartEditParameters.model_validate({'standardAxes':{'mode':'single'}}))
    assert reset.standard_axes.mode=='single' and not reset.standard_axes.right_fields


def candidates():
    from scripts.standard_visualization_box_summary_cases import summary_cases
    from scripts.standard_visualization_dual_stack_cases import dual_stack_cases
    from scripts.standard_visualization_geometry_cases import geometry_cases
    from scripts.standard_visualization_horizontal_break_cases import horizontal_break_cases
    from scripts.standard_visualization_statistics_cases import statistics_cases

    chosen=[next(c for c in dual_stack_cases() if c['id']=='dual-stack-signed-3-1'),
            next(c for c in horizontal_break_cases() if c['id']=='horizontal-breaks-positive-3-1')]
    for factory, forms in ((geometry_cases,{'scatter','bubble','heatmap','line'}),
                           (statistics_cases,{'waterfall','boxplot'}),(summary_cases,{'boxplot'})):
        found=set()
        for c in factory():
            form=c['parameters']['visual_form']
            if c.get('expected','render')=='render' and form in forms and form not in found:
                found.add(form)
                chosen.append(c)
    return chosen


@pytest.mark.parametrize('case',candidates(),ids=lambda case:case['id'])
def test_editor_standard_parameters_execute_production_templates_on_verified_input(render,case):  # noqa: F811
    from scripts.replay_standard_visualization_variants import plan_from_saved

    plan,inputs=prepared(case['parameters'],case['documents'])
    original=plan_from_saved({**case['parameters'],'chart_id':'chart','source_path':'chart.png','title':'标准改图'})
    assert standard_visualization_preflight(plan,inputs).source==standard_visualization_preflight(original,inputs).source
    figure=render(plan,inputs)
    assert figure.axes
    assert plan.charts[0].source_path=='chart.png'


def test_editor_standard_input_identity_changes_are_rejected():
    file=plot_file({'columns':['label','value'],'rows':[['甲',10]],'columnMeta':{'value':{'unit':'元'}}})
    file.sha256='0'*64
    plan,inputs=standard_edit_plan(chart_id='chart',output_path='chart.png',title='测试',alt_text='来源',visual_form='bar',standard=None,bindings=(),plot_files=[file])
    assert standard_visualization_preflight(plan,inputs).source is None


@pytest.mark.parametrize('baseline_year,baseline_months,expected', [
    (2024, ['01', '02'], True), (2023, ['01', '02'], False),
    (2024, ['01', '03'], False),
])
def test_editor_same_month_comparison_preserves_strict_period_validation(
    baseline_year, baseline_months, expected,
):
    documents = [{'columns': ['period', 'value'],
                  'rows': [[f'{year}-{month}-01', 10] for month in months],
                  'columnMeta': {'value': {'unit': '元'}}}
                 for year, months in [(2025, ['01', '02']), (baseline_year, baseline_months)]]
    parameters = {'visual_form': 'line', 'standard_form': 'line',
                  'standard_value_fields': ['当年', '基期'],
                  'standard_sources': [
                      {'sourceIndex': index, 'labelField': 'period', 'valueField': 'value',
                       'seriesName': name, 'labelMode': 'month_of_year', 'periodYear': year}
                      for index, name, year in [(0, '当年', 2025), (1, '基期', baseline_year)]]}
    plan, inputs = prepared(parameters, documents)
    result = standard_visualization_preflight(plan, inputs)
    assert (result.source is not None) is expected, result.diagnostic


def test_editor_pagination_has_every_page_but_one_original_cohort():
    doc={'columns':['label','value'],'rows':[[f'组{n}',n] for n in range(25)],'columnMeta':{'value':{'unit':'元'}}}
    parameters={'visual_form':'barh','standard_value_fields':['value'],'standard_pagination':{'pageSize':10}}
    plan,inputs=prepared(parameters,[doc])
    assert len(plan.charts)==3 and len(inputs.files)==1 and len(inputs.entries)==3
    assert [label for page in plan.charts for label in page.standard_labels]==[row[0] for row in doc['rows']]
    assert {entry['sha256'] for entry in inputs.entries}=={inputs.files[0].sha256}
    assert standard_visualization_preflight(plan,inputs).source


def test_editor_pagination_budget_failure_keeps_pending_spec_and_whole_cohort():
    doc={'columns':['label','value'],'rows':[[f'组{n}',n] for n in range(40)],'columnMeta':{'value':{'unit':'元'}}}
    plan,inputs=prepared({'visual_form':'barh','standard_value_fields':['value'],'standard_pagination':{'pageSize':10}},[doc])
    assert len(plan.charts)==1 and plan.charts[0].standard_pagination and plan.warnings
    assert standard_visualization_preflight(plan,inputs).diagnostic['code']=='standard_pagination_not_expanded'


def test_planner_summary_keeps_units_real_extents_and_explicitly_partial_labels():
    doc={'columns':['label','value'],'rows':[[f'组{n}',n] for n in range(65)],'columnMeta':{'value':{'unit':'%','isPercent':False}}}
    summary=standard_plot_summary([plot_file(doc)])[0]
    assert summary['columnMeta']['value']=={'unit':'%','isPercent':False}
    assert summary['numericExtent']['value']['maximum']==64
    assert not summary['textValues']['label']['complete']
    assert len(summary['textValues']['label']['values'])==60


class StandardRunner(FakeRunner):
    def __init__(self,png):
        super().__init__(png)
        self.standard_calls=[]

    async def run_standard_visualization(self,context,workspace,source,facts):
        from smart_reporting.reporting.workflow.checkpoint import ChartVisualInspectionReceipt

        self.standard_calls.append((context,source,facts))
        await workspace.awrite_bytes(context.workspace_key,context.script_path,source.encode(),overwrite=True)
        for output in context.declared_output_paths:
            (context.workspace_root/output).parent.mkdir(parents=True,exist_ok=True)
        subprocess.run([sys.executable,context.script_path],cwd=context.workspace_root,check=True,capture_output=True)
        receipts=[]
        for output in context.declared_output_paths:
            image,_=await workspace.afile_bytes(context.workspace_key,output)
            receipts.append(ChartVisualInspectionReceipt(sourcePath=output,sha256=_sha(image),reviewed=True,requiresRevision=False,modelId='fixture-only'))
        return SimpleNamespace(script_file={'path':context.script_path},execution_receipt=SimpleNamespace(output_files=()),
            visual_inspection_receipts=tuple(receipts),visual_repair_diagnostic=None)


@pytest.mark.anyio
@pytest.mark.parametrize('anyio_backend',['asyncio'])
async def test_real_edit_l2_uses_standard_source_and_keeps_rebound_lineage(tmp_path):
    fixture=await _make_editor_with_chart(tmp_path,template_ready=True)
    runner=StandardRunner(fixture.chart_bytes)
    requests=[]

    async def planner(request):
        requests.append(request)
        binding=next(item for item in request['registeredBindings'] if item['dataPath'].endswith('.periodValues'))
        return ChartEditPlan(level=['L2'],title='收入标准折线',altText='冻结期间收入',visualForm='line',drawInstruction='使用冻结期间值',
            dataBindings=[{k:binding[k] for k in ('analysisId','factPath','dataPath','fields','role')}],standard={'standardValueFields':['value']})

    service=_service(fixture,runner,planner=planner,timeout_seconds=60)
    started=await service.start_edit(fixture.context,SimpleNamespace(capabilities=None),'chart_001',ChartAIEditRequest(instruction='换成登记期间值折线'))
    result=await _await_edit(service,fixture.context,'chart_001',started['editId'])
    assert result['status']=='succeeded',result
    assert len(runner.standard_calls)==1 and not runner.calls
    assert len(result['pages'])==1 and result['pages'][0]['pageCount']==1
    assert result['pages'][0]['imageSrc']==result['imageSrc']
    records=await load_chart_edit_records(fixture.workspace,fixture.thread_id,fixture.context.markdown_path)
    assert records[0].data_origin=='rebound' and records[0].standard_parameters['standardValueFields']==['value']
    assert requests[0]['standardPlotSummary']


@pytest.mark.anyio
@pytest.mark.parametrize('anyio_backend',['asyncio'])
async def test_real_paginated_edit_reedit_from_page2_inherits_whole_cohort_and_standard_spec(tmp_path):
    fixture=await _make_editor_with_chart(tmp_path,template_ready=True)
    runner=StandardRunner(fixture.chart_bytes)
    requests=[]

    async def planner(request):
        requests.append(request)
        if len(requests)==1:
            binding=next(item for item in request['registeredBindings'] if item['dataPath'].endswith('.periodValues'))
            return ChartEditPlan(level=['L2'],title='收入分页',altText='冻结期间收入',visualForm='barh',drawInstruction='逐页完整显示',
                dataBindings=[{k:binding[k] for k in ('analysisId','factPath','dataPath','fields','role')}],
                standard={'standardValueFields':['value'],'standardPagination':{'pageSize':1},'standardStyle':{'labelRotation':0}})
        return ChartEditPlan(level=['L1'],drawInstruction='改用配色但保留其余标准参数',standard={'standardStyle':{'palette':'viridis','labelRotation':0}})

    service=_service(fixture,runner,planner=planner,timeout_seconds=60)
    session=SimpleNamespace(capabilities=None)
    first=await service.start_edit(fixture.context,session,'chart_001',ChartAIEditRequest(instruction='分页显示冻结期间'))
    first_result=await _await_edit(service,fixture.context,'chart_001',first['editId'])
    assert first_result['status']=='succeeded',first_result
    assert len(first_result['pages'])==3
    assert not any('图注中的数字' in warning for warning in first_result['warnings'])
    records=await load_chart_edit_records(fixture.workspace,fixture.thread_id,fixture.context.markdown_path)
    original=records[0]
    second_page=original.pages[1]
    second=await service.start_edit(fixture.context,session,'chart_001',ChartAIEditRequest(instruction='保持分页只改颜色',
        previousEditId=first['editId'],baseImagePath=second_page.image.path,expectedSha256=second_page.image.sha256,
        baseTitle=second_page.chart.title,baseAltText=second_page.chart.alt_text))
    second_result=await _await_edit(service,fixture.context,'chart_001',second['editId'])
    assert second_result['status']=='succeeded',second_result
    assert len(second_result['pages'])==3 and len(runner.standard_calls)==2 and not runner.calls
    records=await load_chart_edit_records(fixture.workspace,fixture.thread_id,fixture.context.markdown_path)
    result=records[-1]
    assert result.base_image_path==second_page.image.path
    assert len(result.plot_data_files)==len(original.plot_data_files)==1
    assert result.plot_data_files[0].path!=original.plot_data_files[0].path
    assert result.plot_data_files[0].sha256==original.plot_data_files[0].sha256
    assert result.plot_data_files[0].path.startswith(str(result.image.path.rsplit('/',1)[0])+'/')
    assert result.standard_parameters['standardPagination']['pageSize']==1
    assert result.standard_parameters['standardStyle']['palette']=='viridis'
    assert requests[-1]['baseTitle']=='收入分页'
    assert result.pages[0].chart.title=='收入分页（第1/3页）'
    assert not any('图注中的数字' in warning for warning in second_result['warnings'])
    assert all(page.chart.title.count('页）')==1 for page in result.pages)
    response=await service.edit_record(fixture.context,result.edit_id)
    assert response['pages'][1]['imagePath']==result.pages[1].image.path
    assert response['pages'][1]['title']==result.pages[1].chart.title
    assert response['pages'][1]['pageCount']==3
    assert all(len(json.loads(file.content)['rows'])==3 for file in [
        SimpleNamespace(content=(await fixture.workspace.afile_bytes(fixture.thread_id,ref.path))[0]) for ref in result.plot_data_files])


@pytest.mark.anyio
@pytest.mark.parametrize('anyio_backend',['asyncio'])
async def test_unsupported_standard_edit_uses_coding_and_reports_fallback(tmp_path):
    fixture=await _make_editor_with_chart(tmp_path)
    runner=StandardRunner(fixture.chart_bytes)

    async def planner(request):
        return ChartEditPlan(level=['L1'],visualForm='line',drawInstruction='调整缺少元数据的旧图',standard={'standardAxes':{'scale':'log'}})

    service=_service(fixture,runner,planner=planner)
    started=await service.start_edit(fixture.context,SimpleNamespace(capabilities=None),'chart_001',ChartAIEditRequest(instruction='调整对数轴'))
    result=await _await_edit(service,fixture.context,'chart_001',started['editId'])
    assert result['status']=='succeeded' and not runner.standard_calls and len(runner.calls)==1
    assert len(result['pages'])==1


@pytest.mark.anyio
@pytest.mark.parametrize('anyio_backend',['asyncio'])
async def test_standard_runtime_failure_falls_back_with_same_authorized_cohort(tmp_path):
    fixture=await _make_editor_with_chart(tmp_path,template_ready=True)

    class Fails(StandardRunner):
        async def run_standard_visualization(self,context,workspace,source,facts):
            self.standard_calls.append((context,source,facts))
            raise ValueError('intentional standard renderer failure')

    runner=Fails(fixture.chart_bytes)

    async def planner(request):
        binding=next(item for item in request['registeredBindings'] if item['dataPath'].endswith('.periodValues'))
        return ChartEditPlan(level=['L2'],visualForm='line',drawInstruction='冻结期间折线',
            dataBindings=[{k:binding[k] for k in ('analysisId','factPath','dataPath','fields','role')}],standard={'standardValueFields':['value']})

    service=_service(fixture,runner,planner=planner)
    started=await service.start_edit(fixture.context,SimpleNamespace(capabilities=None),'chart_001',ChartAIEditRequest(instruction='换冻结期间折线'))
    result=await _await_edit(service,fixture.context,'chart_001',started['editId'])
    assert result['status']=='succeeded' and len(runner.standard_calls)==len(runner.calls)==1
    assert runner.standard_calls[0][0].authorized_read_paths==runner.calls[0][0].authorized_read_paths
    assert runner.calls[0][1]['standardChartPreflight']['code']=='standard_editor_execution_failed'
    assert any('自由绘图' in warning for warning in result['warnings'])


@pytest.mark.anyio
@pytest.mark.parametrize('anyio_backend',['asyncio'])
async def test_unparameterized_freeform_instruction_is_not_silently_rendered_with_defaults(tmp_path):
    fixture=await _make_editor_with_chart(tmp_path,template_ready=True)
    runner=StandardRunner(fixture.chart_bytes)

    async def planner(request):
        binding=next(item for item in request['registeredBindings'] if item['dataPath'].endswith('.periodValues'))
        return ChartEditPlan(level=['L2'],visualForm='barh',drawInstruction='按金额降序并放大数值字号，未提供参数',
            dataBindings=[{k:binding[k] for k in ('analysisId','factPath','dataPath','fields','role')}])

    service=_service(fixture,runner,planner=planner)
    started=await service.start_edit(fixture.context,SimpleNamespace(capabilities=None),'chart_001',ChartAIEditRequest(instruction='降序并放大字号'))
    result=await _await_edit(service,fixture.context,'chart_001',started['editId'])
    assert result['status']=='succeeded' and not runner.standard_calls and len(runner.calls)==1
    assert '降序' in runner.calls[0][1]['chartEdit']['instruction']

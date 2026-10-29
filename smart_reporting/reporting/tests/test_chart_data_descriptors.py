"""Generation and editor rebinding share exact frozen group selectors."""

from copy import deepcopy
from types import SimpleNamespace

import pytest

from smart_reporting.report_editor.chart_ai import ChartAIEditRequest, ChartEditPlan
from smart_reporting.report_editor.chart_edits import load_chart_edit_records
from smart_reporting.reporting.delivery.artifacts_v1 import ArtifactFile
from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.tests.test_dimension_breakdowns import _bundle
from smart_reporting.reporting.tests.test_report_editor_chart_ai import (
    _await_edit,
    _make_editor_with_chart,
    _service,
    _sha,
)
from smart_reporting.reporting.tests.test_report_editor_standard_charts import StandardRunner
from smart_reporting.reporting.trace.index_builder import encode_trace_index
from smart_reporting.reporting.workflow.runtime.chart_data_descriptors import (
    deterministic_chart_descriptors,
)


def descriptors(document, **kwargs):
    return {item['dataPath']: item for item in deterministic_chart_descriptors(document, **kwargs)}


@pytest.mark.parametrize('population', [None, [], [{'group': '甲'}], [{'group': '甲', 'value': True}], [{'group': '甲', 'value': []}]])
def test_no_complete_population_is_invented_from_ranked_or_invalid_rows(population):
    document = {'metrics': [{'topGroups': [{'group': '甲', 'value': 1}], 'groupPopulation': population}]}
    assert 'metrics[0].groupPopulation' not in descriptors(document)
    assert descriptors(document)['metrics[0].topGroups']['dataScope']['canRepresentFullDistribution'] is False


def test_shared_catalog_keeps_full_population_distinct_from_top_bottom_and_scalar_fields():
    document = {'metrics': [{'unit': '万元', 'total': 6, 'groupPopulation': [
        {'group': '甲', 'value': 1}, {'group': '乙', 'value': 2}, {'group': '丙', 'value': 3},
    ], 'topGroups': [{'group': '丙', 'value': 3}], 'bottomGroups': [{'group': '甲', 'value': 1}]}]}
    before = deepcopy(document)
    catalog = descriptors(document)
    assert catalog['metrics[0].groupPopulation']['fields'] == ['group', 'value']
    assert '完整分组' in catalog['metrics[0].groupPopulation']['dataScope']
    assert catalog['metrics[0]']['fields'] == ['total', 'unit']
    assert document == before


def test_generation_and_editor_never_mix_parent_metrics_or_breakdown_dimensions():
    document = _bundle().model_dump(mode='json', by_alias=True)
    generation = descriptors(document)
    editing = descriptors(document, include_all_breakdown_details=True)
    assert 'breakdowns' not in generation and 'breakdowns' not in editing
    assert all(editing[path] == item for path, item in generation.items())
    assert all(f'breakdowns[{index}]' in editing for index in range(len(document['breakdowns'])))
    one_dimension = deepcopy(document)
    field = one_dimension['breakdowns'][0]['breakdownField']
    one_dimension['breakdowns'] = [row for row in one_dimension['breakdowns'] if row['breakdownField'] == field]
    assert 'breakdowns' in descriptors(one_dimension, include_all_breakdown_details=True)


def test_template_switch_clears_only_explicitly_reset_pagination_and_keeps_style():
    from smart_reporting.report_editor.standard_charts import (
        StandardChartEditParameters,
        inherit_standard,
        standard_edit_plan,
    )
    from smart_reporting.reporting.tests.test_report_editor_standard_charts import plot_file
    from smart_reporting.reporting.workflow.runtime.standard_visualization import (
        standard_visualization_preflight,
    )

    previous = {'standardValueFields': ['value'], 'standardPagination': {'pageSize': 1},
                'standardStyle': {'palette': 'viridis'}}
    document = {'columns': ['label', 'value'], 'rows': [['甲', 1], ['乙', 2]],
                'columnMeta': {'value': {'unit': '元'}}}

    def preflight(options):
        plan, inputs = standard_edit_plan(chart_id='chart', output_path='chart.png', title='冻结趋势',
            alt_text='全部冻结数据', visual_form='line', standard=options, bindings=(), plot_files=[plot_file(document)])
        return standard_visualization_preflight(plan, inputs)

    inherited = inherit_standard(previous, StandardChartEditParameters.model_validate({}))
    assert preflight(inherited).diagnostic['code'] == 'standard_pagination_not_expanded'
    reset = inherit_standard(previous, StandardChartEditParameters.model_validate({'standardPagination': None}))
    assert reset.standard_pagination is None and reset.standard_style.palette == 'viridis'
    assert reset.standard_value_fields == ('value',)
    assert preflight(reset).source


@pytest.mark.anyio
@pytest.mark.parametrize('anyio_backend', ['asyncio'])
@pytest.mark.parametrize('selector', ['topGroups', 'bottomGroups', 'groupPopulation', 'breakdown_period'])
async def test_editor_rebinds_ranked_or_complete_groups_and_executes_standard_source(tmp_path, selector):
    import json

    fixture = await _make_editor_with_chart(tmp_path, template_ready=True)
    editor, workspace, thread = fixture.editor, fixture.workspace, fixture.thread_id
    index = await editor.trace.load_index(fixture.context)
    manifest = await editor.trace.load_manifest(fixture.context)
    entry = next(item for item in index.fact_files if item.analysis_id == 'analysis_001' and item.content_kind == 'deterministic_bundle')
    fact = next(item for item in index.files if item.resource_id == entry.file_resource_id)
    document = json.loads(await workspace.aread_text(thread, fact.path))
    population = [{'group': '甲', 'value': 1200.0}, {'group': '乙', 'value': 1500.0}, {'group': '丙', 'value': 1800.0}]
    document['metrics'][0].update(groupPopulation=population, topGroups=[population[-1]], bottomGroups=[population[0]])
    document['breakdowns'] = [{**deepcopy(document['metrics'][0]),
        'parentFactId': document['metrics'][0]['factId'], 'breakdownField': 'department',
        'breakdownLabel': '科室', 'breakdownValue': '甲',
        'scope': {**document['metrics'][0].get('scope', {}), 'department': '甲'}}]
    selected_path = 'breakdowns[0].periodValues' if selector == 'breakdown_period' else f'metrics[0].{selector}'
    content = json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()
    await workspace.awrite_bytes(thread, fact.path, content, overwrite=True)
    fact = fact.model_copy(update={'size': len(content), 'sha256': _sha(content)})
    index = index.model_copy(update={'files': tuple(fact if item.resource_id == fact.resource_id else item for item in index.files)})
    encoded = encode_trace_index(index)
    await workspace.awrite_bytes(thread, manifest.trace_index.path, encoded, overwrite=True)
    trace_identity = manifest.trace_index.model_copy(update={'size': len(encoded), 'sha256': _sha(encoded)})
    manifest = manifest.model_copy(update={'trace_index': trace_identity})
    encoded = manifest.model_dump_json(by_alias=True).encode()
    await workspace.awrite_bytes(thread, fixture.context.artifact_manifest.path, encoded, overwrite=True)
    identity = ArtifactFile(path=fixture.context.artifact_manifest.path, mediaType='application/json', size=len(encoded), sha256=_sha(encoded))
    context = fixture.context.model_copy(update={'artifact_manifest': identity})
    editor.state_repository.durable.payload['reportEditorContexts']['1'] = context.model_dump(mode='json', by_alias=True)
    requests = []

    async def planner(request):
        requests.append(request)
        selected = next(item for item in request['registeredBindings'] if item['dataPath'] == selected_path)
        return ChartEditPlan(level=['L2'], visualForm='barh', drawInstruction='使用指定冻结分组逐项显示',
            dataBindings=[{key: selected[key] for key in ('analysisId', 'factPath', 'dataPath', 'fields', 'role')}],
            standard={'standardValueFields': ['value']})

    runner = StandardRunner(fixture.chart_bytes)
    service = _service(fixture, runner, planner=planner, timeout_seconds=60)
    try:
        started = await service.start_edit(context, SimpleNamespace(capabilities=None), 'chart_001', ChartAIEditRequest(instruction='使用完整分组' if selector == 'groupPopulation' else '只显示已冻结的排序子集'))
        result = await _await_edit(service, context, 'chart_001', started['editId'])
        assert result['status'] == 'succeeded', result
        assert len(runner.standard_calls) == 1 and not runner.calls
        record = (await load_chart_edit_records(workspace, thread, context.markdown_path))[-1]
        payload = json.loads((await workspace.afile_bytes(thread, record.plot_data_files[0].path))[0])
        expected = document['metrics'][0]['periodValues'] if selector == 'breakdown_period' else population if selector == 'groupPopulation' else document['metrics'][0][selector]
        label = 'period' if selector == 'breakdown_period' else 'group'
        assert payload['rows'] == [[row[label], row['value']] for row in expected]
        assert payload['columnMeta']['value']['unit'] == document['metrics'][0]['unit']
        assert record.data_origin == 'rebound'
        selected = next(item for item in requests[0]['registeredBindings'] if item['dataPath'] == selected_path)
        if selector == 'groupPopulation':
            assert '完整分组' in selected['dataScope'] and len(payload['rows']) == 3
        elif selector != 'breakdown_period':
            assert selected['dataScope']['canRepresentFullDistribution'] is False
            assert payload['dataScope']['coverage'] == 'ranked_subset'
        else:
            # Historical L2 breakdown inputs had no parent-unit columnMeta.
            # Only that exact old format may pass; rehashed altered values/units
            # still fail deterministic provenance reconstruction.
            legacy = deepcopy(payload)
            legacy.pop('columnMeta')
            for fault in ('none', 'rows', 'unit'):
                candidate = deepcopy(legacy)
                if fault == 'rows':
                    candidate['rows'][0][1] += 1
                elif fault == 'unit':
                    candidate['columnMeta'] = {'value': {'unit': '伪造单位'}}
                data = (json.dumps(candidate, ensure_ascii=False, separators=(',', ':')) + '\n').encode()
                ref = record.plot_data_files[0].model_copy(update={'size': len(data), 'sha256': _sha(data)})
                await workspace.awrite_bytes(thread, ref.path, data, overwrite=True)
                check = editor._verify_chart_edit_plot_data(thread, record=record.model_copy(update={'plot_data_files': (ref,)}),
                    trace=index.chart_traces[0], index=index, data_origin='rebound')
                if fault == 'none':
                    await check
                else:
                    with pytest.raises(ReportingError, match='无法从冻结事实重建'):
                        await check
    finally:
        await service.aclose()

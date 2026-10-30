"""标准静态图证明必须来自真实执行身份，不能用图片 hash 冒充数据核验。"""

import hashlib
from types import SimpleNamespace

import pytest

from smart_reporting.reporting.code_agent.context import ExecutionReceipt
from smart_reporting.reporting.tests.test_reporting_interactive_code_agent import (
    binding,  # noqa: F401
    workspace,  # noqa: F401
)
from smart_reporting.reporting.tests.test_standard_visualization import materialization
from smart_reporting.reporting.workflow.checkpoint import FileIdentity
from smart_reporting.reporting.workflow.runtime.phase_models import VisualizationPlanDraft
from smart_reporting.reporting.workflow.runtime.standard_chart_proof import (
    create_standard_render_proofs,
    recompile_standard_render_proof,
)
from smart_reporting.reporting.workflow.runtime.standard_visualization import (
    standard_visualization_script,
)


def proof_case():
    plan = VisualizationPlanDraft.model_validate({"charts": [{
        "chartId": "chart_001", "sourcePath": "chart.png", "title": "收入趋势", "altText": "逐月收入",
        "citationIds": ["C1"], "metricCodes": ["income"], "currentPeriod": "2025-01至2025-02",
        "sourceDatasetId": "dataset-aaaaaa", "aggregationGrain": "month", "visualForm": "柱图",
        "standardForm": "bar",
        "dataBindings": [{"analysisId": "analysis_001", "factPath": "facts.json",
                          "dataPath": "metrics[0].periodValues", "fields": ["period", "value"], "role": "trend"}],
    }]})
    inputs = materialization({"schema": "chart-input/v1", "chartId": "chart_001",
                             "columns": ["period", "value"], "rows": [["2025-01", 10], ["2025-02", 20]],
                             "columnMeta": {"value": {"unit": "元"}}})
    source = standard_visualization_script(plan, inputs).encode()
    script = FileIdentity(path="chart.py", size=len(source), sha256=hashlib.sha256(source).hexdigest())
    image = FileIdentity(path="chart.png", size=5, sha256=hashlib.sha256(b"image").hexdigest())
    result = SimpleNamespace(script_file=script, execution_receipt=ExecutionReceipt(
        runId="real-execution", sourceFile=script, outputFiles=(image,)))
    return plan, inputs, result, source


def test_standard_proof_recompiles_exact_executed_source_and_binds_output():
    plan, inputs, result, source = proof_case()
    records = create_standard_render_proofs(result, plan, inputs)
    assert len(records) == 1
    proof = records[0]["proof"]
    assert proof.image_sha256 == result.execution_receipt.output_files[0].sha256
    assert proof.run_id == "real-execution"
    assert recompile_standard_render_proof(proof, {file.sha256: file.content for file in inputs.files}) == source


def test_proof_uses_the_actual_host_formatted_source_identity():
    from smart_reporting.reporting.code_agent.formatting import format_python_source_sync

    plan, inputs, result, source = proof_case()
    formatted = format_python_source_sync(source.decode()).encode()
    assert formatted != source
    result.script_file = result.script_file.model_copy(update={
        "size": len(formatted), "sha256": hashlib.sha256(formatted).hexdigest(),
    })
    result.execution_receipt = result.execution_receipt.model_copy(update={"source_file": result.script_file})
    proof = create_standard_render_proofs(result, plan, inputs)[0]["proof"]
    assert recompile_standard_render_proof(proof, {file.sha256: file.content for file in inputs.files}) == formatted


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_real_write_and_matplotlib_execution_issue_a_current_proof(binding, monkeypatch):  # noqa: F811
    from dataclasses import replace
    from unittest.mock import AsyncMock

    from smart_reporting.reporting.code_agent.context import ReportingCodingTaskBinding
    from smart_reporting.reporting.code_agent.lsp_process import ReportingLspProcessManager
    from smart_reporting.reporting.code_agent.toolkit import ReportingCodeModeToolkit

    plan, inputs, result, source = proof_case()
    context = replace(binding.context, task_kind="visualization", script_path="chart.py",
                      authorized_read_paths=inputs.read_paths, authorized_write_paths=("chart.py", "chart.png"),
                      declared_output_paths=("chart.png",), max_source_bytes=256000)
    current = ReportingCodingTaskBinding(context, binding.workspace)
    for file in inputs.files:
        await binding.workspace.awrite_bytes(context.task_id, file.path, file.content)
    toolkit = ReportingCodeModeToolkit(current, AsyncMock(), ReportingLspProcessManager())
    written = await toolkit.write_script(source.decode())
    assert written["ok"] is True, written
    saved = await toolkit.read_script()
    monkeypatch.chdir(context.workspace_root)
    exec(saved["source"], {})
    image = (context.workspace_root / "chart.png").read_bytes()
    assert image.startswith(b"\x89PNG")
    result.script_file = FileIdentity(path=context.script_path, size=saved["size"], sha256=saved["sha256"])
    result.execution_receipt = ExecutionReceipt(runId="executed-template", sourceFile=result.script_file,
        outputFiles=(FileIdentity(path="chart.png", size=len(image), sha256=hashlib.sha256(image).hexdigest()),))
    proof = create_standard_render_proofs(result, plan, inputs)[0]["proof"]
    assert recompile_standard_render_proof(proof, {file.sha256: file.content for file in inputs.files}) == saved["source"].encode()


@pytest.mark.anyio
@pytest.mark.parametrize('anyio_backend', ['asyncio'])
@pytest.mark.parametrize('final_image_changed', [False, True])
async def test_mixed_routes_retain_only_standard_proofs_with_identical_final_images(
    binding, monkeypatch, final_image_changed,  # noqa: F811
):
    from dataclasses import replace
    from pathlib import Path

    from smart_reporting.reporting.workflow.runtime.code_generation import CodeGenerationResult
    from smart_reporting.reporting.workflow.runtime.standard_chart_routing import (
        run_standard_chart_routes,
    )

    plan, inputs, _, _ = proof_case()
    custom = plan.charts[0].model_copy(update={
        'chart_id': 'chart_002', 'source_path': 'custom.png', 'standard_form': 'custom'})
    plan = plan.model_copy(update={'charts': (*plan.charts, custom)})
    entries = tuple({**inputs.entries[0], 'chartId': chart.chart_id, 'size': len(inputs.files[0].content)}
                    for chart in plan.charts)
    inputs = replace(inputs, entries=entries)
    context = replace(binding.context, task_kind='visualization', script_path='mixed.py',
        authorized_read_paths=inputs.read_paths, authorized_write_paths=('mixed.py', 'chart.png', 'custom.png'),
        declared_output_paths=('chart.png', 'custom.png'))
    for file in inputs.files:
        await binding.workspace.awrite_bytes(context.task_id, file.path, file.content)
    monkeypatch.chdir(context.workspace_root)

    def identity(path):
        raw = Path(path).read_bytes()
        return FileIdentity(path=path, size=len(raw), sha256=hashlib.sha256(raw).hexdigest())

    async def execute(ctx, host_workspace, source, facts, **kwargs):
        await host_workspace.awrite_bytes(ctx.task_id, ctx.script_path, source.encode())
        exec(source, {})
        if final_image_changed and ctx.script_path == 'mixed.py':
            await host_workspace.awrite_bytes(ctx.task_id, 'chart.png', Path('chart.png').read_bytes() + b'changed',
                                              overwrite=True)
        script = identity(ctx.script_path)
        return CodeGenerationResult(script_file=script, execution_receipt=ExecutionReceipt(
            runId=ctx.script_path, sourceFile=script,
            outputFiles=tuple(identity(path) for path in ctx.declared_output_paths)))

    async def coding(ctx, host_workspace, facts, **kwargs):
        return await execute(ctx, host_workspace,
            'import matplotlib.pyplot as plt\nfig, ax = plt.subplots()\nax.plot([1, 2], [3, 4])\n'
            'fig.savefig("custom.png")\nplt.close(fig)\n', facts)

    result = await run_standard_chart_routes(SimpleNamespace(run_standard_visualization=execute, run=coding),
        context, binding.workspace, plan, inputs, {}, SimpleNamespace())
    assert [route['route'] for route in result.standard_chart_routes] == ['standard', 'coding']
    assert [record['chartId'] for record in result.standard_render_proofs] == (
        [] if final_image_changed else ['chart_001'])
    for record in result.standard_render_proofs:
        assert record['scriptFile'].path == 'mixed-chart-001.py'
        assert recompile_standard_render_proof(record['proof'], {
            file.sha256: file.content for file in inputs.files}) == Path(record['scriptFile'].path).read_bytes()


@pytest.mark.parametrize("fault", ["source", "receipt_source", "missing_image", "missing_receipt"])
def test_standard_proof_rejects_nonmatching_execution(fault):
    plan, inputs, result, _ = proof_case()
    if fault == "source":
        result.script_file = result.script_file.model_copy(update={"sha256": "0" * 64})
    elif fault == "receipt_source":
        result.execution_receipt = result.execution_receipt.model_copy(update={
            "source_file": result.script_file.model_copy(update={"sha256": "0" * 64}),
        })
    elif fault == "missing_image":
        result.execution_receipt = result.execution_receipt.model_copy(update={"output_files": ()})
    else:
        result.execution_receipt = None
    assert create_standard_render_proofs(result, plan, inputs) == ()


@pytest.mark.parametrize("fault", ["input", "plan"])
def test_proof_recompile_rejects_modified_inputs_or_plan(fault):
    plan, inputs, result, source = proof_case()
    proof = create_standard_render_proofs(result, plan, inputs)[0]["proof"]
    data = {file.sha256: file.content for file in inputs.files}
    if fault == "input":
        data[inputs.files[0].sha256] += b" "
    else:
        changed = {**proof.plan, "charts": [{**proof.plan["charts"][0], "standardForm": "line"}]}
        proof = proof.model_copy(update={"plan": changed})
    assert recompile_standard_render_proof(proof, data) is None


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
@pytest.mark.parametrize("fault", [None, "image", "script", "plan", "input"])
async def test_static_quality_requires_proof_and_current_frozen_source_projection(tmp_path, monkeypatch, fault):
    import json
    from unittest.mock import AsyncMock

    from smart_reporting.reporting.tests.test_chart_quality_bundle import chart_case
    from smart_reporting.reporting.trace.chart_quality import evaluate_chart_quality
    from smart_reporting.reporting.trace.contracts_v1 import TraceFileRefV1, derive_resource_id
    from smart_reporting.reporting.workflow.runtime.chart_inputs import (
        ChartInputFile,
        ChartInputMaterialization,
    )

    editor, chart_workspace, context, index, markdown, sources, _ = await chart_case(tmp_path)
    chart = index.chart_traces[0]
    plan, _, result, _ = proof_case()
    image = next(file for file in index.files if file.resource_id == chart.image_file_resource_id)
    plot_id = chart.plot_data_file_resource_ids[0]
    document = json.loads(sources[plot_id])
    draft = plan.charts[0].model_copy(update={
        "chart_id": chart.chart_id, "source_path": image.path,
        "standard_label_field": "field", "standard_value_fields": ("total",),
    })
    plan = plan.model_copy(update={"charts": (draft,)})
    file = ChartInputFile("input.json", sources[plot_id])
    inputs = ChartInputMaterialization(files=(file,), entries=({
        "chartId": chart.chart_id, "path": file.path, "sha256": file.sha256,
    },))
    source = standard_visualization_script(plan, inputs).encode()
    result.script_file = FileIdentity(path="charts.py", size=len(source), sha256=hashlib.sha256(source).hexdigest())
    result.execution_receipt = ExecutionReceipt(runId="static-run", sourceFile=result.script_file,
        outputFiles=(FileIdentity(path=image.path, size=image.size, sha256=image.sha256),))
    record = create_standard_render_proofs(result, plan, inputs)[0]
    proof = record["proof"]
    script_id = derive_resource_id("charts.py")
    sources[script_id] = source
    script_ref = TraceFileRefV1(resourceId=script_id, path="charts.py", mediaType="text/x-python",
                              size=len(source), sha256=result.script_file.sha256)
    if fault == "image":
        proof = proof.model_copy(update={"image_sha256": "0" * 64})
    elif fault == "script":
        sources[script_id] += b"\n"
    elif fault == "plan":
        changed = {**proof.plan, "charts": [{**proof.plan["charts"][0], "standardForm": "line"}]}
        proof = proof.model_copy(update={"plan": changed})
    elif fault == "input":
        document["rows"][0][1] += 999
        sources[plot_id] = json.dumps(document).encode()
    chart = chart.model_copy(update={"script_file_resource_id": script_id, "standard_render_proof": proof})
    index = index.model_copy(update={"files": (*index.files, script_ref), "chart_traces": (chart,)})
    check = evaluate_chart_quality(index, markdown, sources, {})[chart.chart_id]
    assert check.status == ("verified" if fault is None else "unknown")
    if fault is None:
        assert check.reason == "standard_render_matches_frozen_inputs"
        monkeypatch.setattr(editor.trace, 'require_index', AsyncMock(return_value=index))
        monkeypatch.setattr(editor.trace, 'load_manifest', AsyncMock(return_value=SimpleNamespace(charts=[])))
        for file in index.files:
            await chart_workspace.awrite_bytes(context.scope['threadId'], file.path, sources[file.resource_id], overwrite=True)
        current = await editor.trace.validate(context, markdown, hashlib.sha256(markdown.encode()).hexdigest())
        assert current['charts'][0]['dataCheck']['status'] == 'verified'
        await chart_workspace.awrite_bytes(context.scope['threadId'], script_ref.path, source + b'\n', overwrite=True)
        changed = await editor.trace.validate(context, markdown, hashlib.sha256(markdown.encode()).hexdigest())
        assert changed['charts'][0]['dataCheck']['status'] == 'unknown'
        assert changed['quality']['inputSha256'] != current['quality']['inputSha256']


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
@pytest.mark.parametrize("fault", [None, "metric", "binding", "scope", "unit"])
async def test_static_semantics_uses_exact_source_identity_and_not_equal_values(tmp_path, fault):
    import json

    from smart_reporting.reporting.tests.test_semantic_alignment import bound_chart
    from smart_reporting.reporting.trace.chart_quality import ChartQualityCheck
    from smart_reporting.reporting.trace.semantic_alignment import evaluate_semantic_alignment

    index, _, sources, _ = await bound_chart(tmp_path, monthly=True)
    chart = index.chart_traces[0]
    origin = index.fact_files[0]
    fact_document = json.loads(sources[origin.file_resource_id])
    fact_document["metrics"][0]["scope"] = {"company": "甲医院"}
    sources[origin.file_resource_id] = json.dumps(fact_document).encode()
    metric = fact_document["metrics"][0]
    plot_id = chart.plot_data_file_resource_ids[0]
    plot = json.loads(sources[plot_id])
    plot["columnMeta"] = {"value": {"unit": "元"}}
    plot["source"]["path"] = next(file.path for file in index.files if file.resource_id == origin.file_resource_id)
    if fault == "unit":
        plot["columnMeta"] = {}
    sources[plot_id] = json.dumps(plot).encode()
    plan, inputs, result, _ = proof_case()
    draft = plan.charts[0].model_copy(update={
        "chart_id": chart.chart_id, "metric_codes": tuple(metric["metricCodes"]),
        "data_bindings": (plan.charts[0].data_bindings[0].model_copy(update={
            "analysis_id": origin.analysis_id, "data_path": plot["source"]["dataPath"],
            "fact_path": plot["source"]["path"],
            "fields": tuple(plot["columns"]),
        }),),
    })
    if fault == "metric":
        draft = draft.model_copy(update={"metric_codes": ("unrelated_metric",)})
    elif fault == "binding":
        draft = draft.model_copy(update={"data_bindings": (draft.data_bindings[0].model_copy(update={
            "data_path": "metrics[1].periodValues",
        }),)})
    elif fault == "scope":
        document = json.loads(sources[origin.file_resource_id])
        document["metrics"][0]["scope"] = {}
        sources[origin.file_resource_id] = json.dumps(document).encode()
    proof = create_standard_render_proofs(result, plan, inputs)[0]["proof"].model_copy(update={
        "plan": plan.model_copy(update={"charts": (draft,)}).model_dump(mode="json", by_alias=True),
    })
    chart = chart.model_copy(update={"standard_render_proof": proof, "fact_refs": ()})
    index = index.model_copy(update={"chart_traces": (chart,), "files": tuple(
        file.model_copy(update={"size": len(sources[file.resource_id]),
                                "sha256": hashlib.sha256(sources[file.resource_id]).hexdigest()})
        for file in index.files
    )})
    # source hash 随已登记的fixture更新；指标身份仍由精确选择器决定。
    plot["source"]["sha256"] = next(file.sha256 for file in index.files if file.resource_id == origin.file_resource_id)
    sources[plot_id] = json.dumps(plot).encode()
    index = index.model_copy(update={"files": tuple(
        file.model_copy(update={"size": len(sources[file.resource_id]),
                                "sha256": hashlib.sha256(sources[file.resource_id]).hexdigest()})
        for file in index.files
    )})
    proof = proof.model_copy(update={"inputs": ({
        "chartId": chart.chart_id, "path": "input.json", "sha256": hashlib.sha256(sources[plot_id]).hexdigest(),
    },)})
    chart = chart.model_copy(update={"standard_render_proof": proof})
    index = index.model_copy(update={"chart_traces": (chart,)})
    check = evaluate_semantic_alignment(index, sources, chart_checks={chart.chart_id: ChartQualityCheck(
        status="verified", reason="standard_render_matches_frozen_inputs",
    )})[chart.chart_id]
    assert check.status == ("verified" if fault is None else "unknown"), check.reasons
    if fault is None:
        assert metric["factId"] in check.fact_ids


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
@pytest.mark.parametrize("fault", [None, "free_coding", "wrong_parent", "input_identity", "parent_period", "parent_unit", "denominator_correct", "denominator_wrong_metric", "denominator_conversion", "denominator_wrong_scale", "ratio_correct", "ratio_wrong_parents", "group_view", "pivot_view", "temporal_view"])
async def test_standard_supplemental_chart_preserves_exact_registered_computation_ownership(tmp_path, fault):
    import json

    from smart_reporting.reporting.tests.test_chart_quality_bundle import chart_case
    from smart_reporting.reporting.trace.computation_service import (
        build_standard_supplemental_computation_record,
    )
    from smart_reporting.reporting.trace.contracts_v1 import (
        FactFileEntryV1,
        TraceFileRefV1,
        derive_resource_id,
    )
    from smart_reporting.reporting.trace.quality_bundle import evaluate_quality_bundle
    from smart_reporting.reporting.workflow.runtime.chart_inputs import (
        ChartInputFile,
        ChartInputMaterialization,
    )
    from smart_reporting.reporting.workflow.runtime.standard_supplemental import (
        StandardSupplementalRequest,
        run_standard_supplemental,
    )

    _, _, _, index, markdown, sources, _ = await chart_case(tmp_path)
    chart = index.chart_traces[0]
    snapshot = index.datasets[0]
    csv = 'month,department,company,income,budget\n2025-09,A,甲医院,1000,2000\n2025-10,B,甲医院,2600,2000\n'.encode()
    if fault in {'pivot_view', 'temporal_view'}:
        csv = csv.replace(b'2025-10,B,', b'2025-10,A,')
    sources[snapshot.file_resource_id] = csv
    origin = index.fact_files[0]
    source_document = json.loads(sources[origin.file_resource_id])
    source_document['metrics'][0].update(
        field='income', scope={'company': '甲医院'}, unit='元', metricCodes=['income_total'],
        datasetId=snapshot.dataset_id, datasetSha256=hashlib.sha256(csv).hexdigest(),
        periodField='month', periodGranularity='month',
        periodValues=[{'period': '2025-09', 'value': 1000}, {'period': '2025-10', 'value': 2600}],
    )
    if fault == 'wrong_parent':
        source_document['metrics'][0]['field'] = 'cost'
    elif fault == 'parent_period':
        source_document['metrics'][0]['periodValues'] = [{'period': '2024-09', 'value': 3600}]
    elif fault == 'parent_unit':
        source_document['metrics'][0]['unit'] = '万元'
    ratio_case = fault in {'denominator_correct', 'denominator_wrong_metric', 'denominator_conversion', 'denominator_wrong_scale', 'ratio_correct', 'ratio_wrong_parents'}
    converting = fault in {'denominator_conversion', 'denominator_wrong_scale'}
    if ratio_case:
        source_document['metrics'].append({**source_document['metrics'][0], 'field': 'budget',
            'factId': 'fact-' + 'd' * 16, 'metricCodes': ['budget_total'],
            'unit': '万元' if converting else '元',
            'periodValues': [{'period': '2025-09', 'value': 2000}, {'period': '2025-10', 'value': 2000}]})
        source_document['derivedMetrics'] = [{'factId': 'fact-' + 'e' * 16, 'code': 'execution_ratio',
            'scope': {'company': '甲医院'}, 'unit': '%', 'denominatorScale': 10000 if converting else 1,
            'inputFactIds': [source_document['metrics'][0]['factId'], 'fact-' + 'd' * 16]}]
        if fault == 'ratio_wrong_parents':
            source_document['derivedMetrics'][0]['inputFactIds'] = ['fact-' + 'f' * 16]
    sources[origin.file_resource_id] = json.dumps(source_document).encode()
    request = StandardSupplementalRequest(operation='group_summary', datasetId=snapshot.dataset_id,
        outputName='科室收入', measureField='income', measureUnit='元', dimensionField='department',
        periodField='month', periodGranularity='month', currentPeriods=['2025-09', '2025-10'],
        parentTotal=3600, scope={'company': '甲医院'})
    if ratio_case:
        request = request.model_copy(update={'operation': 'group_ratio', 'denominator_field': 'budget',
            'denominator_parent_total': 4000, 'denominator_scale': 10000 if fault == 'denominator_conversion' else 1,
            'ratio_fact_id': 'fact-' + 'e' * 16})
    if fault in {'pivot_view', 'temporal_view'}:
        request = request.model_copy(update={'operation': 'group_period_series', 'parent_period_totals': (1000, 2600)})
    supplemental = run_standard_supplemental(analysis_id='analysis_002', dataset_ids=(snapshot.dataset_id,),
        authorized_fields=('month', 'department', 'company', 'income', 'budget'), csv_content=csv, request=request)
    assert 'analysisId' not in supplemental  # 身份由服务端索引绑定，不要求模型文件自报。
    raw = json.dumps(supplemental).encode()
    supplemental_path = 'supplemental.json'
    supplemental_id = derive_resource_id(supplemental_path)
    sources[supplemental_id] = raw
    supplemental_file = TraceFileRefV1(resourceId=supplemental_id, path=supplemental_path,
        mediaType='application/json', size=len(raw), sha256=hashlib.sha256(raw).hexdigest())
    csv_identity = next(file for file in index.files if file.resource_id == snapshot.file_resource_id)
    record = build_standard_supplemental_computation_record(analysis_id='analysis_002', dataset_ids=(snapshot.dataset_id,),
        input_files=({'path': csv_identity.path, 'size': len(csv), 'sha256': hashlib.sha256(csv).hexdigest()},),
        evidence_file={'path': supplemental_path, 'sha256': supplemental_file.sha256},
        method='supplemental_standard_' + request.operation, method_version='standard-supplemental-v1',
        parameters=request.model_dump(mode='json', by_alias=True), execution_id='standard-executed', finding_count=2)
    if fault == 'free_coding':
        record = record.model_copy(update={'method': 'python_code'})
    elif fault == 'input_identity':
        record = record.model_copy(update={'parameters': {**record.parameters, 'inputFiles': []}})
    table = supplemental['findings'][0]
    plot = {'schema': 'chart-input/v1', 'chartId': chart.chart_id, 'source': {
        'analysisId': 'analysis_002', 'path': supplemental_path, 'sha256': supplemental_file.sha256,
        'dataPath': 'findings[0].rows'}, 'columns': table['columns'], 'rows': table['rows'],
        'columnMeta': table['columnMeta'], 'rowCount': len(table['rows'])}
    plot_id = chart.plot_data_file_resource_ids[0]
    sources[plot_id] = json.dumps(plot).encode()
    plan, _, result, _ = proof_case()
    image = next(file for file in index.files if file.resource_id == chart.image_file_resource_id)
    draft = plan.charts[0].model_copy(update={
        'chart_id': chart.chart_id, 'source_path': image.path,
        'metric_codes': ('budget_total',) if fault in {'denominator_correct', 'denominator_conversion', 'denominator_wrong_scale'} else ('income_total',),
        'standard_label_field': 'department', 'standard_value_fields': ('denominator',) if ratio_case else ('value',),
        'data_bindings': (plan.charts[0].data_bindings[0].model_copy(update={
            'analysis_id': 'analysis_002', 'fact_path': supplemental_path,
            'data_path': 'findings[0].rows', 'fields': tuple(table['columns']),
        }),),
    })
    if fault == 'group_view':
        from smart_reporting.reporting.workflow.runtime.phase_models import StandardChartView

        draft = draft.model_copy(update={'standard_view': StandardChartView(
            kind='group', labelField='department', valueFields=('value',), aggregation='sum')})
    elif fault == 'pivot_view':
        from smart_reporting.reporting.workflow.runtime.phase_models import StandardChartView

        draft = draft.model_copy(update={'standard_label_field': 'month', 'standard_value_fields': ('A',),
            'standard_view': StandardChartView(kind='pivot', labelField='month', valueFields=('value',),
                                             seriesField='department', seriesValues=('A',))})
    elif fault == 'temporal_view':
        from smart_reporting.reporting.workflow.runtime.phase_models import (
            StandardChartAxes,
            StandardChartDerivation,
        )

        draft = draft.model_copy(update={'standard_form': 'line', 'standard_label_field': 'month',
            'standard_value_fields': ('growth',), 'standard_axes': StandardChartAxes(allowNulls=True),
            'standard_derivations': (StandardChartDerivation(kind='mom_percent', name='growth',
                                                            numerator='value', labelField='month'),)})
    elif fault in {'ratio_correct', 'ratio_wrong_parents'}:
        draft = draft.model_copy(update={'metric_codes': ('execution_ratio',), 'standard_value_fields': ('ratio',)})
    plan = plan.model_copy(update={'charts': (draft,)})
    file = ChartInputFile('input.json', sources[plot_id])
    inputs = ChartInputMaterialization(files=(file,), entries=({'chartId': chart.chart_id, 'path': file.path, 'sha256': file.sha256},))
    compiled = standard_visualization_script(plan, inputs).encode()
    result.script_file = FileIdentity(path='charts.py', size=len(compiled), sha256=hashlib.sha256(compiled).hexdigest())
    result.execution_receipt = ExecutionReceipt(runId='render-standard', sourceFile=result.script_file,
        outputFiles=(FileIdentity(path=image.path, size=image.size, sha256=image.sha256),))
    proof = create_standard_render_proofs(result, plan, inputs)[0]['proof']
    script_id = derive_resource_id('charts.py')
    sources[script_id] = compiled
    script = TraceFileRefV1(resourceId=script_id, path='charts.py', mediaType='text/x-python',
                           size=len(compiled), sha256=result.script_file.sha256)
    index = index.model_copy(update={'files': (*index.files, supplemental_file, script),
        'fact_files': (*index.fact_files, FactFileEntryV1(analysisId='analysis_002',
            fileResourceId=supplemental_id, contentKind='supplemental_evidence')),
        'computations': (record,), 'chart_traces': (chart.model_copy(update={
            'standard_render_proof': proof, 'script_file_resource_id': script_id,
        }),)})
    index = index.model_copy(update={'files': tuple(file.model_copy(update={
        'size': len(sources[file.resource_id]), 'sha256': hashlib.sha256(sources[file.resource_id]).hexdigest(),
    }) for file in index.files)})
    quality = evaluate_quality_bundle(index, markdown, sources, authorization_scope_hash='a' * 64)
    assert quality.chart_checks[chart.chart_id].status == 'verified'
    semantic = quality.semantic_checks[chart.chart_id]
    assert semantic.status == ('verified' if fault in {None, 'denominator_correct', 'denominator_conversion', 'ratio_correct', 'group_view', 'pivot_view', 'temporal_view'} else 'unknown'), semantic.reasons


@pytest.mark.anyio
@pytest.mark.parametrize('anyio_backend', ['asyncio'])
@pytest.mark.parametrize('fault', [None, 'script_changed'])
async def test_standard_proof_survives_host_submission_state_and_revision_archive(tmp_path, fault):
    from unittest.mock import AsyncMock

    from smart_reporting.reporting.tests.test_reporting_state import make_visualization_state
    from smart_reporting.reporting.tests.test_reporting_tool_contracts import (
        _toolkit,
        _visual_receipt,
    )
    from smart_reporting.reporting.workflow.runtime.chart_inputs import (
        ChartInputFile,
        ChartInputMaterialization,
        chart_input_root_for,
    )
    from smart_reporting.reporting.workflow.runtime.sections import (
        _analysis_chart_from_registration,
    )
    from smart_reporting.reporting.workflow.runtime.standard_chart_proof import (
        archive_standard_render_proof,
    )
    from smart_reporting.reporting.workflow.state import ReportingStateReducer

    plan, inputs, result, _ = proof_case()
    root = 'analysis/charts/section_001'
    draft = plan.charts[0].model_copy(update={'source_path': root + '/income.png', 'source_dataset_id': 'dataset-1'})
    plan = plan.model_copy(update={'charts': (draft,)})
    file = ChartInputFile(chart_input_root_for(root) + '/input.json', inputs.files[0].content)
    inputs = ChartInputMaterialization(files=(file,), entries=({
        'chartId': draft.chart_id, 'path': file.path, 'size': len(file.content), 'sha256': file.sha256,
    },))
    source = standard_visualization_script(plan, inputs).encode()
    result.script_file = FileIdentity(path=root + '/charts.py', size=len(source), sha256=hashlib.sha256(source).hexdigest())
    image = FileIdentity(path=draft.source_path, size=5, sha256=hashlib.sha256(b'image').hexdigest())
    result.execution_receipt = ExecutionReceipt(runId='host-execution', sourceFile=result.script_file, outputFiles=(image,))
    proof = create_standard_render_proofs(result, plan, inputs)[0]['proof']
    store = {file.path: file.content, result.script_file.path: source, image.path: b'image'}
    if fault == 'script_changed':
        store[result.script_file.path] += b'\n'

    async def current_hash(*, thread_id, path):
        raw = store[path]
        return {'path': path, 'size': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}

    toolkit = _toolkit()
    toolkit._ahash_file = current_hash
    toolkit.runtime.workspace = SimpleNamespace(
        afile_bytes=AsyncMock(side_effect=lambda _thread, path: (store[path], {})),
        inspect_chart_file=AsyncMock(return_value={
            'sourcePath': image.path, 'size': image.size, 'sha256': image.sha256,
            'width': 1600, 'height': 900,
        }),
    )
    receipt = {**_visual_receipt(image.path), 'sha256': image.sha256}
    payload = plan.charts[0].model_dump(mode='json', by_alias=True)
    registration_keys = {'chartId', 'sourcePath', 'title', 'altText', 'citationIds', 'metricCodes',
                         'currentPeriod', 'sourceDatasetId', 'aggregationGrain'}
    submitted = await toolkit.submit_visualization_charts(
        'section_001', [{key: value for key, value in payload.items() if key in registration_keys}],
        visual_receipts=(receipt,), plot_data_files=({'chartId': draft.chart_id, 'files': [{
            'path': file.path, 'size': len(file.content), 'sha256': file.sha256,
        }]},), standard_render_proofs=({'chartId': draft.chart_id,
            'scriptFile': result.script_file.model_dump(mode='json', by_alias=True),
            'proof': proof.model_dump(mode='json', by_alias=True)},),
    )
    assert submitted['ok'] is True
    command = toolkit._apply_durable_command.await_args_list[0].kwargs
    state = ReportingStateReducer.apply(make_visualization_state(), {
        'name': command['name'], 'commandId': command['command_id'], 'payload': command['payload'],
    }).state
    section = state.payload['visualizationSections']['section_001']
    frozen = _analysis_chart_from_registration(section['charts'][0], section['files'][0], None,
                                               section['visualReceipts'][0], section['plotDataFiles'][0])
    if fault:
        assert frozen.standard_render_proof is None
        return
    assert frozen.standard_render_proof == proof

    async def read_identity(_thread, identity, **_kwargs):
        raw = store[identity.path]
        assert len(raw) == identity.size and hashlib.sha256(raw).hexdigest() == identity.sha256
        return raw

    async def write_artifact(_thread, path, raw):
        store[path] = raw
        return FileIdentity(path=path, size=len(raw), sha256=hashlib.sha256(raw).hexdigest())

    runtime = SimpleNamespace(_read_identity_bytes=read_identity, _write_immutable_artifact=write_artifact)
    script, dependencies = await archive_standard_render_proof(runtime, 'thread-1', frozen, 'report/chart-001.png')
    assert script.path == 'report/chart-001.render.py'
    assert len(dependencies) == 2
    archived_inputs = {item.sha256: store[item.path] for item in dependencies if item.path.endswith('.json')}
    assert recompile_standard_render_proof(frozen.standard_render_proof, archived_inputs) == store[script.path]


@pytest.mark.parametrize('selected,expected', [('missingCount', 'unknown'), ('total', 'verified')])
def test_only_drawn_measure_can_supply_units_and_ownership(selected, expected):
    from smart_reporting.reporting.trace.standard_chart_alignment import (
        evaluate_standard_chart_alignment,
    )

    plan, inputs, result, _ = proof_case()
    draft = plan.charts[0].model_copy(update={'standard_value_fields': (selected,),
        'data_bindings': (plan.charts[0].data_bindings[0].model_copy(update={
            'data_path': 'metrics[0]', 'fields': ('field', 'total', 'missingCount', 'average'),
        }),)})
    plot = {'source': {'analysisId': 'analysis_001', 'dataPath': 'metrics[0]', 'path': 'facts.json', 'sha256': 'a' * 64},
            'columns': ['field', 'total', 'missingCount', 'average'], 'rows': [['收入', 1000, 3, None]],
            'columnMeta': {'total': {'unit': '元'}}}
    proof = create_standard_render_proofs(result, plan, inputs)[0]['proof'].model_copy(update={
        'plan': plan.model_copy(update={'charts': (draft,)}).model_dump(mode='json', by_alias=True),
        'inputs': ({'chartId': draft.chart_id, 'sha256': 'b' * 64},),
    })
    chart = SimpleNamespace(chart_id=draft.chart_id, standard_render_proof=proof, plot_data_file_resource_ids=('plot',))
    index = SimpleNamespace(profile_hash='p' * 64,
        files=[SimpleNamespace(resource_id='fact', sha256='a' * 64), SimpleNamespace(resource_id='plot', sha256='b' * 64)],
        fact_files=[SimpleNamespace(content_kind='deterministic_bundle', analysis_id='analysis_001', file_resource_id='fact')])
    documents = {'plot': plot, 'fact': {'analysisId': 'analysis_001', 'metrics': [{
        'factId': 'fact-a', 'scope': {'company': '甲医院'}, 'unit': '元', 'metricCodes': ['income'],
    }]}}
    check = evaluate_standard_chart_alignment(index, chart, documents.__getitem__)
    assert check.status == expected
    if expected == 'unknown':
        assert check.reasons == ('chart_axis_unit_unregistered',)


@pytest.mark.parametrize('other_company,expected', [('甲医院', 'verified'), ('乙医院', 'unknown')])
def test_chart_comparison_cannot_mix_organization_scopes(other_company, expected):
    from smart_reporting.reporting.trace.standard_chart_alignment import (
        evaluate_standard_chart_alignment,
    )

    plan, inputs, result, _ = proof_case()
    first = plan.charts[0]
    second_binding = first.data_bindings[0].model_copy(update={'data_path': 'metrics[1].periodValues'})
    draft = first.model_copy(update={'data_bindings': (*first.data_bindings, second_binding)})
    plots = [{
        'source': {'analysisId': 'analysis_001', 'dataPath': f'metrics[{position}].periodValues',
                   'path': 'facts.json', 'sha256': 'a' * 64},
        'columns': ['period', 'value'], 'rows': [['2025-01', 10]], 'columnMeta': {'value': {'unit': '元'}},
    } for position in range(2)]
    proof = create_standard_render_proofs(result, plan, inputs)[0]['proof'].model_copy(update={
        'plan': plan.model_copy(update={'charts': (draft,)}).model_dump(mode='json', by_alias=True),
        'inputs': tuple({'chartId': draft.chart_id, 'sha256': char * 64} for char in 'bc'),
    })
    chart = SimpleNamespace(chart_id=draft.chart_id, standard_render_proof=proof,
                            plot_data_file_resource_ids=('plot0', 'plot1'))
    metrics = [{'factId': f'fact-{position}', 'scope': {'company': company}, 'unit': '元',
                'metricCodes': ['income'], 'periodValues': [{'period': '2025-01', 'value': 10}]}
               for position, company in enumerate(('甲医院', other_company))]
    index = SimpleNamespace(profile_hash='p' * 64,
        files=[SimpleNamespace(resource_id='fact', sha256='a' * 64),
               SimpleNamespace(resource_id='plot0', sha256='b' * 64), SimpleNamespace(resource_id='plot1', sha256='c' * 64)],
        fact_files=[SimpleNamespace(content_kind='deterministic_bundle', analysis_id='analysis_001', file_resource_id='fact')])
    documents = {'plot0': plots[0], 'plot1': plots[1], 'fact': {'analysisId': 'analysis_001', 'metrics': metrics}}
    check = evaluate_standard_chart_alignment(index, chart, documents.__getitem__)
    assert check.status == expected
    if expected == 'unknown':
        assert check.reasons == ('chart_scope_mismatch',)

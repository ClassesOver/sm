from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from smart_reporting.reporting.contract import ReportRequestEnvelope, infer_delivery_format
from smart_reporting.reporting.tests.test_reporting_interactive_code_agent import (
    workspace,  # noqa: F401
)
from smart_reporting.reporting.workflow.runtime import ReportWorkflowRuntime
from smart_reporting.reporting.workflow.runtime.models import NormalizedReportPrompt


@pytest.mark.parametrize('prompt,expected', [
    ('请生成2025年收入Excel工作簿', 'xlsx'),
    ('请把2025年收入整理成xlsx', 'xlsx'),
    ('生成2025年报告，不需要Excel，提供Word即可', 'document'),
])
def test_explicit_workbook_intent(prompt, expected):
    assert infer_delivery_format(prompt) == expected


@pytest.mark.anyio
async def test_semantic_workbook_intent_and_explicit_override():
    runtime = object.__new__(ReportWorkflowRuntime)
    runtime._request_normalizer = object()
    runtime._run_planner = AsyncMock(return_value=NormalizedReportPrompt(
        reportType='topic', domains=('income',), deliveryFormat='xlsx',
    ))
    context = SimpleNamespace(session_state={})
    result = await runtime.normalize_report_request(SimpleNamespace(
        input={'prompt': '分析2025年收入，各主题放在可编辑工作表中'}, additional_data=None,
    ), context)
    assert result.content['deliveryFormat'] == 'xlsx'
    assert context.session_state['report_request_context']['deliveryFormat'] == 'xlsx'

    other = SimpleNamespace(session_state={})
    result = await runtime.normalize_report_request(SimpleNamespace(
        input={'prompt': '分析2025年收入并生成Excel', 'deliveryFormat': 'document'},
        additional_data=None,
    ), other)
    assert result.content['deliveryFormat'] == 'document'


@pytest.mark.anyio
async def test_ambiguous_formats_use_existing_clarification():
    runtime = object.__new__(ReportWorkflowRuntime)
    runtime._request_normalizer = object()
    runtime._run_planner = AsyncMock(return_value=NormalizedReportPrompt(
        reportType='topic', domains=('income',), deliveryFormatAmbiguous=True,
        clarificationQuestion='请选择演示文稿或Excel工作簿作为本次交付形式。',
    ))
    result = await runtime.normalize_report_request(SimpleNamespace(
        input='分析2025年收入，Excel或PPT都行', additional_data=None,
    ), SimpleNamespace(session_state={}))
    assert result.content == {'clarificationQuestion': '请选择演示文稿或Excel工作簿作为本次交付形式。'}


def test_structured_xlsx_request_and_generation_failure_shape():
    request = ReportRequestEnvelope(reportGoal='收入分析', deliveryFormat='xlsx',
        period={'start': '2025-01-01', 'end': '2025-12-31'})
    assert request.delivery_format == 'xlsx'
    result = ReportWorkflowRuntime._publication_content({
        'reportId': 'r', 'revision': 1, 'jobId': 'j', 'editorJob': {'jobId': 'j'},
        'markdownPath': 'reports/report.md', 'deliveryFormat': 'xlsx',
        'validation': {'ok': False, 'issues': [{'code': 'xlsx_generation_failed'}]},
    })
    assert result['deliveryFormat'] == 'xlsx'
    assert result['xlsxPath'] is None


def test_workbook_sheets_use_frozen_facts_and_preserve_null_zero_and_detail_ids():
    from smart_reporting.reporting.workflow.runtime.workbook import build_workbook_sheets

    manifest = SimpleNamespace(evidence=(SimpleNamespace(
        analysis_id='analysis_001', summary='正文展示123万元但此文本不得反推数值', dataset_ids=('d1',),
    ),), metric_definitions=())
    outline = SimpleNamespace(sections=(SimpleNamespace(
        code='income', title="收入/成本's", analysis_ids=('analysis_001',),
    ),))
    facts = {'analysis_001': {'analysisId': 'analysis_001', 'metrics': [
        {'factId': 'f-zero', 'metricName': '收入', 'total': 0, 'unit': '元', 'datasetId': 'd1', 'periodRoles': ['current']},
        {'factId': 'f-null', 'metricName': '成本', 'total': None, 'unit': '元', 'datasetId': 'd1', 'periodRoles': ['current']},
    ]}}
    sheets, sources = build_workbook_sheets(
        manifest=manifest, outline=outline, fact_documents=facts,
        datasets={'d1': {'columns': ['dept', 'income'], 'rows': [['001', 0], ['002', None]],
                         'path': 'data/d1.csv', 'sha256': 'a' * 64}}, period='2025年',
    )
    assert sheets[1]['rows'][1][2] == 0
    assert sheets[1]['rows'][2][2] is None
    assert sheets[0]['rows'][1][3]['value'] == 0
    assert sheets[0]['rows'][1][3]['formula'].endswith('!C2')
    assert "''" in sheets[0]['rows'][1][3]['formula']
    assert sheets[-1]['rows'][1] == ['001', 0]
    assert sources['datasets']['d1']['sha256'] == 'a' * 64
    assert sources['cells'][0]['factId'] == 'f-zero'
    assert all(123 not in row for sheet in sheets for row in sheet['rows'])


def test_workbook_detail_rows_preserve_registered_types_without_guessing_ids():
    from smart_reporting.reporting.workflow.runtime.workbook import workbook_dataset_rows

    columns, rows, issues = workbook_dataset_rows(
        b'dept,count,active,income,unknown,ambiguous\n001,2,true,0,003,004\n002,,0,,005,006\n',
        dataset_id='d1', measures={'income'}, schema={'tables': [{'columns': [
            {'name': 'dept', 'dataType': 'VARCHAR(10)'},
            {'name': 'count', 'dataType': 'BIGINT'},
            {'name': 'active', 'dataType': 'BOOLEAN'},
            {'name': 'ambiguous', 'dataType': 'INT'},
        ]}, {'columns': [{'name': 'ambiguous', 'dataType': 'VARCHAR(10)'}]}]},
    )
    assert columns == ['dept', 'count', 'active', 'income', 'unknown', 'ambiguous']
    assert rows == [['001', 2, True, 0, '003', '004'], ['002', None, False, None, '005', '006']]
    assert type(rows[0][2]) is bool
    assert type(rows[1][2]) is bool
    assert issues == []


def test_workbook_detail_rows_preserve_invalid_typed_values_with_soft_warning():
    from smart_reporting.reporting.workflow.runtime.workbook import workbook_dataset_rows

    _, rows, issues = workbook_dataset_rows(b'count,active\nNaN,maybe\n', dataset_id='d1',
        measures=set(), schema={'tables': [{'columns': [
            {'name': 'count', 'dataType': 'DECIMAL(18,2)'},
            {'name': 'active', 'dataType': 'BOOLEAN'},
        ]}]})
    assert rows == [['NaN', 'maybe']]
    assert [item['code'] for item in issues] == ['xlsx_numeric_value_invalid', 'xlsx_boolean_value_invalid']
    assert all(item['datasetId'] == 'd1' for item in issues)


@pytest.mark.parametrize('raw,expected,precision_warning', [
    ('9223372036854775807', '9223372036854775807', True),
    ('-9223372036854775808', '-9223372036854775808', True),
    ('0.123456789012345678901234567890', '0.123456789012345678901234567890', True),
    ('999999999999999', 999999999999999, False),
    ('1000000000000001', '1000000000000001', True),
    ('123.456789012345', 123.456789012345, False),
    ('1.23000000000000000000000', 1.23, False),
    ('1e400', '1e400', True),
    ('1e-400', '1e-400', True),
])
def test_workbook_detail_rows_preserve_values_outside_excel_precision(raw, expected, precision_warning):
    from smart_reporting.reporting.workflow.runtime.workbook import workbook_dataset_rows

    _, rows, issues = workbook_dataset_rows(f'value\n{raw}\n'.encode(), dataset_id='d1',
        measures=set(), schema={'tables': [{'columns': [{'name': 'value', 'dataType': 'NUMERIC(38,20)'}]}]})
    assert rows == [[expected]]
    assert [item['code'] for item in issues] == (['xlsx_numeric_precision_preserved'] if precision_warning else [])
    if issues:
        assert '原始文本' in issues[0]['message']


def test_workbook_detail_precision_survives_real_engine_roundtrip(tmp_path):
    from io import BytesIO

    from openpyxl import load_workbook

    from smart_reporting.reporting.delivery.xlsx import (
        build_workbook,
        inspect_workbook,
        patch_workbook,
    )
    from smart_reporting.reporting.workflow.runtime.workbook import workbook_dataset_rows

    columns, rows, issues = workbook_dataset_rows(
        b'bigint,decimal,safe\n9223372036854775807,0.123456789012345678901234567890,123.456789012345\n',
        dataset_id='d1', measures={'decimal', 'safe'}, schema={'tables': [{'columns': [
            {'name': 'bigint', 'dataType': 'BIGINT'},
            {'name': 'decimal', 'dataType': 'DECIMAL(38,30)'},
        ]}]},
    )
    assert len(issues) == 2
    output = tmp_path / 'precision.xlsx'
    build_workbook(output_path=output, title='精度边界', period='',
        sheets=({'name': '明细', 'rows': [columns, *rows]},))
    original = output.read_bytes()
    model = inspect_workbook(original)
    assert model['sheets'][0]['cells']['A2']['value'] == '9223372036854775807'
    assert model['sheets'][0]['cells']['B2']['value'] == '0.123456789012345678901234567890'
    edited = patch_workbook(original, [{'kind': 'applyCellEdits', 'edits': [{
        'sheetName': '明细', 'row': 2, 'column': 0, 'writeValue': True, 'cell': {'value': '已复核'},
    }]}])
    for content in (original, edited):
        book = load_workbook(BytesIO(content))
        assert book['明细']['A2'].value == '9223372036854775807'
        assert book['明细']['A2'].data_type == 's'
        assert book['明细']['B2'].value == '0.123456789012345678901234567890'
        assert book['明细']['B2'].data_type == 's'
        assert book['明细']['C2'].value == 123.456789012345


@pytest.mark.anyio
async def test_workbook_drafting_runs_real_script_and_submits_bound_output(workspace):  # noqa: F811
    import hashlib
    import json
    import subprocess
    import sys
    from pathlib import Path

    from smart_reporting.reporting.code_agent.context import ReportingCodingTaskContext
    from smart_reporting.reporting.code_agent.lsp_process import ReportingLspProcessManager
    from smart_reporting.reporting.code_mode import ScriptProcessResult
    from smart_reporting.reporting.tests.test_reporting_interactive_code_agent import ToolkitRuntime
    from smart_reporting.reporting.workflow.runtime.code_generation import (
        ReportingCodeGenerationRunner,
    )

    class LocalScriptRuntime(ToolkitRuntime):
        async def execute_script_process(self, _session_id, host, path, **_kwargs):
            process = subprocess.run([sys.executable, path], cwd=host.identity.root,
                                     capture_output=True, text=True)
            return ScriptProcessResult(SimpleNamespace(
                status='ok' if process.returncode == 0 else 'error', stdout=process.stdout,
                stderr=process.stderr, traceback=None,
            ), process.returncode)

    spec = {'title': '收入分析', 'period': '2025年', 'sheets': [
        {'name': '汇总', 'rows': [['指标', '数值'], ['收入', 0], ['缺失', None]]},
    ]}
    await workspace.awrite_text('w', 'workbook/input.json', json.dumps(spec))
    context = ReportingCodingTaskContext(
        task_id='w', task_kind='workbook', code_mode_session_id='workbook:w',
        workspace_key=workspace.identity.workspace_key, workspace_root=workspace.identity.root,
        script_path='workbook/build.py', authorized_read_paths=('workbook/input.json',),
        authorized_write_paths=('workbook/build.py', 'workbook/report.xlsx'),
        declared_output_paths=('workbook/report.xlsx',), max_source_bytes=32 * 1024,
    )
    root = str(Path(__file__).resolve().parents[3])
    source = (f'import json,sys\nfrom pathlib import Path\nsys.path.insert(0, {root!r})\n'
        'from smart_reporting.reporting.delivery.xlsx import build_workbook\n'
        "spec=json.loads(Path('workbook/input.json').read_text())\n"
        "build_workbook(output_path=Path('workbook/report.xlsx'), title=spec['title'], period=spec['period'], sheets=tuple(spec['sheets']))\n")
    local = LocalScriptRuntime()
    manager = ReportingLspProcessManager(command=("false",), request_timeout_seconds=0.2)
    runner = ReportingCodeGenerationRunner(lambda _tools: None, local, manager)
    try:
        result = await runner.run_workbook(context, workspace, source)
    finally:
        await manager.aclose()
    output = (workspace.identity.root / 'workbook/report.xlsx').read_bytes()
    assert result.execution_receipt.output_files[0].sha256 == hashlib.sha256(output).hexdigest()
    assert result.execution_receipt.output_files[0].path == 'workbook/report.xlsx'
    assert local.shutdowns == ['workbook:w']


def test_workbook_validation_detects_numeric_formula_and_source_changes():
    import io
    import json
    import zipfile

    from smart_reporting.reporting.workflow.runtime.workbook import validate_workbook_snapshot

    expected = ({'name': '汇总', 'rows': [['数值'], [{'value': 0, 'formula': "='主题'!A2"}]]},)
    sources = {'datasets': {'d1': {'sha256': 'a' * 64}}}
    raw = io.BytesIO()
    with zipfile.ZipFile(raw, 'w') as package:
        package.writestr('smart-reporting/source-mapping.json', json.dumps({'sources': sources}))
    good = {'sheets': [{'name': '汇总', 'cells': {'A1': {'value': '数值'}, 'A2': {'value': 0, 'formula': "'主题'!A2"}}}]}
    assert validate_workbook_snapshot(good, expected, sources, raw.getvalue()) == []
    good['sheets'][0]['cells']['A2'] = {'value': 99, 'formula': '#REF!'}
    issues = validate_workbook_snapshot(good, expected, {'datasets': {}}, raw.getvalue())
    assert {item['code'] for item in issues} == {'xlsx_cell_data_mismatch', 'xlsx_formula_mismatch', 'xlsx_source_mapping_mismatch'}


@pytest.mark.anyio
@pytest.mark.parametrize('checkpoint_failure', [False, True])
async def test_xlsx_render_uses_frozen_inputs_reuses_checkpoint_and_retains_on_failure(
    workspace, monkeypatch, checkpoint_failure,  # noqa: F811
):
    import hashlib
    import io
    import json

    from openpyxl import load_workbook

    from smart_reporting.reporting.code_agent.context import ExecutionReceipt
    from smart_reporting.reporting.data_sources import DatasetHandle
    from smart_reporting.reporting.delivery.xlsx import build_workbook
    from smart_reporting.reporting.workflow.checkpoint import FileIdentity
    from smart_reporting.reporting.workflow.runtime import publication as publication_module

    thread_id = workspace.identity.workspace_key
    csv_bytes = b'dept,income,count,active\n001,0,2,true\n002,,,false\n'
    fact_bytes = json.dumps({'analysisId': 'analysis_001', 'metrics': [{
        'factId': 'f1', 'metricName': '收入', 'total': 0, 'unit': '元',
        'datasetId': 'd1', 'periodRoles': ['current'],
    }]}).encode()
    await workspace.awrite_bytes(thread_id, 'data/d1.csv', csv_bytes)
    await workspace.awrite_bytes(thread_id, 'facts/a1.json', fact_bytes)
    fact_identity = FileIdentity(path='facts/a1.json', size=len(fact_bytes), sha256=hashlib.sha256(fact_bytes).hexdigest())
    dataset = DatasetHandle(dataset_id='d1', source_id='s1', path='data/d1.csv', row_count=2,
        size=len(csv_bytes), sha256=hashlib.sha256(csv_bytes).hexdigest(), requirement_id='q1', sql_hash='a' * 64)
    manifest = SimpleNamespace(evidence=(SimpleNamespace(analysis_id='analysis_001',
        summary='保留已核验结论', dataset_ids=('d1',), evidence_files=(fact_identity,)),))
    current = [SimpleNamespace(files=(), evidence_manifest=manifest,
                               deterministic_fact_files={'analysis_001': fact_identity})]
    current[0].model_copy = lambda update: SimpleNamespace(**{**vars(current[0]), **update})
    monkeypatch.setattr(publication_module, 'ReportingCheckpoint', SimpleNamespace(model_validate=lambda _raw: current[0]))
    result = {'revision': 1, 'jobId': 'j', 'datasets': [dataset.public_dict()]}
    state = {'report_workflow_result': result, 'report_data_requirements': [{
        'requirementId': 'q1', 'sourceId': 's1', 'dimensionColumns': ['dept'], 'grainColumns': ['dept'],
        'tables': [{'table': 'db.data', 'periodColumn': 'period', 'periodGranularity': 'year',
                    'measureColumns': ['income']}],
    }]}
    state['report_analysis_data_context'] = [{
        'datasetId': 'd1', 'sha256': dataset.sha256,
        'schema': {'tables': [{'columns': [
            {'name': 'dept', 'dataType': 'VARCHAR(10)'},
            {'name': 'count', 'dataType': 'BIGINT'},
            {'name': 'active', 'dataType': 'BOOLEAN'},
        ]}]},
    }]
    runtime = object.__new__(ReportWorkflowRuntime)
    runtime.workspace_service = workspace
    runtime.state_repository = SimpleNamespace(get=AsyncMock(return_value=SimpleNamespace(payload={})))
    runtime._state = lambda _ctx: state
    runtime._scope = lambda _ctx: {'threadId': thread_id, 'externalRunId': 'run-1'}
    runtime._envelope = lambda _ctx: ReportRequestEnvelope(reportGoal='收入', deliveryFormat='xlsx',
        period={'start': '2025-01-01', 'end': '2025-12-31'})
    runtime._apply_durable_command = AsyncMock(side_effect=RuntimeError('checkpoint unavailable') if checkpoint_failure else None)
    runtime._native_claim_presentations = AsyncMock(return_value={})

    async def persist(_context, value):
        current[0] = value
        return value

    runtime._persist_reporting_checkpoint = persist

    async def draft(_context, *, spec_path, output_path):
        spec = json.loads((workspace.identity.root / spec_path).read_bytes())
        build_workbook(output_path=workspace.identity.root / output_path, title=spec['title'],
            period=spec['period'], sheets=tuple(spec['sheets']), source_mapping=spec['sourceMapping'])
        await workspace.awrite_text(thread_id, 'scripts/workbook.py', '# bound assembly script\n')
        script = FileIdentity.model_validate(await workspace.ahash_file(thread_id, 'scripts/workbook.py'))
        output = FileIdentity.model_validate(await workspace.ahash_file(thread_id, output_path))
        return SimpleNamespace(script_file=script, execution_receipt=ExecutionReceipt(
            runId='draft-1', sourceFile=script, outputFiles=(output,)))

    runtime._draft_workbook = AsyncMock(side_effect=draft)
    outline = SimpleNamespace(title='收入分析', sections=(SimpleNamespace(code='income', title='收入', analysis_ids=('analysis_001',)),))
    context = SimpleNamespace(run_id='run-1')
    rendered = await runtime._render_xlsx(context, result, outline)
    assert rendered['xlsxPath'].endswith('.xlsx')
    content = (workspace.identity.root / rendered['xlsxPath']).read_bytes()
    workbook = load_workbook(io.BytesIO(content), data_only=True)
    assert workbook['汇总']['D2'].value == 0
    assert workbook['收入']['C2'].value == 0
    assert workbook['汇总']['G2'].value == '保留已核验结论（支持关系待核实）'
    assert rendered['validation']['claimSupport'][0]['support']['supportStatus'] == 'unverified'
    details = workbook.worksheets[-1]
    assert details['A2'].value == '001'
    assert details['B2'].value == 0
    assert details['B3'].value is None
    assert details['C2'].value == 2
    assert details['D2'].value is True
    assert details['D3'].value is False
    assert rendered['xlsxSha256'] == hashlib.sha256(content).hexdigest()
    if checkpoint_failure:
        assert rendered['validation']['ok'] is False
        assert any(issue['code'] == 'xlsx_generation_failed' for issue in rendered['validationIssues'])
    else:
        assert rendered['validation']['ok'] is True
        assert rendered['workbookSources'][0]['datasets']['d1']['sha256'] == dataset.sha256
        repeated = await runtime._render_xlsx(context, result, outline)
        assert repeated['xlsxSha256'] == rendered['xlsxSha256']
        assert runtime._draft_workbook.await_count == 1


@pytest.mark.anyio
async def test_semantic_format_is_frozen_on_resume_even_if_model_changes():
    from smart_reporting.reporting.models import ReportingError

    runtime = object.__new__(ReportWorkflowRuntime)
    runtime._request_normalizer = object()
    runtime._run_planner = AsyncMock(side_effect=[
        NormalizedReportPrompt(reportType='topic', domains=('income',), deliveryFormat='xlsx'),
        NormalizedReportPrompt(reportType='topic', domains=('income',), deliveryFormat='document'),
    ])
    context = SimpleNamespace(session_state={})
    request = {'prompt': '分析2025年收入并整理成工作簿'}
    step = SimpleNamespace(input=request, additional_data=None)
    await runtime.normalize_report_request(step, context)
    repeated = await runtime.normalize_report_request(step, context)
    assert repeated.content['deliveryFormat'] == 'xlsx'
    runtime._run_planner = AsyncMock(return_value=NormalizedReportPrompt(reportType='topic', domains=('income',)))
    with pytest.raises(ReportingError, match='交付格式已冻结'):
        await runtime.normalize_report_request(SimpleNamespace(
            input={**request, 'deliveryFormat': 'pptx'}, additional_data=None,
        ), context)


def test_xlsx_completion_and_mcp_shape_keep_workbook_links():
    from smart_reporting.reporting.presentation import completed_report_content
    from smart_reporting.reporting_mcp.contracts import ReportingPublishedReport

    report = ReportingPublishedReport.model_validate({
        'reportId': 'r', 'revision': 1, 'deliveryFormat': 'xlsx',
        'xlsx': {'downloadUrl': 'https://reports.example.com/report.xlsx', 'expiresAt': '2030-01-01T00:00:00Z',
                 'size': 100, 'sha256': 'a' * 64},
        'validation': {'ok': False, 'issues': [{'code': 'source_unverified'}]},
        'publicationGate': {'formalReleaseAllowed': False, 'issues': [{'message': '编辑后的来源需要核验。'}]},
    })
    content = completed_report_content({'status': 'completed', 'report': report.model_dump(mode='json', by_alias=True)})
    assert '[下载 Excel](https://reports.example.com/report.xlsx)' in content
    assert '编辑后的来源需要核验' in content


def _production_workbook_facts():
    from smart_reporting.reporting.hospital_operation.deterministic_analysis import (
        DeterministicComparison,
        DeterministicDerivedMetricFact,
        DeterministicMetricFact,
    )

    current = DeterministicMetricFact(
        factId='fact-' + '1' * 16, datasetId='current', datasetSha256='a' * 64,
        periodRoles=('current',), metricCodes=('income',), field='amount',
        fieldRef='source.db.income.amount', displayName='医疗收入', aggregation='sum',
        unit='元', formula='SUM(amount)', periodStart='2025-01', periodEnd='2025-12',
        total=100, missingCount=0, zeroCount=0, negativeCount=0,
    )
    baseline = current.model_copy(update={'fact_id': 'fact-' + '2' * 16,
        'dataset_id': 'baseline', 'dataset_sha256': 'b' * 64, 'period_roles': ('yoy',),
        'period_start': '2024-01', 'period_end': '2024-12', 'total': 80})
    groups = [current.model_copy(update={
        'fact_id': 'fact-' + digit * 16, 'scope': {'dept': name}, 'breakdown_field': 'dept',
        'breakdown_label': '科室', 'breakdown_value': name, 'total': total,
    }) for digit, name, total in [('3', '内科', 60), ('4', '外科', 40)]]
    derived = DeterministicDerivedMetricFact(
        factId='fact-' + '5' * 16, code='budget_rate', kind='ratio', periodRole='current',
        numeratorMetric='actual', denominatorMetric='budget', numerator=80, denominator=100,
        percentage=80, value=0.8, unit='元', formula='actual / budget',
        periodStart='2025-01', periodEnd='2025-12', datasetIds=('current',),
        datasetSha256s=('a' * 64,),
    )
    comparison = DeterministicComparison(
        factId='fact-' + '6' * 16, comparisonType='yoy', field='amount',
        fieldRef='source.db.income.amount', currentDatasetId='current', baselineDatasetId='baseline',
        currentDatasetSha256='a' * 64, baselineDatasetSha256='b' * 64,
        currentTotal=100, baselineTotal=80, change=20, changeRate=25,
        formula='current - baseline', unit='元', periodStart='2025-01', periodEnd='2025-12',
        baselinePeriodStart='2024-01', baselinePeriodEnd='2024-12',
    )
    return {'analysisId': 'analysis_001', 'metrics': [current.model_dump(mode='json', by_alias=True), baseline.model_dump(mode='json', by_alias=True)],
        'breakdowns': [item.model_dump(mode='json', by_alias=True) for item in groups],
        'derivedMetrics': [derived.model_dump(mode='json', by_alias=True)],
        'comparisons': [comparison.model_dump(mode='json', by_alias=True)]}


def _production_fact_workbook(document):
    from smart_reporting.reporting.workflow.checkpoint import MetricDefinition
    from smart_reporting.reporting.workflow.runtime.workbook import build_workbook_sheets

    manifest = SimpleNamespace(evidence=(SimpleNamespace(analysis_id='analysis_001',
        summary='已核验分析', dataset_ids=('current', 'baseline')),), metric_definitions=(
        MetricDefinition(code='budget_rate', name='预算完成率', definition='实际与预算之比', unit='%', periodBasis='当前期间'),
    ))
    outline = SimpleNamespace(sections=(SimpleNamespace(code='income', title='收入', analysis_ids=('analysis_001',)),))
    return build_workbook_sheets(manifest=manifest, outline=outline,
        fact_documents={'analysis_001': document}, datasets={}, period='2025年')


def test_workbook_fact_rows_preserve_actual_current_baseline_and_comparison_periods():
    sheets, _sources = _production_fact_workbook(_production_workbook_facts())
    by_fact = {row[6]: row for row in sheets[1]['rows'][1:]}
    assert by_fact['fact-' + '2' * 16][4] == '2024-01 至 2024-12（同比基期）'
    assert by_fact['fact-' + '1' * 16][4] == '2025-01 至 2025-12（本期）'
    comparison = by_fact['fact-' + '6' * 16][4]
    assert '本期：2025-01 至 2025-12' in comparison
    assert '同比基期：2024-01 至 2024-12' in comparison
    assert sheets[0]['rows'][2][5] == by_fact['fact-' + '2' * 16][4]


def test_workbook_fact_rows_preserve_display_name_group_derived_name_and_value_kind():
    sheets, sources = _production_fact_workbook(_production_workbook_facts())
    by_fact = {row[6]: row for row in sheets[1]['rows'][1:]}
    first = by_fact['fact-' + '3' * 16]
    second = by_fact['fact-' + '4' * 16]
    assert '医疗收入' in first[1]
    assert '科室=内科' in first[1]
    assert '科室=外科' in second[1]
    assert first[1] != second[1]
    derived = by_fact['fact-' + '5' * 16]
    assert '预算完成率' in derived[1]
    assert '百分比' in derived[1]
    assert derived[2:4] == [80, '%']
    comparison = by_fact['fact-' + '6' * 16]
    assert '医疗收入' in comparison[1]
    assert '同比变化额' in comparison[1]
    assert comparison[2:4] == [20, '元']
    assert comparison[1] != by_fact['fact-' + '1' * 16][1]
    group_source = next(item for item in sources['cells'] if item['factId'] == first[6])
    assert group_source['scope'] == {'dept': '内科'}


def test_workbook_partial_fact_period_is_not_replaced_by_report_period():
    document = _production_workbook_facts()
    document['metrics'][0]['periodStart'] = None
    sheets, _sources = _production_fact_workbook(document)
    row = sheets[1]['rows'][1]
    assert '2025-12' in row[4]
    assert '起始未登记' in row[4]
    assert '2025年' not in row[4]

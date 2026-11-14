"""正式页面输入按实际 PPTX 和修订冻结，独立实例只读恢复。"""

import asyncio
import hashlib
import json
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from agno.run import RunContext
from agno.workflow.types import StepInput
from PIL import Image
from pptx import Presentation

from smart_reporting.preferences.models import FormatPreferences, resolve_format_preferences
from smart_reporting.reporting.contract import ReportPeriod
from smart_reporting.reporting.hospital_operation.outline import ReportOutline
from smart_reporting.reporting.host_workspace import (
    ReportingWorkspaceRegistry,
    ReportingWorkspaceRouter,
)
from smart_reporting.reporting.workflow.checkpoint import (
    AnalysisChart,
    AnalysisDatasetSemantics,
    AnalysisEvidence,
    AnalysisEvidenceManifest,
    FileIdentity,
    ReportingCheckpoint,
)
from smart_reporting.reporting.workflow.runtime import ReportWorkflowRuntime
from smart_reporting.reporting.workflow.runtime.slides import build_slide_outline

from .narrative_helpers import finding, graph
from .test_dynamic_checkpoint import _coverage


async def pptx_native_case(tmp_path, monkeypatch, *, fault=None, with_narrative=False, with_tables=False):
    from .test_http_publication_lineage import _publication_fixture

    runtime, arguments, scope, durable, artifacts, *_ = await _publication_fixture(tmp_path)
    thread = scope.workspace_key

    async def write(path, content):
        await runtime.workspace_service.awrite_bytes(thread, path, content)
        return FileIdentity(path=path, size=len(content), sha256=hashlib.sha256(content).hexdigest())

    image = BytesIO()
    Image.new('RGB', (320, 180), '#ddeeff').save(image, format='PNG')
    chart = await write('charts/frozen.png', image.getvalue())
    summaries = ()
    if with_narrative:
        from .test_slide_summary_claims import summary_inputs

        summary, *_ = await summary_inputs(monkeypatch, 'mixed')
        summaries = (summary,)
    evidence = AnalysisEvidenceManifest(
        evidence=(AnalysisEvidence(analysisId='analysis_001', summary=summaries[0].blocks[0].markdown if summaries else '收入同比增长5%',
            datasetIds=('dataset-1',), evidenceFiles=(chart,), citationIds=('citation_001',),
            chartIds=('chart_001',)),),
        datasetSemantics=(AnalysisDatasetSemantics(datasetId='dataset-1', rowGrain='month',
            duplicateResolution='not_applicable'),),
        charts=(AnalysisChart(chartId='chart_001', sourceFile=chart, title='冻结图表', altText='冻结静态图',
            citationIds=('citation_001',), metricCodes=('income',), currentPeriod='2025',
            sourceDatasetId='dataset-1', aggregationGrain='month', visualInspectionReceipt={
                'sourcePath': chart.path, 'sha256': chart.sha256, 'inspectionMode': 'deterministic',
                'visualReviewStatus': 'not_run', 'inspectorId': 'deterministic-raster-inspector-v1',
                'reviewed': True, 'requiresRevision': False}),),
    )
    outline = ReportOutline.model_validate({'reportType': 'topic', 'title': '冻结幻灯片',
        'sections': [{'code': 'section_001', 'sectionNumber': '1', 'title': '收入',
            'analysisIds': ['analysis_001']}]})
    source = graph(finding())
    pages = build_slide_outline(source, evidence, title=outline.title, analysis_summaries=summaries)
    fact_files = {}
    if with_tables:
        from .test_trace_table_builder import _bundle

        bundle = _bundle()
        fact_files[bundle.analysis_id] = await write('facts/analysis_001.json', bundle.model_dump_json(by_alias=True).encode())
    checkpoint = ReportingCheckpoint(revision=2, phase='analysis', outlineHash='a'*64,
        profileCoverage=_coverage(), evidenceManifest=evidence, findingGraphHash=source.snapshot_hash,
        findingGraphFile=await write('reports/graph.json', source.model_dump_json(by_alias=True).encode()),
        slideOutlineFile=await write('reports/slides.json', pages.model_dump_json(by_alias=True).encode()),
        deterministicFactFiles=fact_files)
    durable.payload['workflowCheckpoint'] = checkpoint.model_dump(mode='json', by_alias=True)
    durable.payload['artifacts'] = [file.model_dump(mode='json', by_alias=True) for file in fact_files.values()]
    runtime._checkpoint_persist_lock = asyncio.Lock()
    runtime._envelope = lambda _: SimpleNamespace(period=ReportPeriod(start='2025-01-01', end='2025-12-31'))
    runtime._native_claim_presentations = _no_presentations
    runtime._scope = lambda _: scope.as_state()

    async def apply(context, command, **kwargs):
        if fault == 'registration' and command.name == 'record_artifact' and command.payload['artifact']['path'].endswith('.receipt.json'):
            raise OSError('injected pptx native registration failure')
        if command.name == 'record_artifact':
            durable.payload['artifacts'].append(command.payload['artifact'])
        elif command.name == 'set_workflow_checkpoint':
            if fault == 'checkpoint':
                raise OSError('injected pptx native checkpoint failure')
            durable.payload['workflowCheckpoint'] = command.payload['checkpoint']

    runtime._apply_durable_command = apply
    original_write = runtime._write_immutable_artifact

    async def immutable(thread_id, path, content):
        if fault == 'spec' and '/pptx-spec-' in path or fault == 'receipt' and path.endswith('.pptx.receipt.json'):
            raise OSError(f'injected pptx native {fault} failure')
        return await original_write(thread_id, path, content)

    monkeypatch.setattr(runtime, '_write_immutable_artifact', immutable)
    preferences = resolve_format_preferences(FormatPreferences.model_validate({'common': {'signer': '冻结署名'}}), 'pptx')
    context = RunContext(run_id='workflow-run', session_id='workflow-session', session_state={
        'report_request_context': {'deliveryFormat': 'pptx'},
        'report_configuration_snapshot': {'generatedDate': '2026-11-06', 'resolvedFormats': {'pptx': preferences}},
    })
    content = {key: value for key, value in arguments['output'].items() if key not in {
        'artifactManifest', 'pdfPath', 'pdfSize', 'pdfSha256', 'wordPath', 'wordSize', 'wordSha256'}}
    rendered = await runtime._render_pptx(context, content, outline)
    return SimpleNamespace(runtime=runtime, rendered=rendered, arguments=arguments, scope=scope,
        durable=durable, artifacts=artifacts, context=context, outline=outline, chart=chart)


async def _no_presentations(*args, **kwargs):
    return {}


@pytest.mark.anyio
async def test_pptx_native_spec_binds_final_pages_chart_and_actual_artifact_across_restart(tmp_path, monkeypatch):
    case = await pptx_native_case(tmp_path, monkeypatch, with_narrative=True)
    assert case.rendered['validation']['ok'] is True
    native = case.rendered['pptxNativeInput']
    assert native['binding'] == {'workflowRunId': 'workflow-run', 'revision': 2, 'execution': None}
    registered = {item['path']: item for item in case.durable.payload['artifacts']}
    assert all(registered[native[key]['path']] == native[key] for key in ('spec', 'receipt', 'artifact'))
    frozen = ReportingCheckpoint.model_validate(case.durable.payload['workflowCheckpoint'])
    assert all(FileIdentity.model_validate(native[key]) in frozen.files for key in ('spec', 'receipt', 'artifact'))
    # 新实例只使用耐久登记；可变检查点已推进，不能用它证明旧修订。
    case.durable.payload['workflowCheckpoint'] = None
    restarted = object.__new__(ReportWorkflowRuntime)
    restarted.workspace_service = ReportingWorkspaceRouter(ReportingWorkspaceRegistry(tmp_path, secret='s'*32))
    restarted.workspace_service.registry.resolve(case.scope)
    async def read(key):
        return await restarted._read_identity_bytes(case.scope.workspace_key, FileIdentity.model_validate(native[key]))
    receipt = json.loads(await read('receipt'))
    spec_raw = await read('spec')
    spec = json.loads(spec_raw)
    assert receipt['artifact'] == native['artifact']
    assert receipt['spec'] == native['spec']
    assert receipt['binding'] == spec['binding'] == native['binding']
    assert spec['schemaVersion'] == 'pptx-native-input/1'
    assert spec['title'] == '冻结幻灯片'
    assert spec['period'] == '2025-01-01 至 2025-12-31'
    assert spec['generatedDate'] == '2026-11-06'
    assert spec['slides'][0]['bullets'][0] == '收入发生变化（支持关系待核实）'
    assert any('建议按原始金额累计预算' in text for text in spec['slides'][0]['bullets'][1:])
    assert any('建议采用期间平均作为预算合计' in text for text in spec['slides'][0]['bullets'][1:])
    assert spec['slides'][0]['chartPath'] == 'charts/frozen.png'
    assert spec['chartFiles'] == [case.chart.model_dump(mode='json', by_alias=True)]
    assert b'/tmp/' not in spec_raw
    deck = Presentation(BytesIO(await read('artifact')))
    assert len(deck.slides) == 3
    assert '收入发生变化（支持关系待核实）' in '\n'.join(shape.text for shape in deck.slides[1].shapes if shape.has_text_frame)
    assert any(shape.shape_type == 13 for shape in deck.slides[1].shapes)


@pytest.mark.anyio
@pytest.mark.parametrize('fault', ['spec', 'receipt', 'registration', 'checkpoint'])
async def test_pptx_native_registration_fault_preserves_generated_file_and_specific_issue(tmp_path, monkeypatch, fault):
    case = await pptx_native_case(tmp_path, monkeypatch, fault=fault)
    assert case.rendered['status'] == 'validation_failed'
    assert case.rendered['validation']['ok'] is False
    issue = next(item for item in case.rendered['validationIssues'] if item['code'] == 'pptx_native_input_registration_failed')
    assert issue['details']['stage'] == fault
    assert 'pptxNativeInput' not in case.rendered
    actual = await case.runtime.workspace_service.ahash_file(case.scope.workspace_key, case.rendered['pptxPath'])
    assert actual['sha256'] == case.rendered['pptxSha256']
    assert actual['size'] == case.rendered['pptxSize']
    assert actual in case.durable.payload['artifacts']


@pytest.mark.anyio
async def test_initial_publication_freezes_pptx_native_input_in_editor_job(tmp_path, monkeypatch):
    case = await pptx_native_case(tmp_path, monkeypatch)
    case.context.session_state['report_outline'] = case.outline.model_dump(mode='json', by_alias=True)
    case.runtime.report_tools = SimpleNamespace(_load_job=lambda *_: {'jobId': 'job-1'})
    case.runtime._tool_context = lambda context: context
    case.runtime._dataset_publication_gate = AsyncMock(return_value={'formalReleaseAllowed': False, 'issues': [], 'warnings': []})
    published = await case.runtime.publish_report(StepInput(input=''), case.context)
    assert published.content['editorJob']['pptxNativeInput'] == case.rendered['pptxNativeInput']
    result = await case.runtime.issue_http_publication(**{**case.arguments, 'output': published.content})
    assert result['pptx']['downloadUrl']
    frozen_job = case.durable.payload['reportEditorContexts']['2']['job']
    assert frozen_job['pptxNativeInput'] == case.rendered['pptxNativeInput']

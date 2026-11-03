"""PPT 编排只消费冻结证据，不经过文档成稿。"""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from agno.run import RunContext
from agno.workflow import Router
from agno.workflow.types import StepInput, StepOutput

from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.tests.narrative_helpers import finding, graph
from smart_reporting.reporting.workflow.orchestration import create_reporting_workflow
from smart_reporting.reporting.workflow.runtime import ReportWorkflowRuntime
from smart_reporting.reporting.workflow.runtime.models import NormalizedReportPrompt
from smart_reporting.reporting.workflow.state import (
    ReportingCommand,
    ReportingRunState,
    ReportingStateReducer,
)


def _factory(**overrides):
    async def execute(step_input, run_context):
        return StepOutput(content={"status": "completed"})

    names = (
        "normalize_report_request", "confirm_source", "prepare_data_profile",
        "propose_measure_semantics", "commit_measure_semantics", "generate_outline",
        "generate_analysis_plan", "generate_query_candidates", "materialize_datasets",
        "prepare_analysis_context", "generate_detailed_analysis_plan", "run_reporting_analysis",
        "assemble_report", "validate_report", "finalize_publication",
        "run_analysis_evidence", "generate_narrative_outline", "run_report_draft",
    )
    return create_reporting_workflow(db=object(), lifecycle=object(), **{
        **dict.fromkeys(names, execute), **overrides,
    })


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_frozen_pptx_routes_to_slides_without_document_authoring(anyio_backend):
    calls = []

    def executor(name):
        async def execute(step_input, run_context):
            calls.append(name)
            return StepOutput(content={"status": "completed"})
        return execute

    runtime = object.__new__(ReportWorkflowRuntime)
    runtime.state_repository = SimpleNamespace(get=AsyncMock(return_value=SimpleNamespace(
        payload={"deliveryFormat": "pptx"},
    )))
    workflow = _factory(
        generate_slide_outline=executor("slides"),
        assemble_slides=executor("assemble"),
        validate_slides=executor("validate"),
        select_delivery_steps=runtime.select_delivery_steps,
        generate_narrative_outline=executor("document-outline"),
        run_report_draft=executor("document-draft"),
    )
    router = next(step for step in workflow.steps if isinstance(step, Router))
    context = RunContext(run_id="run-1", session_id="session-1", session_state={
        "report_request_context": {"deliveryFormat": "document"},
    })
    routed = await router.selector(StepInput(input="改成普通报告"), context, router.choices)
    for step in routed[0].steps:
        await step.executor(StepInput(input="report"), context)
    for step in workflow.steps[-3:-1]:
        await step.executor(StepInput(input="report"), context)
    assert calls == ["slides", "assemble", "validate"]
    assert context.session_state["report_request_context"]["deliveryFormat"] == "pptx"


def test_delivery_format_is_a_durable_immutable_decision():
    state = ReportingRunState.initial(
        report_run_id="run-1", external_run_id="external-1", thread_id="thread-1",
        owner_user_id="user-1", now=datetime(2026, 11, 3, tzinfo=UTC),
    )
    frozen = ReportingStateReducer.apply(state, ReportingCommand(
        name="freeze_delivery_format", commandId="format:pptx", payload={"deliveryFormat": "pptx"},
    )).state
    assert frozen.payload["deliveryFormat"] == "pptx"
    with pytest.raises(Exception, match="交付格式已冻结"):
        ReportingStateReducer.apply(frozen, ReportingCommand(
            name="freeze_delivery_format", commandId="format:document",
            payload={"deliveryFormat": "document"},
        ))


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_resume_uses_durable_format_without_reinterpreting_prompt(anyio_backend, monkeypatch):
    runtime = object.__new__(ReportWorkflowRuntime)
    runtime._request_normalizer = object()
    runtime._run_planner = AsyncMock(return_value=NormalizedReportPrompt(
        reportType="topic", domains=("income",),
    ))
    runtime.state_repository = SimpleNamespace(get=AsyncMock(return_value=SimpleNamespace(
        payload={"deliveryFormat": "pptx"},
    )))
    runtime._apply_durable_command = AsyncMock()
    monkeypatch.setattr(
        "smart_reporting.reporting.workflow.runtime.planning.infer_delivery_format",
        lambda prompt: pytest.fail("恢复不能重新推断交付格式"),
    )
    context = RunContext(run_id="run-1", session_id="session-1", session_state={})
    output = await runtime.normalize_delivery_request(
        StepInput(input="分析2025年医院收入"), context,
    )
    assert output.content["deliveryFormat"] == "pptx"


def test_slide_outline_binds_each_finding_to_its_own_frozen_evidence():
    from smart_reporting.reporting.workflow.runtime.slides import build_slide_outline

    source = graph(finding(), finding(2, summary="成本上升", citationIds=["citation_002"]))
    evidence = SimpleNamespace(evidence=(
        SimpleNamespace(analysis_id="analysis_001", citation_ids=("citation_001",), chart_ids=()),
        SimpleNamespace(analysis_id="analysis_002", citation_ids=("citation_002",), chart_ids=()),
    ))
    outline = build_slide_outline(source, evidence, title="医院运营分析")
    assert outline.slides[0].finding_ids == ("finding_0000000000000001",)
    assert outline.slides[0].evidence_ids == ("analysis_001", "citation_001")
    assert outline.slides[1].evidence_ids == ("analysis_002", "citation_002")
    assert outline.snapshot_hash == "b" * 64


def test_slide_outline_rejects_unfrozen_analysis_binding():
    from smart_reporting.reporting.workflow.runtime.slides import build_slide_outline

    with pytest.raises(ReportingError, match="冻结证据"):
        build_slide_outline(graph(finding()), SimpleNamespace(evidence=()), title="医院运营分析")


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_pptx_renderer_consumes_frozen_slide_outline_without_document_manifest(anyio_backend, tmp_path, monkeypatch):
    from hashlib import sha256

    from pptx import Presentation

    from smart_reporting.reporting.contract import ReportPeriod
    from smart_reporting.reporting.hospital_operation.outline import ReportOutline
    from smart_reporting.reporting.tests.test_dynamic_checkpoint import _coverage
    from smart_reporting.reporting.workflow.checkpoint import (
        AnalysisDatasetSemantics,
        AnalysisEvidence,
        AnalysisEvidenceManifest,
        FileIdentity,
        ReportingCheckpoint,
    )
    from smart_reporting.reporting.workflow.runtime.slides import build_slide_outline

    class Workspace:
        async def read_limited_regular_file(self, thread, path, max_bytes):
            return (tmp_path / path).read_bytes()

        async def awrite_bytes(self, thread, path, content):
            target = tmp_path / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)

        async def ahash_file(self, thread, path):
            target = tmp_path / path
            if not target.exists():
                return {"path": path, "missing": True}
            content = target.read_bytes()
            return {"path": path, "size": len(content), "sha256": sha256(content).hexdigest()}

    manifest = AnalysisEvidenceManifest(
        evidence=(AnalysisEvidence(
            analysisId="analysis_001", summary="收入同比增长5%", datasetIds=("dataset-1",),
            evidenceFiles=(FileIdentity(path="facts.json", size=1, sha256="a" * 64),),
            citationIds=("citation_001",),
        ),),
        datasetSemantics=(AnalysisDatasetSemantics(
            datasetId="dataset-1", rowGrain="month", duplicateResolution="not_applicable",
        ),),
    )
    planned = build_slide_outline(graph(finding()), manifest, title="医院运营分析")
    raw = planned.model_dump_json(by_alias=True).encode()
    (tmp_path / "slides.json").write_bytes(raw)
    graph_raw = graph(finding()).model_dump_json(by_alias=True).encode()
    (tmp_path / "graph.json").write_bytes(graph_raw)
    checkpoint = ReportingCheckpoint(
        revision=1, phase="analysis", outlineHash="a" * 64, profileCoverage=_coverage(),
        evidenceManifest=manifest,
        findingGraphHash="b" * 64,
        findingGraphFile=FileIdentity(path="graph.json", size=len(graph_raw), sha256=sha256(graph_raw).hexdigest()),
        slideOutlineFile=FileIdentity(path="slides.json", size=len(raw), sha256=sha256(raw).hexdigest()),
    )
    runtime = object.__new__(ReportWorkflowRuntime)
    runtime.workspace_service = Workspace()
    runtime.state_repository = SimpleNamespace(get=AsyncMock(return_value=SimpleNamespace(
        payload={"workflowCheckpoint": checkpoint.model_dump(mode="json", by_alias=True)},
    )))
    runtime._scope = lambda context: {"threadId": "thread-1", "externalRunId": "external-1"}
    runtime._envelope = lambda context: SimpleNamespace(period=ReportPeriod(start="2025-01-01", end="2025-12-31"))
    runtime._apply_durable_command = AsyncMock()
    context = RunContext(run_id="run-1", session_id="session-1", session_state={
        "report_request_context": {"deliveryFormat": "pptx"},
    })
    outline = ReportOutline.model_validate({
        "reportType": "topic", "title": "医院运营分析",
        "sections": [{"code": "section_001", "sectionNumber": "1", "title": "分析分区", "analysisIds": ["analysis_001"]}],
    })
    output = await runtime._render_pptx(context, {"revision": 0}, outline)
    assert output["status"] == "validated"
    presentation = Presentation(tmp_path / output["pptxPath"])
    assert len(presentation.slides) == 2
    assert "finding_0000000000000001" in presentation.slides[1].notes_slide.notes_text_frame.text
    assert "citation_001" in presentation.slides[1].notes_slide.notes_text_frame.text


def test_slide_outline_assigns_registered_static_chart_by_frozen_citation():
    from smart_reporting.reporting.workflow.runtime.slides import build_slide_outline

    evidence = SimpleNamespace(
        evidence=(SimpleNamespace(analysis_id="analysis_001", citation_ids=("citation_001",),
            dataset_ids=("dataset-1",), chart_ids=()),),
        charts=(SimpleNamespace(chart_id="chart_001", citation_ids=("citation_001",),
            source_dataset_id="dataset-1", metric_codes=("income",)),),
    )
    outline = build_slide_outline(graph(finding()), evidence, title="医院运营分析")
    assert outline.slides[0].chart_ids == ("chart_001",)


def test_shared_citation_does_not_bind_other_metric_chart_to_finding():
    from smart_reporting.reporting.workflow.runtime.slides import build_slide_outline

    source = graph(finding(), finding(2, title="成本变化", metricCodes=["cost"]))
    evidence = SimpleNamespace(
        evidence=tuple(SimpleNamespace(analysis_id=f"analysis_{i:03d}", citation_ids=("citation_001",),
            dataset_ids=("shared-dataset",), chart_ids=()) for i in (1, 2)),
        charts=tuple(SimpleNamespace(chart_id=f"{metric}_chart", citation_ids=("citation_001",),
            source_dataset_id="shared-dataset", metric_codes=(metric,)) for metric in ("income", "cost")),
    )
    outline = build_slide_outline(source, evidence, title="经营分析")
    assert outline.slides[0].chart_ids == ("income_chart",)
    assert outline.slides[1].chart_ids == ("cost_chart",)


def test_same_dataset_metric_chart_requires_unambiguous_analysis_binding():
    from smart_reporting.reporting.workflow.runtime.slides import build_slide_outline

    source = graph(finding(), finding(2, title="另一个科室收入"))
    evidence = SimpleNamespace(
        evidence=tuple(SimpleNamespace(analysis_id=f"analysis_{i:03d}", citation_ids=("citation_001",),
            dataset_ids=("shared-dataset",), chart_ids=()) for i in (1, 2)),
        charts=(SimpleNamespace(chart_id="income_chart", citation_ids=("citation_001",),
            source_dataset_id="shared-dataset", metric_codes=("income",)),),
    )
    outline = build_slide_outline(source, evidence, title="经营分析")
    assert all(not slide.chart_ids for slide in outline.slides)
    evidence.evidence[1].chart_ids = ("income_chart",)
    outline = build_slide_outline(source, evidence, title="经营分析")
    assert outline.slides[0].chart_ids == ()
    assert outline.slides[1].chart_ids == ("income_chart",)


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_pptx_assembly_registers_real_static_chart_and_plot_data_for_editor(anyio_backend, tmp_path):
    import json
    from hashlib import sha256

    from smart_reporting.reporting.contract import ReportPeriod
    from smart_reporting.reporting.data_sources import DatasetHandle
    from smart_reporting.reporting.delivery.artifacts_v1 import DatasetLineage
    from smart_reporting.reporting.hospital_operation.outline import ReportOutline
    from smart_reporting.reporting.host_workspace import (
        ReportingWorkspaceRegistry,
        ReportingWorkspaceRouter,
    )
    from smart_reporting.reporting.tests.test_dynamic_checkpoint import _coverage
    from smart_reporting.reporting.tests.test_trace_fact_service import _bundle
    from smart_reporting.reporting.trace.index_builder import (
        build_csv_trace_index,
        encode_trace_index,
    )
    from smart_reporting.reporting.workflow.checkpoint import (
        AnalysisChart,
        AnalysisDatasetSemantics,
        AnalysisEvidence,
        AnalysisEvidenceManifest,
        FileIdentity,
        ReportBrief,
        ReportingCheckpoint,
    )
    from smart_reporting.reporting.workflow.runtime.chart_inputs import _table_for_binding
    from smart_reporting.reporting.workflow.runtime.phase_models import ChartDataBinding
    from smart_reporting.reporting.workflow.runtime.slides import build_slide_outline

    registry = ReportingWorkspaceRegistry(root=tmp_path, secret="test-secret")
    workspace = ReportingWorkspaceRouter(registry)
    from smart_reporting.reporting.tests.test_report_editor_trace import _scope
    scope = _scope("run-1")
    registry.resolve(scope)
    async def write(path, content):
        await workspace.awrite_bytes(scope.workspace_key, path, content)
        return FileIdentity(path=path, size=len(content), sha256=sha256(content).hexdigest())

    from smart_reporting.reporting.tests.test_report_editor_chart_ai import _png_bytes
    image = await write("charts/income.png", _png_bytes())
    csv = await write("datasets/income.csv", bytes([109, 10]))
    fact_payload = _bundle().model_dump(mode="json", by_alias=True)
    facts = await write("facts/income.json", json.dumps(fact_payload).encode())
    binding = ChartDataBinding(analysisId="analysis_001", factPath=facts.path,
        dataPath="metrics[0].periodValues", fields=("period", "value"), role="measure")
    columns, rows, metadata = _table_for_binding(fact_payload, binding)
    plot = await write("charts/income.chart-input.json", json.dumps({
        "schema": "chart-input/v1", "chartId": "income_chart", "role": "measure",
        "source": {"analysisId": "analysis_001", "path": facts.path, "sha256": facts.sha256, "dataPath": binding.data_path},
        "columns": columns, "rows": rows, "rowCount": len(rows), "columnMeta": metadata,
    }).encode())
    handle = DatasetHandle(dataset_id="dataset-url-abc0001", source_id="url", source_type="url_csv", path=csv.path,
        row_count=1, size=csv.size, sha256=csv.sha256, requirement_id="requirement-1", sql_hash="e"*64, filename="income.csv")
    lineage = DatasetLineage(datasetId=handle.dataset_id, sourceId=handle.source_id, sourceType=handle.source_type,
        requirementId=handle.requirement_id, size=handle.size, sha256=handle.sha256,
        rowCount=handle.row_count, sqlHash=handle.sql_hash)
    source = graph(finding())
    manifest = AnalysisEvidenceManifest(
        evidence=(AnalysisEvidence(analysisId="analysis_001", summary="收入同比增长5%", datasetIds=("dataset-url-abc0001",),
            evidenceFiles=(facts,), citationIds=("citation_001",)),),
        charts=(AnalysisChart(chartId="income_chart", sourceFile=image, title="收入趋势", altText="收入趋势",
            citationIds=("citation_001",), metricCodes=("income",), currentPeriod="2025年",
            sourceDatasetId="dataset-url-abc0001", aggregationGrain="month", plotDataFiles=(plot,),
            visualInspectionReceipt={"sourcePath": image.path, "sha256": image.sha256,
                "inspectionMode":"deterministic", "visualReviewStatus":"not_run",
                "inspectorId":"deterministic-raster-inspector-v1", "reviewed":True, "requiresRevision":False}),),
        datasetSemantics=(AnalysisDatasetSemantics(datasetId="dataset-url-abc0001", rowGrain="month", duplicateResolution="not_applicable"),),
    )
    outline = build_slide_outline(source, manifest, title="医院运营分析")
    outline_file = await write("slides/outline.json", outline.model_dump_json(by_alias=True).encode())
    graph_file = await write("slides/graph.json", source.model_dump_json(by_alias=True).encode())
    checkpoint = ReportingCheckpoint(revision=1, phase="analysis", outlineHash="a"*64, profileCoverage=_coverage(),
        evidenceManifest=manifest, slideOutlineFile=outline_file,
        findingGraphFile=graph_file, findingGraphHash=source.snapshot_hash,
        reportBrief=ReportBrief(objective="收入分析", executiveSummary="收入增长", managementQuestions=("收入变化",)),
        analysisManifestFile=FileIdentity(path="evidence.json", size=1, sha256="d"*64),
        deterministicFactFiles={"analysis_001":facts})
    runtime = object.__new__(ReportWorkflowRuntime)
    runtime.workspace_service = workspace
    runtime._scope = lambda context: {"threadId":scope.workspace_key, "externalRunId":"run-1"}
    runtime._profile = lambda context: SimpleNamespace(effective_profile_hash="b"*64)
    runtime._persist_reporting_checkpoint = AsyncMock(side_effect=lambda context, value: value)
    runtime._apply_durable_command = AsyncMock()
    runtime._slide_checkpoint = AsyncMock(return_value=(SimpleNamespace(phase="sections"), checkpoint))
    durable = SimpleNamespace(payload={"workflowCheckpoint":checkpoint.model_dump(mode="json", by_alias=True)}, state_version=0)
    class Repository:
        async def get(self, run_id):
            return durable
        async def apply(self, run_id, command, **kwargs):
            if command.name == "set_report_editor_context":
                durable.payload.setdefault("reportEditorContexts", {})[str(command.payload["context"]["revision"])] = command.payload["context"]
    runtime.state_repository = Repository()
    async def trace(manifest_relative, **kwargs):
        index = build_csv_trace_index(handles=kwargs["handles"], lineage=kwargs["lineage"], report_id="run-1",
            revision=1, workflow_run_id="run-1", markdown_file=kwargs["markdown_artifact"],
            fact_files=kwargs["fact_files"], chart_trace_files=kwargs["chart_trace_files"], chart_traces=kwargs["chart_traces"])
        identity = await runtime._write_immutable_artifact(scope.workspace_key, "slides/trace-index-v1.json", encode_trace_index(index))
        from smart_reporting.reporting.delivery.artifacts_v1 import ArtifactFile
        return ArtifactFile(**identity.model_dump(), mediaType="application/json")
    runtime._write_trace_index = trace
    report_outline = ReportOutline.model_validate({"reportType":"topic", "title":"医院运营分析", "sections":[
        {"code":"section_001","sectionNumber":"1","title":"收入分析","analysisIds":["analysis_001"]}]})
    state = {"report_outline":report_outline.model_dump(mode="json", by_alias=True), "report_outline_hash":"",
        "report_dataset_lineage":[lineage.model_dump(mode="json", by_alias=True)],
        "report_workflow_result":{"jobId":"job-1","revision":0,"datasets":[handle.public_dict()]}}
    from smart_reporting.reporting.workflow.runtime.base import payload_sha256
    state["report_outline_hash"] = payload_sha256(state["report_outline"])
    context = RunContext(run_id="run-1", session_id="session-1", session_state=state)
    await runtime.assemble_slides(StepInput(input="report"), context)
    assert runtime._persist_reporting_checkpoint.await_args.args[1].phase == "completed"
    assert any(call.args[1].name == "complete" for call in runtime._apply_durable_command.await_args_list)
    output = state["report_workflow_result"]
    markdown = await workspace.aread_text(scope.workspace_key, output["markdownPath"])
    registered = state["report_artifacts"]["draft"]
    assert "![收入趋势](chart-001.png) [[citation:citation_001]]" in markdown
    assert len(registered["charts"]) == 1
    assert registered["charts"][0]["sha256"] == image.sha256
    assert registered["traceIndex"]["path"] == "slides/trace-index-v1.json"
    runtime._tool_context = lambda value: value
    runtime._feedback = lambda value: None
    runtime.report_tools = SimpleNamespace(_load_job=lambda *args: {"jobId": "job-1"})
    runtime._dataset_publication_gate = AsyncMock(return_value={"formalReleaseAllowed":True,"issues":[],"warnings":[]})
    state["report_request_context"] = {"deliveryFormat":"pptx"}
    runtime._apply_durable_command = AsyncMock()
    runtime._envelope = lambda value: SimpleNamespace(period=ReportPeriod(start="2025-01-01",end="2025-12-31"))
    rendered = await runtime._render_pptx(context, output, report_outline)
    assert rendered.get("pptxPath"), rendered.get("validationIssues")
    published = await runtime.publish_report(StepInput(input="report"), context)
    assert published.content.get("artifactManifest") == output["artifactManifest"]
    assert published.content["revision"] == registered["revision"]
    runtime._feedback = lambda value: "请重新验收 PPT"
    runtime.run_reporting_analysis = AsyncMock(side_effect=AssertionError("PPT 不得进入文档成稿"))
    runtime.generate_slide_outline = AsyncMock()
    runtime.assemble_slides = AsyncMock()
    runtime._render_and_validate = AsyncMock(return_value=output)
    await runtime.publish_report(StepInput(input="report"), context)
    runtime.generate_slide_outline.assert_awaited_once()
    runtime.assemble_slides.assert_awaited_once()
    runtime.run_reporting_analysis.assert_not_awaited()
    from smart_reporting.report_editor import (
        InMemoryReportEditorRepository,
        ReportEditorGrantService,
        ReportEditorService,
    )
    from smart_reporting.report_editor.service import ReportEditorContext, ReportEditorSession
    from smart_reporting.report_editor.slides import ReportSlidesEditorService
    from smart_reporting.report_editor.slides_chart_ai import ReportSlidesChartAIService
    from smart_reporting.reporting.delivery.publishing import (
        ReportArtifactPersistenceService,
        ReportDownloadGrantService,
    )
    from smart_reporting.reporting.tests.delivery_fakes import (
        InMemoryDownloadGrantRepository,
        InMemoryReportArtifactRepository,
    )
    from smart_reporting.reporting.tests.test_report_editor_chart_ai import FakeRunner, _service
    from smart_reporting.reporting.workflow.scope import REPORT_WORKFLOW_SCOPE_DEPENDENCY
    runtime.artifact_persistence = ReportArtifactPersistenceService(InMemoryReportArtifactRepository(), workspace)
    runtime.download_grants = ReportDownloadGrantService(InMemoryDownloadGrantRepository())
    runtime.editor_grants = ReportEditorGrantService(InMemoryReportEditorRepository(), secret="s"*32)
    runtime.report_public_base_url = "http://reports.test"
    issued = await runtime.issue_http_publication(
        thread_id=scope.workspace_key, caller_thread_id=scope.caller_thread_id, user_id=scope.user_id,
        workflow_session_id=scope.session_id, workflow_run_id=scope.run_id,
        dependencies={REPORT_WORKFLOW_SCOPE_DEPENDENCY:{"externalRunId":scope.external_run_id,"threadId":scope.caller_thread_id,
            "userId":scope.user_id,"database":scope.database,"companyId":scope.company_id}}, output=published.content,
    )
    assert issued["pptx"]["downloadUrl"]
    assert issued["editor"]["openUrl"]
    editor_context = ReportEditorContext.model_validate(durable.payload["reportEditorContexts"]["1"])
    assert editor_context.artifact_manifest is not None
    editor = ReportEditorService(state_repository=runtime.state_repository, workspace_registry=registry, workspace=workspace,
        trace_cursor_secret=b"trace-cursor-secret-32-bytes-ok!")
    session = ReportEditorSession(report_id=scope.run_id, revision=1, workflow_run_id=scope.run_id,
        context_sha256=editor_context.digest(), expires_at=datetime.now(UTC), capabilities={"pptx_editor":True})
    slides = ReportSlidesEditorService(state_repository=runtime.state_repository, workspace_registry=registry, workspace=workspace)
    ai = _service(SimpleNamespace(editor=editor), FakeRunner(_png_bytes()))
    service = ReportSlidesChartAIService(slides, chart_ai=ai)
    listing = await service.list_charts(session)
    assert len(listing["charts"]) == 1
    assert listing["charts"][0]["baseImagePath"].endswith("chart-001.png")
    assert listing["charts"][0]["available"] is True, listing
    binding = listing["charts"][0]
    started = await service.start_edit(session, binding["slideIndex"], binding["elementId"], "改成横向条形图")
    from smart_reporting.reporting.tests.test_report_editor_chart_ai import _await_edit
    status = await _await_edit(ai, editor_context, binding["chartId"], started["editId"])
    assert status["status"] == "succeeded", status
    await ai.aclose()
    from smart_reporting.reporting.workflow.state import ReportingPhase
    completed_checkpoint = runtime._persist_reporting_checkpoint.await_args.args[1]
    runtime._slide_checkpoint.return_value = (SimpleNamespace(phase=ReportingPhase.COMPLETED), completed_checkpoint)
    runtime._persist_reporting_checkpoint.reset_mock()
    await ReportWorkflowRuntime.assemble_slides(runtime, StepInput(input="重试"), context)
    assert all(call.args[1].phase == "completed" for call in runtime._persist_reporting_checkpoint.await_args_list)


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
@pytest.mark.parametrize("delivery_format", ["document", "pptx"])
@pytest.mark.parametrize("failed_stage", ["assemble", "validate"])
async def test_native_agno_delivery_router_resumes_only_failed_nested_step(anyio_backend, delivery_format, failed_stage, tmp_path):
    from agno.db.sqlite import SqliteDb
    from agno.run import RunStatus

    from smart_reporting.reporting.tests.test_managed_reporting_workflow import Lifecycle
    from smart_reporting.reporting.workflow.controller import ReportWorkflowController

    calls = []
    failed = False
    async def execute(step_input, run_context):
        return StepOutput(content={"status":"completed"})
    def stage(name):
        async def run(step_input, run_context):
            nonlocal failed
            calls.append(name)
            if name.endswith(failed_stage) and not failed:
                failed = True
                raise OSError("renderer transient failure")
            return StepOutput(content={"status":"completed"})
        return run
    async def select(step_input, run_context, step_choices):
        return [next(choice for choice in step_choices if choice.name == delivery_format)]
    workflow = _factory(select_delivery_steps=select,
        generate_slide_outline=stage("outline"), assemble_slides=stage("assemble"), validate_slides=stage("validate"),
        generate_narrative_outline=stage("outline"), run_report_draft=stage("draft"),
        assemble_report=stage("document-assemble"),
        validate_report=stage("validate" if delivery_format == "document" else "forbidden-document-validate"))
    workflow.db = SqliteDb(db_file=str(tmp_path / "workflow.db"))
    workflow.lifecycle = Lifecycle()
    for step in workflow.steps[-3:-1]:
        step.max_retries = 0
    output = await workflow.arun("report", run_id="run-native", session_id="session-native", user_id="user", stream=False)
    assert output.status is RunStatus.paused
    requirement = ReportWorkflowController._active_error_requirement(output)
    assert requirement.step_id == f"{failed_stage}-report"
    requirement.retry()
    resumed = await workflow.acontinue_run(run_response=output, stream=False)
    assert resumed.status is RunStatus.completed
    expected = ["outline", "draft", "document-assemble", "validate"] if delivery_format == "document" else ["outline", "assemble", "validate"]
    position = next(index for index, name in enumerate(expected) if name.endswith(failed_stage))
    expected.insert(position, expected[position])
    assert calls == expected


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_native_delivery_router_failure_never_runs_assembly_or_publication(anyio_backend, tmp_path):
    from agno.db.sqlite import SqliteDb

    from smart_reporting.reporting.tests.test_managed_reporting_workflow import Lifecycle

    calls = []
    async def failed(step_input, run_context):
        raise ValueError("frozen evidence unavailable")
    async def forbidden(step_input, run_context):
        calls.append("downstream")
        return StepOutput(content={"status":"completed"})
    async def select(step_input, run_context, step_choices):
        return [next(choice for choice in step_choices if choice.name == "pptx")]
    workflow = _factory(select_delivery_steps=select, generate_slide_outline=failed,
        assemble_slides=forbidden, validate_slides=forbidden, finalize_publication=forbidden)
    workflow.db = SqliteDb(db_file=str(tmp_path / "failed.db"))
    workflow.lifecycle = Lifecycle()
    with pytest.raises(Exception, match="frozen evidence unavailable|编排"):
        await workflow.arun("report", run_id="run-failed", session_id="session-failed", stream=False)
    assert not calls


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
@pytest.mark.parametrize("stored_format", [None, "document", "pptx"])
async def test_legacy_resume_freezes_stored_format_without_prompt_inference(anyio_backend, stored_format, monkeypatch):
    runtime = object.__new__(ReportWorkflowRuntime)
    durable = SimpleNamespace(payload={})
    runtime.state_repository = SimpleNamespace(get=AsyncMock(return_value=durable))
    async def freeze(context, command):
        durable.payload.update(command.payload)
    runtime._apply_durable_command = AsyncMock(side_effect=freeze)
    monkeypatch.setattr(
        "smart_reporting.reporting.workflow.runtime.planning.infer_delivery_format",
        lambda prompt: pytest.fail("历史恢复不能重新解析 prompt"),
    )
    state = {"report_request_context": ({"deliveryFormat": stored_format} if stored_format else {})}
    context = RunContext(run_id="legacy", session_id="session", session_state=state)
    await runtime.restore_delivery_format(StepInput(input="请改成另一个格式"), context)
    assert durable.payload["deliveryFormat"] == (stored_format or "document")
    await runtime.restore_delivery_format(StepInput(input="重复恢复"), context)
    runtime._apply_durable_command.assert_awaited_once()


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_native_legacy_document_pause_resumes_into_current_delivery_dispatch(anyio_backend, tmp_path):
    from agno.db.sqlite import SqliteDb
    from agno.run import RunStatus

    from smart_reporting.reporting.tests.test_managed_reporting_workflow import Lifecycle
    from smart_reporting.reporting.workflow.controller import ReportWorkflowController

    calls = []
    async def failed(step_input, run_context):
        raise OSError("暂时无法渲染")
    async def execute(step_input, run_context):
        calls.append("document-validation")
        return StepOutput(content={"status": "completed"})
    db = SqliteDb(db_file=str(tmp_path / "legacy.db"))
    legacy = _factory(validate_report=failed)
    legacy.db, legacy.lifecycle = db, Lifecycle()
    next(step for step in legacy.steps if step.step_id == "validate-report").max_retries = 0
    paused = await legacy.arun("旧报告", run_id="legacy", session_id="session", stream=False)
    assert paused.status is RunStatus.paused
    runtime = object.__new__(ReportWorkflowRuntime)
    durable = SimpleNamespace(payload={})
    runtime.state_repository = SimpleNamespace(get=AsyncMock(return_value=durable))
    async def freeze(context, command):
        durable.payload.update(command.payload)
    runtime._apply_durable_command = AsyncMock(side_effect=freeze)
    current = _factory(generate_slide_outline=execute, assemble_slides=execute, validate_slides=execute,
        select_delivery_steps=runtime.select_delivery_steps, restore_delivery_format=runtime.restore_delivery_format,
        validate_report=execute)
    current.db, current.lifecycle = db, Lifecycle()
    ReportWorkflowController._active_error_requirement(paused).retry()
    resumed = await current.acontinue_run(run_response=paused, stream=False)
    assert resumed.status is RunStatus.completed
    assert calls == ["document-validation"]
    assert durable.payload["deliveryFormat"] == "document"


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_slide_planning_freezes_visualization_once_and_reuses_outline_on_resume(anyio_backend):
    from hashlib import sha256

    from smart_reporting.reporting.hospital_operation.detailed_analysis import DetailedAnalysisPlan
    from smart_reporting.reporting.hospital_operation.outline import ReportOutline
    from smart_reporting.reporting.tests.test_deterministic_analysis import analysis
    from smart_reporting.reporting.tests.test_dynamic_checkpoint import _coverage
    from smart_reporting.reporting.workflow.checkpoint import (
        AnalysisArtifact,
        AnalysisDatasetSemantics,
        AnalysisEvidence,
        AnalysisEvidenceManifest,
        FileIdentity,
        ReportBrief,
        ReportingCheckpoint,
    )
    from smart_reporting.reporting.workflow.runtime.base import payload_sha256
    from smart_reporting.reporting.workflow.state import ReportingPhase

    documents = {}
    async def write(thread, path, content):
        documents[path] = content
        return FileIdentity(path=path, size=len(content), sha256=sha256(content).hexdigest())
    async def read(thread, identity, model):
        return model.model_validate_json(documents[identity.path])
    fact = await write("thread", "facts.json", b'{"analysisId":"analysis_001"}')
    graph_file = await write("thread", "graph.json", graph(finding()).model_dump_json(by_alias=True).encode())
    validation = await write("thread", "report.validation-context.json", b'{}')
    evidence = AnalysisEvidenceManifest(
        evidence=(AnalysisEvidence(analysisId="analysis_001", summary="收入变化",
            datasetIds=("current",), evidenceFiles=(fact,), citationIds=("citation_001",)),),
        datasetSemantics=(AnalysisDatasetSemantics(datasetId="current", rowGrain="month",
            duplicateResolution="not_applicable"),),
    )
    artifact = AnalysisArtifact(evidenceManifest=evidence, reportBrief=ReportBrief(
        objective="分析收入", executiveSummary="收入变化", managementQuestions=("收入变化",)))
    checkpoint = ReportingCheckpoint(revision=1, phase="analysis", outlineHash="a"*64,
        profileCoverage=_coverage(), findingGraphFile=graph_file, findingGraphHash="b"*64,
        deterministicFactFiles={"analysis_001": fact}, files=(validation,))
    durable = SimpleNamespace(phase=ReportingPhase.NARRATIVE_PLANNING)
    runtime = object.__new__(ReportWorkflowRuntime)
    async def current(context):
        return durable, checkpoint
    async def persist(context, value):
        nonlocal checkpoint
        checkpoint = value
        return value
    async def apply(context, command):
        if command.name == "complete_narrative_planning":
            durable.phase = ReportingPhase.SECTIONS
    runtime._slide_checkpoint = current
    runtime._scope = lambda _: {"threadId": "thread"}
    runtime._read_identity_model, runtime._write_immutable_artifact = read, write
    runtime._persist_reporting_checkpoint = persist
    runtime._current_reporting_checkpoint = AsyncMock(side_effect=lambda context, value: checkpoint)
    runtime._apply_durable_command = AsyncMock(side_effect=apply)
    runtime._build_reporting_artifact = AsyncMock(return_value=artifact)
    runtime._run_visualization_section_task = AsyncMock()
    runtime._vision_enabled = False
    outline = ReportOutline.model_validate({"reportType":"topic", "title":"医院运营分析",
        "sections":[{"code":"section_001","sectionNumber":"1","title":"收入","analysisIds":["analysis_001"]}]})
    state = {"report_outline": outline.model_dump(mode="json", by_alias=True),
        "report_detailed_analysis_plan": DetailedAnalysisPlan(analyses=(analysis(),),
            datasetIds=("current", "yoy", "mom")).model_dump(mode="json", by_alias=True),
        "report_dataset_lineage": []}
    state["report_outline_hash"] = payload_sha256(state["report_outline"])
    context = RunContext(run_id="run", session_id="session", session_state=state)
    await runtime.generate_slide_outline(StepInput(input="PPT"), context)
    frozen_outline = checkpoint.slide_outline_file
    await runtime.generate_slide_outline(StepInput(input="普通报告"), context)
    assert checkpoint.slide_outline_file == frozen_outline
    assert checkpoint.evidence_manifest == evidence
    runtime._run_visualization_section_task.assert_awaited_once()
    runtime._build_reporting_artifact.assert_awaited_once()
    runtime._apply_durable_command.assert_awaited_once()

from unittest.mock import AsyncMock

import pytest
from agno.run import RunContext

from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.workflow.checkpoint import (
    AnalysisEvidence,
    ChartVisualInspectionReceipt,
    FileIdentity,
    SectionCitation,
    SectionWorkItem,
)
from smart_reporting.reporting.workflow.runtime.phase_models import (
    ChartDraft,
    RenderSectionDecision,
    VisualizationScriptDraft,
)
from smart_reporting.reporting.workflow.runtime.section_workflow import SectionWorkflow
from smart_reporting.reporting.workflow.runtime.visualization_section_workflow import (
    VisualizationSectionWorkflow,
)


def _context() -> RunContext:
    return RunContext(run_id="run-1", session_id="session-1")


def _chart() -> ChartDraft:
    return ChartDraft(
        chartId="chart_001",
        sourcePath="charts/chart.png",
        title="收入趋势",
        altText="收入按月趋势",
        citationIds=("citation_001",),
        metricCodes=("revenue",),
        currentPeriod="2026-08",
        sourceDatasetId="dataset_001",
        aggregationGrain="month",
    )


def _visualization_draft() -> VisualizationScriptDraft:
    return VisualizationScriptDraft(
        scriptPath="charts/charts.py", pythonSource="print('ok')", charts=(_chart(),)
    )


def _inspection() -> ChartVisualInspectionReceipt:
    return ChartVisualInspectionReceipt(
        sourcePath="charts/chart.png",
        sha256="a" * 64,
        inspectionMode="vision",
        visualReviewStatus="passed",
        modelId="vision-test",
        reviewed=True,
        requiresRevision=False,
    )


@pytest.mark.anyio
async def test_visualization_workflow_orders_fixed_steps() -> None:
    events: list[str] = []
    file_identity = FileIdentity(path="charts/charts.py", size=1, sha256="a" * 64)

    async def generate(_payload, _context):
        events.append("generate")
        return _visualization_draft()

    async def write(_path, _source, _context):
        events.append("write")
        return file_identity

    async def execute(command, _context):
        events.append(command)
        return {"exitCode": 0}

    async def inspect(_chart, _context):
        events.append("inspect")
        return _inspection()

    async def submit(_draft, _inspections, _context):
        events.append("submit")
        return {"status": "accepted"}

    result = await VisualizationSectionWorkflow(
        generate=generate,
        recover=None,
        write_script=write,
        execute_script=execute,
        inspect_chart=inspect,
        submit=submit,
    ).run({}, _context())

    assert result.status == "accepted"
    assert events == ["generate", "write", "python3 charts/charts.py", "inspect", "submit"]


@pytest.mark.anyio
async def test_visualization_workflow_recovers_script_failure_once() -> None:
    recover = AsyncMock(return_value=_visualization_draft())
    execute = AsyncMock(side_effect=[{"exitCode": 1}, {"exitCode": 0}])
    file_identity = FileIdentity(path="charts/charts.py", size=1, sha256="a" * 64)
    result = await VisualizationSectionWorkflow(
        generate=AsyncMock(return_value=_visualization_draft()),
        recover=recover,
        write_script=AsyncMock(return_value=file_identity),
        execute_script=execute,
        inspect_chart=AsyncMock(return_value=_inspection()),
        submit=AsyncMock(return_value={"status": "accepted"}),
    ).run({}, _context())
    assert result.recovery_used is True
    recover.assert_awaited_once()


@pytest.mark.anyio
async def test_visualization_workflow_does_not_recover_artifact_change() -> None:
    recover = AsyncMock()
    with pytest.raises(ReportingError) as caught:
        await VisualizationSectionWorkflow(
            generate=AsyncMock(return_value=_visualization_draft()),
            recover=recover,
            write_script=AsyncMock(
                side_effect=ReportingError("report_phase_artifact_changed", "SHA changed")
            ),
            execute_script=AsyncMock(),
            inspect_chart=AsyncMock(),
            submit=AsyncMock(),
        ).run({}, _context())
    assert caught.value.code == "report_phase_artifact_changed"
    recover.assert_not_awaited()


@pytest.mark.anyio
async def test_visualization_workflow_allows_deterministic_submission_without_vision() -> None:
    submit = AsyncMock(return_value={"status": "committed"})
    result = await VisualizationSectionWorkflow(
        generate=AsyncMock(return_value=_visualization_draft()),
        recover=None,
        write_script=AsyncMock(
            return_value=FileIdentity(path="charts/charts.py", size=1, sha256="a" * 64)
        ),
        execute_script=AsyncMock(return_value={"exitCode": 0}),
        inspect_chart=None,
        submit=submit,
    ).run({}, _context())

    assert result.status == "accepted"
    assert result.inspections == ()
    submit.assert_awaited_once()


def _section_work_item() -> SectionWorkItem:
    identity = FileIdentity(path="evidence/a.json", size=8, sha256="a" * 64)
    evidence = AnalysisEvidence(
        analysisId="analysis_001",
        summary="summary",
        datasetIds=("dataset_001",),
        evidenceFiles=(identity,),
        citationIds=("citation_001",),
    )
    return SectionWorkItem(
        sectionCode="section_001",
        sectionNumber="1",
        title="收入",
        objective="目标",
        completionConditions=("完成",),
        analysisIds=("analysis_001",),
        evidence=(evidence,),
        citations=(
            SectionCitation(
                citationId="citation_001",
                datasetId="dataset_001",
                requirementId="requirement_001",
                snapshotHash="a" * 64,
            ),
        ),
        factSummaries=("事实摘要",),
        markdownRequirements=("markdown",),
    )


@pytest.mark.anyio
async def test_section_workflow_reads_evidence_before_generation() -> None:
    events: list[str] = []

    async def read(path, offset, _context):
        events.append(f"read:{path}:{offset}")
        return {"content": "证据正文", "nextOffset": None}

    async def generate(bundle, _context):
        events.append("generate")
        assert bundle.files[0].content == "证据正文"
        return RenderSectionDecision.model_construct(
            section_code="section_001", blocks=(), claims=()
        )

    async def render(_decision, _context):
        events.append("render")
        return {"status": "accepted"}

    result = await SectionWorkflow(
        read_evidence=read,
        generate=generate,
        recover=None,
        render=render,
        rework=AsyncMock(),
    ).run(_section_work_item(), _context())
    assert result.status == "accepted"
    assert events == ["read:evidence/a.json:0", "generate", "render"]


@pytest.mark.anyio
async def test_section_workflow_rejects_non_progressing_evidence_offset() -> None:
    with pytest.raises(ReportingError, match="续读 offset"):
        await SectionWorkflow(
            read_evidence=AsyncMock(return_value={"content": "x", "nextOffset": 0}),
            generate=AsyncMock(),
            recover=None,
            render=AsyncMock(),
            rework=AsyncMock(),
        ).run(_section_work_item(), _context())

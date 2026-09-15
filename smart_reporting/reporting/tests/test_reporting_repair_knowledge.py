from __future__ import annotations

from collections.abc import Mapping
from unittest.mock import AsyncMock

import pytest
from agno.run import RunContext
from agno.workflow.types import StepOutput

from smart_reporting.reporting.code_agent.context import ExecutionReceipt
from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.workflow.checkpoint import FileIdentity
from smart_reporting.reporting.workflow.runtime.analysis import _record_successful_repair
from smart_reporting.reporting.workflow.runtime.analysis_item_workflow import (
    AnalysisItemWorkflow,
    AnalysisSummaryDraft,
    SupplementalEvidence,
    _AnalysisItemState,
)
from smart_reporting.reporting.workflow.runtime.code_generation import CodeGenerationResult
from smart_reporting.reporting.workflow.runtime.phase_models import (
    ChartDraft,
    VisualizationPlanDraft,
)
from smart_reporting.reporting.workflow.runtime.visualization_section_workflow import (
    VisualizationSectionWorkflow,
)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def _script_file() -> FileIdentity:
    return FileIdentity(path="charts/charts.py", size=8, sha256="a" * 64)


def _chart_file() -> FileIdentity:
    return FileIdentity(path="charts/chart.png", size=9, sha256="b" * 64)


def _visualization_plan() -> VisualizationPlanDraft:
    return VisualizationPlanDraft(
        charts=(
            ChartDraft(
                chartId="chart_001",
                sourcePath="charts/chart.png",
                title="收入趋势",
                altText="收入月度趋势",
                citationIds=("citation_001",),
                metricCodes=("revenue",),
                currentPeriod="2026-08",
                sourceDatasetId="dataset_001",
                aggregationGrain="month",
            ),
        )
    )


def _result() -> CodeGenerationResult:
    script_file = _script_file()
    return CodeGenerationResult(
        script_file=script_file,
        execution_receipt=ExecutionReceipt(
            runId="run-1",
            sourceFile=script_file,
            outputFiles=(_chart_file(),),
        ),
    )


@pytest.mark.anyio
async def test_visualization_records_only_accepted_repair_after_domain_submission() -> None:
    recorded: list[tuple[Mapping[str, object], FileIdentity]] = []

    async def record(diagnostic: Mapping[str, object], script_file: FileIdentity) -> None:
        recorded.append((diagnostic, script_file))

    workflow = VisualizationSectionWorkflow(
        generate_plan=AsyncMock(return_value=_visualization_plan()),
        run_code=AsyncMock(
            side_effect=[
                ReportingError("report_visualization_script_failed", "执行失败"),
                _result(),
            ]
        ),
        inspect_chart=None,
        submit=AsyncMock(return_value={"status": "accepted"}),
        record_successful_repair=record,
    )

    result = await workflow.run(
        {"visualizationWorkspace": {"scriptPath": "charts/charts.py"}},
        RunContext(run_id="run-1", session_id="session-1"),
    )

    assert result.status == "accepted"
    assert recorded == [
        (
            {
                "code": "report_visualization_script_failed",
                "message": "执行失败",
                "details": {"path": "charts/charts.py"},
            },
            _script_file(),
        )
    ]


@pytest.mark.anyio
async def test_visualization_does_not_record_first_generation() -> None:
    record = AsyncMock()
    workflow = VisualizationSectionWorkflow(
        generate_plan=AsyncMock(return_value=_visualization_plan()),
        run_code=AsyncMock(return_value=_result()),
        inspect_chart=None,
        submit=AsyncMock(return_value={"status": "accepted"}),
        record_successful_repair=record,
    )

    result = await workflow.run(
        {"visualizationWorkspace": {"scriptPath": "charts/charts.py"}},
        RunContext(run_id="run-1", session_id="session-1"),
    )

    assert result.status == "accepted"
    record.assert_not_awaited()


@pytest.mark.anyio
async def test_visualization_does_not_record_repair_when_domain_submission_rejects() -> None:
    record = AsyncMock()
    workflow = VisualizationSectionWorkflow(
        generate_plan=AsyncMock(return_value=_visualization_plan()),
        run_code=AsyncMock(
            side_effect=[
                ReportingError("report_visualization_script_failed", "执行失败"),
                _result(),
            ]
        ),
        inspect_chart=None,
        submit=AsyncMock(return_value={"status": "rejected", "code": "not_accepted"}),
        record_successful_repair=record,
    )

    with pytest.raises(ReportingError, match="not_accepted"):
        await workflow.run(
            {"visualizationWorkspace": {"scriptPath": "charts/charts.py"}},
            RunContext(run_id="run-1", session_id="session-1"),
        )

    record.assert_not_awaited()


@pytest.mark.anyio
async def test_analysis_records_repair_only_after_completion_is_accepted() -> None:
    record = AsyncMock()
    workflow = AnalysisItemWorkflow(
        decide_evidence=AsyncMock(),
        run_code=AsyncMock(),
        summarize=AsyncMock(return_value=AnalysisSummaryDraft(summary="完成", warnings=())),
        read_file=AsyncMock(),
        complete=AsyncMock(return_value={"status": "accepted", "taskFinished": True}),
        record_successful_repair=record,
    )
    workflow._model_facts = lambda _state: {}  # type: ignore[method-assign]
    state = _AnalysisItemState(
        instruction={
            "currentAnalysisId": "analysis_001",
            "currentAnalysis": {"datasetIds": ["dataset_001"]},
            "citationRegistry": (),
        },
        evidence=SupplementalEvidence(
            analysisId="analysis_001",
            datasetIds=("dataset_001",),
            findings=({"name": "事实"},),
            reconciliations=({"name": "对账", "passed": True},),
            warnings=(),
        ),
        evidence_file=FileIdentity(path="analysis/evidence.json", size=2, sha256="c" * 64),
        script_file=FileIdentity(path="analysis/script.py", size=3, sha256="d" * 64),
        repair_diagnostic={"code": "report_analysis_script_failed", "message": "执行失败"},
    )

    output = await workflow._complete_analysis(
        state,
        RunContext(run_id="run-1", session_id="session-1"),
    )

    assert output == StepOutput(content={"status": "accepted"})
    record.assert_awaited_once_with(
        {"code": "report_analysis_script_failed", "message": "执行失败"},
        state.script_file,
    )


@pytest.mark.anyio
async def test_analysis_does_not_record_repair_after_repair_exhaustion() -> None:
    record = AsyncMock()
    workflow = AnalysisItemWorkflow(
        decide_evidence=AsyncMock(),
        run_code=AsyncMock(),
        summarize=AsyncMock(return_value=AnalysisSummaryDraft(summary="完成", warnings=())),
        read_file=AsyncMock(),
        complete=AsyncMock(return_value={"status": "accepted", "taskFinished": True}),
        record_successful_repair=record,
    )
    workflow._model_facts = lambda _state: {}  # type: ignore[method-assign]
    state = _AnalysisItemState(
        instruction={
            "currentAnalysisId": "analysis_001",
            "currentAnalysis": {"datasetIds": ["dataset_001"]},
            "citationRegistry": (),
        },
        script_file=FileIdentity(path="analysis/script.py", size=3, sha256="d" * 64),
        repair_diagnostic={"code": "report_analysis_script_failed", "message": "执行失败"},
        supplement_abandoned=True,
    )

    await workflow._complete_analysis(state, RunContext(run_id="run-1", session_id="session-1"))

    record.assert_not_awaited()


@pytest.mark.anyio
async def test_runtime_repair_record_uses_scoped_metadata_without_diagnostic_content() -> None:
    record = AsyncMock()
    index = type("Knowledge", (), {"record_successful_repair": record})()

    await _record_successful_repair(
        index,
        workspace_key="workspace-a",
        task_kind="analysis",
        diagnostic={
            "code": "report_analysis_script_failed",
            "message": "不得持久化 /host/secret.csv 或数据正文",
        },
        script_file=FileIdentity(path="analysis/script.py", size=3, sha256="d" * 64),
    )

    record.assert_awaited_once_with(
        workspace_key="workspace-a",
        task_kind="analysis",
        error_code="report_analysis_script_failed",
        source_sha256="d" * 64,
        summary="修复 report_analysis_script_failed 后，正式领域验收已通过。",
    )


@pytest.mark.anyio
async def test_runtime_repair_record_softly_ignores_knowledge_failure() -> None:
    record = AsyncMock(side_effect=RuntimeError("knowledge offline"))
    index = type("Knowledge", (), {"record_successful_repair": record})()

    await _record_successful_repair(
        index,
        workspace_key="workspace-a",
        task_kind="visualization",
        diagnostic={"code": "report_visualization_script_failed"},
        script_file=FileIdentity(path="charts/script.py", size=3, sha256="d" * 64),
    )

    record.assert_awaited_once()

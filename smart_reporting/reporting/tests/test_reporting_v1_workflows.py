from __future__ import annotations

import hashlib
import json

import pytest
from agno.run import RunContext

from smart_reporting.reporting.code_agent.context import ExecutionReceipt
from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.workflow.checkpoint import (
    ChartVisualInspectionReceipt,
    FileIdentity,
)
from smart_reporting.reporting.workflow.runtime.analysis_item_workflow import (
    AnalysisEvidenceDecision,
    AnalysisItemWorkflow,
    AnalysisSummaryDraft,
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


@pytest.mark.anyio
async def test_analysis_v1_workflow_executes_signed_code_and_completes_once() -> None:
    facts = json.dumps({"analysisId": "analysis_001", "metrics": [], "derivedMetrics": [], "comparisons": [], "reconciliations": [], "warnings": []})
    evidence = json.dumps({"findings": [{"name": "收入"}], "reconciliations": [{"name": "对账", "passed": True}], "warnings": []})
    facts_path = "facts/analysis_001.json"
    script_path = "evidence/analysis_001/supplement.py"
    evidence_path = "evidence/analysis_001/supplement.json"
    script = FileIdentity(path=script_path, size=10, sha256="b" * 64)
    receipt = ExecutionReceipt(runId="run-1", sourceFile=script, outputFiles=(FileIdentity(path=evidence_path, size=len(evidence.encode()), sha256=hashlib.sha256(evidence.encode()).hexdigest()),))
    calls: list[str] = []

    async def read_file(*, path: str, **_: object) -> dict[str, object]:
        content = facts if path == facts_path else evidence
        digest = hashlib.sha256(content.encode()).hexdigest()
        calls.append(path)
        return {"ok": True, "content": content, "sha256": digest, "totalBytes": len(content.encode()), "nextOffset": len(content.encode())}

    async def run_code(**_: object) -> CodeGenerationResult:
        calls.append("run_code")
        return CodeGenerationResult(script_file=script, execution_receipt=receipt)

    async def complete(**kwargs: object) -> dict[str, object]:
        calls.append("complete")
        assert kwargs["evidencePaths"] == [evidence_path]
        return {"status": "accepted", "taskFinished": True}

    workflow = AnalysisItemWorkflow(
        decide_evidence=lambda _payload: _decision(),
        run_code=run_code,
        summarize=lambda _payload: _summary(),
        read_file=read_file,
        complete=complete,
    )
    instruction = {"currentAnalysisId": "analysis_001", "currentAnalysis": {"analysisId": "analysis_001", "datasetIds": ["dataset_1"]}, "analysisOutputRoot": "evidence/analysis_001", "deterministicFactFile": {"path": facts_path, "size": len(facts.encode()), "sha256": hashlib.sha256(facts.encode()).hexdigest()}, "deterministicFacts": json.loads(facts), "datasets": [{"datasetId": "dataset_1"}]}
    result = await workflow.run(instruction, RunContext(run_id="run-1", session_id="session-1"))
    assert result.stage_statuses == tuple((name, "completed") for name in ("read-facts", "plan-evidence", "execute-script", "validate-evidence", "complete-analysis"))
    assert calls.count("run_code") == 1


async def _decision() -> AnalysisEvidenceDecision:
    return AnalysisEvidenceDecision(requiresSupplementalEvidence=True, reason="缺少收入", missingFacts=("收入",))


async def _summary() -> AnalysisSummaryDraft:
    return AnalysisSummaryDraft(summary="完成", warnings=())


@pytest.mark.anyio
async def test_analysis_v1_workflow_restarts_coding_with_evidence_diagnostic() -> None:
    facts = json.dumps({"analysisId": "analysis_001", "metrics": [], "derivedMetrics": [], "comparisons": [], "reconciliations": [], "warnings": []})
    invalid_evidence = json.dumps({"findings": [], "reconciliations": [], "warnings": []})
    valid_evidence = json.dumps({"findings": [{"name": "收入"}], "reconciliations": [{"name": "对账", "passed": True}], "warnings": []})
    facts_path = "facts/analysis_001.json"
    script_path = "evidence/analysis_001/supplement.py"
    evidence_path = "evidence/analysis_001/supplement.json"
    evidence_reads = 0
    diagnostics: list[object] = []

    async def read_file(*, path: str, **_: object) -> dict[str, object]:
        nonlocal evidence_reads
        if path == facts_path:
            content = facts
        else:
            content = invalid_evidence if evidence_reads == 0 else valid_evidence
            evidence_reads += 1
        return {"ok": True, "content": content, "sha256": hashlib.sha256(content.encode()).hexdigest(), "totalBytes": len(content.encode()), "nextOffset": len(content.encode())}

    async def run_code(**kwargs: object) -> CodeGenerationResult:
        diagnostics.append(kwargs.get("diagnostic"))
        content = invalid_evidence if len(diagnostics) == 1 else valid_evidence
        script = FileIdentity(path=script_path, size=len(diagnostics), sha256=("a" if len(diagnostics) == 1 else "b") * 64)
        evidence_file = FileIdentity(path=evidence_path, size=len(content.encode()), sha256=hashlib.sha256(content.encode()).hexdigest())
        return CodeGenerationResult(script_file=script, execution_receipt=ExecutionReceipt(runId=f"run-{len(diagnostics)}", sourceFile=script, outputFiles=(evidence_file,)))

    complete = []

    async def accepted(**_: object) -> dict[str, object]:
        complete.append(True)
        return {"status": "accepted", "taskFinished": True}

    workflow = AnalysisItemWorkflow(decide_evidence=lambda _payload: _decision(), run_code=run_code, summarize=lambda _payload: _summary(), read_file=read_file, complete=accepted)
    await workflow.run({"currentAnalysisId": "analysis_001", "currentAnalysis": {"analysisId": "analysis_001", "datasetIds": ["dataset_1"]}, "analysisOutputRoot": "evidence/analysis_001", "deterministicFactFile": {"path": facts_path, "size": len(facts.encode()), "sha256": hashlib.sha256(facts.encode()).hexdigest()}, "deterministicFacts": json.loads(facts), "datasets": [{"datasetId": "dataset_1"}]}, RunContext(run_id="run-1", session_id="session-1"))

    assert len(diagnostics) == 2
    assert diagnostics[0] is None
    assert diagnostics[1]["code"] == "report_analysis_evidence_schema_invalid"
    assert complete == [True]


@pytest.mark.anyio
async def test_visualization_v1_workflow_accepts_signed_chart_receipt_without_reexecution() -> None:
    chart = ChartDraft(chartId="chart_001", sourcePath="charts/chart.png", title="收入趋势", altText="收入趋势图", citationIds=("cite_1",), metricCodes=("revenue",), currentPeriod="2026-08", sourceDatasetId="dataset_1", aggregationGrain="month")
    plan = VisualizationPlanDraft(charts=(chart,))
    script = FileIdentity(path="charts/charts.py", size=8, sha256="a" * 64)
    chart_file = FileIdentity(path=chart.source_path, size=9, sha256="b" * 64)
    receipt = ChartVisualInspectionReceipt(
        sourcePath=chart.source_path,
        sha256="b" * 64,
        inspectionMode="vision",
        visualReviewStatus="passed",
        modelId="vision-1",
        reviewed=True,
        requiresRevision=False,
        summary="通过",
    )
    calls = {"run": 0, "submit": 0}

    async def run_code(*_: object, **__: object) -> CodeGenerationResult:
        calls["run"] += 1
        return CodeGenerationResult(
            script_file=script,
            execution_receipt=ExecutionReceipt(
                runId="run-1", sourceFile=script, outputFiles=(chart_file,)
            ),
            visual_inspection_receipts=(receipt,),
        )

    async def submit(*_: object, **__: object) -> dict[str, str]:
        calls["submit"] += 1
        return {"status": "accepted"}

    workflow = VisualizationSectionWorkflow(generate_plan=lambda *_: _plan(plan), run_code=run_code, submit=submit)
    result = await workflow.run({"visualizationWorkspace": {"scriptPath": script.path}}, RunContext(run_id="run-1", session_id="session-1"))
    assert result.status == "accepted"
    assert calls == {"run": 1, "submit": 1}


@pytest.mark.anyio
async def test_visualization_v1_zero_chart_plan_skips_coding() -> None:
    calls = {"run": 0, "submit": 0}

    async def run_code(*_: object, **__: object) -> CodeGenerationResult:
        calls["run"] += 1
        raise AssertionError("零图计划不得启动 Coding Agent")

    async def submit(*_: object, **__: object) -> dict[str, str]:
        calls["submit"] += 1
        return {"status": "accepted"}

    workflow = VisualizationSectionWorkflow(
        generate_plan=lambda *_: _plan(VisualizationPlanDraft(charts=())),
        run_code=run_code,
        submit=submit,
    )
    result = await workflow.run({}, RunContext(run_id="run-1", session_id="session-1"))

    assert result.status == "accepted"
    assert result.script_file is None
    assert calls == {"run": 0, "submit": 1}


@pytest.mark.anyio
async def test_visualization_v1_rejects_unsigned_planned_chart() -> None:
    chart = ChartDraft(chartId="chart_001", sourcePath="charts/chart.png", title="收入趋势", altText="收入趋势图", citationIds=("cite_1",), metricCodes=("revenue",), currentPeriod="2026-08", sourceDatasetId="dataset_1", aggregationGrain="month")
    plan = VisualizationPlanDraft(charts=(chart,))
    script = FileIdentity(path="charts/charts.py", size=8, sha256="a" * 64)

    async def run_code(*_: object, **__: object) -> CodeGenerationResult:
        return CodeGenerationResult(
            script_file=script,
            execution_receipt=ExecutionReceipt(
                runId="run-1", sourceFile=script, outputFiles=()
            ),
        )

    workflow = VisualizationSectionWorkflow(
        generate_plan=lambda *_: _plan(plan),
        run_code=run_code,
        submit=lambda *_: _accepted(),
    )
    with pytest.raises(ReportingError) as caught:
        await workflow.run(
            {"visualizationWorkspace": {"scriptPath": script.path}},
            RunContext(run_id="run-1", session_id="session-1"),
        )

    assert caught.value.code == "report_phase_artifact_changed"


@pytest.mark.anyio
async def test_visualization_v1_does_not_retry_nonrecoverable_coding_failure() -> None:
    chart = ChartDraft(chartId="chart_001", sourcePath="charts/chart.png", title="收入趋势", altText="收入趋势图", citationIds=("cite_1",), metricCodes=("revenue",), currentPeriod="2026-08", sourceDatasetId="dataset_1", aggregationGrain="month")
    calls = {"run": 0, "degrade": 0}

    async def run_code(*_: object, **__: object) -> CodeGenerationResult:
        calls["run"] += 1
        raise ReportingError("report_phase_artifact_changed", "签发身份冲突")

    async def degrade(*_: object) -> dict[str, str]:
        calls["degrade"] += 1
        return {"status": "accepted"}

    workflow = VisualizationSectionWorkflow(
        generate_plan=lambda *_: _plan(VisualizationPlanDraft(charts=(chart,))),
        run_code=run_code,
        submit=lambda *_: _accepted(),
        degrade=degrade,
    )
    with pytest.raises(ReportingError) as caught:
        await workflow.run(
            {"visualizationWorkspace": {"scriptPath": "charts/charts.py"}},
            RunContext(run_id="run-1", session_id="session-1"),
        )

    assert caught.value.code == "report_phase_artifact_changed"
    assert calls == {"run": 1, "degrade": 0}


@pytest.mark.anyio
async def test_visualization_v1_degrades_after_execution_repairs_exhausted() -> None:
    chart = ChartDraft(chartId="chart_001", sourcePath="charts/chart.png", title="收入趋势", altText="收入趋势图", citationIds=("cite_1",), metricCodes=("revenue",), currentPeriod="2026-08", sourceDatasetId="dataset_1", aggregationGrain="month")
    diagnostics: list[object] = []
    repair_attempts: list[int] = []

    async def run_code(*_: object, **kwargs: object) -> CodeGenerationResult:
        diagnostics.append(kwargs.get("diagnostic"))
        task_facts = kwargs.get("task_facts")
        if isinstance(task_facts, dict):
            repair_attempts.append(task_facts["repairAttempt"])
        raise ReportingError("report_visualization_script_failed", "脚本执行失败")

    degraded: list[ReportingError] = []

    async def degrade(error: Exception, _context: RunContext) -> dict[str, str]:
        assert isinstance(error, ReportingError)
        degraded.append(error)
        return {"status": "accepted"}

    workflow = VisualizationSectionWorkflow(
        generate_plan=lambda *_: _plan(VisualizationPlanDraft(charts=(chart,))),
        run_code=run_code,
        submit=lambda *_: _accepted(),
        degrade=degrade,
    )
    result = await workflow.run(
        {"visualizationWorkspace": {"scriptPath": "charts/charts.py"}},
        RunContext(run_id="run-1", session_id="session-1"),
    )

    assert result.status == "degraded"
    assert len(diagnostics) == 4
    assert diagnostics[0] is None
    assert all(item["code"] == "report_visualization_script_failed" for item in diagnostics[1:])
    assert repair_attempts == [1, 2, 3]
    assert degraded[0].details["executionRepairCount"] == 3


@pytest.mark.anyio
async def test_visualization_v1_rejects_invalid_visual_receipt() -> None:
    chart = ChartDraft(chartId="chart_001", sourcePath="charts/chart.png", title="收入趋势", altText="收入趋势图", citationIds=("cite_1",), metricCodes=("revenue",), currentPeriod="2026-08", sourceDatasetId="dataset_1", aggregationGrain="month")
    plan = VisualizationPlanDraft(charts=(chart,))
    script_path = "charts/charts.py"
    script = FileIdentity(path=script_path, size=1, sha256="a" * 64)
    output = FileIdentity(path=chart.source_path, size=1, sha256="c" * 64)
    receipt = ChartVisualInspectionReceipt(
        sourcePath=chart.source_path,
        sha256="d" * 64,
        inspectionMode="vision",
        visualReviewStatus="passed",
        modelId="vision-1",
        reviewed=True,
        requiresRevision=False,
        summary="通过",
    )

    async def run_code(*_: object, **kwargs: object) -> CodeGenerationResult:
        return CodeGenerationResult(
            script_file=script,
            execution_receipt=ExecutionReceipt(
                runId="run-1", sourceFile=script, outputFiles=(output,)
            ),
            visual_inspection_receipts=(receipt,),
        )

    submit = []

    async def accepted(*_: object) -> dict[str, str]:
        submit.append(True)
        return {"status": "accepted"}

    workflow = VisualizationSectionWorkflow(generate_plan=lambda *_: _plan(plan), run_code=run_code, submit=accepted)
    with pytest.raises(ReportingError) as caught:
        await workflow.run(
            {"visualizationWorkspace": {"scriptPath": script_path}},
            RunContext(run_id="run-1", session_id="session-1"),
        )

    assert caught.value.code == "report_phase_artifact_changed"
    assert submit == []


@pytest.mark.anyio
async def test_visualization_v1_degrades_after_code_agent_visual_repairs_exhausted() -> None:
    chart = ChartDraft(chartId="chart_001", sourcePath="charts/chart.png", title="收入趋势", altText="收入趋势图", citationIds=("cite_1",), metricCodes=("revenue",), currentPeriod="2026-08", sourceDatasetId="dataset_1", aggregationGrain="month")
    plan = VisualizationPlanDraft(charts=(chart,))
    run_count = 0

    async def run_code(*_: object, **kwargs: object) -> CodeGenerationResult:
        nonlocal run_count
        run_count += 1
        raise ReportingError("report_code_generation_no_submission", "视觉修复耗尽")

    degraded: list[ReportingError] = []

    async def degrade(error: Exception, _context: RunContext) -> dict[str, str]:
        assert isinstance(error, ReportingError)
        degraded.append(error)
        return {"status": "accepted"}

    workflow = VisualizationSectionWorkflow(generate_plan=lambda *_: _plan(plan), run_code=run_code, submit=lambda *_: _accepted(), degrade=degrade)
    result = await workflow.run({"visualizationWorkspace": {"scriptPath": "charts/charts.py"}}, RunContext(run_id="run-1", session_id="session-1"))

    assert result.status == "degraded"
    assert run_count == 1
    assert degraded[0].details["executionRepairCount"] == 0
    assert degraded[0].details["visualReviewRepairCount"] == 0


async def _plan(plan: VisualizationPlanDraft) -> VisualizationPlanDraft:
    return plan


async def _accepted() -> dict[str, str]:
    return {"status": "accepted"}

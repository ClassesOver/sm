from __future__ import annotations

import hashlib
import json

import pytest
from agno.run import RunContext

from smart_reporting.reporting.code_agent.context import ExecutionReceipt
from smart_reporting.reporting.workflow.checkpoint import FileIdentity
from smart_reporting.reporting.workflow.runtime.analysis_item_workflow import (
    AnalysisEvidenceDecision,
    AnalysisItemWorkflow,
    AnalysisSummaryDraft,
)
from smart_reporting.reporting.workflow.runtime.code_generation import CodeGenerationResult
from smart_reporting.reporting.workflow.runtime.phase_models import ChartDraft, VisualizationPlanDraft
from smart_reporting.reporting.workflow.runtime.visualization_section_workflow import VisualizationSectionWorkflow


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
async def test_visualization_v1_workflow_accepts_signed_chart_receipt_without_reexecution() -> None:
    chart = ChartDraft(chartId="chart_001", sourcePath="charts/chart.png", title="收入趋势", altText="收入趋势图", citationIds=("cite_1",), metricCodes=("revenue",), currentPeriod="2026-08", sourceDatasetId="dataset_1", aggregationGrain="month")
    plan = VisualizationPlanDraft(charts=(chart,))
    script = FileIdentity(path="charts/charts.py", size=8, sha256="a" * 64)
    chart_file = FileIdentity(path=chart.source_path, size=9, sha256="b" * 64)
    calls = {"run": 0, "submit": 0}

    async def run_code(*_: object, **__: object) -> CodeGenerationResult:
        calls["run"] += 1
        return CodeGenerationResult(script_file=script, execution_receipt=ExecutionReceipt(runId="run-1", sourceFile=script, outputFiles=(chart_file,)))

    async def submit(*_: object, **__: object) -> dict[str, str]:
        calls["submit"] += 1
        return {"status": "accepted"}

    workflow = VisualizationSectionWorkflow(generate_plan=lambda *_: _plan(plan), run_code=run_code, inspect_chart=None, submit=submit)
    result = await workflow.run({"visualizationWorkspace": {"scriptPath": script.path}}, RunContext(run_id="run-1", session_id="session-1"))
    assert result.status == "accepted"
    assert calls == {"run": 1, "submit": 1}


async def _plan(plan: VisualizationPlanDraft) -> VisualizationPlanDraft:
    return plan

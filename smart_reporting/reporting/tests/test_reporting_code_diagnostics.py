from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from agno.run import RunContext

from smart_reporting.reporting.code_agent.lsp_process import ReportingLspProcessManager
from smart_reporting.reporting.code_agent.toolkit import (
    MAX_DIAGNOSTIC_BYTES,
    ReportingCodeModeToolkit,
    _bounded_failure,
    _failure,
    compile_script_source,
    validate_draft_source,
)
from smart_reporting.reporting.code_mode import ScriptProcessResult
from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.tests.test_reporting_interactive_code_agent import (
    SOURCE,
    binding,  # noqa: F401
    runtime,  # noqa: F401
    workspace,  # noqa: F401
)
from smart_reporting.reporting.tests.test_reporting_repair_knowledge import (
    _visualization_payload,
    _visualization_plan,
)
from smart_reporting.reporting.workflow.runtime.analysis_item_workflow import (
    MAX_ANALYSIS_SCRIPT_GENERATION_ATTEMPTS,
    AnalysisEvidenceDecision,
    AnalysisItemWorkflow,
    _AnalysisItemState,
)
from smart_reporting.reporting.workflow.runtime.visualization_section_workflow import (
    VisualizationSectionWorkflow,
)


@pytest.fixture
def anyio_backend():
    return "asyncio"


def test_compile_error_retains_source_location_and_reason():
    with pytest.raises(ReportingError) as caught:
        compile_script_source("analysis/a.py", "x = 1\nif True\n    pass\n", frozenset())
    details = caught.value.details
    assert details["path"] == "analysis/a.py"
    assert details["line"] == 2
    assert details["column"] == 8
    assert details["sourceLine"].strip() == "if True"
    assert details["errorType"] == "SyntaxError"
    assert "expected ':'" in details["reason"]


def test_analysis_script_facts_reuse_compact_existing_fact_baseline():
    workflow = AnalysisItemWorkflow(
        decide_evidence=AsyncMock(),
        run_code=AsyncMock(),
        summarize=AsyncMock(),
        read_file=AsyncMock(),
        complete=AsyncMock(),
    )
    state = _AnalysisItemState(
        instruction={
            "currentAnalysis": {
                "analysisId": "analysis_001",
                "datasetIds": ["dataset-1"],
            },
            "deterministicFacts": {
                "analysisId": "analysis_001",
                "metrics": [
                    {
                        "datasetId": "dataset-1",
                        "field": "income",
                        "aggregation": "sum",
                        "unit": "元",
                        "formula": "sum(income)",
                        "total": 120.0,
                        "periodValues": [{"period": "2025-01", "value": 120.0}],
                        "topGroups": [{"group": "A", "value": 120.0}],
                    }
                ],
                "reconciliations": [
                    {
                        "code": "income_check",
                        "leftTotal": 120.0,
                        "rightTotal": 100.0,
                        "difference": 20.0,
                        "passed": False,
                    }
                ],
            },
            "datasets": [
                {
                    "datasetId": "dataset-1",
                    "path": "data/current.csv",
                    "columns": ["income"],
                }
            ],
            "analysisOutputRoot": "analysis/analysis_001",
        },
        decision=AnalysisEvidenceDecision(
            requiresSupplementalEvidence=True,
            reason="需要分项对账",
            missingFacts=("分项构成",),
            codingRequirements=(
                {
                    "datasetId": "dataset-1",
                    "fields": ["income"],
                    "calculation": "计算收入分项并与总量对账",
                    "outputName": "income_components",
                },
            ),
        ),
    )

    facts = workflow._script_task_facts(state)

    assert facts["existingFacts"]["analysisId"] == "analysis_001"
    assert facts["existingFacts"]["metrics"] == [
        {
            "datasetId": "dataset-1",
            "field": "income",
            "aggregation": "sum",
            "unit": "元",
            "formula": "sum(income)",
            "total": 120.0,
        }
    ]
    assert facts["existingFacts"]["reconciliations"][0]["passed"] is False
    assert "periodValues" not in facts["existingFacts"]["metrics"][0]
    assert "topGroups" not in facts["existingFacts"]["metrics"][0]


def test_analysis_script_facts_keep_dataset_identity_nulls_and_period_roles():
    workflow = AnalysisItemWorkflow(
        decide_evidence=AsyncMock(),
        run_code=AsyncMock(),
        summarize=AsyncMock(),
        read_file=AsyncMock(),
        complete=AsyncMock(),
    )
    state = _AnalysisItemState(
        instruction={
            "currentAnalysis": {
                "analysisId": "analysis_002",
                "datasetIds": ["current", "baseline"],
            },
            "deterministicFacts": {
                "analysisId": "analysis_002",
                "metrics": [
                    {
                        "datasetId": "current",
                        "field": "amount",
                        "periodRoles": ["current"],
                        "nullableFields": ["amount"],
                        "total": 10.0,
                    },
                    {
                        "datasetId": "baseline",
                        "field": "amount",
                        "periodRoles": ["yoy"],
                        "nullableFields": ["amount"],
                        "total": None,
                    },
                ],
                "comparisons": [{
                    "currentDatasetId": "current",
                    "baselineDatasetId": "baseline",
                    "currentTotal": 10.0,
                    "baselineTotal": None,
                    "changeRate": None,
                }],
                "reconciliations": [{"name": "total", "passed": False}],
            },
            "datasets": [
                {"datasetId": "current", "path": "data/current.csv", "columns": ["amount"]},
                {"datasetId": "baseline", "path": "data/baseline.csv", "columns": ["amount"]},
            ],
            "analysisOutputRoot": "analysis/analysis_002",
        },
        decision=AnalysisEvidenceDecision(
            requiresSupplementalEvidence=True,
            reason="需要分项对账",
            missingFacts=("同期分项",),
            codingRequirements=(
                {
                    "datasetId": "current",
                    "fields": ["amount"],
                    "calculation": "计算当前期间分项",
                    "outputName": "current_components",
                },
                {
                    "datasetId": "baseline",
                    "fields": ["amount"],
                    "calculation": "计算同期分项",
                    "outputName": "baseline_components",
                },
            ),
        ),
    )

    existing = workflow._script_task_facts(state)["existingFacts"]

    assert [item["datasetId"] for item in existing["metrics"]] == [
        "current", "baseline"
    ]
    assert existing["metrics"][1]["total"] is None
    assert existing["metrics"][0]["periodRoles"] == ["current"]
    assert existing["metrics"][1]["periodRoles"] == ["yoy"]
    assert existing["comparisons"][0]["baselineTotal"] is None
    assert existing["reconciliations"] == [{"name": "total", "passed": False}]


def test_oversized_source_error_reports_size_limit():
    context = SimpleNamespace(max_source_bytes=32)

    with pytest.raises(ReportingError) as caught:
        validate_draft_source(context, "value = 1\n" * 8)

    assert caught.value.code == "report_code_source_invalid"
    assert caught.value.details == {
        "reason": "source_too_large",
        "actualBytes": 80,
        "limitBytes": 32,
    }


def test_long_physical_line_is_preserved_below_total_size_limit():
    context = SimpleNamespace(max_source_bytes=16 * 1024)
    source = "value = '" + ("x" * 9000) + "'\n"

    assert validate_draft_source(context, source) == source.encode("utf-8")


def test_compile_rejects_large_embedded_data_literal_with_workspace_guidance():
    source = "rows = " + repr("id,value\n" + "1,100\n" * 10_000) + "\n"
    with pytest.raises(ReportingError) as caught:
        compile_script_source("analysis/a.py", source, frozenset())

    assert caught.value.code == "report_code_source_invalid"
    assert "Workspace" in caught.value.message
    assert caught.value.details["reason"] == "embedded_data"
    assert caught.value.details["kind"] == "large_literal"


def test_compile_rejects_large_embedded_constant_collection():
    source = "rows = [" + ",".join(repr(f"{index},100") for index in range(10_000)) + "]\n"
    with pytest.raises(ReportingError) as caught:
        compile_script_source("analysis/a.py", source, frozenset())

    assert caught.value.details["reason"] == "embedded_data"
    assert caught.value.details["kind"] == "large_collection"


@pytest.mark.anyio
async def test_write_script_rejects_large_embedded_data_before_workspace_write(
    binding,  # noqa: F811
):
    toolkit = ReportingCodeModeToolkit(binding, AsyncMock(), ReportingLspProcessManager())
    chunks = [repr("1,100\n" * 500) for _ in range(20)]
    source = "rows = (\n" + "\n".join(chunks) + "\n)\n"

    result = await toolkit.write_script(source)

    assert result["ok"] is False
    assert result["details"]["reason"] == "embedded_data"
    assert not await binding.workspace.apath_exists("task-1", "analysis/a.py")


def test_failure_details_are_bounded_and_allowlisted():
    result = _failure("invalid", "invalid", {
        "path": "analysis/a.py", "line": 2, "retryable": False,
        "unsignedPaths": ["secret.csv"] * 1000,
        "forbiddenPathOperations": ["os.getcwd"],
        "traceback": "trace\n" * 5000 + "ValueError: bad value",
        "credentials": {"token": "do-not-disclose"},
    })
    details = result["details"]
    assert details["path"] == "analysis/a.py"
    assert details["line"] == 2
    assert details["retryable"] is False
    assert details["forbiddenPathOperations"] == ["os.getcwd"]
    assert len(details["unsignedPaths"]) <= 20
    assert "ValueError: bad value" in details["traceback"]
    assert "do-not-disclose" not in json.dumps(result)
    assert len(json.dumps(details, ensure_ascii=False).encode()) <= MAX_DIAGNOSTIC_BYTES


def test_runtime_traceback_survives_noisy_output_and_keeps_exception_tail():
    result = _bounded_failure("execution_failed", {
        "stdout": "noise" * 5000, "stderr": "warning" * 5000,
        "traceback": "frame\n" * 5000 + "KeyError: missing_column",
    })
    assert "KeyError: missing_column" in result["details"]["traceback"]
    assert len(json.dumps(result["details"], ensure_ascii=False).encode()) <= MAX_DIAGNOSTIC_BYTES


def test_traceback_tail_survives_json_escape_expansion():
    result = _failure(
        "execution_failed",
        "failed",
        {
            "path": "analysis/a.py",
            "traceback": ("\\\"\n" * 5000) + "RuntimeError: escaped failure",
        },
    )

    details = result["details"]
    assert "RuntimeError: escaped failure" in details["traceback"]
    assert len(json.dumps(details, ensure_ascii=False).encode()) <= MAX_DIAGNOSTIC_BYTES


@pytest.mark.anyio
async def test_run_script_returns_repairable_path_and_syntax_diagnostics(
    binding,  # noqa: F811
    runtime,  # noqa: F811
):
    toolkit = ReportingCodeModeToolkit(binding, runtime, ReportingLspProcessManager())
    await toolkit.write_script("if True\n    pass\n")
    result = await toolkit.run_script()
    assert result["details"]["line"] == 1
    # 路径策略在 write 阶段即拒绝（与 run_script 同一契约），不再等到执行。
    write_result = await toolkit.write_script("open('unsigned.csv')\n")
    assert write_result["ok"] is False
    assert write_result["code"] == "report_python_source_path_invalid"
    assert write_result["details"]["unsignedPaths"] == ["unsigned.csv"]
    # 未保存的草稿不会执行；run_script 仍报告上一份草稿的语法错误。
    result = await toolkit.run_script()
    assert result["details"]["line"] == 1


@pytest.mark.anyio
async def test_run_script_forwards_structured_variable_summary_without_guessing(
    binding,  # noqa: F811
):
    cell = SimpleNamespace(
        status="error",
        stdout="",
        stderr="",
        traceback='File "analysis/a.py", line 1\nTypeError: bad',
        truncated=[],
        variableSummary={"current_income": {"type": "int", "value": "120"}},
    )
    runtime = SimpleNamespace(  # noqa: F811
        execute_script_process=AsyncMock(
            return_value=ScriptProcessResult(cell=cell, exit_code=1)
        )
    )
    toolkit = ReportingCodeModeToolkit(binding, runtime, ReportingLspProcessManager())
    await toolkit.write_script("raise TypeError('bad')\n")

    result = await toolkit.run_script()

    assert result["details"]["variableSummary"] == {
        "current_income": {"type": "int", "value": "120"}
    }
    assert result["details"]["errorType"] == "TypeError"


@pytest.mark.anyio
async def test_run_script_marks_variable_summary_unknown_when_runtime_does_not_expose_locals(
    binding,  # noqa: F811
):
    cell = SimpleNamespace(
        status="error", stdout="", stderr="", traceback="TypeError: bad", truncated=[]
    )
    runtime = SimpleNamespace(  # noqa: F811
        execute_script_process=AsyncMock(
            return_value=ScriptProcessResult(cell=cell, exit_code=1)
        )
    )
    toolkit = ReportingCodeModeToolkit(binding, runtime, ReportingLspProcessManager())
    await toolkit.write_script("raise TypeError('bad')\n")

    result = await toolkit.run_script()

    assert result["details"]["variableSummary"] == {
        "status": "unknown",
        "reason": "runtime_did_not_expose_locals",
    }


@pytest.mark.anyio
async def test_submit_missing_output_retains_its_path(binding, runtime):  # noqa: F811
    toolkit = ReportingCodeModeToolkit(binding, runtime, ReportingLspProcessManager())
    await toolkit.write_script(SOURCE)
    assert (await toolkit.run_script())["ok"] is True
    await binding.workspace.adelete_file("task-1", "analysis/out.json")
    result = await toolkit.submit_script()
    assert result["code"] == "report_code_declared_output_missing"
    assert result["details"]["path"] == "analysis/out.json"


@pytest.mark.anyio
async def test_submit_missing_source_returns_repairable_failure(  # noqa: F811
    binding,  # noqa: F811
    runtime,  # noqa: F811
):
    toolkit = ReportingCodeModeToolkit(binding, runtime, ReportingLspProcessManager())
    await toolkit.write_script(SOURCE)
    assert (await toolkit.run_script())["ok"] is True
    await binding.workspace.adelete_file("task-1", "analysis/a.py")

    result = await toolkit.submit_script()

    assert result["code"] == "report_code_source_missing"
    assert result["details"]["path"] == "analysis/a.py"


@pytest.mark.anyio
async def test_analysis_no_submission_degrades_supplemental_evidence():
    """补充 evidence 是可选增强；no_submission 与 visualization 对必需图表的
    策略一致——先重试到 MAX_ANALYSIS_SCRIPT_GENERATION_ATTEMPTS 耗尽才软降级，
    而不是第一次失败就放弃（后者会与 test_evidence_feedback_to_workflow_
    completion 长期验证的重试行为冲突）。"""
    error = ReportingError("report_code_generation_no_submission", "failed",
                           details={"retryable": False})
    workflow = AnalysisItemWorkflow(
        decide_evidence=AsyncMock(), run_code=AsyncMock(side_effect=error),
        summarize=AsyncMock(), read_file=AsyncMock(), complete=AsyncMock(),
    )
    state = _AnalysisItemState(
        instruction={
            "analysisOutputRoot": "evidence/analysis_001",
            "currentAnalysis": {
                "analysisId": "analysis_001",
                "datasetIds": ["dataset_1"],
            },
            "datasets": [{"datasetId": "dataset_1", "columns": ["trend"]}],
        },
        decision=AnalysisEvidenceDecision(requiresSupplementalEvidence=True,
                                         reason="missing", missingFacts=("trend",),
                                         codingRequirements=({
                                             "datasetId": "dataset_1",
                                             "fields": ["trend"],
                                             "calculation": "计算趋势",
                                             "outputName": "trend",
                                         },)),
    )
    run_context = RunContext(run_id="run", session_id="session")
    for attempt in range(1, MAX_ANALYSIS_SCRIPT_GENERATION_ATTEMPTS):
        result = await workflow._execute_script(state, run_context)
        assert result.content["status"] == "retry"
        assert state.generation_attempts == attempt
        assert state.supplement_abandoned is False
    result = await workflow._execute_script(state, run_context)
    assert result.content["status"] == "degraded"
    assert state.supplement_abandoned is True


@pytest.mark.anyio
async def test_visualization_no_submission_degrades_after_repair_budget():
    error = ReportingError("report_code_generation_no_submission", "failed",
                           details={"retryable": False})
    workflow = VisualizationSectionWorkflow(
        generate_plan=AsyncMock(return_value=_visualization_plan()),
        run_code=AsyncMock(side_effect=error), submit=AsyncMock(),
        degrade=AsyncMock(return_value={"status": "accepted"}),
    )
    result = await workflow.run(
        _visualization_payload(),
        RunContext(run_id="run", session_id="session"),
    )
    assert result.status == "degraded"
    assert workflow.run_code.await_count == 4
    workflow.degrade.assert_awaited_once()

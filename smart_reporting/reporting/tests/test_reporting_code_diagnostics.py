from __future__ import annotations

import json
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
)
from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.tests.test_reporting_interactive_code_agent import (
    SOURCE,
    binding,  # noqa: F401
    runtime,  # noqa: F401
    workspace,  # noqa: F401
)
from smart_reporting.reporting.tests.test_reporting_repair_knowledge import _visualization_plan
from smart_reporting.reporting.workflow.runtime.analysis_item_workflow import (
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

    with pytest.raises(ReportingError) as caught:
        await toolkit.write_script(source)

    assert caught.value.details["reason"] == "embedded_data"
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
    await toolkit.write_script("open('unsigned.csv')\n")
    result = await toolkit.run_script()
    assert result["details"]["unsignedPaths"] == ["unsigned.csv"]


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
async def test_analysis_no_submission_propagates_technical_failure():
    error = ReportingError("report_code_generation_no_submission", "failed",
                           details={"retryable": False})
    workflow = AnalysisItemWorkflow(
        decide_evidence=AsyncMock(), run_code=AsyncMock(side_effect=error),
        summarize=AsyncMock(), read_file=AsyncMock(), complete=AsyncMock(),
    )
    state = _AnalysisItemState(
        instruction={"analysisOutputRoot": "evidence/analysis_001"},
        decision=AnalysisEvidenceDecision(requiresSupplementalEvidence=True,
                                         reason="missing", missingFacts=("trend",)),
    )
    with pytest.raises(ReportingError) as caught:
        await workflow._execute_script(state, RunContext(run_id="run", session_id="session"))
    assert caught.value is error


@pytest.mark.anyio
async def test_visualization_no_submission_propagates_technical_failure():
    error = ReportingError("report_code_generation_no_submission", "failed",
                           details={"retryable": False})
    workflow = VisualizationSectionWorkflow(
        generate_plan=AsyncMock(return_value=_visualization_plan()),
        run_code=AsyncMock(side_effect=error), submit=AsyncMock(),
        degrade=AsyncMock(return_value={"status": "accepted"}),
    )
    with pytest.raises(ReportingError) as caught:
        await workflow.run({"visualizationWorkspace": {"scriptPath": "charts/charts.py"}},
                           RunContext(run_id="run", session_id="session"))
    assert caught.value is error

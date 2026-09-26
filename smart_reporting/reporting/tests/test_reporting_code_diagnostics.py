from __future__ import annotations

import ast
import json
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from agno.run import RunContext

from smart_reporting.reporting.code_agent.context import ReportingCodingTaskBinding
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
from smart_reporting.reporting.tests.test_reporting_code_edit import multi_edit_patch
from smart_reporting.reporting.tests.test_reporting_interactive_code_agent import (
    SOURCE,
    _visualization_task_context,
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
from smart_reporting.workspace import WorkspaceError


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


def test_compile_script_source_allows_safe_os_path_join():
    authorized = frozenset(["/tmp/ws/chart_001.png"])
    compile_script_source(
        "analysis/a.py",
        "import os\np = os.path.join('/tmp/ws', 'chart_001.png')\n",
        authorized,
    )


def test_compile_script_source_allows_safe_os_path_join_with_literal_binding():
    authorized = frozenset(["/tmp/ws/chart_001.png"])
    source = "import os\nout_dir = '/tmp/ws'\np = os.path.join(out_dir, 'chart_001.png')\n"
    compile_script_source("analysis/a.py", source, authorized)


def test_compile_script_source_rejects_os_path_join_to_unsigned_result():
    authorized = frozenset(["/tmp/ws/chart_001.png"])
    source = "import os\np = os.path.join('/tmp/ws', 'unsigned.png')\n"
    with pytest.raises(ReportingError) as caught:
        compile_script_source("analysis/a.py", source, authorized)
    assert caught.value.code == "report_python_source_path_invalid"
    assert "os.path.join" in caught.value.details["forbiddenPathOperations"]


def test_compile_script_source_rejects_os_path_join_with_dynamic_argument():
    authorized = frozenset(["/tmp/ws/chart_001.png"])
    source = "import os\nimport sys\np = os.path.join(sys.argv[1], 'chart_001.png')\n"
    with pytest.raises(ReportingError) as caught:
        compile_script_source("analysis/a.py", source, authorized)
    assert "os.path.join" in caught.value.details["forbiddenPathOperations"]


def test_compile_script_source_still_rejects_other_path_operations():
    authorized = frozenset(["/tmp/ws/chart_001.png"])
    source = "import os\np = os.path.dirname('/tmp/ws/chart_001.png')\n"
    with pytest.raises(ReportingError) as caught:
        compile_script_source("analysis/a.py", source, authorized)
    assert "os.path.dirname" in caught.value.details["forbiddenPathOperations"]


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
async def test_run_script_detects_placeholder_and_opens_rewrite_gate(
    binding,  # noqa: F811
    runtime,  # noqa: F811
):
    # 分析任务保留占位脚本在 run_script 阶段的检测路径；可视化任务已在
    # write_script 阶段用 report_code_script_no_output_write 提前拒绝。
    toolkit = ReportingCodeModeToolkit(binding, runtime, ReportingLspProcessManager())
    placeholder = "import os\nfor root, dirs, files in os.walk('.'):\n    print(root, files)\n"
    write_result = await toolkit.write_script(placeholder)
    assert write_result["ok"] is True

    runtime.execute_script_process = AsyncMock(
        return_value=ScriptProcessResult(
            SimpleNamespace(status="ok", stdout="", stderr="", traceback=None),
            0,
        )
    )
    result = await toolkit.run_script()
    assert result["ok"] is False
    assert result["code"] == "report_code_declared_output_missing"
    assert result["details"].get("isPlaceholderScript") is True
    assert toolkit.rewrite_gate_open is True


@pytest.mark.anyio
async def test_run_script_placeholder_detection_tolerates_indirect_calls(
    binding,  # noqa: F811
    runtime,  # noqa: F811
):
    # 调用目标是下标/调用结果（非 Name/Attribute）时，_qualified_name 返回 None；
    # 占位检测不得因解析不到限定名而抛 AttributeError 吞掉结构化失败回执。
    toolkit = ReportingCodeModeToolkit(binding, runtime, ReportingLspProcessManager())
    source = (
        "import os\n"
        "calls = [print]\n"
        "for root, dirs, files in os.walk('.'):\n"
        "    print(root)\n"
        "calls[0]('x')\n"
    )
    write_result = await toolkit.write_script(source)
    assert write_result["ok"] is True

    runtime.execute_script_process = AsyncMock(
        return_value=ScriptProcessResult(
            SimpleNamespace(status="ok", stdout="", stderr="", traceback=None),
            0,
        )
    )
    result = await toolkit.run_script()
    assert result["ok"] is False
    assert result["code"] == "report_code_declared_output_missing"
    assert result["details"].get("isPlaceholderScript") is True


@pytest.mark.anyio
async def test_run_script_does_not_flag_real_script_as_placeholder(
    runtime,  # noqa: F811
    workspace,  # noqa: F811
):
    vis_binding = ReportingCodingTaskBinding(_visualization_task_context(workspace), workspace)
    toolkit = ReportingCodeModeToolkit(vis_binding, runtime, ReportingLspProcessManager())
    real = "from pathlib import Path\nPath('charts/chart.png').write_bytes(b'image')\n"
    write_result = await toolkit.write_script(real)
    assert write_result["ok"] is True

    runtime.execute_script_process = AsyncMock(
        return_value=ScriptProcessResult(
            SimpleNamespace(status="ok", stdout="", stderr="", traceback=None),
            0,
        )
    )
    result = await toolkit.run_script()
    assert result["ok"] is False
    assert result["code"] == "report_code_declared_output_missing"
    assert result["details"].get("isPlaceholderScript") is not True
    # 脚本 exit 0 但全部声明产物缺失：按零产物快速失败打开重写闸门。
    assert result["details"].get("allDeclaredOutputsMissing") is True
    assert toolkit.rewrite_gate_open is True


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
    assert result["details"]["missingPaths"] == ["analysis/out.json"]
    assert result["details"]["presentPaths"] == []


@pytest.mark.anyio
async def test_declared_outputs_report_all_missing_paths_without_runtime(binding):  # noqa: F811
    binding.context = replace(
        binding.context,
        declared_output_paths=("analysis/a.json", "analysis/b.json"),
        authorized_write_paths=(*binding.context.authorized_write_paths, "analysis/a.json", "analysis/b.json"),
    )
    toolkit = ReportingCodeModeToolkit(binding, AsyncMock(), ReportingLspProcessManager())
    binding.workspace.ahash_file = AsyncMock(side_effect=WorkspaceError("missing"))

    with pytest.raises(ReportingError) as caught:
        await toolkit._declared_output_identities()

    assert caught.value.code == "report_code_declared_output_missing"
    assert caught.value.details == {
        "path": "analysis/a.json",
        "missingPaths": ["analysis/a.json", "analysis/b.json"],
        "presentPaths": [],
        "allDeclaredOutputsMissing": True,
    }


@pytest.mark.anyio
async def test_declared_outputs_partial_missing_keeps_rewrite_gate_closed(binding):  # noqa: F811
    binding.context = replace(
        binding.context,
        declared_output_paths=("analysis/a.json", "analysis/b.json"),
        authorized_write_paths=(*binding.context.authorized_write_paths, "analysis/a.json", "analysis/b.json"),
    )
    toolkit = ReportingCodeModeToolkit(binding, AsyncMock(), ReportingLspProcessManager())

    async def _hash_side_effect(task_id, path):
        if path == "analysis/a.json":
            return {"path": "analysis/a.json", "size": 12, "sha256": "a" * 64}
        raise WorkspaceError("missing")

    binding.workspace.ahash_file = AsyncMock(side_effect=_hash_side_effect)

    with pytest.raises(ReportingError) as caught:
        await toolkit._declared_output_identities()

    assert caught.value.code == "report_code_declared_output_missing"
    assert caught.value.details["missingPaths"] == ["analysis/b.json"]
    assert caught.value.details["presentPaths"] == ["analysis/a.json"]
    assert caught.value.details.get("allDeclaredOutputsMissing") is not True
    assert toolkit.rewrite_gate_open is False


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


# candidate-19 真实形态：navigate 接收 path 参数、split(".") + re.fullmatch 解析、
# 并用解析结果对数据做 cur[key] 下标访问，运行期触发 KeyError。
DYNAMIC_PATH_PARSER_SOURCE = (
    "import re\n"
    "from pathlib import Path\n"
    "\n"
    "def navigate(node, path):\n"
    "    cur = node\n"
    '    for part in path.split("."):\n'
    '        m = re.fullmatch(r"([A-Za-z_][A-Za-z0-9_]*)(?:\\[(\\d+)\\])?", part)\n'
    "        if m is None:\n"
    "            raise KeyError(path)\n"
    "        key = m.group(1)\n"
    "        cur = cur[key]\n"
    "        if m.group(2):\n"
    "            cur = cur[int(m.group(2))]\n"
    "    return cur\n"
    "\n"
    'rows = navigate(facts, "findings[0].rows")\n'
    "Path('charts/chart.png').write_bytes(b'image')\n"
)

_NAVIGATE_BLOCK = DYNAMIC_PATH_PARSER_SOURCE.split("rows = navigate", 1)[0]


def _visualization_toolkit(host_workspace, code_runtime) -> ReportingCodeModeToolkit:
    vis_binding = ReportingCodingTaskBinding(
        _visualization_task_context(host_workspace), host_workspace
    )
    return ReportingCodeModeToolkit(vis_binding, code_runtime, ReportingLspProcessManager())


@pytest.mark.anyio
async def test_write_script_rejects_candidate19_dynamic_path_parser(
    runtime,  # noqa: F811
    workspace,  # noqa: F811
):
    toolkit = _visualization_toolkit(workspace, runtime)
    result = await toolkit.write_script(DYNAMIC_PATH_PARSER_SOURCE)
    assert result["ok"] is False
    assert result["code"] == "report_code_dynamic_path_parser"
    assert result["details"]["functionName"] == "navigate"
    assert result["details"]["parameterName"] == "path"
    assert result["details"]["reason"] == "dynamic_path_parser"
    assert "binding.dataPath" in result["message"]
    assert "不要写通用路径解析器" in result["message"]
    # 拒绝发生在写盘之前，不产生一次无效的写-跑循环。
    assert not await workspace.apath_exists("task-1", "analysis/chart.py")


@pytest.mark.anyio
async def test_write_script_allows_normal_data_processing(
    binding,  # noqa: F811
    runtime,  # noqa: F811
):
    toolkit = ReportingCodeModeToolkit(binding, runtime, ReportingLspProcessManager())
    source = (
        "def to_floats(values):\n"
        "    return [float(v) for v in values if v is not None]\n"
        "\n"
        "result = to_floats(['1', '2'])\n"
        "print(result)\n"
    )
    assert (await toolkit.write_script(source))["ok"] is True


@pytest.mark.anyio
async def test_write_script_requires_all_three_dynamic_path_signals(
    binding,  # noqa: F811
    runtime,  # noqa: F811
):
    toolkit = ReportingCodeModeToolkit(binding, runtime, ReportingLspProcessManager())
    # 只有 path 参数与解析调用、没有解析结果驱动的下标访问；同名 navigate
    # 但参数不叫 path/data_path；文件路径 split("/") 等形态都不得误伤。
    source = (
        "import re\n"
        "\n"
        "def segments(path):\n"
        '    parts = path.split(".")\n'
        '    return [re.fullmatch(r"[a-z]+", part) for part in parts]\n'
        "\n"
        "def navigate(node, selector):\n"
        '    for part in selector.split("."):\n'
        "        node = node[part]\n"
        "    return node\n"
        "\n"
        "def stem(path, index):\n"
        '    name = path.split("/")[-1]\n'
        "    return index[name]\n"
        "\n"
        'print(segments("a.b"), navigate({}, "x"), stem("a/b", {}))\n'
    )
    assert (await toolkit.write_script(source))["ok"] is True


@pytest.mark.anyio
async def test_edit_script_rejects_retained_dynamic_path_parser(
    runtime,  # noqa: F811
    workspace,  # noqa: F811
):
    toolkit = _visualization_toolkit(workspace, runtime)
    source = DYNAMIC_PATH_PARSER_SOURCE
    await workspace.awrite_text("task-1", "analysis/chart.py", source)
    patch = multi_edit_patch(source, [("key = m.group(1)", "key = m.group(1).strip()")])

    result = await toolkit.edit_script(patch)

    assert result["ok"] is False
    assert result["code"] == "report_code_dynamic_path_parser"
    assert result["details"]["functionName"] == "navigate"
    assert result["details"]["parameterName"] == "path"
    # 拒绝是原子的：源码保持原样，执行回执不被无效编辑破坏。
    stored = await workspace.read_limited_regular_file(
        "task-1", "analysis/chart.py", max_bytes=64 * 1024
    )
    assert stored.decode("utf-8") == source


@pytest.mark.anyio
async def test_edit_script_allows_removing_dynamic_path_parser(
    runtime,  # noqa: F811
    workspace,  # noqa: F811
):
    toolkit = _visualization_toolkit(workspace, runtime)
    source = DYNAMIC_PATH_PARSER_SOURCE
    await workspace.awrite_text("task-1", "analysis/chart.py", source)
    patch = multi_edit_patch(
        source,
        [
            (_NAVIGATE_BLOCK, ""),
            (
                'rows = navigate(facts, "findings[0].rows")',
                'rows = facts["findings"][0]["rows"]',
            ),
        ],
    )

    result = await toolkit.edit_script(patch)

    assert result["ok"] is True
    assert result["status"] == "edited"
    stored = await workspace.read_limited_regular_file(
        "task-1", "analysis/chart.py", max_bytes=64 * 1024
    )
    updated = stored.decode("utf-8")
    assert "navigate" not in updated
    assert 'facts["findings"][0]["rows"]' in updated


@pytest.mark.anyio
async def test_write_script_rejects_generic_loader_load_p(
    binding,  # noqa: F811
    runtime,  # noqa: F811
):
    toolkit = ReportingCodeModeToolkit(binding, runtime, ReportingLspProcessManager())
    source = (
        "import json\n"
        "def load(p):\n"
        "    return json.load(open(p))\n"
        "\n"
        "load('analysis/a.py')\n"
    )
    result = await toolkit.write_script(source)
    assert result["ok"] is False
    assert result["code"] == "report_code_generic_data_helper"
    assert result["details"]["reason"] == "generic_loader"
    assert result["details"]["functionName"] == "load"
    assert result["details"]["parameterName"] == "p"


@pytest.mark.anyio
async def test_write_script_rejects_generic_findings_decoder_rows_of(
    binding,  # noqa: F811
    runtime,  # noqa: F811
):
    toolkit = ReportingCodeModeToolkit(binding, runtime, ReportingLspProcessManager())
    source = (
        "def rows_of(src, idx):\n"
        '    return src["findings"][idx]["rows"]\n'
        "\n"
        "print(rows_of)\n"
    )
    result = await toolkit.write_script(source)
    assert result["ok"] is False
    assert result["code"] == "report_code_generic_data_helper"
    assert result["details"]["reason"] == "generic_findings_decoder"
    assert result["details"]["functionName"] == "rows_of"
    assert result["details"]["parameterName"] == "src"


@pytest.mark.anyio
async def test_write_script_rejects_generic_findings_decoder_table_rows(
    binding,  # noqa: F811
    runtime,  # noqa: F811
):
    toolkit = ReportingCodeModeToolkit(binding, runtime, ReportingLspProcessManager())
    source = (
        "def table_rows(data, idx):\n"
        '    rows = data["findings"][idx]["rows"]\n'
        "    return rows\n"
        "\n"
        "print(table_rows)\n"
    )
    result = await toolkit.write_script(source)
    assert result["ok"] is False
    assert result["code"] == "report_code_generic_data_helper"
    assert result["details"]["reason"] == "generic_findings_decoder"
    assert result["details"]["functionName"] == "table_rows"
    assert result["details"]["parameterName"] == "data"


@pytest.mark.anyio
async def test_write_script_allows_chart_function_that_uses_but_not_returns_rows(
    binding,  # noqa: F811
    runtime,  # noqa: F811
):
    toolkit = ReportingCodeModeToolkit(binding, runtime, ReportingLspProcessManager())
    source = (
        "def build_chart_x(data):\n"
        '    rows = data["findings"][0]["rows"]\n'
        '    total = sum(row["value"] for row in rows)\n'
        "    print(total)\n"
        "\n"
        "build_chart_x({})\n"
    )
    assert (await toolkit.write_script(source))["ok"] is True


@pytest.mark.anyio
async def test_write_script_allows_inline_literal_path_load(
    binding,  # noqa: F811
    runtime,  # noqa: F811
):
    toolkit = ReportingCodeModeToolkit(binding, runtime, ReportingLspProcessManager())
    source = (
        "import json\n"
        'data = json.load(open("analysis/a.py"))\n'
        "print(data)\n"
    )
    assert (await toolkit.write_script(source))["ok"] is True


@pytest.mark.anyio
async def test_edit_script_rejects_introduced_generic_helper(
    runtime,  # noqa: F811
    workspace,  # noqa: F811
):
    toolkit = _visualization_toolkit(workspace, runtime)
    source = (
        "import json\n"
        "\n"
        "def build_chart(data):\n"
        '    rows = data["findings"][0]["rows"]\n'
        "    print(rows)\n"
        "\n"
        "build_chart({})\n"
    )
    await workspace.awrite_text("task-1", "analysis/chart.py", source)
    patch = multi_edit_patch(
        source,
        [
            (
                "def build_chart(data):",
                "def build_chart(data):\n    def load(p):\n        return json.load(open(p))",
            ),
        ],
    )

    result = await toolkit.edit_script(patch)

    assert result["ok"] is False
    assert result["code"] == "report_code_generic_data_helper"
    assert result["details"]["reason"] == "generic_loader"
    assert result["details"]["functionName"] == "load"
    assert result["details"]["parameterName"] == "p"
    stored = await workspace.read_limited_regular_file(
        "task-1", "analysis/chart.py", max_bytes=64 * 1024
    )
    assert stored.decode("utf-8") == source


_SIGNED_PATHS = frozenset({"analysis/out.json", "charts/a.png"})


@pytest.mark.parametrize(
    "source",
    [
        'open("./analysis/out.json", "w")',
        'open("analysis//out.json", "w")',
        'from pathlib import Path\nPath("./charts/a.png")',
        'from pathlib import Path\nPath("./charts") / "a.png"',
    ],
    ids=["dot-slash", "double-slash", "pathlib-dot", "pathlib-join-dot"],
)
def test_equivalent_relative_spellings_of_signed_paths_pass_preflight(source):
    from smart_reporting.reporting.code_agent.toolkit import _reject_unauthorized_paths

    _reject_unauthorized_paths(ast.parse(source), "analysis/s.py", _SIGNED_PATHS)


@pytest.mark.parametrize(
    ("source", "unsigned"),
    [
        ('open("../analysis/out.json", "w")', "../analysis/out.json"),
        ('open("/analysis/out.json", "w")', "/analysis/out.json"),
        ('open("./analysis/other.json", "w")', "analysis/other.json"),
    ],
)
def test_non_equivalent_paths_still_rejected(source, unsigned):
    from smart_reporting.reporting.code_agent.toolkit import _reject_unauthorized_paths

    with pytest.raises(ReportingError) as caught:
        _reject_unauthorized_paths(ast.parse(source), "analysis/s.py", _SIGNED_PATHS)
    assert caught.value.details["unsignedPaths"] == [unsigned]


def test_declared_output_write_detected_through_dot_slash():
    from smart_reporting.reporting.code_agent.toolkit import _declared_output_write_paths

    tree = ast.parse('import matplotlib.pyplot as plt\nplt.savefig("./charts/a.png")')
    assert _declared_output_write_paths(tree, frozenset({"charts/a.png"})) == {"charts/a.png"}


def test_every_failure_detail_key_survives_the_allowlist():
    """_failure 按白名单过滤 details；新增字段忘记登记会被静默丢弃，模型永远看不到。"""
    from pathlib import Path

    import smart_reporting.reporting.code_agent.toolkit as toolkit_module

    tree = ast.parse(Path(toolkit_module.__file__).read_text(encoding="utf-8"))
    used: set[str] = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "_failure"
            and len(node.args) >= 3
            and isinstance(node.args[2], ast.Dict)
        ):
            used.update(key.value for key in node.args[2].keys if isinstance(key, ast.Constant))
    used.update({"reason", "patchFormat", "anchor", "hint", "blockIndex", "line"})
    # 字段类型各异：分别以字符串与列表探测，任一形态保留即视为已登记。
    kept = set(_failure("code", "message", {key: "x" for key in used})["details"])
    kept |= set(_failure("code", "message", {key: ["x"] for key in used})["details"])
    assert used - kept == set()


def test_apply_patch_path_mismatch_keeps_format_and_expected_path():
    result = _failure(
        "report_code_script_edit_invalid",
        "path",
        {"reason": "apply_patch_path_mismatch", "patchFormat": "apply_patch",
         "path": "x.py", "expectedPath": "analysis/a.py", "totalLines": 12},
    )

    assert result["details"]["patchFormat"] == "apply_patch"
    assert result["details"]["expectedPath"] == "analysis/a.py"
    assert result["details"]["totalLines"] == 12

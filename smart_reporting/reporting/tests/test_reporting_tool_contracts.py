from __future__ import annotations

import inspect
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from agno.run import RunContext

from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.tools.sections import RuntimeSectionsMixin
from smart_reporting.reporting.tools.toolkit import ReportingToolkit
from smart_reporting.reporting.tools.validation import analysis_patch_parameters
from smart_reporting.task_execution import MAX_TOOL_OUTPUT_READ_BYTES


def _toolkit(*, durable_payload: dict | None = None) -> ReportingToolkit:
    scope = SimpleNamespace(thread_id="thread-1", task=SimpleNamespace(mutation_sequence=7))
    toolkit = object.__new__(ReportingToolkit)
    toolkit.runtime = SimpleNamespace(
        scope=AsyncMock(return_value=scope),
        finish_task=AsyncMock(return_value={"ok": True, "status": "accepted"}),
    )
    toolkit._finish_function = SimpleNamespace(name="finish_task")
    toolkit._require_phase_tool = lambda *_args, **_kwargs: None
    toolkit._active_reporting_task_kind = lambda *_args: "visualization_section"
    toolkit._phase_parameters = lambda *_args: (
        {},
        {
            "sectionCode": "section_001",
            "visualizationWorkspace": {"chartOutputRoot": "analysis/charts/section_001"},
        },
    )
    toolkit._ensure_visualization_script_settled = AsyncMock()
    toolkit._durable_state = AsyncMock(
        return_value=SimpleNamespace(revision=7, payload=durable_payload or {})
    )
    toolkit._apply_durable_command = AsyncMock(return_value=SimpleNamespace(idempotent=False))
    return toolkit


def test_render_report_section_is_bound_to_toolkit_instance() -> None:
    descriptor = inspect.getattr_static(RuntimeSectionsMixin, "render_report_section")

    assert not isinstance(descriptor, staticmethod)


def test_analysis_patch_contract_is_patch_only() -> None:
    schema = analysis_patch_parameters()
    assert set(schema["properties"]) == {"patch"}
    with pytest.raises(Exception):
        from jsonschema import Draft202012Validator

        Draft202012Validator(schema).validate(
            {"patch": "--- /dev/null\n+++ b/analysis/new.py\n@@ -0,0 +1 @@\n+x\n", "expected_sha256": {}}
        )


def test_apply_analysis_patch_signature_hides_expected_sha256() -> None:
    signature = inspect.signature(ReportingToolkit.apply_analysis_patch)
    assert "expected_sha256" not in signature.parameters


def test_signed_fact_page_preserves_structured_read_receipt() -> None:
    toolkit = _toolkit()
    path = "报表/智能分析/run-1/facts/revision-1/analysis_001.json"
    toolkit._active_reporting_phase = lambda *_args: "analysis"
    toolkit._active_reporting_task_kind = lambda *_args: "analysis_item"
    toolkit._phase_parameters = lambda *_args: (
        {},
        {
            "currentAnalysisId": "analysis_001",
            "deterministicFactFiles": {"analysis_001": {"path": path}},
        },
    )
    result = {
        "path": path,
        "offset": 0,
        "nextOffset": MAX_TOOL_OUTPUT_READ_BYTES,
        "totalBytes": 125_429,
        "content": "x" * MAX_TOOL_OUTPUT_READ_BYTES,
        "hasMore": True,
        "sha256": "a" * 64,
    }

    preview_bytes = toolkit._tool_preview_bytes(
        SimpleNamespace(),
        "read_file",
        {"path": path},
        result,
    )
    serialized_bytes = len(
        json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    )

    assert preview_bytes is not None
    assert preview_bytes >= serialized_bytes


def test_section_evidence_page_preserves_structured_read_receipt() -> None:
    toolkit = _toolkit()
    toolkit._active_reporting_phase = lambda *_args: "section"
    toolkit._active_reporting_task_kind = lambda *_args: "section"
    result = {
        "path": "evidence/section.json",
        "offset": 0,
        "nextOffset": MAX_TOOL_OUTPUT_READ_BYTES,
        "totalBytes": 125_429,
        "content": '{"value":"收入"}' * 3_000,
        "hasMore": True,
        "sha256": "a" * 64,
    }

    preview_bytes = toolkit._tool_preview_bytes(
        SimpleNamespace(),
        "read_file",
        {"path": result["path"]},
        result,
    )

    assert toolkit._retain_bounded_tool_result(SimpleNamespace(), "read_file") is True
    assert preview_bytes is not None
    assert preview_bytes >= len(result["content"].encode())


@pytest.mark.anyio
async def test_section_visualization_allows_zero_chart_submission() -> None:
    toolkit = _toolkit()
    result = await toolkit.submit_visualization_charts(
        sectionCode="section_001",
        charts=[],
        run_context=RunContext(run_id="run-1", session_id="session-1"),
    )
    assert result["ok"] is True
    assert result["chartCount"] == 0
    assert result["taskFinished"] is True
    assert toolkit._apply_durable_command.await_args.kwargs["payload"] == {
        "sectionCode": "section_001",
        "charts": [],
        "files": [],
    }


@pytest.mark.anyio
async def test_section_visualization_rejects_cross_section_submission() -> None:
    toolkit = _toolkit()
    result = await toolkit.submit_visualization_charts(
        sectionCode="section_002",
        charts=[],
        run_context=RunContext(run_id="run-1", session_id="session-1"),
    )
    assert result["ok"] is False
    assert result["code"] == "report_visualization_section_invalid"
    assert result["message"] == "sectionCode 与当前章节 Task 契约不匹配。"
    toolkit._apply_durable_command.assert_not_awaited()


@pytest.mark.anyio
async def test_section_visualization_rejects_conflicting_repeat_submission() -> None:
    chart = {
        "chartId": "income",
        "sourcePath": "analysis/charts/section_001/income.png",
        "title": "收入趋势",
        "altText": "收入趋势图",
        "citationIds": ["citation-1"],
        "metricCodes": ["income"],
        "currentPeriod": "2026-01",
        "sourceDatasetId": "dataset-1",
        "aggregationGrain": "month",
        "comparisonPeriod": None,
        "comparisonType": "none",
        "comparability": "strict",
    }
    toolkit = _toolkit(
        durable_payload={"visualizationSections": {"section_001": {"charts": [chart], "files": []}}}
    )
    result = await toolkit.submit_visualization_charts(
        sectionCode="section_001",
        charts=[],
        run_context=RunContext(run_id="run-1", session_id="session-1"),
    )
    assert result["ok"] is False
    assert result["code"] == "report_visualization_section_conflict"
    toolkit._apply_durable_command.assert_not_awaited()


@pytest.mark.anyio
async def test_section_visualization_requires_its_task_kind() -> None:
    toolkit = _toolkit()

    def reject(*_args, **_kwargs) -> None:
        raise ReportingError("report_phase_tool_forbidden", "当前 Task 无权提交图表。")

    toolkit._require_phase_tool = reject
    result = await toolkit.submit_visualization_charts(sectionCode="section_001", charts=[])
    assert result["ok"] is False
    assert result["code"] == "report_phase_tool_forbidden"


def test_visualization_script_forbidden_returns_signed_script_path() -> None:
    error = ReportingError(
        "report_visualization_script_path_forbidden",
        "visualization 只允许执行签发的 Python 脚本。",
        details={"scriptPath": "analysis/charts/section_001/charts.py"},
    )

    result = ReportingToolkit._failure(error, retryable=False)

    assert result["details"] == {"scriptPath": "analysis/charts/section_001/charts.py"}
    assert result["requiredActions"] == [
        "仅将 details.scriptPath 原样作为 run_python_script.script_path；"
        "不要传入解释器、workdir 或 shell 命令。"
    ]


def test_section_heading_failure_preserves_stable_issue_path() -> None:
    error = ReportingError(
        "report_draft_heading_parent_missing",
        "H4 标题必须位于当前章节的 H3 标题之后。",
        details={
            "issues": [
                {
                    "path": "$.blocks[1].markdown",
                    "type": "heading_parent_missing",
                    "message": "H4 标题必须位于当前章节的 H3 标题之后。",
                }
            ]
        },
    )

    result = ReportingToolkit._failure(error)

    assert result["details"] == error.details


@pytest.mark.anyio
async def test_visualization_run_python_script_accepts_signed_script_path() -> None:
    script_path = "analysis/charts/section_001/charts.py"
    identity = {"path": script_path, "size": 12, "sha256": "a" * 64}
    scope = SimpleNamespace(thread_id="thread-1")

    async def invoke(_owner, _tool_name, _arguments, call, _run_context):
        return await call(scope)

    toolkit = object.__new__(ReportingToolkit)
    toolkit.runtime = SimpleNamespace(
        invoke=invoke,
        execute_script=AsyncMock(return_value={"ok": True, "status": "completed", "exitCode": 0}),
        workspace=SimpleNamespace(batch_hash_files=AsyncMock(return_value=[identity])),
    )
    toolkit._active_reporting_phase = lambda _scope: "analysis"
    toolkit._active_reporting_task_kind = lambda _scope: "visualization_section"
    toolkit._phase_parameters = lambda *_args: (
        {},
        {"visualizationWorkspace": {"scriptPath": script_path}},
    )
    toolkit._durable_state = AsyncMock(
        return_value=SimpleNamespace(
            payload={
                "writeIntents": {
                    "intent-1": {
                        "status": "committed",
                        "commitSequence": 1,
                        "artifacts": [identity],
                    }
                }
            }
        )
    )
    toolkit._analysis_python_dependency_rejection = AsyncMock(return_value=None)

    result = await toolkit.run_python_script(
        script_path,
        run_context=RunContext(run_id="run-1", session_id="session-1"),
    )

    assert result == {"ok": True, "status": "completed", "exitCode": 0}
    toolkit._analysis_python_dependency_rejection.assert_awaited_once_with(
        scope=scope, script_path=script_path
    )


@pytest.mark.anyio
async def test_visualization_run_python_script_rejects_unsigned_script_path() -> None:
    signed_script_path = "analysis/charts/section_001/charts.py"
    scope = SimpleNamespace(thread_id="thread-1")

    async def invoke(_owner, _tool_name, _arguments, call, _run_context):
        return await call(scope)

    toolkit = object.__new__(ReportingToolkit)
    toolkit.runtime = SimpleNamespace(
        invoke=invoke,
        execute_script=AsyncMock(),
    )
    toolkit._active_reporting_phase = lambda _scope: "analysis"
    toolkit._active_reporting_task_kind = lambda _scope: "visualization_section"
    toolkit._phase_parameters = lambda *_args: (
        {},
        {"visualizationWorkspace": {"scriptPath": signed_script_path}},
    )

    result = await toolkit.run_python_script(
        "analysis/charts/section_001/other.py",
        run_context=RunContext(run_id="run-1", session_id="session-1"),
    )

    assert result["ok"] is False
    assert result["code"] == "report_visualization_script_path_forbidden"
    assert result["details"] == {"scriptPath": signed_script_path}
    toolkit.runtime.execute_script.assert_not_awaited()


def _analysis_item_runner_toolkit(
    *, script_path: str, identity: dict[str, object], durable_payload: dict[str, object]
) -> ReportingToolkit:
    scope = SimpleNamespace(thread_id="thread-1")

    async def invoke(_owner, _tool_name, _arguments, call, _run_context):
        return await call(scope)

    toolkit = object.__new__(ReportingToolkit)
    toolkit.runtime = SimpleNamespace(
        invoke=invoke,
        execute_script=AsyncMock(return_value={"ok": True, "status": "completed", "exitCode": 0}),
        workspace=SimpleNamespace(batch_hash_files=AsyncMock(return_value=[identity])),
    )
    toolkit._active_reporting_phase = lambda _scope: "analysis"
    toolkit._active_reporting_task_kind = lambda _scope: "analysis_item"
    toolkit._phase_parameters = lambda *_args: (
        {},
        {"taskKind": "analysis_item", "analysisOutputRoot": script_path.rsplit("/", 1)[0]},
    )
    toolkit._durable_state = AsyncMock(return_value=SimpleNamespace(payload=durable_payload))
    toolkit._analysis_python_dependency_rejection = AsyncMock(return_value=None)
    return toolkit


@pytest.mark.anyio
async def test_analysis_item_run_python_script_accepts_signed_committed_script() -> None:
    script_path = "analysis/evidence/analysis_001/attempt-1/supplement.py"
    identity = {"path": script_path, "size": 12, "sha256": "a" * 64}
    toolkit = _analysis_item_runner_toolkit(
        script_path=script_path,
        identity=identity,
        durable_payload={
            "writeIntents": {
                "intent-1": {
                    "status": "committed",
                    "commitSequence": 1,
                    "artifacts": [identity],
                }
            }
        },
    )

    result = await toolkit.run_python_script(script_path)

    assert result["ok"] is True
    toolkit.runtime.execute_script.assert_awaited_once()


@pytest.mark.anyio
async def test_analysis_item_run_python_script_rejects_unsigned_path() -> None:
    script_path = "analysis/evidence/analysis_001/attempt-1/supplement.py"
    identity = {"path": script_path, "size": 12, "sha256": "a" * 64}
    toolkit = _analysis_item_runner_toolkit(
        script_path=script_path,
        identity=identity,
        durable_payload={},
    )

    result = await toolkit.run_python_script("analysis/other.py")

    assert result["ok"] is False
    assert result["code"] == "report_analysis_script_path_forbidden"
    assert result["details"] == {"scriptPath": script_path}
    toolkit.runtime.execute_script.assert_not_awaited()


@pytest.mark.anyio
async def test_analysis_item_run_python_script_rejects_uncommitted_script() -> None:
    script_path = "analysis/evidence/analysis_001/attempt-1/supplement.py"
    identity = {"path": script_path, "size": 12, "sha256": "a" * 64}
    toolkit = _analysis_item_runner_toolkit(
        script_path=script_path,
        identity=identity,
        durable_payload={},
    )

    result = await toolkit.run_python_script(script_path)

    assert result["ok"] is False
    assert result["code"] == "report_analysis_script_identity_changed"
    toolkit.runtime.execute_script.assert_not_awaited()


@pytest.mark.anyio
async def test_visualization_script_settlement_uses_runtime_repository() -> None:
    toolkit = object.__new__(ReportingToolkit)
    repository = SimpleNamespace(
        list_executions=AsyncMock(
            return_value=[
                SimpleNamespace(
                    execution_id="execution-1",
                    internal_run_id="internal-1",
                    kind="terminal",
                    status="running",
                    operation_receipt={"runner": "python", "scriptPath": "analysis/script.py"},
                )
            ]
        )
    )
    toolkit.runtime = SimpleNamespace(repository=repository)
    scope = SimpleNamespace(external_run_id="external-1", internal_run_id="internal-1")

    with pytest.raises(ReportingError) as rejected:
        await toolkit._ensure_visualization_script_settled(scope)

    assert rejected.value.code == "report_visualization_script_running"
    repository.list_executions.assert_awaited_once_with("external-1")


@pytest.mark.anyio
async def test_visualization_script_settlement_ignores_non_runner_terminal_execution() -> None:
    toolkit = object.__new__(ReportingToolkit)
    repository = SimpleNamespace(
        list_executions=AsyncMock(
            return_value=[
                SimpleNamespace(
                    execution_id="execution-1",
                    internal_run_id="internal-1",
                    kind="terminal",
                    status="running",
                    operation_receipt={"command": "echo test"},
                )
            ]
        )
    )
    toolkit.runtime = SimpleNamespace(repository=repository)
    scope = SimpleNamespace(external_run_id="external-1", internal_run_id="internal-1")

    await toolkit._ensure_visualization_script_settled(scope)

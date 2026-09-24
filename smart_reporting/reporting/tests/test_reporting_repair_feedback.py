import hashlib
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from smart_reporting.reporting.code_agent.delivery import _diagnostic_summary
from smart_reporting.reporting.code_agent.lsp_process import ReportingLspProcessManager
from smart_reporting.reporting.code_agent.toolkit import ReportingCodeModeToolkit
from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.tests.test_reporting_code_edit import (
    edit_patch,
    multi_edit_patch,
)
from smart_reporting.reporting.tests.test_reporting_interactive_code_agent import (
    SOURCE,
    ToolkitRuntime,
    _failed_cell,
    binding,  # noqa: F401
    workspace,  # noqa: F401
)
from smart_reporting.workspace import WorkspaceError


@pytest.mark.anyio
@pytest.mark.parametrize("padding", [15, 200])
async def test_repair_scope_covers_function_not_only_error_window(binding, padding):  # noqa: F811
    toolkit = ReportingCodeModeToolkit(binding, ToolkitRuntime(), ReportingLspProcessManager())
    function = (
        "def chart():\n    month = 2025\n"
        + "    # context\n" * padding
        + "    raise ValueError('month')\n"
    )
    source = "unrelated = 1\n\n" + function + "\ndef other():\n    pass\n"
    await toolkit.workspace.awrite_text(toolkit.context.task_id, toolkit.context.script_path, source)
    result = await toolkit._script_repair_details(
        {"stderr": f'  File "analysis/a.py", line {padding + 5}, in chart\nValueError: month'},
        hashlib.sha256(source.encode()).hexdigest(),
    )
    assert result["allowedEditRegion"]["startLine"] == 3
    assert result["allowedEditRegion"]["endLine"] == padding + 5
    assert result["forbiddenEditRegions"][0]["outside"]["allowedStartLine"] == 3
    assert len(result["sourceExcerpt"].encode()) <= 1800
    if padding == 15:
        assert result["sourceExcerpt"] == function
    else:
        assert "raise ValueError" in result["sourceExcerpt"]
        assert result["readRange"] == result["allowedEditRegion"]
        assert "read_script" in result["nextTools"]
    assert "def other" not in result["sourceExcerpt"]
    summary = _diagnostic_summary({"code": "execution_failed", "details": result})["details"]
    assert summary["allowedEditRegion"] == result["allowedEditRegion"]
    assert summary["errorType"] == "ValueError"
    if padding == 200:
        assert summary["readRange"] == result["readRange"]


@pytest.mark.anyio
@pytest.mark.parametrize(
    "stderr, expected_type, expected_line",
    [
        ('  File "analysis/a.py", line 4, in build_chart\nKeyError: missing', "KeyError", 4),
        ('  File "analysis/a.py", line 20, in build_chart\n'
         '  File "analysis/a.py", line 4, in helper\nValueError: missing', "ValueError", 4),
        ("font warning only", "CalledProcessError", 28),
        ('  File "analysis/a.py", line 30, in <module>\n'
         '  File "analysis/a.py", line 28, in main\n'
         '  File "analysis/a.py", line 4, in chart\nValueError: missing', "ValueError", 4),
    ],
)
async def test_repair_uses_one_trace_and_prefers_child_stderr(
    binding, stderr, expected_type, expected_line,  # noqa: F811
):
    runtime = ToolkitRuntime()
    toolkit = ReportingCodeModeToolkit(binding, runtime, ReportingLspProcessManager())
    source = "".join(f"value_{line} = {line}\n" for line in range(1, 31))
    await toolkit.workspace.awrite_text(toolkit.context.task_id, toolkit.context.script_path, source)
    runtime.next_cell = _failed_cell(
        '  File "analysis/a.py", line 28, in wrapper\n'
        'subprocess.CalledProcessError: exit 1'
    )
    runtime.next_cell.stderr = stderr

    result = await toolkit.run_script()

    assert result["details"]["errorType"] == expected_type
    assert result["details"]["errorLine"] == expected_line


@pytest.mark.anyio
async def test_unreadable_edit_does_not_recommend_full_write(binding, monkeypatch):  # noqa: F811
    toolkit = ReportingCodeModeToolkit(binding, ToolkitRuntime(), ReportingLspProcessManager())
    monkeypatch.setattr(toolkit.workspace, "read_limited_regular_file", AsyncMock(side_effect=WorkspaceError("unreadable")))
    result = await toolkit.edit_script(edit_patch(SOURCE, "'{}'", "'[]'"))
    assert result["code"] == "report_code_script_edit_source_unavailable"
    assert result["details"]["nextTools"] == ["read_script"]


@pytest.mark.anyio
@pytest.mark.parametrize("source_state", ["exists", "missing", "unavailable"])
async def test_exploration_error_only_recommends_write_when_source_absent(binding, monkeypatch, source_state):  # noqa: F811
    runtime = SimpleNamespace(execute=AsyncMock(side_effect=ReportingError("report_code_mode_execution_failed", "failed")))
    toolkit = ReportingCodeModeToolkit(binding, runtime, ReportingLspProcessManager())
    if source_state == "exists":
        await toolkit.workspace.awrite_text(toolkit.context.task_id, toolkit.context.script_path, SOURCE)
    elif source_state == "unavailable":
        monkeypatch.setattr(toolkit.workspace, "apath_exists", AsyncMock(side_effect=WorkspaceError("unavailable")))

    result = await toolkit.run("print(1)")

    assert result["code"] == "report_code_mode_execution_failed"
    assert result["details"]["nextTools"] == (
        ["write_script"] if source_state == "missing" else ["read_script", "edit_script", "run_script"]
    )


@pytest.mark.anyio
async def test_edit_failure_anchor_uses_failing_block_search(binding):  # noqa: F811
    toolkit = ReportingCodeModeToolkit(binding, ToolkitRuntime(), ReportingLspProcessManager())
    source = "value = 1\nprint(value)\n"
    await toolkit.workspace.awrite_text(toolkit.context.task_id, toolkit.context.script_path, source)
    patch = multi_edit_patch(
        source,
        [("value = 1", "value = 2"), ("print(value)\nmissing", "print(2)")],
    )
    result = await toolkit.edit_script(patch)
    assert result["code"] == "report_code_script_edit_not_found"
    details = result["details"]
    assert details["blockIndex"] == 2
    # 锚点取自失败块（第二块）的 SEARCH 首行，而不是第一块。
    assert details["errorLine"] == 2
    assert "print(value)" in details["sourceExcerpt"]
    assert details["sourceSha256"] == hashlib.sha256(source.encode()).hexdigest()


@pytest.mark.anyio
async def test_edit_failure_excerpt_shrinks_to_1800_bytes(binding):  # noqa: F811
    toolkit = ReportingCodeModeToolkit(binding, ToolkitRuntime(), ReportingLspProcessManager())
    function = (
        "def chart():\n    month = 2025\n"
        + "    # context\n" * 200
        + "    value = 1\n"
    )
    source = "unrelated = 1\n\n" + function + "\ndef other():\n    pass\n"
    await toolkit.workspace.awrite_text(toolkit.context.task_id, toolkit.context.script_path, source)
    result = await toolkit.edit_script(
        edit_patch(source, "    value = 1\n    missing", "    value = 2")
    )
    assert result["code"] == "report_code_script_edit_not_found"
    details = result["details"]
    assert len(details["sourceExcerpt"].encode("utf-8")) <= 1800
    assert details["allowedEditRegion"]["startLine"] == 3
    assert details["readRange"] == details["allowedEditRegion"]
    assert "read_script" in details["nextTools"]
    assert "def other" not in details["sourceExcerpt"]
    summary = _diagnostic_summary({"code": "edit_not_found", "details": result["details"]})["details"]
    assert len(summary["sourceExcerpt"].encode("utf-8")) <= 1800
    assert summary["readRange"] == details["readRange"]

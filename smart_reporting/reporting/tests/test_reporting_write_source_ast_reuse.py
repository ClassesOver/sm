"""格式化未改变源码时复用本次 AST，不跳过首轮预检或真实文件身份。"""

import hashlib
from dataclasses import replace
from unittest.mock import AsyncMock, Mock

import pytest

from smart_reporting.reporting.code_agent import toolkit as module
from smart_reporting.reporting.code_agent.context import (
    ReportingCodingTaskBinding,
    ReportingCodingTaskContext,
)
from smart_reporting.reporting.code_agent.lsp_process import ReportingLspProcessManager
from smart_reporting.reporting.host_workspace import (
    HostReportingWorkspace,
    ReportingWorkspaceRegistry,
)
from smart_reporting.reporting.workflow.scope import ReportingWorkflowScope

pytestmark = [pytest.mark.anyio, pytest.mark.parametrize("anyio_backend", ["asyncio"])]


@pytest.fixture
def toolkit(tmp_path):
    scope = ReportingWorkflowScope(
        run_id="run-1",
        external_run_id="external-1",
        session_id="session-1",
        caller_thread_id="thread-1",
        user_id="user-1",
        database="database-1",
        company_id="company-1",
        thread_lease_key="lease-1",
        workspace_key="workspace-1",
    )
    workspace = HostReportingWorkspace(
        ReportingWorkspaceRegistry(tmp_path, secret="0" * 32).resolve(scope)
    )
    context = ReportingCodingTaskContext(
        task_id="task-1",
        task_kind="analysis",
        code_mode_session_id="code-task-1",
        workspace_key=workspace.identity.workspace_key,
        workspace_root=workspace.identity.root,
        script_path="analysis/a.py",
        authorized_read_paths=(),
        authorized_write_paths=("analysis/a.py", "analysis/out.json"),
        declared_output_paths=("analysis/out.json",),
        max_source_bytes=128 * 1024,
    )
    return module.ReportingCodeModeToolkit(
        ReportingCodingTaskBinding(context, workspace),
        AsyncMock(),
        ReportingLspProcessManager(),
    )


@pytest.fixture
def checks(monkeypatch):
    spies = {}
    for name in ("parse", "dump"):
        spy = Mock(wraps=getattr(module.ast, name))
        monkeypatch.setattr(module.ast, name, spy)
        spies[name] = spy
    for name in ("_collect_preflight", "_reject_embedded_data"):
        spy = Mock(wraps=getattr(module, name))
        monkeypatch.setattr(module, name, spy)
        spies[name] = spy
    return spies


async def _assert_saved(toolkit, result, source):
    raw = await toolkit.workspace.read_limited_regular_file(
        toolkit.context.task_id,
        toolkit.context.script_path,
        max_bytes=toolkit.context.max_source_bytes,
    )
    assert raw == source.encode()
    assert result["sha256"] == result["sourceSha256"] == hashlib.sha256(raw).hexdigest()
    assert result["size"] == result["sourceBytes"] == len(raw)


async def test_unchanged_format_uses_only_original_preflight_ast(
    toolkit, checks, monkeypatch
):
    source = "value = 1\n"
    formatter = AsyncMock(return_value=source)
    monkeypatch.setattr(module, "format_python_source", formatter)

    result = await toolkit.write_script(source)

    assert result["ok"] is True
    assert result["formatted"] is False
    assert result["savedSource"] is None
    assert result["readyForExecution"] is True
    assert result["warnings"] == []
    assert checks["_collect_preflight"].call_count == 1
    assert (
        checks["parse"].call_count,
        checks["dump"].call_count,
        checks["_reject_embedded_data"].call_count,
    ) == (1, 0, 1)
    formatter.assert_awaited_once_with(source)
    await _assert_saved(toolkit, result, source)


@pytest.mark.parametrize(
    "source,code",
    [
        (
            "from pathlib import Path\nPath('foreign.csv').read_text()\n",
            "report_python_source_path_invalid",
        ),
        ("rows = " + repr("x" * 40000) + "\n", "report_code_source_invalid"),
    ],
)
async def test_original_source_is_really_preflighted_before_formatter(
    toolkit, checks, monkeypatch, source, code
):
    formatter = AsyncMock(return_value=source)
    monkeypatch.setattr(module, "format_python_source", formatter)

    result = await toolkit.write_script(source)

    assert result["ok"] is False
    assert result["code"] == code
    assert checks["_collect_preflight"].call_count == 1
    formatter.assert_not_awaited()
    assert toolkit._rejected_draft.source == source
    assert not await toolkit.workspace.apath_exists(
        toolkit.context.task_id, toolkit.context.script_path
    )


async def test_changed_format_keeps_full_ast_equivalence_validation(
    toolkit, checks, monkeypatch
):
    source = "value=1\n"
    candidate = "value = 1\n"
    monkeypatch.setattr(
        module, "format_python_source", AsyncMock(return_value=candidate)
    )

    result = await toolkit.write_script(source)

    assert result["ok"] is True
    assert result["formatted"] is True
    assert result["savedSource"] == candidate
    assert result["warnings"] == []
    assert checks["_collect_preflight"].call_count == 1
    assert checks["_reject_embedded_data"].call_count == 2
    assert checks["parse"].call_count == 2
    assert checks["dump"].call_count == 2
    await _assert_saved(toolkit, result, candidate)


@pytest.mark.parametrize(
    "candidate,reason",
    [
        ("value = 2\n", "ValueError"),
        ("value =\n", "SyntaxError"),
    ],
)
async def test_invalid_formatter_result_is_rejected_without_changing_original(
    toolkit, checks, monkeypatch, candidate, reason
):
    source = "value = 1\n"
    monkeypatch.setattr(
        module, "format_python_source", AsyncMock(return_value=candidate)
    )

    result = await toolkit.write_script(source)

    assert result["ok"] is True
    assert result["formatted"] is False
    assert result["savedSource"] is None
    assert result["warnings"][0]["code"] == "report_code_formatting_failed"
    assert result["warnings"][0]["reason"] == reason
    assert checks["parse"].call_count == 2
    assert checks["dump"].call_count == (2 if reason == "ValueError" else 0)
    await _assert_saved(toolkit, result, source)


@pytest.mark.parametrize("changed", [False, True])
async def test_output_write_soft_warning_survives_both_format_paths(
    toolkit, monkeypatch, changed
):
    toolkit.binding.context = replace(toolkit.context, task_kind="visualization")
    source = "OUTPUT = 'analysis/out.json'\nprint(OUTPUT)\n"
    candidate = source.replace("'", '"') if changed else source
    monkeypatch.setattr(
        module, "format_python_source", AsyncMock(return_value=candidate)
    )

    result = await toolkit.write_script(source)

    assert result["ok"] is True
    assert result["formatted"] is changed
    assert [warning["code"] for warning in result["warnings"]] == [
        "report_code_script_output_write_unverified"
    ]
    await _assert_saved(toolkit, result, candidate)


@pytest.mark.parametrize("promote_draft", [False, True])
async def test_syntax_error_draft_behavior_is_unchanged(
    toolkit, checks, monkeypatch, promote_draft
):
    source = "if True\n    pass\n"
    formatter = AsyncMock(return_value=source)
    monkeypatch.setattr(module, "format_python_source", formatter)

    result = await toolkit._write_source(source, promote_draft=promote_draft)

    assert checks["parse"].call_count == 1
    assert checks["dump"].call_count == 0
    assert checks["_collect_preflight"].call_count == 0
    formatter.assert_not_awaited()
    if promote_draft:
        assert result["ok"] is False
        assert result["details"]["errorType"] == "SyntaxError"
        assert toolkit._rejected_draft.source == source
        assert not await toolkit.workspace.apath_exists(
            toolkit.context.task_id, toolkit.context.script_path
        )
    else:
        assert result["ok"] is True
        assert result["readyForExecution"] is False
        assert result["formatted"] is False
        assert result["warnings"][0]["reason"] == "syntax_error"
        await _assert_saved(toolkit, result, source)

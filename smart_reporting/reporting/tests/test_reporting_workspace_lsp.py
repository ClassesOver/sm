from __future__ import annotations

from pathlib import Path

import pytest

from smart_reporting.reporting.code_agent.context import (
    ReportingCodingTaskBinding,
    ReportingCodingTaskContext,
)
from smart_reporting.reporting.code_agent.lsp import ReportingWorkspaceLsp
from smart_reporting.reporting.host_workspace import (
    HostReportingWorkspace,
    ReportingWorkspaceRegistry,
)
from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.workflow.scope import ReportingWorkflowScope

pytestmark = pytest.mark.anyio


@pytest.fixture
def binding(tmp_path: Path) -> ReportingCodingTaskBinding:
    scope = ReportingWorkflowScope(
        run_id="run-lsp",
        external_run_id="external-lsp",
        session_id="session-lsp",
        caller_thread_id="thread-lsp",
        user_id="user-lsp",
        database="database-lsp",
        company_id="company-lsp",
        thread_lease_key="lease-lsp",
        workspace_key="workspace-lsp",
    )
    registry = ReportingWorkspaceRegistry(tmp_path, secret="0" * 32)
    identity = registry.resolve(scope)
    workspace = HostReportingWorkspace(identity)
    context = ReportingCodingTaskContext(
        task_id="task-lsp",
        task_kind="analysis",
        code_mode_session_id="code-lsp",
        workspace_key=identity.workspace_key,
        workspace_root=identity.root,
        script_path="analysis/script.py",
        authorized_read_paths=(),
        authorized_write_paths=("analysis/script.py",),
        declared_output_paths=(),
        max_source_bytes=128 * 1024,
    )
    return ReportingCodingTaskBinding(context, workspace)


async def _write_script(binding: ReportingCodingTaskBinding, source: str) -> None:
    await binding.workspace.awrite_text(
        binding.context.task_id,
        binding.context.script_path,
        source,
    )


async def test_diagnostics_reads_current_bound_script_and_reports_syntax_error(
    binding: ReportingCodingTaskBinding,
) -> None:
    await _write_script(binding, "def broken(:\n    pass\n")

    result = await ReportingWorkspaceLsp(binding).diagnostics()

    assert result["ok"] is True
    assert result["path"] == "analysis/script.py"
    assert len(result["sourceSha256"]) == 64
    assert result["diagnostics"] == [
        {
            "code": "syntax-error",
            "severity": "error",
            "line": 0,
            "character": 11,
            "message": "invalid syntax",
        }
    ]


async def test_hover_definition_references_and_symbols_stay_inside_bound_workspace(
    binding: ReportingCodingTaskBinding,
) -> None:
    await _write_script(
        binding,
        "def helper(value: int) -> int:\n"
        "    return value + 1\n"
        "\n"
        "answer = helper(2)\n",
    )
    lsp = ReportingWorkspaceLsp(binding)

    hover = await lsp.hover("analysis/script.py", line=3, character=10)
    definition = await lsp.definition("analysis/script.py", line=3, character=10)
    references = await lsp.references("analysis/script.py", line=3, character=10)
    symbols = await lsp.document_symbols("analysis/script.py")

    assert hover["ok"] is True
    assert hover["found"] is True
    assert "helper(value: int) -> int" in hover["contents"]
    assert definition == {
        "ok": True,
        "locations": [
            {
                "path": "analysis/script.py",
                "line": 0,
                "character": 4,
                "kind": "function",
            }
        ],
    }
    assert references == {
        "ok": True,
        "locations": [
            {
                "path": "analysis/script.py",
                "line": 0,
                "character": 4,
                "kind": "function",
            },
            {
                "path": "analysis/script.py",
                "line": 3,
                "character": 9,
                "kind": "statement",
            },
        ],
    }
    assert symbols == {
        "ok": True,
        "path": "analysis/script.py",
        "symbols": [
            {"name": "helper", "kind": "function", "line": 0, "character": 4},
            {"name": "value", "kind": "param", "line": 0, "character": 11},
            {"name": "answer", "kind": "statement", "line": 3, "character": 0},
        ],
    }


async def test_definition_does_not_expose_paths_outside_workspace(
    binding: ReportingCodingTaskBinding,
) -> None:
    await _write_script(binding, "value = len([])\n")

    result = await ReportingWorkspaceLsp(binding).definition(
        "analysis/script.py", line=0, character=9
    )

    assert result == {"ok": True, "locations": [{"outsideWorkspace": True}]}


async def test_lsp_rejects_paths_outside_the_workspace(binding: ReportingCodingTaskBinding) -> None:
    with pytest.raises(ReportingError, match="report_lsp_invalid_request"):
        await ReportingWorkspaceLsp(binding).document_symbols("../outside.py")

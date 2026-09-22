from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from smart_reporting.reporting.code_agent.context import (
    ReportingCodingTaskBinding,
    ReportingCodingTaskContext,
)
from smart_reporting.reporting.code_agent.lsp import ReportingWorkspaceLsp
from smart_reporting.reporting.code_agent.lsp_process import ReportingLspProcessManager
from smart_reporting.reporting.code_agent.toolkit import ReportingCodeModeToolkit
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

    lsp = ReportingWorkspaceLsp(binding, ReportingLspProcessManager())
    result = await lsp.diagnostics()

    assert result["ok"] is True
    assert result["path"] == "analysis/script.py"
    assert len(result["sourceSha256"]) == 64
    assert result["diagnostics"] == [] or isinstance(result["diagnostics"], list)
    await lsp.manager.aclose()  # type: ignore[union-attr]


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
    lsp = ReportingWorkspaceLsp(binding, ReportingLspProcessManager())
    source_sha256 = hashlib.sha256(
        b"def helper(value: int) -> int:\n"
        b"    return value + 1\n"
        b"\n"
        b"answer = helper(2)\n"
    ).hexdigest()

    hover = await lsp.hover("analysis/script.py", line=3, character=10)
    definition = await lsp.definition("analysis/script.py", line=3, character=10)
    references = await lsp.references("analysis/script.py", line=3, character=10)
    symbols = await lsp.document_symbols("analysis/script.py")

    assert hover["ok"] is True
    assert hover["found"] is True
    assert "helper(value: int) -> int" in hover["contents"]
    assert hover["sourceSha256"] == source_sha256
    assert definition == {
        "ok": True,
        "sourceSha256": source_sha256,
        "locations": [
            {
                "path": "analysis/script.py",
                "line": 0,
                "character": 4,
                "kind": "symbol",
            }
        ],
    }
    assert references == {
        "ok": True,
        "sourceSha256": source_sha256,
        "locations": [
            {
                "path": "analysis/script.py",
                "line": 0,
                "character": 4,
                "kind": "symbol",
            },
            {
                "path": "analysis/script.py",
                "line": 3,
                "character": 9,
                "kind": "symbol",
            },
        ],
    }
    assert symbols == {
        "ok": True,
        "path": "analysis/script.py",
        "sourceSha256": source_sha256,
        "symbols": [
            {"name": "helper", "kind": 12, "line": 0, "character": 4},
            {"name": "answer", "kind": 13, "line": 3, "character": 0},
        ],
    }
    await lsp.manager.aclose()  # type: ignore[union-attr]


async def test_definition_does_not_expose_paths_outside_workspace(
    binding: ReportingCodingTaskBinding,
) -> None:
    await _write_script(binding, "value = len([])\n")

    lsp = ReportingWorkspaceLsp(binding, ReportingLspProcessManager())
    result = await lsp.definition(
        "analysis/script.py", line=0, character=9
    )

    assert result == {
        "ok": True,
        "sourceSha256": hashlib.sha256(b"value = len([])\n").hexdigest(),
        "locations": [{"outsideWorkspace": True}],
    }
    await lsp.manager.aclose()  # type: ignore[union-attr]


async def test_lsp_rejects_paths_outside_the_workspace(binding: ReportingCodingTaskBinding) -> None:
    with pytest.raises(ReportingError, match="report_lsp_invalid_request"):
        await ReportingWorkspaceLsp(binding, ReportingLspProcessManager()).document_symbols("../outside.py")


async def test_lsp_missing_bound_script_is_recoverable_without_starting_process(
    binding: ReportingCodingTaskBinding,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lsp = ReportingWorkspaceLsp(binding, ReportingLspProcessManager())
    started = False

    async def fail_if_started(*_args: object, **_kwargs: object) -> None:
        nonlocal started
        started = True
        raise AssertionError("missing source must not start LSP")

    monkeypatch.setattr(lsp.manager, "diagnostics", fail_if_started)
    result = await lsp.diagnostics()

    assert result == {
        "ok": False,
        "code": "report_lsp_file_missing",
        "message": "绑定脚本尚不存在，请先调用 write_script。",
        "details": {"path": "analysis/script.py", "nextTools": ["write_script"]},
    }
    assert started is False


async def test_lsp_versions_every_snapshot_response_and_rejects_stale_request(
    binding: ReportingCodingTaskBinding,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = "value = 1\n\n"
    await _write_script(binding, source)
    lsp = ReportingWorkspaceLsp(binding, ReportingLspProcessManager())
    source_sha256 = hashlib.sha256(source.encode("utf-8")).hexdigest()

    results = [
        await lsp.diagnostics(expected_source_sha256=source_sha256),
        await lsp.hover("analysis/script.py", line=1, character=0),
        await lsp.definition("analysis/script.py", line=0, character=0),
        await lsp.references("analysis/script.py", line=0, character=0),
        await lsp.document_symbols("analysis/script.py"),
    ]

    assert results[1]["found"] is False
    assert all(result["sourceSha256"] == source_sha256 for result in results)
    manager = lsp.manager
    assert manager is not None
    await manager.aclose()

    class UnavailableManager:
        async def synchronize_document(self, *_args: object) -> int:
            from smart_reporting.reporting.code_agent.lsp_process import ReportingLspProcessError
            raise ReportingLspProcessError("unavailable")

    lsp.manager = UnavailableManager()  # type: ignore[assignment]
    unavailable = await lsp.definition("analysis/script.py", line=0, character=0)
    assert unavailable == {
        "ok": False,
        "code": "report_lsp_unavailable",
        "message": "Python LSP 当前不可用。",
        "sourceSha256": source_sha256,
    }

    stale = await lsp.hover(
        "analysis/script.py",
        line=0,
        character=0,
        expected_source_sha256="0" * 64,
    )
    assert stale == {
        "ok": False,
        "code": "report_lsp_document_version_mismatch",
        "message": "LSP 请求对应的脚本版本已变化，请重新读取后重试。",
        "sourceSha256": source_sha256,
    }


async def test_toolkit_exposes_read_only_lsp_tools_through_its_task_binding(
    binding: ReportingCodingTaskBinding,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, object]] = []

    class RecordingLsp:
        def __init__(self, received_binding: ReportingCodingTaskBinding, _manager: object) -> None:
            assert received_binding is binding

        async def diagnostics(
            self, path: str | None, *, expected_source_sha256: str | None
        ) -> dict[str, str | None]:
            calls.append(("diagnostics", (path, expected_source_sha256)))
            return {"tool": "diagnostics", "path": path}

        async def hover(
            self, path: str, *, line: int, character: int, expected_source_sha256: str | None
        ) -> dict[str, object]:
            calls.append(("hover", (path, line, character, expected_source_sha256)))
            return {"tool": "hover"}

        async def definition(
            self, path: str, *, line: int, character: int, expected_source_sha256: str | None
        ) -> dict[str, object]:
            calls.append(("definition", (path, line, character, expected_source_sha256)))
            return {"tool": "definition"}

        async def references(
            self, path: str, *, line: int, character: int, expected_source_sha256: str | None
        ) -> dict[str, object]:
            calls.append(("references", (path, line, character, expected_source_sha256)))
            return {"tool": "references"}

        async def document_symbols(
            self, path: str, *, expected_source_sha256: str | None
        ) -> dict[str, object]:
            calls.append(("document_symbols", (path, expected_source_sha256)))
            return {"tool": "document_symbols"}

    monkeypatch.setattr(
        "smart_reporting.reporting.code_agent.toolkit.ReportingWorkspaceLsp",
        RecordingLsp,
    )
    toolkit = ReportingCodeModeToolkit(binding, object(), ReportingLspProcessManager())

    assert {
        "lsp_diagnostics",
        "lsp_hover",
        "lsp_definition",
        "lsp_references",
        "lsp_document_symbols",
    }.issubset({function.name for function in toolkit.tool_functions})
    expected_source_sha256 = "a" * 64
    assert await toolkit.lsp_diagnostics(expectedSourceSha256=expected_source_sha256) == {
        "tool": "diagnostics",
        "path": None,
    }
    assert await toolkit.lsp_hover(
        "analysis/script.py", line=1, character=2, expectedSourceSha256=expected_source_sha256
    ) == {"tool": "hover"}
    assert await toolkit.lsp_definition(
        "analysis/script.py", line=1, character=2, expectedSourceSha256=expected_source_sha256
    ) == {
        "tool": "definition"
    }
    assert await toolkit.lsp_references(
        "analysis/script.py", line=1, character=2, expectedSourceSha256=expected_source_sha256
    ) == {
        "tool": "references"
    }
    assert await toolkit.lsp_document_symbols(
        "analysis/script.py", expectedSourceSha256=expected_source_sha256
    ) == {
        "tool": "document_symbols"
    }
    assert calls == [
        ("diagnostics", (None, expected_source_sha256)),
        ("hover", ("analysis/script.py", 1, 2, expected_source_sha256)),
        ("definition", ("analysis/script.py", 1, 2, expected_source_sha256)),
        ("references", ("analysis/script.py", 1, 2, expected_source_sha256)),
        ("document_symbols", ("analysis/script.py", expected_source_sha256)),
    ]
    schemas = {function.name: function.parameters for function in toolkit.tool_functions}
    assert all("expectedSourceSha256" in schemas[name]["properties"] for name in {
        "lsp_diagnostics",
        "lsp_hover",
        "lsp_definition",
        "lsp_references",
        "lsp_document_symbols",
    })

from __future__ import annotations

import hashlib
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from agno.tools import Toolkit

from smart_reporting.reporting.tools.analysis_item import (
    MAX_ANALYSIS_PYTHON_SOURCE_BYTES,
    MAX_VISUALIZATION_SCRIPT_BYTES,
    RuntimeAnalysisMixin,
)
from smart_reporting.reporting.tools.base import ReportingToolkitBase
from smart_reporting.reporting.tools.context import (
    ReportingFileRef,
    ReportingOutputPolicy,
    ReportingToolContext,
)
from smart_reporting.reporting.tools.mock_workspace import (
    MockReportingToolRuntime,
    MockReportingWorkspace,
)
from smart_reporting.reporting.tools.toolkit import ReportingToolkit
from smart_reporting.reporting.tools.workspace_adapter import (
    ReportingWorkspaceAdapter,
    WorkspaceServiceReportingPort,
    WorkspaceServiceReportingRuntime,
)
from smart_reporting.reporting.tools.workspace_port import ReportingWorkspaceError
from smart_reporting.task_execution import abuild_workspace_changes


def test_reporting_toolkit_owns_agno_toolkit_boundary() -> None:
    assert issubclass(ReportingToolkit, Toolkit)
    assert ReportingToolkit.__mro__[-2] is Toolkit


def test_reporting_context_freezes_trusted_file_identity() -> None:
    content = b'{"rows": 1}'
    ref = ReportingFileRef(
        path="inputs/data.json",
        size=len(content),
        sha256=hashlib.sha256(content).hexdigest(),
    )
    context = ReportingToolContext(
        external_run_id="report-run-1",
        thread_id="thread-1",
        attempt_no=1,
        output_policy=ReportingOutputPolicy(roots=("analysis/output",)),
        input_snapshot={"request": {"metrics": ["revenue"]}},
        inputs=(ref,),
    )

    assert context.inputs == (ref,)
    with pytest.raises(TypeError):
        context.input_snapshot["request"]["metrics"] = ()  # type: ignore[index]
    with pytest.raises(AttributeError):
        context.thread_id = "thread-2"  # type: ignore[misc]


@pytest.mark.anyio
async def test_mock_workspace_enforces_readonly_inputs_and_output_root() -> None:
    workspace = MockReportingWorkspace(
        inputs={"inputs/data.json": b"source"},
        output_policy=ReportingOutputPolicy(roots=("analysis/output",)),
    )

    assert await workspace.read_bytes("inputs/data.json") == b"source"
    with pytest.raises(ReportingWorkspaceError, match="只读"):
        await workspace.write_text("inputs/data.json", "changed")
    with pytest.raises(ReportingWorkspaceError, match="输出目录"):
        await workspace.write_text("other/result.json", "{}")

    identity = await workspace.write_text("analysis/output/result.json", "{}")
    assert identity.path == "analysis/output/result.json"
    assert workspace.calls[-1]["operation"] == "write_text"


@pytest.mark.anyio
async def test_mock_workspace_replay_does_not_leak_call_state() -> None:
    first = MockReportingWorkspace(output_policy=ReportingOutputPolicy(roots=("output",)))
    second = MockReportingWorkspace(output_policy=ReportingOutputPolicy(roots=("output",)))

    identity = await first.write_text("output/result.txt", "stable")
    await first.write_text(
        "output/result.txt",
        "stable",
        overwrite=True,
        expected_sha256=identity.sha256,
    )

    assert len(first.calls) == 2
    assert second.calls == []


@pytest.mark.anyio
async def test_mock_workspace_replays_are_deterministic_across_100_cases() -> None:
    snapshots = []
    for _ in range(100):
        runtime = MockReportingToolRuntime(
            input_snapshot={"request": "stable"},
            inputs={"inputs/data.txt": b"source"},
            output_policy=ReportingOutputPolicy(roots=("output",)),
        )
        workspace = runtime.workspace
        source = await workspace.read_text("inputs/data.txt")
        identity = await workspace.write_text("output/result.txt", source)
        snapshots.append((identity, tuple(tuple(sorted(call.items())) for call in runtime.calls)))

    assert all(snapshot == snapshots[0] for snapshot in snapshots)


@pytest.mark.anyio
async def test_mock_workspace_rejects_missing_stale_and_invalid_output_paths() -> None:
    workspace = MockReportingWorkspace(output_policy=ReportingOutputPolicy(roots=("output",)))

    with pytest.raises(ReportingWorkspaceError, match="不存在"):
        await workspace.read_bytes("inputs/missing.txt")
    with pytest.raises(ReportingWorkspaceError, match="路径无效"):
        await workspace.write_text("../escape.txt", "blocked")
    with pytest.raises(ReportingWorkspaceError, match="覆盖目标不存在"):
        await workspace.write_text("output/result.txt", "new", overwrite=True)

    await workspace.write_text("output/result.txt", "first")
    with pytest.raises(ReportingWorkspaceError, match="哈希已变化"):
        await workspace.write_text(
            "output/result.txt",
            "second",
            overwrite=True,
            expected_sha256="0" * 64,
        )


@pytest.mark.anyio
async def test_mock_workspace_rejects_invalid_script_timeout() -> None:
    workspace = MockReportingWorkspace(output_policy=ReportingOutputPolicy(roots=("output",)))

    with pytest.raises(ReportingWorkspaceError, match="超时"):
        await workspace.execute_script("analysis.py", timeout=0)


@pytest.mark.anyio
async def test_production_port_treats_data_as_readonly() -> None:
    content = b"source"
    data_ref = ReportingFileRef(
        path="data/source.csv",
        size=len(content),
        sha256=hashlib.sha256(content).hexdigest(),
    )
    context = ReportingToolContext(
        external_run_id="report-run-1",
        thread_id="thread-1",
        attempt_no=1,
        output_policy=ReportingOutputPolicy(roots=("output",)),
        input_snapshot={},
        data=(data_ref,),
    )
    port = WorkspaceServiceReportingPort(
        SimpleNamespace(),  # type: ignore[arg-type]
        SimpleNamespace(),  # type: ignore[arg-type]
        context,
        SimpleNamespace(),
    )

    with pytest.raises(ReportingWorkspaceError, match="只读"):
        await port.write_text("data/source.csv", "changed")


@pytest.mark.anyio
async def test_production_port_reads_through_async_workspace_api() -> None:
    class AsyncReadService:
        def file_bytes(self, *_args: object) -> tuple[bytes, str]:
            raise AssertionError("异步 Reporting 端口不得调用同步工作区接口")

        async def afile_bytes(self, thread_id: str, path: str) -> tuple[bytes, str]:
            assert (thread_id, path) == ("thread-1", "inputs/source.txt")
            return b"source", "text/plain"

    context = ReportingToolContext(
        external_run_id="report-run-1",
        thread_id="thread-1",
        attempt_no=1,
        output_policy=ReportingOutputPolicy(roots=("output",)),
        input_snapshot={},
    )
    port = WorkspaceServiceReportingPort(
        AsyncReadService(),  # type: ignore[arg-type]
        SimpleNamespace(),  # type: ignore[arg-type]
        context,
        SimpleNamespace(),
    )

    assert await port.read_bytes("inputs/source.txt") == b"source"


@pytest.mark.anyio
async def test_reporting_workspace_adapter_exposes_async_file_read() -> None:
    class AsyncReadService:
        def file_bytes(self, *_args: object) -> tuple[bytes, str]:
            raise AssertionError("异步 Reporting 适配器不得调用同步工作区接口")

        async def afile_bytes(self, thread_id: str, path: str) -> tuple[bytes, str]:
            assert (thread_id, path) == ("thread-1", "inputs/source.txt")
            return b"source", "text/plain"

    adapter = ReportingWorkspaceAdapter(AsyncReadService())  # type: ignore[arg-type]

    assert await adapter.afile_bytes("thread-1", "inputs/source.txt") == (
        b"source",
        "text/plain",
    )


@pytest.mark.anyio
async def test_reporting_workspace_adapter_supports_async_update_patch_reads() -> None:
    class AsyncReadService:
        def read_text(self, *_args: object) -> str:
            raise AssertionError("异步 Reporting 补丁不得调用同步工作区接口")

        async def aread_text(self, thread_id: str, path: str) -> str:
            assert (thread_id, path) == ("thread-1", "analysis/model.py")
            return "value = 1\n"

    adapter = ReportingWorkspaceAdapter(AsyncReadService())  # type: ignore[arg-type]
    patch = """\
--- a/analysis/model.py
+++ b/analysis/model.py
@@ -1 +1 @@
-value = 1
+value = 2
"""

    changes = await abuild_workspace_changes(adapter, "thread-1", patch)  # type: ignore[arg-type]

    assert changes == [
        {
            "operation": "update",
            "path": "analysis/model.py",
            "content": "value = 2\n",
            "expected_sha256": hashlib.sha256(b"value = 1\n").hexdigest(),
        }
    ]


@pytest.mark.anyio
async def test_reporting_runtime_executes_script_with_resolved_scope() -> None:
    scope = SimpleNamespace(thread_id="thread-1")
    kernel = SimpleNamespace(run_python_script=AsyncMock(return_value={"exitCode": 0}))
    runtime = object.__new__(WorkspaceServiceReportingRuntime)
    runtime._kernel = kernel

    result = await runtime.execute_script("analysis/script.py", timeout=30, _scope=scope)

    assert result == {"exitCode": 0}
    kernel.run_python_script.assert_awaited_once_with(
        "analysis/script.py", timeout=30, _scope=scope
    )


@pytest.mark.anyio
async def test_reporting_tool_reads_through_async_workspace_api() -> None:
    class AsyncReadService:
        def file_bytes(self, *_args: object) -> tuple[bytes, str]:
            raise AssertionError("异步 Reporting 工具不得调用同步工作区接口")

        async def afile_bytes(self, thread_id: str, path: str) -> tuple[bytes, str]:
            assert (thread_id, path) == ("thread-1", "inputs/source.txt")
            return b"source", "text/plain"

    class ToolHarness:
        runtime = SimpleNamespace(workspace=AsyncReadService())

        async def _invoke(self, _name, _arguments, call, _run_context):
            return await call(SimpleNamespace(thread_id="thread-1"))

    result = await ReportingToolkitBase.read_file(  # type: ignore[arg-type]
        ToolHarness(), "inputs/source.txt"
    )

    assert result["content"] == "source"


@pytest.mark.anyio
async def test_analysis_dependency_probe_uses_structured_workspace_operation() -> None:
    class Workspace:
        async def probe_python_modules(self, thread_id: str, names: set[str]) -> set[str]:
            assert thread_id == "thread-1"
            assert names == {"numpy", "missing"}
            return {"numpy"}

        async def execute_isolated(self, *_args: object, **_kwargs: object) -> object:
            raise AssertionError("依赖探测不得调用通用命令执行")

    harness = SimpleNamespace(runtime=SimpleNamespace(workspace=Workspace()))

    installed = await RuntimeAnalysisMixin._installed_python_modules(
        harness,  # type: ignore[arg-type]
        thread_id="thread-1",
        module_names={"numpy", "missing"},
    )

    assert installed == {"numpy"}


@pytest.mark.anyio
async def test_production_port_rejects_missing_hash_target() -> None:
    class MissingService:
        async def abatch_hash_files(self, _thread_id: str, paths: list[str]):
            return [{"path": path, "missing": True} for path in paths]

    context = ReportingToolContext(
        external_run_id="report-run-1",
        thread_id="thread-1",
        attempt_no=1,
        output_policy=ReportingOutputPolicy(roots=("output",)),
        input_snapshot={},
    )
    port = WorkspaceServiceReportingPort(
        MissingService(),  # type: ignore[arg-type]
        SimpleNamespace(),  # type: ignore[arg-type]
        context,
        SimpleNamespace(),
    )

    with pytest.raises(ReportingWorkspaceError, match="missing.txt"):
        await port.hash_files(("inputs/missing.txt",))


@pytest.mark.anyio
async def test_analysis_python_source_gate_returns_uniform_shape_error() -> None:
    scope = SimpleNamespace(thread_id="thread-1")
    harness = object.__new__(RuntimeAnalysisMixin)
    harness._phase_parameters = lambda *_args: (
        {},
        {"taskKind": "analysis_item", "analysisOutputRoot": "analysis/evidence/a1"},
    )
    harness._analysis_output_root = lambda contract: contract["analysisOutputRoot"]
    invalid = "if True print('broken')\n"
    with pytest.raises(Exception) as caught:
        await harness._preflight_analysis_python_write(
            scope=scope,
            tool_name="apply_analysis_patch",
            canonical={
                "operations": [{"operation": "create", "path": "analysis/evidence/a1/supplement.py", "content": invalid}]
            },
        )
    error = caught.value
    assert error.code == "report_python_source_shape_invalid"
    assert error.details == {
        "path": "analysis/evidence/a1/supplement.py",
        "size": len(invalid.encode()),
        "lineCount": 1,
        "maxLineLength": len(invalid.rstrip("\n")),
    }

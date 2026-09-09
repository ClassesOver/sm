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
    validate_reporting_python_source,
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
from smart_reporting.reporting.workflow.checkpoint import FileIdentity
from smart_reporting.task_execution import abuild_workspace_changes
from smart_reporting.workspace import WorkspaceService


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


def test_analysis_python_source_gate_returns_stable_metrics() -> None:
    path = "analysis/evidence/a1/supplement.py"
    source = "value = 1\nprint(value)\n"

    metrics = validate_reporting_python_source(
        path=path,
        content=source,
        max_bytes=MAX_ANALYSIS_PYTHON_SOURCE_BYTES,
        visualization=False,
    )

    assert metrics == {
        "path": path,
        "sourceLineCount": 2,
        "sizeBytes": len(source.encode()),
        "sha256": hashlib.sha256(source.encode()).hexdigest(),
    }


@pytest.mark.anyio
async def test_analysis_python_source_gate_requires_multiline_source() -> None:
    scope = SimpleNamespace(thread_id="thread-1")
    harness = object.__new__(RuntimeAnalysisMixin)
    harness._phase_parameters = lambda *_args: (
        {},
        {"taskKind": "analysis_item", "analysisOutputRoot": "analysis/evidence/a1"},
    )
    harness._analysis_output_root = lambda contract: contract["analysisOutputRoot"]
    source = "pass\n"

    with pytest.raises(Exception) as caught:
        await harness._preflight_analysis_python_write(
            scope=scope,
            tool_name="apply_analysis_patch",
            canonical={
                "operations": [
                    {
                        "operation": "create",
                        "path": "analysis/evidence/a1/supplement.py",
                        "content": source,
                    }
                ]
            },
        )

    assert caught.value.code == "report_python_source_shape_invalid"
    assert caught.value.details == {
        "path": "analysis/evidence/a1/supplement.py",
        "size": len(source.encode()),
        "lineCount": 1,
        "maxLineLength": 4,
    }


@pytest.mark.anyio
async def test_analysis_python_source_gate_counts_line_length_as_utf8_bytes() -> None:
    scope = SimpleNamespace(thread_id="thread-1")
    harness = object.__new__(RuntimeAnalysisMixin)
    harness._phase_parameters = lambda *_args: (
        {},
        {"taskKind": "analysis_item", "analysisOutputRoot": "analysis/evidence/a1"},
    )
    harness._analysis_output_root = lambda contract: contract["analysisOutputRoot"]
    source = "#" + "中" * 3000 + "\npass\n"

    with pytest.raises(Exception) as caught:
        await harness._preflight_analysis_python_write(
            scope=scope,
            tool_name="apply_analysis_patch",
            canonical={
                "operations": [
                    {
                        "operation": "create",
                        "path": "analysis/evidence/a1/supplement.py",
                        "content": source,
                    }
                ]
            },
        )

    assert caught.value.code == "report_python_source_shape_invalid"
    assert caught.value.details["maxLineLength"] == len(source.splitlines()[0].encode())


@pytest.mark.anyio
async def test_invalid_python_source_does_not_record_intent_or_mutate_workspace() -> None:
    class Scheduler:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        def write(self):
            return self

    scope = SimpleNamespace(thread_id="thread-1")
    workspace = SimpleNamespace(
        normalize_path=WorkspaceService.normalize_path,
        aapply_changes=AsyncMock(),
    )
    runtime = SimpleNamespace(
        workspace=workspace,
        scope=AsyncMock(return_value=scope),
        bound_external_run_id=lambda _context: "run-1",
        task_scheduler=lambda _run_id: Scheduler(),
        patch=AsyncMock(),
    )
    harness = object.__new__(RuntimeAnalysisMixin)
    harness.runtime = runtime
    harness._phase_parameters = lambda *_args: (
        {},
        {"taskKind": "analysis_item", "analysisOutputRoot": "analysis/evidence/a1"},
    )
    harness._analysis_output_root = lambda contract: contract["analysisOutputRoot"]
    harness._require_phase_tool = lambda *_args, **_kwargs: None
    harness._require_analysis_task_output_paths = lambda *_args: None
    harness._durable_state = AsyncMock()
    harness._apply_durable = AsyncMock()
    harness._failure = ReportingToolkit._failure
    patch = "--- /dev/null\n+++ b/analysis/evidence/a1/supplement.py\n@@ -0,0 +1 @@\n+pass\n"

    result = await harness.apply_analysis_patch(patch)

    assert result["code"] == "report_python_source_shape_invalid"
    assert result["details"] == {
        "path": "analysis/evidence/a1/supplement.py",
        "size": 5,
        "lineCount": 1,
        "maxLineLength": 4,
    }
    runtime.patch.assert_not_awaited()
    workspace.aapply_changes.assert_not_awaited()
    harness._apply_durable.assert_not_awaited()


@pytest.mark.anyio
@pytest.mark.parametrize(
    "patch",
    [
        (
            "diff --git a/analysis/evidence/a1/supplement.py b/analysis/evidence/a1/supplement.py\n"
            "new file mode 100644\n"
            "--- /dev/null\n+++ b/analysis/evidence/a1/supplement.py\n@@ -0,0 +1,2 @@\n"
            "+value = 1\n+print(value)\n"
            "diff --git a/analysis/evidence/a1/extra.txt b/analysis/evidence/a1/extra.txt\n"
            "new file mode 100644\n"
            "--- /dev/null\n+++ b/analysis/evidence/a1/extra.txt\n@@ -0,0 +1 @@\n"
            "+extra\n"
        ),
        "--- /dev/null\n+++ b/analysis/evidence/a1/extra.txt\n@@ -0,0 +1 @@\n+extra\n",
        (
            "--- a/analysis/evidence/a1/supplement.py\n+++ /dev/null\n@@ -1,2 +0,0 @@\n"
            "-value = 1\n-print(value)\n"
        ),
    ],
)
async def test_analysis_patch_rejects_non_single_signed_script_before_intent_or_mutation(
    patch: str,
) -> None:
    class Scheduler:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        def write(self):
            return self

    scope = SimpleNamespace(thread_id="thread-1")
    runtime = SimpleNamespace(
        workspace=SimpleNamespace(
            normalize_path=WorkspaceService.normalize_path,
            aread_text=AsyncMock(return_value="value = 1\nprint(value)\n"),
        ),
        scope=AsyncMock(return_value=scope),
        bound_external_run_id=lambda _context: "run-1",
        task_scheduler=lambda _run_id: Scheduler(),
        patch=AsyncMock(),
    )
    harness = object.__new__(RuntimeAnalysisMixin)
    harness.runtime = runtime
    harness._phase_parameters = lambda *_args: (
        {},
        {"taskKind": "analysis_item", "analysisOutputRoot": "analysis/evidence/a1"},
    )
    harness._analysis_output_root = lambda contract: contract["analysisOutputRoot"]
    harness._require_phase_tool = lambda *_args, **_kwargs: None
    harness._require_analysis_task_output_paths = lambda *_args, **_kwargs: None
    harness._durable_state = AsyncMock(return_value=SimpleNamespace(payload={}))
    harness._apply_durable = AsyncMock()
    harness._failure = ReportingToolkit._failure

    result = await harness.apply_analysis_patch(patch)

    assert result["ok"] is False
    assert result["code"] == "report_python_source_shape_invalid"
    runtime.patch.assert_not_awaited()
    harness._apply_durable.assert_not_awaited()


@pytest.mark.anyio
@pytest.mark.parametrize("operation", ["create", "update"])
async def test_signed_script_loader_recovers_pending_post_mutation_identity(
    operation: str,
) -> None:
    path = "analysis/evidence/a1/supplement.py"
    source = "value = 2\nprint(value)\n"
    identity = {
        "path": path,
        "size": len(source.encode()),
        "sha256": hashlib.sha256(source.encode()).hexdigest(),
    }
    change = {"operation": operation, "path": path, "content": source}
    if operation == "update":
        change["expected_sha256"] = hashlib.sha256(b"value = 1\nprint(value)\n").hexdigest()
    intent = {
        "intentId": "a" * 64,
        "status": "pending",
        "toolName": "apply_analysis_patch",
        "arguments": {"patch": "diff", "operations": [change]},
        "affectedPaths": [path],
        "expectedStates": {path: "present"},
    }
    scope = SimpleNamespace(thread_id="thread-1")
    harness = object.__new__(RuntimeAnalysisMixin)
    harness.runtime = SimpleNamespace(
        scope=AsyncMock(return_value=scope),
        workspace=SimpleNamespace(batch_hash_files=AsyncMock(return_value=[identity])),
    )
    harness._durable_state = AsyncMock(
        return_value=SimpleNamespace(payload={"writeIntents": {"a" * 64: intent}})
    )
    harness._apply_durable = AsyncMock()
    harness._phase_parameters = lambda *_args: (
        {},
        {"taskKind": "analysis_item", "analysisOutputRoot": "analysis/evidence/a1"},
    )
    harness._analysis_output_root = lambda contract: contract["analysisOutputRoot"]

    recovered = await harness.recover_signed_analysis_script(path, None)

    assert recovered == FileIdentity.model_validate(identity)
    harness._apply_durable.assert_awaited_once_with(
        scope,
        name="commit_write_intent",
        payload={"intentId": "a" * 64, "artifacts": [identity]},
        command_id=f"write-commit:{'a' * 64}",
    )


@pytest.mark.anyio
@pytest.mark.parametrize("operation", ["create", "update"])
async def test_signed_script_loader_leaves_pending_pre_mutation_for_normal_flow(
    operation: str,
) -> None:
    path = "analysis/evidence/a1/supplement.py"
    previous = "value = 1\nprint(value)\n"
    source = "value = 2\nprint(value)\n"
    change = {"operation": operation, "path": path, "content": source}
    if operation == "update":
        change["expected_sha256"] = hashlib.sha256(previous.encode()).hexdigest()
        current = {
            "path": path,
            "size": len(previous.encode()),
            "sha256": hashlib.sha256(previous.encode()).hexdigest(),
        }
    else:
        current = {"path": path, "missing": True}
    intent = {
        "intentId": "b" * 64,
        "status": "pending",
        "toolName": "apply_analysis_patch",
        "arguments": {"patch": "diff", "operations": [change]},
        "affectedPaths": [path],
        "expectedStates": {path: "present"},
    }
    scope = SimpleNamespace(thread_id="thread-1")
    harness = object.__new__(RuntimeAnalysisMixin)
    harness.runtime = SimpleNamespace(
        scope=AsyncMock(return_value=scope),
        workspace=SimpleNamespace(batch_hash_files=AsyncMock(return_value=[current])),
    )
    harness._durable_state = AsyncMock(
        return_value=SimpleNamespace(payload={"writeIntents": {"b" * 64: intent}})
    )
    harness._apply_durable = AsyncMock()
    harness._phase_parameters = lambda *_args: (
        {},
        {"taskKind": "analysis_item", "analysisOutputRoot": "analysis/evidence/a1"},
    )
    harness._analysis_output_root = lambda contract: contract["analysisOutputRoot"]

    recovered = await harness.recover_signed_analysis_script(path, None)

    assert recovered is None
    harness._apply_durable.assert_not_awaited()


@pytest.mark.anyio
async def test_signed_script_loader_rejects_current_identity_matching_older_commit() -> None:
    path = "analysis/evidence/a1/supplement.py"
    older_identity = {"path": path, "size": 1, "sha256": "a" * 64}
    latest_identity = {"path": path, "size": 2, "sha256": "b" * 64}

    def committed_intent(intent_id: str, identity: dict[str, object]) -> dict[str, object]:
        return {
            "intentId": intent_id,
            "status": "committed",
            "toolName": "apply_analysis_patch",
            "arguments": {
                "patch": "diff",
                "operations": [
                    {"operation": "create", "path": path, "content": "value = 1\n"}
                ],
            },
            "affectedPaths": [path],
            "expectedStates": {path: "present"},
            "artifacts": [identity],
        }

    scope = SimpleNamespace(thread_id="thread-1")
    harness = object.__new__(RuntimeAnalysisMixin)
    harness.runtime = SimpleNamespace(
        scope=AsyncMock(return_value=scope),
        workspace=SimpleNamespace(
            batch_hash_files=AsyncMock(return_value=[older_identity])
        ),
    )
    harness._durable_state = AsyncMock(
        return_value=SimpleNamespace(
            payload={
                "writeIntents": {
                    "a" * 64: committed_intent("a" * 64, older_identity),
                    "b" * 64: committed_intent("b" * 64, latest_identity),
                }
            }
        )
    )
    harness._phase_parameters = lambda *_args: (
        {},
        {"taskKind": "analysis_item", "analysisOutputRoot": "analysis/evidence/a1"},
    )
    harness._analysis_output_root = lambda contract: contract["analysisOutputRoot"]

    with pytest.raises(Exception) as caught:
        await harness.recover_signed_analysis_script(path, None)

    assert caught.value.code == "report_phase_artifact_changed"


@pytest.mark.anyio
async def test_signed_script_loader_rejects_missing_latest_committed_artifact() -> None:
    path = "analysis/evidence/a1/supplement.py"
    intent_id = "b" * 64
    intent = {
        "intentId": intent_id,
        "status": "committed",
        "toolName": "apply_analysis_patch",
        "arguments": {
            "patch": "diff",
            "operations": [
                {"operation": "create", "path": path, "content": "value = 1\n"}
            ],
        },
        "affectedPaths": [path],
        "expectedStates": {path: "present"},
        "artifacts": [{"path": path, "size": 10, "sha256": "b" * 64}],
    }
    scope = SimpleNamespace(thread_id="thread-1")
    harness = object.__new__(RuntimeAnalysisMixin)
    harness.runtime = SimpleNamespace(
        scope=AsyncMock(return_value=scope),
        workspace=SimpleNamespace(
            batch_hash_files=AsyncMock(return_value=[{"path": path, "missing": True}])
        ),
    )
    harness._durable_state = AsyncMock(
        return_value=SimpleNamespace(payload={"writeIntents": {intent_id: intent}})
    )
    harness._phase_parameters = lambda *_args: (
        {},
        {"taskKind": "analysis_item", "analysisOutputRoot": "analysis/evidence/a1"},
    )
    harness._analysis_output_root = lambda contract: contract["analysisOutputRoot"]

    with pytest.raises(Exception) as caught:
        await harness.recover_signed_analysis_script(path, None)

    assert caught.value.code == "report_phase_artifact_changed"


@pytest.mark.anyio
async def test_analysis_patch_recovers_pending_update_before_rebuilding_old_hunk(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Scheduler:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        def write(self):
            return self

    path = "analysis/evidence/a1/supplement.py"
    previous = "value = 1\nprint(value)\n"
    source = "value = 2\nprint(value)\n"
    patch = (
        f"--- a/{path}\n+++ b/{path}\n@@ -1,2 +1,2 @@\n"
        "-value = 1\n+value = 2\n print(value)\n"
    )
    identity = {
        "path": path,
        "size": len(source.encode()),
        "sha256": hashlib.sha256(source.encode()).hexdigest(),
    }
    intent_id = "a" * 64
    intent = {
        "intentId": intent_id,
        "status": "pending",
        "toolName": "apply_analysis_patch",
        "arguments": {
            "patch": patch,
            "operations": [
                {
                    "operation": "update",
                    "path": path,
                    "content": source,
                    "expected_sha256": hashlib.sha256(previous.encode()).hexdigest(),
                }
            ],
        },
        "affectedPaths": [path],
        "expectedStates": {path: "present"},
    }
    scope = SimpleNamespace(thread_id="thread-1")
    runtime = SimpleNamespace(
        workspace=SimpleNamespace(batch_hash_files=AsyncMock(return_value=[identity])),
        scope=AsyncMock(return_value=scope),
        bound_external_run_id=lambda _context: "run-1",
        task_scheduler=lambda _run_id: Scheduler(),
        patch=AsyncMock(),
    )
    harness = object.__new__(RuntimeAnalysisMixin)
    harness.runtime = runtime
    harness._phase_parameters = lambda *_args: (
        {},
        {"taskKind": "analysis_item", "analysisOutputRoot": "analysis/evidence/a1"},
    )
    harness._analysis_output_root = lambda contract: contract["analysisOutputRoot"]
    harness._require_phase_tool = lambda *_args, **_kwargs: None
    harness._durable_state = AsyncMock(
        return_value=SimpleNamespace(payload={"writeIntents": {intent_id: intent}})
    )
    harness._apply_durable = AsyncMock()
    harness._failure = ReportingToolkit._failure
    rebuild = AsyncMock(side_effect=AssertionError("旧 hunk 不应在恢复前重建"))
    monkeypatch.setattr(
        "smart_reporting.reporting.tools.analysis_item.abuild_workspace_changes", rebuild
    )

    result = await harness.apply_analysis_patch(patch)

    assert result["ok"] is True
    assert result["recovered"] is True
    rebuild.assert_not_awaited()
    runtime.patch.assert_not_awaited()
    harness._apply_durable.assert_awaited_once_with(
        scope,
        name="commit_write_intent",
        payload={"intentId": intent_id, "artifacts": [identity]},
        command_id=f"write-commit:{intent_id}",
    )


@pytest.mark.anyio
async def test_analysis_patch_rejects_create_for_existing_script_before_intent_or_mutation() -> None:
    class Scheduler:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        def write(self):
            return self

    path = "analysis/evidence/a1/supplement.py"
    scope = SimpleNamespace(thread_id="thread-1")
    workspace = SimpleNamespace(
        normalize_path=WorkspaceService.normalize_path,
        batch_hash_files=AsyncMock(
            return_value=[{"path": path, "size": 10, "sha256": "a" * 64}]
        ),
    )
    runtime = SimpleNamespace(
        workspace=workspace,
        scope=AsyncMock(return_value=scope),
        bound_external_run_id=lambda _context: "run-1",
        task_scheduler=lambda _run_id: Scheduler(),
        patch=AsyncMock(),
    )
    harness = object.__new__(RuntimeAnalysisMixin)
    harness.runtime = runtime
    harness._phase_parameters = lambda *_args: (
        {},
        {"taskKind": "analysis_item", "analysisOutputRoot": "analysis/evidence/a1"},
    )
    harness._analysis_output_root = lambda contract: contract["analysisOutputRoot"]
    harness._require_phase_tool = lambda *_args, **_kwargs: None
    harness._durable_state = AsyncMock(return_value=SimpleNamespace(payload={}))
    harness._apply_durable = AsyncMock()
    harness._failure = ReportingToolkit._failure
    patch = (
        f"--- /dev/null\n+++ b/{path}\n@@ -0,0 +1,2 @@\n"
        "+value = 1\n+print(value)\n"
    )

    result = await harness.apply_analysis_patch(patch)

    assert result["ok"] is False
    assert result["code"] == "report_analysis_write_path_conflict"
    runtime.patch.assert_not_awaited()
    harness._apply_durable.assert_not_awaited()


@pytest.mark.anyio
async def test_analysis_patch_passes_intent_operations_to_kernel_unchanged() -> None:
    class Scheduler:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        def write(self):
            return self

    path = "analysis/evidence/a1/supplement.py"
    source = "value = 1\nprint(value)\n"
    identity = {"path": path, "size": len(source.encode()), "sha256": "a" * 64}
    scope = SimpleNamespace(thread_id="thread-1")
    workspace = SimpleNamespace(
        normalize_path=WorkspaceService.normalize_path,
        batch_hash_files=AsyncMock(
            side_effect=[[{"path": path, "missing": True}], [identity]]
        ),
    )
    runtime = SimpleNamespace(
        workspace=workspace,
        scope=AsyncMock(return_value=scope),
        bound_external_run_id=lambda _context: "run-1",
        task_scheduler=lambda _run_id: Scheduler(),
        patch=AsyncMock(return_value={"ok": True}),
    )
    harness = object.__new__(RuntimeAnalysisMixin)
    harness.runtime = runtime
    harness._phase_parameters = lambda *_args: (
        {},
        {"taskKind": "analysis_item", "analysisOutputRoot": "analysis/evidence/a1"},
    )
    harness._analysis_output_root = lambda contract: contract["analysisOutputRoot"]
    harness._require_phase_tool = lambda *_args, **_kwargs: None
    harness._require_analysis_task_output_paths = lambda *_args: None
    harness._durable_state = AsyncMock(return_value=SimpleNamespace(payload={}))
    harness._apply_durable = AsyncMock()
    harness._failure = ReportingToolkit._failure
    patch = (
        "--- /dev/null\n+++ b/analysis/evidence/a1/supplement.py\n@@ -0,0 +1,2 @@\n"
        "+value = 1\n+print(value)\n"
    )

    result = await harness.apply_analysis_patch(patch)

    assert result["ok"] is True
    intent_operations = harness._apply_durable.await_args_list[0].kwargs["payload"]["intent"][
        "arguments"
    ]["operations"]
    assert runtime.patch.await_args.kwargs["_changes"] == intent_operations


def _python_source_of_size(size: int, *, prefix: str = "value = 1\n") -> str:
    source = prefix
    remaining = size - len(source.encode())
    while remaining:
        line_size = min(8 * 1024, remaining)
        source += "#" * (line_size - 1) + "\n"
        remaining -= line_size
    return source


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("task_kind", "path", "limit"),
    [
        ("analysis_item", "analysis/evidence/a1/supplement.py", MAX_ANALYSIS_PYTHON_SOURCE_BYTES),
        ("visualization_section", "analysis/charts/s1/charts.py", MAX_VISUALIZATION_SCRIPT_BYTES),
    ],
)
async def test_analysis_python_source_gate_enforces_signed_source_size_boundary(
    task_kind: str, path: str, limit: int
) -> None:
    scope = SimpleNamespace(thread_id="thread-1")
    contract = {"taskKind": task_kind, "analysisOutputRoot": "analysis/evidence/a1"}
    if task_kind == "visualization_section":
        contract["visualizationWorkspace"] = {"scriptPath": path}
    harness = object.__new__(RuntimeAnalysisMixin)
    harness._phase_parameters = lambda *_args: ({}, contract)
    harness._analysis_output_root = lambda value: value["analysisOutputRoot"]
    prefix = "value = 1\n"
    if task_kind == "visualization_section":
        prefix = (
            'import matplotlib\nmatplotlib.use("Agg")\n'
            'import matplotlib.pyplot as plt\nplt.savefig("analysis/charts/s1/chart.png")\n'
        )
    accepted = _python_source_of_size(limit, prefix=prefix)

    await harness._preflight_analysis_python_write(
        scope=scope,
        tool_name="apply_analysis_patch",
        canonical={"operations": [{"operation": "create", "path": path, "content": accepted}]},
    )

    rejected = accepted + "\n"
    with pytest.raises(Exception) as caught:
        await harness._preflight_analysis_python_write(
            scope=scope,
            tool_name="apply_analysis_patch",
            canonical={"operations": [{"operation": "create", "path": path, "content": rejected}]},
        )
    assert caught.value.code == "report_python_source_shape_invalid"
    assert caught.value.details["size"] == limit + 1


@pytest.mark.anyio
@pytest.mark.parametrize(
    "source",
    [
        "import plotly.express as px\npx.bar(x=[1], y=[2])\n",
        (
            "import matplotlib\n"
            "import matplotlib.pyplot as plt\n"
            "matplotlib.use('Agg')\n"
            "plt.savefig('analysis/charts/s1/chart.png')\n"
        ),
        (
            "import matplotlib\n"
            "matplotlib.use('Agg')\n"
            "import matplotlib.pyplot as plt\n"
            "figure.write_image('analysis/charts/s1/chart.png')\n"
        ),
        (
            "import matplotlib\n"
            "matplotlib.use('Agg')\n"
            "import matplotlib.pyplot as plt\n"
            "print(__file__)\n"
            "plt.savefig('analysis/charts/s1/chart.png')\n"
        ),
    ],
)
async def test_visualization_python_source_gate_enforces_rendering_policy(source: str) -> None:
    path = "analysis/charts/s1/charts.py"
    scope = SimpleNamespace(thread_id="thread-1")
    harness = object.__new__(RuntimeAnalysisMixin)
    harness._phase_parameters = lambda *_args: (
        {},
        {
            "taskKind": "visualization_section",
            "visualizationWorkspace": {"scriptPath": path},
        },
    )

    with pytest.raises(Exception) as caught:
        await harness._preflight_analysis_python_write(
            scope=scope,
            tool_name="apply_analysis_patch",
            canonical={
                "operations": [{"operation": "create", "path": path, "content": source}]
            },
        )

    assert caught.value.code == "report_python_source_shape_invalid"


@pytest.mark.anyio
@pytest.mark.parametrize(
    "path,source",
    [
        ("analysis/evidence/a1/supplement.py", "value = 1\r\nprint(value)\r\n"),
        ("analysis/evidence/a1/supplement.py", "value = 1\nprint(value)"),
        ("analysis/evidence/a1/other.py", "value = 1\nprint(value)\n"),
        (
            "analysis/evidence/a1/supplement.py",
            "value = (\n    \"" + "a" * 5000 + "\"\n    \"" + "b" * 5000 + "\"\n)\nprint(value)\n",
        ),
        (
            "analysis/evidence/a1/supplement.py",
            "values = [\n" + "".join("    1,\n" for _ in range(4097)) + "]\nprint(len(values))\n",
        ),
        ("analysis/evidence/a1/supplement.py", "#" + "a" * 262139 + "\npass\n"),
    ],
)
async def test_analysis_python_source_gate_rejects_invalid_shape(
    path: str, source: str
) -> None:
    scope = SimpleNamespace(thread_id="thread-1")
    harness = object.__new__(RuntimeAnalysisMixin)
    harness._phase_parameters = lambda *_args: (
        {},
        {"taskKind": "analysis_item", "analysisOutputRoot": "analysis/evidence/a1"},
    )
    harness._analysis_output_root = lambda contract: contract["analysisOutputRoot"]

    with pytest.raises(Exception) as caught:
        await harness._preflight_analysis_python_write(
            scope=scope,
            tool_name="apply_analysis_patch",
            canonical={"operations": [{"operation": "create", "path": path, "content": source}]},
        )

    assert caught.value.code == "report_python_source_shape_invalid"
    assert caught.value.details == {
        "path": path,
        "size": len(source.encode()),
        "lineCount": len(source.splitlines()),
        "maxLineLength": max((len(line.encode()) for line in source.splitlines()), default=0),
    }


@pytest.mark.anyio
async def test_analysis_python_source_gate_enforces_eight_kib_line_boundary() -> None:
    scope = SimpleNamespace(thread_id="thread-1")
    harness = object.__new__(RuntimeAnalysisMixin)
    harness._phase_parameters = lambda *_args: (
        {},
        {"taskKind": "analysis_item", "analysisOutputRoot": "analysis/evidence/a1"},
    )
    harness._analysis_output_root = lambda contract: contract["analysisOutputRoot"]
    accepted = "#" + "a" * (8 * 1024 - 1) + "\npass\n"

    await harness._preflight_analysis_python_write(
        scope=scope,
        tool_name="apply_analysis_patch",
        canonical={
            "operations": [
                {
                    "operation": "create",
                    "path": "analysis/evidence/a1/supplement.py",
                    "content": accepted,
                }
            ]
        },
    )

    rejected = "#" + "a" * (8 * 1024) + "\npass\n"
    with pytest.raises(Exception) as caught:
        await harness._preflight_analysis_python_write(
            scope=scope,
            tool_name="apply_analysis_patch",
            canonical={
                "operations": [
                    {
                        "operation": "create",
                        "path": "analysis/evidence/a1/supplement.py",
                        "content": rejected,
                    }
                ]
            },
        )
    assert caught.value.details["maxLineLength"] == 8 * 1024 + 1

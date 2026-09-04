from __future__ import annotations

import hashlib
from types import SimpleNamespace

import pytest
from agno.tools import Toolkit

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
from smart_reporting.reporting.tools.workspace_adapter import WorkspaceServiceReportingPort
from smart_reporting.reporting.tools.workspace_port import ReportingWorkspaceError


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
async def test_mock_workspace_rejects_timeout_foreign_session_and_duplicate_submit() -> None:
    first = MockReportingWorkspace(output_policy=ReportingOutputPolicy(roots=("output",)))
    second = MockReportingWorkspace(output_policy=ReportingOutputPolicy(roots=("output",)))

    with pytest.raises(ReportingWorkspaceError, match="超时"):
        await first.execute_script("python3 analysis.py", timeout=0)
    started = await first.execute_script("python3 analysis.py", timeout=30, background=True)
    session_id = str(started["session_id"])
    with pytest.raises(ReportingWorkspaceError, match="不属于"):
        await second.send_process_input(session_id, "yes", submit=True, timeout=30)

    await first.send_process_input(session_id, "yes", submit=True, timeout=30)
    with pytest.raises(ReportingWorkspaceError, match="已提交"):
        await first.send_process_input(session_id, "yes", submit=True, timeout=30)


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

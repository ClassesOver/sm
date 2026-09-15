from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

from smart_reporting.reporting.code_agent.lsp_process import (
    ReportingLspProcessError,
    ReportingLspProcessManager,
)

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def lsp_server(tmp_path: Path) -> tuple[str, ...]:
    server = tmp_path / "fake_pylsp.py"
    server.write_text(
        """\
import json
import sys

counter = open("starts.txt", "a", encoding="utf-8")
counter.write("start\\n")
counter.close()

def receive():
    headers = {}
    while True:
        line = sys.stdin.buffer.readline()
        if not line:
            return None
        if line == b"\\r\\n":
            break
        name, value = line.decode("ascii").split(":", 1)
        headers[name.lower()] = value.strip()
    return json.loads(sys.stdin.buffer.read(int(headers["content-length"])))

def send(payload):
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    sys.stdout.buffer.write(b"Content-Length: " + str(len(raw)).encode("ascii") + b"\\r\\n\\r\\n" + raw)
    sys.stdout.buffer.flush()

while request := receive():
    method = request.get("method")
    params = request.get("params", {})
    if method == "initialize":
        import time
        time.sleep(0.05)
        send({"jsonrpc": "2.0", "id": request["id"], "result": {"capabilities": {}}})
    elif method == "test/die":
        raise SystemExit(0)
    elif method in {"textDocument/didOpen", "textDocument/didChange"}:
        document = params["textDocument"]
        send({"jsonrpc": "2.0", "method": "textDocument/publishDiagnostics", "params": {"uri": document["uri"], "version": document["version"] - 1, "diagnostics": [{"message": "stale"}]}})
        send({"jsonrpc": "2.0", "method": "textDocument/publishDiagnostics", "params": {"uri": document["uri"], "version": document["version"], "diagnostics": []}})
    elif "id" in request:
        send({"jsonrpc": "2.0", "id": request["id"], "result": {"method": method, "params": params}})
""",
        encoding="utf-8",
    )
    return (sys.executable, str(server))


async def test_manager_correlates_requests_and_waits_for_matching_diagnostic_version(
    tmp_path: Path,
    lsp_server: tuple[str, ...],
) -> None:
    manager = ReportingLspProcessManager(command=lsp_server, request_timeout_seconds=1)
    root = tmp_path / "workspace"
    root.mkdir()

    first = await manager.request(root, "test/first", {"value": 1})
    second = await manager.request(root, "test/second", {"value": 2})
    diagnostics = await manager.diagnostics(root, "file:///workspace/a.py", "value = 1\n")

    assert first == {"method": "test/first", "params": {"value": 1}}
    assert second == {"method": "test/second", "params": {"value": 2}}
    assert diagnostics == (1, [])
    assert (root / "starts.txt").read_text(encoding="utf-8").splitlines() == ["start"]
    await manager.aclose()


async def test_manager_restarts_after_death_reaps_idle_process_and_closes_all(
    tmp_path: Path,
    lsp_server: tuple[str, ...],
) -> None:
    manager = ReportingLspProcessManager(
        command=lsp_server,
        request_timeout_seconds=0.2,
        idle_ttl_seconds=0,
    )
    root = tmp_path / "workspace"
    root.mkdir()

    with pytest.raises(ReportingLspProcessError):
        await manager.request(root, "test/die", {})
    assert await manager.request(root, "test/restarted", {}) == {
        "method": "test/restarted",
        "params": {},
    }
    await manager.reap_idle()
    assert await manager.request(root, "test/reaped", {}) == {
        "method": "test/reaped",
        "params": {},
    }
    await manager.aclose()
    assert (root / "starts.txt").read_text(encoding="utf-8").splitlines() == [
        "start",
        "start",
        "start",
    ]


async def test_manager_automatically_reaps_idle_process(
    tmp_path: Path,
    lsp_server: tuple[str, ...],
) -> None:
    manager = ReportingLspProcessManager(
        command=lsp_server,
        request_timeout_seconds=1,
        idle_ttl_seconds=0.01,
    )
    root = tmp_path / "workspace"
    root.mkdir()

    await manager.request(root, "test/first", {})
    await asyncio.sleep(0.08)

    await manager.request(root, "test/second", {})
    await manager.aclose()

    assert (root / "starts.txt").read_text(encoding="utf-8").splitlines() == [
        "start",
        "start",
    ]


async def test_manager_deduplicates_concurrent_first_start(
    tmp_path: Path,
    lsp_server: tuple[str, ...],
) -> None:
    manager = ReportingLspProcessManager(command=lsp_server, request_timeout_seconds=1)
    root = tmp_path / "workspace"
    root.mkdir()

    results = await asyncio.gather(
        manager.request(root, "test/first", {}),
        manager.request(root, "test/second", {}),
    )

    assert results == [
        {"method": "test/first", "params": {}},
        {"method": "test/second", "params": {}},
    ]
    assert (root / "starts.txt").read_text(encoding="utf-8").splitlines() == ["start"]
    await manager.aclose()


async def test_manager_close_waits_for_process_still_starting(
    tmp_path: Path,
    lsp_server: tuple[str, ...],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    processes: list[asyncio.subprocess.Process] = []
    create_subprocess_exec = asyncio.create_subprocess_exec

    async def capture_process(*args: object, **kwargs: object) -> asyncio.subprocess.Process:
        process = await create_subprocess_exec(*args, **kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", capture_process)
    manager = ReportingLspProcessManager(command=lsp_server, request_timeout_seconds=1)
    root = tmp_path / "workspace"
    root.mkdir()

    request = asyncio.create_task(manager.request(root, "test/first", {}))
    while not processes:
        await asyncio.sleep(0)
    await manager.aclose()
    closed_when_aclose_returned = processes[0].returncode is not None

    with pytest.raises(ReportingLspProcessError, match="管理器已关闭"):
        await request
    assert closed_when_aclose_returned is True


async def test_manager_close_waits_for_reader_task(
    tmp_path: Path,
    lsp_server: tuple[str, ...],
) -> None:
    manager = ReportingLspProcessManager(command=lsp_server, request_timeout_seconds=1)
    root = tmp_path / "workspace"
    root.mkdir()

    await manager.request(root, "test/first", {})
    state = manager._states[root.resolve()]
    reader_task = state.reader_task
    assert reader_task is not None

    await manager.aclose()

    assert reader_task.done()

import asyncio
import hashlib
import json
import shlex
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager, contextmanager
from io import BytesIO

import pytest
from agno.run import RunContext
from pypdf import PdfWriter

import agentos_dev.workspace as workspace_module
from agentos_dev.database import create_agent_database
from agentos_dev.tests.workspace_fakes import (
    SECRET,
    AsyncFakeClient,
    AsyncFakeFs,
    AsyncFakeProcess,
    AsyncMemoryRegistry,
    FakeClient,
    FakeSandbox,
    Info,
    service,
)
from agentos_dev.workspace import (
    MAX_DOWNLOAD_BYTES,
    MAX_MANAGED_PROCESSES,
    MAX_PATH_BYTES,
    MAX_PATH_COMPONENT_BYTES,
    MAX_PATH_DEPTH,
    MAX_PROCESS_INPUT_BYTES,
    MAX_READ_BYTES,
    MAX_TOOL_OUTPUT_BYTES,
    WORKSPACE_ROOT,
    WORKSPACE_SNAPSHOT,
    AsyncSandboxRegistry,
    BaseToolkit,
    DaytonaToolkit,
    SandboxRegistry,
    WorkspaceError,
    WorkspacePathConflict,
    WorkspaceService,
)


def test_每个对话使用独立持久沙箱且注册表可跨服务复用(tmp_path):
    assert WORKSPACE_SNAPSHOT == "sandbox-tools"
    client = FakeClient()
    first = service(tmp_path, client)
    one = first.sandbox_for("thread-one")
    two = first.sandbox_for("thread-two")

    assert one.id != two.id
    assert len(client.created) == 2
    params = client.created[0]
    assert params.public is False
    assert params.ephemeral is False
    assert params.network_block_all is True
    assert params.snapshot == WORKSPACE_SNAPSHOT
    assert params.auto_stop_interval == 60
    assert list(params.labels) == ["agui-thread"]
    assert "thread-one" not in str(params.labels)

    restarted = WorkspaceService(SECRET, client=client, registry=first.registry)
    assert restarted.sandbox_for("thread-one").id == one.id
    assert len(client.created) == 2

    configured = WorkspaceService(
        SECRET,
        client=client,
        registry=first.registry,
        snapshot="custom-snapshot",
    )
    configured.sandbox_for("thread-three")
    assert client.created[-1].snapshot == "custom-snapshot"

    networked = WorkspaceService(
        SECRET,
        client=client,
        registry=first.registry,
        network_allow_list="203.0.113.10/32",
    )
    networked.sandbox_for("thread-four")
    assert client.created[-1].network_allow_list == "203.0.113.10/32"
    assert client.created[-1].network_block_all is None


@pytest.mark.anyio
async def test_async_daytona_client_is_shared_and_shutdown_resists_repeated_cancellation(
    monkeypatch,
):
    close_started = asyncio.Event()
    allow_close = asyncio.Event()
    instances = []
    close_calls = 0

    class ClosingClient:
        def __init__(self):
            instances.append(self)

        async def close(self):
            nonlocal close_calls
            close_calls += 1
            close_started.set()
            await allow_close.wait()

    monkeypatch.setattr(workspace_module, "AsyncDaytona", ClosingClient)
    current = WorkspaceService(SECRET, async_registry=AsyncMemoryRegistry({}))
    async with current._async_client() as first:
        pass
    async with current._async_client() as second:
        pass
    assert first is second
    assert len(instances) == 1

    async def cancelled_request():
        async with current._async_client():
            await asyncio.Event().wait()

    request = asyncio.create_task(cancelled_request())
    await asyncio.sleep(0)
    request.cancel()
    with pytest.raises(asyncio.CancelledError):
        await request
    assert not close_started.is_set()

    shutdown = asyncio.create_task(current.aclose())
    await close_started.wait()
    shutdown.cancel()
    await asyncio.sleep(0)
    shutdown.cancel()
    allow_close.set()
    await shutdown
    await current.aclose()
    assert close_calls == 1


def test_sandbox_id_cache_skips_registry_and_recovers_from_not_found(tmp_path, monkeypatch):
    client = FakeClient()
    current = service(tmp_path, client)
    lock_calls = 0
    original_locked = current.registry.locked

    @contextmanager
    def counted_locked(value):
        nonlocal lock_calls
        lock_calls += 1
        with original_locked(value) as registry:
            yield registry

    monkeypatch.setattr(current.registry, "locked", counted_locked)
    first = current.sandbox_for("thread")
    assert current.sandbox_for("thread") is first
    assert lock_calls == 1

    client.sandboxes.pop(first.id)
    client.sandboxes["unrelated"] = FakeSandbox("unrelated", {})
    rebuilt = current.sandbox_for("thread")
    assert rebuilt.id != first.id
    assert lock_calls == 2

    assert current.destroy("thread") is True
    assert current._cached_sandbox_id(current._hash("thread")) is None


def test_sandbox_id_cache_is_bounded_lru(tmp_path, monkeypatch):
    current = service(tmp_path)
    monkeypatch.setattr(workspace_module, "MAX_SANDBOX_ID_CACHE_ENTRIES", 2)
    values = [current._hash(f"thread-{index}") for index in range(3)]
    for index, value in enumerate(values):
        current._cache_sandbox_id(value, f"sandbox-{index}")
    assert current._cached_sandbox_id(values[0]) is None
    assert list(current._sandbox_ids) == values[1:]


@pytest.mark.anyio
async def test_async_sandbox_cache_hits_overlap_without_registry_lock(tmp_path):
    synchronous = service(tmp_path)
    sandbox = synchronous.sandbox_for("thread")

    class CountingRegistry(AsyncMemoryRegistry):
        def __init__(self, values):
            super().__init__(values)
            self.lock_calls = 0

        @asynccontextmanager
        async def locked(self, value):
            self.lock_calls += 1
            async with super().locked(value) as registry:
                yield registry

    class OverlapClient(AsyncFakeClient):
        def __init__(self, client):
            super().__init__(client)
            self.active = 0
            self.max_active = 0

        async def get(self, sandbox_id):
            self.active += 1
            self.max_active = max(self.max_active, self.active)
            await asyncio.sleep(0)
            try:
                return await super().get(sandbox_id)
            finally:
                self.active -= 1

    registry = CountingRegistry(synchronous.registry.values)
    client = OverlapClient(synchronous.client)
    current = WorkspaceService(
        SECRET,
        client=synchronous.client,
        registry=synchronous.registry,
        async_client=client,
        async_registry=registry,
    )
    first = await current._asandbox_for(client, "thread")
    assert first.id == sandbox.id
    assert registry.lock_calls == 1

    results = await asyncio.gather(
        current._asandbox_for(client, "thread"),
        current._asandbox_for(client, "thread"),
    )
    assert [result.id for result in results] == [sandbox.id, sandbox.id]
    assert registry.lock_calls == 1
    assert client.max_active == 2
    assert await current.adestroy("thread") is True
    assert current._cached_sandbox_id(current._hash("thread")) is None


def test_路径大小符号链接和销毁边界均生效(tmp_path, monkeypatch):
    current = service(tmp_path)
    with pytest.raises(WorkspaceError, match="目录穿越"):
        current.upload("thread", "../escape", b"bad")
    with pytest.raises(WorkspaceError, match="绝对路径"):
        current.list_files("thread", "/etc")
    with monkeypatch.context() as patch:
        patch.setattr(workspace_module, "MAX_UPLOAD_BYTES", 4)
        with pytest.raises(WorkspaceError, match="文件内容超过"):
            current.upload("thread", "large.bin", b"12345")

    current.upload("thread", "docs/readme.txt", b"hello")
    assert current.read_text("thread", "docs/readme.txt") == "hello"
    sandbox = current.sandbox_for("thread")
    sandbox.fs.entries["/home/daytona/workspace/link"] = (
        Info("link", mode="lrwxrwxrwx"),
        b"outside",
    )
    with pytest.raises(WorkspaceError, match="符号链接"):
        current.file_bytes("thread", "link")
    with pytest.raises(WorkspaceError, match="符号链接"):
        current.upload("thread", "link", b"overwrite")

    current.upload("thread", "move-source.txt", b"move")
    with pytest.raises(WorkspaceError, match="符号链接"):
        current.move_file("thread", "move-source.txt", "link")

    assert current.destroy("thread") is True
    assert current.destroy("thread") is False


def test_工作区下载允许200mib并拒绝更大文件(tmp_path):
    current = service(tmp_path)
    current.create_file("thread", "archive.bin", b"file")
    info = current.sandbox_for("thread").fs.entries[f"{WORKSPACE_ROOT}/archive.bin"][0]
    info.size = MAX_DOWNLOAD_BYTES

    assert current.file_bytes("thread", "archive.bin")[0] == b"file"

    info.size = MAX_DOWNLOAD_BYTES + 1
    with pytest.raises(WorkspaceError, match="超过 200 MiB"):
        current.file_bytes("thread", "archive.bin")


def test_销毁会删除重复标签沙箱并清理注册表(tmp_path):
    client = FakeClient()
    current = service(tmp_path, client)
    value = current._hash("thread")
    first = FakeSandbox("sandbox-1", {"agui-thread": value})
    second = FakeSandbox("sandbox-2", {"agui-thread": value})
    client.sandboxes = {first.id: first, second.id: second}
    current.registry.set(value, first.id)

    assert current.destroy("thread") is True
    assert set(client.deleted) == {first.id, second.id}
    assert current.registry.get(value) is None
    assert current.destroy("thread") is False


def test_注册表直到首次使用才初始化(monkeypatch):
    registry = SandboxRegistry("postgresql://unavailable/example")
    monkeypatch.setattr(
        registry,
        "_connect",
        lambda: (_ for _ in ()).throw(RuntimeError("offline")),
    )

    with pytest.raises(RuntimeError, match="offline"):
        registry.ensure_initialized()


@pytest.mark.anyio
async def test_异步注册表连接只启动一次并正常归还(tmp_path):
    database = create_agent_database(f"sqlite:///{tmp_path / 'registry.db'}")
    registry = AsyncSandboxRegistry(database.async_db)

    try:
        async with registry.locked("thread") as transaction:
            await transaction.set("thread", "sandbox-1")
        async with registry.locked("thread") as transaction:
            assert await transaction.get("thread") == "sandbox-1"
    finally:
        await database.async_engine.dispose()
        database.sync_engine.dispose()


@pytest.mark.anyio
async def test_基础工具支持搜索分段读取哈希精确补丁和媒体检查(tmp_path):
    current = service(tmp_path)
    current.create_file("thread", "src/app.py", b"alpha\nneedle here\nomega\n")
    current.create_file("thread", "docs/readme.md", b"needle in docs\n")
    sandbox = current.sandbox_for("thread")

    def execute_workspace_command(command, cwd=None, timeout=None):
        sandbox.process.calls.append({"command": command, "cwd": cwd, "timeout": timeout})
        if "rg --no-config" in command:
            output = (
                "./docs/readme.md\x00./src/app.py\x00" if "*.md" in command else "./src/app.py\x00"
            )
        elif "file --brief --mime-encoding" in command:
            output = "us-ascii\x0024\x003\x00"
        elif "sed -n" in command:
            output = "needle here\n"
        elif "sha256sum" in command:
            digest = hashlib.sha256(b"alpha\nneedle here\nomega\n").hexdigest()
            output = f"{digest}\x0024\x00"
        else:
            raise AssertionError(f"unexpected command: {command}")
        return type("Result", (), {"result": output, "exit_code": 0})()

    sandbox.process.exec = execute_workspace_command
    async_service = WorkspaceService(
        current.secret,
        client=current.client,
        registry=current.registry,
        async_client=AsyncFakeClient(current.client),
        async_registry=AsyncMemoryRegistry(current.registry.values),
    )
    toolkit = BaseToolkit(async_service)
    tools = {**toolkit.functions, **toolkit.async_functions}
    context = RunContext(run_id="run", session_id="thread")

    files = await toolkit.workspace_search_files(pattern="*.py", run_context=context)
    assert files == {
        "matches": [{"path": "src/app.py", "name": "app.py", "size": 24}],
        "truncated": False,
    }
    multiple = await toolkit.workspace_search_files(
        include_globs=["*.py", "*.md"],
        exclude_globs=["vendor/**"],
        run_context=context,
    )
    assert [item["path"] for item in multiple["matches"]] == [
        "docs/readme.md",
        "src/app.py",
    ]
    command = sandbox.process.calls[-1]["command"]
    for argument in ("--files", "*.py", "*.md", "!vendor/**"):
        assert argument in command
    assert sandbox.fs.download_calls == []
    lines = await toolkit.workspace_read_lines(
        path="src/app.py", start_line=2, line_count=1, run_context=context
    )
    assert lines == {
        "path": "src/app.py",
        "startLine": 2,
        "endLine": 2,
        "totalLines": 3,
        "content": "needle here\n",
        "truncated": True,
    }
    digest = await toolkit.workspace_hash_file(path="src/app.py", run_context=context)
    assert digest["path"] == "src/app.py"
    assert digest["sha256"]
    patched = tools["workspace_apply_patch"].entrypoint(
        path="src/app.py",
        old_text="needle here",
        new_text="updated value",
        expected_sha256=digest["sha256"],
        run_context=context,
    )
    assert patched["replacements"] == 1
    assert "-needle here" in patched["diff"]
    assert "+updated value" in patched["diff"]
    assert patched["diffTruncated"] is False
    assert current.read_text("thread", "src/app.py") == "alpha\nupdated value\nomega\n"

    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
    current.upload("thread", "chart.png", png)
    image = tools["workspace_view_image"].entrypoint(path="chart.png", run_context=context)
    assert image.images and image.images[0].content == png
    assert image.images[0].mime_type == "image/png"

    pdf_buffer = BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    writer.write(pdf_buffer)
    current.upload("thread", "report.pdf", pdf_buffer.getvalue())
    pdf = tools["workspace_inspect_pdf"].entrypoint(path="report.pdf", run_context=context)
    assert pdf["pageCount"] == 1
    assert pdf["sha256"]


@pytest.mark.anyio
async def test_大文件分段读取哈希统计和目录树均在沙箱内执行(tmp_path):
    current = service(tmp_path)
    large_content = (("line value\n" * 100_000) + "last line").encode()
    current.create_file("thread", "data/large.txt", large_content)
    current.create_file("thread", "data/small.txt", b"small\n")
    sandbox = current.sandbox_for("thread")
    process = sandbox.process
    total_lines = 100_001
    digest = hashlib.sha256(large_content).hexdigest()

    def execute_command(command, cwd=None, timeout=None):
        process.calls.append({"command": command, "cwd": cwd, "timeout": timeout})
        if "file --brief --mime-encoding" in command:
            output = f"us-ascii\x00{len(large_content)}\x00{total_lines}\x00"
        elif "sed -n" in command:
            output = "line value\nline value\n"
        elif "sha256sum" in command:
            output = f"{digest}\x00{len(large_content)}\x00"
        elif "stat --printf" in command:
            output = f"regular file\x00{len(large_content)}\x001753200000\x00600\x00"
        elif "find " in command:
            output = f"d\tnested\t4096\x00f\tlarge.txt\t{len(large_content)}\x00"
        else:
            raise AssertionError(f"unexpected command: {command}")
        return type("Result", (), {"result": output, "exit_code": 0})()

    process.exec = execute_command
    toolkit = BaseToolkit(
        WorkspaceService(
            current.secret,
            client=current.client,
            registry=current.registry,
            async_client=AsyncFakeClient(current.client),
            async_registry=AsyncMemoryRegistry(current.registry.values),
        )
    )
    context = RunContext(run_id="run", session_id="thread")

    lines = await toolkit.workspace_read_lines(
        "data/large.txt", start_line=90_000, line_count=2, run_context=context
    )
    hashed = await toolkit.workspace_hash_file("data/large.txt", run_context=context)
    stat = await toolkit.workspace_stat("data/large.txt", run_context=context)
    tree = await toolkit.workspace_tree("data", max_depth=2, run_context=context)

    assert len(large_content) > MAX_READ_BYTES
    assert lines == {
        "path": "data/large.txt",
        "startLine": 90_000,
        "endLine": 90_001,
        "totalLines": total_lines,
        "content": "line value\nline value\n",
        "truncated": True,
    }
    assert hashed == {
        "path": "data/large.txt",
        "size": len(large_content),
        "sha256": digest,
    }
    assert stat == {
        "path": "data/large.txt",
        "type": "file",
        "size": len(large_content),
        "modifiedUnix": 1_753_200_000,
        "mode": "600",
    }
    assert tree == {
        "root": "data",
        "entries": [
            {"path": "data/nested", "type": "directory", "size": 4096},
            {"path": "data/large.txt", "type": "file", "size": len(large_content)},
        ],
        "truncated": False,
    }
    assert sandbox.fs.download_calls == []
    assert any("wc -l" in call["command"] for call in process.calls)
    assert any("sed -n" in call["command"] for call in process.calls)
    assert any("sha256sum" in call["command"] for call in process.calls)
    assert any("stat --printf" in call["command"] for call in process.calls)
    assert any("find " in call["command"] for call in process.calls)


@pytest.mark.anyio
async def test_只读_git_工具使用固定参数并拒绝非法修订(tmp_path):
    current = service(tmp_path)
    current.create_file("thread", "repo/src/app.py", b"print('ok')\n")
    sandbox = current.sandbox_for("thread")
    process = sandbox.process

    def execute_git(command, cwd=None, timeout=None):
        process.calls.append({"command": command, "cwd": cwd, "timeout": timeout})
        return type("Result", (), {"result": "git output", "exit_code": 0})()

    process.exec = execute_git
    toolkit = BaseToolkit(
        WorkspaceService(
            current.secret,
            client=current.client,
            registry=current.registry,
            async_client=AsyncFakeClient(current.client),
            async_registry=AsyncMemoryRegistry(current.registry.values),
        )
    )
    context = RunContext(run_id="run", session_id="thread")

    assert (await toolkit.workspace_git_status("repo", run_context=context))["output"]
    assert (
        await toolkit.workspace_git_diff(
            "repo", staged=True, revision="HEAD~2", file_path="src/app.py", run_context=context
        )
    )["output"]
    assert (
        await toolkit.workspace_git_log(
            "repo", revision="main", max_count=10, file_path="src/app.py", run_context=context
        )
    )["output"]
    assert (
        await toolkit.workspace_git_show(
            "repo", revision="HEAD^", file_path="src/app.py", run_context=context
        )
    )["output"]

    commands = [call["command"] for call in process.calls]
    assert all("git -C" in command and "--no-pager" in command for command in commands)
    assert all("core.fsmonitor=false" in command for command in commands)
    assert all("core.hooksPath=/dev/null" in command for command in commands)
    assert "--short" in commands[0] and "--branch" in commands[0]
    assert "--no-ext-diff" in commands[1] and "--no-textconv" in commands[1]
    assert "--cached" in commands[1] and "HEAD~2" in commands[1]
    assert "--max-count=10" in commands[2] and "main" in commands[2]
    assert "--format=fuller" in commands[3] and "HEAD^" in commands[3]
    assert all(call["cwd"] == WORKSPACE_ROOT for call in process.calls)
    assert sandbox.fs.download_calls == []

    with pytest.raises(WorkspaceError, match="Git 修订"):
        await toolkit.workspace_git_show("repo", revision="--help", run_context=context)
    assert len(process.calls) == 4


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("stderr", "message"),
    [
        ("fatal: not a git repository", "不是 Git 仓库"),
        ("fatal: bad revision 'missing'", "修订不存在"),
        ("error: pathspec 'missing.py' did not match", "文件路径不存在"),
        ("fatal: unexpected internal detail /secret/path", "Git 只读命令执行失败"),
    ],
)
async def test_git_失败只返回分类诊断而不暴露原始_stderr(tmp_path, stderr, message):
    current = service(tmp_path)
    current.create_file("thread", "repo/file.txt", b"content\n")
    process = current.sandbox_for("thread").process

    def fail_git(command, cwd=None, timeout=None):
        process.calls.append({"command": command, "cwd": cwd, "timeout": timeout})
        return type("Result", (), {"result": stderr, "exit_code": 128})()

    process.exec = fail_git
    toolkit = BaseToolkit(
        WorkspaceService(
            current.secret,
            client=current.client,
            registry=current.registry,
            async_client=AsyncFakeClient(current.client),
            async_registry=AsyncMemoryRegistry(current.registry.values),
        )
    )

    with pytest.raises(WorkspaceError, match=message) as error:
        await toolkit.workspace_git_show(
            "repo", revision="missing", run_context=RunContext(run_id="run", session_id="thread")
        )
    assert "/secret/path" not in str(error.value)


@pytest.mark.anyio
async def test_文本搜索在沙箱内使用_rg_并支持_codex_常用模式(tmp_path):
    current = service(tmp_path)
    current.create_file("thread", "src/app.py", b"before\nNeedle here\nafter\n")
    sandbox = current.sandbox_for("thread")
    process = sandbox.process

    match_events = [
        {
            "type": "context",
            "data": {
                "path": {"text": "./src/app.py"},
                "lines": {"text": "before\n"},
                "line_number": 1,
                "submatches": [],
            },
        },
        {
            "type": "match",
            "data": {
                "path": {"text": "./src/app.py"},
                "lines": {"text": "Needle here\n"},
                "line_number": 2,
                "submatches": [{"start": 0, "end": 6, "match": {"text": "Needle"}}],
            },
        },
        {
            "type": "context",
            "data": {
                "path": {"text": "./src/app.py"},
                "lines": {"text": "after\n"},
                "line_number": 3,
                "submatches": [],
            },
        },
    ]

    def execute_rg(command, cwd=None, timeout=None):
        process.calls.append({"command": command, "cwd": cwd, "timeout": timeout})
        if "--files-with-matches" in command:
            output = "./docs/readme.md\x00./src/app.py\x00"
        elif "--count" in command:
            output = "./docs/readme.md\x001\n./src/app.py\x002\n"
        else:
            output = "\n".join(json.dumps(event) for event in match_events) + "\n"
        return type("Result", (), {"result": output, "exit_code": 0})()

    process.exec = execute_rg
    async_service = WorkspaceService(
        current.secret,
        client=current.client,
        registry=current.registry,
        async_client=AsyncFakeClient(current.client),
        async_registry=AsyncMemoryRegistry(current.registry.values),
    )
    toolkit = BaseToolkit(async_service)
    context = RunContext(run_id="run", session_id="thread")

    matches = await toolkit.workspace_search_text(
        query=r"Need(le)?",
        regex=True,
        case_mode="smart",
        word_match=True,
        include_globs=["*.py", "*.md"],
        exclude_globs=["vendor/**"],
        before_context=1,
        after_context=1,
        run_context=context,
    )
    files = await toolkit.workspace_search_text(
        query="needle", mode="files_with_matches", run_context=context
    )
    counts = await toolkit.workspace_search_text(query="needle", mode="count", run_context=context)

    assert matches == {
        "mode": "matches",
        "matches": [
            {
                "path": "src/app.py",
                "line": 2,
                "column": 1,
                "text": "Needle here",
                "before": [{"line": 1, "text": "before"}],
                "after": [{"line": 3, "text": "after"}],
            }
        ],
        "truncated": False,
    }
    assert files == {
        "mode": "files_with_matches",
        "files": [{"path": "docs/readme.md"}, {"path": "src/app.py"}],
        "truncated": False,
    }
    assert counts == {
        "mode": "count",
        "counts": [
            {"path": "docs/readme.md", "count": 1},
            {"path": "src/app.py", "count": 2},
        ],
        "truncated": False,
    }
    command = process.calls[0]["command"]
    for argument in (
        "--json",
        "--smart-case",
        "--word-regexp",
        "*.py",
        "*.md",
        "!vendor/**",
        "!报表/原始数据/*/分片/*.jsonl",
        "!reports/data/*.jsonl",
    ):
        assert argument in command
    assert process.calls[0]["cwd"] == WORKSPACE_ROOT
    assert sandbox.fs.download_calls == []


@pytest.mark.anyio
async def test_rg_搜索拒绝非法模式_glob_和受控原始数据(tmp_path):
    current = service(tmp_path)
    current.create_file("thread", "visible.txt", b"needle\n")
    current.upload(
        "thread",
        "报表/原始数据/11111111-1111-4111-8111-111111111111/分片/数据-0001.jsonl",
        b"needle\n",
    )
    async_service = WorkspaceService(
        current.secret,
        client=current.client,
        registry=current.registry,
        async_client=AsyncFakeClient(current.client),
        async_registry=AsyncMemoryRegistry(current.registry.values),
    )
    toolkit = BaseToolkit(async_service)
    context = RunContext(run_id="run", session_id="thread")

    with pytest.raises(WorkspaceError, match="大小写模式"):
        await toolkit.workspace_search_text(query="x", case_mode="invalid", run_context=context)
    with pytest.raises(WorkspaceError, match="输出模式"):
        await toolkit.workspace_search_text(query="x", mode="invalid", run_context=context)
    with pytest.raises(WorkspaceError, match="glob"):
        await toolkit.workspace_search_text(query="x", include_globs=["!*.py"], run_context=context)
    with pytest.raises(WorkspaceError, match="原始报表分片"):
        await toolkit.workspace_search_text(
            query="needle",
            path="报表/原始数据/11111111-1111-4111-8111-111111111111/分片/数据-0001.jsonl",
            run_context=context,
        )


def test_补丁拒绝陈旧和非唯一内容(tmp_path):
    current = service(tmp_path)
    current.create_file("thread", "notes.txt", b"same\nsame\n")
    tools = BaseToolkit(current).functions
    context = RunContext(run_id="run", session_id="thread")
    digest = current.hash_file("thread", "notes.txt")

    current.replace_file("thread", "notes.txt", b"changed\n")
    with pytest.raises(WorkspacePathConflict, match="文件内容已变化"):
        tools["workspace_apply_patch"].entrypoint(
            path="notes.txt",
            old_text="same",
            new_text="updated",
            expected_sha256=digest["sha256"],
            run_context=context,
        )

    current.replace_file("thread", "notes.txt", b"same\nsame\n")
    digest = current.hash_file("thread", "notes.txt")
    with pytest.raises(WorkspaceError, match="出现 2 次"):
        tools["workspace_apply_patch"].entrypoint(
            path="notes.txt",
            old_text="same",
            new_text="updated",
            expected_sha256=digest["sha256"],
            run_context=context,
        )

    current.upload("thread", "fake.png", b"not-a-png")
    with pytest.raises(WorkspaceError, match="文件签名不一致"):
        tools["workspace_view_image"].entrypoint(path="fake.png", run_context=context)


def test_批量补丁支持多文件多段编辑(tmp_path):
    current = service(tmp_path)
    current.create_file("thread", "a.txt", b"one\ntwo\nthree\n")
    current.create_file("thread", "b.txt", b"alpha\nbeta\n")
    tools = BaseToolkit(current).functions
    context = RunContext(run_id="run", session_id="thread")
    a_hash = current.hash_file("thread", "a.txt")["sha256"]
    b_hash = current.hash_file("thread", "b.txt")["sha256"]

    result = tools["workspace_apply_patch_set"].entrypoint(
        patches=[
            {
                "path": "a.txt",
                "expected_sha256": a_hash,
                "edits": [
                    {"old_text": "one", "new_text": "ONE"},
                    {"old_text": "three", "new_text": "THREE"},
                ],
            },
            {
                "path": "b.txt",
                "expected_sha256": b_hash,
                "edits": [{"old_text": "beta", "new_text": "BETA"}],
            },
        ],
        run_context=context,
    )

    assert [item["path"] for item in result["files"]] == ["a.txt", "b.txt"]
    assert result["replacements"] == 3
    assert current.read_text("thread", "a.txt") == "ONE\ntwo\nTHREE\n"
    assert current.read_text("thread", "b.txt") == "alpha\nBETA\n"


def test_批量补丁预检任一冲突时不写入任何文件(tmp_path):
    current = service(tmp_path)
    current.create_file("thread", "a.txt", b"before-a\n")
    current.create_file("thread", "b.txt", b"before-b\n")
    a_hash = current.hash_file("thread", "a.txt")["sha256"]
    tools = BaseToolkit(current).functions

    with pytest.raises(WorkspacePathConflict, match="文件内容已变化"):
        tools["workspace_apply_patch_set"].entrypoint(
            patches=[
                {
                    "path": "a.txt",
                    "expected_sha256": a_hash,
                    "edits": [{"old_text": "before-a", "new_text": "after-a"}],
                },
                {
                    "path": "b.txt",
                    "expected_sha256": "0" * 64,
                    "edits": [{"old_text": "before-b", "new_text": "after-b"}],
                },
            ],
            run_context=RunContext(run_id="run", session_id="thread"),
        )

    assert current.read_text("thread", "a.txt") == "before-a\n"
    assert current.read_text("thread", "b.txt") == "before-b\n"


def test_定位_hunk_支持多文件并拒绝错位或陈旧内容(tmp_path):
    current = service(tmp_path)
    current.create_file("thread", "a.txt", b"one\ntwo\nthree\nfour\n")
    current.create_file("thread", "b.txt", b"alpha\nbeta\ngamma\n")
    tool = BaseToolkit(current).functions["workspace_apply_hunks"]
    context = RunContext(run_id="run", session_id="thread")

    result = tool.entrypoint(
        patches=[
            {
                "path": "a.txt",
                "expected_sha256": current.hash_file("thread", "a.txt")["sha256"],
                "hunks": [{"old_start": 2, "old_text": "two\nthree\n", "new_text": "TWO\nTHREE\n"}],
            },
            {
                "path": "b.txt",
                "expected_sha256": current.hash_file("thread", "b.txt")["sha256"],
                "hunks": [{"old_start": 2, "old_text": "beta\n", "new_text": "BETA\n"}],
            },
        ],
        run_context=context,
    )

    assert result["hunks"] == 2
    assert current.read_text("thread", "a.txt") == "one\nTWO\nTHREE\nfour\n"
    assert current.read_text("thread", "b.txt") == "alpha\nBETA\ngamma\n"

    current.replace_file("thread", "a.txt", b"one\ntwo\nthree\nfour\n")
    with pytest.raises(WorkspaceError, match="第 3 行"):
        tool.entrypoint(
            patches=[
                {
                    "path": "a.txt",
                    "expected_sha256": current.hash_file("thread", "a.txt")["sha256"],
                    "hunks": [{"old_start": 3, "old_text": "two\nthree\n", "new_text": "wrong\n"}],
                }
            ],
            run_context=context,
        )
    assert current.read_text("thread", "a.txt") == "one\ntwo\nthree\nfour\n"


def test_基础读取拒绝把超大文本直接注入模型并要求分段读取(tmp_path):
    current = service(tmp_path)
    current.create_file("thread", "large.txt", b"x" * (MAX_TOOL_OUTPUT_BYTES + 1))
    tools = BaseToolkit(current).functions
    context = RunContext(run_id="run", session_id="thread")

    with pytest.raises(WorkspaceError, match="workspace_read_lines"):
        tools["workspace_read_file"].entrypoint(path="large.txt", run_context=context)


def test_补丁落盘校验失败时不会报告成功(tmp_path, monkeypatch):
    current = service(tmp_path)
    current.create_file("thread", "notes.txt", b"before\n")
    digest = current.hash_file("thread", "notes.txt")["sha256"]
    original_replace = current.replace_file

    def corrupt_replace(thread, path, _content):
        return original_replace(thread, path, b"corrupted\n")

    monkeypatch.setattr(current, "replace_file", corrupt_replace)

    with pytest.raises(WorkspaceError, match="落盘校验失败"):
        current.apply_patch("thread", "notes.txt", "before", "after", digest)


@pytest.mark.anyio
async def test_sandbox_exec_使用原生异步进程并绑定工作区(tmp_path):
    current = service(tmp_path)
    async_service = WorkspaceService(
        current.secret,
        client=current.client,
        registry=current.registry,
        async_client=AsyncFakeClient(current.client),
        async_registry=AsyncMemoryRegistry(current.registry.values),
    )
    toolkit = BaseToolkit(async_service)

    result = await toolkit.sandbox_exec(
        "pwd", cwd="资料", timeout=30, run_context=RunContext(run_id="run", session_id="thread")
    )

    assert result == {"exitCode": 0, "output": "pwd", "truncated": False}
    process = current.sandbox_for("thread").process
    assert process.calls[-1] == {
        "command": "pwd",
        "cwd": f"{WORKSPACE_ROOT}/资料",
        "timeout": 30,
    }


@pytest.mark.anyio
async def test_sandbox_exec_后台模式使用受管会话并支持轮询输入和终止(tmp_path):
    current = service(tmp_path)
    async_service = WorkspaceService(
        current.secret,
        client=current.client,
        registry=current.registry,
        async_client=AsyncFakeClient(current.client),
        async_registry=AsyncMemoryRegistry(current.registry.values),
    )
    toolkit = BaseToolkit(async_service)
    context = RunContext(run_id="run", session_id="thread")

    started = await toolkit.sandbox_exec(
        "python server.py",
        cwd="应用",
        timeout=900,
        background=True,
        pty=True,
        pty_rows=40,
        pty_cols=132,
        suppress_input_echo=True,
        run_context=context,
        yield_time_ms=0,
    )

    assert started["status"] == "running"
    assert started["sessionId"].startswith("agui-exec-")
    assert started["commandId"] == "command-1"
    assert started["originalBytes"] == 7
    assert started["wallTimeSeconds"] >= 0
    process = current.sandbox_for("thread").process
    managed = process.sessions[started["sessionId"]].commands[0]
    assert managed.suppress_input_echo is True
    assert f"cd -- {shlex.quote(f'{WORKSPACE_ROOT}/应用')}" in managed.command
    assert "timeout --signal=TERM --kill-after=5s 900s" in managed.command
    assert "script --quiet --return --command" in managed.command
    assert "stty rows 40 cols 132 -echo" in managed.command
    assert "TERM=xterm-256color" in managed.command

    with pytest.raises(WorkspaceError, match="前台命令.*60"):
        await toolkit.sandbox_exec("sleep 61", timeout=61, run_context=context)

    polled = await toolkit.sandbox_process_poll(
        started["sessionId"], started["commandId"], run_context=context
    )
    assert polled == {
        "sessionId": started["sessionId"],
        "commandId": "command-1",
        "status": "running",
        "exitCode": None,
        "output": "started",
        "offset": 0,
        "nextOffset": 7,
        "totalBytes": 7,
        "originalBytes": 7,
        "hasMore": False,
        "truncated": False,
    }

    with pytest.raises(WorkspaceError, match="超过 8 KiB"):
        await toolkit.sandbox_process_write(
            started["sessionId"],
            started["commandId"],
            "x" * (MAX_PROCESS_INPUT_BYTES + 1),
            run_context=context,
        )
    with pytest.raises(WorkspaceError, match="会话标识无效"):
        await toolkit.sandbox_process_poll("other-session", "command-1", run_context=context)

    written = await toolkit.sandbox_process_write(
        started["sessionId"],
        started["commandId"],
        "continue\n",
        offset=7,
        yield_time_ms=0,
        run_context=context,
    )
    assert written["ok"] is True
    assert written["status"] == "running"
    assert written["offset"] == 7
    assert process.input_calls[-1]["data"] == "continue\n"

    interrupted = await toolkit.sandbox_process_interrupt(
        started["sessionId"], started["commandId"], signal="INT", run_context=context
    )
    assert interrupted == {"ok": True, "status": "signal_sent", "signal": "INT"}
    assert process.input_calls[-1]["data"] == "\x03"

    plain = await toolkit.sandbox_exec("sleep 1", background=True, run_context=context)
    with pytest.raises(WorkspaceError, match="未启用 PTY"):
        await toolkit.sandbox_process_interrupt(
            plain["sessionId"], plain["commandId"], run_context=context
        )
    await toolkit.sandbox_process_stop(plain["sessionId"], plain["commandId"], run_context=context)

    stopped = await toolkit.sandbox_process_stop(
        started["sessionId"], started["commandId"], run_context=context
    )
    assert stopped == {"ok": True, "status": "terminated"}
    assert started["sessionId"] not in process.sessions


@pytest.mark.anyio
async def test_后台进程完成后轮询返回最终输出并清理会话(tmp_path):
    current = service(tmp_path)
    async_service = WorkspaceService(
        current.secret,
        client=current.client,
        registry=current.registry,
        async_client=AsyncFakeClient(current.client),
        async_registry=AsyncMemoryRegistry(current.registry.values),
    )
    toolkit = BaseToolkit(async_service)
    context = RunContext(run_id="run", session_id="thread")
    started = await toolkit.sandbox_exec("pytest", background=True, run_context=context)
    process = current.sandbox_for("thread").process
    command = process.sessions[started["sessionId"]].commands[0]
    command.exit_code = 0
    command.output = "first\nsecond\n"

    first = await toolkit.sandbox_process_poll(
        started["sessionId"], started["commandId"], offset=0, max_bytes=6, run_context=context
    )
    assert first["output"] == "first\n"
    assert first["nextOffset"] == 6
    assert first["totalBytes"] == 13
    assert first["hasMore"] is True
    assert started["sessionId"] in process.sessions

    other = await toolkit.sandbox_exec("sleep 1", background=True, run_context=context)
    assert started["sessionId"] in process.sessions
    await toolkit.sandbox_process_stop(other["sessionId"], other["commandId"], run_context=context)

    result = await toolkit.sandbox_process_poll(
        started["sessionId"], started["commandId"], offset=6, max_bytes=64, run_context=context
    )

    assert result["status"] == "completed"
    assert result["exitCode"] == 0
    assert result["output"] == "second\n"
    assert result["nextOffset"] == 13
    assert result["hasMore"] is False
    assert started["sessionId"] not in process.sessions


@pytest.mark.anyio
async def test_并发启动后台进程不会突破数量上限(tmp_path, monkeypatch):
    current = service(tmp_path)
    async_service = WorkspaceService(
        current.secret,
        client=current.client,
        registry=current.registry,
        async_client=AsyncFakeClient(current.client),
        async_registry=AsyncMemoryRegistry(current.registry.values),
    )
    toolkit = DaytonaToolkit(async_service)
    original_create_session = AsyncFakeProcess.create_session
    original_execute_session_command = AsyncFakeProcess.execute_session_command

    async def delayed_create_session(self, session_id):
        await asyncio.sleep(0)
        return await original_create_session(self, session_id)

    async def delayed_execute_session_command(self, session_id, request, timeout=None):
        await asyncio.sleep(0)
        return await original_execute_session_command(self, session_id, request, timeout=timeout)

    monkeypatch.setattr(AsyncFakeProcess, "create_session", delayed_create_session)
    monkeypatch.setattr(
        AsyncFakeProcess,
        "execute_session_command",
        delayed_execute_session_command,
    )
    results = await asyncio.gather(
        *[
            toolkit.sandbox_exec(
                f"sleep {index}",
                background=True,
                run_context=RunContext(run_id=f"run-{index}", session_id="thread"),
            )
            for index in range(MAX_MANAGED_PROCESSES + 1)
        ],
        return_exceptions=True,
    )

    succeeded = [result for result in results if isinstance(result, dict)]
    failed = [result for result in results if isinstance(result, WorkspaceError)]
    assert len(succeeded) == MAX_MANAGED_PROCESSES
    assert len(failed) == 1
    assert "后台进程" in str(failed[0])
    assert len(current.sandbox_for("thread").process.sessions) == MAX_MANAGED_PROCESSES


@pytest.mark.anyio
async def test_后台日志字节游标不切断_utf8_字符(tmp_path):
    current = service(tmp_path)
    toolkit = BaseToolkit(
        WorkspaceService(
            current.secret,
            client=current.client,
            registry=current.registry,
            async_client=AsyncFakeClient(current.client),
            async_registry=AsyncMemoryRegistry(current.registry.values),
        )
    )
    context = RunContext(run_id="run", session_id="thread")
    started = await toolkit.sandbox_exec("pytest", background=True, run_context=context)
    process = current.sandbox_for("thread").process
    command = process.sessions[started["sessionId"]].commands[0]
    command.exit_code = 0
    command.output = "甲乙\n"

    with pytest.raises(WorkspaceError, match="UTF-8 字符"):
        await toolkit.sandbox_process_poll(
            started["sessionId"], started["commandId"], max_bytes=1, run_context=context
        )

    first = await toolkit.sandbox_process_poll(
        started["sessionId"], started["commandId"], max_bytes=4, run_context=context
    )
    assert first["output"] == "甲"
    assert first["nextOffset"] == 3
    assert first["hasMore"] is True

    second = await toolkit.sandbox_process_poll(
        started["sessionId"],
        started["commandId"],
        offset=first["nextOffset"],
        max_bytes=4,
        run_context=context,
    )
    assert second["output"] == "乙\n"
    assert second["nextOffset"] == 7
    assert second["hasMore"] is False


def test_新建覆盖移动和系统上传保持各自语义(tmp_path):
    current = service(tmp_path)
    current.create_file("thread", "报告.md", "初稿".encode())
    with pytest.raises(WorkspacePathConflict, match="已经存在.*覆盖文件工具"):
        current.create_file("thread", "报告.md", "误覆盖".encode())

    current.replace_file("thread", "报告.md", "终稿".encode())
    assert current.read_text("thread", "报告.md") == "终稿"
    with pytest.raises(WorkspaceError, match="不存在.*新建"):
        current.replace_file("thread", "缺失.md", b"content")

    current.upload("thread", "兼容.txt", b"one")
    current.upload("thread", "兼容.txt", b"two")
    assert current.read_text("thread", "兼容.txt") == "two"

    current.create_file("thread", "来源.txt", b"source")
    current.create_file("thread", "目标.txt", b"target")
    with pytest.raises(WorkspaceError, match="目标路径已经存在"):
        current.move_file("thread", "来源.txt", "目标.txt")
    assert current.read_text("thread", "来源.txt") == "source"

    sandbox = current.sandbox_for("thread")
    sandbox.fs.entries[f"{WORKSPACE_ROOT}/管道"] = (
        Info("管道", mode="prw-------"),
        b"",
    )
    with pytest.raises(WorkspaceError, match="不是普通文件"):
        current.replace_file("thread", "管道", b"content")
    sandbox.fs.create_folder(f"{WORKSPACE_ROOT}/目录", "700")
    with pytest.raises(WorkspaceError, match="自身或其子目录"):
        current.move_file("thread", "目录", "目录/子目录")


def test_完整变更集支持新建更新删除移动(tmp_path):
    current = service(tmp_path)
    current.create_file("thread", "update.txt", b"before update\n")
    current.create_file("thread", "delete.txt", b"delete me\n")
    current.create_file("thread", "move.txt", b"move me\n")
    context = RunContext(run_id="run", session_id="thread")
    tool = BaseToolkit(current).functions["workspace_apply_changes"]

    result = tool.entrypoint(
        changes=[
            {"operation": "create", "path": "created.txt", "content": "created\n"},
            {
                "operation": "update",
                "path": "update.txt",
                "content": "after update\n",
                "expected_sha256": current.hash_file("thread", "update.txt")["sha256"],
            },
            {
                "operation": "delete",
                "path": "delete.txt",
                "expected_sha256": current.hash_file("thread", "delete.txt")["sha256"],
            },
            {
                "operation": "move",
                "path": "move.txt",
                "destination": "nested/moved.txt",
                "expected_sha256": current.hash_file("thread", "move.txt")["sha256"],
            },
        ],
        run_context=context,
    )

    assert result["operations"] == 4
    assert [item["operation"] for item in result["files"]] == [
        "create",
        "update",
        "delete",
        "move",
    ]
    assert current.read_text("thread", "created.txt") == "created\n"
    assert current.read_text("thread", "update.txt") == "after update\n"
    with pytest.raises(WorkspaceError, match="不存在"):
        current.read_text("thread", "delete.txt")
    with pytest.raises(WorkspaceError, match="不存在"):
        current.read_text("thread", "move.txt")
    assert current.read_text("thread", "nested/moved.txt") == "move me\n"


def test_结构化创建目录和复制文件保持边界(tmp_path):
    current = service(tmp_path)
    current.create_file("thread", "source.txt", b"source\n")
    tools = BaseToolkit(current).functions
    context = RunContext(run_id="run", session_id="thread")

    created = tools["workspace_create_directory"].entrypoint(
        path="nested/empty", run_context=context
    )
    copied = tools["workspace_copy_file"].entrypoint(
        source="source.txt", destination="nested/copied.txt", run_context=context
    )

    assert created == {"path": "nested/empty", "status": "created"}
    assert copied["path"] == "nested/copied.txt"
    assert copied["sha256"] == current.hash_file("thread", "source.txt")["sha256"]
    assert current.read_text("thread", "nested/copied.txt") == "source\n"
    with pytest.raises(WorkspacePathConflict, match="已经存在"):
        tools["workspace_copy_file"].entrypoint(
            source="source.txt", destination="nested/copied.txt", run_context=context
        )


def test_完整变更集预检冲突零写入且执行失败会回滚(tmp_path, monkeypatch):
    current = service(tmp_path)
    current.create_file("thread", "a.txt", b"before a\n")
    current.create_file("thread", "b.txt", b"before b\n")
    tool = BaseToolkit(current).functions["workspace_apply_changes"]
    context = RunContext(run_id="run", session_id="thread")
    a_hash = current.hash_file("thread", "a.txt")["sha256"]

    with pytest.raises(WorkspacePathConflict, match="文件内容已变化"):
        tool.entrypoint(
            changes=[
                {
                    "operation": "update",
                    "path": "a.txt",
                    "content": "after a\n",
                    "expected_sha256": a_hash,
                },
                {
                    "operation": "update",
                    "path": "b.txt",
                    "content": "after b\n",
                    "expected_sha256": "0" * 64,
                },
            ],
            run_context=context,
        )
    assert current.read_text("thread", "a.txt") == "before a\n"
    assert current.read_text("thread", "b.txt") == "before b\n"

    b_hash = current.hash_file("thread", "b.txt")["sha256"]
    original_replace = current.replace_file

    def fail_second_update(thread, path, content):
        if path == "b.txt" and content == b"after b\n":
            raise RuntimeError("write failed")
        return original_replace(thread, path, content)

    monkeypatch.setattr(current, "replace_file", fail_second_update)
    with pytest.raises(RuntimeError, match="write failed"):
        tool.entrypoint(
            changes=[
                {
                    "operation": "update",
                    "path": "a.txt",
                    "content": "after a\n",
                    "expected_sha256": a_hash,
                },
                {
                    "operation": "update",
                    "path": "b.txt",
                    "content": "after b\n",
                    "expected_sha256": b_hash,
                },
            ],
            run_context=context,
        )
    assert current.read_text("thread", "a.txt") == "before a\n"
    assert current.read_text("thread", "b.txt") == "before b\n"


def test_create_file_locked_serializes_same_thread_and_path(tmp_path):
    current = service(tmp_path)

    def create(content):
        try:
            return current.create_file_locked("thread", "exports/report.csv", content)
        except WorkspacePathConflict:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(create, (b"first", b"second")))

    assert results.count("conflict") == 1
    assert sum(isinstance(result, dict) for result in results) == 1
    assert current.file_bytes("thread", "exports/report.csv")[0] in {b"first", b"second"}


def test_智能体新建覆盖和安全移动返回中文提示(tmp_path):
    current = service(tmp_path)
    toolkit = BaseToolkit(current)
    tools = toolkit.functions
    context = RunContext(run_id="run", session_id="thread")

    created = tools["workspace_write_file"].entrypoint(
        path="新建.txt",
        content="内容",
        run_context=context,
    )
    replaced = tools["workspace_replace_file"].entrypoint(
        path="新建.txt",
        content="新内容",
        run_context=context,
    )
    moved = tools["workspace_move_file"].entrypoint(
        source="新建.txt",
        destination="已移动.txt",
        run_context=context,
    )

    assert created["message"] == "文件已新建。"
    assert replaced["message"] == "文件已覆盖。"
    assert moved["message"] == "文件或目录已移动。"


@pytest.mark.parametrize(
    "path",
    [
        "报表/原始数据/11111111-1111-4111-8111-111111111111/分片/数据-0001.jsonl",
        "reports/data/legacy.jsonl",
    ],
)
def test_智能体文本工具禁止读取受控原始报表分片(tmp_path, path):
    current = service(tmp_path)
    current.upload("thread", path, b'{"secret":"raw"}\n')
    current_tools = BaseToolkit(current).functions

    with pytest.raises(WorkspaceError, match="不能进入智能体上下文"):
        current_tools["workspace_read_file"].entrypoint(
            path=path,
            run_context=RunContext(run_id="run", session_id="thread"),
        )
    assert current.file_bytes("thread", path)[0] == b'{"secret":"raw"}\n'


def test_中文路径长度层级控制字符和目录穿越受到限制(tmp_path):
    current = service(tmp_path)
    current.create_file("thread", "资料/报告.md", "内容".encode())
    assert current.read_text("thread", "资料/报告.md") == "内容"

    valid_boundary = "/".join(["a" * 204] * 5)
    assert len(valid_boundary.encode()) == MAX_PATH_BYTES
    assert current.normalize_path(valid_boundary)[0] == valid_boundary

    with pytest.raises(WorkspaceError, match="超过 1024 字节"):
        current.normalize_path("/".join(["a" * 205] + ["a" * 204] * 4))
    with pytest.raises(WorkspaceError, match="名称超过 255 字节"):
        current.normalize_path("a" * (MAX_PATH_COMPONENT_BYTES + 1))
    with pytest.raises(WorkspaceError, match="目录层级超过 32 层"):
        current.normalize_path("/".join(["a"] * (MAX_PATH_DEPTH + 1)))
    with pytest.raises(WorkspaceError, match="控制字符"):
        current.normalize_path("资料/报\n告.md")
    with pytest.raises(WorkspaceError, match="控制字符"):
        current.normalize_path("资料/报\x85告.md")
    with pytest.raises(WorkspaceError, match="目录穿越"):
        current.normalize_path("资料/../报告.md")
    with pytest.raises(WorkspaceError, match="绝对路径"):
        current.normalize_path("C:\\Windows\\system.ini")


def test_中文文件使用流式下载并限制实际返回大小(tmp_path, monkeypatch):
    current = service(tmp_path)
    current.create_file("thread", "资料/报告.md", "内容".encode())
    sandbox = current.sandbox_for("thread")
    remote = f"{WORKSPACE_ROOT}/资料/报告.md"
    sandbox.fs.download_file = lambda _path: (_ for _ in ()).throw(
        AssertionError("中文路径不应使用 bulk 下载")
    )

    assert current.file_bytes("thread", "资料/报告.md")[0] == "内容".encode()
    assert current.read_text("thread", "资料/报告.md") == "内容"
    assert sandbox.fs.stream_download_calls == [remote, remote]

    monkeypatch.setattr(workspace_module, "MAX_DOWNLOAD_BYTES", 4)
    sandbox.fs.entries[remote][0].size = 4
    with pytest.raises(WorkspaceError, match="超过允许大小"):
        current.file_bytes("thread", "资料/报告.md")


def test_文本读取严格区分目录二进制非_utf8_和大小边界(tmp_path):
    current = service(tmp_path)
    sandbox = current.sandbox_for("thread")
    sandbox.fs.create_folder(f"{WORKSPACE_ROOT}/目录", "700")
    current.upload("thread", "二进制.bin", b"a\x00b")
    current.upload("thread", "非编码.txt", b"\xff")
    current.upload("thread", "边界.txt", b"x" * MAX_READ_BYTES)
    current.upload("thread", "过大.txt", b"x" * (MAX_READ_BYTES + 1))

    with pytest.raises(WorkspaceError, match="目录.*文本文件"):
        current.read_text("thread", "目录")
    with pytest.raises(WorkspaceError, match="二进制内容"):
        current.read_text("thread", "二进制.bin")
    with pytest.raises(WorkspaceError, match="不是 UTF-8"):
        current.read_text("thread", "非编码.txt")
    assert len(current.read_text("thread", "边界.txt")) == MAX_READ_BYTES
    with pytest.raises(WorkspaceError, match="超过 1 MB"):
        current.read_text("thread", "过大.txt")


def test_沙箱启动异常多实例与后端故障均明确处理(tmp_path):
    current = service(tmp_path)
    sandbox = current.sandbox_for("thread")
    sandbox.state = "starting"
    with pytest.raises(WorkspaceError, match="正在启动"):
        current.sandbox_for("thread")
    sandbox.state = "error"
    with pytest.raises(WorkspaceError, match="状态异常"):
        current.sandbox_for("thread")
    sandbox.state = "stopped"
    assert current.sandbox_for("thread").state == "started"

    duplicate_client = FakeClient()
    duplicate = service(tmp_path, duplicate_client)
    label = duplicate._hash("duplicate")
    duplicate_client.sandboxes = {
        "one": FakeSandbox("one", {"agui-thread": label}),
        "two": FakeSandbox("two", {"agui-thread": label}),
    }
    with pytest.raises(WorkspaceError, match="多个运行环境"):
        duplicate.sandbox_for("duplicate")

    missing_root = FakeSandbox("missing", {})
    missing_root.fs.entries.pop(WORKSPACE_ROOT)
    current._ensure_directory(missing_root, WORKSPACE_ROOT)
    assert WORKSPACE_ROOT in missing_root.fs.entries

    broken = FakeSandbox("broken", {})
    broken.fs.get_file_info = lambda _path: (_ for _ in ()).throw(RuntimeError("backend failed"))
    with pytest.raises(RuntimeError, match="backend failed"):
        current._ensure_directory(broken, WORKSPACE_ROOT)


@pytest.mark.anyio
async def test_分支工作区使用异步客户端完整复制目录和文件(tmp_path):
    current = service(tmp_path)
    current.create_file("source", "资料/报告.txt", "内容".encode())
    current.create_file("source", "根文件.bin", b"binary")
    async_service = WorkspaceService(
        current.secret,
        client=current.client,
        registry=current.registry,
        async_client=AsyncFakeClient(current.client),
        async_registry=AsyncMemoryRegistry(current.registry.values),
    )

    result = await async_service.acopy_branch("source", "target")

    assert result == {"files": 2, "bytes": len("内容".encode()) + 6}
    assert current.file_bytes("target", "资料/报告.txt")[0] == "内容".encode()
    assert current.file_bytes("target", "根文件.bin")[0] == b"binary"
    assert current.file_bytes("source", "根文件.bin")[0] == b"binary"


@pytest.mark.anyio
async def test_异步分支工作区先校验限制和符号链接再创建目标(tmp_path, monkeypatch):
    current = service(tmp_path)
    current.create_file("source", "一.txt", b"1")
    current.create_file("source", "二.txt", b"22")
    async_service = WorkspaceService(
        current.secret,
        client=current.client,
        registry=current.registry,
        async_client=AsyncFakeClient(current.client),
        async_registry=AsyncMemoryRegistry(current.registry.values),
    )
    monkeypatch.setattr(workspace_module, "MAX_BRANCH_FILES", 1)

    with pytest.raises(WorkspaceError, match="文件数超过"):
        await async_service.acopy_branch("source", "too-many")
    assert current.sandbox_for("too-many", create=False) is None

    monkeypatch.setattr(workspace_module, "MAX_BRANCH_FILES", 2000)
    monkeypatch.setattr(workspace_module, "MAX_BRANCH_TOTAL_BYTES", 2)
    with pytest.raises(WorkspaceError, match="总大小超过"):
        await async_service.acopy_branch("source", "too-large")
    assert current.sandbox_for("too-large", create=False) is None

    monkeypatch.setattr(workspace_module, "MAX_BRANCH_TOTAL_BYTES", 256 * 1024 * 1024)
    source = current.sandbox_for("source")
    source.fs.entries[f"{WORKSPACE_ROOT}/link"] = (
        Info("link", mode="lrwxrwxrwx"),
        b"",
    )
    with pytest.raises(WorkspaceError, match="符号链接"):
        await async_service.acopy_branch("source", "linked")
    assert current.sandbox_for("linked", create=False) is None


@pytest.mark.anyio
async def test_异步分支工作区复制失败会清理目标(tmp_path):
    current = service(tmp_path)
    current.create_file("source", "report.txt", b"content")
    source = current.sandbox_for("source")
    source.fs.download_file = lambda _path: (_ for _ in ()).throw(RuntimeError("offline"))
    async_service = WorkspaceService(
        current.secret,
        client=current.client,
        registry=current.registry,
        async_client=AsyncFakeClient(current.client),
        async_registry=AsyncMemoryRegistry(current.registry.values),
    )

    with pytest.raises(RuntimeError, match="offline"):
        await async_service.acopy_branch("source", "target")

    assert current.sandbox_for("target", create=False) is None
    assert async_service._cached_sandbox_id(async_service._hash("target")) is None


@pytest.mark.anyio
async def test_异步分支工作区复制被取消也会清理目标(tmp_path, monkeypatch):
    current = service(tmp_path)
    current.create_file("source", "报告.txt", b"content")
    download_started = asyncio.Event()
    never_complete = asyncio.Event()

    async def blocking_download(_self, _path):
        download_started.set()
        await never_complete.wait()

    monkeypatch.setattr(AsyncFakeFs, "download_file_stream", blocking_download)
    async_service = WorkspaceService(
        current.secret,
        client=current.client,
        registry=current.registry,
        async_client=AsyncFakeClient(current.client),
        async_registry=AsyncMemoryRegistry(current.registry.values),
    )

    copy_task = asyncio.create_task(async_service.acopy_branch("source", "target"))
    await download_started.wait()
    copy_task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await copy_task

    assert current.sandbox_for("target", create=False) is None
    assert async_service._cached_sandbox_id(async_service._hash("target")) is None


@pytest.mark.integration
def test_数据库注册表会串行化两个工作区服务():
    client = FakeClient()
    thread = "concurrent-" + uuid.uuid4().hex
    first = WorkspaceService(SECRET, client=client, registry=SandboxRegistry())
    second = WorkspaceService(SECRET, client=client, registry=SandboxRegistry())
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            sandboxes = list(pool.map(lambda service: service.sandbox_for(thread), [first, second]))
        assert sandboxes[0].id == sandboxes[1].id
        assert len(client.created) == 1
    finally:
        first.destroy(thread)

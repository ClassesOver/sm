import asyncio
import hashlib
import json
import os
import subprocess
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager, contextmanager

import pytest
from sqlalchemy import delete, select

import smart_reporting.workspace as workspace_module
from smart_reporting.runtime.database import create_agent_database
from smart_reporting.sandbox import IsolationKind, ProviderKind, SandboxRef
from smart_reporting.tests.workspace_fakes import (
    SECRET,
    AsyncFakeClient,
    AsyncFakeFs,
    AsyncFakeSandbox,
    AsyncMemoryRegistry,
    FakeClient,
    FakeSandbox,
    Info,
    service,
)
from smart_reporting.workspace import (
    MAX_BATCH_HASH_CONCURRENCY,
    MAX_BATCH_HASH_FILE_TIMEOUT,
    MAX_DOWNLOAD_BYTES,
    MAX_PATH_BYTES,
    MAX_PATH_COMPONENT_BYTES,
    MAX_PATH_DEPTH,
    MAX_READ_BYTES,
    WORKSPACE_ROOT,
    WORKSPACE_SNAPSHOT,
    AsyncSandboxRegistry,
    SandboxRegistry,
    WorkspaceError,
    WorkspacePathConflict,
    WorkspaceService,
)


@pytest.mark.anyio
async def test_workspace_service_uses_provider_handle_for_hashing() -> None:
    class Provider:
        def __init__(self) -> None:
            self.bindings = []
            raw_sandbox = FakeSandbox("provider-1", {})
            raw_sandbox.fs.upload_file(b'{"ok":true}', f"{WORKSPACE_ROOT}/result.json")
            sandbox = AsyncFakeSandbox(raw_sandbox)
            sandbox.ref = SandboxRef(
                provider=ProviderKind.LOCAL,
                isolation=IsolationKind.LINUX_PROCESS,
                node="node-a",
                resource_id="provider-1",
                generation=1,
                binding_digest="a" * 64,
            )
            self.sandbox = sandbox

        async def ensure_workspace(self, binding):
            self.bindings.append(binding)
            return self.sandbox

    provider = Provider()
    current = WorkspaceService(
        SECRET,
        provider=provider,
        async_registry=AsyncMemoryRegistry({}),
    )

    result = await current.ahash_file("thread", "result.json")

    assert result == {
        "path": "result.json",
        "size": 11,
        "sha256": hashlib.sha256(b'{"ok":true}').hexdigest(),
    }
    assert provider.bindings[0].thread_id == "thread"


def _provider_workspace_service(monkeypatch) -> tuple[WorkspaceService, AsyncFakeSandbox]:
    class Provider:
        def __init__(self) -> None:
            raw_sandbox = FakeSandbox("provider-1", {})
            sandbox = AsyncFakeSandbox(raw_sandbox)
            sandbox.ref = SandboxRef(
                provider=ProviderKind.LOCAL,
                isolation=IsolationKind.LINUX_PROCESS,
                node="node-a",
                resource_id="provider-1",
                generation=1,
                binding_digest="a" * 64,
            )
            self.sandbox = sandbox

        async def ensure_workspace(self, _binding):
            return self.sandbox

    provider = Provider()
    monkeypatch.setattr(
        workspace_module,
        "Daytona",
        lambda: pytest.fail("LocalProvider 文件变更不得实例化同步 Daytona client"),
    )
    return (
        WorkspaceService(
            SECRET,
            provider=provider,
            async_registry=AsyncMemoryRegistry({}),
        ),
        provider.sandbox,
    )


@pytest.mark.anyio
async def test_async_apply_changes_creates_file_through_provider(monkeypatch) -> None:
    current, _sandbox = _provider_workspace_service(monkeypatch)

    result = await current.aapply_changes(
        "thread",
        [{"operation": "create", "path": "analysis/model.py", "content": "value = 1\n"}],
    )

    assert result["files"][0]["sha256"] == hashlib.sha256(b"value = 1\n").hexdigest()
    assert await current.aread_text("thread", "analysis/model.py") == "value = 1\n"


@pytest.mark.anyio
async def test_async_apply_changes_updates_file_through_provider(monkeypatch) -> None:
    current, sandbox = _provider_workspace_service(monkeypatch)
    await sandbox.fs.create_folder(f"{WORKSPACE_ROOT}/analysis", "700")
    await sandbox.fs.upload_file(b"value = 1\n", f"{WORKSPACE_ROOT}/analysis/model.py")

    await current.aapply_changes(
        "thread",
        [
            {
                "operation": "update",
                "path": "analysis/model.py",
                "content": "value = 2\n",
                "expected_sha256": hashlib.sha256(b"value = 1\n").hexdigest(),
            }
        ],
    )

    assert await current.aread_text("thread", "analysis/model.py") == "value = 2\n"


@pytest.mark.anyio
async def test_async_apply_changes_rejects_hash_conflict_without_writing(monkeypatch) -> None:
    current, sandbox = _provider_workspace_service(monkeypatch)
    await sandbox.fs.create_folder(f"{WORKSPACE_ROOT}/analysis", "700")
    await sandbox.fs.upload_file(b"value = 1\n", f"{WORKSPACE_ROOT}/analysis/model.py")

    with pytest.raises(WorkspacePathConflict, match="文件内容已变化"):
        await current.aapply_changes(
            "thread",
            [
                {
                    "operation": "update",
                    "path": "analysis/model.py",
                    "content": "value = 2\n",
                    "expected_sha256": "0" * 64,
                }
            ],
        )

    assert await current.aread_text("thread", "analysis/model.py") == "value = 1\n"


def test_workspace模块不再导出旧模型工具集():
    assert not hasattr(workspace_module, "DaytonaToolkit")
    assert not hasattr(workspace_module, "WorkspaceToolkit")


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
    assert list(params.labels) == ["agent-thread"]
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


@pytest.mark.anyio
async def test_quarantine_rotates_workspace_generation_without_reusing_old_sandbox(
    tmp_path,
) -> None:
    current = service(tmp_path)
    async_registry = AsyncMemoryRegistry(current.registry.values)
    async_service = WorkspaceService(
        current.secret,
        client=current.client,
        registry=current.registry,
        async_client=AsyncFakeClient(current.client),
        async_registry=async_registry,
    )

    async with async_service._async_client() as client:
        first = await async_service._asandbox_for(client, "thread")

    old_label = first.labels["agent-thread"]
    await async_service.aquarantine("thread")

    async with async_service._async_client() as client:
        second = await async_service._asandbox_for(client, "thread")

    assert second.id != first.id
    assert second.labels["agent-thread"] != old_label
    assert first.id in current.client.sandboxes
    assert async_registry.cleanup_labels == {old_label}

    assert await async_service.acleanup_quarantined() == 1
    assert first.id not in current.client.sandboxes
    assert async_registry.cleanup_labels == set()


@pytest.mark.anyio
async def test_quarantined_cleanup_job_survives_temporary_daytona_failure(tmp_path) -> None:
    current = service(tmp_path)
    async_registry = AsyncMemoryRegistry(current.registry.values)

    class FailingListClient(AsyncFakeClient):
        async def list(self, query):
            del query
            raise RuntimeError("temporary auth failure")
            yield

    async_service = WorkspaceService(
        current.secret,
        client=current.client,
        registry=current.registry,
        async_client=AsyncFakeClient(current.client),
        async_registry=async_registry,
    )
    async with async_service._async_client() as client:
        first = await async_service._asandbox_for(client, "thread")
    old_label = first.labels["agent-thread"]
    await async_service.aquarantine("thread")
    async_service._async_client_override = FailingListClient(current.client)

    assert await async_service.acleanup_quarantined() == 0
    assert first.id in current.client.sandboxes
    assert async_registry.cleanup_labels == {old_label}


@pytest.mark.anyio
async def test_sandbox_service_probe_uses_read_only_bounded_list() -> None:
    queries = []
    iterator_closed = False

    class ProbeClient:
        async def list(self, query):
            nonlocal iterator_closed
            queries.append(query)
            try:
                yield object()
                await asyncio.Event().wait()
            finally:
                iterator_closed = True

    current = WorkspaceService(
        SECRET,
        async_client=ProbeClient(),
        async_registry=AsyncMemoryRegistry({}),
    )

    await current.check_sandbox_service()

    assert len(queries) == 1
    assert queries[0].limit == 1
    assert iterator_closed is True


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
    first = FakeSandbox("sandbox-1", {"agent-thread": value})
    second = FakeSandbox("sandbox-2", {"agent-thread": value})
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
async def test_异步文件哈希接受_json_回执(tmp_path):
    current = service(tmp_path)
    current.create_file("thread", "dataset.csv", b"report")
    sandbox = current.sandbox_for("thread")
    digest = hashlib.sha256(b"report").hexdigest()

    def execute_hash(command, cwd=None, timeout=None):
        sandbox.process.calls.append({"command": command, "cwd": cwd, "timeout": timeout})
        return type(
            "Result",
            (),
            {"result": json.dumps({"sha256": digest, "size": 6}) + "\n", "exit_code": 0},
        )()

    sandbox.process.exec = execute_hash
    async_service = WorkspaceService(
        current.secret,
        client=current.client,
        registry=current.registry,
        async_client=AsyncFakeClient(current.client),
        async_registry=AsyncMemoryRegistry(current.registry.values),
    )

    assert await async_service.ahash_file("thread", "dataset.csv") == {
        "path": "dataset.csv",
        "size": 6,
        "sha256": digest,
    }


@pytest.mark.anyio
async def test_异步文件哈希执行真实_shell_json回执(tmp_path):
    current = service(tmp_path)
    current.create_file("thread", "dataset.csv", b"report")
    (tmp_path / "dataset.csv").write_bytes(b"report")
    sandbox = current.sandbox_for("thread")

    def execute_hash(command, cwd=None, timeout=None):
        sandbox.process.calls.append({"command": command, "cwd": cwd, "timeout": timeout})
        local_command = command.replace(WORKSPACE_ROOT, str(tmp_path))
        completed = subprocess.run(
            local_command,
            shell=True,
            check=False,
            capture_output=True,
            text=True,
        )
        return type(
            "Result",
            (),
            {"result": completed.stdout, "exit_code": completed.returncode},
        )()

    sandbox.process.exec = execute_hash
    async_service = WorkspaceService(
        current.secret,
        client=current.client,
        registry=current.registry,
        async_client=AsyncFakeClient(current.client),
        async_registry=AsyncMemoryRegistry(current.registry.values),
    )

    assert await async_service.ahash_file("thread", "dataset.csv") == {
        "path": "dataset.csv",
        "size": 6,
        "sha256": hashlib.sha256(b"report").hexdigest(),
    }


@pytest.mark.anyio
async def test_异步文件哈希从_artifacts_stdout_读取回执(tmp_path):
    current = service(tmp_path)
    current.create_file("thread", "dataset.csv", b"report")
    sandbox = current.sandbox_for("thread")
    digest = hashlib.sha256(b"report").hexdigest()

    def execute_hash(command, cwd=None, timeout=None):
        sandbox.process.calls.append({"command": command, "cwd": cwd, "timeout": timeout})
        return type(
            "Result",
            (),
            {
                "result": "",
                "artifacts": type(
                    "Artifacts",
                    (),
                    {"stdout": json.dumps({"sha256": digest, "size": 6}) + "\n"},
                )(),
                "exit_code": 0,
            },
        )()

    sandbox.process.exec = execute_hash
    async_service = WorkspaceService(
        current.secret,
        client=current.client,
        registry=current.registry,
        async_client=AsyncFakeClient(current.client),
        async_registry=AsyncMemoryRegistry(current.registry.values),
    )

    assert await async_service.ahash_file("thread", "dataset.csv") == {
        "path": "dataset.csv",
        "size": 6,
        "sha256": digest,
    }


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


@pytest.mark.anyio
async def test_批量哈希限制并发且保持输入顺序和缺失语义(tmp_path, monkeypatch):
    current = service(tmp_path)
    paths = [f"file-{index}.txt" for index in range(MAX_BATCH_HASH_CONCURRENCY + 2)]
    for index, path in enumerate(paths):
        current.create_file("thread", path, str(index).encode())

    active_downloads = 0
    max_active_downloads = 0
    original_download = AsyncFakeFs.download_file_stream
    download_timeouts = []

    async def tracked_download(fake_fs, path, timeout=30 * 60):
        nonlocal active_downloads, max_active_downloads
        active_downloads += 1
        max_active_downloads = max(max_active_downloads, active_downloads)
        download_timeouts.append(timeout)
        try:
            await asyncio.sleep(0)
            return await original_download(fake_fs, path, timeout=timeout)
        finally:
            active_downloads -= 1

    monkeypatch.setattr(AsyncFakeFs, "download_file_stream", tracked_download)
    async_service = WorkspaceService(
        current.secret,
        client=current.client,
        registry=current.registry,
        async_client=AsyncFakeClient(current.client),
        async_registry=AsyncMemoryRegistry(current.registry.values),
    )
    requested = [paths[-1], "missing.txt", *paths[:-1]]

    results = await async_service.abatch_hash_files("thread", requested)

    assert [item["path"] for item in results] == requested
    assert results[1] == {"path": "missing.txt", "missing": True}
    assert 1 < max_active_downloads <= MAX_BATCH_HASH_CONCURRENCY
    assert download_timeouts == [MAX_BATCH_HASH_FILE_TIMEOUT] * len(paths)


@pytest.mark.anyio
async def test_异步下载对英文和中文路径统一使用带超时的流式接口(tmp_path, monkeypatch):
    current = service(tmp_path)
    current.create_file("thread", "report.md", b"ascii")
    current.create_file("thread", "报告.md", b"unicode")
    calls = []
    original_download = AsyncFakeFs.download_file_stream

    async def tracked_download(fake_fs, path, timeout=30 * 60):
        calls.append((path, timeout))
        return await original_download(fake_fs, path, timeout=timeout)

    monkeypatch.setattr(AsyncFakeFs, "download_file_stream", tracked_download)
    async_service = WorkspaceService(
        current.secret,
        client=current.client,
        registry=current.registry,
        async_client=AsyncFakeClient(current.client),
        async_registry=AsyncMemoryRegistry(current.registry.values),
    )
    sandbox = await async_service._asandbox_for(async_service._async_client_override, "thread")

    assert (
        await async_service._adownload_file(
            sandbox, f"{WORKSPACE_ROOT}/report.md", MAX_DOWNLOAD_BYTES, timeout=7
        )
        == b"ascii"
    )
    assert (
        await async_service._adownload_file(
            sandbox, f"{WORKSPACE_ROOT}/报告.md", MAX_DOWNLOAD_BYTES, timeout=9
        )
        == b"unicode"
    )
    assert calls == [
        (f"{WORKSPACE_ROOT}/report.md", 7),
        (f"{WORKSPACE_ROOT}/报告.md", 9),
    ]


@pytest.mark.anyio
async def test_批量哈希流式下载超时后明确失败(tmp_path, monkeypatch):
    current = service(tmp_path)
    current.create_file("thread", "报告.md", b"report")
    download_started = asyncio.Event()
    never_complete = asyncio.Event()

    async def blocking_download(_self, _path, timeout=30 * 60):
        download_started.set()
        await never_complete.wait()

    monkeypatch.setattr(AsyncFakeFs, "download_file_stream", blocking_download)
    monkeypatch.setattr(workspace_module, "MAX_BATCH_HASH_TIMEOUT", 0.01)
    async_service = WorkspaceService(
        current.secret,
        client=current.client,
        registry=current.registry,
        async_client=AsyncFakeClient(current.client),
        async_registry=AsyncMemoryRegistry(current.registry.values),
    )

    with pytest.raises(WorkspaceError, match="批量哈希读取超时"):
        await async_service.abatch_hash_files("thread", ["报告.md"])
    assert download_started.is_set()


@pytest.mark.anyio
async def test_批量哈希使用隔离客户端并在完成后关闭(tmp_path, monkeypatch):
    current = service(tmp_path)
    current.create_file("thread", "report.md", b"report")
    instances = []

    class IsolatedClient(AsyncFakeClient):
        def __init__(self):
            super().__init__(current.client)
            self.closed = False
            instances.append(self)

        async def close(self):
            self.closed = True

    monkeypatch.setattr(workspace_module, "AsyncDaytona", IsolatedClient)
    async_service = WorkspaceService(
        current.secret,
        client=current.client,
        registry=current.registry,
        async_registry=AsyncMemoryRegistry(current.registry.values),
    )

    result = await async_service.abatch_hash_files("thread", ["report.md"])

    assert result == [
        {
            "path": "report.md",
            "size": 6,
            "sha256": hashlib.sha256(b"report").hexdigest(),
        }
    ]
    assert len(instances) == 1
    assert instances[0].closed is True
    assert async_service._owned_async_client is None


@pytest.mark.anyio
async def test_批量哈希不会因隔离客户端关闭阻塞(tmp_path, monkeypatch):
    current = service(tmp_path)
    current.create_file("thread", "report.md", b"report")
    close_started = asyncio.Event()
    never_complete = asyncio.Event()

    class BlockingCloseClient(AsyncFakeClient):
        async def close(self):
            close_started.set()
            await never_complete.wait()

    monkeypatch.setattr(
        workspace_module,
        "AsyncDaytona",
        lambda: BlockingCloseClient(current.client),
    )
    monkeypatch.setattr(workspace_module, "MAX_ISOLATED_CLIENT_CLOSE_TIMEOUT", 0.01)
    async_service = WorkspaceService(
        current.secret,
        client=current.client,
        registry=current.registry,
        async_registry=AsyncMemoryRegistry(current.registry.values),
    )

    result = await async_service.abatch_hash_files("thread", ["report.md"])

    assert result[0]["sha256"] == hashlib.sha256(b"report").hexdigest()
    assert close_started.is_set()


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
        "one": FakeSandbox("one", {"agent-thread": label}),
        "two": FakeSandbox("two", {"agent-thread": label}),
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

    def offline_stream(_path):
        raise RuntimeError("offline")
        yield b""  # pragma: no cover

    source.fs.download_file_stream = offline_stream
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

    async def blocking_download(_self, _path, timeout=30 * 60):
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


@pytest.mark.integration
@pytest.mark.anyio
async def test_postgres注册表持久化工作区隔离并跨同步异步实例可见():
    database_url = os.getenv("REPORTING_TEST_DB_URL", "").strip()
    if not database_url:
        pytest.skip("未设置 REPORTING_TEST_DB_URL，跳过 PostgreSQL workspace 集成测试。")
    first_database = create_agent_database(database_url)
    restarted_database = create_agent_database(database_url)
    first = AsyncSandboxRegistry(first_database.async_db)
    restarted = AsyncSandboxRegistry(restarted_database.async_db)
    sync_registry = SandboxRegistry(restarted_database.sync_db)
    base_label = hashlib.sha256(f"integration-workspace-{uuid.uuid4().hex}".encode()).hexdigest()

    try:
        assert await first.workspace_label(base_label) == base_label
        async with first.locked(base_label) as transaction:
            await transaction.set(base_label, "integration-old-sandbox")

        assert await first.quarantine_workspace(base_label) == base_label
        rotated_label = await restarted.workspace_label(base_label)

        assert rotated_label != base_label
        assert await asyncio.to_thread(sync_registry.workspace_label, base_label) == rotated_label
        async with restarted.locked(base_label) as transaction:
            assert await transaction.get(base_label) is None
        async with restarted._connect() as connection:
            cleanup_label = (
                await connection.execute(
                    select(restarted.cleanup_table.c.workspace_label).where(
                        restarted.cleanup_table.c.workspace_label == base_label
                    )
                )
            ).scalar_one_or_none()
        assert cleanup_label == base_label

        await restarted.complete_cleanup(base_label)
        async with first._connect() as connection:
            cleanup_label = (
                await connection.execute(
                    select(first.cleanup_table.c.workspace_label).where(
                        first.cleanup_table.c.workspace_label == base_label
                    )
                )
            ).scalar_one_or_none()
        assert cleanup_label is None
    finally:
        await first.ensure_initialized()
        async with first._connect() as connection:
            async with connection.begin():
                await connection.execute(
                    delete(first.cleanup_table).where(
                        first.cleanup_table.c.workspace_label == base_label
                    )
                )
                await connection.execute(
                    delete(first.generation_table).where(
                        first.generation_table.c.thread_hash == base_label
                    )
                )
                await connection.execute(
                    delete(first.table).where(first.table.c.thread_hash == base_label)
                )
        await first_database.async_engine.dispose()
        first_database.sync_engine.dispose()
        await restarted_database.async_engine.dispose()
        restarted_database.sync_engine.dispose()

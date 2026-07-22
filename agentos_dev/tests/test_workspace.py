import asyncio
import hashlib
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from agno.run import RunContext

import agentos_dev.workspace as workspace_module
from agentos_dev.skills import SecureSkills
from agentos_dev.tests.workspace_fakes import (
    SECRET,
    AsyncFakeClient,
    AsyncFakeFs,
    AsyncMemoryRegistry,
    FakeClient,
    FakeSandbox,
    Info,
    service,
)
from agentos_dev.workspace import (
    MAX_EXECUTION_TIMEOUT,
    MAX_PATH_BYTES,
    MAX_PATH_COMPONENT_BYTES,
    MAX_PATH_DEPTH,
    MAX_READ_BYTES,
    MAX_SCRIPT_ARG_BYTES,
    MAX_SCRIPT_BYTES,
    MAX_UPLOAD_BYTES,
    WORKSPACE_ROOT,
    SandboxRegistry,
    WorkspaceError,
    WorkspacePathConflict,
    WorkspaceService,
    workspace_tools,
)


def test_每个对话使用独立持久沙箱且注册表可跨服务复用(tmp_path):
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
    assert params.auto_stop_interval == 60
    assert list(params.labels) == ["agui-thread"]
    assert "thread-one" not in str(params.labels)

    restarted = WorkspaceService(SECRET, client=client, registry=first.registry)
    assert restarted.sandbox_for("thread-one").id == one.id
    assert len(client.created) == 2


def test_路径大小符号链接和销毁边界均生效(tmp_path):
    current = service(tmp_path)
    with pytest.raises(WorkspaceError, match="目录穿越"):
        current.upload("thread", "../escape", b"bad")
    with pytest.raises(WorkspaceError, match="绝对路径"):
        current.list_files("thread", "/etc")
    with pytest.raises(WorkspaceError, match="10 MB"):
        current.upload("thread", "large.bin", b"x" * (MAX_UPLOAD_BYTES + 1))

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


def test_工具确认边界与可信技能注册符合策略(tmp_path):
    no_skill_tools = {
        tool.name: tool for tool in workspace_tools(service(tmp_path), SecureSkills([]))
    }
    assert set(no_skill_tools) == {
        "workspace_list_files",
        "workspace_read_file",
        "workspace_write_file",
        "workspace_move_file",
        "workspace_replace_file",
        "workspace_delete_file",
    }
    for name in (
        "workspace_list_files",
        "workspace_read_file",
        "workspace_write_file",
        "workspace_move_file",
    ):
        assert no_skill_tools[name].requires_confirmation is not True
        assert no_skill_tools[name].description
    for name in ("workspace_replace_file", "workspace_delete_file"):
        assert no_skill_tools[name].requires_confirmation is True

    fake_skills = type(
        "可信技能",
        (),
        {
            "get_all_skills": lambda _self: [object()],
            "script_bytes": lambda *_args: b"print('ok')",
        },
    )()
    skill_tools = {tool.name: tool for tool in workspace_tools(service(tmp_path), fake_skills)}
    assert skill_tools["run_skill_script"].requires_confirmation is True
    assert "workspace_shell" not in skill_tools
    assert "workspace_run_code" not in skill_tools


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
    tools = {tool.name: tool for tool in workspace_tools(current, SecureSkills([]))}
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
    current_tools = {tool.name: tool for tool in workspace_tools(current, SecureSkills([]))}

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
    current.create_file("source", "报告.txt", b"content")
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


@pytest.mark.anyio
async def test_异步分支工作区复制被取消也会清理目标(tmp_path, monkeypatch):
    current = service(tmp_path)
    current.create_file("source", "报告.txt", b"content")
    download_started = asyncio.Event()
    never_complete = asyncio.Event()

    async def blocking_download(_self, _path):
        download_started.set()
        await never_complete.wait()

    monkeypatch.setattr(AsyncFakeFs, "download_file", blocking_download)
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


def test_技能执行输入在创建沙箱前被拒绝(tmp_path):
    current = service(tmp_path)
    fake_skills = type("Skills", (), {"script_bytes": lambda *_args: b"print('ok')"})()
    with pytest.raises(WorkspaceError, match="最多接受 20"):
        current.run_skill_script("thread", fake_skills, "review", "check.py", ["x"] * 21)
    with pytest.raises(WorkspaceError, match="1 KiB"):
        current.run_skill_script(
            "thread",
            fake_skills,
            "review",
            "check.py",
            ["界" * (MAX_SCRIPT_ARG_BYTES // 3 + 1)],
        )
    with pytest.raises(WorkspaceError, match="1 至 60 秒"):
        current.run_skill_script(
            "thread",
            fake_skills,
            "review",
            "check.py",
            timeout=MAX_EXECUTION_TIMEOUT + 1,
        )
    with pytest.raises(WorkspaceError, match="字符串列表"):
        current.run_skill_script(
            "thread",
            fake_skills,
            "review",
            "check.py",
            args="bad",
        )
    large_skills = type(
        "Skills",
        (),
        {
            "script_bytes": lambda *_args: b"x" * (MAX_SCRIPT_BYTES + 1),
        },
    )()
    with pytest.raises(WorkspaceError, match="脚本超过 256 KiB"):
        current.run_skill_script("thread", large_skills, "review", "check.py")
    assert not current.client.created


def test_技能执行接受参数和超时边界并使用内容摘要路径(tmp_path):
    current = service(tmp_path)
    content = b"print('ok')"
    fake_skills = type("Skills", (), {"script_bytes": lambda *_args: content})()

    result = current.run_skill_script(
        "thread",
        fake_skills,
        "review",
        "check.py",
        ["x" * MAX_SCRIPT_ARG_BYTES] * 20,
        timeout=MAX_EXECUTION_TIMEOUT,
    )
    assert result["exitCode"] == 0
    assert hashlib.sha256(content).hexdigest() + ".py" in result["output"]
    assert "检查结果" in result["message"]


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

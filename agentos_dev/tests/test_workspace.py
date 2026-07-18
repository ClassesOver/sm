from pathlib import PurePosixPath
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import threading
import uuid

import pytest

from agentos_dev.workspace import (
    MAX_UPLOAD_BYTES,
    MAX_CODE_BYTES,
    MAX_SCRIPT_ARG_BYTES,
    MAX_SHELL_BYTES,
    SandboxRegistry,
    WorkspaceError,
    WorkspaceService,
    workspace_tools,
)
from agentos_dev.skills import SecureSkills


SECRET = "0123456789abcdef0123456789abcdef"


class Info:
    def __init__(self, name, is_dir=False, size=0, mode=None):
        self.name = name
        self.is_dir = is_dir
        self.size = size
        self.mode = mode or ("drwx------" if is_dir else "-rw-------")
        self.modified_at = "2026-07-17T00:00:00Z"
        self.mod_time = self.modified_at
        self.additional_properties = {}


class FakeFs:
    def __init__(self):
        self.entries = {"/home/daytona/workspace": (Info("workspace", True), b"")}

    def get_file_info(self, path):
        if path not in self.entries:
            from daytona.common.errors import DaytonaNotFoundError
            raise DaytonaNotFoundError("not found")
        return self.entries[path][0]

    def create_folder(self, path, _mode):
        self.entries[path] = (Info(PurePosixPath(path).name, True), b"")

    def upload_file(self, content, path):
        self.entries[path] = (Info(PurePosixPath(path).name, size=len(content)), bytes(content))

    def download_file(self, path):
        return self.entries[path][1]

    def list_files(self, path):
        prefix = path.rstrip("/") + "/"
        return [
            info for child, (info, _content) in self.entries.items()
            if child.startswith(prefix) and "/" not in child[len(prefix):]
        ]

    def delete_file(self, path, recursive=False):
        del self.entries[path]

    def move_files(self, source, destination):
        self.entries[destination] = self.entries.pop(source)


class FakeProcess:
    def exec(self, command, cwd=None, timeout=None):
        return type("Result", (), {"result": command, "exit_code": 0})()

    def code_run(self, code, timeout=None):
        return type("Result", (), {"result": code, "exit_code": 0})()


class FakeSandbox:
    def __init__(self, sandbox_id, labels, params=None):
        self.id = sandbox_id
        self.labels = labels
        self.params = params
        self.state = "started"
        self.fs = FakeFs()
        self.process = FakeProcess()


class FakeClient:
    def __init__(self):
        self.sandboxes = {}
        self.created = []
        self.deleted = []

    def create(self, params):
        sandbox = FakeSandbox(f"sandbox-{len(self.sandboxes) + 1}", params.labels, params)
        self.sandboxes[sandbox.id] = sandbox
        self.created.append(params)
        return sandbox

    def get(self, sandbox_id):
        if sandbox_id not in self.sandboxes:
            from daytona.common.errors import DaytonaNotFoundError
            raise DaytonaNotFoundError("not found")
        return self.sandboxes[sandbox_id]

    def list(self, query):
        return iter([
            sandbox for sandbox in self.sandboxes.values()
            if all(sandbox.labels.get(key) == value for key, value in (query.labels or {}).items())
        ])

    def start(self, sandbox):
        sandbox.state = "started"

    def delete(self, sandbox):
        self.deleted.append(sandbox.id)
        del self.sandboxes[sandbox.id]


class MemoryRegistry:
    def __init__(self):
        self.values = {}
        self.lock = threading.RLock()

    @contextmanager
    def locked(self, _value):
        with self.lock:
            yield self

    def get(self, value):
        return self.values.get(value)

    def set(self, value, sandbox_id):
        self.values[value] = sandbox_id

    def delete(self, value):
        self.values.pop(value, None)


def service(tmp_path, client=None):
    return WorkspaceService(
        SECRET,
        client=client or FakeClient(),
        registry=MemoryRegistry(),
    )


def test_each_thread_gets_private_persistent_sandbox_and_registry_survives_restart(tmp_path):
    client = FakeClient()
    first = service(tmp_path, client)
    one = first.sandbox_for("thread-one")
    two = first.sandbox_for("thread-two")

    assert one.id != two.id
    assert len(client.created) == 2
    params = client.created[0]
    assert params.public is False
    assert params.ephemeral is False
    assert params.auto_stop_interval == 60
    assert list(params.labels) == ["agui-thread"]
    assert "thread-one" not in str(params.labels)

    restarted = WorkspaceService(SECRET, client=client, registry=first.registry)
    assert restarted.sandbox_for("thread-one").id == one.id
    assert len(client.created) == 2


def test_paths_sizes_symlinks_and_destroy_are_enforced(tmp_path):
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
        Info("link", mode="lrwxrwxrwx"), b"outside",
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


def test_destroy_removes_duplicate_labeled_sandboxes_and_clears_registry(tmp_path):
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


def test_registry_initialization_is_deferred_until_first_use(monkeypatch):
    registry = SandboxRegistry("postgresql://unavailable/example")
    monkeypatch.setattr(
        registry, "_connect", lambda: (_ for _ in ()).throw(RuntimeError("offline")),
    )

    with pytest.raises(RuntimeError, match="offline"):
        registry.ensure_initialized()


def test_mutating_and_execution_tools_all_require_confirmation(tmp_path):
    tools = {tool.name: tool for tool in workspace_tools(service(tmp_path), SecureSkills([]))}
    assert tools["workspace_list_files"].requires_confirmation is not True
    assert tools["workspace_read_file"].requires_confirmation is not True
    for name in (
        "workspace_write_file", "workspace_move_file", "workspace_delete_file",
        "workspace_shell", "workspace_run_code", "run_skill_script",
    ):
        assert tools[name].requires_confirmation is True


def test_execution_inputs_are_rejected_before_sandbox_creation(tmp_path):
    current = service(tmp_path)
    with pytest.raises(WorkspaceError, match="8 KiB"):
        current.shell("thread", "界" * (MAX_SHELL_BYTES // 3 + 1))
    with pytest.raises(WorkspaceError, match="256 KiB"):
        current.run_code("thread", "界" * (MAX_CODE_BYTES // 3 + 1))
    fake_skills = type("Skills", (), {"script_bytes": lambda *_args: b"print('ok')"})()
    with pytest.raises(WorkspaceError, match="最多接受 20"):
        current.run_skill_script("thread", fake_skills, "review", "check.py", ["x"] * 21)
    with pytest.raises(WorkspaceError, match="1 KiB"):
        current.run_skill_script(
            "thread", fake_skills, "review", "check.py",
            ["界" * (MAX_SCRIPT_ARG_BYTES // 3 + 1)],
        )
    assert not current.client.created


def test_execution_input_boundaries_are_accepted(tmp_path):
    current = service(tmp_path)
    fake_skills = type("Skills", (), {"script_bytes": lambda *_args: b"print('ok')"})()

    assert current.shell("thread", "x" * MAX_SHELL_BYTES)["exitCode"] == 0
    assert current.run_code("thread", "x" * MAX_CODE_BYTES)["exitCode"] == 0
    result = current.run_skill_script(
        "thread", fake_skills, "review", "check.py",
        ["x" * MAX_SCRIPT_ARG_BYTES] * 20,
    )
    assert result["exitCode"] == 0


def test_postgres_registry_serializes_two_workspace_services():
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

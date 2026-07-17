from pathlib import PurePosixPath

import pytest

from agentos_dev.workspace import (
    MAX_UPLOAD_BYTES,
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


def service(tmp_path, client=None):
    return WorkspaceService(
        SECRET,
        client=client or FakeClient(),
        registry=SandboxRegistry(str(tmp_path / "registry.sqlite")),
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

    restarted = service(tmp_path, client)
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


def test_mutating_and_execution_tools_all_require_confirmation(tmp_path):
    tools = {tool.name: tool for tool in workspace_tools(service(tmp_path), SecureSkills([]))}
    assert tools["workspace_list_files"].requires_confirmation is not True
    assert tools["workspace_read_file"].requires_confirmation is not True
    for name in (
        "workspace_write_file", "workspace_move_file", "workspace_delete_file",
        "workspace_shell", "workspace_run_code", "run_skill_script",
    ):
        assert tools[name].requires_confirmation is True

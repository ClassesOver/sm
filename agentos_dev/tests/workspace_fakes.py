import threading
from contextlib import contextmanager
from pathlib import PurePosixPath

from agentos_dev.workspace import WorkspaceService

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
            info
            for child, (info, _content) in self.entries.items()
            if child.startswith(prefix) and "/" not in child[len(prefix) :]
        ]

    def delete_file(self, path, recursive=False):
        del self.entries[path]

    def move_files(self, source, destination):
        self.entries[destination] = self.entries.pop(source)


class FakeProcess:
    def exec(self, command, cwd=None, timeout=None):
        return type("Result", (), {"result": command, "exit_code": 0})()


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
        return iter(
            sandbox
            for sandbox in self.sandboxes.values()
            if all(sandbox.labels.get(key) == value for key, value in (query.labels or {}).items())
        )

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


def service(_tmp_path, client=None):
    return WorkspaceService(
        SECRET,
        client=client or FakeClient(),
        registry=MemoryRegistry(),
    )

import asyncio
import threading
from contextlib import asynccontextmanager, contextmanager
from pathlib import PurePosixPath

from smart_reporting.workspace import WorkspaceService

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
        self.owner = None
        self.group = None


class FakeFs:
    def __init__(self):
        self.entries = {"/home/daytona/workspace": (Info("workspace", True), b"")}
        self.download_calls = []
        self.stream_download_calls = []

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
        self.download_calls.append(path)
        return self.entries[path][1]

    def download_file_stream(self, path):
        self.stream_download_calls.append(path)
        content = self.entries[path][1]
        midpoint = len(content) // 2
        for chunk in (content[:midpoint], content[midpoint:]):
            if chunk:
                yield chunk

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

    def set_file_permissions(self, path, mode=None, owner=None, group=None):
        info = self.entries[path][0]
        if mode is not None:
            info.mode = mode
        info.owner = owner
        info.group = group


class FakeProcess:
    def __init__(self):
        self.calls = []
        self.sessions = {}
        self.input_calls = []
        self.deleted_sessions = []

    def exec(self, command, cwd=None, timeout=None):
        self.calls.append({"command": command, "cwd": cwd, "timeout": timeout})
        return type("Result", (), {"result": command, "exit_code": 0})()

    def create_session(self, session_id):
        self.sessions[session_id] = type(
            "Session", (), {"session_id": session_id, "commands": []}
        )()

    def list_sessions(self):
        return list(self.sessions.values())

    def execute_session_command(self, session_id, request, timeout=None):
        session = self.sessions[session_id]
        command_id = f"command-{len(session.commands) + 1}"
        command = type(
            "Command",
            (),
            {
                "id": command_id,
                "command": request.command,
                "suppress_input_echo": request.suppress_input_echo,
                "exit_code": None if request.run_async else 0,
                "output": "started",
            },
        )()
        session.commands.append(command)
        return type(
            "SessionResult",
            (),
            {
                "cmd_id": command_id,
                "output": "started",
                "stdout": "started",
                "stderr": "",
                "exit_code": command.exit_code,
            },
        )()

    def get_session(self, session_id):
        if session_id not in self.sessions:
            from daytona.common.errors import DaytonaNotFoundError

            raise DaytonaNotFoundError("not found")
        return self.sessions[session_id]

    def get_session_command(self, session_id, command_id):
        from daytona.common.errors import DaytonaNotFoundError

        session = self.get_session(session_id)
        try:
            return next(command for command in session.commands if command.id == command_id)
        except StopIteration as error:
            raise DaytonaNotFoundError("not found") from error

    def get_session_command_logs(self, session_id, command_id):
        command = self.get_session_command(session_id, command_id)
        return type(
            "Logs",
            (),
            {"output": command.output, "stdout": command.output, "stderr": ""},
        )()

    def send_session_command_input(self, session_id, command_id, data):
        self.get_session_command(session_id, command_id)
        self.input_calls.append({"session_id": session_id, "command_id": command_id, "data": data})

    def delete_session(self, session_id):
        self.deleted_sessions.append(session_id)
        del self.sessions[session_id]


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


class AsyncFakeFs:
    def __init__(self, fs):
        self._fs = fs

    async def get_file_info(self, path):
        return self._fs.get_file_info(path)

    async def create_folder(self, path, mode):
        return self._fs.create_folder(path, mode)

    async def upload_file(self, content, path):
        return self._fs.upload_file(content, path)

    async def download_file(self, path):
        return self._fs.download_file(path)

    async def download_file_stream(self, path, timeout=30 * 60):
        async def stream():
            for chunk in self._fs.download_file_stream(path):
                yield chunk

        return stream()

    async def list_files(self, path):
        return self._fs.list_files(path)

    async def delete_file(self, path, recursive=False):
        if recursive:
            for child in list(self._fs.entries):
                if child == path or child.startswith(path.rstrip("/") + "/"):
                    self._fs.entries.pop(child, None)
            return None
        return self._fs.delete_file(path, recursive=False)

    async def set_file_permissions(self, path, mode=None, owner=None, group=None):
        return self._fs.set_file_permissions(path, mode=mode, owner=owner, group=group)


class AsyncFakeProcess:
    def __init__(self, process):
        self._process = process

    async def exec(self, command, cwd=None, timeout=None):
        return self._process.exec(command, cwd=cwd, timeout=timeout)

    async def create_session(self, session_id):
        return self._process.create_session(session_id)

    async def list_sessions(self):
        return self._process.list_sessions()

    async def execute_session_command(self, session_id, request, timeout=None):
        return self._process.execute_session_command(session_id, request, timeout=timeout)

    async def get_session(self, session_id):
        return self._process.get_session(session_id)

    async def get_session_command(self, session_id, command_id):
        return self._process.get_session_command(session_id, command_id)

    async def get_session_command_logs(self, session_id, command_id):
        return self._process.get_session_command_logs(session_id, command_id)

    async def send_session_command_input(self, session_id, command_id, data):
        return self._process.send_session_command_input(session_id, command_id, data)

    async def delete_session(self, session_id):
        return self._process.delete_session(session_id)


class AsyncFakeSandbox:
    def __init__(self, sandbox):
        self._sandbox = sandbox
        self.fs = AsyncFakeFs(sandbox.fs)
        self.process = AsyncFakeProcess(sandbox.process)

    @property
    def id(self):
        return self._sandbox.id

    @property
    def labels(self):
        return self._sandbox.labels

    @property
    def state(self):
        return self._sandbox.state


class AsyncFakeClient:
    def __init__(self, client):
        self._client = client

    async def create(self, params):
        return AsyncFakeSandbox(self._client.create(params))

    async def get(self, sandbox_id):
        return AsyncFakeSandbox(self._client.get(sandbox_id))

    async def list(self, query):
        for sandbox in self._client.list(query):
            yield AsyncFakeSandbox(sandbox)

    async def start(self, sandbox):
        self._client.start(sandbox._sandbox)

    async def delete(self, sandbox):
        self._client.delete(sandbox._sandbox)


class MemoryRegistry:
    def __init__(self, values=None):
        self.values = values if values is not None else {}
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


class AsyncMemoryRegistry:
    def __init__(self, values):
        self.values = values
        self.lock = asyncio.Lock()

    @asynccontextmanager
    async def locked(self, _value):
        async with self.lock:
            yield self

    async def get(self, value):
        return self.values.get(value)

    async def set(self, value, sandbox_id):
        self.values[value] = sandbox_id

    async def delete(self, value):
        self.values.pop(value, None)

    async def workspace_label(self, base_label):
        return base_label


def service(_tmp_path, client=None):
    return WorkspaceService(
        SECRET,
        client=client or FakeClient(),
        registry=MemoryRegistry(),
    )

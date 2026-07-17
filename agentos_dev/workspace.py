import json
import mimetypes
import os
import shlex
import sqlite3
import threading
from pathlib import PurePosixPath
from typing import Any

from agno.run import RunContext
from agno.tools.function import Function
from daytona import (
    CreateSandboxFromSnapshotParams,
    Daytona,
    ListSandboxesQuery,
)
from daytona.common.errors import DaytonaNotFoundError

from .security import thread_label
from .skills import SecureSkills


WORKSPACE_ROOT = "/home/daytona/workspace"
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_DOWNLOAD_BYTES = 25 * 1024 * 1024
MAX_READ_BYTES = 1024 * 1024
MAX_TOOL_OUTPUT_BYTES = 64 * 1024
MAX_LIST_ENTRIES = 500


class WorkspaceError(ValueError):
    pass


class SandboxRegistry:
    def __init__(self, path: str):
        self.path = path
        self._lock = threading.Lock()
        self._initialize()

    def _connect(self):
        connection = sqlite3.connect(self.path, timeout=10)
        connection.execute("PRAGMA journal_mode=WAL")
        return connection

    def _initialize(self):
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS workspace_sandbox ("
                "thread_hash TEXT PRIMARY KEY, sandbox_id TEXT NOT NULL, updated_at INTEGER NOT NULL"
                ")"
            )

    def get(self, value: str) -> str | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT sandbox_id FROM workspace_sandbox WHERE thread_hash = ?", (value,)
            ).fetchone()
        return row[0] if row else None

    def set(self, value: str, sandbox_id: str):
        with self._lock, self._connect() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO workspace_sandbox "
                "(thread_hash, sandbox_id, updated_at) VALUES (?, ?, strftime('%s','now'))",
                (value, sandbox_id),
            )

    def delete(self, value: str):
        with self._lock, self._connect() as connection:
            connection.execute(
                "DELETE FROM workspace_sandbox WHERE thread_hash = ?", (value,)
            )


def default_registry_path() -> str:
    configured = os.getenv("AGENT_WORKSPACE_DB_FILE")
    if configured:
        return configured
    agent_db = os.getenv("AGENT_DB_FILE", "/tmp/agui_agentos_dev.db")
    return os.path.join(os.path.dirname(agent_db), "agui_workspaces.db")


class WorkspaceService:
    def __init__(
        self,
        secret: str,
        client: Any | None = None,
        registry: SandboxRegistry | None = None,
    ):
        self.secret = secret
        self._client = client
        self.registry = registry or SandboxRegistry(default_registry_path())
        self._lock = threading.Lock()

    @property
    def client(self):
        if self._client is None:
            self._client = Daytona()
        return self._client

    def _hash(self, thread: str) -> str:
        return thread_label(thread, self.secret)

    def _find_existing(self, value: str):
        sandbox_id = self.registry.get(value)
        if sandbox_id:
            try:
                return self.client.get(sandbox_id)
            except DaytonaNotFoundError:
                self.registry.delete(value)
        matches = list(self.client.list(ListSandboxesQuery(
            labels={"agui-thread": value}, limit=2,
        )))
        if len(matches) > 1:
            raise WorkspaceError("Multiple sandboxes are bound to one thread")
        if matches:
            self.registry.set(value, matches[0].id)
            return matches[0]
        return None

    def sandbox_for(self, thread: str, create: bool = True):
        value = self._hash(thread)
        with self._lock:
            sandbox = self._find_existing(value)
            if sandbox is None and create:
                sandbox = self.client.create(CreateSandboxFromSnapshotParams(
                    name=f"agui-{value[:20]}",
                    language="python",
                    labels={"agui-thread": value},
                    public=False,
                    ephemeral=False,
                    auto_stop_interval=60,
                    auto_archive_interval=0,
                    auto_delete_interval=-1,
                ))
                self.registry.set(value, sandbox.id)
            if sandbox is None:
                return None
            state = str(getattr(sandbox, "state", "")).lower()
            if "stopped" in state or "archived" in state:
                self.client.start(sandbox)
            self._ensure_directory(sandbox, WORKSPACE_ROOT)
            return sandbox

    def destroy(self, thread: str) -> bool:
        value = self._hash(thread)
        with self._lock:
            sandbox = self._find_existing(value)
            if sandbox is None:
                return False
            self.client.delete(sandbox)
            self.registry.delete(value)
            return True

    @staticmethod
    def normalize_path(path: str | None, allow_root: bool = True) -> tuple[str, str]:
        raw = str(path or "").replace("\\", "/")
        candidate = PurePosixPath(raw)
        if candidate.is_absolute() or "\x00" in raw:
            raise WorkspaceError("Absolute workspace paths are not allowed")
        parts = [part for part in candidate.parts if part not in ("", ".")]
        if any(part == ".." for part in parts):
            raise WorkspaceError("Workspace path traversal is not allowed")
        relative = "/".join(parts)
        if not relative and not allow_root:
            raise WorkspaceError("A workspace path is required")
        remote = WORKSPACE_ROOT + (f"/{relative}" if relative else "")
        return relative, remote

    @staticmethod
    def _is_symlink(info: Any) -> bool:
        mode = str(getattr(info, "mode", "") or "")
        return mode.startswith("l") or bool(
            getattr(info, "additional_properties", {}).get("isSymlink", False)
        )

    def _info(self, sandbox, remote: str):
        return sandbox.fs.get_file_info(remote)

    def _validate_existing_path(self, sandbox, relative: str, include_leaf: bool = True):
        parts = relative.split("/") if relative else []
        end = len(parts) if include_leaf else max(0, len(parts) - 1)
        for index in range(1, end + 1):
            remote = f"{WORKSPACE_ROOT}/{'/'.join(parts[:index])}"
            info = self._info(sandbox, remote)
            if self._is_symlink(info):
                raise WorkspaceError("Symbolic links are not allowed in workspace paths")

    def _validate_destination(self, sandbox, relative: str, remote: str):
        self._validate_existing_path(sandbox, relative, include_leaf=False)
        try:
            info = self._info(sandbox, remote)
        except DaytonaNotFoundError:
            return
        if self._is_symlink(info):
            raise WorkspaceError("Symbolic links are not allowed in workspace paths")

    def _ensure_directory(self, sandbox, remote: str):
        if remote == WORKSPACE_ROOT:
            try:
                info = self._info(sandbox, remote)
                if self._is_symlink(info) or not info.is_dir:
                    raise WorkspaceError("Workspace root is not a safe directory")
                return
            except WorkspaceError:
                raise
            except Exception:
                sandbox.fs.create_folder(remote, "700")
                return
        relative = remote[len(WORKSPACE_ROOT):].strip("/")
        current = WORKSPACE_ROOT
        self._ensure_directory(sandbox, WORKSPACE_ROOT)
        for part in relative.split("/") if relative else []:
            current = f"{current}/{part}"
            try:
                info = self._info(sandbox, current)
                if self._is_symlink(info) or not info.is_dir:
                    raise WorkspaceError("Workspace parent is not a safe directory")
            except WorkspaceError:
                raise
            except Exception:
                sandbox.fs.create_folder(current, "700")

    def list_files(self, thread: str, path: str = "") -> list[dict[str, Any]]:
        relative, remote = self.normalize_path(path)
        sandbox = self.sandbox_for(thread)
        self._validate_existing_path(sandbox, relative)
        entries = sandbox.fs.list_files(remote)
        if len(entries) > MAX_LIST_ENTRIES:
            raise WorkspaceError("Workspace directory contains too many entries")
        result = []
        for entry in entries:
            if entry.name in (".", "..") or self._is_symlink(entry):
                continue
            child = f"{relative}/{entry.name}".strip("/")
            result.append({
                "path": child,
                "name": entry.name,
                "isDirectory": bool(entry.is_dir),
                "size": int(entry.size or 0),
                "mimeType": False if entry.is_dir else (
                    mimetypes.guess_type(entry.name)[0] or "application/octet-stream"
                ),
                "modifiedAt": entry.modified_at or entry.mod_time,
            })
        return sorted(result, key=lambda item: (not item["isDirectory"], item["name"].lower()))

    def upload(self, thread: str, path: str, content: bytes) -> dict[str, Any]:
        if len(content) > MAX_UPLOAD_BYTES:
            raise WorkspaceError("Workspace upload exceeds 10 MB")
        relative, remote = self.normalize_path(path, allow_root=False)
        sandbox = self.sandbox_for(thread)
        parent = remote.rsplit("/", 1)[0]
        self._ensure_directory(sandbox, parent)
        self._validate_destination(sandbox, relative, remote)
        sandbox.fs.upload_file(content, remote)
        return {"path": relative, "size": len(content), "status": "synced"}

    def file_bytes(self, thread: str, path: str) -> tuple[bytes, str]:
        relative, remote = self.normalize_path(path, allow_root=False)
        sandbox = self.sandbox_for(thread)
        self._validate_existing_path(sandbox, relative)
        info = self._info(sandbox, remote)
        if info.is_dir or int(info.size or 0) > MAX_DOWNLOAD_BYTES:
            raise WorkspaceError("Workspace file is not downloadable or exceeds 25 MB")
        content = sandbox.fs.download_file(remote)
        if not isinstance(content, bytes) or len(content) > MAX_DOWNLOAD_BYTES:
            raise WorkspaceError("Workspace response exceeds 25 MB")
        return content, mimetypes.guess_type(relative)[0] or "application/octet-stream"

    def read_text(self, thread: str, path: str) -> str:
        content, _mime_type = self.file_bytes(thread, path)
        if len(content) > MAX_READ_BYTES or b"\x00" in content:
            raise WorkspaceError("Workspace file is binary or exceeds 1 MB")
        try:
            return content.decode("utf-8")
        except UnicodeDecodeError as error:
            raise WorkspaceError("Workspace file is not UTF-8 text") from error

    def delete_file(self, thread: str, path: str, recursive: bool = False):
        relative, remote = self.normalize_path(path, allow_root=False)
        sandbox = self.sandbox_for(thread)
        self._validate_existing_path(sandbox, relative)
        sandbox.fs.delete_file(remote, recursive=recursive)

    def move_file(self, thread: str, source: str, destination: str):
        source_relative, source_remote = self.normalize_path(source, allow_root=False)
        destination_relative, destination_remote = self.normalize_path(destination, allow_root=False)
        sandbox = self.sandbox_for(thread)
        self._validate_existing_path(sandbox, source_relative)
        self._ensure_directory(sandbox, destination_remote.rsplit("/", 1)[0])
        self._validate_destination(sandbox, destination_relative, destination_remote)
        sandbox.fs.move_files(source_remote, destination_remote)

    @staticmethod
    def _bounded_output(value: Any) -> dict[str, Any]:
        output = str(getattr(value, "result", "") or "")
        encoded = output.encode("utf-8", errors="replace")
        truncated = len(encoded) > MAX_TOOL_OUTPUT_BYTES
        if truncated:
            output = encoded[:MAX_TOOL_OUTPUT_BYTES].decode("utf-8", errors="replace")
        return {
            "exitCode": getattr(value, "exit_code", None),
            "output": output,
            "truncated": truncated,
        }

    def shell(self, thread: str, command: str, timeout: int = 30):
        sandbox = self.sandbox_for(thread)
        value = sandbox.process.exec(
            command[:8000], cwd=WORKSPACE_ROOT, timeout=max(1, min(int(timeout), 60)),
        )
        return self._bounded_output(value)

    def run_code(self, thread: str, code: str, timeout: int = 30):
        sandbox = self.sandbox_for(thread)
        value = sandbox.process.code_run(
            code[:256 * 1024], timeout=max(1, min(int(timeout), 60)),
        )
        return self._bounded_output(value)

    def run_skill_script(
        self,
        thread: str,
        skills: SecureSkills,
        skill_name: str,
        script_path: str,
        args: list[str] | None = None,
        timeout: int = 30,
    ):
        content = skills.script_bytes(skill_name, script_path)
        safe_name = PurePosixPath(script_path).name
        skill_key = SecureSkills.skill_id(skill_name)
        relative = f"skills/{skill_key}/{safe_name}"
        self.upload(thread, relative, content)
        remote = f"{WORKSPACE_ROOT}/{relative}"
        arguments = " ".join(shlex.quote(str(value)[:1024]) for value in (args or [])[:20])
        extension = PurePosixPath(safe_name).suffix.lower()
        interpreter = {".py": "python", ".js": "node", ".sh": "sh"}.get(extension)
        if not interpreter:
            raise WorkspaceError("Skill script type is not executable")
        return self.shell(
            thread,
            f"{interpreter} {shlex.quote(remote)} {arguments}".rstrip(),
            timeout,
        )


def _thread(run_context: RunContext) -> str:
    if not run_context or not run_context.session_id:
        raise WorkspaceError("A thread-bound run context is required")
    return run_context.session_id


def workspace_tools(service: WorkspaceService, skills: SecureSkills) -> list[Function]:
    def list_files(path: str = "", run_context: RunContext = None):
        """List files in the current thread workspace."""
        return json.dumps(service.list_files(_thread(run_context), path), ensure_ascii=False)

    def read_file(path: str, run_context: RunContext = None):
        """Read a bounded UTF-8 text file from the current thread workspace."""
        return service.read_text(_thread(run_context), path)

    def write_file(path: str, content: str, run_context: RunContext = None):
        """Write a UTF-8 file in the current thread workspace."""
        return service.upload(_thread(run_context), path, content.encode("utf-8"))

    def move_file(source: str, destination: str, run_context: RunContext = None):
        """Move a file inside the current thread workspace."""
        service.move_file(_thread(run_context), source, destination)
        return {"ok": True}

    def delete_file(path: str, recursive: bool = False, run_context: RunContext = None):
        """Delete a file or directory from the current thread workspace."""
        service.delete_file(_thread(run_context), path, recursive)
        return {"ok": True}

    def shell(command: str, timeout: int = 30, run_context: RunContext = None):
        """Run a bounded shell command in the current thread Daytona sandbox."""
        return service.shell(_thread(run_context), command, timeout)

    def run_code(code: str, timeout: int = 30, run_context: RunContext = None):
        """Run bounded Python code in the current thread Daytona sandbox."""
        return service.run_code(_thread(run_context), code, timeout)

    def run_skill_script(
        skill_name: str,
        script_path: str,
        args: list[str] | None = None,
        timeout: int = 30,
        run_context: RunContext = None,
    ):
        """Copy and execute a declared skill script in the current Daytona sandbox."""
        return service.run_skill_script(
            _thread(run_context), skills, skill_name, script_path, args, timeout,
        )

    return [
        Function(name="workspace_list_files", entrypoint=list_files),
        Function(name="workspace_read_file", entrypoint=read_file),
        Function(name="workspace_write_file", entrypoint=write_file, requires_confirmation=True),
        Function(name="workspace_move_file", entrypoint=move_file, requires_confirmation=True),
        Function(name="workspace_delete_file", entrypoint=delete_file, requires_confirmation=True),
        Function(name="workspace_shell", entrypoint=shell, requires_confirmation=True),
        Function(name="workspace_run_code", entrypoint=run_code, requires_confirmation=True),
        Function(name="run_skill_script", entrypoint=run_skill_script, requires_confirmation=True),
    ]

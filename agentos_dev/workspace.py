import json
import mimetypes
import os
import shlex
import threading
from contextlib import contextmanager
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
import psycopg

from .security import thread_label
from .database import psycopg_db_url
from .skills import SecureSkills


WORKSPACE_ROOT = "/home/daytona/workspace"
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_DOWNLOAD_BYTES = 25 * 1024 * 1024
MAX_READ_BYTES = 1024 * 1024
MAX_TOOL_OUTPUT_BYTES = 64 * 1024
MAX_LIST_ENTRIES = 500
MAX_SHELL_BYTES = 8 * 1024
MAX_CODE_BYTES = 256 * 1024
MAX_SCRIPT_ARGS = 20
MAX_SCRIPT_ARG_BYTES = 1024


class WorkspaceError(ValueError):
    pass


class SandboxRegistry:
    def __init__(self, db_url: str | None = None):
        self.db_url = db_url or psycopg_db_url()
        self._initialized = False
        self._initialize_lock = threading.Lock()

    def _connect(self):
        return psycopg.connect(self.db_url)

    def ensure_initialized(self):
        if self._initialized:
            return
        with self._initialize_lock:
            if self._initialized:
                return
            with self._connect() as connection:
                connection.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                    ("agui-workspace:initialize",),
                )
                connection.execute(
                    "CREATE TABLE IF NOT EXISTS agui_workspace_sandbox ("
                    "thread_hash TEXT PRIMARY KEY, sandbox_id TEXT NOT NULL, "
                    "updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP"
                    ")"
                )
            self._initialized = True

    @contextmanager
    def locked(self, value: str):
        self.ensure_initialized()
        with self._connect() as connection:
            connection.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (value,)
            )
            yield SandboxRegistryTransaction(connection)


class SandboxRegistryTransaction:
    def __init__(self, connection):
        self.connection = connection

    def get(self, value: str) -> str | None:
        row = self.connection.execute(
            "SELECT sandbox_id FROM agui_workspace_sandbox WHERE thread_hash = %s",
            (value,),
        ).fetchone()
        return row[0] if row else None

    def set(self, value: str, sandbox_id: str):
        self.connection.execute(
            "INSERT INTO agui_workspace_sandbox (thread_hash, sandbox_id, updated_at) "
            "VALUES (%s, %s, CURRENT_TIMESTAMP) "
            "ON CONFLICT (thread_hash) DO UPDATE SET "
            "sandbox_id = EXCLUDED.sandbox_id, updated_at = CURRENT_TIMESTAMP",
            (value, sandbox_id),
        )

    def delete(self, value: str):
        self.connection.execute(
            "DELETE FROM agui_workspace_sandbox WHERE thread_hash = %s", (value,)
        )


class WorkspaceService:
    def __init__(
        self,
        secret: str,
        client: Any | None = None,
        registry: SandboxRegistry | None = None,
    ):
        self.secret = secret
        self._client = client
        self.registry = registry or SandboxRegistry()

    @property
    def client(self):
        if self._client is None:
            self._client = Daytona()
        return self._client

    def _hash(self, thread: str) -> str:
        return thread_label(thread, self.secret)

    def _find_existing(self, value: str, registry):
        sandbox_id = registry.get(value)
        if sandbox_id:
            try:
                return self.client.get(sandbox_id)
            except DaytonaNotFoundError:
                registry.delete(value)
        matches = list(self.client.list(ListSandboxesQuery(
            labels={"agui-thread": value}, limit=2,
        )))
        if len(matches) > 1:
            raise WorkspaceError("一个对话绑定了多个沙箱")
        if matches:
            registry.set(value, matches[0].id)
            return matches[0]
        return None

    def sandbox_for(self, thread: str, create: bool = True):
        value = self._hash(thread)
        with self.registry.locked(value) as registry:
            sandbox = self._find_existing(value, registry)
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
                registry.set(value, sandbox.id)
            if sandbox is None:
                return None
            state = str(getattr(sandbox, "state", "")).lower()
            if "stopped" in state or "archived" in state:
                self.client.start(sandbox)
            self._ensure_directory(sandbox, WORKSPACE_ROOT)
            return sandbox

    def destroy(self, thread: str) -> bool:
        value = self._hash(thread)
        with self.registry.locked(value) as registry:
            sandboxes = {}
            sandbox_id = registry.get(value)
            if sandbox_id:
                try:
                    sandbox = self.client.get(sandbox_id)
                    sandboxes[sandbox.id] = sandbox
                except DaytonaNotFoundError:
                    pass
            for sandbox in self.client.list(ListSandboxesQuery(
                labels={"agui-thread": value},
            )):
                sandboxes[sandbox.id] = sandbox
            for sandbox in sandboxes.values():
                try:
                    self.client.delete(sandbox)
                except DaytonaNotFoundError:
                    pass
            registry.delete(value)
            return bool(sandboxes)

    @staticmethod
    def normalize_path(path: str | None, allow_root: bool = True) -> tuple[str, str]:
        raw = str(path or "").replace("\\", "/")
        candidate = PurePosixPath(raw)
        if candidate.is_absolute() or "\x00" in raw:
            raise WorkspaceError("工作区路径不能使用绝对路径")
        parts = [part for part in candidate.parts if part not in ("", ".")]
        if any(part == ".." for part in parts):
            raise WorkspaceError("工作区路径不能包含目录穿越")
        relative = "/".join(parts)
        if not relative and not allow_root:
            raise WorkspaceError("必须提供工作区路径")
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
                raise WorkspaceError("工作区路径不能包含符号链接")

    def _validate_destination(self, sandbox, relative: str, remote: str):
        self._validate_existing_path(sandbox, relative, include_leaf=False)
        try:
            info = self._info(sandbox, remote)
        except DaytonaNotFoundError:
            return
        if self._is_symlink(info):
            raise WorkspaceError("工作区路径不能包含符号链接")

    def _ensure_directory(self, sandbox, remote: str):
        if remote == WORKSPACE_ROOT:
            try:
                info = self._info(sandbox, remote)
                if self._is_symlink(info) or not info.is_dir:
                    raise WorkspaceError("工作区根路径不是安全目录")
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
                    raise WorkspaceError("工作区父路径不是安全目录")
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
            raise WorkspaceError("工作区目录包含的条目过多")
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
            raise WorkspaceError("工作区上传内容超过 10 MB")
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
            raise WorkspaceError("工作区文件不可下载或超过 25 MB")
        content = sandbox.fs.download_file(remote)
        if not isinstance(content, bytes) or len(content) > MAX_DOWNLOAD_BYTES:
            raise WorkspaceError("工作区响应超过 25 MB")
        return content, mimetypes.guess_type(relative)[0] or "application/octet-stream"

    def read_text(self, thread: str, path: str) -> str:
        content, _mime_type = self.file_bytes(thread, path)
        if len(content) > MAX_READ_BYTES or b"\x00" in content:
            raise WorkspaceError("工作区文件是二进制文件或超过 1 MB")
        try:
            return content.decode("utf-8")
        except UnicodeDecodeError as error:
            raise WorkspaceError("工作区文件不是 UTF-8 文本") from error

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
        if len(str(command).encode("utf-8")) > MAX_SHELL_BYTES:
            raise WorkspaceError("Shell 命令超过 8 KiB")
        sandbox = self.sandbox_for(thread)
        value = sandbox.process.exec(
            command, cwd=WORKSPACE_ROOT, timeout=max(1, min(int(timeout), 60)),
        )
        return self._bounded_output(value)

    def run_code(self, thread: str, code: str, timeout: int = 30):
        if len(str(code).encode("utf-8")) > MAX_CODE_BYTES:
            raise WorkspaceError("代码超过 256 KiB")
        sandbox = self.sandbox_for(thread)
        value = sandbox.process.code_run(
            code, timeout=max(1, min(int(timeout), 60)),
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
        arguments = args or []
        if len(arguments) > MAX_SCRIPT_ARGS:
            raise WorkspaceError("技能脚本最多接受 20 个参数")
        if any(len(str(value).encode("utf-8")) > MAX_SCRIPT_ARG_BYTES for value in arguments):
            raise WorkspaceError("技能脚本参数超过 1 KiB")
        content = skills.script_bytes(skill_name, script_path)
        safe_name = PurePosixPath(script_path).name
        extension = PurePosixPath(safe_name).suffix.lower()
        interpreter = {".py": "python", ".js": "node", ".sh": "sh"}.get(extension)
        if not interpreter:
            raise WorkspaceError("技能脚本类型不可执行")
        skill_key = SecureSkills.skill_id(skill_name)
        relative = f"skills/{skill_key}/{safe_name}"
        self.upload(thread, relative, content)
        remote = f"{WORKSPACE_ROOT}/{relative}"
        arguments = " ".join(shlex.quote(str(value)) for value in arguments)
        value = self.sandbox_for(thread).process.exec(
            f"{interpreter} {shlex.quote(remote)} {arguments}".rstrip(),
            cwd=WORKSPACE_ROOT,
            timeout=max(1, min(int(timeout), 60)),
        )
        return self._bounded_output(value)


def _thread(run_context: RunContext) -> str:
    if not run_context or not run_context.session_id:
        raise WorkspaceError("需要绑定对话的运行上下文")
    return run_context.session_id


def workspace_tools(service: WorkspaceService, skills: SecureSkills) -> list[Function]:
    def list_files(path: str = "", run_context: RunContext = None):
        """列出当前对话工作区中的文件。"""
        return json.dumps(service.list_files(_thread(run_context), path), ensure_ascii=False)

    def read_file(path: str, run_context: RunContext = None):
        """读取当前对话工作区中大小受限的 UTF-8 文本文件。"""
        return service.read_text(_thread(run_context), path)

    def write_file(path: str, content: str, run_context: RunContext = None):
        """在当前对话工作区中写入 UTF-8 文件。"""
        return service.upload(_thread(run_context), path, content.encode("utf-8"))

    def move_file(source: str, destination: str, run_context: RunContext = None):
        """在当前对话工作区中移动文件。"""
        service.move_file(_thread(run_context), source, destination)
        return {"ok": True}

    def delete_file(path: str, recursive: bool = False, run_context: RunContext = None):
        """删除当前对话工作区中的文件或目录。"""
        service.delete_file(_thread(run_context), path, recursive)
        return {"ok": True}

    def shell(command: str, timeout: int = 30, run_context: RunContext = None):
        """在当前对话的 Daytona 沙箱中运行受限的 Shell 命令。"""
        return service.shell(_thread(run_context), command, timeout)

    def run_code(code: str, timeout: int = 30, run_context: RunContext = None):
        """在当前对话的 Daytona 沙箱中运行受限的 Python 代码。"""
        return service.run_code(_thread(run_context), code, timeout)

    def run_skill_script(
        skill_name: str,
        script_path: str,
        args: list[str] | None = None,
        timeout: int = 30,
        run_context: RunContext = None,
    ):
        """在当前 Daytona 沙箱中复制并执行已声明的技能脚本。"""
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

import asyncio
import hashlib
import json
import mimetypes
import shlex
import threading
import unicodedata
from contextlib import asynccontextmanager, contextmanager
from pathlib import PurePosixPath
from typing import Any

import psycopg
from agno.run import RunContext
from agno.tools import Toolkit
from daytona import (
    AsyncDaytona,
    CreateSandboxFromSnapshotParams,
    Daytona,
    ListSandboxesQuery,
)
from daytona.common.errors import DaytonaNotFoundError

from .async_utils import complete_cleanup
from .database import psycopg_db_url
from .security import thread_label

WORKSPACE_ROOT = "/home/daytona/workspace"
WORKSPACE_SNAPSHOT = "sandbox-tools-20260722"
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_DOWNLOAD_BYTES = 25 * 1024 * 1024
MAX_READ_BYTES = 1024 * 1024
MAX_TOOL_OUTPUT_BYTES = 64 * 1024
MAX_LIST_ENTRIES = 500
MAX_PATH_BYTES = 1024
MAX_PATH_COMPONENT_BYTES = 255
MAX_PATH_DEPTH = 32
MAX_EXECUTION_TIMEOUT = 60
MAX_BRANCH_FILES = 2000
MAX_BRANCH_TOTAL_BYTES = 256 * 1024 * 1024
MAX_BRANCH_FILE_BYTES = 25 * 1024 * 1024


class WorkspaceError(ValueError):
    pass


class WorkspacePathConflict(WorkspaceError):
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
            connection.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (value,))
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


class AsyncSandboxRegistry:
    def __init__(self, db_url: str | None = None):
        self.db_url = db_url or psycopg_db_url()
        self._initialized = False
        self._initialize_lock = asyncio.Lock()

    async def _connect(self):
        return await psycopg.AsyncConnection.connect(self.db_url)

    async def ensure_initialized(self):
        if self._initialized:
            return
        async with self._initialize_lock:
            if self._initialized:
                return
            connection = await self._connect()
            async with connection:
                await connection.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                    ("agui-workspace:initialize",),
                )
                await connection.execute(
                    "CREATE TABLE IF NOT EXISTS agui_workspace_sandbox ("
                    "thread_hash TEXT PRIMARY KEY, sandbox_id TEXT NOT NULL, "
                    "updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP"
                    ")"
                )
            self._initialized = True

    @asynccontextmanager
    async def locked(self, value: str):
        await self.ensure_initialized()
        connection = await self._connect()
        async with connection:
            await connection.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (value,)
            )
            yield AsyncSandboxRegistryTransaction(connection)


class AsyncSandboxRegistryTransaction:
    def __init__(self, connection):
        self.connection = connection

    async def get(self, value: str) -> str | None:
        cursor = await self.connection.execute(
            "SELECT sandbox_id FROM agui_workspace_sandbox WHERE thread_hash = %s",
            (value,),
        )
        row = await cursor.fetchone()
        return row[0] if row else None

    async def set(self, value: str, sandbox_id: str):
        await self.connection.execute(
            "INSERT INTO agui_workspace_sandbox (thread_hash, sandbox_id, updated_at) "
            "VALUES (%s, %s, CURRENT_TIMESTAMP) "
            "ON CONFLICT (thread_hash) DO UPDATE SET "
            "sandbox_id = EXCLUDED.sandbox_id, updated_at = CURRENT_TIMESTAMP",
            (value, sandbox_id),
        )

    async def delete(self, value: str):
        await self.connection.execute(
            "DELETE FROM agui_workspace_sandbox WHERE thread_hash = %s", (value,)
        )


class WorkspaceService:
    def __init__(
        self,
        secret: str,
        client: Any | None = None,
        registry: SandboxRegistry | None = None,
        async_client: Any | None = None,
        async_registry: Any | None = None,
    ):
        self.secret = secret
        self._client = client
        self.registry = registry or SandboxRegistry()
        self._async_client_override = async_client
        self.async_registry = async_registry or AsyncSandboxRegistry(
            getattr(self.registry, "db_url", None)
        )

    @property
    def client(self):
        if self._client is None:
            self._client = Daytona()
        return self._client

    @asynccontextmanager
    async def _async_client(self):
        if self._async_client_override is not None:
            yield self._async_client_override
            return
        async with AsyncDaytona() as client:
            yield client

    def _hash(self, thread: str) -> str:
        return thread_label(thread, self.secret)

    def _find_existing(self, value: str, registry):
        sandbox_id = registry.get(value)
        if sandbox_id:
            try:
                return self.client.get(sandbox_id)
            except DaytonaNotFoundError:
                registry.delete(value)
        matches = list(
            self.client.list(
                ListSandboxesQuery(
                    labels={"agui-thread": value},
                    limit=2,
                )
            )
        )
        if len(matches) > 1:
            raise WorkspaceError("当前对话关联了多个运行环境，请联系管理员清理后重试。")
        if matches:
            registry.set(value, matches[0].id)
            return matches[0]
        return None

    def sandbox_for(self, thread: str, create: bool = True):
        value = self._hash(thread)
        with self.registry.locked(value) as registry:
            sandbox = self._find_existing(value, registry)
            if sandbox is None and create:
                sandbox = self.client.create(
                    CreateSandboxFromSnapshotParams(
                        snapshot=WORKSPACE_SNAPSHOT,
                        name=f"agui-{value[:20]}",
                        language="python",
                        labels={"agui-thread": value},
                        public=False,
                        ephemeral=False,
                        auto_stop_interval=60,
                        auto_archive_interval=0,
                        auto_delete_interval=-1,
                        network_block_all=True,
                    )
                )
                registry.set(value, sandbox.id)
            if sandbox is None:
                return None
            raw_state = getattr(sandbox, "state", "")
            state = str(getattr(raw_state, "value", raw_state) or "").lower()
            if state in {"stopped", "archived"}:
                self.client.start(sandbox)
                raw_state = getattr(sandbox, "state", "")
                state = str(getattr(raw_state, "value", raw_state) or "").lower()
            if state in {
                "creating",
                "restoring",
                "starting",
                "pending_build",
                "building_snapshot",
                "pulling_snapshot",
                "resuming",
            }:
                raise WorkspaceError("当前工作区正在启动，请稍后重试。")
            if state != "started":
                raise WorkspaceError("当前工作区状态异常，请稍后重试；如问题持续，请联系管理员。")
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
            for sandbox in self.client.list(
                ListSandboxesQuery(
                    labels={"agui-thread": value},
                )
            ):
                sandboxes[sandbox.id] = sandbox
            for sandbox in sandboxes.values():
                try:
                    self.client.delete(sandbox)
                except DaytonaNotFoundError:
                    pass
            registry.delete(value)
            return bool(sandboxes)

    async def _afind_existing(self, client: Any, value: str, registry: Any):
        sandbox_id = await registry.get(value)
        if sandbox_id:
            try:
                return await client.get(sandbox_id)
            except DaytonaNotFoundError:
                await registry.delete(value)
        matches = [
            sandbox
            async for sandbox in client.list(
                ListSandboxesQuery(
                    labels={"agui-thread": value},
                    limit=2,
                )
            )
        ]
        if len(matches) > 1:
            raise WorkspaceError("当前对话关联了多个运行环境，请联系管理员清理后重试。")
        if matches:
            await registry.set(value, matches[0].id)
            return matches[0]
        return None

    async def _asandbox_for(self, client: Any, thread: str, create: bool = True):
        value = self._hash(thread)
        async with self.async_registry.locked(value) as registry:
            sandbox = await self._afind_existing(client, value, registry)
            if sandbox is None and create:
                sandbox = await client.create(
                    CreateSandboxFromSnapshotParams(
                        snapshot=WORKSPACE_SNAPSHOT,
                        name=f"agui-{value[:20]}",
                        language="python",
                        labels={"agui-thread": value},
                        public=False,
                        ephemeral=False,
                        auto_stop_interval=60,
                        auto_archive_interval=0,
                        auto_delete_interval=-1,
                        network_block_all=True,
                    )
                )
                await registry.set(value, sandbox.id)
            if sandbox is None:
                return None
            raw_state = getattr(sandbox, "state", "")
            state = str(getattr(raw_state, "value", raw_state) or "").lower()
            if state in {"stopped", "archived"}:
                await client.start(sandbox)
                raw_state = getattr(sandbox, "state", "")
                state = str(getattr(raw_state, "value", raw_state) or "").lower()
            if state in {
                "creating",
                "restoring",
                "starting",
                "pending_build",
                "building_snapshot",
                "pulling_snapshot",
                "resuming",
            }:
                raise WorkspaceError("当前工作区正在启动，请稍后重试。")
            if state != "started":
                raise WorkspaceError("当前工作区状态异常，请稍后重试；如问题持续，请联系管理员。")
            await self._aensure_directory(sandbox, WORKSPACE_ROOT)
            return sandbox

    async def _adestroy(self, client: Any, thread: str) -> bool:
        value = self._hash(thread)
        async with self.async_registry.locked(value) as registry:
            sandboxes = {}
            sandbox_id = await registry.get(value)
            if sandbox_id:
                try:
                    sandbox = await client.get(sandbox_id)
                    sandboxes[sandbox.id] = sandbox
                except DaytonaNotFoundError:
                    pass
            async for sandbox in client.list(
                ListSandboxesQuery(
                    labels={"agui-thread": value},
                )
            ):
                sandboxes[sandbox.id] = sandbox
            for sandbox in sandboxes.values():
                try:
                    await client.delete(sandbox)
                except DaytonaNotFoundError:
                    pass
            await registry.delete(value)
            return bool(sandboxes)

    async def adestroy(self, thread: str) -> bool:
        async with self._async_client() as client:
            return await self._adestroy(client, thread)

    async def _abranch_inventory(self, client: Any, thread: str):
        sandbox = await self._asandbox_for(client, thread, create=False)
        if sandbox is None:
            return None, [], []
        root = await self._ainfo(sandbox, WORKSPACE_ROOT)
        if self._is_symlink(root) or not root.is_dir:
            raise WorkspaceError("源工作区根路径不是安全目录，无法创建分支。")

        directories = []
        files = []
        total_bytes = 0
        seen = set()
        pending = [("", WORKSPACE_ROOT)]
        while pending:
            relative_parent, remote_parent = pending.pop()
            for entry in await sandbox.fs.list_files(remote_parent):
                name = str(getattr(entry, "name", "") or "")
                if name in ("", ".", "..") or "/" in name or "\\" in name:
                    raise WorkspaceError("源工作区包含无效路径，无法创建分支。")
                relative = f"{relative_parent}/{name}".strip("/")
                normalized, remote = self.normalize_path(relative, allow_root=False)
                if normalized != relative or relative in seen:
                    raise WorkspaceError("源工作区包含重复或越界路径，无法创建分支。")
                seen.add(relative)
                if self._is_symlink(entry):
                    raise WorkspaceError("源工作区包含符号链接，无法创建分支。")
                if entry.is_dir:
                    directories.append(relative)
                    pending.append((relative, remote))
                    continue
                if not self._is_regular_file(entry):
                    raise WorkspaceError("源工作区包含非普通文件，无法创建分支。")
                size = int(entry.size or 0)
                if size < 0 or size > MAX_BRANCH_FILE_BYTES:
                    raise WorkspaceError("源工作区存在超过 25 MiB 的文件，无法创建分支。")
                files.append((relative, remote, size))
                if len(files) > MAX_BRANCH_FILES:
                    raise WorkspaceError("源工作区文件数超过 2000 个，无法创建分支。")
                total_bytes += size
                if total_bytes > MAX_BRANCH_TOTAL_BYTES:
                    raise WorkspaceError("源工作区总大小超过 256 MiB，无法创建分支。")
        return sandbox, directories, files

    async def acopy_branch(self, source_thread: str, target_thread: str) -> dict[str, int]:
        if not source_thread or not target_thread or source_thread == target_thread:
            raise WorkspaceError("分支工作区线程无效。")
        async with self._async_client() as client:
            source, directories, files = await self._abranch_inventory(client, source_thread)
            if source is None:
                return {"files": 0, "bytes": 0}
            if await self._asandbox_for(client, target_thread, create=False) is not None:
                raise WorkspaceError("目标分支工作区已经存在。")

            target = None
            copied_bytes = 0
            try:
                target = await self._asandbox_for(client, target_thread, create=True)
                if target is None:
                    raise WorkspaceError("目标分支工作区创建失败。")
                for relative in sorted(
                    directories,
                    key=lambda value: (value.count("/"), value),
                ):
                    _relative, remote = self.normalize_path(relative, allow_root=False)
                    await self._aensure_directory(target, remote)
                for relative, remote, expected_size in files:
                    content = await self._adownload_file(
                        source,
                        remote,
                        MAX_BRANCH_FILE_BYTES,
                    )
                    if not isinstance(content, bytes) or len(content) != expected_size:
                        raise WorkspaceError("源工作区在分支复制期间发生变化，请重试。")
                    _relative, target_remote = self.normalize_path(relative, allow_root=False)
                    await self._aensure_directory(target, target_remote.rsplit("/", 1)[0])
                    await target.fs.upload_file(content, target_remote)
                    copied_bytes += len(content)
                return {"files": len(files), "bytes": copied_bytes}
            except BaseException:
                if target is not None:
                    try:
                        await complete_cleanup(self._adestroy(client, target_thread))
                    except Exception:
                        pass
                raise

    @staticmethod
    def normalize_path(path: str | None, allow_root: bool = True) -> tuple[str, str]:
        raw = str(path or "")
        if any(unicodedata.category(character).startswith("C") for character in raw):
            raise WorkspaceError("工作区路径包含控制字符，请删除不可见字符后重试。")
        raw = raw.replace("\\", "/")
        if len(raw.encode("utf-8")) > MAX_PATH_BYTES:
            raise WorkspaceError(f"工作区路径超过 {MAX_PATH_BYTES} 字节，请缩短路径后重试。")
        candidate = PurePosixPath(raw)
        windows_absolute = len(raw) >= 2 and raw[0].isalpha() and raw[1] == ":"
        if candidate.is_absolute() or windows_absolute:
            raise WorkspaceError("工作区路径是绝对路径，请改用当前工作区内的相对路径。")
        parts = [part for part in candidate.parts if part not in ("", ".")]
        if any(part == ".." for part in parts):
            raise WorkspaceError("工作区路径包含目录穿越“..”，请改用当前工作区内的路径。")
        if len(parts) > MAX_PATH_DEPTH:
            raise WorkspaceError(
                f"工作区路径目录层级超过 {MAX_PATH_DEPTH} 层，请减少目录层级后重试。"
            )
        if any(len(part.encode("utf-8")) > MAX_PATH_COMPONENT_BYTES for part in parts):
            raise WorkspaceError(
                f"工作区路径中的名称超过 {MAX_PATH_COMPONENT_BYTES} 字节，请缩短名称后重试。"
            )
        relative = "/".join(parts)
        if not relative and not allow_root:
            raise WorkspaceError("没有提供工作区路径，请指定文件或目录后重试。")
        remote = WORKSPACE_ROOT + (f"/{relative}" if relative else "")
        return relative, remote

    @staticmethod
    def _is_symlink(info: Any) -> bool:
        mode = str(getattr(info, "mode", "") or "")
        return mode.startswith("l") or bool(
            (getattr(info, "additional_properties", {}) or {}).get("isSymlink", False)
        )

    @classmethod
    def _is_regular_file(cls, info: Any) -> bool:
        if bool(getattr(info, "is_dir", False)) or cls._is_symlink(info):
            return False
        mode = str(getattr(info, "mode", "") or "")
        return not mode or mode.startswith("-") or mode[0].isdigit()

    def _info(self, sandbox, remote: str):
        return sandbox.fs.get_file_info(remote)

    async def _ainfo(self, sandbox, remote: str):
        return await sandbox.fs.get_file_info(remote)

    def _validate_existing_path(self, sandbox, relative: str, include_leaf: bool = True):
        parts = relative.split("/") if relative else []
        end = len(parts) if include_leaf else max(0, len(parts) - 1)
        for index in range(1, end + 1):
            remote = f"{WORKSPACE_ROOT}/{'/'.join(parts[:index])}"
            try:
                info = self._info(sandbox, remote)
            except DaytonaNotFoundError as error:
                raise WorkspaceError("工作区路径不存在，请检查名称后重试。") from error
            if self._is_symlink(info):
                raise WorkspaceError("工作区路径包含符号链接，请改用普通文件或目录。")

    def _validate_destination(self, sandbox, relative: str, remote: str):
        self._validate_existing_path(sandbox, relative, include_leaf=False)
        try:
            info = self._info(sandbox, remote)
        except DaytonaNotFoundError:
            return None
        if self._is_symlink(info):
            raise WorkspaceError("工作区路径包含符号链接，请改用普通文件或目录。")
        return info

    def _ensure_directory(self, sandbox, remote: str):
        if remote == WORKSPACE_ROOT:
            try:
                info = self._info(sandbox, remote)
                if self._is_symlink(info) or not info.is_dir:
                    raise WorkspaceError("工作区根路径不是安全目录，请联系管理员检查运行环境。")
                return
            except WorkspaceError:
                raise
            except DaytonaNotFoundError:
                sandbox.fs.create_folder(remote, "700")
                return
        relative = remote[len(WORKSPACE_ROOT) :].strip("/")
        current = WORKSPACE_ROOT
        self._ensure_directory(sandbox, WORKSPACE_ROOT)
        for part in relative.split("/") if relative else []:
            current = f"{current}/{part}"
            try:
                info = self._info(sandbox, current)
                if self._is_symlink(info) or not info.is_dir:
                    raise WorkspaceError("工作区父路径不是安全目录，请更换路径后重试。")
            except WorkspaceError:
                raise
            except DaytonaNotFoundError:
                sandbox.fs.create_folder(current, "700")

    async def _aensure_directory(self, sandbox, remote: str):
        if remote == WORKSPACE_ROOT:
            try:
                info = await self._ainfo(sandbox, remote)
                if self._is_symlink(info) or not info.is_dir:
                    raise WorkspaceError("工作区根路径不是安全目录，请联系管理员检查运行环境。")
                return
            except WorkspaceError:
                raise
            except DaytonaNotFoundError:
                await sandbox.fs.create_folder(remote, "700")
                return
        relative = remote[len(WORKSPACE_ROOT) :].strip("/")
        current = WORKSPACE_ROOT
        await self._aensure_directory(sandbox, WORKSPACE_ROOT)
        for part in relative.split("/") if relative else []:
            current = f"{current}/{part}"
            try:
                info = await self._ainfo(sandbox, current)
                if self._is_symlink(info) or not info.is_dir:
                    raise WorkspaceError("工作区目录路径不是安全目录，请改用普通目录。")
            except WorkspaceError:
                raise
            except DaytonaNotFoundError:
                await sandbox.fs.create_folder(current, "700")

    def list_files(self, thread: str, path: str = "") -> list[dict[str, Any]]:
        relative, remote = self.normalize_path(path)
        sandbox = self.sandbox_for(thread)
        self._validate_existing_path(sandbox, relative)
        entries = sandbox.fs.list_files(remote)
        if len(entries) > MAX_LIST_ENTRIES:
            raise WorkspaceError(
                f"工作区目录包含超过 {MAX_LIST_ENTRIES} 个项目，请进入子目录后重试。"
            )
        result = []
        for entry in entries:
            if entry.name in (".", "..") or self._is_symlink(entry):
                continue
            child = f"{relative}/{entry.name}".strip("/")
            result.append(
                {
                    "path": child,
                    "name": entry.name,
                    "isDirectory": bool(entry.is_dir),
                    "size": int(entry.size or 0),
                    "mimeType": False
                    if entry.is_dir
                    else (mimetypes.guess_type(entry.name)[0] or "application/octet-stream"),
                    "modifiedAt": entry.modified_at or entry.mod_time,
                }
            )
        return sorted(result, key=lambda item: (not item["isDirectory"], item["name"].lower()))

    @staticmethod
    def _validate_content(content: bytes):
        if not isinstance(content, bytes):
            raise WorkspaceError("文件内容格式无效，请使用二进制内容后重试。")
        if len(content) > MAX_UPLOAD_BYTES:
            raise WorkspaceError("文件内容超过 10 MB，请缩小文件后重试。")

    def _store_file(
        self,
        thread: str,
        path: str,
        content: bytes,
        mode: str,
    ) -> dict[str, Any]:
        self._validate_content(content)
        relative, remote = self.normalize_path(path, allow_root=False)
        sandbox = self.sandbox_for(thread)
        parent = remote.rsplit("/", 1)[0]
        self._ensure_directory(sandbox, parent)
        info = self._validate_destination(sandbox, relative, remote)
        if mode == "create" and info is not None:
            raise WorkspacePathConflict(
                f"文件“{relative}”已经存在。如需覆盖，请使用覆盖文件工具并确认。"
            )
        if mode == "replace" and info is None:
            raise WorkspaceError(f"文件“{relative}”不存在。如需新建，请使用新建文件工具。")
        if info is not None and info.is_dir:
            raise WorkspaceError("目标路径是目录，不能写入文件，请更换文件路径后重试。")
        if info is not None and not self._is_regular_file(info):
            raise WorkspaceError("目标路径不是普通文件，请更换文件路径后重试。")
        sandbox.fs.upload_file(content, remote)
        return {"path": relative, "size": len(content), "status": "synced"}

    def upload(self, thread: str, path: str, content: bytes) -> dict[str, Any]:
        """供 HTTP 上传和系统报表使用，保留覆盖已有文件的语义。"""
        return self._store_file(thread, path, content, "upload")

    def create_file(self, thread: str, path: str, content: bytes) -> dict[str, Any]:
        return self._store_file(thread, path, content, "create")

    def create_file_locked(self, thread: str, path: str, content: bytes) -> dict[str, Any]:
        relative, _remote = self.normalize_path(path, allow_root=False)
        lock_key = f"agui-workspace-file:{self._hash(thread)}:{relative}"
        with self.registry.locked(lock_key):
            return self.create_file(thread, relative, content)

    def replace_file(self, thread: str, path: str, content: bytes) -> dict[str, Any]:
        return self._store_file(thread, path, content, "replace")

    def file_bytes(self, thread: str, path: str) -> tuple[bytes, str]:
        relative, remote = self.normalize_path(path, allow_root=False)
        sandbox = self.sandbox_for(thread)
        self._validate_existing_path(sandbox, relative)
        info = self._info(sandbox, remote)
        if info.is_dir:
            raise WorkspaceError("所选项目是目录，不能作为文件下载，请选择普通文件。")
        if int(info.size or 0) > MAX_DOWNLOAD_BYTES:
            raise WorkspaceError("所选文件超过 25 MB，请缩小文件后重试。")
        content = self._download_file(sandbox, remote, MAX_DOWNLOAD_BYTES)
        if not isinstance(content, bytes) or len(content) > MAX_DOWNLOAD_BYTES:
            raise WorkspaceError("工作区返回的文件超过 25 MB，请缩小文件后重试。")
        return content, mimetypes.guess_type(relative)[0] or "application/octet-stream"

    @staticmethod
    def _download_file(sandbox: Any, remote: str, max_bytes: int) -> bytes:
        if remote.isascii():
            return sandbox.fs.download_file(remote)

        chunks = []
        total = 0
        for chunk in sandbox.fs.download_file_stream(remote):
            if not isinstance(chunk, bytes):
                raise WorkspaceError("工作区返回了无效的文件内容，请稍后重试。")
            total += len(chunk)
            if total > max_bytes:
                raise WorkspaceError("工作区返回的文件超过允许大小，请缩小文件后重试。")
            chunks.append(chunk)
        return b"".join(chunks)

    @staticmethod
    async def _adownload_file(sandbox: Any, remote: str, max_bytes: int) -> bytes:
        if remote.isascii():
            return await sandbox.fs.download_file(remote)

        chunks = []
        total = 0
        stream = await sandbox.fs.download_file_stream(remote)
        async for chunk in stream:
            if not isinstance(chunk, bytes):
                raise WorkspaceError("工作区返回了无效的文件内容，请稍后重试。")
            total += len(chunk)
            if total > max_bytes:
                raise WorkspaceError("工作区返回的文件超过允许大小，请缩小文件后重试。")
            chunks.append(chunk)
        return b"".join(chunks)

    def read_text(self, thread: str, path: str) -> str:
        relative, remote = self.normalize_path(path, allow_root=False)
        sandbox = self.sandbox_for(thread)
        self._validate_existing_path(sandbox, relative)
        info = self._info(sandbox, remote)
        if info.is_dir:
            raise WorkspaceError("所选项目是目录，不能作为文本文件读取。")
        if int(info.size or 0) > MAX_READ_BYTES:
            raise WorkspaceError("所选文件超过 1 MB，请下载后使用对应软件打开。")
        content = self._download_file(sandbox, remote, MAX_READ_BYTES)
        if not isinstance(content, bytes) or len(content) > MAX_READ_BYTES:
            raise WorkspaceError("工作区返回的文件超过 1 MB，请下载后使用对应软件打开。")
        if b"\x00" in content:
            raise WorkspaceError("该文件包含二进制内容，请下载后使用对应软件打开。")
        try:
            return content.decode("utf-8")
        except UnicodeDecodeError as error:
            raise WorkspaceError("该文件不是 UTF-8 文本，请下载后使用对应软件打开。") from error

    def delete_file(self, thread: str, path: str, recursive: bool = False):
        relative, remote = self.normalize_path(path, allow_root=False)
        sandbox = self.sandbox_for(thread)
        self._validate_existing_path(sandbox, relative)
        info = self._info(sandbox, remote)
        if info.is_dir and not recursive:
            raise WorkspaceError("所选项目是目录；如需删除，请启用递归删除并重新确认。")
        sandbox.fs.delete_file(remote, recursive=recursive)

    def move_file(self, thread: str, source: str, destination: str):
        source_relative, source_remote = self.normalize_path(source, allow_root=False)
        destination_relative, destination_remote = self.normalize_path(
            destination, allow_root=False
        )
        sandbox = self.sandbox_for(thread)
        self._validate_existing_path(sandbox, source_relative)
        source_info = self._info(sandbox, source_remote)
        if source_info.is_dir and (
            destination_relative == source_relative
            or destination_relative.startswith(f"{source_relative}/")
        ):
            raise WorkspaceError("目录不能移动到自身或其子目录，请更换目标路径后重试。")
        self._ensure_directory(sandbox, destination_remote.rsplit("/", 1)[0])
        if (
            self._validate_destination(sandbox, destination_relative, destination_remote)
            is not None
        ):
            raise WorkspaceError("目标路径已经存在，请更换名称后重试。")
        sandbox.fs.move_files(source_remote, destination_remote)

    @staticmethod
    def _bounded_output(value: Any) -> dict[str, Any]:
        output = str(getattr(value, "result", "") or "")
        encoded = output.encode("utf-8", errors="replace")
        truncated = len(encoded) > MAX_TOOL_OUTPUT_BYTES
        if truncated:
            output = encoded[:MAX_TOOL_OUTPUT_BYTES].decode("utf-8", errors="ignore")
        return {
            "exitCode": getattr(value, "exit_code", None),
            "output": output,
            "truncated": truncated,
        }

    @staticmethod
    def _validate_timeout(timeout: int) -> int:
        if isinstance(timeout, bool) or not isinstance(timeout, int):
            raise WorkspaceError("执行超时必须是整数秒，请修改后重试。")
        if not 1 <= timeout <= MAX_EXECUTION_TIMEOUT:
            raise WorkspaceError(
                f"执行超时必须在 1 至 {MAX_EXECUTION_TIMEOUT} 秒之间，请修改后重试。"
            )
        return timeout


def _thread(run_context: RunContext | None) -> str:
    if not run_context or not run_context.session_id:
        raise WorkspaceError("当前操作没有绑定对话，请刷新页面后重试。")
    return run_context.session_id


def _is_controlled_raw_dataset(path: str) -> bool:
    parts = PurePosixPath(str(path or "")).parts
    return bool(
        len(parts) == 5
        and parts[0:2] == ("报表", "原始数据")
        and parts[3] == "分片"
        and parts[4].endswith(".jsonl")
    ) or bool(len(parts) == 3 and parts[0:2] == ("reports", "data") and parts[2].endswith(".jsonl"))


class DaytonaToolkit(Toolkit):
    def __init__(self, service: WorkspaceService):
        self.service = service
        super().__init__(
            name="daytona_workspace",
            tools=[self.sandbox_exec],
            requires_confirmation_tools=["sandbox_exec"],
        )

    async def sandbox_exec(
        self,
        command: str,
        cwd: str | None = None,
        timeout: int = 30,
        run_context: RunContext | None = None,
    ) -> dict[str, Any]:
        """在当前对话的 Daytona sandbox 中执行命令；默认工作目录为 /home/daytona/workspace。命令切换到其他目录后，工作区文件须使用该目录下的绝对路径。"""
        if not isinstance(command, str) or not command.strip():
            raise WorkspaceError("命令不能为空。")
        execution_timeout = self.service._validate_timeout(timeout)
        remote_cwd = WORKSPACE_ROOT
        if cwd is not None:
            _relative, remote_cwd = self.service.normalize_path(cwd)
        async with self.service._async_client() as client:
            sandbox = await self.service._asandbox_for(client, _thread(run_context))
            value = await sandbox.process.exec(command, cwd=remote_cwd, timeout=execution_timeout)
        return self.service._bounded_output(value)


class WorkspaceToolkit(DaytonaToolkit):
    def __init__(self, service: WorkspaceService):
        super().__init__(service)
        for function in (
            self.workspace_list_files,
            self.workspace_read_file,
            self.workspace_write_file,
            self.workspace_replace_file,
            self.workspace_move_file,
            self.workspace_delete_file,
        ):
            self.register(function)
        for name in (
            "workspace_write_file",
            "workspace_replace_file",
            "workspace_move_file",
            "workspace_delete_file",
        ):
            self.functions[name].requires_confirmation = True

    def workspace_list_files(self, path: str = "", run_context: RunContext | None = None):
        """列出当前对话工作区中的文件。"""
        return json.dumps(self.service.list_files(_thread(run_context), path), ensure_ascii=False)

    def workspace_read_file(self, path: str, run_context: RunContext | None = None):
        """读取当前对话工作区中大小受限的 UTF-8 文本文件。"""
        if _is_controlled_raw_dataset(path):
            raise WorkspaceError("原始报表分片不能进入智能体上下文；请使用报表分析工具。")
        return self.service.read_text(_thread(run_context), path)

    def workspace_write_file(self, path: str, content: str, run_context: RunContext | None = None):
        """在当前对话工作区中新建 UTF-8 文件；执行前需要确认。"""
        result = self.service.create_file(_thread(run_context), path, content.encode("utf-8"))
        return {**result, "message": "文件已新建。"}

    def workspace_replace_file(
        self, path: str, content: str, run_context: RunContext | None = None
    ):
        """覆盖当前对话工作区中的普通 UTF-8 文件；执行前需要确认。"""
        result = self.service.replace_file(_thread(run_context), path, content.encode("utf-8"))
        return {**result, "message": "文件已覆盖。"}

    def workspace_move_file(
        self, source: str, destination: str, run_context: RunContext | None = None
    ):
        """移动或重命名当前对话工作区中的文件或目录；目标已存在时拒绝操作。"""
        self.service.move_file(_thread(run_context), source, destination)
        return {"ok": True, "message": "文件或目录已移动。"}

    def workspace_delete_file(
        self, path: str, recursive: bool = False, run_context: RunContext | None = None
    ):
        """删除当前对话工作区中的文件或目录；执行前需要确认。"""
        self.service.delete_file(_thread(run_context), path, recursive)
        return {"ok": True, "message": "文件或目录已删除。"}


class WorkspaceReportToolkit(WorkspaceToolkit):
    def __init__(self, service: WorkspaceService):
        super().__init__(service)
        for function in (
            self.report_list_capabilities,
            self.report_prepare_dataset,
            self.report_analyze_dataset,
            self.report_compile,
            self.report_render,
        ):
            self.register(function)
        self.async_functions["report_render"].requires_confirmation = True

    async def _report(self, action: str, payload: dict[str, Any], run_context: RunContext | None):
        from . import report_runtime

        content = open(report_runtime.__file__, "rb").read()
        digest = hashlib.sha256(content).hexdigest()
        remote = f"/tmp/workspace-report-runtime-{digest}.py"
        async with self.service._async_client() as client:
            sandbox = await self.service._asandbox_for(client, _thread(run_context))
            await sandbox.fs.upload_file(content, remote)
            command = f"python {shlex.quote(remote)} {shlex.quote(action)} {shlex.quote(json.dumps(payload, ensure_ascii=False))}"
            value = await sandbox.process.exec(command, cwd=WORKSPACE_ROOT, timeout=60)
        result = self.service._bounded_output(value)
        if result["exitCode"] != 0:
            raise WorkspaceError(result["output"] or "报表运行失败。")
        try:
            output = next(line for line in reversed(result["output"].splitlines()) if line.strip())
            return json.loads(output)
        except (StopIteration, json.JSONDecodeError) as error:
            raise WorkspaceError("报表运行时返回无效结果。") from error

    async def report_list_capabilities(self, run_context: RunContext | None = None):
        """检查固定报表运行时、依赖、格式、分析、图表与模板能力。"""
        return await self._report("capabilities", {}, run_context)

    async def report_prepare_dataset(
        self, paths: list[str], sheet_name: str | None = None, run_context: RunContext | None = None
    ):
        """从一至五个当前工作区相对路径准备统一数据集；附件直接使用 workspacePath，已选文件和 Odoo 导出直接使用 path，不接受绝对路径；未指定工作表时省略 sheet_name，空字符串按未指定处理。"""
        return await self._report(
            "prepare", {"paths": paths, "sheet_name": sheet_name}, run_context
        )

    async def report_analyze_dataset(
        self, job_id: str, operations: list[dict[str, Any]], run_context: RunContext | None = None
    ):
        """对已准备数据执行受控分析并保存可复用结果。"""
        return await self._report(
            "analyze", {"job_id": job_id, "operations": operations}, run_context
        )

    async def report_compile(
        self,
        job_id: str,
        title: str,
        template: str,
        blocks: list[dict[str, Any]],
        run_context: RunContext | None = None,
    ):
        """使用模板和已保存分析结果编排 PDF 报表。"""
        return await self._report(
            "compile",
            {"job_id": job_id, "title": title, "template": template, "blocks": blocks},
            run_context,
        )

    async def report_render(self, job_id: str, run_context: RunContext | None = None):
        """在 sandbox 内生成并校验最终 PDF；执行前需要确认。"""
        return await self._report("render", {"job_id": job_id}, run_context)

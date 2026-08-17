import asyncio
import difflib
import hashlib
import json
import mimetypes
import re
import shlex
import threading
import unicodedata
import uuid
from collections import OrderedDict
from collections.abc import Callable
from contextlib import asynccontextmanager, contextmanager
from io import BytesIO
from pathlib import PurePosixPath
from typing import Any

from agno.db.base import AsyncBaseDb, BaseDb
from agno.media import Image
from agno.run import RunContext
from agno.tools import Toolkit
from agno.tools.function import ToolResult
from daytona import (
    AsyncDaytona,
    CreateSandboxFromSnapshotParams,
    Daytona,
    ListSandboxesQuery,
    SessionExecuteRequest,
)
from daytona.common.errors import DaytonaNotFoundError
from sqlalchemy import Column, DateTime, MetaData, String, Table, insert, select, update
from sqlalchemy.sql import func

from .async_utils import complete_cleanup
from .database import AgentDatabase, create_agent_database
from .observability import suppress_expected_probe_tracing
from .security import thread_label

WORKSPACE_ROOT = "/home/daytona/workspace"
WORKSPACE_SNAPSHOT = "sandbox-tools"
MAX_UPLOAD_BYTES = 200 * 1024 * 1024
MAX_DOWNLOAD_BYTES = 200 * 1024 * 1024
MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_READ_BYTES = 1024 * 1024
MAX_TOOL_OUTPUT_BYTES = 64 * 1024
MAX_LIST_ENTRIES = 500
MAX_SEARCH_ENTRIES = 2000
MAX_SEARCH_RESULTS = 100
MAX_READ_LINES = 500
MAX_SEARCH_LINE_BYTES = 384
MAX_SEARCH_GLOBS = 20
MAX_SEARCH_GLOB_BYTES = 256
MAX_SEARCH_CONTEXT_LINES = 5
MAX_SEARCH_COMMAND_OUTPUT_BYTES = 2 * 1024 * 1024
MAX_PATCH_FILES = 20
MAX_PATCH_EDITS = 50
MAX_BATCH_HASH_CONCURRENCY = 8
MAX_BATCH_HASH_FILE_TIMEOUT = 30
MAX_BATCH_HASH_TIMEOUT = 60
MAX_ASYNC_DOWNLOAD_TIMEOUT = 5 * 60
MAX_ISOLATED_CLIENT_CLOSE_TIMEOUT = 5
MAX_PATH_BYTES = 1024
MAX_PATH_COMPONENT_BYTES = 255
MAX_PATH_DEPTH = 32
MAX_EXECUTION_TIMEOUT = 60
MAX_BACKGROUND_EXECUTION_TIMEOUT = 24 * 60 * 60
MAX_MANAGED_PROCESSES = 4
MAX_PROCESS_INPUT_BYTES = 8 * 1024
MAX_PTY_ROWS = 200
MAX_PTY_COLS = 400
MAX_GIT_LOG_ENTRIES = 100
MAX_BRANCH_FILES = 2000
MAX_BRANCH_TOTAL_BYTES = 256 * 1024 * 1024
MAX_BRANCH_FILE_BYTES = 200 * 1024 * 1024
MAX_INSPECT_PDF_PAGES = 200
MAX_SANDBOX_ID_CACHE_ENTRIES = 1024
IMAGE_SUFFIXES = {".gif", ".jpeg", ".jpg", ".png", ".webp"}
MANAGED_PROCESS_PREFIX = "agent-exec-"
MANAGED_TIMEOUT_ENV = "AGENT_MANAGED_TIMEOUT_MARKER"
MANAGED_TIMEOUT_OUTPUT_PREFIX = "__AGENT_MANAGED_TIMEOUT__"


class WorkspaceError(ValueError):
    pass


class WorkspaceProcessNotFound(WorkspaceError):
    pass


class WorkspacePathConflict(WorkspaceError):
    pass


class SandboxRegistry:
    def __init__(self, database: BaseDb | str | None = None):
        self._database_bundle = (
            create_agent_database(database if isinstance(database, str) else None)
            if database is None or isinstance(database, str)
            else None
        )
        if self._database_bundle is not None:
            resolved_database = self._database_bundle.sync_db
        else:
            assert isinstance(database, BaseDb)
            resolved_database = database
        self.db: BaseDb = resolved_database
        schema = getattr(self.db, "db_schema", None)
        self.metadata = MetaData(schema=schema)
        self.table = Table(
            "agent_workspace_sandbox",
            self.metadata,
            Column("thread_hash", String(64), primary_key=True),
            Column("sandbox_id", String(256), nullable=False),
            Column(
                "updated_at",
                DateTime(timezone=True),
                nullable=False,
                server_default=func.current_timestamp(),
            ),
        )
        self._initialized = False

    def _connect(self):
        return self.db.db_engine.connect()  # type: ignore[attr-defined,no-any-return]

    def ensure_initialized(self):
        if self._initialized:
            return
        with self._connect() as connection, connection.begin():
            if connection.dialect.name == "postgresql":
                if self.metadata.schema:
                    connection.exec_driver_sql(
                        f'CREATE SCHEMA IF NOT EXISTS "{self.metadata.schema}"'
                    )
                connection.exec_driver_sql(
                    "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                    ("agent-workspace:initialize",),
                )
            self.metadata.create_all(connection)
        self.db.upsert_schema_version(self.table.name, "1.0.0")
        self._initialized = True

    @contextmanager
    def locked(self, value: str):
        self.ensure_initialized()
        with self._connect() as connection:
            if connection.dialect.name == "sqlite":
                connection.exec_driver_sql("BEGIN IMMEDIATE")
                try:
                    yield SandboxRegistryTransaction(connection, self.table)
                    connection.commit()
                except Exception:
                    connection.rollback()
                    raise
            else:
                with connection.begin():
                    connection.exec_driver_sql(
                        "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                        (value,),
                    )
                    yield SandboxRegistryTransaction(connection, self.table)


class SandboxRegistryTransaction:
    def __init__(self, connection, table: Table):
        self.connection = connection
        self.table = table

    def get(self, value: str) -> str | None:
        row = self.connection.execute(
            select(self.table.c.sandbox_id).where(self.table.c.thread_hash == value)
        ).first()
        return row[0] if row else None

    def set(self, value: str, sandbox_id: str):
        exists = self.connection.execute(
            select(self.table.c.thread_hash).where(self.table.c.thread_hash == value)
        ).first()
        statement = (
            update(self.table)
            .where(self.table.c.thread_hash == value)
            .values(sandbox_id=sandbox_id, updated_at=func.current_timestamp())
            if exists
            else insert(self.table).values(thread_hash=value, sandbox_id=sandbox_id)
        )
        self.connection.execute(statement)

    def delete(self, value: str):
        self.connection.execute(self.table.delete().where(self.table.c.thread_hash == value))


class AsyncSandboxRegistry:
    def __init__(self, database: AsyncBaseDb | str | None = None):
        self._database_bundle = (
            create_agent_database(database if isinstance(database, str) else None)
            if database is None or isinstance(database, str)
            else None
        )
        if self._database_bundle is not None:
            resolved_database = self._database_bundle.async_db
        else:
            assert isinstance(database, AsyncBaseDb)
            resolved_database = database
        self.db: AsyncBaseDb = resolved_database
        schema = getattr(self.db, "db_schema", None)
        self.metadata = MetaData(schema=schema)
        self.table = Table(
            "agent_workspace_sandbox",
            self.metadata,
            Column("thread_hash", String(64), primary_key=True),
            Column("sandbox_id", String(256), nullable=False),
            Column(
                "updated_at",
                DateTime(timezone=True),
                nullable=False,
                server_default=func.current_timestamp(),
            ),
        )
        self._initialized = False
        self._initialize_lock = asyncio.Lock()

    def _connect(self):
        return self.db.db_engine.connect()  # type: ignore[attr-defined,no-any-return]

    async def ensure_initialized(self):
        if self._initialized:
            return
        async with self._initialize_lock:
            if self._initialized:
                return
            async with self._connect() as connection:
                async with connection.begin():
                    if connection.dialect.name == "postgresql":
                        if self.metadata.schema:
                            await connection.exec_driver_sql(
                                f'CREATE SCHEMA IF NOT EXISTS "{self.metadata.schema}"'
                            )
                        await connection.exec_driver_sql(
                            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                            ("agent-workspace:initialize",),
                        )
                    await connection.run_sync(self.metadata.create_all)
            await self.db.upsert_schema_version(self.table.name, "1.0.0")
            self._initialized = True

    @asynccontextmanager
    async def locked(self, value: str):
        await self.ensure_initialized()
        async with self._connect() as connection:
            if connection.dialect.name == "sqlite":
                await connection.exec_driver_sql("BEGIN IMMEDIATE")
                try:
                    yield AsyncSandboxRegistryTransaction(connection, self.table)
                    await connection.commit()
                except Exception:
                    await connection.rollback()
                    raise
            else:
                async with connection.begin():
                    await connection.exec_driver_sql(
                        "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                        (value,),
                    )
                    yield AsyncSandboxRegistryTransaction(connection, self.table)


class AsyncSandboxRegistryTransaction:
    def __init__(self, connection, table: Table):
        self.connection = connection
        self.table = table

    async def get(self, value: str) -> str | None:
        row = (
            await self.connection.execute(
                select(self.table.c.sandbox_id).where(self.table.c.thread_hash == value)
            )
        ).first()
        return row[0] if row else None

    async def set(self, value: str, sandbox_id: str):
        exists = (
            await self.connection.execute(
                select(self.table.c.thread_hash).where(self.table.c.thread_hash == value)
            )
        ).first()
        statement = (
            update(self.table)
            .where(self.table.c.thread_hash == value)
            .values(sandbox_id=sandbox_id, updated_at=func.current_timestamp())
            if exists
            else insert(self.table).values(thread_hash=value, sandbox_id=sandbox_id)
        )
        await self.connection.execute(statement)

    async def delete(self, value: str):
        await self.connection.execute(self.table.delete().where(self.table.c.thread_hash == value))


class WorkspaceService:
    def __init__(
        self,
        secret: str,
        client: Any | None = None,
        registry: SandboxRegistry | None = None,
        async_client: Any | None = None,
        async_registry: Any | None = None,
        database: AgentDatabase | None = None,
        snapshot: str = WORKSPACE_SNAPSHOT,
        network_allow_list: str | None = None,
    ):
        self.secret = secret
        self.snapshot = snapshot
        self.network_allow_list = network_allow_list
        self._client = client
        self.registry = registry or SandboxRegistry(database.sync_db if database else None)
        self._async_client_override = async_client
        self._owned_async_client: Any | None = None
        self._async_client_close_task: asyncio.Task[None] | None = None
        self._async_client_closed = False
        self._async_client_state_lock = threading.Lock()
        self._sandbox_ids: OrderedDict[str, str] = OrderedDict()
        self._sandbox_ids_lock = threading.Lock()
        self.async_registry = async_registry or AsyncSandboxRegistry(
            database.async_db if database else None
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
        with self._async_client_state_lock:
            if self._async_client_closed:
                raise WorkspaceError("Daytona 客户端已经关闭。")
            if self._owned_async_client is None:
                self._owned_async_client = AsyncDaytona()
            client = self._owned_async_client
        yield client

    @asynccontextmanager
    async def _isolated_async_client(self):
        if self._async_client_override is not None:
            yield self._async_client_override
            return
        client = AsyncDaytona()
        try:
            yield client
        finally:
            # 正式验收会密集下载多个产物复核哈希，不得复用长生命周期 client。
            # 远端半关闭连接时 SDK close 也可能等待，因此清理必须抵抗外层取消且有硬上限；
            # 该 client 不再复用，关闭超时不能覆盖已经完成的可信哈希结果。
            try:
                await complete_cleanup(
                    asyncio.wait_for(
                        client.close(),
                        timeout=MAX_ISOLATED_CLIENT_CLOSE_TIMEOUT,
                    )
                )
            except TimeoutError:
                pass

    async def aclose(self) -> None:
        if self._async_client_override is not None:
            return
        with self._async_client_state_lock:
            self._async_client_closed = True
            close_task = self._async_client_close_task
            if close_task is None and self._owned_async_client is not None:
                close_task = asyncio.create_task(self._owned_async_client.close())
                self._async_client_close_task = close_task
        if close_task is not None:
            await complete_cleanup(close_task)

    def _cached_sandbox_id(self, value: str) -> str | None:
        with self._sandbox_ids_lock:
            sandbox_id = self._sandbox_ids.get(value)
            if sandbox_id is not None:
                self._sandbox_ids.move_to_end(value)
            return sandbox_id

    def _cache_sandbox_id(self, value: str, sandbox_id: str) -> None:
        with self._sandbox_ids_lock:
            self._sandbox_ids[value] = sandbox_id
            self._sandbox_ids.move_to_end(value)
            while len(self._sandbox_ids) > MAX_SANDBOX_ID_CACHE_ENTRIES:
                self._sandbox_ids.popitem(last=False)

    def _invalidate_sandbox_id(self, value: str, sandbox_id: str | None = None) -> None:
        with self._sandbox_ids_lock:
            if sandbox_id is None or self._sandbox_ids.get(value) == sandbox_id:
                self._sandbox_ids.pop(value, None)

    def _hash(self, thread: str) -> str:
        return thread_label(thread, self.secret)

    def _sandbox_network_settings(self) -> dict[str, Any]:
        if self.network_allow_list:
            return {"network_allow_list": self.network_allow_list}
        return {"network_block_all": True}

    def _find_existing(self, value: str, registry):
        sandbox_id = registry.get(value)
        if sandbox_id:
            try:
                sandbox = self.client.get(sandbox_id)
                self._cache_sandbox_id(value, sandbox_id)
                return sandbox
            except DaytonaNotFoundError:
                self._invalidate_sandbox_id(value, sandbox_id)
                registry.delete(value)
        matches = list(
            self.client.list(
                ListSandboxesQuery(
                    labels={"agent-thread": value},
                    limit=2,
                )
            )
        )
        if len(matches) > 1:
            raise WorkspaceError("当前对话关联了多个运行环境，请联系管理员清理后重试。")
        if matches:
            registry.set(value, matches[0].id)
            self._cache_sandbox_id(value, matches[0].id)
            return matches[0]
        return None

    def _ready_sandbox(self, sandbox: Any):
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

    def sandbox_for(self, thread: str, create: bool = True):
        value = self._hash(thread)
        sandbox = None
        sandbox_id = self._cached_sandbox_id(value)
        if sandbox_id is not None:
            try:
                sandbox = self.client.get(sandbox_id)
            except DaytonaNotFoundError:
                self._invalidate_sandbox_id(value, sandbox_id)
        if sandbox is None:
            with self.registry.locked(value) as registry:
                sandbox = self._find_existing(value, registry)
                if sandbox is None and create:
                    sandbox = self.client.create(
                        CreateSandboxFromSnapshotParams(
                            snapshot=self.snapshot,
                            name=f"agent-{value[:20]}",
                            language="python",
                            labels={"agent-thread": value},
                            public=False,
                            ephemeral=False,
                            auto_stop_interval=60,
                            auto_archive_interval=0,
                            auto_delete_interval=-1,
                            **self._sandbox_network_settings(),
                        )
                    )
                    registry.set(value, sandbox.id)
                    self._cache_sandbox_id(value, sandbox.id)
        if sandbox is None:
            return None
        return self._ready_sandbox(sandbox)

    def destroy(self, thread: str) -> bool:
        value = self._hash(thread)
        self._invalidate_sandbox_id(value)
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
                    labels={"agent-thread": value},
                )
            ):
                sandboxes[sandbox.id] = sandbox
            for sandbox in sandboxes.values():
                try:
                    self.client.delete(sandbox)
                except DaytonaNotFoundError:
                    pass
            registry.delete(value)
            self._invalidate_sandbox_id(value)
            return bool(sandboxes)

    async def _afind_existing(self, client: Any, value: str, registry: Any):
        sandbox_id = await registry.get(value)
        if sandbox_id:
            try:
                sandbox = await client.get(sandbox_id)
                self._cache_sandbox_id(value, sandbox_id)
                return sandbox
            except DaytonaNotFoundError:
                self._invalidate_sandbox_id(value, sandbox_id)
                await registry.delete(value)
        matches = [
            sandbox
            async for sandbox in client.list(
                ListSandboxesQuery(
                    labels={"agent-thread": value},
                    limit=2,
                )
            )
        ]
        if len(matches) > 1:
            raise WorkspaceError("当前对话关联了多个运行环境，请联系管理员清理后重试。")
        if matches:
            await registry.set(value, matches[0].id)
            self._cache_sandbox_id(value, matches[0].id)
            return matches[0]
        return None

    async def _aready_sandbox(self, client: Any, sandbox: Any):
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

    async def _asandbox_for(self, client: Any, thread: str, create: bool = True):
        value = self._hash(thread)
        sandbox = None
        sandbox_id = self._cached_sandbox_id(value)
        if sandbox_id is not None:
            try:
                sandbox = await client.get(sandbox_id)
            except DaytonaNotFoundError:
                self._invalidate_sandbox_id(value, sandbox_id)
        if sandbox is None:
            async with self.async_registry.locked(value) as registry:
                sandbox = await self._afind_existing(client, value, registry)
                if sandbox is None and create:
                    sandbox = await client.create(
                        CreateSandboxFromSnapshotParams(
                            snapshot=self.snapshot,
                            name=f"agent-{value[:20]}",
                            language="python",
                            labels={"agent-thread": value},
                            public=False,
                            ephemeral=False,
                            auto_stop_interval=60,
                            auto_archive_interval=0,
                            auto_delete_interval=-1,
                            **self._sandbox_network_settings(),
                        )
                    )
                    await registry.set(value, sandbox.id)
                    self._cache_sandbox_id(value, sandbox.id)
        if sandbox is None:
            return None
        return await self._aready_sandbox(client, sandbox)

    async def _adestroy(self, client: Any, thread: str) -> bool:
        value = self._hash(thread)
        self._invalidate_sandbox_id(value)
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
                    labels={"agent-thread": value},
                )
            ):
                sandboxes[sandbox.id] = sandbox
            for sandbox in sandboxes.values():
                try:
                    await client.delete(sandbox)
                except DaytonaNotFoundError:
                    pass
            await registry.delete(value)
            self._invalidate_sandbox_id(value)
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
                    raise WorkspaceError("源工作区存在超过 200 MiB 的文件，无法创建分支。")
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

    async def _avalidate_existing_path(
        self, sandbox: Any, relative: str, include_leaf: bool = True
    ) -> None:
        parts = relative.split("/") if relative else []
        end = len(parts) if include_leaf else max(0, len(parts) - 1)
        for index in range(1, end + 1):
            remote = f"{WORKSPACE_ROOT}/{'/'.join(parts[:index])}"
            try:
                info = await self._ainfo(sandbox, remote)
            except DaytonaNotFoundError as error:
                raise WorkspaceError("工作区路径不存在，请检查名称后重试。") from error
            if self._is_symlink(info):
                raise WorkspaceError("工作区路径包含符号链接，请改用普通文件或目录。")

    def _validate_destination(self, sandbox, relative: str, remote: str):
        self._validate_existing_path(sandbox, relative, include_leaf=False)
        try:
            with suppress_expected_probe_tracing():
                info = self._info(sandbox, remote)
        except DaytonaNotFoundError:
            return None
        if self._is_symlink(info):
            raise WorkspaceError("工作区路径包含符号链接，请改用普通文件或目录。")
        return info

    def _ensure_directory(self, sandbox, remote: str):
        if remote == WORKSPACE_ROOT:
            try:
                with suppress_expected_probe_tracing():
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
                with suppress_expected_probe_tracing():
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
                with suppress_expected_probe_tracing():
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
                with suppress_expected_probe_tracing():
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

    async def alist_files(self, thread: str, path: str = "") -> list[dict[str, Any]]:
        relative, remote = self.normalize_path(path)
        async with self._async_client() as client:
            sandbox = await self._asandbox_for(client, thread)
            await self._avalidate_existing_path(sandbox, relative)
            entries = await sandbox.fs.list_files(remote)
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
            raise WorkspaceError("文件内容超过 200 MiB，请缩小文件后重试。")

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
        return self._store_file_in_sandbox(sandbox, relative, remote, content, mode)

    def _store_file_in_sandbox(
        self,
        sandbox: Any,
        relative: str,
        remote: str,
        content: bytes,
        mode: str,
    ) -> dict[str, Any]:
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
        lock_key = f"agent-workspace-file:{self._hash(thread)}:{relative}"
        with self.registry.locked(lock_key):
            return self.create_file(thread, relative, content)

    def replace_file(self, thread: str, path: str, content: bytes) -> dict[str, Any]:
        return self._store_file(thread, path, content, "replace")

    def file_bytes(self, thread: str, path: str) -> tuple[bytes, str]:
        relative, remote = self.normalize_path(path, allow_root=False)
        sandbox = self.sandbox_for(thread)
        return self._file_bytes_from_sandbox(sandbox, relative, remote)

    def _file_bytes_from_sandbox(
        self, sandbox: Any, relative: str, remote: str
    ) -> tuple[bytes, str]:
        self._validate_existing_path(sandbox, relative)
        info = self._info(sandbox, remote)
        if info.is_dir:
            raise WorkspaceError("所选项目是目录，不能作为文件下载，请选择普通文件。")
        if int(info.size or 0) > MAX_DOWNLOAD_BYTES:
            raise WorkspaceError("所选文件超过 200 MiB，请缩小文件后重试。")
        content = self._download_file(sandbox, remote, MAX_DOWNLOAD_BYTES)
        if not isinstance(content, bytes) or len(content) > MAX_DOWNLOAD_BYTES:
            raise WorkspaceError("工作区返回的文件超过 200 MiB，请缩小文件后重试。")
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
    async def _adownload_file(
        sandbox: Any,
        remote: str,
        max_bytes: int,
        *,
        timeout: int | float = MAX_ASYNC_DOWNLOAD_TIMEOUT,
    ) -> bytes:
        chunks = []
        total = 0
        # 普通下载和流式下载在 Daytona SDK 中是两条不同实现。统一使用流式接口，
        # 避免路径字符集改变网络行为，并显式覆盖 SDK 30 分钟的默认等待时间。
        stream = await sandbox.fs.download_file_stream(remote, timeout=timeout)
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

    @staticmethod
    def _validate_page_window(limit: int, offset: int) -> tuple[int, int]:
        if (
            isinstance(limit, bool)
            or not isinstance(limit, int)
            or not 1 <= limit <= MAX_SEARCH_RESULTS
        ):
            raise WorkspaceError(f"结果数量必须是 1 至 {MAX_SEARCH_RESULTS} 之间的整数。")
        if (
            isinstance(offset, bool)
            or not isinstance(offset, int)
            or not 0 <= offset < MAX_SEARCH_ENTRIES
        ):
            raise WorkspaceError(f"结果偏移必须是 0 至 {MAX_SEARCH_ENTRIES - 1} 之间的整数。")
        return limit, offset

    @staticmethod
    def _search_line_excerpt(line: str, match_index: int) -> str:
        encoded = line.encode("utf-8")
        if len(encoded) <= MAX_SEARCH_LINE_BYTES:
            return line
        start = max(0, match_index - 96)
        excerpt = line[start:]
        clipped = excerpt.encode("utf-8")[:MAX_SEARCH_LINE_BYTES].decode("utf-8", errors="ignore")
        return (
            ("..." if start else "") + clipped + ("..." if start + len(clipped) < len(line) else "")
        )

    @staticmethod
    def _validate_search_globs(
        include_globs: list[str] | None,
        exclude_globs: list[str] | None,
    ) -> tuple[list[str], list[str]]:
        validated: list[list[str]] = []
        for label, values in (("包含", include_globs), ("排除", exclude_globs)):
            if values is None:
                validated.append([])
                continue
            if not isinstance(values, list) or len(values) > MAX_SEARCH_GLOBS:
                raise WorkspaceError(f"{label} glob 必须是最多 {MAX_SEARCH_GLOBS} 项的数组。")
            current = []
            for value in values:
                if (
                    not isinstance(value, str)
                    or not value
                    or value.startswith("!")
                    or len(value.encode("utf-8")) > MAX_SEARCH_GLOB_BYTES
                    or any(character in value for character in ("\x00", "\n", "\r"))
                ):
                    raise WorkspaceError(
                        f"{label} glob 必须是非空、不能以 ! 开头且不超过 "
                        f"{MAX_SEARCH_GLOB_BYTES} 字节的字符串。"
                    )
                current.append(value)
            validated.append(current)
        return validated[0], validated[1]

    @staticmethod
    def _validate_search_context(value: int, label: str) -> int:
        if (
            isinstance(value, bool)
            or not isinstance(value, int)
            or not 0 <= value <= MAX_SEARCH_CONTEXT_LINES
        ):
            raise WorkspaceError(f"{label}必须是 0 至 {MAX_SEARCH_CONTEXT_LINES} 之间的整数。")
        return value

    @staticmethod
    def _rg_command(arguments: list[str]) -> str:
        pipeline = f"{shlex.join(arguments)} | head -c {MAX_SEARCH_COMMAND_OUTPUT_BYTES}"
        return f"/bin/bash --noprofile --norc -o pipefail -c {shlex.quote(pipeline)}"

    @classmethod
    def _normalize_rg_path(cls, value: Any) -> str | None:
        if not isinstance(value, str) or not value:
            return None
        candidate = value[2:] if value.startswith("./") else value
        try:
            relative = cls.normalize_path(candidate, allow_root=False)[0]
        except WorkspaceError:
            return None
        return None if _is_controlled_raw_dataset(relative) else relative

    @staticmethod
    def _fit_search_result(
        mode: str,
        key: str,
        items: list[dict[str, Any]],
        truncated: bool,
    ) -> dict[str, Any]:
        selected = list(items)
        while selected:
            result = {"mode": mode, key: selected, "truncated": truncated}
            if len(json.dumps(result, ensure_ascii=False).encode("utf-8")) <= MAX_TOOL_OUTPUT_BYTES:
                return result
            selected.pop()
            truncated = True
        return {"mode": mode, key: [], "truncated": truncated or bool(items)}

    async def _arun_rg(
        self,
        thread: str,
        relative: str,
        remote: str,
        arguments: list[str],
    ) -> tuple[str, bool]:
        async with self._async_client() as client:
            sandbox = await self._asandbox_for(client, thread)
            await self._avalidate_existing_path(sandbox, relative)
            root = await self._ainfo(sandbox, remote)
            if self._is_symlink(root) or not (root.is_dir or self._is_regular_file(root)):
                raise WorkspaceError("工作区路径不是普通文件或目录。")
            value = await sandbox.process.exec(
                self._rg_command(arguments),
                cwd=WORKSPACE_ROOT,
                timeout=MAX_EXECUTION_TIMEOUT,
            )

        exit_code = getattr(value, "exit_code", None)
        raw_value = getattr(value, "result", "")
        if isinstance(raw_value, bytes):
            output = raw_value.decode("utf-8", errors="replace")
        else:
            output = str(raw_value or "")
        encoded = output.encode("utf-8", errors="replace")
        output_truncated = len(encoded) >= MAX_SEARCH_COMMAND_OUTPUT_BYTES or exit_code == 141
        if len(encoded) > MAX_SEARCH_COMMAND_OUTPUT_BYTES:
            output = encoded[:MAX_SEARCH_COMMAND_OUTPUT_BYTES].decode("utf-8", errors="ignore")
        if exit_code not in (0, 1, 141):
            if exit_code == 127:
                raise WorkspaceError("当前工作区缺少搜索组件，请重新构建并激活工具 Snapshot。")
            raise WorkspaceError("工作区搜索失败，请检查正则表达式和搜索参数后重试。")
        return output, output_truncated

    @staticmethod
    def _rg_base_arguments() -> list[str]:
        return [
            "rg",
            "--no-config",
            "--no-messages",
            "--color",
            "never",
            "--sort",
            "path",
            "--max-filesize",
            "200M",
        ]

    @staticmethod
    def _append_rg_globs(
        arguments: list[str], include_globs: list[str], exclude_globs: list[str]
    ) -> None:
        for value in include_globs:
            arguments.extend(("--glob", value))
        for value in exclude_globs:
            arguments.extend(("--glob", f"!{value}"))
        arguments.extend(
            (
                "--glob",
                "!报表/原始数据/*/分片/*.jsonl",
                "--glob",
                "!reports/data/*.jsonl",
            )
        )

    async def asearch_files(
        self,
        thread: str,
        pattern: str = "*",
        path: str = "",
        include_globs: list[str] | None = None,
        exclude_globs: list[str] | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        if not isinstance(pattern, str) or not pattern:
            raise WorkspaceError("文件搜索模式不能为空。")
        limit, offset = self._validate_page_window(limit, offset)
        includes, excludes = self._validate_search_globs(
            [pattern] if include_globs is None else include_globs,
            exclude_globs,
        )
        relative, remote = self.normalize_path(path)
        if _is_controlled_raw_dataset(relative):
            raise WorkspaceError("原始报表分片不能通过基础搜索工具读取；请使用报表分析工具。")
        arguments = [*self._rg_base_arguments(), "--files", "--null"]
        self._append_rg_globs(arguments, includes, excludes)
        arguments.extend(("--", relative or "."))
        output, output_truncated = await self._arun_rg(thread, relative, remote, arguments)

        parts = output.split("\x00")
        if parts and parts[-1]:
            output_truncated = True
            parts.pop()
        else:
            parts = parts[:-1]
        paths = sorted(
            {
                normalized
                for value in parts
                if (normalized := self._normalize_rg_path(value)) is not None
            }
        )
        output_truncated = output_truncated or len(paths) > offset + limit
        matches = []
        async with self._async_client() as client:
            sandbox = await self._asandbox_for(client, thread)
            for found in paths[offset : offset + limit]:
                try:
                    info = await self._ainfo(sandbox, f"{WORKSPACE_ROOT}/{found}")
                except DaytonaNotFoundError:
                    output_truncated = True
                    continue
                if not self._is_regular_file(info):
                    continue
                matches.append(
                    {
                        "path": found,
                        "name": PurePosixPath(found).name,
                        "size": int(info.size or 0),
                    }
                )
        result = self._fit_search_result("files", "matches", matches, output_truncated)
        result.pop("mode")
        return result

    @classmethod
    def _parse_rg_matches(
        cls,
        output: str,
        before_context: int,
        after_context: int,
    ) -> tuple[list[dict[str, Any]], bool]:
        matches: list[dict[str, Any]] = []
        pending: dict[str, list[dict[str, Any]]] = {}
        last_match: dict[str, dict[str, Any]] = {}
        malformed = False
        for raw_line in output.splitlines():
            try:
                event = json.loads(raw_line)
            except (TypeError, json.JSONDecodeError):
                malformed = True
                continue
            event_type = event.get("type")
            data = event.get("data")
            if event_type not in {"match", "context"} or not isinstance(data, dict):
                continue
            path_data = data.get("path")
            line_data = data.get("lines")
            if not isinstance(path_data, dict) or not isinstance(line_data, dict):
                continue
            path = cls._normalize_rg_path(path_data.get("text"))
            text = line_data.get("text")
            line_number = data.get("line_number")
            if path is None or not isinstance(text, str) or not isinstance(line_number, int):
                continue
            line_text = text.rstrip("\r\n")
            if event_type == "context":
                context = {
                    "line": line_number,
                    "text": cls._search_line_excerpt(line_text, 0),
                }
                previous = last_match.get(path)
                if (
                    previous is not None
                    and line_number > previous["line"]
                    and len(previous.get("after", [])) < after_context
                ):
                    previous.setdefault("after", []).append(context)
                if before_context:
                    pending[path] = [*pending.get(path, []), context][-before_context:]
                continue

            submatches = data.get("submatches")
            start_byte = 0
            if isinstance(submatches, list) and submatches and isinstance(submatches[0], dict):
                raw_start = submatches[0].get("start", 0)
                if isinstance(raw_start, int) and raw_start >= 0:
                    start_byte = raw_start
            prefix = line_text.encode("utf-8")[:start_byte].decode("utf-8", errors="ignore")
            column = len(prefix) + 1
            match = {
                "path": path,
                "line": line_number,
                "column": column,
                "text": cls._search_line_excerpt(line_text, column - 1),
            }
            if before_context:
                match["before"] = list(pending.get(path, []))
            if after_context:
                match["after"] = []
            matches.append(match)
            last_match[path] = match
        return sorted(
            matches, key=lambda item: (item["path"], item["line"], item["column"])
        ), malformed

    @classmethod
    def _parse_rg_paths(cls, output: str) -> tuple[list[str], bool]:
        parts = output.split("\x00")
        malformed = bool(parts and parts[-1])
        if malformed:
            parts.pop()
        else:
            parts = parts[:-1]
        return sorted(
            {
                normalized
                for value in parts
                if (normalized := cls._normalize_rg_path(value)) is not None
            }
        ), malformed

    @classmethod
    def _parse_rg_counts(cls, output: str) -> tuple[list[dict[str, Any]], bool]:
        counts = []
        cursor = 0
        malformed = False
        while cursor < len(output):
            separator = output.find("\x00", cursor)
            line_end = output.find("\n", separator + 1) if separator >= 0 else -1
            if separator < 0 or line_end < 0:
                malformed = True
                break
            path = cls._normalize_rg_path(output[cursor:separator])
            raw_count = output[separator + 1 : line_end]
            if path is not None:
                try:
                    count = int(raw_count)
                except ValueError:
                    malformed = True
                else:
                    counts.append({"path": path, "count": count})
            cursor = line_end + 1
        return sorted(counts, key=lambda item: item["path"]), malformed

    async def asearch_text(
        self,
        thread: str,
        query: str,
        path: str = "",
        include_globs: list[str] | None = None,
        exclude_globs: list[str] | None = None,
        regex: bool = False,
        case_mode: str = "smart",
        word_match: bool = False,
        before_context: int = 0,
        after_context: int = 0,
        mode: str = "matches",
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        if not isinstance(query, str) or not query:
            raise WorkspaceError("文本搜索内容不能为空。")
        if len(query.encode("utf-8")) > 1024 or "\x00" in query:
            raise WorkspaceError("文本搜索内容超过 1024 字节或包含空字符，请修改后重试。")
        if not isinstance(regex, bool) or not isinstance(word_match, bool):
            raise WorkspaceError("正则和整词搜索标志必须是布尔值。")
        if case_mode not in {"smart", "sensitive", "insensitive"}:
            raise WorkspaceError("大小写模式必须是 smart、sensitive 或 insensitive。")
        if mode not in {"matches", "files_with_matches", "count"}:
            raise WorkspaceError("输出模式必须是 matches、files_with_matches 或 count。")
        before_context = self._validate_search_context(before_context, "前置上下文行数")
        after_context = self._validate_search_context(after_context, "后置上下文行数")
        limit, offset = self._validate_page_window(limit, offset)
        includes, excludes = self._validate_search_globs(include_globs, exclude_globs)
        relative, remote = self.normalize_path(path)
        if _is_controlled_raw_dataset(relative):
            raise WorkspaceError("原始报表分片不能通过基础搜索工具读取；请使用报表分析工具。")

        arguments = self._rg_base_arguments()
        if mode == "matches":
            arguments.append("--json")
        elif mode == "files_with_matches":
            arguments.extend(("--files-with-matches", "--null"))
        else:
            arguments.extend(("--count", "--null"))
        if not regex:
            arguments.append("--fixed-strings")
        arguments.append(
            {
                "smart": "--smart-case",
                "sensitive": "--case-sensitive",
                "insensitive": "--ignore-case",
            }[case_mode]
        )
        if word_match:
            arguments.append("--word-regexp")
        if mode == "matches" and before_context:
            arguments.extend(("--before-context", str(before_context)))
        if mode == "matches" and after_context:
            arguments.extend(("--after-context", str(after_context)))
        self._append_rg_globs(arguments, includes, excludes)
        arguments.extend(("--", query, relative or "."))
        output, output_truncated = await self._arun_rg(thread, relative, remote, arguments)

        if mode == "matches":
            items, malformed = self._parse_rg_matches(output, before_context, after_context)
            key = "matches"
        elif mode == "files_with_matches":
            paths, malformed = self._parse_rg_paths(output)
            items = [{"path": value} for value in paths]
            key = "files"
        else:
            items, malformed = self._parse_rg_counts(output)
            key = "counts"
        truncated = output_truncated or malformed or len(items) > offset + limit
        return self._fit_search_result(mode, key, items[offset : offset + limit], truncated)

    @staticmethod
    def _shell_command(command: str, *, pipefail: bool = False) -> str:
        options = " -o pipefail" if pipefail else ""
        return f"/bin/bash --noprofile --norc{options} -c {shlex.quote(command)}"

    async def _arun_workspace_command(
        self,
        thread: str,
        relative: str,
        remote: str,
        command: str,
        *,
        expected_type: str,
        failure_message: str,
        output_limit: int = MAX_SEARCH_COMMAND_OUTPUT_BYTES,
        accepted_exit_codes: tuple[int, ...] = (0,),
        failure_classifier: Callable[[str], str] | None = None,
    ) -> tuple[str, bool]:
        async with self._async_client() as client:
            sandbox = await self._asandbox_for(client, thread)
            await self._avalidate_existing_path(sandbox, relative)
            info = await self._ainfo(sandbox, remote)
            if self._is_symlink(info):
                raise WorkspaceError("工作区路径包含符号链接，请改用普通文件或目录。")
            if expected_type == "file" and not self._is_regular_file(info):
                raise WorkspaceError("所选项目不是普通文件，请选择普通文件后重试。")
            if expected_type == "directory" and not bool(getattr(info, "is_dir", False)):
                raise WorkspaceError("所选项目不是目录，请选择目录后重试。")
            if expected_type == "any" and not (
                bool(getattr(info, "is_dir", False)) or self._is_regular_file(info)
            ):
                raise WorkspaceError("所选项目不是普通文件或目录，请更换路径后重试。")
            value = await sandbox.process.exec(
                command,
                cwd=WORKSPACE_ROOT,
                timeout=MAX_EXECUTION_TIMEOUT,
            )

        exit_code = getattr(value, "exit_code", None)
        raw_output = getattr(value, "result", "")
        if isinstance(raw_output, bytes):
            output = raw_output.decode("utf-8", errors="replace")
        else:
            output = str(raw_output or "")
        encoded = output.encode("utf-8", errors="replace")
        truncated = len(encoded) > output_limit or exit_code == 141
        if truncated:
            output = encoded[:output_limit].decode("utf-8", errors="ignore")
        if exit_code not in accepted_exit_codes:
            if exit_code == 127:
                raise WorkspaceError("当前工作区缺少基础命令，请重新构建并激活工具 Snapshot。")
            raise WorkspaceError(
                failure_classifier(output) if failure_classifier is not None else failure_message
            )
        return output, truncated

    @staticmethod
    def _parse_null_fields(output: str, count: int, error_message: str) -> list[str]:
        fields = output.split("\x00")
        if len(fields) != count + 1 or fields[-1] != "":
            raise WorkspaceError(error_message)
        return fields[:-1]

    async def aread_lines(
        self,
        thread: str,
        path: str,
        start_line: int,
        line_count: int,
    ) -> dict[str, Any]:
        if isinstance(start_line, bool) or not isinstance(start_line, int) or start_line < 1:
            raise WorkspaceError("起始行必须是大于等于 1 的整数。")
        if (
            isinstance(line_count, bool)
            or not isinstance(line_count, int)
            or not 1 <= line_count <= MAX_READ_LINES
        ):
            raise WorkspaceError(f"读取行数必须是 1 至 {MAX_READ_LINES} 之间的整数。")
        relative, remote = self.normalize_path(path, allow_root=False)
        quoted = shlex.quote(remote)
        metadata_script = (
            f"encoding=$(file --brief --mime-encoding -- {quoted}) || exit $?; "
            f"size=$(stat --format=%s -- {quoted}) || exit $?; "
            f"lines=$(wc -l < {quoted}) || exit $?; "
            f'if [ "$size" -gt 0 ] && [ -n "$(tail -c 1 -- {quoted})" ]; '
            "then lines=$((lines + 1)); fi; "
            'printf \'%s\\0%s\\0%s\\0\' "$encoding" "$size" "$lines"'
        )
        metadata, _truncated = await self._arun_workspace_command(
            thread,
            relative,
            remote,
            self._shell_command(metadata_script),
            expected_type="file",
            failure_message="工作区文本统计失败，请检查文件后重试。",
        )
        encoding, raw_size, raw_total_lines = self._parse_null_fields(
            metadata, 3, "工作区文本统计结果无效，请稍后重试。"
        )
        try:
            size = int(raw_size)
            total_lines = int(raw_total_lines)
        except ValueError as error:
            raise WorkspaceError("工作区文本统计结果无效，请稍后重试。") from error
        if size and encoding.lower() not in {"us-ascii", "utf-8"}:
            raise WorkspaceError("该文件不是 UTF-8 文本，请下载后使用对应软件打开。")

        end_line_requested = start_line + line_count - 1
        content_script = (
            f"sed -n {shlex.quote(f'{start_line},{end_line_requested}p')} -- {quoted} "
            f"| head -c {MAX_TOOL_OUTPUT_BYTES + 1}"
        )
        raw_content, command_truncated = await self._arun_workspace_command(
            thread,
            relative,
            remote,
            self._shell_command(content_script),
            expected_type="file",
            failure_message="工作区文本读取失败，请检查行号后重试。",
            output_limit=MAX_TOOL_OUTPUT_BYTES + 1,
        )
        encoded_content = raw_content.encode("utf-8")
        output_truncated = command_truncated or len(encoded_content) > MAX_TOOL_OUTPUT_BYTES
        if len(encoded_content) > MAX_TOOL_OUTPUT_BYTES:
            content = encoded_content[:MAX_TOOL_OUTPUT_BYTES].decode("utf-8", errors="ignore")
        else:
            content = raw_content
        selected_lines = len(content.splitlines(keepends=True))
        end_line = start_line + selected_lines - 1 if selected_lines else start_line - 1
        return {
            "path": relative,
            "startLine": start_line,
            "endLine": end_line,
            "totalLines": total_lines,
            "content": content,
            "truncated": output_truncated or end_line < total_lines,
        }

    async def ahash_file(self, thread: str, path: str) -> dict[str, Any]:
        relative, remote = self.normalize_path(path, allow_root=False)
        quoted = shlex.quote(remote)
        script = (
            f"digest=$(sha256sum -- {quoted}) || exit $?; digest=${{digest%% *}}; "
            f"size=$(stat --format=%s -- {quoted}) || exit $?; "
            'printf \'%s\\0%s\\0\' "$digest" "$size"'
        )
        output, _truncated = await self._arun_workspace_command(
            thread,
            relative,
            remote,
            self._shell_command(script),
            expected_type="file",
            failure_message="工作区文件哈希计算失败，请检查文件后重试。",
        )
        digest, raw_size = self._parse_null_fields(
            output, 2, "工作区文件哈希结果无效，请稍后重试。"
        )
        if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
            raise WorkspaceError("工作区文件哈希结果无效，请稍后重试。")
        try:
            size = int(raw_size)
        except ValueError as error:
            raise WorkspaceError("工作区文件哈希结果无效，请稍后重试。") from error
        return {"path": relative, "size": size, "sha256": digest}

    async def aworkspace_fingerprint(self, thread: str) -> str:
        script = "LC_ALL=C find . -xdev -printf '%P\\0%y\\0%s\\0%T@\\0' | sort -z | sha256sum"
        output, truncated = await self._arun_workspace_command(
            thread,
            "",
            WORKSPACE_ROOT,
            self._shell_command(script, pipefail=True),
            expected_type="directory",
            failure_message="工作区变更指纹计算失败，请稍后重试。",
            output_limit=128,
        )
        digest = output.split(maxsplit=1)[0] if not truncated else ""
        if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
            raise WorkspaceError("工作区变更指纹结果无效，请稍后重试。")
        return digest

    async def abatch_hash_files(self, thread: str, paths: list[str]) -> list[dict[str, Any]]:
        if not isinstance(paths, list) or len(paths) > MAX_PATCH_FILES * 3:
            raise WorkspaceError(f"批量哈希路径不能超过 {MAX_PATCH_FILES * 3} 个。")
        normalized = [self.normalize_path(path, allow_root=False) for path in paths]
        try:
            async with asyncio.timeout(MAX_BATCH_HASH_TIMEOUT):
                async with self._isolated_async_client() as client:
                    sandbox = await self._asandbox_for(client, thread)

                    semaphore = asyncio.Semaphore(MAX_BATCH_HASH_CONCURRENCY)

                    async def hash_file(relative: str, remote: str) -> dict[str, Any]:
                        async with semaphore:
                            try:
                                await self._avalidate_existing_path(sandbox, relative)
                                info = await self._ainfo(sandbox, remote)
                                if not self._is_regular_file(info):
                                    raise DaytonaNotFoundError("not a regular file")
                                content = await self._adownload_file(
                                    sandbox,
                                    remote,
                                    MAX_DOWNLOAD_BYTES,
                                    timeout=MAX_BATCH_HASH_FILE_TIMEOUT,
                                )
                            except (DaytonaNotFoundError, WorkspaceError):
                                return {"path": relative, "missing": True}
                            return {
                                "path": relative,
                                "size": len(content),
                                "sha256": hashlib.sha256(content).hexdigest(),
                            }

                    results = await asyncio.gather(
                        *(hash_file(relative, remote) for relative, remote in normalized)
                    )
        except TimeoutError as error:
            raise WorkspaceError("批量哈希读取超时，请稍后重试。") from error
        return results

    async def astat(self, thread: str, path: str = "") -> dict[str, Any]:
        relative, remote = self.normalize_path(path)
        script = f"stat --printf='%F\\0%s\\0%Y\\0%a\\0' -- {shlex.quote(remote)}"
        output, _truncated = await self._arun_workspace_command(
            thread,
            relative,
            remote,
            self._shell_command(script),
            expected_type="any",
            failure_message="工作区路径统计失败，请检查路径后重试。",
        )
        raw_type, raw_size, raw_modified, mode = self._parse_null_fields(
            output, 4, "工作区路径统计结果无效，请稍后重试。"
        )
        if "directory" in raw_type:
            item_type = "directory"
        elif "regular" in raw_type:
            item_type = "file"
        else:
            raise WorkspaceError("工作区路径不是普通文件或目录，请更换路径后重试。")
        try:
            size = int(raw_size)
            modified = int(raw_modified)
        except ValueError as error:
            raise WorkspaceError("工作区路径统计结果无效，请稍后重试。") from error
        return {
            "path": relative,
            "type": item_type,
            "size": size,
            "modifiedUnix": modified,
            "mode": mode,
        }

    async def atree(
        self,
        thread: str,
        path: str = "",
        max_depth: int = 4,
        limit: int = 200,
    ) -> dict[str, Any]:
        if (
            isinstance(max_depth, bool)
            or not isinstance(max_depth, int)
            or not 1 <= max_depth <= 32
        ):
            raise WorkspaceError("目录树深度必须是 1 至 32 之间的整数。")
        if (
            isinstance(limit, bool)
            or not isinstance(limit, int)
            or not 1 <= limit <= MAX_LIST_ENTRIES
        ):
            raise WorkspaceError(f"目录树条目数必须是 1 至 {MAX_LIST_ENTRIES} 之间的整数。")
        relative, remote = self.normalize_path(path)
        arguments = [
            "find",
            remote,
            "-xdev",
            "-mindepth",
            "1",
            "-maxdepth",
            str(max_depth),
            "(",
            "-type",
            "f",
            "-o",
            "-type",
            "d",
            ")",
            "!",
            "-path",
            f"{WORKSPACE_ROOT}/报表/原始数据/*/分片/*.jsonl",
            "!",
            "-path",
            f"{WORKSPACE_ROOT}/reports/data/*.jsonl",
            "-printf",
            "%y\\t%P\\t%s\\0",
        ]
        pipeline = f"{shlex.join(arguments)} | sort -z | head -z -n {limit + 1}"
        output, command_truncated = await self._arun_workspace_command(
            thread,
            relative,
            remote,
            self._shell_command(pipeline, pipefail=True),
            expected_type="directory",
            failure_message="工作区目录树读取失败，请缩小范围后重试。",
            accepted_exit_codes=(0, 141),
        )
        records = output.split("\x00")
        malformed = bool(records and records[-1])
        records = records[:-1] if records and records[-1] == "" else records
        entries = []
        for record in records[: limit + 1]:
            fields = record.split("\t")
            if len(fields) != 3:
                malformed = True
                continue
            raw_type, raw_path, raw_size = fields
            try:
                found = self.normalize_path(f"{relative}/{raw_path}".strip("/"), allow_root=False)[
                    0
                ]
                size = int(raw_size)
            except (ValueError, WorkspaceError):
                malformed = True
                continue
            if _is_controlled_raw_dataset(found) or raw_type not in {"d", "f"}:
                continue
            entries.append(
                {
                    "path": found,
                    "type": "directory" if raw_type == "d" else "file",
                    "size": size,
                }
            )
        truncated = command_truncated or malformed or len(entries) > limit
        return {"root": relative, "entries": entries[:limit], "truncated": truncated}

    @staticmethod
    def _validate_git_revision(revision: str) -> str:
        allowed = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._/@{}^~:-"
        if (
            not isinstance(revision, str)
            or not 1 <= len(revision) <= 128
            or revision.startswith("-")
            or not revision.isascii()
            or any(character not in allowed for character in revision)
        ):
            raise WorkspaceError("Git 修订格式无效，请使用分支、标签或提交哈希。")
        return revision

    @classmethod
    def _validate_git_file_path(cls, file_path: str | None) -> str | None:
        if file_path is None:
            return None
        if not isinstance(file_path, str) or not file_path:
            raise WorkspaceError("Git 文件路径必须是非空的仓库相对路径。")
        return cls.normalize_path(file_path, allow_root=False)[0]

    async def _agit(
        self,
        thread: str,
        repo_path: str,
        arguments: list[str],
    ) -> dict[str, Any]:
        relative, remote = self.normalize_path(repo_path)
        command = shlex.join(
            [
                "git",
                "-C",
                remote,
                "--no-pager",
                "-c",
                "color.ui=false",
                "-c",
                "core.fsmonitor=false",
                "-c",
                "core.hooksPath=/dev/null",
                "-c",
                "core.pager=cat",
                *arguments,
            ]
        )
        pipeline = f"{command} 2>&1 | head -c {MAX_TOOL_OUTPUT_BYTES + 1}"
        output, command_truncated = await self._arun_workspace_command(
            thread,
            relative,
            remote,
            self._shell_command(pipeline, pipefail=True),
            expected_type="directory",
            failure_message="Git 只读命令执行失败，请检查仓库路径和修订后重试。",
            output_limit=MAX_TOOL_OUTPUT_BYTES + 1,
            accepted_exit_codes=(0, 141),
            failure_classifier=self._classify_git_failure,
        )
        encoded = output.encode("utf-8")
        truncated = command_truncated or len(encoded) > MAX_TOOL_OUTPUT_BYTES
        if len(encoded) > MAX_TOOL_OUTPUT_BYTES:
            output = encoded[:MAX_TOOL_OUTPUT_BYTES].decode("utf-8", errors="ignore")
        return {"exitCode": 0, "output": output, "truncated": truncated}

    @staticmethod
    def _classify_git_failure(output: str) -> str:
        normalized = output.lower()
        if "not a git repository" in normalized:
            return "所选目录不是 Git 仓库。"
        if any(
            marker in normalized
            for marker in ("bad revision", "unknown revision", "ambiguous argument")
        ):
            return "Git 修订不存在或无法解析。"
        if "pathspec" in normalized and (
            "did not match" in normalized or "does not match" in normalized
        ):
            return "Git 文件路径不存在或不匹配。"
        return "Git 只读命令执行失败。"

    async def agit_status(self, thread: str, repo_path: str = "") -> dict[str, Any]:
        return await self._agit(
            thread,
            repo_path,
            ["status", "--short", "--branch", "--untracked-files=all"],
        )

    async def agit_diff(
        self,
        thread: str,
        repo_path: str = "",
        staged: bool = False,
        revision: str | None = None,
        file_path: str | None = None,
    ) -> dict[str, Any]:
        if not isinstance(staged, bool):
            raise WorkspaceError("Git 暂存区标志必须是布尔值。")
        arguments = ["diff", "--no-ext-diff", "--no-textconv", "--unified=3"]
        if staged:
            arguments.append("--cached")
        if revision is not None:
            arguments.append(self._validate_git_revision(revision))
        path = self._validate_git_file_path(file_path)
        if path is not None:
            arguments.extend(("--", path))
        return await self._agit(thread, repo_path, arguments)

    async def agit_log(
        self,
        thread: str,
        repo_path: str = "",
        revision: str = "HEAD",
        max_count: int = 20,
        file_path: str | None = None,
    ) -> dict[str, Any]:
        if (
            isinstance(max_count, bool)
            or not isinstance(max_count, int)
            or not 1 <= max_count <= MAX_GIT_LOG_ENTRIES
        ):
            raise WorkspaceError(f"Git 日志条数必须是 1 至 {MAX_GIT_LOG_ENTRIES} 之间的整数。")
        arguments = [
            "log",
            f"--max-count={max_count}",
            "--date=iso-strict",
            "--pretty=format:%H%x09%ad%x09%an%x09%s",
            self._validate_git_revision(revision),
        ]
        path = self._validate_git_file_path(file_path)
        if path is not None:
            arguments.extend(("--", path))
        return await self._agit(thread, repo_path, arguments)

    async def agit_show(
        self,
        thread: str,
        repo_path: str = "",
        revision: str = "HEAD",
        file_path: str | None = None,
    ) -> dict[str, Any]:
        arguments = [
            "show",
            "--no-ext-diff",
            "--no-textconv",
            "--format=fuller",
            "--stat",
            "--patch",
            self._validate_git_revision(revision),
        ]
        path = self._validate_git_file_path(file_path)
        if path is not None:
            arguments.extend(("--", path))
        return await self._agit(thread, repo_path, arguments)

    def hash_file(self, thread: str, path: str) -> dict[str, Any]:
        relative = self.normalize_path(path, allow_root=False)[0]
        content, _mime_type = self.file_bytes(thread, relative)
        return {
            "path": relative,
            "size": len(content),
            "sha256": hashlib.sha256(content).hexdigest(),
        }

    def apply_patch(
        self,
        thread: str,
        path: str,
        old_text: str,
        new_text: str,
        expected_sha256: str,
        replace_all: bool = False,
    ) -> dict[str, Any]:
        if not isinstance(old_text, str) or not old_text:
            raise WorkspaceError("补丁原文不能为空。")
        if not isinstance(new_text, str):
            raise WorkspaceError("补丁替换内容必须是文本。")
        if (
            not isinstance(expected_sha256, str)
            or len(expected_sha256) != 64
            or any(character not in "0123456789abcdefABCDEF" for character in expected_sha256)
        ):
            raise WorkspaceError("补丁文件哈希格式无效，请先重新读取文件哈希。")
        relative = self.normalize_path(path, allow_root=False)[0]
        lock_key = f"agent-workspace-patch:{self._hash(thread)}"
        with self.registry.locked(lock_key):
            current = self.read_text(thread, relative)
            current_bytes = current.encode("utf-8")
            current_sha256 = hashlib.sha256(current_bytes).hexdigest()
            if current_sha256 != expected_sha256.lower():
                raise WorkspacePathConflict("文件内容已变化，请重新读取文件和哈希后再应用补丁。")
            count = current.count(old_text)
            if count == 0:
                raise WorkspaceError("补丁原文未在文件中找到，请重新读取文件后重试。")
            if count > 1 and not replace_all:
                raise WorkspaceError(
                    f"补丁原文在文件中出现 {count} 次，请提供更完整的上下文或启用全部替换。"
                )
            replacements = count if replace_all else 1
            updated = (
                current.replace(old_text, new_text)
                if replace_all
                else current.replace(old_text, new_text, 1)
            )
            updated_bytes = updated.encode("utf-8")
            result = self.replace_file(thread, relative, updated_bytes)
            persisted = self.read_text(thread, relative).encode("utf-8")
            if persisted != updated_bytes:
                raise WorkspaceError("补丁落盘校验失败，请重新读取文件后再试。")
            diff = "".join(
                difflib.unified_diff(
                    current.splitlines(keepends=True),
                    updated.splitlines(keepends=True),
                    fromfile=relative,
                    tofile=relative,
                )
            )
            diff, diff_truncated = self._bounded_text(diff)
        return {
            **result,
            "replacements": replacements,
            "sha256": hashlib.sha256(updated_bytes).hexdigest(),
            "diff": diff,
            "diffTruncated": diff_truncated,
        }

    @staticmethod
    def _validate_patch_hash(value: Any) -> str:
        if (
            not isinstance(value, str)
            or len(value) != 64
            or any(character not in "0123456789abcdefABCDEF" for character in value)
        ):
            raise WorkspaceError("补丁文件哈希格式无效，请先重新读取文件哈希。")
        return value.lower()

    def apply_patch_set(
        self,
        thread: str,
        patches: list[dict[str, Any]],
    ) -> dict[str, Any]:
        if not isinstance(patches, list) or not 1 <= len(patches) <= MAX_PATCH_FILES:
            raise WorkspaceError(f"批量补丁必须包含 1 至 {MAX_PATCH_FILES} 个文件。")

        normalized = []
        seen_paths = set()
        edit_count = 0
        for patch in patches:
            if not isinstance(patch, dict) or set(patch) != {
                "path",
                "expected_sha256",
                "edits",
            }:
                raise WorkspaceError("批量补丁文件项必须只包含 path、expected_sha256 和 edits。")
            if not isinstance(patch["path"], str):
                raise WorkspaceError("批量补丁路径必须是工作区相对路径字符串。")
            relative = self.normalize_path(patch["path"], allow_root=False)[0]
            if relative in seen_paths:
                raise WorkspaceError("批量补丁不能重复修改同一个文件。")
            seen_paths.add(relative)
            expected_sha256 = self._validate_patch_hash(patch["expected_sha256"])
            edits = patch["edits"]
            if not isinstance(edits, list) or not edits:
                raise WorkspaceError("每个批量补丁文件至少需要一个编辑项。")
            validated_edits = []
            for edit in edits:
                if (
                    not isinstance(edit, dict)
                    or not set(edit).issubset({"old_text", "new_text", "replace_all"})
                    or not {"old_text", "new_text"}.issubset(edit)
                ):
                    raise WorkspaceError(
                        "批量补丁编辑项必须包含 old_text、new_text，可选 replace_all。"
                    )
                old_text = edit["old_text"]
                new_text = edit["new_text"]
                replace_all = edit.get("replace_all", False)
                if not isinstance(old_text, str) or not old_text:
                    raise WorkspaceError("批量补丁原文不能为空。")
                if not isinstance(new_text, str) or not isinstance(replace_all, bool):
                    raise WorkspaceError("批量补丁替换内容必须是文本，全部替换标志必须是布尔值。")
                validated_edits.append((old_text, new_text, replace_all))
                edit_count += 1
                if edit_count > MAX_PATCH_EDITS:
                    raise WorkspaceError(f"批量补丁编辑项不能超过 {MAX_PATCH_EDITS} 个。")
            normalized.append((relative, expected_sha256, validated_edits))

        lock_key = f"agent-workspace-patch:{self._hash(thread)}"
        with self.registry.locked(lock_key):
            prepared: list[dict[str, Any]] = []
            for relative, expected_sha256, edits in normalized:
                current = self.read_text(thread, relative)
                current_bytes = current.encode("utf-8")
                if hashlib.sha256(current_bytes).hexdigest() != expected_sha256:
                    raise WorkspacePathConflict(
                        "文件内容已变化，请重新读取全部目标文件和哈希后再应用批量补丁。"
                    )
                updated = current
                replacements = 0
                for old_text, new_text, replace_all in edits:
                    count = updated.count(old_text)
                    if count == 0:
                        raise WorkspaceError(
                            f"文件“{relative}”中未找到补丁原文，请重新读取文件后重试。"
                        )
                    if count > 1 and not replace_all:
                        raise WorkspaceError(
                            f"文件“{relative}”中的补丁原文出现 {count} 次，"
                            "请提供更完整的上下文或启用全部替换。"
                        )
                    replacements += count if replace_all else 1
                    updated = (
                        updated.replace(old_text, new_text)
                        if replace_all
                        else updated.replace(old_text, new_text, 1)
                    )
                updated_bytes = updated.encode("utf-8")
                self._validate_content(updated_bytes)
                prepared.append(
                    {
                        "path": relative,
                        "original": current_bytes,
                        "updated": updated_bytes,
                        "replacements": replacements,
                        "diff": "".join(
                            difflib.unified_diff(
                                current.splitlines(keepends=True),
                                updated.splitlines(keepends=True),
                                fromfile=relative,
                                tofile=relative,
                            )
                        ),
                    }
                )

            written: list[dict[str, Any]] = []
            try:
                for item in prepared:
                    result = self.replace_file(thread, item["path"], item["updated"])
                    written.append(item)
                    persisted = self.read_text(thread, item["path"]).encode("utf-8")
                    if persisted != item["updated"]:
                        raise WorkspaceError("批量补丁落盘校验失败，请重新读取文件后再试。")
                    item["result"] = result
            except Exception as error:
                rollback_failed = False
                for item in reversed(written):
                    try:
                        self.replace_file(thread, item["path"], item["original"])
                    except Exception:
                        rollback_failed = True
                if rollback_failed:
                    raise WorkspaceError(
                        "批量补丁写入失败且未能完整回滚，请重新检查所有目标文件。"
                    ) from error
                raise

        diff, diff_truncated = self._bounded_text("".join(item["diff"] for item in prepared))
        return {
            "files": [
                {
                    **item["result"],
                    "replacements": item["replacements"],
                    "sha256": hashlib.sha256(item["updated"]).hexdigest(),
                }
                for item in prepared
            ],
            "replacements": sum(item["replacements"] for item in prepared),
            "diff": diff,
            "diffTruncated": diff_truncated,
        }

    def apply_hunks(self, thread: str, patches: list[dict[str, Any]]) -> dict[str, Any]:
        if not isinstance(patches, list) or not 1 <= len(patches) <= MAX_PATCH_FILES:
            raise WorkspaceError(f"定位补丁必须包含 1 至 {MAX_PATCH_FILES} 个文件。")

        normalized = []
        seen_paths = set()
        hunk_count = 0
        for patch in patches:
            if not isinstance(patch, dict) or set(patch) != {
                "path",
                "expected_sha256",
                "hunks",
            }:
                raise WorkspaceError("定位补丁文件项必须只包含 path、expected_sha256 和 hunks。")
            if not isinstance(patch["path"], str):
                raise WorkspaceError("定位补丁路径必须是工作区相对路径字符串。")
            relative = self.normalize_path(patch["path"], allow_root=False)[0]
            if relative in seen_paths:
                raise WorkspaceError("定位补丁不能重复修改同一个文件。")
            seen_paths.add(relative)
            expected_sha256 = self._validate_patch_hash(patch["expected_sha256"])
            raw_hunks = patch["hunks"]
            if not isinstance(raw_hunks, list) or not raw_hunks:
                raise WorkspaceError("每个定位补丁文件至少需要一个 hunk。")
            validated_hunks = []
            for hunk in raw_hunks:
                if not isinstance(hunk, dict) or set(hunk) != {
                    "old_start",
                    "old_text",
                    "new_text",
                }:
                    raise WorkspaceError(
                        "定位补丁 hunk 必须只包含 old_start、old_text 和 new_text。"
                    )
                old_start = hunk["old_start"]
                old_text = hunk["old_text"]
                new_text = hunk["new_text"]
                if isinstance(old_start, bool) or not isinstance(old_start, int) or old_start < 1:
                    raise WorkspaceError("定位补丁起始行必须是大于等于 1 的整数。")
                if not isinstance(old_text, str) or not old_text:
                    raise WorkspaceError("定位补丁原文不能为空。")
                if not isinstance(new_text, str):
                    raise WorkspaceError("定位补丁替换内容必须是文本。")
                validated_hunks.append((old_start, old_text, new_text))
                hunk_count += 1
                if hunk_count > MAX_PATCH_EDITS:
                    raise WorkspaceError(f"定位补丁 hunk 不能超过 {MAX_PATCH_EDITS} 个。")
            normalized.append((relative, expected_sha256, validated_hunks))

        lock_key = f"agent-workspace-patch:{self._hash(thread)}"
        with self.registry.locked(lock_key):
            prepared: list[dict[str, Any]] = []
            for relative, expected_sha256, hunks in normalized:
                current = self.read_text(thread, relative)
                current_bytes = current.encode("utf-8")
                if hashlib.sha256(current_bytes).hexdigest() != expected_sha256:
                    raise WorkspacePathConflict(
                        "文件内容已变化，请重新读取全部目标文件和哈希后再应用定位补丁。"
                    )
                lines = current.splitlines(keepends=True)
                positioned = []
                for old_start, old_text, new_text in hunks:
                    if old_start > len(lines):
                        raise WorkspaceError(
                            f"文件“{relative}”第 {old_start} 行不存在，请重新读取文件后重试。"
                        )
                    start = sum(len(line) for line in lines[: old_start - 1])
                    end = start + len(old_text)
                    if current[start:end] != old_text:
                        raise WorkspaceError(
                            f"文件“{relative}”第 {old_start} 行与定位补丁原文不匹配，"
                            "请重新读取文件后重试。"
                        )
                    positioned.append((start, end, new_text))
                positioned.sort(key=lambda item: item[0])
                if any(
                    current_item[0] < previous[1]
                    for previous, current_item in zip(positioned, positioned[1:])
                ):
                    raise WorkspaceError(f"文件“{relative}”中的定位补丁 hunk 不能重叠。")
                updated = current
                for start, end, new_text in reversed(positioned):
                    updated = updated[:start] + new_text + updated[end:]
                updated_bytes = updated.encode("utf-8")
                self._validate_content(updated_bytes)
                prepared.append(
                    {
                        "path": relative,
                        "original": current_bytes,
                        "updated": updated_bytes,
                        "hunks": len(positioned),
                        "diff": "".join(
                            difflib.unified_diff(
                                current.splitlines(keepends=True),
                                updated.splitlines(keepends=True),
                                fromfile=relative,
                                tofile=relative,
                            )
                        ),
                    }
                )

            written: list[dict[str, Any]] = []
            try:
                for item in prepared:
                    item["result"] = self.replace_file(thread, item["path"], item["updated"])
                    written.append(item)
                    if self.read_text(thread, item["path"]).encode("utf-8") != item["updated"]:
                        raise WorkspaceError("定位补丁落盘校验失败，请重新读取全部目标文件后再试。")
            except Exception as error:
                rollback_failed = False
                for item in reversed(written):
                    try:
                        self.replace_file(thread, item["path"], item["original"])
                    except Exception:
                        rollback_failed = True
                if rollback_failed:
                    raise WorkspaceError(
                        "定位补丁写入失败且未能完整回滚，请重新检查所有目标文件。"
                    ) from error
                raise

        diff, diff_truncated = self._bounded_text("".join(item["diff"] for item in prepared))
        return {
            "files": [
                {
                    **item["result"],
                    "hunks": item["hunks"],
                    "sha256": hashlib.sha256(item["updated"]).hexdigest(),
                }
                for item in prepared
            ],
            "hunks": sum(item["hunks"] for item in prepared),
            "diff": diff,
            "diffTruncated": diff_truncated,
        }

    def _inspect_destination_without_writes(self, sandbox: Any, relative: str):
        parts = relative.split("/")
        for index in range(1, len(parts) + 1):
            remote = f"{WORKSPACE_ROOT}/{'/'.join(parts[:index])}"
            try:
                with suppress_expected_probe_tracing():
                    info = self._info(sandbox, remote)
            except DaytonaNotFoundError:
                return None
            if self._is_symlink(info):
                raise WorkspaceError("工作区路径包含符号链接，请改用普通文件或目录。")
            if index < len(parts) and not bool(getattr(info, "is_dir", False)):
                raise WorkspaceError("工作区父路径不是安全目录，请更换路径后重试。")
        return info

    def apply_changes(self, thread: str, changes: list[dict[str, Any]]) -> dict[str, Any]:
        if not isinstance(changes, list) or not 1 <= len(changes) <= MAX_PATCH_FILES:
            raise WorkspaceError(f"变更集必须包含 1 至 {MAX_PATCH_FILES} 个文件操作。")

        sandbox = self.sandbox_for(thread)
        prepared: list[dict[str, Any]] = []
        used_paths: set[str] = set()
        keys_by_operation = {
            "create": {"operation", "path", "content"},
            "update": {"operation", "path", "content", "expected_sha256"},
            "delete": {"operation", "path", "expected_sha256"},
            "move": {"operation", "path", "destination", "expected_sha256"},
        }
        lock_key = f"agent-workspace-changes:{self._hash(thread)}"
        with self.registry.locked(lock_key):
            for change in changes:
                if not isinstance(change, dict):
                    raise WorkspaceError("变更集中的每一项都必须是文件操作对象。")
                raw_operation = change.get("operation")
                if not isinstance(raw_operation, str):
                    raise WorkspaceError("变更集操作必须是 create、update、delete 或 move。")
                operation = raw_operation
                required_keys = keys_by_operation.get(operation)
                if required_keys is None or set(change) != required_keys:
                    raise WorkspaceError(
                        "变更集操作字段无效；请按 create、update、delete 或 move 的字段要求重试。"
                    )
                if not isinstance(change.get("path"), str):
                    raise WorkspaceError("变更集路径必须是工作区相对路径字符串。")
                relative, remote = self.normalize_path(change["path"], allow_root=False)
                destinations = [relative]
                destination = None
                destination_remote = None
                if operation == "move":
                    if not isinstance(change.get("destination"), str):
                        raise WorkspaceError("移动目标必须是工作区相对路径字符串。")
                    destination, destination_remote = self.normalize_path(
                        change["destination"], allow_root=False
                    )
                    if destination == relative:
                        raise WorkspaceError("移动源路径和目标路径不能相同。")
                    destinations.append(destination)
                if any(path in used_paths for path in destinations):
                    raise WorkspaceError("变更集不能重复使用同一个源路径或目标路径。")
                used_paths.update(destinations)

                if operation == "create":
                    content = change["content"]
                    if not isinstance(content, str):
                        raise WorkspaceError("新建文件内容必须是 UTF-8 文本。")
                    updated = content.encode("utf-8")
                    self._validate_content(updated)
                    if self._inspect_destination_without_writes(sandbox, relative) is not None:
                        raise WorkspacePathConflict(
                            f"文件“{relative}”已经存在，请重新读取变更目标后重试。"
                        )
                    prepared.append(
                        {
                            "operation": operation,
                            "path": relative,
                            "remote": remote,
                            "updated": updated,
                        }
                    )
                    continue

                self._validate_existing_path(sandbox, relative)
                info = self._info(sandbox, remote)
                if not self._is_regular_file(info):
                    raise WorkspaceError("变更集只能更新、删除或移动普通文件。")
                original, _mime_type = self._file_bytes_from_sandbox(sandbox, relative, remote)
                if operation == "delete" and len(original) > MAX_UPLOAD_BYTES:
                    raise WorkspaceError(
                        "变更集不能删除超过 200 MiB 的文件；请使用独立删除工具并确认。"
                    )
                expected_sha256 = self._validate_patch_hash(change["expected_sha256"])
                if hashlib.sha256(original).hexdigest() != expected_sha256:
                    raise WorkspacePathConflict(
                        "文件内容已变化，请重新读取全部目标文件和哈希后再应用变更集。"
                    )
                item: dict[str, Any] = {
                    "operation": operation,
                    "path": relative,
                    "remote": remote,
                    "original": original,
                    "sha256": expected_sha256,
                }
                if operation == "update":
                    content = change["content"]
                    if not isinstance(content, str):
                        raise WorkspaceError("更新文件内容必须是 UTF-8 文本。")
                    item["updated"] = content.encode("utf-8")
                    self._validate_content(item["updated"])
                elif operation == "move":
                    if destination is None or destination_remote is None:
                        raise WorkspaceError("移动目标必须是工作区相对路径字符串。")
                    if self._inspect_destination_without_writes(sandbox, destination) is not None:
                        raise WorkspacePathConflict(
                            f"移动目标“{destination}”已经存在，请更换路径后重试。"
                        )
                    item["destination"] = destination
                    item["destination_remote"] = destination_remote
                prepared.append(item)

            completed: list[dict[str, Any]] = []
            try:
                for item in prepared:
                    operation = item["operation"]
                    if operation == "create":
                        self._store_file_in_sandbox(
                            sandbox,
                            item["path"],
                            item["remote"],
                            item["updated"],
                            "create",
                        )
                    elif operation == "update":
                        self._store_file_in_sandbox(
                            sandbox,
                            item["path"],
                            item["remote"],
                            item["updated"],
                            "replace",
                        )
                    elif operation == "delete":
                        self._delete_file_from_sandbox(sandbox, item["path"], item["remote"])
                    else:
                        self._move_file_in_sandbox(
                            sandbox,
                            item["path"],
                            item["remote"],
                            item["destination"],
                            item["destination_remote"],
                        )
                    completed.append(item)

                    if operation in {"create", "update"}:
                        persisted, _mime_type = self._file_bytes_from_sandbox(
                            sandbox, item["path"], item["remote"]
                        )
                        if persisted != item["updated"]:
                            raise WorkspaceError("变更集落盘校验失败，请重新检查目标文件。")
                    elif operation == "move":
                        persisted, _mime_type = self._file_bytes_from_sandbox(
                            sandbox, item["destination"], item["destination_remote"]
                        )
                        if persisted != item["original"]:
                            raise WorkspaceError("变更集移动校验失败，请重新检查目标文件。")
            except Exception as error:
                rollback_failed = False
                for item in reversed(completed):
                    try:
                        operation = item["operation"]
                        if operation == "create":
                            self._delete_file_from_sandbox(sandbox, item["path"], item["remote"])
                        elif operation == "update":
                            self._store_file_in_sandbox(
                                sandbox,
                                item["path"],
                                item["remote"],
                                item["original"],
                                "replace",
                            )
                        elif operation == "delete":
                            self._store_file_in_sandbox(
                                sandbox,
                                item["path"],
                                item["remote"],
                                item["original"],
                                "create",
                            )
                        else:
                            self._move_file_in_sandbox(
                                sandbox,
                                item["destination"],
                                item["destination_remote"],
                                item["path"],
                                item["remote"],
                            )
                    except Exception:
                        rollback_failed = True
                if rollback_failed:
                    raise WorkspaceError(
                        "变更集执行失败且未能完整回滚，请重新检查所有目标文件。"
                    ) from error
                raise

        results = []
        for item in prepared:
            result = {"operation": item["operation"], "path": item["path"]}
            if item["operation"] in {"create", "update"}:
                result.update(
                    {
                        "size": len(item["updated"]),
                        "sha256": hashlib.sha256(item["updated"]).hexdigest(),
                    }
                )
            elif item["operation"] == "move":
                result["destination"] = item["destination"]
                result["sha256"] = item["sha256"]
            else:
                result["sha256"] = item["sha256"]
            results.append(result)
        return {"files": results, "operations": len(results)}

    def view_image(self, thread: str, path: str) -> ToolResult:
        relative = self.normalize_path(path, allow_root=False)[0]
        suffix = PurePosixPath(relative).suffix.lower()
        if suffix not in IMAGE_SUFFIXES:
            raise WorkspaceError("仅支持 PNG、JPEG、GIF 或 WebP 图片。")
        content, mime_type = self.file_bytes(thread, relative)
        if len(content) > MAX_IMAGE_BYTES:
            raise WorkspaceError("图片超过 10 MiB，请缩小后重试。")
        header = content[:12]
        valid_signature = {
            ".png": header.startswith(b"\x89PNG\r\n\x1a\n"),
            ".jpg": header.startswith(b"\xff\xd8\xff"),
            ".jpeg": header.startswith(b"\xff\xd8\xff"),
            ".gif": header.startswith((b"GIF87a", b"GIF89a")),
            ".webp": header.startswith(b"RIFF") and header[8:12] == b"WEBP",
        }[suffix]
        if not valid_signature:
            raise WorkspaceError("图片扩展名与文件签名不一致，请检查文件格式。")
        return ToolResult(
            content=f"已加载工作区图片：{relative}",
            images=[
                Image(
                    content=content,
                    mime_type=mime_type,
                    format="jpeg" if suffix in {".jpg", ".jpeg"} else suffix.lstrip("."),
                )
            ],
        )

    def inspect_pdf(self, thread: str, path: str) -> dict[str, Any]:
        relative = self.normalize_path(path, allow_root=False)[0]
        if PurePosixPath(relative).suffix.lower() != ".pdf":
            raise WorkspaceError("PDF 检查只支持 .pdf 文件。")
        content, _mime_type = self.file_bytes(thread, relative)
        try:
            from pypdf import PdfReader

            reader = PdfReader(BytesIO(content), strict=False)
        except Exception as error:
            raise WorkspaceError("PDF 文件无法解析，请检查文件是否完整。") from error
        if reader.is_encrypted:
            raise WorkspaceError("PDF 文件已加密，无法检查页面内容。")
        page_count = len(reader.pages)
        if page_count > MAX_INSPECT_PDF_PAGES:
            raise WorkspaceError(f"PDF 超过 {MAX_INSPECT_PDF_PAGES} 页，请拆分后检查。")
        pages = []
        for index, page in enumerate(reader.pages, 1):
            try:
                text_characters = len(page.extract_text() or "")
            except Exception:
                text_characters = 0
            pages.append(
                {
                    "page": index,
                    "width": round(float(page.mediabox.width), 2),
                    "height": round(float(page.mediabox.height), 2),
                    "textCharacters": text_characters,
                }
            )
        return {
            "path": relative,
            "size": len(content),
            "sha256": hashlib.sha256(content).hexdigest(),
            "pageCount": page_count,
            "pages": pages,
        }

    def delete_file(self, thread: str, path: str, recursive: bool = False):
        relative, remote = self.normalize_path(path, allow_root=False)
        sandbox = self.sandbox_for(thread)
        self._delete_file_from_sandbox(sandbox, relative, remote, recursive)

    def _delete_file_from_sandbox(
        self,
        sandbox: Any,
        relative: str,
        remote: str,
        recursive: bool = False,
    ) -> None:
        self._validate_existing_path(sandbox, relative)
        info = self._info(sandbox, remote)
        if info.is_dir and not recursive:
            raise WorkspaceError("所选项目是目录；如需删除，请启用递归删除并重新确认。")
        sandbox.fs.delete_file(remote, recursive=recursive)

    def create_directory(self, thread: str, path: str) -> dict[str, Any]:
        relative, remote = self.normalize_path(path, allow_root=False)
        lock_key = f"agent-workspace-directory:{self._hash(thread)}:{relative}"
        with self.registry.locked(lock_key):
            sandbox = self.sandbox_for(thread)
            if self._inspect_destination_without_writes(sandbox, relative) is not None:
                raise WorkspacePathConflict(f"目录“{relative}”已经存在，请更换路径后重试。")
            self._ensure_directory(sandbox, remote)
            info = self._info(sandbox, remote)
            if self._is_symlink(info) or not bool(getattr(info, "is_dir", False)):
                raise WorkspaceError("工作区目录创建后校验失败，请检查目标路径后重试。")
        return {"path": relative, "status": "created"}

    def copy_file(self, thread: str, source: str, destination: str) -> dict[str, Any]:
        source_relative, source_remote = self.normalize_path(source, allow_root=False)
        destination_relative, destination_remote = self.normalize_path(
            destination, allow_root=False
        )
        lock_key = f"agent-workspace-copy:{self._hash(thread)}"
        with self.registry.locked(lock_key):
            sandbox = self.sandbox_for(thread)
            self._validate_existing_path(sandbox, source_relative)
            source_info = self._info(sandbox, source_remote)
            if not self._is_regular_file(source_info):
                raise WorkspaceError("复制源路径不是普通文件，请选择普通文件后重试。")
            if int(getattr(source_info, "size", 0) or 0) > MAX_UPLOAD_BYTES:
                raise WorkspaceError("复制源文件超过 200 MiB，请使用工作区命令处理大文件。")
            if self._inspect_destination_without_writes(sandbox, destination_relative) is not None:
                raise WorkspacePathConflict(
                    f"文件“{destination_relative}”已经存在，请更换目标路径后重试。"
                )
            content = self._download_file(sandbox, source_remote, MAX_UPLOAD_BYTES)
            if not isinstance(content, bytes) or len(content) > MAX_UPLOAD_BYTES:
                raise WorkspaceError("复制源文件超过 200 MiB，请使用工作区命令处理大文件。")
            digest = hashlib.sha256(content).hexdigest()
            created = False
            try:
                self.create_file(thread, destination_relative, content)
                created = True
                persisted, _mime_type = self.file_bytes(thread, destination_relative)
                if persisted != content:
                    raise WorkspaceError("复制文件落盘校验失败，请检查目标路径后重试。")
            except Exception as error:
                cleanup_failed = False
                if created:
                    try:
                        sandbox.fs.delete_file(destination_remote, recursive=False)
                    except Exception:
                        cleanup_failed = True
                if cleanup_failed:
                    raise WorkspaceError(
                        "复制文件失败且未能清理目标，请重新检查目标路径。"
                    ) from error
                raise
        return {
            "path": destination_relative,
            "source": source_relative,
            "size": len(content),
            "sha256": digest,
            "status": "copied",
        }

    def move_file(self, thread: str, source: str, destination: str):
        source_relative, source_remote = self.normalize_path(source, allow_root=False)
        destination_relative, destination_remote = self.normalize_path(
            destination, allow_root=False
        )
        sandbox = self.sandbox_for(thread)
        self._move_file_in_sandbox(
            sandbox,
            source_relative,
            source_remote,
            destination_relative,
            destination_remote,
        )

    def _move_file_in_sandbox(
        self,
        sandbox: Any,
        source_relative: str,
        source_remote: str,
        destination_relative: str,
        destination_remote: str,
    ) -> None:
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
    def _bounded_text(value: Any) -> tuple[str, bool]:
        output = str(value or "")
        encoded = output.encode("utf-8", errors="replace")
        truncated = len(encoded) > MAX_TOOL_OUTPUT_BYTES
        if truncated:
            output = encoded[:MAX_TOOL_OUTPUT_BYTES].decode("utf-8", errors="ignore")
        return output, truncated

    @classmethod
    def _bounded_output(cls, value: Any) -> dict[str, Any]:
        output, truncated = cls._bounded_text(getattr(value, "result", ""))
        return {
            "exitCode": getattr(value, "exit_code", None),
            "output": output,
            "truncated": truncated,
        }

    @staticmethod
    def _validate_timeout(timeout: int, maximum: int = MAX_EXECUTION_TIMEOUT) -> int:
        if isinstance(timeout, bool) or not isinstance(timeout, int):
            raise WorkspaceError("执行超时必须是整数秒，请修改后重试。")
        if not 1 <= timeout <= maximum:
            label = "后台命令" if maximum == MAX_BACKGROUND_EXECUTION_TIMEOUT else "前台命令"
            raise WorkspaceError(f"{label}执行超时必须在 1 至 {maximum} 秒之间，请修改后重试。")
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


BASE_TOOLKIT_INSTRUCTIONS = """
基础工作区工具规则：
- 所有工具都操作当前 thread 的同一个 Daytona sandbox，不是 AgentOS 宿主机；路径使用工作区相对路径。
- 文件定位优先使用 rg 搜索，读取、stat、目录树、哈希和 Git 只读检查优先使用 workspace_* 专用工具；这些工具在 sandbox 内复用 sed、wc、stat、find、sha256sum 和 git，不要用 sandbox_exec 重复实现。
- 修改已有文本遵循“读取和哈希 → 精确补丁 → 重新读取或检查”；已知原文件行坐标时使用 workspace_apply_hunks，同一任务涉及 create/update/delete/move 时优先使用 workspace_apply_changes，只有不依赖行坐标的纯文本多段替换使用 workspace_apply_patch_set。创建目录或复制普通文件使用对应 workspace_* 工具。
- 对编码任务先检查相关文件、测试和 Git 状态，明确可验证的成功标准；完成修改后运行与改动匹配的测试或脚本，再检查输出和 workspace_git_diff，不能只凭写入成功声称完成。
- Python 编码优先创建工作区内 `.py` 脚本并反复读取、精确修改和执行；使用当前沙箱已安装的解释器和依赖，不要默认安装新包或访问网络。
- 独立的只读调用可放在同一工具批次；后一步依赖前一步结果时必须串行，并原样使用工具返回的路径、SHA-256、sessionId 和 commandId。
- 短命令使用前台 sandbox_exec；后台命令默认使用短时限，只有明确的长构建、测试或服务才提高 timeout，最长 86400 秒，再用 sandbox_process_poll 轮询到 completed，每次分页原样使用返回的 nextOffset。需要输入、PTY 中断或终止时分别使用 sandbox_process_write、sandbox_process_interrupt 或 sandbox_process_stop，不要用 shell 后台符号绕过受管会话。
- 工具失败时依据返回的错误、output、exitCode 或 status 修正后再继续；不得忽略失败或盲目重复有副作用的调用。
- 只有命令成功结束、后台任务到达 completed、文件修改重新校验后，才能声称对应操作完成；running、已提交或已写入输入都不代表完成。
""".strip()


# Agno 从 Python 签名可以推断类型和必填项，但不会推断这些运行时边界。
# 约束直接写入 Agno Function.parameters；工具实现仍保留同样的服务端校验。
BASE_TOOL_PARAMETER_CONSTRAINTS: dict[str, dict[str, dict[str, Any]]] = {
    "sandbox_exec": {
        "command": {"minLength": 1},
        "timeout": {
            "minimum": 1,
            "maximum": MAX_BACKGROUND_EXECUTION_TIMEOUT,
            "default": 30,
        },
        "background": {"default": False},
        "pty": {"default": False},
        "pty_rows": {"minimum": 1, "maximum": MAX_PTY_ROWS, "default": 24},
        "pty_cols": {"minimum": 1, "maximum": MAX_PTY_COLS, "default": 80},
        "suppress_input_echo": {"default": True},
        "yield_time_ms": {"minimum": 0, "maximum": 30000},
    },
    "sandbox_process_poll": {
        "session_id": {"pattern": r"^agent-exec-[0-9a-f]{32}$"},
        "command_id": {
            "minLength": 1,
            "maxLength": 128,
            "pattern": r"^[A-Za-z0-9._-]+$",
        },
        "offset": {"minimum": 0, "default": 0},
        "max_bytes": {
            "minimum": 1,
            "maximum": MAX_TOOL_OUTPUT_BYTES,
            "default": MAX_TOOL_OUTPUT_BYTES,
        },
    },
    "sandbox_process_write": {
        "session_id": {"pattern": r"^agent-exec-[0-9a-f]{32}$"},
        "command_id": {
            "minLength": 1,
            "maxLength": 128,
            "pattern": r"^[A-Za-z0-9._-]+$",
        },
        "data": {"minLength": 1, "maxLength": MAX_PROCESS_INPUT_BYTES},
        "offset": {"minimum": 0, "default": 0},
        "max_bytes": {
            "minimum": 1,
            "maximum": MAX_TOOL_OUTPUT_BYTES,
            "default": MAX_TOOL_OUTPUT_BYTES,
        },
        "yield_time_ms": {"minimum": 0, "maximum": 30000},
    },
    "sandbox_process_stop": {
        "session_id": {"pattern": r"^agent-exec-[0-9a-f]{32}$"},
        "command_id": {
            "minLength": 1,
            "maxLength": 128,
            "pattern": r"^[A-Za-z0-9._-]+$",
        },
    },
    "sandbox_process_interrupt": {
        "session_id": {"pattern": r"^agent-exec-[0-9a-f]{32}$"},
        "command_id": {
            "minLength": 1,
            "maxLength": 128,
            "pattern": r"^[A-Za-z0-9._-]+$",
        },
        "signal": {"enum": ["INT"], "default": "INT"},
    },
    "workspace_read_lines": {
        "start_line": {"minimum": 1},
        "line_count": {"minimum": 1, "maximum": MAX_READ_LINES, "default": 200},
    },
    "workspace_tree": {
        "max_depth": {"minimum": 1, "maximum": 32, "default": 4},
        "limit": {"minimum": 1, "maximum": MAX_LIST_ENTRIES, "default": 200},
    },
    "workspace_search_files": {
        "pattern": {"minLength": 1, "maxLength": MAX_SEARCH_GLOB_BYTES, "default": "*"},
        "include_globs": {
            "maxItems": MAX_SEARCH_GLOBS,
            "items": {"type": "string", "minLength": 1, "maxLength": MAX_SEARCH_GLOB_BYTES},
        },
        "exclude_globs": {
            "maxItems": MAX_SEARCH_GLOBS,
            "items": {"type": "string", "minLength": 1, "maxLength": MAX_SEARCH_GLOB_BYTES},
        },
        "limit": {"minimum": 1, "maximum": MAX_SEARCH_RESULTS, "default": 50},
        "offset": {"minimum": 0, "maximum": MAX_SEARCH_ENTRIES - 1, "default": 0},
    },
    "workspace_search_text": {
        "query": {"minLength": 1, "maxLength": 1024},
        "include_globs": {
            "maxItems": MAX_SEARCH_GLOBS,
            "items": {"type": "string", "minLength": 1, "maxLength": MAX_SEARCH_GLOB_BYTES},
        },
        "exclude_globs": {
            "maxItems": MAX_SEARCH_GLOBS,
            "items": {"type": "string", "minLength": 1, "maxLength": MAX_SEARCH_GLOB_BYTES},
        },
        "regex": {"default": False},
        "case_mode": {
            "enum": ["smart", "sensitive", "insensitive"],
            "default": "smart",
        },
        "word_match": {"default": False},
        "before_context": {
            "minimum": 0,
            "maximum": MAX_SEARCH_CONTEXT_LINES,
            "default": 0,
        },
        "after_context": {
            "minimum": 0,
            "maximum": MAX_SEARCH_CONTEXT_LINES,
            "default": 0,
        },
        "mode": {
            "enum": ["matches", "files_with_matches", "count"],
            "default": "matches",
        },
        "limit": {"minimum": 1, "maximum": MAX_SEARCH_RESULTS, "default": 50},
        "offset": {"minimum": 0, "maximum": MAX_SEARCH_ENTRIES - 1, "default": 0},
    },
    "workspace_apply_patch": {
        "old_text": {"minLength": 1},
        "expected_sha256": {
            "minLength": 64,
            "maxLength": 64,
            "pattern": r"^[0-9a-fA-F]{64}$",
        },
    },
    "workspace_apply_patch_set": {
        "patches": {
            "minItems": 1,
            "maxItems": MAX_PATCH_FILES,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["path", "expected_sha256", "edits"],
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "目标工作区相对文件路径。",
                        "minLength": 1,
                        "maxLength": MAX_PATH_BYTES,
                    },
                    "expected_sha256": {
                        "type": "string",
                        "description": "修改前由 workspace_hash_file 返回的 SHA-256。",
                        "minLength": 64,
                        "maxLength": 64,
                        "pattern": r"^[0-9a-fA-F]{64}$",
                    },
                    "edits": {
                        "type": "array",
                        "description": "按顺序应用到当前文件的精确文本编辑。",
                        "minItems": 1,
                        "maxItems": MAX_PATCH_EDITS,
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["old_text", "new_text"],
                            "properties": {
                                "old_text": {
                                    "type": "string",
                                    "description": "必须精确匹配的原文本。",
                                    "minLength": 1,
                                },
                                "new_text": {
                                    "type": "string",
                                    "description": "替换后的新文本。",
                                },
                                "replace_all": {
                                    "type": "boolean",
                                    "description": "是否替换当前文件中的全部匹配。",
                                    "default": False,
                                },
                            },
                        },
                    },
                },
            },
        },
    },
    "workspace_apply_hunks": {
        "patches": {
            "minItems": 1,
            "maxItems": MAX_PATCH_FILES,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["path", "expected_sha256", "hunks"],
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "目标工作区相对文件路径。",
                        "minLength": 1,
                        "maxLength": MAX_PATH_BYTES,
                    },
                    "expected_sha256": {
                        "type": "string",
                        "description": "修改前由 workspace_hash_file 返回的 SHA-256。",
                        "minLength": 64,
                        "maxLength": 64,
                        "pattern": r"^[0-9a-fA-F]{64}$",
                    },
                    "hunks": {
                        "type": "array",
                        "description": "按原文件行坐标定位且互不重叠的文本 hunk。",
                        "minItems": 1,
                        "maxItems": MAX_PATCH_EDITS,
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["old_start", "old_text", "new_text"],
                            "properties": {
                                "old_start": {
                                    "type": "integer",
                                    "description": "原文件中的 1-based 起始行号。",
                                    "minimum": 1,
                                },
                                "old_text": {
                                    "type": "string",
                                    "description": "必须从起始行精确匹配的原文本。",
                                    "minLength": 1,
                                },
                                "new_text": {
                                    "type": "string",
                                    "description": "替换后的新文本。",
                                },
                            },
                        },
                    },
                },
            },
        },
    },
    "workspace_git_log": {
        "revision": {"minLength": 1, "maxLength": 128, "default": "HEAD"},
        "max_count": {
            "minimum": 1,
            "maximum": MAX_GIT_LOG_ENTRIES,
            "default": 20,
        },
    },
    "workspace_git_show": {
        "revision": {"minLength": 1, "maxLength": 128, "default": "HEAD"},
    },
    "workspace_apply_changes": {
        "changes": {
            "minItems": 1,
            "maxItems": MAX_PATCH_FILES,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["operation", "path"],
                "properties": {
                    "operation": {
                        "type": "string",
                        "description": "文件操作：create、update、delete 或 move。",
                        "enum": ["create", "update", "delete", "move"],
                    },
                    "path": {
                        "type": "string",
                        "description": "源文件或新建文件的工作区相对路径。",
                        "minLength": 1,
                        "maxLength": MAX_PATH_BYTES,
                    },
                    "destination": {
                        "type": "string",
                        "description": "move 操作的目标工作区相对路径。",
                        "minLength": 1,
                        "maxLength": MAX_PATH_BYTES,
                    },
                    "content": {
                        "type": "string",
                        "description": "create 或 update 操作的完整 UTF-8 文本。",
                    },
                    "expected_sha256": {
                        "type": "string",
                        "description": "update、delete 或 move 前的文件 SHA-256。",
                        "minLength": 64,
                        "maxLength": 64,
                        "pattern": r"^[0-9a-fA-F]{64}$",
                    },
                },
            },
        },
    },
}


class DaytonaToolkit(Toolkit):
    def __init__(
        self,
        service: WorkspaceService,
        *,
        name: str = "daytona_workspace",
        instructions: str | None = None,
        add_instructions: bool = False,
    ):
        self.service = service
        super().__init__(
            name=name,
            tools=[
                self.sandbox_exec,
                self.sandbox_process_poll,
                self.sandbox_process_write,
                self.sandbox_process_interrupt,
                self.sandbox_process_stop,
            ],
            instructions=instructions,
            add_instructions=add_instructions,
            requires_confirmation_tools=[
                "sandbox_exec",
                "sandbox_process_write",
                "sandbox_process_interrupt",
                "sandbox_process_stop",
            ],
        )

    @staticmethod
    def _validate_process_ids(session_id: str, command_id: str) -> tuple[str, str]:
        suffix = session_id[len(MANAGED_PROCESS_PREFIX) :] if isinstance(session_id, str) else ""
        if (
            not isinstance(session_id, str)
            or not session_id.startswith(MANAGED_PROCESS_PREFIX)
            or len(suffix) != 32
            or any(character not in "0123456789abcdef" for character in suffix)
        ):
            raise WorkspaceError("后台进程会话标识无效，请使用 sandbox_exec 返回的 sessionId。")
        if (
            not isinstance(command_id, str)
            or not 1 <= len(command_id) <= 128
            or not command_id.isascii()
            or any(not (character.isalnum() or character in "-_.") for character in command_id)
        ):
            raise WorkspaceError("后台进程命令标识无效，请使用 sandbox_exec 返回的 commandId。")
        return session_id, command_id

    @staticmethod
    async def _managed_command(process: Any, session_id: str, command_id: str):
        session_id, command_id = DaytonaToolkit._validate_process_ids(session_id, command_id)
        try:
            session = await process.get_session(session_id)
        except DaytonaNotFoundError as error:
            raise WorkspaceProcessNotFound("后台进程不属于当前会话或已经结束。") from error
        if command_id not in {
            str(getattr(command, "id", "") or "") for command in getattr(session, "commands", [])
        }:
            raise WorkspaceProcessNotFound("后台进程不属于当前会话或已经结束。")
        try:
            return await process.get_session_command(session_id, command_id)
        except DaytonaNotFoundError as error:
            raise WorkspaceProcessNotFound("后台进程不属于当前会话或已经结束。") from error

    async def _start_managed_session(
        self,
        process: Any,
        thread: str,
        request: SessionExecuteRequest,
        session_id: str | None = None,
    ) -> tuple[str, str, Any]:
        lock_key = f"agent-managed-processes:{self.service._hash(thread)}"
        async with self.service.async_registry.locked(lock_key):
            active = 0
            for session in await process.list_sessions():
                existing_session_id = str(getattr(session, "session_id", "") or "")
                if not existing_session_id.startswith(MANAGED_PROCESS_PREFIX):
                    continue
                commands = list(getattr(session, "commands", []) or [])
                if not commands:
                    await process.delete_session(existing_session_id)
                elif any(getattr(command, "exit_code", None) is None for command in commands):
                    active += 1
            if active >= MAX_MANAGED_PROCESSES:
                raise WorkspaceError(
                    f"当前对话已有 {MAX_MANAGED_PROCESSES} 个后台进程，请轮询或终止后再启动。"
                )
            session_id = session_id or f"{MANAGED_PROCESS_PREFIX}{uuid.uuid4().hex}"
            self._validate_process_ids(session_id, "pending")
            await process.create_session(session_id)
            try:
                value = await process.execute_session_command(
                    session_id,
                    request,
                    timeout=5,
                )
                command_id = str(getattr(value, "cmd_id", "") or "")
                self._validate_process_ids(session_id, command_id)
            except BaseException:
                try:
                    await complete_cleanup(process.delete_session(session_id))
                except Exception:
                    pass
                raise
            return session_id, command_id, value

    def _session_output(
        self,
        value: Any,
        *,
        session_id: str,
        command_id: str,
        status: str,
        exit_code: int | None,
        offset: int = 0,
        max_bytes: int = MAX_TOOL_OUTPUT_BYTES,
        wall_time_seconds: float | None = None,
        timeout_marker: str | None = None,
    ) -> dict[str, Any]:
        stdout = str(getattr(value, "stdout", "") or "")
        stderr = str(getattr(value, "stderr", "") or "")
        if stdout or stderr:
            output = stdout + (("\n" if stdout and stderr else "") + stderr)
        else:
            output = re.sub(
                r"(?m)^(?:\x01{1,3}|\x02{1,3})",
                "",
                str(getattr(value, "output", "") or ""),
            )
        if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
            raise WorkspaceError("后台日志偏移必须是大于等于 0 的整数。")
        if (
            isinstance(max_bytes, bool)
            or not isinstance(max_bytes, int)
            or not 1 <= max_bytes <= MAX_TOOL_OUTPUT_BYTES
        ):
            raise WorkspaceError(
                f"后台日志单次读取字节数必须是 1 至 {MAX_TOOL_OUTPUT_BYTES} 之间的整数。"
            )
        raw_output = str(output or "")
        marker_output = self._timeout_output_marker(timeout_marker) if timeout_marker else None
        timed_out = bool(marker_output and marker_output in raw_output)
        if marker_output:
            raw_output = raw_output.replace(marker_output, "")
        encoded = raw_output.encode("utf-8", errors="replace")
        total_bytes = len(encoded)
        if offset > total_bytes:
            raise WorkspaceError("后台日志偏移超过当前日志大小，请使用返回的 nextOffset。")
        try:
            encoded[:offset].decode("utf-8")
        except UnicodeDecodeError as error:
            raise WorkspaceError(
                "后台日志偏移不是 UTF-8 字符边界，请使用返回的 nextOffset。"
            ) from error
        end = min(total_bytes, offset + max_bytes)
        while end > offset:
            try:
                selected = encoded[offset:end].decode("utf-8")
                break
            except UnicodeDecodeError:
                end -= 1
        else:
            selected = ""
        if not selected and offset < total_bytes:
            raise WorkspaceError(
                "后台日志单次读取字节数不足以容纳下一个 UTF-8 字符，请增大 max_bytes。"
            )
        has_more = end < total_bytes
        result: dict[str, Any] = {
            "sessionId": session_id,
            "commandId": command_id,
            "status": status,
            "exitCode": exit_code,
            "output": selected,
            "offset": offset,
            "nextOffset": end,
            "totalBytes": total_bytes,
            "originalBytes": total_bytes,
            "hasMore": has_more,
            "truncated": has_more,
        }
        if wall_time_seconds is not None:
            result["wallTimeSeconds"] = round(max(0.0, wall_time_seconds), 3)
        if timed_out:
            result["timedOut"] = True
        return result

    @staticmethod
    def _timeout_output_marker(marker: str) -> str:
        return f"\n{MANAGED_TIMEOUT_OUTPUT_PREFIX}:{marker}\n"

    @staticmethod
    def _managed_timeout_marker(command: Any) -> str | None:
        try:
            wrapper = shlex.split(str(getattr(command, "command", "") or ""))
        except ValueError:
            return None
        prefix = f"{MANAGED_TIMEOUT_ENV}="
        for token in wrapper:
            if not token.startswith(prefix):
                continue
            marker = token.removeprefix(prefix)
            if len(marker) == 32 and all(character in "0123456789abcdef" for character in marker):
                return marker
        return None

    @staticmethod
    def _validate_yield_time(yield_time_ms: int | None) -> int | None:
        if yield_time_ms is None:
            return None
        if (
            isinstance(yield_time_ms, bool)
            or not isinstance(yield_time_ms, int)
            or not 0 <= yield_time_ms <= 30000
        ):
            raise WorkspaceError("命令等待时间必须是 0 至 30000 毫秒之间的整数。")
        return yield_time_ms

    async def _wait_managed_output(
        self,
        process: Any,
        session_id: str,
        command_id: str,
        *,
        offset: int,
        max_bytes: int,
        yield_time_ms: int,
        started_at: float,
    ) -> dict[str, Any]:
        deadline = asyncio.get_running_loop().time() + yield_time_ms / 1000
        while True:
            command = await self._managed_command(process, session_id, command_id)
            exit_code = getattr(command, "exit_code", None)
            if exit_code is not None or asyncio.get_running_loop().time() >= deadline:
                break
            await asyncio.sleep(min(0.1, max(0.0, deadline - asyncio.get_running_loop().time())))
        logs = await process.get_session_command_logs(session_id, command_id)
        status = "completed" if exit_code is not None else "running"
        result = self._session_output(
            logs,
            session_id=session_id,
            command_id=command_id,
            status=status,
            exit_code=exit_code,
            offset=offset,
            max_bytes=max_bytes,
            wall_time_seconds=asyncio.get_running_loop().time() - started_at,
            timeout_marker=self._managed_timeout_marker(command),
        )
        if status == "completed" and not result["hasMore"]:
            await process.delete_session(session_id)
        return result

    async def sandbox_exec(
        self,
        command: str,
        cwd: str | None = None,
        timeout: int = 30,
        background: bool = False,
        pty: bool = False,
        pty_rows: int = 24,
        pty_cols: int = 80,
        suppress_input_echo: bool = True,
        yield_time_ms: int | None = None,
        run_context: RunContext | None = None,
    ) -> dict[str, Any]:
        """在当前对话的 Daytona sandbox 中执行命令；默认工作目录为 /home/daytona/workspace。

        background=true 返回受管 sessionId/commandId，后续用进程工具轮询，
        禁止用 nohup 或 shell 后台符号绕过会话。

        Args:
            command: 要在 sandbox 内执行的完整 Shell 命令。
            cwd: 相对工作区根目录的工作目录；省略时使用工作区根目录。
            timeout: 执行超时秒数；前台最多 60 秒，后台最多 86400 秒。
            background: 是否以受管后台会话执行；长任务使用后台模式。
            pty: 是否通过 script 分配伪终端；仅交互式命令需要启用。
            pty_rows: 伪终端行数，范围为 1 至 200。
            pty_cols: 伪终端列数，范围为 1 至 400。
            suppress_input_echo: 是否关闭伪终端输入回显，默认关闭回显。
            yield_time_ms: 后台命令启动后等待输出或完成的毫秒数，范围 0 至 30000。
        """
        if not isinstance(command, str) or not command.strip():
            raise WorkspaceError("命令不能为空。")
        if not isinstance(background, bool):
            raise WorkspaceError("后台执行标志必须是布尔值。")
        if not isinstance(pty, bool):
            raise WorkspaceError("伪终端标志必须是布尔值。")
        if (
            isinstance(pty_rows, bool)
            or not isinstance(pty_rows, int)
            or not 1 <= pty_rows <= MAX_PTY_ROWS
        ):
            raise WorkspaceError(f"伪终端行数必须是 1 至 {MAX_PTY_ROWS} 之间的整数。")
        if (
            isinstance(pty_cols, bool)
            or not isinstance(pty_cols, int)
            or not 1 <= pty_cols <= MAX_PTY_COLS
        ):
            raise WorkspaceError(f"伪终端列数必须是 1 至 {MAX_PTY_COLS} 之间的整数。")
        if not isinstance(suppress_input_echo, bool):
            raise WorkspaceError("伪终端输入回显标志必须是布尔值。")
        yield_time_ms = self._validate_yield_time(yield_time_ms)
        if yield_time_ms is not None and not background:
            raise WorkspaceError("命令等待时间只适用于后台模式。")
        execution_timeout = self.service._validate_timeout(
            timeout,
            MAX_BACKGROUND_EXECUTION_TIMEOUT if background else MAX_EXECUTION_TIMEOUT,
        )
        executed_command = command
        if pty:
            stty = f"stty rows {pty_rows} cols {pty_cols}"
            if suppress_input_echo:
                stty += " -echo"
            pty_command = (
                f"export TERM=xterm-256color; {stty}; exec /bin/sh -lc {shlex.quote(command)}"
            )
            executed_command = shlex.join(
                ["script", "--quiet", "--return", "--command", pty_command, "/dev/null"]
            )
        remote_cwd = WORKSPACE_ROOT
        if cwd is not None:
            _relative, remote_cwd = self.service.normalize_path(cwd)
        async with self.service._async_client() as client:
            sandbox = await self.service._asandbox_for(client, _thread(run_context))
            if background:
                started_at = asyncio.get_running_loop().time()
                timeout_marker = uuid.uuid4().hex
                timeout_status_path = f"/tmp/agent-managed-status-{timeout_marker}"
                tracked_command = (
                    f"(\n{executed_command}\n)\n"
                    "command_status=$?\n"
                    f"printf '%s' \"$command_status\" > {shlex.quote(timeout_status_path)}\n"
                    'exit "$command_status"'
                )
                timeout_command = (
                    "timeout --signal=TERM --kill-after=5s "
                    f"{execution_timeout}s /bin/sh -lc {shlex.quote(tracked_command)}\n"
                    "transport_status=$?\n"
                    f"if [ -f {shlex.quote(timeout_status_path)} ]; then\n"
                    f"  command_status=$(cat -- {shlex.quote(timeout_status_path)})\n"
                    f"  rm -f -- {shlex.quote(timeout_status_path)}\n"
                    '  exit "$command_status"\n'
                    "fi\n"
                    f"rm -f -- {shlex.quote(timeout_status_path)}\n"
                    'if [ "$transport_status" -eq 124 ]; then\n'
                    f"  printf '%s' {shlex.quote(self._timeout_output_marker(timeout_marker))} >&2\n"
                    "fi\n"
                    'exit "$transport_status"'
                )
                environment = ["env"]
                if pty:
                    environment.append("AGENT_MANAGED_PTY=1")
                environment.append(f"{MANAGED_TIMEOUT_ENV}={timeout_marker}")
                wrapped_command = (
                    f"cd -- {shlex.quote(remote_cwd)} && "
                    f"{shlex.join(environment)} /bin/sh -lc {shlex.quote(timeout_command)}"
                )
                session_id, command_id, value = await self._start_managed_session(
                    sandbox.process,
                    _thread(run_context),
                    SessionExecuteRequest(
                        command=wrapped_command,
                        run_async=True,
                        suppress_input_echo=suppress_input_echo if pty else False,
                    ),
                )
                exit_code = getattr(value, "exit_code", None)
                if yield_time_ms is not None:
                    return await self._wait_managed_output(
                        sandbox.process,
                        session_id,
                        command_id,
                        offset=0,
                        max_bytes=MAX_TOOL_OUTPUT_BYTES,
                        yield_time_ms=yield_time_ms,
                        started_at=started_at,
                    )
                status = "completed" if exit_code is not None else "running"
                result = self._session_output(
                    value,
                    session_id=session_id,
                    command_id=command_id,
                    status=status,
                    exit_code=exit_code,
                    wall_time_seconds=asyncio.get_running_loop().time() - started_at,
                    timeout_marker=timeout_marker,
                )
                if status == "completed" and not result["hasMore"]:
                    await sandbox.process.delete_session(session_id)
                return result
            value = await sandbox.process.exec(
                executed_command, cwd=remote_cwd, timeout=execution_timeout
            )
        return self.service._bounded_output(value)

    async def sandbox_process_poll(
        self,
        session_id: str,
        command_id: str,
        offset: int = 0,
        max_bytes: int = MAX_TOOL_OUTPUT_BYTES,
        run_context: RunContext | None = None,
    ) -> dict[str, Any]:
        """轮询 sandbox_exec 后台命令并返回最多 64 KiB 日志。

        Args:
            session_id: sandbox_exec 返回的 sessionId。
            command_id: sandbox_exec 返回的 commandId。
            offset: UTF-8 日志字节偏移，首次为 0，后续使用上次返回的 nextOffset。
            max_bytes: 本次最多读取的日志字节数，上限为 64 KiB。
        """
        async with self.service._async_client() as client:
            sandbox = await self.service._asandbox_for(client, _thread(run_context))
            command = await self._managed_command(sandbox.process, session_id, command_id)
            logs = await sandbox.process.get_session_command_logs(session_id, command_id)
            exit_code = getattr(command, "exit_code", None)
            status = "completed" if exit_code is not None else "running"
            result = self._session_output(
                logs,
                session_id=session_id,
                command_id=command_id,
                status=status,
                exit_code=exit_code,
                offset=offset,
                max_bytes=max_bytes,
                timeout_marker=self._managed_timeout_marker(command),
            )
            if status == "completed" and not result["hasMore"]:
                await sandbox.process.delete_session(session_id)
            return result

    async def sandbox_process_write(
        self,
        session_id: str,
        command_id: str,
        data: str,
        offset: int = 0,
        max_bytes: int = MAX_TOOL_OUTPUT_BYTES,
        yield_time_ms: int | None = None,
        run_context: RunContext | None = None,
    ) -> dict[str, Any]:
        """向当前对话仍在运行的受管后台命令写入文本；执行前需要确认。

        Args:
            session_id: sandbox_exec 返回的 sessionId。
            command_id: sandbox_exec 返回的 commandId。
            data: 写入后台进程标准输入的 UTF-8 文本，最多 8 KiB。
            offset: 写入后读取日志的 UTF-8 字节偏移。
            max_bytes: 写入后最多读取的日志字节数，上限为 64 KiB。
            yield_time_ms: 写入后等待新输出或完成的毫秒数，范围 0 至 30000；省略则只写入。
        """
        if not isinstance(data, str) or not data:
            raise WorkspaceError("后台进程输入不能为空。")
        if len(data.encode("utf-8")) > MAX_PROCESS_INPUT_BYTES:
            raise WorkspaceError("后台进程单次输入超过 8 KiB，请拆分后重试。")
        yield_time_ms = self._validate_yield_time(yield_time_ms)
        async with self.service._async_client() as client:
            sandbox = await self.service._asandbox_for(client, _thread(run_context))
            command = await self._managed_command(sandbox.process, session_id, command_id)
            if getattr(command, "exit_code", None) is not None:
                raise WorkspaceError("后台进程已经结束，不能继续写入。")
            await sandbox.process.send_session_command_input(session_id, command_id, data)
            if yield_time_ms is not None:
                result = await self._wait_managed_output(
                    sandbox.process,
                    session_id,
                    command_id,
                    offset=offset,
                    max_bytes=max_bytes,
                    yield_time_ms=yield_time_ms,
                    started_at=asyncio.get_running_loop().time(),
                )
                return {"ok": True, **result}
        return {"ok": True, "status": "input_sent"}

    async def sandbox_process_interrupt(
        self,
        session_id: str,
        command_id: str,
        signal: str = "INT",
        run_context: RunContext | None = None,
    ) -> dict[str, Any]:
        """向使用 PTY 的受管后台命令发送 Ctrl-C；执行前需要确认。

        Args:
            session_id: sandbox_exec 返回的 sessionId。
            command_id: sandbox_exec 返回的 commandId。
            signal: 要发送的信号，目前只支持 INT。
        """
        if signal != "INT":
            raise WorkspaceError("后台进程中断目前只支持 INT 信号。")
        async with self.service._async_client() as client:
            sandbox = await self.service._asandbox_for(client, _thread(run_context))
            command = await self._managed_command(sandbox.process, session_id, command_id)
            if getattr(command, "exit_code", None) is not None:
                raise WorkspaceError("后台进程已经结束，不能发送中断信号。")
            try:
                wrapper = shlex.split(str(getattr(command, "command", "") or ""))
            except ValueError:
                wrapper = []
            if wrapper[3:6] != ["&&", "env", "AGENT_MANAGED_PTY=1"]:
                raise WorkspaceError("后台进程未启用 PTY，不能发送终端中断信号。")
            await sandbox.process.send_session_command_input(session_id, command_id, "\x03")
        return {"ok": True, "status": "signal_sent", "signal": signal}

    async def sandbox_process_stop(
        self,
        session_id: str,
        command_id: str,
        run_context: RunContext | None = None,
    ) -> dict[str, Any]:
        """终止当前对话的受管后台命令并清理会话；执行前需要确认。

        Args:
            session_id: sandbox_exec 返回的 sessionId。
            command_id: sandbox_exec 返回的 commandId。
        """
        async with self.service._async_client() as client:
            sandbox = await self.service._asandbox_for(client, _thread(run_context))
            await self._managed_command(sandbox.process, session_id, command_id)
            await sandbox.process.delete_session(session_id)
        return {"ok": True, "status": "terminated"}


class WorkspaceToolkit(DaytonaToolkit):
    def __init__(
        self,
        service: WorkspaceService,
        *,
        name: str = "daytona_workspace",
        instructions: str | None = None,
        add_instructions: bool = False,
    ):
        super().__init__(
            service,
            name=name,
            instructions=instructions,
            add_instructions=add_instructions,
        )
        for function in (
            self.workspace_list_files,
            self.workspace_read_file,
            self.workspace_read_lines,
            self.workspace_stat,
            self.workspace_tree,
            self.workspace_search_files,
            self.workspace_search_text,
            self.workspace_hash_file,
            self.workspace_git_status,
            self.workspace_git_diff,
            self.workspace_git_log,
            self.workspace_git_show,
            self.workspace_write_file,
            self.workspace_replace_file,
            self.workspace_move_file,
            self.workspace_apply_patch,
            self.workspace_apply_patch_set,
            self.workspace_apply_hunks,
            self.workspace_apply_changes,
            self.workspace_create_directory,
            self.workspace_copy_file,
            self.workspace_delete_file,
            self.workspace_view_image,
            self.workspace_inspect_pdf,
        ):
            self.register(function)
        for name in (
            "workspace_write_file",
            "workspace_replace_file",
            "workspace_move_file",
            "workspace_apply_patch",
            "workspace_apply_patch_set",
            "workspace_apply_hunks",
            "workspace_apply_changes",
            "workspace_create_directory",
            "workspace_copy_file",
            "workspace_delete_file",
        ):
            self.functions[name].requires_confirmation = True

    def workspace_list_files(self, path: str = "", run_context: RunContext | None = None):
        """列出当前对话工作区中的文件。

        Args:
            path: 要列出的工作区相对目录；空字符串表示根目录。
        """
        return json.dumps(self.service.list_files(_thread(run_context), path), ensure_ascii=False)

    def workspace_read_file(self, path: str, run_context: RunContext | None = None):
        """读取当前对话工作区中不超过 64 KiB 的 UTF-8 文本。

        Args:
            path: 要读取的工作区相对文件路径；更大文件使用 workspace_read_lines。
        """
        if _is_controlled_raw_dataset(path):
            raise WorkspaceError("原始报表分片不能进入智能体上下文；请在 sandbox 中分析。")
        content = self.service.read_text(_thread(run_context), path)
        if len(content.encode("utf-8")) > MAX_TOOL_OUTPUT_BYTES:
            raise WorkspaceError(
                "文件内容超过单次工具输出限制，请使用 workspace_read_lines 分段读取。"
            )
        return content

    async def workspace_read_lines(
        self,
        path: str,
        start_line: int = 1,
        line_count: int = 200,
        run_context: RunContext | None = None,
    ):
        """按一至五百行分段读取当前工作区 UTF-8 文本。

        Args:
            path: 要读取的工作区相对文件路径。
            start_line: 起始行号，从 1 开始。
            line_count: 本次读取的行数，范围为 1 至 500。
        """
        if _is_controlled_raw_dataset(path):
            raise WorkspaceError("原始报表分片不能进入智能体上下文；请在 sandbox 中分析。")
        return await self.service.aread_lines(
            _thread(run_context),
            path,
            start_line,
            line_count,
        )

    async def workspace_stat(
        self,
        path: str = "",
        run_context: RunContext | None = None,
    ):
        """使用 sandbox 内的 stat 读取普通文件或目录元数据。

        Args:
            path: 工作区相对文件或目录路径；空字符串表示工作区根目录。
        """
        return await self.service.astat(_thread(run_context), path)

    async def workspace_tree(
        self,
        path: str = "",
        max_depth: int = 4,
        limit: int = 200,
        run_context: RunContext | None = None,
    ):
        """使用 sandbox 内的 find 递归列出目录树，不读取文件内容。

        Args:
            path: 目录树根路径；空字符串表示工作区根目录。
            max_depth: 最大递归深度，范围为 1 至 32。
            limit: 最多返回的文件和目录条目数，上限为 500。
        """
        return await self.service.atree(
            _thread(run_context), path, max_depth=max_depth, limit=limit
        )

    async def workspace_search_files(
        self,
        pattern: str = "*",
        path: str = "",
        include_globs: list[str] | None = None,
        exclude_globs: list[str] | None = None,
        limit: int = 50,
        offset: int = 0,
        run_context: RunContext | None = None,
    ):
        """使用 sandbox 内的 rg 按 glob 递归查找当前工作区文件。

        Args:
            pattern: 兼容单模式搜索的文件 glob；提供 include_globs 时忽略此项。
            path: 搜索起点的工作区相对目录；空字符串表示根目录。
            include_globs: 最多二十个包含 glob；空数组表示不限制文件名。
            exclude_globs: 最多二十个排除 glob，不要添加前导 !。
            limit: 本次最多返回的项数，上限为 100。
            offset: 分页起始偏移量，从 0 开始。
        """
        return await self.service.asearch_files(
            _thread(run_context),
            pattern,
            path,
            include_globs,
            exclude_globs,
            limit,
            offset,
        )

    async def workspace_search_text(
        self,
        query: str,
        path: str = "",
        include_globs: list[str] | None = None,
        exclude_globs: list[str] | None = None,
        regex: bool = False,
        case_mode: str = "smart",
        word_match: bool = False,
        before_context: int = 0,
        after_context: int = 0,
        mode: str = "matches",
        limit: int = 50,
        offset: int = 0,
        run_context: RunContext | None = None,
    ):
        """使用 sandbox 内的 rg 搜索文本；支持正则、上下文和计数输出。

        Args:
            query: 要查找的文本；regex=true 时按正则表达式解析。
            path: 搜索起点的工作区相对目录；空字符串表示根目录。
            include_globs: 最多二十个包含 glob；空数组表示不限制文件名。
            exclude_globs: 最多二十个排除 glob，不要添加前导 !。
            regex: 是否将 query 作为正则表达式。
            case_mode: 大小写模式：smart、sensitive 或 insensitive。
            word_match: 是否仅匹配完整单词。
            before_context: 每个匹配前返回的上下文行数，范围为零至五。
            after_context: 每个匹配后返回的上下文行数，范围为零至五。
            mode: 输出 matches、files_with_matches 或 count。
            limit: 本次最多返回的匹配数，上限为 100。
            offset: 分页起始偏移量，从 0 开始。
        """
        return await self.service.asearch_text(
            _thread(run_context),
            query,
            path,
            include_globs,
            exclude_globs,
            regex,
            case_mode,
            word_match,
            before_context,
            after_context,
            mode,
            limit,
            offset,
        )

    async def workspace_hash_file(self, path: str, run_context: RunContext | None = None):
        """使用 sandbox 内的 sha256sum 计算普通文件的 SHA-256 和大小。

        Args:
            path: 要计算哈希的工作区相对文件路径。
        """
        return await self.service.ahash_file(_thread(run_context), path)

    async def workspace_git_status(
        self,
        repo_path: str = "",
        run_context: RunContext | None = None,
    ):
        """读取 Git 工作区、暂存区和分支状态，不修改仓库。

        Args:
            repo_path: Git 仓库的工作区相对目录；空字符串表示工作区根目录。
        """
        return await self.service.agit_status(_thread(run_context), repo_path)

    async def workspace_git_diff(
        self,
        repo_path: str = "",
        staged: bool = False,
        revision: str | None = None,
        file_path: str | None = None,
        run_context: RunContext | None = None,
    ):
        """读取 Git 未提交、暂存区或指定修订的差异，不接受自由 flags。

        Args:
            repo_path: Git 仓库的工作区相对目录；空字符串表示工作区根目录。
            staged: 是否读取暂存区差异。
            revision: 可选的基准分支、标签或提交哈希。
            file_path: 可选的仓库内相对文件路径，用于限制差异范围。
        """
        return await self.service.agit_diff(
            _thread(run_context), repo_path, staged, revision, file_path
        )

    async def workspace_git_log(
        self,
        repo_path: str = "",
        revision: str = "HEAD",
        max_count: int = 20,
        file_path: str | None = None,
        run_context: RunContext | None = None,
    ):
        """读取 Git 提交日志，不接受自由 flags。

        Args:
            repo_path: Git 仓库的工作区相对目录；空字符串表示工作区根目录。
            revision: 起始分支、标签或提交哈希，默认为 HEAD。
            max_count: 最多返回的提交数，范围为 1 至 100。
            file_path: 可选的仓库内相对文件路径，用于限制日志范围。
        """
        return await self.service.agit_log(
            _thread(run_context), repo_path, revision, max_count, file_path
        )

    async def workspace_git_show(
        self,
        repo_path: str = "",
        revision: str = "HEAD",
        file_path: str | None = None,
        run_context: RunContext | None = None,
    ):
        """读取 Git 提交详情和补丁，不接受自由 flags。

        Args:
            repo_path: Git 仓库的工作区相对目录；空字符串表示工作区根目录。
            revision: 要查看的分支、标签或提交哈希，默认为 HEAD。
            file_path: 可选的仓库内相对文件路径，用于限制补丁范围。
        """
        return await self.service.agit_show(_thread(run_context), repo_path, revision, file_path)

    def workspace_write_file(self, path: str, content: str, run_context: RunContext | None = None):
        """在当前对话工作区中新建 UTF-8 文件；执行前需要确认。

        Args:
            path: 要新建的工作区相对文件路径。
            content: 要写入的完整 UTF-8 文本。
        """
        result = self.service.create_file(_thread(run_context), path, content.encode("utf-8"))
        return {**result, "message": "文件已新建。"}

    def workspace_replace_file(
        self, path: str, content: str, run_context: RunContext | None = None
    ):
        """覆盖当前对话工作区中的普通 UTF-8 文件；执行前需要确认。

        Args:
            path: 要覆盖的工作区相对文件路径。
            content: 要写入的完整 UTF-8 文本。
        """
        result = self.service.replace_file(_thread(run_context), path, content.encode("utf-8"))
        return {**result, "message": "文件已覆盖。"}

    def workspace_move_file(
        self, source: str, destination: str, run_context: RunContext | None = None
    ):
        """移动或重命名当前对话工作区中的文件或目录；目标已存在时拒绝操作。

        Args:
            source: 源文件或目录的工作区相对路径。
            destination: 目标的工作区相对路径。
        """
        self.service.move_file(_thread(run_context), source, destination)
        return {"ok": True, "message": "文件或目录已移动。"}

    def workspace_apply_patch(
        self,
        path: str,
        old_text: str,
        new_text: str,
        expected_sha256: str,
        replace_all: bool = False,
        run_context: RunContext | None = None,
    ):
        """精确替换 UTF-8 文件中的文本；执行前需要确认。

        Args:
            path: 要修改的工作区相对文件路径。
            old_text: 必须精确匹配的原文本。
            new_text: 替换后的新文本。
            expected_sha256: 修改前由 workspace_hash_file 返回的 SHA-256。
            replace_all: 是否允许并替换 old_text 的所有匹配；默认只允许唯一匹配。
        """
        result = self.service.apply_patch(
            _thread(run_context),
            path,
            old_text,
            new_text,
            expected_sha256,
            replace_all,
        )
        return {**result, "message": "文件补丁已应用。"}

    def workspace_apply_patch_set(
        self,
        patches: list[dict[str, Any]],
        run_context: RunContext | None = None,
    ):
        """预检后批量修改多个 UTF-8 文件；整个工具调用执行前只确认一次。

        Args:
            patches: 一至二十个文件补丁；每项携带 path、expected_sha256 和顺序 edits。
        """
        result = self.service.apply_patch_set(_thread(run_context), patches)
        return {**result, "message": "批量文件补丁已应用。"}

    def workspace_apply_hunks(
        self,
        patches: list[dict[str, Any]],
        run_context: RunContext | None = None,
    ):
        """按原文件行号精确应用一个或多个 UTF-8 hunk；执行前只确认一次。

        Args:
            patches: 一至二十个文件补丁；每项携带 path、expected_sha256 和 hunks。
        """
        result = self.service.apply_hunks(_thread(run_context), patches)
        return {**result, "message": "定位文件补丁已应用。"}

    def workspace_apply_changes(
        self,
        changes: list[dict[str, Any]],
        run_context: RunContext | None = None,
    ):
        """预检后批量新建、更新、删除或移动普通文件；执行前只确认一次。

        Args:
            changes: 一至二十个 create、update、delete 或 move 文件操作。
        """
        result = self.service.apply_changes(_thread(run_context), changes)
        return {**result, "message": "完整文件变更集已应用。"}

    def workspace_create_directory(
        self,
        path: str,
        run_context: RunContext | None = None,
    ):
        """递归创建当前工作区相对目录；目标已存在时拒绝；执行前需要确认。

        Args:
            path: 要创建的工作区相对目录路径。
        """
        return self.service.create_directory(_thread(run_context), path)

    def workspace_copy_file(
        self,
        source: str,
        destination: str,
        run_context: RunContext | None = None,
    ):
        """复制不超过 200 MiB 的普通文件；目标已存在时拒绝；执行前需要确认。

        Args:
            source: 源普通文件的工作区相对路径。
            destination: 目标普通文件的工作区相对路径。
        """
        return self.service.copy_file(_thread(run_context), source, destination)

    def workspace_delete_file(
        self, path: str, recursive: bool = False, run_context: RunContext | None = None
    ):
        """删除当前对话工作区中的文件或目录；执行前需要确认。

        Args:
            path: 要删除的工作区相对文件或目录路径。
            recursive: 删除目录时是否递归删除其内容。
        """
        self.service.delete_file(_thread(run_context), path, recursive)
        return {"ok": True, "message": "文件或目录已删除。"}

    def workspace_view_image(self, path: str, run_context: RunContext | None = None) -> ToolResult:
        """加载当前工作区中不超过 10 MiB 的 PNG、JPEG、GIF 或 WebP 图片。

        Args:
            path: 要检查的工作区相对图片路径。
        """
        return self.service.view_image(_thread(run_context), path)

    def workspace_inspect_pdf(self, path: str, run_context: RunContext | None = None):
        """检查当前工作区 PDF 的页数、页面尺寸、文本量和 SHA-256。

        Args:
            path: 要检查的工作区相对 PDF 路径。
        """
        return self.service.inspect_pdf(_thread(run_context), path)


class BaseToolkit(WorkspaceToolkit):
    def __init__(self, service: WorkspaceService):
        super().__init__(
            service,
            name="base",
            instructions=BASE_TOOLKIT_INSTRUCTIONS,
            add_instructions=True,
        )
        self._apply_parameter_constraints()

    def _apply_parameter_constraints(self) -> None:
        for function in {**self.functions, **self.async_functions}.values():
            function.process_entrypoint()
            schema = dict(function.parameters)
            schema["additionalProperties"] = False
            properties = {name: dict(value) for name, value in schema.get("properties", {}).items()}
            for name, constraints in BASE_TOOL_PARAMETER_CONSTRAINTS.get(function.name, {}).items():
                if name in properties:
                    properties[name].update(constraints)
            schema["properties"] = properties
            function.parameters = schema
            function.skip_entrypoint_processing = True

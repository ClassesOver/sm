import asyncio
import difflib
import hashlib
import json
import mimetypes
import shlex
import threading
import unicodedata
import uuid
from collections import OrderedDict
from collections.abc import Callable
from contextlib import aclosing, asynccontextmanager, contextmanager
from io import BytesIO
from pathlib import PurePosixPath
from typing import Any

from agno.db.base import AsyncBaseDb, BaseDb
from agno.media import Image
from agno.run import RunContext
from agno.tools.function import ToolResult
from daytona import (
    AsyncDaytona,
    CreateSandboxFromSnapshotParams,
    Daytona,
    ListSandboxesQuery,
)
from daytona.common.errors import DaytonaNotFoundError
from loguru import logger
from sqlalchemy import Column, DateTime, Integer, MetaData, String, Table, insert, select, update
from sqlalchemy.sql import func

from .async_utils import complete_cleanup
from .http.security import thread_label
from .runtime.database import AgentDatabase, create_agent_database
from .runtime.observability import suppress_expected_probe_tracing
from .sandbox.contracts import ExecRequest, RunPythonScriptRequest, WorkspaceBinding
from .sandbox.errors import SandboxNotFound, SandboxProviderError, SandboxTimeout
from .sandbox.python_runner import PythonScriptRunner
from .sandbox.registry import SandboxBindingRecord

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
MAX_PROCESS_INPUT_BYTES = 8 * 1024
MAX_BRANCH_FILES = 2000
MAX_BRANCH_TOTAL_BYTES = 256 * 1024 * 1024
MAX_BRANCH_FILE_BYTES = 200 * 1024 * 1024
MAX_INSPECT_PDF_PAGES = 200
MAX_SANDBOX_ID_CACHE_ENTRIES = 1024
WORKSPACE_CLEANUP_BATCH_SIZE = 20
WORKSPACE_CLEANUP_INTERVAL_SECONDS = 60
IMAGE_SUFFIXES = {".gif", ".jpeg", ".jpg", ".png", ".webp"}
MANAGED_PROCESS_PREFIX = "agent-exec-"


class WorkspaceError(ValueError):
    pass


class WorkspaceHashResultError(WorkspaceError):
    """远端哈希命令成功但返回的身份字段不符合协议。"""


class WorkspaceProcessNotFound(WorkspaceError):
    pass


class WorkspacePathConflict(WorkspaceError):
    pass


def _workspace_generation_table(metadata: MetaData) -> Table:
    return Table(
        "agent_workspace_generation",
        metadata,
        Column("thread_hash", String(64), primary_key=True),
        Column("generation", String(32), nullable=False),
        Column(
            "updated_at",
            DateTime(timezone=True),
            nullable=False,
            server_default=func.current_timestamp(),
        ),
    )


def _workspace_cleanup_table(metadata: MetaData) -> Table:
    return Table(
        "agent_workspace_cleanup",
        metadata,
        Column("workspace_label", String(64), primary_key=True),
        Column(
            "created_at",
            DateTime(timezone=True),
            nullable=False,
            server_default=func.current_timestamp(),
        ),
    )


def _workspace_generation_label(base_label: str, generation: str | None) -> str:
    if generation is None:
        return base_label
    return hashlib.sha256(f"{base_label}:{generation}".encode()).hexdigest()


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
        if resolved_database.db_engine.dialect.name != "postgresql":  # type: ignore[attr-defined]
            raise ValueError("工作区注册表只支持 PostgreSQL。")
        self.db: BaseDb = resolved_database
        schema = getattr(self.db, "db_schema", None)
        self.metadata = MetaData(schema=schema)
        self.table = Table(
            "agent_workspace_sandbox",
            self.metadata,
            Column("thread_hash", String(64), primary_key=True),
            Column("sandbox_id", String(256), nullable=False),
            Column("provider", String(32), nullable=False, server_default="daytona"),
            Column(
                "isolation",
                String(32),
                nullable=False,
                server_default="provider_managed",
            ),
            Column("node", String(256), nullable=True),
            Column("resource_id", String(256), nullable=False),
            Column("generation", Integer, nullable=False, server_default="1"),
            Column("dependency_bundle_digest", String(71), nullable=True),
            Column(
                "updated_at",
                DateTime(timezone=True),
                nullable=False,
                server_default=func.current_timestamp(),
            ),
        )
        self.generation_table = _workspace_generation_table(self.metadata)
        self.cleanup_table = _workspace_cleanup_table(self.metadata)
        self._initialized = False

    def _connect(self):
        return self.db.db_engine.connect()  # type: ignore[attr-defined,no-any-return]

    def ensure_initialized(self):
        if self._initialized:
            return
        with self._connect() as connection, connection.begin():
            if self.metadata.schema:
                connection.exec_driver_sql(f'CREATE SCHEMA IF NOT EXISTS "{self.metadata.schema}"')
            connection.exec_driver_sql(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                ("agent-workspace:initialize",),
            )
            self.metadata.create_all(connection)
            table_name = connection.dialect.identifier_preparer.format_table(self.table)
            # create_all 不会扩展既有表。迁移必须与 advisory lock 位于同一事务，
            # 否则多副本启动时可能观察到只增加了一部分字段的中间状态。
            for definition in (
                "provider VARCHAR(32)",
                "isolation VARCHAR(32)",
                "node VARCHAR(256)",
                "resource_id VARCHAR(256)",
                "generation INTEGER",
                "dependency_bundle_digest VARCHAR(71)",
            ):
                connection.exec_driver_sql(
                    f"ALTER TABLE {table_name} ADD COLUMN IF NOT EXISTS {definition}"
                )
            connection.exec_driver_sql(
                f"UPDATE {table_name} SET provider = COALESCE(provider, 'daytona'), "
                "isolation = COALESCE(isolation, 'provider_managed'), "
                "resource_id = COALESCE(resource_id, sandbox_id), "
                "generation = COALESCE(generation, 1)"
            )
            for column in ("provider", "isolation", "resource_id", "generation"):
                connection.exec_driver_sql(
                    f"ALTER TABLE {table_name} ALTER COLUMN {column} SET NOT NULL"
                )
        self.db.upsert_schema_version(self.table.name, "2.0.0")
        self._initialized = True

    def workspace_label(self, base_label: str) -> str:
        self.ensure_initialized()
        with self._connect() as connection:
            generation = connection.execute(
                select(self.generation_table.c.generation).where(
                    self.generation_table.c.thread_hash == base_label
                )
            ).scalar_one_or_none()
        return _workspace_generation_label(base_label, generation)

    @contextmanager
    def locked(self, value: str):
        self.ensure_initialized()
        with self._connect() as connection:
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
            .values(
                sandbox_id=sandbox_id,
                provider="daytona",
                isolation="provider_managed",
                resource_id=sandbox_id,
                generation=1,
                updated_at=func.current_timestamp(),
            )
            if exists
            else insert(self.table).values(
                thread_hash=value,
                sandbox_id=sandbox_id,
                provider="daytona",
                isolation="provider_managed",
                resource_id=sandbox_id,
                generation=1,
            )
        )
        self.connection.execute(statement)

    def get_binding(self, value: str) -> SandboxBindingRecord | None:
        row = self.connection.execute(
            select(
                self.table.c.provider,
                self.table.c.isolation,
                self.table.c.node,
                self.table.c.resource_id,
                self.table.c.generation,
                self.table.c.dependency_bundle_digest,
            ).where(self.table.c.thread_hash == value)
        ).first()
        if row is None:
            return None
        return SandboxBindingRecord(binding_digest=value, **row._mapping)

    def set_binding(self, record: SandboxBindingRecord) -> None:
        values = record.model_dump(mode="json", exclude={"binding_digest"})
        values["sandbox_id"] = record.resource_id
        values["updated_at"] = func.current_timestamp()
        exists = self.connection.execute(
            select(self.table.c.thread_hash).where(
                self.table.c.thread_hash == record.binding_digest
            )
        ).first()
        statement = (
            update(self.table)
            .where(self.table.c.thread_hash == record.binding_digest)
            .values(**values)
            if exists
            else insert(self.table).values(thread_hash=record.binding_digest, **values)
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
        if resolved_database.db_engine.dialect.name != "postgresql":  # type: ignore[attr-defined]
            raise ValueError("工作区注册表只支持 PostgreSQL。")
        self.db: AsyncBaseDb = resolved_database
        schema = getattr(self.db, "db_schema", None)
        self.metadata = MetaData(schema=schema)
        self.table = Table(
            "agent_workspace_sandbox",
            self.metadata,
            Column("thread_hash", String(64), primary_key=True),
            Column("sandbox_id", String(256), nullable=False),
            Column("provider", String(32), nullable=False, server_default="daytona"),
            Column(
                "isolation",
                String(32),
                nullable=False,
                server_default="provider_managed",
            ),
            Column("node", String(256), nullable=True),
            Column("resource_id", String(256), nullable=False),
            Column("generation", Integer, nullable=False, server_default="1"),
            Column("dependency_bundle_digest", String(71), nullable=True),
            Column(
                "updated_at",
                DateTime(timezone=True),
                nullable=False,
                server_default=func.current_timestamp(),
            ),
        )
        self.generation_table = _workspace_generation_table(self.metadata)
        self.cleanup_table = _workspace_cleanup_table(self.metadata)
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
                    if self.metadata.schema:
                        await connection.exec_driver_sql(
                            f'CREATE SCHEMA IF NOT EXISTS "{self.metadata.schema}"'
                        )
                    await connection.exec_driver_sql(
                        "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                        ("agent-workspace:initialize",),
                    )
                    await connection.run_sync(self.metadata.create_all)
                    table_name = connection.dialect.identifier_preparer.format_table(self.table)
                    for definition in (
                        "provider VARCHAR(32)",
                        "isolation VARCHAR(32)",
                        "node VARCHAR(256)",
                        "resource_id VARCHAR(256)",
                        "generation INTEGER",
                        "dependency_bundle_digest VARCHAR(71)",
                    ):
                        await connection.exec_driver_sql(
                            f"ALTER TABLE {table_name} ADD COLUMN IF NOT EXISTS {definition}"
                        )
                    await connection.exec_driver_sql(
                        f"UPDATE {table_name} SET provider = COALESCE(provider, 'daytona'), "
                        "isolation = COALESCE(isolation, 'provider_managed'), "
                        "resource_id = COALESCE(resource_id, sandbox_id), "
                        "generation = COALESCE(generation, 1)"
                    )
                    for column in ("provider", "isolation", "resource_id", "generation"):
                        await connection.exec_driver_sql(
                            f"ALTER TABLE {table_name} ALTER COLUMN {column} SET NOT NULL"
                        )
            await self.db.upsert_schema_version(self.table.name, "2.0.0")
            self._initialized = True

    async def workspace_label(self, base_label: str) -> str:
        await self.ensure_initialized()
        async with self._connect() as connection:
            generation = (
                await connection.execute(
                    select(self.generation_table.c.generation).where(
                        self.generation_table.c.thread_hash == base_label
                    )
                )
            ).scalar_one_or_none()
        return _workspace_generation_label(base_label, generation)

    async def quarantine_workspace(self, base_label: str) -> str:
        await self.ensure_initialized()
        async with self._connect() as connection:
            async with connection.begin():
                await connection.exec_driver_sql(
                    "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                    (f"agent-workspace-generation:{base_label}",),
                )
                generation = (
                    await connection.execute(
                        select(self.generation_table.c.generation).where(
                            self.generation_table.c.thread_hash == base_label
                        )
                    )
                ).scalar_one_or_none()
                old_label = _workspace_generation_label(base_label, generation)
                cleanup_exists = (
                    await connection.execute(
                        select(self.cleanup_table.c.workspace_label).where(
                            self.cleanup_table.c.workspace_label == old_label
                        )
                    )
                ).first()
                if cleanup_exists is None:
                    await connection.execute(
                        insert(self.cleanup_table).values(workspace_label=old_label)
                    )
                next_generation = uuid.uuid4().hex
                generation_exists = (
                    await connection.execute(
                        select(self.generation_table.c.thread_hash).where(
                            self.generation_table.c.thread_hash == base_label
                        )
                    )
                ).first()
                statement = (
                    update(self.generation_table)
                    .where(self.generation_table.c.thread_hash == base_label)
                    .values(
                        generation=next_generation,
                        updated_at=func.current_timestamp(),
                    )
                    if generation_exists is not None
                    else insert(self.generation_table).values(
                        thread_hash=base_label,
                        generation=next_generation,
                    )
                )
                await connection.execute(statement)
                await connection.execute(
                    self.table.delete().where(self.table.c.thread_hash == old_label)
                )
        return old_label

    async def pending_cleanup_labels(
        self, limit: int = WORKSPACE_CLEANUP_BATCH_SIZE
    ) -> tuple[str, ...]:
        await self.ensure_initialized()
        async with self._connect() as connection:
            rows = (
                await connection.execute(
                    select(self.cleanup_table.c.workspace_label)
                    .order_by(self.cleanup_table.c.created_at)
                    .limit(limit)
                )
            ).all()
        return tuple(str(row[0]) for row in rows)

    async def complete_cleanup(self, workspace_label: str) -> None:
        await self.ensure_initialized()
        async with self._connect() as connection:
            async with connection.begin():
                await connection.execute(
                    self.cleanup_table.delete().where(
                        self.cleanup_table.c.workspace_label == workspace_label
                    )
                )

    @asynccontextmanager
    async def locked(self, value: str):
        await self.ensure_initialized()
        async with self._connect() as connection:
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
            .values(
                sandbox_id=sandbox_id,
                provider="daytona",
                isolation="provider_managed",
                resource_id=sandbox_id,
                generation=1,
                updated_at=func.current_timestamp(),
            )
            if exists
            else insert(self.table).values(
                thread_hash=value,
                sandbox_id=sandbox_id,
                provider="daytona",
                isolation="provider_managed",
                resource_id=sandbox_id,
                generation=1,
            )
        )
        await self.connection.execute(statement)

    async def get_binding(self, value: str) -> SandboxBindingRecord | None:
        row = (
            await self.connection.execute(
                select(
                    self.table.c.provider,
                    self.table.c.isolation,
                    self.table.c.node,
                    self.table.c.resource_id,
                    self.table.c.generation,
                    self.table.c.dependency_bundle_digest,
                ).where(self.table.c.thread_hash == value)
            )
        ).first()
        if row is None:
            return None
        return SandboxBindingRecord(binding_digest=value, **row._mapping)

    async def set_binding(self, record: SandboxBindingRecord) -> None:
        values = record.model_dump(mode="json", exclude={"binding_digest"})
        values["sandbox_id"] = record.resource_id
        values["updated_at"] = func.current_timestamp()
        exists = (
            await self.connection.execute(
                select(self.table.c.thread_hash).where(
                    self.table.c.thread_hash == record.binding_digest
                )
            )
        ).first()
        statement = (
            update(self.table)
            .where(self.table.c.thread_hash == record.binding_digest)
            .values(**values)
            if exists
            else insert(self.table).values(thread_hash=record.binding_digest, **values)
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
        provider: Any | None = None,
    ):
        self.secret = secret
        self.snapshot = snapshot
        self.network_allow_list = network_allow_list
        self._provider = provider
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
        if self._provider is not None:
            yield None
            return
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
        if self._provider is not None:
            yield None
            return
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
        if self._provider is not None:
            await self._provider.aclose()
            return
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

    async def check_sandbox_service(self) -> None:
        """通过只读列表请求验证 Daytona Sandbox API 可访问。"""

        if self._provider is not None:
            health = await self._provider.health_check()
            if not health.healthy:
                raise WorkspaceError("sandbox provider 健康检查失败。")
            return

        async with self._async_client() as client:
            # Daytona.list 返回异步生成器；提前取得首项后必须显式关闭，避免分页响应
            # 和底层连接等待垃圾回收才释放。
            async with aclosing(client.list(ListSandboxesQuery(limit=1))) as sandboxes:
                async for _sandbox in sandboxes:
                    break

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

    def _base_hash(self, thread: str) -> str:
        return thread_label(thread, self.secret)

    def _hash(self, thread: str) -> str:
        base_label = self._base_hash(thread)
        resolver = getattr(self.registry, "workspace_label", None)
        return str(resolver(base_label)) if callable(resolver) else base_label

    async def _ahash(self, thread: str) -> str:
        base_label = self._base_hash(thread)
        resolver = getattr(self.async_registry, "workspace_label", None)
        return str(await resolver(base_label)) if callable(resolver) else base_label

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
        if self._provider is not None:
            if not create:
                binding = self._provider_binding(thread)
                matches = await self._provider.list_workspaces(binding)
                if not matches:
                    return None
                if len(matches) != 1:
                    raise WorkspaceError("当前对话关联了多个运行环境，请联系管理员清理后重试。")
                return await self._provider.get_workspace(matches[0].ref, binding)
            try:
                return await self._provider.ensure_workspace(self._provider_binding(thread))
            except SandboxTimeout as error:
                raise WorkspaceError("工作区服务超时，请稍后重试。") from error
            except SandboxProviderError as error:
                raise WorkspaceError(f"工作区服务失败：{error.message}") from error
        value = await self._ahash(thread)
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
        try:
            return await self._aready_sandbox(client, sandbox)
        except DaytonaNotFoundError:
            # Daytona 资源可能在查找成功后才被回收；清除旧绑定并只重建一次，
            # 让长任务下一次工具调用继续使用同一 thread 的新工作区。
            self._invalidate_sandbox_id(value, getattr(sandbox, "id", None))
            async with self.async_registry.locked(value) as registry:
                await registry.delete(value)
            if not create:
                return None
            replacement = await client.create(
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
            async with self.async_registry.locked(value) as registry:
                await registry.set(value, replacement.id)
            self._cache_sandbox_id(value, replacement.id)
            return await self._aready_sandbox(client, replacement)

    async def _adestroy(self, client: Any, thread: str) -> bool:
        value = await self._ahash(thread)
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
        if self._provider is not None:
            binding = self._provider_binding(thread)
            matches = await self._provider.list_workspaces(binding)
            deleted = False
            for summary in matches:
                result = await self._provider.destroy_workspace(summary.ref, binding)
                deleted = result.deleted or deleted
            return deleted
        async with self._async_client() as client:
            return await self._adestroy(client, thread)

    def _provider_binding(self, thread: str) -> WorkspaceBinding:
        # WorkspaceService 的调用方已经在 HTTP/Workflow 边界完成用户、公司和 thread
        # 所有权校验；此处只把不含明文身份的 thread scope 固化为 Provider 绑定。
        # 三个 scope 字段使用不同域分隔摘要，避免它们被误当成可互换标识。
        base = self._base_hash(thread)

        def scoped(name: str) -> str:
            return hashlib.sha256(f"{name}:{base}".encode()).hexdigest()

        return WorkspaceBinding(
            tenant_id=scoped("tenant"),
            user_id=scoped("user"),
            company_id=scoped("company"),
            thread_id=thread,
            idempotency_key=scoped("workspace"),
            profile=getattr(getattr(self._provider, "_config", None), "profile", None),
        )

    async def aquarantine(self, thread: str) -> str:
        """隔离当前 workspace generation，使后续请求无法复用旧 sandbox。"""

        base_label = self._base_hash(thread)
        quarantine = getattr(self.async_registry, "quarantine_workspace", None)
        if not callable(quarantine):
            raise WorkspaceError("工作区注册表不支持隔离失败运行环境。")
        old_label = str(await quarantine(base_label))
        self._invalidate_sandbox_id(old_label)
        logger.warning("workspace_sandbox_quarantined workspace_label={}", old_label)
        return old_label

    async def acleanup_quarantined(self, *, limit: int = WORKSPACE_CLEANUP_BATCH_SIZE) -> int:
        pending = getattr(self.async_registry, "pending_cleanup_labels", None)
        complete = getattr(self.async_registry, "complete_cleanup", None)
        if not callable(pending) or not callable(complete):
            return 0
        labels = await pending(limit)
        completed = 0
        async with self._async_client() as client:
            for workspace_label in labels:
                try:
                    sandboxes = [
                        sandbox
                        async for sandbox in client.list(
                            ListSandboxesQuery(labels={"agent-thread": workspace_label})
                        )
                    ]
                    for sandbox in sandboxes:
                        try:
                            await client.delete(sandbox)
                        except DaytonaNotFoundError:
                            pass
                except Exception as error:
                    logger.warning(
                        "workspace_quarantine_cleanup_failed workspace_label={} error_type={}",
                        workspace_label,
                        type(error).__name__,
                    )
                    continue
                await complete(workspace_label)
                completed += 1
                logger.debug(
                    "workspace_quarantine_cleanup_completed workspace_label={} sandbox_count={}",
                    workspace_label,
                    len(sandboxes),
                )
        return completed

    async def run_quarantine_cleanup_loop(self) -> None:
        while True:
            try:
                await self.acleanup_quarantined()
            except asyncio.CancelledError:
                raise
            except Exception as error:
                logger.warning(
                    "workspace_quarantine_cleanup_batch_failed error_type={}",
                    type(error).__name__,
                )
            await asyncio.sleep(WORKSPACE_CLEANUP_INTERVAL_SECONDS)

    async def run_provider_reconcile_loop(self) -> None:
        reconcile = getattr(self._provider, "run_reconcile_loop", None)
        if callable(reconcile):
            await reconcile()

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
            except (DaytonaNotFoundError, SandboxNotFound) as error:
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
            except (DaytonaNotFoundError, SandboxNotFound) as error:
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
            except (DaytonaNotFoundError, SandboxNotFound):
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
            except (DaytonaNotFoundError, SandboxNotFound):
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
            except (DaytonaNotFoundError, SandboxNotFound):
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
            except (DaytonaNotFoundError, SandboxNotFound):
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
                    "modifiedAt": getattr(entry, "modified_at", None)
                    or getattr(entry, "mod_time", None),
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

    async def _astore_file(
        self, thread: str, path: str, content: bytes, mode: str
    ) -> dict[str, Any]:
        self._validate_content(content)
        relative, remote = self.normalize_path(path, allow_root=False)
        async with self._async_client() as client:
            sandbox = await self._asandbox_for(client, thread)
            await self._aensure_directory(sandbox, remote.rsplit("/", 1)[0])
            try:
                info = await self._ainfo(sandbox, remote)
            except (DaytonaNotFoundError, SandboxNotFound):
                info = None
            if mode == "create" and info is not None:
                raise WorkspacePathConflict(
                    f"文件“{relative}”已经存在。如需覆盖，请使用覆盖文件工具并确认。"
                )
            if info is not None and (info.is_dir or not self._is_regular_file(info)):
                raise WorkspaceError("目标路径不是普通文件，请更换文件路径后重试。")
            await sandbox.fs.upload_file(content, remote)
        return {"path": relative, "size": len(content), "status": "synced"}

    async def aupload(self, thread: str, path: str, content: bytes) -> dict[str, Any]:
        return await self._astore_file(thread, path, content, "upload")

    async def acreate_file_locked(self, thread: str, path: str, content: bytes) -> dict[str, Any]:
        relative, _remote = self.normalize_path(path, allow_root=False)
        lock_key = f"agent-workspace-file:{await self._ahash(thread)}:{relative}"
        async with self.async_registry.locked(lock_key):
            return await self._astore_file(thread, relative, content, "create")

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

    async def afile_bytes(self, thread: str, path: str) -> tuple[bytes, str]:
        relative, remote = self.normalize_path(path, allow_root=False)
        async with self._async_client() as client:
            sandbox = await self._asandbox_for(client, thread)
            await self._avalidate_existing_path(sandbox, relative)
            info = await self._ainfo(sandbox, remote)
            if info.is_dir:
                raise WorkspaceError("所选项目是目录，不能作为文件下载，请选择普通文件。")
            if int(info.size or 0) > MAX_DOWNLOAD_BYTES:
                raise WorkspaceError("所选文件超过 200 MiB，请缩小文件后重试。")
            content = await self._adownload_file(sandbox, remote, MAX_DOWNLOAD_BYTES)
        return content, mimetypes.guess_type(relative)[0] or "application/octet-stream"

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

    async def _aread_text_from_sandbox(self, sandbox: Any, relative: str, remote: str) -> str:
        await self._avalidate_existing_path(sandbox, relative)
        info = await self._ainfo(sandbox, remote)
        if info.is_dir:
            raise WorkspaceError("所选项目是目录，不能作为文本文件读取。")
        if int(info.size or 0) > MAX_READ_BYTES:
            raise WorkspaceError("所选文件超过 1 MB，请下载后使用对应软件打开。")
        content = await self._adownload_file(sandbox, remote, MAX_READ_BYTES)
        if b"\x00" in content:
            raise WorkspaceError("该文件包含二进制内容，请下载后使用对应软件打开。")
        try:
            return content.decode("utf-8")
        except UnicodeDecodeError as error:
            raise WorkspaceError("该文件不是 UTF-8 文本，请下载后使用对应软件打开。") from error

    async def aread_text(self, thread: str, path: str) -> str:
        relative, remote = self.normalize_path(path, allow_root=False)
        async with self._async_client() as client:
            sandbox = await self._asandbox_for(client, thread)
            return await self._aread_text_from_sandbox(sandbox, relative, remote)

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
            command = self._rg_command(arguments)
            if self._provider is not None:
                value = await sandbox.process.exec(
                    ExecRequest(command=command, timeout=MAX_EXECUTION_TIMEOUT)
                )
            else:
                value = await sandbox.process.exec(
                    command,
                    cwd=WORKSPACE_ROOT,
                    timeout=MAX_EXECUTION_TIMEOUT,
                )

        exit_code = getattr(value, "exit_code", None)
        raw_value = getattr(value, "result", "") or getattr(value, "stdout", "")
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
            if self._provider is not None:
                value = await sandbox.process.exec(
                    ExecRequest(command=command, timeout=MAX_EXECUTION_TIMEOUT)
                )
            else:
                value = await sandbox.process.exec(
                    command,
                    cwd=WORKSPACE_ROOT,
                    timeout=MAX_EXECUTION_TIMEOUT,
                )

        exit_code = getattr(value, "exit_code", None)
        raw_output = getattr(value, "result", "")
        if not raw_output:
            artifacts = getattr(value, "artifacts", None)
            raw_output = getattr(artifacts, "stdout", "") if artifacts is not None else ""
        if not raw_output:
            raw_output = getattr(value, "stdout", "") or getattr(value, "output", "")
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
        if self._provider is not None:
            async with self._async_client() as client:
                sandbox = await self._asandbox_for(client, thread)
                try:
                    await self._avalidate_existing_path(sandbox, relative)
                    info = await self._ainfo(sandbox, remote)
                    if not self._is_regular_file(info):
                        raise WorkspaceError("工作区路径不是普通文件。")
                    content = await self._adownload_file(sandbox, remote, MAX_DOWNLOAD_BYTES)
                except SandboxNotFound as error:
                    raise WorkspaceError("工作区路径不存在，请检查名称后重试。") from error
            return {
                "path": relative,
                "size": len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
            }
        quoted = shlex.quote(remote)
        script = (
            f"digest=$(sha256sum -- {quoted}) || exit $?; digest=${{digest%% *}}; "
            f"size=$(stat --format=%s -- {quoted}) || exit $?; "
            'printf \'{"sha256":"%s","size":%s}\n\' "$digest" "$size"'
        )
        output, _truncated = await self._arun_workspace_command(
            thread,
            relative,
            remote,
            self._shell_command(script),
            expected_type="file",
            failure_message="工作区文件哈希计算失败，请检查文件后重试。",
        )
        digest: Any
        raw_size: Any
        try:
            payload = json.loads(output)
            if (
                not isinstance(payload, dict)
                or set(payload) != {"sha256", "size"}
                or isinstance(payload.get("size"), bool)
                or not isinstance(payload.get("size"), int)
            ):
                raise ValueError
            digest = payload["sha256"]
            raw_size = payload["size"]
        except (TypeError, ValueError, json.JSONDecodeError):
            # 兼容旧版 Snapshot 仍返回的 NUL 分隔回执；新命令不再依赖该格式，
            # 因为部分 Daytona 工具链会在传输过程中改写或截断 NUL 字节。
            try:
                digest, raw_size = self._parse_null_fields(
                    output, 2, "工作区文件哈希结果无效，请稍后重试。"
                )
            except WorkspaceError as error:
                raise WorkspaceHashResultError(str(error)) from error
        if (
            not isinstance(digest, str)
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
        ):
            raise WorkspaceHashResultError("工作区文件哈希结果无效，请稍后重试。")
        try:
            size = int(raw_size)
        except ValueError as error:
            raise WorkspaceHashResultError("工作区文件哈希结果无效，请稍后重试。") from error
        return {"path": relative, "size": size, "sha256": digest}

    async def arun_python_script(
        self, thread: str, script_path: str, *, timeout: int = MAX_EXECUTION_TIMEOUT
    ) -> dict[str, Any]:
        relative, remote = self.normalize_path(script_path, allow_root=False)
        if PurePosixPath(relative).suffix.lower() != ".py":
            raise WorkspaceError("Python runner 只接受 .py 脚本。")
        execution_timeout = self._validate_timeout(timeout, MAX_BACKGROUND_EXECUTION_TIMEOUT)
        async with self._async_client() as client:
            sandbox = await self._asandbox_for(client, thread)
            await self._avalidate_existing_path(sandbox, relative)
            info = await self._ainfo(sandbox, remote)
            if not self._is_regular_file(info) or int(info.size or 0) > MAX_UPLOAD_BYTES:
                raise WorkspaceError("Python 脚本不是允许大小的普通文件。")
            content = await self._adownload_file(sandbox, remote, MAX_UPLOAD_BYTES)
            try:
                script = content.decode("utf-8")
            except UnicodeDecodeError as error:
                raise WorkspaceError("Python 脚本必须使用 UTF-8 编码。") from error
            result = await PythonScriptRunner(sandbox.execution).run(
                RunPythonScriptRequest(
                    script=script,
                    cwd="",
                    timeout_ms=execution_timeout * 1000,
                    output_limit_bytes=MAX_TOOL_OUTPUT_BYTES,
                )
            )
        output = result.stdout
        if result.stderr:
            output += ("\n" if output else "") + result.stderr
        return {
            "ok": result.exit_code == 0,
            "status": "completed",
            "exitCode": result.exit_code,
            "output": output,
            "scriptPath": relative,
            "scriptSha256": result.script_hash,
            "dependencyBundleDigest": result.dependency_bundle_digest,
        }

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

    async def _ainspect_destination_without_writes(self, sandbox: Any, relative: str):
        parts = relative.split("/")
        info = None
        for index in range(1, len(parts) + 1):
            remote = f"{WORKSPACE_ROOT}/{'/'.join(parts[:index])}"
            try:
                with suppress_expected_probe_tracing():
                    info = await self._ainfo(sandbox, remote)
            except (DaytonaNotFoundError, SandboxNotFound):
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

    async def aapply_changes(self, thread: str, changes: list[dict[str, Any]]) -> dict[str, Any]:
        if not isinstance(changes, list) or not 1 <= len(changes) <= MAX_PATCH_FILES:
            raise WorkspaceError(f"变更集必须包含 1 至 {MAX_PATCH_FILES} 个文件操作。")

        keys_by_operation = {
            "create": {"operation", "path", "content"},
            "update": {"operation", "path", "content", "expected_sha256"},
            "delete": {"operation", "path", "expected_sha256"},
            "move": {"operation", "path", "destination", "expected_sha256"},
        }
        lock_key = f"agent-workspace-changes:{await self._ahash(thread)}"
        async with self.async_registry.locked(lock_key):
            async with self._async_client() as client:
                sandbox = await self._asandbox_for(client, thread)
                prepared: list[dict[str, Any]] = []
                used_paths: set[str] = set()
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
                    occupied_paths = [relative]
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
                        occupied_paths.append(destination)
                    if any(path in used_paths for path in occupied_paths):
                        raise WorkspaceError("变更集不能重复使用同一个源路径或目标路径。")
                    used_paths.update(occupied_paths)

                    if operation == "create":
                        content = change["content"]
                        if not isinstance(content, str):
                            raise WorkspaceError("新建文件内容必须是 UTF-8 文本。")
                        updated = content.encode("utf-8")
                        self._validate_content(updated)
                        if (
                            await self._ainspect_destination_without_writes(sandbox, relative)
                            is not None
                        ):
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

                    await self._avalidate_existing_path(sandbox, relative)
                    info = await self._ainfo(sandbox, remote)
                    if not self._is_regular_file(info):
                        raise WorkspaceError("变更集只能更新、删除或移动普通文件。")
                    original = await self._adownload_file(sandbox, remote, MAX_DOWNLOAD_BYTES)
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
                        if (
                            await self._ainspect_destination_without_writes(sandbox, destination)
                            is not None
                        ):
                            raise WorkspacePathConflict(
                                f"移动目标“{destination}”已经存在，请更换路径后重试。"
                            )
                        item["destination"] = destination
                        item["destination_remote"] = destination_remote
                    prepared.append(item)

                # 所有路径和内容身份必须在首次写入前完成校验；执行失败时按逆序恢复，
                # 保持 Reporting 一次补丁要么整体可见、要么回到原状态的不变量。
                completed: list[dict[str, Any]] = []
                try:
                    for item in prepared:
                        operation = item["operation"]
                        if operation in {"create", "update"}:
                            await self._aensure_directory(sandbox, item["remote"].rsplit("/", 1)[0])
                            await sandbox.fs.upload_file(item["updated"], item["remote"])
                        elif operation == "delete":
                            await sandbox.fs.delete_file(item["remote"], recursive=False)
                        else:
                            await self._aensure_directory(
                                sandbox, item["destination_remote"].rsplit("/", 1)[0]
                            )
                            await sandbox.fs.move_files(item["remote"], item["destination_remote"])
                        completed.append(item)

                        if operation in {"create", "update"}:
                            persisted = await self._adownload_file(
                                sandbox, item["remote"], MAX_UPLOAD_BYTES
                            )
                            if persisted != item["updated"]:
                                raise WorkspaceError("变更集落盘校验失败，请重新检查目标文件。")
                        elif operation == "move":
                            persisted = await self._adownload_file(
                                sandbox, item["destination_remote"], MAX_UPLOAD_BYTES
                            )
                            if persisted != item["original"]:
                                raise WorkspaceError("变更集移动校验失败，请重新检查目标文件。")
                except Exception as error:
                    rollback_failed = False
                    for item in reversed(completed):
                        try:
                            operation = item["operation"]
                            if operation == "create":
                                await sandbox.fs.delete_file(item["remote"], recursive=False)
                            elif operation == "update":
                                await sandbox.fs.upload_file(item["original"], item["remote"])
                            elif operation == "delete":
                                await self._aensure_directory(
                                    sandbox, item["remote"].rsplit("/", 1)[0]
                                )
                                await sandbox.fs.upload_file(item["original"], item["remote"])
                            else:
                                await self._aensure_directory(
                                    sandbox, item["remote"].rsplit("/", 1)[0]
                                )
                                await sandbox.fs.move_files(
                                    item["destination_remote"], item["remote"]
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
        content, mime_type = self.file_bytes(thread, relative)
        return self._image_result(relative, content, mime_type)

    async def aview_image(self, thread: str, path: str) -> ToolResult:
        relative = self.normalize_path(path, allow_root=False)[0]
        content, mime_type = await self.afile_bytes(thread, relative)
        return self._image_result(relative, content, mime_type)

    @staticmethod
    def _image_result(relative: str, content: bytes, mime_type: str) -> ToolResult:
        suffix = PurePosixPath(relative).suffix.lower()
        if suffix not in IMAGE_SUFFIXES:
            raise WorkspaceError("仅支持 PNG、JPEG、GIF 或 WebP 图片。")
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

    async def adelete_file(self, thread: str, path: str, recursive: bool = False) -> None:
        relative, remote = self.normalize_path(path, allow_root=False)
        async with self._async_client() as client:
            sandbox = await self._asandbox_for(client, thread)
            await self._avalidate_existing_path(sandbox, relative)
            info = await self._ainfo(sandbox, remote)
            if info.is_dir and not recursive:
                raise WorkspaceError("所选项目是目录；如需删除，请启用递归删除并重新确认。")
            await sandbox.fs.delete_file(remote, recursive=recursive)

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

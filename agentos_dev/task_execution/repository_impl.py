from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from agno.db.base import AsyncBaseDb
from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
    and_,
    delete,
    exists,
    func,
    insert,
    or_,
    select,
    text,
    update,
)
from sqlalchemy.exc import IntegrityError

from .acceptance import AcceptanceContractError, normalize_acceptance_contract
from .models import (
    AttemptOutcome,
    AttemptSnapshot,
    AttemptState,
    CodingScope,
    InstructionReceipt,
    InstructionState,
    Lease,
    TaskSnapshot,
    TaskState,
)

TASK_SCHEMA_VERSION = "2.1.0"
CODING_DB_SCHEMA = "agentos_coding"
MAX_CONTINUATIONS = 20
MAX_TERMINAL_OUTPUT_BYTES = 64 * 1024
MAX_INSTRUCTION_ID_LENGTH = 128
MAX_INSTRUCTION_BYTES = 32 * 1024
MAX_PENDING_INSTRUCTIONS = 50
MAX_PENDING_INSTRUCTION_BYTES = 256 * 1024
TASK_RETENTION = timedelta(days=7)
TERMINAL_TASK_STATUSES = frozenset({"completed", "failed", "cancelled", "lost", "terminated"})
ACTIVE_TASK_STATUSES = frozenset({"pending", "running", "suspended"})
TERMINAL_EXECUTION_STATUSES = frozenset({"completed", "failed", "cancelled", "lost", "terminated"})


class CodingRepositoryError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def utcnow() -> datetime:
    return datetime.now(UTC)


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def bounded_output(value: Any) -> str:
    encoded = str(value or "").encode("utf-8", errors="replace")
    if len(encoded) <= MAX_TERMINAL_OUTPUT_BYTES:
        return encoded.decode("utf-8", errors="replace")
    return encoded[-MAX_TERMINAL_OUTPUT_BYTES:].decode("utf-8", errors="ignore")


def error_fingerprint(value: BaseException | str) -> str:
    text = str(value).strip().lower()
    normalized = " ".join(text.split())[:4096]
    return hashlib.sha256(normalized.encode("utf-8", errors="replace")).hexdigest()


@dataclass(frozen=True)
class CodingTask:
    external_run_id: str
    current_internal_run_id: str | None
    owner_user_id: str
    thread_id: str
    agent_id: str
    sandbox_id: str
    status: str
    continuation_count: int
    same_error_count: int
    error_fingerprint: str | None
    deadline_at: datetime
    mutation_sequence: int
    acceptance_contract: dict[str, Any] | None
    finish_payload: dict[str, Any] | None
    result_text: str | None


@dataclass(frozen=True)
class CodingExecution:
    execution_id: str
    external_run_id: str
    internal_run_id: str
    owner_user_id: str
    thread_id: str
    sandbox_id: str
    daytona_session_id: str
    command_id: str | None
    status: str
    output_cursor: int
    terminal_output: str
    exit_code: int | None
    mutation_sequence: int
    is_verification: bool
    retained_service: bool
    kind: str = "terminal"
    attempt_no: int = 0
    lease_epoch: int = 0
    operation_receipt: dict[str, Any] | None = None


def _task_from_row(row: Any) -> CodingTask:
    value = row._mapping
    return CodingTask(
        external_run_id=value["external_run_id"],
        current_internal_run_id=value["current_internal_run_id"],
        owner_user_id=value["owner_user_id"],
        thread_id=value["thread_id"],
        agent_id=value["agent_id"],
        sandbox_id=value["sandbox_id"],
        status=value["status"],
        continuation_count=value["continuation_count"],
        same_error_count=value["same_error_count"],
        error_fingerprint=value["error_fingerprint"],
        deadline_at=_as_utc(value["deadline_at"]),
        mutation_sequence=value["mutation_sequence"],
        acceptance_contract=value["acceptance_contract"],
        finish_payload=value["finish_payload"],
        result_text=value["result_text"],
    )


def _execution_from_row(row: Any) -> CodingExecution:
    value = row._mapping
    return CodingExecution(
        execution_id=value["execution_id"],
        external_run_id=value["external_run_id"],
        internal_run_id=value["internal_run_id"],
        owner_user_id=value["owner_user_id"],
        thread_id=value["thread_id"],
        sandbox_id=value["sandbox_id"],
        daytona_session_id=value["daytona_session_id"],
        command_id=value["command_id"],
        status=value["status"],
        output_cursor=value["output_cursor"],
        terminal_output=value["terminal_output"],
        exit_code=value["exit_code"],
        mutation_sequence=value["mutation_sequence"],
        is_verification=value["is_verification"],
        retained_service=value["retained_service"],
        kind=value["kind"],
        attempt_no=int(value["attempt_no"] or 0),
        lease_epoch=int(value["lease_epoch"] or 0),
        operation_receipt=value["operation_receipt"],
    )


class CodingTaskRepository:
    def __init__(self, db: AsyncBaseDb):
        self.db = db
        dialect = db.db_engine.dialect.name  # type: ignore[attr-defined]
        schema = CODING_DB_SCHEMA if dialect == "postgresql" else None
        self._legacy_schema = getattr(db, "db_schema", None) if schema else None
        self.metadata = MetaData(schema=schema)
        self.schema_versions = Table(
            "agentos_coding_schema_versions",
            self.metadata,
            Column("component", String(128), primary_key=True),
            Column("version", String(32), nullable=False),
            Column("updated_at", DateTime(timezone=True), nullable=False),
        )
        self.tasks = Table(
            "agentos_coding_tasks",
            self.metadata,
            Column("external_run_id", String(128), primary_key=True),
            Column("current_internal_run_id", String(128)),
            Column("owner_user_id", String(256), nullable=False),
            Column("thread_id", String(256), nullable=False),
            Column("agent_id", String(128), nullable=False),
            Column("sandbox_id", String(256), nullable=False),
            Column("status", String(32), nullable=False),
            Column("state_version", BigInteger, nullable=False, default=0),
            Column("lease_epoch", BigInteger, nullable=False, default=0),
            Column("instruction_sequence", BigInteger, nullable=False, default=0),
            Column("continuation_count", Integer, nullable=False, default=0),
            Column("same_error_count", Integer, nullable=False, default=0),
            Column("error_fingerprint", String(64)),
            Column("deadline_at", DateTime(timezone=True), nullable=False),
            Column("lease_owner", String(128)),
            Column("lease_expires_at", DateTime(timezone=True)),
            Column("mutation_sequence", BigInteger, nullable=False, default=0),
            Column("acceptance_contract", JSON),
            Column("finish_payload", JSON),
            Column("finish_receipt", JSON),
            Column("result_text", Text),
            Column(
                "predecessor_task_id",
                String(128),
                ForeignKey("agentos_coding_tasks.external_run_id", ondelete="SET NULL"),
            ),
            Column("created_at", DateTime(timezone=True), nullable=False),
            Column("updated_at", DateTime(timezone=True), nullable=False, default=utcnow),
            Column("completed_at", DateTime(timezone=True)),
            Index("ix_agentos_coding_tasks_owner", "owner_user_id", "thread_id"),
            Index("ix_agentos_coding_tasks_cleanup", "status", "completed_at"),
        )
        task_reference = self.tasks.c.external_run_id
        self.runs = Table(
            "agentos_coding_task_runs",
            self.metadata,
            Column("internal_run_id", String(128), primary_key=True),
            Column(
                "external_run_id",
                String(128),
                ForeignKey(task_reference, ondelete="CASCADE"),
                nullable=False,
            ),
            Column("continuation_index", Integer, nullable=False),
            Column("status", String(32), nullable=False),
            Column("resume_count", Integer, nullable=False, default=0),
            Column("outcome", String(32)),
            Column("agno_status", String(32)),
            Column("lease_epoch", BigInteger, nullable=False, default=0),
            Column("error_fingerprint", String(64)),
            Column("terminal_output", Text),
            Column("created_at", DateTime(timezone=True), nullable=False),
            Column("updated_at", DateTime(timezone=True), nullable=False, default=utcnow),
            Column("completed_at", DateTime(timezone=True)),
            Index("ix_agentos_coding_task_runs_external", "external_run_id"),
            UniqueConstraint(
                "external_run_id",
                "continuation_index",
                name="uq_agentos_coding_task_runs_attempt",
            ),
        )
        self.executions = Table(
            "agentos_coding_executions",
            self.metadata,
            Column("execution_id", String(64), primary_key=True),
            Column(
                "external_run_id",
                String(128),
                ForeignKey(task_reference, ondelete="CASCADE"),
                nullable=False,
            ),
            Column("internal_run_id", String(128), nullable=False),
            Column("owner_user_id", String(256), nullable=False),
            Column("thread_id", String(256), nullable=False),
            Column("sandbox_id", String(256), nullable=False),
            Column("daytona_session_id", String(128), nullable=False, unique=True),
            Column("command_id", String(128)),
            Column("status", String(32), nullable=False),
            Column("kind", String(32), nullable=False, default="terminal"),
            Column("attempt_no", Integer, nullable=False, default=0),
            Column("lease_epoch", BigInteger, nullable=False, default=0),
            Column("operation_receipt", JSON),
            Column("output_cursor", BigInteger, nullable=False, default=0),
            Column("terminal_output", Text, nullable=False, default=""),
            Column("exit_code", Integer),
            Column("mutation_sequence", BigInteger, nullable=False),
            Column("is_verification", Boolean, nullable=False, default=False),
            Column("retained_service", Boolean, nullable=False, default=False),
            Column("created_at", DateTime(timezone=True), nullable=False),
            Column("updated_at", DateTime(timezone=True), nullable=False),
            Column("completed_at", DateTime(timezone=True)),
            Index(
                "ix_agentos_coding_executions_scope",
                "external_run_id",
                "owner_user_id",
                "thread_id",
            ),
            Index("ix_agentos_coding_executions_cleanup", "status", "completed_at"),
        )
        self.instructions = Table(
            "agentos_coding_task_instructions",
            self.metadata,
            Column("external_run_id", String(128), nullable=False),
            Column("instruction_id", String(128), nullable=False),
            Column("sequence", BigInteger, nullable=False),
            Column("content", Text, nullable=False),
            Column("content_hash", String(64), nullable=False),
            Column("content_bytes", Integer, nullable=False),
            Column("status", String(32), nullable=False),
            Column("rejection_code", String(64)),
            Column("applied_attempt_no", Integer),
            Column("created_at", DateTime(timezone=True), nullable=False),
            Column("updated_at", DateTime(timezone=True), nullable=False),
            ForeignKeyConstraint(
                ["external_run_id"],
                ["agentos_coding_tasks.external_run_id"],
                ondelete="CASCADE",
            ),
            UniqueConstraint(
                "external_run_id",
                "instruction_id",
                name="pk_agentos_coding_task_instructions",
            ),
            UniqueConstraint(
                "external_run_id",
                "sequence",
                name="uq_agentos_coding_task_instructions_sequence",
            ),
            Index(
                "ix_agentos_coding_task_instructions_pending",
                "external_run_id",
                "status",
                "sequence",
            ),
        )
        self._initialized = False
        shared_lock = getattr(db, "_agentos_coding_initialize_lock", None)
        if shared_lock is None:
            shared_lock = asyncio.Lock()
            setattr(db, "_agentos_coding_initialize_lock", shared_lock)
        self._initialize_lock = shared_lock

    async def initialize(self) -> None:
        if self._initialized:
            return
        async with self._initialize_lock:
            if self._initialized:
                return
            async with self.db.db_engine.begin() as connection:  # type: ignore[attr-defined]
                if connection.dialect.name == "postgresql":
                    await connection.execute(text("SELECT pg_advisory_xact_lock(1735812441)"))
                    await connection.execute(
                        text(f'CREATE SCHEMA IF NOT EXISTS "{CODING_DB_SCHEMA}"')
                    )
                    await self._move_legacy_schema(connection)
                await connection.run_sync(self.metadata.create_all)
                await self._migrate_schema(connection)
                await connection.execute(delete(self.schema_versions))
                await connection.execute(
                    insert(self.schema_versions),
                    [
                        {
                            "component": component,
                            "version": TASK_SCHEMA_VERSION,
                            "updated_at": utcnow(),
                        }
                        for component in (
                            "agentos_coding_repository",
                            self.tasks.name,
                            self.runs.name,
                            self.executions.name,
                            self.instructions.name,
                        )
                    ],
                )
            self._initialized = True

    async def _move_legacy_schema(self, connection: Any) -> None:
        source_schema = self._legacy_schema
        target_schema = self.metadata.schema
        if not source_schema or not target_schema or source_schema == target_schema:
            return

        def table_names(sync_connection: Any, schema: str) -> set[str]:
            from sqlalchemy import inspect

            return set(inspect(sync_connection).get_table_names(schema=schema))

        source_tables = await connection.run_sync(table_names, source_schema)
        target_tables = await connection.run_sync(table_names, target_schema)
        coding_tables = [
            self.tasks.name,
            self.runs.name,
            self.executions.name,
            self.instructions.name,
        ]
        conflicts = (source_tables & target_tables).intersection(coding_tables)
        if conflicts:
            raise CodingRepositoryError(
                "migration_schema_conflict",
                "新旧 Coding schema 同时包含同名表，迁移已停止。",
            )

        preparer = connection.dialect.identifier_preparer
        for table_name in coding_tables:
            if table_name not in source_tables:
                continue
            await connection.execute(
                text(
                    f"ALTER TABLE {preparer.quote_schema(source_schema)}."
                    f"{preparer.quote(table_name)} SET SCHEMA "
                    f"{preparer.quote_schema(target_schema)}"
                )
            )

    async def _migrate_schema(self, connection: Any) -> None:
        """在协调停机窗口内把 1.x 三表升级为 2.x schema。"""

        def columns(sync_connection: Any, table_name: str) -> set[str]:
            from sqlalchemy import inspect

            return {
                str(item["name"])
                for item in inspect(sync_connection).get_columns(
                    table_name, schema=self.metadata.schema
                )
            }

        task_columns = await connection.run_sync(columns, self.tasks.name)
        run_columns = await connection.run_sync(columns, self.runs.name)
        execution_columns = await connection.run_sync(columns, self.executions.name)
        dialect = connection.dialect.name
        identifier_preparer = connection.dialect.identifier_preparer
        qualified_tables = {
            table.name: identifier_preparer.format_table(table)
            for table in (self.tasks, self.runs, self.executions)
        }
        json_type = "JSONB" if dialect == "postgresql" else "JSON"
        timestamp_type = "TIMESTAMP WITH TIME ZONE" if dialect == "postgresql" else "DATETIME"
        additions = {
            self.tasks.name: (
                ("state_version", "BIGINT NOT NULL DEFAULT 0"),
                ("lease_epoch", "BIGINT NOT NULL DEFAULT 0"),
                ("instruction_sequence", "BIGINT NOT NULL DEFAULT 0"),
                ("acceptance_contract", json_type),
                ("finish_receipt", json_type),
                ("predecessor_task_id", "VARCHAR(128)"),
            ),
            self.runs.name: (
                ("resume_count", "INTEGER NOT NULL DEFAULT 0"),
                ("outcome", "VARCHAR(32)"),
                ("agno_status", "VARCHAR(32)"),
                ("lease_epoch", "BIGINT NOT NULL DEFAULT 0"),
                ("updated_at", timestamp_type),
            ),
            self.executions.name: (
                ("kind", "VARCHAR(32) NOT NULL DEFAULT 'terminal'"),
                ("attempt_no", "INTEGER NOT NULL DEFAULT 0"),
                ("lease_epoch", "BIGINT NOT NULL DEFAULT 0"),
                ("operation_receipt", json_type),
            ),
        }
        known = {
            self.tasks.name: task_columns,
            self.runs.name: run_columns,
            self.executions.name: execution_columns,
        }
        for table_name, table_additions in additions.items():
            for column_name, ddl in table_additions:
                if column_name not in known[table_name]:
                    await connection.execute(
                        text(
                            f"ALTER TABLE {qualified_tables[table_name]} "
                            f"ADD COLUMN {identifier_preparer.quote(column_name)} {ddl}"
                        )
                    )
        await connection.execute(
            update(self.runs)
            .where(self.runs.c.updated_at.is_(None))
            .values(updated_at=self.runs.c.created_at)
        )
        duplicate = (
            await connection.execute(
                select(self.runs.c.external_run_id, self.runs.c.continuation_index)
                .group_by(self.runs.c.external_run_id, self.runs.c.continuation_index)
                .having(func.count() > 1)
                .limit(1)
            )
        ).first()
        if duplicate is not None:
            raise CodingRepositoryError(
                "migration_duplicate_attempt",
                "旧编码任务包含重复 Attempt 编号，迁移已停止。",
            )
        await connection.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS "
                f"{identifier_preparer.quote('uq_agentos_coding_task_runs_attempt')} "
                f"ON {qualified_tables[self.runs.name]} "
                f"({identifier_preparer.quote('external_run_id')}, "
                f"{identifier_preparer.quote('continuation_index')})"
            )
        )

    async def create_task(
        self,
        *,
        external_run_id: str,
        owner_user_id: str,
        thread_id: str,
        agent_id: str,
        sandbox_id: str,
        deadline_at: datetime,
        acceptance_contract: dict[str, Any] | None = None,
    ) -> CodingTask:
        await self.initialize()
        normalized_contract = self._normalize_acceptance_contract(acceptance_contract)
        now = utcnow()
        try:
            async with self.db.db_engine.begin() as connection:  # type: ignore[attr-defined]
                await connection.execute(
                    insert(self.tasks).values(
                        external_run_id=external_run_id,
                        owner_user_id=owner_user_id,
                        thread_id=thread_id,
                        agent_id=agent_id,
                        sandbox_id=sandbox_id,
                        status="pending",
                        continuation_count=0,
                        same_error_count=0,
                        deadline_at=deadline_at,
                        mutation_sequence=0,
                        acceptance_contract=normalized_contract,
                        created_at=now,
                        updated_at=now,
                    )
                )
        except IntegrityError:
            pass
        task = await self.get_task(external_run_id)
        if task is None:
            raise CodingRepositoryError("task_create_failed", "编码任务状态创建失败。")
        self._assert_scope(task, owner_user_id, thread_id, sandbox_id)
        if task.agent_id != agent_id:
            raise CodingRepositoryError("task_agent_mismatch", "编码任务智能体绑定不一致。")
        if task.acceptance_contract != normalized_contract:
            raise CodingRepositoryError(
                "task_acceptance_contract_conflict", "编码任务验收契约不可修改。"
            )
        return task

    async def get_task(self, external_run_id: str) -> CodingTask | None:
        await self.initialize()
        async with self.db.db_engine.connect() as connection:  # type: ignore[attr-defined]
            row = (
                await connection.execute(
                    select(self.tasks).where(self.tasks.c.external_run_id == external_run_id)
                )
            ).first()
        return _task_from_row(row) if row is not None else None

    @staticmethod
    def _assert_scope(
        task: CodingTask,
        owner_user_id: str,
        thread_id: str,
        sandbox_id: str | None = None,
    ) -> None:
        if task.owner_user_id != owner_user_id or task.thread_id != thread_id:
            raise CodingRepositoryError("task_scope_mismatch", "编码任务不属于当前用户或对话。")
        if sandbox_id is not None and task.sandbox_id != sandbox_id:
            raise CodingRepositoryError("task_sandbox_mismatch", "编码任务不属于当前工作区。")

    async def claim_lease(
        self,
        external_run_id: str,
        lease_owner: str,
        *,
        ttl: timedelta = timedelta(seconds=45),
    ) -> bool | Lease | None:
        await self.initialize()
        task = await self.get_task(external_run_id)
        if task is not None and task.status in {
            TaskState.NEW,
            TaskState.ACTIVE,
            TaskState.SUSPENDED,
            TaskState.FINISHING,
        }:
            return await self._claim_epoch_lease(external_run_id, lease_owner, ttl=ttl)
        now = utcnow()
        async with self.db.db_engine.begin() as connection:  # type: ignore[attr-defined]
            result = await connection.execute(
                update(self.tasks)
                .where(
                    self.tasks.c.external_run_id == external_run_id,
                    self.tasks.c.status.in_(ACTIVE_TASK_STATUSES),
                    self.tasks.c.deadline_at > now,
                    or_(
                        self.tasks.c.lease_owner.is_(None),
                        self.tasks.c.lease_expires_at <= now,
                        self.tasks.c.lease_owner == lease_owner,
                    ),
                )
                .values(
                    lease_owner=lease_owner,
                    lease_expires_at=now + ttl,
                    updated_at=now,
                )
            )
        return result.rowcount == 1

    async def _claim_epoch_lease(
        self,
        external_run_id: str,
        lease_owner: str,
        *,
        ttl: timedelta,
    ) -> Lease | None:
        now = utcnow()
        async with self.db.db_engine.begin() as connection:  # type: ignore[attr-defined]
            row = (
                await connection.execute(
                    select(
                        self.tasks.c.lease_owner,
                        self.tasks.c.lease_epoch,
                        self.tasks.c.lease_expires_at,
                        self.tasks.c.status,
                        self.tasks.c.deadline_at,
                    ).where(self.tasks.c.external_run_id == external_run_id)
                )
            ).first()
            if row is None:
                raise CodingRepositoryError("task_not_found", "编码任务不存在。")
            value = row._mapping
            if value["status"] not in {
                TaskState.NEW,
                TaskState.ACTIVE,
                TaskState.SUSPENDED,
                TaskState.FINISHING,
            }:
                return None
            expires_at = value["lease_expires_at"]
            same_owner = value["lease_owner"] == lease_owner
            available = (
                value["lease_owner"] is None
                or expires_at is None
                or _as_utc(expires_at) <= now
                or same_owner
            )
            if not available:
                return None
            epoch = int(value["lease_epoch"] or 0) + (0 if same_owner else 1)
            new_expiry = now + ttl
            conditions = [
                self.tasks.c.external_run_id == external_run_id,
                self.tasks.c.lease_epoch == int(value["lease_epoch"] or 0),
            ]
            if value["lease_owner"] is None:
                conditions.append(self.tasks.c.lease_owner.is_(None))
            else:
                conditions.append(self.tasks.c.lease_owner == value["lease_owner"])
            result = await connection.execute(
                update(self.tasks)
                .where(*conditions)
                .values(
                    lease_owner=lease_owner,
                    lease_epoch=epoch,
                    lease_expires_at=new_expiry,
                    updated_at=now,
                )
            )
            if result.rowcount != 1:
                return None
        return Lease(lease_owner, epoch, new_expiry)

    async def release_lease(self, external_run_id: str, lease_owner: str) -> None:
        await self.initialize()
        async with self.db.db_engine.begin() as connection:  # type: ignore[attr-defined]
            await connection.execute(
                update(self.tasks)
                .where(
                    self.tasks.c.external_run_id == external_run_id,
                    self.tasks.c.lease_owner == lease_owner,
                )
                .values(lease_owner=None, lease_expires_at=None, updated_at=utcnow())
            )

    async def suspend_task(self, external_run_id: str, lease_owner: str) -> bool:
        await self.initialize()
        async with self.db.db_engine.begin() as connection:  # type: ignore[attr-defined]
            result = await connection.execute(
                update(self.tasks)
                .where(
                    self.tasks.c.external_run_id == external_run_id,
                    self.tasks.c.status.in_(ACTIVE_TASK_STATUSES),
                    self.tasks.c.lease_owner == lease_owner,
                )
                .values(
                    status="suspended",
                    lease_owner=None,
                    lease_expires_at=None,
                    updated_at=utcnow(),
                )
            )
        return result.rowcount == 1

    async def bind_initial_run(self, external_run_id: str, internal_run_id: str) -> CodingTask:
        await self.initialize()
        now = utcnow()
        async with self.db.db_engine.begin() as connection:  # type: ignore[attr-defined]
            result = await connection.execute(
                update(self.tasks)
                .where(
                    self.tasks.c.external_run_id == external_run_id,
                    self.tasks.c.current_internal_run_id.is_(None),
                    self.tasks.c.continuation_count == 0,
                    self.tasks.c.status.in_(ACTIVE_TASK_STATUSES),
                )
                .values(
                    current_internal_run_id=internal_run_id,
                    status="running",
                    updated_at=now,
                )
            )
            if result.rowcount == 1:
                await connection.execute(
                    insert(self.runs).values(
                        internal_run_id=internal_run_id,
                        external_run_id=external_run_id,
                        continuation_index=0,
                        status="running",
                        created_at=now,
                    )
                )
        task = await self.get_task(external_run_id)
        if task is None:
            raise CodingRepositoryError("task_not_found", "编码任务不存在。")
        if task.current_internal_run_id != internal_run_id:
            raise CodingRepositoryError("task_run_conflict", "编码任务已由其他内部运行接管。")
        return task

    async def begin_run(self, external_run_id: str, internal_run_id: str) -> CodingTask:
        await self.initialize()
        task = await self.get_task(external_run_id)
        if task is None:
            raise CodingRepositoryError("task_not_found", "编码任务不存在。")
        now = utcnow()
        if task.deadline_at <= now:
            raise CodingRepositoryError("task_deadline_exceeded", "编码任务已达到 24 小时时限。")
        if task.continuation_count >= MAX_CONTINUATIONS:
            raise CodingRepositoryError("task_continuation_exhausted", "编码任务已达到续跑上限。")
        next_count = task.continuation_count + 1
        async with self.db.db_engine.begin() as connection:  # type: ignore[attr-defined]
            result = await connection.execute(
                update(self.tasks)
                .where(
                    self.tasks.c.external_run_id == external_run_id,
                    self.tasks.c.continuation_count == task.continuation_count,
                    self.tasks.c.status.in_(ACTIVE_TASK_STATUSES),
                )
                .values(
                    current_internal_run_id=internal_run_id,
                    continuation_count=next_count,
                    status="running",
                    lease_owner=None,
                    lease_expires_at=None,
                    updated_at=now,
                )
            )
            if result.rowcount != 1:
                raise CodingRepositoryError("task_cas_conflict", "编码任务状态已被其他实例更新。")
            await connection.execute(
                insert(self.runs).values(
                    internal_run_id=internal_run_id,
                    external_run_id=external_run_id,
                    continuation_index=next_count,
                    status="running",
                    created_at=now,
                )
            )
        updated = await self.get_task(external_run_id)
        assert updated is not None
        return updated

    async def clear_error(self, external_run_id: str) -> None:
        await self.initialize()
        async with self.db.db_engine.begin() as connection:  # type: ignore[attr-defined]
            await connection.execute(
                update(self.tasks)
                .where(self.tasks.c.external_run_id == external_run_id)
                .values(error_fingerprint=None, same_error_count=0, updated_at=utcnow())
            )

    async def finish_run(
        self,
        internal_run_id: str,
        status: str,
        *,
        output: str = "",
        fingerprint: str | None = None,
    ) -> None:
        await self.initialize()
        async with self.db.db_engine.begin() as connection:  # type: ignore[attr-defined]
            await connection.execute(
                update(self.runs)
                .where(self.runs.c.internal_run_id == internal_run_id)
                .values(
                    status=status,
                    error_fingerprint=fingerprint,
                    terminal_output=bounded_output(output),
                    completed_at=utcnow(),
                )
            )

    async def latest_run_output(self, external_run_id: str) -> str:
        await self.initialize()
        async with self.db.db_engine.connect() as connection:  # type: ignore[attr-defined]
            value = (
                await connection.execute(
                    select(self.runs.c.terminal_output)
                    .where(self.runs.c.external_run_id == external_run_id)
                    .order_by(self.runs.c.continuation_index.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
        return str(value or "")

    async def record_error(self, external_run_id: str, error: BaseException | str) -> CodingTask:
        task = await self.get_task(external_run_id)
        if task is None:
            raise CodingRepositoryError("task_not_found", "编码任务不存在。")
        fingerprint = error_fingerprint(error)
        same_count = task.same_error_count + 1 if task.error_fingerprint == fingerprint else 1
        async with self.db.db_engine.begin() as connection:  # type: ignore[attr-defined]
            result = await connection.execute(
                update(self.tasks)
                .where(
                    self.tasks.c.external_run_id == external_run_id,
                    self.tasks.c.same_error_count == task.same_error_count,
                )
                .values(
                    error_fingerprint=fingerprint,
                    same_error_count=same_count,
                    status="suspended",
                    updated_at=utcnow(),
                )
            )
        if result.rowcount != 1:
            raise CodingRepositoryError("task_cas_conflict", "编码任务错误状态已被其他实例更新。")
        updated = await self.get_task(external_run_id)
        assert updated is not None
        return updated

    async def set_task_status(
        self,
        external_run_id: str,
        status: str,
        *,
        result_text: str | None = None,
        finish_payload: dict[str, Any] | None = None,
    ) -> None:
        await self.initialize()
        now = utcnow()
        values: dict[str, Any] = {
            "status": status,
            "updated_at": now,
            "lease_owner": None,
            "lease_expires_at": None,
        }
        if status in TERMINAL_TASK_STATUSES:
            values["completed_at"] = now
        if result_text is not None:
            values["result_text"] = bounded_output(result_text)
        if finish_payload is not None:
            json.dumps(finish_payload)
            values["finish_payload"] = finish_payload
        async with self.db.db_engine.begin() as connection:  # type: ignore[attr-defined]
            result = await connection.execute(
                update(self.tasks)
                .where(self.tasks.c.external_run_id == external_run_id)
                .values(**values)
            )
        if result.rowcount != 1:
            raise CodingRepositoryError("task_not_found", "编码任务不存在。")

    async def complete_task(
        self,
        external_run_id: str,
        *,
        expected_mutation_sequence: int,
        expected_lease_owner: str,
        result_text: str,
        finish_payload: dict[str, Any],
        retained_execution_ids: list[str],
    ) -> None:
        await self.initialize()
        json.dumps(finish_payload)
        now = utcnow()
        retained_ids = set(retained_execution_ids)
        async with self.db.db_engine.begin() as connection:  # type: ignore[attr-defined]
            result = await connection.execute(
                update(self.tasks)
                .where(
                    self.tasks.c.external_run_id == external_run_id,
                    self.tasks.c.status.in_(ACTIVE_TASK_STATUSES),
                    self.tasks.c.mutation_sequence == expected_mutation_sequence,
                    self.tasks.c.lease_owner == expected_lease_owner,
                )
                .values(
                    status="completed",
                    result_text=bounded_output(result_text),
                    finish_payload=finish_payload,
                    completed_at=now,
                    updated_at=now,
                    lease_owner=None,
                    lease_expires_at=None,
                )
            )
            if result.rowcount != 1:
                raise CodingRepositoryError("task_cas_conflict", "编码任务在验收期间发生变化。")
            if retained_ids:
                retained = await connection.execute(
                    update(self.executions)
                    .where(
                        self.executions.c.external_run_id == external_run_id,
                        self.executions.c.execution_id.in_(retained_ids),
                        self.executions.c.status.not_in(TERMINAL_EXECUTION_STATUSES),
                    )
                    .values(retained_service=True, updated_at=now)
                )
                if retained.rowcount != len(retained_ids):
                    raise CodingRepositoryError("task_cas_conflict", "保留服务在验收期间发生变化。")

    async def increment_mutation(
        self,
        external_run_id: str,
        *,
        lease: Lease | None = None,
        internal_run_id: str | None = None,
    ) -> int:
        await self.initialize()
        async with self.db.db_engine.begin() as connection:  # type: ignore[attr-defined]
            conditions = [
                self.tasks.c.external_run_id == external_run_id,
                self.tasks.c.status.in_(
                    [*ACTIVE_TASK_STATUSES, TaskState.NEW, TaskState.ACTIVE, TaskState.SUSPENDED]
                ),
            ]
            if lease is not None:
                conditions.extend(
                    [
                        self.tasks.c.lease_owner == lease.owner,
                        self.tasks.c.lease_epoch == lease.epoch,
                        self.tasks.c.lease_expires_at > utcnow(),
                    ]
                )
            if internal_run_id is not None:
                conditions.append(self.tasks.c.current_internal_run_id == internal_run_id)
            value = (
                await connection.execute(
                    update(self.tasks)
                    .where(*conditions)
                    .values(
                        mutation_sequence=self.tasks.c.mutation_sequence + 1,
                        updated_at=utcnow(),
                    )
                    .returning(self.tasks.c.mutation_sequence)
                )
            ).scalar_one_or_none()
        if value is None:
            raise CodingRepositoryError("task_not_active", "编码任务已结束，不能继续修改。")
        return int(value)

    async def record_execution_mutation(
        self,
        external_run_id: str,
        execution_id: str,
        expected_mutation_sequence: int,
        *,
        lease: Lease | None,
        internal_run_id: str,
    ) -> int:
        await self.initialize()
        async with self.db.db_engine.begin() as connection:  # type: ignore[attr-defined]
            conditions = [
                self.tasks.c.external_run_id == external_run_id,
                self.tasks.c.current_internal_run_id == internal_run_id,
                self.tasks.c.mutation_sequence == expected_mutation_sequence,
                self.tasks.c.status.in_([TaskState.NEW, TaskState.ACTIVE, TaskState.SUSPENDED]),
            ]
            if lease is not None:
                conditions.extend(
                    [
                        self.tasks.c.lease_owner == lease.owner,
                        self.tasks.c.lease_epoch == lease.epoch,
                        self.tasks.c.lease_expires_at > utcnow(),
                    ]
                )
            value = (
                await connection.execute(
                    update(self.tasks)
                    .where(*conditions)
                    .values(
                        mutation_sequence=self.tasks.c.mutation_sequence + 1,
                        updated_at=utcnow(),
                    )
                    .returning(self.tasks.c.mutation_sequence)
                )
            ).scalar_one_or_none()
            if value is None:
                raise CodingRepositoryError(
                    "execution_mutation_conflict", "Execution mutation 序号已变化。"
                )
            execution = await connection.execute(
                update(self.executions)
                .where(
                    self.executions.c.execution_id == execution_id,
                    self.executions.c.external_run_id == external_run_id,
                    self.executions.c.internal_run_id == internal_run_id,
                    self.executions.c.mutation_sequence == expected_mutation_sequence,
                )
                .values(mutation_sequence=value, updated_at=utcnow())
            )
            if execution.rowcount != 1:
                raise CodingRepositoryError(
                    "execution_mutation_conflict", "Execution mutation 绑定已变化。"
                )
        return int(value)

    async def reserve_execution(
        self,
        *,
        execution_id: str,
        external_run_id: str,
        internal_run_id: str,
        owner_user_id: str,
        thread_id: str,
        sandbox_id: str,
        daytona_session_id: str,
        mutation_sequence: int,
        is_verification: bool = False,
        kind: str = "terminal",
        attempt_no: int = 0,
        lease_epoch: int = 0,
        operation_receipt: dict[str, Any] | None = None,
        lease: Lease | None = None,
    ) -> CodingExecution:
        await self.initialize()
        now = utcnow()
        async with self.db.db_engine.begin() as connection:  # type: ignore[attr-defined]
            if lease is not None:
                task = await self._locked_task_for_execution(
                    connection,
                    external_run_id,
                    internal_run_id,
                    attempt_no,
                    lease,
                )
                if int(task._mapping["mutation_sequence"] or 0) != mutation_sequence:
                    raise CodingRepositoryError(
                        "execution_mutation_conflict", "Execution mutation 序号已变化。"
                    )
            await connection.execute(
                insert(self.executions).values(
                    execution_id=execution_id,
                    external_run_id=external_run_id,
                    internal_run_id=internal_run_id,
                    owner_user_id=owner_user_id,
                    thread_id=thread_id,
                    sandbox_id=sandbox_id,
                    daytona_session_id=daytona_session_id,
                    status="reserved",
                    kind=kind,
                    attempt_no=attempt_no,
                    lease_epoch=lease_epoch,
                    operation_receipt=operation_receipt,
                    output_cursor=0,
                    terminal_output="",
                    mutation_sequence=mutation_sequence,
                    is_verification=is_verification,
                    retained_service=False,
                    created_at=now,
                    updated_at=now,
                )
            )
        execution = await self.get_execution(execution_id)
        assert execution is not None
        return execution

    async def validate_execution_fence(
        self,
        execution_id: str,
        lease: Lease,
        *,
        allow_finishing: bool = False,
    ) -> CodingExecution:
        await self.initialize()
        states = [TaskState.NEW, TaskState.ACTIVE, TaskState.SUSPENDED]
        if allow_finishing:
            states.append(TaskState.FINISHING)
        async with self.db.db_engine.connect() as connection:  # type: ignore[attr-defined]
            row = (
                await connection.execute(
                    select(self.executions)
                    .join(
                        self.tasks,
                        self.tasks.c.external_run_id == self.executions.c.external_run_id,
                    )
                    .where(
                        self.executions.c.execution_id == execution_id,
                        self.executions.c.internal_run_id == self.tasks.c.current_internal_run_id,
                        self.executions.c.attempt_no == self.tasks.c.continuation_count,
                        self.executions.c.lease_epoch == lease.epoch,
                        self.tasks.c.lease_owner == lease.owner,
                        self.tasks.c.lease_epoch == lease.epoch,
                        self.tasks.c.lease_expires_at > utcnow(),
                        self.tasks.c.status.in_(states),
                    )
                )
            ).first()
        if row is None:
            raise CodingRepositoryError("execution_fenced", "Execution 已被新的任务租约隔离。")
        return _execution_from_row(row)

    async def _locked_task_for_execution(
        self,
        connection: Any,
        external_run_id: str,
        internal_run_id: str,
        attempt_no: int,
        lease: Lease,
    ) -> Any:
        row = (
            await connection.execute(
                select(self.tasks).where(
                    self.tasks.c.external_run_id == external_run_id,
                    self.tasks.c.current_internal_run_id == internal_run_id,
                    self.tasks.c.continuation_count == attempt_no,
                    self.tasks.c.lease_owner == lease.owner,
                    self.tasks.c.lease_epoch == lease.epoch,
                    self.tasks.c.lease_expires_at > utcnow(),
                    self.tasks.c.status.in_([TaskState.NEW, TaskState.ACTIVE, TaskState.SUSPENDED]),
                )
            )
        ).first()
        if row is None:
            raise CodingRepositoryError("execution_fenced", "Execution 已被新的任务租约隔离。")
        return row

    async def get_execution(self, execution_id: str) -> CodingExecution | None:
        await self.initialize()
        async with self.db.db_engine.connect() as connection:  # type: ignore[attr-defined]
            row = (
                await connection.execute(
                    select(self.executions).where(self.executions.c.execution_id == execution_id)
                )
            ).first()
        return _execution_from_row(row) if row is not None else None

    async def scoped_execution(
        self,
        execution_id: str,
        *,
        owner_user_id: str,
        thread_id: str,
        sandbox_id: str,
    ) -> CodingExecution:
        execution = await self.get_execution(execution_id)
        if execution is None:
            raise CodingRepositoryError("execution_not_found", "执行句柄不存在。")
        if (
            execution.owner_user_id != owner_user_id
            or execution.thread_id != thread_id
            or execution.sandbox_id != sandbox_id
        ):
            raise CodingRepositoryError("execution_scope_mismatch", "执行句柄不属于当前工作区。")
        return execution

    async def update_execution(
        self,
        execution_id: str,
        *,
        status: str | None = None,
        command_id: str | None = None,
        output_cursor: int | None = None,
        output: str | None = None,
        exit_code: int | None = None,
        retained_service: bool | None = None,
        operation_receipt: dict[str, Any] | None = None,
        expected_output_cursor: int | None = None,
        expected_status: str | None = None,
    ) -> CodingExecution:
        await self.initialize()
        existing = await self.get_execution(execution_id)
        if existing is None:
            raise CodingRepositoryError("execution_not_found", "执行句柄不存在。")
        values: dict[str, Any] = {"updated_at": utcnow()}
        if status is not None:
            values["status"] = status
            if status in TERMINAL_EXECUTION_STATUSES:
                values["completed_at"] = utcnow()
        if command_id is not None:
            values["command_id"] = command_id
        if output_cursor is not None:
            values["output_cursor"] = output_cursor
        if output is not None:
            values["terminal_output"] = bounded_output(existing.terminal_output + output)
        if exit_code is not None:
            values["exit_code"] = exit_code
        if retained_service is not None:
            values["retained_service"] = retained_service
        if operation_receipt is not None:
            encoded_receipt = json.dumps(operation_receipt, sort_keys=True, separators=(",", ":"))
            if len(encoded_receipt.encode()) > MAX_TERMINAL_OUTPUT_BYTES:
                raise CodingRepositoryError("execution_receipt_too_large", "Execution 回执过大。")
            values["operation_receipt"] = operation_receipt
        async with self.db.db_engine.begin() as connection:  # type: ignore[attr-defined]
            conditions = [self.executions.c.execution_id == execution_id]
            if expected_output_cursor is not None:
                conditions.append(self.executions.c.output_cursor == expected_output_cursor)
            if expected_status is not None:
                conditions.append(self.executions.c.status == expected_status)
            result = await connection.execute(
                update(self.executions).where(*conditions).values(**values)
            )
        if result.rowcount != 1:
            raise CodingRepositoryError(
                "execution_cas_conflict", "执行输出已被其他实例读取，请使用最新游标重试。"
            )
        updated = await self.get_execution(execution_id)
        assert updated is not None
        return updated

    async def list_executions(self, external_run_id: str) -> list[CodingExecution]:
        await self.initialize()
        async with self.db.db_engine.connect() as connection:  # type: ignore[attr-defined]
            rows = (
                await connection.execute(
                    select(self.executions)
                    .where(self.executions.c.external_run_id == external_run_id)
                    .order_by(self.executions.c.created_at)
                )
            ).all()
        return [_execution_from_row(row) for row in rows]

    async def successful_verification(
        self,
        external_run_id: str,
        execution_id: str,
        mutation_sequence: int,
    ) -> bool:
        execution = await self.get_execution(execution_id)
        return bool(
            execution is not None
            and execution.external_run_id == external_run_id
            and execution.is_verification
            and execution.status == "completed"
            and execution.exit_code == 0
            and (execution.operation_receipt or {}).get("valid", True) is not False
            and execution.mutation_sequence == mutation_sequence
        )

    async def cleanup_expired(
        self,
        *,
        lease_owner: str,
        now: datetime | None = None,
    ) -> int:
        await self.initialize()
        current = now or utcnow()
        cutoff = current - TASK_RETENTION
        async with self.db.db_engine.begin() as connection:  # type: ignore[attr-defined]
            coordinator = (
                await connection.execute(
                    select(self.tasks.c.external_run_id)
                    .where(
                        self.tasks.c.status.in_(TERMINAL_TASK_STATUSES),
                        self.tasks.c.completed_at <= cutoff,
                        or_(
                            self.tasks.c.lease_owner.is_(None),
                            self.tasks.c.lease_expires_at <= current,
                            self.tasks.c.lease_owner == lease_owner,
                        ),
                    )
                    .order_by(self.tasks.c.completed_at)
                    .limit(1)
                )
            ).scalar_one_or_none()
            if coordinator is None:
                return 0
            claimed = await connection.execute(
                update(self.tasks)
                .where(
                    self.tasks.c.external_run_id == coordinator,
                    or_(
                        self.tasks.c.lease_owner.is_(None),
                        self.tasks.c.lease_expires_at <= current,
                        self.tasks.c.lease_owner == lease_owner,
                    ),
                )
                .values(lease_owner=lease_owner, lease_expires_at=current + timedelta(minutes=5))
            )
            if claimed.rowcount != 1:
                return 0
            old_task_ids = select(self.tasks.c.external_run_id).where(
                self.tasks.c.status.in_(TERMINAL_TASK_STATUSES),
                self.tasks.c.completed_at <= cutoff,
                ~exists(
                    select(self.executions.c.execution_id).where(
                        self.executions.c.external_run_id == self.tasks.c.external_run_id,
                        self.executions.c.retained_service.is_(True),
                        self.executions.c.status.not_in(TERMINAL_EXECUTION_STATUSES),
                    )
                ),
            )
            execution_result = await connection.execute(
                delete(self.executions).where(
                    and_(
                        self.executions.c.status.in_(TERMINAL_EXECUTION_STATUSES),
                        self.executions.c.completed_at <= cutoff,
                    )
                )
            )
            task_result = await connection.execute(
                delete(self.tasks).where(self.tasks.c.external_run_id.in_(old_task_ids))
            )
        return int((execution_result.rowcount or 0) + (task_result.rowcount or 0))

    @staticmethod
    def _task_snapshot(row: Any) -> TaskSnapshot:
        value = row._mapping
        scope = CodingScope(
            external_run_id=value["external_run_id"],
            owner_user_id=value["owner_user_id"],
            thread_id=value["thread_id"],
            sandbox_id=value["sandbox_id"],
            agent_id=value["agent_id"],
        )
        return TaskSnapshot(
            scope=scope,
            state=TaskState(value["status"]),
            state_version=int(value["state_version"] or 0),
            lease_epoch=int(value["lease_epoch"] or 0),
            continuation_count=int(value["continuation_count"] or 0),
            instruction_sequence=int(value["instruction_sequence"] or 0),
            current_internal_run_id=str(value["current_internal_run_id"] or ""),
            current_attempt_no=int(value["continuation_count"] or 0),
            deadline_at=_as_utc(value["deadline_at"]),
            mutation_sequence=int(value["mutation_sequence"] or 0),
            same_error_count=int(value["same_error_count"] or 0),
            error_fingerprint=value["error_fingerprint"],
            predecessor_task_id=value["predecessor_task_id"],
            acceptance_contract=value["acceptance_contract"],
            finish_receipt=value["finish_receipt"],
            result_text=value["result_text"],
            lease_owner=value["lease_owner"],
            lease_expires_at=(
                _as_utc(value["lease_expires_at"])
                if value["lease_expires_at"] is not None
                else None
            ),
        )

    @staticmethod
    def _attempt_snapshot(row: Any) -> AttemptSnapshot:
        value = row._mapping
        return AttemptSnapshot(
            internal_run_id=value["internal_run_id"],
            external_run_id=value["external_run_id"],
            attempt_no=int(value["continuation_index"]),
            state=AttemptState(value["status"]),
            resume_count=int(value["resume_count"] or 0),
            lease_epoch=int(value["lease_epoch"] or 0),
            outcome=AttemptOutcome(value["outcome"]) if value["outcome"] else None,
            agno_status=value["agno_status"],
            terminal_output=str(value["terminal_output"] or ""),
            error_fingerprint=value["error_fingerprint"],
        )

    async def get_task_snapshot(self, external_run_id: str) -> TaskSnapshot | None:
        await self.initialize()
        async with self.db.db_engine.connect() as connection:  # type: ignore[attr-defined]
            row = (
                await connection.execute(
                    select(self.tasks).where(self.tasks.c.external_run_id == external_run_id)
                )
            ).first()
        if (
            row is None
            or int(row._mapping["state_version"] or 0) <= 0
            or row._mapping["status"] not in {state.value for state in TaskState}
        ):
            return None
        return self._task_snapshot(row)

    async def get_attempt(self, internal_run_id: str) -> AttemptSnapshot | None:
        await self.initialize()
        async with self.db.db_engine.connect() as connection:  # type: ignore[attr-defined]
            row = (
                await connection.execute(
                    select(self.runs).where(self.runs.c.internal_run_id == internal_run_id)
                )
            ).first()
        if row is None or row._mapping["status"] not in {state.value for state in AttemptState}:
            return None
        return self._attempt_snapshot(row)

    @staticmethod
    def internal_run_id(external_run_id: str, attempt_no: int) -> str:
        value = f"{external_run_id}:attempt:{attempt_no}".encode()
        return hashlib.sha256(value).hexdigest()[:32]

    async def create_task_with_initial_attempt(
        self,
        scope: CodingScope,
        initial_instruction: str,
        predecessor_task_id: str | None = None,
        *,
        acceptance_contract: dict[str, Any] | None = None,
    ) -> TaskSnapshot:
        await self.initialize()
        self._validate_instruction("initial", initial_instruction)
        normalized_contract = self._normalize_acceptance_contract(acceptance_contract)
        now = utcnow()
        internal_run_id = self.internal_run_id(scope.external_run_id, 0)
        content_bytes = len(initial_instruction.encode("utf-8"))
        content_hash = hashlib.sha256(initial_instruction.encode()).hexdigest()
        try:
            async with self.db.db_engine.begin() as connection:  # type: ignore[attr-defined]
                if predecessor_task_id is not None:
                    predecessor = (
                        await connection.execute(
                            select(self.tasks).where(
                                self.tasks.c.external_run_id == predecessor_task_id
                            )
                        )
                    ).first()
                    if predecessor is None:
                        raise CodingRepositoryError("predecessor_not_found", "前序编码任务不存在。")
                    predecessor_scope = predecessor._mapping
                    if (
                        predecessor_scope["owner_user_id"] != scope.owner_user_id
                        or predecessor_scope["thread_id"] != scope.thread_id
                        or predecessor_scope["sandbox_id"] != scope.sandbox_id
                    ):
                        raise CodingRepositoryError(
                            "predecessor_scope_mismatch", "前序任务不属于当前工作区范围。"
                        )
                await connection.execute(
                    insert(self.tasks).values(
                        external_run_id=scope.external_run_id,
                        current_internal_run_id=internal_run_id,
                        owner_user_id=scope.owner_user_id,
                        thread_id=scope.thread_id,
                        agent_id=scope.agent_id,
                        sandbox_id=scope.sandbox_id,
                        status=TaskState.NEW,
                        state_version=1,
                        lease_epoch=0,
                        instruction_sequence=1,
                        continuation_count=0,
                        same_error_count=0,
                        deadline_at=now + timedelta(hours=24),
                        mutation_sequence=0,
                        predecessor_task_id=predecessor_task_id,
                        acceptance_contract=normalized_contract,
                        created_at=now,
                        updated_at=now,
                    )
                )
                await connection.execute(
                    insert(self.runs).values(
                        internal_run_id=internal_run_id,
                        external_run_id=scope.external_run_id,
                        continuation_index=0,
                        status=AttemptState.CREATED,
                        resume_count=0,
                        lease_epoch=0,
                        created_at=now,
                        updated_at=now,
                    )
                )
                await connection.execute(
                    insert(self.instructions).values(
                        external_run_id=scope.external_run_id,
                        instruction_id="initial",
                        sequence=1,
                        content=initial_instruction,
                        content_hash=content_hash,
                        content_bytes=content_bytes,
                        status=InstructionState.APPLIED,
                        applied_attempt_no=0,
                        created_at=now,
                        updated_at=now,
                    )
                )
        except IntegrityError:
            existing = await self.get_task_snapshot(scope.external_run_id)
            if existing is None:
                raise CodingRepositoryError("task_create_failed", "编码任务状态创建失败。")
            if existing.scope != scope or existing.predecessor_task_id != predecessor_task_id:
                raise CodingRepositoryError(
                    "task_scope_conflict", "外部 run 已绑定到其他编码任务。"
                )
            if existing.acceptance_contract != normalized_contract:
                raise CodingRepositoryError(
                    "task_acceptance_contract_conflict", "编码任务验收契约不可修改。"
                )
            async with self.db.db_engine.connect() as connection:  # type: ignore[attr-defined]
                stored_hash = (
                    await connection.execute(
                        select(self.instructions.c.content_hash).where(
                            self.instructions.c.external_run_id == scope.external_run_id,
                            self.instructions.c.instruction_id == "initial",
                        )
                    )
                ).scalar_one_or_none()
            if stored_hash != content_hash:
                raise CodingRepositoryError(
                    "task_initial_instruction_conflict", "外部 run 的初始目标不一致。"
                )
            return existing
        created = await self.get_task_snapshot(scope.external_run_id)
        assert created is not None
        return created

    @staticmethod
    def _normalize_acceptance_contract(
        acceptance_contract: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        if acceptance_contract is None:
            return None
        try:
            return normalize_acceptance_contract(acceptance_contract)
        except AcceptanceContractError as error:
            raise CodingRepositoryError("acceptance_contract_invalid", str(error)) from error

    @staticmethod
    def _validate_instruction(instruction_id: str, content: str) -> None:
        if (
            not isinstance(instruction_id, str)
            or not instruction_id
            or len(instruction_id) > MAX_INSTRUCTION_ID_LENGTH
        ):
            raise CodingRepositoryError("instruction_id_invalid", "instruction_id 无效。")
        if not isinstance(content, str) or not content.strip():
            raise CodingRepositoryError("instruction_content_invalid", "指令内容不能为空。")
        if len(content.encode("utf-8")) > MAX_INSTRUCTION_BYTES:
            raise CodingRepositoryError("instruction_too_large", "单条指令超过 32 KiB。")

    async def submit_instruction(
        self,
        scope: CodingScope,
        instruction_id: str,
        content: str,
    ) -> InstructionReceipt:
        await self.initialize()
        self._validate_instruction(instruction_id, content)
        content_hash = hashlib.sha256(content.encode()).hexdigest()
        content_bytes = len(content.encode("utf-8"))
        now = utcnow()
        async with self.db.db_engine.begin() as connection:  # type: ignore[attr-defined]
            task = (
                await connection.execute(
                    select(self.tasks).where(self.tasks.c.external_run_id == scope.external_run_id)
                )
            ).first()
            if task is None:
                raise CodingRepositoryError("task_not_found", "编码任务不存在。")
            value = task._mapping
            if any(
                value[key] != expected
                for key, expected in (
                    ("owner_user_id", scope.owner_user_id),
                    ("thread_id", scope.thread_id),
                    ("sandbox_id", scope.sandbox_id),
                    ("agent_id", scope.agent_id),
                )
            ):
                raise CodingRepositoryError("task_scope_mismatch", "编码任务范围不匹配。")
            existing = (
                await connection.execute(
                    select(self.instructions).where(
                        self.instructions.c.external_run_id == scope.external_run_id,
                        self.instructions.c.instruction_id == instruction_id,
                    )
                )
            ).first()
            if existing is not None:
                stored = existing._mapping
                if stored["content_hash"] != content_hash:
                    raise CodingRepositoryError(
                        "instruction_id_conflict", "instruction_id 已绑定到不同内容。"
                    )
                return InstructionReceipt(
                    instruction_id,
                    int(stored["sequence"]),
                    InstructionState(stored["status"]),
                    stored["rejection_code"],
                    stored["applied_attempt_no"],
                )
            if value["status"] == TaskState.FINISHING or value["finish_receipt"] is not None:
                raise CodingRepositoryError(
                    "task_successor_required", "任务已进入完成阶段，请创建 successor task。"
                )
            if value["status"] in {
                TaskState.COMPLETED,
                TaskState.FAILED,
                TaskState.CANCELLED,
            }:
                raise CodingRepositoryError(
                    "task_successor_required", "任务已结束，请创建 successor task。"
                )
            pending = (
                await connection.execute(
                    select(
                        func.count(), func.coalesce(func.sum(self.instructions.c.content_bytes), 0)
                    ).where(
                        self.instructions.c.external_run_id == scope.external_run_id,
                        self.instructions.c.status == InstructionState.PENDING,
                    )
                )
            ).one()
            if int(pending[0]) >= MAX_PENDING_INSTRUCTIONS:
                raise CodingRepositoryError(
                    "instruction_pending_limit", "待处理指令已达到 50 条上限。"
                )
            if int(pending[1]) + content_bytes > MAX_PENDING_INSTRUCTION_BYTES:
                raise CodingRepositoryError(
                    "instruction_pending_bytes_limit", "待处理指令总大小超过 256 KiB。"
                )
            sequence = int(value["instruction_sequence"] or 0) + 1
            result = await connection.execute(
                update(self.tasks)
                .where(
                    self.tasks.c.external_run_id == scope.external_run_id,
                    self.tasks.c.state_version == value["state_version"],
                    self.tasks.c.status == value["status"],
                    self.tasks.c.finish_receipt.is_(None),
                )
                .values(
                    instruction_sequence=sequence,
                    state_version=self.tasks.c.state_version + 1,
                    updated_at=now,
                )
            )
            if result.rowcount != 1:
                raise CodingRepositoryError("task_cas_conflict", "任务状态已发生变化。")
            await connection.execute(
                insert(self.instructions).values(
                    external_run_id=scope.external_run_id,
                    instruction_id=instruction_id,
                    sequence=sequence,
                    content=content,
                    content_hash=content_hash,
                    content_bytes=content_bytes,
                    status=InstructionState.PENDING,
                    created_at=now,
                    updated_at=now,
                )
            )
        return InstructionReceipt(instruction_id, sequence, InstructionState.PENDING)

    async def revise_completed_task(
        self,
        scope: CodingScope,
        instruction_id: str,
        content: str,
        *,
        acceptance_contract: dict[str, Any] | None = None,
    ) -> TaskSnapshot:
        """在同一任务内为已完成结果开启下一个修订 Attempt。"""

        await self.initialize()
        self._validate_instruction(instruction_id, content)
        normalized_contract = (
            self._normalize_acceptance_contract(acceptance_contract)
            if acceptance_contract is not None
            else None
        )
        content_hash = hashlib.sha256(content.encode()).hexdigest()
        content_bytes = len(content.encode("utf-8"))
        now = utcnow()
        async with self.db.db_engine.begin() as connection:  # type: ignore[attr-defined]
            task = (
                await connection.execute(
                    select(self.tasks).where(self.tasks.c.external_run_id == scope.external_run_id)
                )
            ).first()
            if task is None:
                raise CodingRepositoryError("task_not_found", "编码任务不存在。")
            value = task._mapping
            if any(
                value[key] != expected
                for key, expected in (
                    ("owner_user_id", scope.owner_user_id),
                    ("thread_id", scope.thread_id),
                    ("sandbox_id", scope.sandbox_id),
                    ("agent_id", scope.agent_id),
                )
            ):
                raise CodingRepositoryError("task_scope_mismatch", "编码任务范围不匹配。")
            existing = (
                await connection.execute(
                    select(self.instructions).where(
                        self.instructions.c.external_run_id == scope.external_run_id,
                        self.instructions.c.instruction_id == instruction_id,
                    )
                )
            ).first()
            if existing is not None:
                if existing._mapping["content_hash"] != content_hash:
                    raise CodingRepositoryError(
                        "instruction_id_conflict", "instruction_id 已绑定到不同内容。"
                    )
            else:
                if value["status"] != TaskState.COMPLETED:
                    raise CodingRepositoryError(
                        "task_revision_not_ready", "只能修订已完成的编码任务。"
                    )
                if _as_utc(value["deadline_at"]) <= now:
                    raise CodingRepositoryError(
                        "task_deadline_exceeded", "编码任务已达到 24 小时时限。"
                    )
                next_attempt_no = int(value["continuation_count"] or 0) + 1
                if next_attempt_no > MAX_CONTINUATIONS:
                    raise CodingRepositoryError(
                        "task_continuation_exhausted", "编码任务已达到续跑上限。"
                    )
                next_run_id = self.internal_run_id(scope.external_run_id, next_attempt_no)
                sequence = int(value["instruction_sequence"] or 0) + 1
                next_lease_epoch = int(value["lease_epoch"] or 0) + 1
                await connection.execute(
                    insert(self.runs).values(
                        internal_run_id=next_run_id,
                        external_run_id=scope.external_run_id,
                        continuation_index=next_attempt_no,
                        status=AttemptState.CREATED,
                        resume_count=0,
                        lease_epoch=next_lease_epoch,
                        created_at=now,
                        updated_at=now,
                    )
                )
                await connection.execute(
                    insert(self.instructions).values(
                        external_run_id=scope.external_run_id,
                        instruction_id=instruction_id,
                        sequence=sequence,
                        content=content,
                        content_hash=content_hash,
                        content_bytes=content_bytes,
                        status=InstructionState.APPLIED,
                        applied_attempt_no=next_attempt_no,
                        created_at=now,
                        updated_at=now,
                    )
                )
                result = await connection.execute(
                    update(self.tasks)
                    .where(
                        self.tasks.c.external_run_id == scope.external_run_id,
                        self.tasks.c.state_version == value["state_version"],
                        self.tasks.c.status == TaskState.COMPLETED,
                    )
                    .values(
                        status=TaskState.NEW,
                        current_internal_run_id=next_run_id,
                        continuation_count=next_attempt_no,
                        instruction_sequence=sequence,
                        state_version=self.tasks.c.state_version + 1,
                        lease_epoch=next_lease_epoch,
                        lease_owner=None,
                        lease_expires_at=None,
                        finish_receipt=None,
                        result_text=None,
                        same_error_count=0,
                        error_fingerprint=None,
                        **(
                            {"acceptance_contract": normalized_contract}
                            if normalized_contract is not None
                            else {}
                        ),
                        completed_at=None,
                        updated_at=now,
                    )
                )
                if result.rowcount != 1:
                    raise CodingRepositoryError("task_cas_conflict", "任务状态已发生变化。")
        updated = await self.get_task_snapshot(scope.external_run_id)
        assert updated is not None
        return updated

    async def pending_instructions(self, external_run_id: str) -> list[tuple[int, str]]:
        await self.initialize()
        async with self.db.db_engine.connect() as connection:  # type: ignore[attr-defined]
            rows = (
                await connection.execute(
                    select(self.instructions.c.sequence, self.instructions.c.content)
                    .where(
                        self.instructions.c.external_run_id == external_run_id,
                        self.instructions.c.status == InstructionState.PENDING,
                    )
                    .order_by(self.instructions.c.sequence)
                )
            ).all()
        return [(int(row.sequence), str(row.content)) for row in rows]

    async def attempt_instruction(self, external_run_id: str, attempt_no: int) -> str:
        await self.initialize()
        async with self.db.db_engine.connect() as connection:  # type: ignore[attr-defined]
            initial = (
                await connection.execute(
                    select(self.instructions.c.content).where(
                        self.instructions.c.external_run_id == external_run_id,
                        self.instructions.c.status == InstructionState.APPLIED,
                        self.instructions.c.instruction_id == "initial",
                    )
                )
            ).scalar_one_or_none()
            supplemental = (
                await connection.execute(
                    select(self.instructions.c.content)
                    .where(
                        self.instructions.c.external_run_id == external_run_id,
                        self.instructions.c.status == InstructionState.APPLIED,
                        self.instructions.c.applied_attempt_no == attempt_no,
                        self.instructions.c.instruction_id != "initial",
                    )
                    .order_by(self.instructions.c.sequence.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
        return "\n\n".join(
            str(content) for content in (initial, supplemental) if content is not None
        )

    async def open_initial(
        self,
        external_run_id: str,
        lease: Lease,
        expected_state_version: int,
    ) -> tuple[TaskSnapshot, AttemptSnapshot]:
        await self.initialize()
        now = utcnow()
        async with self.db.db_engine.begin() as connection:  # type: ignore[attr-defined]
            task = await self._locked_task(
                connection, external_run_id, lease, expected_state_version
            )
            value = task._mapping
            attempt_result = await connection.execute(
                update(self.runs)
                .where(
                    self.runs.c.internal_run_id == value["current_internal_run_id"],
                    self.runs.c.status == AttemptState.CREATED,
                    self.runs.c.continuation_index == value["continuation_count"],
                )
                .values(
                    status=AttemptState.RUNNING,
                    lease_epoch=lease.epoch,
                    updated_at=now,
                )
            )
            if attempt_result.rowcount != 1:
                raise CodingRepositoryError("attempt_cas_conflict", "初始 Attempt 状态已变化。")
            task_result = await connection.execute(
                update(self.tasks)
                .where(
                    self.tasks.c.external_run_id == external_run_id,
                    self.tasks.c.state_version == expected_state_version,
                )
                .values(
                    status=TaskState.ACTIVE,
                    state_version=self.tasks.c.state_version + 1,
                    updated_at=now,
                )
            )
            if task_result.rowcount != 1:
                raise CodingRepositoryError("task_cas_conflict", "任务状态已发生变化。")
        return await self._required_current(external_run_id)

    async def heartbeat_lease(
        self,
        external_run_id: str,
        lease: Lease,
        *,
        ttl: timedelta = timedelta(seconds=45),
    ) -> Lease:
        await self.initialize()
        now = utcnow()
        expires_at = now + ttl
        async with self.db.db_engine.begin() as connection:  # type: ignore[attr-defined]
            result = await connection.execute(
                update(self.tasks)
                .where(
                    self.tasks.c.external_run_id == external_run_id,
                    self.tasks.c.lease_owner == lease.owner,
                    self.tasks.c.lease_epoch == lease.epoch,
                    self.tasks.c.lease_expires_at > now,
                    self.tasks.c.status.in_(
                        [TaskState.NEW, TaskState.ACTIVE, TaskState.SUSPENDED, TaskState.FINISHING]
                    ),
                )
                .values(lease_expires_at=expires_at, updated_at=now)
            )
        if result.rowcount != 1:
            raise CodingRepositoryError("task_lease_lost", "编码任务租约已失效。")
        return Lease(lease.owner, lease.epoch, expires_at)

    async def resume_current(
        self,
        external_run_id: str,
        lease: Lease,
        expected_state_version: int,
    ) -> tuple[TaskSnapshot, AttemptSnapshot]:
        await self.initialize()
        now = utcnow()
        async with self.db.db_engine.begin() as connection:  # type: ignore[attr-defined]
            task = await self._locked_task(
                connection, external_run_id, lease, expected_state_version
            )
            value = task._mapping
            if value["status"] not in {TaskState.NEW, TaskState.ACTIVE, TaskState.SUSPENDED}:
                raise CodingRepositoryError("task_not_runnable", "编码任务当前不可恢复。")
            run_id = value["current_internal_run_id"]
            attempt = (
                await connection.execute(
                    select(self.runs).where(
                        self.runs.c.internal_run_id == run_id,
                        self.runs.c.external_run_id == external_run_id,
                        self.runs.c.continuation_index == value["continuation_count"],
                    )
                )
            ).first()
            if attempt is None or attempt._mapping["status"] not in {
                AttemptState.CREATED,
                AttemptState.RUNNING,
                AttemptState.PAUSED,
            }:
                raise CodingRepositoryError("attempt_not_resumable", "当前 Attempt 不可恢复。")
            await connection.execute(
                update(self.runs)
                .where(self.runs.c.internal_run_id == run_id)
                .values(
                    status=AttemptState.RUNNING,
                    resume_count=self.runs.c.resume_count + 1,
                    lease_epoch=lease.epoch,
                    updated_at=now,
                )
            )
            await connection.execute(
                update(self.tasks)
                .where(
                    self.tasks.c.external_run_id == external_run_id,
                    self.tasks.c.state_version == expected_state_version,
                )
                .values(
                    status=TaskState.ACTIVE,
                    state_version=self.tasks.c.state_version + 1,
                    updated_at=now,
                )
            )
        return await self._required_current(external_run_id)

    async def pause_and_release(
        self,
        external_run_id: str,
        lease: Lease,
        expected_state_version: int,
        *,
        agno_status: str | None = None,
    ) -> TaskSnapshot:
        await self.initialize()
        now = utcnow()
        async with self.db.db_engine.begin() as connection:  # type: ignore[attr-defined]
            task = await self._locked_task(
                connection, external_run_id, lease, expected_state_version
            )
            value = task._mapping
            run_id = value["current_internal_run_id"]
            if value["status"] != TaskState.FINISHING:
                await connection.execute(
                    update(self.runs)
                    .where(
                        self.runs.c.internal_run_id == run_id,
                        self.runs.c.status.in_([AttemptState.RUNNING, AttemptState.CREATED]),
                    )
                    .values(status=AttemptState.PAUSED, agno_status=agno_status, updated_at=now)
                )
            task_state = (
                TaskState.FINISHING
                if value["status"] == TaskState.FINISHING
                else TaskState.SUSPENDED
            )
            result = await connection.execute(
                update(self.tasks)
                .where(
                    self.tasks.c.external_run_id == external_run_id,
                    self.tasks.c.state_version == expected_state_version,
                )
                .values(
                    status=task_state,
                    state_version=self.tasks.c.state_version + 1,
                    lease_owner=None,
                    lease_expires_at=None,
                    updated_at=now,
                )
            )
            if result.rowcount != 1:
                raise CodingRepositoryError("task_cas_conflict", "任务状态已发生变化。")
        snapshot = await self.get_task_snapshot(external_run_id)
        assert snapshot is not None
        return snapshot

    async def close_and_decide(
        self,
        external_run_id: str,
        lease: Lease,
        expected_state_version: int,
        *,
        outcome: AttemptOutcome,
        agno_status: str | None,
        terminal_output: str = "",
        error: BaseException | str | None = None,
        create_next: bool,
    ) -> TaskSnapshot:
        await self.initialize()
        now = utcnow()
        async with self.db.db_engine.begin() as connection:  # type: ignore[attr-defined]
            task = await self._locked_task(
                connection, external_run_id, lease, expected_state_version
            )
            value = task._mapping
            if value["status"] == TaskState.FINISHING:
                raise CodingRepositoryError("task_finishing", "任务已进入完成阶段。")
            run_id = value["current_internal_run_id"]
            fingerprint = error_fingerprint(error) if error is not None else None
            await connection.execute(
                update(self.runs)
                .where(
                    self.runs.c.internal_run_id == run_id,
                    self.runs.c.external_run_id == external_run_id,
                    self.runs.c.status != AttemptState.CLOSED,
                )
                .values(
                    status=AttemptState.CLOSED,
                    outcome=outcome,
                    agno_status=agno_status,
                    error_fingerprint=fingerprint,
                    terminal_output=bounded_output(terminal_output),
                    updated_at=now,
                    completed_at=now,
                )
            )
            same_error_count = 0
            task_fingerprint = None
            if outcome in {AttemptOutcome.ERROR, AttemptOutcome.LOST}:
                same_error_count = (
                    int(value["same_error_count"] or 0) + 1
                    if value["error_fingerprint"] == fingerprint
                    else 1
                )
                task_fingerprint = fingerprint
            pending_rows = (
                await connection.execute(
                    select(self.instructions.c.instruction_id)
                    .where(
                        self.instructions.c.external_run_id == external_run_id,
                        self.instructions.c.status == InstructionState.PENDING,
                    )
                    .order_by(self.instructions.c.sequence)
                )
            ).all()
            next_attempt_no = int(value["continuation_count"] or 0) + 1
            if create_next:
                if next_attempt_no > MAX_CONTINUATIONS:
                    raise CodingRepositoryError(
                        "task_continuation_exhausted", "编码任务已达到续跑上限。"
                    )
                next_run_id = self.internal_run_id(external_run_id, next_attempt_no)
                await connection.execute(
                    insert(self.runs).values(
                        internal_run_id=next_run_id,
                        external_run_id=external_run_id,
                        continuation_index=next_attempt_no,
                        status=AttemptState.CREATED,
                        resume_count=0,
                        lease_epoch=lease.epoch,
                        created_at=now,
                        updated_at=now,
                    )
                )
                if pending_rows:
                    await connection.execute(
                        update(self.instructions)
                        .where(
                            self.instructions.c.external_run_id == external_run_id,
                            self.instructions.c.status == InstructionState.PENDING,
                        )
                        .values(
                            status=InstructionState.APPLIED,
                            applied_attempt_no=next_attempt_no,
                            updated_at=now,
                        )
                    )
                    same_error_count = 0
                    task_fingerprint = None
                task_values = {
                    "status": TaskState.ACTIVE,
                    "current_internal_run_id": next_run_id,
                    "continuation_count": next_attempt_no,
                }
            else:
                task_values = {"status": TaskState.SUSPENDED}
            result = await connection.execute(
                update(self.tasks)
                .where(
                    self.tasks.c.external_run_id == external_run_id,
                    self.tasks.c.state_version == expected_state_version,
                )
                .values(
                    **task_values,
                    same_error_count=same_error_count,
                    error_fingerprint=task_fingerprint,
                    state_version=self.tasks.c.state_version + 1,
                    updated_at=now,
                )
            )
            if result.rowcount != 1:
                raise CodingRepositoryError("task_cas_conflict", "任务状态已发生变化。")
        snapshot = await self.get_task_snapshot(external_run_id)
        assert snapshot is not None
        return snapshot

    async def request_finish(
        self,
        external_run_id: str,
        lease: Lease,
        expected_state_version: int,
        finish_receipt: dict[str, Any],
        *,
        result_text: str,
        retained_execution_ids: list[str],
    ) -> TaskSnapshot:
        await self.initialize()
        encoded_receipt = json.dumps(finish_receipt, sort_keys=True, separators=(",", ":"))
        if len(encoded_receipt.encode()) > MAX_TERMINAL_OUTPUT_BYTES:
            raise CodingRepositoryError("finish_receipt_too_large", "完成回执超过 64 KiB。")
        now = utcnow()
        async with self.db.db_engine.begin() as connection:  # type: ignore[attr-defined]
            task = await self._locked_task(
                connection, external_run_id, lease, expected_state_version
            )
            value = task._mapping
            if value["finish_receipt"] is not None:
                if value["finish_receipt"] != finish_receipt:
                    raise CodingRepositoryError("finish_receipt_conflict", "完成回执不可修改。")
                return self._task_snapshot(task)
            pending = (
                await connection.execute(
                    select(func.count())
                    .select_from(self.instructions)
                    .where(
                        self.instructions.c.external_run_id == external_run_id,
                        self.instructions.c.status == InstructionState.PENDING,
                    )
                )
            ).scalar_one()
            if pending:
                raise CodingRepositoryError("finish_instruction_pending", "存在待处理的新指令。")
            run_id = value["current_internal_run_id"]
            attempt_result = await connection.execute(
                update(self.runs)
                .where(
                    self.runs.c.internal_run_id == run_id,
                    self.runs.c.status.in_(
                        [AttemptState.CREATED, AttemptState.RUNNING, AttemptState.PAUSED]
                    ),
                )
                .values(status=AttemptState.FINISH_REQUESTED, updated_at=now)
            )
            if attempt_result.rowcount != 1:
                raise CodingRepositoryError("attempt_cas_conflict", "Attempt 状态已发生变化。")
            retained = set(retained_execution_ids)
            if retained:
                retained_result = await connection.execute(
                    update(self.executions)
                    .where(
                        self.executions.c.external_run_id == external_run_id,
                        self.executions.c.execution_id.in_(retained),
                        self.executions.c.status.not_in(TERMINAL_EXECUTION_STATUSES),
                    )
                    .values(retained_service=True, updated_at=now)
                )
                if retained_result.rowcount != len(retained):
                    raise CodingRepositoryError("task_cas_conflict", "保留服务状态已发生变化。")
            result = await connection.execute(
                update(self.tasks)
                .where(
                    self.tasks.c.external_run_id == external_run_id,
                    self.tasks.c.state_version == expected_state_version,
                    self.tasks.c.status.in_([TaskState.NEW, TaskState.ACTIVE, TaskState.SUSPENDED]),
                )
                .values(
                    status=TaskState.FINISHING,
                    finish_receipt=finish_receipt,
                    result_text=bounded_output(result_text),
                    state_version=self.tasks.c.state_version + 1,
                    updated_at=now,
                )
            )
            if result.rowcount != 1:
                raise CodingRepositoryError("task_cas_conflict", "任务状态已发生变化。")
        updated_task = await self.get_task_snapshot(external_run_id)
        assert updated_task is not None
        return updated_task

    async def finalize_finish(
        self,
        external_run_id: str,
        lease: Lease,
        expected_state_version: int,
        *,
        agno_status: str,
    ) -> TaskSnapshot:
        await self.initialize()
        now = utcnow()
        async with self.db.db_engine.begin() as connection:  # type: ignore[attr-defined]
            task = await self._locked_task(
                connection, external_run_id, lease, expected_state_version
            )
            value = task._mapping
            if value["status"] != TaskState.FINISHING or value["finish_receipt"] is None:
                raise CodingRepositoryError("finish_not_requested", "任务没有有效完成回执。")
            await connection.execute(
                update(self.runs)
                .where(self.runs.c.internal_run_id == value["current_internal_run_id"])
                .values(
                    status=AttemptState.CLOSED,
                    outcome=AttemptOutcome.FINISH_ACCEPTED,
                    agno_status=agno_status,
                    updated_at=now,
                    completed_at=now,
                )
            )
            result = await connection.execute(
                update(self.tasks)
                .where(
                    self.tasks.c.external_run_id == external_run_id,
                    self.tasks.c.state_version == expected_state_version,
                )
                .values(
                    status=TaskState.COMPLETED,
                    state_version=self.tasks.c.state_version + 1,
                    lease_owner=None,
                    lease_expires_at=None,
                    updated_at=now,
                    completed_at=now,
                )
            )
            if result.rowcount != 1:
                raise CodingRepositoryError("task_cas_conflict", "任务状态已发生变化。")
        snapshot = await self.get_task_snapshot(external_run_id)
        assert snapshot is not None
        return snapshot

    async def cancel_and_reject(self, scope: CodingScope) -> TaskSnapshot:
        await self.initialize()
        now = utcnow()
        async with self.db.db_engine.begin() as connection:  # type: ignore[attr-defined]
            task = (
                await connection.execute(
                    select(self.tasks).where(self.tasks.c.external_run_id == scope.external_run_id)
                )
            ).first()
            if task is None:
                raise CodingRepositoryError("task_not_found", "编码任务不存在。")
            value = task._mapping
            if any(
                value[key] != expected
                for key, expected in (
                    ("owner_user_id", scope.owner_user_id),
                    ("thread_id", scope.thread_id),
                    ("sandbox_id", scope.sandbox_id),
                    ("agent_id", scope.agent_id),
                )
            ):
                raise CodingRepositoryError("task_scope_mismatch", "编码任务范围不匹配。")
            if value["status"] in {TaskState.COMPLETED, TaskState.FAILED, TaskState.CANCELLED}:
                return self._task_snapshot(task)
            await connection.execute(
                update(self.runs)
                .where(self.runs.c.internal_run_id == value["current_internal_run_id"])
                .values(
                    status=AttemptState.CLOSED,
                    outcome=AttemptOutcome.CANCELLED,
                    updated_at=now,
                    completed_at=now,
                )
            )
            await connection.execute(
                update(self.instructions)
                .where(
                    self.instructions.c.external_run_id == scope.external_run_id,
                    self.instructions.c.status == InstructionState.PENDING,
                )
                .values(
                    status=InstructionState.REJECTED,
                    rejection_code="coding_task_cancelled",
                    updated_at=now,
                )
            )
            await connection.execute(
                update(self.tasks)
                .where(self.tasks.c.external_run_id == scope.external_run_id)
                .values(
                    status=TaskState.CANCELLED,
                    state_version=self.tasks.c.state_version + 1,
                    lease_epoch=self.tasks.c.lease_epoch + 1,
                    lease_owner=None,
                    lease_expires_at=None,
                    updated_at=now,
                    completed_at=now,
                )
            )
        snapshot = await self.get_task_snapshot(scope.external_run_id)
        assert snapshot is not None
        return snapshot

    async def fail_indeterminate_mutation(
        self, scope: CodingScope, current_epoch: int
    ) -> TaskSnapshot:
        await self.initialize()
        now = utcnow()
        async with self.db.db_engine.begin() as connection:  # type: ignore[attr-defined]
            task = (
                await connection.execute(
                    select(self.tasks).where(
                        self.tasks.c.external_run_id == scope.external_run_id,
                        self.tasks.c.owner_user_id == scope.owner_user_id,
                        self.tasks.c.thread_id == scope.thread_id,
                        self.tasks.c.sandbox_id == scope.sandbox_id,
                        self.tasks.c.agent_id == scope.agent_id,
                        self.tasks.c.lease_epoch == current_epoch,
                        self.tasks.c.status.in_(
                            [TaskState.NEW, TaskState.ACTIVE, TaskState.SUSPENDED]
                        ),
                    )
                )
            ).first()
            if task is None:
                raise CodingRepositoryError("task_cas_conflict", "任务 epoch 已发生变化。")
            value = task._mapping
            await connection.execute(
                update(self.runs)
                .where(self.runs.c.internal_run_id == value["current_internal_run_id"])
                .values(
                    status=AttemptState.CLOSED,
                    outcome=AttemptOutcome.ERROR,
                    agno_status="lost",
                    error_fingerprint=error_fingerprint("workspace_mutation_indeterminate"),
                    updated_at=now,
                    completed_at=now,
                )
            )
            await connection.execute(
                update(self.instructions)
                .where(
                    self.instructions.c.external_run_id == scope.external_run_id,
                    self.instructions.c.status == InstructionState.PENDING,
                )
                .values(
                    status=InstructionState.REJECTED,
                    rejection_code="workspace_mutation_indeterminate",
                    updated_at=now,
                )
            )
            await connection.execute(
                update(self.tasks)
                .where(self.tasks.c.external_run_id == scope.external_run_id)
                .values(
                    status=TaskState.FAILED,
                    result_text="workspace_mutation_indeterminate",
                    state_version=self.tasks.c.state_version + 1,
                    lease_owner=None,
                    lease_expires_at=None,
                    updated_at=now,
                    completed_at=now,
                )
            )
        snapshot = await self.get_task_snapshot(scope.external_run_id)
        assert snapshot is not None
        return snapshot

    async def fail_closed_task(
        self, external_run_id: str, expected_state_version: int, code: str
    ) -> TaskSnapshot:
        await self.initialize()
        now = utcnow()
        async with self.db.db_engine.begin() as connection:  # type: ignore[attr-defined]
            result = await connection.execute(
                update(self.tasks)
                .where(
                    self.tasks.c.external_run_id == external_run_id,
                    self.tasks.c.state_version == expected_state_version,
                    self.tasks.c.status == TaskState.SUSPENDED,
                )
                .values(
                    status=TaskState.FAILED,
                    result_text=code,
                    state_version=self.tasks.c.state_version + 1,
                    lease_owner=None,
                    lease_expires_at=None,
                    updated_at=now,
                    completed_at=now,
                )
            )
        if result.rowcount != 1:
            raise CodingRepositoryError("task_cas_conflict", "任务失败状态已发生变化。")
        snapshot = await self.get_task_snapshot(external_run_id)
        assert snapshot is not None
        return snapshot

    async def _locked_task(
        self,
        connection: Any,
        external_run_id: str,
        lease: Lease,
        expected_state_version: int,
    ) -> Any:
        task = (
            await connection.execute(
                select(self.tasks).where(
                    self.tasks.c.external_run_id == external_run_id,
                    self.tasks.c.state_version == expected_state_version,
                    self.tasks.c.lease_owner == lease.owner,
                    self.tasks.c.lease_epoch == lease.epoch,
                    self.tasks.c.lease_expires_at > utcnow(),
                )
            )
        ).first()
        if task is None:
            raise CodingRepositoryError("task_cas_conflict", "任务状态或租约已发生变化。")
        return task

    async def _required_current(self, external_run_id: str) -> tuple[TaskSnapshot, AttemptSnapshot]:
        task = await self.get_task_snapshot(external_run_id)
        if task is None:
            raise CodingRepositoryError("task_not_found", "编码任务不存在。")
        attempt = await self.get_attempt(task.current_internal_run_id)
        if attempt is None:
            raise CodingRepositoryError("attempt_not_found", "当前 Attempt 不存在。")
        return task, attempt


__all__ = [
    "ACTIVE_TASK_STATUSES",
    "MAX_CONTINUATIONS",
    "MAX_INSTRUCTION_BYTES",
    "MAX_INSTRUCTION_ID_LENGTH",
    "MAX_PENDING_INSTRUCTIONS",
    "MAX_PENDING_INSTRUCTION_BYTES",
    "MAX_TERMINAL_OUTPUT_BYTES",
    "TASK_RETENTION",
    "TASK_SCHEMA_VERSION",
    "TERMINAL_EXECUTION_STATUSES",
    "TERMINAL_TASK_STATUSES",
    "CodingExecution",
    "CodingRepositoryError",
    "CodingTask",
    "CodingTaskRepository",
    "bounded_output",
    "error_fingerprint",
    "utcnow",
]

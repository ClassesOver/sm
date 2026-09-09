"""ReportingRunState 的 SQLAlchemy 持久化边界。"""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

import anyio
from agno.db.base import AsyncBaseDb
from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    MetaData,
    String,
    Table,
    insert,
    select,
    text,
    update,
)
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.exc import IntegrityError

from .state import (
    REPORTING_STATE_SCHEMA_VERSION,
    ReportingCommand,
    ReportingReducerResult,
    ReportingRunState,
    ReportingStateConflict,
    ReportingStateError,
    ReportingStateReducer,
    ReportingStateVersionUnsupported,
)

REPORTING_DB_SCHEMA = "agentos_reporting"
_REPORTING_SCHEMA_LOCK_KEY = 1_381_125_712
_WORKFLOW_THREAD_LOCK_WAIT_SECONDS = 2.0
_WORKFLOW_THREAD_LOCK_RETRY_DELAY_SECONDS = 0.1


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _command_fingerprint(command: ReportingCommand) -> str:
    payload = json.dumps(
        {"name": command.name, "payload": command.payload},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


class ReportingStateRepository:
    """Reporting 专属状态仓储；不复用 Reporting task 的业务列或 session checkpoint。"""

    def __init__(self, db: AsyncBaseDb):
        self.db = db
        dialect = db.db_engine.dialect.name  # type: ignore[attr-defined]
        if dialect != "postgresql":
            raise ValueError("Reporting 状态仓储只支持 PostgreSQL。")
        self.metadata = MetaData(schema=REPORTING_DB_SCHEMA)
        self.runs = Table(
            "reporting_runs",
            self.metadata,
            Column("report_run_id", String(256), primary_key=True),
            Column("external_run_id", String(256), nullable=False, unique=True),
            Column("entrypoint", String(32), nullable=False),
            Column("workflow_id", String(256), nullable=False),
            Column("agno_session_id", String(256), nullable=False),
            Column("agno_run_id", String(256), nullable=False),
            Column("caller_session_id", String(256)),
            Column("caller_run_id", String(256)),
            Column("thread_id", String(256), nullable=False),
            Column("owner_user_id", String(256), nullable=False),
            Column("database", String(256), nullable=False),
            Column("company_id", String(256), nullable=False),
            Column("revision", BigInteger, nullable=False),
            Column("status", String(32), nullable=False),
            Column("finalization_pending", Boolean, nullable=False, default=False),
            Column("created_at", DateTime(timezone=True), nullable=False),
            Column("started_at", DateTime(timezone=True)),
            Column("finished_at", DateTime(timezone=True)),
            Column("updated_at", DateTime(timezone=True), nullable=False),
            Index("ix_reporting_runs_agno_session_updated", "agno_session_id", "updated_at"),
            Index("ix_reporting_runs_thread_status", "thread_id", "status"),
            Index(
                "uq_reporting_runs_agno_identity",
                "agno_session_id",
                "agno_run_id",
                unique=True,
            ),
        )
        self.states = Table(
            "reporting_run_states",
            self.metadata,
            Column(
                "report_run_id",
                String(256),
                ForeignKey(
                    f"{REPORTING_DB_SCHEMA}.reporting_runs.report_run_id",
                    name="fk_reporting_run_states_report_run_id",
                ),
                primary_key=True,
            ),
            Column("external_run_id", String(256), nullable=False, unique=True),
            Column("thread_id", String(256), nullable=False),
            Column("owner_user_id", String(256), nullable=False),
            Column("revision", BigInteger, nullable=False),
            Column("schema_version", BigInteger, nullable=False),
            Column("state_version", BigInteger, nullable=False),
            Column("phase", String(64), nullable=False),
            Column("payload", JSON, nullable=False),
            Column("created_at", DateTime(timezone=True), nullable=False),
            Column("updated_at", DateTime(timezone=True), nullable=False),
        )
        self.command_receipts = Table(
            "reporting_command_receipts",
            self.metadata,
            Column(
                "report_run_id",
                String(256),
                ForeignKey(
                    f"{REPORTING_DB_SCHEMA}.reporting_runs.report_run_id",
                    name="fk_reporting_command_receipts_report_run_id",
                ),
                primary_key=True,
            ),
            Column("command_id", String(256), primary_key=True),
            Column("fingerprint", String(64), nullable=False),
            Column("created_at", DateTime(timezone=True), nullable=False),
        )
        self.workflow_thread_owners = Table(
            "reporting_workflow_thread_owners",
            self.metadata,
            Column("thread_id", String(256), primary_key=True),
            Column(
                "report_run_id",
                String(256),
                ForeignKey(
                    f"{REPORTING_DB_SCHEMA}.reporting_runs.report_run_id",
                    name="fk_reporting_workflow_thread_owners_report_run_id",
                ),
            ),
            Column("external_run_id", String(256), nullable=False),
            Column("owner_user_id", String(256), nullable=False),
            Column("created_at", DateTime(timezone=True), nullable=False),
            Index("ix_reporting_workflow_thread_owners_report_run_id", "report_run_id"),
        )
        self.mcp_requests = Table(
            "reporting_mcp_requests",
            self.metadata,
            Column("external_run_id", String(256), primary_key=True),
            Column(
                "report_run_id",
                String(256),
                ForeignKey(
                    f"{REPORTING_DB_SCHEMA}.reporting_runs.report_run_id",
                    name="fk_reporting_mcp_requests_report_run_id",
                ),
            ),
            Column("request_fingerprint", String(64), nullable=False),
            Column("thread_id", String(256), nullable=False),
            Column("owner_user_id", String(256), nullable=False),
            Column("database", String(256), nullable=False),
            Column("company_id", String(256), nullable=False),
            Column("created_at", DateTime(timezone=True), nullable=False),
            Index("ix_reporting_mcp_requests_report_run_id", "report_run_id"),
        )
        self._initialized = False
        shared_lock = getattr(db, "_agentos_reporting_state_initialize_lock", None)
        if shared_lock is None:
            shared_lock = asyncio.Lock()
            setattr(db, "_agentos_reporting_state_initialize_lock", shared_lock)
        self._initialize_lock = shared_lock

    async def initialize(self) -> None:
        if self._initialized:
            return
        async with self._initialize_lock:
            if self._initialized:
                return
            async with self.db.db_engine.begin() as connection:  # type: ignore[attr-defined]
                await connection.execute(
                    text("SELECT pg_advisory_xact_lock(:lock_key)"),
                    {"lock_key": _REPORTING_SCHEMA_LOCK_KEY},
                )
                await connection.execute(
                    text(f'CREATE SCHEMA IF NOT EXISTS "{REPORTING_DB_SCHEMA}"')
                )
                await connection.run_sync(self.metadata.create_all)
                for table_name in ("reporting_mcp_requests", "reporting_workflow_thread_owners"):
                    await connection.execute(
                        text(
                            f'ALTER TABLE "{REPORTING_DB_SCHEMA}"."{table_name}" '
                            'ADD COLUMN IF NOT EXISTS report_run_id VARCHAR(256)'
                        )
                    )
                upgrade_statements = self._legacy_upgrade_statements()
                await connection.execute(text(upgrade_statements[0]))
                conflict = await connection.scalar(
                    text(self._legacy_parent_conflict_query())
                )
                if conflict:
                    raise ReportingStateError(
                        "report_run_legacy_identity_conflict",
                        "Legacy Reporting 状态与父运行身份冲突。",
                    )
                for statement in upgrade_statements[1:]:
                    await connection.execute(text(statement))
            self._initialized = True

    @staticmethod
    def _legacy_parent_conflict_query() -> str:
        schema = REPORTING_DB_SCHEMA
        return f"""
            SELECT EXISTS (
                SELECT 1
                FROM {schema}.reporting_run_states AS state
                LEFT JOIN {schema}.reporting_runs AS run
                  ON run.report_run_id = state.report_run_id
                WHERE run.report_run_id IS NULL
                   OR run.external_run_id IS DISTINCT FROM state.external_run_id
                   OR run.agno_run_id IS DISTINCT FROM state.report_run_id
                   OR run.thread_id IS DISTINCT FROM state.thread_id
                   OR run.owner_user_id IS DISTINCT FROM state.owner_user_id
                   OR run.revision IS DISTINCT FROM state.revision
            )
        """

    @staticmethod
    def _legacy_upgrade_statements() -> tuple[str, ...]:
        schema = REPORTING_DB_SCHEMA
        statements = [
            f"""
            INSERT INTO {schema}.reporting_runs (
                report_run_id, external_run_id, entrypoint, workflow_id,
                agno_session_id, agno_run_id, caller_session_id, caller_run_id,
                thread_id, owner_user_id, database, company_id, revision, status,
                finalization_pending, created_at, started_at, finished_at, updated_at
            )
            SELECT
                state.report_run_id, state.external_run_id, 'unknown',
                'enterprise-reporting-workflow-v1', state.thread_id, state.report_run_id,
                NULL, NULL, state.thread_id, state.owner_user_id, 'default', 'default',
                state.revision,
                CASE
                    WHEN state.phase = 'completed' THEN 'completed'
                    WHEN state.phase = 'failed' THEN 'failed'
                    ELSE 'running'
                END,
                FALSE, state.created_at, state.created_at,
                CASE
                    WHEN state.phase IN ('completed', 'failed') THEN state.updated_at
                    ELSE NULL
                END,
                state.updated_at
            FROM {schema}.reporting_run_states AS state
            ON CONFLICT DO NOTHING
            """,
            f"""
            UPDATE {schema}.reporting_workflow_thread_owners AS owner
            SET report_run_id = run.report_run_id
            FROM {schema}.reporting_runs AS run
            WHERE owner.report_run_id IS NULL
              AND owner.external_run_id = run.external_run_id
            """,
            f"""
            UPDATE {schema}.reporting_mcp_requests AS request
            SET report_run_id = run.report_run_id
            FROM {schema}.reporting_runs AS run
            WHERE request.report_run_id IS NULL
              AND request.external_run_id = run.external_run_id
            """,
            f"CREATE INDEX IF NOT EXISTS ix_reporting_workflow_thread_owners_report_run_id "
            f"ON {schema}.reporting_workflow_thread_owners (report_run_id)",
            f"CREATE INDEX IF NOT EXISTS ix_reporting_mcp_requests_report_run_id "
            f"ON {schema}.reporting_mcp_requests (report_run_id)",
        ]
        constraints = (
            ("reporting_run_states", "fk_reporting_run_states_report_run_id"),
            ("reporting_command_receipts", "fk_reporting_command_receipts_report_run_id"),
            (
                "reporting_workflow_thread_owners",
                "fk_reporting_workflow_thread_owners_report_run_id",
            ),
            ("reporting_mcp_requests", "fk_reporting_mcp_requests_report_run_id"),
        )
        for table_name, constraint_name in constraints:
            statements.extend(
                (
                    f"""
                    DO $$
                    BEGIN
                        IF NOT EXISTS (
                            SELECT 1 FROM pg_constraint
                            WHERE conname = '{constraint_name}'
                              AND conrelid = '{schema}.{table_name}'::regclass
                        ) THEN
                            ALTER TABLE {schema}.{table_name}
                            ADD CONSTRAINT {constraint_name}
                            FOREIGN KEY (report_run_id)
                            REFERENCES {schema}.reporting_runs (report_run_id)
                            NOT VALID;
                        END IF;
                    END $$
                    """,
                    f"ALTER TABLE {schema}.{table_name} "
                    f"VALIDATE CONSTRAINT {constraint_name}",
                )
            )
        return tuple(statements)

    async def register_run(self, **values: Any) -> dict[str, Any]:
        """登记 Reporting 顶层运行及其 Agno 身份；重复登记只读取首条绑定。"""

        await self.initialize()
        now = datetime.now(UTC)
        row_values = {
            "report_run_id": str(values["report_run_id"]),
            "external_run_id": str(values["external_run_id"]),
            "entrypoint": str(values.get("entrypoint") or "unknown"),
            "workflow_id": str(values.get("workflow_id") or "enterprise-reporting-workflow-v1"),
            "agno_session_id": str(values["agno_session_id"]),
            "agno_run_id": str(values["agno_run_id"]),
            "caller_session_id": (
                str(values["caller_session_id"])
                if values.get("caller_session_id") is not None
                else None
            ),
            "caller_run_id": (
                str(values["caller_run_id"])
                if values.get("caller_run_id") is not None
                else None
            ),
            "thread_id": str(values["thread_id"]),
            "owner_user_id": str(values["owner_user_id"]),
            "database": str(values.get("database") or "default"),
            "company_id": str(values.get("company_id") or "default"),
            "revision": int(values.get("revision") or 1),
            "status": str(values.get("status") or "running"),
            "finalization_pending": bool(values.get("finalization_pending")),
            "created_at": values.get("created_at") or now,
            "started_at": values.get("started_at") or now,
            "updated_at": values.get("updated_at") or now,
        }
        async with self.db.db_engine.begin() as connection:  # type: ignore[attr-defined]
            statement: Any = postgresql_insert(self.runs).values(**row_values)
            statement = statement.on_conflict_do_nothing(
                index_elements=[self.runs.c.report_run_id]
            )
            try:
                await connection.execute(statement)
            except IntegrityError as error:
                raise ReportingStateError(
                    "report_run_identity_conflict", "Reporting run 身份绑定冲突。"
                ) from error
            row = (
                await connection.execute(
                    select(self.runs)
                    .where(self.runs.c.report_run_id == row_values["report_run_id"])
                    .with_for_update()
                )
            ).first()
            if row is None:
                raise ReportingStateError(
                    "report_run_registration_failed", "Reporting run 登记失败。"
                )
            stored = dict(row._mapping)
            core_identity_keys = (
                "external_run_id",
                "agno_run_id",
                "thread_id",
                "owner_user_id",
                "revision",
            )
            self._assert_run_identity(stored, row_values, core_identity_keys)
            if stored["entrypoint"] == "unknown" and row_values["entrypoint"] != "unknown":
                upgrade_values = {
                    key: row_values[key]
                    for key in (
                        "entrypoint",
                        "workflow_id",
                        "agno_session_id",
                        "caller_session_id",
                        "caller_run_id",
                        "database",
                        "company_id",
                    )
                }
                try:
                    result = await connection.execute(
                        update(self.runs)
                        .where(
                            self.runs.c.report_run_id == row_values["report_run_id"],
                            self.runs.c.entrypoint == "unknown",
                            *(self.runs.c[key] == row_values[key] for key in core_identity_keys),
                        )
                        .values(**upgrade_values)
                    )
                except IntegrityError as error:
                    raise ReportingStateError(
                        "report_run_identity_conflict", "Reporting run 身份绑定冲突。"
                    ) from error
                if result.rowcount != 1:
                    raise ReportingStateError(
                        "report_run_identity_conflict", "Reporting run 身份绑定冲突。"
                    )
                row = (
                    await connection.execute(
                        select(self.runs).where(
                            self.runs.c.report_run_id == row_values["report_run_id"]
                        )
                    )
                ).first()
                if row is None:
                    raise ReportingStateError(
                        "report_run_registration_failed", "Reporting run 登记失败。"
                    )
                stored = dict(row._mapping)
            if row_values["entrypoint"] != "unknown":
                self._assert_run_identity(
                    stored,
                    row_values,
                    (
                        "entrypoint",
                        "workflow_id",
                        "agno_session_id",
                        "caller_session_id",
                        "caller_run_id",
                        "database",
                        "company_id",
                    ),
                )
        return stored

    @staticmethod
    def _assert_run_identity(
        stored: Mapping[str, Any], expected: Mapping[str, Any], keys: tuple[str, ...]
    ) -> None:
        if any(stored[key] != expected[key] for key in keys):
            raise ReportingStateError(
                "report_run_identity_conflict", "Reporting run 身份绑定冲突。"
            )

    async def attach_request_run(self, external_run_id: str, report_run_id: str) -> None:
        await self.initialize()
        async with self.db.db_engine.begin() as connection:  # type: ignore[attr-defined]
            result = await connection.execute(
                update(self.mcp_requests)
                .where(self.mcp_requests.c.external_run_id == external_run_id)
                .values(report_run_id=report_run_id)
            )
        if result.rowcount != 1:
            raise ReportingStateError(
                "report_mcp_request_not_found", "Reporting MCP 请求不存在。"
            )

    async def attach_workflow_owner_run(
        self,
        *,
        thread_id: str,
        external_run_id: str,
        owner_user_id: str,
        report_run_id: str,
    ) -> None:
        await self.initialize()
        async with self.db.db_engine.begin() as connection:  # type: ignore[attr-defined]
            result = await connection.execute(
                update(self.workflow_thread_owners)
                .where(
                    self.workflow_thread_owners.c.thread_id == thread_id,
                    self.workflow_thread_owners.c.external_run_id == external_run_id,
                    self.workflow_thread_owners.c.owner_user_id == owner_user_id,
                )
                .values(report_run_id=report_run_id)
            )
        if result.rowcount != 1:
            raise ReportingStateError(
                "report_workflow_owner_not_found", "Reporting workflow owner 不存在。"
            )

    async def update_run_status(
        self,
        report_run_id: str,
        *,
        status: str,
        finalization_pending: bool | None = None,
    ) -> None:
        await self.initialize()
        now = datetime.now(UTC)
        values: dict[str, Any] = {
            "status": status,
            "updated_at": now,
        }
        if finalization_pending is not None:
            values["finalization_pending"] = finalization_pending
        values["finished_at"] = (
            now if status in {"completed", "cancelled", "failed"} else None
        )
        async with self.db.db_engine.begin() as connection:  # type: ignore[attr-defined]
            result = await connection.execute(
                update(self.runs)
                .where(self.runs.c.report_run_id == report_run_id)
                .values(**values)
            )
        if result.rowcount != 1:
            raise ReportingStateError("report_run_not_found", "Reporting run 不存在。")

    @staticmethod
    def _state_from_row(row: Any) -> ReportingRunState:
        if row is None:
            raise ReportingStateError("report_state_not_found", "Reporting 运行状态不存在。")
        value = row._mapping
        schema_version = int(value["schema_version"])
        if schema_version != REPORTING_STATE_SCHEMA_VERSION:
            raise ReportingStateVersionUnsupported()
        try:
            return ReportingRunState.model_validate(
                {
                    "reportRunId": value["report_run_id"],
                    "externalRunId": value["external_run_id"],
                    "threadId": value["thread_id"],
                    "ownerUserId": value["owner_user_id"],
                    "revision": int(value["revision"]),
                    "schemaVersion": schema_version,
                    "stateVersion": int(value["state_version"]),
                    "phase": value["phase"],
                    "payload": value["payload"] if isinstance(value["payload"], dict) else {},
                    "createdAt": _utc(value["created_at"]),
                    "updatedAt": _utc(value["updated_at"]),
                }
            )
        except ReportingStateVersionUnsupported:
            raise
        except Exception as error:
            raise ReportingStateError(
                "report_state_invalid", "Reporting 运行状态数据无效。"
            ) from error

    async def get(self, report_run_id: str) -> ReportingRunState | None:
        await self.initialize()
        async with self.db.db_engine.connect() as connection:  # type: ignore[attr-defined]
            row = (
                await connection.execute(
                    select(self.states).where(self.states.c.report_run_id == report_run_id)
                )
            ).first()
        return self._state_from_row(row) if row is not None else None

    async def get_by_external_run_id(self, external_run_id: str) -> ReportingRunState | None:
        await self.initialize()
        async with self.db.db_engine.connect() as connection:  # type: ignore[attr-defined]
            row = (
                await connection.execute(
                    select(self.states).where(self.states.c.external_run_id == external_run_id)
                )
            ).first()
        return self._state_from_row(row) if row is not None else None

    async def get_run(self, report_run_id: str) -> dict[str, Any] | None:
        await self.initialize()
        async with self.db.db_engine.connect() as connection:  # type: ignore[attr-defined]
            row = (
                await connection.execute(
                    select(self.runs).where(self.runs.c.report_run_id == report_run_id)
                )
            ).first()
        return dict(row._mapping) if row is not None else None

    async def get_run_by_external(self, external_run_id: str) -> dict[str, Any] | None:
        await self.initialize()
        async with self.db.db_engine.connect() as connection:  # type: ignore[attr-defined]
            row = (
                await connection.execute(
                    select(self.runs).where(self.runs.c.external_run_id == external_run_id)
                )
            ).first()
        return dict(row._mapping) if row is not None else None

    async def claim_workflow_thread(
        self, *, thread_id: str, external_run_id: str, owner_user_id: str
    ) -> bool:
        """原子占用 thread；暂停期间所有权继续保存在数据库中。"""

        await self.initialize()
        async with self.db.db_engine.connect() as connection:  # type: ignore[attr-defined]
            report_run_id = await connection.scalar(
                select(self.runs.c.report_run_id).where(
                    self.runs.c.external_run_id == external_run_id
                )
            )
        values = {
            "thread_id": thread_id,
            "report_run_id": report_run_id,
            "external_run_id": external_run_id,
            "owner_user_id": owner_user_id,
            "created_at": datetime.now(UTC),
        }
        async with self.db.db_engine.begin() as connection:  # type: ignore[attr-defined]
            statement: Any = postgresql_insert(self.workflow_thread_owners).values(**values)
            statement = statement.on_conflict_do_nothing(
                index_elements=[self.workflow_thread_owners.c.thread_id]
            ).returning(self.workflow_thread_owners.c.thread_id)
            try:
                result = await connection.execute(statement)
            except IntegrityError:
                return False
        return result.scalar_one_or_none() == thread_id

    async def register_external_request(self, **values: str) -> dict[str, Any]:
        """首次请求永久绑定租户作用域和 payload 指纹，跨进程重试不得改写。"""

        await self.initialize()
        row_values = {
            "external_run_id": values["external_run_id"],
            "request_fingerprint": values["request_fingerprint"],
            "thread_id": values["thread_id"],
            "owner_user_id": values["owner_user_id"],
            "database": values["database"],
            "company_id": values["company_id"],
            "created_at": datetime.now(UTC),
        }
        async with self.db.db_engine.begin() as connection:  # type: ignore[attr-defined]
            statement: Any = postgresql_insert(self.mcp_requests).values(**row_values)
            statement = statement.on_conflict_do_nothing(
                index_elements=[self.mcp_requests.c.external_run_id]
            )
            await connection.execute(statement)
            row = (
                await connection.execute(
                    select(self.mcp_requests).where(
                        self.mcp_requests.c.external_run_id == values["external_run_id"]
                    )
                )
            ).first()
        if row is None:
            raise ReportingStateError(
                "report_workflow_reservation_failed", "Reporting MCP 请求幂等记录不存在。"
            )
        stored = row._mapping
        return {
            "external_run_id": str(stored["external_run_id"]),
            "request_fingerprint": str(stored["request_fingerprint"]),
            "thread_id": str(stored["thread_id"]),
            "owner_user_id": str(stored["owner_user_id"]),
            "database": str(stored["database"]),
            "company_id": str(stored["company_id"]),
        }

    async def get_workflow_thread_owner(self, thread_id: str) -> dict[str, Any] | None:
        """读取 thread owner，供控制器核验旧 run 终态和安全回收孤儿记录。"""

        await self.initialize()
        async with self.db.db_engine.connect() as connection:  # type: ignore[attr-defined]
            row = (
                await connection.execute(
                    select(self.workflow_thread_owners).where(
                        self.workflow_thread_owners.c.thread_id == thread_id
                    )
                )
            ).first()
        if row is None:
            return None
        value = row._mapping
        return {
            "thread_id": str(value["thread_id"]),
            "report_run_id": str(value["report_run_id"]) if value.get("report_run_id") else None,
            "external_run_id": str(value["external_run_id"]),
            "owner_user_id": str(value["owner_user_id"]),
            "created_at": _utc(value["created_at"]),
        }

    async def ensure_workflow_thread_owner(
        self, *, thread_id: str, external_run_id: str, owner_user_id: str
    ) -> bool:
        """在同一事务内恢复 owner，避免检查后被其他 run 替换。"""

        await self.initialize()
        async with self.db.db_engine.connect() as connection:  # type: ignore[attr-defined]
            report_run_id = await connection.scalar(
                select(self.runs.c.report_run_id).where(
                    self.runs.c.external_run_id == external_run_id
                )
            )
        values = {
            "thread_id": thread_id,
            "report_run_id": report_run_id,
            "external_run_id": external_run_id,
            "owner_user_id": owner_user_id,
            "created_at": datetime.now(UTC),
        }
        async with self.db.db_engine.begin() as connection:  # type: ignore[attr-defined]
            statement = postgresql_insert(self.workflow_thread_owners).values(**values)
            statement = statement.on_conflict_do_nothing(
                index_elements=[self.workflow_thread_owners.c.thread_id]
            )
            try:
                await connection.execute(statement)
            except IntegrityError:
                return False
            query = (
                select(
                    self.workflow_thread_owners.c.external_run_id,
                    self.workflow_thread_owners.c.owner_user_id,
                )
                .where(self.workflow_thread_owners.c.thread_id == thread_id)
                .with_for_update()
            )
            row = (await connection.execute(query)).first()
        return row is not None and tuple(row) == (external_run_id, owner_user_id)

    async def release_workflow_thread(
        self, *, thread_id: str, external_run_id: str, owner_user_id: str
    ) -> bool:
        """只释放完整身份匹配的所有权，避免旧运行删除新运行的记录。"""

        await self.initialize()
        async with self.db.db_engine.begin() as connection:  # type: ignore[attr-defined]
            result = await connection.execute(
                self.workflow_thread_owners.delete().where(
                    self.workflow_thread_owners.c.thread_id == thread_id,
                    self.workflow_thread_owners.c.external_run_id == external_run_id,
                    self.workflow_thread_owners.c.owner_user_id == owner_user_id,
                )
            )
        return result.rowcount == 1

    async def create(self, state: ReportingRunState) -> ReportingRunState:
        await self.initialize()
        if state.schema_version != REPORTING_STATE_SCHEMA_VERSION:
            raise ReportingStateVersionUnsupported()
        await self.register_run(
            report_run_id=state.report_run_id,
            external_run_id=state.external_run_id,
            entrypoint="unknown",
            agno_session_id=state.thread_id,
            agno_run_id=state.report_run_id,
            thread_id=state.thread_id,
            owner_user_id=state.owner_user_id,
            revision=state.revision,
            status=(
                "completed"
                if state.phase.value == "completed"
                else "failed"
                if state.phase.value == "failed"
                else "running"
            ),
            created_at=state.created_at,
            updated_at=state.updated_at,
        )
        values = self._row_values(state)
        try:
            async with self.db.db_engine.begin() as connection:  # type: ignore[attr-defined]
                await connection.execute(insert(self.states).values(**values))
        except IntegrityError:
            existing = await self.get(state.report_run_id)
            if existing is None:
                raise ReportingStateError("report_state_create_failed", "Reporting 状态创建失败。")
            self._assert_binding(existing, state)
            return existing
        return state

    async def get_or_create(
        self,
        *,
        report_run_id: str,
        external_run_id: str,
        thread_id: str,
        owner_user_id: str,
        revision: int = 1,
        payload: Mapping[str, Any] | None = None,
    ) -> ReportingRunState:
        existing = await self.get(report_run_id)
        if existing is not None:
            if (
                existing.external_run_id != external_run_id
                or existing.thread_id != thread_id
                or existing.owner_user_id != owner_user_id
                or existing.revision != revision
            ):
                raise ReportingStateError(
                    "report_state_binding_conflict", "Reporting 状态绑定不一致。"
                )
            return existing
        return await self.create(
            ReportingRunState.initial(
                report_run_id=report_run_id,
                external_run_id=external_run_id,
                thread_id=thread_id,
                owner_user_id=owner_user_id,
                revision=revision,
                payload=payload,
            )
        )

    async def apply(
        self,
        report_run_id: str,
        command: ReportingCommand | Mapping[str, Any] | str,
        *,
        expected_version: int,
    ) -> ReportingReducerResult:
        """在同一事务中读取、reduce 并执行 ``WHERE id AND state_version`` 更新。"""

        await self.initialize()
        command_value = ReportingCommand.from_value(command)
        async with self.db.db_engine.begin() as connection:  # type: ignore[attr-defined]
            row = (
                await connection.execute(
                    select(self.states).where(self.states.c.report_run_id == report_run_id)
                )
            ).first()
            current = self._state_from_row(row)
            if current.schema_version != REPORTING_STATE_SCHEMA_VERSION:
                raise ReportingStateVersionUnsupported()
            if current.report_run_id != report_run_id:
                raise ReportingStateError(
                    "report_state_binding_conflict", "Reporting 状态绑定不一致。"
                )
            receipt = (
                await connection.execute(
                    select(self.command_receipts).where(
                        self.command_receipts.c.report_run_id == report_run_id,
                        self.command_receipts.c.command_id == command_value.command_id,
                    )
                )
            ).first()
            if receipt is not None:
                self._assert_receipt_fingerprint(receipt._mapping["fingerprint"], command_value)
                return ReportingReducerResult(state=current, idempotent=True)

            applied = current.payload.get("appliedCommands", {})
            if isinstance(applied, Mapping) and command_value.command_id in applied:
                stored = applied[command_value.command_id]
                if isinstance(stored, Mapping) and stored.get("fingerprint") not in {
                    None,
                    _command_fingerprint(command_value),
                }:
                    raise ReportingStateError(
                        "report_command_replay_conflict", "幂等键已绑定其他 command。"
                    )
                await self._insert_command_receipts(
                    connection,
                    [
                        *self._receipt_values(report_run_id, applied),
                        {
                            "report_run_id": report_run_id,
                            "command_id": command_value.command_id,
                            "fingerprint": _command_fingerprint(command_value),
                            "created_at": datetime.now(UTC),
                        },
                    ],
                )
                return ReportingReducerResult(state=current, idempotent=True)
            if current.state_version != expected_version:
                raise ReportingStateConflict()
            result = ReportingStateReducer.apply(current, command_value, expected_version)
            # reducer payload 中也记录 command fingerprint，保证同一 command_id 不能换参重放。
            result.state.payload.setdefault("appliedCommands", {}).setdefault(
                command_value.command_id, {}
            )["fingerprint"] = _command_fingerprint(command_value)
            needs_receipt_backfill = current.payload.get("commandReceiptsVersion") != 1
            result.state.payload["commandReceiptsVersion"] = 1
            values = self._row_values(result.state)
            updated = await connection.execute(
                update(self.states)
                .where(
                    self.states.c.report_run_id == report_run_id,
                    self.states.c.state_version == expected_version,
                )
                .values(**values)
            )
            if updated.rowcount != 1:
                raise ReportingStateConflict()
            receipts = (
                self._receipt_values(report_run_id, applied) if needs_receipt_backfill else []
            )
            receipts.append(
                {
                    "report_run_id": report_run_id,
                    "command_id": command_value.command_id,
                    "fingerprint": _command_fingerprint(command_value),
                    "created_at": datetime.now(UTC),
                }
            )
            await self._insert_command_receipts(connection, receipts)
            status = (
                "failed"
                if result.state.phase.value == "failed"
                else "running"
            )
            await connection.execute(
                update(self.runs)
                .where(self.runs.c.report_run_id == report_run_id)
                .values(
                    status=status,
                    updated_at=result.state.updated_at,
                    finished_at=(
                        result.state.updated_at
                        if status == "failed"
                        else None
                    ),
                )
            )
            return result

    @asynccontextmanager
    async def workflow_execution_lock(self, external_run_id: str) -> AsyncIterator[None]:
        """同一 Reporting run 只能由一个 CLI 进程推进。"""

        engine = self.db.db_engine  # type: ignore[attr-defined]
        lock_key = self._workflow_execution_lock_key(external_run_id)
        async with engine.connect() as connection:
            acquired = bool(
                await connection.scalar(
                    text("SELECT pg_try_advisory_lock(hashtextextended(:lock_key, 0))"),
                    {"lock_key": lock_key},
                )
            )
            await connection.commit()
            if not acquired:
                raise ReportingStateError(
                    "report_workflow_run_conflict", "Reporting run 正由其他进程执行。"
                )
            try:
                yield
            finally:
                # session advisory lock 必须在连接回池前显式释放；屏蔽调用方取消，
                # 进程异常退出时 PostgreSQL 仍会随连接关闭自动回收该锁。
                with anyio.CancelScope(shield=True):
                    await connection.execute(
                        text("SELECT pg_advisory_unlock(hashtextextended(:lock_key, 0))"),
                        {"lock_key": lock_key},
                    )
                    await connection.commit()

    @staticmethod
    def _workflow_execution_lock_key(external_run_id: str) -> str:
        return f"reporting-workflow-execution:{external_run_id}"

    @asynccontextmanager
    async def workflow_thread_lifecycle_lock(self, thread_id: str) -> AsyncIterator[None]:
        """串行化同一 thread 的 workspace 清理与 owner 交接。"""

        engine = self.db.db_engine  # type: ignore[attr-defined]
        lock_key = f"reporting-workflow-thread-lifecycle:{thread_id}"
        deadline = asyncio.get_running_loop().time() + _WORKFLOW_THREAD_LOCK_WAIT_SECONDS
        while True:
            async with engine.connect() as connection:
                acquired = bool(
                    await connection.scalar(
                        text("SELECT pg_try_advisory_lock(hashtextextended(:lock_key, 0))"),
                        {"lock_key": lock_key},
                    )
                )
                if acquired:
                    try:
                        await connection.commit()
                        yield
                    finally:
                        with anyio.CancelScope(shield=True):
                            await connection.execute(
                                text(
                                    "SELECT pg_advisory_unlock("
                                    "hashtextextended(:lock_key, 0))"
                                ),
                                {"lock_key": lock_key},
                            )
                            await connection.commit()
                    return
                await connection.commit()
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                raise ReportingStateError(
                    "report_workflow_run_conflict",
                    "Reporting thread 生命周期操作等待超时。",
                )
            await asyncio.sleep(min(_WORKFLOW_THREAD_LOCK_RETRY_DELAY_SECONDS, remaining))

    async def is_workflow_run_active(self, external_run_id: str) -> bool:
        """探测旧 run 是否仍被其他进程推进，供 thread owner 恢复使用。"""

        engine = self.db.db_engine  # type: ignore[attr-defined]
        lock_key = self._workflow_execution_lock_key(external_run_id)
        async with engine.connect() as connection:
            acquired = bool(
                await connection.scalar(
                    text("SELECT pg_try_advisory_lock(hashtextextended(:lock_key, 0))"),
                    {"lock_key": lock_key},
                )
            )
            if acquired:
                await connection.execute(
                    text("SELECT pg_advisory_unlock(hashtextextended(:lock_key, 0))"),
                    {"lock_key": lock_key},
                )
            await connection.commit()
            return not acquired

    @staticmethod
    def _assert_receipt_fingerprint(stored: Any, command: ReportingCommand) -> None:
        fingerprint = str(stored or "")
        if fingerprint != _command_fingerprint(command):
            raise ReportingStateError(
                "report_command_replay_conflict", "幂等键已绑定其他 command。"
            )

    @staticmethod
    def _receipt_values(report_run_id: str, applied: Mapping[str, Any]) -> list[dict[str, Any]]:
        now = datetime.now(UTC)
        values: list[dict[str, Any]] = []
        for command_id, stored in applied.items():
            if not isinstance(command_id, str) or not command_id:
                continue
            fingerprint = stored.get("fingerprint") if isinstance(stored, Mapping) else None
            if not isinstance(fingerprint, str) or len(fingerprint) != 64:
                continue
            values.append(
                {
                    "report_run_id": report_run_id,
                    "command_id": command_id,
                    "fingerprint": fingerprint,
                    "created_at": now,
                }
            )
        return values

    async def _insert_command_receipts(self, connection: Any, values: list[dict[str, Any]]) -> None:
        if not values:
            return
        index_elements = [
            self.command_receipts.c.report_run_id,
            self.command_receipts.c.command_id,
        ]
        statement = postgresql_insert(self.command_receipts).values(values)
        statement = statement.on_conflict_do_nothing(index_elements=index_elements)
        await connection.execute(statement)

    @staticmethod
    def _assert_binding(existing: ReportingRunState, requested: ReportingRunState) -> None:
        if (
            existing.external_run_id != requested.external_run_id
            or existing.thread_id != requested.thread_id
            or existing.owner_user_id != requested.owner_user_id
        ):
            raise ReportingStateError("report_state_binding_conflict", "Reporting 状态绑定不一致。")

    @staticmethod
    def _row_values(state: ReportingRunState) -> dict[str, Any]:
        return {
            "report_run_id": state.report_run_id,
            "external_run_id": state.external_run_id,
            "thread_id": state.thread_id,
            "owner_user_id": state.owner_user_id,
            "revision": state.revision,
            "schema_version": state.schema_version,
            "state_version": state.state_version,
            "phase": state.phase.value,
            "payload": state.payload,
            "created_at": state.created_at,
            "updated_at": state.updated_at,
        }

"""ReportingRunState 的 SQLAlchemy 持久化边界。"""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from agno.db.base import AsyncBaseDb
from sqlalchemy import (
    JSON,
    BigInteger,
    Column,
    DateTime,
    MetaData,
    String,
    Table,
    insert,
    select,
    text,
    update,
)
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
    """Reporting 专属状态仓储；不复用 Coding task 的业务列或 session checkpoint。"""

    def __init__(self, db: AsyncBaseDb):
        self.db = db
        dialect = db.db_engine.dialect.name  # type: ignore[attr-defined]
        schema = REPORTING_DB_SCHEMA if dialect == "postgresql" else None
        self.metadata = MetaData(schema=schema)
        self.states = Table(
            "reporting_run_states",
            self.metadata,
            Column("report_run_id", String(256), primary_key=True),
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
                if connection.dialect.name == "postgresql":
                    await connection.execute(
                        text(f'CREATE SCHEMA IF NOT EXISTS "{REPORTING_DB_SCHEMA}"')
                    )
                await connection.run_sync(self.metadata.create_all)
            self._initialized = True

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

    async def create(self, state: ReportingRunState) -> ReportingRunState:
        await self.initialize()
        if state.schema_version != REPORTING_STATE_SCHEMA_VERSION:
            raise ReportingStateVersionUnsupported()
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
                return ReportingReducerResult(state=current, idempotent=True)
            if current.state_version != expected_version:
                raise ReportingStateConflict()
            result = ReportingStateReducer.apply(current, command_value, expected_version)
            # reducer payload 中也记录 command fingerprint，保证同一 command_id 不能换参重放。
            result.state.payload.setdefault("appliedCommands", {}).setdefault(
                command_value.command_id, {}
            )["fingerprint"] = _command_fingerprint(command_value)
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
            return result

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

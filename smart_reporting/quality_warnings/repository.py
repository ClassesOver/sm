from __future__ import annotations

import base64
import json
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any, Literal, Protocol, cast
from uuid import UUID, uuid4

from loguru import logger
from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
    Uuid,
    and_,
    insert,
    or_,
    select,
    text,
    update,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from .models import (
    CheckContext,
    CheckScope,
    QualityWarningEvent,
    QualityWarningPage,
    QualityWarningRecord,
    TenantScope,
    WarningCheck,
    WarningDisposition,
    WarningFinding,
    WarningQuery,
    warning_fingerprint,
)

_metadata = MetaData()
quality_warnings_v1 = Table(
    "quality_warnings_v1",
    _metadata,
    Column("warning_id", Uuid(as_uuid=True), primary_key=True),
    Column("database_name", String(256), nullable=False),
    Column("company_id", String(256), nullable=False),
    Column("domain", String(128), nullable=False),
    Column("rule_code", String(128), nullable=False),
    Column("subject_type", String(128), nullable=False),
    Column("subject_id", String(128), nullable=False),
    Column("fingerprint", String(64), nullable=False),
    Column("status", String(16), nullable=False),
    Column("severity", String(16), nullable=False),
    Column("disposition", String(32), nullable=False, server_default="quality_warning"),
    Column("source_phase", String(64), nullable=False, server_default="legacy"),
    Column("message", Text, nullable=False),
    Column("details", JSONB, nullable=False),
    Column("first_observed_at", DateTime(timezone=True), nullable=False),
    Column("last_observed_at", DateTime(timezone=True), nullable=False),
    Column("resolved_at", DateTime(timezone=True)),
    Column("occurrence_count", Integer, nullable=False),
    Column("last_check_id", String(256), nullable=False),
    Column("version", Integer, nullable=False),
    CheckConstraint("status IN ('open', 'resolved')", name="quality_warnings_v1_status"),
    CheckConstraint("severity = 'warning'", name="quality_warnings_v1_severity"),
    UniqueConstraint(
        "database_name",
        "company_id",
        "domain",
        "rule_code",
        "subject_type",
        "subject_id",
        "fingerprint",
        name="uq_quality_warnings_v1_identity",
    ),
    Index(
        "ix_quality_warnings_v1_tenant_status_observed",
        "database_name",
        "company_id",
        "domain",
        "status",
        "last_observed_at",
        "warning_id",
    ),
)
quality_warning_events_v1 = Table(
    "quality_warning_events_v1",
    _metadata,
    Column("event_id", Uuid(as_uuid=True), primary_key=True),
    Column(
        "warning_id",
        Uuid(as_uuid=True),
        ForeignKey("quality_warnings_v1.warning_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("database_name", String(256), nullable=False),
    Column("company_id", String(256), nullable=False),
    Column("event_type", String(32), nullable=False),
    Column("check_id", String(256), nullable=False),
    Column("occurred_at", DateTime(timezone=True), nullable=False),
    Column("details", JSONB, nullable=False),
    Column("report_run_id", String(256)),
    Column("revision", Integer),
    Column("thread_id", String(256)),
    Column("user_id", String(256)),
    Column("session_id", String(256)),
    CheckConstraint(
        "event_type IN ('detected', 'rechecked_open', 'resolved')",
        name="quality_warning_events_v1_type",
    ),
    UniqueConstraint("warning_id", "check_id", name="uq_quality_warning_events_v1_check"),
    Index(
        "ix_quality_warning_events_v1_tenant_warning",
        "database_name",
        "company_id",
        "warning_id",
        "occurred_at",
    ),
)


class QualityWarningRepository(Protocol):
    async def create_schema(self) -> None: ...

    async def record_successful_check(
        self,
        *,
        tenant: TenantScope,
        check_scope: CheckScope,
        findings: Sequence[WarningFinding],
        context: CheckContext,
    ) -> tuple[QualityWarningRecord, ...]: ...

    async def record_successful_checks(
        self, *, tenant: TenantScope, checks: Sequence[WarningCheck]
    ) -> tuple[QualityWarningRecord, ...]: ...

    async def list_warnings(
        self, *, tenant: TenantScope, query: WarningQuery
    ) -> tuple[QualityWarningRecord, ...]: ...

    async def list_warning_page(
        self, *, tenant: TenantScope, query: WarningQuery
    ) -> QualityWarningPage: ...

    async def get_warning(
        self, *, tenant: TenantScope, warning_id: UUID
    ) -> QualityWarningRecord | None: ...

    async def list_events(
        self, *, tenant: TenantScope, warning_id: UUID
    ) -> tuple[QualityWarningEvent, ...]: ...


class SqlAlchemyQualityWarningRepository:
    """只支持 PostgreSQL 的全局质量告警仓，事件表只能追加。"""

    def __init__(self, engine: AsyncEngine):
        if engine.dialect.name != "postgresql":
            raise ValueError("全局质量告警只支持 PostgreSQL。")
        self.engine = engine

    async def create_schema(self) -> None:
        async with self.engine.begin() as connection:
            await connection.run_sync(_metadata.create_all)
            await connection.execute(
                text(
                    "ALTER TABLE quality_warnings_v1 "
                    "ADD COLUMN IF NOT EXISTS disposition VARCHAR(32) NOT NULL DEFAULT 'quality_warning'"
                )
            )
            await connection.execute(
                text(
                    "ALTER TABLE quality_warnings_v1 "
                    "ADD COLUMN IF NOT EXISTS source_phase VARCHAR(64) NOT NULL DEFAULT 'legacy'"
                )
            )

    async def record_successful_check(
        self,
        *,
        tenant: TenantScope,
        check_scope: CheckScope,
        findings: Sequence[WarningFinding],
        context: CheckContext,
    ) -> tuple[QualityWarningRecord, ...]:
        return await self.record_successful_checks(
            tenant=tenant,
            checks=(
                WarningCheck(
                    checkScope=check_scope,
                    findings=tuple(findings),
                    context=context,
                ),
            ),
        )

    async def record_successful_checks(
        self,
        *,
        tenant: TenantScope,
        checks: Sequence[WarningCheck],
    ) -> tuple[QualityWarningRecord, ...]:
        if not checks:
            raise ValueError("成功检查批次不能为空。")
        now = datetime.now(UTC)
        try:
            async with self.engine.begin() as connection:
                ordered_checks = tuple(
                    sorted(
                        checks,
                        key=lambda item: (
                            item.check_scope.domain,
                            item.check_scope.rule_code,
                            item.check_scope.subject_type,
                        ),
                    )
                )
                # 所有检查先按稳定范围顺序加锁，再写入和解析缺失项，避免并发批次死锁。
                for check in ordered_checks:
                    await connection.execute(
                        text("SELECT pg_advisory_xact_lock(hashtextextended(:scope, 0))"),
                        {"scope": _scope_lock_key(tenant, check.check_scope)},
                    )
                records: list[QualityWarningRecord] = []
                found_by_check: list[tuple[WarningCheck, set[tuple[str, str]]]] = []
                for check in ordered_checks:
                    deduplicated = _deduplicate_findings(check.findings)
                    found_identity_keys: set[tuple[str, str]] = set()
                    for finding in deduplicated:
                        fingerprint = warning_fingerprint(finding)
                        identity = _identity_values(tenant, check.check_scope, finding, fingerprint)
                        found_identity_keys.add((finding.subject_id, fingerprint))
                        records.append(
                            await self._upsert_open_warning(
                                connection,
                                identity=identity,
                                finding=finding,
                                context=check.context,
                                now=now,
                            )
                        )
                    found_by_check.append((check, found_identity_keys))
                for check, found_identity_keys in found_by_check:
                    await self._resolve_absent_covered_warnings(
                        connection,
                        tenant=tenant,
                        check_scope=check.check_scope,
                        found_identity_keys=found_identity_keys,
                        context=check.context,
                        now=now,
                    )
        except BaseException as error:
            if not isinstance(error, Exception):
                raise
            logger.error(
                "quality_warning_batch_persist_failed check_count={} error_type={}",
                len(checks),
                type(error).__name__,
            )
            raise
        return tuple(records)

    async def list_warnings(
        self, *, tenant: TenantScope, query: WarningQuery
    ) -> tuple[QualityWarningRecord, ...]:
        return (await self.list_warning_page(tenant=tenant, query=query)).records

    async def list_warning_page(
        self, *, tenant: TenantScope, query: WarningQuery
    ) -> QualityWarningPage:
        conditions = _tenant_conditions(tenant)
        conditions.append(quality_warnings_v1.c.status == query.status)
        if query.domain is not None:
            conditions.append(quality_warnings_v1.c.domain == query.domain)
        if query.rule_code is not None:
            conditions.append(quality_warnings_v1.c.rule_code == query.rule_code)
        if query.subject_type is not None:
            conditions.append(quality_warnings_v1.c.subject_type == query.subject_type)
        if query.subject_id is not None:
            conditions.append(quality_warnings_v1.c.subject_id == query.subject_id)
        if query.disposition is not None:
            conditions.append(quality_warnings_v1.c.disposition == query.disposition)
        if query.first_observed_after is not None:
            conditions.append(quality_warnings_v1.c.first_observed_at >= query.first_observed_after)
        if query.last_observed_before is not None:
            conditions.append(quality_warnings_v1.c.last_observed_at <= query.last_observed_before)
        if query.cursor is not None:
            observed_at, warning_id = _decode_cursor(query.cursor)
            conditions.append(
                or_(
                    quality_warnings_v1.c.last_observed_at < observed_at,
                    and_(
                        quality_warnings_v1.c.last_observed_at == observed_at,
                        quality_warnings_v1.c.warning_id < warning_id,
                    ),
                )
            )
        statement = (
            select(quality_warnings_v1)
            .where(*conditions)
            .order_by(
                quality_warnings_v1.c.last_observed_at.desc(),
                quality_warnings_v1.c.warning_id.desc(),
            )
            .limit(query.limit + 1)
        )
        async with self.engine.connect() as connection:
            rows = (await connection.execute(statement)).mappings().all()
        records = tuple(_record_from_row(row) for row in rows[: query.limit])
        next_cursor = _encode_cursor(records[-1]) if len(rows) > query.limit else None
        return QualityWarningPage(records=records, next_cursor=next_cursor)

    async def get_warning(
        self, *, tenant: TenantScope, warning_id: UUID
    ) -> QualityWarningRecord | None:
        statement = select(quality_warnings_v1).where(
            *_tenant_conditions(tenant), quality_warnings_v1.c.warning_id == warning_id
        )
        async with self.engine.connect() as connection:
            row = (await connection.execute(statement)).mappings().one_or_none()
        return _record_from_row(row) if row is not None else None

    async def list_events(
        self, *, tenant: TenantScope, warning_id: UUID
    ) -> tuple[QualityWarningEvent, ...]:
        statement = (
            select(quality_warning_events_v1)
            .where(
                quality_warning_events_v1.c.database_name == tenant.database_name,
                quality_warning_events_v1.c.company_id == tenant.company_id,
                quality_warning_events_v1.c.warning_id == warning_id,
            )
            .order_by(quality_warning_events_v1.c.occurred_at, quality_warning_events_v1.c.event_id)
        )
        async with self.engine.connect() as connection:
            rows = (await connection.execute(statement)).mappings().all()
        return tuple(_event_from_row(row) for row in rows)

    async def _upsert_open_warning(
        self,
        connection: AsyncConnection,
        *,
        identity: dict[str, str],
        finding: WarningFinding,
        context: CheckContext,
        now: datetime,
    ) -> QualityWarningRecord:
        inserted_id = await connection.scalar(
            postgresql_insert(quality_warnings_v1)
            .values(
                warning_id=uuid4(),
                **identity,
                status="open",
                severity=finding.severity,
                disposition=finding.disposition,
                source_phase=finding.source_phase,
                message=finding.message,
                details=finding.details,
                first_observed_at=now,
                last_observed_at=now,
                occurrence_count=1,
                last_check_id=context.check_id,
                version=1,
            )
            .on_conflict_do_nothing(constraint="uq_quality_warnings_v1_identity")
            .returning(quality_warnings_v1.c.warning_id)
        )
        row = (
            (
                await connection.execute(
                    select(quality_warnings_v1)
                    .where(*_identity_conditions(identity))
                    .with_for_update()
                )
            )
            .mappings()
            .one()
        )
        if inserted_id is None and str(row["last_check_id"]) != context.check_id:
            await connection.execute(
                update(quality_warnings_v1)
                .where(quality_warnings_v1.c.warning_id == row["warning_id"])
                .values(
                    status="open",
                    disposition=finding.disposition,
                    source_phase=finding.source_phase,
                    message=finding.message,
                    details=finding.details,
                    last_observed_at=now,
                    resolved_at=None,
                    occurrence_count=int(row["occurrence_count"]) + 1,
                    last_check_id=context.check_id,
                    version=int(row["version"]) + 1,
                )
            )
            row = (
                (
                    await connection.execute(
                        select(quality_warnings_v1).where(
                            quality_warnings_v1.c.warning_id == row["warning_id"]
                        )
                    )
                )
                .mappings()
                .one()
            )
            event_type = "rechecked_open"
        elif inserted_id is not None:
            event_type = "detected"
        else:
            return _record_from_row(row)
        await self._append_event(
            connection,
            warning_id=cast(UUID, row["warning_id"]),
            tenant=TenantScope(
                database_name=cast(str, row["database_name"]),
                company_id=cast(str, row["company_id"]),
            ),
            event_type=event_type,
            details=finding.details,
            context=context,
            now=now,
        )
        logger.info(
            "quality_warning_recorded warning_id={} rule_code={} subject_type={} subject_id={}",
            row["warning_id"],
            identity["rule_code"],
            identity["subject_type"],
            identity["subject_id"],
        )
        return _record_from_row(row)

    async def _resolve_absent_covered_warnings(
        self,
        connection: AsyncConnection,
        *,
        tenant: TenantScope,
        check_scope: CheckScope,
        found_identity_keys: set[tuple[str, str]],
        context: CheckContext,
        now: datetime,
    ) -> None:
        rows = (
            (
                await connection.execute(
                    select(quality_warnings_v1)
                    .where(
                        *_tenant_conditions(tenant),
                        quality_warnings_v1.c.domain == check_scope.domain,
                        quality_warnings_v1.c.rule_code == check_scope.rule_code,
                        quality_warnings_v1.c.subject_type == check_scope.subject_type,
                        quality_warnings_v1.c.subject_id.in_(check_scope.covered_subject_ids),
                        quality_warnings_v1.c.status == "open",
                    )
                    .with_for_update()
                )
            )
            .mappings()
            .all()
        )
        for row in rows:
            if (str(row["subject_id"]), str(row["fingerprint"])) in found_identity_keys:
                continue
            if str(row["last_check_id"]) == context.check_id:
                continue
            await connection.execute(
                update(quality_warnings_v1)
                .where(quality_warnings_v1.c.warning_id == row["warning_id"])
                .values(
                    status="resolved",
                    resolved_at=now,
                    last_check_id=context.check_id,
                    version=int(row["version"]) + 1,
                )
            )
            await self._append_event(
                connection,
                warning_id=cast(UUID, row["warning_id"]),
                tenant=tenant,
                event_type="resolved",
                details=cast(dict[str, Any], row["details"]),
                context=context,
                now=now,
            )
            logger.info(
                "quality_warning_resolved warning_id={} rule_code={} subject_type={} subject_id={}",
                row["warning_id"],
                check_scope.rule_code,
                check_scope.subject_type,
                row["subject_id"],
            )

    @staticmethod
    async def _append_event(
        connection: AsyncConnection,
        *,
        warning_id: UUID,
        tenant: TenantScope,
        event_type: str,
        details: dict[str, Any],
        context: CheckContext,
        now: datetime,
    ) -> None:
        await connection.execute(
            insert(quality_warning_events_v1).values(
                event_id=uuid4(),
                warning_id=warning_id,
                database_name=tenant.database_name,
                company_id=tenant.company_id,
                event_type=event_type,
                check_id=context.check_id,
                occurred_at=now,
                details=details,
                report_run_id=context.report_run_id,
                revision=context.revision,
                thread_id=context.thread_id,
                user_id=context.user_id,
                session_id=context.session_id,
            )
        )


def _deduplicate_findings(findings: Sequence[WarningFinding]) -> tuple[WarningFinding, ...]:
    result: list[WarningFinding] = []
    seen: set[tuple[str, str, str, str]] = set()
    for finding in findings:
        key = (
            finding.rule_code,
            finding.subject_type,
            finding.subject_id,
            warning_fingerprint(finding),
        )
        if key not in seen:
            seen.add(key)
            result.append(finding)
    return tuple(result)


def _scope_lock_key(tenant: TenantScope, check_scope: CheckScope) -> str:
    return ":".join(
        (
            tenant.database_name,
            tenant.company_id,
            check_scope.domain,
            check_scope.rule_code,
            check_scope.subject_type,
        )
    )


def _identity_values(
    tenant: TenantScope,
    check_scope: CheckScope,
    finding: WarningFinding,
    fingerprint: str,
) -> dict[str, str]:
    return {
        "database_name": tenant.database_name,
        "company_id": tenant.company_id,
        "domain": check_scope.domain,
        "rule_code": finding.rule_code,
        "subject_type": finding.subject_type,
        "subject_id": finding.subject_id,
        "fingerprint": fingerprint,
    }


def _tenant_conditions(tenant: TenantScope) -> list[Any]:
    return [
        quality_warnings_v1.c.database_name == tenant.database_name,
        quality_warnings_v1.c.company_id == tenant.company_id,
    ]


def _identity_conditions(identity: dict[str, str]) -> list[Any]:
    return [getattr(quality_warnings_v1.c, key) == value for key, value in identity.items()]


def _utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _record_from_row(row: RowMapping) -> QualityWarningRecord:
    return QualityWarningRecord(
        warning_id=cast(UUID, row["warning_id"]),
        tenant=TenantScope(
            database_name=cast(str, row["database_name"]),
            company_id=cast(str, row["company_id"]),
        ),
        domain=cast(str, row["domain"]),
        rule_code=cast(str, row["rule_code"]),
        subject_type=cast(str, row["subject_type"]),
        subject_id=cast(str, row["subject_id"]),
        fingerprint=cast(str, row["fingerprint"]),
        status=cast(Literal["open", "resolved"], row["status"]),
        severity=cast(Literal["warning"], row["severity"]),
        disposition=cast(WarningDisposition, row.get("disposition") or "quality_warning"),
        sourcePhase=cast(str, row.get("source_phase") or "legacy"),
        message=cast(str, row["message"]),
        details=cast(dict[str, Any], row["details"]),
        first_observed_at=_utc(cast(datetime, row["first_observed_at"])),
        last_observed_at=_utc(cast(datetime, row["last_observed_at"])),
        resolved_at=(
            _utc(cast(datetime, row["resolved_at"])) if row["resolved_at"] is not None else None
        ),
        occurrence_count=cast(int, row["occurrence_count"]),
        last_check_id=cast(str, row["last_check_id"]),
        version=cast(int, row["version"]),
    )


def _event_from_row(row: RowMapping) -> QualityWarningEvent:
    return QualityWarningEvent(
        event_id=cast(UUID, row["event_id"]),
        warning_id=cast(UUID, row["warning_id"]),
        tenant=TenantScope(
            database_name=cast(str, row["database_name"]),
            company_id=cast(str, row["company_id"]),
        ),
        event_type=cast(Literal["detected", "rechecked_open", "resolved"], row["event_type"]),
        check_id=cast(str, row["check_id"]),
        occurred_at=_utc(cast(datetime, row["occurred_at"])),
        details=cast(dict[str, Any], row["details"]),
    )


def _encode_cursor(record: QualityWarningRecord) -> str:
    value = json.dumps(
        {
            "lastObservedAt": record.last_observed_at.isoformat(),
            "warningId": str(record.warning_id),
        },
        separators=(",", ":"),
    )
    return base64.urlsafe_b64encode(value.encode("ascii")).decode("ascii").rstrip("=")


def _decode_cursor(value: str) -> tuple[datetime, UUID]:
    try:
        payload = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
        decoded = json.loads(payload.decode("ascii"))
        observed_at = datetime.fromisoformat(str(decoded["lastObservedAt"]))
        warning_id = UUID(str(decoded["warningId"]))
    except (KeyError, TypeError, ValueError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("质量告警分页游标无效。") from error
    if observed_at.tzinfo is None:
        raise ValueError("质量告警分页游标无效。")
    return observed_at, warning_id

from __future__ import annotations

import hmac
import threading
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from .credentials import TemporaryCredentialStore
from .intake import ParsedReportIntake
from .models import ReportingError, ReportSourceBinding, SourceMode, TemporarySourceRequest
from .providers import StarRocksClientFactory, validate_network_target

SOURCE_CONFIRMATION_TTL = timedelta(minutes=15)
_ADMIN_USERS = frozenset({"root", "admin", "administrator"})


@dataclass(frozen=True)
class SourceConfirmation:
    confirmation_id: str
    endpoint: str
    database: str
    allowed_tables: tuple[str, ...]
    expires_at: datetime

    def public_dict(self) -> dict[str, object]:
        return {
            "confirmationId": self.confirmation_id,
            "sourceType": "starrocks",
            "endpoint": self.endpoint,
            "database": self.database,
            "allowedTables": list(self.allowed_tables),
            "expiresAt": self.expires_at.isoformat(),
        }


@dataclass
class _PendingConfirmation:
    request: TemporarySourceRequest
    allowed_tables: tuple[str, ...]
    user_id: str
    thread_id: str
    session_id: str
    expires_at: datetime


class TemporarySourceBindingService:
    def __init__(
        self,
        credentials: TemporaryCredentialStore,
        client_factory: StarRocksClientFactory,
        *,
        network_allowlist: str | tuple[str, ...] | None,
    ):
        self._credentials = credentials
        self._client_factory = client_factory
        self._network_allowlist = network_allowlist
        self._pending: dict[str, _PendingConfirmation] = {}
        self._lock = threading.Lock()

    def prepare(
        self,
        intake: ParsedReportIntake,
        *,
        user_id: str,
        thread_id: str,
        session_id: str,
        now: datetime | None = None,
    ) -> SourceConfirmation:
        request = intake.source_request
        if request is None or not intake.ddl_tables:
            raise ReportingError("source_connection_incomplete", "临时来源信息不完整。")
        validate_network_target(request.host, self._network_allowlist)
        if request.username.lower() in _ADMIN_USERS:
            raise ReportingError("source_account_privileged", "临时数据库账号不能是管理员账号。")
        allowed_tables = tuple(
            _qualified_for_database(table, request.database) for table in intake.ddl_tables
        )
        current = _now(now)
        confirmation_id = f"confirm_{uuid4().hex}"
        expires_at = current + SOURCE_CONFIRMATION_TTL
        with self._lock:
            self._pending[confirmation_id] = _PendingConfirmation(
                request, allowed_tables, user_id, thread_id, session_id, expires_at
            )
        return SourceConfirmation(
            confirmation_id,
            f"{request.host}:{request.port}",
            request.database,
            allowed_tables,
            expires_at,
        )

    def approve(
        self,
        confirmation_id: str,
        *,
        user_id: str,
        thread_id: str,
        session_id: str,
        now: datetime | None = None,
    ) -> ReportSourceBinding:
        current = _now(now)
        with self._lock:
            pending = self._pending.get(confirmation_id)
        if pending is None:
            raise ReportingError("source_confirmation_invalid", "来源确认已失效或已使用。")
        if pending.expires_at <= current:
            raise ReportingError("source_confirmation_expired", "来源确认已过期。")
        expected = (pending.user_id, pending.thread_id, pending.session_id)
        actual = (user_id, thread_id, session_id)
        if not all(hmac.compare_digest(left, right) for left, right in zip(expected, actual)):
            raise ReportingError("source_confirmation_scope_mismatch", "来源确认不属于当前会话。")
        with self._lock:
            if self._pending.pop(confirmation_id, None) is not pending:
                raise ReportingError("source_confirmation_invalid", "来源确认已失效或已使用。")
        client = self._client_factory(pending.request.secret_payload())
        try:
            if not client.verify_read_only(pending.allowed_tables):
                raise ReportingError(
                    "source_account_not_read_only", "无法证明数据库账号仅具有目标表只读权限。"
                )
            description = client.describe(pending.allowed_tables)
        finally:
            client.close()
        actual_tables = set(description.tables)
        if description.database.lower() != pending.request.database.lower() or actual_tables != set(
            pending.allowed_tables
        ):
            raise ReportingError("source_ddl_mismatch", "DDL 表范围与 StarRocks 实际元数据不一致。")
        binding_id = f"src_{uuid4().hex}"
        _, expires_at = self._credentials.put(
            pending.request,
            connection_ref=binding_id,
            user_id=user_id,
            thread_id=thread_id,
            session_id=session_id,
            now=current,
        )
        return ReportSourceBinding(
            bindingId=binding_id,
            sourceMode=SourceMode.TEMPORARY_DATABASE,
            database=pending.request.database,
            allowedTables=pending.allowed_tables,
            metadataFingerprint=description.metadata_fingerprint,
            threadId=thread_id,
            userId=user_id,
            sessionId=session_id,
            expiresAt=expires_at,
        )

    def cancel(self, confirmation_id: str) -> None:
        with self._lock:
            self._pending.pop(confirmation_id, None)


def _qualified_for_database(table: str, database: str) -> str:
    parts = table.split(".")
    if len(parts) == 1:
        return f"{database.lower()}.{parts[0].lower()}"
    if len(parts) == 2 and parts[0].lower() == database.lower():
        return table.lower()
    raise ReportingError("source_ddl_mismatch", "DDL 包含其他数据库的表。")


def _now(value: datetime | None) -> datetime:
    current = value or datetime.now(UTC)
    if current.tzinfo is None:
        raise ValueError("now 必须包含时区")
    return current.astimezone(UTC)

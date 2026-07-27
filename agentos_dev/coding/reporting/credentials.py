from __future__ import annotations

import hmac
import threading
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from .models import ReportingError, TemporarySourceRequest

DEFAULT_CREDENTIAL_IDLE_TTL = timedelta(hours=2)


@dataclass
class _CredentialEntry:
    request: TemporarySourceRequest
    user_id: str
    thread_id: str
    session_id: str
    expires_at: datetime


class TemporaryCredentialStore:
    """进程内临时凭据仓；进程重启后 connectionRef 自然失效。"""

    def __init__(self, idle_ttl: timedelta = DEFAULT_CREDENTIAL_IDLE_TTL):
        if idle_ttl <= timedelta(0):
            raise ValueError("idle_ttl 必须为正数")
        self._idle_ttl = idle_ttl
        self._entries: dict[str, _CredentialEntry] = {}
        self._lock = threading.Lock()

    def put(
        self,
        request: TemporarySourceRequest,
        *,
        connection_ref: str | None = None,
        user_id: str,
        thread_id: str,
        session_id: str,
        now: datetime | None = None,
    ) -> tuple[str, datetime]:
        current = self._now(now)
        connection_ref = connection_ref or f"src_{uuid4().hex}"
        if not connection_ref.startswith("src_") or len(connection_ref) > 128:
            raise ValueError("connection_ref 无效")
        expires_at = current + self._idle_ttl
        with self._lock:
            self._purge(current)
            self._entries[connection_ref] = _CredentialEntry(
                request, user_id, thread_id, session_id, expires_at
            )
        return connection_ref, expires_at

    def resolve(
        self,
        connection_ref: str,
        *,
        user_id: str,
        thread_id: str,
        session_id: str,
        now: datetime | None = None,
    ) -> TemporarySourceRequest:
        current = self._now(now)
        with self._lock:
            entry = self._entries.get(connection_ref)
            if entry is None:
                raise ReportingError("connection_ref_invalid", "临时数据源引用无效。")
            if entry.expires_at <= current:
                del self._entries[connection_ref]
                raise ReportingError("connection_ref_expired", "临时数据源引用已过期。")
            expected = (entry.user_id, entry.thread_id, entry.session_id)
            actual = (user_id, thread_id, session_id)
            if not all(hmac.compare_digest(left, right) for left, right in zip(expected, actual)):
                raise ReportingError(
                    "connection_ref_scope_mismatch", "临时数据源引用不属于当前会话。"
                )
            entry.expires_at = current + self._idle_ttl
            return entry.request

    def close(self, connection_ref: str) -> None:
        with self._lock:
            self._entries.pop(connection_ref, None)

    def close_session(self, *, user_id: str, thread_id: str, session_id: str) -> None:
        with self._lock:
            matching = [
                key
                for key, entry in self._entries.items()
                if (entry.user_id, entry.thread_id, entry.session_id)
                == (user_id, thread_id, session_id)
            ]
            for key in matching:
                del self._entries[key]

    def close_all(self) -> None:
        with self._lock:
            self._entries.clear()

    def _purge(self, now: datetime) -> None:
        expired = [key for key, entry in self._entries.items() if entry.expires_at <= now]
        for key in expired:
            del self._entries[key]

    @staticmethod
    def _now(value: datetime | None) -> datetime:
        current = value or datetime.now(UTC)
        if current.tzinfo is None:
            raise ValueError("now 必须包含时区")
        return current.astimezone(UTC)

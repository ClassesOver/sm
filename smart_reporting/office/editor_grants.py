"""编辑器授权链接与短期会话：Office 文件链接签发、兑换和 CSRF 校验。"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from cryptography.fernet import Fernet, InvalidToken

from ..reporting.models import ReportingError

EDITOR_SESSION_COOKIE = "report_editor_session"


class GrantContext(Protocol):
    """签发授权所需的最小上下文身份。"""

    @property
    def report_id(self) -> str: ...

    @property
    def revision(self) -> int: ...

    @property
    def workflow_run_id(self) -> str: ...

    def digest(self) -> str: ...


# 签发链接默认长期有效（10 年，等价永久；存储列不允许 NULL，用远端日期表达）。
EDITOR_GRANT_TTL = timedelta(days=3650)
EDITOR_SHARE_TTL = timedelta(days=30)
EDITOR_SESSION_TTL = timedelta(hours=8)



@dataclass(frozen=True)
class ReportEditorSession:
    report_id: str
    revision: int
    workflow_run_id: str
    context_sha256: str
    expires_at: datetime
    # None 表示完整 editor 会话（兼容旧授权）；分享链接签发时写入受限能力，
    # 例如 {"download_original": False}。B0 权限矩阵按此执行。
    capabilities: dict[str, Any] | None = None



class ReportEditorRepository(Protocol):
    async def put_grant(self, jti: str, *, expires_at: datetime) -> None: ...

    async def grant_active(self, jti: str, *, now: datetime) -> bool: ...

    async def put_session(self, session_hash: str, session: ReportEditorSession) -> None: ...

    async def get_session(self, session_hash: str) -> ReportEditorSession | None: ...


class InMemoryReportEditorRepository:
    def __init__(self) -> None:
        self.grants: dict[str, datetime] = {}
        self.sessions: dict[str, ReportEditorSession] = {}

    async def put_grant(self, jti: str, *, expires_at: datetime) -> None:
        self.grants[jti] = expires_at

    async def grant_active(self, jti: str, *, now: datetime) -> bool:
        expires_at = self.grants.get(jti)
        return expires_at is not None and expires_at > now

    async def put_session(self, session_hash: str, session: ReportEditorSession) -> None:
        self.sessions[session_hash] = session

    async def get_session(self, session_hash: str) -> ReportEditorSession | None:
        return self.sessions.get(session_hash)


class ReportEditorGrantService:
    def __init__(
        self,
        repository: ReportEditorRepository,
        *,
        secret: str,
        grant_ttl: timedelta = EDITOR_GRANT_TTL,
        session_ttl: timedelta = EDITOR_SESSION_TTL,
    ) -> None:
        if len(secret.encode()) < 32:
            raise ValueError("报告编辑授权密钥至少需要 32 字节。")
        key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest())
        self._fernet = Fernet(key)
        self._csrf_key = hashlib.sha256(f"report-editor-csrf:{secret}".encode()).digest()
        self.repository = repository
        self.grant_ttl = grant_ttl
        self.session_ttl = session_ttl

    async def issue(
        self, context: GrantContext, *, now: datetime | None = None,
        ttl: timedelta | None = None,
        capabilities: Mapping[str, Any] | None = None,
    ) -> tuple[str, datetime]:
        issued_at = utc(now or datetime.now(UTC))
        expires_at = issued_at + (ttl if ttl is not None else self.grant_ttl)
        jti = secrets.token_urlsafe(24)
        payload = {
            "contextSha256": context.digest(),
            "expiresAt": int(expires_at.timestamp()),
            "jti": jti,
            "reportId": context.report_id,
            "revision": context.revision,
            "workflowRunId": context.workflow_run_id,
        }
        if capabilities is not None:
            payload["capabilities"] = dict(capabilities)
        raw = self._fernet.encrypt(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).decode()
        await self.repository.put_grant(jti, expires_at=expires_at)
        return raw, expires_at

    async def exchange(
        self, raw_grant: str, *, now: datetime | None = None
    ) -> tuple[str, ReportEditorSession]:
        current = utc(now or datetime.now(UTC))
        try:
            payload = json.loads(self._fernet.decrypt(raw_grant.encode()))
            expires_at = datetime.fromtimestamp(int(payload["expiresAt"]), tz=UTC)
            jti = str(payload["jti"])
            raw_capabilities = payload.get("capabilities")
            session = ReportEditorSession(
                report_id=str(payload["reportId"]),
                revision=int(payload["revision"]),
                workflow_run_id=str(payload["workflowRunId"]),
                context_sha256=str(payload["contextSha256"]),
                expires_at=current + self.session_ttl,
                capabilities=(
                    dict(raw_capabilities)
                    if isinstance(raw_capabilities, dict)
                    else None
                ),
            )
        except (InvalidToken, KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            raise ReportingError("report_editor_grant_invalid", "报告编辑授权无效。") from error
        if expires_at <= current:
            raise ReportingError("report_editor_grant_expired", "报告编辑授权已过期。")
        # 编辑链接是长期入口，可重复打开；每次兑换签发独立的短期会话，服务端只核验
        # 授权仍登记且未过期，不做一次性消费。
        if not await self.repository.grant_active(jti, now=current):
            raise ReportingError("report_editor_grant_invalid", "报告编辑授权无效。")
        raw_session = secrets.token_urlsafe(32)
        await self.repository.put_session(token_hash(raw_session), session)
        return raw_session, session

    async def lookup_session(
        self, raw_session: str, *, now: datetime | None = None
    ) -> ReportEditorSession:
        return await self.lookup_registered_session(token_hash(raw_session), now=now)

    async def lookup_registered_session(
        self, session_hash: str, *, now: datetime | None = None
    ) -> ReportEditorSession:
        """仅供服务端已登记交接句柄使用；HTTP不得接收浏览器提交的会话摘要。"""
        current = utc(now or datetime.now(UTC))
        session = await self.repository.get_session(session_hash)
        if session is None:
            raise ReportingError("report_editor_session_invalid", "报告编辑会话无效。")
        if session.expires_at <= current:
            raise ReportingError("report_editor_session_expired", "报告编辑会话已过期。")
        return session

    def csrf_token(self, raw_session: str) -> str:
        return hmac.new(self._csrf_key, raw_session.encode(), hashlib.sha256).hexdigest()



def token_hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


__all__ = [
    "EDITOR_GRANT_TTL",
    "EDITOR_SESSION_COOKIE",
    "EDITOR_SESSION_TTL",
    "EDITOR_SHARE_TTL",
    "GrantContext",
    "InMemoryReportEditorRepository",
    "ReportEditorGrantService",
    "ReportEditorRepository",
    "ReportEditorSession",
    "token_hash",
    "utc",
]

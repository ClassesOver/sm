from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from uuid import NAMESPACE_URL, uuid5


class ManagementError(Exception):
    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(code)
        self.code, self.message, self.status = code, message, status


class AdminSessionInvalid(ManagementError):
    def __init__(self):
        super().__init__("management_session_invalid", "管理会话已失效，请重新登录。", 401)


@dataclass(frozen=True)
class AdminAccount:
    account_id: int
    username: str
    password_hash: str
    auth_version: int


@dataclass(frozen=True)
class AdminLogin:
    raw_token: str
    expires_at: datetime


@dataclass(frozen=True)
class ManagementScope:
    database: str
    company_id: str

    def __post_init__(self):
        if any(not value.strip() or value != value.strip() or len(value) > 128
               for value in (self.database, self.company_id)):
            raise ManagementError("management_scope_invalid", "请填写有效的数据库与组织标识。", 422)


@dataclass(frozen=True)
class ManagementActor:
    account_id: int
    username: str
    scope: ManagementScope
    auth_version: int
    raw_session: str = field(repr=False)


# 单实例配置的内部命名空间，不由浏览器选择或填写。
INSTANCE_SCOPE = ManagementScope("instance", "instance")
INSTANCE_SCOPE_ID = str(uuid5(NAMESPACE_URL, "urn:smart-reporting:management:instance"))


def invalid_credentials() -> ManagementError:
    return ManagementError("management_credentials_invalid", "用户名或密码错误。", 401)

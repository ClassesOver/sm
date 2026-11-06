from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


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


def invalid_credentials() -> ManagementError:
    return ManagementError("management_credentials_invalid", "用户名或密码错误。", 401)

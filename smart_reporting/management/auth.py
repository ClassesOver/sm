from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime

from pwdlib import PasswordHash
from pwdlib.exceptions import UnknownHashError

from .models import AdminAccount, AdminLogin, ManagementError, invalid_credentials
from .repository import AdminRepository


def validate_password(password: str) -> None:
    if not isinstance(password, str) or not 12 <= len(password) <= 128:
        raise ManagementError("management_password_invalid", "密码长度须为 12–128 个字符。")


class AdminAuthService:
    def __init__(
        self,
        repository: AdminRepository,
        *,
        clock: Callable[[], datetime] | None = None,
    ):
        self.repository = repository
        self.clock = clock or (lambda: datetime.now(UTC))
        self.passwords = PasswordHash.recommended()

    async def verify_password(self, password: str, encoded: str) -> bool:
        try:
            return await asyncio.to_thread(self.passwords.verify, password, encoded)
        except UnknownHashError:
            return False

    async def _hash(self, password: str) -> str:
        validate_password(password)
        return await asyncio.to_thread(self.passwords.hash, password)

    async def bootstrap(self, password: str) -> None:
        await self.repository.bootstrap(await self._hash(password), self.clock())

    async def login(self, username: str, password: str, client_address: str) -> AdminLogin:
        if not isinstance(password, str) or len(password) > 128:
            password = ""
        address = client_address[:128]
        account = await self.repository.login_account(address, self.clock())
        valid = False
        if account is not None:
            matches = await self.verify_password(password, account.password_hash)
            valid = matches and username == "admin"
        return await self.repository.finish_login(
            expected_version=account.auth_version if account else None,
            valid=valid,
            address=address,
            now=self.clock(),
        )

    async def authenticate(self, raw_session: str) -> AdminAccount:
        return await self.repository.authenticate(raw_session, self.clock())

    async def logout(self, raw_session: str) -> None:
        await self.repository.logout(raw_session, self.clock())

    async def change_password(self, raw_session: str, current_password: str, new_password: str):
        account = await self.authenticate(raw_session)
        if not await self.verify_password(current_password, account.password_hash):
            raise invalid_credentials()
        encoded = await self._hash(new_password)
        await self.repository.replace_password(
            encoded,
            self.clock(),
            raw=raw_session,
            expected_version=account.auth_version,
        )

    async def reset_password(self, new_password: str):
        await self.repository.replace_password(await self._hash(new_password), self.clock())

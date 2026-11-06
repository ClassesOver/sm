from __future__ import annotations

import argparse
import asyncio
import getpass

from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import create_async_engine

from ..runtime.database import _normalized_database_urls
from ..runtime.settings import database_url_from_environment
from .auth import AdminAuthService
from .models import ManagementError
from .repository import AdminRepository


async def run(command: str) -> None:
    password = getpass.getpass("admin 新密码：")
    repeated = getpass.getpass("再次输入：")
    if password != repeated:
        raise ManagementError("management_password_mismatch", "两次密码不一致。")
    _, url, _ = _normalized_database_urls(database_url_from_environment())
    engine = create_async_engine(url)
    try:
        auth = AdminAuthService(AdminRepository(engine))
        if command == "bootstrap-admin":
            await auth.bootstrap(password)
        else:
            await auth.reset_password(password)
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="管理后台账号初始化与恢复")
    parser.add_argument("command", choices=["bootstrap-admin", "reset-admin-password"])
    args = parser.parse_args()
    load_dotenv()
    try:
        asyncio.run(run(args.command))
    except ManagementError as error:
        parser.exit(1, f"{error.message} ({error.code})\n")
    print("admin 账号已更新；密码重置会撤销全部旧会话。")


if __name__ == "__main__":
    main()

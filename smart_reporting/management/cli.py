from __future__ import annotations

import argparse
import asyncio
import getpass
import json
import os
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import create_async_engine

from ..reporting.metadata import ReportingMetadataClient
from ..runtime.database import _normalized_database_urls
from ..runtime.settings import _report_metadata_url, database_url_from_environment
from .auth import AdminAuthService
from .data_sources.secrets import CredentialVault
from .importer import ConfigurationImporter
from .models import INSTANCE_SCOPE, ManagementError
from .repository import AdminRepository
from .scopes import ScopeService


async def run(
    command: str,
    *,
    directory: Path | None = None,
    dry_run: bool = False,
) -> dict | None:
    password = getpass.getpass("admin 密码：" if command == "import-config" else "admin 新密码：")
    if command != "import-config":
        repeated = getpass.getpass("再次输入：")
        if password != repeated:
            raise ManagementError("management_password_mismatch", "两次密码不一致。")
    _, url, _ = _normalized_database_urls(database_url_from_environment())
    engine = create_async_engine(url)
    try:
        auth = AdminAuthService(AdminRepository(engine))
        if command == "import-config":
            if directory is None:
                raise ManagementError(
                    "management_import_invalid", "导入必须显式指定配置目录。", 422
                )
            login = await auth.login("admin", password, "host-cli")
            try:
                metadata_url = _report_metadata_url(os.environ)
                metadata = (
                    ReportingMetadataClient(
                        metadata_url,
                        token=os.environ.get("AGENT_REPORT_METADATA_TOKEN") or None,
                    )
                    if metadata_url
                    else None
                )
                importer = ConfigurationImporter(
                    ScopeService(auth), CredentialVault(), metadata_client=metadata
                )
                return await importer.import_configuration(
                    login.raw_token, INSTANCE_SCOPE, directory, dry_run, os.environ
                )
            finally:
                await auth.logout(login.raw_token)
        elif command == "bootstrap-admin":
            await auth.bootstrap(password)
        else:
            await auth.reset_password(password)
        return None
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="管理后台账号与配置导入")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("bootstrap-admin", help="初始化 admin，无默认密码")
    commands.add_parser("reset-admin-password", help="重置密码并撤销全部会话")
    importing = commands.add_parser("import-config", help="预检并原子导入现有文件配置")
    importing.add_argument("--directory", required=True, type=Path, help="现有配置目录")
    importing.add_argument("--dry-run", action="store_true", help="完成预检并显示差异，不发布配置")
    args = parser.parse_args()
    load_dotenv()
    try:
        result = asyncio.run(
            run(
                args.command,
                directory=getattr(args, "directory", None),
                dry_run=getattr(args, "dry_run", False),
            )
        )
    except ManagementError as error:
        parser.exit(1, f"{error.message} ({error.code})\n")
    if result is not None:
        print(json.dumps(result, ensure_ascii=False))
    else:
        print("admin 账号已更新；密码重置会撤销全部旧会话。")


if __name__ == "__main__":
    main()

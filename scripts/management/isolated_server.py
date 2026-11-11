"""隔离完整 AgentOS 验收服务。只接受显式专用测试库，不读取业务 .env。"""

from __future__ import annotations

import asyncio
import json
import os
import secrets
import sys
from pathlib import Path

from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def configure():
    raw = os.environ.get("REPORTING_MANAGEMENT_TEST_DB_URL")
    if not raw:
        raise SystemExit("必须显式提供 REPORTING_MANAGEMENT_TEST_DB_URL")
    url = make_url(raw)
    if (
        url.database != "management_test"
        or url.port != 55439
        or url.host not in {"127.0.0.1", "localhost"}
    ):
        raise SystemExit("本工具仅允许本机 55439/management_test 专用库")
    # 显式覆盖全部数据库入口；模型使用假密钥，验收不会调用模型或数仓。
    os.environ.update(
        AGENT_ENV_FILE="/dev/null",
        AGENT_DB_URL=raw,
        DATABASE_URL=raw,
        OPENAI_API_KEY="management-isolated-no-model-calls",
        AGENT_WORKSPACE_HMAC_SECRET=secrets.token_urlsafe(48),
        AGENT_MANAGEMENT_CREDENTIAL_KEYS="e2e:"
        + __import__("cryptography.fernet", fromlist=["Fernet"]).Fernet.generate_key().decode(),
        AGENT_MANAGEMENT_PUBLIC_ORIGIN="http://127.0.0.1:7789",
        AGENT_MANAGEMENT_LOCAL_HTTP="true",
        AGENT_REPORT_PUBLIC_BASE_URL="http://127.0.0.1:7789",
        REPORTING_HOST_WORKSPACE_ROOT="/tmp/management-depth-workspaces",
    )


async def seed():
    from sqlalchemy import text

    from smart_reporting.app import agent_database, app
    from smart_reporting.management.data_sources.models import SourceDraftInput
    from smart_reporting.management.data_sources.secrets import CredentialVault
    from smart_reporting.management.data_sources.service import SourceService
    from smart_reporting.management.models import ManagementScope
    from smart_reporting.management.repository import metadata
    from smart_reporting.management.scopes import ScopeService
    from smart_reporting.tests.management_fixtures import publish_dependencies

    async with agent_database.async_engine.begin() as connection:
        await connection.execute(text("CREATE SCHEMA IF NOT EXISTS reporting_management"))
        await connection.run_sync(metadata.drop_all)
        await connection.run_sync(metadata.create_all)
    auth = app.state.management_auth
    password = secrets.token_urlsafe(24)
    await auth.bootstrap(password)
    login = await auth.login("admin", password, "isolated-seed")
    scopes = ScopeService(auth)
    service = SourceService(scopes, CredentialVault())
    for company, name in [("100", "华东运营"), ("200", "华南运营"), ("300", "尚未配置的机构")]:
        scope = ManagementScope("warehouse", company)
        await scopes.register(login.raw_token, scope, name)
        for index in range(55 if company == "100" else 1 if company == "200" else 0):
            source_id = "operations" if index == 0 else f"source-{index:03}"
            payload = SourceDraftInput.model_validate(
                {
                    "name": ("经营数仓" if index == 0 else f"测试数据源 {index:03}")
                    if company == "100"
                    else "其他机构同标识数仓",
                    "database": "warehouse",
                    "dsn": "starrocks://reader:isolated-secret@localhost:9030/warehouse",
                    "reportingProfileVersionId": "base:1",
                    "metadataVersionId": f"{source_id}:1",
                }
            )
            await service.create_draft(login.raw_token, scope, source_id, payload)
        if company == "100":
            await publish_dependencies(scopes, login.raw_token, scope)
    await auth.logout(login.raw_token)
    credentials = Path(
        os.environ.get("MANAGEMENT_E2E_CREDENTIALS", "/tmp/management-depth-credentials.json")
    )
    fd = os.open(credentials, os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "w") as stream:
        json.dump({"username": "admin", "password": password}, stream)
    print("隔离测试数据已就绪；临时凭据保存在权限 0600 文件中。", flush=True)


if __name__ == "__main__":
    configure()
    if "--reset-test-data" not in sys.argv:
        raise SystemExit("必须显式传入 --reset-test-data；仅重建专用管理测试 schema")
    asyncio.run(seed())
    import uvicorn

    from smart_reporting.app import app

    uvicorn.run(app, host="127.0.0.1", port=7789, access_log=False)

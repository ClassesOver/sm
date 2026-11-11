"""工作台表范围 HTTP/浏览器验收：真实管理库，数仓只读 I/O 使用固定测试结构。"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.management.isolated_server import configure, seed

configure()
from smart_reporting.management.table_access import TableAccessService  # noqa: E402
from smart_reporting.reporting.data_source.models import CatalogColumn, CatalogTable  # noqa: E402


def fixture(config):
    return (
        CatalogTable(
            config.id,
            config.database,
            "orders",
            (CatalogColumn("amount", "DECIMAL(18,2)", False, "金额"),),
            "订单事实",
        ),
        *(
            CatalogTable(
                config.id,
                config.database,
                f"table_{i:03}",
                (CatalogColumn("id", "BIGINT", False),),
                "",
            )
            for i in range(54)
        ),
        CatalogTable(
            config.id,
            config.database,
            "view_orders",
            (CatalogColumn("amount", "DECIMAL(18,2)", False),),
            "汇总视图",
        ),
    )


async def discover(self, config):
    return [
        {
            **self.catalogs._payload((t,))[0],
            "type": "view" if t.name.startswith("view_") else "table",
        }
        for t in fixture(config)
    ]


async def read(self, config, selected):
    return tuple(t for t in fixture(config) if (t.database, t.name) in selected)


original = TableAccessService.__init__


def initialize(self, scopes, vault, metadata_client=None):
    original(self, scopes, vault, metadata_client=None)


TableAccessService.__init__ = initialize
TableAccessService._discover = discover
TableAccessService._read_selected = read

if __name__ == "__main__":
    if "--reset-test-data" not in sys.argv:
        raise SystemExit("需要 --reset-test-data；只重建本机专用 management_test 管理schema")

    async def prepare():
        await seed()
        import json

        from smart_reporting.app import app
        from smart_reporting.management.data_sources.secrets import CredentialVault
        from smart_reporting.management.models import ManagementScope
        from smart_reporting.management.scopes import ScopeService

        credentials = json.loads(Path("/tmp/management-depth-credentials.json").read_text())
        auth = app.state.management_auth
        login = await auth.login("admin", credentials["password"], "upgrade-seed")
        service = TableAccessService(ScopeService(auth), CredentialVault())
        scope = ManagementScope("warehouse", "100")
        await service.sources.publish(login.raw_token, scope, "operations", 1)
        await service.discover(login.raw_token, scope, "operations", 1)
        await auth.logout(login.raw_token)

    asyncio.run(prepare())
    import uvicorn

    from smart_reporting.app import app

    uvicorn.run(app, host="127.0.0.1", port=7789, access_log=False)

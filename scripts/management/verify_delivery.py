"""只读检查容器中的管理bundle，包含源码bind mount场景；不连接数据库。"""

import asyncio
import hashlib
import json
from unittest.mock import AsyncMock

import httpx
from fastapi import FastAPI

from smart_reporting.management.api import create_management_router
from smart_reporting.management.models import AdminSessionInvalid
from smart_reporting.management.settings import ManagementSettings


async def main():
    settings = ManagementSettings.from_environment()
    assert str(settings.static_dir) == "/opt/report-editor-static/management"
    manifest = json.loads((settings.static_dir / ".vite/manifest.json").read_text())
    assets = {node["file"] for node in manifest.values()}
    for node in manifest.values():
        assets.update(node.get("css", []))
    auth = AsyncMock()
    auth.authenticate.side_effect = AdminSessionInvalid()
    app = FastAPI()
    app.include_router(create_management_router(auth, settings))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="https://isolated.test"
    ) as client:
        assert (await client.get("/management/")).status_code == 303
        html = await client.get("/management/login")
        assert html.status_code == 200
        for asset in assets:
            response = await client.get("/management/" + asset)
            assert response.status_code == 200, asset
            assert response.headers["cache-control"] == "no-store"
        for missing in [
            "/management/unknown",
            "/management/api/v1/missing",
            "/management/assets/missing.js",
        ]:
            assert (await client.get(missing)).status_code == 404
    print(
        json.dumps(
            {
                "staticDir": str(settings.static_dir),
                "assetsChecked": len(assets),
                "htmlSha256": hashlib.sha256(html.content).hexdigest(),
                "sourceBindMountCompatible": True,
                "passed": True,
            }
        )
    )


asyncio.run(main())

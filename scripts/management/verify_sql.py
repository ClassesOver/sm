"""只读核对真实浏览器操作后的专用测试库，报告只输出公开事实与计数。"""

import asyncio
import json
import os
import sys
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from smart_reporting.management.repository import (
    source_credentials,
    source_drafts,
    source_versions,
    sources,
)


async def main():
    raw = os.environ.get("REPORTING_MANAGEMENT_TEST_DB_URL")
    if not raw:
        raise SystemExit("必须提供显式测试库")
    url = make_url(raw)
    if (
        url.database != "management_test"
        or url.port != 55439
        or url.host not in {"127.0.0.1", "localhost"}
    ):
        raise SystemExit("拒绝访问非专用测试库")
    engine = create_async_engine(raw)
    async with engine.connect() as db:
        drafts = (
            (
                await db.execute(
                    select(source_drafts).where(source_drafts.c.source_id == "operations")
                )
            )
            .mappings()
            .all()
        )
        rows = []
        for draft in drafts:
            source = (
                (
                    await db.execute(
                        select(sources).where(
                            sources.c.scope_id == draft["scope_id"],
                            sources.c.source_id == "operations",
                        )
                    )
                )
                .mappings()
                .one()
            )
            count = await db.scalar(
                select(func.count())
                .select_from(source_credentials)
                .where(
                    source_credentials.c.scope_id == draft["scope_id"],
                    source_credentials.c.source_id == "operations",
                )
            )
            assert count == 1, "仅修改公开字段不得轮换凭据"
            published = None
            if source["published_revision"]:
                published = (
                    (
                        await db.execute(
                            select(source_versions).where(
                                source_versions.c.scope_id == draft["scope_id"],
                                source_versions.c.source_id == "operations",
                                source_versions.c.revision == source["published_revision"],
                            )
                        )
                    )
                    .mappings()
                    .one()
                )
            rows.append(
                {
                    "name": draft["name"],
                    "draftVersion": draft["version"],
                    "publishedRevision": source["published_revision"],
                    "credentialRows": count,
                    "draftMatchesPublished": published is not None
                    and draft["content_hash"] == published["content_hash"],
                }
            )
        assert len(rows) == 2
        assert any(row["publishedRevision"] == 1 and row["draftMatchesPublished"] for row in rows)
        result = {"sources": rows, "passed": True}
        output = Path("output/management-depth/sql-verification.json")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2))
        print("只读SQL验证通过；未输出凭据引用或秘密。")
    await engine.dispose()


asyncio.run(main())

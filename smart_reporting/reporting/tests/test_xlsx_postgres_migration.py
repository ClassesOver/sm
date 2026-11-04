"""在独立 PostgreSQL schema 中验证旧授权迁移与 XLSX 持久化。"""
from __future__ import annotations

import hashlib
import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

from smart_reporting.reporting.delivery.publishing import (
    ReportArtifactPersistenceService,
    ReportArtifactSpec,
    ReportDownloadGrantService,
    ReportDownloadHttpService,
    SqlAlchemyDownloadGrantRepository,
    SqlAlchemyReportArtifactRepository,
)
from smart_reporting.reporting.tests.test_xlsx_publication_storage import _scope, _Workspace


@pytest.mark.anyio
@pytest.mark.integration
async def test_legacy_grants_migrate_idempotently_and_xlsx_survives_cleanup():
    url = os.getenv("REPORTING_TEST_DB_URL", "").strip()
    if not url:
        pytest.skip("未设置 REPORTING_TEST_DB_URL，跳过 PostgreSQL 迁移验证。")
    schema = f"xlsx_migration_{uuid4().hex}"
    engine_url = make_url(url).set(drivername="postgresql+psycopg")
    admin = create_async_engine(engine_url)
    engine = create_async_engine(engine_url, connect_args={"options": f"-csearch_path={schema}"})
    try:
        async with admin.begin() as connection:
            await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        repository = SqlAlchemyDownloadGrantRepository(engine)
        grants = ReportDownloadGrantService(repository)
        await repository.create_schema()
        old_tokens = []
        for report_id, fields in (
            ("document", {"pdf_path": "reports/report.pdf", "pdf_size": 3, "pdf_sha256": "a" * 64,
                          "word_path": "reports/report.docx", "word_size": 4, "word_sha256": "b" * 64}),
            ("pptx", {"pptx_path": "reports/report.pptx", "pptx_size": 5, "pptx_sha256": "c" * 64}),
        ):
            token, grant = await grants.issue(scope=_scope(), report_id=report_id, revision=1, **fields)
            old_tokens.append((token, grant))
        # 还原成真实的迁移前表结构；该连接仅能看到本测试的随机 schema。
        async with engine.begin() as connection:
            for column in ("xlsx_path", "xlsx_size", "xlsx_sha256"):
                await connection.execute(text(f"ALTER TABLE report_download_grants_v2 DROP COLUMN {column}"))
        await repository.create_schema()
        await repository.create_schema()
        for token, previous in old_tokens:
            assert await grants.lookup(token) == previous

        content = b"isolated synthetic workbook payload"
        digest = hashlib.sha256(content).hexdigest()
        workspace = _Workspace({"reports/report.xlsx": content})
        artifacts = SqlAlchemyReportArtifactRepository(engine)
        await ReportArtifactPersistenceService(artifacts, workspace).persist(
            scope=_scope(), report_id="xlsx", revision=1,
            artifacts=(ReportArtifactSpec("xlsx", "reports/report.xlsx", len(content), digest),),
        )
        token, _ = await grants.issue(
            scope=_scope(), report_id="xlsx", revision=1,
            xlsx_path="reports/report.xlsx", xlsx_size=len(content), xlsx_sha256=digest,
        )
        # 超过回收宽限期后，有效 XLSX 授权仍须保留产物。
        async with engine.begin() as connection:
            await connection.execute(text("UPDATE report_artifact_files_v1 SET created_at = :created_at"),
                                     {"created_at": datetime.now(UTC) - timedelta(days=2)})
        await repository.cleanup_expired(now=datetime.now(UTC))
        workspace.remove_files()
        grant, stream = await ReportDownloadHttpService(grants, artifacts).stream(token, artifact="xlsx")
        assert grant.xlsx_sha256 == digest
        assert b"".join([chunk async for chunk in stream]) == content
    finally:
        await engine.dispose()
        async with admin.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await admin.dispose()

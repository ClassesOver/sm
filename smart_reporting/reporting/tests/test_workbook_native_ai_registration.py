"""XLSX AI 原生上下文的总开关与编辑权限装配。"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from smart_reporting.report_editor.native_api import (
    NATIVE_SESSION_COOKIE,
    create_native_editor_router,
)
from smart_reporting.report_editor.native_models import (
    NATIVE_MEDIA,
    NativeEditorContext,
)
from smart_reporting.office.editor_grants import (
    InMemoryReportEditorRepository,
    ReportEditorGrantService,
)


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("enabled", "office_enabled", "expected"),
    [(True, True, True), (False, True, False), (True, False, False)],
)
async def test_native_xlsx_context_requires_ai_and_office_permission(
    enabled, office_enabled, expected
):
    context = NativeEditorContext(
        documentId="book-ai",
        revision=1,
        format="xlsx",
        origin="upload",
        scope={
            "database": "db",
            "companyId": "co",
            "userId": "user",
            "threadId": "thread",
        },
        sourceFile={
            "path": "native/probe.xlsx",
            "size": 10,
            "sha256": "a" * 64,
            "mediaType": NATIVE_MEDIA["xlsx"],
        },
    )
    grants = ReportEditorGrantService(InMemoryReportEditorRepository(), secret="s" * 32)
    raw, _ = await grants.issue(context, capabilities={})
    token, _ = await grants.exchange(raw)
    editor = SimpleNamespace(
        context_for_session=AsyncMock(return_value=context),
        office_enabled=office_enabled,
        docx_enabled=False,
        pdf_enabled=False,
        pdf_text_enabled=False,
        is_enabled=lambda _: office_enabled,
    )
    app = FastAPI()
    app.include_router(
        create_native_editor_router(grants, editor=editor, ai_enabled=enabled)
    )
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        client.cookies.set(NATIVE_SESSION_COOKIE, token)
        response = await client.get("/reports/v1/native/book-ai/1/api/context")
    assert response.status_code == 200, response.text
    assert response.json()["aiEnabled"] is expected
    assert response.json()["editingEnabled"] is office_enabled

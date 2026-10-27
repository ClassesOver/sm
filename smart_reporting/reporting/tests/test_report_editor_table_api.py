from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from smart_reporting.report_editor.api import create_report_editor_router
from smart_reporting.report_editor.service import (
    InMemoryReportEditorRepository,
    ReportEditorGrantService,
    ReportEditorSession,
)
from smart_reporting.reporting.models import ReportingError


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_table_edit_record_can_be_resolved_from_accepted_table_id() -> None:
    class Editor:
        async def context_for_session(self, session: ReportEditorSession) -> SimpleNamespace:
            return SimpleNamespace(report_id=session.report_id, revision=session.revision)

    class TableAI:
        async def edit_record_by_table_id(
            self, context: SimpleNamespace, table_id: str
        ) -> dict[str, str]:
            if table_id == "missing":
                raise ReportingError("report_editor_table_ai_missing", "改表登记不存在。")
            return {
                "editId": "tedit-0123456789abcdef",
                "tableId": "table-original",
                "newTableId": table_id,
                "markdown": "[[table:table-new]]\n| 指标 |\n| --- |\n| 收入 |\n\n[[/table:table-new]]",
            }

    repository = InMemoryReportEditorRepository()
    grants = ReportEditorGrantService(repository, secret="s" * 32)
    await repository.put_session(
        hashlib.sha256(b"session-1").hexdigest(),
        ReportEditorSession(
            report_id="report-1",
            revision=1,
            workflow_run_id="report-1",
            context_sha256="0" * 64,
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        ),
    )
    app = FastAPI()
    app.include_router(
        create_report_editor_router(
            grants, editor=Editor(), table_ai=TableAI(), cookie_secure=False
        )
    )
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="https://reports.example.com"
    ) as client:
        client.cookies.set("report_editor_session", "session-1")
        base = "/reports/v1/editor/report-1/1/api/table-edits/by-table"
        response = await client.get(f"{base}/table-new")
        assert response.status_code == 200
        assert response.json()["tableId"] == "table-original"
        assert response.json()["newTableId"] == "table-new"
        missing = await client.get(f"{base}/missing")
        assert missing.status_code == 404


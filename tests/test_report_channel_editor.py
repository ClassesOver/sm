from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient

from smart_reporting.report_channel_editor import report_channel_editor_authorizer
from smart_reporting.report_editor.native_api import NATIVE_SESSION_COOKIE


@pytest.mark.anyio
async def test_editor_channel_is_bound_to_word_session_and_csrf():
    context = SimpleNamespace(format="docx", document_id="synthetic-document", revision=1)
    grants = SimpleNamespace(lookup_session=AsyncMock(return_value="synthetic-session"),
        csrf_token=lambda token: "csrf-" + token)
    editor = SimpleNamespace(grants=grants, context_for_session=AsyncMock(return_value=context),
        is_enabled=lambda format: format == "docx")
    resolve = AsyncMock(return_value="synthetic-channel")
    origin = "https://reports.test"
    authorize = report_channel_editor_authorizer(editor, resolve, allowed_origin=origin)
    app = FastAPI()

    @app.post("/share")
    @app.post("/share/{document_id}/{revision}")
    async def share(request: Request):
        return await authorize(request)

    async with AsyncClient(transport=ASGITransport(app=app), base_url=origin) as client:
        assert (await client.post("/share")).json() is None
        client.cookies.set(NATIVE_SESSION_COOKIE, "synthetic-token")
        assert (await client.post("/share")).status_code == 403
        headers = {"Origin": origin, "X-CSRF-Token": "csrf-synthetic-token"}
        assert (await client.post("/share", headers=headers)).json() == "synthetic-channel"
        resolve.assert_awaited_once_with(context)
        assert (await client.post("/share/other-document/1", headers=headers)).json() is None
        assert (await client.post("/share/synthetic-document/2", headers=headers)).json() is None
        assert (await client.post("/share/synthetic-document/1", headers=headers)).json() == "synthetic-channel"
        context.format = "pdf"
        assert (await client.post("/share", headers=headers)).json() is None

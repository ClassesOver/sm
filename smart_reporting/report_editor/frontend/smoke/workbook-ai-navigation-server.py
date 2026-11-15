"""Native HTTP/grants and Agno navigation; only provider/revision storage use fixtures."""

import asyncio
import hashlib
import json
import os
from contextlib import asynccontextmanager
from io import BytesIO
from pathlib import Path
from runpy import run_path

import uvicorn
from agno.agent import Agent
from agno.models.response import ModelResponse
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from openpyxl import Workbook

from smart_reporting.report_editor.native_ai_api import create_native_ai_router
from smart_reporting.report_editor.native_api import create_native_editor_router
from smart_reporting.report_editor.native_models import NativeArtifacts
from smart_reporting.report_editor.native_office_read_tasks import NativeOfficeReadService
from smart_reporting.report_editor.native_workbook_read_ai import AgnoNativeWorkbookReadPlanner
from smart_reporting.report_editor.workbook_ai import AgnoWorkbookProposalPlanner
from smart_reporting.report_editor.workbook_native_ai import NativeWorkbookAIService
from smart_reporting.report_editor.workbook_native_ai_api import create_native_workbook_ai_router
from smart_reporting.reporting.delivery.artifacts_v1 import ArtifactFile
from smart_reporting.reporting.tests.test_native_pdf_ai import ScriptedModel
from smart_reporting.reporting.tests.test_native_pdf_extract import extract_fixture


async def create(directory, port):
    f = await extract_fixture(directory / "runtime")
    book = Workbook()
    book.active.title = "First"
    book.active["A1"] = "original42"
    target = book.create_sheet("Target")
    target["K2000"] = "navigation-canary84"
    target["A2500"] = "extent"
    stream = BytesIO()
    book.save(stream)
    source = stream.getvalue()
    identity = ArtifactFile(
        path="native/source.xlsx",
        size=len(source),
        sha256=hashlib.sha256(source).hexdigest(),
        mediaType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    await f.workspace.awrite_bytes(f.thread, identity.path, source)
    f.parent = f.parent.model_copy(update={"format": "xlsx", "source_file": identity})
    root = Path(__file__).resolve().parent
    repository = run_path(str(root / "pdf-form-design-server.py"))["SaveRepository"]()
    row = f.repository.revisions[f.parent.document_id]
    repository.revisions[f.parent.document_id] = row.model_copy(
        update={"context": f.parent, "artifacts": NativeArtifacts(xlsx=identity)}
    )
    f.editor.repository = repository
    f.editor.office_enabled = True
    f.publication.repository = repository
    origin = f"http://127.0.0.1:{port}"
    f.publication.public_base_url = origin
    model = ScriptedModel(
        id="browser-navigation",
        expected_tool_text="navigation_requested",
        responses=[
            ModelResponse(
                tool_calls=[
                    {
                        "id": "nav",
                        "type": "function",
                        "function": {
                            "name": "select_range",
                            "arguments": json.dumps({"range": "l2001:k2000"}),
                        },
                    }
                ]
            ),
            ModelResponse(
                content=json.dumps(
                    {"answer": "已请求定位到当前工作表的目标区域。", "citations": []}
                )
            ),
        ],
    )
    candidate_mode = os.environ.get("WORKBOOK_AI_NAVIGATION_CANDIDATE") == "1"
    candidate = NativeWorkbookAIService(
        f.editor, planner=AgnoWorkbookProposalPlanner(Agent(model=model)), enabled=True
    )
    service = NativeOfficeReadService(
        f.editor, planners={"xlsx": AgnoNativeWorkbookReadPlanner(model)}, enabled=True
    )

    @asynccontextmanager
    async def lifespan(app):
        yield
        await service.aclose()
        await candidate.aclose()
        await f.workspace.registry.aclose()

    app = FastAPI(lifespan=lifespan)
    static = run_path(str(root / "pdf_smoke_static.py"))["pdf_smoke_static_directory"]()
    app.include_router(
        create_native_editor_router(
            f.publication.editor_grants,
            editor=f.editor,
            download_service=f.downloads,
            cookie_secure=False,
            allowed_origin=origin,
            static_dir=static,
            ai_enabled=True,
        )
    )
    app.include_router(
        create_native_ai_router(
            f.publication.editor_grants,
            editor=f.editor,
            ai=None,
            office_read=service,
            allowed_origin=origin,
        )
    )
    if candidate_mode:
        app.include_router(
            create_native_workbook_ai_router(
                f.publication.editor_grants, editor=f.editor, ai=candidate, allowed_origin=origin
            )
        )
    app.mount("/reports/v1/editor/assets", StaticFiles(directory=static))
    requests = []

    @app.middleware("http")
    async def record(request: Request, call_next):
        response = await call_next(request)
        path = request.url.path
        if path.startswith("/reports/v1/native/open/"):
            path = "/reports/v1/native/open/<fixture-grant>"
        requests.append({"method": request.method, "path": path, "status": response.status_code})
        return response

    @app.get("/__smoke__/state")
    async def state():
        actual = await f.editor.read_file(f.parent)
        return {
            "sha256": hashlib.sha256(actual).hexdigest(),
            "saved": len(repository.saved),
            "requests": requests,
        }

    raw, _ = await f.publication.editor_grants.issue(
        f.parent, capabilities=f.editor.capabilities(f.parent)
    )
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "info.json").write_text(
        json.dumps({"openPath": f"/reports/v1/native/open/{raw}", "sha256": identity.sha256})
    )
    return app


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--port", type=int, default=4367)
    args = parser.parse_args()
    directory = args.directory
    port = args.port
    uvicorn.run(
        asyncio.run(create(directory, port)), host="127.0.0.1", port=port, log_level="warning"
    )

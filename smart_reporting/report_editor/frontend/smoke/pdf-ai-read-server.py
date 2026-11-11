"""仅本地验收：真实 HTTP/授权/引擎/Agno，模型为脚本替身而非 provider。"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from contextlib import asynccontextmanager
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import uvicorn
from agno.models.response import ModelResponse
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from reportlab.pdfgen.canvas import Canvas

from smart_reporting.report_editor.native import (
    NativeEditorService,
    bind_native_workspace,
)
from smart_reporting.report_editor.native_ai_api import create_native_ai_router
from smart_reporting.report_editor.native_api import create_native_editor_router
from smart_reporting.report_editor.native_models import NativeEditorContext, NativeScope
from smart_reporting.report_editor.native_pdf_ai import create_native_pdf_read_planner
from smart_reporting.report_editor.native_pdf_ai_tasks import NativePDFReadService
from smart_reporting.report_editor.service import (
    InMemoryReportEditorRepository,
    ReportEditorGrantService,
)
from smart_reporting.reporting.delivery.artifacts_v1 import ArtifactFile
from smart_reporting.reporting.delivery.pdf_native import inspect_pdf
from smart_reporting.reporting.host_workspace import (
    ReportingWorkspaceRegistry,
    ReportingWorkspaceRouter,
)
from smart_reporting.reporting.tests.test_native_pdf_ai import ScriptedModel


async def create_app(directory: Path, port: int, *, draft: bool = False) -> FastAPI:
    stream = BytesIO()
    canvas = Canvas(stream, pagesize=(400, 350))
    canvas.bookmarkPage("summary")
    canvas.addOutlineEntry("Financial overview", "summary", 0)
    canvas.drawString(30, 290, "Revenue is 42. Confirmed source amount.")
    canvas.textAnnotation("Please verify revenue before approval.", (30, 180, 50, 200))
    canvas.showPage()
    canvas.drawString(30, 290, "Second page: expenses are 12.")
    canvas.save()
    content = stream.getvalue()
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "source.pdf").write_bytes(content)
    scope = NativeScope(
        database="smoke", companyId="company", userId="reader", threadId="pdf-ai-read"
    )
    workspace = ReportingWorkspaceRouter(
        ReportingWorkspaceRegistry(directory / "workspace", secret="w" * 32)
    )
    await workspace.awrite_bytes(
        bind_native_workspace(workspace, scope), "native/source.pdf", content
    )
    context = NativeEditorContext(
        documentId="pdf-ai-smoke",
        revision=1,
        format="pdf",
        origin="upload",
        scope=scope,
        sourceFile=ArtifactFile(
            path="native/source.pdf",
            size=len(content),
            sha256=hashlib.sha256(content).hexdigest(),
            mediaType="application/pdf",
        ),
    )

    class ScopedRepository:
        async def get_revision(self, document_id, revision, *, scope):
            if (
                document_id == context.document_id
                and revision == context.revision
                and scope == context.scope
            ):
                return SimpleNamespace(status="saved", context=context)
            return None

    grants = ReportEditorGrantService(InMemoryReportEditorRepository(), secret="g" * 32)
    editor = NativeEditorService(
        workspace,
        ScopedRepository(),
        grants,
        report_editor=None,
        pdf_enabled=draft,
        pdf_text_enabled=draft,
    )
    model = ScriptedModel(
        id="scripted-pdf-read-smoke",
        expected_tool_text="Revenue is 42.",
        responses=[
            ModelResponse(
                tool_calls=[
                    {
                        "id": "pages",
                        "type": "function",
                        "function": {
                            "name": "read_pages",
                            "arguments": '{"start_page":1,"page_count":2}',
                        },
                    },
                    {
                        "id": "notes",
                        "type": "function",
                        "function": {"name": "read_annotations", "arguments": "{}"},
                    },
                    {
                        "id": "outline",
                        "type": "function",
                        "function": {"name": "get_outline", "arguments": "{}"},
                    },
                ]
            ),
            ModelResponse(
                content=json.dumps(
                    {
                        "answer": "第1页收入为42，第2页费用为12。批注要求核实收入；作者和处理状态未知。本次只读，未修改文档。",
                        "citations": [1, 2],
                    },
                    ensure_ascii=False,
                )
            ),
        ],
    )
    gate = {"blockNext": False, "blockedEntered": False, "blockedCancelled": False}
    actual_planner = create_native_pdf_read_planner(model)
    draft_fixtures = {}
    if draft:
        source_model = inspect_pdf(content, include_text=True)
        first, second = source_model["pages"]
        target = first["textObjects"][0]
        replace = {
            "kind": "replaceText",
            "pageId": first["pageId"],
            "objectId": target["objectId"],
            "expectedTextSha256": target["expectedTextSha256"],
            "newText": "Revenue is 72.",
        }
        draft_fixtures = {
            "text": [replace],
            "reorder": [
                replace,
                {
                    "kind": "reorderPages",
                    "pageIds": [second["pageId"], first["pageId"]],
                },
            ],
            "partial": [
                {**replace, "expectedTextSha256": "0" * 64},
                {"kind": "rotatePage", "pageId": second["pageId"], "delta": 90},
            ],
            "blank": [
                {
                    "kind": "insertBlankPage",
                    "pageId": "blank:ai-read",
                    "width": 400,
                    "height": 350,
                },
                {
                    "kind": "reorderPages",
                    "pageIds": ["blank:ai-read", first["pageId"], second["pageId"]],
                },
            ],
        }

    async def planner(**kwargs):
        if gate["blockNext"]:
            gate["blockNext"] = False
            gate["blockedEntered"] = True
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                gate["blockedCancelled"] = True
                raise
        if not draft:
            return await actual_planner(**kwargs)
        projection = kwargs["draft_projection"]
        applied = projection.projection["appliedOperationIndices"]
        changed = any(kwargs["operations"][i]["kind"] == "replaceText" for i in applied)
        amount = 72 if changed else 42
        draft_model = ScriptedModel(
            id="scripted-pdf-draft-smoke",
            expected_tool_text=f"Revenue is {amount}.",
            responses=[
                ModelResponse(
                    tool_calls=[
                        {
                            "id": "draft-pages",
                            "type": "function",
                            "function": {
                                "name": "read_pages",
                                "arguments": '{"start_page":1,"page_count":10}',
                            },
                        }
                    ]
                ),
                ModelResponse(
                    content=json.dumps(
                        {
                            "answer": f"实际草稿收入为{amount}，仅根据投影后的正文回答，未保存或改变草稿。",
                            "citations": list(range(1, len(projection.pages) + 1)),
                        },
                        ensure_ascii=False,
                    )
                ),
            ],
        )
        return await create_native_pdf_read_planner(draft_model)(**kwargs)

    ai = NativePDFReadService(editor, planner=planner, enabled=True)

    @asynccontextmanager
    async def lifespan(app):
        yield
        await ai.aclose()

    app = FastAPI(lifespan=lifespan)
    origin = f"http://127.0.0.1:{port}"
    app.include_router(
        create_native_editor_router(
            grants,
            editor=editor,
            cookie_secure=False,
            allowed_origin=origin,
            ai_enabled=True,
        )
    )
    app.include_router(
        create_native_ai_router(
            grants, editor=editor, ai=None, pdf_read=ai, allowed_origin=origin
        )
    )
    static = Path(__file__).resolve().parents[2] / "static"
    app.mount("/reports/v1/editor/assets", StaticFiles(directory=static))
    requests = []

    @app.middleware("http")
    async def record(request: Request, call_next):
        response = await call_next(request)
        requests.append(
            {
                "method": request.method,
                "path": request.url.path,
                "status": response.status_code,
            }
        )
        (directory / "http-evidence.json").write_text(
            json.dumps(requests, ensure_ascii=False, indent=2)
        )
        return response

    @app.get("/__smoke__/state")
    async def state():
        current = await editor.read_file(context)
        return {
            "sourceSha256": hashlib.sha256(current).hexdigest(),
            "originalSha256": context.source_file.sha256,
            "jobs": [{**ai._serialize(job)} for job in ai._jobs.values()],
            "requests": requests,
            "editingEnabled": editor.pdf_enabled,
            "pdfTextEnabled": editor.pdf_text_enabled,
            "draftMode": draft,
            "provider": "scripted-model-not-real-provider",
            **gate,
        }

    @app.post("/__smoke__/block-next")
    async def block_next():
        gate["blockNext"] = True
        return {"armed": True}

    raw, _ = await grants.issue(context, capabilities=editor.capabilities(context))
    (directory / "server-info.json").write_text(
        json.dumps(
            {
                "openPath": f"/reports/v1/native/open/{raw}",
                "sourceSha256": context.source_file.sha256,
                "context": context.model_dump(mode="json", by_alias=True),
                "draftFixtures": draft_fixtures,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return app


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--port", type=int, default=4285)
    parser.add_argument("--draft", action="store_true")
    args = parser.parse_args()
    uvicorn.run(
        asyncio.run(create_app(args.directory, args.port, draft=args.draft)),
        host="127.0.0.1",
        port=args.port,
        log_level="warning",
    )

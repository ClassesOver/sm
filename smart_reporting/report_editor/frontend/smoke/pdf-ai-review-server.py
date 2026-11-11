"""本地专项：真实 HTTP/授权/PDF/Agno；ScriptedModel 不代表真实 provider。"""

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
from pypdf import PdfReader, PdfWriter
from pypdf.annotations import Text
from pypdf.generic import NameObject, TextStringObject
from reportlab.pdfgen.canvas import Canvas

from smart_reporting.report_editor.native import NativeEditorService, bind_native_workspace
from smart_reporting.report_editor.native_api import create_native_editor_router
from smart_reporting.report_editor.native_models import NativeEditorContext, NativeScope
from smart_reporting.report_editor.native_pdf_review_ai import create_native_pdf_review_planner
from smart_reporting.report_editor.native_pdf_review_ai_api import (
    create_native_pdf_review_ai_router,
)
from smart_reporting.report_editor.native_pdf_review_ai_tasks import NativePDFReviewService
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


async def create_app(directory: Path, port: int):
    directory.mkdir(parents=True, exist_ok=True)
    stream = BytesIO()
    canvas = Canvas(stream, pagesize=(400, 350))
    canvas.drawString(30, 290, "Amount due 500")
    canvas.drawString(30, 240, "Keep this passage unchanged.")
    canvas.save()
    writer = PdfWriter(clone_from=PdfReader(BytesIO(stream.getvalue())))
    for index, (contents, author) in enumerate(
        [
            ("Change Amount due 500 to Amount due 700.", "Reviewer"),
            ("An earlier AI comment, do not process it again.", "AI Assistant"),
            ("Thank you, this is discussion only; no change needed.", "Reviewer"),
        ]
    ):
        note = Text(rect=(30 + index * 40, 170, 50 + index * 40, 190), text=contents)
        note[NameObject("/T")] = TextStringObject(author)
        writer.add_annotation(0, note)
    output = BytesIO()
    writer.write(output)
    content = output.getvalue()
    (directory / "source.pdf").write_bytes(content)
    scope = NativeScope(
        database="smoke", companyId="company", userId="reviewer", threadId="pdf-ai-review"
    )
    workspace = ReportingWorkspaceRouter(
        ReportingWorkspaceRegistry(directory / "workspace", secret="w" * 32)
    )
    await workspace.awrite_bytes(
        bind_native_workspace(workspace, scope), "native/source.pdf", content
    )
    context = NativeEditorContext(
        documentId="pdf-ai-review-smoke",
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
        pdf_enabled=True,
        pdf_text_enabled=True,
    )
    annotations = inspect_pdf(content, include_text=True)["pages"][0]["notes"]
    gate = {
        "mode": "normal",
        "blockedEntered": False,
        "blockedCancelled": False,
        "providerCalls": 0,
    }

    def call(name, arguments, identifier):
        return ModelResponse(
            tool_calls=[
                {
                    "id": identifier,
                    "type": "function",
                    "function": {
                        "name": name,
                        "arguments": json.dumps(arguments, ensure_ascii=False),
                    },
                }
            ]
        )

    async def planner(**kwargs):
        gate["providerCalls"] += 1
        if gate["mode"] == "cancel":
            gate["blockedEntered"] = True
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                gate["blockedCancelled"] = True
                return {"answer": "迟到候选不得复活", "operations": [], "replies": [], "notes": []}
        if gate["mode"] == "pending":
            reader = kwargs["reader"]
            target = next(
                m for m in reader.projection["pendingNoteMapping"] if m["operationIndex"] == 1
            )
            responses = [call("read_annotations", {}, "notes"), call("read_pages", {}, "body")]
            for index, note in enumerate(reader.pages[0]["notes"]):
                if note["annotationId"] != target["annotationId"]:
                    responses.append(
                        call(
                            "skip_note",
                            {
                                "annotation_id": note["annotationId"],
                                "reason": "本轮只处理第二条待保存批注，其余原批注与重复根保持原样。",
                            },
                            "skip-" + str(index),
                        )
                    )
            responses.extend(
                [
                    call(
                        "propose_replace_text",
                        {
                            "annotation_id": target["annotationId"],
                            "page_number": 1,
                            "old_text": "Amount due 500",
                            "new_text": "Amount due 700",
                            "reason": "按第二条未保存批注更正",
                        },
                        "replace-pending",
                    ),
                    call(
                        "propose_reply",
                        {
                            "annotation_id": target["annotationId"],
                            "contents": "已按第二条待保存批注将金额改为700。",
                            "intent": "change",
                        },
                        "reply-pending",
                    ),
                    ModelResponse(
                        content=json.dumps(
                            {"answer": "第二条待保存批注已生成改字和回复候选，其他草稿保持原样。"},
                            ensure_ascii=False,
                        )
                    ),
                ]
            )
            return await create_native_pdf_review_planner(
                ScriptedModel(id="scripted-pdf-pending-review-smoke", responses=responses)
            )(**kwargs)
        primary, own, discussion = [n["annotationId"] for n in annotations]
        responses = [call("read_annotations", {}, "notes"), call("read_pages", {}, "body")]
        mode = gate["mode"]
        if mode in {"normal", "overflow"}:
            responses.extend(
                [
                    call(
                        "propose_replace_text",
                        {
                            "annotation_id": primary,
                            "page_number": 1,
                            "old_text": "Amount due 500",
                            "new_text": "Amount due 700"
                            if mode == "normal"
                            else "Cannot fit into this PDF line. " * 80,
                            "reason": "依批注更正应付金额",
                        },
                        "replace",
                    ),
                    call(
                        "propose_reply",
                        {
                            "annotation_id": primary,
                            "contents": "已将应付金额由500改为700。",
                            "intent": "change",
                        },
                        "reply",
                    ),
                ]
            )
        elif mode == "clarify":
            responses.append(
                call(
                    "propose_reply",
                    {
                        "annotation_id": primary,
                        "contents": "请确认本次是否按700更正？",
                        "intent": "clarify",
                    },
                    "clarify",
                )
            )
        else:
            responses.append(
                call(
                    "skip_note",
                    {"annotation_id": primary, "reason": "本次仅讨论，不执行改字。"},
                    "discussion-primary",
                )
            )
        responses.extend(
            [
                call(
                    "skip_note",
                    {"annotation_id": own, "reason": "AI 自身批注，不重复处理。"},
                    "own",
                ),
                call(
                    "skip_note",
                    {"annotation_id": discussion, "reason": "纯讨论，没有修改行动。"},
                    "discussion",
                ),
                ModelResponse(
                    content=json.dumps(
                        {
                            "answer": "逐条建议已生成，实际应用与跳过以真实预览回执为准，待显式采纳。"
                        },
                        ensure_ascii=False,
                    )
                ),
            ]
        )
        return await create_native_pdf_review_planner(
            ScriptedModel(id="scripted-pdf-review-smoke", responses=responses)
        )(**kwargs)

    review = NativePDFReviewService(editor, planner=planner, enabled=True)

    @asynccontextmanager
    async def lifespan(app):
        yield
        await review.aclose()

    app = FastAPI(lifespan=lifespan)
    origin = f"http://127.0.0.1:{port}"
    app.include_router(
        create_native_editor_router(
            grants, editor=editor, cookie_secure=False, allowed_origin=origin, ai_enabled=True
        )
    )
    app.include_router(
        create_native_pdf_review_ai_router(
            grants, editor=editor, review=review, allowed_origin=origin
        )
    )
    app.mount(
        "/reports/v1/editor/assets",
        StaticFiles(directory=Path(__file__).resolve().parents[2] / "static"),
    )
    requests = []

    @app.middleware("http")
    async def record(request: Request, call_next):
        response = await call_next(request)
        requests.append(
            {"method": request.method, "path": request.url.path, "status": response.status_code}
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
            "jobs": [review._serialize(j) for j in review._jobs.values()],
            "requests": requests,
            **gate,
        }

    @app.post("/__smoke__/mode/{mode}")
    async def mode(mode: str):
        assert mode in {"normal", "overflow", "clarify", "discussion", "cancel", "pending"}
        gate.update(mode=mode, blockedEntered=False, blockedCancelled=False)
        return gate

    @app.post("/__smoke__/verify")
    async def verify(request: Request):
        payload = await request.json()
        job = next(j for j in review._jobs.values() if j.task_id == payload["editId"])
        assert payload["operations"] == job.result["operations"]
        receipt = await editor.preview_file(
            context,
            expected_sha256=context.source_file.sha256,
            operations=payload["operations"],
            expected_preview_digest=job.result["previewDigest"],
        )
        pdf = PdfReader(BytesIO(receipt["content"]))
        notes = [raw.get_object() for page in pdf.pages for raw in page.get("/Annots", [])]
        replies = [n for n in notes if n.get("/IRT") is not None]
        (directory / (gate["mode"] + "-preview.pdf")).write_bytes(receipt["content"])
        return {
            "text": "\n".join(page.extract_text() for page in pdf.pages),
            "replyAuthors": [str(n.get("/T")) for n in replies],
            "replyContents": [str(n.get("/Contents")) for n in replies],
            "sha256": receipt["sha256"],
            "previewDigest": receipt["previewDigest"],
            "appliedOperationIndices": receipt["appliedOperationIndices"],
            "skippedOperations": receipt["skippedOperations"],
            "pendingNoteMapping": receipt.get("pendingNoteMapping", []),
            "replyParentRefs": [
                str(n.raw_get("/IRT").idnum) + "R" + str(n.raw_get("/IRT").generation or "")
                for n in replies
            ],
        }

    raw, _ = await grants.issue(context, capabilities=editor.capabilities(context))
    (directory / "server-info.json").write_text(
        json.dumps(
            {
                "openPath": f"/reports/v1/native/open/{raw}",
                "sourceSha256": context.source_file.sha256,
                "context": context.model_dump(mode="json", by_alias=True),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return app


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--port", type=int, default=4287)
    args = parser.parse_args()
    uvicorn.run(
        asyncio.run(create_app(args.directory, args.port)),
        host="127.0.0.1",
        port=args.port,
        log_level="warning",
    )

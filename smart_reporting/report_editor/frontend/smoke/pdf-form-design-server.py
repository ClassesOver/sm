"""Form Design 浏览器验收：真实路由与字节，仅持久化仓储使用内存。"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles

from smart_reporting.report_editor.native_api import create_native_editor_router
from smart_reporting.report_editor.native_models import NativeArtifacts, NativeRevision
from smart_reporting.report_editor.native_repository import NativeRepositoryConflict
from smart_reporting.reporting.delivery.artifacts_v1 import ArtifactFile
from smart_reporting.reporting.tests.test_native_pdf_extract import MemoryRepository, extract_fixture
from smart_reporting.reporting.tests.test_pdf_form_design import form_pdf


class SaveRepository(MemoryRepository):
    def __init__(self):
        super().__init__()
        self.reservations = {}
        self.saved = {}

    async def get_revision(self, document_id, revision, *, scope):
        result = self.saved.get((document_id, revision))
        if result and result.scope == scope:
            return result
        return await super().get_revision(document_id, revision, scope=scope)

    async def reserve_revision(self, document_id, *, parent_revision, request_id, request_sha256, scope, note=""):
        key = (document_id, request_id)
        if key in self.reservations:
            row = self.reservations[key]
            if row.request_sha256 != request_sha256 or row.parent_revision != parent_revision or row.scope != scope:
                raise NativeRepositoryConflict()
            return row
        row = NativeRevision(documentId=document_id, revision=parent_revision + 1,
            scope=scope, parentRevision=parent_revision, requestId=request_id,
            requestSha256=request_sha256, note=note, status="reserved", createdAt=datetime.now(UTC))
        self.reservations[key] = row
        return row

    async def complete_revision(self, reservation, *, context, artifacts, validation):
        result = reservation.model_copy(update={"context": context, "artifacts": artifacts, "validation": validation, "status": "saved"})
        self.reservations[(result.document_id, result.request_id)] = result
        self.saved[(result.document_id, result.revision)] = result
        return result

    async def fail_revision(self, reservation, *, code):
        self.reservations[(reservation.document_id, reservation.request_id)] = reservation.model_copy(update={"status": "failed", "failure_code": code})


async def create_app(directory: Path, port: int):
    directory.mkdir(parents=True, exist_ok=True)
    f = await extract_fixture(directory / "runtime")
    source = Path(os.environ["PDF_FORM_DESIGN_SOURCE"]).read_bytes() if os.environ.get("PDF_FORM_DESIGN_SOURCE") else form_pdf()
    identity = ArtifactFile(path=f.original_identity.path, size=len(source), sha256=hashlib.sha256(source).hexdigest(), mediaType="application/pdf")
    await f.workspace.awrite_bytes(f.thread, identity.path, source, overwrite=True, expected_sha256=f.original_identity.sha256)
    f.parent = f.parent.model_copy(update={"source_file": identity})
    repository = SaveRepository()
    original_row = f.repository.revisions[f.parent.document_id]
    repository.revisions[f.parent.document_id] = original_row.model_copy(update={"context": f.parent, "artifacts": NativeArtifacts(pdf=identity)})
    f.editor.repository = repository
    if os.environ.get("PDF_FORM_DESIGN_READ_ONLY") == "1":
        f.editor.pdf_enabled = False
    f.publication.repository = repository
    f.publication.public_base_url = origin = f"http://127.0.0.1:{port}"
    (directory / "source.pdf").write_bytes(source)
    requests = []

    @asynccontextmanager
    async def lifespan(_app):
        yield
        await f.workspace.registry.aclose()

    app = FastAPI(lifespan=lifespan)
    static_root = Path(os.environ.get("PDF_FORM_DESIGN_STATIC_ROOT", Path(__file__).resolve().parents[2] / "static"))
    app.include_router(create_native_editor_router(f.publication.editor_grants, editor=f.editor,
        download_service=f.downloads, cookie_secure=False, allowed_origin=origin, static_dir=static_root))
    app.mount("/reports/v1/editor/assets", StaticFiles(directory=static_root))

    @app.middleware("http")
    async def record(request: Request, call_next):
        response = await call_next(request)
        requests.append({"method": request.method, "path": request.url.path, "status": response.status_code})
        (directory / "http-evidence.json").write_text(json.dumps(requests, indent=2))
        return response

    @app.get("/__smoke__/state")
    async def state():
        actual = await f.editor.read_file(f.parent)
        return {"sourceSha256": hashlib.sha256(actual).hexdigest(), "savedRevisions": len(repository.saved), "requests": requests}

    raw, _ = await f.publication.editor_grants.issue(f.parent, capabilities=f.editor.capabilities(f.parent))
    (directory / "server-info.json").write_text(json.dumps({"openPath": f"/reports/v1/native/open/{raw}", "sourceSha256": identity.sha256, "context": f.parent.model_dump(mode="json", by_alias=True)}, indent=2))
    return app


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--port", type=int, default=4297)
    args = parser.parse_args()
    uvicorn.run(asyncio.run(create_app(args.directory, args.port)), host="127.0.0.1", port=args.port, log_level="warning")

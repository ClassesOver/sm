"""Resume the actual saved Scatter r5 for read-only HTTP/UI acceptance."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import quote

import uvicorn
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles

from smart_reporting.report_editor.native_api import create_native_editor_router
from smart_reporting.report_editor.native_models import NativeEditorContext
from smart_reporting.reporting.tests.test_native_pdf_extract import MemoryRepository, extract_fixture


async def create_app(directory: Path, port: int, receipt_path: Path, artifact_path: Path):
    receipt_bytes = receipt_path.read_bytes()
    receipt = json.loads(receipt_bytes)
    context = NativeEditorContext.model_validate(receipt["context"])
    assert context.document_id == "parent-document" and context.revision == 5 and context.parent_revision == 4
    identity = context.source_file
    assert receipt["artifacts"]["xlsx"] == identity.model_dump(mode="json", by_alias=True)
    content = artifact_path.read_bytes()
    assert len(content) == identity.size and hashlib.sha256(content).hexdigest() == identity.sha256
    f = await extract_fixture(directory / "runtime")
    await f.workspace.awrite_bytes(f.thread, identity.path, content)
    repository = MemoryRepository()
    # Only the already persisted context is seeded into the scoped test repository.
    # No reservation, publication, validation, or new revision is manufactured.
    repository.revisions[context.document_id] = SimpleNamespace(
        revision=context.revision, scope=context.scope, status="saved", context=context,
    )
    f.editor.repository = repository
    f.editor.office_enabled = True
    assert await f.editor.read_file(context) == content
    origin = f"http://127.0.0.1:{port}"
    static = Path(os.environ["PDF_SMOKE_STATIC_DIRECTORY"]).resolve(strict=True)
    requests = []

    @asynccontextmanager
    async def lifespan(_app):
        yield
        await f.workspace.registry.aclose()

    app = FastAPI(lifespan=lifespan)
    app.include_router(create_native_editor_router(
        f.publication.editor_grants, editor=f.editor, download_service=f.downloads,
        cookie_secure=False, allowed_origin=origin, static_dir=static,
    ))
    app.mount("/reports/v1/editor/assets", StaticFiles(directory=static))

    @app.middleware("http")
    async def record(request: Request, call_next):
        response = await call_next(request)
        requests.append({"method": request.method, "path": request.url.path, "status": response.status_code})
        (directory / "http-evidence.json").write_text(json.dumps(requests, indent=2))
        return response

    @app.get("/__smoke__/state")
    async def state():
        actual = await f.editor.read_file(context)
        return {"context": context.model_dump(mode="json", by_alias=True),
                "sourceSha256": hashlib.sha256(actual).hexdigest(),
                "postSaveRequests": sum(row["method"] == "POST" and row["path"].endswith("/api/save") for row in requests),
                "requests": requests}

    capabilities = {**f.editor.capabilities(context),
                    "context": context.model_dump(mode="json", by_alias=True),
                    "artifacts": {"xlsx": identity.model_dump(mode="json", by_alias=True)}}
    open_grant, _ = await f.publication.editor_grants.issue(context, capabilities=capabilities)
    download_grant, _ = await f.publication.editor_grants.issue(context, capabilities=capabilities)
    (directory / "server-info.json").write_text(json.dumps({
        "context": context.model_dump(mode="json", by_alias=True),
        "openPath": f"/reports/v1/native/open/{quote(open_grant, safe='')}",
        "downloadPath": f"/reports/v1/native/download/{quote(download_grant, safe='')}/xlsx",
        "restoredReceiptPath": str(receipt_path),
        "restoredReceiptSha256": hashlib.sha256(receipt_bytes).hexdigest(),
        "restoredArtifactPath": str(artifact_path), "originalSaveResponseAvailable": False,
        "fixtureRepository": "existing saved r5 context only; no reserve/save/publish or validation synthesis",
    }, indent=2))
    return app


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--port", type=int, default=4393)
    args = parser.parse_args()
    uvicorn.run(asyncio.run(create_app(args.directory, args.port, args.receipt, args.artifact)),
                host="127.0.0.1", port=args.port, log_level="warning")

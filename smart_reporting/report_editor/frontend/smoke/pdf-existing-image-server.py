"""已有图像移动缩放浏览器验收：真实路由与字节，仅持久化仓储使用内存。"""
from __future__ import annotations

import argparse
import base64
import fitz
import asyncio
import hashlib
import json
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from loguru import logger
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles

from smart_reporting.report_editor.native_api import create_native_editor_router
from smart_reporting.report_editor.native_models import NativeArtifacts
from smart_reporting.reporting.delivery.artifacts_v1 import ArtifactFile
from smart_reporting.reporting.tests.test_native_pdf_extract import extract_fixture
from smart_reporting.reporting.tests.test_native_pdf_extract import source_pdf


from runpy import run_path
SaveRepository = run_path(str(Path(__file__).with_name('pdf-form-design-server.py')))['SaveRepository']


async def create_app(directory: Path, port: int):
    directory.mkdir(parents=True, exist_ok=True)
    logger.info("smoke_fixture_initializing")
    f = await extract_fixture(directory / "runtime")
    logger.info("smoke_fixture_ready")
    f.editor.pdf_text_enabled = True
    document = fitz.open(stream=source_pdf(), filetype="pdf")
    png = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==")
    document[0].insert_image(fitz.Rect(60, 230, 160, 310), stream=png, keep_proportion=False)
    source = document.tobytes()
    document.close()
    identity = ArtifactFile(path=f.original_identity.path, size=len(source), sha256=hashlib.sha256(source).hexdigest(), mediaType="application/pdf")
    await f.workspace.awrite_bytes(f.thread, identity.path, source, overwrite=True, expected_sha256=f.original_identity.sha256)
    f.parent = f.parent.model_copy(update={"source_file": identity})
    repository = SaveRepository()
    original_row = f.repository.revisions[f.parent.document_id]
    repository.revisions[f.parent.document_id] = original_row.model_copy(update={"context": f.parent, "artifacts": NativeArtifacts(pdf=identity)})
    f.editor.repository = repository
    f.publication.repository = repository
    f.publication.public_base_url = origin = f"http://127.0.0.1:{port}"
    (directory / "source.pdf").write_bytes(source)
    requests = []

    @asynccontextmanager
    async def lifespan(_app):
        yield
        await f.workspace.registry.aclose()

    app = FastAPI(lifespan=lifespan)
    app.include_router(create_native_editor_router(f.publication.editor_grants, editor=f.editor,
        download_service=f.downloads, cookie_secure=False, allowed_origin=origin))
    app.mount("/reports/v1/editor/assets", StaticFiles(directory=Path(__file__).resolve().parents[2] / "static"))

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
    logger.info("smoke_app_ready")
    return app


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--port", type=int, default=4302)
    args = parser.parse_args()
    uvicorn.run(asyncio.run(create_app(args.directory, args.port)), host="127.0.0.1", port=args.port, log_level="warning")

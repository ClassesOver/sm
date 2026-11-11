"""本地提取验收：真实授权/发布/下载与 PDF 引擎，仅文档和授权仓储在内存中。"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from contextlib import asynccontextmanager
from io import BytesIO
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from pypdf import PdfReader

from smart_reporting.report_editor.native_api import create_native_editor_router
from smart_reporting.reporting.tests.test_native_pdf_extract import extract_fixture


async def create_app(directory: Path, port: int) -> FastAPI:
    directory.mkdir(parents=True, exist_ok=True)
    fixture = await extract_fixture(directory / "runtime")
    origin = f"http://127.0.0.1:{port}"
    fixture.publication.public_base_url = origin
    (directory / "source.pdf").write_bytes(fixture.original)
    requests = []

    @asynccontextmanager
    async def lifespan(_app):
        yield
        await fixture.workspace.registry.aclose()

    app = FastAPI(lifespan=lifespan)
    app.include_router(create_native_editor_router(
        fixture.publication.editor_grants, editor=fixture.editor,
        download_service=fixture.downloads, cookie_secure=False, allowed_origin=origin,
    ))
    static = Path(__file__).resolve().parents[2] / "static"
    app.mount("/reports/v1/editor/assets", StaticFiles(directory=static))

    @app.middleware("http")
    async def record(request: Request, call_next):
        response = await call_next(request)
        requests.append({"method": request.method, "path": request.url.path, "status": response.status_code})
        (directory / "http-evidence.json").write_text(json.dumps(requests, ensure_ascii=False, indent=2))
        return response

    @app.get("/__smoke__/state")
    async def state():
        original = await fixture.editor.read_file(fixture.parent)
        children = []
        for child in fixture.repository.documents.values():
            identity = child.source.source_file
            content, _ = await fixture.workspace.afile_bytes(fixture.thread, identity.path)
            children.append({
                "documentId": child.document_id, "source": child.source.model_dump(mode="json", by_alias=True),
                "sha256": hashlib.sha256(content).hexdigest(), "size": len(content),
                "pageTexts": [page.extract_text().strip() for page in PdfReader(BytesIO(content)).pages],
            })
        return {"sourceSha256": hashlib.sha256(original).hexdigest(), "children": children, "requests": requests}

    raw, _ = await fixture.publication.editor_grants.issue(
        fixture.parent, capabilities=fixture.editor.capabilities(fixture.parent)
    )
    (directory / "server-info.json").write_text(json.dumps({
        "openPath": f"/reports/v1/native/open/{raw}",
        "sourceSha256": fixture.parent.source_file.sha256,
        "context": fixture.parent.model_dump(mode="json", by_alias=True),
    }, ensure_ascii=False, indent=2))
    return app


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--port", type=int, default=4296)
    args = parser.parse_args()
    uvicorn.run(asyncio.run(create_app(args.directory, args.port)), host="127.0.0.1", port=args.port, log_level="warning")

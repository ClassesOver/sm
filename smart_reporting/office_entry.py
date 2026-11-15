from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, JSONResponse


def create_office_entry_router(*, static_dir: str | Path | None = None) -> APIRouter:
    router = APIRouter()
    mount_editor_assets(router, static_dir)

    @router.api_route(
        "/reports/v1/editor/{retired_path:path}",
        methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        include_in_schema=False,
    )
    async def retired_report_editor() -> JSONResponse:
        return JSONResponse(
            {"detail": {"code": "report_editor_retired", "message": "旧报告编辑器已停用。"}},
            status_code=410,
            headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"},
        )

    router.add_api_route(
        "/reports/v1/editor", retired_report_editor, methods=["GET", "HEAD"], include_in_schema=False,
    )
    return router


def mount_editor_assets(router: APIRouter, static_dir: str | Path | None) -> Path:
    frontend_static = Path(static_dir) if static_dir else Path(__file__).with_name("report_editor") / "static"

    @router.get("/office", include_in_schema=False)
    async def open_office_workspace() -> FileResponse:
        page = frontend_static / "office.html"
        if not page.is_file():
            raise HTTPException(status_code=404)
        return FileResponse(page)

    @router.get("/reports/v1/editor/assets/{asset_path:path}", include_in_schema=False)
    async def read_editor_static(asset_path: str) -> FileResponse:
        root = frontend_static.resolve()
        target = (root / asset_path).resolve()
        if not target.is_relative_to(root) or not target.is_file():
            raise HTTPException(status_code=404)
        return FileResponse(target)

    return frontend_static

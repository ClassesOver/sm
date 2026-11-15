"""Office 入口层路由：GenOffice 首页、前端构建资源与旧报告编辑入口退役。"""

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse

# 报告工作流与旧 Markdown/幻灯片/工作簿编辑器已退役，旧链接统一返回 410。
RETIRED_EDITOR_PREFIXES = ("/reports/v1/editor", "/reports/v1/slides", "/reports/v1/workbooks")
_ALL_METHODS = ["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]


async def retired_report_editor() -> JSONResponse:
    return JSONResponse(
        {"detail": {"code": "report_editor_retired", "message": "旧报告编辑入口已停用，请在 Office 中打开文件。"}},
        status_code=410,
        headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"},
    )


def create_office_entry_router(*, static_dir: str | Path | None = None, office=None) -> APIRouter:
    router = APIRouter()
    # 静态资源先注册，优先于下面 /reports/v1/editor 的退役兜底匹配。
    frontend_static = mount_editor_assets(router, static_dir)

    @router.get('/office/admin', include_in_schema=False)
    async def office_admin(request: Request):
        if office is None:
            raise HTTPException(503, 'Office 管理服务不可用。')
        from .office.api import COOKIE
        from .office.repository import OfficeError
        try:
            actor = await office.authenticate(request.cookies.get(COOKIE, ''))
            async with office.transaction(actor) as connection:
                await office._user(connection, actor, admin=True)
        except OfficeError as error:
            raise HTTPException(error.status, error.message) from None
        page = frontend_static / 'office-admin.html'
        if not page.is_file(): raise HTTPException(404)
        return FileResponse(page, headers={'Cache-Control': 'no-store'})

    for prefix in RETIRED_EDITOR_PREFIXES:
        router.add_api_route(
            f"{prefix}/{{retired_path:path}}", retired_report_editor,
            methods=_ALL_METHODS, include_in_schema=False,
        )
        router.add_api_route(prefix, retired_report_editor, methods=["GET", "HEAD"], include_in_schema=False)
    return router


def mount_editor_assets(router: APIRouter, static_dir: str | Path | None) -> Path:
    frontend_static = Path(static_dir) if static_dir else Path(__file__).with_name("report_editor") / "static"

    @router.get("/office", include_in_schema=False)
    async def open_office_workspace() -> FileResponse:
        page = frontend_static / "office.html"
        if not page.is_file():
            raise HTTPException(status_code=404)
        return FileResponse(page)

    # 前端构建 base 为 /reports/v1/editor/assets/（office.html、native.html 引用的 JS/CSS/字体均在此）。
    @router.get("/reports/v1/editor/assets/{asset_path:path}", include_in_schema=False)
    async def read_editor_static(asset_path: str) -> FileResponse:
        root = frontend_static.resolve()
        target = (root / asset_path).resolve()
        if not target.is_relative_to(root) or not target.is_file():
            raise HTTPException(status_code=404)
        return FileResponse(target)

    return frontend_static

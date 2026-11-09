"""上传路由必须消费已验签作用域，分块限额并关闭临时文件。"""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from smart_reporting.http.security import CapabilityClaims
from smart_reporting.report_editor.native_import_api import create_native_import_router

@pytest.fixture
def anyio_backend():
    return "asyncio"


def app_for(*, claims=True, enabled=True):
    app = FastAPI()
    importer = SimpleNamespace(import_file=AsyncMock(return_value={"documentId":"doc", "revision":1}))
    @app.middleware("http")
    async def identity(request, call_next):
        if claims:
            request.state.capability = CapabilityClaims(database="hospital",user=7,company=3,thread="trusted",odoo_session="a"*64,issued_at=1,expires_at=2)
        return await call_next(request)
    app.include_router(create_native_import_router(importer, enabled=enabled))
    return app, importer


@pytest.mark.anyio
async def test_import_uses_verified_claims_and_only_one_file():
    app, importer = app_for()
    async with AsyncClient(transport=ASGITransport(app=app),base_url="http://test") as client:
        response=await client.post("/reports/v1/native/import",data={"requestId":"req"},files={"file":("../a.pdf",b"%PDF-test","application/pdf")},headers={"X-Workspace-Thread":"foreign"})
        assert response.status_code==200, response.text
        kwargs=importer.import_file.call_args.kwargs
        assert kwargs["scope"].model_dump(by_alias=True)=={"database":"hospital","userId":"7","companyId":"3","threadId":"trusted"}
        assert kwargs["content"]==b"%PDF-test"
        assert kwargs["request_id"]=="req"
        response=await client.post("/reports/v1/native/import",data={"requestId":"req","userId":"foreign"},files={"file":("a.pdf",b"%PDF-test")})
        assert response.status_code==422
        assert importer.import_file.await_count==1


@pytest.mark.anyio
@pytest.mark.parametrize("claims,enabled,status",[(False,True,403),(True,False,503)])
async def test_import_requires_verified_identity_and_flag(claims,enabled,status):
    app, importer=app_for(claims=claims,enabled=enabled)
    async with AsyncClient(transport=ASGITransport(app=app),base_url="http://test") as client:
        response=await client.post("/reports/v1/native/import",data={"requestId":"req"},files={"file":("a.pdf",b"%PDF-test")})
        assert response.status_code==status
        importer.import_file.assert_not_awaited()


@pytest.mark.anyio
async def test_import_rejects_oversize_stream_and_multiple_files():
    app, importer=app_for()
    async with AsyncClient(transport=ASGITransport(app=app),base_url="http://test") as client:
        response=await client.post("/reports/v1/native/import",data={"requestId":"req"},files=[("file",("a.pdf",b"pdf")),("file",("b.pdf",b"pdf"))])
        assert response.status_code==422
        response=await client.post("/reports/v1/native/import",data={"requestId":"req"},files={"file":("a.pdf",b"x"*(24*1024*1024+1))})
        assert response.status_code==413
        importer.import_file.assert_not_awaited()


@pytest.mark.anyio
async def test_import_real_middleware_verifies_capability_before_consuming_upload():
    from smart_reporting.app import require_workspace_capability
    from smart_reporting.tests.test_reporting_request_identity import SECRET, _capability
    app=FastAPI()
    app.state.agentos_context=SimpleNamespace(settings=SimpleNamespace(workspace_hmac_secret=SECRET))
    app.middleware('http')(require_workspace_capability)
    importer=SimpleNamespace(import_file=AsyncMock(return_value={'documentId':'doc'}))
    app.include_router(create_native_import_router(importer,enabled=True))
    async with AsyncClient(transport=ASGITransport(app=app),base_url='http://test') as client:
        headers={'X-Workspace-Thread':'thread-1','X-Workspace-Capability':_capability()}
        response=await client.post('/reports/v1/native/import',headers=headers,data={'requestId':'r'},files={'file':('a.pdf',b'x'*(13*1024*1024))})
        assert response.status_code==200, response.text
        assert importer.import_file.call_args.kwargs['scope'].user_id=='7'
        response=await client.post('/reports/v1/native/import',headers={**headers,'X-Workspace-Thread':'other'},data={'requestId':'r'},files={'file':('a.pdf',b'pdf')})
        assert response.status_code==401
        response=await client.post('/reports/v1/native/import',headers=headers,content=b'',extensions={'timeout':{'connect':10}},)
        assert response.status_code==422
        assert importer.import_file.await_count==1

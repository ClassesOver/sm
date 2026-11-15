import asyncio

import httpx
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import create_async_engine

from pwdlib import PasswordHash
from smart_reporting.office.api import create_office_router
from smart_reporting.office.repository import Identity, OfficeRepository


def test_standalone_login_csrf_and_persistent_library():
    async def scenario():
        engine = create_async_engine("sqlite+aiosqlite://")
        office = OfficeRepository(engine)
        await office.create_schema()
        password = "local-office-password"
        await office.bootstrap(Identity("db", "1", "10"), "Admin",
                               password_hash=PasswordHash.recommended().hash(password))
        app = FastAPI()
        app.include_router(create_office_router(office, public_origin="http://test", cookie_secure=False))
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                     base_url="http://test") as client:
            body = {"database": "db", "company": "1", "user": "10", "password": "wrong"}
            invalid_password = "not-to-be-echoed" * 30
            invalid = await client.post("/office/api/session", headers={"origin": "http://test"},
                                        json={**body, "password": invalid_password})
            assert invalid.status_code == 422
            assert invalid_password not in invalid.text
            assert invalid.json()["detail"][0]["loc"] == ["body", "password"]
            response = await client.post("/office/api/session", headers={"origin": "http://test"}, json=body)
            assert response.status_code == 401
            response = await client.post("/office/api/session", headers={"origin": "http://test"},
                                         json={**body, "password": password})
            assert response.status_code == 200
            csrf = response.json()["csrfToken"]
            space = (await client.get("/office/api/workspaces")).json()["items"][0]["id"]
            path = f"/office/api/workspaces/{space}/folders"
            assert (await client.post(path, json={"name": "Files"})).status_code == 403
            headers = {"origin": "http://test", "x-csrf-token": csrf}
            assert (await client.post(path, headers=headers, json={"name": "Files"})).status_code == 201
            library = (await client.get(f"/office/api/workspaces/{space}/library")).json()
            assert library["folders"][0]["name"] == "Files"
            rotated = "new-local-office-password"
            reset = await client.put("/office/api/admin/users/10/password", headers=headers, json={"password": rotated})
            assert reset.status_code == 200, reset.text
            assert (await client.get("/office/api/session")).status_code == 401
            assert (await client.post("/office/api/session", headers={"origin": "http://test"},
                                      json={**body, "password": password})).status_code == 401
            relogin = await client.post("/office/api/session", headers={"origin": "http://test"},
                                        json={**body, "password": rotated})
            assert relogin.status_code == 200
            headers["x-csrf-token"] = relogin.json()["csrfToken"]
            assert (await client.post("/office/api/logout", headers=headers)).status_code == 200
            assert (await client.get("/office/api/session")).status_code == 401
        await engine.dispose()
    asyncio.run(scenario())


def test_admin_can_revoke_a_grant_after_its_source_is_retired():
    from smart_reporting.management.data_sources.secrets import CredentialVault
    from smart_reporting.office.api import COOKIE, csrf_token

    async def scenario():
        engine = create_async_engine("sqlite+aiosqlite://")
        try:
            office = OfficeRepository(engine)
            await office.create_schema()
            admin = Identity("db", "1", "10")
            member = Identity("db", "1", "20")
            await office.bootstrap(admin, "Admin")
            await office.provision(admin, member.user, "Member")
            space = (await office.create_space(admin, "Team", admin.user))["id"]
            await office.set_member(admin, space, member.user, "viewer")
            await office.grant_source(admin, space, "retired", ["db.orders"])
            app = FastAPI()
            app.include_router(create_office_router(
                office, public_origin="http://test", cookie_secure=False,
                source_vault=CredentialVault("test:" + CredentialVault.generate_key()),
            ))
            path = f"/office/api/admin/workspaces/{space}/data-sources/retired"
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                token = await office.create_session(member)
                client.cookies.set(COOKIE, token)
                response = await client.put(path, json={"tables": []},
                    headers={"Origin": "http://test", "X-CSRF-Token": csrf_token(token)})
                assert response.status_code == 403
                token = await office.create_session(admin)
                client.cookies.set(COOKIE, token)
                assert (await client.get(path)).json() == {"tables": ["db.orders"]}
                response = await client.put(path, json={"tables": []},
                    headers={"Origin": "http://test", "X-CSRF-Token": csrf_token(token)})
                assert response.status_code == 200, response.text
                assert (await client.get(path)).json() == {"tables": []}
                assert (await client.get(f"/office/api/workspaces/{space}/data-sources")).json() == {"items": []}
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def test_knowledge_answer_exports_structured_word_and_rechecks_access():
    from io import BytesIO

    from docx import Document
    from smart_reporting.office.api import COOKIE, csrf_token

    class Documents:
        async def import_file(self, actor, space, folder, name, content, request_id):
            assert name == "收入分析.docx"
            document = Document(BytesIO(content))
            assert document.paragraphs[0].style.name == "Heading 1"
            assert document.paragraphs[1].runs[0].bold
            assert document.tables[0].cell(1, 1).text == "42"
            return {"fileId": "word"}

    async def scenario():
        engine = create_async_engine("sqlite+aiosqlite://")
        try:
            office = OfficeRepository(engine)
            await office.create_schema()
            actor = Identity("db", "1", "10")
            await office.bootstrap(actor, "Admin")
            space = (await office.spaces(actor))[0]["id"]
            file = await office.register_file(actor, space, None, "Source.docx", "docx", "source", 1,
                                              {"database": "db", "companyId": "1"})
            await office.favorite(actor, file["id"], True)
            source = {"fileId": file["id"], "revision": 1}
            turn = await office.save_knowledge_turn(
                actor, space, "收入分析", "# 摘要\n\n- **收入**\n\n| 项目 | 值 |\n| --- | --- |\n| 收入 | 42 |",
                [source], [source], conversation="testing",
            )
            token = await office.create_session(actor)
            app = FastAPI()
            app.include_router(create_office_router(office, public_origin="http://test", documents=Documents()))
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test",
                                         cookies={COOKIE: token}) as client:
                headers = {"origin": "http://test", "x-csrf-token": csrf_token(token)}
                path = f"/office/api/workspaces/{space}/knowledge/{turn['id']}/docx"
                assert (await client.post(path, headers=headers)).status_code == 404
                assert (await client.post(path, params={"conversation": "testing"}, headers=headers)).status_code == 201
                await office.favorite(actor, file["id"], False)
                assert (await client.post(path, params={"conversation": "testing"}, headers=headers)).status_code == 404
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def test_knowledge_disconnect_cancels_inflight_model_request():
    from smart_reporting.office.api import COOKIE, csrf_token

    async def scenario():
        engine = create_async_engine("sqlite+aiosqlite://")
        try:
            office = OfficeRepository(engine)
            await office.create_schema()
            actor = Identity("db", "1", "10")
            await office.bootstrap(actor, "Admin")
            space = (await office.spaces(actor))[0]["id"]
            token = await office.create_session(actor)
            started, cancelled = asyncio.Event(), asyncio.Event()

            class Knowledge:
                async def ask(self, *args, **kwargs):
                    started.set()
                    try:
                        await asyncio.Future()
                    finally:
                        cancelled.set()

            app = FastAPI()
            app.include_router(create_office_router(office, public_origin="http://test", knowledge=Knowledge()))
            path = f"/office/api/workspaces/{space}/knowledge"
            scope = {"type": "http", "method": "POST", "path": path, "query_string": b"",
                     "headers": [(b"content-type", b"application/json"), (b"origin", b"http://test"),
                                 (b"cookie", f"{COOKIE}={token}".encode()),
                                 (b"x-csrf-token", csrf_token(token).encode())]}
            first = True
            messages = []

            async def receive():
                nonlocal first
                if first:
                    first = False
                    return {"type": "http.request", "body": b'{"question":"Question"}'}
                await started.wait()
                return {"type": "http.disconnect"}

            async def send(message):
                messages.append(message)

            await asyncio.wait_for(app(scope, receive, send), 5)
            assert cancelled.is_set()
            assert messages[0]["status"] == 499
            assert await office.knowledge_history(actor, space) == []
        finally:
            await engine.dispose()

    asyncio.run(scenario())

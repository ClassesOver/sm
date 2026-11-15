import asyncio

import httpx
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import create_async_engine

from smart_reporting.office.api import create_office_router, csrf_token
from smart_reporting.office.repository import Identity, OfficeRepository


def test_personal_settings_are_isolated_and_only_admin_can_manage_global_settings():
    async def scenario():
        engine = create_async_engine("sqlite+aiosqlite://")
        office = OfficeRepository(engine)
        await office.create_schema()
        admin = Identity("db", "1", "10")
        await office.bootstrap(admin, "Admin")
        await office.provision(admin, "20", "Alice")
        await office.provision(admin, "30", "Bob")
        app = FastAPI()
        app.include_router(
            create_office_router(office, public_origin="http://test", cookie_secure=False)
        )
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://test"
        ) as c:
            assert (await c.get("/office/api/settings")).status_code == 401
            raw = await office.create_session(Identity("db", "1", "20"))
            c.cookies.set("genoffice_session", raw)
            headers = {"origin": "http://test", "x-csrf-token": csrf_token(raw)}
            before = await c.get("/office/api/settings")
            assert before.status_code == 200
            item = before.json()["skills"][0]["id"]
            body = {"theme": "dark", "disabledSkills": [item], "expectedVersion": 0}
            assert (await c.put("/office/api/settings", json=body)).status_code == 403
            result = await c.put("/office/api/settings", headers=headers, json=body)
            assert result.status_code == 200 and result.json()["version"] == 1
            assert (
                await c.put("/office/api/settings", headers=headers, json=body)
            ).status_code == 409
            assert (await c.get("/office/api/admin/settings")).status_code == 403
            assert (
                await c.put(
                    "/office/api/admin/settings",
                    headers=headers,
                    json={"modelId": "custom", "expectedVersion": 0},
                )
            ).status_code == 403
            assert (
                await c.put("/office/api/settings", headers=headers, json={**body, "user": "30"})
            ).status_code == 422
            c.cookies.set(
                "genoffice_session", await office.create_session(Identity("db", "1", "30"))
            )
            assert (await c.get("/office/api/settings")).json()["theme"] == "system"
            token = await office.create_session(admin)
            c.cookies.set("genoffice_session", token)
            global_settings = {
                "modelId": "custom",
                "imageModel": "image-custom",
                "searchEnabled": False,
                "integrationsEnabled": False,
                "expectedVersion": 0,
            }
            saved = await c.put(
                "/office/api/admin/settings",
                headers={"origin": "http://test", "x-csrf-token": csrf_token(token)},
                json=global_settings,
            )
            assert saved.status_code == 200 and saved.json()["modelId"] == "custom"
            assert (await c.get("/office/api/settings")).json()["theme"] == "system"
            c.cookies.set("genoffice_session", raw)
            assert (await c.get("/office/api/settings")).json()["theme"] == "dark"
            await office.logout(raw)
            assert (await c.get("/office/api/settings")).status_code == 401
        await engine.dispose()

    asyncio.run(scenario())


def test_personal_skill_snapshot_and_model_default_are_not_shared_between_users(monkeypatch):
    async def scenario():
        from types import SimpleNamespace

        from smart_reporting.office.settings import OfficeSettings, skill_catalog

        engine = create_async_engine("sqlite+aiosqlite://")
        office = OfficeRepository(engine)
        await office.create_schema()
        admin = Identity("db", "1", "10")
        await office.bootstrap(admin, "Admin")
        await office.provision(admin, "20", "Alice")
        actor = Identity("db", "1", "20")
        service = OfficeSettings(office)
        assert await service.skills(actor) is None
        ids = [item["id"] for item in skill_catalog()]
        await service.save(actor, {"theme": "system", "disabledSkills": ids[1:]}, 0)
        running = await service.skills(actor)
        assert running.get_skill_names() == [ids[0]]
        assert "unavailable" in running._get_skill_script(ids[0], "anything.py", execute=True)
        await service.save(actor, {"theme": "dark", "disabledSkills": ids}, 1)
        assert await service.skills(actor) is None
        assert running.get_skill_names() == [ids[0]]
        assert await service.skills(admin) is None
        from agno.agent import Agent
        from smart_reporting.office import settings as settings_module

        async def context():
            return service, actor

        monkeypatch.setattr(settings_module, "native_settings", context)
        agent = Agent()
        await settings_module.configure_office_agent(agent)
        assert agent.skills is None  # upstream's complete catalog cannot override user opt-out
        assert "GenOffice native host" in agent.additional_context
        original = SimpleNamespace(id="default")
        await service.save(
            admin,
            {
                "modelId": "company-model",
                "imageModel": "",
                "searchEnabled": True,
                "integrationsEnabled": True,
            },
            0,
            global_settings=True,
        )
        assert (await service.model(actor, original)).id == "company-model"
        assert original.id == "default"
        other = Identity("db", "2", "10")
        await office.bootstrap(other, "Other")
        assert (await service.model(other, original)).id == "default"
        await engine.dispose()

    asyncio.run(scenario())


def test_admin_page_has_its_own_permission_checked_route(tmp_path):
    async def scenario():
        from smart_reporting.office_entry import create_office_entry_router

        engine = create_async_engine("sqlite+aiosqlite://")
        office = OfficeRepository(engine)
        await office.create_schema()
        admin = Identity("db", "1", "10")
        await office.bootstrap(admin, "Admin")
        await office.provision(admin, "20", "Alice")
        (tmp_path / "office-admin.html").write_text("admin-console")
        app = FastAPI()
        app.include_router(create_office_entry_router(office=office, static_dir=tmp_path))
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://test"
        ) as c:
            assert (await c.get("/office/admin")).status_code == 401
            c.cookies.set(
                "genoffice_session", await office.create_session(Identity("db", "1", "20"))
            )
            assert (await c.get("/office/admin")).status_code == 403
            c.cookies.set("genoffice_session", await office.create_session(admin))
            response = await c.get("/office/admin")
            assert response.status_code == 200 and response.text == "admin-console"
            assert response.headers["cache-control"] == "no-store"
        await engine.dispose()

    asyncio.run(scenario())

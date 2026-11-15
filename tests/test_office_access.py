import asyncio

import pytest
from sqlalchemy.ext.asyncio import create_async_engine

from smart_reporting.office.repository import OfficeRepository, OfficeError, Identity


def test_office_membership_sessions_and_team_permissions():
    async def scenario():
        engine = create_async_engine("sqlite+aiosqlite://")
        office = OfficeRepository(engine)
        await office.create_schema()
        admin = Identity("db", "1", "10")
        alice = Identity("db", "1", "20")
        bob = Identity("db", "1", "30")
        foreign = Identity("db", "2", "20")
        await office.bootstrap(admin, "Admin")
        await office.provision(admin, alice.user, "Alice")
        await office.provision(admin, bob.user, "Bob")
        token = await office.create_session(alice)
        assert (await office.authenticate(token)).user == alice.user
        personal = await office.spaces(alice)
        assert len(personal) == 1
        with pytest.raises(OfficeError):
            await office.space_access(admin, personal[0]["id"])
        team = await office.create_space(admin, "Project", alice.user)
        await office.set_member(alice, team["id"], bob.user, "viewer")
        assert (await office.space_access(bob, team["id"]))["role"] == "viewer"
        with pytest.raises(OfficeError):
            await office.space_access(bob, team["id"], write=True)
        with pytest.raises(OfficeError):
            await office.space_access(foreign, team["id"])
        with pytest.raises(OfficeError):
            await office.set_member(alice, team["id"], alice.user, None)
        await office.set_member(alice, team["id"], bob.user, "owner")
        await office.set_member(alice, team["id"], alice.user, None)
        with pytest.raises(OfficeError):
            await office.space_access(alice, team["id"])
        await office.update_user(admin, alice.user, enabled=False)
        with pytest.raises(OfficeError) as expired:
            await office.authenticate(token)
        assert expired.value.status == 401
        assert expired.value.code == "office_session_invalid"
        with pytest.raises(OfficeError):
            await office.update_user(admin, admin.user, role="user")
        await engine.dispose()
    asyncio.run(scenario())


def test_source_grants_require_membership_and_company_scope():
    async def scenario():
        engine = create_async_engine("sqlite+aiosqlite://")
        office = OfficeRepository(engine)
        await office.create_schema()
        admin = Identity("db", "1", "10")
        user = Identity("db", "1", "20")
        await office.bootstrap(admin, "Admin")
        await office.provision(admin, user.user, "User")
        space = await office.create_space(admin, "Team", user.user)
        await office.grant_source(admin, space["id"], "sales", ["orders"])
        assert await office.source_tables(user, space["id"], "sales") == ["orders"]
        await office.grant_source(admin, space["id"], "sales", [])
        with pytest.raises(OfficeError):
            await office.source_tables(user, space["id"], "sales")
        await engine.dispose()
    asyncio.run(scenario())


def test_library_persistence_and_folder_cycle():
    async def scenario():
        engine = create_async_engine("sqlite+aiosqlite://")
        office = OfficeRepository(engine)
        await office.create_schema()
        actor = Identity("db", "1", "10")
        await office.bootstrap(actor, "Admin")
        space = (await office.spaces(actor))[0]["id"]
        parent = await office.create_folder(actor, space, None, "Parent")
        child = await office.create_folder(actor, space, parent["id"], "Child")
        with pytest.raises(OfficeError):
            await office.update_folder(actor, space, parent["id"], parent=child["id"])
        entry = await office.register_file(actor, space, child["id"], "test.docx",
            "docx", "native-1", 1, {"threadId": "thread", "userId": "10",
                                    "database": "db", "companyId": "1"})
        await office.favorite(actor, entry["id"], True)
        library = await OfficeRepository(engine).library(actor, space)
        assert library["files"][0]["starred"] is True
        with pytest.raises(OfficeError):
            await office.update_file(actor, entry["id"], expected_version=99, name="renamed")
        await office.update_file(actor, entry["id"], expected_version=1, name="renamed.docx")
        assert (await office.library(actor, space))["files"][0]["name"] == "renamed.docx"
        await engine.dispose()
    asyncio.run(scenario())

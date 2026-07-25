from dataclasses import replace

import httpx
import pytest
from fastapi import FastAPI

from agentos_dev.application import ApplicationContext, create_agentos_app
from agentos_dev.settings import AgentSettings
from agentos_dev.skills import public_skill_metadata


class FakeAssistant:
    id = "test-assistant"
    name = "测试助手"


class FakeSkills:
    def __init__(self, name):
        self.name = name

    def get_all_skills(self):
        return [type("FakeSkill", (), {"name": self.name, "description": ""})()]


class FakeWorkspace:
    def __init__(self, name):
        self.name = name

    def list_files(self, _thread_id, _path):
        return [{"name": self.name}]


@pytest.fixture
def anyio_backend():
    return "asyncio"


def test_application_factory_keeps_instances_isolated(monkeypatch):
    created = []

    class FakeAgentOS:
        def __init__(self, **values):
            self.values = values
            created.append(self)

        def get_app(self):
            return self.values["base_app"]

    monkeypatch.setattr("agentos_dev.application.AgentOS", FakeAgentOS)
    monkeypatch.setattr("agentos_dev.application.AGUI", lambda **value: ("agui", value))
    settings = AgentSettings.from_environment({}, load_env_file=False)
    first_base = FastAPI()
    second_base = FastAPI()
    first_context = ApplicationContext(
        settings,
        object(),
        FakeSkills("first"),
        FakeAssistant(),
        FakeAssistant(),
        FakeAssistant(),
        FakeAssistant(),
        coding_agent=FakeAssistant(),
    )
    second_context = ApplicationContext(
        settings,
        object(),
        FakeSkills("second"),
        FakeAssistant(),
        FakeAssistant(),
        FakeAssistant(),
        FakeAssistant(),
    )

    first_os, first_app = create_agentos_app(first_context, first_base)
    second_os, second_app = create_agentos_app(second_context, second_base)

    assert first_os is not second_os
    assert first_app is first_base
    assert second_app is second_base
    assert created[0].values["on_route_conflict"] == "preserve_base_app"
    assert created[0].values["cors_allowed_origins"] == list(settings.cors_allowed_origins)
    assert created[0].values["db"] is None
    assert created[0].values["agents"] == [
        first_context.assistant,
        first_context.odoo_command_assistant,
        first_context.report_agent,
    ]
    assert first_context.coding_agent not in created[0].values["agents"]
    assert created[0].values["teams"] == [first_context.assistant_team]
    assert created[0].values["interfaces"] == [("agui", {"team": first_context.assistant_team})]


def test_application_passes_trace_database_to_agentos(monkeypatch):
    captured = {}

    class FakeAgentOS:
        def __init__(self, **values):
            captured.update(values)

        def get_app(self):
            return captured["base_app"]

    database = type("Database", (), {"async_db": object()})()
    monkeypatch.setattr("agentos_dev.application.AgentOS", FakeAgentOS)
    monkeypatch.setattr("agentos_dev.application.AGUI", lambda **value: value)
    settings = AgentSettings.from_environment({}, load_env_file=False)
    context = ApplicationContext(
        settings,
        object(),
        FakeSkills("test"),
        FakeAssistant(),
        FakeAssistant(),
        FakeAssistant(),
        FakeAssistant(),
        database=database,
    )

    create_agentos_app(context, FastAPI())

    assert captured["db"] is database.async_db


def test_default_application_exposes_explicit_context():
    from agentos_dev import app as app_module

    context = app_module.base_app.state.agentos_context
    assert context.settings is app_module.settings
    assert context.workspace_service is app_module.workspace_service
    assert context.skills is app_module.agent_skills
    assert context.assistant is app_module.assistant
    assert context.odoo_command_assistant is app_module.odoo_command_assistant
    assert context.report_agent is app_module.report_agent
    assert context.assistant_team is app_module.assistant_team
    assert app_module.agent_os.db is app_module.agent_database.async_db


@pytest.mark.anyio
async def test_base_application_routes_use_their_own_context():
    from agentos_dev import app as app_module

    settings = AgentSettings.from_environment({}, load_env_file=False)
    first_context = ApplicationContext(
        settings=replace(settings, workspace_hmac_secret="first-secret"),
        workspace_service=FakeWorkspace("first-file"),
        skills=FakeSkills("first"),
        assistant=FakeAssistant(),
        odoo_command_assistant=FakeAssistant(),
        report_agent=FakeAssistant(),
        assistant_team=FakeAssistant(),
    )
    second_context = ApplicationContext(
        settings=replace(settings, workspace_hmac_secret="second-secret"),
        workspace_service=FakeWorkspace("second-file"),
        skills=FakeSkills("second"),
        assistant=FakeAssistant(),
        odoo_command_assistant=FakeAssistant(),
        report_agent=FakeAssistant(),
        assistant_team=FakeAssistant(),
    )
    first_app = app_module.create_base_app(first_context)
    second_app = app_module.create_base_app(second_context)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=first_app), base_url="http://test"
    ) as first_client:
        first_config = await first_client.get("/config")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=second_app), base_url="http://test"
    ) as second_client:
        second_config = await second_client.get("/config")

    assert first_config.json()["skills"] == public_skill_metadata(first_context.skills)
    assert second_config.json()["skills"] == public_skill_metadata(second_context.skills)
    assert first_app.state.agentos_context is first_context
    assert second_app.state.agentos_context is second_context
    assert first_app.state.agentos_context.workspace_service.name == "first-file"
    assert second_app.state.agentos_context.workspace_service.name == "second-file"

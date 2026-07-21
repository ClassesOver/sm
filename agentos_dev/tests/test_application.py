from dataclasses import replace

import httpx
import pytest
from fastapi import FastAPI

from agentos_dev.application import ApplicationContext, create_agentos_app
from agentos_dev.settings import AgentSettings


class FakeAssistant:
    id = "test-assistant"
    name = "测试助手"


class FakeSkills:
    def __init__(self, name):
        self.name = name

    def public_metadata(self):
        return [{"name": self.name}]


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
    monkeypatch.setattr("agentos_dev.application.AGUI", lambda agent: ("agui", agent))
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
    )
    second_context = ApplicationContext(
        settings,
        object(),
        FakeSkills("second"),
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


def test_default_application_exposes_explicit_context():
    from agentos_dev import app as app_module

    context = app_module.base_app.state.agentos_context
    assert context.settings is app_module.settings
    assert context.workspace_service is app_module.workspace_service
    assert context.skills is app_module.agent_skills
    assert context.assistant is app_module.assistant
    assert context.edit_mode_assistant is app_module.edit_mode_assistant
    assert context.menu_navigation_assistant is app_module.menu_navigation_assistant


@pytest.mark.anyio
async def test_base_application_routes_use_their_own_context():
    from agentos_dev import app as app_module

    settings = AgentSettings.from_environment({}, load_env_file=False)
    first_context = ApplicationContext(
        settings=replace(settings, workspace_hmac_secret="first-secret"),
        workspace_service=FakeWorkspace("first-file"),
        skills=FakeSkills("first"),
        assistant=FakeAssistant(),
        edit_mode_assistant=FakeAssistant(),
        menu_navigation_assistant=FakeAssistant(),
    )
    second_context = ApplicationContext(
        settings=replace(settings, workspace_hmac_secret="second-secret"),
        workspace_service=FakeWorkspace("second-file"),
        skills=FakeSkills("second"),
        assistant=FakeAssistant(),
        edit_mode_assistant=FakeAssistant(),
        menu_navigation_assistant=FakeAssistant(),
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

    assert first_config.json()["skills"] == [{"name": "first"}]
    assert second_config.json()["skills"] == [{"name": "second"}]
    assert first_app.state.agentos_context is first_context
    assert second_app.state.agentos_context is second_context
    assert first_app.state.agentos_context.workspace_service.name == "first-file"
    assert second_app.state.agentos_context.workspace_service.name == "second-file"

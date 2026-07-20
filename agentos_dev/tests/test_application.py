from fastapi import FastAPI

from agentos_dev.application import create_agentos_app
from agentos_dev.settings import AgentSettings


class FakeAssistant:
    id = "test-assistant"
    name = "测试助手"


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

    first_os, first_app = create_agentos_app(settings, first_base, FakeAssistant())
    second_os, second_app = create_agentos_app(settings, second_base, FakeAssistant())

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

import pytest
from fastapi import FastAPI

from smart_reporting.application import ApplicationContext, create_agentos_app
from smart_reporting.settings import AgentSettings


class FakeAssistant:
    id = "smart-reporting"
    name = "测试助手"

    def deep_copy(self, *, update=None):
        copied = FakeAssistant()
        for key, value in (update or {}).items():
            setattr(copied, key, value)
        return copied


class FakeWorkflow:
    id = "test-workflow"
    name = "测试工作流"


class FakeWorkspace:
    def __init__(self, name):
        self.name = name
        self.close_calls = 0

    def list_files(self, _thread_id, _path):
        return [{"name": self.name}]

    async def aclose(self):
        self.close_calls += 1


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

    monkeypatch.setattr("smart_reporting.application.AgentOS", FakeAgentOS)
    settings = AgentSettings.from_environment({}, load_env_file=False)
    first_base = FastAPI()
    second_base = FastAPI()
    first_context = ApplicationContext(
        settings,
        object(),
        FakeAssistant(),
        report_workflow=FakeWorkflow(),
    )
    second_context = ApplicationContext(
        settings,
        object(),
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
    assert [agent.id for agent in created[0].values["agents"]] == [
        "smart-reporting",
        "report-agent",
    ]
    assert created[0].values["agents"][0] is first_context.report_agent
    assert created[0].values["agents"][1] is not first_context.report_agent
    assert created[0].values["teams"] == []
    assert created[0].values["workflows"] == [first_context.report_workflow]
    assert created[0].values["interfaces"] == []
    assert created[0].values["telemetry"] is False


def test_application_passes_trace_database_to_agentos(monkeypatch):
    captured = {}

    class FakeAgentOS:
        def __init__(self, **values):
            captured.update(values)

        def get_app(self):
            return captured["base_app"]

    database = type("Database", (), {"async_db": object()})()
    monkeypatch.setattr("smart_reporting.application.AgentOS", FakeAgentOS)
    settings = AgentSettings.from_environment({}, load_env_file=False)
    context = ApplicationContext(
        settings,
        object(),
        FakeAssistant(),
        database=database,
    )

    create_agentos_app(context, FastAPI())

    assert captured["db"] is database.async_db


@pytest.mark.anyio
async def test_application_lifespan_closes_workspace_service(monkeypatch):
    captured = {}

    class FakeAgentOS:
        def __init__(self, **values):
            captured.update(values)

        def get_app(self):
            return captured["base_app"]

    monkeypatch.setattr("smart_reporting.application.AgentOS", FakeAgentOS)
    settings = AgentSettings.from_environment({}, load_env_file=False)
    workspace = FakeWorkspace("lifespan")
    context = ApplicationContext(
        settings,
        workspace,
        FakeAssistant(),
    )

    create_agentos_app(context, FastAPI())
    async with captured["lifespan"](FastAPI()):
        assert workspace.close_calls == 0
    assert workspace.close_calls == 1


def test_default_application_exposes_explicit_context():
    from smart_reporting import app as app_module

    context = app_module.base_app.state.agentos_context
    assert context.settings is app_module.settings
    assert context.workspace_service is app_module.workspace_service
    assert context.report_agent is app_module.report_agent
    assert context.report_workflow is app_module.report_workflow
    assert app_module.agent_os.db is app_module.agent_database.async_db
    assert [agent.id for agent in app_module.agent_os.agents or []] == [
        "smart-reporting",
        "report-agent",
    ]

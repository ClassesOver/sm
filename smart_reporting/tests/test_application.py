import asyncio
import json
from io import BytesIO
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, UploadFile
from loguru import logger as loguru_logger
from starlette.requests import Request

from smart_reporting.runtime.application import ApplicationContext, create_agentos_app
from smart_reporting.runtime.settings import AgentSettings


class FakeAgent:
    id = "smart-reporting"


class FakeWorkflow:
    id = "enterprise-reporting-workflow-v1"


class FakeWorkspace:
    def __init__(self, name):
        self.name = name
        self.close_calls = 0
        self.cleanup_started = asyncio.Event()
        self.cleanup_stopped = asyncio.Event()

    def list_files(self, _thread_id, _path):
        return [{"name": self.name}]

    async def aclose(self):
        self.close_calls += 1

    async def run_quarantine_cleanup_loop(self):
        self.cleanup_started.set()
        try:
            await asyncio.Future()
        finally:
            self.cleanup_stopped.set()


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

    monkeypatch.setattr("smart_reporting.runtime.application.AgentOS", FakeAgentOS)
    settings = AgentSettings.from_environment({}, load_env_file=False)
    first_base = FastAPI()
    second_base = FastAPI()
    first_context = ApplicationContext(
        settings,
        object(),
        FakeAgent(),
        FakeWorkflow(),
    )
    second_context = ApplicationContext(
        settings,
        object(),
        FakeAgent(),
        FakeWorkflow(),
    )

    first_os, first_app = create_agentos_app(first_context, first_base)
    second_os, second_app = create_agentos_app(second_context, second_base)

    assert first_os is not second_os
    assert first_app is first_base
    assert second_app is second_base
    assert created[0].values["on_route_conflict"] == "preserve_base_app"
    assert created[0].values["cors_allowed_origins"] == list(settings.cors_allowed_origins)
    assert created[0].values["db"] is None
    assert created[0].values["agents"] == [first_context.report_agent]
    assert created[0].values["teams"] == []
    assert created[0].values["workflows"] == [first_context.report_workflow]
    assert created[0].values["interfaces"] == []
    assert created[0].values["telemetry"] is False
    assert created[0].values["mcp_server"] is False
    assert created[0].values["mcp_auth"] is None


def test_application_passes_trace_database_to_agentos(monkeypatch):
    captured = {}

    class FakeAgentOS:
        def __init__(self, **values):
            captured.update(values)

        def get_app(self):
            return captured["base_app"]

    database = type("Database", (), {"async_db": object()})()
    monkeypatch.setattr("smart_reporting.runtime.application.AgentOS", FakeAgentOS)
    settings = AgentSettings.from_environment({}, load_env_file=False)
    context = ApplicationContext(
        settings,
        object(),
        FakeAgent(),
        FakeWorkflow(),
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

    monkeypatch.setattr("smart_reporting.runtime.application.AgentOS", FakeAgentOS)
    settings = AgentSettings.from_environment({}, load_env_file=False)
    workspace = FakeWorkspace("lifespan")
    context = ApplicationContext(
        settings,
        workspace,
        FakeAgent(),
        FakeWorkflow(),
    )

    create_agentos_app(context, FastAPI())
    async with captured["lifespan"](FastAPI()):
        await asyncio.wait_for(workspace.cleanup_started.wait(), timeout=0.1)
        assert workspace.close_calls == 0
    assert workspace.close_calls == 1
    assert workspace.cleanup_stopped.is_set()


@pytest.mark.anyio
async def test_application_lifespan_stops_optional_sandbox_reconciler(monkeypatch):
    captured = {}

    class FakeAgentOS:
        def __init__(self, **values):
            captured.update(values)

        def get_app(self):
            return captured["base_app"]

    class ReconcilingWorkspace(FakeWorkspace):
        def __init__(self):
            super().__init__("reconcile")
            self.reconcile_started = asyncio.Event()
            self.reconcile_stopped = asyncio.Event()

        async def run_provider_reconcile_loop(self):
            self.reconcile_started.set()
            try:
                await asyncio.Future()
            finally:
                self.reconcile_stopped.set()

    monkeypatch.setattr("smart_reporting.runtime.application.AgentOS", FakeAgentOS)
    workspace = ReconcilingWorkspace()
    context = ApplicationContext(
        AgentSettings.from_environment({}, load_env_file=False),
        workspace,
        FakeAgent(),
        FakeWorkflow(),
    )

    create_agentos_app(context, FastAPI())
    async with captured["lifespan"](FastAPI()):
        await asyncio.wait_for(workspace.reconcile_started.wait(), timeout=0.1)

    assert workspace.reconcile_stopped.is_set()


@pytest.mark.anyio
async def test_reporting_runtime_identity_log_contains_deployment_boundary(monkeypatch):
    from smart_reporting import app as app_module

    records: list[str] = []
    sink_id = loguru_logger.add(
        lambda message: records.append(str(message).rstrip("\n")),
        format="{message}",
        level="INFO",
    )
    try:
        monkeypatch.setattr(
            app_module,
            "agent_database",
            type("Database", (), {"backend": "postgresql"})(),
        )
        monkeypatch.setattr(app_module, "settings", type("Settings", (), {"workers": 2})())
        monkeypatch.setenv("REPORTING_BUILD_ID", "test-build")

        await app_module._log_reporting_runtime_identity()
    finally:
        loguru_logger.remove(sink_id)

    assert records == [
        "reporting_runtime_started workflow_id=enterprise-reporting-workflow-v1 "
        "build_id=test-build database_backend=postgresql reporting_schema=agentos_reporting workers=2"
    ]


def test_default_application_exposes_explicit_context():
    from smart_reporting import app as app_module

    context = app_module.base_app.state.agentos_context
    assert context.settings is app_module.settings
    assert context.workspace_service is app_module.workspace_service
    assert context.report_agent is app_module.report_agent
    assert context.report_workflow is app_module.report_workflow
    assert app_module.agent_os.db is app_module.agent_database.async_db
    assert app_module.reporting_agent_template.id == "smart-reporting"
    assert [agent.id for agent in app_module.agent_os.agents or []] == ["smart-reporting"]
    assert [workflow.id for workflow in app_module.agent_os.workflows or []] == [
        "enterprise-reporting-workflow-v1"
    ]
    assert str(app_module.base_app.url_path_for("reporting_dependency_diagnostics")) == (
        "/diagnostics/reporting-dependencies"
    )


@pytest.mark.anyio
async def test_legacy_workspace_upload_returns_413_before_workspace_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from smart_reporting import app as app_module

    class Workspace:
        def upload(self, *_args, **_kwargs):
            raise AssertionError("超限文件不应进入 Workspace")

    application = SimpleNamespace(
        state=SimpleNamespace(agentos_context=SimpleNamespace(workspace_service=Workspace()))
    )
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/workspace/upload",
            "headers": [(b"x-workspace-thread", b"thread-1")],
            "app": application,
        }
    )
    request.state.capability = SimpleNamespace(thread="thread-1")
    monkeypatch.setattr(app_module, "WORKSPACE_FILE_BYTES", 4)

    response = await app_module.workspace_upload(
        request,
        threadId="thread-1",
        path="oversized.bin",
        file=UploadFile(file=BytesIO(b"12345"), filename="oversized.bin"),
    )

    assert response.status_code == 413
    assert json.loads(response.body) == {"error": "export_file_too_large"}

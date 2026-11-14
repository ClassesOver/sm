import os
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI
from loguru import logger as loguru_logger

from smart_reporting.runtime.application import ApplicationContext, create_agentos_app
from smart_reporting.runtime.database import SerializedAsyncPostgresDb
from smart_reporting.runtime.settings import AgentSettings


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
    )
    second_context = ApplicationContext(
        settings,
    )

    first_os, first_app = create_agentos_app(first_context, first_base)
    second_os, second_app = create_agentos_app(second_context, second_base)

    assert first_os is not second_os
    assert first_app is first_base
    assert second_app is second_base
    assert created[0].values["on_route_conflict"] == "preserve_base_app"
    assert created[0].values["cors_allowed_origins"] == list(settings.cors_allowed_origins)
    assert created[0].values["db"] is None
    # 报告工作流已退役：AgentOS 只承载数据库与路由，不再登记报告 agent/workflow/MCP 工具。
    assert created[0].values["agents"] == []
    assert created[0].values["teams"] == []
    assert created[0].values["workflows"] == []
    assert created[0].values["interfaces"] == []
    assert created[0].values["telemetry"] is False
    assert "mcp" not in created[0].values


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
        database=database,
    )

    create_agentos_app(context, FastAPI())

    assert captured["db"] is database.async_db


@pytest.mark.anyio
@pytest.mark.parametrize("initialization_fails", [False, True])
async def test_application_initializes_database_before_serving(monkeypatch, initialization_fails):
    captured = {}
    initialized = False

    class FakeDatabase:
        async def _create_all_tables(self):
            nonlocal initialized
            if initialization_fails:
                raise RuntimeError("database initialization failed")
            initialized = True

    class FakeAgentOS:
        def __init__(self, **values):
            captured.update(values)

        def get_app(self):
            return captured["base_app"]

    monkeypatch.setattr("smart_reporting.runtime.application.AgentOS", FakeAgentOS)
    context = ApplicationContext(
        AgentSettings.from_environment({}, load_env_file=False),
        database=SimpleNamespace(async_db=FakeDatabase()),
    )
    create_agentos_app(context, FastAPI())

    if initialization_fails:
        with pytest.raises(RuntimeError, match="database initialization failed"):
            async with captured["lifespan"](FastAPI()):
                pass
    else:
        async with captured["lifespan"](FastAPI()):
            assert initialized


@pytest.mark.integration
@pytest.mark.anyio
async def test_application_new_database_persists_sessions_and_runs(monkeypatch):
    from agno.db.base import SessionType
    from agno.run.agent import RunOutput
    from agno.session import AgentSession
    from sqlalchemy import text

    url = os.getenv("REPORTING_TEST_DB_URL", "").strip()
    if not url:
        pytest.skip("未设置 REPORTING_TEST_DB_URL，跳过 PostgreSQL 启动集成测试。")
    schema = f"test_agno_startup_{uuid4().hex}"
    database = SerializedAsyncPostgresDb(db_url=url, db_schema=schema)
    captured = {}

    class FakeAgentOS:
        def __init__(self, **values):
            captured.update(values)

        def get_app(self):
            return captured["base_app"]

    monkeypatch.setattr("smart_reporting.runtime.application.AgentOS", FakeAgentOS)
    context = ApplicationContext(
        AgentSettings.from_environment({}, load_env_file=False),
        database=SimpleNamespace(async_db=database),
    )
    create_agentos_app(context, FastAPI())
    try:
        async with captured["lifespan"](FastAPI()):
            assert await database.table_exists(database.session_table_name)
            assert await database.table_exists(database.runs_table_name)
            session = AgentSession(
                session_id="startup-session",
                agent_id="startup-agent",
                created_at=1,
                updated_at=1,
            )
            assert await database.upsert_session(session) is not None
            await database.upsert_run(
                RunOutput(
                    run_id="startup-run",
                    agent_id=session.agent_id,
                    session_id=session.session_id,
                    content="新库持久化验证",
                ),
                session_id=session.session_id,
                run_index=0,
            )
            stored = await database.get_session(session.session_id, SessionType.AGENT)
            assert stored is not None
            assert stored.runs[0].content == "新库持久化验证"
    finally:
        async with database.db_engine.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await database.close()


@pytest.mark.anyio
async def test_runtime_identity_log_contains_deployment_boundary(monkeypatch):
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

        await app_module._log_runtime_identity()
    finally:
        loguru_logger.remove(sink_id)

    assert records == [
        "office_runtime_started build_id=test-build database_backend=postgresql workers=2"
    ]


def test_default_application_exposes_explicit_context_and_retires_report_editors():
    from fastapi.testclient import TestClient

    from smart_reporting import app as app_module

    context = app_module.base_app.state.agentos_context
    assert context.settings is app_module.settings
    assert app_module.agent_os.db is app_module.agent_database.async_db
    assert list(app_module.agent_os.agents or []) == []
    assert list(app_module.agent_os.workflows or []) == []
    client = TestClient(app_module.base_app)
    for path in (
        "/reports/v1/editor/open/grant",
        "/reports/v1/editor/report/1/api/native/open",
        "/reports/v1/slides/report/1",
        "/reports/v1/workbooks/report/1/api/file",
    ):
        response = client.get(path)
        assert response.status_code == 410
        assert response.json()["error"] == "report_editor_retired"

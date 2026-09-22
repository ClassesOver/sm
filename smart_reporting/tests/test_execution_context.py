from types import SimpleNamespace

import pytest

from smart_reporting.runtime.execution import (
    ExecutionContext,
    close_execution_resources,
    configure_execution_tracing,
    create_execution_context,
)
from smart_reporting.runtime.settings import AgentSettings


class _Client:
    def __init__(self):
        self.closed = 0

    async def aclose(self):
        self.closed += 1


def test_create_execution_context_uses_reporting_code_mode_factory_configuration(
    tmp_path, monkeypatch
):
    settings = AgentSettings.from_environment(
        {
            "REPORTING_HOST_WORKSPACE_ROOT": str(tmp_path),
            "AGENT_REPORT_ANALYSIS_CONCURRENCY": "2",
            "AGENT_REPORT_SECTION_CONCURRENCY": "3",
        },
        load_env_file=False,
    )
    database = SimpleNamespace(async_db=object(), sync_db=object())
    runtime = object()
    calls = []
    monkeypatch.setattr(
        "smart_reporting.runtime.execution.AsyncSandboxRegistry",
        lambda _database: object(),
    )
    monkeypatch.setattr(
        "smart_reporting.runtime.execution.create_sandbox_provider",
        lambda *_args, **_kwargs: object(),
    )
    monkeypatch.setattr(
        "smart_reporting.runtime.execution.create_reporting_code_mode_runtime",
        lambda root, **values: calls.append((root, values)) or runtime,
        raising=False,
    )

    context = create_execution_context(
        settings,
        database_factory=lambda _url: database,
        tracing_configurer=lambda *_args, **_kwargs: None,
        workspace_factory=lambda **_kwargs: object(),
    )

    assert context.reporting_code_mode_runtime is runtime
    assert calls == [
        (
            tmp_path,
            {
                "analysis_concurrency": 2,
                "section_concurrency": 3,
                "timeout": 900,
            },
        )
    ]


def test_configure_execution_tracing使用同步数据库和批处理():
    settings = AgentSettings.from_environment(
        {"AGENT_TRACING_ENABLED": "true", "REPORTING_HOST_WORKSPACE_ROOT": "/tmp/reporting-test"},
        load_env_file=False,
    )
    sync_db = object()
    database = SimpleNamespace(async_db=object(), sync_db=sync_db)
    calls = []

    configure_execution_tracing(
        database,
        settings,
        tracing_configurer=lambda db, **values: calls.append((db, values)),
    )

    assert calls == [
        (
            sync_db,
            {
                "enabled": True,
                "batch_processing": True,
            },
        )
    ]


@pytest.mark.anyio
async def test_close_execution_resources关闭session_summary_model且按client去重():
    shared = _Client()
    workspace = _Client()
    database = _Client()
    model = SimpleNamespace(async_client=shared)
    agent = SimpleNamespace(
        model=model,
        compression_manager=SimpleNamespace(model=model),
        session_summary_manager=SimpleNamespace(model=model),
    )
    context = ExecutionContext(
        settings=AgentSettings.from_environment(
            {"REPORTING_HOST_WORKSPACE_ROOT": "/tmp/reporting-test"}, load_env_file=False
        ),
        database=database,
        workspace_service=workspace,
    )

    await close_execution_resources(context, agent, tracing_flusher=lambda: True)

    assert shared.closed == 1
    assert workspace.closed == 1
    assert database.closed == 1


@pytest.mark.anyio
async def test_close_execution_resources_closes_reporting_lsp_manager() -> None:
    manager = _Client()
    context = ExecutionContext(
        settings=AgentSettings.from_environment(
            {"REPORTING_HOST_WORKSPACE_ROOT": "/tmp/reporting-test"}, load_env_file=False
        ),
        database=_Client(),
        workspace_service=_Client(),
        reporting_lsp_process_manager=manager,
    )
    await close_execution_resources(context, tracing_flusher=lambda: True)
    assert manager.closed == 1

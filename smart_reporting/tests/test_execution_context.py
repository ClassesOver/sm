from types import SimpleNamespace

import pytest

from smart_reporting.execution_context import ExecutionContext, close_execution_resources
from smart_reporting.settings import AgentSettings


class _Client:
    def __init__(self):
        self.closed = 0

    async def aclose(self):
        self.closed += 1


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
        settings=AgentSettings.from_environment({}, load_env_file=False),
        database=database,
        workspace_service=workspace,
    )

    await close_execution_resources(context, agent, tracing_flusher=lambda: True)

    assert shared.closed == 1
    assert workspace.closed == 1
    assert database.closed == 1

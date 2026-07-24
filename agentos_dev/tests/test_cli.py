import pytest

from agentos_dev.cli import CliContext, create_cli_agent, create_cli_app_agent, run_cli_app
from agentos_dev.cli import app as cli_module
from agentos_dev.cli.app import CLI_ROUTER_MODEL_ID
from agentos_dev.settings import AgentSettings


def test_create_cli_agent_is_independent_coding_agent():
    settings = AgentSettings.from_environment({}, load_env_file=False)
    database = object()
    workspace_service = object()

    agent = create_cli_agent(
        CliContext(
            settings=settings,
            database=database,
            workspace_service=workspace_service,
            coding_repository=object(),  # type: ignore[arg-type]
        )
    )

    assert agent.id == "coding-agent-cli"
    assert agent.db is database
    assert agent.model.id == settings.model_id
    assert agent.model.base_url == settings.openai_base_url
    assert agent.model.extra_body is None
    assert agent.num_history_runs == 5
    assert agent.tools[0].kernel.service is workspace_service

    app_agent = create_cli_app_agent(
        CliContext(
            settings=settings,
            database=database,
            workspace_service=workspace_service,
            coding_repository=object(),  # type: ignore[arg-type]
        ),
        agent,
    )
    assert app_agent.id == "coding-agent-cli-app"
    assert app_agent.model is not agent.model
    assert app_agent.model.id == CLI_ROUTER_MODEL_ID
    assert app_agent.model.extra_body is None
    assert [tool.name for tool in app_agent.tools] == ["run_coding_task"]
    expected_tool_choice = {
        "type": "function",
        "function": {"name": "run_coding_task"},
    }
    assert app_agent.tool_choice == expected_tool_choice
    request_params = app_agent.model.get_request_params(
        tools=[app_agent.tools[0].to_dict()],
        tool_choice=app_agent.tool_choice,
    )
    assert request_params["tool_choice"] == expected_tool_choice
    assert "extra_body" not in request_params


@pytest.mark.anyio
async def test_cli_uses_agno_native_async_app_without_initial_input(monkeypatch):
    calls = []

    class NativeCliAgent:
        async def acli_app(self, **kwargs):
            calls.append(kwargs)

    monkeypatch.setattr(
        cli_module,
        "create_cli_app_agent",
        lambda _context, _agent: NativeCliAgent(),
    )
    context = object()
    agent = object()

    await run_cli_app(context, agent)  # type: ignore[arg-type]

    assert len(calls) == 1
    assert calls[0]["session_id"].startswith("cli-")
    assert calls[0] == {
        "session_id": calls[0]["session_id"],
        "user_id": "cli",
        "stream": True,
        "markdown": True,
    }

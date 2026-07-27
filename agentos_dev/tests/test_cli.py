import asyncio
from inspect import isasyncgenfunction

import pytest

from agentos_dev.cli import CliContext, create_cli_agent, create_cli_app_agent, run_cli_app
from agentos_dev.cli import app as cli_module
from agentos_dev.coding.execution import is_coding_tool_scheduler_hook
from agentos_dev.context_management import ContextBudgetController, ProjectedOpenAIChat
from agentos_dev.settings import AgentSettings
from agentos_dev.skills import SkillValidatorRegistry, skill_script_receipt_hook


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
    assert isinstance(agent.model, ProjectedOpenAIChat)
    assert agent.model.base_url == settings.openai_base_url
    assert agent.model.extra_body is None
    assert agent.model.request_params == {"parallel_tool_calls": True}
    assert agent.num_history_runs == 5
    assert isinstance(agent.compression_manager, ContextBudgetController)
    assert agent.compression_manager.context_token_limit == 96 * 1024
    assert agent.compression_manager.input_token_budget == 64 * 1024
    assert agent.compression_manager.model is agent.model
    assert agent.tools[0].kernel.service is workspace_service
    assert isinstance(agent.tools[0].kernel.validator_registry, SkillValidatorRegistry)
    assert skill_script_receipt_hook in agent.tool_hooks
    assert sum(is_coding_tool_scheduler_hook(hook) for hook in agent.tool_hooks) == 1

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
    assert app_agent.model.id == settings.model_id
    assert app_agent.model.extra_body == {"enable_thinking": False}
    assert app_agent.model.request_params == {"parallel_tool_calls": True}
    assert [tool.name for tool in app_agent.tools] == ["run_coding_task"]
    assert app_agent.tools[0].parameters == {
        "type": "object",
        "properties": {"instruction": {"type": "string", "minLength": 1}},
        "required": ["instruction"],
        "additionalProperties": False,
    }
    assert skill_script_receipt_hook not in (app_agent.tool_hooks or [])
    assert not any(is_coding_tool_scheduler_hook(hook) for hook in app_agent.tool_hooks or [])
    assert isasyncgenfunction(app_agent.tools[0].entrypoint)
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
    assert request_params["extra_body"] == {"enable_thinking": False}
    assert request_params["parallel_tool_calls"] is True


def test_create_cli_context_configures_tracing_before_services(monkeypatch):
    settings = AgentSettings.from_environment(
        {
            "AGENT_TRACING_ENABLED": "true",
            "AGENT_TRACING_PHOENIX_ENDPOINT": "https://phoenix.example",
            "AGENT_TRACING_PHOENIX_API_KEY": "secret",
            "AGENT_TRACING_PHOENIX_PROJECT": "hrp",
        },
        load_env_file=False,
    )
    async_db = object()
    database = type("Database", (), {"async_db": async_db})()
    calls = []

    monkeypatch.setattr(cli_module, "create_agent_database", lambda _url: database)
    monkeypatch.setattr(
        cli_module,
        "configure_tracing",
        lambda db, **values: calls.append((db, values)),
    )
    monkeypatch.setattr(cli_module, "WorkspaceService", lambda **_values: object())
    monkeypatch.setattr(cli_module, "CodingTaskRepository", lambda _db: object())

    context = cli_module.create_cli_context(settings)

    assert calls == [
        (
            async_db,
            {
                "enabled": True,
                "phoenix_endpoint": "https://phoenix.example/v1/traces",
                "phoenix_api_key": "secret",
                "phoenix_project_name": "hrp",
            },
        )
    ]
    assert context.database is async_db


def test_create_cli_agent_loads_configured_skills_directory(monkeypatch):
    settings = AgentSettings.from_environment(
        {"AGENT_SKILLS_DIR": "/opt/agent-skills"}, load_env_file=False
    )
    loaded_paths = []
    original = cli_module.load_builtin_coding_skills

    def load_skills(path):
        loaded_paths.append(path)
        return original()

    monkeypatch.setattr(cli_module, "load_builtin_coding_skills", load_skills)
    create_cli_agent(
        CliContext(
            settings=settings,
            database=object(),
            workspace_service=object(),
            coding_repository=object(),  # type: ignore[arg-type]
        )
    )

    assert loaded_paths == ["/opt/agent-skills"]


def test_cli_agents_inject_registry_built_from_internal_skills(monkeypatch):
    settings = AgentSettings.from_environment({}, load_env_file=False)
    context = CliContext(
        settings=settings,
        database=object(),
        workspace_service=object(),
        coding_repository=object(),  # type: ignore[arg-type]
    )
    registries = [object(), object()]
    observed_skills = []
    supervisor_kwargs = {}

    class RegistryFactory:
        @classmethod
        def from_skills(cls, skills):
            observed_skills.append(skills)
            return registries[len(observed_skills) - 1]

    class Supervisor:
        def __init__(self, *_args, **kwargs):
            supervisor_kwargs.update(kwargs)

    monkeypatch.setattr(cli_module, "SkillValidatorRegistry", RegistryFactory)
    monkeypatch.setattr(cli_module, "CodingTaskSupervisor", Supervisor)

    coding_agent = create_cli_agent(context)
    create_cli_app_agent(context, coding_agent)

    assert coding_agent.tools[0].kernel.validator_registry is registries[0]
    assert supervisor_kwargs["validator_registry"] is registries[1]
    assert observed_skills == [coding_agent.skills, coding_agent.skills]


@pytest.mark.anyio
async def test_cli_uses_agno_native_async_app_without_initial_input(monkeypatch):
    calls = []

    class AsyncClient:
        def __init__(self):
            self.closed = False

        async def close(self):
            self.closed = True

    coding_client = AsyncClient()
    coding_compression_client = AsyncClient()
    app_client = AsyncClient()
    app_compression_client = AsyncClient()
    database = AsyncClient()

    class NativeCliAgent:
        model = type("Model", (), {"async_client": app_client})()
        compression_manager = type(
            "CompressionManager",
            (),
            {"model": type("Model", (), {"async_client": app_compression_client})()},
        )()

        async def acli_app(self, **kwargs):
            calls.append(kwargs)

    coding_agent = type(
        "CodingAgent",
        (),
        {
            "model": type("Model", (), {"async_client": coding_client})(),
            "compression_manager": type(
                "CompressionManager",
                (),
                {"model": type("Model", (), {"async_client": coding_compression_client})()},
            )(),
        },
    )()
    monkeypatch.setattr(
        cli_module,
        "create_cli_app_agent",
        lambda _context, _agent: NativeCliAgent(),
    )
    context = type("Context", (), {"database": database})()

    await run_cli_app(context, coding_agent)  # type: ignore[arg-type]

    assert len(calls) == 1
    assert calls[0]["session_id"].startswith("cli-")
    assert calls[0] == {
        "session_id": calls[0]["session_id"],
        "user_id": "cli",
        "stream": True,
        "markdown": True,
    }
    assert coding_client.closed
    assert coding_compression_client.closed
    assert app_client.closed
    assert app_compression_client.closed
    assert database.closed


@pytest.mark.anyio
async def test_cli_closes_resources_when_native_app_is_cancelled(monkeypatch):
    closed = []

    class AsyncClient:
        def __init__(self, name):
            self.name = name

        async def close(self):
            closed.append(self.name)

    class NativeCliAgent:
        model = type("Model", (), {"async_client": AsyncClient("app-model")})()
        compression_manager = type(
            "CompressionManager",
            (),
            {"model": type("Model", (), {"async_client": AsyncClient("app-compression")})()},
        )()

        async def acli_app(self, **kwargs):
            raise asyncio.CancelledError

    coding_agent = type(
        "CodingAgent",
        (),
        {
            "model": type("Model", (), {"async_client": AsyncClient("coding-model")})(),
            "compression_manager": type(
                "CompressionManager",
                (),
                {"model": type("Model", (), {"async_client": AsyncClient("coding-compression")})()},
            )(),
        },
    )()
    context = type("Context", (), {"database": AsyncClient("database")})()
    monkeypatch.setattr(
        cli_module,
        "create_cli_app_agent",
        lambda _context, _agent: NativeCliAgent(),
    )

    with pytest.raises(asyncio.CancelledError):
        await run_cli_app(context, coding_agent)  # type: ignore[arg-type]

    assert closed == [
        "app-model",
        "app-compression",
        "coding-model",
        "coding-compression",
        "database",
    ]

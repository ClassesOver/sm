import asyncio
from inspect import isasyncgenfunction
from io import StringIO

import pytest
from agno.agent.protocol import AgentProtocol
from agno.run import RunContext
from agno.run.agent import RunContentEvent

from smart_reporting.coding import cli as cli_module
from smart_reporting.coding.cli import (
    CliContext,
    DirectCodingAgent,
    create_cli_agent,
    create_cli_app_agent,
    run_cli,
)
from smart_reporting.context_management import ContextBudgetController, ProjectedOpenAIChat
from smart_reporting.instructions import (
    CODING_DELIVERABLE_VERIFICATION_INSTRUCTION,
    CODING_VALIDATOR_FEEDBACK_INSTRUCTION,
    PURE_CODING_PARALLEL_READ_INSTRUCTIONS,
)
from smart_reporting.settings import AgentSettings
from smart_reporting.skills import SkillValidatorRegistry, is_skill_script_hook
from smart_reporting.task_execution.execution import (
    _create_files_patch,
    is_coding_tool_scheduler_hook,
)
from smart_reporting.task_execution.tools import build_workspace_changes
from smart_reporting.workspace import WorkspaceService


def test_cli_main_reads_complete_stdin_without_rewriting(monkeypatch):
    captured = []
    instruction = "第一行\n第二行\n"

    async def capture_run_cli(*, initial_input=None):
        captured.append(initial_input)

    monkeypatch.setattr(cli_module.sys, "stdin", StringIO(instruction))
    monkeypatch.setattr(cli_module, "run_cli", capture_run_cli)

    cli_module.main(["--stdin"])

    assert captured == [instruction]


def test_cli_main_rejects_empty_stdin(monkeypatch):
    monkeypatch.setattr(cli_module.sys, "stdin", StringIO(" \n"))

    with pytest.raises(SystemExit, match="coding_cli_input_empty"):
        cli_module.main(["--stdin"])


def test_create_cli_agent_is_independent_coding_agent():
    settings = AgentSettings.from_environment(
        {"AGENT_MODEL_TIMEOUT_SECONDS": "123"}, load_env_file=False
    )
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
    assert agent.model.timeout == 123
    assert agent.model.max_retries == 0
    assert agent.model.extra_body == {"enable_thinking": True, "thinking_budget": 16384}
    assert agent.model.temperature == 0.1
    assert agent.model.reasoning_effort == "medium"
    assert agent.model.get_request_params()["temperature"] == 0.1
    assert agent.model.get_request_params()["reasoning_effort"] == "medium"
    assert agent.model.request_params == {"parallel_tool_calls": True}
    assert agent.add_history_to_context is False
    assert agent.debug_mode is False
    assert isinstance(agent.compression_manager, ContextBudgetController)
    assert agent.compression_manager.context_token_limit == 256 * 1024
    assert agent.compression_manager.input_token_budget == 224 * 1024
    assert agent.compression_manager.model is agent.model
    assert agent.tools[0].kernel.service is workspace_service
    assert isinstance(agent.tools[0].kernel.validator_registry, SkillValidatorRegistry)
    assert "create_file" not in agent.tools[0].get_async_functions()
    assert "create_files" in agent.tools[0].get_async_functions()
    assert sum(is_skill_script_hook(hook) for hook in agent.tool_hooks) == 1
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
    assert isinstance(app_agent, DirectCodingAgent)
    assert isinstance(app_agent, AgentProtocol)
    assert app_agent.model is agent.model
    assert app_agent.model.id == settings.model_id
    assert app_agent.model.extra_body == {"enable_thinking": True, "thinking_budget": 16384}
    assert app_agent.model.reasoning_effort == "medium"
    assert app_agent.model.request_params == {"parallel_tool_calls": True}
    assert app_agent.add_history_to_context is False
    assert app_agent.num_history_runs is None
    assert app_agent.debug_mode is False
    assert [tool.name for tool in app_agent.tools] == ["run_coding_task"]
    assert app_agent.tools[0].parameters == {
        "type": "object",
        "properties": {"instruction": {"type": "string", "minLength": 1}},
        "required": ["instruction"],
        "additionalProperties": False,
    }
    assert not any(is_skill_script_hook(hook) for hook in app_agent.tool_hooks or [])
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
    assert request_params["parallel_tool_calls"] is True


@pytest.mark.parametrize(
    "base_url",
    [
        "https://api.siliconflow.cn/v1",
        "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "http://127.0.0.1:8000/v1",
    ],
    ids=["siliconflow", "qianwen-dashscope", "vllm"],
)
def test_coding_thinking_parameters_use_openai_compatible_request_fields(base_url):
    settings = AgentSettings.from_environment({"OPENAI_BASE_URL": base_url}, load_env_file=False)
    agent = create_cli_agent(
        CliContext(
            settings=settings,
            database=object(),
            workspace_service=object(),
            coding_repository=object(),  # type: ignore[arg-type]
        )
    )

    request_params = agent.model.get_request_params()

    assert str(agent.model.base_url).rstrip("/") == base_url.rstrip("/")
    assert request_params["reasoning_effort"] == "medium"
    assert request_params["temperature"] == 0.1
    assert request_params["extra_body"] == {
        "enable_thinking": True,
        "thinking_budget": 16384,
    }


def test_cli_instructions_prefer_direct_verify_and_batch_patch():
    instructions = "\n".join(cli_module.CLI_AGENT_INSTRUCTIONS)

    assert "首次" in instructions and "verify" in instructions
    assert "一次调用 create_files" in instructions and "一次 apply_patch" in instructions
    assert "标准 unified diff" in instructions and "/dev/null" in instructions
    assert "两次" in instructions and "计划" in instructions
    assert "cd /workspace" in instructions
    assert 'list_files(path="")' in instructions
    assert "禁止把 /workspace" in instructions
    assert CODING_VALIDATOR_FEEDBACK_INSTRUCTION in cli_module.CLI_AGENT_INSTRUCTIONS
    assert CODING_DELIVERABLE_VERIFICATION_INSTRUCTION in cli_module.CLI_AGENT_INSTRUCTIONS
    assert cli_module.CLI_AGENT_INSTRUCTIONS[-len(PURE_CODING_PARALLEL_READ_INSTRUCTIONS) :] == (
        PURE_CODING_PARALLEL_READ_INSTRUCTIONS
    )


def test_cli_agent_explicitly_honors_thinking_setting():
    settings = AgentSettings.from_environment(
        {"AGENT_CODING_ENABLE_THINKING": "false"}, load_env_file=False
    )
    agent = create_cli_agent(
        CliContext(
            settings=settings,
            database=object(),
            workspace_service=object(),
            coding_repository=object(),  # type: ignore[arg-type]
        )
    )

    assert agent.model.extra_body == {"enable_thinking": False}
    assert agent.model.reasoning_effort == "medium"


def test_create_files_patch_builds_one_native_multi_file_patch():
    patch = _create_files_patch(
        [
            {"path": "calculator.py", "content": "def add(a, b):\n    return a + b\n"},
            {"path": "test_calculator.py", "content": "def test_add():\n    assert True\n"},
        ]
    )

    assert patch.count("--- /dev/null") == 2
    assert patch.count("+++ b/") == 2
    assert patch.count("@@ -0,0") == 2


def test_create_files_patch_preserves_missing_trailing_newline() -> None:
    patch = _create_files_patch(
        [{"path": "analysis/report.py", "content": 'print("OK")'}]
    )

    changes = build_workspace_changes(
        object.__new__(WorkspaceService),
        "thread",
        patch,
    )

    assert '+print("OK")\n\\ No newline at end of file\n' in patch
    assert changes == [
        {
            "operation": "create",
            "path": "analysis/report.py",
            "content": 'print("OK")',
        }
    ]


@pytest.mark.anyio
async def test_cli_app_agent_routes_exact_input_without_facade_model(monkeypatch):
    captured: list[tuple] = []

    class ClientContext:
        async def __aenter__(self):
            return object()

        async def __aexit__(self, *_args):
            return None

    class Workspace:
        def _async_client(self):
            return ClientContext()

        async def _asandbox_for(self, _client, thread_id):
            captured.append(("sandbox", thread_id))
            return type("Sandbox", (), {"id": "sandbox-1"})()

    class Adapter:
        def __init__(self, supervisor):
            captured.append(("supervisor", supervisor))

        async def start_events(self, scope, instruction):
            captured.append(("task", scope, instruction))
            yield RunContentEvent(run_id=scope.external_run_id, content="完成")

    supervisor = object()
    monkeypatch.setattr(cli_module, "CodingTaskSupervisor", lambda *_args, **_kwargs: supervisor)
    monkeypatch.setattr(cli_module, "CliCodingAdapter", Adapter)
    settings = AgentSettings.from_environment({}, load_env_file=False)
    context = CliContext(
        settings=settings,
        database=object(),
        workspace_service=Workspace(),  # type: ignore[arg-type]
        coding_repository=object(),  # type: ignore[arg-type]
    )
    worker = create_cli_agent(context)
    app_agent = create_cli_app_agent(context, worker)

    events = [
        event
        async for event in app_agent.arun(
            "原样实现目标",
            stream=True,
            run_context=RunContext(
                run_id="run-1",
                session_id="thread-1",
                user_id="user-1",
            ),
        )
    ]

    assert [event.content for event in events] == ["完成"]
    assert captured[0] == ("supervisor", supervisor)
    assert captured[1] == ("sandbox", "thread-1")
    _, scope, instruction = captured[2]
    assert instruction == "原样实现目标"
    assert (
        scope.external_run_id,
        scope.owner_user_id,
        scope.thread_id,
        scope.sandbox_id,
        scope.agent_id,
    ) == ("run-1", "user-1", "thread-1", "sandbox-1", "coding-agent-cli")


def test_cli_debug_mode_is_independent_from_thinking():
    settings = AgentSettings.from_environment(
        {"AGENT_DEBUG": "true", "AGENT_CODING_ENABLE_THINKING": "true"},
        load_env_file=False,
    )
    context = CliContext(
        settings=settings,
        database=object(),
        workspace_service=object(),
        coding_repository=object(),  # type: ignore[arg-type]
    )

    coding_agent = create_cli_agent(context)
    app_agent = create_cli_app_agent(context, coding_agent)

    assert coding_agent.debug_mode is True
    assert app_agent.debug_mode is True


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
    sync_db = object()
    database = type("Database", (), {"async_db": async_db, "sync_db": sync_db})()
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
            sync_db,
            {
                "enabled": True,
                "batch_processing": True,
                "phoenix_endpoint": "https://phoenix.example/v1/traces",
                "phoenix_api_key": "secret",
                "phoenix_project_name": "hrp",
            },
        )
    ]
    assert context.database is async_db
    assert context.trace_database is sync_db


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
    workspace = AsyncClient()
    database = AsyncClient()

    class NativeCliAgent:
        debug_mode = False
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
    context = type("Context", (), {"workspace_service": workspace, "database": database})()

    await run_cli(context, coding_agent)  # type: ignore[arg-type]

    assert len(calls) == 1
    assert calls[0]["session_id"].startswith("cli-")
    console = calls[0].pop("console")
    assert console.is_interactive is False
    assert calls[0] == {
        "input": None,
        "session_id": calls[0]["session_id"],
        "user_id": "cli",
        "stream": True,
        "markdown": True,
        "exit_on": ["exit", "quit", "bye", "/exit", "/quit"],
    }
    assert coding_client.closed
    assert coding_compression_client.closed
    assert app_client.closed
    assert app_compression_client.closed
    assert workspace.closed
    assert database.closed


@pytest.mark.anyio
async def test_cli_passes_multiline_initial_input_verbatim(monkeypatch):
    calls = []

    class NativeCliAgent:
        debug_mode = False
        model = None
        compression_manager = None

        async def aprint_response(self, instruction, **kwargs):
            calls.append((instruction, kwargs))

        async def acli_app(self, **_kwargs):
            raise AssertionError("stdin 模式不应进入交互循环")

    monkeypatch.setattr(
        cli_module,
        "create_cli_app_agent",
        lambda _context, _agent: NativeCliAgent(),
    )
    context = type(
        "Context",
        (),
        {"workspace_service": object(), "database": object()},
    )()
    instruction = "第一行\n第二行\n"

    await run_cli(context, object(), initial_input=instruction)  # type: ignore[arg-type]

    assert calls[0][0] == instruction
    assert calls[0][1]["session_id"].startswith("cli-")
    assert calls[0][1]["user_id"] == "cli"
    assert calls[0][1]["stream"] is True
    assert calls[0][1]["markdown"] is True


@pytest.mark.anyio
async def test_cli_treats_eof_as_normal_exit_and_closes_resources(monkeypatch):
    closed = []

    class Client:
        async def close(self):
            closed.append(True)

    class NativeCliAgent:
        debug_mode = False
        model = None
        compression_manager = None

        async def acli_app(self, **_kwargs):
            raise EOFError

    monkeypatch.setattr(
        cli_module,
        "create_cli_app_agent",
        lambda _context, _agent: NativeCliAgent(),
    )
    monkeypatch.setattr(cli_module, "flush_tracing", lambda: True)
    context = type(
        "Context",
        (),
        {"workspace_service": Client(), "database": Client()},
    )()

    await run_cli(context, object())  # type: ignore[arg-type]

    assert closed == [True, True]


@pytest.mark.anyio
async def test_cli_debug_mode_keeps_rich_dynamic_rendering(monkeypatch):
    calls = []

    class NativeCliAgent:
        debug_mode = True
        model = None
        compression_manager = None

        async def acli_app(self, **kwargs):
            calls.append(kwargs)

    monkeypatch.setattr(
        cli_module,
        "create_cli_app_agent",
        lambda _context, _agent: NativeCliAgent(),
    )
    context = type(
        "Context",
        (),
        {"workspace_service": object(), "database": object()},
    )()

    await run_cli(context, object())  # type: ignore[arg-type]

    assert calls[0]["console"].is_interactive is True


@pytest.mark.anyio
async def test_cli_default_context_always_enables_debug_and_tracing(monkeypatch):
    configured = AgentSettings.from_environment({}, load_env_file=False)
    captured_settings = []

    class NativeCliAgent:
        debug_mode = True
        model = None
        compression_manager = None

        async def acli_app(self, **_kwargs):
            return None

    context = type(
        "Context",
        (),
        {"workspace_service": object(), "database": object()},
    )()
    monkeypatch.setattr(
        cli_module.AgentSettings,
        "from_environment",
        lambda: configured,
    )
    monkeypatch.setattr(
        cli_module,
        "create_cli_context",
        lambda settings: captured_settings.append(settings) or context,
    )
    monkeypatch.setattr(cli_module, "create_cli_agent", lambda _context: object())
    monkeypatch.setattr(
        cli_module,
        "create_cli_app_agent",
        lambda _context, _agent: NativeCliAgent(),
    )

    await run_cli()

    assert configured.debug is False
    assert configured.tracing_enabled is False
    assert captured_settings[0].debug is True
    assert captured_settings[0].tracing_enabled is True


@pytest.mark.anyio
async def test_cli_closes_resources_when_native_app_is_cancelled(monkeypatch):
    closed = []

    class AsyncClient:
        def __init__(self, name):
            self.name = name

        async def close(self):
            closed.append(self.name)

    class NativeCliAgent:
        debug_mode = False
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
    context = type(
        "Context",
        (),
        {
            "workspace_service": AsyncClient("workspace"),
            "database": AsyncClient("database"),
        },
    )()
    monkeypatch.setattr(
        cli_module,
        "create_cli_app_agent",
        lambda _context, _agent: NativeCliAgent(),
    )
    monkeypatch.setattr(cli_module, "flush_tracing", lambda: closed.append("tracing") or True)

    with pytest.raises(asyncio.CancelledError):
        await run_cli(context, coding_agent)  # type: ignore[arg-type]

    assert closed == [
        "tracing",
        "app-model",
        "app-compression",
        "coding-model",
        "coding-compression",
        "workspace",
        "database",
    ]


@pytest.mark.anyio
async def test_cli_cleanup_continues_after_individual_close_failure(monkeypatch):
    closed = []

    class Client:
        def __init__(self, name, *, fail=False):
            self.name = name
            self.fail = fail

        async def close(self):
            closed.append(self.name)
            if self.fail:
                raise RuntimeError(self.name)

    class NativeCliAgent:
        debug_mode = False
        model = type("Model", (), {"async_client": Client("app", fail=True)})()
        compression_manager = None

        async def acli_app(self, **_kwargs):
            return None

    coding_agent = type(
        "CodingAgent",
        (),
        {
            "model": type("Model", (), {"async_client": Client("coding")})(),
            "compression_manager": None,
        },
    )()
    context = type(
        "Context",
        (),
        {"workspace_service": Client("workspace"), "database": Client("database")},
    )()
    monkeypatch.setattr(
        cli_module,
        "create_cli_app_agent",
        lambda _context, _agent: NativeCliAgent(),
    )
    monkeypatch.setattr(cli_module, "flush_tracing", lambda: closed.append("tracing") or True)

    with pytest.raises(RuntimeError, match="app"):
        await run_cli(context, coding_agent)  # type: ignore[arg-type]

    assert closed == ["tracing", "app", "coding", "workspace", "database"]


@pytest.mark.anyio
async def test_cli_flush_failure_is_reported_after_all_resources_close(monkeypatch):
    closed = []

    class Client:
        def __init__(self, name):
            self.name = name

        async def close(self):
            closed.append(self.name)

    class NativeCliAgent:
        debug_mode = False
        model = None
        compression_manager = None

        async def acli_app(self, **_kwargs):
            return None

    coding_agent = type("CodingAgent", (), {"model": None, "compression_manager": None})()
    context = type(
        "Context",
        (),
        {
            "workspace_service": Client("workspace"),
            "database": Client("database"),
            "trace_database": Client("trace-database"),
        },
    )()
    monkeypatch.setattr(
        cli_module,
        "create_cli_app_agent",
        lambda _context, _agent: NativeCliAgent(),
    )
    monkeypatch.setattr(cli_module, "flush_tracing", lambda: False)

    with pytest.raises(RuntimeError, match="agent_tracing_flush_failed"):
        await run_cli(context, coding_agent)  # type: ignore[arg-type]

    assert closed == ["workspace", "database", "trace-database"]

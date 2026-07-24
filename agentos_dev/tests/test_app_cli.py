from agentos_dev.app_cli import CliContext, create_cli_agent
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
    assert agent.num_history_runs == 5
    assert agent.tools[0].kernel.service is workspace_service

from functools import partial

from agno.agent import Agent

from ..agent_control import build_report_agent_tools
from ..workspace import WorkspaceService
from .assistant import AgentInstructions


def create_report_agent(
    base_agent: Agent,
    workspace_service: WorkspaceService,
    *,
    instructions: AgentInstructions,
    context_token_budget: int = 262144,
    output_token_reserve: int = 32768,
    report_data_sources_file: str | None = None,
    database_url: str | None = None,
) -> Agent:
    agent = base_agent.deep_copy(
        update={
            "id": "report-agent",
            "name": "智能报表",
            "role": "在当前 Daytona 工作区执行受控 Python 编码、数据分析和智能报表任务。",
            "instructions": instructions,
            "tools": partial(
                build_report_agent_tools,
                workspace_service,
                context_token_budget=context_token_budget,
                output_token_reserve=output_token_reserve,
                report_data_sources_file=report_data_sources_file,
                database_url=database_url,
            ),
            "tool_choice": "auto",
        }
    )
    agent.num_history_runs = None
    return agent

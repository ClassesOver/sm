from collections.abc import Callable
from functools import partial

from agno.agent import Agent

from ..agent_control import build_coding_agent_tools
from ..instructions import build_coding_agent_instructions
from ..workspace import WorkspaceService

AgentInstructions = str | list[str] | Callable[..., str | list[str]]


def create_coding_agent(
    base_agent: Agent,
    workspace_service: WorkspaceService,
    *,
    instructions: AgentInstructions = build_coding_agent_instructions,
    context_token_budget: int = 262144,
    output_token_reserve: int = 32768,
) -> Agent:
    agent = base_agent.deep_copy(
        update={
            "id": "coding-agent",
            "name": "Coding Agent",
            "role": "在当前 Daytona 工作区执行受控软件开发任务。",
            "instructions": instructions,
            "skills": None,
            "tools": partial(
                build_coding_agent_tools,
                workspace_service,
                context_token_budget=context_token_budget,
                output_token_reserve=output_token_reserve,
            ),
            "tool_choice": "auto",
        }
    )
    agent.num_history_runs = None
    return agent

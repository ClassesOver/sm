from collections.abc import Callable
from functools import partial

from agno.agent import Agent

from ..agent_control import build_coding_agent_tools
from ..workspace import WorkspaceService

AgentInstructions = str | list[str] | Callable[..., str | list[str]]

CODING_AGENT_INSTRUCTIONS = [
    "你是工作区 Coding Agent，只在当前 thread 隔离的 Daytona 工作区中编写、运行和验证代码。",
    "开始前检查相关文件和现状；复杂任务维护计划；修改后运行匹配的测试并检查结果。",
    "可以创建和反复修改任意 Python 脚本，但不得访问 AgentOS 宿主文件系统、开放网络或通用 Odoo RPC。",
]


def create_coding_agent(
    base_agent: Agent,
    workspace_service: WorkspaceService,
    *,
    instructions: AgentInstructions = CODING_AGENT_INSTRUCTIONS,
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

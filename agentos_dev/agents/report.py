from functools import partial
from typing import Any

from agno.agent import Agent
from agno.run import RunContext

from ..agent_control import build_report_agent_tools
from ..coding.repository import CodingTaskRepository
from ..skills import SkillValidatorRegistry
from ..workspace import (
    REPORT_DELIVERY_STATE_KEY,
    WorkspaceReportToolkit,
    WorkspaceService,
    report_delivery_content,
)
from .assistant import AgentInstructions


async def enforce_report_delivery_output(
    run_output: Any,
    run_context: RunContext,
    workspace_service: WorkspaceService,
) -> None:
    state = run_context.session_state if isinstance(run_context.session_state, dict) else {}
    delivery = state.get(REPORT_DELIVERY_STATE_KEY)
    delivery_id = delivery.get("deliveryId") if isinstance(delivery, dict) else None
    if not isinstance(delivery_id, str):
        return
    evidence = None
    evidence = await WorkspaceReportToolkit(workspace_service).validated_delivery(
        delivery_id,
        run_context,
    )
    content = report_delivery_content(getattr(run_output, "content", None), evidence)
    run_output.content = content
    if hasattr(run_output, "content_type"):
        run_output.content_type = "str"
    for message in reversed(getattr(run_output, "messages", None) or []):
        if getattr(message, "role", None) in {"assistant", "model"}:
            message.content = content
            break


def report_delivery_post_hook(workspace_service: WorkspaceService):
    async def report_delivery_guard(run_output: Any, run_context: RunContext) -> None:
        await enforce_report_delivery_output(run_output, run_context, workspace_service)

    return report_delivery_guard


def create_report_agent(
    base_agent: Agent,
    workspace_service: WorkspaceService,
    coding_repository: CodingTaskRepository,
    *,
    instructions: AgentInstructions,
    context_token_budget: int = 262144,
    output_token_reserve: int = 32768,
    report_data_sources_file: str | None = None,
    database_url: str | None = None,
) -> Agent:
    post_hooks = [*(base_agent.post_hooks or []), report_delivery_post_hook(workspace_service)]
    validator_registry = SkillValidatorRegistry.from_skills(base_agent.skills)
    agent = base_agent.deep_copy(
        update={
            "id": "report-agent",
            "name": "智能报表",
            "role": "在当前 Daytona 工作区执行受控 Python 编码、数据分析和智能报表任务。",
            "instructions": instructions,
            "tools": partial(
                build_report_agent_tools,
                workspace_service,
                coding_repository,
                validator_registry=validator_registry,
                context_token_budget=context_token_budget,
                output_token_reserve=output_token_reserve,
                report_data_sources_file=report_data_sources_file,
                database_url=database_url,
            ),
            "tool_choice": "auto",
            "post_hooks": post_hooks,
        }
    )
    agent.num_history_runs = None
    return agent

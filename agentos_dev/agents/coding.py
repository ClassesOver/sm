from collections.abc import AsyncIterator, Callable
from copy import copy
from functools import partial

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.run import RunContext
from agno.run.agent import RunOutputEvent
from agno.tools import Function

from ..agent_control import build_coding_agent_tools
from ..coding.adapters import CliCodingAdapter
from ..coding.execution import (
    create_coding_tool_scheduler_hook,
    is_coding_tool_scheduler_hook,
)
from ..coding.models import CodingScope
from ..coding.repository import CodingTaskRepository
from ..coding.supervisor import CodingTaskSupervisor
from ..context_management import ContextBudgetController, projected_coding_model
from ..instructions import build_coding_agent_instructions
from ..skills import (
    SkillValidatorRegistry,
    load_builtin_coding_skills,
    skill_script_receipt_hook,
)
from ..workspace import WorkspaceService, _thread

AgentInstructions = str | list[str] | Callable[..., str | list[str]]


def create_coding_agent(
    base_agent: Agent,
    workspace_service: WorkspaceService,
    coding_repository: CodingTaskRepository,
    *,
    instructions: AgentInstructions = build_coding_agent_instructions,
    context_token_budget: int = 262144,
    output_token_reserve: int = 32768,
) -> Agent:
    tool_hooks = [
        *(base_agent.tool_hooks or []),
        create_coding_tool_scheduler_hook(coding_repository),
        skill_script_receipt_hook,
    ]
    if not isinstance(base_agent.model, OpenAIChat):
        raise TypeError("Coding Agent requires OpenAIChat")
    coding_model = projected_coding_model(base_agent.model)
    coding_model.reasoning_effort = "medium"
    coding_skills = load_builtin_coding_skills()
    validator_registry = SkillValidatorRegistry.from_skills(coding_skills)
    agent = base_agent.deep_copy(
        update={
            "id": "coding-agent",
            "name": "Coding Agent",
            "role": "在当前 Daytona 工作区执行受控软件开发任务。",
            "instructions": instructions,
            "model": coding_model,
            "skills": coding_skills,
            "tools": partial(
                build_coding_agent_tools,
                workspace_service,
                coding_repository,
                validator_registry=validator_registry,
                context_token_budget=context_token_budget,
                output_token_reserve=output_token_reserve,
            ),
            "tool_choice": "auto",
            "tool_hooks": tool_hooks,
        }
    )
    agent.num_history_runs = None
    if base_agent.compress_tool_results:
        agent.compression_manager = ContextBudgetController(
            model=agent.model,
            context_token_budget=context_token_budget,
            output_token_reserve=output_token_reserve,
        )
        agent.compress_tool_results = True
    return agent


def create_coding_facade_agent(
    internal_agent: Agent,
    supervisor: CodingTaskSupervisor,
    workspace_service: WorkspaceService,
) -> Agent:
    if not isinstance(internal_agent.model, OpenAIChat):
        raise TypeError("Coding facade requires OpenAIChat")
    facade_model = copy(internal_agent.model)
    facade_model.extra_body = {
        **(getattr(internal_agent.model, "extra_body", None) or {}),
        "enable_thinking": False,
    }
    facade_model.reasoning_effort = None
    facade_tool_hooks = [
        hook
        for hook in (internal_agent.tool_hooks or [])
        if hook is not skill_script_receipt_hook and not is_coding_tool_scheduler_hook(hook)
    ]

    async def run_coding_task(
        instruction: str, run_context: RunContext
    ) -> AsyncIterator[RunOutputEvent]:
        dependencies = (
            run_context.dependencies if isinstance(run_context.dependencies, dict) else {}
        )
        binding = dependencies.get("AgentOS 编码任务")
        external_run_id = binding.get("externalRunId") if isinstance(binding, dict) else None
        if not isinstance(external_run_id, str) or not external_run_id:
            raise ValueError("task_binding_missing")
        thread_id = _thread(run_context)
        async with workspace_service._async_client() as client:
            sandbox = await workspace_service._asandbox_for(client, thread_id)
            sandbox_id = str(getattr(sandbox, "id", "") or "")
        scope = CodingScope(
            external_run_id,
            str(run_context.user_id),
            thread_id,
            sandbox_id,
            str(internal_agent.id),
        )
        acceptance_contract = (
            binding.get("acceptanceContract") if isinstance(binding, dict) else None
        )
        if acceptance_contract is not None and not isinstance(acceptance_contract, dict):
            raise ValueError("task_acceptance_contract_invalid")
        async for event in CliCodingAdapter(supervisor).start_events(
            scope,
            instruction,
            acceptance_contract=acceptance_contract,
        ):
            yield event

    function = Function(
        name="run_coding_task",
        description="把完整编码目标交给受控 CodingTaskSupervisor 执行并返回验收结果。",
        parameters={
            "type": "object",
            "properties": {"instruction": {"type": "string", "minLength": 1}},
            "required": ["instruction"],
            "additionalProperties": False,
        },
        entrypoint=run_coding_task,
        stop_after_tool_call=True,
    )
    facade = internal_agent.deep_copy(
        update={
            "instructions": [
                "必须把收到的完整用户编码目标原样传给 run_coding_task，并直接返回工具结果。"
            ],
            "model": facade_model,
            "tools": [function],
            "tool_choice": {"type": "function", "function": {"name": "run_coding_task"}},
            "skills": None,
            "tool_hooks": facade_tool_hooks,
        }
    )
    facade.tool_choice = {"type": "function", "function": {"name": "run_coding_task"}}
    facade.num_history_runs = None
    return facade

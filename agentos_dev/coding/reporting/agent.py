from copy import copy
from functools import partial
from typing import Any

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.run import RunContext

from ...agents.assistant import AgentInstructions
from ...context_management import ContextBudgetController
from ...skills import SkillValidatorRegistry, is_skill_script_hook
from ...workspace import WorkspaceService
from ..execution import is_coding_tool_scheduler_hook
from ..repository import CodingTaskRepository
from .acceptance import load_reporting_skills
from .controller import ReportWorkflowController, ReportWorkflowToolkit
from .tools import build_report_worker_tools
from .workspace import (
    REPORT_DELIVERY_STATE_KEY,
    WorkspaceReportToolkit,
    report_delivery_content,
)


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


def create_report_worker(
    base_agent: Agent,
    workspace_service: WorkspaceService,
    coding_repository: CodingTaskRepository,
    *,
    instructions: AgentInstructions,
    report_enable_thinking: bool = True,
    report_enable_vision: bool = False,
    context_token_budget: int = 262144,
    output_token_reserve: int = 32768,
) -> Agent:
    if not isinstance(base_agent.model, OpenAIChat):
        raise TypeError("Report worker requires OpenAIChat")
    reporting_skills = load_reporting_skills(base_agent.skills)
    validator_registry = SkillValidatorRegistry.from_skills(reporting_skills)
    worker_model = copy(base_agent.model)
    worker_model.extra_body = {
        **(getattr(base_agent.model, "extra_body", None) or {}),
        "enable_thinking": report_enable_thinking,
    }
    worker_compression_manager = (
        ContextBudgetController(
            model=worker_model,
            context_token_budget=context_token_budget,
            output_token_reserve=output_token_reserve,
        )
        if base_agent.compress_tool_results
        else None
    )
    worker = base_agent.deep_copy(
        update={
            "id": "report-worker",
            "name": "智能报表 Worker",
            "role": "根据已批准的分析计划和不可变数据集执行受控 Coding 分析。",
            "model": worker_model,
            "compression_manager": worker_compression_manager,
            "instructions": instructions,
            "use_instruction_tags": True,
            "skills": reporting_skills,
            "send_media_to_model": report_enable_vision,
            "tools": partial(
                build_report_worker_tools,
                workspace_service,
                coding_repository,
                validator_registry=validator_registry,
                enable_vision=report_enable_vision,
                context_token_budget=context_token_budget,
                output_token_reserve=output_token_reserve,
            ),
            "tool_choice": "auto",
        }
    )
    worker.num_history_runs = None
    return worker


def create_report_agent(
    report_worker: Agent,
    controller: ReportWorkflowController,
) -> Agent:
    """创建公开 facade；实际分析只由 Workflow 内的 report-worker 执行。"""
    if not isinstance(report_worker.model, OpenAIChat):
        raise TypeError("Report facade requires OpenAIChat")
    facade_model = copy(report_worker.model)
    facade_model.extra_body = {
        **(getattr(report_worker.model, "extra_body", None) or {}),
        "enable_thinking": False,
    }
    facade_model.reasoning_effort = None
    facade_compression_manager = None
    if report_worker.compress_tool_results:
        if not isinstance(report_worker.compression_manager, ContextBudgetController):
            raise TypeError("Report worker requires ContextBudgetController")
        facade_compression_manager = ContextBudgetController(
            model=facade_model,
            context_token_budget=report_worker.compression_manager.context_token_limit,
            output_token_reserve=report_worker.compression_manager.output_token_reserve,
        )
    facade_tool_hooks = [
        hook
        for hook in (report_worker.tool_hooks or [])
        if not is_skill_script_hook(hook) and not is_coding_tool_scheduler_hook(hook)
    ]

    def workflow_tools(
        *, run_context: RunContext | None = None, agent: Agent | None = None
    ) -> list[ReportWorkflowToolkit]:
        _ = run_context, agent
        return [ReportWorkflowToolkit(controller)]

    facade = report_worker.deep_copy(
        update={
            "id": "report-agent",
            "name": "智能报表",
            "role": "通过受控 Workflow 编排来源确认、分析、验收和发布审核。",
            "model": facade_model,
            "compression_manager": facade_compression_manager,
            "instructions": [
                "新报表输入为 Envelope 时调用不带参数的 report_workflow_start；输入为自然语言时调用 "
                "report_workflow_start_from_prompt，由你把明确期间转换为 period_start/period_end。"
                "单个明确日历年份已构成明确期间，必须转换为该年1月1日至12月31日，不得因用户未写出"
                "起止日期而追问。report_goal 必须逐字复制包含业务目标的用户输入全文，不得改写、摘要"
                "或补充；若用户在追问后仅补充期间，复用本会话最近一条尚未启动的业务目标原文。只有"
                "期间确实缺失或冲突时才询问用户，不得猜测。不得自行取数、执行 Coding 或生成报告。",
                "工具返回 paused 时准确展示当前审核预览。用户批准后调用 report_workflow_approve；"
                "审核阶段为 agent 时必须调用 report_workflow_select_agent 并传入列表中的 code；"
                "用户拒绝时把完整反馈传给 report_workflow_reject；明确取消时调用 "
                "report_workflow_cancel。",
                "工具返回 completed 后只返回其正式报告产物；不得把 paused、running 或 failed "
                "描述为完成。",
            ],
            "tools": workflow_tools,
            "skills": None,
            "tool_hooks": facade_tool_hooks,
            "tool_choice": "auto",
        }
    )
    facade.num_history_runs = None
    return facade

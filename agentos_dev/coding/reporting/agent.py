from copy import copy
from functools import partial

from agno.agent import Agent
from agno.db.base import AsyncBaseDb
from agno.models.openai import OpenAIChat
from agno.run import RunContext

from ...agents import OPENAI_COMPATIBLE_ROLE_MAP
from ...agents.assistant import AgentInstructions
from ...context_management import (
    ContextBudgetController,
    RollingSessionSummaryManager,
    clear_terminal_reasoning,
    projected_coding_model,
)
from ...settings import AgentSettings
from ...skills import (
    SkillValidatorRegistry,
    create_skill_script_hook,
    is_skill_script_hook,
    load_sandbox_execution_skills,
)
from ...task_execution import TaskExecutionRepository
from ...task_execution.execution import (
    create_task_tool_scheduler_hook,
    is_task_tool_scheduler_hook,
)
from ...workspace import WorkspaceService
from .acceptance import load_reporting_skills
from .controller import ReportWorkflowController, ReportWorkflowToolkit
from .tools import build_report_worker_tools


def _report_model(settings: AgentSettings, *, enable_thinking: bool) -> OpenAIChat:
    return OpenAIChat(
        id=settings.model_id,
        base_url=settings.openai_base_url,
        api_key=settings.openai_api_key,
        timeout=settings.model_timeout_seconds,
        max_retries=0,
        role_map=OPENAI_COMPATIBLE_ROLE_MAP,
        extra_body={"enable_thinking": enable_thinking},
        retries=2,
        exponential_backoff=True,
    )


def create_report_worker(
    settings: AgentSettings,
    database: AsyncBaseDb,
    workspace_service: WorkspaceService,
    task_repository: TaskExecutionRepository,
    *,
    instructions: AgentInstructions,
    report_coding_enable_thinking: bool = True,
    report_enable_vision: bool = False,
    context_token_budget: int = 262144,
    output_token_reserve: int = 32768,
) -> Agent:
    reporting_skills = load_reporting_skills(load_sandbox_execution_skills(settings.skills_dir))
    validator_registry = SkillValidatorRegistry.from_skills(reporting_skills)
    worker_model = projected_coding_model(
        _report_model(settings, enable_thinking=report_coding_enable_thinking)
    )
    worker_model.max_tokens = output_token_reserve
    worker_model.reasoning_effort = settings.report_coding_reasoning_effort
    extra_body = dict(worker_model.extra_body or {})
    if report_coding_enable_thinking:
        extra_body["thinking_budget"] = settings.report_coding_thinking_budget
    else:
        extra_body.pop("thinking_budget", None)
    worker_model.extra_body = extra_body
    worker_compression_manager = (
        ContextBudgetController(
            model=worker_model,
            context_token_budget=context_token_budget,
            output_token_reserve=output_token_reserve,
        )
        if settings.enable_tool_result_compression
        else None
    )
    worker = Agent(
        id="report-worker",
        name="智能报表 Worker",
        role="根据已批准的分析计划和不可变数据集执行受控 Coding 分析。",
        model=worker_model,
        instructions=instructions,
        use_instruction_tags=True,
        skills=reporting_skills,
        tools=partial(
            build_report_worker_tools,
            workspace_service,
            task_repository,
            validator_registry=validator_registry,
            enable_vision=report_enable_vision,
            context_token_budget=context_token_budget,
            output_token_reserve=output_token_reserve,
        ),
        db=database,
        checkpoint="tool-batch",
        add_history_to_context=False,
        enable_session_summaries=settings.enable_session_summaries,
        add_session_summary_to_context=False,
        session_summary_manager=(
            RollingSessionSummaryManager(model=_report_model(settings, enable_thinking=False))
            if settings.enable_session_summaries
            else None
        ),
        compress_tool_results=settings.enable_tool_result_compression,
        compression_manager=worker_compression_manager,
        retries=0,
        post_hooks=[clear_terminal_reasoning],
        tool_hooks=[
            create_task_tool_scheduler_hook(task_repository),
            create_skill_script_hook(workspace_service),
        ],
        debug_mode=settings.debug,
        markdown=True,
        send_media_to_model=report_enable_vision,
        tool_choice="auto",
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
    facade_model.extra_body.pop("thinking_budget", None)
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
        if not is_skill_script_hook(hook) and not is_task_tool_scheduler_hook(hook)
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
                "report_workflow_start_from_prompt，并把用户输入全文逐字复制到 prompt。不得自行解析期间、"
                "改写目标、取数、执行 Coding 或生成报告。Workflow 返回 request 阶段 paused 时，向用户"
                "展示 clarificationQuestion，并由 report_workflow_review 的 AgentOS 用户输入收集补充原文，"
                "使 Workflow 首步按官方 HumanReview retry 继续归一化。",
                "任一报表工具返回 paused 时，准确展示当前 review 预览，并在同一 run 中立即调用 "
                "report_workflow_review。action、feedback 和 agent_id 必须由 AgentOS 用户输入提供；"
                "不得在文本回答中询问审批、猜测审批动作或宣称没有进行中的 Workflow。"
                "report_workflow_review 返回 paused 时重复本流程。",
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

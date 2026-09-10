"""Reporting Agent、Workflow Runtime 和执行依赖的协议无关装配。"""

from agno.agent import Agent

from ..model_routing import build_model_profiles
from ..quality_warnings.service import QualityWarningService
from ..runtime.execution import ExecutionContext
from ..runtime.settings import AgentSettings
from ..task_execution import TaskExecutionKernel, TaskExecutionRepository
from .agent import (
    create_reporting_code_agent,
    create_reporting_generator_agent,
    create_reporting_phase_agent,
)
from .data_source import load_configured_report_source_registry
from .delivery.publishing import (
    ReportArtifactPersistenceService,
    ReportDownloadGrantService,
)
from .metadata import ReportingMetadataClient
from .profile import load_configured_reporting_profiles
from .vision import ReportVisionReviewer
from .workflow.execution import ReportingEventSink, ReportingTaskCoordinator
from .workflow.repository import ReportingStateRepository
from .workflow.runtime import ReportWorkflowRuntime
from .workflow.runtime.phase_models import SectionDecisionOutput, VisualizationPlanDraft


def create_report_runtime(
    context: ExecutionContext,
    settings: AgentSettings,
    *,
    download_grants: ReportDownloadGrantService | None = None,
    artifact_persistence: ReportArtifactPersistenceService | None = None,
    quality_warning_service: QualityWarningService | None = None,
    reporting_event_sink: ReportingEventSink | None = None,
) -> tuple[Agent, ReportWorkflowRuntime]:
    task_repository = TaskExecutionRepository(context.database)
    state_repository = ReportingStateRepository(context.database)
    reporting_agent_template = create_reporting_phase_agent(
        settings,
        context.database,
        context.workspace_service,
        task_repository,
        state_repository=state_repository,
    )
    visualization_generator = create_reporting_generator_agent(
        model=reporting_agent_template.model,
        output_schema=VisualizationPlanDraft,
        name="reporting-visualization-generator",
    )
    visualization_code_agent = create_reporting_code_agent(
        model=reporting_agent_template.model,
        name="reporting-visualization-code-agent",
        role="只为冻结图表计划签发可视化脚本。",
        instructions=[
            "只能修改 visualizationWorkspace.scriptPath 签发的唯一 Python 文件。",
            "逐字使用 facts 中的 factFile.path、visualizationPlan.charts 和输出路径；"
            "不得使用 __file__、cwd 或目录探测重新推导路径。",
            "脚本从冻结 facts 生成计划中的全部图表，不得增删图表或改写引用元数据。",
            "绘图只能使用 Matplotlib；在导入 matplotlib.pyplot 前调用 "
            'matplotlib.use("Agg")，并使用 fig.savefig(...) 写入签发路径。',
            "不得调用或导入 run_python_script、submit_visualization_charts 等编排工具。",
        ],
    )
    section_generator = create_reporting_generator_agent(
        model=reporting_agent_template.model,
        output_schema=SectionDecisionOutput,
        name="reporting-section-generator",
    )
    section_recovery = create_reporting_generator_agent(
        model=reporting_agent_template.model,
        output_schema=SectionDecisionOutput,
        name="reporting-section-recovery",
    )
    vision_reviewer = (
        ReportVisionReviewer(settings, context.workspace_service)
        if settings.report_enable_vision
        else None
    )
    task_runner = ReportingTaskCoordinator(
        task_repository,
        TaskExecutionKernel(context.workspace_service, task_repository),
        model_profiles=build_model_profiles(
            fast_model_id=settings.model_fast_id,
            standard_model_id=settings.model_standard_id,
            strong_model_id=settings.model_strong_id,
        ),
    )
    _ = reporting_event_sink
    runtime = ReportWorkflowRuntime(
        db=context.database,
        reporting_agent_template=reporting_agent_template,
        task_runner=task_runner,
        visualization_generator=visualization_generator,
        visualization_recovery=visualization_code_agent,
        section_generator=section_generator,
        section_recovery=section_recovery,
        vision_reviewer=vision_reviewer,
        vision_enabled=settings.report_enable_vision,
        workspace_service=context.workspace_service,
        registry=load_configured_report_source_registry(settings.report_data_sources_dir),
        profiles=load_configured_reporting_profiles(settings.report_data_sources_dir),
        planner_enable_thinking=settings.report_enable_thinking,
        planner_reasoning_effort=settings.report_planner_reasoning_effort,
        planner_thinking_budget=settings.report_planner_thinking_budget,
        metadata_client=(
            ReportingMetadataClient(
                settings.report_metadata_url,
                token=settings.report_metadata_token,
            )
            if settings.report_metadata_url
            else None
        ),
        download_grants=download_grants,
        artifact_persistence=artifact_persistence,
        quality_warning_service=quality_warning_service,
        report_public_base_url=(
            settings.report_public_base_url if download_grants is not None else None
        ),
        state_repository=state_repository,
        analysis_concurrency=settings.report_analysis_concurrency,
        section_concurrency=settings.report_section_concurrency,
        reporting_execution_mode=settings.reporting_execution_mode,
    )
    return reporting_agent_template, runtime

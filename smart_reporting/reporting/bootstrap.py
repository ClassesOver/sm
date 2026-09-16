"""Reporting Agent、Workflow Runtime 和执行依赖的协议无关装配。"""

from agno.agent import Agent

from ..model_routing import build_model_profiles
from ..quality_warnings.service import QualityWarningService
from ..report_editor import ReportEditorGrantService
from ..runtime.execution import ExecutionContext
from ..runtime.settings import AgentSettings
from ..task_execution import DEFAULT_TERMINAL_TIMEOUT, TaskExecutionKernel, TaskExecutionRepository
from .agent import (
    create_reporting_code_agent,
    create_reporting_generator_agent,
    create_reporting_phase_agent,
)
from .code_mode import create_reporting_code_mode_runtime
from .data_source import load_configured_report_source_registry
from .delivery.publishing import (
    ReportArtifactPersistenceService,
    ReportDownloadGrantService,
)
from .host_workspace import ReportingWorkspaceRegistry, ReportingWorkspaceRouter
from .metadata import ReportingMetadataClient
from .profile import load_configured_reporting_profiles
from .vision import ReportVisionReviewer
from .workflow.execution import ReportingEventSink, ReportingTaskCoordinator
from .workflow.repository import ReportingStateRepository
from .workflow.runtime import ReportWorkflowRuntime
from .workflow.runtime.phase_models import SectionDecisionOutput, VisualizationPlanDraft

_VISUALIZATION_CODE_INSTRUCTIONS = (
    "只能修改 visualizationWorkspace.scriptPath 签发的唯一 Python 文件。",
    "逐字使用 facts 中的 factFile.path、visualizationPlan.charts 和输出路径；"
    "不得使用 __file__、cwd 或目录探测重新推导路径。",
    "脚本从冻结 facts 生成计划中的全部图表，不得增删图表或改写引用元数据。",
    "source descriptor 声明 rowEncoding=columns_rows 时，每个 row 都是与 columns 按位置对应的列表；"
    "必须先校验行列长度一致，再用 dict(zip(columns, row)) 解码，禁止把 row 当作字典使用"
    '或写 row["字段名"]。',
    "字段缺失、行列不一致、类型不符或数值转换失败时必须显式抛出异常；"
    "禁止使用 .get(..., 0)、or 0、except 后赋 0 等默认值掩盖解析失败。",
    "只有冻结 facts 中的真实数据全零时才允许绘制全零系列；真实全零或恒定序列必须保留"
    "真实刻度并明确标注数据为零或无变化，不得隐藏系列。不得把缺失、解析失败或空输入"
    "替换成零值、常数值或占位数据来规避脚本执行与可视化审查。",
    "每个 metricIndex 的 topGroups 和 bottomGroups 都是指标局部集合；不同 metricIndex 的"
    "分组标签、顺序和数量可以完全不同，禁止跨指标复用分组标签、数组位置或查找结果。",
    "多个指标需要展示分组贡献时必须在同一签发图片内使用独立子图，各子图只读取自身"
    "metricIndex 的真实分组；同一指标内缺失的分类值保留为 NaN 或空白并明确标注无数据，"
    "不得补零。",
    "修复 execution_output_error 时必须修正原始数据读取或解码错误，不得仅删除失败代码、"
    "吞掉异常或补默认数据。",
    "绘图只能使用 Matplotlib；在导入 matplotlib.pyplot 前调用 "
    'matplotlib.use("Agg")，并使用 fig.savefig(...) 写入签发路径。',
    "不得调用或导入 run_python_script、submit_visualization_charts 等编排工具。",
)


def create_report_runtime(
    context: ExecutionContext,
    settings: AgentSettings,
    *,
    download_grants: ReportDownloadGrantService | None = None,
    editor_grants: ReportEditorGrantService | None = None,
    artifact_persistence: ReportArtifactPersistenceService | None = None,
    quality_warning_service: QualityWarningService | None = None,
    reporting_event_sink: ReportingEventSink | None = None,
) -> tuple[Agent, ReportWorkflowRuntime]:
    workspace_registry = context.reporting_workspace_registry or ReportingWorkspaceRegistry(
        settings.reporting_host_workspace_root,
        secret=settings.workspace_hmac_secret,
    )
    reporting_workspace = ReportingWorkspaceRouter(workspace_registry)
    if artifact_persistence is not None:
        artifact_persistence = ReportArtifactPersistenceService(
            artifact_persistence.repository,
            reporting_workspace,
        )
    task_repository = TaskExecutionRepository(context.database)
    state_repository = ReportingStateRepository(context.database)
    reporting_agent_template = create_reporting_phase_agent(
        settings,
        context.database,
        reporting_workspace,
        task_repository,
        state_repository=state_repository,
        workspace_registry=workspace_registry,
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
        instructions=_VISUALIZATION_CODE_INSTRUCTIONS,
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
        ReportVisionReviewer(settings, reporting_workspace)
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
        workspace_service=reporting_workspace,
        workspace_registry=workspace_registry,
        code_mode_runtime=(
            getattr(context, "reporting_code_mode_runtime", None)
            or create_reporting_code_mode_runtime(
                workspace_registry.root,
                analysis_concurrency=settings.report_analysis_concurrency,
                section_concurrency=settings.report_section_concurrency,
                timeout=DEFAULT_TERMINAL_TIMEOUT,
            )
        ),
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
        editor_grants=editor_grants,
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
